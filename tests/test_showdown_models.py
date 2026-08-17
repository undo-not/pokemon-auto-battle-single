from __future__ import annotations

from copy import deepcopy

import pytest

from champions_sim.core.canonical import canonical_hash
from champions_sim.showdown.models import (
    DamageSample,
    ShowdownObservation,
    ShowdownReplay,
)


def _engine() -> dict[str, object]:
    return {
        "artifact_id": "pokemon-showdown-champions",
        "repository_url": "https://github.com/smogon/pokemon-showdown.git",
        "commit": "1" * 40,
        "tree": "2" * 40,
        "build_fingerprint_sha256": "3" * 64,
        "manifest_sha256": "4" * 64,
        "node_version": "v22.18.0",
        "license": "MIT",
        "bridge_protocol_version": "1.0.0",
        "bridge_sha256": "5" * 64,
    }


def _replay_document() -> dict[str, object]:
    document: dict[str, object] = {
        "schema_version": "1.0.0",
        "format_id": "gen9championsbssregmb",
        "seed": "sodium," + "00" * 32,
        "input_log": [],
        "public_log": [],
        "ended": False,
        "winner": None,
        "turns": 0,
        "score": None,
        "engine": _engine(),
    }
    document["replay_hash"] = canonical_hash(document)
    return document


def test_replay_model_accepts_canonical_document_without_node() -> None:
    document = _replay_document()

    assert ShowdownReplay.from_document(document).to_dict() == document


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("seed", "1,2,3,4"), "sodium seed"),
        (("winner", "Mallory"), "non-terminal replay"),
        (("replay_hash", "0" * 64), "replay hash"),
    ],
)
def test_replay_model_rejects_contract_drift_without_node(
    mutation: tuple[str, object], message: str
) -> None:
    document = _replay_document()
    document[mutation[0]] = mutation[1]

    with pytest.raises(ValueError, match=message):
        ShowdownReplay.from_document(document)


def test_damage_sample_rejects_live_prng_mutation_without_node() -> None:
    value: dict[str, object] = {
        "session_id": "offline",
        "revision": 1,
        "attacker": "p1",
        "source": "Sylveon",
        "target": "Pikachu",
        "move_id": "hypervoice",
        "move_type": "Fairy",
        "move_category": "Special",
        "damage": 42,
        "damage_status": "value",
        "target_max_hp": 100,
        "target_current_hp": 100,
        "clone_seed_before": "sodium," + "11" * 32,
        "clone_seed_after": "sodium," + "22" * 32,
        "live_seed_before": "sodium," + "11" * 32,
        "live_seed_after": "sodium," + "11" * 32,
    }
    assert DamageSample.from_mapping(value).damage == 42

    hostile = deepcopy(value)
    hostile["live_seed_after"] = "sodium," + "33" * 32
    with pytest.raises(ValueError, match="mutated the live PRNG"):
        DamageSample.from_mapping(hostile)

    hostile = deepcopy(value)
    hostile["clone_seed_after"] = "1,2,3,4"
    with pytest.raises(ValueError, match="must be a Showdown sodium seed"):
        DamageSample.from_mapping(hostile)


def test_observation_rejects_private_contract_inconsistency_without_node() -> None:
    value: dict[str, object] = {
        "schema_version": "1.0.0",
        "session_id": "offline",
        "format_id": "gen9championsbssregmb",
        "revision": 0,
        "ended": False,
        "winner": None,
        "turn": 0,
        "player": "p1",
        "request": {},
        "legal_actions": ["team 123"],
        "visible_log": [],
        "next_sequence": 0,
    }
    assert ShowdownObservation.from_mapping(value).player == "p1"

    value["legal_actions"] = ["team 123", "team 123"]
    with pytest.raises(ValueError, match="must be unique"):
        ShowdownObservation.from_mapping(value)
