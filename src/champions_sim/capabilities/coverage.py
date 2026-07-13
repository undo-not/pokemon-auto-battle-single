"""MechanicCoverageMatrix derivation from frozen, validated inputs."""

from __future__ import annotations

from collections import defaultdict

from .grounding import ValidatedGroundingAssertionSet
from .models import (
    EXECUTION_DIMENSIONS,
    SCHEMA_VERSION,
    CoverageDimensionResult,
    DimensionStatus,
    ExecutionRegistry,
    HoldoutGapReport,
    MechanicCoverageMatrix,
    MechanicCoverageRow,
    ResolvedAssertionVerdict,
    TargetCapabilitySet,
)
from .probes import ValidatedProbeReport


def build_mechanic_coverage_matrix(
    *,
    matrix_id: str,
    capability_set: TargetCapabilitySet,
    execution_registry: ExecutionRegistry,
    probe_report: ValidatedProbeReport,
    grounding_assertions: ValidatedGroundingAssertionSet,
    holdout_report: HoldoutGapReport | None,
) -> MechanicCoverageMatrix:
    """Recompute every count/rate; no caller-supplied summary is accepted."""

    capability_hash = capability_set.capability_set_hash
    if probe_report.capability_set_hash != capability_hash:
        raise ValueError("probe report capability-set hash mismatch")
    if grounding_assertions.target_capability_set_hash != capability_hash:
        raise ValueError("grounding assertion capability-set hash mismatch")
    if holdout_report is not None:
        if holdout_report.target_capability_set_hash != capability_hash:
            raise ValueError("holdout report capability-set hash mismatch")

    support_by_capability = {
        value.capability_id: value for value in execution_registry.supports
    }
    extra_support = set(support_by_capability) - {
        value.capability_id for value in capability_set.capabilities
    }
    if extra_support:
        raise ValueError(
            f"execution registry contains capabilities outside denominator: {sorted(extra_support)}"
        )
    probe_by_capability = defaultdict(list)
    for value in probe_report.results:
        probe_by_capability[value.capability_id].append(value)

    assertion_by_requirement = defaultdict(list)
    for assertion in grounding_assertions.results:
        for requirement_id in assertion.requirement_ids:
            assertion_by_requirement[requirement_id].append(assertion)

    rows: list[MechanicCoverageRow] = []
    for capability in capability_set.capabilities:
        blockers: list[str] = []
        support = support_by_capability.get(capability.capability_id)
        supplied = {
            value.dimension: value for value in support.dimensions
        } if support is not None else {}
        dimensions: list[CoverageDimensionResult] = []
        for dimension in EXECUTION_DIMENSIONS:
            result = supplied.get(dimension)
            if result is None:
                result = CoverageDimensionResult(
                    dimension=dimension,
                    status=DimensionStatus.MISSING,
                    contract_id=f"missing:{dimension}",
                    test_ids=(),
                )
                blockers.append(f"missing_execution_dimension:{dimension}")
            elif result.status is not DimensionStatus.PASS:
                blockers.append(f"execution_dimension_{result.status.value}:{dimension}")
            dimensions.append(result)
        if set(supplied) - set(EXECUTION_DIMENSIONS):
            raise ValueError("execution registry contains an unknown dimension")

        probes = probe_by_capability.get(capability.capability_id, ())
        if not probes:
            blockers.append("missing_capability_probe")
        if any(value.silent_fallback_detected for value in probes):
            blockers.append("silent_fallback_detected")
        positive_probe = probe_report.positive_passed(capability.capability_id)
        if not positive_probe:
            blockers.append("missing_positive_execution_probe")

        passed_requirements: list[str] = []
        for requirement_id in capability.grounding_requirement_ids:
            results = assertion_by_requirement.get(requirement_id, ())
            has_pass = any(
                value.verdict is ResolvedAssertionVerdict.PASS for value in results
            )
            has_fail = any(
                value.verdict is ResolvedAssertionVerdict.FAIL for value in results
            )
            if has_pass and not has_fail:
                passed_requirements.append(requirement_id)
            else:
                blockers.append(f"grounding_requirement_unmet:{requirement_id}")

        execution_pass = (
            all(value.status is DimensionStatus.PASS for value in dimensions)
            and positive_probe
            and not any(value.silent_fallback_detected for value in probes)
        )
        grounding_complete = set(passed_requirements) == set(
            capability.grounding_requirement_ids
        )
        rows.append(
            MechanicCoverageRow(
                capability_id=capability.capability_id,
                entity_ref_ids=capability.entity_ref_ids,
                execution_dimensions=tuple(dimensions),
                grounding_requirement_ids=capability.grounding_requirement_ids,
                passed_grounding_requirement_ids=tuple(sorted(passed_requirements)),
                probe_ids=tuple(sorted(value.probe_id for value in probes)),
                fully_supported=execution_pass,
                grounding_complete=grounding_complete,
                blockers=tuple(sorted(set(blockers))),
            )
        )

    rows_tuple = tuple(rows)
    silent_count = probe_report.silent_fallback_count
    denominator_final = capability_set.denominator_final
    if denominator_final:
        declared_count = len(rows_tuple)
        fully_supported_count = sum(value.fully_supported for value in rows_tuple)
        execution_rate = _rate_ppm(fully_supported_count, declared_count)
        required_grounding_count = len(capability_set.grounding_requirements)
        passed_ids = {
            requirement_id
            for row in rows_tuple
            for requirement_id in row.passed_grounding_requirement_ids
        }
        passed_grounding_count = len(passed_ids)
        grounding_rate = _rate_ppm(passed_grounding_count, required_grounding_count)
    else:
        declared_count = None
        fully_supported_count = None
        execution_rate = None
        required_grounding_count = None
        passed_grounding_count = None
        grounding_rate = None

    coverage_complete = bool(
        denominator_final
        and rows_tuple
        and all(value.fully_supported for value in rows_tuple)
        and silent_count == 0
    )
    grounding_complete = bool(
        denominator_final
        and rows_tuple
        and all(value.grounding_complete for value in rows_tuple)
    )
    holdout_clean = holdout_report is not None and holdout_report.holdout_clean
    candidate_ready = coverage_complete and grounding_complete and holdout_clean
    reasons: list[str] = []
    if not denominator_final:
        reasons.append("capability_denominator_not_final")
        reasons.extend(value.blocker_code for value in capability_set.unresolved_requirements)
    if denominator_final and not coverage_complete:
        reasons.append("target_pool_execution_coverage_below_one")
    if denominator_final and not grounding_complete:
        reasons.append("verified_grounding_conformance_below_one")
    if silent_count:
        reasons.append(f"silent_fallback_count:{silent_count}")
    if holdout_report is None:
        reasons.append("external_holdout_missing")
    elif not holdout_report.holdout_clean:
        reasons.extend(holdout_report.blocking_reasons)
    return MechanicCoverageMatrix(
        schema_version=SCHEMA_VERSION,
        matrix_id=matrix_id,
        target_capability_set_id=capability_set.capability_set_id,
        target_capability_set_hash=capability_hash,
        execution_registry_hash=execution_registry.registry_hash,
        grounding_assertion_set_hash=grounding_assertions.assertion_set_hash,
        probe_report_hash=probe_report.report_hash,
        holdout_report_hash=(holdout_report.report_hash if holdout_report is not None else None),
        denominator_final=denominator_final,
        declared_target_capability_count=declared_count,
        fully_supported_target_capability_count=fully_supported_count,
        target_pool_execution_coverage_rate_ppm=execution_rate,
        required_grounding_requirement_count=required_grounding_count,
        passed_grounding_requirement_count=passed_grounding_count,
        verified_grounding_conformance_rate_ppm=grounding_rate,
        silent_fallback_count=silent_count,
        rows=rows_tuple,
        unresolved_requirements=capability_set.unresolved_requirements,
        coverage_complete=coverage_complete,
        candidate_ready=candidate_ready,
        blocking_reasons=tuple(sorted(set(reasons))),
    )


def _rate_ppm(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    return numerator * 1_000_000 // denominator
