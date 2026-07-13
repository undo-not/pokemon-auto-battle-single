from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from champions_sim import (  # noqa: E402
    BattleEngine,
    IllegalAction,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
)
from champions_sim.catalog import (  # noqa: E402
    AbilityDefinition,
    CatalogSnapshot,
    ItemDefinition,
    RuleSetSnapshot,
)
from champions_sim.core import (  # noqa: E402
    ActionSelection,
    AbilityId,
    BattleEvent,
    BattleEventKind,
    BattlePhase,
    BattleState,
    DecisionKind,
    ExplicitRNG,
    ItemId,
    PlayerId,
    PokemonInstanceId,
    PokemonState,
    StatStages,
    UnsupportedMechanic,
    canonical_hash,
    canonical_json,
)
from champions_sim.fixtures import LoadedBattleFixture  # noqa: E402


@pytest.fixture(scope="module")
def sim() -> tuple[BattleEngine, LoadedBattleFixture, CatalogSnapshot, RuleSetSnapshot]:
    catalog = load_catalog(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json")
    battle = load_battle_fixture(
        ROOT / "data/fixtures/sim01_battle.json",
        catalog=catalog,
        ruleset=ruleset,
    )
    return BattleEngine(catalog, ruleset), battle, catalog, ruleset


def _put_member(
    state: BattleState,
    player: PlayerId,
    instance_id: str,
    **changes: object,
) -> BattleState:
    side = state.side(player)
    key = PokemonInstanceId(instance_id)
    updated = replace(side.pokemon(key), **changes)
    team = tuple(updated if member.instance_id == key else member for member in side.team)
    replacement = replace(side, team=team)
    sides = tuple(replacement if value.player is player else value for value in state.sides)
    return replace(state, sides=sides)  # type: ignore[arg-type]


def _set_active(state: BattleState, player: PlayerId, instance_id: str) -> BattleState:
    side = state.side(player)
    replacement = replace(side, active_instance_id=PokemonInstanceId(instance_id))
    sides = tuple(replacement if value.player is player else value for value in state.sides)
    return replace(state, sides=sides)  # type: ignore[arg-type]


def _selections(
    engine: BattleEngine,
    state: BattleState,
    wanted: dict[PlayerId, str],
) -> tuple[ActionSelection, ...]:
    requests = engine.required_decisions(state)
    assert requests is not None
    selections: list[ActionSelection] = []
    for request in requests.requests:
        suffix = wanted[request.player]
        action = next(
            candidate
            for candidate in request.legal_actions
            if candidate.action_id == suffix or candidate.action_id.endswith(f":{suffix}")
        )
        selections.append(
            ActionSelection(request.request_id, request.player, action.action_id)
        )
    return tuple(selections)


def _advance(
    engine: BattleEngine,
    state: BattleState,
    rng: ExplicitRNG,
    wanted: dict[PlayerId, str],
):
    return engine.advance(state, _selections(engine, state, wanted), rng)


def _event_details(event: BattleEvent) -> dict[str, str | int | bool | None]:
    return dict(event.details)


def _ordered_players(events: tuple[BattleEvent, ...]) -> list[PlayerId | None]:
    return [event.actor for event in events if event.kind is BattleEventKind.ACTION_ORDERED]


def test_same_state_seed_and_actions_are_deterministic_and_branch_safe(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(91))
    root_state = initialized.state
    root_rng = initialized.rng
    root_hash = canonical_hash(root_state)

    boost_actions = _selections(
        engine,
        root_state,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:dragon_dance"},
    )
    attack_actions = _selections(
        engine,
        root_state,
        {PlayerId.P1: "move:dragon_claw", PlayerId.P2: "move:waterfall"},
    )
    boost_a = engine.advance(root_state, boost_actions, root_rng)
    attack = engine.advance(root_state, attack_actions, root_rng)
    boost_b = engine.advance(root_state, boost_actions, root_rng)

    assert canonical_hash(root_state) == root_hash
    assert root_rng.cursor == 0
    assert canonical_hash(boost_a.state) == canonical_hash(boost_b.state)
    assert boost_a.events == boost_b.events
    assert boost_a.rng == boost_b.rng
    assert canonical_hash(boost_a.state) != canonical_hash(attack.state)


def test_drain_move_heals_from_actual_damage_when_target_faints(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(419))
    state = _set_active(initialized.state, PlayerId.P2, "p2-venusaur")
    state = _put_member(state, PlayerId.P2, "p2-venusaur", hp=50)
    state = _put_member(state, PlayerId.P1, "p1-garchomp", hp=1)

    result = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:giga_drain"},
    )

    assert result.state.side(PlayerId.P1).active.fainted
    assert result.state.side(PlayerId.P2).active.hp == 51
    assert any(
        event.kind is BattleEventKind.HEALED
        and event.subject == PokemonInstanceId("p2-venusaur")
        and _event_details(event).get("source") == "giga_drain"
        for event in result.events
    )


