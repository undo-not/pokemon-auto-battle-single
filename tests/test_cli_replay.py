from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def test_replay_written_by_one_process_is_verified_by_another(tmp_path: Path) -> None:
    replay_path = tmp_path / "battle.replay.json"
    battle = subprocess.run(
        [
            sys.executable,
            "-m",
            "champions_sim",
            "battle",
            "--seed",
            "20260713",
            "--replay-out",
            str(replay_path),
        ],
        cwd=ROOT,
        env=_environment(),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    verification = subprocess.run(
        [
            sys.executable,
            "-m",
            "champions_sim",
            "verify-replay",
            "--replay",
            str(replay_path),
        ],
        cwd=ROOT,
        env=_environment(),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    produced = json.loads(battle.stdout)
    verified = json.loads(verification.stdout)
    assert verified["ok"] is True
    assert verified["replay_hash"] == produced["replay_hash"]
    assert verified["final_state_hash"] == produced["final_state_hash"]
