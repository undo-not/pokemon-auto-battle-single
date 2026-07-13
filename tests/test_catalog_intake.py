from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import shutil

import pytest

from champions_sim.intake import (
    CatalogIntakeError,
    CatalogIntakePaths,
    CatalogIntakeProfile,
    build_catalog_intake,
    load_source_lock,
)
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/intake/synthetic_mini"
LOCK = ROOT / "data/manifests/catalog-intake-synthetic.json"
M_B_SOURCE_LOCK = ROOT / "data/manifests/catalog-intake-m-b-source-lock.json"
PROFILE = CatalogIntakeProfile(
    profile_id="synthetic_mini",
    regulation_id="TEST-B",
    regulation_revision="synthetic-v1",
    expected_target_count=3,
    expected_usage_count=2,
)
PATHS = CatalogIntakePaths(target_pool="target_pool.json")


def _build(root: Path, *, locked: bool = False):
    return build_catalog_intake(
        repository_root=root,
        legacy_root=root,
        paths=PATHS,
        profile=PROFILE,
        expected_inventory=load_source_lock(LOCK) if locked else None,
    )


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixture"
    shutil.copytree(FIXTURE, root)
    return root


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_synthetic_bundle_is_deterministic_locked_and_schema_valid() -> None:
    expected = load_source_lock(LOCK)
    first = _build(FIXTURE, locked=True)
    second = _build(FIXTURE, locked=True)

    assert first.to_json() == second.to_json()
    assert first.bundle_hash == second.bundle_hash
    assert first.target_member_count == 3
    assert first.summary["mapping_counts"] == {
        "exact_name_candidate": 1,
        "usage_crosswalk": 2,
    }
    assert first.summary["detail_counts"] == {"available": 2, "missing": 1}
    assert len(first.artifacts) == len(expected) == 9
    assert all(value.license_status == "unverified" for value in first.artifacts)
    assert all(value.access_scope == "local_only" for value in first.artifacts)
    assert all(value.redistribution == "prohibited" for value in first.artifacts)
    assert tuple(value.target_key for value in first.members) == tuple(
        sorted(value.target_key for value in first.members)
    )
    with pytest.raises(FrozenInstanceError):
        first.members[0].target_key = "mutated"  # type: ignore[misc]

    bundle_schema = _read(ROOT / "data/schemas/catalog-intake.schema.json")
    lock_schema = _read(ROOT / "data/schemas/catalog-intake-source-lock.schema.json")
    validate_document_contract(first.to_data(), bundle_schema, "catalog intake")
    validate_document_contract(_read(LOCK), lock_schema, "catalog intake source lock")


def test_m_b_source_lock_is_schema_valid_and_freezes_all_nine_inputs() -> None:
    lock_schema = _read(ROOT / "data/schemas/catalog-intake-source-lock.schema.json")
    raw = _read(M_B_SOURCE_LOCK)
    validate_document_contract(raw, lock_schema, "M-B catalog intake source lock")
    loaded = load_source_lock(M_B_SOURCE_LOCK)

    assert len(loaded) == 9
    assert loaded["official_target_pool"].record_count == 235
    assert loaded["pokemon_usage"].record_count == 213
    assert loaded["pokemon_catalog"].sha256 == (
        "f16267653e07446cbcd68d2c9624cc1aea023ef65bf1340d2676fe3cf8f9c411"
    )


def test_usage_detail_id_conflict_is_diagnostic_and_never_overrides() -> None:
    bundle = _build(FIXTURE)
    member = next(value for value in bundle.members if value.national_dex_no == 2)
    conflict = bundle.usage_detail_conflicts[0]

    assert member.selected_pokemon_id == "p2"
    assert member.mapping_status == "usage_crosswalk"
    assert member.evidence.matched_by == "pokedb_id_map"
    assert conflict.selected_pokemon_id == "p2"
    assert conflict.diagnostic_pokemon_id == "wrong-p2"
    assert bundle.summary["usage_detail_conflict_count"] == 1
    assert any(
        value.code == "usage_detail_pokemon_id_conflict"
        and "diagnostic never overrides" in value.detail
        for value in bundle.blockers
    )


