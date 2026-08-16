from __future__ import annotations

import json
import subprocess
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
    load_json_object_strict,
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


def test_schema_conditionals_and_composed_siblings_are_conjunctive() -> None:
    conditional = {
        "type": "object",
        "if": {"properties": {"ready": {"const": True}}, "required": ["ready"]},
        "then": {"required": ["seal"]},
        "else": {"required": ["blockers"]},
    }
    validate_document_contract({"ready": True, "seal": "ok"}, conditional, "conditional")
    validate_document_contract({"ready": False, "blockers": ["missing"]}, conditional, "conditional")
    with pytest.raises(BundleValidationError, match="missing required fields"):
        validate_document_contract({"ready": False}, conditional, "conditional")

    ref_with_sibling = {
        "$defs": {"base": {"type": "object"}},
        "$ref": "#/$defs/base",
        "required": ["bound"],
    }
    with pytest.raises(BundleValidationError, match="missing required fields"):
        validate_document_contract({}, ref_with_sibling, "ref-sibling")

    one_of_with_sibling = {
        "oneOf": [
            {"type": "object", "properties": {"kind": {"const": "a"}}, "required": ["kind"]},
            {"type": "object", "properties": {"kind": {"const": "b"}}, "required": ["kind"]},
        ],
        "required": ["bound"],
    }
    with pytest.raises(BundleValidationError, match="missing required fields"):
        validate_document_contract({"kind": "a"}, one_of_with_sibling, "one-of-sibling")


def test_promotion_schema_mode_rejects_unknown_keywords_and_non_strict_json(
    tmp_path: Path,
) -> None:
    with pytest.raises(BundleValidationError, match="unsupported schema keywords"):
        validate_document_contract(
            {},
            {"type": "object", "minContains": 1},
            "promotion",
            fail_on_unknown_keywords=True,
        )

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"key":1,"key":2}', encoding="utf-8")
    with pytest.raises(BundleValidationError, match="duplicate JSON key"):
        load_json_object_strict(duplicate, "duplicate")

    non_finite = tmp_path / "nan.json"
    non_finite.write_text('{"key":NaN}', encoding="utf-8")
    with pytest.raises(BundleValidationError, match="non-finite JSON number"):
        load_json_object_strict(non_finite, "nan")

    overflow = tmp_path / "overflow.json"
    overflow.write_text('{"nested":[1e999,-1e999]}', encoding="utf-8")
    with pytest.raises(BundleValidationError, match="non-finite JSON number"):
        load_json_object_strict(overflow, "overflow")


def test_strict_schema_preflight_visits_inactive_branches_and_meta_shapes() -> None:
    cases = (
        {"type": "object", "properties": {"absent": {"format": "date"}}},
        {"$defs": {"unused": {"format": "date"}}, "type": "object"},
        {"if": {"format": "date"}, "then": {"type": "string"}},
        {"oneOf": [{"const": "used"}, {"format": "date"}]},
        {"type": "array", "contains": {"format": "date"}},
        {"type": "array", "items": {"format": "date"}},
        {"type": "object", "additionalProperties": {"format": "date"}},
    )
    for schema in cases:
        with pytest.raises(BundleValidationError, match="unsupported schema keywords"):
            validate_document_contract(
                {}, schema, "promotion", fail_on_unknown_keywords=True
            )

    for schema, match in (
        ({"oneOf": {}}, "oneOf must be a non-empty array"),
        ({"properties": []}, "properties must be an object"),
        ({"required": "ab"}, "required must be unique strings"),
    ):
        with pytest.raises(BundleValidationError, match=match):
            validate_document_contract(
                {}, schema, "promotion", fail_on_unknown_keywords=True
            )


def test_schema_equality_separates_boolean_and_rejects_numeric_duplicates() -> None:
    with pytest.raises(BundleValidationError, match="must equal"):
        validate_document_contract(True, {"const": 1}, "const")
    with pytest.raises(BundleValidationError, match="must be unique"):
        validate_document_contract(
            [1, 1.0], {"type": "array", "uniqueItems": True}, "unique"
        )


def test_non_progressing_schema_reference_cycle_fails_closed() -> None:
    schema = {
        "$defs": {
            "a": {"$ref": "#/$defs/b"},
            "b": {"$ref": "#/$defs/a"},
        },
        "$ref": "#/$defs/a",
    }
    with pytest.raises(BundleValidationError, match="cyclic \\$ref"):
        validate_document_contract({}, schema, "cycle", fail_on_unknown_keywords=True)


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


def test_ml_artifacts_are_ignored_without_hiding_small_sources_or_fixtures() -> None:
    ignored = {
        "wandb/run-1/history.jsonl",
        "experiments/mlruns/0/meta.yaml",
        "tensorboard/events.out.tfevents.1",
        "lightning_logs/version_0/metrics.csv",
        "tb_logs/train/events.out.tfevents.2",
        "models/candidate.ckpt",
        "models/candidate.safetensors",
        "scratch/features.npy",
        "scratch/features.npz",
        "models/policy.pt",
        "models/policy.pth",
        "models/policy.onnx",
    }
    retained = {
        "src/champions_sim/engine.py",
        "tests/test_governance_validation.py",
        "data/fixtures/sim01_catalog.json",
        "data/golden/ai01-synthetic-benchmark-v1.json",
    }
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-z", "--stdin"],
        cwd=ROOT,
        input=("\0".join(sorted(ignored | retained)) + "\0").encode("utf-8"),
        check=False,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8")
    actual = {
        value.decode("utf-8") for value in result.stdout.split(b"\0") if value
    }
    assert actual == ignored


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
        ("data/fixtures/too-large.json", "ADR-0002:fixture-limit"),
        ("data/golden/too-large.json", "ADR-0002:fixture-limit"),
    ]
