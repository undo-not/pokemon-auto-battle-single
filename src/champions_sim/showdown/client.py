"""Python facade over the persistent pinned Showdown bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from .models import DamageSample, ShowdownObservation, ShowdownReplay
from .process import PROTOCOL_VERSION, ShowdownProcess
from .resolver import ResolvedShowdown, resolve_showdown


Team = Sequence[Mapping[str, object]]


def _validate_session_summary(
    value: Mapping[str, Any], *, session_id: str, format_id: str
) -> Mapping[str, Any]:
    if set(value) != {"session_id", "format_id", "revision", "ended", "winner", "turn"}:
        raise RuntimeError("Showdown session summary fields violate the protocol")
    if value["session_id"] != session_id or value["format_id"] != format_id:
        raise RuntimeError("Showdown session summary identity mismatch")
    for field in ("revision", "turn"):
        if (
            not isinstance(value[field], int)
            or isinstance(value[field], bool)
            or value[field] < 0
        ):
            raise RuntimeError(f"Showdown session summary {field} is invalid")
    if not isinstance(value["ended"], bool):
        raise RuntimeError("Showdown session summary ended is invalid")
    if value["winner"] is not None and not isinstance(value["winner"], str):
        raise RuntimeError("Showdown session summary winner is invalid")
    if not value["ended"] and value["winner"] is not None:
        raise RuntimeError("a non-terminal Showdown session cannot have a winner")
    return value


class ShowdownClient:
    def __init__(
        self,
        *,
        root: Path | None = None,
        node_executable: Path | None = None,
        manifest_path: Path | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.resolved: ResolvedShowdown = resolve_showdown(
            root=root,
            node_executable=node_executable,
            manifest_path=manifest_path,
        )
        self.process = ShowdownProcess(self.resolved, timeout_seconds=timeout_seconds)
        for expected in self.resolved.manifest.formats:
            actual = self.process.request("describe_format", {"format_id": expected.id})
            if set(actual) != {"id", "name", "mod", "game_type", "ruleset"} or not isinstance(
                actual.get("ruleset"), list
            ) or any(not isinstance(item, str) for item in actual["ruleset"]):
                self.close()
                raise RuntimeError("Showdown format response violates the bridge contract")
            identity = (actual.get("id"), actual.get("name"), actual.get("mod"), actual.get("game_type"))
            required = (expected.id, expected.name, expected.mod, "singles")
            if identity != required:
                self.close()
                raise RuntimeError(f"Showdown format identity mismatch: expected {required!r}, got {identity!r}")

    @property
    def default_format_id(self) -> str:
        return self.resolved.manifest.default_format.id

    def engine_identity(self) -> dict[str, object]:
        return {
            **self.resolved.identity(),
            "bridge_protocol_version": PROTOCOL_VERSION,
            "bridge_sha256": self.process.bridge_sha256,
        }

    def validate_team(self, team: Team, *, format_id: str | None = None) -> tuple[str, ...]:
        result = self.process.request(
            "validate_team",
            {"format_id": format_id or self.default_format_id, "team": list(team)},
        )
        problems = result.get("problems")
        if set(result) != {"valid", "problems"} or not isinstance(
            result.get("valid"), bool
        ) or not isinstance(problems, list):
            raise RuntimeError("Showdown bridge returned an invalid validation result")
        if result["valid"] != (not problems):
            raise RuntimeError("Showdown bridge returned inconsistent team validity")
        return tuple(str(problem) for problem in problems)

    def create_session(
        self,
        *,
        session_id: str,
        seed: Sequence[int],
        p1_name: str,
        p1_team: Team,
        p2_name: str,
        p2_team: Team,
        format_id: str | None = None,
    ) -> "ShowdownSession":
        selected_format = format_id or self.default_format_id
        summary = self.process.request(
            "create_session",
            {
                "session_id": session_id,
                "format_id": selected_format,
                "seed": list(seed),
                "players": {
                    "p1": {"name": p1_name, "team": list(p1_team)},
                    "p2": {"name": p2_name, "team": list(p2_team)},
                },
            },
        )
        _validate_session_summary(
            summary, session_id=session_id, format_id=selected_format
        )
        return ShowdownSession(self, session_id=session_id, format_id=selected_format)

    def close(self) -> None:
        process = getattr(self, "process", None)
        if process is not None:
            process.close()

    def replay_input_log(self, document: Mapping[str, Any]) -> ShowdownReplay:
        expected = ShowdownReplay.from_document(document)
        if expected.document["engine"] != self.engine_identity():
            raise RuntimeError("Replay engine identity does not match the active Showdown engine")
        result = self.process.request(
            "replay_input_log", {"input_log": expected.document["input_log"]}
        )
        actual = ShowdownReplay.from_mapping(result, engine=self.engine_identity())
        if actual.to_dict() != expected.to_dict():
            raise RuntimeError("Replay execution does not reproduce the canonical document")
        return actual

    def __enter__(self) -> "ShowdownClient":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class ShowdownSession:
    def __init__(self, client: ShowdownClient, *, session_id: str, format_id: str) -> None:
        self.client = client
        self.session_id = session_id
        self.format_id = format_id
        self._closed = False

    def observe(self, player: str, *, since: int = 0) -> ShowdownObservation:
        result = self.client.process.request(
            "observe", {"session_id": self.session_id, "player": player, "since": since}
        )
        observation = ShowdownObservation.from_mapping(result)
        if (
            observation.session_id != self.session_id
            or observation.format_id != self.format_id
            or observation.player != player
        ):
            raise RuntimeError("Showdown observation identity mismatch")
        return observation

    def choose(self, player: str, choice: str) -> Mapping[str, Any]:
        result = self.client.process.request(
            "choose", {"session_id": self.session_id, "player": player, "choice": choice}
        )
        return _validate_session_summary(
            result, session_id=self.session_id, format_id=self.format_id
        )

    def damage_sample(self, attacker: str, move: str) -> DamageSample:
        result = self.client.process.request(
            "damage_sample",
            {"session_id": self.session_id, "attacker": attacker, "move": move},
        )
        sample = DamageSample.from_mapping(result)
        if sample.session_id != self.session_id or sample.attacker != attacker:
            raise RuntimeError("Showdown damage sample identity mismatch")
        return sample

    def replay(self) -> ShowdownReplay:
        result = self.client.process.request(
            "export_replay", {"session_id": self.session_id}
        )
        replay = ShowdownReplay.from_mapping(
            result,
            engine=self.client.engine_identity(),
        )
        if replay.document["format_id"] != self.format_id:
            raise RuntimeError("Showdown Replay format identity mismatch")
        return replay

    def close(self) -> None:
        if self._closed:
            return
        result = self.client.process.request(
            "close_session", {"session_id": self.session_id}
        )
        if result != {"session_id": self.session_id, "closed": True}:
            raise RuntimeError("Showdown close response violates the bridge contract")
        self._closed = True

    def __enter__(self) -> "ShowdownSession":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()
