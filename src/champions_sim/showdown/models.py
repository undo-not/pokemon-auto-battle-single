"""Stable Python-side records exposed to policies and evaluators."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from champions_sim.core.canonical import canonical_hash, to_canonical_data


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")
_NODE_VERSION = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")
_SODIUM_SEED = re.compile(r"^sodium,[0-9a-f]{64}$")
_ENGINE_FIELDS = {
    "artifact_id",
    "repository_url",
    "commit",
    "tree",
    "build_fingerprint_sha256",
    "manifest_sha256",
    "node_version",
    "license",
    "bridge_protocol_version",
    "bridge_sha256",
}


def _exact(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} fields violate the bridge contract")


def _string(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{label} must be an array of strings")
    return tuple(value)


def _engine(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("replay.engine must be an object")
    _exact(value, _ENGINE_FIELDS, "replay.engine")
    converted = {key: _string(item, f"replay.engine.{key}") for key, item in value.items()}
    if _GIT_OBJECT.fullmatch(converted["commit"]) is None or _GIT_OBJECT.fullmatch(
        converted["tree"]
    ) is None:
        raise ValueError("replay.engine commit and tree must be Git object IDs")
    for field in ("build_fingerprint_sha256", "manifest_sha256", "bridge_sha256"):
        if _SHA256.fullmatch(converted[field]) is None:
            raise ValueError(f"replay.engine.{field} must be a SHA-256 digest")
    if _NODE_VERSION.fullmatch(converted["node_version"]) is None:
        raise ValueError("replay.engine.node_version is invalid")
    if converted["license"] != "MIT" or converted["bridge_protocol_version"] != "1.0.0":
        raise ValueError("replay.engine license or bridge protocol is unsupported")
    return converted


@dataclass(frozen=True, slots=True)
class ShowdownObservation:
    schema_version: str
    session_id: str
    format_id: str
    revision: int
    ended: bool
    winner: str | None
    turn: int
    player: str
    request: Mapping[str, Any] | None
    legal_actions: tuple[str, ...]
    visible_log: tuple[str, ...]
    next_sequence: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ShowdownObservation":
        _exact(
            value,
            {
                "schema_version",
                "session_id",
                "format_id",
                "revision",
                "ended",
                "winner",
                "turn",
                "player",
                "request",
                "legal_actions",
                "visible_log",
                "next_sequence",
            },
            "observation",
        )
        request = value["request"]
        if request is not None and not isinstance(request, dict):
            raise ValueError("observation.request must be an object or null")
        observation = cls(
            schema_version=_string(value["schema_version"], "observation.schema_version"),
            session_id=_string(value["session_id"], "observation.session_id"),
            format_id=_string(value["format_id"], "observation.format_id"),
            revision=_integer(value["revision"], "observation.revision"),
            ended=_boolean(value["ended"], "observation.ended"),
            winner=_string(value["winner"], "observation.winner", nullable=True),
            turn=_integer(value["turn"], "observation.turn"),
            player=_string(value["player"], "observation.player"),
            request=request,
            legal_actions=_strings(value["legal_actions"], "observation.legal_actions"),
            visible_log=_strings(value["visible_log"], "observation.visible_log"),
            next_sequence=_integer(value["next_sequence"], "observation.next_sequence"),
        )
        if observation.schema_version != "1.0.0":
            raise ValueError("unsupported observation schema version")
        if observation.player not in {"p1", "p2"}:
            raise ValueError("observation.player must be p1 or p2")
        if not observation.ended and observation.winner is not None:
            raise ValueError("a non-terminal observation cannot have a winner")
        if len(observation.legal_actions) != len(set(observation.legal_actions)):
            raise ValueError("observation legal actions must be unique")
        return observation


@dataclass(frozen=True, slots=True)
class DamageSample:
    session_id: str
    revision: int
    attacker: str
    source: str
    target: str
    move_id: str
    move_type: str
    move_category: str
    damage: int | None
    damage_status: str
    target_max_hp: int
    target_current_hp: int
    clone_seed_before: str
    clone_seed_after: str
    live_seed_before: str
    live_seed_after: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "DamageSample":
        _exact(
            value,
            {
                "session_id",
                "revision",
                "attacker",
                "source",
                "target",
                "move_id",
                "move_type",
                "move_category",
                "damage",
                "damage_status",
                "target_max_hp",
                "target_current_hp",
                "clone_seed_before",
                "clone_seed_after",
                "live_seed_before",
                "live_seed_after",
            },
            "damage sample",
        )
        damage = value["damage"]
        if damage is not None:
            damage = _integer(damage, "damage_sample.damage")
        sample = cls(
            session_id=_string(value["session_id"], "damage_sample.session_id"),
            revision=_integer(value["revision"], "damage_sample.revision"),
            attacker=_string(value["attacker"], "damage_sample.attacker"),
            source=_string(value["source"], "damage_sample.source"),
            target=_string(value["target"], "damage_sample.target"),
            move_id=_string(value["move_id"], "damage_sample.move_id"),
            move_type=_string(value["move_type"], "damage_sample.move_type"),
            move_category=_string(value["move_category"], "damage_sample.move_category"),
            damage=damage,
            damage_status=_string(value["damage_status"], "damage_sample.damage_status"),
            target_max_hp=_integer(value["target_max_hp"], "damage_sample.target_max_hp", minimum=1),
            target_current_hp=_integer(value["target_current_hp"], "damage_sample.target_current_hp"),
            clone_seed_before=_string(value["clone_seed_before"], "damage_sample.clone_seed_before"),
            clone_seed_after=_string(value["clone_seed_after"], "damage_sample.clone_seed_after"),
            live_seed_before=_string(value["live_seed_before"], "damage_sample.live_seed_before"),
            live_seed_after=_string(value["live_seed_after"], "damage_sample.live_seed_after"),
        )
        if sample.attacker not in {"p1", "p2"}:
            raise ValueError("damage_sample.attacker must be p1 or p2")
        if sample.move_category not in {"Physical", "Special", "Status"}:
            raise ValueError("damage_sample.move_category is invalid")
        if sample.damage_status not in {
            "value",
            "blocked",
            "silent_failure",
            "non_damaging",
        }:
            raise ValueError("damage_sample.damage_status is invalid")
        if (sample.damage_status == "value") != (sample.damage is not None):
            raise ValueError("damage_sample status and numeric damage disagree")
        for field in (
            "clone_seed_before",
            "clone_seed_after",
            "live_seed_before",
            "live_seed_after",
        ):
            if _SODIUM_SEED.fullmatch(getattr(sample, field)) is None:
                raise ValueError(f"damage_sample.{field} must be a Showdown sodium seed")
        if sample.target_current_hp > sample.target_max_hp:
            raise ValueError("damage_sample target HP exceeds its maximum")
        if sample.clone_seed_before != sample.live_seed_before:
            raise ValueError("damage_sample clone did not start from the live PRNG state")
        if sample.live_seed_before != sample.live_seed_after:
            raise ValueError("damage_sample mutated the live PRNG state")
        return sample


@dataclass(frozen=True, slots=True)
class ShowdownReplay:
    document: Mapping[str, Any]

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
        *,
        engine: Mapping[str, Any],
    ) -> "ShowdownReplay":
        _exact(
            value,
            {
                "schema_version",
                "format_id",
                "seed",
                "input_log",
                "public_log",
                "ended",
                "winner",
                "turns",
                "score",
            },
            "replay",
        )
        seed = _string(value["seed"], "replay.seed")
        if _SODIUM_SEED.fullmatch(seed) is None:
            raise ValueError("replay.seed must be a 32-byte Showdown sodium seed")
        score = value["score"]
        if score is not None and (
            not isinstance(score, list)
            or len(score) != 2
            or any(
                not isinstance(item, int) or isinstance(item, bool) or item < 0
                for item in score
            )
        ):
            raise ValueError("replay.score must contain two non-negative integers or null")
        ended = _boolean(value["ended"], "replay.ended")
        winner = _string(value["winner"], "replay.winner", nullable=True)
        if not ended and (winner is not None or score is not None):
            raise ValueError("a non-terminal replay cannot have a winner or score")
        schema_version = _string(value["schema_version"], "replay.schema_version")
        if schema_version != "1.0.0":
            raise ValueError("unsupported replay schema version")
        document = {
            "schema_version": schema_version,
            "format_id": _string(value["format_id"], "replay.format_id"),
            "seed": seed,
            "input_log": list(_strings(value["input_log"], "replay.input_log")),
            "public_log": list(_strings(value["public_log"], "replay.public_log")),
            "ended": ended,
            "winner": winner,
            "turns": _integer(value["turns"], "replay.turns"),
            "score": list(score) if score is not None else None,
            "engine": _engine(engine),
        }
        return cls(document)

    @classmethod
    def from_document(cls, value: Mapping[str, Any]) -> "ShowdownReplay":
        _exact(
            value,
            {
                "schema_version",
                "format_id",
                "seed",
                "input_log",
                "public_log",
                "ended",
                "winner",
                "turns",
                "score",
                "engine",
                "replay_hash",
            },
            "replay document",
        )
        replay = cls.from_mapping(
            {key: item for key, item in value.items() if key not in {"engine", "replay_hash"}},
            engine=value["engine"],
        )
        claimed_hash = _string(value["replay_hash"], "replay.replay_hash")
        if _SHA256.fullmatch(claimed_hash) is None or claimed_hash != replay.replay_hash:
            raise ValueError("replay hash does not match the canonical document")
        return replay

    @property
    def replay_hash(self) -> str:
        value = dict(self.document)
        value.pop("replay_hash", None)
        return canonical_hash(value)

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self.document)
        assert isinstance(value, dict)
        value["replay_hash"] = self.replay_hash
        return value
