"""Print BlueStacks capture diagnostics/plan without invoking ADB or launching a GUI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.grounding import (  # noqa: E402
    AdbObservationCapture,
    ExternalCaptureUnavailable,
    discover_bluestacks,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only BlueStacks diagnostics; this command never invokes ADB"
    )
    parser.add_argument(
        "--plan",
        metavar="INSTANCE",
        help="show the exact allowlisted commands without running them",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    diagnostics = discover_bluestacks()
    result: dict[str, object] = {
        "ok": True,
        "adb_invoked": False,
        "diagnostics": diagnostics.to_dict(),
    }
    if args.plan:
        try:
            result["plan"] = AdbObservationCapture(diagnostics).plan(args.plan).to_dict()
        except ExternalCaptureUnavailable as error:
            result["ok"] = False
            result["error"] = str(error)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
