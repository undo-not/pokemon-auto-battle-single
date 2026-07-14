from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from _sim02b_fixture import build_test_authoritative_sim02b_fixture
from champions_sim.core import canonical_hash, canonical_json
from champions_sim.env import (
    ResolvedChampionsReadiness,
    ResolvedChampionsReadinessV2,
    resolve_champions_readiness,
    resolve_champions_readiness_v2,
)
from champions_sim.env import readiness_v2
from champions_sim.env.readiness_v2 import ChampionsReadinessV2Error
from champions_sim.promotion.compiler import ProductionPromotionCompilationV2
from champions_sim.promotion.reporting import (
    PROMOTION_COMPILER_ID,
    PROMOTION_REPORT_SCHEMA_VERSION,
    ExactRateV2,
    ProductionPromotionReportV2,
    PromotionDocumentDigestV2,
    PromotionTimingEvidenceV2,
    exact_rate_binding_hash_v2,
    production_report_id_v2,
)
from champions_sim.promotion.sources import PromotionSourceScopeV2
from scripts.validate_sim01_bundle import (
    BundleValidationError,
    validate_document_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "data/schemas/sim02b-champions-readiness-v2.schema.json"
COMPILATION_SCHEMA = (
    ROOT / "data/schemas/sim02b-production-compilation-v2.schema.json"
)

_COMPONENT_NAMES = (
    "source_resolution_set_hash",
    "artifact_binding_hash",
    "regulation_hash",
    "target_pool_hash",
    "catalog_hash",
    "ruleset_hash",
    "mapping_evidence_hash",
    "target_pool_manifest_hash",
    "semantic_compilation_hash",
    "target_capability_set_hash",
    "execution_compilation_hash",
    "construction_corpus_hash",
    "scenario_corpus_hash",
    "external_holdout_scenario_corpus_hash",
    "partition_manifest_hash",
    "external_holdout_hash",
    "grounding_resolution_hash",
    "engine_probe_report_hash",
    "mechanic_coverage_matrix_hash",
    "timing_evidence_hash",
)


def _sha(label: str) -> str:
    return canonical_hash(("readiness-v2-test", label))


def _rate(
    metric_id: str,
    count: int,
    component_hashes: dict[str, str],
) -> ExactRateV2:
    binding_names = {
        "verified_target_mapping_rate": ("target_pool_hash",),
        "development_scenario_coverage_rate": (
            "target_capability_set_hash",
            "partition_manifest_hash",
        ),
        "verified_grounding_conformance_rate": (
            "target_capability_set_hash",
            "partition_manifest_hash",
            "grounding_resolution_hash",
        ),
        "engine_probe_pass_rate": (
            "target_capability_set_hash",
            "partition_manifest_hash",
            "engine_probe_report_hash",
        ),
    }[metric_id]
    return ExactRateV2(
        metric_id=metric_id,
        numerator=count,
        denominator=count,
        rate_ppm=1_000_000,
        denominator_binding_hash=exact_rate_binding_hash_v2(
            metric_id,
            count,
            count,
            *(component_hashes[name] for name in binding_names),
        ),
    )


def _compilation(scope: str) -> ProductionPromotionCompilationV2:
    source_scope = PromotionSourceScopeV2(scope)
    grounding_resolution = ("validated-grounding-resolution", scope)
    timing = PromotionTimingEvidenceV2(
        timing_id=f"timing-{scope}",
        measurement_status=(
            "measured" if scope == "production_champions" else "test_fixed"
        ),
        t0="2026-07-01T00:00:00+00:00",
        t_decision="2026-07-02T00:00:00+00:00",
        compute_seconds=3_600,
        manual_seconds=3_600,
        external_wait_seconds=79_200,
    )
    component_hashes = {
        name: _sha(f"{scope}:{name}") for name in _COMPONENT_NAMES
    }
    component_hashes["grounding_resolution_hash"] = canonical_hash(
        grounding_resolution
    )
    component_hashes["timing_evidence_hash"] = timing.timing_hash
    base_documents = {
        "engine-probe-report.json": canonical_json(
            {"engine_probe_report_hash": component_hashes["engine_probe_report_hash"]}
        ),
        "scenario-partition.json": canonical_json(
            {"partition_manifest_hash": component_hashes["partition_manifest_hash"]}
        ),
    }
    document_digests = tuple(
        PromotionDocumentDigestV2(
            name,
            hashlib.sha256(document.encode("utf-8")).hexdigest(),
            len(document.encode("utf-8")),
        )
        for name, document in sorted(base_documents.items())
    )
    production = scope == "production_champions"
    report_id = production_report_id_v2(
        attestation_scope=scope,
        source_resolution_set_hash=component_hashes[
            "source_resolution_set_hash"
        ],
        target_pool_hash=component_hashes["target_pool_hash"],
        target_capability_set_hash=component_hashes[
            "target_capability_set_hash"
        ],
        partition_manifest_hash=component_hashes["partition_manifest_hash"],
        engine_probe_report_hash=component_hashes["engine_probe_report_hash"],
    )
    report = ProductionPromotionReportV2(
        schema_version=PROMOTION_REPORT_SCHEMA_VERSION,
        report_id=report_id,
        compiler_id=PROMOTION_COMPILER_ID,
        attestation_scope=scope,
        status="production_candidate" if production else "engineering_candidate",
        promotion_gate_passed=True,
        champions_candidate=production,
        champions_fidelity_status=(
            "evidence_attested" if production else "not_attested"
        ),
        rank1_equivalence_status="unmeasured",
        regulation_id="TEST-C",
        regulation_revision="v1.0.0",
        **component_hashes,
        timing_evidence=timing,
        verified_target_mapping_rate=_rate(
            "verified_target_mapping_rate", 3, component_hashes
        ),
        development_scenario_coverage_rate=_rate(
            "development_scenario_coverage_rate", 4, component_hashes
        ),
        verified_grounding_conformance_rate=_rate(
            "verified_grounding_conformance_rate", 5, component_hashes
        ),
        engine_probe_pass_rate=_rate(
            "engine_probe_pass_rate", 4, component_hashes
        ),
        external_holdout_novel_gap_count=0,
        silent_fallback_count=0,
        decision_lead_time_seconds=timing.lead_time_seconds,
        blockers=(),
        resume_conditions=(),
        documents=document_digests,
    )
    documents = {**base_documents, "promotion-report.json": report.to_json()}
    source_set = SimpleNamespace(
        scope=source_scope,
        source_set_id=f"promotion-source-set-{scope}",
        resolution_set_hash=component_hashes["source_resolution_set_hash"],
    )
    regulation_bundle = SimpleNamespace(
        regulation=SimpleNamespace(
            regulation_id=report.regulation_id,
            revision=report.regulation_revision,
            snapshot_hash=component_hashes["regulation_hash"],
        ),
        target_pool=SimpleNamespace(
            snapshot_hash=component_hashes["target_pool_hash"]
        ),
    )
    return ProductionPromotionCompilationV2(
        schema_version="2.0.0",
        source_set=source_set,
        regulation_bundle=regulation_bundle,
        catalog=SimpleNamespace(snapshot_hash=component_hashes["catalog_hash"]),
        ruleset=SimpleNamespace(snapshot_hash=component_hashes["ruleset_hash"]),
        mapping_evidence=SimpleNamespace(
            snapshot_hash=component_hashes["mapping_evidence_hash"]
        ),
        development_construction_corpus=SimpleNamespace(
            snapshot_hash=component_hashes["construction_corpus_hash"]
        ),
        external_holdout_construction_corpus=SimpleNamespace(
            snapshot_hash=_sha(f"{scope}:holdout-construction")
        ),
        target_pool_manifest=SimpleNamespace(
            manifest_hash=component_hashes["target_pool_manifest_hash"]
        ),
        semantic_compilation=SimpleNamespace(
            compilation_hash=component_hashes["semantic_compilation_hash"]
        ),
        target_capability_set=SimpleNamespace(
            capability_set_hash=component_hashes["target_capability_set_hash"]
        ),
        execution_compilation=SimpleNamespace(
            compilation_hash=component_hashes["execution_compilation_hash"]
        ),
        development_scenario_corpus=SimpleNamespace(
            corpus_hash=component_hashes["scenario_corpus_hash"]
        ),
        external_holdout_scenario_corpus=SimpleNamespace(
            corpus_hash=component_hashes[
                "external_holdout_scenario_corpus_hash"
            ]
        ),
        partition_manifest=SimpleNamespace(
            partition_hash=component_hashes["partition_manifest_hash"]
        ),
        engine_probe_report=SimpleNamespace(
            report_hash=component_hashes["engine_probe_report_hash"]
        ),
        grounding_resolution=grounding_resolution,
        external_holdout_gap_report=SimpleNamespace(
            report_hash=_sha(f"{scope}:holdout-construction-gap")
        ),
        external_holdout_report=SimpleNamespace(
            report_hash=component_hashes["external_holdout_hash"]
        ),
        mechanic_coverage_matrix=SimpleNamespace(
            matrix_hash=component_hashes["mechanic_coverage_matrix_hash"]
        ),
        timing_evidence=timing,
        report=report,
        documents=documents,
        _request=SimpleNamespace(),
        _replays={},
        _validated_traces={},
    )


def _issue(
    monkeypatch: pytest.MonkeyPatch,
    scope: str = "test_authoritative",
) -> tuple[ProductionPromotionCompilationV2, ResolvedChampionsReadinessV2]:
    compilation = _compilation(scope)
    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        lambda value: compilation,
    )
    return compilation, resolve_champions_readiness_v2(compilation)


