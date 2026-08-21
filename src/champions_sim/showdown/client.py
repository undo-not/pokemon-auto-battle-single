"""Python facade over the persistent pinned Showdown bridge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from champions_sim.core import to_canonical_data

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
            if set(actual) != {
                "id",
                "name",
                "mod",
                "game_type",
                "ruleset",
                "rule_table",
                "team_constraints",
            }:
                self.close()
                raise RuntimeError("Showdown format response violates the bridge contract")
            for field in ("ruleset", "rule_table"):
                if not isinstance(actual[field], list) or any(
                    not isinstance(item, str) for item in actual[field]
                ):
                    self.close()
                    raise RuntimeError(
                        "Showdown format response violates the bridge contract"
                    )
            constraints = actual["team_constraints"]
            if (
                not isinstance(constraints, dict)
                or set(constraints) != set(expected.team_constraints.to_dict())
                or any(
                    value is not None and type(value) is not int
                    for value in constraints.values()
                )
            ):
                self.close()
                raise RuntimeError(
                    "Showdown format response violates the bridge contract"
                )
            identity = (
                actual.get("id"),
                actual.get("name"),
                actual.get("mod"),
                actual.get("game_type"),
            )
            required = (expected.id, expected.name, expected.mod, expected.game_type)
            if identity != required:
                self.close()
                raise RuntimeError(f"Showdown format identity mismatch: expected {required!r}, got {identity!r}")
            if tuple(actual["ruleset"]) != expected.ruleset:
                self.close()
                raise RuntimeError(
                    "Showdown format ruleset mismatch: "
                    f"expected {expected.ruleset!r}, got {tuple(actual['ruleset'])!r}"
                )
            if tuple(actual["rule_table"]) != expected.rule_table:
                self.close()
                raise RuntimeError("Showdown effective rule table mismatch")
            if constraints != expected.team_constraints.to_dict():
                self.close()
                raise RuntimeError("Showdown team constraints mismatch")

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
        selected_format = format_id or self.default_format_id
        binding = self.resolved.manifest.format_by_id(selected_format)
        if binding is not None and binding.purpose != "battle":
            raise ValueError(f"format is not a battle binding: {selected_format}")
        result = self.process.request(
            "validate_team",
            {"format_id": selected_format, "team": list(team)},
        )
        problems = result.get("problems")
        if set(result) != {"valid", "problems"} or not isinstance(
            result.get("valid"), bool
        ) or not isinstance(problems, list):
            raise RuntimeError("Showdown bridge returned an invalid validation result")
        if result["valid"] != (not problems):
            raise RuntimeError("Showdown bridge returned inconsistent team validity")
        return tuple(str(problem) for problem in problems)

    def generate_random_team_candidates(
        self,
        *,
        generation_format_id: str,
        seeds: Sequence[Sequence[int]],
        target_format_id: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        target_id = target_format_id or self.default_format_id
        generation = self.resolved.manifest.format_by_id(generation_format_id)
        target = self.resolved.manifest.format_by_id(target_id)
        if generation is None or generation.purpose != "team_generation":
            raise ValueError(
                f"format is not a team-generation binding: {generation_format_id}"
            )
        if target is None or target.purpose != "battle":
            raise ValueError(f"format is not a battle binding: {target_id}")
        converted_seeds: list[list[int]] = []
        if not isinstance(seeds, Sequence) or isinstance(seeds, (str, bytes)):
            raise ValueError("seeds must be a sequence")
        for index, seed in enumerate(seeds):
            if (
                not isinstance(seed, Sequence)
                or isinstance(seed, (str, bytes))
                or len(seed) != 4
                or any(
                    not isinstance(part, int)
                    or isinstance(part, bool)
                    or not 0 <= part <= 0xFFFF
                    for part in seed
                )
            ):
                raise ValueError(
                    f"seeds[{index}] must contain four integers between 0 and 65535"
                )
            converted_seeds.append(list(seed))
        if not 1 <= len(converted_seeds) <= 512:
            raise ValueError("seeds must contain 1 to 512 Showdown seeds")
        result = self.process.request(
            "generate_random_teams",
            {
                "generation_format_id": generation.id,
                "target_format_id": target.id,
                "seeds": converted_seeds,
            },
        )
        if set(result) != {
            "generation_format_id",
            "target_format_id",
            "candidates",
        } or result.get("generation_format_id") != generation.id or result.get(
            "target_format_id"
        ) != target.id:
            raise RuntimeError("Showdown random-team response identity mismatch")
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or len(candidates) != len(converted_seeds):
            raise RuntimeError("Showdown random-team candidate count mismatch")
        parsed: list[Mapping[str, Any]] = []
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict) or set(candidate) != {
                "generation_seed",
                "team",
                "problems",
            }:
                raise RuntimeError(
                    f"Showdown random-team candidate[{index}] fields are invalid"
                )
            team = candidate["team"]
            problems = candidate["problems"]
            if candidate["generation_seed"] != converted_seeds[index]:
                raise RuntimeError(
                    f"Showdown random-team candidate[{index}] seed mismatch"
                )
            if (
                not isinstance(team, list)
                or len(team) != 6
                or not all(isinstance(item, dict) for item in team)
            ):
                raise RuntimeError(
                    f"Showdown random-team candidate[{index}] team is invalid"
                )
            if not isinstance(problems, list) or not all(
                isinstance(problem, str) for problem in problems
            ):
                raise RuntimeError(
                    f"Showdown random-team candidate[{index}] problems are invalid"
                )
            parsed.append(candidate)
        return tuple(parsed)

    def create_session(
        self,
        *,
        session_id: str,
        seed: str,
        p1_name: str,
        p1_team: Team,
        p2_name: str,
        p2_team: Team,
        format_id: str | None = None,
    ) -> "ShowdownSession":
        selected_format = format_id or self.default_format_id
        binding = self.resolved.manifest.format_by_id(selected_format)
        if binding is not None and binding.purpose != "battle":
            raise ValueError(f"format is not a battle binding: {selected_format}")
        summary = self.process.request(
            "create_session",
            {
                "session_id": session_id,
                "format_id": selected_format,
                "seed": seed,
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
        binding = self.resolved.manifest.format_by_id(expected.document["format_id"])
        if binding is None or binding.purpose != "battle":
            raise RuntimeError("Replay format is not an active battle binding")
        result = self.process.request(
            "replay_input_log", {"input_log": expected.document["input_log"]}
        )
        actual = ShowdownReplay.from_mapping(result, engine=self.engine_identity())
        if actual.to_dict() != expected.to_dict():
            raise RuntimeError("Replay execution does not reproduce the canonical document")
        return actual

    def resolve_replay_expectations(
        self,
        document: Mapping[str, Any],
        selectors: Sequence[Mapping[str, object]],
    ) -> tuple[ShowdownReplay, Mapping[str, Any]]:
        """Re-execute a Replay and resolve bounded player-view JSON pointers."""

        expected = ShowdownReplay.from_document(document)
        if expected.document["engine"] != self.engine_identity():
            raise RuntimeError("Replay engine identity does not match the active Showdown engine")
        binding = self.resolved.manifest.format_by_id(expected.document["format_id"])
        if binding is None or binding.purpose != "battle":
            raise RuntimeError("Replay format is not an active battle binding")
        converted: list[dict[str, object]] = []
        selector_ids: set[str] = set()
        for index, selector in enumerate(selectors):
            if set(selector) != {"selector_id", "player", "revision", "pointer"}:
                raise ValueError(f"Replay selector[{index}] fields are invalid")
            selector_id = selector["selector_id"]
            player = selector["player"]
            revision = selector["revision"]
            pointer = selector["pointer"]
            if (
                not isinstance(selector_id, str)
                or not selector_id
                or selector_id in selector_ids
                or player not in {"p1", "p2"}
                or not isinstance(revision, int)
                or isinstance(revision, bool)
                or revision < 0
                or not isinstance(pointer, str)
                or not pointer.startswith("/")
            ):
                raise ValueError(f"Replay selector[{index}] is invalid")
            selector_ids.add(selector_id)
            converted.append(dict(selector))
        result = self.process.request(
            "resolve_replay_expectations",
            {"input_log": expected.document["input_log"], "selectors": converted},
        )
        if set(result) != {"replay", "expectations"}:
            raise RuntimeError("Replay expectation response fields violate the protocol")
        replay_raw = result["replay"]
        if not isinstance(replay_raw, dict):
            raise RuntimeError("Replay expectation response omitted the Replay")
        actual = ShowdownReplay.from_mapping(replay_raw, engine=self.engine_identity())
        if actual.to_dict() != expected.to_dict():
            raise RuntimeError("Replay expectation execution did not reproduce the Replay")
        raw_expectations = result["expectations"]
        if not isinstance(raw_expectations, list):
            raise RuntimeError("Replay expectations must be an array")
        values: dict[str, Any] = {}
        for index, item in enumerate(raw_expectations):
            if not isinstance(item, dict) or set(item) != {"selector_id", "value"}:
                raise RuntimeError(f"Replay expectation[{index}] fields are invalid")
            selector_id = item["selector_id"]
            if (
                not isinstance(selector_id, str)
                or selector_id not in selector_ids
                or selector_id in values
            ):
                raise RuntimeError("Replay expectation selector identity is invalid")
            try:
                values[selector_id] = to_canonical_data(item["value"])
            except TypeError as error:
                raise RuntimeError("Replay expectation value is not canonical") from error
        if set(values) != selector_ids:
            raise RuntimeError("Replay expectation response is incomplete")
        return actual, values

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

    def choose_with_replay_input(
        self, player: str, choice: str
    ) -> tuple[Mapping[str, Any], str]:
        result = self.client.process.request(
            "choose_with_replay_input",
            {"session_id": self.session_id, "player": player, "choice": choice},
        )
        replay_input = result.get("replay_input")
        if (
            set(result) != {"summary", "replay_input"}
            or not isinstance(result.get("summary"), dict)
            or not isinstance(replay_input, str)
            or not replay_input.startswith(f">{player} ")
            or len(replay_input) > 1024 * 1024
        ):
            raise RuntimeError("Showdown canonical-choice response violates the protocol")
        summary = _validate_session_summary(
            result["summary"], session_id=self.session_id, format_id=self.format_id
        )
        return summary, replay_input

    def damage_sample(self, attacker: str, move: str) -> DamageSample:
        result = self.client.process.request(
            "damage_sample",
            {"session_id": self.session_id, "attacker": attacker, "move": move},
        )
        sample = DamageSample.from_mapping(result)
        if sample.session_id != self.session_id or sample.attacker != attacker:
            raise RuntimeError("Showdown damage sample identity mismatch")
        return sample

    def replay(self, *, allow_incomplete: bool = False) -> ShowdownReplay:
        result = self.client.process.request(
            "export_replay",
            {
                "session_id": self.session_id,
                "allow_incomplete": allow_incomplete,
            },
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
