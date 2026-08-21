"""Initialize one external capture-store identity before sealing a plan."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.core import canonical_json  # noqa: E402
from champions_sim.grounding import CaptureStore  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize an external physical capture store; performs no game access"
    )
    parser.add_argument("--store", type=Path)
    parser.add_argument("--store-id")
    parser.add_argument(
        "--partition",
        choices=("development", "holdout"),
        default="development",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        store = CaptureStore(
            args.store,
            store_id=args.store_id,
            partition=args.partition,
        )
        print(
            canonical_json(
                {
                    "ok": True,
                    "store_id": store.store_id,
                    "partition": store.partition,
                    "capture_store_identity_sha256": store.identity_hash,
                    "game_access_performed": False,
                }
            )
        )
        return 0
    except (OSError, TypeError, ValueError) as error:
        print(canonical_json({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
