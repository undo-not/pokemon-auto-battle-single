import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from champions_sim.core import (  # noqa: E402
    AbilityId,
    BattlePhase,
    BattleState,
    ItemId,
    MoveId,
    MoveSlotState,
    PlayerId,
    PokemonId,
    PokemonInstanceId,
    PokemonState,
    RuleSetId,
    SideState,
    StatBlock,
    canonical_json,
)


def _pokemon(
    owner: str,
    slot: int,
    *,
    revealed: bool,
    move_revealed: bool = False,
    item_revealed: bool = False,
    ability_revealed: bool = False,
) -> PokemonState:
    return PokemonState(
        instance_id=PokemonInstanceId(f"{owner}-slot-{slot}"),
        pokemon_id=PokemonId(f"{owner}-species-{slot}"),
        level=50,
        hp=150 - slot,
        stats=StatBlock(150, 100, 101, 102, 103, 104),
        types=("normal",),
        moves=(
            MoveSlotState(
                move_id=MoveId(f"{owner}-secret-move-{slot}"),
                pp=9,
                max_pp=10,
                revealed_to_opponent=move_revealed,
            ),
        ),
        item_id=ItemId(f"{owner}-secret-item-{slot}"),
        ability_id=AbilityId(f"{owner}-secret-ability-{slot}"),
        revealed_to_opponent=revealed,
        item_revealed_to_opponent=item_revealed,
        ability_revealed_to_opponent=ability_revealed,
    )


def _state() -> BattleState:
    p1_team = tuple(
        _pokemon("p1", slot, revealed=slot == 1) for slot in range(1, 4)
    )
    p2_team = (
        _pokemon("p2", 1, revealed=True, move_revealed=True),
        _pokemon("p2", 2, revealed=False),
        _pokemon("p2", 3, revealed=False),
    )
    return BattleState(
        battle_id="observation-test",
        ruleset_id=RuleSetId("fixture-rules-v1"),
        turn=3,
        phase=BattlePhase.AWAITING_DECISIONS,
        sides=(
            SideState(PlayerId.P1, p1_team, p1_team[0].instance_id),
            SideState(PlayerId.P2, p2_team, p2_team[0].instance_id),
        ),
    )


def test_observation_hides_unrevealed_opponent_bench_and_private_fields() -> None:
    observation = _state().observation_for(PlayerId.P1)

    assert len(observation.own_side.pokemon) == 3
    assert len(observation.opponent_side.pokemon) == 1
    assert observation.opponent_side.unrevealed_count == 2

    active = observation.opponent_side.pokemon[0]
    assert active.pokemon_id == PokemonId("p2-species-1")
    assert tuple(move.move_id for move in active.moves) == (
        MoveId("p2-secret-move-1"),
    )
    assert active.moves[0].pp is None
    assert active.moves[0].max_pp is None
    assert active.item_id is None
    assert active.ability_id is None
    assert active.hp is None
    assert active.max_hp is None
    assert active.hp_fraction_millionths is None
    assert active.stats is None

    encoded = canonical_json(observation)
    for hidden_value in (
        "p2-species-2",
        "p2-species-3",
        "p2-secret-move-2",
        "p2-secret-move-3",
        "p2-secret-item-1",
        "p2-secret-ability-1",
    ):
        assert hidden_value not in encoded


def test_owner_always_observes_own_complete_team() -> None:
    observation = _state().observation_for(PlayerId.P2)
    own_second = observation.own_side.pokemon[1]

    assert own_second.pokemon_id == PokemonId("p2-species-2")
    assert own_second.moves[0].pp == 9
    assert own_second.item_id == ItemId("p2-secret-item-2")
    assert own_second.ability_id == AbilityId("p2-secret-ability-2")
    assert own_second.stats is not None
    assert own_second.hp_fraction_millionths == (148 * 1_000_000) // 150