@pytest.mark.parametrize(
    ("scope", "status", "champions_candidate", "fidelity"),
    (
        (
            "test_authoritative",
            "engineering_sealed",
            False,
            "not_attested",
        ),
        (
            "production_champions",
            "production_candidate",
            True,
            "evidence_attested",
        ),
    ),
)
def test_v2_readiness_scope_controls_candidate_semantics_and_schema(
    monkeypatch: pytest.MonkeyPatch,
    scope: str,
    status: str,
    champions_candidate: bool,
    fidelity: str,
) -> None:
    _, seal = _issue(monkeypatch, scope)
    assert seal.attestation_scope == scope
    assert seal.readiness_status == status
    assert seal.engineering_seal_issued is True
    assert seal.champions_candidate is champions_candidate
    assert seal.champions_fidelity_status == fidelity
    assert seal.rank1_equivalence_status == "unmeasured"
    assert seal.to_json() == canonical_json(seal.to_data())
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validate_document_contract(seal.to_data(), schema, "Champions readiness V2")


def test_v2_resolver_uses_recomputed_compilation_and_is_byte_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller = _compilation("test_authoritative")
    recomputed = _compilation("production_champions")
    seen: list[Any] = []

    def validate(value: Any) -> ProductionPromotionCompilationV2:
        seen.append(value)
        return recomputed

    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        validate,
    )
    first = resolve_champions_readiness_v2(caller)
    second = resolve_champions_readiness_v2(caller)
    assert seen == [caller, caller]
    assert first.attestation_scope == "production_champions"
    assert first.to_json() == second.to_json()
    assert first._compilation is recomputed


