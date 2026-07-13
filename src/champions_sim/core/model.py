"""Simulator core contracts independent from catalogs, engines, and UIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

from .ids import (
    AbilityId,
    ItemId,
    MoveId,
    PokemonId,
    PokemonInstanceId,
    RuleSetId,
)
from .rng import ExplicitRNG


class PlayerId(str, Enum):
    P1 = "p1"
    P2 = "p2"

    @property
    def opponent(self) -> "PlayerId":
        return PlayerId.P2 if self is PlayerId.P1 else PlayerId.P1


class BattlePhase(str, Enum):
    TEAM_PREVIEW = "team_preview"
    AWAITING_DECISIONS = "awaiting_decisions"
    RESOLVING = "resolving"
    FORCED_SWITCH = "forced_switch"
    FINISHED = "finished"


class ActionKind(str, Enum):
    MOVE = "move"
    SWITCH = "switch"
    PASS = "pass"
    FORFEIT = "forfeit"


class DecisionKind(str, Enum):
    ACTION = "action"
    FORCED_SWITCH = "forced_switch"


class BattleEventKind(str, Enum):
    BATTLE_STARTED = "battle_started"
    TURN_STARTED = "turn_started"
    ACTION_ORDERED = "action_ordered"
    MOVE_USED = "move_used"
    MOVE_MISSED = "move_missed"
    ACTION_FAILED = "action_failed"
    CRITICAL_HIT = "critical_hit"
    SWITCHED = "switched"
    DAMAGE = "damage"
    HEALED = "healed"
    STAT_STAGE_CHANGED = "stat_stage_changed"
    STATUS_CHANGED = "status_changed"
    VOLATILE_CHANGED = "volatile_changed"
    ABILITY_TRIGGERED = "ability_triggered"
    ITEM_TRIGGERED = "item_triggered"
    ITEM_CONSUMED = "item_consumed"
    MEGA_EVOLVED = "mega_evolved"
    PP_CHANGED = "pp_changed"
    FAINTED = "fainted"
    REVEALED = "revealed"
    RNG_DRAW = "rng_draw"
    TURN_ENDED = "turn_ended"
    BATTLE_ENDED = "battle_ended"


EventScalar: TypeAlias = str | int | bool | None


@dataclass(frozen=True, slots=True)
class TrainingStatBlock:
    hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def values(self) -> tuple[int, ...]:
        return (
            self.hp,
            self.attack,
            self.defense,
            self.special_attack,
            self.special_defense,
            self.speed,
        )


@dataclass(frozen=True, slots=True)
class MegaEvolutionStatProfile:
    """Grounded, integrity-bound exact stats for one configured build.

    The simulator deliberately does not infer the Champions stat formula.
    Instead, a catalog source record and all derivation inputs are retained in
    the complete state.  ``profile_hash`` binds those inputs to the exact
    precomputed result used by the engine and Replay v2.
    """

    target_pokemon_id: PokemonId
    stats: "StatBlock"
    level: int
    ivs: TrainingStatBlock
    evs: TrainingStatBlock
    nature_increased_stat: str | None
    nature_decreased_stat: str | None
    derivation_method_id: str
    source_manifest_id: str
    source_record_id: str
    profile_hash: str

    def __post_init__(self) -> None:
        if not 1 <= self.level <= 100:
            raise ValueError("Mega stat profile level must be between 1 and 100")
        if any(not 0 <= value <= 31 for value in self.ivs.values()):
            raise ValueError("Mega stat profile IVs must be between 0 and 31")
        if any(value < 0 or value > 252 or value % 4 for value in self.evs.values()):
            raise ValueError("Mega stat profile EVs must be 0..252 in multiples of four")
        if sum(self.evs.values()) > 508:
            raise ValueError("Mega stat profile EV total must not exceed 508")
        nature_stats = {
            "attack",
            "defense",
            "special_attack",
            "special_defense",
            "speed",
        }
        for value in (self.nature_increased_stat, self.nature_decreased_stat):
            if value is not None and value not in nature_stats:
                raise ValueError("Mega stat profile has an invalid nature stat")
        if (
            self.nature_increased_stat is None
        ) != (self.nature_decreased_stat is None):
            raise ValueError("Mega stat profile nature modifiers must both be set or null")
        if (
            self.nature_increased_stat is not None
            and self.nature_increased_stat == self.nature_decreased_stat
        ):
            raise ValueError("Mega stat profile nature modifiers must differ")
        if not (
            self.derivation_method_id
            and self.source_manifest_id
            and self.source_record_id
        ):
            raise ValueError("Mega stat profile derivation and source IDs are required")
        if self.derivation_method_id != "pokemon-mainline-stat-v1":
            raise ValueError("unsupported Mega stat profile derivation method")
        if self.profile_hash != self.expected_hash():
            raise ValueError("Mega stat profile hash does not match its payload")

    def hash_payload(self) -> dict[str, object]:
        return {
            "target_pokemon_id": self.target_pokemon_id,
            "stats": self.stats,
            "level": self.level,
            "ivs": self.ivs,
            "evs": self.evs,
            "nature_increased_stat": self.nature_increased_stat,
            "nature_decreased_stat": self.nature_decreased_stat,
            "derivation_method_id": self.derivation_method_id,
            "source_manifest_id": self.source_manifest_id,
            "source_record_id": self.source_record_id,
        }

    def expected_hash(self) -> str:
        from .canonical import canonical_hash

        return canonical_hash(self.hash_payload())


@dataclass(frozen=True, slots=True)
class StatBlock:
    max_hp: int
    attack: int
    defense: int
    special_attack: int
    special_defense: int
    speed: int

    def __post_init__(self) -> None:
        if min(
            self.max_hp,
            self.attack,
            self.defense,
            self.special_attack,
            self.special_defense,
            self.speed,
        ) <= 0:
            raise ValueError("all stats must be positive")


@dataclass(frozen=True, slots=True)
class StatStages:
    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0
    accuracy: int = 0
    evasion: int = 0

    def __post_init__(self) -> None:
        values = (
            self.attack,
            self.defense,
            self.special_attack,
            self.special_defense,
            self.speed,
            self.accuracy,
            self.evasion,
        )
        if any(value < -6 or value > 6 for value in values):
            raise ValueError("stat stages must be between -6 and 6")


@dataclass(frozen=True, slots=True)
class MoveSlotState:
    move_id: MoveId
    pp: int
    max_pp: int
    revealed_to_opponent: bool = False

    def __post_init__(self) -> None:
        if self.max_pp <= 0:
            raise ValueError("max_pp must be positive")
        if not 0 <= self.pp <= self.max_pp:
            raise ValueError("pp must be between 0 and max_pp")


@dataclass(frozen=True, slots=True)
class PokemonState:
    instance_id: PokemonInstanceId
    pokemon_id: PokemonId
    level: int
    hp: int
    stats: StatBlock
    types: tuple[str, ...]
    moves: tuple[MoveSlotState, ...]
    item_id: ItemId | None = None
    consumed_item_id: ItemId | None = None
    ability_id: AbilityId | None = None
    status_id: str | None = None
    stat_stages: StatStages = field(default_factory=StatStages)
    volatile_statuses: tuple[str, ...] = ()
    revealed_to_opponent: bool = False
    item_revealed_to_opponent: bool = False
    ability_revealed_to_opponent: bool = False
    mega_evolved: bool = field(
        default=False,
        metadata={"canonical_omit_default": True},
    )
    mega_evolution_profile: MegaEvolutionStatProfile | None = field(
        default=None,
        metadata={"canonical_omit_default": True},
        repr=False,
    )

    def __post_init__(self) -> None:
        if not 1 <= self.level <= 100:
            raise ValueError("level must be between 1 and 100")
        if not 0 <= self.hp <= self.stats.max_hp:
            raise ValueError("hp must be between 0 and max_hp")
        if not 1 <= len(self.types) <= 2:
            raise ValueError("a Pokemon must have one or two types")
        if len(set(self.types)) != len(self.types):
            raise ValueError("Pokemon types must be unique")
        if len({move.move_id for move in self.moves}) != len(self.moves):
            raise ValueError("move IDs must be unique within a move set")
        if len(set(self.volatile_statuses)) != len(self.volatile_statuses):
            raise ValueError("volatile statuses must be unique")
        if self.item_id is not None and self.consumed_item_id is not None:
            raise ValueError("a Pokemon cannot hold and have consumed an item in SIM-01")

    @property
    def fainted(self) -> bool:
        return self.hp == 0


@dataclass(frozen=True, slots=True)
class SideState:
    player: PlayerId
    team: tuple[PokemonState, ...]
    active_instance_id: PokemonInstanceId

    def __post_init__(self) -> None:
        if not self.team:
            raise ValueError("a side must contain at least one Pokemon")
        instance_ids = [pokemon.instance_id for pokemon in self.team]
        if len(set(instance_ids)) != len(instance_ids):
            raise ValueError("Pokemon instance IDs must be unique per side")
        if self.active_instance_id not in instance_ids:
            raise ValueError("active_instance_id must refer to a team member")

    @property
    def active(self) -> PokemonState:
        return self.pokemon(self.active_instance_id)

    def pokemon(self, instance_id: PokemonInstanceId) -> PokemonState:
        for pokemon in self.team:
            if pokemon.instance_id == instance_id:
                return pokemon
        raise KeyError(instance_id)


@dataclass(frozen=True, slots=True)
class BattleState:
    battle_id: str
    ruleset_id: RuleSetId
    turn: int
    phase: BattlePhase
    sides: tuple[SideState, SideState]
    field_conditions: tuple[str, ...] = ()
    winner: PlayerId | None = None

    def __post_init__(self) -> None:
        if not self.battle_id:
            raise ValueError("battle_id must be non-empty")
        if self.turn < 0:
            raise ValueError("turn must be non-negative")
        if len(self.sides) != 2:
            raise ValueError("a singles battle requires exactly two sides")
        if {side.player for side in self.sides} != {PlayerId.P1, PlayerId.P2}:
            raise ValueError("battle sides must be P1 and P2")
        all_ids = [pokemon.instance_id for side in self.sides for pokemon in side.team]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("Pokemon instance IDs must be unique within a battle")
        if len(set(self.field_conditions)) != len(self.field_conditions):
            raise ValueError("field conditions must be unique")
        if self.winner is not None and self.phase is not BattlePhase.FINISHED:
            raise ValueError("winner may only be set for a finished battle")

    def side(self, player: PlayerId) -> SideState:
        for side in self.sides:
            if side.player is player:
                return side
        raise KeyError(player)

    def observation_for(self, viewer: PlayerId) -> "PlayerObservation":
        # This is the sole public path from complete state to player knowledge.
        return make_player_observation(self, viewer)


@dataclass(frozen=True, slots=True)
class ObservedMove:
    move_id: MoveId
    pp: int | None = None
    max_pp: int | None = None


@dataclass(frozen=True, slots=True)
class ObservedPokemon:
    instance_id: PokemonInstanceId
    pokemon_id: PokemonId
    level: int
    hp: int | None
    max_hp: int | None
    hp_fraction_millionths: int | None
    stats: StatBlock | None
    types: tuple[str, ...]
    moves: tuple[ObservedMove, ...]
    item_id: ItemId | None
    consumed_item_id: ItemId | None
    ability_id: AbilityId | None
    status_id: str | None
    stat_stages: StatStages
    volatile_statuses: tuple[str, ...]
    is_active: bool
    mega_evolved: bool = field(
        default=False,
        metadata={"canonical_omit_default": True},
    )


@dataclass(frozen=True, slots=True)
class ObservedSide:
    player: PlayerId
    team_size: int
    pokemon: tuple[ObservedPokemon, ...]
    unrevealed_count: int
    active_instance_id: PokemonInstanceId | None
    mega_evolution_used: bool = field(
        default=False,
        metadata={"canonical_omit_default": True},
    )


@dataclass(frozen=True, slots=True)
class PlayerObservation:
    battle_id: str
    ruleset_id: RuleSetId
    viewer: PlayerId
    turn: int
    phase: BattlePhase
    own_side: ObservedSide
    opponent_side: ObservedSide
    field_conditions: tuple[str, ...]
    winner: PlayerId | None


def _observed_pokemon(
    pokemon: PokemonState,
    *,
    is_own: bool,
    is_active: bool,
) -> ObservedPokemon:
    if is_own:
        moves = tuple(
            ObservedMove(move_id=move.move_id, pp=move.pp, max_pp=move.max_pp)
            for move in pokemon.moves
        )
        item_id = pokemon.item_id
        consumed_item_id = pokemon.consumed_item_id
        ability_id = pokemon.ability_id
        hp = pokemon.hp
        max_hp = pokemon.stats.max_hp
        stats: StatBlock | None = pokemon.stats
    else:
        moves = tuple(
            ObservedMove(move_id=move.move_id)
            for move in pokemon.moves
            if move.revealed_to_opponent
        )
        item_id = pokemon.item_id if pokemon.item_revealed_to_opponent else None
        consumed_item_id = (
            pokemon.consumed_item_id if pokemon.item_revealed_to_opponent else None
        )
        ability_id = (
            pokemon.ability_id if pokemon.ability_revealed_to_opponent else None
        )
        hp = None
        max_hp = None
        stats = None
    hp_fraction = (
        (pokemon.hp * 1_000_000) // pokemon.stats.max_hp if is_own else None
    )
    return ObservedPokemon(
        instance_id=pokemon.instance_id,
        pokemon_id=pokemon.pokemon_id,
        level=pokemon.level,
        hp=hp,
        max_hp=max_hp,
        hp_fraction_millionths=hp_fraction,
        stats=stats,
        types=pokemon.types,
        moves=moves,
        item_id=item_id,
        consumed_item_id=consumed_item_id,
        ability_id=ability_id,
        status_id=pokemon.status_id,
        stat_stages=pokemon.stat_stages,
        volatile_statuses=pokemon.volatile_statuses,
        is_active=is_active,
        mega_evolved=pokemon.mega_evolved,
    )


def _observed_side(side: SideState, *, is_own: bool) -> ObservedSide:
    visible = (
        side.team
        if is_own
        else tuple(p for p in side.team if p.revealed_to_opponent)
    )
    observed = tuple(
        _observed_pokemon(
            pokemon,
            is_own=is_own,
            is_active=pokemon.instance_id == side.active_instance_id,
        )
        for pokemon in visible
    )
    visible_ids = {pokemon.instance_id for pokemon in visible}
    active_id = (
        side.active_instance_id if side.active_instance_id in visible_ids else None
    )
    return ObservedSide(
        player=side.player,
        team_size=len(side.team),
        pokemon=observed,
        unrevealed_count=0 if is_own else len(side.team) - len(visible),
        active_instance_id=active_id,
        mega_evolution_used=any(pokemon.mega_evolved for pokemon in visible),
    )


def make_player_observation(
    state: BattleState,
    viewer: PlayerId,
) -> PlayerObservation:
    """Create the complete, centrally-filtered observation for one player."""

    return PlayerObservation(
        battle_id=state.battle_id,
        ruleset_id=state.ruleset_id,
        viewer=viewer,
        turn=state.turn,
        phase=state.phase,
        own_side=_observed_side(state.side(viewer), is_own=True),
        opponent_side=_observed_side(state.side(viewer.opponent), is_own=False),
        field_conditions=state.field_conditions,
        winner=state.winner,
    )


@dataclass(frozen=True, slots=True)
class LegalAction:
    action_id: str
    kind: ActionKind
    move_id: MoveId | None = None
    switch_to: PokemonInstanceId | None = None

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("action_id must be non-empty")
        if self.kind is ActionKind.MOVE:
            if self.move_id is None or self.switch_to is not None:
                raise ValueError("move actions require only move_id")
        elif self.kind is ActionKind.SWITCH:
            if self.switch_to is None or self.move_id is not None:
                raise ValueError("switch actions require only switch_to")
        elif self.move_id is not None or self.switch_to is not None:
            raise ValueError("pass/forfeit actions carry no catalog choice")


@dataclass(frozen=True, slots=True)
class DecisionRequest:
    request_id: str
    player: PlayerId
    kind: DecisionKind
    legal_actions: tuple[LegalAction, ...]

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id must be non-empty")
        if not self.legal_actions:
            raise ValueError("a decision request must contain legal actions")
        ids = [action.action_id for action in self.legal_actions]
        if len(set(ids)) != len(ids):
            raise ValueError("legal action IDs must be unique within a request")
        if self.kind is DecisionKind.FORCED_SWITCH and any(
            action.kind is not ActionKind.SWITCH for action in self.legal_actions
        ):
            raise ValueError("forced-switch requests may only contain switches")


@dataclass(frozen=True, slots=True)
class DecisionRequestSet:
    requests: tuple[DecisionRequest, ...]

    def __post_init__(self) -> None:
        if len(self.requests) not in (1, 2):
            raise ValueError("a request set must contain one or two players")
        players = [request.player for request in self.requests]
        if len(set(players)) != len(players):
            raise ValueError("a player may only have one pending request")
        request_ids = [request.request_id for request in self.requests]
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("request IDs must be unique within a set")

    @property
    def simultaneous(self) -> bool:
        return len(self.requests) == 2

    def for_player(self, player: PlayerId) -> DecisionRequest | None:
        for request in self.requests:
            if request.player is player:
                return request
        return None


@dataclass(frozen=True, slots=True)
class ActionSelection:
    request_id: str
    player: PlayerId
    action_id: str


@dataclass(frozen=True, slots=True)
class BattleEvent:
    sequence: int
    kind: BattleEventKind
    actor: PlayerId | None = None
    subject: PokemonInstanceId | None = None
    details: tuple[tuple[str, EventScalar], ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("event sequence must be non-negative")
        keys = [key for key, _ in self.details]
        if any(not key for key in keys):
            raise ValueError("event detail keys must be non-empty")
        if len(set(keys)) != len(keys):
            raise ValueError("event detail keys must be unique")
        if any(
            value is not None and not isinstance(value, (str, int, bool))
            for _, value in self.details
        ):
            raise TypeError("event detail values must be canonical scalars")


@dataclass(frozen=True, slots=True)
class TransitionResult:
    state: BattleState
    events: tuple[BattleEvent, ...]
    next_decisions: DecisionRequestSet | None
    rng: ExplicitRNG
    terminal: bool
    winner: PlayerId | None = None

    def __post_init__(self) -> None:
        if self.terminal != (self.state.phase is BattlePhase.FINISHED):
            raise ValueError("terminal must agree with the battle phase")
        if self.winner != self.state.winner:
            raise ValueError("result winner must agree with state winner")
        if self.terminal and self.next_decisions is not None:
            raise ValueError("terminal transitions cannot request another decision")
        sequences = [event.sequence for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("event sequences must be strictly increasing")
