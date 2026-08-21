"""Resolver gates from plan-bound traces to complete grounding coverage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from champions_sim.core import canonical_json

from .android_client import AndroidClientBuild
from .expectations import ResolvedGroundingExpectations
from .models import ConformanceVerdict
from .plan import (
    GroundingEvidenceMethod,
    GroundingPlanError,
    ResolvedGroundingPlan,
    ValidatedGroundingPlanPair,
)
from .seal import VerifiedGroundingPlanSeal
from .validation import ValidatedGroundingTrace


class GroundingCoverageError(ValueError):
    """Raised when a plan requirement lacks correctly bound conformant evidence."""


_BINDING_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedGroundingRequirementEvidence:
    requirement_id: str
    trace_id: str
    trace_hash: str
    evidence_artifact_ids: frozenset[str]
    validated_trace: ValidatedGroundingTrace

    def __init__(
        self,
        *,
        requirement_id: str,
        trace_id: str,
        trace_hash: str,
        evidence_artifact_ids: frozenset[str],
        validated_trace: ValidatedGroundingTrace,
        _token: object | None = None,
    ) -> None:
        if _token is not _BINDING_TOKEN:
            raise GroundingCoverageError(
                "grounding evidence binding must be created by the resolver"
            )
        object.__setattr__(self, "requirement_id", requirement_id)
        object.__setattr__(self, "trace_id", trace_id)
        object.__setattr__(self, "trace_hash", trace_hash)
        object.__setattr__(self, "evidence_artifact_ids", evidence_artifact_ids)
        object.__setattr__(self, "validated_trace", validated_trace)


def bind_grounding_trace_to_plan(
    validated_trace: ValidatedGroundingTrace,
    resolved_plan: ResolvedGroundingPlan,
    verified_seal: VerifiedGroundingPlanSeal,
    resolved_expectations: ResolvedGroundingExpectations,
) -> ValidatedGroundingRequirementEvidence:
    trace = validated_trace.trace
    plan = resolved_plan.plan
    if resolved_expectations.plan_hash != resolved_plan.plan_hash:
        raise GroundingCoverageError(
            "resolved grounding expectations do not belong to the plan"
        )
    if (
        verified_seal.plan_id != plan.plan_id
        or verified_seal.plan_hash != resolved_plan.plan_hash
        or verified_seal.partition != plan.partition.value
    ):
        raise GroundingCoverageError("GitHub plan seal does not belong to the plan")
    expected_bindings = {
        "plan_id": plan.plan_id,
        "plan_hash": resolved_plan.plan_hash,
        "lineage_receipt_sha256": plan.lineage_receipt_sha256,
        "partition": plan.partition.value,
        "capture_store_id": plan.capture_store_id,
        "format_id": plan.format_id,
    }
    for field_name, expected in expected_bindings.items():
        if getattr(trace, field_name) != expected:
            raise GroundingCoverageError(f"grounding trace {field_name} does not match plan")
    requirement = next(
        (
            value
            for value in plan.requirements
            if value.requirement_id == trace.requirement_id
        ),
        None,
    )
    if requirement is None:
        raise GroundingCoverageError("grounding trace requirement is not in the plan")
    expectation = resolved_expectations.for_requirement(requirement.requirement_id)
    if (
        expectation.expected_source is not requirement.expected_source
        or canonical_json(expectation.expected) != canonical_json(requirement.expected)
        or expectation.replay_hash != requirement.reference_replay_hash
    ):
        raise GroundingCoverageError(
            "grounding requirement differs from its resolved expectation evidence"
        )
    if not validated_trace.promotable:
        raise GroundingCoverageError("grounding trace is not conformant")
    all_checks = [check for frame in trace.frames for check in frame.conformance]
    if any(check.path != requirement.path for check in all_checks):
        raise GroundingCoverageError(
            "grounding trace contains an assertion outside its planned requirement"
        )
    checks = [check for check in all_checks if check.path == requirement.path]
    if not checks or any(check.verdict is not ConformanceVerdict.MATCH for check in checks):
        raise GroundingCoverageError(
            "grounding requirement needs an evidence-backed match at its exact path"
        )
    expected_json = canonical_json(requirement.expected)
    if any(canonical_json(check.expected) != expected_json for check in checks):
        raise GroundingCoverageError("grounding trace expected value differs from the plan")
    if (
        requirement.reference_replay_hash is not None
        and trace.reference_replay_hash != requirement.reference_replay_hash
    ):
        raise GroundingCoverageError("grounding trace Replay hash differs from the plan")
    artifact_ids = frozenset(
        artifact_id for check in checks for artifact_id in check.artifact_ids
    )
    required_artifacts = {
        GroundingEvidenceMethod.SCREENSHOT: frozenset({"screenshot"}),
        GroundingEvidenceMethod.UI_HIERARCHY: frozenset(
            {"ui-hierarchy-before", "ui-hierarchy"}
        ),
        GroundingEvidenceMethod.BOTH: frozenset(
            {"screenshot", "ui-hierarchy-before", "ui-hierarchy"}
        ),
    }[requirement.evidence_method]
    if not any(
        required_artifacts <= frozenset(check.artifact_ids) for check in checks
    ):
        raise GroundingCoverageError("grounding trace lacks the planned evidence method")
    sealed_at = _instant(plan.sealed_at)
    receipt_at = _instant(verified_seal.created_at)
    if receipt_at < sealed_at:
        raise GroundingCoverageError("GitHub plan seal predates the external plan")
    if any(
        _instant(timestamp) < receipt_at
        for binding in validated_trace.capture_bindings
        for timestamp in (
            binding.ui_hierarchy_before_captured_at,
            binding.screenshot_captured_at,
            binding.ui_hierarchy_captured_at,
            binding.captured_at,
        )
    ):
        raise GroundingCoverageError(
            "grounding capture predates the live GitHub denominator seal"
        )
    if any(
        binding.target_package != plan.target_package
        or binding.client_build != plan.client_build
        or binding.lineage_receipt_sha256 != plan.lineage_receipt_sha256
        or binding.capture_store_identity_sha256
        != plan.capture_store_identity_sha256
        for binding in validated_trace.capture_bindings
    ):
        raise GroundingCoverageError(
            "grounding capture target or physical store differs from the sealed plan"
        )
    if any(
        binding.authorization_issue_url != verified_seal.issue_url
        or binding.plan_seal_comment_url != verified_seal.comment_url
        or binding.plan_seal_receipt_sha256 != verified_seal.receipt_sha256
        or _instant(binding.authorization_granted_at) < receipt_at
        for binding in validated_trace.capture_bindings
    ):
        raise GroundingCoverageError(
            "grounding authorization predates or differs from the live plan seal"
        )
    return ValidatedGroundingRequirementEvidence(
        requirement_id=requirement.requirement_id,
        trace_id=trace.trace_id,
        trace_hash=validated_trace.source_trace_hash,
        evidence_artifact_ids=artifact_ids,
        validated_trace=validated_trace,
        _token=_BINDING_TOKEN,
    )


_COVERAGE_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class CompleteGroundingCoverage:
    plan: ResolvedGroundingPlan
    seal: VerifiedGroundingPlanSeal
    expectations: ResolvedGroundingExpectations
    evidence: tuple[ValidatedGroundingRequirementEvidence, ...]
    client_build: AndroidClientBuild
    capture_store_identity_sha256: str
    capture_ids: frozenset[str]
    capture_manifest_sha256: frozenset[str]
    artifact_sha256: frozenset[str]
    authorization_sha256: frozenset[str]
    replay_source_sha256: frozenset[str]

    def __init__(
        self,
        plan: ResolvedGroundingPlan,
        seal: VerifiedGroundingPlanSeal,
        expectations: ResolvedGroundingExpectations,
        evidence: tuple[ValidatedGroundingRequirementEvidence, ...],
        client_build: AndroidClientBuild,
        capture_store_identity_sha256: str,
        capture_ids: frozenset[str],
        capture_manifest_sha256: frozenset[str],
        artifact_sha256: frozenset[str],
        authorization_sha256: frozenset[str],
        replay_source_sha256: frozenset[str],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _COVERAGE_TOKEN:
            raise GroundingCoverageError(
                "complete grounding coverage must be created by the coverage gate"
            )
        object.__setattr__(self, "plan", plan)
        object.__setattr__(self, "seal", seal)
        object.__setattr__(self, "expectations", expectations)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "client_build", client_build)
        object.__setattr__(
            self,
            "capture_store_identity_sha256",
            capture_store_identity_sha256,
        )
        object.__setattr__(self, "capture_ids", capture_ids)
        object.__setattr__(
            self, "capture_manifest_sha256", capture_manifest_sha256
        )
        object.__setattr__(self, "artifact_sha256", artifact_sha256)
        object.__setattr__(self, "authorization_sha256", authorization_sha256)
        object.__setattr__(self, "replay_source_sha256", replay_source_sha256)


def validate_complete_grounding_coverage(
    resolved_plan: ResolvedGroundingPlan,
    verified_seal: VerifiedGroundingPlanSeal,
    resolved_expectations: ResolvedGroundingExpectations,
    traces: Iterable[ValidatedGroundingTrace],
) -> CompleteGroundingCoverage:
    if resolved_expectations.plan_hash != resolved_plan.plan_hash:
        raise GroundingCoverageError(
            "resolved grounding expectations do not belong to the plan"
        )
    evidence: dict[str, ValidatedGroundingRequirementEvidence] = {}
    for trace in traces:
        binding = bind_grounding_trace_to_plan(
            trace, resolved_plan, verified_seal, resolved_expectations
        )
        if binding.requirement_id in evidence:
            raise GroundingCoverageError(
                f"duplicate grounding evidence: {binding.requirement_id}"
            )
        evidence[binding.requirement_id] = binding
    required = {value.requirement_id for value in resolved_plan.plan.requirements}
    missing = sorted(required - set(evidence))
    unexpected = sorted(set(evidence) - required)
    if missing or unexpected:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if unexpected:
            detail.append("unexpected=" + ",".join(unexpected))
        raise GroundingCoverageError("grounding denominator is incomplete: " + "; ".join(detail))
    bindings = [
        binding
        for item in evidence.values()
        for binding in item.validated_trace.capture_bindings
    ]
    store_identities = {
        binding.capture_store_identity_sha256 for binding in bindings
    }
    if len(store_identities) != 1:
        raise GroundingCoverageError(
            "grounding coverage spans multiple physical capture stores"
        )
    client_builds = {binding.client_build for binding in bindings}
    if client_builds != {resolved_plan.plan.client_build}:
        raise GroundingCoverageError(
            "grounding coverage does not use exactly the sealed client build"
        )
    return CompleteGroundingCoverage(
        plan=resolved_plan,
        seal=verified_seal,
        expectations=resolved_expectations,
        evidence=tuple(evidence[key] for key in sorted(evidence)),
        client_build=next(iter(client_builds)),
        capture_store_identity_sha256=next(iter(store_identities)),
        capture_ids=frozenset(binding.capture_id for binding in bindings),
        capture_manifest_sha256=frozenset(
            binding.manifest_hash for binding in bindings
        ),
        artifact_sha256=frozenset(
            digest for binding in bindings for digest in binding.artifact_sha256
        ),
        authorization_sha256=frozenset(
            binding.authorization_sha256 for binding in bindings
        ),
        replay_source_sha256=frozenset(
            item.replay_source_sha256
            for item in resolved_expectations.evidence
            if item.replay_source_sha256 is not None
        ),
        _token=_COVERAGE_TOKEN,
    )


_ENVIRONMENT_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class CompleteGroundingEnvironmentEvidence:
    plans: ValidatedGroundingPlanPair
    development: CompleteGroundingCoverage
    holdout: CompleteGroundingCoverage

    def __init__(
        self,
        plans: ValidatedGroundingPlanPair,
        development: CompleteGroundingCoverage,
        holdout: CompleteGroundingCoverage,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _ENVIRONMENT_TOKEN:
            raise GroundingCoverageError(
                "complete environment evidence must be created by the pair gate"
            )
        object.__setattr__(self, "plans", plans)
        object.__setattr__(self, "development", development)
        object.__setattr__(self, "holdout", holdout)


def validate_complete_grounding_environment(
    plans: ValidatedGroundingPlanPair,
    development: CompleteGroundingCoverage,
    holdout: CompleteGroundingCoverage,
) -> CompleteGroundingEnvironmentEvidence:
    if development.plan != plans.development or holdout.plan != plans.holdout:
        raise GroundingPlanError("grounding coverage does not belong to the plan pair")
    if development.client_build != holdout.client_build:
        raise GroundingPlanError(
            "development and holdout use different installed client builds"
        )
    for label, lineage, coverage in (
        ("development", plans.development_lineage, development),
        ("holdout", plans.holdout_lineage, holdout),
    ):
        declared_sources = frozenset(lineage.receipt.source_artifact_sha256)
        if declared_sources != coverage.replay_source_sha256:
            raise GroundingPlanError(
                f"{label} lineage source artifacts do not match resolved Replay bytes"
            )
    if (
        development.capture_store_identity_sha256
        == holdout.capture_store_identity_sha256
    ):
        raise GroundingPlanError(
            "development and holdout use the same physical capture store"
        )
    if development.capture_ids & holdout.capture_ids:
        raise GroundingPlanError(
            "development and holdout reuse capture identities"
        )
    if development.capture_manifest_sha256 & holdout.capture_manifest_sha256:
        raise GroundingPlanError(
            "development and holdout reuse capture manifests"
        )
    if development.authorization_sha256 & holdout.authorization_sha256:
        raise GroundingPlanError(
            "development and holdout reuse observation authorization bytes"
        )
    if development.seal.comment_url == holdout.seal.comment_url:
        raise GroundingPlanError(
            "development and holdout reuse the same GitHub plan-seal comment"
        )
    if development.seal.receipt_sha256 == holdout.seal.receipt_sha256:
        raise GroundingPlanError(
            "development and holdout reuse the same GitHub plan-seal receipt"
        )
    if development.replay_source_sha256 & holdout.replay_source_sha256:
        raise GroundingPlanError(
            "development and holdout reuse external Replay bytes"
        )
    return CompleteGroundingEnvironmentEvidence(
        plans=plans,
        development=development,
        holdout=holdout,
        _token=_ENVIRONMENT_TOKEN,
    )


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GroundingCoverageError("grounding timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroundingCoverageError("grounding timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "CompleteGroundingCoverage",
    "CompleteGroundingEnvironmentEvidence",
    "GroundingCoverageError",
    "ValidatedGroundingRequirementEvidence",
    "bind_grounding_trace_to_plan",
    "validate_complete_grounding_coverage",
    "validate_complete_grounding_environment",
]
