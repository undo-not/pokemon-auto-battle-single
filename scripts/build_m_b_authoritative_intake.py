"""Build the local-only SIM-02C-A authoritative evidence intake workbench."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim.authoritative.compiler import (  # noqa: E402
    AuthoritativeIntakeConfig,
    compile_authoritative_intake,
    load_source_acquisition_plan,
    load_source_policy_registry,
    write_authoritative_intake_documents,
)
from champions_sim.authoritative.models import (  # noqa: E402
    AuthoritativeIntakeError,
)


DEFAULT_PLAN = (
    ROOT / "data/manifests/sim02c-m-b-source-acquisition-plan-v2.json"
)
DEFAULT_POLICY = ROOT / "data/manifests/sim02c-source-policy-register-v1.json"
DEFAULT_SOURCE_LOCK = ROOT / "data/manifests/catalog-intake-m-b-source-lock.json"
DEFAULT_OUTPUT_ROOT = ROOT / "data/processed/sim02c/authoritative-intake"
EXPECTED_PLAN_HASH = "f4d0fbc5290ade0bec9079073082860f86f1fdb9805e3d6248f65cc4a15cd1f9"
EXPECTED_POLICY_HASH = "bbf3ee3afc70ed49ebeef7d196bf7324379341dd78e421da400512511dbd1277"
EXPECTED_SOURCE_LOCK_HASH = "68dc5041fa52c3ccc63f8b588cc8e52f8f6814d79203e64b0d8686b86675a8e8"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile local M-B source evidence into a deterministic, "
            "non-authorizing SIM-02C-A intake workbench"
        )
    )
    parser.add_argument(
        "--legacy-root",
        type=Path,
        required=True,
        help="Path to the local legacy champions repository",
    )
    parser.add_argument(
        "--plan",
        "--acquisition-plan",
        dest="plan",
        type=Path,
        default=DEFAULT_PLAN,
        help="Tracked source-acquisition plan",
    )
    parser.add_argument(
        "--policy",
        "--policy-registry",
        dest="policy",
        type=Path,
        default=DEFAULT_POLICY,
        help="Tracked source-policy register",
    )
    parser.add_argument(
        "--source-lock",
        type=Path,
        default=DEFAULT_SOURCE_LOCK,
        help="Tracked legacy source inventory lock",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Gitignored base directory under data/processed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile and validate without writing generated documents",
    )
    parser.add_argument(
        "--require-candidate",
        action="store_true",
        help="Return exit code 3 when the assessment is a reasoned NO-GO",
    )
    return parser


def _confined_output_root(path: Path) -> Path:
    output_root = path.expanduser().resolve()
    processed_root = (ROOT / "data/processed").resolve()
    try:
        relative = output_root.relative_to(processed_root)
    except ValueError as error:
        raise AuthoritativeIntakeError(
            "authoritative intake artifacts must remain under data/processed"
        ) from error
    if not relative.parts:
        raise AuthoritativeIntakeError(
            "authoritative intake output root must be below data/processed"
        )
    return output_root


def _candidate_ready(assessment: Mapping[str, Any]) -> bool:
    summary = assessment.get("summary")
    if isinstance(summary, Mapping):
        value = summary.get("candidate_for_production_promotion")
        if type(value) is bool:
            return value
    raise AuthoritativeIntakeError(
        "authoritative intake assessment does not declare "
        "candidate_for_production_promotion"
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output_root = _confined_output_root(args.output_root)

        # Surface contract errors at the CLI boundary.  Compilation revalidates
        # the same documents and binds their final self-hashes into its identity.
        plan = load_source_acquisition_plan(args.plan)
        policy = load_source_policy_registry(args.policy)
        if plan["plan_hash"] != EXPECTED_PLAN_HASH:
            raise AuthoritativeIntakeError(
                "this M-B command accepts only the reviewed acquisition-plan identity"
            )
        if policy["registry_hash"] != EXPECTED_POLICY_HASH:
            raise AuthoritativeIntakeError(
                "this M-B command accepts only the reviewed source-policy identity"
            )
        source_lock_hash = hashlib.sha256(args.source_lock.read_bytes()).hexdigest()
        if source_lock_hash != EXPECTED_SOURCE_LOCK_HASH:
            raise AuthoritativeIntakeError(
                "this M-B command accepts only the reviewed source-lock identity"
            )

        compilation = compile_authoritative_intake(
            AuthoritativeIntakeConfig(
                repository_root=ROOT,
                legacy_root=args.legacy_root,
                plan_path=args.plan,
                policy_registry_path=args.policy,
                source_lock_path=args.source_lock,
            )
        )
        if compilation.plan_hash != EXPECTED_PLAN_HASH:
            raise AuthoritativeIntakeError(
                "acquisition plan changed between M-B preflight and compilation"
            )
        if compilation.policy_registry_hash != EXPECTED_POLICY_HASH:
            raise AuthoritativeIntakeError(
                "source policy changed between M-B preflight and compilation"
            )
        if compilation.source_lock_hash != EXPECTED_SOURCE_LOCK_HASH:
            raise AuthoritativeIntakeError(
                "source lock changed between M-B preflight and compilation"
            )
        candidate_ready = _candidate_ready(compilation.assessment)
        destination = output_root / compilation.compilation_hash
        artifact_count = len(compilation.document_map) + 1
        if not args.dry_run:
            written_destination = write_authoritative_intake_documents(
                compilation,
                output_root,
            )
            if written_destination.resolve() != destination.resolve():
                raise AuthoritativeIntakeError(
                    "authoritative intake writer returned an unexpected destination"
                )

        compilation_summary = compilation.summary_data()
        summary = {
            "ok": True,
            "operational_success": True,
            "status": "CANDIDATE" if candidate_ready else "NO-GO",
            "candidate_ready": candidate_ready,
            "written": not args.dry_run,
            "output_directory": str(destination),
            "artifact_count": artifact_count,
            "written_file_count": 0 if args.dry_run else artifact_count,
            **compilation_summary,
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        if args.require_candidate and not candidate_ready:
            return 3
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "operational_success": False,
                    "error": str(error),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
