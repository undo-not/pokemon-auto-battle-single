from __future__ import annotations

import json
from pathlib import Path

import pytest

from champions_sim.catalog import load_catalog, load_ruleset
from champions_sim.engine import BattleEngine
from champions_sim.fixtures import load_battle_fixture
from champions_sim.runner import run_battle
from scripts.check_repo_size import evaluate_paths, git_candidate_files
from scripts.validate_sim01_bundle import (
    ROOT,
    BundleValidationError,
    validate_bundle,
    validate_document_contract,
    validate_top_level_contract,
)


def test_current_bundle_is_valid_for_local_research_but_not_redistribution() -> None:
    report = validate_bundle()

    assert report.license_status == "unverified"
    assert report.local_research_allowed is True
    assert report.redistribution_allowed is False
    assert set(report.source_manifest_ids) == {
        "champions-wiki-damage-reference",
        "legacy-champions-59bf57c-sim01",
    }
    assert report.catalog_hash
    assert report.ruleset_hash
    assert report.replay_schema_version == "2.0.0"
    assert len(report.replay_hash) == 64
    assert report.decision_windows > 0

    with pytest.raises(BundleValidationError, match="not eligible for distribution"):
        validate_bundle(usage_scope="distribution")


def test_top_level_schema_contract_rejects_missing_and_extra_fields() -> None:
    schema = json.loads((ROOT / "data/schemas/catalog.schema.json").read_text(encoding="utf-8"))
    fixture = json.loads((ROOT / "data/fixtures/sim01_catalog.json").read_text(encoding="utf-8"))
    validate_top_level_contract(fixture, schema, "catalog")

    incomplete = {"schema_version": "1.0.0"}
    with pytest.raises(BundleValidationError, match="missing schema fields"):
        validate_top_level_contract(incomplete, schema, "catalog")

    extra = {**fixture, "undeclared": True}
    with pytest.raises(BundleValidationError, match="outside schema"):
        validate_top_level_contract(extra, schema, "catalog")


def test_recursive_schema_contract_accepts_bundle_documents() -> None:
    cases = (
        ("catalog", "sim01_catalog.json", "catalog.schema.json"),
        ("ruleset", "sim01_ruleset.json", "ruleset.schema.json"),
        ("battle", "sim01_battle.json", "battle-fixture.schema.json"),
    )
    for label, fixture_name, schema_name in cases:
        document = json.loads(
            (ROOT / "data/fixtures" / fixture_name).read_text(encoding="utf-8")
        )
        schema = json.loads(
            (ROOT / "data/schemas" / schema_name).read_text(encoding="utf-8")
        )
        validate_document_contract(document, schema, label)


def test_legacy_manifest_records_six_sources_and_catalog_lineage() -> None:
    manifest = json.loads(
        (ROOT / "data/manifests/legacy-champions-59bf57c-sim01.json").read_text(
            encoding="utf-8"
        )
    )
    artifact_ids = {artifact["artifact_id"] for artifact in manifest["artifacts"]}
    assert {
        "legacy-pokemon-json-59bf57c",
        "legacy-moves-json-59bf57c",
        "legacy-types-json-59bf57c",
        "legacy-abilities-json-59bf57c",
        "legacy-items-json-59bf57c",
        "legacy-damage-calculator-py-59bf57c",
        "sim01-catalog-fixture-v1",
    } == artifact_ids
    assert manifest["license_status"] == "unverified"
    assert manifest["usage_policy"]["redistribution"] == "prohibited"


def test_same_bundle_and_seed_are_byte_identical_across_100_runs() -> None:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    fixture = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    engine = BattleEngine(catalog, ruleset)
    expected = run_battle(engine, fixture.initial_state, seed=20260713).replay.to_json()

    for _ in range(99):
        actual = run_battle(engine, fixture.initial_state, seed=20260713).replay.to_json()
        assert actual == expected


def test_repo_candidates_fit_provisional_size_limits() -> None:
    assert evaluate_paths(git_candidate_files()) == ()


def test_fixture_limit_is_stricter_than_general_file_limit(tmp_path: Path) -> None:
    fixture_dir = tmp_path / "data/fixtures"
    fixture_dir.mkdir(parents=True)
    fixture = fixture_dir / "too-large.json"
    fixture.write_bytes(b"x" * 11)
    golden_dir = tmp_path / "data/golden"
    golden_dir.mkdir(parents=True)
    golden = golden_dir / "too-large.json"
    golden.write_bytes(b"x" * 11)
    ordinary = tmp_path / "ordinary.txt"
    ordinary.write_bytes(b"x" * 11)

    violations = evaluate_paths(
        (fixture, golden, ordinary),
        root=tmp_path,
        file_limit=20,
        fixture_limit=10,
    )

    assert [(value.path, value.policy_id) for value in violations] == [
        ("data/fixtures/too-large.json", "PD-002"),
        ("data/golden/too-large.json", "PD-002"),
    ]