def test_remaining_targeted_move_fails_without_rng_after_rough_skin_self_ko(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(811))
    state = _put_member(
        initialized.state,
        PlayerId.P2,
        "p2-gyarados",
        hp=1,
        stat_stages=StatStages(speed=6),
    )

    result = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:dragon_claw", PlayerId.P2: "move:aqua_tail"},
    )

    assert result.state.side(PlayerId.P2).active.fainted
    failures = [
        _event_details(event)
        for event in result.events
        if event.kind is BattleEventKind.ACTION_FAILED and event.actor is PlayerId.P1
    ]
    assert failures == [{"move_id": "dragon_claw", "reason": "no_target"}]
    p1_move = next(
        move
        for move in result.state.side(PlayerId.P1).active.moves
        if str(move.move_id) == "dragon_claw"
    )
    assert p1_move.pp == p1_move.max_pp - 1
    p1_action_position = next(
        event.sequence
        for event in result.events
        if event.kind is BattleEventKind.MOVE_USED and event.actor is PlayerId.P1
    )
    assert not any(
        event.kind is BattleEventKind.RNG_DRAW and event.sequence > p1_action_position
        for event in result.events
    )


def test_engine_observation_does_not_leak_hidden_bench_or_private_fields(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(13))
    result = _advance(
        engine,
        initialized.state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:dragon_dance"},
    )

    observation = result.state.observation_for(PlayerId.P1)
    encoded = canonical_json(observation.opponent_side)
    opponent = observation.opponent_side.pokemon[0]

    assert observation.opponent_side.unrevealed_count == 2
    assert [str(move.move_id) for move in opponent.moves] == ["dragon_dance"]
    assert opponent.moves[0].pp is None
    assert opponent.item_id is None
    assert str(opponent.ability_id) == "intimidate"
    for hidden in (
        "p2-venusaur",
        "p2-charizard",
        "sludge_bomb",
        "giga_drain",
        "will_o_wisp",
        "sitrus_berry",
        "focus_sash",
        "overgrow",
        "blaze",
    ):
        assert hidden not in encoded


def test_illegal_or_stale_selections_are_rejected_without_mutation(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(17))
    state = initialized.state
    rng = initialized.rng
    before = canonical_hash(state)
    requests = engine.required_decisions(state)
    assert requests is not None
    valid = _selections(
        engine,
        state,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:dragon_dance"},
    )

    bad_cases = (
        valid[:1],
        (
            valid[0],
            ActionSelection(valid[0].request_id, PlayerId.P1, valid[0].action_id),
        ),
        (
            replace(valid[0], request_id="stale:turn:0:p1"),
            valid[1],
        ),
        (
            replace(valid[0], action_id="p1:move:invented_move"),
            valid[1],
        ),
    )
    for selections in bad_cases:
        with pytest.raises(IllegalAction):
            engine.advance(state, selections, rng)
        assert canonical_hash(state) == before
        assert rng.cursor == 0


def test_one_sided_forced_switch_requests_only_the_fainted_side(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(0))
    state = _put_member(
        initialized.state,
        PlayerId.P2,
        "p2-gyarados",
        hp=1,
    )
    knocked_out = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:dragon_claw", PlayerId.P2: "move:dragon_dance"},
    )

    assert knocked_out.state.phase is BattlePhase.FORCED_SWITCH
    assert knocked_out.next_decisions is not None
    assert len(knocked_out.next_decisions.requests) == 1
    request = knocked_out.next_decisions.requests[0]
    assert request.player is PlayerId.P2
    assert request.kind is DecisionKind.FORCED_SWITCH

    replaced_result = _advance(
        engine,
        knocked_out.state,
        knocked_out.rng,
        {PlayerId.P2: "switch:p2-venusaur"},
    )
    assert replaced_result.state.phase is BattlePhase.AWAITING_DECISIONS
    assert replaced_result.state.turn == 2
    assert str(replaced_result.state.side(PlayerId.P2).active_instance_id) == "p2-venusaur"


