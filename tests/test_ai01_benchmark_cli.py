from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest

from champions_sim import BattleEngine, load_catalog, load_ruleset
from champions_sim.core import ReplayRecord, canonical_hash
from champions_sim.runner import verify_replay
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]


def _run_benchmark(*arguments: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_ai01_benchmark.py",
            "--pairs",
            "1",
            *arguments,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


@pytest.mark.parametrize("legacy_write_flag", [False, True])
def test_ai01_cli_persists_battle_replay_evidence_by_default(
    legacy_write_flag: bool,
) -> None:
    output_root = ROOT / "runs" / f"pytest-ai01-evidence-{uuid4().hex}"
    arguments = ["--output-root", str(output_root)]
    if legacy_write_flag:
        arguments.append("--write-replays")

    try:
        summary = _run_benchmark(*arguments)
        output_directory = Path(str(summary["output_directory"]))
        assert output_directory == output_root / str(summary["report_hash"])
        assert summary["evidence_persisted"] is True
        assert summary["evidence_mode"] == "battle_replay_bundle"

        report_path = output_directory / "arena-report.json"
        manifest_path = output_directory / "arena-evidence-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        report = json.loads(report_path.read_text(encoding="utf-8"))
        manifest_schema = json.loads(
            (
                ROOT
                / "data/schemas/ai01-arena-evidence-manifest.schema.json"
            ).read_text(encoding="utf-8")
        )
        validate_document_contract(
            manifest,
            manifest_schema,
            "AI-01 arena evidence manifest",
        )

        assert manifest["schema_version"] == "ai01-arena-evidence-manifest-v1"
        assert manifest["report_path"] == "arena-report.json"
        assert manifest["report_hash"] == summary["report_hash"]
        assert manifest["report_file_sha256"] == _file_sha256(report_path)
        assert manifest["prebattle_evidence_mode"] == "regeneration_required"
        assert manifest["prebattle_session_hash"] == summary["prebattle_session_hash"]
        assert manifest["prebattle_proof_hash"] == summary["prebattle_proof_hash"]
        assert manifest["arena_evidence_hash"] == summary["arena_evidence_hash"]

        replay_hashes = [item["replay_hash"] for item in report["matches"]]
        assert manifest["replay_hashes"] == replay_hashes
        assert len(manifest["replay_files"]) == 2
        engine = BattleEngine(
            load_catalog(ROOT / "data/fixtures/sim01_catalog.json"),
            load_ruleset(ROOT / "data/fixtures/sim01_ruleset.json"),
        )
        for replay_file, replay_hash in zip(
            manifest["replay_files"], replay_hashes, strict=True
        ):
            path = output_directory / replay_file["path"]
            assert path.is_file()
            assert replay_file["replay_hash"] == replay_hash
            assert replay_hash in path.name
            assert replay_file["file_sha256"] == _file_sha256(path)
            replay = ReplayRecord.from_json(path.read_text(encoding="utf-8"))
            verified = verify_replay(engine, replay)
            assert canonical_hash(verified) == replay.final_state_hash

        assert manifest["arena_evidence_hash"] == canonical_hash(
            {
                "report_hash": manifest["report_hash"],
                "replay_hashes": tuple(replay_hashes),
            }
        )
    finally:
        if output_root.exists():
            shutil.rmtree(output_root)


def test_ai01_cli_summary_only_is_explicit_and_writes_nothing() -> None:
    output_root = ROOT / "runs" / f"pytest-ai01-summary-{uuid4().hex}"

    summary = _run_benchmark(
        "--output-root",
        str(output_root),
        "--summary-only",
    )

    assert summary["evidence_persisted"] is False
    assert summary["evidence_mode"] == "summary_only"
    assert summary["output_directory"] is None
    assert not output_root.exists()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
