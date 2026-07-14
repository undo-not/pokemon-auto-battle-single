"""Deterministic public-information baselines for AI-01."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from champions_sim.catalog import CatalogSnapshot, MoveDefinition
from champions_sim.core import (
    ActionKind,
    ActionSelection,
    DecisionRequest,
    ExplicitRNG,
    LegalAction,
    PlayerObservation,
)
from champions_sim.policies import RandomLegalPolicy
from champions_sim.prebattle import (
    FirstThreeTeamSelectionPolicy,
    TypeCoverageTeamSelectionPolicy,
    make_team_selection_policy_identity,
)

from .binding import BoundAgent, bind_agent
from .models import AgentIdentity


TYPE_AWARE_POLICY_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class TypeAwareDamagePolicy:
    """Choose the strongest public-information damaging move lexicographically.

    The policy deliberately has no access to ``BattleState``.  Its estimate is
    exact rational move power × accuracy × public type effectiveness × STAB.
    It is a transparent baseline, not a claim of optimal play.
    """

    catalog: CatalogSnapshot

    def select(
        self,
        request: DecisionRequest,
        observation: PlayerObservation,
        rng: ExplicitRNG,
    ) -> tuple[ActionSelection, ExplicitRNG]:
        switches = tuple(
            action for action in request.legal_actions if action.kind is ActionKind.SWITCH
        )
        if switches and not any(
            action.kind is ActionKind.MOVE for action in request.legal_actions
        ):
            action = self._healthiest_switch(switches, observation)
            return ActionSelection(request.request_id, request.player, action.action_id), rng

        own_active = next(
            (item for item in observation.own_side.pokemon if item.is_active),
            None,
        )
        opponent_active = next(
            (item for item in observation.opponent_side.pokemon if item.is_active),
            None,
        )
        damaging = []
        for action in request.legal_actions:
            if action.kind is not ActionKind.MOVE or action.move_id is None:
                continue
            move = self.catalog.move(action.move_id)
            if move.power is None:
                continue
            damaging.append((action, move))

        if damaging:
            # Stable action IDs make equal-score tie breaking byte reproducible.
            damaging.sort(key=lambda item: item[0].action_id)

            def score(
                item: tuple[LegalAction, MoveDefinition],
            ) -> tuple[Fraction, int, int]:
                action, move = item
                del action
                accuracy = move.accuracy if move.accuracy is not None else 100
                effectiveness = (
                    self.catalog.type_effectiveness(move.type_id, opponent_active.types)
                    if opponent_active is not None
                    else Fraction(1, 1)
                )
                stab = (
                    Fraction(3, 2)
                    if own_active is not None and move.type_id in own_active.types
                    else Fraction(1, 1)
                )
                expected_power = Fraction(move.power * accuracy, 100) * effectiveness * stab
                return expected_power, move.priority or 0, accuracy

            action, _ = max(damaging, key=score)
        else:
            action = next(
                (
                    item
                    for item in request.legal_actions
                    if item.kind is not ActionKind.FORFEIT
                ),
                request.legal_actions[0],
            )
        return ActionSelection(request.request_id, request.player, action.action_id), rng

    @staticmethod
    def _healthiest_switch(switches, observation: PlayerObservation):
        visible = {item.instance_id: item for item in observation.own_side.pokemon}
        ordered = sorted(switches, key=lambda item: item.action_id)

        def score(action) -> tuple[int, int]:
            pokemon = visible.get(action.switch_to)
            if pokemon is None:
                return -1, -1
            fraction = pokemon.hp_fraction_millionths or 0
            speed = pokemon.stats.speed if pokemon.stats is not None else 0
            return fraction, speed

        return max(ordered, key=score)


def type_aware_agent_identity(catalog: CatalogSnapshot) -> AgentIdentity:
    return type_aware_agent_binding(catalog).identity


def type_aware_agent_binding(catalog: CatalogSnapshot) -> BoundAgent:
    configuration = {
        "catalog_hash": catalog.snapshot_hash,
        "inputs": "DecisionRequest+PlayerObservation",
        "score": "power*accuracy*type_effectiveness*stab",
    }
    return bind_agent(
        agent_id="type-aware-damage-baseline",
        version=TYPE_AWARE_POLICY_VERSION,
        policy_type=TypeAwareDamagePolicy,
        factory=lambda: TypeAwareDamagePolicy(catalog),
        component_types=(TypeAwareDamagePolicy,),
        configuration=configuration,
    )


def random_legal_agent_identity() -> AgentIdentity:
    return random_legal_agent_binding().identity


def random_legal_agent_binding() -> BoundAgent:
    return bind_agent(
        agent_id="random-legal-baseline",
        version="1.0",
        policy_type=RandomLegalPolicy,
        factory=RandomLegalPolicy,
        component_types=(RandomLegalPolicy,),
        configuration={
            "allow_forfeit": False,
            "inputs": "DecisionRequest+PlayerObservation",
        },
    )


def competitive_baseline_identity(catalog: CatalogSnapshot) -> AgentIdentity:
    """Identity for the type-coverage selection + type-aware battle baseline."""

    return competitive_baseline_binding(catalog).identity


def competitive_baseline_binding(catalog: CatalogSnapshot) -> BoundAgent:
    """Bound type-coverage selection + type-aware battle baseline."""

    selection_policy = TypeCoverageTeamSelectionPolicy(catalog)

    return bind_agent(
        agent_id="type-coverage-selection+type-aware-battle-baseline",
        version="1.0",
        policy_type=TypeAwareDamagePolicy,
        factory=lambda: TypeAwareDamagePolicy(catalog),
        component_types=(TypeCoverageTeamSelectionPolicy, TypeAwareDamagePolicy),
        configuration={
            "catalog_hash": catalog.snapshot_hash,
            "selection_score": "super-effective-count,best-type-sum,speed",
            "selection_policy_implementation_hash": (
                make_team_selection_policy_identity(
                    selection_policy
                ).implementation_hash
            ),
            "battle_score": "power*accuracy*type_effectiveness*stab",
        },
        observation_contract="team-preview-observation-v1+player-observation-v1",
    )


def random_reference_identity() -> AgentIdentity:
    """Identity for first-three selection followed by random legal actions."""

    return random_reference_binding().identity


def random_reference_binding() -> BoundAgent:
    """Bound first-three selection + random legal action reference."""

    selection_policy = FirstThreeTeamSelectionPolicy()

    return bind_agent(
        agent_id="first-three-selection+random-legal-reference",
        version="1.0",
        policy_type=RandomLegalPolicy,
        factory=RandomLegalPolicy,
        component_types=(FirstThreeTeamSelectionPolicy, RandomLegalPolicy),
        configuration={
            "selection": "first-three",
            "selection_policy_implementation_hash": (
                make_team_selection_policy_identity(
                    selection_policy
                ).implementation_hash
            ),
            "allow_forfeit": False,
        },
        observation_contract="team-preview-observation-v1+player-observation-v1",
    )