def test_v2_seal_binds_report_and_every_recomputed_component(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compilation, seal = _issue(monkeypatch)
    report = compilation.report
    assert seal.promotion_report_id == report.report_id
    assert seal.promotion_report_hash == report.report_hash
    for name in _COMPONENT_NAMES:
        assert getattr(seal, name) == getattr(report, name)
    assert seal.source_resolution_set_hash == compilation.source_set.resolution_set_hash
    assert seal.catalog_hash == compilation.catalog.snapshot_hash
    assert seal.ruleset_hash == compilation.ruleset.snapshot_hash
    assert seal.grounding_resolution_hash == canonical_hash(
        compilation.grounding_resolution
    )
    assert seal.scenario_corpus_hash == compilation.development_scenario_corpus.corpus_hash
    assert seal.partition_manifest_hash == compilation.partition_manifest.partition_hash
    assert seal.engine_probe_report_hash == compilation.engine_probe_report.report_hash


@pytest.mark.parametrize(
    "field",
    (
        "promotion_report_hash",
        "source_resolution_set_hash",
        "catalog_hash",
        "ruleset_hash",
        "grounding_resolution_hash",
        "scenario_corpus_hash",
        "partition_manifest_hash",
        "engine_probe_report_hash",
        "document_set_hash",
    ),
)
def test_v2_seal_rejects_each_bound_hash_mutation(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    _, seal = _issue(monkeypatch)
    with pytest.raises(ChampionsReadinessV2Error):
        replace(seal, **{field: "0" * 64})


def test_v2_seal_rejects_rehashed_component_forgery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, seal = _issue(monkeypatch)
    component_hashes = {
        name: getattr(seal, name) for name in _COMPONENT_NAMES
    }
    component_hashes["catalog_hash"] = "0" * 64
    projection_hash = readiness_v2._readiness_projection_hash(
        attestation_scope=seal.attestation_scope,
        regulation_id=seal.regulation_id,
        regulation_revision=seal.regulation_revision,
        source_set_id=seal.source_set_id,
        promotion_report_id=seal.promotion_report_id,
        promotion_report_hash=seal.promotion_report_hash,
        compilation_hash=seal.compilation_binding_hash,
        component_hashes=component_hashes,
        document_set_hash=seal.document_set_hash,
    )
    forged_seal_id = readiness_v2._seal_id(
        seal.attestation_scope,
        projection_hash,
    )

    with pytest.raises(
        ChampionsReadinessV2Error,
        match="projection differs from retained compilation",
    ):
        replace(
            seal,
            catalog_hash="0" * 64,
            seal_id=forged_seal_id,
        )


def test_v2_seal_revalidates_retained_compilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, seal = _issue(monkeypatch, "test_authoritative")
    production = _compilation("production_champions")
    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        lambda value: production,
    )
    with pytest.raises(ChampionsReadinessV2Error, match="differs from recomputed"):
        seal.validate_against()


@pytest.mark.parametrize(
    "target",
    (
        "source_resolution",
        "catalog",
        "ruleset",
        "grounding",
        "scenario",
        "partition",
        "engine_probe",
        "external_holdout",
        "report",
        "documents",
    ),
)
def test_v2_resolver_rejects_each_recomputed_substance_mutation(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    compilation = _compilation("test_authoritative")
    if target == "source_resolution":
        compilation.source_set.resolution_set_hash = "0" * 64
    elif target == "catalog":
        compilation.catalog.snapshot_hash = "0" * 64
    elif target == "ruleset":
        compilation.ruleset.snapshot_hash = "0" * 64
    elif target == "grounding":
        object.__setattr__(compilation, "grounding_resolution", ("changed",))
    elif target == "scenario":
        compilation.development_scenario_corpus.corpus_hash = "0" * 64
    elif target == "partition":
        compilation.partition_manifest.partition_hash = "0" * 64
    elif target == "engine_probe":
        compilation.engine_probe_report.report_hash = "0" * 64
    elif target == "external_holdout":
        compilation.external_holdout_report.report_hash = "0" * 64
    elif target == "report":
        object.__setattr__(compilation.report, "catalog_hash", "0" * 64)
    else:
        compilation.documents["engine-probe-report.json"] += " "
    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        lambda value: compilation,
    )
    with pytest.raises(ChampionsReadinessV2Error):
        resolve_champions_readiness_v2(compilation)


def test_v2_resolver_rejects_source_scope_report_scope_disagreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compilation = _compilation("test_authoritative")
    compilation.source_set.scope = PromotionSourceScopeV2.PRODUCTION_CHAMPIONS
    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        lambda value: compilation,
    )
    with pytest.raises(ChampionsReadinessV2Error, match="scope differs"):
        resolve_champions_readiness_v2(compilation)


