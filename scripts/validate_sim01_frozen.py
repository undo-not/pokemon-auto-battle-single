"""Re-execute the frozen SIM-01 representative battle and reject drift."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim import (  # noqa: E402
    BattleEngine,
    load_battle_fixture,
    load_catalog,
    load_ruleset,
    run_battle,
    verify_replay,
)
from scripts.validate_sim01_bundle import validate_document_contract  # noqa: E402


class FrozenBaselineError(RuntimeError):
    """Raised when the current implementation drifts from a frozen baseline."""


def validate_frozen_baseline(path: Path) -> dict[str, Any]:
    baseline = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(baseline, dict):
        raise FrozenBaselineError("baseline root must be an object")
    schema = json.loads(
        (ROOT / "data/schemas/frozen-baseline.schema.json").read_text(encoding="utf-8")
    )
    validate_document_contract(baseline, schema, "frozen baseline")

    catalog = load_catalog(ROOT / str(baseline["catalog_path"]))
    ruleset = load_ruleset(ROOT / str(baseline["ruleset_path"]))
    fixture = load_battle_fixture(
        ROOT / str(baseline["battle_path"]),
        catalog=catalog,
        ruleset=ruleset,
    )
    engine = BattleEngine(catalog, ruleset)
    run = run_battle(
        engine,
        fixture.initial_state,
        seed=int(baseline["representative_seed"]),
    )
    verify_replay(engine, run.replay)

    checks = {
        "catalog_sha256": catalog.snapshot_hash,
        "ruleset_sha256": ruleset.snapshot_hash,
        "replay_schema_version": run.replay.schema_version,
        "replay_sha256": run.replay.replay_hash,
        "final_state_sha256": run.replay.final_state_hash,
        "winner": run.winner.value if run.winner else None,
        "turn": run.final_state.turn,
        "decision_windows": run.decision_windows,
        "provisional_decision_ids": list(run.replay.provisional_decision_ids),
        "source_manifest_ids": list(run.replay.source_manifest_ids),
    }
    mismatches = {
        key: {"expected": baseline.get(key), "actual": actual}
        for key, actual in checks.items()
        if baseline.get(key) != actual
    }
    if mismatches:
        raise FrozenBaselineError(
            "SIM-01 frozen baseline drift: "
            + json.dumps(mismatches, ensure_ascii=False, sort_keys=True)
        )
    return {
        "ok": True,
        "baseline_id": baseline["baseline_id"],
        **checks,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate frozen SIM-01 regression")
    parser.add_argument(
        "--baseline",
        type=Path,
        default=ROOT / "data/baselines/sim01-frozen-v1.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_frozen_baseline(args.baseline)
    except (OSError, KeyError, TypeError, ValueError, FrozenBaselineError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, sort_keys=True))
        return 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
