"""Explicitly inspect installed Champions build identity without ADB client/input."""

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
from champions_sim.grounding import (  # noqa: E402
    AdbObservationCapture,
    ExternalCaptureUnavailable,
    discover_bluestacks,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect version and installed APK-set identity through an existing "
            "owned BlueStacks ADB server; never starts ADB, captures UI, or performs input"
        )
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--target-package", required=True)
    parser.add_argument(
        "--confirm-read-only-inspection",
        action="store_true",
        help="Confirm this explicit package-metadata inspection",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.confirm_read_only_inspection:
        print(
            canonical_json(
                {
                    "ok": False,
                    "error": "--confirm-read-only-inspection is required",
                }
            ),
            file=sys.stderr,
        )
        return 2
    try:
        build = AdbObservationCapture(
            discover_bluestacks()
        ).inspect_client_build(args.instance, args.target_package)
        print(
            canonical_json(
                {
                    "ok": True,
                    "adb_client_process_invoked": False,
                    "game_input_performed": False,
                    "target_package": args.target_package,
                    "client_build": build,
                }
            )
        )
        return 0
    except (OSError, TypeError, ValueError, ExternalCaptureUnavailable) as error:
        print(canonical_json({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