def test_double_forced_switch_is_simultaneous_and_replaces_both_sides(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(0))
    state = _put_member(
        initialized.state,
        PlayerId.P1,
        "p1-garchomp",
        hp=1,
        status_id="burn",
    )
    state = _put_member(
        state,
        PlayerId.P2,
        "p2-gyarados",
        hp=1,
        status_id="poison",
    )
    double_knockout = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:dragon_dance"},
    )

    assert double_knockout.state.phase is BattlePhase.FORCED_SWITCH
    assert double_knockout.next_decisions is not None
    assert double_knockout.next_decisions.simultaneous
    assert {request.player for request in double_knockout.next_decisions.requests} == {
        PlayerId.P1,
        PlayerId.P2,
    }

    replacements = _advance(
        engine,
        double_knockout.state,
        double_knockout.rng,
        {
            PlayerId.P1: "switch:p1-starmie",
            PlayerId.P2: "switch:p2-venusaur",
        },
    )
    assert replacements.state.phase is BattlePhase.AWAITING_DECISIONS
    assert str(replacements.state.side(PlayerId.P1).active_instance_id) == "p1-starmie"
    assert str(replacements.state.side(PlayerId.P2).active_instance_id) == "p2-venusaur"


def test_rough_skin_holder_wins_when_both_last_pokemon_faint(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(991))
    state = initialized.state
    for instance_id in ("p1-starmie", "p1-scizor"):
        state = _put_member(state, PlayerId.P1, instance_id, hp=0)
    for instance_id in ("p2-venusaur", "p2-charizard"):
        state = _put_member(state, PlayerId.P2, instance_id, hp=0)
    state = _put_member(state, PlayerId.P1, "p1-garchomp", hp=1)
    state = _put_member(
        state,
        PlayerId.P2,
        "p2-gyarados",
        hp=1,
        stat_stages=StatStages(speed=6),
    )

    result = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:dragon_claw", PlayerId.P2: "move:aqua_tail"},
    )

    assert result.terminal
    assert result.winner is PlayerId.P1
    ended = next(event for event in result.events if event.kind is BattleEventKind.BATTLE_ENDED)
    assert _event_details(ended)["reason"] == "rough_skin_simultaneous_faint"


def test_residual_double_faint_uses_recorded_speed_order(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(992))
    state = initialized.state
    for instance_id in ("p1-starmie", "p1-scizor"):
        state = _put_member(state, PlayerId.P1, instance_id, hp=0)
    for instance_id in ("p2-venusaur", "p2-charizard"):
        state = _put_member(state, PlayerId.P2, instance_id, hp=0)
    state = _put_member(
        state, PlayerId.P1, "p1-garchomp", hp=1, status_id="burn"
    )
    state = _put_member(
        state,
        PlayerId.P2,
        "p2-gyarados",
        hp=1,
        status_id="burn",
        stat_stages=StatStages(speed=-1),
    )

    result = _advance(
        engine,
        state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:dragon_dance"},
    )

    assert result.terminal
    assert result.winner is PlayerId.P2
    ended = next(event for event in result.events if event.kind is BattleEventKind.BATTLE_ENDED)
    assert _event_details(ended)["reason"] == "ordered_simultaneous_faint"


