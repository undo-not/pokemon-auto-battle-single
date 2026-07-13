"""Build a local SIM-02 regulation coverage/diff bundle without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from champions_sim import load_catalog, load_ruleset  # noqa: E402
from champions_sim.regulations import (  # noqa: E402
    RehearsalResources,
    build_coverage_gap_report,
    build_regulation_rehearsal_report,
    diff_regulation_bundles,
    load_regulation_bundle,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build deterministic SIM-02 regulation coverage and delta JSON"
    )
    parser.add_argument(
        "--before-regulation",
        type=Path,
        default=ROOT / "data/fixtures/regulations/m-b-current.json",
    )
    parser.add_argument("--rehearsal-report-out", type=Path)
    parser.add_argument(
        "--before-pool",
        type=Path,
        default=ROOT / "data/fixtures/regulations/m-b-eligible-pokemon.json",
    )
    parser.add_argument(
        "--after-regulation",
        type=Path,
        default=ROOT / "data/fixtures/regulations/m-c-synthetic-delta.json",
    )
    parser.add_argument(
        "--after-pool",
        type=Path,
        default=ROOT / "data/fixtures/regulations/m-c-eligible-pokemon-synthetic.json",
    )
    parser.add_argument(
        "--catalog", type=Path, default=ROOT / "data/fixtures/sim01_catalog.json"
    )
    parser.add_argument(
        "--ruleset", type=Path, default=ROOT / "data/fixtures/sim01_ruleset.json"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--rehearsal-input",
        type=Path,
        default=ROOT / "data/fixtures/regulations/synthetic-rehearsal-input.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    before = load_regulation_bundle(
        args.before_regulation,
        args.before_pool,
        manifest_dir=ROOT / "data/manifests",
        repository_root=ROOT,
    )
    after = load_regulation_bundle(
        args.after_regulation,
        args.after_pool,
        manifest_dir=ROOT / "data/manifests",
        repository_root=ROOT,
    )
    catalog = load_catalog(args.catalog)
    ruleset = load_ruleset(args.ruleset)
    before_coverage = build_coverage_gap_report(before, catalog, ruleset)
    after_coverage = build_coverage_gap_report(after, catalog, ruleset)
    diff = diff_regulation_bundles(before, after, before_coverage, after_coverage)
    rehearsal_raw = json.loads(args.rehearsal_input.read_text(encoding="utf-8"))
    try:
        rehearsal_logical_path = args.rehearsal_input.resolve().relative_to(ROOT).as_posix()
    except ValueError as error:
        raise ValueError("rehearsal input must be inside the repository") from error
    declared_after_artifacts = {
        path
        for manifest in after.manifests
        for path in manifest.declared_artifact_paths
    }
    if rehearsal_logical_path not in declared_after_artifacts:
        raise ValueError("rehearsal input is not declared by the after-bundle manifests")
    rehearsal_input_hash = hashlib.sha256(args.rehearsal_input.read_bytes()).hexdigest()
    expected_rehearsal_fields = {
        "schema_version",
        "report_id",
        "rehearsal_kind",
        "t0",
        "t_decision",
        "resources",
        "silent_fallback_count",
        "source_manifest_ids",
        "notes",
    }
    if not isinstance(rehearsal_raw, dict) or set(rehearsal_raw) != expected_rehearsal_fields:
        raise ValueError("rehearsal input has missing or extra fields")
    if rehearsal_raw["schema_version"] != "1.0.0":
        raise ValueError("unsupported rehearsal input schema_version")
    resource_raw = rehearsal_raw["resources"]
    expected_resource_fields = {
        "measurement_status",
        "compute_environment",
        "process_count",
        "max_parallel_workers",
        "network_fetch_count",
        "execution_minutes",
        "manual_work_minutes",
        "external_wait_minutes",
    }
    if not isinstance(resource_raw, dict) or set(resource_raw) != expected_resource_fields:
        raise ValueError("rehearsal resources have missing or extra fields")
    rehearsal = build_regulation_rehearsal_report(
        report_id=str(rehearsal_raw["report_id"]),
        rehearsal_kind=str(rehearsal_raw["rehearsal_kind"]),
        t0=str(rehearsal_raw["t0"]),
        t_decision=str(rehearsal_raw["t_decision"]),
        before_bundle=before,
        after_bundle=after,
        before_coverage=before_coverage,
        after_coverage=after_coverage,
        diff=diff,
        catalog=catalog,
        ruleset=ruleset,
        resources=RehearsalResources(**resource_raw),
        silent_fallback_count=int(rehearsal_raw["silent_fallback_count"]),
        rehearsal_input_hash=rehearsal_input_hash,
        report_source_manifest_ids=tuple(
            str(value) for value in rehearsal_raw["source_manifest_ids"]
        ),
        notes=tuple(str(value) for value in rehearsal_raw["notes"]),
    )
    payload = {
        "before_coverage": json.loads(before_coverage.to_json()),
        "after_coverage": json.loads(after_coverage.to_json()),
        "diff": json.loads(diff.to_json()),
        "rehearsal_report": json.loads(rehearsal.to_json()),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.rehearsal_report_out is not None:
        args.rehearsal_report_out.parent.mkdir(parents=True, exist_ok=True)
        args.rehearsal_report_out.write_text(rehearsal.to_json() + "\n", encoding="utf-8")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
