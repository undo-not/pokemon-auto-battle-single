from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from champions_sim.compiler import (
    CatalogBridgeProfile,
    SourceToCapabilityConfig,
    compile_source_to_capability_bundle,
)
from champions_sim.core import canonical_hash, canonical_json
from champions_sim.intake import CatalogIntakeProfile
from champions_sim.promotion.assessment import (
    PromotionAssessmentError,
    build_production_promotion_assessment_v2,
)
from scripts.validate_sim01_bundle import validate_document_contract


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
            "title": "Synthetic promotion negative assessment",
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


def _resign_report(compilation: object) -> None:
    report = compilation.report
    unsigned = {key: value for key, value in report.items() if key != "report_hash"}
    report["report_hash"] = canonical_hash(unsigned)
    compilation.documents["compiler-report.json"] = canonical_json(report)


def test_v1_diagnostic_produces_deterministic_unsealed_no_go(
    tmp_path: Path,
) -> None:
    first = build_production_promotion_assessment_v2(
        compile_source_to_capability_bundle(_config(tmp_path / "first"))
    )
    second = build_production_promotion_assessment_v2(
        compile_source_to_capability_bundle(_config(tmp_path / "second"))
    )

    assert first.to_json() == second.to_json()
    assert first.assessment_hash == second.assessment_hash
    assert first.status == "no_go"
    assert first.promotion_candidate is False
    assert first.denominator_final is False
    assert first.catalog_emit_eligible is False
    assert first.readiness_seal_hash is None
    assert first.verified_target_mapping_numerator == 0
    assert first.verified_target_mapping_denominator == 3
    assert first.verified_target_mapping_rate_ppm == 0
    assert first.development_scenario_coverage_rate_ppm is None
    assert first.verified_grounding_conformance_rate_ppm is None
    assert first.engine_probe_pass_rate_ppm is None
    assert first.external_holdout_novel_gap_count is None
    assert first.silent_fallback_count == 0
    assert all(
        blocker.stage
        and blocker.code
        and blocker.subject
        and blocker.evidence_required
        and blocker.restart_condition
        for blocker in first.blockers
    )
    assert any(
        blocker.code == "v1_diagnostic_not_promotion_input"
        for blocker in first.blockers
    )
    assert any(
        blocker.code == "production_trust_anchor_missing"
        for blocker in first.blockers
    )

    schema = json.loads(
        (
            ROOT / "data/schemas/sim02b-production-assessment-v2.schema.json"
        ).read_text(encoding="utf-8")
    )
    validate_document_contract(first.to_data(), schema, "SIM-02B assessment")


@pytest.mark.parametrize("forgery", ["status", "count", "candidate"])
def test_assessment_rejects_resigned_report_decision_forgery(
    tmp_path: Path,
    forgery: str,
) -> None:
    compilation = compile_source_to_capability_bundle(_config(tmp_path))
    if forgery == "status":
        compilation.report["status"] = "candidate"
    elif forgery == "count":
        compilation.report["counts"] = {
            **compilation.report["counts"],
            "target_members": 4,
        }
    else:
        compilation.report["candidate_ready"] = True
    _resign_report(compilation)

    with pytest.raises(PromotionAssessmentError, match="validation failed"):
        build_production_promotion_assessment_v2(compilation)


def test_assessment_rejects_resigned_source_policy_promotion(
    tmp_path: Path,
) -> None:
    compilation = compile_source_to_capability_bundle(_config(tmp_path))
    compilation.report["source_policy"] = {
        "license_status": "verified",
        "access_scope": "approved",
        "redistribution": "allowed",
    }
    _resign_report(compilation)

    with pytest.raises(PromotionAssessmentError, match="source policy is not exact"):
        build_production_promotion_assessment_v2(compilation)


@pytest.mark.parametrize("attribute", ["denominator_final", "catalog_emit_eligible"])
def test_assessment_rejects_v1_catalog_promotion_flag_mutation(
    tmp_path: Path,
    attribute: str,
) -> None:
    compilation = compile_source_to_capability_bundle(_config(tmp_path))
    object.__setattr__(compilation.bridge.catalog_input, attribute, True)

    with pytest.raises(PromotionAssessmentError, match="validation failed"):
        build_production_promotion_assessment_v2(compilation)


def test_assessment_rejects_non_compilation_input() -> None:
    with pytest.raises(PromotionAssessmentError, match="validation failed"):
        build_production_promotion_assessment_v2(object())  # type: ignore[arg-type]


def test_checked_in_m_b_summary_is_small_strict_and_explicitly_unmeasured() -> None:
    summary_path = ROOT / "data/golden/sim02b-m-b-no-go-v2.json"
    schema_path = (
        ROOT / "data/schemas/sim02b-m-b-assessment-summary-v2.schema.json"
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    validate_document_contract(
        summary,
        schema,
        "checked-in SIM-02B M-B assessment summary",
        fail_on_unknown_keywords=True,
    )
    assert summary_path.stat().st_size < 4 * 1024
    assert summary["verified_target_mapping"] == {
        "numerator": 0,
        "denominator": 235,
        "rate_ppm": 0,
    }
    assert summary["promotion_candidate"] is False
    assert summary["champions_candidate"] is False
    assert summary["rank1_equivalence_status"] == "unmeasured"
    assert summary["production_trust_anchor_status"] == "not_implemented"
    assert summary["large_assessment_storage"] == "gitignored_data_processed_only"
