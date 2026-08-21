"""BlueStacks discovery and fail-closed observation capture boundary.

Discovery never invokes ADB. Capture talks directly to an already-running ADB
server and verifies its Windows listener owner before and after every stream;
the Python capture path never executes an ADB client binary.
"""

from __future__ import annotations

import csv
import io
import re
import struct
import subprocess
import xml.etree.ElementTree as ElementTree
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from champions_sim.core import canonical_hash, to_canonical_data

from .adb import (
    AdbObservationTransport,
    AdbOwnershipError,
    AdbOwnershipProbe,
    AdbProtocolError,
    AdbServerIdentity,
    DirectAdbServerTransport,
    WindowsAdbOwnershipProbe,
)
from .android_client import (
    AndroidClientBuild,
    AndroidClientIdentityError,
    is_read_only_client_identity_service,
    observe_android_client_build,
)
from .authorization import (
    ObservationAuthorizationError,
    ValidatedObservationAuthorization,
)
from .seal import VerifiedGroundingPlanSeal


_ADB_PORT_RE = re.compile(
    r'^bst\.instance\.(?P<name>[A-Za-z0-9_-]+)\.(?:status\.)?adb_port='
    r'"?(?P<port>[0-9]{1,5})"?\s*$'
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ANDROID_PACKAGE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
_MAX_ARTIFACT_SKEW = timedelta(seconds=30)
_MAX_PNG_DIMENSION = 16_384
_MAX_PNG_DECOMPRESSED_BYTES = 128 * 1024 * 1024


def _validate_png(payload: bytes) -> None:
    if not isinstance(payload, bytes) or not payload.startswith(_PNG_SIGNATURE):
        raise ValueError("screenshot payload is not a PNG")
    offset = len(_PNG_SIGNATURE)
    ihdr: tuple[int, int, int, int] | None = None
    idat_parts: list[bytes] = []
    saw_palette = False
    idat_ended = False
    saw_iend = False
    chunk_index = 0
    while offset < len(payload):
        if len(payload) - offset < 12:
            raise ValueError("screenshot PNG has a truncated chunk")
        length = int.from_bytes(payload[offset : offset + 4], "big")
        chunk_type = payload[offset + 4 : offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(payload):
            raise ValueError("screenshot PNG has a truncated chunk")
        if (
            len(chunk_type) != 4
            or any(not (65 <= value <= 90 or 97 <= value <= 122) for value in chunk_type)
            or chunk_type[2] & 0x20
        ):
            raise ValueError("screenshot PNG has an invalid chunk type")
        data = payload[data_start:data_end]
        declared_crc = int.from_bytes(payload[data_end:crc_end], "big")
        actual_crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        if declared_crc != actual_crc:
            raise ValueError("screenshot PNG chunk CRC is invalid")
        offset = crc_end

        if chunk_index == 0 and chunk_type != b"IHDR":
            raise ValueError("screenshot PNG does not begin with IHDR")
        if chunk_type == b"IHDR":
            if chunk_index != 0 or ihdr is not None or length != 13:
                raise ValueError("screenshot PNG IHDR is invalid")
            width, height, bit_depth, color_type, compression, filtering, interlace = (
                struct.unpack(">IIBBBBB", data)
            )
            allowed_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if (
                width == 0
                or height == 0
                or width > _MAX_PNG_DIMENSION
                or height > _MAX_PNG_DIMENSION
                or color_type not in allowed_depths
                or bit_depth not in allowed_depths[color_type]
                or compression != 0
                or filtering != 0
                or interlace != 0
            ):
                raise ValueError("screenshot PNG IHDR values are unsupported")
            ihdr = (width, height, bit_depth, color_type)
        elif ihdr is None:
            raise ValueError("screenshot PNG is missing IHDR")
        elif chunk_type == b"PLTE":
            if idat_parts or saw_palette or not 0 < length <= 768 or length % 3:
                raise ValueError("screenshot PNG palette is invalid")
            saw_palette = True
        elif chunk_type == b"IDAT":
            if idat_ended or length == 0:
                raise ValueError("screenshot PNG IDAT sequence is invalid")
            idat_parts.append(data)
        else:
            if idat_parts:
                idat_ended = True
            if chunk_type == b"IEND":
                if length != 0 or saw_iend or offset != len(payload):
                    raise ValueError("screenshot PNG IEND is invalid")
                saw_iend = True
                break
            if chunk_type[0] & 0x20 == 0:
                raise ValueError("screenshot PNG has an unknown critical chunk")
        chunk_index += 1

    if ihdr is None or not idat_parts or not saw_iend:
        raise ValueError("screenshot PNG is incomplete")
    width, height, bit_depth, color_type = ihdr
    if color_type == 3 and not saw_palette:
        raise ValueError("screenshot indexed PNG is missing its palette")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    row_bytes = (width * bit_depth * channels + 7) // 8
    expected_bytes = height * (row_bytes + 1)
    if expected_bytes > _MAX_PNG_DECOMPRESSED_BYTES:
        raise ValueError("screenshot PNG expands beyond the configured limit")
    decoder = zlib.decompressobj()
    try:
        decoded = decoder.decompress(b"".join(idat_parts), expected_bytes + 1)
        if len(decoded) > expected_bytes or decoder.unconsumed_tail:
            raise ValueError(
                "screenshot PNG IDAT stream is incomplete or oversized"
            )
        decoded += decoder.flush()
    except zlib.error as error:
        raise ValueError("screenshot PNG IDAT stream is invalid") from error
    if (
        len(decoded) != expected_bytes
        or not decoder.eof
        or decoder.unused_data
        or decoder.unconsumed_tail
    ):
        raise ValueError("screenshot PNG IDAT stream is incomplete or oversized")
    scanline_size = row_bytes + 1
    if any(decoded[index] > 4 for index in range(0, len(decoded), scanline_size)):
        raise ValueError("screenshot PNG uses an invalid scanline filter")


class ExternalCaptureUnavailable(RuntimeError):
    """Raised before ADB execution when a capture precondition is absent."""


@dataclass(frozen=True, slots=True)
class BlueStacksInstance:
    name: str
    adb_port: int

    def __post_init__(self) -> None:
        if not self.name or not 1 <= self.adb_port <= 65_535:
            raise ValueError("BlueStacks instance requires a name and valid ADB port")

    @property
    def adb_serial(self) -> str:
        return f"127.0.0.1:{self.adb_port}"


@dataclass(frozen=True, slots=True)
class BlueStacksDiagnostics:
    installed: bool
    version: str | None
    install_dir: str | None
    adb_path: str | None
    config_path: str | None
    player_process_running: bool
    adb_process_running: bool
    adb_server_ownership_verified: bool
    instances: tuple[BlueStacksInstance, ...]
    blockers: tuple[str, ...]

    @property
    def capture_ready(self) -> bool:
        return (
            self.installed
            and self.adb_path is not None
            and self.player_process_running
            and self.adb_process_running
            and self.adb_server_ownership_verified
            and bool(self.instances)
            and not self.blockers
        )

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class CapturePlan:
    instance_name: str
    adb_serial: str
    adb_server_host: str
    adb_server_port: int
    screenshot_service: str
    ui_hierarchy_service: str
    adb_client_process_invoked: bool
    adb_client_may_start_server: bool

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


@dataclass(frozen=True, slots=True)
class CapturePayload:
    instance_name: str
    adb_serial: str
    captured_at: str
    ui_hierarchy_before_captured_at: str
    screenshot_captured_at: str
    ui_hierarchy_captured_at: str
    format_id: str
    plan_id: str
    plan_hash: str
    lineage_receipt_sha256: str
    plan_seal_comment_url: str
    plan_seal_receipt_sha256: str
    partition: str
    target_package: str
    client_build: AndroidClientBuild
    capture_store_id: str
    capture_store_identity_sha256: str
    authorization_id: str
    authorization_sha256: str
    adb_server_ownership_verified: bool
    adb_server: AdbServerIdentity
    screenshot_png: bytes
    ui_hierarchy_before_xml: bytes
    ui_hierarchy_xml: bytes
    ui_state_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not self.instance_name
            or not self.adb_serial
            or not self.captured_at
            or not self.format_id
            or not self.plan_id
            or not self.capture_store_id
            or not self.authorization_id
        ):
            raise ValueError("capture identity and timestamp are required")
        serial_match = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", self.adb_serial)
        if serial_match is None or int(serial_match.group(1)) > 65_535:
            raise ValueError("capture ADB serial must be a valid loopback endpoint")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.authorization_sha256) is None:
            raise ValueError("capture authorization hash is invalid")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.plan_hash) is None:
            raise ValueError("capture plan hash is invalid")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.lineage_receipt_sha256) is None:
            raise ValueError("capture lineage receipt hash is invalid")
        if re.fullmatch(
            r"https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*"
            r"#issuecomment-[1-9][0-9]*",
            self.plan_seal_comment_url,
        ) is None:
            raise ValueError("capture plan-seal comment URL is invalid")
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.plan_seal_receipt_sha256
        ) is None:
            raise ValueError("capture plan-seal receipt hash is invalid")
        if self.partition not in {"development", "holdout"}:
            raise ValueError("capture partition is invalid")
        if (
            len(self.target_package) > 240
            or _ANDROID_PACKAGE_RE.fullmatch(self.target_package) is None
        ):
            raise ValueError("capture target_package is invalid")
        if not isinstance(self.client_build, AndroidClientBuild):
            raise ValueError("capture client_build identity is invalid")
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.capture_store_identity_sha256
        ) is None:
            raise ValueError("capture store physical identity is invalid")
        completed = _capture_instant(self.captured_at, "captured_at")
        hierarchy_before_at = _capture_instant(
            self.ui_hierarchy_before_captured_at,
            "ui_hierarchy_before_captured_at",
        )
        screenshot_at = _capture_instant(
            self.screenshot_captured_at, "screenshot_captured_at"
        )
        hierarchy_at = _capture_instant(
            self.ui_hierarchy_captured_at, "ui_hierarchy_captured_at"
        )
        if not hierarchy_before_at <= screenshot_at <= hierarchy_at <= completed:
            raise ValueError("capture artifact timestamps are not ordered")
        if hierarchy_at - hierarchy_before_at > _MAX_ARTIFACT_SKEW:
            raise ValueError("capture artifacts exceed the maximum temporal skew")
        if self.adb_server_ownership_verified is not True:
            raise ValueError("capture requires externally verified ADB server ownership")
        _validate_png(self.screenshot_png)
        for payload in (self.ui_hierarchy_before_xml, self.ui_hierarchy_xml):
            if not payload.lstrip().startswith((b"<?xml", b"<hierarchy")):
                raise ValueError("UI hierarchy payload is not XML")
        before_state = _ui_state_identity(
            self.ui_hierarchy_before_xml, self.target_package
        )
        after_state = _ui_state_identity(self.ui_hierarchy_xml, self.target_package)
        if before_state != after_state:
            raise ValueError("UI hierarchy state changed around the screenshot")
        object.__setattr__(self, "ui_state_sha256", before_state)

