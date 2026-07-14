from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_ai01_synthetic_benchmark_matches_frozen_golden() -> None:
    expected = json.loads(
        (ROOT / "data/golden/ai01-synthetic-benchmark-v1.json").read_text(
            encoding="utf-8"
        )
    )
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_ai01_benchmark.py",
            "--pairs",
            str(expected["pairs"]),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    actual = json.loads(completed.stdout)
    compared = {
        key: actual[key]
        for key in (
            "scope",
            "decision",
            "champions_readiness_decision",
            "pairs",
            "matches",
            "wins",
            "draws",
            "losses",
            "paired_net_utility_ppm",
            "replay_verification_rate_ppm",
            "plan_hash",
            "prebattle_session_hash",
            "prebattle_proof_hash",
            "provisional_decision_ids",
            "report_hash",
            "arena_evidence_hash",
            "champions_candidate",
            "rank1_equivalence_status",
        )
    }
    assert compared == {key: expected[key] for key in compared}
    assert expected["rank1_equivalence_claim_allowed"] is False
    assert expected["interpretation"] == "engineering_baseline_only_not_rank_evidence"
