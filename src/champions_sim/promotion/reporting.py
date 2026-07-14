"""Exact, content-addressed SIM-02B promotion report contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from champions_sim.core import canonical_hash, canonical_json


PROMOTION_REPORT_SCHEMA_VERSION = "2.0.0"
PROMOTION_COMPILER_ID = "production-promotion-v2"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")
_SCOPES = {"test_authoritative", "production_champions"}


class PromotionReportingError(ValueError):
    """A promotion metric, timing record, or report is not self-consistent."""


def _sha(value: str, label: str) -> None:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise PromotionReportingError(f"{label} must be a lowercase SHA-256")


def _stable(value: str, label: str) -> None:
    if type(value) is not str or _STABLE_ID.fullmatch(value) is None:
        raise PromotionReportingError(f"{label} must be a stable ID")


@dataclass(frozen=True, slots=True)
class ExactRateV2:
    metric_id: str
    numerator: int
    denominator: int
    rate_ppm: int
    denominator_binding_hash: str

    def __post_init__(self) -> None:
        _stable(self.metric_id, "metric_id")
        if (
            type(self.numerator) is not int
            or type(self.denominator) is not int
            or type(self.rate_ppm) is not int
            or self.denominator <= 0
            or not 0 <= self.numerator <= self.denominator
        ):
            raise PromotionReportingError("rate counts require an exact positive denominator")
        if self.rate_ppm != self.numerator * 1_000_000 // self.denominator:
            raise PromotionReportingError("rate_ppm differs from its exact counts")
        _sha(self.denominator_binding_hash, "denominator_binding_hash")

    def to_data(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "rate_ppm": self.rate_ppm,
            "denominator_binding_hash": self.denominator_binding_hash,
        }


@dataclass(frozen=True, slots=True)
class PromotionTimingEvidenceV2:
    timing_id: str
    measurement_status: str
    t0: str
    t_decision: str
    compute_seconds: int
    manual_seconds: int
    external_wait_seconds: int

    def __post_init__(self) -> None:
        _stable(self.timing_id, "timing_id")
        if self.measurement_status not in {"test_fixed", "measured"}:
            raise PromotionReportingError("unsupported timing measurement_status")
        start = _timestamp(self.t0, "t0")
        decision = _timestamp(self.t_decision, "t_decision")
        if decision < start:
            raise PromotionReportingError("t_decision precedes t0")
        if start.microsecond != 0 or decision.microsecond != 0:
            raise PromotionReportingError(
                "promotion timing timestamps require whole-second precision"
            )
        for value, label in (
            (self.compute_seconds, "compute_seconds"),
            (self.manual_seconds, "manual_seconds"),
            (self.external_wait_seconds, "external_wait_seconds"),
        ):
            if type(value) is not int or value < 0:
                raise PromotionReportingError(f"{label} must be a non-negative integer")
        if self.accounted_seconds > self.lead_time_seconds:
            raise PromotionReportingError("accounted timing exceeds elapsed lead time")

    @property
    def lead_time_seconds(self) -> int:
        return int((_timestamp(self.t_decision, "t_decision") - _timestamp(self.t0, "t0")).total_seconds())

    @property
    def accounted_seconds(self) -> int:
        return self.compute_seconds + self.manual_seconds + self.external_wait_seconds

    @property
    def timing_hash(self) -> str:
        return canonical_hash(self.to_data())

    def to_data(self) -> dict[str, Any]:
        return {
            "timing_id": self.timing_id,
            "measurement_status": self.measurement_status,
            "t0": self.t0,
            "t_decision": self.t_decision,
            "compute_seconds": self.compute_seconds,
            "manual_seconds": self.manual_seconds,
            "external_wait_seconds": self.external_wait_seconds,
            "lead_time_seconds": self.lead_time_seconds,
        }


def _timestamp(value: str, label: str) -> datetime:
    if type(value) is not str:
        raise PromotionReportingError(f"{label} must be an ISO-8601 string")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PromotionReportingError(f"{label} must be an ISO-8601 timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise PromotionReportingError(f"{label} must include a timezone")
    return result


@dataclass(frozen=True, slots=True)
class PromotionDocumentDigestV2:
    file_name: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        if (
            type(self.file_name) is not str
            or not self.file_name
            or "/" in self.file_name
            or "\\" in self.file_name
        ):
            raise PromotionReportingError("promotion document name must be a basename")
        _sha(self.sha256, "document sha256")
        if type(self.byte_count) is not int or self.byte_count < 0:
            raise PromotionReportingError("document byte_count must be non-negative")

    def to_data(self) -> dict[str, Any]:
        return {
            "file_name": self.file_name,
            "sha256": self.sha256,
            "byte_count": self.byte_count,
        }


@dataclass(frozen=True, slots=True)
class ProductionPromotionReportV2:
    schema_version: str
    report_id: str
    compiler_id: str
    attestation_scope: str
    status: str
    promotion_gate_passed: bool
    champions_candidate: bool
    champions_fidelity_status: str
    rank1_equivalence_status: str
    regulation_id: str
    regulation_revision: str
    source_resolution_set_hash: str
    artifact_binding_hash: str
    regulation_hash: str
    target_pool_hash: str
    catalog_hash: str
    ruleset_hash: str
    mapping_evidence_hash: str
    target_pool_manifest_hash: str
    semantic_compilation_hash: str
    target_capability_set_hash: str
    execution_compilation_hash: str
    construction_corpus_hash: str
    scenario_corpus_hash: str
    external_holdout_scenario_corpus_hash: str
    partition_manifest_hash: str
    external_holdout_hash: str
    grounding_resolution_hash: str
    engine_probe_report_hash: str
    mechanic_coverage_matrix_hash: str
    timing_evidence_hash: str
    timing_evidence: PromotionTimingEvidenceV2
    verified_target_mapping_rate: ExactRateV2
    development_scenario_coverage_rate: ExactRateV2
    verified_grounding_conformance_rate: ExactRateV2
    engine_probe_pass_rate: ExactRateV2
    external_holdout_novel_gap_count: int
    silent_fallback_count: int
    decision_lead_time_seconds: int
    blockers: tuple[str, ...]
    resume_conditions: tuple[str, ...]
    documents: tuple[PromotionDocumentDigestV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != PROMOTION_REPORT_SCHEMA_VERSION:
            raise PromotionReportingError("unsupported promotion report schema_version")
        if self.compiler_id != PROMOTION_COMPILER_ID:
            raise PromotionReportingError("unsupported promotion compiler identity")
        if self.attestation_scope not in _SCOPES:
            raise PromotionReportingError("unsupported attestation_scope")
        _stable(self.regulation_id, "regulation_id")
        _stable(self.regulation_revision, "regulation_revision")
        for value, label in self._hash_fields():
            _sha(value, label)
        if any(type(value) is not ExactRateV2 for value in self._rates()):
            raise PromotionReportingError("report rates require exact ExactRateV2 values")
        for rate in self._rates():
            rate.__post_init__()
            if rate.rate_ppm != 1_000_000:
                raise PromotionReportingError("promotion compilation requires every rate at 1.0")
        expected_rate_ids = (
            "verified_target_mapping_rate",
            "development_scenario_coverage_rate",
            "verified_grounding_conformance_rate",
            "engine_probe_pass_rate",
        )
        if tuple(rate.metric_id for rate in self._rates()) != expected_rate_ids:
            raise PromotionReportingError("promotion rate slots require their exact metric IDs")
        expected_rate_bindings = (
            exact_rate_binding_hash_v2(
                expected_rate_ids[0],
                self.verified_target_mapping_rate.numerator,
                self.verified_target_mapping_rate.denominator,
                self.target_pool_hash,
            ),
            exact_rate_binding_hash_v2(
                expected_rate_ids[1],
                self.development_scenario_coverage_rate.numerator,
                self.development_scenario_coverage_rate.denominator,
                self.target_capability_set_hash,
                self.partition_manifest_hash,
            ),
            exact_rate_binding_hash_v2(
                expected_rate_ids[2],
                self.verified_grounding_conformance_rate.numerator,
                self.verified_grounding_conformance_rate.denominator,
                self.target_capability_set_hash,
                self.partition_manifest_hash,
                self.grounding_resolution_hash,
            ),
            exact_rate_binding_hash_v2(
                expected_rate_ids[3],
                self.engine_probe_pass_rate.numerator,
                self.engine_probe_pass_rate.denominator,
                self.target_capability_set_hash,
                self.partition_manifest_hash,
                self.engine_probe_report_hash,
            ),
        )
        if tuple(rate.denominator_binding_hash for rate in self._rates()) != expected_rate_bindings:
            raise PromotionReportingError("promotion rate denominator binding differs")
        if type(self.timing_evidence) is not PromotionTimingEvidenceV2:
            raise PromotionReportingError("report requires exact timing evidence")
        self.timing_evidence.__post_init__()
        if (
            self.timing_evidence_hash != self.timing_evidence.timing_hash
            or self.decision_lead_time_seconds != self.timing_evidence.lead_time_seconds
        ):
            raise PromotionReportingError("timing hash/lead differs from timing evidence")
        if (
            self.attestation_scope == "test_authoritative"
            and self.timing_evidence.measurement_status != "test_fixed"
        ) or (
            self.attestation_scope == "production_champions"
            and self.timing_evidence.measurement_status != "measured"
        ):
            raise PromotionReportingError("timing measurement status differs from scope")
        expected_status = (
            "engineering_candidate"
            if self.attestation_scope == "test_authoritative"
            else "production_candidate"
        )
        if self.status != expected_status or self.promotion_gate_passed is not True:
            raise PromotionReportingError("positive compilation has an invalid status")
        expected_champions = self.attestation_scope == "production_champions"
        if self.champions_candidate is not expected_champions:
            raise PromotionReportingError("Champions candidate flag differs from scope")
        expected_fidelity = "not_attested" if not expected_champions else "evidence_attested"
        if self.champions_fidelity_status != expected_fidelity:
            raise PromotionReportingError("Champions fidelity status differs from scope")
        if self.rank1_equivalence_status != "unmeasured":
            raise PromotionReportingError("SIM-02B cannot claim rank-1 equivalence")
        if (
            type(self.external_holdout_novel_gap_count) is not int
            or self.external_holdout_novel_gap_count != 0
            or type(self.silent_fallback_count) is not int
            or self.silent_fallback_count != 0
        ):
            raise PromotionReportingError("promotion requires zero holdout gaps and fallbacks")
        if (
            type(self.decision_lead_time_seconds) is not int
            or not 0 <= self.decision_lead_time_seconds <= 48 * 60 * 60
        ):
            raise PromotionReportingError("promotion decision exceeds the 48-hour gate")
        if self.blockers or self.resume_conditions:
            raise PromotionReportingError("positive compilation cannot contain blockers")
        if type(self.documents) is not tuple or not self.documents:
            raise PromotionReportingError("promotion report requires document digests")
        if any(type(value) is not PromotionDocumentDigestV2 for value in self.documents):
            raise PromotionReportingError("invalid promotion document digest type")
        for value in self.documents:
            value.__post_init__()
        names = tuple(value.file_name for value in self.documents)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise PromotionReportingError("promotion document digests must be unique and sorted")
        if self.report_id != _report_id(self):
            raise PromotionReportingError("promotion report_id is not content-derived")

    def _hash_fields(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (getattr(self, name), name)
            for name in (
                "source_resolution_set_hash", "artifact_binding_hash",
                "regulation_hash", "target_pool_hash", "catalog_hash",
                "ruleset_hash", "mapping_evidence_hash",
                "target_pool_manifest_hash", "semantic_compilation_hash",
                "target_capability_set_hash", "execution_compilation_hash",
                "construction_corpus_hash", "scenario_corpus_hash",
                "external_holdout_scenario_corpus_hash", "partition_manifest_hash",
                "external_holdout_hash", "grounding_resolution_hash",
                "engine_probe_report_hash", "mechanic_coverage_matrix_hash",
                "timing_evidence_hash",
            )
        )

    def _rates(self) -> tuple[ExactRateV2, ...]:
        return (
            self.verified_target_mapping_rate,
            self.development_scenario_coverage_rate,
            self.verified_grounding_conformance_rate,
            self.engine_probe_pass_rate,
        )

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "compiler_id": self.compiler_id,
            "attestation_scope": self.attestation_scope,
            "status": self.status,
            "promotion_gate_passed": self.promotion_gate_passed,
            "champions_candidate": self.champions_candidate,
            "champions_fidelity_status": self.champions_fidelity_status,
            "rank1_equivalence_status": self.rank1_equivalence_status,
            "regulation_id": self.regulation_id,
            "regulation_revision": self.regulation_revision,
            "component_hashes": {name: value for value, name in self._hash_fields()},
            "metrics": {
                rate.metric_id: rate.to_data() for rate in self._rates()
            },
            "external_holdout_novel_gap_count": self.external_holdout_novel_gap_count,
            "silent_fallback_count": self.silent_fallback_count,
            "decision_lead_time_seconds": self.decision_lead_time_seconds,
            "timing_evidence": self.timing_evidence.to_data(),
            "blockers": list(self.blockers),
            "resume_conditions": list(self.resume_conditions),
            "documents": [value.to_data() for value in self.documents],
        }

    @property
    def report_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "report_hash": self.report_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


def _report_id(report: ProductionPromotionReportV2) -> str:
    return "promotion-report-" + canonical_hash(
        (
            report.attestation_scope,
            report.source_resolution_set_hash,
            report.target_pool_hash,
            report.target_capability_set_hash,
            report.partition_manifest_hash,
            report.engine_probe_report_hash,
        )
    )


def production_report_id_v2(
    *,
    attestation_scope: str,
    source_resolution_set_hash: str,
    target_pool_hash: str,
    target_capability_set_hash: str,
    partition_manifest_hash: str,
    engine_probe_report_hash: str,
) -> str:
    """Compute the canonical report ID before constructing its exact model."""

    return "promotion-report-" + canonical_hash(
        (
            attestation_scope,
            source_resolution_set_hash,
            target_pool_hash,
            target_capability_set_hash,
            partition_manifest_hash,
            engine_probe_report_hash,
        )
    )


def exact_rate_binding_hash_v2(
    metric_id: str,
    numerator: int,
    denominator: int,
    *component_hashes: str,
) -> str:
    """Bind an exact rate to its immutable denominator and evidence lineage."""

    _stable(metric_id, "metric_id")
    if (
        type(numerator) is not int
        or type(denominator) is not int
        or denominator <= 0
        or not 0 <= numerator <= denominator
    ):
        raise PromotionReportingError("rate binding requires exact valid counts")
    if not component_hashes:
        raise PromotionReportingError("rate binding requires component hashes")
    for index, value in enumerate(component_hashes):
        _sha(value, f"component_hashes[{index}]")
    return canonical_hash((metric_id, numerator, denominator, component_hashes))


__all__ = [
    "PROMOTION_COMPILER_ID",
    "PROMOTION_REPORT_SCHEMA_VERSION",
    "ExactRateV2",
    "ProductionPromotionReportV2",
    "PromotionDocumentDigestV2",
    "PromotionReportingError",
    "PromotionTimingEvidenceV2",
    "exact_rate_binding_hash_v2",
    "production_report_id_v2",
]
