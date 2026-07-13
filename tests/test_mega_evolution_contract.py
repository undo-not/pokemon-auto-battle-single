from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from champions_sim import (
    BattleEngine,
    SnapshotValidationError,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
    verify_replay,
)
from champions_sim.core import (
    ActionSelection,
    BattleEventKind,
    ExplicitRNG,
    PlayerId,
    ReplayRecord,
    UnsupportedMechanic,
    canonical_hash,
)
from champions_sim.policies import FirstLegalPolicy, ScriptedPolicy
from champions_sim.grounding.env import LegalActionMask
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _profile_hash(profile: dict[str, object]) -> str:
    stats = profile["stats"]
    ivs = profile["ivs"]
    evs = profile["evs"]
    assert isinstance(stats, dict)
    assert isinstance(ivs, dict)
    assert isinstance(evs, dict)

    def long_stats(raw: dict[str, object], *, hp_name: str) -> dict[str, object]:
        return {
            hp_name: raw["hp"],
            "attack": raw["atk"],
            "defense": raw["def"],
            "special_attack": raw["spa"],
            "special_defense": raw["spd"],
            "speed": raw["spe"],
        }

    return canonical_hash(
        {
            "target_pokemon_id": profile["target_pokemon_id"],
            "stats": long_stats(stats, hp_name="max_hp"),
            "level": profile["level"],
            "ivs": long_stats(ivs, hp_name="hp"),
            "evs": long_stats(evs, hp_name="hp"),
            "nature_increased_stat": profile["nature_increased_stat"],
            "nature_decreased_stat": profile["nature_decreased_stat"],
            "derivation_method_id": profile["derivation_method_id"],
            "source_manifest_id": profile["source_manifest_id"],
            "source_record_id": profile["source_record_id"],
        }
    )


def _synthetic_bundle(tmp_path: Path):
    """Build a contract fixture; it intentionally asserts no real M-B form data."""

    catalog = _json(ROOT / "data/fixtures/sim01_catalog.json")
    ruleset = _json(ROOT / "data/fixtures/sim01_ruleset.json")
    battle = _json(ROOT / "data/fixtures/sim01_battle.json")

    abilities = catalog["abilities"]
    items = catalog["items"]
    species = catalog["species"]
    assert isinstance(abilities, list)
    assert isinstance(items, list)
    assert isinstance(species, list)
    items.append(
        {
            "item_id": "fixture_mega_stone",
            "legacy_item_id": None,
            "name": "synthetic test stone",
            "effect_id": "mega_stone",
            "consumable": False,
        }
    )
    species.append(
        {
            "pokemon_id": "fixture_base",
            "legacy_pokemon_id": None,
            "name": "synthetic base form",
            "types": ["dragon", "ground"],
            "ability_ids": ["rough_skin"],
            "legal_move_ids": [
                "earthquake",
                "dragon_claw",
                "swords_dance",
                "flamethrower",
            ],
        }
    )
    species.append(
        {
            "pokemon_id": "fixture_mega",
            "legacy_pokemon_id": None,
            "name": "synthetic transformed form",
            "types": ["water", "dragon"],
            "ability_ids": ["intimidate"],
            "legal_move_ids": [
                "earthquake",
                "dragon_claw",
                "swords_dance",
                "flamethrower",
            ],
        }
    )
    catalog["mega_evolutions"] = [
        {
            "base_pokemon_id": "fixture_base",
            "mega_pokemon_id": "fixture_mega",
            "required_item_id": "fixture_mega_stone",
            "base_stats": {
                "hp": 123,
                "attack": 177,
                "defense": 110,
                "special_attack": 95,
                "special_defense": 100,
                "speed": 149,
            },
            "mega_stats": {
                "hp": 123,
                "attack": 207,
                "defense": 140,
                "special_attack": 110,
                "special_defense": 120,
                "speed": 195,
            },
            "types": ["water", "dragon"],
            "ability_id": "intimidate",
            "source_manifest_id": "synthetic-mega-contract-test-only",
        }
    ]

    supported = ruleset["supported_mechanics"]
    unsupported = ruleset["unsupported_mechanics"]
    assert isinstance(supported, list)
    assert isinstance(unsupported, list)
    supported.append("mega_evolution")
    unsupported.remove("mega_evolution")
    ruleset["mega_evolution"] = {
        "max_uses_per_side": 1,
        "activation_timing": "before_move_ordering",
        "requires_active": True,
        "consumes_item": False,
    }

    sides = battle["sides"]
    assert isinstance(sides, dict)
    p1 = sides["p1"]
    assert isinstance(p1, dict)
    team = p1["team"]
    assert isinstance(team, list)
    active = team[0]
    assert isinstance(active, dict)
    active["pokemon_id"] = "fixture_base"
    active["item_id"] = "fixture_mega_stone"
    profile: dict[str, object] = {
        "target_pokemon_id": "fixture_mega",
        "stats": {
            "hp": 183,
            "atk": 212,
            "def": 145,
            "spa": 115,
            "spd": 125,
            "spe": 200,
        },
        "level": 50,
        "ivs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        "evs": {"hp": 0, "atk": 0, "def": 0, "spa": 0, "spd": 0, "spe": 0},
        "nature_increased_stat": None,
        "nature_decreased_stat": None,
        "derivation_method_id": "pokemon-mainline-stat-v1",
        "source_manifest_id": "synthetic-mega-contract-test-only",
        "source_record_id": "synthetic-build-profile-test-only",
        "profile_hash": "",
    }
    profile["profile_hash"] = _profile_hash(profile)
    active["mega_evolution_profile"] = profile

    catalog_path = tmp_path / "catalog.json"
    ruleset_path = tmp_path / "ruleset.json"
    battle_path = tmp_path / "battle.json"
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    ruleset_path.write_text(json.dumps(ruleset), encoding="utf-8")
    battle_path.write_text(json.dumps(battle), encoding="utf-8")
    loaded_catalog = load_catalog(catalog_path)
    loaded_ruleset = load_ruleset(ruleset_path)
    loaded_battle = load_battle_fixture(
        battle_path,
        catalog=loaded_catalog,
        ruleset=loaded_ruleset,
    )
    return loaded_catalog, loaded_ruleset, loaded_battle, catalog_path, battle_path


