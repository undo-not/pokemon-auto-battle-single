"""Resolve a grounding plan and its external Replay-derived expectations."""

from __future__ import annotations

import argparse
import re
import sys
from contextlib import nullcontext
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.core import canonical_json  # noqa: E402
from champions_sim.grounding import (  # noqa: E402
    grounding_plan_seal_marker,
    load_grounding_lineage_receipt,
    load_grounding_plan,
    resolve_grounding_expectations,
    validate_grounding_plan_lineage,
)
from champions_sim.showdown import ShowdownClient  # noqa: E402


_REPLAY_ARGUMENT_RE = re.compile(r"^(?P<hash>[0-9a-f]{64})=(?P<path>.+)$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Re-execute external Replay expectations before sealing a plan"
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument(
        "--replay",
        action="append",
        default=[],
        metavar="SHA256=ABSOLUTE_PATH",
    )
    return parser


def _replay_paths(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        match = _REPLAY_ARGUMENT_RE.fullmatch(value)
        if match is None:
            raise ValueError("--replay must use SHA256=ABSOLUTE_PATH")
        replay_hash = match.group("hash")
        if replay_hash in result:
            raise ValueError(f"duplicate Replay mapping: {replay_hash}")
        result[replay_hash] = Path(match.group("path"))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = load_grounding_plan(args.plan)
        lineage = load_grounding_lineage_receipt(args.lineage)
        validate_grounding_plan_lineage(plan, lineage)
        replay_paths = _replay_paths(args.replay)
        client_context = ShowdownClient() if replay_paths else nullcontext(None)
        with client_context as client:
            expectations = resolve_grounding_expectations(
                plan,
                replay_paths,
                client=client,
            )
        resolved_sources = frozenset(
            evidence.replay_source_sha256
            for evidence in expectations.evidence
            if evidence.replay_source_sha256 is not None
        )
        if resolved_sources != frozenset(
            lineage.receipt.source_artifact_sha256
        ):
            raise ValueError(
                "lineage source artifacts do not match resolved Replay bytes"
            )
        print(
            canonical_json(
                {
                    "ok": True,
                    "plan_id": plan.plan.plan_id,
                    "plan_hash": plan.plan_hash,
                    "lineage_receipt_sha256": lineage.receipt_sha256,
                    "partition": plan.plan.partition.value,
                    "requirement_count": len(expectations.evidence),
                    "replay_hashes": sorted(expectations.replay_hashes),
                    "seal_marker": grounding_plan_seal_marker(plan),
                }
            )
        )
        return 0
    except (OSError, TypeError, ValueError, RuntimeError) as error:
        print(canonical_json({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
