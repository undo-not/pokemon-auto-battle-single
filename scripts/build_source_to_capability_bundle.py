"""Build the local-only SIM-02 capability bundle or a reasoned NO-GO."""

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

from champions_sim.compiler.bridge import CatalogBridgeProfile
from champions_sim.compiler.bridge_models import CatalogCompilerError
from champions_sim.compiler.bundle import (
    SourceToCapabilityConfig,
    compile_source_to_capability_bundle,
    write_compilation_documents,
)
from champions_sim.intake import CatalogIntakeProfile


DEFAULT_OUTPUT_ROOT = ROOT / "data/processed/sim02/source-to-capability"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compile the sealed M-B sources into a capability candidate or a "
            "deterministic reasoned NO-GO bundle"
        )
    )
    parser.add_argument(
        "--legacy-root",
        type=Path,
        required=True,
        help="Path to the local legacy champions repository",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Gitignored base directory for content-addressed output",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compile and validate without writing generated documents",
    )
    parser.add_argument(
        "--require-candidate",
        action="store_true",
        help="Return exit code 3 when the correct result is NO-GO",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output_root = args.output_root.resolve()
        processed_root = (ROOT / "data/processed").resolve()
        try:
            output_root.relative_to(processed_root)
        except ValueError as error:
            raise CatalogCompilerError(
                "full compiler artifacts must remain under Gitignored data/processed"
            ) from error

        intake_profile = CatalogIntakeProfile(
            profile_id="official_m_b_local_v1",
            regulation_id="M-B",
            regulation_revision="official-2026-06-17",
            expected_target_count=235,
            expected_usage_count=213,
        )
        bridge_profile = CatalogBridgeProfile(
            profile_id="official_m_b_source_bound_v1",
            regulation_id="M-B",
            regulation_revision="official-2026-06-17",
            expected_target_count=235,
            source_manifest_id="catalog-intake-m-b-source-lock-legacy-59bf57c",
            engine_semantics_version="sim-core-0.1",
        )
        compilation = compile_source_to_capability_bundle(
            SourceToCapabilityConfig(
                repository_root=ROOT,
                legacy_root=args.legacy_root,
                regulation_path=ROOT / "data/fixtures/regulations/m-b-current.json",
                target_pool_path=(
                    ROOT / "data/fixtures/regulations/m-b-eligible-pokemon.json"
                ),
                ruleset_path=ROOT / "data/fixtures/sim01_ruleset.json",
                manifest_dir=ROOT / "data/manifests",
                source_lock_path=(
                    ROOT / "data/manifests/catalog-intake-m-b-source-lock.json"
                ),
                intake_profile=intake_profile,
                bridge_profile=bridge_profile,
            )
        )
        destination = output_root / compilation.report_hash
        written = ()
        if not args.dry_run:
            written = write_compilation_documents(compilation, destination)
        counts = compilation.report["counts"]
        summary = {
            "ok": True,
            "operational_success": True,
            "status": compilation.report["status"],
            "candidate_ready": compilation.candidate_ready,
            "report_hash": compilation.report_hash,
            "written": not args.dry_run,
            "output_directory": str(destination),
            "artifact_count": len(compilation.documents),
            "written_file_count": len(written),
            "target_members": counts["target_members"],
            "mapping_unresolved": counts["mapping_unresolved"],
            "mapping_conflict": counts["mapping_conflict"],
            "semantic_selectors": counts["semantic_selectors"],
            "target_capability_rows": counts["target_capability_rows"],
            "execution_gaps": counts["execution_gaps"],
            "probe_unexpected_errors": counts["probe_unexpected_errors"],
            "silent_fallbacks": counts["silent_fallbacks"],
            "blocking_reason_count": counts["blocking_reasons"],
        }
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        if args.require_candidate and not compilation.candidate_ready:
            return 3
        return 0
    except (KeyError, TypeError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"sealed source structure is invalid: {error}",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    except (CatalogCompilerError, OSError, ValueError) as error:
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
