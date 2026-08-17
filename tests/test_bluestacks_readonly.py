from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from champions_sim.grounding import (
    AdbObservationCapture,
    BlueStacksDiagnostics,
    BlueStacksInstance,
    CapturePayload,
    CaptureStore,
    ExternalCaptureUnavailable,
    parse_bluestacks_config,
)
from champions_sim.grounding.bluestacks import CommandResult, _bluestacks_hd_adb_running


ROOT = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\nminimal-test-payload"
XML = b'<?xml version="1.0"?><hierarchy rotation="0"></hierarchy>'


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def run(self, command: tuple[str, ...], *, timeout_seconds: int) -> CommandResult:
        assert timeout_seconds == 15
        self.commands.append(command)
        if command[-2:] == ("screencap", "-p"):
            stdout = PNG
        else:
            stdout = b"UI hierchary dumped to: /dev/tty\n" + XML + b"\n"
        return CommandResult(command=command, returncode=0, stdout=stdout, stderr=b"")


def _diagnostics(*, ready: bool) -> BlueStacksDiagnostics:
    blockers = () if ready else (
        "bluestacks_player_not_running",
        "existing_adb_process_not_running",
    )
    return BlueStacksDiagnostics(
        installed=True,
        version="5.22.51.1038",
        install_dir=r"C:\Program Files\BlueStacks_nxt",
        adb_path=r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        config_path=r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf",
        player_process_running=ready,
        adb_process_running=ready,
        adb_server_ownership_verified=ready,
        instances=(BlueStacksInstance(name="Pie64", adb_port=5555),),
        blockers=blockers,
    )


def test_config_parser_deduplicates_status_port_aliases_and_ignores_other_values() -> None:
    config = """
bst.instance.Pie64.adb_port="5555"
bst.instance.Pie64.status.adb_port="5555"
bst.instance.Pie64_3.adb_port="5585"
bst.instance.Pie64_3.status.adb_port="5585"
bst.instance.Pie64_3.some_secret="must-not-be-returned"
bst.instance.invalid.adb_port="99999"
"""

    assert parse_bluestacks_config(config) == (
        BlueStacksInstance(name="Pie64", adb_port=5555),
        BlueStacksInstance(name="Pie64_3", adb_port=5585),
    )


def test_unrelated_generic_adb_process_is_not_bluestacks_daemon_evidence() -> None:
    assert not _bluestacks_hd_adb_running(frozenset({"adb.exe"}))
    assert _bluestacks_hd_adb_running(frozenset({"hd-adb.exe"}))


def test_externally_managed_capture_runs_only_two_exact_observation_commands() -> None:
    runner = FakeRunner()
    capture = AdbObservationCapture(_diagnostics(ready=True), runner)
    plan = capture.plan("Pie64")

    payload = capture.capture("Pie64")

    assert runner.commands == [plan.screenshot_command, plan.ui_hierarchy_command]
    prefix = (
        r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        "-s",
        "127.0.0.1:5555",
        "exec-out",
    )
    assert plan.screenshot_command == prefix + ("screencap", "-p")
    assert plan.ui_hierarchy_command == prefix + (
        "uiautomator",
        "dump",
        "/dev/tty",
    )
    assert plan.adb_client_may_start_server is True
    assert all("input" not in command and "connect" not in command for command in runner.commands)
    assert payload.screenshot_png == PNG
    assert payload.ui_hierarchy_xml == XML


def test_stopped_emulator_fails_before_runner_is_called() -> None:
    runner = FakeRunner()
    capture = AdbObservationCapture(_diagnostics(ready=False), runner)

    with pytest.raises(ExternalCaptureUnavailable, match="player_not_running"):
        capture.capture("Pie64")

    assert runner.commands == []


def test_unmitigated_adb_daemon_race_fails_before_runner_is_called() -> None:
    runner = FakeRunner()
    diagnostics = BlueStacksDiagnostics(
        installed=True,
        version="5.22.51.1038",
        install_dir=r"C:\Program Files\BlueStacks_nxt",
        adb_path=r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        config_path=r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf",
        player_process_running=True,
        adb_process_running=True,
        adb_server_ownership_verified=False,
        instances=(BlueStacksInstance(name="Pie64", adb_port=5555),),
        blockers=("adb_external_side_effect_risk_not_mitigated",),
    )

    with pytest.raises(ExternalCaptureUnavailable, match="side_effect_risk"):
        AdbObservationCapture(diagnostics, runner).capture("Pie64")

    assert runner.commands == []


def test_capture_store_hashes_and_verifies_gitignored_local_artifacts(tmp_path: Path) -> None:
    payload = CapturePayload(
        instance_name="Pie64",
        adb_serial="127.0.0.1:5555",
        captured_at="2026-07-13T00:00:00Z",
        adb_server_ownership_verified=True,
        screenshot_png=PNG,
        ui_hierarchy_xml=XML,
    )
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")

    manifest = store.save(payload)

    capture_dir = store.root / manifest.capture_id
    assert (capture_dir / "screenshot.png").read_bytes() == PNG
    assert (capture_dir / "ui-hierarchy.xml").read_bytes() == XML
    assert store.verify(manifest.capture_id)
    assert store.manifest_hash(manifest.capture_id).startswith("sha256:")
    assert manifest.game_input_performed is False
    assert manifest.adb_server_ownership_verified is True
    assert manifest.contains_sensitive_content is None
    assert manifest.local_research_only is True
    assert manifest.distribution_allowed is False
    assert all(artifact.sha256.startswith("sha256:") for artifact in manifest.artifacts)
    schema = json.loads(
        (ROOT / "data/schemas/capture-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(manifest.to_dict())

    with pytest.raises(FileExistsError):
        store.save(payload, capture_id=manifest.capture_id)
    with pytest.raises(ValueError, match="stable ID"):
        store.save(payload, capture_id="../outside")


def test_capture_store_rejects_manifest_schema_identity_and_hash_tampering(tmp_path: Path) -> None:
    payload = CapturePayload(
        instance_name="Pie64",
        adb_serial="127.0.0.1:5555",
        captured_at="2026-07-13T00:00:00Z",
        adb_server_ownership_verified=True,
        screenshot_png=PNG,
        ui_hierarchy_xml=XML,
    )
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")
    manifest = store.save(payload)
    manifest_path = store.root / manifest.capture_id / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    mutations = []
    empty_artifacts = json.loads(json.dumps(original))
    empty_artifacts["artifacts"] = []
    mutations.append(empty_artifacts)
    wrong_identity = json.loads(json.dumps(original))
    wrong_identity["capture_id"] = "capture-" + "0" * 64
    mutations.append(wrong_identity)
    wrong_metadata = json.loads(json.dumps(original))
    wrong_metadata["instance_name"] = "Pie64_3"
    mutations.append(wrong_metadata)
    wrong_hash = json.loads(json.dumps(original))
    wrong_hash["artifacts"][0]["sha256"] = "sha256:" + "0" * 64
    mutations.append(wrong_hash)
    extra_field = json.loads(json.dumps(original))
    extra_field["trusted"] = True
    mutations.append(extra_field)

    for mutated in mutations:
        manifest_path.write_text(json.dumps(mutated), encoding="utf-8")
        assert store.verify(manifest.capture_id) is False

    manifest_path.write_text(json.dumps(original), encoding="utf-8")
    assert store.verify(manifest.capture_id) is True


def test_default_capture_store_is_repo_anchored_even_after_cwd_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert CaptureStore().root == ROOT / "artifacts" / "bluestacks"


def test_default_raw_capture_path_is_gitignored() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "**/artifacts/bluestacks/" in ignore
