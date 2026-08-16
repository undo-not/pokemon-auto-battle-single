from __future__ import annotations

import json
from pathlib import Path
import platform
import re
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "data/golden/ai01-synthetic-benchmark-v2.json"
RUNTIME_BOUND_HASH_KEYS = (
    "plan_hash",
    "prebattle_proof_hash",
    "report_hash",
    "arena_evidence_hash",
)


def test_ai01_synthetic_benchmark_matches_frozen_golden() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert expected["schema_version"] == "ai01-synthetic-benchmark-golden-v2"
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
    semantic_keys = (
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
        "prebattle_session_hash",
        "provisional_decision_ids",
        "champions_candidate",
        "rank1_equivalence_status",
    )
    compared = {
        key: actual[key]
        for key in semantic_keys
    }
    assert compared == {key: expected[key] for key in compared}

    reference_runtime = expected["reference_runtime"]
    is_reference_runtime = (
        platform.python_implementation() == reference_runtime["implementation"]
        and sys.version_info[:3]
        == (
            reference_runtime["major"],
            reference_runtime["minor"],
            reference_runtime["micro"],
        )
    )
    for key in RUNTIME_BOUND_HASH_KEYS:
        assert re.fullmatch(r"[0-9a-f]{64}", actual[key]) is not None
        if is_reference_runtime:
            assert actual[key] == expected[key]

    assert expected["rank1_equivalence_claim_allowed"] is False
    assert expected["interpretation"] == "engineering_baseline_only_not_rank_evidence"


def test_ai01_reference_runtime_is_exercised_by_ci() -> None:
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    runtime = expected["reference_runtime"]
    reference_version = f'{runtime["major"]}.{runtime["minor"]}.{runtime["micro"]}'
    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )

    configured_versions = workflow["jobs"]["validate"]["strategy"]["matrix"][
        "python-version"
    ]
    assert reference_version in configured_versions
