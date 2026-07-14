from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from champions_sim.core import canonical_hash
from champions_sim.promotion.reporting import (
    PROMOTION_COMPILER_ID,
    PROMOTION_REPORT_SCHEMA_VERSION,
    ExactRateV2,
    ProductionPromotionReportV2,
    PromotionDocumentDigestV2,
    PromotionReportingError,
    PromotionTimingEvidenceV2,
    exact_rate_binding_hash_v2,
    production_report_id_v2,
)
from scripts.validate_sim01_bundle import (
    BundleValidationError,
    validate_document_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT / "data/schemas/sim02b-production-promotion-report-v2.schema.json"
)

COMPONENT_HASH_FIELDS = (
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

REPORT_ID_COMPONENT_FIELDS = frozenset(
    {
        "source_resolution_set_hash",
        "target_pool_hash",
        "target_capability_set_hash",
        "partition_manifest_hash",
        "engine_probe_report_hash",
    }
)

RATE_FIELDS = (
    "verified_target_mapping_rate",
    "development_scenario_coverage_rate",
    "verified_grounding_conformance_rate",
    "engine_probe_pass_rate",
)

RATE_COMPONENT_FIELDS = {
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
}


def _sha(label: str) -> str:
    return canonical_hash(("promotion-reporting-v2-test", label))


def _schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _timing(
    attestation_scope: str = "test_authoritative",
) -> PromotionTimingEvidenceV2:
    return PromotionTimingEvidenceV2(
        timing_id="regulation-turnaround-TEST-C-v1",
        measurement_status=(
            "measured"
            if attestation_scope == "production_champions"
            else "test_fixed"
        ),
        t0="2026-07-01T00:00:00+00:00",
        t_decision="2026-07-03T00:00:00+00:00",
        compute_seconds=7_200,
        manual_seconds=3_600,
        external_wait_seconds=162_000,
    )


def _component_value(source: Any, field_name: str) -> str:
    if isinstance(source, dict):
        return source[field_name]
    return getattr(source, field_name)


def _binding_hash(
    metric_id: str,
    numerator: int,
    denominator: int,
    component_source: Any,
) -> str:
    return exact_rate_binding_hash_v2(
        metric_id,
        numerator,
        denominator,
        *(
            _component_value(component_source, field_name)
            for field_name in RATE_COMPONENT_FIELDS[metric_id]
        ),
    )


def _exact_rate(
    metric_id: str,
    numerator: int,
    denominator: int,
    component_source: Any,
) -> ExactRateV2:
    return ExactRateV2(
        metric_id=metric_id,
        numerator=numerator,
        denominator=denominator,
        rate_ppm=numerator * 1_000_000 // denominator,
        denominator_binding_hash=_binding_hash(
            metric_id,
            numerator,
            denominator,
            component_source,
        ),
    )


def _report(
    attestation_scope: str = "test_authoritative",
    **overrides: Any,
) -> ProductionPromotionReportV2:
    production_scope = attestation_scope == "production_champions"
    component_hashes = {
        name: _sha(name) for name in COMPONENT_HASH_FIELDS
    }
    timing = _timing(attestation_scope)
    component_hashes["timing_evidence_hash"] = timing.timing_hash
    values: dict[str, Any] = {
        "schema_version": PROMOTION_REPORT_SCHEMA_VERSION,
        "compiler_id": PROMOTION_COMPILER_ID,
        "attestation_scope": attestation_scope,
        "status": (
            "production_candidate" if production_scope else "engineering_candidate"
        ),
        "promotion_gate_passed": True,
        "champions_candidate": production_scope,
        "champions_fidelity_status": (
            "evidence_attested" if production_scope else "not_attested"
        ),
        "rank1_equivalence_status": "unmeasured",
        "regulation_id": "TEST-C",
        "regulation_revision": "v1.0.0",
        **component_hashes,
        "verified_target_mapping_rate": _exact_rate(
            "verified_target_mapping_rate",
            3,
            3,
            component_hashes,
        ),
        "development_scenario_coverage_rate": _exact_rate(
            "development_scenario_coverage_rate",
            12,
            12,
            component_hashes,
        ),
        "verified_grounding_conformance_rate": _exact_rate(
            "verified_grounding_conformance_rate",
            8,
            8,
            component_hashes,
        ),
        "engine_probe_pass_rate": _exact_rate(
            "engine_probe_pass_rate",
            6,
            6,
            component_hashes,
        ),
        "external_holdout_novel_gap_count": 0,
        "silent_fallback_count": 0,
        "decision_lead_time_seconds": timing.lead_time_seconds,
        "timing_evidence": timing,
        "blockers": (),
        "resume_conditions": (),
        "documents": (
            PromotionDocumentDigestV2(
                "engine-probe-report.json", _sha("engine-probe-document"), 4_096
            ),
            PromotionDocumentDigestV2(
                "promotion-decision.md", _sha("promotion-decision-document"), 2_048
            ),
        ),
    }
    values.update(overrides)
    values.setdefault(
        "report_id",
        production_report_id_v2(
            attestation_scope=values["attestation_scope"],
            source_resolution_set_hash=values["source_resolution_set_hash"],
            target_pool_hash=values["target_pool_hash"],
            target_capability_set_hash=values["target_capability_set_hash"],
            partition_manifest_hash=values["partition_manifest_hash"],
            engine_probe_report_hash=values["engine_probe_report_hash"],
        ),
    )
    return ProductionPromotionReportV2(**values)


def _replace_with_valid_report_id(
    report: ProductionPromotionReportV2,
    **changes: Any,
) -> ProductionPromotionReportV2:
    def value(name: str) -> Any:
        return changes.get(name, getattr(report, name))

    component_values = {
        name: value(name) for name in COMPONENT_HASH_FIELDS
    }
    for rate_field in RATE_FIELDS:
        rate = changes.get(rate_field, getattr(report, rate_field))
        changes[rate_field] = replace(
            rate,
            denominator_binding_hash=_binding_hash(
                rate.metric_id,
                rate.numerator,
                rate.denominator,
                component_values,
            ),
        )
    if "timing_evidence" in changes:
        timing_evidence = changes["timing_evidence"]
        changes.setdefault("timing_evidence_hash", timing_evidence.timing_hash)
        changes.setdefault(
            "decision_lead_time_seconds", timing_evidence.lead_time_seconds
        )

    report_id = production_report_id_v2(
        attestation_scope=value("attestation_scope"),
        source_resolution_set_hash=value("source_resolution_set_hash"),
        target_pool_hash=value("target_pool_hash"),
        target_capability_set_hash=value("target_capability_set_hash"),
        partition_manifest_hash=value("partition_manifest_hash"),
        engine_probe_report_hash=value("engine_probe_report_hash"),
    )
    return replace(report, report_id=report_id, **changes)


@pytest.mark.parametrize(
    ("scope", "status", "champions_candidate", "fidelity_status"),
    [
        (
            "test_authoritative",
            "engineering_candidate",
            False,
            "not_attested",
        ),
        (
            "production_champions",
            "production_candidate",
            True,
            "evidence_attested",
        ),
    ],
)
def test_positive_report_scopes_are_exact_and_strict_schema_valid(
    scope: str,
    status: str,
    champions_candidate: bool,
    fidelity_status: str,
) -> None:
    report = _report(scope)
    data = report.to_data()

    assert report.status == status
    assert report.champions_candidate is champions_candidate
    assert report.champions_fidelity_status == fidelity_status
    assert report.timing_evidence.measurement_status == (
        "measured" if scope == "production_champions" else "test_fixed"
    )
    assert report.timing_evidence_hash == report.timing_evidence.timing_hash
    assert report.decision_lead_time_seconds == report.timing_evidence.lead_time_seconds
    assert report.rank1_equivalence_status == "unmeasured"
    assert report.promotion_gate_passed is True
    assert report.report_hash == canonical_hash(report.unsigned_data())
    assert json.loads(report.to_json()) == data
    assert set(data["component_hashes"]) == set(COMPONENT_HASH_FIELDS)
    assert set(data["metrics"]) == set(RATE_FIELDS)
    assert all(
        metric["numerator"] == metric["denominator"]
        and metric["rate_ppm"] == 1_000_000
        for metric in data["metrics"].values()
    )

    validate_document_contract(
        data,
        _schema(),
        "SIM-02B production promotion report",
        fail_on_unknown_keywords=True,
    )


def test_report_serialization_and_identity_are_deterministic() -> None:
    first = _report()
    second = _report()

    assert first == second
    assert first.report_id == second.report_id
    assert first.report_hash == second.report_hash
    assert first.to_json() == second.to_json()
    assert first.report_id == production_report_id_v2(
        attestation_scope=first.attestation_scope,
        source_resolution_set_hash=first.source_resolution_set_hash,
        target_pool_hash=first.target_pool_hash,
        target_capability_set_hash=first.target_capability_set_hash,
        partition_manifest_hash=first.partition_manifest_hash,
        engine_probe_report_hash=first.engine_probe_report_hash,
    )


@pytest.mark.parametrize("field_name", COMPONENT_HASH_FIELDS)
def test_every_component_hash_is_bound_by_the_report_hash(field_name: str) -> None:
    report = _report()
    if field_name == "timing_evidence_hash":
        mutated = _replace_with_valid_report_id(
            report,
            timing_evidence=replace(
                report.timing_evidence,
                timing_id="mutated-regulation-turnaround",
            ),
        )
    else:
        mutated = _replace_with_valid_report_id(
            report,
            **{field_name: _sha(f"mutated-{field_name}")},
        )

    assert mutated.report_hash != report.report_hash
    assert (
        mutated.to_data()["component_hashes"][field_name]
        != report.to_data()["component_hashes"][field_name]
    )
    assert (mutated.report_id != report.report_id) is (
        field_name in REPORT_ID_COMPONENT_FIELDS
    )


@pytest.mark.parametrize("rate_field", RATE_FIELDS)
def test_every_exact_rate_is_bound_by_the_report_hash(rate_field: str) -> None:
    report = _report()
    original_rate = getattr(report, rate_field)
    mutated_rate = replace(
        original_rate,
        numerator=original_rate.numerator + 1,
        denominator=original_rate.denominator + 1,
    )
    mutated = _replace_with_valid_report_id(
        report,
        **{rate_field: mutated_rate},
    )

    assert mutated.report_id == report.report_id
    assert mutated.report_hash != report.report_hash
    assert mutated.to_data()["metrics"][rate_field]["rate_ppm"] == 1_000_000


def test_scope_lead_time_and_documents_are_bound_by_report_hash() -> None:
    report = _report()
    production = _report("production_champions")
    shorter_timing = replace(
        report.timing_evidence,
        t_decision="2026-07-02T23:59:59+00:00",
        external_wait_seconds=161_999,
    )
    shorter = _replace_with_valid_report_id(
        report,
        timing_evidence=shorter_timing,
    )
    changed_document = replace(
        report,
        documents=(
            report.documents[0],
            replace(report.documents[1], byte_count=2_049),
        ),
    )

    assert production.report_id != report.report_id
    assert production.report_hash != report.report_hash
    assert shorter.report_id == report.report_id
    assert shorter.report_hash != report.report_hash
    assert changed_document.report_id == report.report_id
    assert changed_document.report_hash != report.report_hash


def test_grounding_rate_counts_unique_required_requirement_ids() -> None:
    required_requirement_ids = (
        "grounding:ability:static",
        "grounding:ability:static",
        "grounding:move:thunderbolt",
    )
    satisfied_requirement_ids = (
        "grounding:move:thunderbolt",
        "grounding:ability:static",
        "grounding:move:thunderbolt",
    )
    unique_required = frozenset(required_requirement_ids)
    unique_satisfied = frozenset(satisfied_requirement_ids) & unique_required
    baseline = _report()
    rate = _exact_rate(
        "verified_grounding_conformance_rate",
        len(unique_satisfied),
        len(unique_required),
        baseline,
    )
    report = replace(baseline, verified_grounding_conformance_rate=rate)

    assert rate.numerator == 2
    assert rate.denominator == 2
    assert len(required_requirement_ids) == 3
    assert rate.denominator_binding_hash == exact_rate_binding_hash_v2(
        rate.metric_id,
        rate.numerator,
        rate.denominator,
        report.target_capability_set_hash,
        report.partition_manifest_hash,
        report.grounding_resolution_hash,
    )
    assert report.to_data()["metrics"][rate.metric_id] == rate.to_data()


def test_exact_rate_rejects_inexact_counts_and_non_sha_binding() -> None:
    binding = _sha("rate-binding")

    with pytest.raises(PromotionReportingError, match="exact positive denominator"):
        ExactRateV2("rate", True, 1, 1_000_000, binding)
    with pytest.raises(PromotionReportingError, match="exact positive denominator"):
        ExactRateV2("rate", 0, 0, 0, binding)
    with pytest.raises(PromotionReportingError, match="differs from its exact counts"):
        ExactRateV2("rate", 1, 2, 1_000_000, binding)
    with pytest.raises(PromotionReportingError, match="lowercase SHA-256"):
        ExactRateV2("rate", 1, 1, 1_000_000, "not-a-sha")


def test_exact_rate_binding_hash_is_deterministic_and_mutation_sensitive() -> None:
    first_component = _sha("binding-component-a")
    second_component = _sha("binding-component-b")
    binding = exact_rate_binding_hash_v2(
        "development_scenario_coverage_rate",
        2,
        2,
        first_component,
        second_component,
    )

    assert binding == exact_rate_binding_hash_v2(
        "development_scenario_coverage_rate",
        2,
        2,
        first_component,
        second_component,
    )
    mutations = {
        exact_rate_binding_hash_v2(
            "engine_probe_pass_rate", 2, 2, first_component, second_component
        ),
        exact_rate_binding_hash_v2(
            "development_scenario_coverage_rate",
            1,
            2,
            first_component,
            second_component,
        ),
        exact_rate_binding_hash_v2(
            "development_scenario_coverage_rate",
            2,
            3,
            first_component,
            second_component,
        ),
        exact_rate_binding_hash_v2(
            "development_scenario_coverage_rate",
            2,
            2,
            second_component,
            first_component,
        ),
        exact_rate_binding_hash_v2(
            "development_scenario_coverage_rate",
            2,
            2,
            first_component,
            _sha("binding-component-c"),
        ),
    }
    assert binding not in mutations
    assert len(mutations) == 5

    with pytest.raises(PromotionReportingError, match="exact valid counts"):
        exact_rate_binding_hash_v2("rate", True, 1, first_component)
    with pytest.raises(PromotionReportingError, match="component hashes"):
        exact_rate_binding_hash_v2("rate", 1, 1)
    with pytest.raises(PromotionReportingError, match="lowercase SHA-256"):
        exact_rate_binding_hash_v2("rate", 1, 1, "not-a-sha")


@pytest.mark.parametrize("rate_field", RATE_FIELDS)
def test_report_rejects_wrong_or_duplicate_metric_slot_ids(rate_field: str) -> None:
    report = _report()
    original = getattr(report, rate_field)
    wrong_id = RATE_FIELDS[(RATE_FIELDS.index(rate_field) + 1) % len(RATE_FIELDS)]

    with pytest.raises(PromotionReportingError, match="exact metric IDs"):
        replace(report, **{rate_field: replace(original, metric_id=wrong_id)})


@pytest.mark.parametrize("rate_field", RATE_FIELDS)
def test_report_rejects_rate_binding_and_count_forgery(rate_field: str) -> None:
    report = _report()
    original = getattr(report, rate_field)

    with pytest.raises(PromotionReportingError, match="denominator binding differs"):
        replace(
            report,
            **{
                rate_field: replace(
                    original,
                    denominator_binding_hash=_sha(f"forged-{rate_field}"),
                )
            },
        )

    changed_counts_with_stale_binding = replace(
        original,
        numerator=original.numerator + 1,
        denominator=original.denominator + 1,
    )
    with pytest.raises(PromotionReportingError, match="denominator binding differs"):
        replace(report, **{rate_field: changed_counts_with_stale_binding})


@pytest.mark.parametrize(
    "component_field",
    sorted(
        {
            field_name
            for field_names in RATE_COMPONENT_FIELDS.values()
            for field_name in field_names
        }
    ),
)
def test_report_rejects_upstream_hash_mutation_without_rate_rebinding(
    component_field: str,
) -> None:
    report = _report()

    with pytest.raises(PromotionReportingError, match="denominator binding differs"):
        replace(
            report,
            **{component_field: _sha(f"unbound-{component_field}")},
        )


@pytest.mark.parametrize("rate_field", RATE_FIELDS)
def test_report_rejects_any_rate_below_one(rate_field: str) -> None:
    report = _report()
    original = getattr(report, rate_field)
    incomplete = ExactRateV2(
        metric_id=original.metric_id,
        numerator=original.denominator - 1,
        denominator=original.denominator,
        rate_ppm=(original.denominator - 1) * 1_000_000 // original.denominator,
        denominator_binding_hash=original.denominator_binding_hash,
    )

    with pytest.raises(PromotionReportingError, match="every rate at 1.0"):
        replace(report, **{rate_field: incomplete})


def test_report_rejects_timing_hash_lead_and_payload_forgery() -> None:
    report = _report()
    changed_payload = replace(
        report.timing_evidence,
        timing_id="forged-timing-payload",
    )

    for changes in (
        {"timing_evidence_hash": _sha("unrelated-timing-evidence")},
        {"decision_lead_time_seconds": report.decision_lead_time_seconds - 1},
        {"timing_evidence": changed_payload},
    ):
        with pytest.raises(PromotionReportingError, match="timing hash/lead"):
            replace(report, **changes)


@pytest.mark.parametrize(
    ("scope", "wrong_measurement_status"),
    [
        ("test_authoritative", "measured"),
        ("production_champions", "test_fixed"),
    ],
)
def test_report_rejects_timing_measurement_status_outside_scope(
    scope: str,
    wrong_measurement_status: str,
) -> None:
    report = _report(scope)
    wrong_timing = replace(
        report.timing_evidence,
        measurement_status=wrong_measurement_status,
    )

    with pytest.raises(PromotionReportingError, match="status differs from scope"):
        replace(
            report,
            timing_evidence=wrong_timing,
            timing_evidence_hash=wrong_timing.timing_hash,
        )


def test_48_hour_timing_boundary_and_accounting_are_exact() -> None:
    timing = _timing()

    assert timing.lead_time_seconds == 48 * 60 * 60
    assert timing.accounted_seconds == timing.lead_time_seconds
    assert timing.timing_hash == canonical_hash(timing.to_data())
    assert _report(
        timing_evidence_hash=timing.timing_hash,
        decision_lead_time_seconds=timing.lead_time_seconds,
    ).decision_lead_time_seconds == 172_800

    over_limit = PromotionTimingEvidenceV2(
        timing_id="regulation-turnaround-over-limit",
        measurement_status="test_fixed",
        t0="2026-07-01T00:00:00Z",
        t_decision="2026-07-03T00:00:01Z",
        compute_seconds=1,
        manual_seconds=0,
        external_wait_seconds=0,
    )
    assert over_limit.lead_time_seconds == 172_801
    with pytest.raises(PromotionReportingError, match="48-hour gate"):
        _report(
            timing_evidence_hash=over_limit.timing_hash,
            decision_lead_time_seconds=over_limit.lead_time_seconds,
            timing_evidence=over_limit,
        )

    with pytest.raises(PromotionReportingError, match="whole-second precision"):
        PromotionTimingEvidenceV2(
            timing_id="regulation-turnaround-fractional-over-limit",
            measurement_status="test_fixed",
            t0="2026-07-01T00:00:00+00:00",
            t_decision="2026-07-03T00:00:00.500000+00:00",
            compute_seconds=1,
            manual_seconds=0,
            external_wait_seconds=0,
        )


@pytest.mark.parametrize(
    "timing_kwargs",
    [
        {"measurement_status": "estimated"},
        {"t0": "2026-07-01T00:00:00"},
        {"t_decision": "2026-06-30T23:59:59+00:00"},
        {"compute_seconds": -1},
        {"manual_seconds": True},
        {
            "t_decision": "2026-07-01T00:00:01+00:00",
            "compute_seconds": 2,
            "manual_seconds": 0,
            "external_wait_seconds": 0,
        },
    ],
)
def test_timing_rejects_invalid_measurement_evidence(
    timing_kwargs: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "timing_id": "invalid-timing",
        "measurement_status": "test_fixed",
        "t0": "2026-07-01T00:00:00+00:00",
        "t_decision": "2026-07-01T01:00:00+00:00",
        "compute_seconds": 1,
        "manual_seconds": 0,
        "external_wait_seconds": 0,
    }
    values.update(timing_kwargs)

    with pytest.raises(PromotionReportingError):
        PromotionTimingEvidenceV2(**values)


@pytest.mark.parametrize(
    ("scope", "overrides", "message"),
    [
        ("test_authoritative", {"champions_candidate": True}, "candidate flag"),
        ("production_champions", {"champions_candidate": False}, "candidate flag"),
        ("test_authoritative", {"status": "production_candidate"}, "invalid status"),
        ("test_authoritative", {"promotion_gate_passed": False}, "invalid status"),
        (
            "test_authoritative",
            {"champions_fidelity_status": "evidence_attested"},
            "fidelity status",
        ),
        (
            "production_champions",
            {"champions_fidelity_status": "not_attested"},
            "fidelity status",
        ),
        ("test_authoritative", {"rank1_equivalence_status": "measured"}, "rank-1"),
        ("test_authoritative", {"external_holdout_novel_gap_count": 1}, "zero"),
        ("test_authoritative", {"silent_fallback_count": 1}, "zero"),
        (
            "test_authoritative",
            {"decision_lead_time_seconds": 172_801},
            "timing hash/lead",
        ),
        (
            "test_authoritative",
            {"decision_lead_time_seconds": True},
            "timing hash/lead",
        ),
        ("test_authoritative", {"blockers": ("blocked",)}, "cannot contain"),
        ("test_authoritative", {"resume_conditions": ("retry",)}, "cannot contain"),
    ],
)
def test_positive_report_rejects_promotion_claim_mutations(
    scope: str,
    overrides: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(PromotionReportingError, match=message):
        _report(scope, **overrides)


def test_report_rejects_forged_content_identity() -> None:
    report = _report()

    with pytest.raises(PromotionReportingError, match="content-derived"):
        replace(report, report_id="promotion-report-" + "0" * 64)


@pytest.mark.parametrize(
    "document_kwargs",
    [
        {"file_name": "nested/report.json"},
        {"file_name": "nested\\report.json"},
        {"file_name": ""},
        {"sha256": "0" * 63},
        {"byte_count": -1},
        {"byte_count": True},
    ],
)
def test_document_digest_rejects_invalid_values(
    document_kwargs: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "file_name": "report.json",
        "sha256": _sha("report-document"),
        "byte_count": 1,
    }
    values.update(document_kwargs)

    with pytest.raises(PromotionReportingError):
        PromotionDocumentDigestV2(**values)


def test_report_rejects_unsorted_or_duplicate_document_names() -> None:
    first = PromotionDocumentDigestV2("a.json", _sha("a"), 1)
    second = PromotionDocumentDigestV2("b.json", _sha("b"), 2)
    duplicate = PromotionDocumentDigestV2("a.json", _sha("a-duplicate"), 3)

    with pytest.raises(PromotionReportingError, match="unique and sorted"):
        _report(documents=(second, first))
    with pytest.raises(PromotionReportingError, match="unique and sorted"):
        _report(documents=(first, duplicate))


def _add_root_property(document: dict[str, Any]) -> None:
    document["unexpected"] = True


def _add_component_property(document: dict[str, Any]) -> None:
    document["component_hashes"]["unexpected_hash"] = _sha("unexpected")


def _remove_metric(document: dict[str, Any]) -> None:
    del document["metrics"]["engine_probe_pass_rate"]


def _change_metric_identity(document: dict[str, Any]) -> None:
    document["metrics"]["verified_target_mapping_rate"]["metric_id"] = "wrong"


def _change_test_scope_status(document: dict[str, Any]) -> None:
    document["status"] = "production_candidate"


def _change_rate(document: dict[str, Any]) -> None:
    document["metrics"]["engine_probe_pass_rate"]["rate_ppm"] = 999_999


def _exceed_lead_time(document: dict[str, Any]) -> None:
    document["decision_lead_time_seconds"] = 172_801


def _remove_timing_evidence(document: dict[str, Any]) -> None:
    del document["timing_evidence"]


def _change_test_scope_timing_status(document: dict[str, Any]) -> None:
    document["timing_evidence"]["measurement_status"] = "measured"


def _add_timing_property(document: dict[str, Any]) -> None:
    document["timing_evidence"]["estimated"] = True


def _remove_timing_timezone(document: dict[str, Any]) -> None:
    document["timing_evidence"]["t0"] = "2026-07-01T00:00:00"


def _add_fractional_timing_precision(document: dict[str, Any]) -> None:
    document["timing_evidence"]["t_decision"] = (
        "2026-07-03T00:00:00.500000+00:00"
    )


def _exceed_nested_timing_lead(document: dict[str, Any]) -> None:
    document["timing_evidence"]["lead_time_seconds"] = 172_801


def _make_document_path(document: dict[str, Any]) -> None:
    document["documents"][0]["file_name"] = "nested/report.json"


@pytest.mark.parametrize(
    "mutation",
    [
        _add_root_property,
        _add_component_property,
        _remove_metric,
        _change_metric_identity,
        _change_test_scope_status,
        _change_rate,
        _exceed_lead_time,
        _remove_timing_evidence,
        _change_test_scope_timing_status,
        _add_timing_property,
        _remove_timing_timezone,
        _add_fractional_timing_precision,
        _exceed_nested_timing_lead,
        _make_document_path,
    ],
)
def test_strict_schema_rejects_serialized_contract_mutations(
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    document = deepcopy(_report().to_data())
    mutation(document)

    with pytest.raises(BundleValidationError):
        validate_document_contract(
            document,
            _schema(),
            "mutated SIM-02B production promotion report",
            fail_on_unknown_keywords=True,
        )