def test_priority_precedes_speed_and_equal_priority_uses_speed(sim) -> None:
    engine, battle, _, _ = sim
    normal = engine.initialize(battle.initial_state, ExplicitRNG.seeded(4))
    speed_order = _advance(
        engine,
        normal.state,
        normal.rng,
        {PlayerId.P1: "move:dragon_claw", PlayerId.P2: "move:aqua_tail"},
    )
    assert _ordered_players(speed_order.events) == [PlayerId.P1, PlayerId.P2]

    priority_state = _set_active(battle.initial_state, PlayerId.P1, "p1-scizor")
    priority_state = _set_active(priority_state, PlayerId.P2, "p2-charizard")
    priority = engine.initialize(priority_state, ExplicitRNG.seeded(4))
    priority_order = _advance(
        engine,
        priority.state,
        priority.rng,
        {PlayerId.P1: "move:bullet_punch", PlayerId.P2: "move:flamethrower"},
    )
    assert priority.state.side(PlayerId.P1).active.stats.speed < priority.state.side(PlayerId.P2).active.stats.speed
    assert _ordered_players(priority_order.events) == [PlayerId.P1, PlayerId.P2]


def test_switch_in_contact_and_end_turn_effects_are_integrated(sim) -> None:
    engine, battle, _, _ = sim
    initialized = engine.initialize(battle.initial_state, ExplicitRNG.seeded(1))

    assert initialized.state.side(PlayerId.P1).active.stat_stages.attack == -1
    assert initialized.state.side(PlayerId.P2).active.ability_revealed_to_opponent
    assert any(
        event.kind is BattleEventKind.ABILITY_TRIGGERED
        and _event_details(event).get("ability_id") == "intimidate"
        for event in initialized.events
    )

    result = _advance(
        engine,
        initialized.state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:waterfall"},
    )
    ability_ids = {
        _event_details(event).get("ability_id")
        for event in result.events
        if event.kind is BattleEventKind.ABILITY_TRIGGERED
    }
    item_ids = {
        _event_details(event).get("item_id")
        for event in result.events
        if event.kind is BattleEventKind.ITEM_TRIGGERED
    }
    assert "rough_skin" in ability_ids
    assert item_ids == {"leftovers"}
    assert result.state.side(PlayerId.P1).active.item_revealed_to_opponent
    assert result.state.side(PlayerId.P2).active.item_revealed_to_opponent


def test_runtime_dispatch_uses_catalog_effect_ids_not_literal_entity_ids(sim) -> None:
    _, battle, catalog, ruleset = sim
    alias_ability = AbilityDefinition(
        ability_id=AbilityId("alias_intimidate"),
        name="alias intimidate",
        effect_id="intimidate",
    )
    alias_item = ItemDefinition(
        item_id=ItemId("alias_leftovers"),
        name="alias leftovers",
        effect_id="leftovers",
    )
    species = tuple(
        replace(
            value,
            ability_ids=value.ability_ids + (alias_ability.ability_id,),
        )
        if str(value.pokemon_id) == "gyarados"
        else value
        for value in catalog.species
    )
    alias_catalog = replace(
        catalog,
        abilities=catalog.abilities + (alias_ability,),
        items=catalog.items + (alias_item,),
        species=species,
    )
    engine = BattleEngine(alias_catalog, ruleset)
    state = _put_member(
        battle.initial_state,
        PlayerId.P2,
        "p2-gyarados",
        ability_id=alias_ability.ability_id,
    )
    state = _put_member(
        state,
        PlayerId.P1,
        "p1-garchomp",
        item_id=alias_item.item_id,
    )
    initialized = engine.initialize(state, ExplicitRNG.seeded(1))
    assert initialized.state.side(PlayerId.P1).active.stat_stages.attack == -1

    result = _advance(
        engine,
        initialized.state,
        initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:waterfall"},
    )
    assert any(
        event.kind is BattleEventKind.ITEM_TRIGGERED
        and _event_details(event).get("item_id") == "alias_leftovers"
        for event in result.events
    )