def test_exact_normalized_name_is_candidate_and_missing_detail_is_explicit() -> None:
    bundle = _build(FIXTURE)
    member = next(value for value in bundle.members if value.national_dex_no == 3)

    assert member.mapping_status == "exact_name_candidate"
    assert member.selected_pokemon_id == "p3"
    assert member.evidence.matched_by == "normalized_official_name_exact"
    assert member.detail_status == "missing"
    assert member.detail_record_sha256 is None
    codes = {(value.code, value.subject) for value in bundle.blockers}
    assert ("mapping_candidate_unverified", member.target_key) in codes
    assert ("pokemon_detail_missing", member.target_key) in codes
    pokemon_union = next(
        value for value in bundle.entity_unions if value.entity_kind == "pokemon"
    )
    assert pokemon_union.ids == ("p1", "p2", "p3")
    assert pokemon_union.missing_record_ids == ("p3",)


def test_duplicate_target_key_is_rejected(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    path = root / "target_pool.json"
    raw = _read(path)
    raw["members"][2].update(
        raw["members"][0]
    )
    _write(path, raw)

    with pytest.raises(CatalogIntakeError, match="duplicate target key"):
        _build(root)


def test_ambiguous_normalized_name_fails_closed_without_selecting_id(
    tmp_path: Path,
) -> None:
    root = _copy_fixture(tmp_path)
    path = root / "data/processed/pokemon_catalog.json"
    raw = _read(path)
    raw["items"].append({"pokemon_id": "p3-other", "name": "ガンマ"})
    _write(path, raw)

    bundle = _build(root)
    member = next(value for value in bundle.members if value.national_dex_no == 3)
    assert member.mapping_status == "ambiguous_name"
    assert member.selected_pokemon_id is None
    assert member.evidence.candidate_pokemon_ids == ("p3", "p3-other")
    assert any(value.code == "target_mapping_ambiguous" for value in bundle.blockers)


def test_source_hash_drift_against_lock_is_rejected(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    path = root / "data/processed/moves.json"
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(CatalogIntakeError, match="source hash drift: moves"):
        _build(root, locked=True)


def test_source_lock_count_mismatch_is_rejected() -> None:
    expected = load_source_lock(LOCK)
    expected["moves"] = replace(
        expected["moves"], record_count=expected["moves"].record_count + 1
    )
    with pytest.raises(CatalogIntakeError, match="source record-count mismatch: moves"):
        build_catalog_intake(
            repository_root=FIXTURE,
            legacy_root=FIXTURE,
            paths=PATHS,
            profile=PROFILE,
            expected_inventory=expected,
        )


def test_internal_parallel_id_count_mismatch_is_rejected(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    path = root / "data/processed/moves.json"
    raw = _read(path)
    raw["move_ids"].pop()
    _write(path, raw)

    with pytest.raises(CatalogIntakeError, match="move_ids count or membership mismatch"):
        _build(root)


def test_path_escape_and_missing_required_source_are_rejected(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    escaped = replace(PATHS, pokemon_usage="../outside.json")
    with pytest.raises(CatalogIntakeError, match="unsafe relative source path"):
        build_catalog_intake(
            repository_root=root,
            legacy_root=root,
            paths=escaped,
            profile=PROFILE,
        )

    (root / "data/processed/abilities.json").unlink()
    with pytest.raises(CatalogIntakeError, match="required source does not exist"):
        _build(root)


def test_source_effect_text_is_hashed_but_not_copied_into_bundle(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    path = root / "data/processed/moves.json"
    raw = _read(path)
    raw["items"][0]["effect"] = "DO_NOT_COPY_SOURCE_EFFECT"
    _write(path, raw)

    bundle = _build(root)
    serialized = bundle.to_json()
    assert "DO_NOT_COPY_SOURCE_EFFECT" not in serialized
    move_union = next(
        value for value in bundle.entity_unions if value.entity_kind == "move"
    )
    assert len(move_union.record_hashes) == 2
    assert all(len(value.canonical_sha256) == 64 for value in move_union.record_hashes)


def test_optional_usage_details_can_be_absent_without_becoming_authoritative(
    tmp_path: Path,
) -> None:
    root = _copy_fixture(tmp_path)
    (root / "data/processed/pokemon_usage_details/season_2_rule_0.json").unlink()
    bundle = _build(root)

    assert bundle.usage_detail_present is False
    assert bundle.usage_detail_conflicts == ()
    assert all(
        value.code != "usage_detail_pokemon_id_conflict" for value in bundle.blockers
    )
