from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from champions_sim.compiler import (
    CatalogBridgeProfile,
    CatalogCompilerError,
    SourceToCapabilityConfig,
    compile_source_to_capability_bundle,
    write_compilation_documents,
)
from champions_sim.intake import CatalogIntakeProfile
from scripts import build_source_to_capability_bundle as compiler_cli
from scripts.validate_sim01_bundle import BundleValidationError, validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/fixtures/intake/synthetic_mini"


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _artifact(path: Path, logical_path: str) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "logical_path": logical_path,
        "byte_size": len(payload),
        "sha256": "sha256:" + hashlib.sha256(payload).hexdigest(),
    }


def _config(tmp_path: Path) -> SourceToCapabilityConfig:
    repository = tmp_path / "repository"
    shutil.copytree(FIXTURE, repository)
    regulation_path = repository / "regulation.json"
    _write_json(
        regulation_path,
        {
            "schema_version": "1.0.0",
            "regulation_id": "TEST-B",
            "revision": "synthetic-v1",
            "title": "Synthetic compiler integration",
            "status": "synthetic",
            "verification_status": "synthetic_rehearsal",
            "published_at": None,
            "period": {
                "start_date": "2026-01-01",
                "end_at": "2026-01-31T23:59:00+09:00",
                "timezone": "Asia/Tokyo",
            },
            "battle_format": "singles_3v3",
            "team_size": 3,
            "level": 50,
            "item_clause": {
                "held_items_enabled": True,
                "duplicate_held_items_allowed": False,
            },
            "battle_timer": {
                "total_minutes": 20,
                "player_minutes": 7,
                "turn_seconds": 45,
                "selection_seconds": 90,
            },
            "required_mechanics": ["mega_evolution"],
            "source_manifest_ids": ["synthetic-catalog-intake"],
        },
    )
    manifest_dir = repository / "manifests"
    manifest_dir.mkdir()
    _write_json(
        manifest_dir / "synthetic-catalog-intake.json",
        {
            "schema_version": "1.0.0",
            "manifest_id": "synthetic-catalog-intake",
            "license_status": "unverified",
            "license": {
                "redistribution_allowed": False,
                "commercial_use_allowed": False,
            },
            "usage_policy": {
                "local_research_only": True,
                "redistribution": "prohibited",
            },
            "artifacts": [
                _artifact(regulation_path, "regulation.json"),
                _artifact(repository / "target_pool.json", "target_pool.json"),
            ],
            "trust": {"verification_status": "unverified"},
        },
    )
    return SourceToCapabilityConfig(
        repository_root=repository,
        legacy_root=repository,
        regulation_path=regulation_path,
        target_pool_path=repository / "target_pool.json",
        ruleset_path=ROOT / "data/fixtures/sim01_ruleset.json",
        manifest_dir=manifest_dir,
        source_lock_path=ROOT / "data/manifests/catalog-intake-synthetic.json",
        intake_profile=CatalogIntakeProfile(
            "synthetic_mini", "TEST-B", "synthetic-v1", 3, 2
        ),
        bridge_profile=CatalogBridgeProfile(
            "synthetic_bridge",
            "TEST-B",
            "synthetic-v1",
            3,
            "catalog-intake-synthetic",
            "sim-core-0.1",
        ),
    )


