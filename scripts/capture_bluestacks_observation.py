"""Capture one authorized screenshot/UI-hierarchy pair without executing ADB."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.core import canonical_json  # noqa: E402
from champions_sim.grounding import (  # noqa: E402
    AdbObservationCapture,
    CaptureStore,
    ExternalCaptureUnavailable,
    ObservationAuthorizationError,
    discover_bluestacks,
    load_grounding_plan,
    load_grounding_lineage_receipt,
    load_observation_authorization,
    validate_grounding_plan_lineage,
    verify_grounding_plan_seal,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Capture through an already-running owned ADB server; never starts ADB or input"
        )
    )
    parser.add_argument("--instance", required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--lineage", type=Path, required=True)
    parser.add_argument("--plan-seal-comment", required=True)
    parser.add_argument("--store", type=Path)
    parser.add_argument("--store-id")
    parser.add_argument(
        "--partition",
        choices=("development", "holdout"),
        default="development",
    )
    parser.add_argument("--format", default="gen9championsbssregmb")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = load_grounding_plan(args.plan)
        lineage = load_grounding_lineage_receipt(args.lineage)
        validate_grounding_plan_lineage(plan, lineage)
        store = CaptureStore(
            args.store,
            store_id=args.store_id,
            partition=args.partition,
            initialize=False,
        )
        if (
            plan.plan.format_id != args.format
            or plan.plan.capture_store_id != store.store_id
            or plan.plan.partition.value != args.partition
            or plan.plan.capture_store_identity_sha256 != store.identity_hash
        ):
            raise ValueError("grounding plan does not match format or capture store")
        plan_seal = verify_grounding_plan_seal(
            plan,
            issue_url=plan.plan.issue_url,
            comment_url=args.plan_seal_comment,
            authorized_actor=plan.plan.seal_actor,
        )
        authorization = load_observation_authorization(
            args.authorization,
            now=datetime.now(timezone.utc),
            issue_url=plan.plan.issue_url,
            format_id=args.format,
            plan_id=plan.plan.plan_id,
            plan_hash=plan.plan_hash,
            lineage_receipt_sha256=lineage.receipt_sha256,
            plan_seal_comment_url=plan_seal.comment_url,
            plan_seal_receipt_sha256=plan_seal.receipt_sha256,
            partition=plan.plan.partition.value,
            instance_name=args.instance,
            target_package=plan.plan.target_package,
            client_build=plan.plan.client_build,
            capture_store_id=store.store_id,
            capture_store_identity_sha256=store.identity_hash,
        )
        diagnostics = discover_bluestacks()
        payload = AdbObservationCapture(
            diagnostics,
            authorization=authorization,
            plan_seal=plan_seal,
            capture_store_id=store.store_id,
            capture_store_identity_sha256=store.identity_hash,
            format_id=args.format,
            issue_url=plan.plan.issue_url,
        ).capture(args.instance)
        manifest = store.save(payload)
        result = {
            "ok": True,
            "adb_client_process_invoked": False,
            "game_input_performed": False,
            "capture_id": manifest.capture_id,
            "manifest_hash": store.manifest_hash(manifest.capture_id),
            "format_id": manifest.format_id,
            "capture_store_id": manifest.capture_store_id,
            "authorization_sha256": manifest.authorization_sha256,
        }
        print(canonical_json(result))
        return 0
    except (
        OSError,
        TypeError,
        ValueError,
        ExternalCaptureUnavailable,
        ObservationAuthorizationError,
    ) as error:
        print(canonical_json({"ok": False, "error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
