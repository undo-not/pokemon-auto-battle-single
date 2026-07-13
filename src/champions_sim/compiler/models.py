"""Compiler result contracts for source-bound capability registries.

These are deliberately diagnostic wrappers around the public capability
models.  The frozen denominator, coverage rates, and promotion decision remain
owned by :mod:`champions_sim.capabilities`; the compiler cannot manufacture
those summary values.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from champions_sim.capabilities import (
    EffectSemanticRegistry,
    ExecutionRegistry,
    ProbeSpec,
)
from champions_sim.core import canonical_hash


@dataclass(frozen=True, slots=True)
class SelectorDiagnostic:
    """One Catalog/mechanic selector retained in the compiler inventory."""

    entity_kind: str
    entity_id: str
    selector_id: str
    capability_id: str
    status: str
    reason_codes: tuple[str, ...]
    source_record_sha256: str | None = None
    source_reason: str | None = None

    def __post_init__(self) -> None:
        if self.entity_kind not in {"move", "ability", "item", "mechanic"}:
            raise ValueError("unsupported diagnostic entity kind")
        if not self.entity_id or not self.selector_id or not self.capability_id:
            raise ValueError("selector diagnostic requires stable identities")
        if self.status not in {"known", "explicit_unsupported"}:
            raise ValueError("unsupported selector diagnostic status")
        if self.status == "known" and self.reason_codes:
            raise ValueError("known selector cannot carry unsupported reasons")
        if self.status == "explicit_unsupported" and not self.reason_codes:
            raise ValueError("unsupported selector requires a reason")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("selector diagnostic reasons must be unique")
        if (
            self.source_record_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.source_record_sha256) is None
        ):
            raise ValueError("selector source record hash must be SHA-256")
        if self.source_reason is not None and not self.source_reason:
            raise ValueError("selector source reason cannot be empty")


@dataclass(frozen=True, slots=True)
class SemanticCompilation:
    catalog_hash: str
    ruleset_hash: str
    registry: EffectSemanticRegistry
    inventory: tuple[SelectorDiagnostic, ...]

    def __post_init__(self) -> None:
        definition_ids = {value.semantic_id for value in self.registry.definitions}
        if len(self.inventory) != len(definition_ids):
            raise ValueError("semantic inventory must cover every definition exactly once")
        capability_ids = {
            value.signature.capability_id for value in self.registry.definitions
        }
        if any(value.capability_id not in capability_ids for value in self.inventory):
            raise ValueError("semantic diagnostic references an unknown capability")

    @property
    def unsupported_selectors(self) -> tuple[SelectorDiagnostic, ...]:
        return tuple(
            value for value in self.inventory
            if value.status == "explicit_unsupported"
        )

    @property
    def compilation_hash(self) -> str:
        return canonical_hash(
            (self.catalog_hash, self.ruleset_hash, self.registry, self.inventory)
        )


@dataclass(frozen=True, slots=True)
class ExecutionGap:
    capability_id: str
    effect_id: str
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.capability_id or not self.effect_id or not self.reason_codes:
            raise ValueError("execution gap requires capability, effect, and reason")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("execution gap reasons must be unique")


@dataclass(frozen=True, slots=True)
class ExecutionCompilation:
    target_capability_set_hash: str
    semantic_compilation_hash: str
    registry: ExecutionRegistry
    gaps: tuple[ExecutionGap, ...]

    def __post_init__(self) -> None:
        support_ids = {value.capability_id for value in self.registry.supports}
        if any(value.capability_id not in support_ids for value in self.gaps):
            raise ValueError("execution gap requires an explicit registry support row")
        if len(self.gaps) != len({value.capability_id for value in self.gaps}):
            raise ValueError("execution gaps must be unique per capability")

    @property
    def compilation_hash(self) -> str:
        return canonical_hash(
            (
                self.target_capability_set_hash,
                self.semantic_compilation_hash,
                self.registry,
                self.gaps,
            )
        )


@dataclass(frozen=True, slots=True)
class CompiledProbePlan:
    target_capability_set_hash: str
    execution_registry_hash: str
    specs: tuple[ProbeSpec, ...]

    def __post_init__(self) -> None:
        probe_ids = tuple(value.probe_id for value in self.specs)
        capability_ids = tuple(value.capability_id for value in self.specs)
        if len(probe_ids) != len(set(probe_ids)):
            raise ValueError("compiled probe IDs must be unique")
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("compiled probes require exactly one probe per capability")

    @property
    def plan_hash(self) -> str:
        return canonical_hash(self)
