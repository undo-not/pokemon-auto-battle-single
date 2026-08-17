from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.cli import main


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("SHOWDOWN_INTEGRATION") != "1",
    reason="set SHOWDOWN_INTEGRATION=1 after bootstrapping the pinned external Showdown build",
)


def test_battle_script_fixture_and_cli(capsys: pytest.CaptureFixture[str]) -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "data/schemas/showdown-battle-script.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(document)

    assert main(["battle", "--input", str(fixture)]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["format_id"] == "gen9championsbssregmb"
    assert replay["input_log"][-1] == ">p2 move thunderbolt"


def test_damage_cli_uses_showdown_state(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["session_id"] = "fixture-damage"
    document["choices"] = document["choices"][:2]
    temporary = tmp_path / "battle.json"
    temporary.write_text(json.dumps(document), encoding="utf-8")
    assert main(
        ["damage", "--input", str(temporary), "--attacker", "p1", "--move", "Thunderbolt"]
    ) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["move_id"] == "thunderbolt"
    assert result["damage"] > 0
    assert result["live_seed_before"] == result["live_seed_after"]


def test_replay_cli_reexecutes_and_verifies_document(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"
    assert main(["battle", "--input", str(fixture)]) == 0
    replay = json.loads(capsys.readouterr().out)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    assert main(["replay", "--input", str(replay_path)]) == 0
    assert json.loads(capsys.readouterr().out) == replay


def test_cli_rejects_type_coercion(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"
    document = json.loads(fixture.read_text(encoding="utf-8"))
    document["players"]["p1"]["name"] = 7
    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps(document), encoding="utf-8")

    assert main(["battle", "--input", str(hostile)]) == 2
    assert "players.p1.name must be" in capsys.readouterr().err


@pytest.mark.skipif(os.name != "nt", reason="Windows console encoding regression")
def test_cli_forces_utf8_when_parent_console_is_cp932() -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "cp932:strict"
    result = subprocess.run(
        [sys.executable, "-m", "champions_sim", "battle", "--input", str(fixture)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        timeout=30,
    )

    replay = json.loads(result.stdout.decode("utf-8"))
    assert any("Pokémon" in line for line in replay["public_log"])
