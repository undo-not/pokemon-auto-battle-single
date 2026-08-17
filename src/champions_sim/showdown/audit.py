"""Reproducible random-battle completion audit for the pinned Champions format."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping, Sequence

from champions_sim.core.canonical import canonical_hash, canonical_json

from .client import ShowdownClient
from .models import ShowdownReplay


AUDIT_SCHEMA_VERSION = "1.0.0"
AUDIT_ID = "champions-m-b-random-battle-completion-v1"
GENERATION_FORMAT_ID = "gen9championsrandombattle"
DEFAULT_AUDIT_SEED = "issue-2-m-b-random-10-v1"
DEFAULT_BATTLE_COUNT = 10
DEFAULT_MAX_DECISIONS = 2_000
_MAX_CANDIDATES = 512
_AUDIT_SCHEMA_SHA256 = "73f36c9dd33f9f3f9e904d28184c2cfd1322df10de338d8911c2de94cc3ab4c7"
_REPLAY_SCHEMA_SHA256 = "46c15087eed2652eeb076c694150e1e86a881f21b81216292c29569a6dbc9006"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SODIUM_SEED = re.compile(r"^sodium,[0-9a-f]{64}$")


class RandomBattleAuditError(RuntimeError):
    """Raised when any completion-audit invariant fails closed."""


def _digest(seed: str, domain: str, index: int) -> bytes:
    payload = (
        b"champions-random-battle-audit-v1\x00"
        + seed.encode("utf-8")
        + b"\x00"
        + domain.encode("ascii")
        + b"\x00"
        + index.to_bytes(8, "big")
    )
    return hashlib.sha256(payload).digest()


class _HashChoiceStream:
    def __init__(self, seed: str, domain: str) -> None:
        self._seed = seed
        self._domain = domain
        self._counter = 0

    def choose(self, values: Sequence[str]) -> str:
        if not values:
            raise RandomBattleAuditError("cannot choose from an empty legal-action list")
        if len(set(values)) != len(values):
            raise RandomBattleAuditError("legal-action list contains duplicate choices")
        size = len(values)
        ceiling = 1 << 256
        limit = ceiling - (ceiling % size)
        while True:
            candidate = int.from_bytes(
                _digest(self._seed, self._domain, self._counter), "big"
            )
            self._counter += 1
            if candidate < limit:
                return values[candidate % size]


def _generation_seed(audit_seed: str, index: int) -> tuple[int, int, int, int]:
    payload = _digest(audit_seed, "team-generation", index)
    return tuple(
        int.from_bytes(payload[offset : offset + 2], "big")
        for offset in range(0, 8, 2)
    )  # type: ignore[return-value]


def _battle_seed(audit_seed: str, index: int) -> str:
    return f"sodium,{_digest(audit_seed, 'battle', index).hex()}"


def _select_teams(
    client: ShowdownClient,
    *,
    audit_seed: str,
    count: int,
) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    required = count * 2
    selected: list[Mapping[str, Any]] = []
    identities: set[str] = set()
    rejected = 0
    candidate_count = 0
    while len(selected) < required and candidate_count < _MAX_CANDIDATES:
        batch_size = min(required - len(selected), _MAX_CANDIDATES - candidate_count)
        seeds = [
            _generation_seed(audit_seed, index)
            for index in range(candidate_count, candidate_count + batch_size)
        ]
        candidates = client.generate_random_team_candidates(
            generation_format_id=GENERATION_FORMAT_ID,
            target_format_id=client.default_format_id,
            seeds=seeds,
        )
        candidate_count += len(candidates)
        for candidate in candidates:
            if candidate["problems"]:
                rejected += 1
                continue
            team = candidate["team"]
            problems = client.validate_team(team)
            if problems:
                raise RandomBattleAuditError(
                    "generation and execution TeamValidator results disagree: "
                    + "; ".join(problems)
                )
            identity = canonical_hash(team)
            if identity in identities:
                rejected += 1
                continue
            identities.add(identity)
            selected.append(
                {
                    "generation_seed": candidate["generation_seed"],
                    "team_hash": identity,
                    "team": team,
                }
            )
    if len(selected) != required:
        raise RandomBattleAuditError(
            f"only {len(selected)} unique legal teams were generated; {required} required"
        )
    return selected, {
        "format_id": GENERATION_FORMAT_ID,
        "format_name": client.resolved.manifest.format_by_id(
            GENERATION_FORMAT_ID
        ).name,
        "mod": client.resolved.manifest.format_by_id(GENERATION_FORMAT_ID).mod,
        "candidate_count": candidate_count,
        "rejected_before_selection": rejected,
        "selected_team_count": len(selected),
    }


def _choice_kind(choice: str) -> str:
    for kind in ("team", "move", "switch"):
        if choice.startswith(f"{kind} "):
            return kind
    raise RandomBattleAuditError(f"unexpected singles legal action: {choice}")


def _run_battle(
    client: ShowdownClient,
    *,
    audit_seed: str,
    battle_index: int,
    p1: Mapping[str, Any],
    p2: Mapping[str, Any],
    max_decisions: int,
) -> Mapping[str, Any]:
    player_names = {
        "p1": f"Audit-{battle_index:02d}-P1",
        "p2": f"Audit-{battle_index:02d}-P2",
    }
    seed = _battle_seed(audit_seed, battle_index)
    choices = _HashChoiceStream(audit_seed, f"battle-choices-{battle_index}")
    decisions: list[dict[str, Any]] = []
    counts = {"team": 0, "move": 0, "switch": 0}
    sequences = {"p1": 0, "p2": 0}
    session = client.create_session(
        session_id=f"random-audit-{battle_index:02d}",
        seed=seed,
        p1_name=player_names["p1"],
        p1_team=p1["team"],
        p2_name=player_names["p2"],
        p2_team=p2["team"],
    )
    try:
        while True:
            acted = False
            for player in ("p1", "p2"):
                observation = session.observe(player, since=sequences[player])
                sequences[player] = observation.next_sequence
                if observation.ended:
                    replay = session.replay().to_dict()
                    reproduced = client.replay_input_log(replay).to_dict()
                    if reproduced != replay:
                        raise RandomBattleAuditError(
                            f"battle {battle_index} Replay did not reproduce"
                        )
                    replay_choices = replay["input_log"][3:]
                    if len(replay_choices) != len(decisions):
                        raise RandomBattleAuditError(
                            f"battle {battle_index} decision log does not match Replay"
                        )
                    player_decisions = {
                        player: [
                            item for item in decisions if item["player"] == player
                        ]
                        for player in ("p1", "p2")
                    }
                    positions = {"p1": 0, "p2": 0}
                    for replay_input in replay_choices:
                        player = replay_input[1:3]
                        kind = replay_input[4:].split(" ", 1)[0]
                        if (
                            player not in positions
                            or positions[player] >= len(player_decisions[player])
                        ):
                            raise RandomBattleAuditError(
                                f"battle {battle_index} decision players do not match Replay"
                            )
                        decision = player_decisions[player][positions[player]]
                        if (
                            kind != decision["kind"]
                            or replay_input != decision["replay_input"]
                        ):
                            raise RandomBattleAuditError(
                                f"battle {battle_index} decisions do not match Replay"
                            )
                        positions[player] += 1
                    if any(
                        positions[player] != len(player_decisions[player])
                        for player in positions
                    ):
                        raise RandomBattleAuditError(
                            f"battle {battle_index} decision order does not match Replay"
                        )
                    selections = {
                        side: [
                            item["choice"]
                            for item in decisions
                            if item["player"] == side and item["kind"] == "team"
                        ]
                        for side in ("p1", "p2")
                    }
                    if any(len(value) != 1 for value in selections.values()):
                        raise RandomBattleAuditError(
                            f"battle {battle_index} did not record one selection per player"
                        )
                    if replay["winner"] not in set(player_names.values()):
                        raise RandomBattleAuditError(
                            f"battle {battle_index} ended without a named winner"
                        )
                    return {
                        "battle_index": battle_index,
                        "battle_seed": seed,
                        "players": player_names,
                        "teams": {"p1": p1, "p2": p2},
                        "selections": {
                            side: value[0] for side, value in selections.items()
                        },
                        "decision_count": len(decisions),
                        "choice_counts": counts,
                        "decisions": decisions,
                        "winner": replay["winner"],
                        "turns": replay["turns"],
                        "score": replay["score"],
                        "replay_verification": {
                            "exact_match": True,
                            "decision_log_match": True,
                            "reexecuted_replay_hash": reproduced["replay_hash"],
                        },
                        "replay": replay,
                    }
                if observation.legal_actions:
                    if len(decisions) >= max_decisions:
                        raise RandomBattleAuditError(
                            f"battle {battle_index} exceeded {max_decisions} decisions"
                        )
                    choice = choices.choose(observation.legal_actions)
                    kind = _choice_kind(choice)
                    decisions.append(
                        {
                            "decision_index": len(decisions),
                            "player": player,
                            "revision": observation.revision,
                            "turn": observation.turn,
                            "kind": kind,
                            "choice": choice,
                            "legal_action_count": len(observation.legal_actions),
                            "legal_actions_hash": canonical_hash(
                                list(observation.legal_actions)
                            ),
                        }
                    )
                    counts[kind] += 1
                    _summary, replay_input = session.choose_with_replay_input(
                        player, choice
                    )
                    decisions[-1]["replay_input"] = replay_input
                    acted = True
            if not acted:
                raise RandomBattleAuditError(
                    f"battle {battle_index} stalled without a legal action"
                )
    finally:
        session.close()


def run_random_battle_audit(
    client: ShowdownClient,
    *,
    audit_seed: str = DEFAULT_AUDIT_SEED,
    battle_count: int = DEFAULT_BATTLE_COUNT,
    max_decisions: int = DEFAULT_MAX_DECISIONS,
) -> dict[str, Any]:
    if (
        not audit_seed
        or len(audit_seed) > 512
        or any(
            ord(character) < 0x20 or ord(character) == 0x7F
            for character in audit_seed
        )
    ):
        raise RandomBattleAuditError(
            "audit_seed must be a control-free string of 1 to 512 characters"
        )
    if battle_count != DEFAULT_BATTLE_COUNT:
        raise RandomBattleAuditError("the completion audit requires exactly 10 battles")
    if not 1 <= max_decisions <= 4_000:
        raise RandomBattleAuditError("max_decisions must be between 1 and 4000")
    expected = client.resolved.manifest.default_format
    generation = client.resolved.manifest.format_by_id(GENERATION_FORMAT_ID)
    if (
        client.default_format_id != "gen9championsbssregmb"
        or expected.purpose != "battle"
        or expected.regulation != "M-B"
        or expected.game_type != "singles"
        or expected.team_constraints.max_team_size != 6
        or expected.team_constraints.picked_team_size != 3
    ):
        raise RandomBattleAuditError("active format is not the bound M-B 6-pick-3 singles format")
    if (
        generation is None
        or generation.purpose != "team_generation"
        or generation.mod != expected.mod
        or generation.game_type != "singles"
    ):
        raise RandomBattleAuditError("random-team generation format is not exactly bound")

    teams, generator = _select_teams(
        client, audit_seed=audit_seed, count=battle_count
    )
    battles = [
        _run_battle(
            client,
            audit_seed=audit_seed,
            battle_index=index + 1,
            p1=teams[index * 2],
            p2=teams[index * 2 + 1],
            max_decisions=max_decisions,
        )
        for index in range(battle_count)
    ]
    totals = {
        "terminal_battles": len(battles),
        "replay_verified_battles": sum(
            int(item["replay_verification"]["exact_match"]) for item in battles
        ),
        "unique_teams": len(
            {
                item["teams"][side]["team_hash"]
                for item in battles
                for side in ("p1", "p2")
            }
        ),
        "decisions": sum(item["decision_count"] for item in battles),
        "team_choices": sum(item["choice_counts"]["team"] for item in battles),
        "move_choices": sum(item["choice_counts"]["move"] for item in battles),
        "switch_choices": sum(item["choice_counts"]["switch"] for item in battles),
    }
    if totals["terminal_battles"] != battle_count:
        raise RandomBattleAuditError("not every requested battle reached a terminal state")
    if totals["replay_verified_battles"] != battle_count:
        raise RandomBattleAuditError("not every terminal Replay was verified")
    if totals["unique_teams"] != battle_count * 2:
        raise RandomBattleAuditError("the audit did not use unique random teams")
    if totals["team_choices"] != battle_count * 2:
        raise RandomBattleAuditError("the audit did not make one selection per player")
    if totals["move_choices"] < 1 or totals["switch_choices"] < 1:
        raise RandomBattleAuditError("the audit did not exercise both move and switch choices")

    report: dict[str, Any] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_id": AUDIT_ID,
        "status": "passed",
        "audit_seed": audit_seed,
        "battle_count": battle_count,
        "max_decisions": max_decisions,
        "engine": client.engine_identity(),
        "format": {
            "id": expected.id,
            "name": expected.name,
            "mod": expected.mod,
            "regulation": expected.regulation,
            "game_type": expected.game_type,
            "registered_team_size": expected.team_constraints.max_team_size,
            "picked_team_size": expected.team_constraints.picked_team_size,
        },
        "team_generator": generator,
        "totals": totals,
        "battles": battles,
    }
    report["report_hash"] = canonical_hash(report)
    return report


def verify_repeated_random_battle_audit(
    client: ShowdownClient,
    *,
    audit_seed: str = DEFAULT_AUDIT_SEED,
    battle_count: int = DEFAULT_BATTLE_COUNT,
    max_decisions: int = DEFAULT_MAX_DECISIONS,
    repetitions: int = 2,
) -> dict[str, Any]:
    if not 2 <= repetitions <= 4:
        raise RandomBattleAuditError("repetitions must be between 2 and 4")
    reports = [
        run_random_battle_audit(
            client,
            audit_seed=audit_seed,
            battle_count=battle_count,
            max_decisions=max_decisions,
        )
    ]
    for _ in range(1, repetitions):
        with ShowdownClient(
            root=client.resolved.root,
            node_executable=client.resolved.node_executable,
            manifest_path=client.resolved.manifest.path,
        ) as isolated:
            reports.append(
                run_random_battle_audit(
                    isolated,
                    audit_seed=audit_seed,
                    battle_count=battle_count,
                    max_decisions=max_decisions,
                )
            )
    hashes = [report["report_hash"] for report in reports]
    if len(set(hashes)) != 1 or any(report != reports[0] for report in reports[1:]):
        raise RandomBattleAuditError("repeated audit runs produced different reports")
    result = dict(reports[0])
    report_hash = result.pop("report_hash")
    result["determinism"] = {
        "repetitions": repetitions,
        "process_isolated": True,
        "matching_report_hash": report_hash,
    }
    result["report_hash"] = canonical_hash(result)
    validate_random_battle_audit_document(result)
    return result


def validate_random_battle_audit_document(report: Mapping[str, Any]) -> None:
    schema_root = Path(__file__).resolve().parents[3] / "data" / "schemas"
    try:
        for filename, expected_hash in (
            ("random-battle-audit.schema.json", _AUDIT_SCHEMA_SHA256),
            ("showdown-replay.schema.json", _REPLAY_SCHEMA_SHA256),
        ):
            payload = (schema_root / filename).read_bytes().replace(b"\r\n", b"\n")
            if hashlib.sha256(payload).hexdigest() != expected_hash:
                raise RandomBattleAuditError(
                    f"tracked Schema identity mismatch: {filename}"
                )

        def fields(
            value: Any,
            required: set[str],
            label: str,
            optional: set[str] = frozenset(),
        ) -> Mapping[str, Any]:
            if not isinstance(value, dict):
                raise RandomBattleAuditError(f"{label} must be an object")
            actual = set(value)
            if not required <= actual or not actual <= required | optional:
                raise RandomBattleAuditError(f"{label} fields violate the contract")
            return value

        def integer(
            value: Any, label: str, minimum: int, maximum: int | None = None
        ) -> int:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < minimum
                or (maximum is not None and value > maximum)
            ):
                raise RandomBattleAuditError(f"{label} is outside its integer range")
            return value

        def text(value: Any, label: str, maximum: int = 512) -> str:
            if (
                not isinstance(value, str)
                or not value
                or len(value) > maximum
                or any(
                    ord(character) < 0x20 or ord(character) == 0x7F
                    for character in value
                )
            ):
                raise RandomBattleAuditError(
                    f"{label} must be a non-empty bounded control-free string"
                )
            return value

        def sha256(value: Any, label: str) -> str:
            value = text(value, label, 64)
            if _SHA256.fullmatch(value) is None:
                raise RandomBattleAuditError(f"{label} must be lowercase SHA-256")
            return value

        root = fields(
            report,
            {
                "schema_version",
                "audit_id",
                "status",
                "audit_seed",
                "battle_count",
                "max_decisions",
                "engine",
                "format",
                "team_generator",
                "totals",
                "battles",
                "determinism",
                "report_hash",
            },
            "audit report",
        )
        if (
            root["schema_version"] != AUDIT_SCHEMA_VERSION
            or root["audit_id"] != AUDIT_ID
            or root["status"] != "passed"
            or root["battle_count"] != DEFAULT_BATTLE_COUNT
        ):
            raise RandomBattleAuditError("audit report identity is invalid")
        audit_seed = text(root["audit_seed"], "audit_seed")
        max_decisions = integer(root["max_decisions"], "max_decisions", 1, 4_000)
        expected_format = {
            "id": "gen9championsbssregmb",
            "name": "[Gen 9 Champions] BSS Reg M-B",
            "mod": "champions",
            "regulation": "M-B",
            "game_type": "singles",
            "registered_team_size": 6,
            "picked_team_size": 3,
        }
        if root["format"] != expected_format:
            raise RandomBattleAuditError("audit battle format identity is invalid")

        generator = fields(
            root["team_generator"],
            {
                "format_id",
                "format_name",
                "mod",
                "candidate_count",
                "rejected_before_selection",
                "selected_team_count",
            },
            "team_generator",
        )
        if (
            generator["format_id"] != GENERATION_FORMAT_ID
            or generator["format_name"] != "[Gen 9 Champions] Random Battle"
            or generator["mod"] != "champions"
            or generator["selected_team_count"] != 20
        ):
            raise RandomBattleAuditError("team generator identity is invalid")
        candidate_count = integer(
            generator["candidate_count"], "candidate_count", 20, _MAX_CANDIDATES
        )
        rejected = integer(
            generator["rejected_before_selection"],
            "rejected_before_selection",
            0,
            _MAX_CANDIDATES - 20,
        )
        if candidate_count != 20 + rejected:
            raise RandomBattleAuditError("team generator counts are inconsistent")

        totals = fields(
            root["totals"],
            {
                "terminal_battles",
                "replay_verified_battles",
                "unique_teams",
                "decisions",
                "team_choices",
                "move_choices",
                "switch_choices",
            },
            "totals",
        )
        for field, expected in (
            ("terminal_battles", 10),
            ("replay_verified_battles", 10),
            ("unique_teams", 20),
            ("team_choices", 20),
        ):
            if totals[field] != expected or isinstance(totals[field], bool):
                raise RandomBattleAuditError(f"totals.{field} is invalid")
        integer(totals["decisions"], "totals.decisions", 20, 40_000)
        integer(totals["move_choices"], "totals.move_choices", 1)
        integer(totals["switch_choices"], "totals.switch_choices", 1)

        battles = root["battles"]
        if not isinstance(battles, list) or len(battles) != DEFAULT_BATTLE_COUNT:
            raise RandomBattleAuditError("battles must contain exactly ten entries")
        all_team_hashes: list[str] = []
        selected_generation_seeds: list[list[int]] = []
        aggregate = {"decisions": 0, "team": 0, "move": 0, "switch": 0}
        top_engine = root["engine"]

        allowed_set_fields = {
            "species",
            "item",
            "ability",
            "moves",
            "nature",
            "gender",
            "evs",
            "ivs",
            "level",
            "shiny",
            "happiness",
            "pokeball",
            "hpType",
            "dynamaxLevel",
            "gigantamax",
            "teraType",
        }
        required_set_fields = {"species", "ability", "moves", "nature", "level"}

        def validate_team_set(value: Any, label: str) -> None:
            item = fields(
                value,
                required_set_fields,
                label,
                allowed_set_fields - required_set_fields,
            )
            for field in ("species", "ability", "nature"):
                text(item[field], f"{label}.{field}", 128)
            for field in ("item", "pokeball", "hpType", "teraType"):
                if field in item:
                    text(item[field], f"{label}.{field}", 128)
            moves = item["moves"]
            if not isinstance(moves, list) or not 1 <= len(moves) <= 4:
                raise RandomBattleAuditError(f"{label}.moves is invalid")
            for index, move in enumerate(moves):
                text(move, f"{label}.moves[{index}]", 128)
            if "gender" in item and item["gender"] not in {"M", "F", "N"}:
                raise RandomBattleAuditError(f"{label}.gender is invalid")
            for field, maximum in (("evs", 65_535), ("ivs", 31)):
                if field not in item:
                    continue
                stats = fields(
                    item[field],
                    set(),
                    f"{label}.{field}",
                    {"hp", "atk", "def", "spa", "spd", "spe"},
                )
                for stat, amount in stats.items():
                    integer(amount, f"{label}.{field}.{stat}", 0, maximum)
            integer(item["level"], f"{label}.level", 1, 9_999)
            for field, minimum, maximum in (
                ("happiness", 0, 255),
                ("dynamaxLevel", 0, 10),
            ):
                if field in item:
                    integer(item[field], f"{label}.{field}", minimum, maximum)
            for field in ("shiny", "gigantamax"):
                if field in item and not isinstance(item[field], bool):
                    raise RandomBattleAuditError(f"{label}.{field} must be boolean")

        for battle_offset, raw_battle in enumerate(battles):
            battle_index = battle_offset + 1
            battle = fields(
                raw_battle,
                {
                    "battle_index",
                    "battle_seed",
                    "players",
                    "teams",
                    "selections",
                    "decision_count",
                    "choice_counts",
                    "decisions",
                    "winner",
                    "turns",
                    "score",
                    "replay_verification",
                    "replay",
                },
                f"battles[{battle_offset}]",
            )
            if battle["battle_index"] != battle_index or isinstance(
                battle["battle_index"], bool
            ):
                raise RandomBattleAuditError("battle indices are not canonical")
            battle_seed = text(
                battle["battle_seed"], f"battles[{battle_offset}].battle_seed", 71
            )
            if (
                _SODIUM_SEED.fullmatch(battle_seed) is None
                or battle_seed != _battle_seed(audit_seed, battle_index)
            ):
                raise RandomBattleAuditError("battle seed lineage is invalid")
            players = fields(
                battle["players"], {"p1", "p2"}, f"battles[{battle_offset}].players"
            )
            expected_players = {
                "p1": f"Audit-{battle_index:02d}-P1",
                "p2": f"Audit-{battle_index:02d}-P2",
            }
            if players != expected_players:
                raise RandomBattleAuditError("audit player identity is invalid")
            teams = fields(
                battle["teams"], {"p1", "p2"}, f"battles[{battle_offset}].teams"
            )
            for player in ("p1", "p2"):
                team_identity = fields(
                    teams[player],
                    {"generation_seed", "team_hash", "team"},
                    f"battles[{battle_offset}].teams.{player}",
                )
                generation_seed = team_identity["generation_seed"]
                if (
                    not isinstance(generation_seed, list)
                    or len(generation_seed) != 4
                ):
                    raise RandomBattleAuditError("generation seed is invalid")
                for part in generation_seed:
                    integer(part, "generation seed part", 0, 65_535)
                selected_generation_seeds.append(generation_seed)
                team = team_identity["team"]
                if not isinstance(team, list) or len(team) != 6:
                    raise RandomBattleAuditError("registered team must contain six sets")
                for set_index, pokemon_set in enumerate(team):
                    validate_team_set(
                        pokemon_set,
                        f"battles[{battle_offset}].teams.{player}.team[{set_index}]",
                    )
                team_hash = sha256(team_identity["team_hash"], "team_hash")
                if team_hash != canonical_hash(team):
                    raise RandomBattleAuditError("team hash does not match team bytes")
                all_team_hashes.append(team_hash)

            selections = fields(
                battle["selections"],
                {"p1", "p2"},
                f"battles[{battle_offset}].selections",
            )
            for player in ("p1", "p2"):
                selection = text(selections[player], "team selection", 8)
                if re.fullmatch(r"team [1-6]{3}", selection) is None or len(
                    set(selection[-3:])
                ) != 3:
                    raise RandomBattleAuditError("team selection is invalid")

            decision_count = integer(
                battle["decision_count"], "decision_count", 2, max_decisions
            )
            decisions = battle["decisions"]
            if not isinstance(decisions, list) or len(decisions) != decision_count:
                raise RandomBattleAuditError("decision count is inconsistent")
            choice_counts = fields(
                battle["choice_counts"],
                {"team", "move", "switch"},
                f"battles[{battle_offset}].choice_counts",
            )
            if choice_counts["team"] != 2 or isinstance(choice_counts["team"], bool):
                raise RandomBattleAuditError("each battle must have two team choices")
            for kind in ("move", "switch"):
                integer(choice_counts[kind], f"choice_counts.{kind}", 0)
            if sum(choice_counts.values()) != decision_count:
                raise RandomBattleAuditError("choice counts are inconsistent")

            for decision_index, raw_decision in enumerate(decisions):
                decision = fields(
                    raw_decision,
                    {
                        "decision_index",
                        "player",
                        "revision",
                        "turn",
                        "kind",
                        "choice",
                        "replay_input",
                        "legal_action_count",
                        "legal_actions_hash",
                    },
                    f"decision[{decision_index}]",
                )
                if decision["decision_index"] != decision_index or isinstance(
                    decision["decision_index"], bool
                ):
                    raise RandomBattleAuditError("decision indices are not canonical")
                if decision["player"] not in {"p1", "p2"}:
                    raise RandomBattleAuditError("decision player is invalid")
                integer(decision["revision"], "decision.revision", 0)
                integer(decision["turn"], "decision.turn", 0)
                kind = decision["kind"]
                if kind not in {"team", "move", "switch"}:
                    raise RandomBattleAuditError("decision kind is invalid")
                choice = text(decision["choice"], "decision.choice", 256)
                replay_input = text(
                    decision["replay_input"], "decision.replay_input", 1024 * 1024
                )
                if not choice.startswith(f"{kind} ") or not replay_input.startswith(
                    f">{decision['player']} {kind} "
                ):
                    raise RandomBattleAuditError("decision choice encoding is invalid")
                integer(
                    decision["legal_action_count"],
                    "decision.legal_action_count",
                    1,
                    4_096,
                )
                sha256(decision["legal_actions_hash"], "legal_actions_hash")

            for player in ("p1", "p2"):
                team_choices = [
                    item["choice"]
                    for item in decisions
                    if item["player"] == player and item["kind"] == "team"
                ]
                if team_choices != [selections[player]]:
                    raise RandomBattleAuditError("recorded selection is inconsistent")

            replay = ShowdownReplay.from_document(battle["replay"]).to_dict()
            if (
                replay["engine"] != top_engine
                or replay["format_id"] != expected_format["id"]
                or replay["seed"] != battle_seed
                or replay["ended"] is not True
                or replay["winner"] != battle["winner"]
                or replay["turns"] != battle["turns"]
                or replay["score"] != battle["score"]
                or battle["winner"] not in players.values()
            ):
                raise RandomBattleAuditError("battle summary does not match Replay")
            replay_choices = replay["input_log"][3:]
            if len(replay_choices) != decision_count:
                raise RandomBattleAuditError("Replay decision count is inconsistent")
            for player in ("p1", "p2"):
                if [
                    line for line in replay_choices if line.startswith(f">{player} ")
                ] != [
                    item["replay_input"]
                    for item in decisions
                    if item["player"] == player
                ]:
                    raise RandomBattleAuditError("Replay decision lineage is invalid")

            verification = fields(
                battle["replay_verification"],
                {"exact_match", "decision_log_match", "reexecuted_replay_hash"},
                "replay_verification",
            )
            if (
                verification["exact_match"] is not True
                or verification["decision_log_match"] is not True
                or verification["reexecuted_replay_hash"] != replay["replay_hash"]
            ):
                raise RandomBattleAuditError("Replay verification claim is invalid")
            integer(battle["turns"], "battle.turns", 0)
            aggregate["decisions"] += decision_count
            for kind in ("team", "move", "switch"):
                aggregate[kind] += choice_counts[kind]

        if len(set(all_team_hashes)) != 20:
            raise RandomBattleAuditError("team identities are not unique")
        expected_generation_seeds = [
            list(_generation_seed(audit_seed, index))
            for index in range(candidate_count)
        ]
        positions = iter(expected_generation_seeds)
        for selected_seed in selected_generation_seeds:
            if not any(candidate == selected_seed for candidate in positions):
                raise RandomBattleAuditError("team generation seed lineage is invalid")
        if (
            totals["decisions"] != aggregate["decisions"]
            or totals["team_choices"] != aggregate["team"]
            or totals["move_choices"] != aggregate["move"]
            or totals["switch_choices"] != aggregate["switch"]
        ):
            raise RandomBattleAuditError("audit totals do not match battles")

        determinism = fields(
            root["determinism"],
            {"repetitions", "process_isolated", "matching_report_hash"},
            "determinism",
        )
        repetitions = integer(
            determinism["repetitions"], "determinism.repetitions", 2, 4
        )
        if repetitions < 2 or determinism["process_isolated"] is not True:
            raise RandomBattleAuditError("determinism evidence is invalid")
        matching_hash = sha256(
            determinism["matching_report_hash"], "matching_report_hash"
        )
        base_report = dict(root)
        base_report.pop("report_hash")
        base_report.pop("determinism")
        if matching_hash != canonical_hash(base_report):
            raise RandomBattleAuditError("matching report hash is invalid")
        claimed_hash = sha256(root["report_hash"], "report_hash")
        final_report = dict(root)
        final_report.pop("report_hash")
        if claimed_hash != canonical_hash(final_report):
            raise RandomBattleAuditError("audit report self-hash is invalid")
    except RandomBattleAuditError:
        raise
    except (KeyError, OSError, TypeError, ValueError) as error:
        raise RandomBattleAuditError(
            f"audit report does not match the tracked Schema: {error}"
        ) from error


def validate_random_battle_audit_output(path: Path) -> Path:
    root = Path(__file__).resolve().parents[3]
    expanded = path.expanduser()
    absolute = expanded if expanded.is_absolute() else Path.cwd() / expanded
    target = absolute.parent.resolve() / absolute.name
    if target == root or root in target.parents:
        raise RandomBattleAuditError("audit output must be outside the repository workspace")
    if os.path.lexists(target):
        raise RandomBattleAuditError(f"audit output already exists: {target}")
    return target


def write_random_battle_audit(path: Path, report: Mapping[str, Any]) -> None:
    validate_random_battle_audit_document(report)
    document = dict(report)
    claimed_hash = document.pop("report_hash", None)
    determinism = report.get("determinism")
    repetitions = (
        determinism.get("repetitions") if isinstance(determinism, dict) else None
    )
    if (
        report.get("schema_version") != AUDIT_SCHEMA_VERSION
        or report.get("audit_id") != AUDIT_ID
        or report.get("status") != "passed"
        or report.get("battle_count") != DEFAULT_BATTLE_COUNT
        or not isinstance(determinism, dict)
        or determinism.get("process_isolated") is not True
        or not isinstance(repetitions, int)
        or isinstance(repetitions, bool)
        or not 2 <= repetitions <= 4
        or not isinstance(claimed_hash, str)
        or claimed_hash != canonical_hash(document)
    ):
        raise RandomBattleAuditError("audit report identity or self-hash is invalid")
    target = validate_random_battle_audit_output(path)
    temporary: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(canonical_json(report))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError as error:
            raise RandomBattleAuditError(
                f"audit output already exists: {target}"
            ) from error
    except RandomBattleAuditError:
        raise
    except OSError as error:
        raise RandomBattleAuditError(f"cannot write audit output: {error}") from error
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
