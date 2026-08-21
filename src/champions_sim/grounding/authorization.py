"""Strict external authorization for read-only private-match observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core import to_canonical_data

from .android_client import AndroidClientBuild


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ANDROID_PACKAGE_RE = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
_ISSUE_URL_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*$")
_COMMENT_URL_RE = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*"
    r"#issuecomment-[1-9][0-9]*$"
)
_ALLOWED_ACTIONS = ("client_identity", "screenshot", "ui_hierarchy")
_MAX_AUTHORIZATION_LIFETIME = timedelta(hours=8)
_MAX_AUTHORIZATION_BYTES = 64 * 1024
_AUTHORIZATION_KEYS = {
    "schema_version",
    "authorization_id",
    "issue_url",
    "granted_by",
    "granted_at",
    "expires_at",
    "format_id",
    "plan_id",
    "plan_hash",
    "lineage_receipt_sha256",
    "plan_seal_comment_url",
    "plan_seal_receipt_sha256",
    "partition",
    "instance_name",
    "target_package",
    "client_build",
    "capture_store_id",
    "capture_store_identity_sha256",
    "allowed_actions",
    "game_scope",
    "ranked_match_allowed",
    "input_automation_allowed",
}


class ObservationAuthorizationError(ValueError):
    """Raised when an external observation authorization is unusable."""


def _parse_utc(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ObservationAuthorizationError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ObservationAuthorizationError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _stable_id(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 240
        or _STABLE_ID_RE.fullmatch(value) is None
    ):
        raise ObservationAuthorizationError(f"{field_name} must be a stable ID")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ObservationAuthorizationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ObservationAuthorizationError(f"non-finite JSON value is not allowed: {value}")


def _reject_non_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ObservationAuthorizationError("non-finite JSON value is not allowed")
    if isinstance(value, list):
        for item in value:
            _reject_non_finite(item)
    elif isinstance(value, Mapping):
        for item in value.values():
            _reject_non_finite(item)


def _outside_repository(path: Path, field_name: str) -> Path:
    if not path.is_absolute():
        raise ObservationAuthorizationError(f"{field_name} must be an absolute path")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(_REPOSITORY_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise ObservationAuthorizationError(f"{field_name} must stay outside the repository")


@dataclass(frozen=True, slots=True)
class ObservationAuthorization:
    """Operator assertion scoped to client identity and two capture actions."""

    schema_version: str
    authorization_id: str
    issue_url: str
    granted_by: str
    granted_at: str
    expires_at: str
    format_id: str
    plan_id: str
    plan_hash: str
    lineage_receipt_sha256: str
    plan_seal_comment_url: str
    plan_seal_receipt_sha256: str
    partition: str
    instance_name: str
    target_package: str
    client_build: AndroidClientBuild
    capture_store_id: str
    capture_store_identity_sha256: str
    allowed_actions: tuple[str, ...]
    game_scope: str
    ranked_match_allowed: bool
    input_automation_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ObservationAuthorizationError(
                "only observation authorization schema 1.0.0 is supported"
            )
        _stable_id(self.authorization_id, "authorization_id")
        if _ISSUE_URL_RE.fullmatch(self.issue_url) is None:
            raise ObservationAuthorizationError("issue_url must identify a GitHub Issue")
        if not self.granted_by or len(self.granted_by) > 240 or any(
            ord(character) < 32 or ord(character) == 127 for character in self.granted_by
        ):
            raise ObservationAuthorizationError("granted_by must be a non-empty safe string")
        granted_at = _parse_utc(self.granted_at, "granted_at")
        expires_at = _parse_utc(self.expires_at, "expires_at")
        if expires_at <= granted_at:
            raise ObservationAuthorizationError("expires_at must be after granted_at")
        if expires_at - granted_at > _MAX_AUTHORIZATION_LIFETIME:
            raise ObservationAuthorizationError(
                "observation authorization lifetime must not exceed eight hours"
            )
        _stable_id(self.format_id, "format_id")
        _stable_id(self.plan_id, "plan_id")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.plan_hash) is None:
            raise ObservationAuthorizationError("plan_hash must be a SHA-256 identity")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.lineage_receipt_sha256) is None:
            raise ObservationAuthorizationError(
                "lineage_receipt_sha256 must be a SHA-256 identity"
            )
        if _COMMENT_URL_RE.fullmatch(self.plan_seal_comment_url) is None:
            raise ObservationAuthorizationError(
                "plan_seal_comment_url must identify a GitHub Issue comment"
            )
        if not self.plan_seal_comment_url.startswith(self.issue_url + "#"):
            raise ObservationAuthorizationError(
                "plan seal comment must belong to the authorization Issue"
            )
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.plan_seal_receipt_sha256
        ) is None:
            raise ObservationAuthorizationError(
                "plan_seal_receipt_sha256 must be a SHA-256 identity"
            )
        if self.partition not in {"development", "holdout"}:
            raise ObservationAuthorizationError("authorization partition is invalid")
        _stable_id(self.instance_name, "instance_name")
        if (
            len(self.target_package) > 240
            or _ANDROID_PACKAGE_RE.fullmatch(self.target_package) is None
        ):
            raise ObservationAuthorizationError(
                "target_package must be a fully qualified Android package"
            )
        if not isinstance(self.client_build, AndroidClientBuild):
            raise ObservationAuthorizationError(
                "client_build must be an exact Android client identity"
            )
        _stable_id(self.capture_store_id, "capture_store_id")
        if re.fullmatch(
            r"sha256:[0-9a-f]{64}", self.capture_store_identity_sha256
        ) is None:
            raise ObservationAuthorizationError(
                "capture_store_identity_sha256 must be a SHA-256 identity"
            )
        if self.allowed_actions != _ALLOWED_ACTIONS:
            raise ObservationAuthorizationError(
                "allowed_actions must be the canonical client-identity/capture set"
            )
        if self.game_scope != "private_friend_match":
            raise ObservationAuthorizationError(
                "observation authorization is limited to private friend matches"
            )
        if self.ranked_match_allowed is not False:
            raise ObservationAuthorizationError("ranked-match observation is not authorized")
        if self.input_automation_allowed is not False:
            raise ObservationAuthorizationError("input automation is not authorized")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


_VALIDATION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ValidatedObservationAuthorization:
    authorization: ObservationAuthorization
    authorization_hash: str
    source_path: Path

    def __init__(
        self,
        authorization: ObservationAuthorization,
        authorization_hash: str,
        source_path: Path,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _VALIDATION_TOKEN:
            raise ObservationAuthorizationError(
                "validated authorization must be created by the external resolver"
            )
        object.__setattr__(self, "authorization", authorization)
        object.__setattr__(self, "authorization_hash", authorization_hash)
        object.__setattr__(self, "source_path", source_path)

    def assert_current(
        self,
        *,
        now: datetime,
        issue_url: str,
        format_id: str,
        plan_id: str,
        plan_hash: str,
        lineage_receipt_sha256: str,
        plan_seal_comment_url: str,
        plan_seal_receipt_sha256: str,
        partition: str,
        instance_name: str,
        target_package: str,
        client_build: AndroidClientBuild,
        capture_store_id: str,
        capture_store_identity_sha256: str,
    ) -> None:
        observed, observed_hash = _read_authorization(self.source_path)
        if observed != self.authorization or observed_hash != self.authorization_hash:
            raise ObservationAuthorizationError(
                "observation authorization source was replaced or modified"
            )
        if now.tzinfo is None or now.utcoffset() is None:
            raise ObservationAuthorizationError("current time must include a timezone")
        current = now.astimezone(timezone.utc)
        granted = _parse_utc(self.authorization.granted_at, "granted_at")
        expires = _parse_utc(self.authorization.expires_at, "expires_at")
        if current < granted or current >= expires:
            raise ObservationAuthorizationError("observation authorization is not current")
        expected = {
            "issue_url": issue_url,
            "format_id": format_id,
            "plan_id": plan_id,
            "plan_hash": plan_hash,
            "lineage_receipt_sha256": lineage_receipt_sha256,
            "plan_seal_comment_url": plan_seal_comment_url,
            "plan_seal_receipt_sha256": plan_seal_receipt_sha256,
            "partition": partition,
            "instance_name": instance_name,
            "target_package": target_package,
            "client_build": client_build,
            "capture_store_id": capture_store_id,
            "capture_store_identity_sha256": capture_store_identity_sha256,
        }
        for field_name, value in expected.items():
            if getattr(self.authorization, field_name) != value:
                raise ObservationAuthorizationError(
                    f"observation authorization {field_name} does not match"
                )


def load_observation_authorization(
    path: Path | str,
    *,
    now: datetime,
    issue_url: str,
    format_id: str,
    plan_id: str,
    plan_hash: str,
    lineage_receipt_sha256: str,
    plan_seal_comment_url: str,
    plan_seal_receipt_sha256: str,
    partition: str,
    instance_name: str,
    target_package: str,
    client_build: AndroidClientBuild,
    capture_store_id: str,
    capture_store_identity_sha256: str,
) -> ValidatedObservationAuthorization:
    """Resolve a scoped authorization from an absolute path outside the repository."""

    source_path = _outside_repository(Path(path), "authorization path")
    authorization, authorization_hash = _read_authorization(source_path)
    validated = ValidatedObservationAuthorization(
        authorization=authorization,
        authorization_hash=authorization_hash,
        source_path=source_path,
        _token=_VALIDATION_TOKEN,
    )
    validated.assert_current(
        now=now,
        issue_url=issue_url,
        format_id=format_id,
        plan_id=plan_id,
        plan_hash=plan_hash,
        lineage_receipt_sha256=lineage_receipt_sha256,
        plan_seal_comment_url=plan_seal_comment_url,
        plan_seal_receipt_sha256=plan_seal_receipt_sha256,
        partition=partition,
        instance_name=instance_name,
        target_package=target_package,
        client_build=client_build,
        capture_store_id=capture_store_id,
        capture_store_identity_sha256=capture_store_identity_sha256,
    )
    return validated


def _read_authorization(source_path: Path) -> tuple[ObservationAuthorization, str]:
    source_path = _outside_repository(source_path, "authorization path")
    try:
        if source_path.stat().st_size > _MAX_AUTHORIZATION_BYTES:
            raise ObservationAuthorizationError(
                "observation authorization exceeds the configured limit"
            )
        payload = source_path.read_bytes()
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ObservationAuthorizationError(
            f"cannot read observation authorization: {error}"
        ) from error
    _reject_non_finite(raw)
    if not isinstance(raw, Mapping) or set(raw) != _AUTHORIZATION_KEYS:
        raise ObservationAuthorizationError(
            "observation authorization has missing or unexpected fields"
        )
    actions = raw["allowed_actions"]
    if not isinstance(actions, list) or not all(isinstance(item, str) for item in actions):
        raise ObservationAuthorizationError("allowed_actions must be an array of strings")
    for field_name in (
        "schema_version",
        "authorization_id",
        "issue_url",
        "granted_by",
        "granted_at",
        "expires_at",
        "format_id",
        "plan_id",
        "plan_hash",
        "lineage_receipt_sha256",
        "plan_seal_comment_url",
        "plan_seal_receipt_sha256",
        "partition",
        "instance_name",
        "target_package",
        "capture_store_id",
        "capture_store_identity_sha256",
        "game_scope",
    ):
        if not isinstance(raw[field_name], str):
            raise ObservationAuthorizationError(f"{field_name} must be a string")
    client_build_raw = raw["client_build"]
    if not isinstance(client_build_raw, Mapping) or set(client_build_raw) != {
        "version_code",
        "version_name",
        "apk_count",
        "apk_set_sha256",
    }:
        raise ObservationAuthorizationError("client_build is invalid")
    if not all(
        isinstance(client_build_raw[field], int)
        and not isinstance(client_build_raw[field], bool)
        for field in ("version_code", "apk_count")
    ) or not all(
        isinstance(client_build_raw[field], str)
        for field in ("version_name", "apk_set_sha256")
    ):
        raise ObservationAuthorizationError("client_build values are invalid")
    for field_name in ("ranked_match_allowed", "input_automation_allowed"):
        if not isinstance(raw[field_name], bool):
            raise ObservationAuthorizationError(f"{field_name} must be a boolean")

    authorization = ObservationAuthorization(
        schema_version=raw["schema_version"],
        authorization_id=raw["authorization_id"],
        issue_url=raw["issue_url"],
        granted_by=raw["granted_by"],
        granted_at=raw["granted_at"],
        expires_at=raw["expires_at"],
        format_id=raw["format_id"],
        plan_id=raw["plan_id"],
        plan_hash=raw["plan_hash"],
        lineage_receipt_sha256=raw["lineage_receipt_sha256"],
        plan_seal_comment_url=raw["plan_seal_comment_url"],
        plan_seal_receipt_sha256=raw["plan_seal_receipt_sha256"],
        partition=raw["partition"],
        instance_name=raw["instance_name"],
        target_package=raw["target_package"],
        client_build=AndroidClientBuild(
            version_code=client_build_raw["version_code"],
            version_name=client_build_raw["version_name"],
            apk_count=client_build_raw["apk_count"],
            apk_set_sha256=client_build_raw["apk_set_sha256"],
        ),
        capture_store_id=raw["capture_store_id"],
        capture_store_identity_sha256=raw["capture_store_identity_sha256"],
        allowed_actions=tuple(actions),
        game_scope=raw["game_scope"],
        ranked_match_allowed=raw["ranked_match_allowed"],
        input_automation_allowed=raw["input_automation_allowed"],
    )
    return authorization, "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "ObservationAuthorization",
    "ObservationAuthorizationError",
    "ValidatedObservationAuthorization",
    "load_observation_authorization",
]
