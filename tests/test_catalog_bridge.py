from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from champions_sim.capabilities import MappingResolutionStatus, VerificationStatus
from champions_sim.catalog import load_catalog, load_ruleset
from champions_sim.compiler.bridge import (
    CatalogBridgeProfile,
    compile_catalog_bridge,
)
from champions_sim.compiler.bridge_models import CatalogCompilerError
from champions_sim.compiler.loader import (
    load_production_catalog_input,
    load_verified_intake_document,
)
from champions_sim.core import UnsupportedMechanic
from champions_sim.engine import BattleEngine
from champions_sim.intake import (
    CatalogIntakePaths,
    CatalogIntakeProfile,
    build_catalog_intake,
)
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/intake/synthetic_mini"
INTAKE_PROFILE = CatalogIntakeProfile(
    "synthetic_mini", "TEST-B", "synthetic-v1", 3, 2
)
BRIDGE_PROFILE = CatalogBridgeProfile(
    "synthetic_bridge",
    "TEST-B",
    "synthetic-v1",
    3,
    "synthetic-local-unverified",
    "sim-core-0.1",
)


def _intake(root: Path = FIXTURE):
    return build_catalog_intake(
        repository_root=root,
        legacy_root=root,
        paths=CatalogIntakePaths(target_pool="target_pool.json"),
        profile=INTAKE_PROFILE,
    )


def _bridge(root: Path = FIXTURE, intake=None):
    return compile_catalog_bridge(
        intake or _intake(root),
        repository_root=root,
        legacy_root=root,
        profile=BRIDGE_PROFILE,
    )


def test_bridge_keeps_all_mapping_candidates_nonfinal_and_source_bound() -> None:
    result = _bridge()
    mapping = result.mapping_evidence

    assert len(mapping.entries) == 3
    assert all(
        value.catalog_pokemon_id is None
        and value.verification_status is VerificationStatus.UNVERIFIED
        for value in mapping.entries
    )
    by_key = {value.target_key: value for value in mapping.entries}
    assert by_key["dex:0001:form:00:variant:0"].resolution_status is MappingResolutionStatus.UNRESOLVED
    assert by_key["dex:0001:form:00:variant:0"].candidate_pokemon_ids == ("p1",)
    assert by_key["dex:0002:form:00:variant:0"].resolution_status is MappingResolutionStatus.CONFLICT
    assert by_key["dex:0002:form:00:variant:0"].candidate_pokemon_ids == (
        "p2",
        "wrong-p2",
    )
    assert by_key["dex:0003:form:00:variant:0"].mapping_method == (
        "intake.exact_name_candidate.normalized_official_name_exact"
    )
    assert result.catalog_input.denominator_final is False
    assert result.catalog_input.catalog_emit_eligible is False
    assert len(result.catalog_input.members) == 3
    assert all(
        value.verification_status is VerificationStatus.UNVERIFIED
        for value in result.catalog_input.records
    )


