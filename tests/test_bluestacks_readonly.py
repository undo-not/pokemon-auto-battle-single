from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pytest
from jsonschema import Draft202012Validator

from champions_sim.core import canonical_hash, to_canonical_data
from champions_sim.grounding import (
    AdbObservationCapture,
    AdbServerIdentity,
    AndroidClientBuild,
    BlueStacksDiagnostics,
    BlueStacksInstance,
    CapturePayload,
    CaptureStore,
    ExternalCaptureUnavailable,
    ObservationAuthorizationError,
    load_observation_authorization,
    parse_bluestacks_config,
)
from champions_sim.grounding.bluestacks import _bluestacks_hd_adb_running
import champions_sim.grounding.seal as seal_module


ROOT = Path(__file__).resolve().parents[1]
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c63103209fb0f000294019c1d5b465f0000000049454e44"
    "ae426082"
)
TARGET_PACKAGE = "com.pokemon.champions"
XML = (
    b'<?xml version="1.0"?><hierarchy rotation="0">'
    b'<node package="com.pokemon.champions"/></hierarchy>'
)
NOW = datetime(2026, 8, 21, 8, 0, tzinfo=timezone.utc)
ISSUE_URL = "https://github.com/undo-not/pokemon-auto-battle-single/issues/3"
PLAN_ID = "m-b-development-plan"
PLAN_HASH = "sha256:" + "c" * 64
LINEAGE_RECEIPT_SHA256 = "sha256:" + "f" * 64
PARTITION = "development"
SEAL_COMMENT_URL = ISSUE_URL + "#issuecomment-123"
SEAL_RECEIPT_SHA256 = "sha256:" + "d" * 64
STORE_IDENTITY_SHA256 = "sha256:" + "e" * 64
APK_PATH = "/data/app/~~fixture/com.pokemon.champions-fixture==/base.apk"
APK_SHA256 = "1" * 64
CLIENT_BUILD = AndroidClientBuild(
    version_code=2026082101,
    version_name="1.0.0-test",
    apk_count=1,
    apk_set_sha256="sha256:"
    + canonical_hash(
        {"apk_files": [{"name": "base.apk", "sha256": "sha256:" + APK_SHA256}]}
    ),
)


def _seal():
    return seal_module.VerifiedGroundingPlanSeal(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        partition=PARTITION,
        issue_url=ISSUE_URL,
        comment_url=SEAL_COMMENT_URL,
        comment_id=123,
        actor="undo-not",
        created_at="2026-08-21T06:59:00Z",
        receipt_sha256=SEAL_RECEIPT_SHA256,
        _token=seal_module._SEAL_TOKEN,
    )


def _server(*, process_id: int = 4321) -> AdbServerIdentity:
    return AdbServerIdentity(
        host="127.0.0.1",
        port=5037,
        process_id=process_id,
        process_started_at="2026-08-21T07:45:00+00:00",
        executable_sha256="sha256:" + "a" * 64,
    )


