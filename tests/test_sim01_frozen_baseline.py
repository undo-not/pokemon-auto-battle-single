from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_sim01_frozen import FrozenBaselineError, validate_frozen_baseline
from scripts.validate_sim01_bundle import BundleValidationError


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "data/baselines/sim01-frozen-v1.json"


def test_current_sim01_matches_frozen_baseline() -> None:
    report = validate_frozen_baseline(BASELINE)

    assert report["ok"] is True
    assert report["baseline_id"] == "sim01-frozen-v1"


def test_frozen_baseline_detects_expected_hash_drift(tmp_path: Path) -> None:
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    payload["replay_sha256"] = "0" * 64
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FrozenBaselineError, match="replay_sha256"):
        validate_frozen_baseline(changed)


def test_frozen_baseline_rejects_legacy_v1_container(tmp_path: Path) -> None:
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    payload["schema_version"] = "1.0.0"
    legacy = tmp_path / "legacy-v1.json"
    legacy.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BundleValidationError, match="schema_version"):
        validate_frozen_baseline(legacy)
