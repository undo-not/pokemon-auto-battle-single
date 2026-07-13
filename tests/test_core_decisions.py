import sys
from dataclasses import fields
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.core import (  # noqa: E402
    ActionKind,
    DecisionKind,
    DecisionRequest,
    DecisionRequestSet,
    LegalAction,
    MoveId,
    PlayerId,
    PokemonInstanceId,
)


def _move_action(player: PlayerId) -> LegalAction:
    return LegalAction(
        action_id=f"{player.value}:move:tackle",
        kind=ActionKind.MOVE,
        move_id=MoveId("tackle"),
    )


def _switch_action(player: PlayerId) -> LegalAction:
    return LegalAction(
        action_id=f"{player.value}:switch:bench-1",
        kind=ActionKind.SWITCH,
        switch_to=PokemonInstanceId(f"{player.value}-bench-1"),
    )


def test_normal_decisions_can_be_simultaneous() -> None:
    requests = DecisionRequestSet(
        (
            DecisionRequest(
                "turn-1:p1", PlayerId.P1, DecisionKind.ACTION, (_move_action(PlayerId.P1),)
            ),
            DecisionRequest(
                "turn-1:p2", PlayerId.P2, DecisionKind.ACTION, (_move_action(PlayerId.P2),)
            ),
        )
    )

    assert requests.simultaneous
    assert requests.for_player(PlayerId.P1) is not None


def test_forced_switch_supports_one_or_both_players() -> None:
    p1 = DecisionRequest(
        "forced:p1",
        PlayerId.P1,
        DecisionKind.FORCED_SWITCH,
        (_switch_action(PlayerId.P1),),
    )
    p2 = DecisionRequest(
        "forced:p2",
        PlayerId.P2,
        DecisionKind.FORCED_SWITCH,
        (_switch_action(PlayerId.P2),),
    )

    assert not DecisionRequestSet((p1,)).simultaneous
    assert DecisionRequestSet((p1, p2)).simultaneous


def test_forced_switch_rejects_non_switch_actions() -> None:
    with pytest.raises(ValueError, match="only contain switches"):
        DecisionRequest(
            "forced:p1",
            PlayerId.P1,
            DecisionKind.FORCED_SWITCH,
            (_move_action(PlayerId.P1),),
        )


def test_legal_action_contract_contains_no_ui_or_rl_addressing() -> None:
    names = {field.name for field in fields(LegalAction)}

    assert names == {"action_id", "kind", "move_id", "switch_to"}
    assert "x" not in names
    assert "y" not in names
    assert "rl_index" not in names