def _selections(engine: BattleEngine, state, wanted: dict[PlayerId, str]):
    requests = engine.required_decisions(state)
    assert requests is not None
    result = []
    for request in requests.requests:
        suffix = wanted[request.player]
        action = next(
            action
            for action in request.legal_actions
            if action.action_id.endswith(f":{suffix}")
        )
        result.append(
            ActionSelection(request.request_id, request.player, action.action_id)
        )
    return tuple(result)


def test_mega_evolution_is_explicit_pre_move_persistent_and_once_per_side(
    tmp_path: Path,
) -> None:
    catalog, ruleset, battle, _, _ = _synthetic_bundle(tmp_path)
    engine = BattleEngine(catalog, ruleset)
    initialized = engine.initialize(battle.initial_state, battle.rng)
    requests = initialized.next_decisions
    assert requests is not None
    p1_actions = requests.for_player(PlayerId.P1)
    assert p1_actions is not None
    assert len(
        [action for action in p1_actions.legal_actions if ":mega:" in action.action_id]
    ) == 4
    action_space = tuple(action.action_id for action in p1_actions.legal_actions)
    mask = LegalActionMask.from_request(p1_actions, action_space)
    assert any(
        is_legal and ":mega:" in action_id
        for action_id, is_legal in zip(mask.action_ids, mask.legal, strict=True)
    )

    evolved = engine.advance(
        initialized.state,
        _selections(
            engine,
            initialized.state,
            {
                PlayerId.P1: "move:earthquake:mega:fixture_mega",
                PlayerId.P2: "move:dragon_dance",
            },
        ),
        initialized.rng,
    )
    event_kinds = [event.kind for event in evolved.events]
    assert event_kinds.index(BattleEventKind.MEGA_EVOLVED) < event_kinds.index(
        BattleEventKind.ACTION_ORDERED
    )
    assert event_kinds.index(BattleEventKind.MEGA_EVOLVED) < event_kinds.index(
        BattleEventKind.MOVE_USED
    )
    active = evolved.state.side(PlayerId.P1).active
    assert active.pokemon_id == "fixture_mega"
    assert active.stats.speed == 200
    assert active.types == ("water", "dragon")
    assert active.ability_id == "intimidate"
    assert active.item_id == "fixture_mega_stone"
    assert active.mega_evolved
    assert active.mega_evolution_profile is not None
    observation = evolved.state.observation_for(PlayerId.P2)
    assert observation.opponent_side.mega_evolution_used
    assert observation.opponent_side.pokemon[0].mega_evolved

    switched_out = engine.advance(
        evolved.state,
        _selections(
            engine,
            evolved.state,
            {
                PlayerId.P1: "switch:p1-starmie",
                PlayerId.P2: "move:dragon_dance",
            },
        ),
        evolved.rng,
    )
    switched_back = engine.advance(
        switched_out.state,
        _selections(
            engine,
            switched_out.state,
            {
                PlayerId.P1: "switch:p1-garchomp",
                PlayerId.P2: "move:dragon_dance",
            },
        ),
        switched_out.rng,
    )
    returned = switched_back.state.side(PlayerId.P1).active
    assert returned.pokemon_id == "fixture_mega"
    assert returned.mega_evolved
    legal = engine.legal_actions(switched_back.state, PlayerId.P1)
    assert not any(":mega:" in action.action_id for action in legal)