class FakeOwnershipProbe:
    def __init__(self, snapshots: tuple[AdbServerIdentity, ...] | None = None) -> None:
        self.snapshots = list(snapshots or (_server(),) * 19)
        self.calls: list[tuple[str, int, Path]] = []

    def snapshot(
        self,
        *,
        host: str,
        port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        self.calls.append((host, port, expected_executable))
        if not self.snapshots:
            raise AssertionError("unexpected ownership probe")
        return self.snapshots.pop(0)

    def snapshot_connection(
        self,
        *,
        server_host: str,
        server_port: int,
        client_host: str,
        client_port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        assert (server_host, server_port) == ("127.0.0.1", 5037)
        assert client_host == "127.0.0.1"
        assert 1 <= client_port <= 65_535
        return self.snapshot(
            host=server_host,
            port=server_port,
            expected_executable=expected_executable,
        )


class FakeTransport:
    def __init__(self, *, screenshot: bytes = PNG) -> None:
        self.calls: list[tuple[AdbServerIdentity, str, str, int, int]] = []
        self.screenshot = screenshot

    def execute(
        self,
        *,
        server: AdbServerIdentity,
        serial: str,
        service: str,
        timeout_seconds: int,
        max_bytes: int,
        pre_send_check: Callable[[str, int, str, int], None],
    ) -> bytes:
        pre_send_check("127.0.0.1", 49152, server.host, server.port)
        self.calls.append((server, serial, service, timeout_seconds, max_bytes))
        if service == "exec:screencap -p":
            return self.screenshot
        if service == "exec:uiautomator dump /dev/tty":
            return b"UI hierarchy dumped to: /dev/tty\n" + XML + b"\n"
        if service == f"exec:dumpsys package {TARGET_PACKAGE}":
            return b"  versionCode=2026082101 minSdk=30 targetSdk=35\n  versionName=1.0.0-test\n"
        if service == f"exec:cmd package path {TARGET_PACKAGE}":
            return f"package:{APK_PATH}\n".encode()
        if service == f"exec:sha256sum {APK_PATH}":
            return f"{APK_SHA256}  {APK_PATH}\n".encode()
        raise AssertionError(f"unexpected service: {service}")


def _diagnostics(*, ready: bool) -> BlueStacksDiagnostics:
    blockers = () if ready else (
        "bluestacks_player_not_running",
        "existing_bluestacks_hd_adb_process_not_running",
        "adb_external_side_effect_risk_not_mitigated",
    )
    return BlueStacksDiagnostics(
        installed=True,
        version="5.22.51.1038",
        install_dir=r"C:\Program Files\BlueStacks_nxt",
        adb_path=r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
        config_path=r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf",
        player_process_running=ready,
        adb_process_running=ready,
        adb_server_ownership_verified=False,
        instances=(BlueStacksInstance(name="Pie64", adb_port=5555),),
        blockers=blockers,
    )


def _authorization(tmp_path: Path, *, expires_at: str = "2026-08-21T09:00:00Z"):
    path = tmp_path / "observation-authorization.json"
    document = {
        "schema_version": "1.0.0",
        "authorization_id": "authorization-issue-3-test",
        "issue_url": ISSUE_URL,
        "granted_by": "repository-owner",
        "granted_at": "2026-08-21T07:00:00Z",
        "expires_at": expires_at,
        "format_id": "gen9championsbssregmb",
        "plan_id": PLAN_ID,
        "plan_hash": PLAN_HASH,
        "lineage_receipt_sha256": LINEAGE_RECEIPT_SHA256,
        "plan_seal_comment_url": SEAL_COMMENT_URL,
        "plan_seal_receipt_sha256": SEAL_RECEIPT_SHA256,
        "partition": PARTITION,
        "instance_name": "Pie64",
        "target_package": TARGET_PACKAGE,
        "client_build": CLIENT_BUILD.to_dict(),
        "capture_store_id": "development-captures",
        "capture_store_identity_sha256": STORE_IDENTITY_SHA256,
        "allowed_actions": ["client_identity", "screenshot", "ui_hierarchy"],
        "game_scope": "private_friend_match",
        "ranked_match_allowed": False,
        "input_automation_allowed": False,
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    authorization = load_observation_authorization(
        path,
        now=NOW,
        issue_url=ISSUE_URL,
        format_id="gen9championsbssregmb",
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
        plan_seal_comment_url=SEAL_COMMENT_URL,
        plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
        partition=PARTITION,
        instance_name="Pie64",
        target_package=TARGET_PACKAGE,
        client_build=CLIENT_BUILD,
        capture_store_id="development-captures",
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
    )
    return authorization, document


def _payload() -> CapturePayload:
    return CapturePayload(
        instance_name="Pie64",
        adb_serial="127.0.0.1:5555",
        captured_at="2026-08-21T08:00:00Z",
        ui_hierarchy_before_captured_at="2026-08-21T07:59:58Z",
        screenshot_captured_at="2026-08-21T07:59:59Z",
        ui_hierarchy_captured_at="2026-08-21T08:00:00Z",
        format_id="gen9championsbssregmb",
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
        plan_seal_comment_url=SEAL_COMMENT_URL,
        plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
        partition=PARTITION,
        target_package=TARGET_PACKAGE,
        client_build=CLIENT_BUILD,
        capture_store_id="development-captures",
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        authorization_id="authorization-issue-3-test",
        authorization_sha256="sha256:" + "b" * 64,
        adb_server_ownership_verified=True,
        adb_server=_server(),
        screenshot_png=PNG,
        ui_hierarchy_before_xml=XML,
        ui_hierarchy_xml=XML,
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


def test_owned_capture_uses_only_direct_allowlisted_services(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)
    ownership = FakeOwnershipProbe()
    transport = FakeTransport()
    capture = AdbObservationCapture(
        _diagnostics(ready=True),
        authorization=authorization,
        plan_seal=_seal(),
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        ownership_probe=ownership,
        transport=transport,
        clock=lambda: NOW,
    )
    plan = capture.plan("Pie64")

    payload = capture.capture("Pie64")

    assert plan.screenshot_service == "exec:screencap -p"
    assert plan.ui_hierarchy_service == "exec:uiautomator dump /dev/tty"
    assert plan.adb_client_process_invoked is False
    assert plan.adb_client_may_start_server is False
    assert [call[2] for call in transport.calls] == [
        f"exec:dumpsys package {TARGET_PACKAGE}",
        f"exec:cmd package path {TARGET_PACKAGE}",
        f"exec:sha256sum {APK_PATH}",
        plan.ui_hierarchy_service,
        plan.screenshot_service,
        plan.ui_hierarchy_service,
        f"exec:dumpsys package {TARGET_PACKAGE}",
        f"exec:cmd package path {TARGET_PACKAGE}",
        f"exec:sha256sum {APK_PATH}",
    ]
    assert all(call[1] == "127.0.0.1:5555" for call in transport.calls)
    assert len(ownership.calls) == 19
    assert payload.screenshot_png == PNG
    assert payload.ui_hierarchy_xml == XML
    assert payload.adb_server == _server()
    assert payload.client_build == CLIENT_BUILD
    assert payload.authorization_sha256 == authorization.authorization_hash


def test_preseal_client_build_inspection_needs_no_capture_authorization() -> None:
    ownership = FakeOwnershipProbe()
    transport = FakeTransport()
    build = AdbObservationCapture(
        _diagnostics(ready=True),
        ownership_probe=ownership,
        transport=transport,
        clock=lambda: NOW,
    ).inspect_client_build("Pie64", TARGET_PACKAGE)

    assert build == CLIENT_BUILD
    assert [call[2] for call in transport.calls] == [
        f"exec:dumpsys package {TARGET_PACKAGE}",
        f"exec:cmd package path {TARGET_PACKAGE}",
        f"exec:sha256sum {APK_PATH}",
    ]
    assert len(ownership.calls) == 7


def test_stopped_emulator_fails_before_authorization_or_transport(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)
    ownership = FakeOwnershipProbe()
    transport = FakeTransport()
    capture = AdbObservationCapture(
        _diagnostics(ready=False),
        authorization=authorization,
        plan_seal=_seal(),
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        ownership_probe=ownership,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(ExternalCaptureUnavailable, match="player_not_running"):
        capture.capture("Pie64")

    assert ownership.calls == []
    assert transport.calls == []


def test_capture_rejects_wrong_or_changed_installed_client_build(
    tmp_path: Path,
) -> None:
    authorization, _document = _authorization(tmp_path)

    class WrongBuildTransport(FakeTransport):
        def execute(self, **kwargs) -> bytes:
            payload = super().execute(**kwargs)
            if kwargs["service"] == f"exec:dumpsys package {TARGET_PACKAGE}":
                return payload.replace(b"2026082101", b"2026082102")
            return payload

    wrong = WrongBuildTransport()
    with pytest.raises(ExternalCaptureUnavailable, match="authorized identity"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=_seal(),
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=FakeOwnershipProbe(),
            transport=wrong,
            clock=lambda: NOW,
        ).capture("Pie64")
    assert "exec:screencap -p" not in [call[2] for call in wrong.calls]

    class BuildDriftTransport(FakeTransport):
        def __init__(self) -> None:
            super().__init__()
            self.dump_count = 0

        def execute(self, **kwargs) -> bytes:
            payload = super().execute(**kwargs)
            if kwargs["service"] == f"exec:dumpsys package {TARGET_PACKAGE}":
                self.dump_count += 1
                if self.dump_count == 2:
                    return payload.replace(b"2026082101", b"2026082102")
            return payload

    drift = BuildDriftTransport()
    with pytest.raises(ExternalCaptureUnavailable, match="changed during capture"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=_seal(),
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=FakeOwnershipProbe(),
            transport=drift,
            clock=lambda: NOW,
        ).capture("Pie64")
    assert drift.dump_count == 2


def test_capture_requires_external_authorization_before_ownership_probe() -> None:
    ownership = FakeOwnershipProbe()
    transport = FakeTransport()
    capture = AdbObservationCapture(
        _diagnostics(ready=True),
        ownership_probe=ownership,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(ExternalCaptureUnavailable, match="authorization is required"):
        capture.capture("Pie64")

    assert ownership.calls == []
    assert transport.calls == []


def test_capture_requires_the_exact_live_plan_seal_before_ownership_probe(
    tmp_path: Path,
) -> None:
    authorization, _document = _authorization(tmp_path)
    ownership = FakeOwnershipProbe()
    transport = FakeTransport()

    with pytest.raises(ExternalCaptureUnavailable, match="seal is required"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            ownership_probe=ownership,
            transport=transport,
            clock=lambda: NOW,
        ).capture("Pie64")

    mismatched = seal_module.VerifiedGroundingPlanSeal(
        plan_id=PLAN_ID,
        plan_hash=PLAN_HASH,
        partition=PARTITION,
        issue_url=ISSUE_URL,
        comment_url=SEAL_COMMENT_URL,
        comment_id=123,
        actor="undo-not",
        created_at="2026-08-21T06:59:00Z",
        receipt_sha256="sha256:" + "e" * 64,
        _token=seal_module._SEAL_TOKEN,
    )
    with pytest.raises(ExternalCaptureUnavailable, match="does not follow"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=mismatched,
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=ownership,
            transport=transport,
            clock=lambda: NOW,
        ).capture("Pie64")

    assert ownership.calls == []
    assert transport.calls == []


def test_changed_server_owner_fails_closed_during_client_identity(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)
    ownership = FakeOwnershipProbe(
        (_server(), _server(), _server(process_id=9999))
    )
    transport = FakeTransport()
    capture = AdbObservationCapture(
        _diagnostics(ready=True),
        authorization=authorization,
        plan_seal=_seal(),
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        ownership_probe=ownership,
        transport=transport,
        clock=lambda: NOW,
    )

    with pytest.raises(ExternalCaptureUnavailable, match="ownership changed"):
        capture.capture("Pie64")

    assert [call[2] for call in transport.calls] == [
        f"exec:dumpsys package {TARGET_PACKAGE}"
    ]


def test_changed_server_owner_after_connect_fails_before_first_adb_request(
    tmp_path: Path,
) -> None:
    authorization, _document = _authorization(tmp_path)
    ownership = FakeOwnershipProbe((_server(), _server(process_id=9999)))
    transport = FakeTransport()

    with pytest.raises(ExternalCaptureUnavailable, match="not owned"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=_seal(),
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=ownership,
            transport=transport,
            clock=lambda: NOW,
        ).capture("Pie64")

    assert transport.calls == []


def test_expired_or_scope_mismatched_authorization_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ObservationAuthorizationError, match="not current"):
        _authorization(tmp_path, expires_at="2026-08-21T08:00:00Z")

    authorization, document = _authorization(tmp_path)
    schema = json.loads(
        (ROOT / "data/schemas/observation-authorization.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema).validate(document)
    with pytest.raises(ObservationAuthorizationError, match="instance_name does not match"):
        authorization.assert_current(
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64_3",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )
    with pytest.raises(ObservationAuthorizationError, match="target_package does not match"):
        authorization.assert_current(
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package="com.example.wrong",
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )


def test_authorization_source_deletion_or_replacement_revokes_loaded_token(
    tmp_path: Path,
) -> None:
    authorization, document = _authorization(tmp_path)
    authorization.source_path.unlink()
    with pytest.raises(ObservationAuthorizationError, match="cannot read"):
        authorization.assert_current(
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )

    authorization, document = _authorization(tmp_path)
    authorization.source_path.write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    with pytest.raises(ObservationAuthorizationError, match="replaced or modified"):
        authorization.assert_current(
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )

    authorization, document = _authorization(tmp_path)
    document["granted_by"] = "different-operator"
    authorization.source_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ObservationAuthorizationError, match="replaced or modified"):
        authorization.assert_current(
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )


def test_authorization_rejects_long_lifetime_duplicate_keys_and_repository_path(
    tmp_path: Path,
) -> None:
    with pytest.raises(ObservationAuthorizationError, match="eight hours"):
        _authorization(tmp_path, expires_at="2026-08-22T07:00:01Z")

    duplicate = tmp_path / "duplicate-authorization.json"
    duplicate.write_text(
        '{"schema_version":"1.0.0","schema_version":"1.0.0"}',
        encoding="utf-8",
    )
    with pytest.raises(ObservationAuthorizationError, match="duplicate JSON key"):
        load_observation_authorization(
            duplicate,
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )

    with pytest.raises(ObservationAuthorizationError, match="outside the repository"):
        load_observation_authorization(
            ROOT / "data/schemas/observation-authorization.schema.json",
            now=NOW,
            issue_url=ISSUE_URL,
            format_id="gen9championsbssregmb",
            plan_id=PLAN_ID,
            plan_hash=PLAN_HASH,
            lineage_receipt_sha256=LINEAGE_RECEIPT_SHA256,
            plan_seal_comment_url=SEAL_COMMENT_URL,
            plan_seal_receipt_sha256=SEAL_RECEIPT_SHA256,
            partition=PARTITION,
            instance_name="Pie64",
            target_package=TARGET_PACKAGE,
            client_build=CLIENT_BUILD,
            capture_store_id="development-captures",
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        )


def test_capture_store_hashes_and_verifies_external_artifacts(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")
    payload = replace(
        _payload(), capture_store_identity_sha256=store.identity_hash
    )

    manifest = store.save(payload)

    capture_dir = store.root / manifest.capture_id
    assert (capture_dir / "screenshot.png").read_bytes() == PNG
    assert (capture_dir / "ui-hierarchy.xml").read_bytes() == XML
    assert store.verify(manifest.capture_id)
    assert store.manifest_hash(manifest.capture_id).startswith("sha256:")
    assert manifest.schema_version == "2.0.0"
    assert manifest.game_input_performed is False
    assert manifest.adb_server_ownership_verified is True
    assert manifest.adb_server.transport == "existing_server_socket"
    assert manifest.contains_sensitive_content is None
    assert manifest.local_research_only is True
    assert manifest.distribution_allowed is False
    assert all(artifact.sha256.startswith("sha256:") for artifact in manifest.artifacts)
    schema = json.loads(
        (ROOT / "data/schemas/capture-manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(schema).validate(manifest.to_dict())
    store_schema = json.loads(
        (ROOT / "data/schemas/capture-store.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(store_schema).validate(to_canonical_data(store.identity))

    with pytest.raises(ValueError, match="different physical capture store"):
        store.save(
            replace(
                payload,
                capture_store_identity_sha256="sha256:" + "0" * 64,
            )
        )
    with pytest.raises(FileExistsError):
        store.save(payload, capture_id=manifest.capture_id)
    with pytest.raises(ValueError, match="stable ID"):
        store.save(payload, capture_id="../outside")


def test_capture_store_rejects_manifest_identity_and_hash_tampering(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "artifacts" / "bluestacks")
    payload = replace(
        _payload(), capture_store_identity_sha256=store.identity_hash
    )
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
    wrong_owner = json.loads(json.dumps(original))
    wrong_owner["adb_server"]["process_id"] = 9999
    mutations.append(wrong_owner)
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

    canonical = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        canonical.replace(
            '"schema_version": "2.0.0"',
            '"schema_version": "2.0.0", "schema_version": "2.0.0"',
            1,
        ),
        encoding="utf-8",
    )
    assert store.verify(manifest.capture_id) is False


def test_capture_rejects_malformed_ui_hierarchy(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)

    class MalformedXmlTransport(FakeTransport):
        def execute(self, **kwargs) -> bytes:
            if kwargs["service"] == "exec:uiautomator dump /dev/tty":
                return b"<hierarchy><node></hierarchy>"
            return super().execute(**kwargs)

    with pytest.raises(ExternalCaptureUnavailable, match="malformed XML"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=_seal(),
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=FakeOwnershipProbe(),
            transport=MalformedXmlTransport(),
            clock=lambda: NOW,
        ).capture("Pie64")


def test_capture_rejects_ui_hierarchy_from_another_package(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)

    class WrongPackageTransport(FakeTransport):
        def execute(self, **kwargs) -> bytes:
            if kwargs["service"] == "exec:uiautomator dump /dev/tty":
                return b'<hierarchy><node package="com.example.other"/></hierarchy>'
            return super().execute(**kwargs)

    with pytest.raises(ExternalCaptureUnavailable, match="authorized package"):
        AdbObservationCapture(
            _diagnostics(ready=True),
            authorization=authorization,
            plan_seal=_seal(),
            capture_store_identity_sha256=STORE_IDENTITY_SHA256,
            ownership_probe=FakeOwnershipProbe(),
            transport=WrongPackageTransport(),
            clock=lambda: NOW,
        ).capture("Pie64")


def test_capture_payload_rejects_artifact_temporal_drift() -> None:
    with pytest.raises(ValueError, match="maximum temporal skew"):
        replace(
            _payload(),
            ui_hierarchy_before_captured_at="2026-08-21T07:59:00Z",
            ui_hierarchy_captured_at="2026-08-21T08:00:00Z",
        )


def test_capture_rejects_truncated_png_stream(tmp_path: Path) -> None:
    authorization, _document = _authorization(tmp_path)
    capture = AdbObservationCapture(
        _diagnostics(ready=True),
        authorization=authorization,
        plan_seal=_seal(),
        capture_store_identity_sha256=STORE_IDENTITY_SHA256,
        ownership_probe=FakeOwnershipProbe(),
        transport=FakeTransport(screenshot=PNG[:-1]),
        clock=lambda: NOW,
    )

    with pytest.raises(ExternalCaptureUnavailable, match="PNG"):
        capture.capture("Pie64")


def test_capture_payload_rejects_png_with_invalid_crc() -> None:
    corrupted = bytearray(PNG)
    corrupted[29] ^= 1

    with pytest.raises(ValueError, match="CRC"):
        replace(_payload(), screenshot_png=bytes(corrupted))


def test_capture_payload_rejects_screen_state_change_around_screenshot() -> None:
    changed = (
        b'<?xml version="1.0"?><hierarchy rotation="0">'
        b'<node package="com.pokemon.champions" text="different-state"/>'
        b"</hierarchy>"
    )
    with pytest.raises(ValueError, match="state changed"):
        replace(_payload(), ui_hierarchy_xml=changed)


def test_default_capture_store_is_external_and_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    monkeypatch.delenv("CHAMPIONS_SIM_CAPTURE_STORE", raising=False)
    monkeypatch.chdir(tmp_path)

    assert CaptureStore().root == (
        tmp_path
        / "local-app-data"
        / "pokemon-auto-battle-single"
        / "captures"
        / "development"
    )


def test_holdout_capture_store_requires_explicit_external_root() -> None:
    with pytest.raises(ValueError, match="holdout capture store root must be explicit"):
        CaptureStore(partition="holdout")


def test_capture_store_default_id_follows_partition(tmp_path: Path) -> None:
    store = CaptureStore(tmp_path / "holdout", partition="holdout")

    assert store.store_id == "holdout-captures"


def test_workspace_capture_store_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        CaptureStore(ROOT / "artifacts" / "bluestacks")


def test_capture_store_persistently_rejects_logical_identity_relabeling(
    tmp_path: Path,
) -> None:
    root = tmp_path / "one-physical-store"
    development = CaptureStore(
        root,
        store_id="development-captures",
        partition="development",
    )
    reopened = CaptureStore(
        root,
        store_id="development-captures",
        partition="development",
        initialize=False,
    )
    assert reopened.identity_hash == development.identity_hash

    with pytest.raises(ValueError, match="must be initialized"):
        CaptureStore(
            tmp_path / "missing-store",
            store_id="development-captures",
            partition="development",
            initialize=False,
        )

    with pytest.raises(ValueError, match="does not match requested identity"):
        CaptureStore(
            root,
            store_id="holdout-captures",
            partition="holdout",
        )

    store_manifest = root / "store.json"
    original = store_manifest.read_text(encoding="utf-8")
    store_manifest.write_text(original + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="canonical JSON"):
        development.save(_payload())
