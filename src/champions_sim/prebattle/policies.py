"""Policy boundary and public-information baselines for team preview."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Protocol

from champions_sim.catalog import CatalogSnapshot
from champions_sim.core import (
    ExplicitRNG,
    PokemonInstanceId,
    class_runtime_sha256,
    class_source_sha256,
    component_state_sha256,
)

from .models import (
    TeamPreviewError,
    TeamPreviewObservation,
    TeamSelectionPolicyIdentity,
)


class TeamSelectionPolicy(Protocol):
    def select(
        self,
        observation: TeamPreviewObservation,
        rng: ExplicitRNG,
    ) -> tuple[tuple[PokemonInstanceId, ...], ExplicitRNG]: ...

    def identity_configuration(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class FirstThreeTeamSelectionPolicy:
    """Deterministic trivial reference policy."""

    def select(
        self,
        observation: TeamPreviewObservation,
        rng: ExplicitRNG,
    ) -> tuple[tuple[PokemonInstanceId, ...], ExplicitRNG]:
        return tuple(member.instance_id for member in observation.own_roster[:3]), rng

    def identity_configuration(self) -> Mapping[str, object]:
        return {}


@dataclass(frozen=True, slots=True)
class TypeCoverageTeamSelectionPolicy:
    """Select three sets covering the most public opposing roster types.

    The score is lexicographic and coefficient-free: number of opposing slots
    that can be hit super-effectively, sum of each slot's best exact type
    multiplier, then own Speed.  Only the viewer's complete sets and the
    opponent-safe ``PublicRosterMember`` fields enter the calculation.
    """

    catalog: CatalogSnapshot

    def identity_configuration(self) -> Mapping[str, object]:
        return {
            "catalog_id": self.catalog.catalog_id,
            "catalog_hash": self.catalog.snapshot_hash,
            "engine_semantics_version": self.catalog.engine_semantics_version,
        }

    def select(
        self,
        observation: TeamPreviewObservation,
        rng: ExplicitRNG,
    ) -> tuple[tuple[PokemonInstanceId, ...], ExplicitRNG]:
        ordered = sorted(
            observation.own_roster,
            key=lambda member: str(member.instance_id),
        )

        def score(member) -> tuple[int, Fraction, int]:
            best_by_opponent: list[Fraction] = []
            damaging_types = tuple(
                self.catalog.move(slot.move_id).type_id
                for slot in member.moves
                if self.catalog.move(slot.move_id).power is not None
            )
            for opponent in observation.opponent_roster:
                values = tuple(
                    self.catalog.type_effectiveness(type_id, opponent.types)
                    for type_id in damaging_types
                )
                best_by_opponent.append(max(values, default=Fraction(0, 1)))
            coverage = sum(value > 1 for value in best_by_opponent)
            total = sum(best_by_opponent, Fraction(0, 1))
            return coverage, total, member.stats.speed

        ranked = sorted(ordered, key=score, reverse=True)
        return tuple(member.instance_id for member in ranked[:3]), rng


def make_team_selection_policy_identity(
    policy: TeamSelectionPolicy,
) -> TeamSelectionPolicyIdentity:
    """Bind identity to the actual policy class, state, and declared config."""

    component_type = type(policy)
    component = f"{component_type.__module__}.{component_type.__qualname__}"
    try:
        source_hash = class_source_sha256(component_type)
        runtime_hash = class_runtime_sha256(component_type)
        state_hash = component_state_sha256(policy)
    except (OSError, TypeError) as error:
        raise TeamPreviewError(
            f"team-selection policy implementation/state is unavailable: {component}"
        ) from error
    configuration_method = getattr(policy, "identity_configuration", None)
    if not callable(configuration_method):
        raise TeamPreviewError(
            f"team-selection policy lacks identity_configuration: {component}"
        )
    configuration = configuration_method()
    if not isinstance(configuration, Mapping):
        raise TeamPreviewError(
            f"team-selection policy configuration must be a mapping: {component}"
        )
    try:
        stable = (
            class_source_sha256(component_type) == source_hash
            and class_runtime_sha256(component_type) == runtime_hash
            and component_state_sha256(policy) == state_hash
        )
    except (OSError, TypeError) as error:
        raise TeamPreviewError(
            f"team-selection policy identity became unavailable: {component}"
        ) from error
    if not stable:
        raise TeamPreviewError(
            f"team-selection policy mutated while deriving identity: {component}"
        )
    try:
        return TeamSelectionPolicyIdentity.create(
            policy_component=component,
            source_sha256=source_hash,
            runtime_sha256=runtime_hash,
            initial_policy_state_hash=state_hash,
            configuration=configuration,
        )
    except (TypeError, ValueError) as error:
        raise TeamPreviewError(
            f"team-selection policy configuration is not canonical: {component}"
        ) from error
