"""Execution probes whose results derive, rather than accept, fallback counts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from champions_sim.core import UnsupportedMechanic, canonical_hash

from .models import (
    ProbeExecution,
    ProbeSpec,
    SilentFallbackProbeResult,
    TargetCapabilitySet,
)


_PROBE_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedProbeReport:
    capability_set_hash: str
    results: tuple[SilentFallbackProbeResult, ...]

    def __init__(
        self,
        capability_set_hash: str,
        results: tuple[SilentFallbackProbeResult, ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _PROBE_TOKEN:
            raise ValueError("ValidatedProbeReport must be created by run_capability_probes")
        object.__setattr__(self, "capability_set_hash", capability_set_hash)
        object.__setattr__(self, "results", results)

    @property
    def report_hash(self) -> str:
        return canonical_hash((self.capability_set_hash, self.results))

    @property
    def silent_fallback_count(self) -> int:
        return sum(value.silent_fallback_detected for value in self.results)

    def positive_passed(self, capability_id: str) -> bool:
        return any(
            value.capability_id == capability_id
            and value.expected_outcome == "supported"
            and value.observed_outcome == "success"
            and not value.silent_fallback_detected
            for value in self.results
        )


def run_capability_probes(
    capability_set: TargetCapabilitySet,
    specs: tuple[ProbeSpec, ...],
    executors: Mapping[str, Callable[[], ProbeExecution]],
) -> ValidatedProbeReport:
    """Run every declared probe and derive explicit/silent outcomes.

    Missing executors are recorded as unexpected errors; they are never treated
    as support. ``UnsupportedMechanic`` is recognized as an explicit fail-closed
    result and therefore does not increment the silent-fallback count.
    """

    capability_ids = {value.capability_id for value in capability_set.capabilities}
    probe_ids = tuple(value.probe_id for value in specs)
    if len(probe_ids) != len(set(probe_ids)):
        raise ValueError("probe IDs must be unique")
    if any(value.capability_id not in capability_ids for value in specs):
        raise ValueError("probe references a capability outside the frozen denominator")
    extra_executors = set(executors) - set(probe_ids)
    if extra_executors:
        raise ValueError(f"executors supplied for undeclared probes: {sorted(extra_executors)}")

    results: list[SilentFallbackProbeResult] = []
    for spec in sorted(specs, key=lambda value: value.probe_id):
        executor = executors.get(spec.probe_id)
        if executor is None:
            execution = ProbeExecution("unexpected_error", False, None)
        else:
            try:
                execution = executor()
                if not isinstance(execution, ProbeExecution):
                    raise TypeError("probe executor must return ProbeExecution")
            except UnsupportedMechanic:
                execution = ProbeExecution("unsupported_exception", False, None)
            except Exception:
                execution = ProbeExecution("unexpected_error", False, None)
        explicit = execution.observed_outcome == "unsupported_exception"
        silent = (
            spec.expected_outcome == "explicit_unsupported"
            and execution.observed_outcome == "success"
        ) or (
            spec.expected_outcome == "supported"
            and execution.observed_outcome == "success"
            and not execution.contract_observed
        )
        results.append(
            SilentFallbackProbeResult(
                probe_id=spec.probe_id,
                capability_id=spec.capability_id,
                expected_outcome=spec.expected_outcome,
                observed_outcome=execution.observed_outcome,
                explicit_unsupported=explicit,
                silent_fallback_detected=silent,
                replay_hash=execution.replay_hash,
            )
        )
    return ValidatedProbeReport(
        capability_set.capability_set_hash,
        tuple(results),
        _token=_PROBE_TOKEN,
    )