def test_one_command_compiler_produces_deterministic_reasoned_no_go(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    first = compile_source_to_capability_bundle(config)
    second = compile_source_to_capability_bundle(config)

    assert first.report_hash == second.report_hash
    assert first.documents == second.documents
    assert first.report["status"] == "no_go"
    assert first.report["operational_success"] is True
    assert first.candidate_ready is False
    assert first.capability_set.denominator_final is False
    assert first.matrix.target_pool_execution_coverage_rate_ppm is None
    assert first.probe_report.silent_fallback_count == 0
    assert all(
        value.observed_outcome == "unexpected_error"
        for value in first.probe_report.results
    )
    assert first.report["counts"]["target_members"] == 3
    assert first.report["counts"]["mapping_resolved"] == 0
    assert first.report["counts"]["mapping_conflict"] == 1
    assert first.report["counts"]["mapping_unresolved"] == 2
    assert first.report["counts"]["probe_explicit_unsupported"] == 0
    assert first.report["counts"]["probe_unexpected_errors"] == len(
        first.capability_set.capabilities
    )

    schema = json.loads(
        (ROOT / "data/schemas/source-to-capability-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate_document_contract(first.report, schema, "compiler report")

    output = tmp_path / "generated"
    written = write_compilation_documents(first, output)
    assert len(written) == len(first.documents)
    for artifact in first.report["artifacts"]:
        payload = (output / artifact["file_name"]).read_bytes()
        assert len(payload) == artifact["byte_count"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_compiler_report_hash_rejects_report_mutation(tmp_path: Path) -> None:
    result = compile_source_to_capability_bundle(_config(tmp_path))
    unsigned = {
        key: value for key, value in result.report.items() if key != "report_hash"
    }
    assert result.report_hash == hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_report_schema_has_a_satisfiable_candidate_branch(tmp_path: Path) -> None:
    result = compile_source_to_capability_bundle(_config(tmp_path))
    candidate = dict(result.report)
    candidate["status"] = "candidate"
    candidate["candidate_ready"] = True
    candidate["denominator_final"] = True
    candidate["blocking_reasons"] = []
    candidate["source_policy"] = {
        "license_status": "verified",
        "access_scope": "approved",
        "redistribution": "allowed",
    }
    candidate["counts"] = {
        **candidate["counts"],
        "mapping_resolved": candidate["counts"]["target_members"],
        "mapping_unresolved": 0,
        "mapping_conflict": 0,
        "semantic_unsupported_selectors": 0,
        "execution_gaps": 0,
        "grounding_assertions": 1,
        "probe_explicit_unsupported": 0,
        "probe_unexpected_errors": 0,
        "silent_fallbacks": 0,
        "blocking_reasons": 0,
    }
    unsigned = {key: value for key, value in candidate.items() if key != "report_hash"}
    candidate["report_hash"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    schema = json.loads(
        (ROOT / "data/schemas/source-to-capability-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    validate_document_contract(candidate, schema, "candidate compiler report")

    candidate["counts"] = {**candidate["counts"], "execution_gaps": 1}
    with pytest.raises(BundleValidationError):
        validate_document_contract(candidate, schema, "candidate compiler report with gap")


def test_writer_rejects_post_compile_document_mutation(tmp_path: Path) -> None:
    result = compile_source_to_capability_bundle(_config(tmp_path))
    assert isinstance(result.documents, dict)
    result.documents["runtime-catalog.json"] = "{}"

    with pytest.raises(CatalogCompilerError, match="digest mismatch"):
        write_compilation_documents(result, tmp_path / "mutated-output")


def test_cli_normalizes_sealed_source_shape_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_compile(_config: SourceToCapabilityConfig) -> None:
        raise KeyError("moves")

    monkeypatch.setattr(
        compiler_cli,
        "compile_source_to_capability_bundle",
        fail_compile,
    )
    exit_code = compiler_cli.main(
        ["--legacy-root", str(tmp_path), "--dry-run"]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == "sealed source structure is invalid: 'moves'"


def test_cli_can_emit_exact_sim02b_negative_assessment_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    compilation = compile_source_to_capability_bundle(_config(tmp_path / "source"))
    monkeypatch.setattr(
        compiler_cli,
        "compile_source_to_capability_bundle",
        lambda _config: compilation,
    )

    exit_code = compiler_cli.main(
        [
            "--legacy-root",
            str(tmp_path),
            "--dry-run",
            "--sim02b-assessment",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sim02b_assessment_generated"] is True
    assert payload["sim02b_assessment_written"] is False
    assert payload["sim02b_assessment_blocker_count"] > 0
    assert payload["verified_target_mapping_numerator"] == 0
    assert payload["verified_target_mapping_denominator"] == 3
    assert payload["verified_target_mapping_rate_ppm"] == 0
    assert len(payload["sim02b_assessment_hash"]) == 64
