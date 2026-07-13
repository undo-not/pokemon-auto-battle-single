"""Command-line entry points for fixture runs and seeded smoke batches."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .catalog import load_catalog, load_ruleset
from .engine import BattleEngine
from .fixtures import load_battle_fixture
from .core import ReplayRecord
from .runner import run_battle, run_random_batch, verify_replay


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="champions-sim")
    parser.add_argument("--catalog", default="data/fixtures/sim01_catalog.json")
    parser.add_argument("--ruleset", default="data/fixtures/sim01_ruleset.json")
    parser.add_argument("--battle", default="data/fixtures/sim01_battle.json")
    subparsers = parser.add_subparsers(dest="command", required=True)

    battle = subparsers.add_parser("battle", help="run one random-policy battle")
    battle.add_argument("--seed", type=int, default=20260713)
    battle.add_argument("--replay-out", type=Path)

    smoke = subparsers.add_parser("smoke", help="run a deterministic random batch")
    smoke.add_argument("--battles", type=int, default=100)
    smoke.add_argument("--seed-start", type=int, default=0)

    verify = subparsers.add_parser(
        "verify-replay", help="load and deterministically re-execute a replay"
    )
    verify.add_argument("--replay", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    catalog = load_catalog(args.catalog)
    ruleset = load_ruleset(args.ruleset)
    fixture = load_battle_fixture(args.battle, catalog=catalog, ruleset=ruleset)
    engine = BattleEngine(catalog, ruleset)

    if args.command == "battle":
        run = run_battle(engine, fixture.initial_state, seed=args.seed)
        if args.replay_out is not None:
            args.replay_out.parent.mkdir(parents=True, exist_ok=True)
            args.replay_out.write_text(run.replay.to_json() + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "battle_id": run.final_state.battle_id,
                    "winner": run.winner.value if run.winner else None,
                    "turn": run.final_state.turn,
                    "decision_windows": run.decision_windows,
                    "events": run.event_count,
                    "final_state_hash": run.replay.final_state_hash,
                    "replay_hash": run.replay.replay_hash,
                    "replay_schema_version": run.replay.schema_version,
                    "engine_semantics_version": run.replay.bundle.engine_semantics_version,
                    "provisional_decision_ids": run.replay.provisional_decision_ids,
                    "rng_cursor": run.engine_rng.cursor,
                    "catalog_hash": catalog.snapshot_hash,
                    "ruleset_hash": ruleset.snapshot_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "verify-replay":
        replay = ReplayRecord.from_json(args.replay.read_text(encoding="utf-8"))
        final_state = verify_replay(engine, replay)
        print(
            json.dumps(
                {
                    "ok": True,
                    "replay_id": replay.replay_id,
                    "replay_hash": replay.replay_hash,
                    "final_state_hash": replay.final_state_hash,
                    "winner": final_state.winner.value if final_state.winner else None,
                    "turn": final_state.turn,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    summary = run_random_batch(
        engine,
        fixture.initial_state,
        battles=args.battles,
        seed_start=args.seed_start,
    )
    print(
        json.dumps(
            {
                "battles": summary.battles,
                "p1_wins": summary.p1_wins,
                "p2_wins": summary.p2_wins,
                "draws": summary.draws,
                "decision_windows": summary.decision_windows,
                "events": summary.events,
                "unique_final_hashes": len(set(summary.final_hashes)),
                "catalog_hash": catalog.snapshot_hash,
                "ruleset_hash": ruleset.snapshot_hash,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0
