"""Persistent, strict JSON-lines process transport for the Node bridge."""

from __future__ import annotations

import hashlib
import json
import math
import queue
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core.canonical import canonical_json

from .resolver import ResolvedShowdown, sanitized_node_environment


PROTOCOL_VERSION = "1.0.0"
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
SESSION_CAPACITY = 64


class ShowdownProcessError(RuntimeError):
    """The bridge process could not be started or communicated with safely."""


class ShowdownBridgeError(ShowdownProcessError):
    """The bridge rejected a request using a stable error code."""

    def __init__(self, code: str, message: str, details: object | None = None) -> None:
        self.code = code
        self.details = details
        super().__init__(f"{code}: {message}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ShowdownProcessError(f"bridge returned duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_float(value: str) -> None:
    raise ShowdownProcessError(f"bridge returned a floating-point value: {value}")


def _reject_constant(value: str) -> None:
    raise ShowdownProcessError(f"bridge returned a non-finite value: {value}")


def _strict_loads(text: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_pairs,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except json.JSONDecodeError as error:
        raise ShowdownProcessError(f"bridge returned invalid JSON: {error}") from error


def _response_result(line: str, request_id: int) -> Mapping[str, Any]:
    response = _strict_loads(line)
    if not isinstance(response, dict):
        raise ShowdownProcessError("bridge response must be an object")
    expected = {"protocol_version", "request_id", "ok"}
    if response.get("ok") is True:
        expected.add("result")
    elif response.get("ok") is False:
        expected.add("error")
    else:
        raise ShowdownProcessError("bridge response has invalid ok field")
    if set(response) != expected:
        raise ShowdownProcessError("bridge response fields violate the protocol")
    response_id = response["request_id"]
    if (
        response["protocol_version"] != PROTOCOL_VERSION
        or not isinstance(response_id, int)
        or isinstance(response_id, bool)
        or response_id != request_id
    ):
        raise ShowdownProcessError("bridge response identity mismatch")
    if response["ok"]:
        result = response["result"]
        if not isinstance(result, dict):
            raise ShowdownProcessError("bridge result must be an object")
        return result
    error_payload = response["error"]
    if not isinstance(error_payload, dict):
        raise ShowdownProcessError("bridge error must be an object")
    if set(error_payload) not in (
        {"code", "message"},
        {"code", "message", "details"},
    ):
        raise ShowdownProcessError("bridge error fields violate the protocol")
    code = error_payload.get("code")
    message = error_payload.get("message")
    if not isinstance(code, str) or not code or not isinstance(message, str) or not message:
        raise ShowdownProcessError("bridge error fields are invalid")
    raise ShowdownBridgeError(code, message, error_payload.get("details"))


class ShowdownProcess:
    """One persistent Node process serving multiple independent battle sessions."""

    def __init__(self, resolved: ResolvedShowdown, *, timeout_seconds: float = 15.0) -> None:
        if (
            not isinstance(timeout_seconds, (int, float))
            or isinstance(timeout_seconds, bool)
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        self.resolved = resolved
        self.timeout_seconds = float(timeout_seconds)
        self._next_request_id = 0
        self._responses: queue.Queue[str | BaseException | None] = queue.Queue()
        self._stderr: deque[str] = deque(maxlen=100)
        self._lock = threading.Lock()
        bridge = Path(__file__).resolve().parents[3] / "bridge" / "showdown-bridge.cjs"
        if not bridge.is_file():
            raise ShowdownProcessError(f"Showdown bridge is missing: {bridge}")
        try:
            normalized_bridge = (
                bridge.read_text(encoding="utf-8")
                .replace("\r\n", "\n")
                .replace("\r", "\n")
            )
        except (OSError, UnicodeError) as error:
            raise ShowdownProcessError(f"cannot read Showdown bridge: {error}") from error
        self.bridge_sha256 = hashlib.sha256(normalized_bridge.encode("utf-8")).hexdigest()
        try:
            self._process = subprocess.Popen(
                [
                    str(resolved.node_executable),
                    str(bridge),
                    str(resolved.root),
                    ",".join(sorted(item.id for item in resolved.manifest.formats)),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=resolved.root,
                env=sanitized_node_environment(),
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
            )
        except OSError as error:
            raise ShowdownProcessError(f"cannot start Showdown bridge: {error}") from error
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        try:
            hello = self.request("hello", {})
            if set(hello) != {
                "protocol_version",
                "bridge_sha256",
                "node_version",
                "showdown_root",
                "allowed_format_ids",
                "session_capacity",
            }:
                raise ShowdownProcessError("bridge hello fields violate the protocol")
            if hello.get("protocol_version") != PROTOCOL_VERSION:
                raise ShowdownProcessError("bridge hello protocol mismatch")
            if hello.get("bridge_sha256") != self.bridge_sha256:
                raise ShowdownProcessError("bridge source identity mismatch")
            if Path(str(hello.get("showdown_root"))).resolve() != resolved.root:
                raise ShowdownProcessError("bridge loaded a different Showdown root")
            if hello.get("node_version") != resolved.node_version:
                raise ShowdownProcessError("bridge Node version mismatch")
            if hello.get("allowed_format_ids") != sorted(
                item.id for item in resolved.manifest.formats
            ):
                raise ShowdownProcessError("bridge format allowlist mismatch")
            if hello.get("session_capacity") != SESSION_CAPACITY or isinstance(
                hello.get("session_capacity"), bool
            ):
                raise ShowdownProcessError("bridge session capacity is invalid")
        except BaseException:
            self.close()
            raise

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                if len(line.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    self._responses.put(ShowdownProcessError("bridge response exceeds 64 MiB"))
                    return
                self._responses.put(line.rstrip("\r\n"))
        except BaseException as error:  # transport failures must reach the waiting caller
            self._responses.put(error)
        finally:
            self._responses.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        try:
            for line in self._process.stderr:
                self._stderr.append(line.rstrip("\r\n"))
        except (OSError, UnicodeError):
            return

    def request(self, method: str, params: Mapping[str, object]) -> Mapping[str, Any]:
        with self._lock:
            if self._process.poll() is not None:
                raise ShowdownProcessError(self._exit_message("bridge is not running"))
            request_id = self._next_request_id
            self._next_request_id += 1
            envelope = {
                "protocol_version": PROTOCOL_VERSION,
                "request_id": request_id,
                "method": method,
                "params": params,
            }
            payload = canonical_json(envelope)
            if len(payload.encode("utf-8")) > 1024 * 1024:
                raise ShowdownProcessError("bridge request exceeds 1 MiB")
            assert self._process.stdin is not None
            try:
                self._process.stdin.write(payload + "\n")
                self._process.stdin.flush()
            except (OSError, UnicodeError) as error:
                raise ShowdownProcessError(self._exit_message(f"cannot write to bridge: {error}")) from error
            try:
                line = self._responses.get(timeout=self.timeout_seconds)
            except queue.Empty as error:
                message = self._exit_message(
                    f"bridge timed out after {self.timeout_seconds:g}s"
                )
                self.close()
                raise ShowdownProcessError(message) from error
            try:
                if line is None:
                    raise ShowdownProcessError(
                        self._exit_message("bridge closed stdout")
                    )
                if isinstance(line, BaseException):
                    raise ShowdownProcessError(
                        self._exit_message(f"cannot read bridge output: {line}")
                    ) from line
                return _response_result(line, request_id)
            except ShowdownBridgeError:
                raise
            except BaseException:
                self.close()
                raise

    def _exit_message(self, prefix: str) -> str:
        stderr = " | ".join(self._stderr)
        status = self._process.poll()
        suffix = f"; exit={status}" if status is not None else ""
        if stderr:
            suffix += f"; stderr={stderr}"
        return prefix + suffix

    def close(self) -> None:
        process = getattr(self, "_process", None)
        if process is None or process.poll() is not None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def __enter__(self) -> "ShowdownProcess":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()
