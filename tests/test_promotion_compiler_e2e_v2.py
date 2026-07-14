from __future__ import annotations

import json
from pathlib import Path

import pytest
import _sim02b_fixture as fixture_module

from _sim02b_fixture import (
    CORE_ARTIFACT_IDS,
    DEVELOPMENT_ARTIFACT_IDS,
    build_test_authoritative_sim02b_fixture,
    rewrite_manifest_artifact,
    rewrite_source_manifests_as_production_claim,
)
from champions_sim.promotion.compiler import (
    PromotionCompilationError,
    resolve_promotion_source_set_v2,
    validate_production_promotion_compilation_v2,
)
from champions_sim.core import canonical_json
from champions_sim.promotion import compiler as promotion_compiler
from champions_sim.promotion.sources import (
    PromotionSourceError,
    PromotionSourceScopeV2,
)


def test_test_authoritative_fixture_compiles_revalidates_and_is_deterministic(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)

    first = fixture.compile()
    second = fixture.compile()
    revalidated = validate_production_promotion_compilation_v2(first)

    assert first.report.to_json() == second.report.to_json()
    assert first.report.to_json() == revalidated.report.to_json()
    assert dict(first.documents) == dict(second.documents) == dict(revalidated.documents)
    assert first.source_set.to_json() == second.source_set.to_json()
    assert first.source_set.scope is PromotionSourceScopeV2.TEST_AUTHORITATIVE
    assert len(first.source_set.manifests) == 3
    assert first.report.attestation_scope == "test_authoritative"
    assert first.report.status == "engineering_candidate"
    assert first.report.promotion_gate_passed is True
    assert first.report.champions_candidate is False
    assert first.report.champions_fidelity_status == "not_attested"
    assert first.report.rank1_equivalence_status == "unmeasured"
    assert first.report.external_holdout_novel_gap_count == 0
    assert first.report.silent_fallback_count == 0
    assert first.external_holdout_gap_report.holdout_clean is True
    assert first.mechanic_coverage_matrix.candidate_ready is True
    assert {
        value.signature.effect_id for value in first.target_capability_set.capabilities
    } == {"move.damage", "ability.rough_skin", "item.leftovers"}
    for rate in (
        first.report.verified_target_mapping_rate,
        first.report.development_scenario_coverage_rate,
        first.report.verified_grounding_conformance_rate,
        first.report.engine_probe_pass_rate,
    ):
        assert rate.numerator == rate.denominator > 0
        assert rate.rate_ppm == 1_000_000


def test_compile_resolves_each_source_manifest_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    original = promotion_compiler.resolve_promotion_source_manifest_v2
    calls: list[str] = []

    def counted(path, **kwargs):
        calls.append(Path(path).name)
        return original(path, **kwargs)

    monkeypatch.setattr(
        promotion_compiler,
        "resolve_promotion_source_manifest_v2",
        counted,
    )
    fixture.compile()

    assert calls == sorted(path.name for path in fixture.manifest_paths)


def test_unsealed_artifact_tamper_fails_compile_and_revalidation(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    compilation = fixture.compile()
    catalog_path = fixture.artifact_paths[CORE_ARTIFACT_IDS["catalog"]]
    catalog_path.write_bytes(catalog_path.read_bytes() + b"\n")

    with pytest.raises(PromotionSourceError, match="artifact byte_count mismatch"):
        fixture.compile()
    with pytest.raises(PromotionSourceError, match="artifact byte_count mismatch"):
        validate_production_promotion_compilation_v2(compilation)


def test_portable_compilation_rejects_document_digest_drift(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    compilation = fixture.compile()
    compilation.documents["engine-probe-report.json"] += " "

    with pytest.raises(
        PromotionCompilationError,
        match="document digest differs: engine-probe-report.json",
    ):
        compilation.to_json()


def test_resigned_scenario_byte_drift_is_rejected_against_runtime_object(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    scenario_id = DEVELOPMENT_ARTIFACT_IDS["scenarios"]
    scenario_path = fixture.artifact_paths[scenario_id]

    rewrite_manifest_artifact(
        fixture,
        scenario_id,
        scenario_path.read_text(encoding="utf-8") + "\n",
    )

    with pytest.raises(
        PromotionCompilationError,
        match="development scenario corpus bytes differ from exact runtime object",
    ):
        fixture.compile()


def test_resolver_derived_production_claim_cannot_promote_synthetic_regulation(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    assert not hasattr(fixture.request, "attestation_scope")
    rewrite_source_manifests_as_production_claim(fixture)

    resolved = resolve_promotion_source_set_v2(fixture.request)
    assert resolved.scope is PromotionSourceScopeV2.PRODUCTION_CHAMPIONS
    with pytest.raises(
        PromotionCompilationError,
        match="production source scope requires current verified Regulation",
    ):
        fixture.compile()


def test_untrusted_local_claims_cannot_issue_production_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_regulation = fixture_module._regulation_document

    def production_claim_regulation():
        document = original_regulation()
        document.update(
            {
                "status": "current",
                "verification_status": "verified",
                "published_at": "2026-07-13T00:00:00+00:00",
            }
        )
        return document

    monkeypatch.setattr(
        fixture_module,
        "_regulation_document",
        production_claim_regulation,
    )
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    rewrite_source_manifests_as_production_claim(fixture)
    timing_id = CORE_ARTIFACT_IDS["timing_evidence"]
    timing = json.loads(
        fixture.artifact_paths[timing_id].read_text(encoding="utf-8")
    )
    timing["measurement_status"] = "measured"
    rewrite_manifest_artifact(fixture, timing_id, canonical_json(timing))

    with pytest.raises(
        PromotionCompilationError,
        match="artifact-root-external trust anchor",
    ):
        fixture.compile()
