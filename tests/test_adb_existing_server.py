from __future__ import annotations

import json
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from champions_sim.grounding import (
    AdbProtocolError,
    AdbServerIdentity,
    DirectAdbServerTransport,
    WindowsAdbOwnershipProbe,
)
from champions_sim.grounding import adb as adb_module


def _identity(port: int) -> AdbServerIdentity:
    return AdbServerIdentity(
        host="127.0.0.1",
        port=port,
        process_id=4321,
        process_started_at="2026-08-21T07:45:00+00:00",
        executable_sha256="sha256:" + "a" * 64,
    )


def _read_request(connection: socket.socket) -> str:
    raw_length = connection.recv(4)
    assert len(raw_length) == 4
    length = int(raw_length, 16)
    payload = bytearray()
    while len(payload) < length:
        payload.extend(connection.recv(length - len(payload)))
    return bytes(payload).decode("utf-8")


def _serve_once(
    listener: socket.socket,
    *,
    payload: bytes = b"capture-bytes",
    second_status: bytes = b"OKAY",
) -> tuple[threading.Thread, list[str]]:
    requests: list[str] = []

    def serve() -> None:
        connection, _address = listener.accept()
        with connection:
            requests.append(_read_request(connection))
            connection.sendall(b"OKAY")
            requests.append(_read_request(connection))
            if second_status == b"OKAY":
                connection.sendall(b"OKAY" + payload)
            else:
                detail = b"rejected-by-test-server"
                connection.sendall(b"FAIL" + f"{len(detail):04x}".encode("ascii") + detail)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread, requests


def test_direct_transport_uses_existing_server_without_a_client_process() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        thread, requests = _serve_once(listener, payload=b"png-payload")
        ownership_checks: list[str] = []

        def verify_before_send(
            client_host: str,
            client_port: int,
            server_host: str,
            server_port: int,
        ) -> None:
            assert requests == []
            assert client_host == server_host == "127.0.0.1"
            assert client_port > 0
            assert server_port == port
            ownership_checks.append("verified")

        result = DirectAdbServerTransport().execute(
            server=_identity(port),
            serial="127.0.0.1:5555",
            service="exec:screencap -p",
            timeout_seconds=2,
            max_bytes=1024,
            pre_send_check=verify_before_send,
        )
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert result == b"png-payload"
    assert ownership_checks == ["verified"]
    assert requests == ["host:transport:127.0.0.1:5555", "exec:screencap -p"]


def test_direct_transport_allows_only_scoped_client_identity_query() -> None:
    service = "exec:dumpsys package com.pokemon.champions"
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        thread, requests = _serve_once(listener, payload=b"versionCode=1")

        result = DirectAdbServerTransport().execute(
            server=_identity(port),
            serial="127.0.0.1:5555",
            service=service,
            timeout_seconds=2,
            max_bytes=1024,
            pre_send_check=lambda *_endpoint: None,
        )
        thread.join(timeout=2)

    assert result == b"versionCode=1"
    assert requests == ["host:transport:127.0.0.1:5555", service]

    with pytest.raises(AdbProtocolError, match="not allowlisted"):
        DirectAdbServerTransport().execute(
            server=_identity(5037),
            serial="127.0.0.1:5555",
            service=service + "; input tap 1 1",
            timeout_seconds=2,
            max_bytes=1024,
            pre_send_check=lambda *_endpoint: None,
        )


def test_direct_transport_rejects_server_failure_and_non_allowlisted_service() -> None:
    transport = DirectAdbServerTransport()
    with pytest.raises(AdbProtocolError, match="not allowlisted"):
        transport.execute(
            server=_identity(5037),
            serial="127.0.0.1:5555",
            service="shell:input tap 1 1",
            timeout_seconds=2,
            max_bytes=1024,
            pre_send_check=lambda *_endpoint: None,
        )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        thread, _requests = _serve_once(listener, second_status=b"FAIL")
        with pytest.raises(AdbProtocolError, match="rejected-by-test-server"):
            transport.execute(
                server=_identity(port),
                serial="127.0.0.1:5555",
                service="exec:screencap -p",
                timeout_seconds=2,
                max_bytes=1024,
                pre_send_check=lambda *_endpoint: None,
            )
        thread.join(timeout=2)