def test_mega_catalog_ruleset_and_battle_extensions_match_schemas(
    tmp_path: Path,
) -> None:
    _synthetic_bundle(tmp_path)
    cases = (
        ("catalog", tmp_path / "catalog.json", "catalog.schema.json"),
        ("ruleset", tmp_path / "ruleset.json", "ruleset.schema.json"),
        ("battle", tmp_path / "battle.json", "battle-fixture.schema.json"),
    )
    for label, document_path, schema_name in cases:
        validate_document_contract(
            _json(document_path),
            _json(ROOT / "data/schemas" / schema_name),
            label,
        )


def test_mega_action_and_state_roundtrip_through_replay_v2(tmp_path: Path) -> None:
    catalog, ruleset, battle, _, _ = _synthetic_bundle(tmp_path)
    engine = BattleEngine(catalog, ruleset)
    policies = {
        PlayerId.P1: ScriptedPolicy(
            {PlayerId.P1: ("move:earthquake:mega:fixture_mega",)}
        ),
        PlayerId.P2: FirstLegalPolicy(),
    }
    run = run_battle(
        engine,
        battle.initial_state,
        seed=battle.rng.seed,
        policies=policies,
    )
    payload = run.replay.to_json()
    validate_document_contract(
        json.loads(payload),
        _json(ROOT / "data/schemas/replay.schema.json"),
        "replay",
    )
    restored = ReplayRecord.from_json(payload)
    assert restored.to_json() == payload
    assert any(
        ":mega:" in selection.action_id
        for step in restored.steps
        for selection in step.selections
    )
    assert any(
        event.kind is BattleEventKind.MEGA_EVOLVED
        for step in restored.steps
        for event in step.events
    )
    verified = verify_replay(engine, restored)
    assert verified == run.final_state

    for path in ("root", "nested_pokemon"):
        unknown = json.loads(payload)
        if path == "root":
            unknown["future_security_critical_flag"] = True
        else:
            unknown["initial_state"]["payload"]["sides"][0]["team"][0][
                "future_security_critical_flag"
            ] = True
        with pytest.raises(ValueError, match="unknown fields"):
            ReplayRecord.from_json(json.dumps(unknown))


def test_wrong_item_generates_no_mega_action(tmp_path: Path) -> None:
    catalog, ruleset, battle, _, _ = _synthetic_bundle(tmp_path)
    side = battle.initial_state.side(PlayerId.P1)
    active = replace(
        side.active,
        item_id="leftovers",
        mega_evolution_profile=None,
    )
    team = tuple(active if member is side.active else member for member in side.team)
    replacement = replace(side, team=team)
    state = replace(
        battle.initial_state,
        sides=(replacement, battle.initial_state.side(PlayerId.P2)),
    )
    engine = BattleEngine(catalog, ruleset)
    initialized = engine.initialize(state, ExplicitRNG.seeded(1))
    legal = engine.legal_actions(initialized.state, PlayerId.P1)
    assert not any(":mega:" in action.action_id for action in legal)


