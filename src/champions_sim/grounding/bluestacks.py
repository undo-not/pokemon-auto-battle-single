"""BlueStacks discovery and fail-closed observation capture boundary.

Discovery never invokes ADB. An ADB client can start a daemon if the daemon
exits between preflight and invocation, so discovery never marks server
ownership verified. Capture remains blocked until a future external supervisor
can make and maintain that guarantee.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from champions_sim.core import to_canonical_data


_ADB_PORT_RE = re.compile(
    r'^bst\.instance\.(?P<name>[A-Za-z0-9_-]+)\.(?:status\.)?adb_port='
    r'"?(?P<port>[0-9]{1,5})"?\s*$'
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


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
    screenshot_command: tuple[str, ...]
    ui_hierarchy_command: tuple[str, ...]
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
    adb_server_ownership_verified: bool
    screenshot_png: bytes
    ui_hierarchy_xml: bytes

    def __post_init__(self) -> None:
        if not self.instance_name or not self.adb_serial or not self.captured_at:
            raise ValueError("capture identity and timestamp are required")
        if self.adb_server_ownership_verified is not True:
            raise ValueError("capture requires externally verified ADB server ownership")
        if not self.screenshot_png.startswith(_PNG_SIGNATURE):
            raise ValueError("screenshot payload is not a PNG")
        if not self.ui_hierarchy_xml.lstrip().startswith((b"<?xml", b"<hierarchy")):
            raise ValueError("UI hierarchy payload is not XML")


@dataclass(frozen=True, slots=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(self, command: tuple[str, ...], *, timeout_seconds: int) -> CommandResult:
        """Run one exact, already allowlisted command."""


class SubprocessRunner:
    """No-shell runner used only after externally managed ADB preflight passes."""

    def run(self, command: tuple[str, ...], *, timeout_seconds: int) -> CommandResult:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            shell=False,
            timeout=timeout_seconds,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


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
    """Allowlisted observation capture requiring externally managed ADB ownership."""

    def __init__(
        self,
        diagnostics: BlueStacksDiagnostics,
        runner: CommandRunner | None = None,
        *,
        timeout_seconds: int = 15,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._diagnostics = diagnostics
        self._runner = runner or SubprocessRunner()
        self._timeout_seconds = timeout_seconds

    def plan(self, instance_name: str) -> CapturePlan:
        instance = next(
            (item for item in self._diagnostics.instances if item.name == instance_name),
            None,
        )
        if instance is None:
            raise ExternalCaptureUnavailable(f"unknown BlueStacks instance: {instance_name}")
        if self._diagnostics.adb_path is None:
            raise ExternalCaptureUnavailable("BlueStacks HD-Adb binary is unavailable")
        prefix = (self._diagnostics.adb_path, "-s", instance.adb_serial, "exec-out")
        return CapturePlan(
            instance_name=instance.name,
            adb_serial=instance.adb_serial,
            screenshot_command=prefix + ("screencap", "-p"),
            ui_hierarchy_command=prefix
            + ("uiautomator", "dump", "/dev/tty"),
            adb_client_may_start_server=True,
        )

    def capture(self, instance_name: str) -> CapturePayload:
        plan = self.plan(instance_name)
        if not self._diagnostics.capture_ready:
            detail = ", ".join(self._diagnostics.blockers) or "capture preflight failed"
            raise ExternalCaptureUnavailable(detail)

        screenshot = self._run_exact(plan.screenshot_command, plan)
        if not screenshot.startswith(_PNG_SIGNATURE):
            raise ExternalCaptureUnavailable("ADB screenshot output did not contain a PNG")
        ui_output = self._run_exact(plan.ui_hierarchy_command, plan)
        xml = _extract_xml(ui_output)
        return CapturePayload(
            instance_name=plan.instance_name,
            adb_serial=plan.adb_serial,
            captured_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            adb_server_ownership_verified=True,
            screenshot_png=screenshot,
            ui_hierarchy_xml=xml,
        )

    def _run_exact(self, command: tuple[str, ...], plan: CapturePlan) -> bytes:
        allowed = {plan.screenshot_command, plan.ui_hierarchy_command}
        if command not in allowed:
            raise RuntimeError("refusing non-allowlisted ADB command")
        result = self._runner.run(command, timeout_seconds=self._timeout_seconds)
        if result.command != command:
            raise RuntimeError("command runner returned a mismatched command identity")
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise ExternalCaptureUnavailable(
                f"read-only ADB command failed with {result.returncode}: {stderr[:240]}"
            )
        return result.stdout


def _extract_xml(payload: bytes) -> bytes:
    starts = [index for marker in (b"<?xml", b"<hierarchy") if (index := payload.find(marker)) >= 0]
    if not starts:
        raise ExternalCaptureUnavailable("ADB UI hierarchy output did not contain XML")
    xml = payload[min(starts) :].strip()
    if b"</hierarchy>" in xml:
        xml = xml[: xml.rfind(b"</hierarchy>") + len(b"</hierarchy>")]
    return xml
