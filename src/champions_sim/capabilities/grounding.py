"""Resolver-backed TargetCapability grounding assertions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from champions_sim.core import canonical_hash
from champions_sim.grounding import (
    ConformanceVerdict,
    GroundingTraceStatus,
    ValidatedGroundingTrace,
)

from .models import (
    GroundingAssertion,
    GroundingAssertionSet,
    ResolvedAssertionVerdict,
    ResolvedGroundingAssertion,
    TargetCapabilitySet,
)


_ASSERTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedGroundingAssertionSet:
    assertion_set_hash: str
    target_capability_set_hash: str
    results: tuple[ResolvedGroundingAssertion, ...]

    def __init__(
        self,
        assertion_set_hash: str,
        target_capability_set_hash: str,
        results: tuple[ResolvedGroundingAssertion, ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _ASSERTION_TOKEN:
            raise ValueError(
                "ValidatedGroundingAssertionSet must be created by its resolver gate"
            )
        object.__setattr__(self, "assertion_set_hash", assertion_set_hash)
        object.__setattr__(self, "target_capability_set_hash", target_capability_set_hash)
        object.__setattr__(self, "results", results)


def resolve_grounding_assertions(
    assertion_set: GroundingAssertionSet,
    capability_set: TargetCapabilitySet,
    *,
    validated_traces: Mapping[str, ValidatedGroundingTrace],
    evidence_resolver: Callable[[str], bool],
) -> ValidatedGroundingAssertionSet:
    """Resolve every assertion to actual capture/source evidence.

    A raw ``claimed_verdict`` never enters coverage directly. Actual BlueStacks
    assertions must reference a resolver-promoted trace and MATCH checks.
    Official/published assertions must resolve all source evidence references.
    """

    if assertion_set.schema_version != "1.0.0":
        raise ValueError("unsupported grounding assertion schema_version")
    if assertion_set.target_capability_set_id != capability_set.capability_set_id:
        raise ValueError("grounding assertion capability-set ID mismatch")
    if assertion_set.target_capability_set_hash != capability_set.capability_set_hash:
        raise ValueError("grounding assertion capability-set hash mismatch")
    assertion_ids = tuple(value.assertion_id for value in assertion_set.assertions)
    if len(assertion_ids) != len(set(assertion_ids)):
        raise ValueError("grounding assertion IDs must be unique")

    capabilities = {value.capability_id: value for value in capability_set.capabilities}
    requirements = {
        value.requirement_id: value for value in capability_set.grounding_requirements
    }
    results: list[ResolvedGroundingAssertion] = []
    for assertion in sorted(assertion_set.assertions, key=lambda value: value.assertion_id):
        blockers = _validate_assertion_relations(assertion, capabilities, requirements)
        if assertion.ruleset_hash != capability_set.ruleset_hash:
            blockers.append("ruleset_hash_mismatch")
        if assertion.catalog_hash != capability_set.catalog_hash:
            blockers.append("catalog_hash_mismatch")
        if not assertion.evidence_ref_ids:
            blockers.append("missing_evidence_refs")
        elif any(not evidence_resolver(value) for value in assertion.evidence_ref_ids):
            blockers.append("unresolved_evidence_ref")

        if assertion.evidence_kind == "actual_bluestacks":
            blockers.extend(_validate_trace_assertion(assertion, validated_traces))
        elif assertion.evidence_kind not in {
            "official_primary",
            "published_reference",
        }:
            blockers.append("unsupported_evidence_kind")

        if assertion.claimed_verdict == "fail":
            verdict = ResolvedAssertionVerdict.FAIL
        elif assertion.claimed_verdict == "unknown":
            blockers.append("assertion_claimed_unknown")
            verdict = ResolvedAssertionVerdict.UNVERIFIED
        elif blockers:
            verdict = ResolvedAssertionVerdict.UNVERIFIED
        else:
            verdict = ResolvedAssertionVerdict.PASS
        results.append(
            ResolvedGroundingAssertion(
                assertion_id=assertion.assertion_id,
                requirement_ids=assertion.requirement_ids,
                capability_ids=assertion.capability_ids,
                verdict=verdict,
                blockers=tuple(sorted(set(blockers))),
            )
        )
    return ValidatedGroundingAssertionSet(
        assertion_set.assertion_set_hash,
        capability_set.capability_set_hash,
        tuple(results),
        _token=_ASSERTION_TOKEN,
    )


def _validate_assertion_relations(assertion, capabilities, requirements) -> list[str]:
    blockers: list[str] = []
    if not assertion.capability_ids or not assertion.requirement_ids:
        blockers.append("missing_capability_or_requirement")
    if any(value not in capabilities for value in assertion.capability_ids):
        blockers.append("unknown_capability")
    if any(value not in requirements for value in assertion.requirement_ids):
        blockers.append("unknown_grounding_requirement")
    for requirement_id in assertion.requirement_ids:
        requirement = requirements.get(requirement_id)
        if requirement is not None and requirement.capability_id not in assertion.capability_ids:
            blockers.append("requirement_capability_mismatch")
        if (
            requirement is not None
            and assertion.evidence_kind not in requirement.allowed_evidence_kinds
        ):
            blockers.append("evidence_kind_not_allowed")
    return blockers


def _validate_trace_assertion(
    assertion: GroundingAssertion,
    validated_traces: Mapping[str, ValidatedGroundingTrace],
) -> list[str]:
    blockers: list[str] = []
    if assertion.trace_id is None or assertion.trace_hash is None:
        return ["actual_assertion_missing_trace_binding"]
    if assertion.reference_replay_hash is None:
        blockers.append("actual_assertion_missing_reference_replay")
    validated = validated_traces.get(assertion.trace_id)
    if validated is None:
        return ["trace_not_resolver_validated"]
    trace = validated.trace
    if not validated.promotable or trace.status is not GroundingTraceStatus.CONFORMANT:
        blockers.append("trace_not_conformant")
    if canonical_hash(trace.to_dict()) != assertion.trace_hash:
        blockers.append("trace_hash_mismatch")
    if trace.ruleset_id != assertion.ruleset_id:
        blockers.append("trace_ruleset_id_mismatch")
    if assertion.reference_replay_hash != trace.reference_replay_hash:
        blockers.append("trace_replay_hash_mismatch")
    checks = {
        (frame.frame_id, check.path): check
        for frame in trace.frames
        for check in frame.conformance
    }
    if not assertion.conformance_check_refs:
        blockers.append("actual_assertion_missing_conformance_checks")
    for reference in assertion.conformance_check_refs:
        check = checks.get((reference.frame_id, reference.path))
        if check is None:
            blockers.append("missing_conformance_check")
        elif check.verdict is not ConformanceVerdict.MATCH:
            blockers.append("conformance_check_not_match")
    return blockers