def test_missing_exact_build_stats_and_unknown_target_fail_closed(
    tmp_path: Path,
) -> None:
    catalog, ruleset, _, catalog_path, battle_path = _synthetic_bundle(tmp_path)
    battle_raw = _json(battle_path)
    sides = battle_raw["sides"]
    assert isinstance(sides, dict)
    p1 = sides["p1"]
    assert isinstance(p1, dict)
    team = p1["team"]
    assert isinstance(team, list)
    active = team[0]
    assert isinstance(active, dict)
    del active["mega_evolution_profile"]
    missing_path = tmp_path / "missing-stats.json"
    missing_path.write_text(json.dumps(battle_raw), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="mega_evolution_profile"):
        load_battle_fixture(missing_path, catalog=catalog, ruleset=ruleset)

    catalog_raw = _json(catalog_path)
    relations = catalog_raw["mega_evolutions"]
    assert isinstance(relations, list)
    relation = relations[0]
    assert isinstance(relation, dict)
    relation["mega_pokemon_id"] = "missing_target"
    unknown_path = tmp_path / "unknown-target.json"
    unknown_path.write_text(json.dumps(catalog_raw), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="unknown reference"):
        load_catalog(unknown_path)


def test_rehashed_9999_attack_profile_is_rejected_by_versioned_derivation(
    tmp_path: Path,
) -> None:
    catalog, ruleset, _, _, battle_path = _synthetic_bundle(tmp_path)
    battle_raw = _json(battle_path)
    profile = battle_raw["sides"]["p1"]["team"][0]["mega_evolution_profile"]
    assert isinstance(profile, dict)
    stats = profile["stats"]
    assert isinstance(stats, dict)
    stats["atk"] = 9999
    profile["profile_hash"] = _profile_hash(profile)
    attacked_path = tmp_path / "rehashed-9999.json"
    attacked_path.write_text(json.dumps(battle_raw), encoding="utf-8")
    with pytest.raises(SnapshotValidationError, match="derivation inputs"):
        load_battle_fixture(attacked_path, catalog=catalog, ruleset=ruleset)


def test_simultaneous_mega_order_is_fail_closed_until_grounded(
    tmp_path: Path,
) -> None:
    catalog, ruleset, _, _, battle_path = _synthetic_bundle(tmp_path)
    battle_raw = _json(battle_path)
    sides = battle_raw["sides"]
    assert isinstance(sides, dict)
    p2 = sides["p2"]
    assert isinstance(p2, dict)
    team = p2["team"]
    assert isinstance(team, list)
    active = team[0]
    assert isinstance(active, dict)
    active.update(
        {
            "pokemon_id": "fixture_base",
            "ability_id": "rough_skin",
            "item_id": "fixture_mega_stone",
            "moves": [
                "earthquake",
                "dragon_claw",
                "swords_dance",
                "flamethrower",
            ],
            "stats": {"hp": 183, "atk": 182, "def": 115, "spa": 100, "spd": 105, "spe": 154},
            "mega_evolution_profile": _json(battle_path)["sides"]["p1"]["team"][0]["mega_evolution_profile"],
        }
    )
    two_sided_path = tmp_path / "two-sided-mega.json"
    two_sided_path.write_text(json.dumps(battle_raw), encoding="utf-8")
    battle = load_battle_fixture(
        two_sided_path,
        catalog=catalog,
        ruleset=ruleset,
    )
    engine = BattleEngine(catalog, ruleset)
    initialized = engine.initialize(battle.initial_state, battle.rng)
    selections = _selections(
        engine,
        initialized.state,
        {
            PlayerId.P1: "move:earthquake:mega:fixture_mega",
            PlayerId.P2: "move:earthquake:mega:fixture_mega",
        },
    )
    with pytest.raises(UnsupportedMechanic, match="simultaneous_order"):
        engine.advance(initialized.state, selections, initialized.rng)


def test_catalog_mega_form_cannot_enter_state_without_transition_marker(
    tmp_path: Path,
) -> None:
    catalog, ruleset, battle, _, _ = _synthetic_bundle(tmp_path)
    side = battle.initial_state.side(PlayerId.P1)
    active = replace(
        side.active,
        pokemon_id="fixture_mega",
        types=("water", "dragon"),
        ability_id="intimidate",
        mega_evolution_profile=None,
    )
    team = tuple(active if member is side.active else member for member in side.team)
    state = replace(
        battle.initial_state,
        sides=(
            replace(side, team=team),
            battle.initial_state.side(PlayerId.P2),
        ),
    )
    with pytest.raises(UnsupportedMechanic, match="unmarked_target_form"):
        BattleEngine(catalog, ruleset).initialize(state, battle.rng)
