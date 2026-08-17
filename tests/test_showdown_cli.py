from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from champions_sim.cli import main
from champions_sim.core.canonical import canonical_hash
from champions_sim.showdown import (
    RandomBattleAuditError,
    validate_random_battle_audit_document,
)


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

    assert main(["battle", "--input", str(fixture), "--allow-incomplete"]) == 0
    replay = json.loads(capsys.readouterr().out)
    assert replay["format_id"] == "gen9championsbssregmb"
    assert replay["input_log"][-1] == ">p2 move thunderbolt"


def test_battle_cli_requires_explicit_incomplete_replay_export(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = ROOT / "data/fixtures/showdown-battle-script.json"

    assert main(["battle", "--input", str(fixture)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "REPLAY_INCOMPLETE" in error["error"]


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
    assert main(["battle", "--input", str(fixture), "--allow-incomplete"]) == 0
    replay = json.loads(capsys.readouterr().out)
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    assert main(["replay", "--input", str(replay_path)]) == 0
    assert json.loads(capsys.readouterr().out) == replay


def test_random_battle_completion_audit_runs_ten_reproducible_battles(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "m-b-random-10.json"

    assert main(["audit-random-battles", "--output", str(output)]) == 0

    result = json.loads(capsys.readouterr().out)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert result == {
        "ok": True,
        "audit_id": report["audit_id"],
        "status": "passed",
        "output": str(output.resolve()),
        "report_hash": report["report_hash"],
        "totals": report["totals"],
        "determinism": report["determinism"],
    }
    assert report["battle_count"] == 10
    assert report["format"] == {
        "id": "gen9championsbssregmb",
        "name": "[Gen 9 Champions] BSS Reg M-B",
        "mod": "champions",
        "regulation": "M-B",
        "game_type": "singles",
        "registered_team_size": 6,
        "picked_team_size": 3,
    }
    assert report["totals"]["terminal_battles"] == 10
    assert report["totals"]["replay_verified_battles"] == 10
    assert report["totals"]["unique_teams"] == 20
    assert report["totals"]["team_choices"] == 20
    assert report["totals"]["move_choices"] > 0
    assert report["totals"]["switch_choices"] > 0
    assert report["determinism"]["repetitions"] == 2
    assert report["determinism"]["process_isolated"] is True
    assert len(report["battles"]) == 10
    assert len(
        {
            battle["teams"][player]["team_hash"]
            for battle in report["battles"]
            for player in ("p1", "p2")
        }
    ) == 20
    for battle in report["battles"]:
        assert battle["replay_verification"]["exact_match"] is True
        assert battle["replay_verification"]["decision_log_match"] is True
        assert (
            battle["replay_verification"]["reexecuted_replay_hash"]
            == battle["replay"]["replay_hash"]
        )
        assert battle["replay"]["ended"] is True
        assert battle["winner"] in battle["players"].values()
        assert all(len(battle["teams"][player]["team"]) == 6 for player in ("p1", "p2"))
        assert all(battle["selections"][player].startswith("team ") for player in ("p1", "p2"))
        for player in ("p1", "p2"):
            assert [
                line
                for line in battle["replay"]["input_log"][3:]
                if line.startswith(f">{player} ")
            ] == [
                decision["replay_input"]
                for decision in battle["decisions"]
                if decision["player"] == player
            ]
    assert any(
        decision["replay_input"]
        != f">{decision['player']} {decision['choice']}"
        for battle in report["battles"]
        for decision in battle["decisions"]
    )
    schema_root = ROOT / "data" / "schemas"
    replay_schema = json.loads(
        (schema_root / "showdown-replay.schema.json").read_text(encoding="utf-8")
    )
    audit_schema = json.loads(
        (schema_root / "random-battle-audit.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(
        replay_schema["$id"], Resource.from_contents(replay_schema)
    )
    Draft202012Validator(audit_schema, registry=registry).validate(report)
    validate_random_battle_audit_document(report)
    false_claim = json.loads(json.dumps(report))
    false_claim["determinism"]["process_isolated"] = False
    with pytest.raises(ValidationError):
        Draft202012Validator(audit_schema, registry=registry).validate(false_claim)
    with pytest.raises(RandomBattleAuditError, match="determinism"):
        validate_random_battle_audit_document(false_claim)
    false_decision = json.loads(json.dumps(report))
    false_decision["battles"][0]["decisions"][0]["replay_input"] = (
        ">p1 team 1, 2, 3"
    )
    with pytest.raises(RandomBattleAuditError, match="Replay decision"):
        validate_random_battle_audit_document(false_decision)
    claimed_hash = report.pop("report_hash")
    assert claimed_hash == canonical_hash(report)


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
        [
            sys.executable,
            "-m",
            "champions_sim",
            "battle",
            "--input",
            str(fixture),
            "--allow-incomplete",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=True,
        timeout=30,
    )

    replay = json.loads(result.stdout.decode("utf-8"))
    assert any("Pokémon" in line for line in replay["public_log"])