def parse_bluestacks_config(text: str) -> tuple[BlueStacksInstance, ...]:
    """Extract only instance names and ADB ports from a BlueStacks config.

    The rest of the config may contain machine-specific or sensitive values and
    is intentionally neither parsed nor returned.
    """

    ports: dict[str, int] = {}
    for raw_line in text.splitlines():
        match = _ADB_PORT_RE.fullmatch(raw_line.strip())
        if match is None:
            continue
        port = int(match.group("port"))
        if 1 <= port <= 65_535:
            ports[match.group("name")] = port
    return tuple(
        BlueStacksInstance(name=name, adb_port=port)
        for name, port in sorted(ports.items())
    )


def _registry_installation() -> tuple[str | None, str | None]:
    try:
        import winreg
    except ImportError:
        return None, None

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\BlueStacks_nxt") as key:
            values: dict[str, str] = {}
            index = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                if isinstance(value, str):
                    values[name.lower()] = value
                index += 1
    except OSError:
        return None, None

    install_dir = values.get("installdir") or values.get("install_dir")
    version = (
        values.get("clientversion")
        or values.get("version")
        or values.get("productversion")
    )
    return install_dir, version


def _process_names() -> frozenset[str]:
    try:
        completed = subprocess.run(
            ("tasklist.exe", "/FO", "CSV", "/NH"),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    if completed.returncode != 0:
        return frozenset()
    names: set[str] = set()
    for row in csv.reader(io.StringIO(completed.stdout)):
        if row:
            names.add(row[0].casefold())
    return frozenset(names)


def _bluestacks_hd_adb_running(processes: frozenset[str]) -> bool:
    """Reject a generic Android adb process as BlueStacks daemon evidence."""

    return "hd-adb.exe" in processes


def discover_bluestacks() -> BlueStacksDiagnostics:
    """Return safe local diagnostics without launching a GUI or invoking ADB."""

    install_dir, version = _registry_installation()
    install_path = Path(install_dir) if install_dir else None
    adb = install_path / "HD-Adb.exe" if install_path else None
    config = Path(r"C:\ProgramData\BlueStacks_nxt\bluestacks.conf")
    instances: tuple[BlueStacksInstance, ...] = ()
    if config.is_file():
        try:
            instances = parse_bluestacks_config(config.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            instances = ()

    processes = _process_names()
    player_running = "hd-player.exe" in processes
    # A generic adb.exe may belong to an unrelated Android tool. Only the
    # BlueStacks-specific process name is accepted as supporting evidence.
    adb_running = _bluestacks_hd_adb_running(processes)
    blockers: list[str] = []
    if install_path is None:
        blockers.append("bluestacks_installation_not_found")
    if adb is None or not adb.is_file():
        blockers.append("bluestacks_adb_binary_not_found")
    if not instances:
        blockers.append("no_bluestacks_adb_instances_discovered")
    if not player_running:
        blockers.append("bluestacks_player_not_running")
    if not adb_running:
        blockers.append("existing_bluestacks_hd_adb_process_not_running")
    # Process-name/config checks cannot eliminate the race in which HD-Adb
    # exits and the next client invocation starts a replacement daemon.
    blockers.append("adb_external_side_effect_risk_not_mitigated")

    return BlueStacksDiagnostics(
        installed=install_path is not None,
        version=version,
        install_dir=str(install_path) if install_path is not None else None,
        adb_path=str(adb) if adb is not None and adb.is_file() else None,
        config_path=str(config) if config.is_file() else None,
        player_process_running=player_running,
        adb_process_running=adb_running,
        adb_server_ownership_verified=False,
        instances=instances,
        blockers=tuple(blockers),
    )


class AdbObservationCapture:
    """Allowlisted observation through an owned, already-running ADB server."""

    def __init__(
        self,
        diagnostics: BlueStacksDiagnostics,
        *,
        authorization: ValidatedObservationAuthorization | None = None,
        plan_seal: VerifiedGroundingPlanSeal | None = None,
        capture_store_id: str = "development-captures",
        capture_store_identity_sha256: str | None = None,
        format_id: str = "gen9championsbssregmb",
        issue_url: str = (
            "https://github.com/undo-not/pokemon-auto-battle-single/issues/3"
        ),
        ownership_probe: AdbOwnershipProbe | None = None,
        transport: AdbObservationTransport | None = None,
        adb_server_host: str = "127.0.0.1",
        adb_server_port: int = 5037,
        timeout_seconds: int = 15,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if adb_server_host != "127.0.0.1" or not 1 <= adb_server_port <= 65_535:
            raise ValueError("capture requires a valid IPv4 loopback ADB server")
        self._diagnostics = diagnostics
        self._authorization = authorization
        self._plan_seal = plan_seal
        self._capture_store_id = capture_store_id
        self._capture_store_identity_sha256 = capture_store_identity_sha256
        self._format_id = format_id
        self._issue_url = issue_url
        self._ownership_probe = ownership_probe or WindowsAdbOwnershipProbe()
        self._transport = transport or DirectAdbServerTransport()
        self._adb_server_host = adb_server_host
        self._adb_server_port = adb_server_port
        self._timeout_seconds = timeout_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def plan(self, instance_name: str) -> CapturePlan:
        instance = next(
            (item for item in self._diagnostics.instances if item.name == instance_name),
            None,
        )
        if instance is None:
            raise ExternalCaptureUnavailable(f"unknown BlueStacks instance: {instance_name}")
        if self._diagnostics.adb_path is None:
            raise ExternalCaptureUnavailable("BlueStacks HD-Adb binary is unavailable")
        return CapturePlan(
            instance_name=instance.name,
            adb_serial=instance.adb_serial,
            adb_server_host=self._adb_server_host,
            adb_server_port=self._adb_server_port,
            screenshot_service="exec:screencap -p",
            ui_hierarchy_service="exec:uiautomator dump /dev/tty",
            adb_client_process_invoked=False,
            adb_client_may_start_server=False,
        )

    def inspect_client_build(
        self,
        instance_name: str,
        target_package: str,
    ) -> AndroidClientBuild:
        """Explicitly resolve pre-seal client identity without capturing match UI."""

        plan = self.plan(instance_name)
        blockers = tuple(
            blocker
            for blocker in self._diagnostics.blockers
            if blocker != "adb_external_side_effect_risk_not_mitigated"
        )
        if (
            not self._diagnostics.installed
            or self._diagnostics.adb_path is None
            or not self._diagnostics.player_process_running
            or not self._diagnostics.adb_process_running
            or blockers
        ):
            detail = ", ".join(blockers) or "client-build inspection preflight failed"
            raise ExternalCaptureUnavailable(detail)
        expected_executable = Path(self._diagnostics.adb_path)
        try:
            server = self._ownership_probe.snapshot(
                host=plan.adb_server_host,
                port=plan.adb_server_port,
                expected_executable=expected_executable,
            )
            if (
                server.host != plan.adb_server_host
                or server.port != plan.adb_server_port
            ):
                raise AdbOwnershipError(
                    "ADB ownership probe returned a different server endpoint"
                )
            return self._observe_client_build(
                plan,
                server,
                expected_executable,
                target_package,
                require_authorization=False,
            )
        except (
            AdbOwnershipError,
            AdbProtocolError,
            AndroidClientIdentityError,
        ) as error:
            raise ExternalCaptureUnavailable(str(error)) from error

    def capture(self, instance_name: str) -> CapturePayload:
        plan = self.plan(instance_name)
        blockers = tuple(
            blocker
            for blocker in self._diagnostics.blockers
            if blocker != "adb_external_side_effect_risk_not_mitigated"
        )
        if (
            not self._diagnostics.installed
            or self._diagnostics.adb_path is None
            or not self._diagnostics.player_process_running
            or not self._diagnostics.adb_process_running
            or blockers
        ):
            detail = ", ".join(blockers) or "capture preflight failed"
            raise ExternalCaptureUnavailable(detail)
        if self._authorization is None:
            raise ExternalCaptureUnavailable("external observation authorization is required")
        if self._plan_seal is None:
            raise ExternalCaptureUnavailable("live GitHub grounding-plan seal is required")
        if self._capture_store_identity_sha256 is None:
            raise ExternalCaptureUnavailable(
                "external capture-store physical identity is required"
            )
        authorization_scope = self._authorization.authorization
        if (
            self._plan_seal.plan_id != authorization_scope.plan_id
            or self._plan_seal.plan_hash != authorization_scope.plan_hash
            or self._plan_seal.partition != authorization_scope.partition
            or self._plan_seal.issue_url != self._issue_url
            or self._plan_seal.comment_url
            != authorization_scope.plan_seal_comment_url
            or self._plan_seal.receipt_sha256
            != authorization_scope.plan_seal_receipt_sha256
            or self._capture_store_identity_sha256
            != authorization_scope.capture_store_identity_sha256
            or _capture_instant(authorization_scope.granted_at, "granted_at")
            < _capture_instant(self._plan_seal.created_at, "plan seal created_at")
        ):
            raise ExternalCaptureUnavailable(
                "observation authorization does not follow the live grounding-plan seal"
            )
        now = self._clock()
        try:
            self._authorization.assert_current(
                now=now,
                issue_url=self._issue_url,
                format_id=self._format_id,
                plan_id=self._authorization.authorization.plan_id,
                plan_hash=self._authorization.authorization.plan_hash,
                lineage_receipt_sha256=(
                    self._authorization.authorization.lineage_receipt_sha256
                ),
                plan_seal_comment_url=self._plan_seal.comment_url,
                plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
                partition=self._authorization.authorization.partition,
                instance_name=plan.instance_name,
                target_package=self._authorization.authorization.target_package,
                client_build=self._authorization.authorization.client_build,
                capture_store_id=self._capture_store_id,
                capture_store_identity_sha256=self._capture_store_identity_sha256,
            )
            expected_executable = Path(self._diagnostics.adb_path)
            server = self._ownership_probe.snapshot(
                host=plan.adb_server_host,
                port=plan.adb_server_port,
                expected_executable=expected_executable,
            )
            if (
                server.host != plan.adb_server_host
                or server.port != plan.adb_server_port
            ):
                raise AdbOwnershipError(
                    "ADB ownership probe returned a different server endpoint"
                )
            client_build_before = self._observe_client_build(
                plan,
                server,
                expected_executable,
                authorization_scope.target_package,
            )
            if client_build_before != authorization_scope.client_build:
                raise ExternalCaptureUnavailable(
                    "installed client build differs from the authorized identity"
                )
            ui_before_output = self._run_owned(
                plan.ui_hierarchy_service,
                plan,
                server,
                8 * 1024 * 1024,
            )
            ui_before_at = self._clock()
            self._require_same_owner(server, expected_executable)
            self._authorization.assert_current(
                now=ui_before_at,
                issue_url=self._issue_url,
                format_id=self._format_id,
                plan_id=self._authorization.authorization.plan_id,
                plan_hash=self._authorization.authorization.plan_hash,
                lineage_receipt_sha256=(
                    self._authorization.authorization.lineage_receipt_sha256
                ),
                plan_seal_comment_url=self._plan_seal.comment_url,
                plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
                partition=self._authorization.authorization.partition,
                instance_name=plan.instance_name,
                target_package=self._authorization.authorization.target_package,
                client_build=self._authorization.authorization.client_build,
                capture_store_id=self._capture_store_id,
                capture_store_identity_sha256=self._capture_store_identity_sha256,
            )
            screenshot = self._run_owned(
                plan.screenshot_service,
                plan,
                server,
                32 * 1024 * 1024,
            )
            screenshot_at = self._clock()
            self._require_same_owner(server, expected_executable)
            self._authorization.assert_current(
                now=screenshot_at,
                issue_url=self._issue_url,
                format_id=self._format_id,
                plan_id=self._authorization.authorization.plan_id,
                plan_hash=self._authorization.authorization.plan_hash,
                lineage_receipt_sha256=(
                    self._authorization.authorization.lineage_receipt_sha256
                ),
                plan_seal_comment_url=self._plan_seal.comment_url,
                plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
                partition=self._authorization.authorization.partition,
                instance_name=plan.instance_name,
                target_package=self._authorization.authorization.target_package,
                client_build=self._authorization.authorization.client_build,
                capture_store_id=self._capture_store_id,
                capture_store_identity_sha256=self._capture_store_identity_sha256,
            )
            ui_output = self._run_owned(
                plan.ui_hierarchy_service,
                plan,
                server,
                8 * 1024 * 1024,
            )
            ui_hierarchy_at = self._clock()
            self._require_same_owner(server, expected_executable)
            client_build_after = self._observe_client_build(
                plan,
                server,
                expected_executable,
                authorization_scope.target_package,
            )
            if client_build_after != client_build_before:
                raise ExternalCaptureUnavailable(
                    "installed client build changed during capture"
                )
            completed_at = self._clock()
            self._authorization.assert_current(
                now=completed_at,
                issue_url=self._issue_url,
                format_id=self._format_id,
                plan_id=self._authorization.authorization.plan_id,
                plan_hash=self._authorization.authorization.plan_hash,
                lineage_receipt_sha256=(
                    self._authorization.authorization.lineage_receipt_sha256
                ),
                plan_seal_comment_url=self._plan_seal.comment_url,
                plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
                partition=self._authorization.authorization.partition,
                instance_name=plan.instance_name,
                target_package=self._authorization.authorization.target_package,
                client_build=self._authorization.authorization.client_build,
                capture_store_id=self._capture_store_id,
                capture_store_identity_sha256=self._capture_store_identity_sha256,
            )
        except (
            AdbOwnershipError,
            AdbProtocolError,
            AndroidClientIdentityError,
            ObservationAuthorizationError,
        ) as error:
            raise ExternalCaptureUnavailable(str(error)) from error
        try:
            _validate_png(screenshot)
        except ValueError as error:
            raise ExternalCaptureUnavailable(str(error)) from error
        before_xml = _extract_xml(
            ui_before_output,
            target_package=self._authorization.authorization.target_package,
        )
        xml = _extract_xml(
            ui_output,
            target_package=self._authorization.authorization.target_package,
        )
        return CapturePayload(
            instance_name=plan.instance_name,
            adb_serial=plan.adb_serial,
            captured_at=_utc_text(completed_at),
            ui_hierarchy_before_captured_at=_utc_text(ui_before_at),
            screenshot_captured_at=_utc_text(screenshot_at),
            ui_hierarchy_captured_at=_utc_text(ui_hierarchy_at),
            format_id=self._format_id,
            plan_id=self._authorization.authorization.plan_id,
            plan_hash=self._authorization.authorization.plan_hash,
            lineage_receipt_sha256=(
                self._authorization.authorization.lineage_receipt_sha256
            ),
            plan_seal_comment_url=self._plan_seal.comment_url,
            plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
            partition=self._authorization.authorization.partition,
            target_package=self._authorization.authorization.target_package,
            client_build=client_build_before,
            capture_store_id=self._capture_store_id,
            capture_store_identity_sha256=self._capture_store_identity_sha256,
            authorization_id=self._authorization.authorization.authorization_id,
            authorization_sha256=self._authorization.authorization_hash,
            adb_server_ownership_verified=True,
            adb_server=server,
            screenshot_png=screenshot,
            ui_hierarchy_before_xml=before_xml,
            ui_hierarchy_xml=xml,
        )

    def _run_owned(
        self,
        service: str,
        plan: CapturePlan,
        server: AdbServerIdentity,
        max_bytes: int,
    ) -> bytes:
        allowed = {plan.screenshot_service, plan.ui_hierarchy_service}
        if service not in allowed and not is_read_only_client_identity_service(service):
            raise RuntimeError("refusing non-allowlisted ADB service")
        return self._transport.execute(
            server=server,
            serial=plan.adb_serial,
            service=service,
            timeout_seconds=self._timeout_seconds,
            max_bytes=max_bytes,
            pre_send_check=lambda client_host, client_port, peer_host, peer_port: (
                self._require_owned_connection(
                    server,
                    Path(self._diagnostics.adb_path or ""),
                    client_host=client_host,
                    client_port=client_port,
                    peer_host=peer_host,
                    peer_port=peer_port,
                )
            ),
        )

    def _observe_client_build(
        self,
        plan: CapturePlan,
        server: AdbServerIdentity,
        expected_executable: Path,
        target_package: str,
        *,
        require_authorization: bool = True,
    ) -> AndroidClientBuild:
        def execute(service: str, max_bytes: int) -> bytes:
            if require_authorization:
                assert self._authorization is not None
                assert self._plan_seal is not None
                assert self._capture_store_identity_sha256 is not None
                self._authorization.assert_current(
                    now=self._clock(),
                    issue_url=self._issue_url,
                    format_id=self._format_id,
                    plan_id=self._authorization.authorization.plan_id,
                    plan_hash=self._authorization.authorization.plan_hash,
                    lineage_receipt_sha256=(
                        self._authorization.authorization.lineage_receipt_sha256
                    ),
                    plan_seal_comment_url=self._plan_seal.comment_url,
                    plan_seal_receipt_sha256=self._plan_seal.receipt_sha256,
                    partition=self._authorization.authorization.partition,
                    instance_name=plan.instance_name,
                    target_package=(
                        self._authorization.authorization.target_package
                    ),
                    client_build=self._authorization.authorization.client_build,
                    capture_store_id=self._capture_store_id,
                    capture_store_identity_sha256=(
                        self._capture_store_identity_sha256
                    ),
                )
            payload = self._run_owned(service, plan, server, max_bytes)
            self._require_same_owner(server, expected_executable)
            return payload

        return observe_android_client_build(target_package, execute)

    def _require_owned_connection(
        self,
        expected: AdbServerIdentity,
        expected_executable: Path,
        *,
        client_host: str,
        client_port: int,
        peer_host: str,
        peer_port: int,
    ) -> None:
        if peer_host != expected.host or peer_port != expected.port:
            raise AdbOwnershipError("ADB connection peer differs from the owned server")
        observed = self._ownership_probe.snapshot_connection(
            server_host=peer_host,
            server_port=peer_port,
            client_host=client_host,
            client_port=client_port,
            expected_executable=expected_executable,
        )
        if observed != expected:
            raise AdbOwnershipError(
                "accepted ADB connection is not owned by the verified server"
            )

    def _require_same_owner(
        self,
        expected: AdbServerIdentity,
        expected_executable: Path,
    ) -> None:
        observed = self._ownership_probe.snapshot(
            host=expected.host,
            port=expected.port,
            expected_executable=expected_executable,
        )
        if observed != expected:
            raise AdbOwnershipError("ADB server ownership changed during capture")


def _extract_xml(payload: bytes, *, target_package: str) -> bytes:
    starts = [
        index
        for marker in (b"<?xml", b"<hierarchy")
        if (index := payload.find(marker)) >= 0
    ]
    if not starts:
        raise ExternalCaptureUnavailable("ADB UI hierarchy output did not contain XML")
    xml = payload[min(starts) :].strip()
    if b"</hierarchy>" in xml:
        xml = xml[: xml.rfind(b"</hierarchy>") + len(b"</hierarchy>")]
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as error:
        raise ExternalCaptureUnavailable("ADB UI hierarchy output was malformed XML") from error
    if root.tag != "hierarchy":
        raise ExternalCaptureUnavailable("ADB UI hierarchy root was not hierarchy")
    try:
        _ui_state_identity(xml, target_package)
    except ValueError as error:
        raise ExternalCaptureUnavailable(str(error)) from error
    return xml


def _capture_instant(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExternalCaptureUnavailable("capture clock returned a naive timestamp")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _require_target_package(payload: bytes, target_package: str) -> None:
    _ui_state_identity(payload, target_package)


def _ui_state_identity(payload: bytes, target_package: str) -> str:
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise ValueError("UI hierarchy payload is malformed XML") from error
    if root.tag != "hierarchy":
        raise ValueError("UI hierarchy root is invalid")
    top_level = list(root)
    if not top_level or top_level[0].attrib.get("package") != target_package:
        raise ValueError(
            "UI hierarchy does not show the authorized package in the foreground"
        )
    target_nodes = [
        node for node in root.iter("node") if node.attrib.get("package") == target_package
    ]
    if not target_nodes:
        raise ValueError("UI hierarchy does not bind the authorized target package")
    projection = [
        {key: value for key, value in sorted(node.attrib.items())}
        for node in target_nodes
    ]
    return "sha256:" + canonical_hash(
        {"target_package": target_package, "nodes": projection}
    )
