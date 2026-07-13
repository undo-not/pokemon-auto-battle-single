import sys
from dataclasses import replace
from pathlib import Path

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.core import (  # noqa: E402
    ActionKind,
    ActionSelection,
    BattleEvent,
    BattleEventKind,
    BattlePhase,
    BattleState,
    DecisionKind,
    DecisionRequest,
    DecisionRequestSet,
    ExplicitRNG,
    LegalAction,
    MoveId,
    MoveSlotState,
    PlayerId,
    PokemonId,
    PokemonInstanceId,
    PokemonState,
    REPLAY_SCHEMA_VERSION,
    RNG_ALGORITHM_ID,
    SIMULATOR_VERSION,
    ReplayBundle,
    ReplayInitialState,
    ReplayOutcome,
    ReplayRecord,
    ReplayRedaction,
    ReplayResult,
    ReplayStep,
    ReplayVisibility,
    RuleSetId,
    SideState,
    StatBlock,
    canonical_hash,
    canonical_json,
)


def _pokemon(player: PlayerId) -> PokemonState:
    return PokemonState(
        instance_id=PokemonInstanceId(f"{player.value}-active"),
        pokemon_id=PokemonId(f"{player.value}-species"),
        level=50,
        hp=120,
        stats=StatBlock(120, 90, 90, 90, 90, 90),
        types=("normal",),
        moves=(MoveSlotState(MoveId("tackle"), 35, 35, True),),
        revealed_to_opponent=True,
    )


def _state() -> BattleState:
    p1 = _pokemon(PlayerId.P1)
    p2 = _pokemon(PlayerId.P2)
    return BattleState(
        battle_id="replay-test",
        ruleset_id=RuleSetId("fixture-v1"),
        turn=1,
        phase=BattlePhase.AWAITING_DECISIONS,
        sides=(
            SideState(PlayerId.P1, (p1,), p1.instance_id),
            SideState(PlayerId.P2, (p2,), p2.instance_id),
        ),
    )


def _requests() -> DecisionRequestSet:
    return DecisionRequestSet(
        tuple(
            DecisionRequest(
                request_id=f"turn-1:{player.value}",
                player=player,
                kind=DecisionKind.ACTION,
                legal_actions=(
                    LegalAction(
                        action_id=f"{player.value}:move:tackle",
                        kind=ActionKind.MOVE,
                        move_id=MoveId("tackle"),
                    ),
                ),
            )
            for player in (PlayerId.P1, PlayerId.P2)
        )
    )


def test_canonical_json_and_hash_ignore_mapping_insertion_order() -> None:
    left = {"z": 3, "a": {"second": 2, "first": 1}}
    right = {"a": {"first": 1, "second": 2}, "z": 3}

    assert canonical_json(left) == canonical_json(right)
    assert canonical_hash(left) == canonical_hash(right)
    assert len(canonical_hash(left)) == 64


def test_canonical_data_rejects_ambiguous_values() -> None:
    with pytest.raises(TypeError, match="floats"):
        canonical_json({"value": 0.5})
    with pytest.raises(TypeError, match="unordered"):
        canonical_json({"value": {1, 2}})


def test_frozen_state_supports_independent_branches() -> None:
    state = _state()
    branch_a = replace(state, turn=2)
    branch_b = replace(state, phase=BattlePhase.RESOLVING)

    assert state.turn == 1
    assert state.phase is BattlePhase.AWAITING_DECISIONS
    assert branch_a.turn == 2
    assert branch_b.phase is BattlePhase.RESOLVING
    assert canonical_hash(branch_a) != canonical_hash(branch_b)


def test_replay_canonical_roundtrip_preserves_explicit_rng_and_hash() -> None:
    state = _state()
    finished_state = replace(state, phase=BattlePhase.FINISHED)
    requests = _requests()
    rng_before = ExplicitRNG.seeded(20260713)
    _, rng_after = rng_before.randbelow(16)
    result_hash = canonical_hash(finished_state)
    selections = tuple(
        ActionSelection(
            request_id=request.request_id,
            player=request.player,
            action_id=request.legal_actions[0].action_id,
        )
        for request in requests.requests
    )
    rng_event = BattleEvent(
        sequence=0,
        kind=BattleEventKind.RNG_DRAW,
        details=(("cursor_before", 0), ("cursor_after", rng_after.cursor)),
    )
    end_event = BattleEvent(
        sequence=1,
        kind=BattleEventKind.BATTLE_ENDED,
        details=(("reason", "fixture_draw"), ("winner", None)),
    )
    step = ReplayStep(
        requests=requests,
        selections=selections,
        rng_before=rng_before,
        rng_after=rng_after,
        events=(rng_event, end_event),
        result_state_hash=result_hash,
        terminal=True,
        provisional_decision_ids=("PD-003",),
    )
    replay = ReplayRecord(
        schema_version=REPLAY_SCHEMA_VERSION,
        replay_id="replay-test:seed:000000000134fd29",
        bundle=ReplayBundle(
            simulator_version=SIMULATOR_VERSION,
            engine_semantics_version="fixture-engine-v1",
            ruleset_id=state.ruleset_id,
            ruleset_content_hash="a" * 64,
            catalog_id="fixture-catalog-v1",
            catalog_content_hash="b" * 64,
        ),
        rng_algorithm_id=RNG_ALGORITHM_ID,
        initial_rng=rng_before,
        rng_after_initialization=rng_before,
        final_rng=rng_after,
        initial_state=ReplayInitialState.capture(state),
        initial_events=(),
        initialized_state_hash=canonical_hash(state),
        steps=(step,),
        result=ReplayResult(
            outcome=ReplayOutcome.DRAW,
            winner=None,
            reason="fixture_draw",
        ),
        final_state_hash=result_hash,
        visibility=ReplayVisibility(True, ReplayRedaction.NONE),
        provisional_decision_ids=("PD-003",),
        source_manifest_ids=("fixture-source-v1",),
    )

    restored = ReplayRecord.from_json(replay.to_json())

    assert restored == replay
    assert restored.to_json() == replay.to_json()
    assert restored.replay_hash == replay.replay_hash
    assert restored.steps[0].rng_after.cursor == 1
    assert restored.initial_state.payload == state
    assert restored.bundle.engine_semantics_version == "fixture-engine-v1"
    assert restored.provisional_decision_ids == ("PD-003",)
