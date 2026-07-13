"""Versioned replay records built only from stable core contracts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, TypeVar

from .canonical import canonical_hash, canonical_json
from .ids import AbilityId, ItemId, MoveId, PokemonId, PokemonInstanceId, RuleSetId
from .model import (
    ActionKind,
    ActionSelection,
    BattleEvent,
    BattleEventKind,
    BattlePhase,
    BattleState,
    DecisionKind,
    DecisionRequest,
    DecisionRequestSet,
    LegalAction,
    MegaEvolutionStatProfile,
    MoveSlotState,
    PlayerId,
    PokemonState,
    SideState,
    StatBlock,
    StatStages,
    TrainingStatBlock,
)
from .rng import ExplicitRNG


REPLAY_SCHEMA_VERSION = "2.0.0"
SIMULATOR_VERSION = "0.1.0"
RNG_ALGORITHM_ID = "splitmix64-v1"
BATTLE_STATE_ENCODING = "champions_sim.battle_state.v1"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_PROVISIONAL_DECISION_PATTERN = re.compile(r"^PD-[0-9]{3}$")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,239}$")


def _validate_hash(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _validate_stable_id(value: str, field_name: str) -> None:
    if _STABLE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a stable ID")


def _validate_stable_ids(
    values: tuple[str, ...],
    field_name: str,
    *,
    require_nonempty: bool = False,
) -> None:
    if require_nonempty and not values:
        raise ValueError(f"{field_name} must not be empty")
    if any(not value for value in values):
        raise ValueError(f"{field_name} values must be non-empty")
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} values must be unique")


@dataclass(frozen=True, slots=True)
class ReplayBundle:
    """Exact simulator/data semantics under which a replay was produced."""

    simulator_version: str
    engine_semantics_version: str
    ruleset_id: RuleSetId
    ruleset_content_hash: str
    catalog_id: str
    catalog_content_hash: str

    def __post_init__(self) -> None:
        if not self.simulator_version or not self.engine_semantics_version:
            raise ValueError("simulator and engine semantics versions are required")
        _validate_stable_id(self.engine_semantics_version, "engine_semantics_version")
        _validate_stable_id(str(self.ruleset_id), "ruleset_id")
        _validate_stable_id(self.catalog_id, "catalog_id")
        _validate_hash(self.ruleset_content_hash, "ruleset_content_hash")
        _validate_hash(self.catalog_content_hash, "catalog_content_hash")


@dataclass(frozen=True, slots=True)
class ReplayInitialState:
    """Complete, private battle state before engine initialization."""

    encoding: str
    payload: BattleState
    state_hash: str

    def __post_init__(self) -> None:
        if self.encoding != BATTLE_STATE_ENCODING:
            raise ValueError(f"unsupported battle state encoding: {self.encoding}")
        _validate_hash(self.state_hash, "initial_state.state_hash")
        if canonical_hash(self.payload) != self.state_hash:
            raise ValueError("initial state hash does not match its payload")

    @classmethod
    def capture(cls, state: BattleState) -> "ReplayInitialState":
        return cls(
            encoding=BATTLE_STATE_ENCODING,
            payload=state,
            state_hash=canonical_hash(state),
        )


class ReplayOutcome(str, Enum):
    PLAYER_WIN = "player_win"
    DRAW = "draw"
    ABORTED = "aborted"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ReplayResult:
    outcome: ReplayOutcome
    winner: PlayerId | None
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("replay result reason must be non-empty")
        if self.outcome is ReplayOutcome.PLAYER_WIN and self.winner is None:
            raise ValueError("player_win requires a winner")
        if self.outcome is not ReplayOutcome.PLAYER_WIN and self.winner is not None:
            raise ValueError("only player_win may carry a winner")


class ReplayRedaction(str, Enum):
    NONE = "none"
    PLAYER_VIEW = "player_view"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class ReplayVisibility:
    contains_private_state: bool
    redaction: ReplayRedaction

    def __post_init__(self) -> None:
        if self.contains_private_state != (self.redaction is ReplayRedaction.NONE):
            raise ValueError(
                "unredacted replays contain private state; redacted replays do not"
            )


@dataclass(frozen=True, slots=True)
class ReplayStep:
    requests: DecisionRequestSet
    selections: tuple[ActionSelection, ...]
    rng_before: ExplicitRNG
    rng_after: ExplicitRNG
    events: tuple[BattleEvent, ...]
    result_state_hash: str
    terminal: bool
    provisional_decision_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_hash(self.result_state_hash, "result_state_hash")
        expected = {request.player for request in self.requests.requests}
        actual = {selection.player for selection in self.selections}
        if actual != expected:
            raise ValueError("replay selections must cover every requested player")
        if len(actual) != len(self.selections):
            raise ValueError("a replay step may only select once per player")
        request_by_player = {
            request.player: request for request in self.requests.requests
        }
        for selection in self.selections:
            request = request_by_player[selection.player]
            if selection.request_id != request.request_id:
                raise ValueError("selection request_id does not match the request")
            if selection.action_id not in {
                action.action_id for action in request.legal_actions
            }:
                raise ValueError("selection must reference a legal action")
        _validate_stable_ids(
            self.provisional_decision_ids, "provisional_decision_ids"
        )
        if any(
            _PROVISIONAL_DECISION_PATTERN.fullmatch(value) is None
            for value in self.provisional_decision_ids
        ):
            raise ValueError("invalid provisional decision ID")


@dataclass(frozen=True, slots=True)
class ReplayRecord:
    """Self-contained deterministic replay contract.

    ``initial_state`` is the complete state *before* ``BattleEngine.initialize``.
    The initialization event/RNG boundary is recorded separately so replay does
    not silently discard switch-in effects or future initialization randomness.
    """

    schema_version: str
    replay_id: str
    bundle: ReplayBundle
    rng_algorithm_id: str
    initial_rng: ExplicitRNG
    rng_after_initialization: ExplicitRNG
    final_rng: ExplicitRNG
    initial_state: ReplayInitialState
    initial_events: tuple[BattleEvent, ...]
    initialized_state_hash: str
    steps: tuple[ReplayStep, ...]
    result: ReplayResult
    final_state_hash: str
    visibility: ReplayVisibility
    provisional_decision_ids: tuple[str, ...]
    source_manifest_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_SCHEMA_VERSION:
            raise ValueError(
                f"only replay schema {REPLAY_SCHEMA_VERSION} is supported"
            )
        _validate_stable_id(self.replay_id, "replay_id")
        if self.rng_algorithm_id != RNG_ALGORITHM_ID:
            raise ValueError(f"unsupported RNG algorithm: {self.rng_algorithm_id}")
        if self.bundle.ruleset_id != self.initial_state.payload.ruleset_id:
            raise ValueError("replay bundle ruleset must match the initial state")
        _validate_hash(self.initialized_state_hash, "initialized_state_hash")
        _validate_hash(self.final_state_hash, "final_state_hash")
        if not self.visibility.contains_private_state:
            raise ValueError("Replay v2 requires a complete private initial state")

        rng_values = (
            self.initial_rng,
            self.rng_after_initialization,
            self.final_rng,
        )
        if any(rng.seed != self.initial_rng.seed for rng in rng_values):
            raise ValueError("engine RNG states must share the replay seed")
        expected_rng = self.rng_after_initialization
        for step in self.steps:
            if step.rng_before != expected_rng:
                raise ValueError("replay RNG states are not contiguous")
            expected_rng = step.rng_after
        if self.final_rng != expected_rng:
            raise ValueError("final_rng does not match the final transition")

        expected_final_hash = (
            self.steps[-1].result_state_hash
            if self.steps
            else self.initialized_state_hash
        )
        if self.final_state_hash != expected_final_hash:
            raise ValueError("final_state_hash does not match the final replay boundary")
        if self.steps and not self.steps[-1].terminal:
            raise ValueError("a completed ReplayRecord must end with a terminal step")

        _validate_stable_ids(
            self.provisional_decision_ids, "provisional_decision_ids"
        )
        if any(
            _PROVISIONAL_DECISION_PATTERN.fullmatch(value) is None
            for value in self.provisional_decision_ids
        ):
            raise ValueError("invalid provisional decision ID")
        replay_decisions = set(self.provisional_decision_ids)
        if any(
            not set(step.provisional_decision_ids) <= replay_decisions
            for step in self.steps
        ):
            raise ValueError("step provisional decisions must be declared by the replay")
        _validate_stable_ids(
            self.source_manifest_ids,
            "source_manifest_ids",
            require_nonempty=True,
        )
        for source_manifest_id in self.source_manifest_ids:
            _validate_stable_id(source_manifest_id, "source_manifest_id")

    @property
    def battle_id(self) -> str:
        return self.initial_state.payload.battle_id

    @property
    def ruleset_id(self) -> RuleSetId:
        return self.bundle.ruleset_id

    def to_json(self) -> str:
        return canonical_json(self)

    @classmethod
    def from_json(cls, payload: str) -> "ReplayRecord":
        raw = json.loads(payload, object_pairs_hook=_reject_duplicate_object_keys)
        if not isinstance(raw, dict):
            raise ValueError("replay JSON root must be an object")
        return _replay_record(raw)

    @property
    def replay_hash(self) -> str:
        return canonical_hash(self)


T = TypeVar("T")


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"replay JSON contains duplicate object key: {key}")
        result[key] = value
    return result


def _exact_object(
    raw: Any,
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
    label: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a JSON object")
    actual = set(raw)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing:
        raise ValueError(f"{label} is missing fields: {missing}")
    if unknown:
        raise ValueError(f"{label} has unknown fields: {unknown}")
    return raw


def _tuple(items: Any, converter: Callable[[Any], T]) -> tuple[T, ...]:
    if not isinstance(items, list):
        raise ValueError("expected a JSON array")
    return tuple(converter(item) for item in items)


def _stat_block(raw: dict[str, Any]) -> StatBlock:
    _exact_object(
        raw,
        required=frozenset(
            {
                "max_hp",
                "attack",
                "defense",
                "special_attack",
                "special_defense",
                "speed",
            }
        ),
        label="stats",
    )
    return StatBlock(**raw)


def _training_stat_block(raw: dict[str, Any]) -> TrainingStatBlock:
    _exact_object(
        raw,
        required=frozenset(
            {"hp", "attack", "defense", "special_attack", "special_defense", "speed"}
        ),
        label="training stats",
    )
    return TrainingStatBlock(**raw)


def _mega_evolution_profile(raw: dict[str, Any]) -> MegaEvolutionStatProfile:
    _exact_object(
        raw,
        required=frozenset(
            {
                "target_pokemon_id",
                "stats",
                "level",
                "ivs",
                "evs",
                "nature_increased_stat",
                "nature_decreased_stat",
                "derivation_method_id",
                "source_manifest_id",
                "source_record_id",
                "profile_hash",
            }
        ),
        label="Mega Evolution stat profile",
    )
    return MegaEvolutionStatProfile(
        target_pokemon_id=PokemonId(raw["target_pokemon_id"]),
        stats=_stat_block(raw["stats"]),
        level=raw["level"],
        ivs=_training_stat_block(raw["ivs"]),
        evs=_training_stat_block(raw["evs"]),
        nature_increased_stat=raw["nature_increased_stat"],
        nature_decreased_stat=raw["nature_decreased_stat"],
        derivation_method_id=raw["derivation_method_id"],
        source_manifest_id=raw["source_manifest_id"],
        source_record_id=raw["source_record_id"],
        profile_hash=raw["profile_hash"],
    )


def _stat_stages(raw: dict[str, Any]) -> StatStages:
    _exact_object(
        raw,
        required=frozenset(
            {
                "attack",
                "defense",
                "special_attack",
                "special_defense",
                "speed",
                "accuracy",
                "evasion",
            }
        ),
        label="stat stages",
    )
    return StatStages(**raw)


def _move_slot(raw: dict[str, Any]) -> MoveSlotState:
    _exact_object(
        raw,
        required=frozenset({"move_id", "pp", "max_pp", "revealed_to_opponent"}),
        label="move slot",
    )
    return MoveSlotState(
        move_id=MoveId(raw["move_id"]),
        pp=raw["pp"],
        max_pp=raw["max_pp"],
        revealed_to_opponent=raw["revealed_to_opponent"],
    )


def _pokemon(raw: dict[str, Any]) -> PokemonState:
    _exact_object(
        raw,
        required=frozenset(
            {
                "instance_id",
                "pokemon_id",
                "level",
                "hp",
                "stats",
                "types",
                "moves",
                "item_id",
                "consumed_item_id",
                "ability_id",
                "status_id",
                "stat_stages",
                "volatile_statuses",
                "revealed_to_opponent",
                "item_revealed_to_opponent",
                "ability_revealed_to_opponent",
            }
        ),
        optional=frozenset({"mega_evolved", "mega_evolution_profile"}),
        label="Pokemon state",
    )
    mega_profile = raw.get("mega_evolution_profile")
    return PokemonState(
        instance_id=PokemonInstanceId(raw["instance_id"]),
        pokemon_id=PokemonId(raw["pokemon_id"]),
        level=raw["level"],
        hp=raw["hp"],
        stats=_stat_block(raw["stats"]),
        types=tuple(raw["types"]),
        moves=_tuple(raw["moves"], _move_slot),
        item_id=ItemId(raw["item_id"]) if raw["item_id"] is not None else None,
        consumed_item_id=(
            ItemId(raw["consumed_item_id"])
            if raw["consumed_item_id"] is not None
            else None
        ),
        ability_id=(
            AbilityId(raw["ability_id"])
            if raw["ability_id"] is not None
            else None
        ),
        status_id=raw["status_id"],
        stat_stages=_stat_stages(raw["stat_stages"]),
        volatile_statuses=tuple(raw["volatile_statuses"]),
        revealed_to_opponent=raw["revealed_to_opponent"],
        item_revealed_to_opponent=raw["item_revealed_to_opponent"],
        ability_revealed_to_opponent=raw["ability_revealed_to_opponent"],
        mega_evolved=raw.get("mega_evolved", False),
        mega_evolution_profile=(
            _mega_evolution_profile(mega_profile)
            if mega_profile is not None
            else None
        ),
    )


def _side(raw: dict[str, Any]) -> SideState:
    _exact_object(
        raw,
        required=frozenset({"player", "team", "active_instance_id"}),
        label="side state",
    )
    return SideState(
        player=PlayerId(raw["player"]),
        team=_tuple(raw["team"], _pokemon),
        active_instance_id=PokemonInstanceId(raw["active_instance_id"]),
    )


def _battle_state(raw: dict[str, Any]) -> BattleState:
    _exact_object(
        raw,
        required=frozenset(
            {
                "battle_id",
                "ruleset_id",
                "turn",
                "phase",
                "sides",
                "field_conditions",
                "winner",
            }
        ),
        label="battle state",
    )
    winner = raw["winner"]
    return BattleState(
        battle_id=raw["battle_id"],
        ruleset_id=RuleSetId(raw["ruleset_id"]),
        turn=raw["turn"],
        phase=BattlePhase(raw["phase"]),
        sides=_tuple(raw["sides"], _side),
        field_conditions=tuple(raw["field_conditions"]),
        winner=PlayerId(winner) if winner is not None else None,
    )


def _legal_action(raw: dict[str, Any]) -> LegalAction:
    _exact_object(
        raw,
        required=frozenset({"action_id", "kind", "move_id", "switch_to"}),
        label="legal action",
    )
    return LegalAction(
        action_id=raw["action_id"],
        kind=ActionKind(raw["kind"]),
        move_id=MoveId(raw["move_id"]) if raw["move_id"] is not None else None,
        switch_to=(
            PokemonInstanceId(raw["switch_to"])
            if raw["switch_to"] is not None
            else None
        ),
    )


def _decision_request(raw: dict[str, Any]) -> DecisionRequest:
    _exact_object(
        raw,
        required=frozenset({"request_id", "player", "kind", "legal_actions"}),
        label="decision request",
    )
    return DecisionRequest(
        request_id=raw["request_id"],
        player=PlayerId(raw["player"]),
        kind=DecisionKind(raw["kind"]),
        legal_actions=_tuple(raw["legal_actions"], _legal_action),
    )


def _request_set(raw: dict[str, Any]) -> DecisionRequestSet:
    _exact_object(
        raw,
        required=frozenset({"requests"}),
        label="decision request set",
    )
    return DecisionRequestSet(
        requests=_tuple(raw["requests"], _decision_request),
    )


def _selection(raw: dict[str, Any]) -> ActionSelection:
    _exact_object(
        raw,
        required=frozenset({"request_id", "player", "action_id"}),
        label="action selection",
    )
    return ActionSelection(
        request_id=raw["request_id"],
        player=PlayerId(raw["player"]),
        action_id=raw["action_id"],
    )


def _rng(raw: dict[str, Any]) -> ExplicitRNG:
    _exact_object(
        raw,
        required=frozenset({"seed", "state", "cursor"}),
        label="RNG state",
    )
    return ExplicitRNG(seed=raw["seed"], state=raw["state"], cursor=raw["cursor"])


def _event(raw: dict[str, Any]) -> BattleEvent:
    _exact_object(
        raw,
        required=frozenset({"sequence", "kind", "actor", "subject", "details"}),
        label="battle event",
    )
    actor = raw["actor"]
    subject = raw["subject"]
    return BattleEvent(
        sequence=raw["sequence"],
        kind=BattleEventKind(raw["kind"]),
        actor=PlayerId(actor) if actor is not None else None,
        subject=PokemonInstanceId(subject) if subject is not None else None,
        details=tuple((key, value) for key, value in raw["details"]),
    )


def _bundle(raw: dict[str, Any]) -> ReplayBundle:
    _exact_object(
        raw,
        required=frozenset(
            {
                "simulator_version",
                "engine_semantics_version",
                "ruleset_id",
                "ruleset_content_hash",
                "catalog_id",
                "catalog_content_hash",
            }
        ),
        label="replay bundle",
    )
    return ReplayBundle(
        simulator_version=raw["simulator_version"],
        engine_semantics_version=raw["engine_semantics_version"],
        ruleset_id=RuleSetId(raw["ruleset_id"]),
        ruleset_content_hash=raw["ruleset_content_hash"],
        catalog_id=raw["catalog_id"],
        catalog_content_hash=raw["catalog_content_hash"],
    )


def _initial_state(raw: dict[str, Any]) -> ReplayInitialState:
    _exact_object(
        raw,
        required=frozenset({"encoding", "payload", "state_hash"}),
        label="replay initial state",
    )
    return ReplayInitialState(
        encoding=raw["encoding"],
        payload=_battle_state(raw["payload"]),
        state_hash=raw["state_hash"],
    )


def _result(raw: dict[str, Any]) -> ReplayResult:
    _exact_object(
        raw,
        required=frozenset({"outcome", "winner", "reason"}),
        label="replay result",
    )
    winner = raw["winner"]
    return ReplayResult(
        outcome=ReplayOutcome(raw["outcome"]),
        winner=PlayerId(winner) if winner is not None else None,
        reason=raw["reason"],
    )


def _visibility(raw: dict[str, Any]) -> ReplayVisibility:
    _exact_object(
        raw,
        required=frozenset({"contains_private_state", "redaction"}),
        label="replay visibility",
    )
    return ReplayVisibility(
        contains_private_state=raw["contains_private_state"],
        redaction=ReplayRedaction(raw["redaction"]),
    )


def _replay_step(raw: dict[str, Any]) -> ReplayStep:
    _exact_object(
        raw,
        required=frozenset(
            {
                "requests",
                "selections",
                "rng_before",
                "rng_after",
                "events",
                "result_state_hash",
                "terminal",
                "provisional_decision_ids",
            }
        ),
        label="replay step",
    )
    return ReplayStep(
        requests=_request_set(raw["requests"]),
        selections=_tuple(raw["selections"], _selection),
        rng_before=_rng(raw["rng_before"]),
        rng_after=_rng(raw["rng_after"]),
        events=_tuple(raw["events"], _event),
        result_state_hash=raw["result_state_hash"],
        terminal=raw["terminal"],
        provisional_decision_ids=tuple(raw["provisional_decision_ids"]),
    )


def _replay_record(raw: dict[str, Any]) -> ReplayRecord:
    _exact_object(
        raw,
        required=frozenset(
            {
                "schema_version",
                "replay_id",
                "bundle",
                "rng_algorithm_id",
                "initial_rng",
                "rng_after_initialization",
                "final_rng",
                "initial_state",
                "initial_events",
                "initialized_state_hash",
                "steps",
                "result",
                "final_state_hash",
                "visibility",
                "provisional_decision_ids",
                "source_manifest_ids",
            }
        ),
        label="replay record",
    )
    return ReplayRecord(
        schema_version=raw["schema_version"],
        replay_id=raw["replay_id"],
        bundle=_bundle(raw["bundle"]),
        rng_algorithm_id=raw["rng_algorithm_id"],
        initial_rng=_rng(raw["initial_rng"]),
        rng_after_initialization=_rng(raw["rng_after_initialization"]),
        final_rng=_rng(raw["final_rng"]),
        initial_state=_initial_state(raw["initial_state"]),
        initial_events=_tuple(raw["initial_events"], _event),
        initialized_state_hash=raw["initialized_state_hash"],
        steps=_tuple(raw["steps"], _replay_step),
        result=_result(raw["result"]),
        final_state_hash=raw["final_state_hash"],
        visibility=_visibility(raw["visibility"]),
        provisional_decision_ids=tuple(raw["provisional_decision_ids"]),
        source_manifest_ids=tuple(raw["source_manifest_ids"]),
    )
