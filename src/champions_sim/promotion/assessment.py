"""Negative-only SIM-02B assessment for the frozen v1 diagnostic compiler.

The v1 source-to-capability compiler cannot create a production Catalog,
finalize the capability denominator, or issue readiness.  This module keeps
that boundary explicit: it validates the complete v1 compilation, translates
its evidence gaps into structured restart conditions, and emits an exact
``NO-GO`` assessment.  It never converts v1 data into a v2 promotion input.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from champions_sim.capabilities import MappingResolutionStatus, VerificationStatus
from champions_sim.compiler.bundle import COMPILER_ID, SourceToCapabilityCompilation
from champions_sim.core import canonical_hash, canonical_json
from champions_sim.env.readiness import (
    ChampionsReadinessError,
    validate_v1_diagnostic_compilation,
)


ASSESSMENT_SCHEMA_VERSION = "2.0.0"
ASSESSMENT_KIND = "v1_diagnostic_no_go"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")
_V1_SOURCE_POLICY = {
    "license_status": "unverified",
    "access_scope": "local_only",
    "redistribution": "prohibited",
}


class PromotionAssessmentError(ValueError):
    """The supplied object cannot support an exact negative assessment."""


@dataclass(frozen=True, slots=True)
class PromotionBlockerV2:
    """One evidence gap and its explicit restart condition."""

    stage: str
    code: str
    subject: str
    evidence_required: str
    restart_condition: str

    def __post_init__(self) -> None:
        if _TOKEN.fullmatch(self.stage) is None:
            raise PromotionAssessmentError("blocker stage must be a stable token")
        if _TOKEN.fullmatch(self.code) is None:
            raise PromotionAssessmentError("blocker code must be a stable token")
        for value, label in (
            (self.subject, "subject"),
            (self.evidence_required, "evidence_required"),
            (self.restart_condition, "restart_condition"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise PromotionAssessmentError(f"blocker {label} must be non-empty")

    def to_data(self) -> dict[str, str]:
        return {
            "stage": self.stage,
            "code": self.code,
            "subject": self.subject,
            "evidence_required": self.evidence_required,
            "restart_condition": self.restart_condition,
        }

    @property
    def sort_key(self) -> tuple[str, str, str, str, str]:
        return (
            self.stage,
            self.code,
            self.subject,
            self.evidence_required,
            self.restart_condition,
        )


@dataclass(frozen=True, slots=True)
class ProductionPromotionAssessmentV2:
    """Content-bound v2 ``NO-GO`` derived from a validated v1 diagnostic."""

    schema_version: str
    assessment_id: str
    assessment_kind: str
    source_compiler_id: str
    source_report_hash: str
    diagnostic_artifact_manifest_hash: str
    target_pool_hash: str
    catalog_hash: str
    ruleset_hash: str
    target_capability_set_hash: str
    source_license_status: str
    source_access_scope: str
    source_redistribution: str
    status: str
    promotion_candidate: bool
    denominator_final: bool
    catalog_emit_eligible: bool
    verified_target_mapping_numerator: int
    verified_target_mapping_denominator: int
    verified_target_mapping_rate_ppm: int
    development_scenario_coverage_numerator: None
    development_scenario_coverage_denominator: None
    development_scenario_coverage_rate_ppm: None
    verified_grounding_conformance_numerator: None
    verified_grounding_conformance_denominator: None
    verified_grounding_conformance_rate_ppm: None
    engine_probe_pass_numerator: None
    engine_probe_pass_denominator: None
    engine_probe_pass_rate_ppm: None
    external_holdout_novel_gap_count: None
    silent_fallback_count: int
    readiness_seal_hash: None
    blockers: tuple[PromotionBlockerV2, ...]

    def __post_init__(self) -> None:
        if self.schema_version != ASSESSMENT_SCHEMA_VERSION:
            raise PromotionAssessmentError("unsupported assessment schema_version")
        if self.assessment_kind != ASSESSMENT_KIND:
            raise PromotionAssessmentError("unsupported assessment kind")
        if self.source_compiler_id != COMPILER_ID:
            raise PromotionAssessmentError("assessment requires the frozen v1 compiler")
        for value, label in (
            (self.source_report_hash, "source_report_hash"),
            (self.diagnostic_artifact_manifest_hash, "artifact manifest hash"),
            (self.target_pool_hash, "target_pool_hash"),
            (self.catalog_hash, "catalog_hash"),
            (self.ruleset_hash, "ruleset_hash"),
            (self.target_capability_set_hash, "target_capability_set_hash"),
        ):
            if _SHA256.fullmatch(value) is None:
                raise PromotionAssessmentError(f"{label} must be a lowercase SHA-256")
        if self.assessment_id != f"production-assessment-v2:{self.source_report_hash}":
            raise PromotionAssessmentError("assessment ID must bind the v1 report")
        if (
            self.source_license_status,
            self.source_access_scope,
            self.source_redistribution,
        ) != ("unverified", "local_only", "prohibited"):
            raise PromotionAssessmentError("v1 source policy cannot be promoted")
        if (
            self.status != "no_go"
            or self.promotion_candidate
            or self.denominator_final
            or self.catalog_emit_eligible
            or self.readiness_seal_hash is not None
        ):
            raise PromotionAssessmentError("v1 assessment must remain an unsealed NO-GO")
        if self.verified_target_mapping_denominator <= 0:
            raise PromotionAssessmentError("target mapping denominator must be positive")
        if (
            self.verified_target_mapping_numerator != 0
            or self.verified_target_mapping_rate_ppm != 0
        ):
            raise PromotionAssessmentError(
                "v1 diagnostic cannot contribute a verified mapping numerator"
            )
        undefined_metrics = (
            self.development_scenario_coverage_numerator,
            self.development_scenario_coverage_denominator,
            self.development_scenario_coverage_rate_ppm,
            self.verified_grounding_conformance_numerator,
            self.verified_grounding_conformance_denominator,
            self.verified_grounding_conformance_rate_ppm,
            self.engine_probe_pass_numerator,
            self.engine_probe_pass_denominator,
            self.engine_probe_pass_rate_ppm,
            self.external_holdout_novel_gap_count,
        )
        if any(value is not None for value in undefined_metrics):
            raise PromotionAssessmentError(
                "non-final v1 evidence cannot publish promotion rates or holdout gaps"
            )
        if self.silent_fallback_count < 0:
            raise PromotionAssessmentError("silent fallback count cannot be negative")
        if not self.blockers or any(
            type(value) is not PromotionBlockerV2 for value in self.blockers
        ):
            raise PromotionAssessmentError("assessment requires exact structured blockers")
        keys = tuple(value.sort_key for value in self.blockers)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise PromotionAssessmentError("assessment blockers must be unique and sorted")

    def unsigned_data(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "assessment_kind": self.assessment_kind,
            "source_compiler_id": self.source_compiler_id,
            "source_report_hash": self.source_report_hash,
            "diagnostic_artifact_manifest_hash": self.diagnostic_artifact_manifest_hash,
            "target_pool_hash": self.target_pool_hash,
            "catalog_hash": self.catalog_hash,
            "ruleset_hash": self.ruleset_hash,
            "target_capability_set_hash": self.target_capability_set_hash,
            "source_policy": {
                "license_status": self.source_license_status,
                "access_scope": self.source_access_scope,
                "redistribution": self.source_redistribution,
            },
            "status": self.status,
            "promotion_candidate": self.promotion_candidate,
            "denominator_final": self.denominator_final,
            "catalog_emit_eligible": self.catalog_emit_eligible,
            "verified_target_mapping": {
                "numerator": self.verified_target_mapping_numerator,
                "denominator": self.verified_target_mapping_denominator,
                "rate_ppm": self.verified_target_mapping_rate_ppm,
            },
            "development_scenario_coverage": {
                "numerator": self.development_scenario_coverage_numerator,
                "denominator": self.development_scenario_coverage_denominator,
                "rate_ppm": self.development_scenario_coverage_rate_ppm,
            },
            "verified_grounding_conformance": {
                "numerator": self.verified_grounding_conformance_numerator,
                "denominator": self.verified_grounding_conformance_denominator,
                "rate_ppm": self.verified_grounding_conformance_rate_ppm,
            },
            "engine_probe_pass": {
                "numerator": self.engine_probe_pass_numerator,
                "denominator": self.engine_probe_pass_denominator,
                "rate_ppm": self.engine_probe_pass_rate_ppm,
            },
            "external_holdout_novel_gap_count": self.external_holdout_novel_gap_count,
            "silent_fallback_count": self.silent_fallback_count,
            "readiness_seal_hash": self.readiness_seal_hash,
            "blockers": [value.to_data() for value in self.blockers],
        }

    @property
    def assessment_hash(self) -> str:
        return canonical_hash(self.unsigned_data())

    def to_data(self) -> dict[str, Any]:
        return {**self.unsigned_data(), "assessment_hash": self.assessment_hash}

    def to_json(self) -> str:
        return canonical_json(self.to_data())


def build_production_promotion_assessment_v2(
    compilation: SourceToCapabilityCompilation,
) -> ProductionPromotionAssessmentV2:
    """Validate v1 substance and return a deterministic, unsealed ``NO-GO``.

    The function intentionally has no positive branch.  Supplying new evidence
    requires the separate production-v2 compiler and cannot mutate or extend
    this assessment into a candidate.
    """

    try:
        report, artifacts = validate_v1_diagnostic_compilation(compilation)
    except ChampionsReadinessError as error:
        raise PromotionAssessmentError(
            f"v1 diagnostic compilation validation failed: {error}"
        ) from error

    source_policy = report.get("source_policy")
    if source_policy != _V1_SOURCE_POLICY:
        raise PromotionAssessmentError("v1 diagnostic source policy is not exact")
    if (
        report.get("status") != "no_go"
        or report.get("candidate_ready") is not False
        or report.get("denominator_final") is not False
        or compilation.bridge.catalog_input.denominator_final
        or compilation.bridge.catalog_input.catalog_emit_eligible
        or compilation.capability_set.denominator_final
        or compilation.matrix.candidate_ready
    ):
        raise PromotionAssessmentError("v1 diagnostic attempted a promotion state")

    entries = compilation.bridge.mapping_evidence.entries
    verified_mapping_count = sum(
        value.resolution_status is MappingResolutionStatus.RESOLVED
        and value.verification_status is VerificationStatus.VERIFIED
        for value in entries
    )
    if verified_mapping_count != 0:
        raise PromotionAssessmentError(
            "v1 diagnostic cannot supply verified production mappings"
        )
    if any(
        value.verification_status is VerificationStatus.VERIFIED
        for value in compilation.bridge.catalog_input.members
    ) or any(
        value.verification_status is VerificationStatus.VERIFIED
        for value in compilation.bridge.catalog_input.records
    ):
        raise PromotionAssessmentError(
            "v1 Catalog input cannot supply verified production evidence"
        )

    report_hash = str(report["report_hash"])
    raw_reasons = report.get("blocking_reasons")
    if not isinstance(raw_reasons, list) or not raw_reasons or any(
        not isinstance(value, str) or not value for value in raw_reasons
    ):
        raise PromotionAssessmentError("v1 diagnostic blocking reasons are missing")
    blockers = {
        _blocker_from_reason(value)
        for value in raw_reasons
    }
    blockers.add(
        PromotionBlockerV2(
            stage="readiness",
            code="v1_diagnostic_not_promotion_input",
            subject=report_hash,
            evidence_required=(
                "resolver-backed v2 source, license, artifact, mapping, scenario, "
                "grounding, probe, and sealed-holdout evidence"
            ),
            restart_condition=(
                "compile the evidence through the separate production-v2 path; "
                "do not mutate or convert the v1 diagnostic"
            ),
        )
    )
    blockers.add(
        PromotionBlockerV2(
            stage="source",
            code="production_trust_anchor_missing",
            subject="production-promotion-v2",
            evidence_required=(
                "an artifact-root-external trusted issuer/authority attestation "
                "that pins the approved source manifest and license identities"
            ),
            restart_condition=(
                "implement and configure the external trust-anchor verifier; "
                "local authority or verified strings are not sufficient"
            ),
        )
    )
    ordered_blockers = tuple(sorted(blockers, key=lambda value: value.sort_key))

    return ProductionPromotionAssessmentV2(
        schema_version=ASSESSMENT_SCHEMA_VERSION,
        assessment_id=f"production-assessment-v2:{report_hash}",
        assessment_kind=ASSESSMENT_KIND,
        source_compiler_id=COMPILER_ID,
        source_report_hash=report_hash,
        diagnostic_artifact_manifest_hash=canonical_hash(artifacts),
        target_pool_hash=compilation.bridge.mapping_evidence.target_pool_hash,
        catalog_hash=compilation.catalog.snapshot_hash,
        ruleset_hash=compilation.ruleset.snapshot_hash,
        target_capability_set_hash=compilation.capability_set.capability_set_hash,
        source_license_status="unverified",
        source_access_scope="local_only",
        source_redistribution="prohibited",
        status="no_go",
        promotion_candidate=False,
        denominator_final=False,
        catalog_emit_eligible=False,
        verified_target_mapping_numerator=0,
        verified_target_mapping_denominator=len(entries),
        verified_target_mapping_rate_ppm=0,
        development_scenario_coverage_numerator=None,
        development_scenario_coverage_denominator=None,
        development_scenario_coverage_rate_ppm=None,
        verified_grounding_conformance_numerator=None,
        verified_grounding_conformance_denominator=None,
        verified_grounding_conformance_rate_ppm=None,
        engine_probe_pass_numerator=None,
        engine_probe_pass_denominator=None,
        engine_probe_pass_rate_ppm=None,
        external_holdout_novel_gap_count=None,
        silent_fallback_count=compilation.probe_report.silent_fallback_count,
        readiness_seal_hash=None,
        blockers=ordered_blockers,
    )


def _blocker_from_reason(reason: str) -> PromotionBlockerV2:
    parts = reason.split(":")
    prefix = parts[0]
    if prefix == "manifest_blocker" and len(parts) > 1:
        detail = parts[1]
        code = f"manifest_blocker.{detail}"
        subject = ":".join(parts[2:]) or "global"
        guidance_key = detail
    else:
        code = prefix
        subject = ":".join(parts[1:]) or "global"
        guidance_key = prefix
    stage, evidence, restart = _guidance(guidance_key)
    return PromotionBlockerV2(
        stage=stage,
        code=code,
        subject=subject,
        evidence_required=evidence,
        restart_condition=restart,
    )


def _guidance(code: str) -> tuple[str, str, str]:
    if code in {"mapping_unresolved", "mapping_conflict", "unmapped_target"}:
        return (
            "mapping",
            "authoritative namespace-bound target-to-Catalog mapping evidence",
            "resolve and verify the exact target member without shrinking the pool",
        )
    if code == "restricted_source":
        return (
            "source",
            "resolver-verified source, license/use-policy record, and artifact bytes",
            "replace or verify the restricted source through the v2 resolver",
        )
    if code == "catalog_not_emit_eligible":
        return (
            "catalog",
            "verified Catalog records and an emit-eligible v2 compilation",
            "compile verified records through v2 instead of changing the v1 flag",
        )
    if code == "construction_corpus_missing":
        return (
            "scenario",
            "non-empty lineage-bound development scenario corpus",
            "supply executable development scenarios before rebuilding the denominator",
        )
    if code == "capability_denominator_not_final":
        return (
            "capability",
            "an exact non-empty capability set with no unresolved requirements",
            "resolve every mapping and semantic gap, then recompute the full closure",
        )
    if code == "semantic_unsupported_selector_count":
        return (
            "semantic",
            "authoritative structured semantics for every declared selector",
            "implement and verify each selector without a default or no-op fallback",
        )
    if code == "execution_gap_count":
        return (
            "engine_probe",
            "verified positive engine probe and Replay for every declared capability",
            "implement the missing executors and rerun capability-specific probes",
        )
    if code == "grounding_assertion_corpus_missing":
        return (
            "grounding",
            "resolver-validated grounding assertions for every required boundary",
            "supply source- or trace-backed assertions and rerun grounding resolution",
        )
    if code == "external_holdout_missing":
        return (
            "holdout",
            "sealed external holdout with lineage separated from development",
            "seal and evaluate the independent holdout before candidate assessment",
        )
    return (
        "diagnostic",
        "resolver-backed evidence that directly resolves the v1 diagnostic reason",
        "resolve the reason in production-v2 inputs and regenerate the assessment",
    )
