"""Versioned, immutable catalog and ruleset snapshots for SIM-01."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

from .core import (
    AbilityId,
    ItemId,
    MegaEvolutionStatProfile,
    MoveId,
    PokemonId,
    RuleSetId,
    StatBlock,
    TrainingStatBlock,
)


class SnapshotValidationError(ValueError):
    """Raised when a snapshot is internally inconsistent."""


def _read_json(path: Path | str) -> tuple[dict[str, Any], str]:
    resolved = Path(path)
    payload = resolved.read_bytes()
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SnapshotValidationError(f"invalid UTF-8 JSON: {resolved}") from error
    if not isinstance(raw, dict):
        raise SnapshotValidationError(f"snapshot root must be an object: {resolved}")
    return raw, hashlib.sha256(payload).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class MoveDefinition:
    move_id: MoveId
    name: str
    type_id: str
    category: str
    power: int | None
    accuracy: int | None
    pp: int
    priority: int | None
    contact: bool
    effect: Mapping[str, Any]
    legacy_move_id: int | None = None


@dataclass(frozen=True, slots=True)
class AbilityDefinition:
    ability_id: AbilityId
    name: str
    effect_id: str
    legacy_ability_id: int | None = None
    source_record_sha256: str | None = None
    unsupported_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    item_id: ItemId
    name: str
    effect_id: str
    consumable: bool | None = False
    legacy_item_id: int | None = None
    source_record_sha256: str | None = None
    unsupported_reason: str | None = None


@dataclass(frozen=True, slots=True)
class SpeciesDefinition:
    pokemon_id: PokemonId
    name: str
    types: tuple[str, ...]
    ability_ids: tuple[AbilityId, ...]
    legal_move_ids: tuple[MoveId, ...]
    legacy_pokemon_id: str | None = None


@dataclass(frozen=True, slots=True)
class TypeChartEntry:
    attack_type: str
    defense_type: str
    multiplier: Fraction


@dataclass(frozen=True, slots=True)
class BaseStatBlock:
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def __post_init__(self) -> None:
        if min(
            self.hp,
            self.attack,
            self.defense,
            self.special_attack,
            self.special_defense,
            self.speed,
        ) <= 0:
            raise SnapshotValidationError("Mega Evolution base stats must be positive")


@dataclass(frozen=True, slots=True)
class MegaEvolutionDefinition:
    """Catalog-grounded, build-independent Mega Evolution relation.

    ``base_stats`` and ``mega_stats`` are species base stats.  The exact
    battle stats depend on IVs, EVs, nature, level and rounding, so the battle
    fixture carries a separately precomputed ``mega_evolution_profile``.
    Keeping those domains separate prevents a plausible-but-wrong inferred
    stat block from silently entering a deterministic replay.
    """

    base_pokemon_id: PokemonId
    mega_pokemon_id: PokemonId
    required_item_id: ItemId
    base_stats: BaseStatBlock
    mega_stats: BaseStatBlock
    types: tuple[str, ...]
    ability_id: AbilityId
    source_manifest_id: str


MEGA_STAT_DERIVATION_METHOD_ID = "pokemon-mainline-stat-v1"


def derive_battle_stats(
    base_stats: BaseStatBlock,
    *,
    level: int,
    ivs: TrainingStatBlock,
    evs: TrainingStatBlock,
    nature_increased_stat: str | None,
    nature_decreased_stat: str | None,
    derivation_method_id: str,
) -> StatBlock:
    """Apply the versioned standard stat formula used by synthetic contracts.

    This is not yet a claim that Champions uses identical rounding.  Profiles
    remain ineligible for a grounded M-B bundle until that formula is checked
    against captured Champions evidence.
    """

    if derivation_method_id != MEGA_STAT_DERIVATION_METHOD_ID:
        raise SnapshotValidationError(
            f"unsupported Mega stat derivation method: {derivation_method_id}"
        )

    def raw(base: int, iv: int, ev: int) -> int:
        return ((2 * base + iv + ev // 4) * level) // 100

    def non_hp(name: str, base: int, iv: int, ev: int) -> int:
        value = raw(base, iv, ev) + 5
        if name == nature_increased_stat:
            return value * 110 // 100
        if name == nature_decreased_stat:
            return value * 90 // 100
        return value

    return StatBlock(
        max_hp=raw(base_stats.hp, ivs.hp, evs.hp) + level + 10,
        attack=non_hp("attack", base_stats.attack, ivs.attack, evs.attack),
        defense=non_hp("defense", base_stats.defense, ivs.defense, evs.defense),
        special_attack=non_hp(
            "special_attack",
            base_stats.special_attack,
            ivs.special_attack,
            evs.special_attack,
        ),
        special_defense=non_hp(
            "special_defense",
            base_stats.special_defense,
            ivs.special_defense,
            evs.special_defense,
        ),
        speed=non_hp("speed", base_stats.speed, ivs.speed, evs.speed),
    )


def validate_mega_stat_profile(
    definition: MegaEvolutionDefinition,
    profile: MegaEvolutionStatProfile,
) -> tuple[StatBlock, StatBlock]:
    if profile.target_pokemon_id != definition.mega_pokemon_id:
        raise SnapshotValidationError("Mega stat profile targets the wrong form")
    if profile.source_manifest_id != definition.source_manifest_id:
        raise SnapshotValidationError("Mega stat profile source differs from Catalog")
    arguments = {
        "level": profile.level,
        "ivs": profile.ivs,
        "evs": profile.evs,
        "nature_increased_stat": profile.nature_increased_stat,
        "nature_decreased_stat": profile.nature_decreased_stat,
        "derivation_method_id": profile.derivation_method_id,
    }
    base_result = derive_battle_stats(definition.base_stats, **arguments)
    mega_result = derive_battle_stats(definition.mega_stats, **arguments)
    if profile.stats != mega_result:
        raise SnapshotValidationError(
            "Mega stat profile does not match its versioned derivation inputs"
        )
    return base_result, mega_result


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    schema_version: str
    catalog_id: str
    engine_semantics_version: str
    source_manifest_id: str
    snapshot_hash: str
    type_chart_default_multiplier: Fraction
    type_ids: tuple[str, ...]
    type_chart: tuple[TypeChartEntry, ...]
    moves: tuple[MoveDefinition, ...]
    abilities: tuple[AbilityDefinition, ...]
    items: tuple[ItemDefinition, ...]
    species: tuple[SpeciesDefinition, ...]
    mega_evolutions: tuple[MegaEvolutionDefinition, ...] = ()

    def move(self, move_id: MoveId | str) -> MoveDefinition:
        key = str(move_id)
        for move in self.moves:
            if move.move_id == key:
                return move
        raise KeyError(f"unknown move_id: {key}")

    def ability(self, ability_id: AbilityId | str) -> AbilityDefinition:
        key = str(ability_id)
        for ability in self.abilities:
            if ability.ability_id == key:
                return ability
        raise KeyError(f"unknown ability_id: {key}")

    def item(self, item_id: ItemId | str) -> ItemDefinition:
        key = str(item_id)
        for item in self.items:
            if item.item_id == key:
                return item
        raise KeyError(f"unknown item_id: {key}")

    def pokemon(self, pokemon_id: PokemonId | str) -> SpeciesDefinition:
        key = str(pokemon_id)
        for species in self.species:
            if species.pokemon_id == key:
                return species
        raise KeyError(f"unknown pokemon_id: {key}")

    def mega_evolution(
        self,
        base_pokemon_id: PokemonId | str,
        required_item_id: ItemId | str,
    ) -> MegaEvolutionDefinition:
        base_key = str(base_pokemon_id)
        item_key = str(required_item_id)
        for definition in self.mega_evolutions:
            if (
                definition.base_pokemon_id == base_key
                and definition.required_item_id == item_key
            ):
                return definition
        raise KeyError(
            f"unknown Mega Evolution: base={base_key}, item={item_key}"
        )

    def type_effectiveness(self, attack_type: str, defense_types: tuple[str, ...]) -> Fraction:
        if attack_type not in self.type_ids:
            raise SnapshotValidationError(f"unknown attacking type: {attack_type}")
        multiplier = Fraction(1, 1)
        entries = {(entry.attack_type, entry.defense_type): entry.multiplier for entry in self.type_chart}
        for defense_type in defense_types:
            if defense_type not in self.type_ids:
                raise SnapshotValidationError(f"unknown defending type: {defense_type}")
            multiplier *= entries.get(
                (attack_type, defense_type), self.type_chart_default_multiplier
            )
        return multiplier


@dataclass(frozen=True, slots=True)
class RuleSetSnapshot:
    schema_version: str
    ruleset_id: RuleSetId
    engine_semantics_version: str
    snapshot_hash: str
    battle_format: str
    team_size: int
    level: int
    item_clause: bool
    max_turns: int
    damage_rolls: tuple[int, ...]
    supported_mechanics: frozenset[str]
    unsupported_mechanics: frozenset[str]
    provisional_rules: tuple[str, ...]
    provisional_decision_ids: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]
    critical_chance: Fraction
    critical_multiplier: Fraction
    raw: Mapping[str, Any]

    def rule(self, *path: str) -> Any:
        current: Any = self.raw
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                raise SnapshotValidationError(f"missing ruleset value: {'.'.join(path)}")
            current = current[key]
        return current


def load_catalog(path: Path | str) -> CatalogSnapshot:
    raw, snapshot_hash = _read_json(path)
    if "type_chart_default_multiplier" not in raw:
        raise SnapshotValidationError(
            "SIM-01 sparse type chart must explicitly default omitted pairs to neutral"
        )
    type_chart_default_multiplier = Fraction(
        str(raw["type_chart_default_multiplier"])
    )
    if type_chart_default_multiplier != Fraction(1, 1):
        raise SnapshotValidationError(
            "SIM-01 sparse type chart must explicitly default omitted pairs to neutral"
        )
    type_ids = tuple(str(item["type_id"]) for item in raw.get("types", ()))
    if len(type_ids) != len(set(type_ids)) or not type_ids:
        raise SnapshotValidationError("catalog type IDs must be non-empty and unique")

    chart: list[TypeChartEntry] = []
    for attack_type, rows in raw.get("type_chart", {}).items():
        if attack_type not in type_ids or not isinstance(rows, dict):
            raise SnapshotValidationError(f"invalid type chart row: {attack_type}")
        for defense_type, multiplier in rows.items():
            if defense_type not in type_ids:
                raise SnapshotValidationError(f"unknown type chart defense type: {defense_type}")
            chart.append(
                TypeChartEntry(
                    attack_type=attack_type,
                    defense_type=defense_type,
                    multiplier=Fraction(str(multiplier)),
                )
            )

    moves = tuple(
        MoveDefinition(
            move_id=MoveId(str(item["move_id"])),
            legacy_move_id=item.get("legacy_move_id"),
            name=str(item["name"]),
            type_id=str(item["type_id"]),
            category=str(item["category"]),
            power=item.get("power"),
            accuracy=item.get("accuracy"),
            pp=int(item["pp"]),
            priority=(
                None
                if item.get("priority", 0) is None
                else int(item.get("priority", 0))
            ),
            contact=bool(item.get("contact", False)),
            effect=_freeze(item.get("effect", {"kind": "damage"})),
        )
        for item in raw.get("moves", ())
    )
    abilities = tuple(
        AbilityDefinition(
            ability_id=AbilityId(str(item["ability_id"])),
            legacy_ability_id=item.get("legacy_ability_id"),
            name=str(item["name"]),
            effect_id=str(item["effect_id"]),
            source_record_sha256=item.get("source_record_sha256"),
            unsupported_reason=item.get("unsupported_reason"),
        )
        for item in raw.get("abilities", ())
    )
    items = tuple(
        ItemDefinition(
            item_id=ItemId(str(item["item_id"])),
            legacy_item_id=item.get("legacy_item_id"),
            name=str(item["name"]),
            effect_id=str(item["effect_id"]),
            consumable=(
                None
                if item.get("consumable", False) is None
                else bool(item.get("consumable", False))
            ),
            source_record_sha256=item.get("source_record_sha256"),
            unsupported_reason=item.get("unsupported_reason"),
        )
        for item in raw.get("items", ())
    )
    species = tuple(
        SpeciesDefinition(
            pokemon_id=PokemonId(str(item["pokemon_id"])),
            legacy_pokemon_id=item.get("legacy_pokemon_id"),
            name=str(item["name"]),
            types=tuple(str(value) for value in item["types"]),
            ability_ids=tuple(AbilityId(str(value)) for value in item["ability_ids"]),
            legal_move_ids=tuple(MoveId(str(value)) for value in item["legal_move_ids"]),
        )
        for item in raw.get("species", ())
    )
    mega_evolutions = tuple(
        MegaEvolutionDefinition(
            base_pokemon_id=PokemonId(str(item["base_pokemon_id"])),
            mega_pokemon_id=PokemonId(str(item["mega_pokemon_id"])),
            required_item_id=ItemId(str(item["required_item_id"])),
            base_stats=_base_stat_block(item["base_stats"]),
            mega_stats=_base_stat_block(item["mega_stats"]),
            types=tuple(str(value) for value in item["types"]),
            ability_id=AbilityId(str(item["ability_id"])),
            source_manifest_id=str(item["source_manifest_id"]),
        )
        for item in raw.get("mega_evolutions", ())
    )
    _validate_unique("move", tuple(str(value.move_id) for value in moves))
    _validate_unique("ability", tuple(str(value.ability_id) for value in abilities))
    _validate_unique("item", tuple(str(value.item_id) for value in items))
    _validate_unique("pokemon", tuple(str(value.pokemon_id) for value in species))
    catalog = CatalogSnapshot(
        schema_version=str(raw["schema_version"]),
        catalog_id=str(raw["catalog_id"]),
        engine_semantics_version=str(raw["engine_semantics_version"]),
        source_manifest_id=str(raw["source_manifest_id"]),
        snapshot_hash=snapshot_hash,
        type_chart_default_multiplier=type_chart_default_multiplier,
        type_ids=type_ids,
        type_chart=tuple(chart),
        moves=moves,
        abilities=abilities,
        items=items,
        species=species,
        mega_evolutions=mega_evolutions,
    )
    _validate_catalog_references(catalog)
    return catalog


def load_ruleset(path: Path | str) -> RuleSetSnapshot:
    raw, snapshot_hash = _read_json(path)
    critical = raw["critical"]
    result = RuleSetSnapshot(
        schema_version=str(raw["schema_version"]),
        ruleset_id=RuleSetId(str(raw["ruleset_id"])),
        engine_semantics_version=str(raw["engine_semantics_version"]),
        snapshot_hash=snapshot_hash,
        battle_format=str(raw["battle_format"]),
        team_size=int(raw["team_size"]),
        level=int(raw["level"]),
        item_clause=bool(raw["item_clause"]),
        max_turns=int(raw["max_turns"]),
        damage_rolls=tuple(int(value) for value in raw["damage_rolls"]),
        supported_mechanics=frozenset(str(value) for value in raw["supported_mechanics"]),
        unsupported_mechanics=frozenset(str(value) for value in raw["unsupported_mechanics"]),
        provisional_rules=tuple(str(value) for value in raw.get("provisional_rules", ())),
        provisional_decision_ids=tuple(
            str(value) for value in raw.get("provisional_decision_ids", ())
        ),
        source_manifest_ids=tuple(
            str(value) for value in raw.get("source_manifest_ids", ())
        ),
        critical_chance=Fraction(
            int(critical["chance_numerator"]), int(critical["chance_denominator"])
        ),
        critical_multiplier=Fraction(
            int(critical["multiplier_numerator"]), int(critical["multiplier_denominator"])
        ),
        raw=_freeze(raw),
    )
    if result.battle_format != "singles_3v3" or result.team_size != 3:
        raise SnapshotValidationError("SIM-01 requires singles_3v3 with team_size 3")
    if result.damage_rolls != tuple(range(85, 101)):
        raise SnapshotValidationError("SIM-01 requires the sixteen 85..100 damage rolls")
    if result.supported_mechanics & result.unsupported_mechanics:
        raise SnapshotValidationError("a mechanic cannot be both supported and unsupported")
    mega_rule = raw.get("mega_evolution")
    if "mega_evolution" in result.supported_mechanics:
        expected = {
            "max_uses_per_side": 1,
            "activation_timing": "before_move_ordering",
            "requires_active": True,
            "consumes_item": False,
        }
        if mega_rule != expected:
            raise SnapshotValidationError(
                "supported mega_evolution requires the exact transition rule contract"
            )
    elif mega_rule is not None:
        raise SnapshotValidationError(
            "mega_evolution rules cannot be present unless the mechanic is supported"
        )
    return result


def validate_snapshot_pair(catalog: CatalogSnapshot, ruleset: RuleSetSnapshot) -> None:
    if catalog.engine_semantics_version != ruleset.engine_semantics_version:
        raise SnapshotValidationError("catalog and ruleset engine semantics versions differ")


def _validate_unique(label: str, values: tuple[str, ...]) -> None:
    if not values or len(values) != len(set(values)):
        raise SnapshotValidationError(f"{label} IDs must be non-empty and unique")


def _base_stat_block(raw: Mapping[str, Any]) -> BaseStatBlock:
    return BaseStatBlock(
        hp=int(raw["hp"]),
        attack=int(raw["attack"]),
        defense=int(raw["defense"]),
        special_attack=int(raw["special_attack"]),
        special_defense=int(raw["special_defense"]),
        speed=int(raw["speed"]),
    )


def _validate_catalog_references(catalog: CatalogSnapshot) -> None:
    move_ids = {move.move_id for move in catalog.moves}
    ability_ids = {ability.ability_id for ability in catalog.abilities}
    for move in catalog.moves:
        if move.type_id not in catalog.type_ids:
            raise SnapshotValidationError(f"move {move.move_id} has unknown type {move.type_id}")
        if move.category not in {"physical", "special", "status"}:
            raise SnapshotValidationError(f"move {move.move_id} has unsupported category")
        unsupported = move.effect.get("kind") == "unsupported"
        if move.pp <= 0 or (
            move.priority is None and not unsupported
        ) or (
            move.priority is not None
            and (move.priority < -7 or move.priority > 7)
        ):
            raise SnapshotValidationError(f"move {move.move_id} has invalid PP or priority")
        if move.accuracy is not None and not 1 <= move.accuracy <= 100:
            raise SnapshotValidationError(f"move {move.move_id} has invalid accuracy")
        _validate_move_effect(move)
    for ability in catalog.abilities:
        _validate_unsupported_entity_source(
            "ability", ability.effect_id, ability.source_record_sha256, ability.unsupported_reason
        )
    for item in catalog.items:
        if item.consumable is None and not item.effect_id.startswith("unsupported:"):
            raise SnapshotValidationError(
                f"item {item.item_id} has unknown consumable semantics"
            )
        _validate_unsupported_entity_source(
            "item", item.effect_id, item.source_record_sha256, item.unsupported_reason
        )
    for species in catalog.species:
        if not set(species.types) <= set(catalog.type_ids):
            raise SnapshotValidationError(f"species {species.pokemon_id} has unknown types")
        if not set(species.ability_ids) <= ability_ids:
            raise SnapshotValidationError(f"species {species.pokemon_id} has unknown abilities")
        if not set(species.legal_move_ids) <= move_ids:
            raise SnapshotValidationError(f"species {species.pokemon_id} has unknown moves")
    relations: set[tuple[PokemonId, ItemId]] = set()
    target_ids: set[PokemonId] = set()
    for definition in catalog.mega_evolutions:
        relation = (definition.base_pokemon_id, definition.required_item_id)
        if relation in relations:
            raise SnapshotValidationError(
                "Mega Evolution base/item relations must be unique"
            )
        relations.add(relation)
        if definition.mega_pokemon_id in target_ids:
            raise SnapshotValidationError("Mega Evolution target forms must be unique")
        target_ids.add(definition.mega_pokemon_id)
        if definition.base_pokemon_id == definition.mega_pokemon_id:
            raise SnapshotValidationError("Mega Evolution must change pokemon_id")
        try:
            base_species = catalog.pokemon(definition.base_pokemon_id)
            mega_species = catalog.pokemon(definition.mega_pokemon_id)
            required_item = catalog.item(definition.required_item_id)
            catalog.ability(definition.ability_id)
        except KeyError as error:
            raise SnapshotValidationError(
                f"Mega Evolution has an unknown reference: {error}"
            ) from error
        if required_item.effect_id != "mega_stone":
            raise SnapshotValidationError(
                f"Mega Evolution item {required_item.item_id} must use mega_stone effect"
            )
        if definition.types != mega_species.types:
            raise SnapshotValidationError(
                f"Mega Evolution {definition.mega_pokemon_id} type contract differs from species"
            )
        if definition.ability_id not in mega_species.ability_ids:
            raise SnapshotValidationError(
                f"Mega Evolution {definition.mega_pokemon_id} ability contract differs from species"
            )
        if definition.base_stats.hp != definition.mega_stats.hp:
            raise SnapshotValidationError(
                "Mega Evolution base HP must remain unchanged during battle"
            )
        if not definition.source_manifest_id:
            raise SnapshotValidationError(
                "Mega Evolution requires a source_manifest_id"
            )


def _validate_move_effect(move: MoveDefinition) -> None:
    effect = move.effect
    kind = effect.get("kind")
    if kind == "unsupported":
        source_hash = effect.get("source_record_sha256")
        reason = effect.get("reason")
        if (
            not isinstance(source_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None
            or not isinstance(reason, str)
            or not reason
        ):
            raise SnapshotValidationError(
                f"unsupported move {move.move_id} requires source hash and reason"
            )
        return
    damage_kinds = {
        "damage",
        "damage_drain",
        "damage_secondary_flinch",
        "damage_secondary_stage",
        "damage_secondary_status",
    }
    status_kinds = {"heal_self", "inflict_status", "raise_self"}
    if kind not in damage_kinds | status_kinds:
        # The engine will also reject unsupported effects, but malformed or
        # unknown catalog records should fail before a battle can start.
        raise SnapshotValidationError(f"move {move.move_id} has unknown effect kind {kind!r}")
    if kind in damage_kinds:
        if move.category not in {"physical", "special"}:
            raise SnapshotValidationError(f"damaging move {move.move_id} has a non-damage category")
        if not isinstance(move.power, int) or isinstance(move.power, bool) or move.power <= 0:
            raise SnapshotValidationError(f"damaging move {move.move_id} needs positive power")
    elif move.category != "status" or move.power is not None:
        raise SnapshotValidationError(f"status move {move.move_id} has damage fields")

    required: dict[str, frozenset[str]] = {
        "damage": frozenset(),
        "damage_drain": frozenset({"numerator", "denominator"}),
        "damage_secondary_flinch": frozenset({"chance_numerator", "chance_denominator"}),
        "damage_secondary_stage": frozenset(
            {"chance_numerator", "chance_denominator", "target", "stages"}
        ),
        "damage_secondary_status": frozenset(
            {"chance_numerator", "chance_denominator", "status"}
        ),
        "heal_self": frozenset({"numerator", "denominator"}),
        "inflict_status": frozenset({"status"}),
        "raise_self": frozenset({"stages"}),
    }
    missing = required[str(kind)] - set(effect)
    if missing:
        raise SnapshotValidationError(
            f"move {move.move_id} effect is missing {sorted(missing)}"
        )
    if "status" in effect and effect["status"] not in {"burn", "poison"}:
        raise SnapshotValidationError(f"move {move.move_id} has unsupported status")
    if "target" in effect and effect["target"] not in {"self", "opponent"}:
        raise SnapshotValidationError(f"move {move.move_id} has invalid effect target")
    if "stages" in effect:
        stages = effect["stages"]
        if not isinstance(stages, Mapping) or not stages:
            raise SnapshotValidationError(f"move {move.move_id} needs stage changes")
        if not set(stages) <= {"atk", "def", "spa", "spd", "spe"}:
            raise SnapshotValidationError(f"move {move.move_id} has unknown stage keys")
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or value == 0
            or not -6 <= value <= 6
            for value in stages.values()
        ):
            raise SnapshotValidationError(f"move {move.move_id} has invalid stage changes")
    for numerator_key, denominator_key in (
        ("chance_numerator", "chance_denominator"),
        ("numerator", "denominator"),
    ):
        if denominator_key not in effect:
            continue
        numerator = effect[numerator_key]
        denominator = effect[denominator_key]
        if (
            not isinstance(numerator, int)
            or isinstance(numerator, bool)
            or not isinstance(denominator, int)
            or isinstance(denominator, bool)
            or numerator < (0 if numerator_key == "chance_numerator" else 1)
            or denominator <= 0
            or numerator > denominator
        ):
            raise SnapshotValidationError(f"move {move.move_id} has invalid effect fraction")


def _validate_unsupported_entity_source(
    kind: str,
    effect_id: str,
    source_record_sha256: str | None,
    unsupported_reason: str | None,
) -> None:
    if not effect_id.startswith("unsupported:"):
        return
    if (
        source_record_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", source_record_sha256) is None
        or not unsupported_reason
    ):
        raise SnapshotValidationError(
            f"unsupported {kind} effect requires source hash and reason"
        )