def test_mapping_evidence_preserves_record_hashes_and_never_uses_detail_as_id() -> None:
    result = _bridge()
    entry = next(
        value
        for value in result.mapping_evidence.entries
        if value.target_key == "dex:0002:form:00:variant:0"
    )
    evidence = {
        value.evidence_ref_id: value for value in result.mapping_evidence.evidence_refs
    }
    refs = [evidence[value] for value in entry.evidence_ref_ids]
    assert {value.artifact_id for value in refs} == {
        "pokemon_usage",
        "pokemon_usage_details",
    }
    usage = json.loads(
        (FIXTURE / "data/processed/pokemon_usage.json").read_text(encoding="utf-8")
    )["items"][1]
    expected = hashlib.sha256(
        json.dumps(
            usage,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert next(value for value in refs if value.artifact_id == "pokemon_usage").record_sha256 == expected
    assert entry.catalog_pokemon_id is None


def test_runtime_catalog_loads_but_engine_rejects_unsupported_before_priority(
    tmp_path: Path,
) -> None:
    result = _bridge()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(result.runtime_catalog_json(), encoding="utf-8", newline="")
    catalog = load_catalog(catalog_path)

    assert catalog.snapshot_hash == result.mapping_evidence.catalog_hash
    assert catalog.moves[0].priority is None
    assert catalog.moves[0].effect["kind"] == "unsupported"
    assert catalog.abilities[0].effect_id.startswith("unsupported:ability:")
    assert catalog.items[0].effect_id.startswith("unsupported:item:")
    assert "synthetic text only" not in result.runtime_catalog_json()
    with pytest.raises(UnsupportedMechanic, match="move_effect:unsupported"):
        BattleEngine(catalog, load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json"))


def test_bridge_outputs_are_canonical_schema_valid_and_loader_round_trip(
    tmp_path: Path,
) -> None:
    first = _bridge()
    second = _bridge()
    assert first.catalog_input.to_json() == second.catalog_input.to_json()
    assert first.mapping_evidence.to_json() == second.mapping_evidence.to_json()
    assert first.runtime_catalog_json() == second.runtime_catalog_json()

    production_schema = json.loads(
        (ROOT / "data/schemas/production-catalog-input.schema.json").read_text(
            encoding="utf-8"
        )
    )
    mapping_schema = json.loads(
        (ROOT / "data/schemas/target-mapping-evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )
    catalog_schema = json.loads(
        (ROOT / "data/schemas/catalog.schema.json").read_text(encoding="utf-8")
    )
    validate_document_contract(first.catalog_input.to_data(), production_schema, "production input")
    validate_document_contract(
        json.loads(first.mapping_evidence.to_json()), mapping_schema, "mapping evidence"
    )
    validate_document_contract(first.runtime_catalog, catalog_schema, "runtime Catalog")

    path = tmp_path / "production-input.json"
    path.write_text(first.catalog_input.to_json(), encoding="utf-8")
    loaded = load_production_catalog_input(path)
    assert loaded.to_json() == first.catalog_input.to_json()
    assert loaded.input_hash == first.catalog_input.input_hash
    assert loaded.unsigned_data()["source_policy"] == {
        "license_status": "unverified",
        "access_scope": "local_only",
        "redistribution": "prohibited",
        "payload_policy": "reference_only_no_raw_effect_text",
    }


def test_exact_official_target_key_set_is_mandatory() -> None:
    intake = _intake()
    shortened = replace(intake, members=intake.members[:-1])
    with pytest.raises(CatalogCompilerError, match="internally inconsistent"):
        _bridge(intake=shortened)


def test_source_hash_drift_and_license_upgrade_are_rejected(tmp_path: Path) -> None:
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    intake = _intake(root)
    moves = root / "data/processed/moves.json"
    moves.write_bytes(moves.read_bytes() + b"\n")
    with pytest.raises(CatalogCompilerError, match="source byte-count drift"):
        _bridge(root, intake)

    artifact = replace(intake.artifacts[0], license_status="verified")
    upgraded = replace(intake, artifacts=(artifact, *intake.artifacts[1:]))
    with pytest.raises(CatalogCompilerError, match="refuses to change"):
        _bridge(root, upgraded)


def test_intake_loader_rejects_canonical_hash_tampering(tmp_path: Path) -> None:
    intake = _intake()
    path = tmp_path / "intake.json"
    raw = intake.to_data()
    raw["members"][0]["label"] = "tampered"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(CatalogCompilerError, match="bundle hash mismatch"):
        load_verified_intake_document(path)


def test_semantic_absence_is_an_explicit_blocker() -> None:
    result = _bridge()
    blockers = set(result.catalog_input.blockers)
    assert "source_priority_missing:2/2" in blockers
    assert "source_structured_effect_missing:2/2" in blockers
    assert "source_base_stats_missing:0/3" in blockers
    assert "source_mega_stone_relations_missing:0/1" in blockers
    assert "runtime_catalog_contains_explicit_unsupported_semantics" in blockers
