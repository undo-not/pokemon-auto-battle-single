"""Deterministic probe-plan factory backed by the capability probe runner."""

from __future__ import annotations

from typing import Callable, Mapping

from champions_sim.capabilities import (
    EXECUTION_DIMENSIONS,
    DimensionStatus,
    ProbeExecution,
    ProbeSpec,
    TargetCapabilitySet,
    ValidatedProbeReport,
    run_capability_probes,
)
from champions_sim.core import canonical_hash

from .models import CompiledProbePlan, ExecutionCompilation


ProbeExecutor = Callable[[], ProbeExecution]


def compile_probe_plan(
    capability_set: TargetCapabilitySet,
    execution_compilation: ExecutionCompilation,
) -> CompiledProbePlan:
    """Generate exactly one supported/explicit-unsupported probe per capability."""

    if execution_compilation.target_capability_set_hash != capability_set.capability_set_hash:
        raise ValueError("execution compilation capability-set hash mismatch")
    support_by_capability = {
        value.capability_id: value
        for value in execution_compilation.registry.supports
    }
    expected_ids = {value.capability_id for value in capability_set.capabilities}
    if set(support_by_capability) != expected_ids:
        raise ValueError("execution registry must cover the exact capability denominator")

    specs: list[ProbeSpec] = []
    for capability in sorted(capability_set.capabilities, key=lambda value: value.capability_id):
        support = support_by_capability[capability.capability_id]
        dimensions = {value.dimension: value for value in support.dimensions}
        supported = (
            set(dimensions) == set(EXECUTION_DIMENSIONS)
            and all(value.status is DimensionStatus.PASS for value in dimensions.values())
        )
        expected = "supported" if supported else "explicit_unsupported"
        probe_id = "probe-" + canonical_hash(
            (
                capability.capability_id,
                execution_compilation.registry.registry_hash,
                expected,
            )
        )
        specs.append(ProbeSpec(probe_id, capability.capability_id, expected))
    return CompiledProbePlan(
        target_capability_set_hash=capability_set.capability_set_hash,
        execution_registry_hash=execution_compilation.registry.registry_hash,
        specs=tuple(specs),
    )


def run_compiled_probe_plan(
    capability_set: TargetCapabilitySet,
    execution_compilation: ExecutionCompilation,
    plan: CompiledProbePlan,
    capability_executors: Mapping[str, ProbeExecutor],
) -> ValidatedProbeReport:
    """Run a compiled plan without allowing callers to rewrite expectations.

    Executors are keyed by capability ID.  For an unsupported capability the
    engine/adapter must raise ``UnsupportedMechanic`` (or return the equivalent
    ``unsupported_exception`` result).  Returning success is derived as a
    silent fallback by the existing validated probe runner.
    """

    if plan.target_capability_set_hash != capability_set.capability_set_hash:
        raise ValueError("probe plan capability-set hash mismatch")
    expected_plan = compile_probe_plan(capability_set, execution_compilation)
    if plan != expected_plan:
        raise ValueError("probe plan differs from compiler-derived expectations")
    capability_ids = {value.capability_id for value in capability_set.capabilities}
    extra = set(capability_executors) - capability_ids
    if extra:
        raise ValueError(f"executors supplied outside capability denominator: {sorted(extra)}")
    executors = {
        spec.probe_id: capability_executors[spec.capability_id]
        for spec in plan.specs
        if spec.capability_id in capability_executors
    }
    return run_capability_probes(capability_set, plan.specs, executors)
