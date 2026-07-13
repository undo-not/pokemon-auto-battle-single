from __future__ import annotations

import json
from pathlib import Path

import pytest

from champions_sim.catalog import SnapshotValidationError, load_catalog


ROOT = Path(__file__).resolve().parents[1]


def _catalog() -> dict[str, object]:
    return json.loads(
        (ROOT / "data/fixtures/sim01_catalog.json").read_text(encoding="utf-8")
    )


def test_effect_missing_runtime_inputs_fails_at_catalog_load(tmp_path: Path) -> None:
    catalog = _catalog()
    moves = catalog["moves"]
    assert isinstance(moves, list)
    sludge_bomb = next(move for move in moves if move["move_id"] == "sludge_bomb")
    del sludge_bomb["effect"]["chance_denominator"]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(SnapshotValidationError, match="missing"):
        load_catalog(path)


def test_damage_effect_on_status_move_fails_at_catalog_load(tmp_path: Path) -> None:
    catalog = _catalog()
    moves = catalog["moves"]
    assert isinstance(moves, list)
    earthquake = next(move for move in moves if move["move_id"] == "earthquake")
    earthquake["category"] = "status"
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(SnapshotValidationError, match="non-damage category"):
        load_catalog(path)


def test_sparse_type_chart_requires_an_explicit_neutral_default(tmp_path: Path) -> None:
    catalog = _catalog()
    catalog.pop("type_chart_default_multiplier")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    with pytest.raises(SnapshotValidationError, match="explicitly default"):
        load_catalog(path)
