"""Existing-server ADB transport and Windows listener ownership evidence."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import socket
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from .android_client import is_read_only_client_identity_service


_ADB_SERIAL_RE = re.compile(r"^127\.0\.0\.1:[1-9][0-9]{0,4}$")
_ALLOWED_SERVICES = {
    "exec:screencap -p",
    "exec:uiautomator dump /dev/tty",
}
_POWERSHELL = (
    Path(os.environ.get("SystemRoot", r"C:\Windows"))
    / "System32"
    / "WindowsPowerShell"
    / "v1.0"
    / "powershell.exe"
)
_OWNERSHIP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$port = __PORT__
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
if ($listeners.Count -ne 1) {
    throw "expected exactly one listener on port $port"
}
if ($listeners[0].LocalAddress -ne '127.0.0.1') {
    throw "listener on port $port is not bound to IPv4 loopback"
}
$process = Get-Process -Id $listeners[0].OwningProcess -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace($process.Path)) {
    throw 'listener process path is unavailable'
}
[pscustomobject]@{
    process_id = [int]$process.Id
    executable_path = [string]$process.Path
    process_started_at = $process.StartTime.ToUniversalTime().ToString('o')
} | ConvertTo-Json -Compress
""".strip()

_CONNECTION_OWNERSHIP_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$utf8 = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$serverPort = __SERVER_PORT__
$clientPort = __CLIENT_PORT__
$connections = @(Get-NetTCPConnection -State Established `
    -LocalAddress '127.0.0.1' -LocalPort $serverPort `
    -RemoteAddress '127.0.0.1' -RemotePort $clientPort `
    -ErrorAction SilentlyContinue)
if ($connections.Count -ne 1) {
    throw "expected exactly one server-side established connection"
}
$process = Get-Process -Id $connections[0].OwningProcess -ErrorAction Stop
if ([string]::IsNullOrWhiteSpace($process.Path)) {
    throw 'connection process path is unavailable'
}
[pscustomobject]@{
    process_id = [int]$process.Id
    executable_path = [string]$process.Path
    process_started_at = $process.StartTime.ToUniversalTime().ToString('o')
} | ConvertTo-Json -Compress
""".strip()


class AdbOwnershipError(RuntimeError):
    """Raised when the existing ADB server cannot be bound to BlueStacks."""


class AdbProtocolError(RuntimeError):
    """Raised for malformed, rejected, or oversized ADB server responses."""


@dataclass(frozen=True, slots=True)
class AdbServerIdentity:
    host: str
    port: int
    process_id: int
    process_started_at: str
    executable_sha256: str
    transport: str = "existing_server_socket"

    def __post_init__(self) -> None:
        if self.host != "127.0.0.1":
            raise ValueError("ADB server must be bound through IPv4 loopback")
        if not 1 <= self.port <= 65_535:
            raise ValueError("ADB server port is invalid")
        if self.process_id <= 0:
            raise ValueError("ADB server process identity is incomplete")
        try:
            timestamp = re.sub(
                r"(\.\d{6})\d+(?=Z|[+-]\d{2}:\d{2}$)",
                r"\1",
                self.process_started_at,
            )
            started_at = datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            )
        except (AttributeError, ValueError) as error:
            raise ValueError("ADB server process start time is invalid") from error
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("ADB server process start time must include a timezone")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.executable_sha256) is None:
            raise ValueError("ADB server executable hash is invalid")
        if self.transport != "existing_server_socket":
            raise ValueError("only the existing-server socket transport is permitted")


class AdbOwnershipProbe(Protocol):
    def snapshot(
        self,
        *,
        host: str,
        port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        """Resolve the current loopback listener without starting ADB."""

    def snapshot_connection(
        self,
        *,
        server_host: str,
        server_port: int,
        client_host: str,
        client_port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        """Resolve the owner of the exact accepted server-side TCP connection."""


class AdbObservationTransport(Protocol):
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
        """Connect, verify the accepted listener, then send one allowlisted service."""


class WindowsAdbOwnershipProbe:
    """Bind a loopback listener to the exact installed BlueStacks HD-Adb image."""

    def __init__(self, *, command_timeout_seconds: int = 10) -> None:
        if command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")
        self._command_timeout_seconds = command_timeout_seconds

    def snapshot(
        self,
        *,
        host: str,
        port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        if platform.system() != "Windows":
            raise AdbOwnershipError("ADB listener ownership is supported only on Windows")
        if host != "127.0.0.1" or not 1 <= port <= 65_535:
            raise AdbOwnershipError("ADB ownership requires a valid IPv4 loopback endpoint")
        try:
            expected = expected_executable.resolve(strict=True)
        except OSError as error:
            raise AdbOwnershipError(
                "expected BlueStacks ADB executable cannot be resolved"
            ) from error
        if not expected.is_file():
            raise AdbOwnershipError("expected BlueStacks ADB executable is not a file")
        script = _OWNERSHIP_SCRIPT.replace("__PORT__", str(port))
        return self._snapshot_from_script(
            script=script,
            host=host,
            port=port,
            expected_executable=expected,
            label="listener",
        )

    def snapshot_connection(
        self,
        *,
        server_host: str,
        server_port: int,
        client_host: str,
        client_port: int,
        expected_executable: Path,
    ) -> AdbServerIdentity:
        if platform.system() != "Windows":
            raise AdbOwnershipError("ADB connection ownership is supported only on Windows")
        if (
            server_host != "127.0.0.1"
            or client_host != "127.0.0.1"
            or not 1 <= server_port <= 65_535
            or not 1 <= client_port <= 65_535
        ):
            raise AdbOwnershipError(
                "ADB connection ownership requires an IPv4 loopback 4-tuple"
            )
        try:
            expected = expected_executable.resolve(strict=True)
        except OSError as error:
            raise AdbOwnershipError(
                "expected BlueStacks ADB executable cannot be resolved"
            ) from error
        if not expected.is_file():
            raise AdbOwnershipError("expected BlueStacks ADB executable is not a file")
        script = (
            _CONNECTION_OWNERSHIP_SCRIPT.replace("__SERVER_PORT__", str(server_port))
            .replace("__CLIENT_PORT__", str(client_port))
        )
        return self._snapshot_from_script(
            script=script,
            host=server_host,
            port=server_port,
            expected_executable=expected,
            label="established connection",
        )

    def _snapshot_from_script(
        self,
        *,
        script: str,
        host: str,
        port: int,
        expected_executable: Path,
        label: str,
    ) -> AdbServerIdentity:
        command = (
            str(_POWERSHELL),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        )
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                shell=False,
                timeout=self._command_timeout_seconds,
            )
        except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
            raise AdbOwnershipError(f"cannot inspect ADB listener ownership: {error}") from error
        if completed.returncode != 0:
            lines = [line.strip() for line in completed.stderr.splitlines() if line.strip()]
            detail = lines[0] if lines else "ownership probe returned no diagnostic"
            raise AdbOwnershipError(
                f"ADB {label} ownership inspection failed: {detail[:240]}"
            )
        try:
            raw = json.loads(completed.stdout, object_pairs_hook=_unique_object)
        except (json.JSONDecodeError, ValueError) as error:
            raise AdbOwnershipError(
                f"ADB {label} ownership output is invalid JSON"
            ) from error
        if not isinstance(raw, dict) or set(raw) != {
            "process_id",
            "executable_path",
            "process_started_at",
        }:
            raise AdbOwnershipError(
                f"ADB {label} ownership output has an invalid shape"
            )
        process_id = raw["process_id"]
        executable_path = raw["executable_path"]
        process_started_at = raw["process_started_at"]
        if (
            not isinstance(process_id, int)
            or isinstance(process_id, bool)
            or process_id <= 0
            or not isinstance(executable_path, str)
            or not isinstance(process_started_at, str)
            or not process_started_at
        ):
            raise AdbOwnershipError(f"ADB {label} ownership output has invalid fields")
        try:
            observed = Path(executable_path).resolve(strict=True)
        except OSError as error:
            raise AdbOwnershipError(
                f"ADB {label} executable cannot be resolved"
            ) from error
        if os.path.normcase(str(observed)) != os.path.normcase(
            str(expected_executable)
        ):
            raise AdbOwnershipError(
                f"ADB {label} is not owned by the expected HD-Adb image"
            )
        return AdbServerIdentity(
            host=host,
            port=port,
            process_id=process_id,
            process_started_at=process_started_at,
            executable_sha256="sha256:" + _file_sha256(expected_executable),
        )


class DirectAdbServerTransport:
    """Use the ADB client/server protocol without executing an ADB client binary."""

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
        if _ADB_SERIAL_RE.fullmatch(serial) is None:
            raise AdbProtocolError("ADB serial must identify a loopback BlueStacks instance")
        serial_port = int(serial.rsplit(":", 1)[1])
        if serial_port > 65_535:
            raise AdbProtocolError("ADB serial port is invalid")
        if service not in _ALLOWED_SERVICES and not is_read_only_client_identity_service(
            service
        ):
            raise AdbProtocolError("ADB service is not allowlisted")
        if timeout_seconds <= 0 or max_bytes <= 0:
            raise ValueError("ADB timeout and response limit must be positive")
        deadline = time.monotonic() + timeout_seconds
        try:
            connection = socket.create_connection(
                (server.host, server.port), timeout=_remaining_seconds(deadline)
            )
            with connection:
                client_host, client_port = connection.getsockname()[:2]
                peer_host, peer_port = connection.getpeername()[:2]
                if peer_host != server.host or peer_port != server.port:
                    raise AdbProtocolError("ADB connection peer does not match the owned server")
                if client_host != "127.0.0.1" or not isinstance(client_port, int):
                    raise AdbProtocolError("ADB client socket is not IPv4 loopback")
                pre_send_check(client_host, client_port, peer_host, peer_port)
                _send_request(connection, f"host:transport:{serial}", deadline)
                _expect_okay(connection, deadline)
                _send_request(connection, service, deadline)
                _expect_okay(connection, deadline)
                payload = bytearray()
                while True:
                    connection.settimeout(_remaining_seconds(deadline))
                    chunk = connection.recv(min(65_536, max_bytes + 1 - len(payload)))
                    if not chunk:
                        break
                    payload.extend(chunk)
                    if len(payload) > max_bytes:
                        raise AdbProtocolError("ADB response exceeded the configured limit")
        except AdbProtocolError:
            raise
        except (OSError, TimeoutError) as error:
            raise AdbProtocolError(f"existing ADB server request failed: {error}") from error
        return bytes(payload)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AdbProtocolError("ADB request exceeded the aggregate deadline")
    return remaining


def _send_request(connection: socket.socket, request: str, deadline: float) -> None:
    encoded = request.encode("utf-8")
    if not encoded or len(encoded) > 0xFFFF:
        raise AdbProtocolError("ADB request length is invalid")
    connection.settimeout(_remaining_seconds(deadline))
    connection.sendall(f"{len(encoded):04x}".encode("ascii") + encoded)


def _recv_exact(connection: socket.socket, length: int, deadline: float) -> bytes:
    payload = bytearray()
    while len(payload) < length:
        connection.settimeout(_remaining_seconds(deadline))
        chunk = connection.recv(length - len(payload))
        if not chunk:
            raise AdbProtocolError("ADB server closed an incomplete response")
        payload.extend(chunk)
    return bytes(payload)


def _expect_okay(connection: socket.socket, deadline: float) -> None:
    status = _recv_exact(connection, 4, deadline)
    if status == b"OKAY":
        return
    if status == b"FAIL":
        raw_length = _recv_exact(connection, 4, deadline)
        try:
            length = int(raw_length, 16)
        except ValueError as error:
            raise AdbProtocolError("ADB failure response has an invalid length") from error
        if length > 65_535:
            raise AdbProtocolError("ADB failure response is too large")
        detail = _recv_exact(connection, length, deadline).decode(
            "utf-8", errors="replace"
        )
        raise AdbProtocolError(f"ADB server rejected the request: {detail[:240]}")
    raise AdbProtocolError("ADB server returned an unknown status")


__all__ = [
    "AdbObservationTransport",
    "AdbOwnershipError",
    "AdbOwnershipProbe",
    "AdbProtocolError",
    "AdbServerIdentity",
    "DirectAdbServerTransport",
    "WindowsAdbOwnershipProbe",
]