def test_v2_rejects_non_v2_input_and_wraps_compiler_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ChampionsReadinessV2Error, match="exact"):
        resolve_champions_readiness_v2(object())  # type: ignore[arg-type]

    compilation = _compilation("test_authoritative")

    def fail(value: Any) -> ProductionPromotionCompilationV2:
        raise ValueError("source bytes changed")

    monkeypatch.setattr(
        readiness_v2,
        "validate_production_promotion_compilation_v2",
        fail,
    )
    with pytest.raises(ChampionsReadinessV2Error, match="revalidation failed"):
        resolve_champions_readiness_v2(compilation)


def test_v1_and_v2_readiness_exports_remain_distinct() -> None:
    assert ResolvedChampionsReadinessV2 is not ResolvedChampionsReadiness
    assert resolve_champions_readiness_v2 is not resolve_champions_readiness


def test_authoritative_fixture_portable_compilation_and_readiness_round_trip(
    tmp_path: Path,
) -> None:
    fixture = build_test_authoritative_sim02b_fixture(tmp_path)
    compilation = fixture.compile()
    seal = resolve_champions_readiness_v2(compilation)

    compilation_data = compilation.to_data()
    assert json.loads(compilation.to_json()) == compilation_data
    assert compilation.to_json() == canonical_json(compilation_data)
    compilation_schema = json.loads(
        COMPILATION_SCHEMA.read_text(encoding="utf-8")
    )
    validate_document_contract(
        compilation_data,
        compilation_schema,
        "production promotion compilation V2",
    )

    readiness_schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validate_document_contract(
        seal.to_data(), readiness_schema, "Champions readiness V2"
    )
    assert seal.attestation_scope == "test_authoritative"
    assert seal.readiness_status == "engineering_sealed"
    assert seal.champions_candidate is False
    assert seal.compilation_binding_hash == compilation.compilation_hash
    assert seal.document_set_hash == compilation.document_set_hash
    seal.validate_against()


def test_v2_schema_rejects_missing_unknown_and_scope_forgery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, seal = _issue(monkeypatch)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    missing = seal.to_data()
    missing.pop("engine_probe_report_hash", None)
    missing["component_hashes"].pop("engine_probe_report_hash")
    with pytest.raises(BundleValidationError):
        validate_document_contract(missing, schema, "readiness missing binding")

    extra = {**seal.to_data(), "caller_verified": True}
    with pytest.raises(BundleValidationError):
        validate_document_contract(extra, schema, "readiness caller flag")

    forged = seal.to_data()
    forged["champions_candidate"] = True
    with pytest.raises(BundleValidationError):
        validate_document_contract(forged, schema, "readiness scope forgery")
