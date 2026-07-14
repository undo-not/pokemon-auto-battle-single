from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest
import _sim02b_fixture as fixture_module

from _sim02b_fixture import (
    CORE_ARTIFACT_IDS,
    DEVELOPMENT_ARTIFACT_IDS,
    HOLDOUT_ARTIFACT_IDS,
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
from champions_sim.promotion.scenarios import (
    PromotionScenarioError,
    build_engine_scenario_corpus_v2,
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


def test_compiler_rejects_replay_id_relabelled_development_execution_as_holdout(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    holdout_scenario = fixture.external_holdout_scenario_corpus.scenarios[0]
    development_scenario = next(
        value
        for value in fixture.development_scenario_corpus.scenarios
        if value.capability_id == holdout_scenario.capability_id
    )
    development_replay = fixture.replays[development_scenario.scenario_id]
    relabelled_replay = replace(
        development_replay,
        replay_id="replay-cosmetically-relabeled-holdout",
    )
    attacked_scenario = replace(
        holdout_scenario,
        initial_state_hash=development_scenario.initial_state_hash,
        choice_sequence_hash=development_scenario.choice_sequence_hash,
        seed=development_scenario.seed,
        rng_algorithm_id=development_scenario.rng_algorithm_id,
        replay_hash=relabelled_replay.replay_hash,
        replay_execution_hash=development_scenario.replay_execution_hash,
        witness_step_index=development_scenario.witness_step_index,
        witness_event_index=development_scenario.witness_event_index,
        witness_event_kind=development_scenario.witness_event_kind,
        witness_event_hash=development_scenario.witness_event_hash,
    )
    attacked_holdout = build_engine_scenario_corpus_v2(
        corpus_id=fixture.external_holdout_scenario_corpus.corpus_id,
        corpus_role="external_holdout",
        target_capability_set_hash=(
            fixture.external_holdout_scenario_corpus.target_capability_set_hash
        ),
        catalog_hash=fixture.external_holdout_scenario_corpus.catalog_hash,
        ruleset_hash=fixture.external_holdout_scenario_corpus.ruleset_hash,
        scenarios=(attacked_scenario,),
    )
    rewrite_manifest_artifact(
        fixture,
        HOLDOUT_ARTIFACT_IDS["replay"],
        relabelled_replay.to_json(),
    )
    rewrite_manifest_artifact(
        fixture,
        HOLDOUT_ARTIFACT_IDS["scenarios"],
        attacked_holdout.to_json(),
    )
    replays = dict(fixture.replays)
    replays[holdout_scenario.scenario_id] = relabelled_replay
    attacked_fixture = replace(
        fixture,
        external_holdout_scenario_corpus=attacked_holdout,
        replays=replays,
    )

    assert relabelled_replay.replay_hash != development_replay.replay_hash
    assert (
        attacked_scenario.replay_execution_hash
        == development_scenario.replay_execution_hash
    )
    with pytest.raises(
        PromotionScenarioError,
        match="replay_execution_hash_overlap",
    ):
        attacked_fixture.compile()


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
