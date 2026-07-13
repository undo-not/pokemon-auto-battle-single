"""Load the bounded SIM-01 battle fixture into complete core state."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import (
    CatalogSnapshot,
    RuleSetSnapshot,
    SnapshotValidationError,
    validate_mega_stat_profile,
)
from .core import (
    AbilityId,
    BattlePhase,
    BattleState,
    ExplicitRNG,
    ItemId,
    MoveId,
    MoveSlotState,
    MegaEvolutionStatProfile,
    PlayerId,
    PokemonId,
    PokemonInstanceId,
    PokemonState,
    RuleSetId,
    SideState,
    StatBlock,
    TrainingStatBlock,
)


@dataclass(frozen=True, slots=True)
class LoadedBattleFixture:
    initial_state: BattleState
    rng: ExplicitRNG
    catalog_id: str
    catalog_hash: str
    ruleset_id: RuleSetId
    ruleset_hash: str
    engine_semantics_version: str
    provisional_decision_ids: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]


def load_battle_fixture(
    path: Path | str,
    *,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> LoadedBattleFixture:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SnapshotValidationError("battle fixture root must be an object")
    if raw.get("catalog_id") != catalog.catalog_id:
        raise SnapshotValidationError("battle fixture catalog_id mismatch")
    if raw.get("ruleset_id") != ruleset.ruleset_id:
        raise SnapshotValidationError("battle fixture ruleset_id mismatch")

    sides = tuple(
        _side(PlayerId(player), raw["sides"][player], catalog, ruleset)
        for player in ("p1", "p2")
    )
    state = BattleState(
        battle_id=str(raw["battle_id"]),
        ruleset_id=RuleSetId(str(raw["ruleset_id"])),
        turn=0,
        phase=BattlePhase.TEAM_PREVIEW,
        sides=sides,  # type: ignore[arg-type]
    )
    seed = int(raw["seed"])
    return LoadedBattleFixture(
        initial_state=state,
        rng=ExplicitRNG.seeded(seed),
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=ruleset.ruleset_id,
        ruleset_hash=ruleset.snapshot_hash,
        engine_semantics_version=ruleset.engine_semantics_version,
        provisional_decision_ids=ruleset.provisional_decision_ids,
        source_manifest_ids=tuple(
            sorted({catalog.source_manifest_id, *ruleset.source_manifest_ids})
        ),
    )


def _side(
    player: PlayerId,
    raw: dict[str, Any],
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> SideState:
    team = tuple(_pokemon(item, catalog, ruleset) for item in raw["team"])
    if len(team) != ruleset.team_size:
        raise SnapshotValidationError(f"{player.value} must have {ruleset.team_size} Pokemon")
    item_ids = [pokemon.item_id for pokemon in team if pokemon.item_id is not None]
    if ruleset.item_clause and len(item_ids) != len(set(item_ids)):
        raise SnapshotValidationError(f"{player.value} violates the item clause")
    return SideState(
        player=player,
        team=team,
        active_instance_id=PokemonInstanceId(str(raw["active"])),
    )


def _pokemon(
    raw: dict[str, Any],
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
) -> PokemonState:
    pokemon_id = PokemonId(str(raw["pokemon_id"]))
    species = catalog.pokemon(pokemon_id)
    ability_id = AbilityId(str(raw["ability_id"]))
    item_id = ItemId(str(raw["item_id"])) if raw.get("item_id") is not None else None
    if ability_id not in species.ability_ids:
        raise SnapshotValidationError(f"illegal ability {ability_id} for {pokemon_id}")
    catalog.ability(ability_id)
    if item_id is not None:
        catalog.item(item_id)

    move_ids = tuple(MoveId(str(value)) for value in raw["moves"])
    if len(move_ids) != 4 or len(set(move_ids)) != 4:
        raise SnapshotValidationError(f"{pokemon_id} must have four unique moves")
    if not set(move_ids) <= set(species.legal_move_ids):
        raise SnapshotValidationError(f"illegal move in fixture for {pokemon_id}")
    moves = tuple(
        MoveSlotState(move_id=move_id, pp=catalog.move(move_id).pp, max_pp=catalog.move(move_id).pp)
        for move_id in move_ids
    )
    stats = raw["stats"]
    stat_block = StatBlock(
        max_hp=int(stats["hp"]),
        attack=int(stats["atk"]),
        defense=int(stats["def"]),
        special_attack=int(stats["spa"]),
        special_defense=int(stats["spd"]),
        speed=int(stats["spe"]),
    )
    mega_profile_raw = raw.get("mega_evolution_profile")
    mega_evolution_profile = (
        _mega_evolution_profile(mega_profile_raw)
        if mega_profile_raw is not None
        else None
    )
    mega_definition = None
    if item_id is not None:
        try:
            mega_definition = catalog.mega_evolution(pokemon_id, item_id)
        except KeyError:
            pass
    mega_enabled = "mega_evolution" in ruleset.supported_mechanics
    if mega_evolution_profile is not None and not mega_enabled:
        raise SnapshotValidationError(
            f"{pokemon_id} provides a Mega stat profile while mega_evolution is not supported"
        )
    if mega_evolution_profile is not None and mega_definition is None:
        raise SnapshotValidationError(
            f"{pokemon_id} provides a Mega stat profile without a Catalog base/item relation"
        )
    if mega_enabled and mega_definition is not None and mega_evolution_profile is None:
        raise SnapshotValidationError(
            f"{pokemon_id} requires an integrity-bound mega_evolution_profile"
        )
    if (
        mega_evolution_profile is not None
        and mega_evolution_profile.stats.max_hp != stat_block.max_hp
    ):
        raise SnapshotValidationError(
            f"{pokemon_id} Mega Evolution cannot change max HP"
        )
    if mega_evolution_profile is not None:
        assert mega_definition is not None
        if mega_evolution_profile.target_pokemon_id != mega_definition.mega_pokemon_id:
            raise SnapshotValidationError(
                f"{pokemon_id} Mega stat profile targets the wrong form"
            )
        if mega_evolution_profile.level != ruleset.level:
            raise SnapshotValidationError(
                f"{pokemon_id} Mega stat profile level differs from the RuleSet"
            )
        if mega_evolution_profile.source_manifest_id != mega_definition.source_manifest_id:
            raise SnapshotValidationError(
                f"{pokemon_id} Mega stat profile source differs from the Catalog relation"
            )
        derived_base_stats, _ = validate_mega_stat_profile(
            mega_definition,
            mega_evolution_profile,
        )
        if derived_base_stats != stat_block:
            raise SnapshotValidationError(
                f"{pokemon_id} base stats do not match the Mega profile derivation inputs"
            )
    return PokemonState(
        instance_id=PokemonInstanceId(str(raw["instance_id"])),
        pokemon_id=pokemon_id,
        level=ruleset.level,
        hp=stat_block.max_hp,
        stats=stat_block,
        types=species.types,
        moves=moves,
        item_id=item_id,
        ability_id=ability_id,
        mega_evolution_profile=mega_evolution_profile,
    )


def _mega_evolution_profile(raw: dict[str, Any]) -> MegaEvolutionStatProfile:
    stats = raw["stats"]
    ivs = raw["ivs"]
    evs = raw["evs"]
    try:
        return MegaEvolutionStatProfile(
            target_pokemon_id=PokemonId(str(raw["target_pokemon_id"])),
            stats=StatBlock(
                max_hp=int(stats["hp"]),
                attack=int(stats["atk"]),
                defense=int(stats["def"]),
                special_attack=int(stats["spa"]),
                special_defense=int(stats["spd"]),
                speed=int(stats["spe"]),
            ),
            level=int(raw["level"]),
            ivs=TrainingStatBlock(
                hp=int(ivs["hp"]),
                attack=int(ivs["atk"]),
                defense=int(ivs["def"]),
                special_attack=int(ivs["spa"]),
                special_defense=int(ivs["spd"]),
                speed=int(ivs["spe"]),
            ),
            evs=TrainingStatBlock(
                hp=int(evs["hp"]),
                attack=int(evs["atk"]),
                defense=int(evs["def"]),
                special_attack=int(evs["spa"]),
                special_defense=int(evs["spd"]),
                speed=int(evs["spe"]),
            ),
            nature_increased_stat=raw["nature_increased_stat"],
            nature_decreased_stat=raw["nature_decreased_stat"],
            derivation_method_id=str(raw["derivation_method_id"]),
            source_manifest_id=str(raw["source_manifest_id"]),
            source_record_id=str(raw["source_record_id"]),
            profile_hash=str(raw["profile_hash"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SnapshotValidationError(
            f"invalid Mega Evolution stat profile: {error}"
        ) from error
