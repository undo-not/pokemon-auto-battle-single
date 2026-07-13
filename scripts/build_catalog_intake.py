"""Build the local-only SIM-02 source-to-capability catalog intake bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.intake import (
    CatalogIntakeError,
    CatalogIntakePaths,
    build_catalog_intake,
    load_source_lock,
)


DEFAULT_OUTPUT = ROOT / "data/processed/sim02/catalog-intake-m-b.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic metadata-only catalog intake bundle from "
            "the official M-B target fixture and local legacy processed data"
        )
    )
    parser.add_argument(
        "--legacy-root",
        type=Path,
        required=True,
        help="Path to the legacy champions repository (never fetched over network)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output bundle path (default is Gitignored data/processed/sim02)",
    )
    parser.add_argument(
        "--target-pool",
        default="data/fixtures/regulations/m-b-eligible-pokemon.json",
        help="Repository-relative official target-pool fixture",
    )
    parser.add_argument(
        "--source-lock",
        type=Path,
        help="Optional prior source inventory lock; any hash/count drift is fatal",
    )
    parser.add_argument(
        "--without-usage-details",
        action="store_true",
        help="Skip optional usage-detail conflict diagnostics",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the report summary without writing the bundle",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        source_lock = load_source_lock(args.source_lock) if args.source_lock else None
        bundle = build_catalog_intake(
            repository_root=ROOT,
            legacy_root=args.legacy_root,
            paths=CatalogIntakePaths(target_pool=args.target_pool),
            include_usage_details=not args.without_usage_details,
            expected_inventory=source_lock,
        )
        output = args.output.resolve()
        if not args.dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_name(f".{output.name}.tmp")
            temporary.write_text(bundle.to_json() + "\n", encoding="utf-8", newline="\n")
            temporary.replace(output)
        summary = {
            "ok": True,
            "written": not args.dry_run,
            "output": str(output),
            "bundle_hash": bundle.bundle_hash,
            "target_member_count": bundle.target_member_count,
            "ready_for_capability_promotion": not bundle.blockers,
            "source_policy": {
                "license_status": "unverified",
                "access_scope": "local_only",
                "redistribution": "prohibited",
            },
            **dict(bundle.summary),
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except CatalogIntakeError as error:
        print(
            json.dumps(
                {"ok": False, "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