def test_direct_transport_rejects_oversized_response() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        thread, _requests = _serve_once(listener, payload=b"12345")
        with pytest.raises(AdbProtocolError, match="exceeded"):
            DirectAdbServerTransport().execute(
                server=_identity(port),
                serial="127.0.0.1:5555",
                service="exec:screencap -p",
                timeout_seconds=2,
                max_bytes=4,
                pre_send_check=lambda *_endpoint: None,
            )
        thread.join(timeout=2)


def test_direct_transport_enforces_one_aggregate_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def settimeout(self, _seconds: float) -> None:
            return None

        def sendall(self, _payload: bytes) -> None:
            return None

        def recv(self, _length: int) -> bytes:
            raise AssertionError("deadline should expire before receiving")

        def getpeername(self):
            return ("127.0.0.1", 5037)

        def getsockname(self):
            return ("127.0.0.1", 49152)

    ticks = iter((0.0, 0.1, 0.2, 1.1))
    monkeypatch.setattr(adb_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        adb_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: FakeConnection(),
    )

    with pytest.raises(AdbProtocolError, match="aggregate deadline"):
        DirectAdbServerTransport().execute(
            server=_identity(5037),
            serial="127.0.0.1:5555",
            service="exec:screencap -p",
            timeout_seconds=1,
            max_bytes=1024,
            pre_send_check=lambda *_endpoint: None,
        )


def test_windows_ownership_probe_binds_listener_to_exact_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "HD-Adb.exe"
    executable.write_bytes(b"verified-test-binary")
    output = {
        "process_id": 4321,
        "executable_path": str(executable),
        "process_started_at": "2026-08-21T07:45:00.0000000Z",
    }

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=("powershell.exe",),
            returncode=0,
            stdout=json.dumps(output),
            stderr="",
        )

    monkeypatch.setattr(adb_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(adb_module.subprocess, "run", fake_run)

    identity = WindowsAdbOwnershipProbe().snapshot(
        host="127.0.0.1",
        port=5037,
        expected_executable=executable,
    )

    assert identity.process_id == 4321
    assert identity.executable_sha256.startswith("sha256:")
    assert identity.transport == "existing_server_socket"


def test_windows_ownership_probe_binds_exact_established_connection_four_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / "HD-Adb.exe"
    executable.write_bytes(b"verified-test-binary")
    scripts: list[str] = []

    def fake_run(command, **_kwargs):
        scripts.append(command[-1])
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(
                {
                    "process_id": 4321,
                    "executable_path": str(executable),
                    "process_started_at": "2026-08-21T07:45:00.0000000Z",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(adb_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(adb_module.subprocess, "run", fake_run)

    identity = WindowsAdbOwnershipProbe().snapshot_connection(
        server_host="127.0.0.1",
        server_port=5037,
        client_host="127.0.0.1",
        client_port=49152,
        expected_executable=executable,
    )

    assert identity.process_id == 4321
    assert "-LocalPort $serverPort" in scripts[0]
    assert "-RemotePort $clientPort" in scripts[0]
    assert "$serverPort = 5037" in scripts[0]
    assert "$clientPort = 49152" in scripts[0]


def test_windows_ownership_probe_rejects_different_listener_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "HD-Adb.exe"
    observed = tmp_path / "other-adb.exe"
    expected.write_bytes(b"expected")
    observed.write_bytes(b"other")

    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            args=("powershell.exe",),
            returncode=0,
            stdout=json.dumps(
                {
                    "process_id": 9999,
                    "executable_path": str(observed),
                    "process_started_at": "2026-08-21T07:45:00Z",
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(adb_module.platform, "system", lambda: "Windows")
    monkeypatch.setattr(adb_module.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="not owned by the expected"):
        WindowsAdbOwnershipProbe().snapshot(
            host="127.0.0.1",
            port=5037,
            expected_executable=expected,
        )


def test_adb_server_identity_requires_timezone_aware_process_start() -> None:
    with pytest.raises(ValueError, match="include a timezone"):
        AdbServerIdentity(
            host="127.0.0.1",
            port=5037,
            process_id=1,
            process_started_at="2026-08-21T07:45:00",
            executable_sha256="sha256:" + "a" * 64,
        )
