"""Command-line entry points for the pinned Showdown integration."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from champions_sim.core.canonical import canonical_json
from champions_sim.showdown import ShowdownClient


class CliInputError(ValueError):
    pass


_SODIUM_SEED = re.compile(r"^sodium,[0-9a-f]{64}$")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CliInputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise CliInputError(f"floating-point or non-finite value is not allowed: {value}")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CliInputError(f"cannot read {path}: {error}") from error


def _exact(
    value: Any,
    label: str,
    required: set[str],
    optional: set[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise CliInputError(f"{label} must be an object")
    actual = set(value)
    missing = required - actual
    unknown = actual - required - optional
    if missing or unknown:
        raise CliInputError(
            f"{label} fields differ: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )
    return value


def _team(value: Any, label: str) -> list[Mapping[str, object]]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, dict) for item in value)
    ):
        raise CliInputError(f"{label} must be a non-empty array of objects")
    return value


def _string(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
    ):
        raise CliInputError(f"{label} must be a non-empty control-free string")
    return value


def _client_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--showdown-root", type=Path)
    parser.add_argument("--node", type=Path)


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="champions-sim")
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser(
        "verify-showdown", help="verify the external pinned engine"
    )
    _client_arguments(verify)

    team = subparsers.add_parser(
        "validate-team", help="validate a structured Showdown team JSON"
    )
    _client_arguments(team)
    team.add_argument("--team", type=Path, required=True)
    team.add_argument("--format-id")

    battle = subparsers.add_parser(
        "battle", help="execute a deterministic choice script"
    )
    _client_arguments(battle)
    battle.add_argument("--input", type=Path, required=True)

    replay = subparsers.add_parser(
        "replay", help="re-execute and verify a canonical Showdown Replay"
    )
    _client_arguments(replay)
    replay.add_argument("--input", type=Path, required=True)

    damage = subparsers.add_parser(
        "damage", help="sample damage from a scripted battle state"
    )
    _client_arguments(damage)
    damage.add_argument("--input", type=Path, required=True)
    damage.add_argument("--attacker", choices=("p1", "p2"), required=True)
    damage.add_argument("--move", required=True)
    return parser


def _create_scripted_session(client: ShowdownClient, path: Path):
    document = _exact(
        _load_json(path),
        "battle script",
        {"schema_version", "session_id", "seed", "players", "choices"},
        {"format_id"},
    )
    if document["schema_version"] != "1.0.0":
        raise CliInputError("battle script schema_version must be 1.0.0")
    players = _exact(document["players"], "players", {"p1", "p2"})
    player_data: dict[str, Mapping[str, Any]] = {}
    for player in ("p1", "p2"):
        player_data[player] = _exact(
            players[player], f"players.{player}", {"name", "team"}
        )
    seed = _string(document["seed"], "seed")
    if _SODIUM_SEED.fullmatch(seed) is None:
        raise CliInputError("seed must be a 32-byte Showdown sodium seed")
    choices = document["choices"]
    if not isinstance(choices, list):
        raise CliInputError("choices must be an array")
    parsed_choices: list[tuple[str, str]] = []
    for index, raw_choice in enumerate(choices):
        choice = _exact(raw_choice, f"choices[{index}]", {"player", "choice"})
        player = _string(choice["player"], f"choices[{index}].player")
        if player not in {"p1", "p2"}:
            raise CliInputError(f"choices[{index}].player must be p1 or p2")
        parsed_choices.append(
            (player, _string(choice["choice"], f"choices[{index}].choice"))
        )
    session = client.create_session(
        session_id=_string(document["session_id"], "session_id"),
        seed=seed,
        p1_name=_string(player_data["p1"]["name"], "players.p1.name"),
        p1_team=_team(player_data["p1"]["team"], "players.p1.team"),
        p2_name=_string(player_data["p2"]["name"], "players.p2.name"),
        p2_team=_team(player_data["p2"]["team"], "players.p2.team"),
        format_id=(
            _string(document["format_id"], "format_id")
            if "format_id" in document
            else None
        ),
    )
    try:
        for player, choice in parsed_choices:
            session.choose(player, choice)
    except BaseException:
        session.close()
        raise
    return session


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdio()
    args = _parser().parse_args(argv)
    try:
        with ShowdownClient(
            root=args.showdown_root, node_executable=args.node
        ) as client:
            if args.command == "verify-showdown":
                print(
                    canonical_json(
                        {
                            "ok": True,
                            "identity": client.engine_identity(),
                            "formats": [
                                item.id for item in client.resolved.manifest.formats
                            ],
                        }
                    )
                )
                return 0
            if args.command == "validate-team":
                team = _team(_load_json(args.team), "team")
                problems = client.validate_team(team, format_id=args.format_id)
                print(canonical_json({"ok": not problems, "problems": problems}))
                return 0 if not problems else 2
            if args.command == "replay":
                document = _load_json(args.input)
                if not isinstance(document, dict):
                    raise CliInputError("Replay must be an object")
                print(canonical_json(client.replay_input_log(document).to_dict()))
                return 0
            with _create_scripted_session(client, args.input) as session:
                if args.command == "battle":
                    print(
                        canonical_json(
                            session.replay(allow_incomplete=True).to_dict()
                        )
                    )
                    return 0
                sample = session.damage_sample(args.attacker, args.move)
                print(canonical_json(sample))
                return 0
    except (CliInputError, RuntimeError, ValueError) as error:
        print(canonical_json({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2
    raise AssertionError("unreachable")