def test_focus_sash_and_sitrus_berry_trigger_and_are_consumed(sim) -> None:
    engine, battle, _, _ = sim

    sash_state = _set_active(battle.initial_state, PlayerId.P1, "p1-scizor")
    sash_user = sash_state.side(PlayerId.P1).active
    sash_state = _put_member(
        sash_state,
        PlayerId.P1,
        "p1-scizor",
        stats=replace(sash_user.stats, max_hp=10),
        hp=10,
    )
    sash_initialized = engine.initialize(sash_state, ExplicitRNG.seeded(2))
    sash_result = _advance(
        engine,
        sash_initialized.state,
        sash_initialized.rng,
        {PlayerId.P1: "move:swords_dance", PlayerId.P2: "move:earthquake"},
    )
    sash_after = sash_result.state.side(PlayerId.P1).active
    assert sash_after.hp == 1
    assert sash_after.item_id is None
    assert str(sash_after.consumed_item_id) == "focus_sash"
    sash_observed = sash_result.state.observation_for(PlayerId.P2).opponent_side.pokemon[0]
    assert str(sash_observed.consumed_item_id) == "focus_sash"
    assert {
        event.kind
        for event in sash_result.events
        if _event_details(event).get("item_id") == "focus_sash"
    } == {BattleEventKind.ITEM_TRIGGERED, BattleEventKind.ITEM_CONSUMED}

    berry_state = _set_active(battle.initial_state, PlayerId.P1, "p1-starmie")
    berry_state = _put_member(berry_state, PlayerId.P1, "p1-starmie", hp=70)
    berry_initialized = engine.initialize(berry_state, ExplicitRNG.seeded(2))
    berry_result = _advance(
        engine,
        berry_initialized.state,
        berry_initialized.rng,
        {PlayerId.P1: "move:psychic", PlayerId.P2: "move:waterfall"},
    )
    berry_after = berry_result.state.side(PlayerId.P1).active
    assert berry_after.hp == 62
    assert berry_after.item_id is None
    assert str(berry_after.consumed_item_id) == "sitrus_berry"
    assert any(
        event.kind is BattleEventKind.HEALED
        and _event_details(event).get("source") == "sitrus_berry"
        for event in berry_result.events
    )


def test_burn_residual_and_natural_cure_switch_are_integrated(sim) -> None:
    engine, battle, _, _ = sim
    state = _set_active(battle.initial_state, PlayerId.P1, "p1-starmie")
    state = _set_active(state, PlayerId.P2, "p2-charizard")
    initialized = engine.initialize(state, ExplicitRNG.seeded(0))
    burned = _advance(
        engine,
        initialized.state,
        initialized.rng,
        {PlayerId.P1: "move:psychic", PlayerId.P2: "move:will_o_wisp"},
    )
    starmie = burned.state.side(PlayerId.P1).active
    assert starmie.status_id == "burn"
    assert starmie.hp == starmie.stats.max_hp - 8
    assert any(
        event.kind is BattleEventKind.DAMAGE
        and _event_details(event).get("source") == "burn"
        for event in burned.events
    )

    switched = _advance(
        engine,
        burned.state,
        burned.rng,
        {PlayerId.P1: "switch:p1-garchomp", PlayerId.P2: "move:air_slash"},
    )
    benched_starmie = switched.state.side(PlayerId.P1).pokemon(
        PokemonInstanceId("p1-starmie")
    )
    assert benched_starmie.status_id is None
    assert benched_starmie.ability_revealed_to_opponent
    assert any(
        event.kind is BattleEventKind.ABILITY_TRIGGERED
        and _event_details(event).get("ability_id") == "natural_cure"
        for event in switched.events
    )


def test_unknown_catalog_effect_is_rejected_before_battle(sim) -> None:
    _, _, catalog, ruleset = sim
    bad_move = replace(catalog.moves[0], effect={"kind": "set_weather"})
    bad_catalog = replace(catalog, moves=(bad_move,) + catalog.moves[1:])

    with pytest.raises(UnsupportedMechanic, match="move_effect:set_weather"):
        BattleEngine(bad_catalog, ruleset)


@pytest.mark.parametrize(
    ("mutation", "mechanic"),
    (
        ("field", "field_condition:weather:rain"),
        ("status", "status:sleep"),
        ("volatile", "volatile_status:confusion"),
    ),
)
def test_unsupported_state_fails_closed_on_initialize(sim, mutation: str, mechanic: str) -> None:
    engine, battle, _, _ = sim
    state = battle.initial_state
    if mutation == "field":
        state = replace(state, field_conditions=("weather:rain",))
    elif mutation == "status":
        state = _put_member(state, PlayerId.P1, "p1-garchomp", status_id="sleep")
    else:
        state = _put_member(
            state,
            PlayerId.P1,
            "p1-garchomp",
            volatile_statuses=("confusion",),
        )

    with pytest.raises(UnsupportedMechanic) as raised:
        engine.initialize(state, ExplicitRNG.seeded(0))
    assert raised.value.mechanic_id == mechanic
