"""Small deterministic policy boundary used to exercise SIM-01."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol

from .core import (
    ActionKind,
    ActionSelection,
    DecisionRequest,
    ExplicitRNG,
    PlayerId,
    PlayerObservation,
)


class Policy(Protocol):
    def select(
        self,
        request: DecisionRequest,
        observation: PlayerObservation,
        rng: ExplicitRNG,
    ) -> tuple[ActionSelection, ExplicitRNG]: ...


@dataclass(frozen=True, slots=True)
class FirstLegalPolicy:
    """Pick the first non-forfeit action, then forfeit only as a last resort."""

    def select(
        self,
        request: DecisionRequest,
        observation: PlayerObservation,
        rng: ExplicitRNG,
    ) -> tuple[ActionSelection, ExplicitRNG]:
        del observation
        action = next(
            (candidate for candidate in request.legal_actions if candidate.kind is not ActionKind.FORFEIT),
            request.legal_actions[0],
        )
        return ActionSelection(request.request_id, request.player, action.action_id), rng


@dataclass(frozen=True, slots=True)
class RandomLegalPolicy:
    allow_forfeit: bool = False

    def select(
        self,
        request: DecisionRequest,
        observation: PlayerObservation,
        rng: ExplicitRNG,
    ) -> tuple[ActionSelection, ExplicitRNG]:
        del observation
        choices = tuple(
            action
            for action in request.legal_actions
            if self.allow_forfeit or action.kind is not ActionKind.FORFEIT
        )
        if not choices:
            choices = request.legal_actions
        index, rng = rng.randbelow(len(choices))
        action = choices[index]
        return ActionSelection(request.request_id, request.player, action.action_id), rng


@dataclass(slots=True)
class ScriptedPolicy:
    """Select action suffixes in order, falling back without inventing actions.

    Script entries can be full action IDs or suffixes such as ``move:surf`` and
    ``switch:p1-starmie``. A separate cursor is maintained for each player.
    """

    scripts: Mapping[PlayerId, tuple[str, ...]]
    cursors: dict[PlayerId, int] = field(default_factory=dict)

    def select(
        self,
        request: DecisionRequest,
        observation: PlayerObservation,
        rng: ExplicitRNG,
    ) -> tuple[ActionSelection, ExplicitRNG]:
        del observation
        script = self.scripts.get(request.player, ())
        cursor = self.cursors.get(request.player, 0)
        wanted = script[cursor] if cursor < len(script) else None
        if wanted is not None:
            self.cursors[request.player] = cursor + 1
        action = None
        if wanted is not None:
            action = next(
                (
                    candidate
                    for candidate in request.legal_actions
                    if candidate.action_id == wanted or candidate.action_id.endswith(f":{wanted}")
                ),
                None,
            )
        if action is None:
            action = next(
                (
                    candidate
                    for candidate in request.legal_actions
                    if candidate.kind is not ActionKind.FORFEIT
                ),
                request.legal_actions[0],
            )
        return ActionSelection(request.request_id, request.player, action.action_id), rng
