"""Content-addressed external provenance for development and holdout evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core import canonical_json, to_canonical_data


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ISSUE_URL_RE = re.compile(r"^https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*$")
_MAX_LINEAGE_BYTES = 2 * 1024 * 1024
_LINEAGE_KEYS = {
    "schema_version",
    "lineage_id",
    "issue_url",
    "regulation_id",
    "format_id",
    "partition",
    "capture_store_id",
    "capture_store_identity_sha256",
    "source_artifact_sha256",
    "source_store_identity_sha256",
    "collected_at",
    "collection_method",
    "collector_id",
    "author_id",
    "executor_id",
    "independence_attested",
    "local_research_only",
    "distribution_allowed",
}


class GroundingLineageError(ValueError):
    """Raised for unresolved, noncanonical, or overlapping lineage evidence."""


def _stable_id(value: Any, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 240
        or _STABLE_ID_RE.fullmatch(value) is None
    ):
        raise GroundingLineageError(f"{field_name} must be a stable ID")
    return value


def _sha256(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise GroundingLineageError(f"{field_name} must be a SHA-256 identity")
    return value


def _instant(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise GroundingLineageError(f"{field_name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GroundingLineageError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroundingLineageError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class GroundingLineageReceipt:
    schema_version: str
    lineage_id: str
    issue_url: str
    regulation_id: str
    format_id: str
    partition: str
    capture_store_id: str
    capture_store_identity_sha256: str
    source_artifact_sha256: tuple[str, ...]
    source_store_identity_sha256: str
    collected_at: str
    collection_method: str
    collector_id: str
    author_id: str
    executor_id: str
    independence_attested: bool
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise GroundingLineageError(
                "only grounding lineage receipt schema 1.0.0 is supported"
            )
        for field_name in (
            "lineage_id",
            "regulation_id",
            "format_id",
            "capture_store_id",
            "collection_method",
            "collector_id",
            "author_id",
            "executor_id",
        ):
            _stable_id(getattr(self, field_name), field_name)
        if _ISSUE_URL_RE.fullmatch(self.issue_url) is None:
            raise GroundingLineageError("lineage issue_url must identify a GitHub Issue")
        if self.partition not in {"development", "holdout"}:
            raise GroundingLineageError("lineage partition is invalid")
        _sha256(
            self.capture_store_identity_sha256,
            "capture_store_identity_sha256",
        )
        _sha256(self.source_store_identity_sha256, "source_store_identity_sha256")
        if (
            not self.source_artifact_sha256
            or tuple(sorted(self.source_artifact_sha256))
            != self.source_artifact_sha256
            or len(set(self.source_artifact_sha256))
            != len(self.source_artifact_sha256)
        ):
            raise GroundingLineageError(
                "source_artifact_sha256 must be a non-empty sorted unique tuple"
            )
        for value in self.source_artifact_sha256:
            _sha256(value, "source_artifact_sha256")
        _instant(self.collected_at, "collected_at")
        if self.independence_attested is not True:
            raise GroundingLineageError("lineage independence must be explicitly attested")
        if self.local_research_only is not True or self.distribution_allowed is not False:
            raise GroundingLineageError("grounding lineage is local research only")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


_RESOLUTION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class ResolvedGroundingLineageReceipt:
    receipt: GroundingLineageReceipt
    receipt_sha256: str
    source_path: Path

    def __init__(
        self,
        *,
        receipt: GroundingLineageReceipt,
        receipt_sha256: str,
        source_path: Path,
        _token: object | None = None,
    ) -> None:
        if _token is not _RESOLUTION_TOKEN:
            raise GroundingLineageError(
                "resolved lineage receipts must be created by the external loader"
            )
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "receipt_sha256", receipt_sha256)
        object.__setattr__(self, "source_path", source_path)


def load_grounding_lineage_receipt(
    path: Path | str,
) -> ResolvedGroundingLineageReceipt:
    source_path = _outside_repository(Path(path))
    try:
        if source_path.stat().st_size > _MAX_LINEAGE_BYTES:
            raise GroundingLineageError("grounding lineage receipt is too large")
        payload = source_path.read_bytes()
        raw = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GroundingLineageError(
            f"cannot read grounding lineage receipt: {error}"
        ) from error
    if not isinstance(raw, Mapping) or set(raw) != _LINEAGE_KEYS:
        raise GroundingLineageError(
            "grounding lineage receipt has missing or unexpected fields"
        )
    artifacts = raw["source_artifact_sha256"]
    if not isinstance(artifacts, list):
        raise GroundingLineageError("source_artifact_sha256 must be an array")
    try:
        receipt = GroundingLineageReceipt(
            schema_version=_string(raw["schema_version"], "schema_version"),
            lineage_id=_string(raw["lineage_id"], "lineage_id"),
            issue_url=_string(raw["issue_url"], "issue_url"),
            regulation_id=_string(raw["regulation_id"], "regulation_id"),
            format_id=_string(raw["format_id"], "format_id"),
            partition=_string(raw["partition"], "partition"),
            capture_store_id=_string(raw["capture_store_id"], "capture_store_id"),
            capture_store_identity_sha256=_string(
                raw["capture_store_identity_sha256"],
                "capture_store_identity_sha256",
            ),
            source_artifact_sha256=tuple(
                _string(value, "source_artifact_sha256") for value in artifacts
            ),
            source_store_identity_sha256=_string(
                raw["source_store_identity_sha256"],
                "source_store_identity_sha256",
            ),
            collected_at=_string(raw["collected_at"], "collected_at"),
            collection_method=_string(
                raw["collection_method"], "collection_method"
            ),
            collector_id=_string(raw["collector_id"], "collector_id"),
            author_id=_string(raw["author_id"], "author_id"),
            executor_id=_string(raw["executor_id"], "executor_id"),
            independence_attested=_boolean(
                raw["independence_attested"], "independence_attested"
            ),
            local_research_only=_boolean(
                raw["local_research_only"], "local_research_only"
            ),
            distribution_allowed=_boolean(
                raw["distribution_allowed"], "distribution_allowed"
            ),
        )
    except GroundingLineageError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise GroundingLineageError(
            f"grounding lineage receipt is invalid: {error}"
        ) from error
    canonical = canonical_json(receipt).encode("utf-8")
    if payload != canonical:
        raise GroundingLineageError(
            "grounding lineage receipt bytes must be canonical JSON"
        )
    return ResolvedGroundingLineageReceipt(
        receipt=receipt,
        receipt_sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        source_path=source_path,
        _token=_RESOLUTION_TOKEN,
    )


def _outside_repository(path: Path) -> Path:
    if not path.is_absolute():
        raise GroundingLineageError("lineage receipt path must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(_REPOSITORY_ROOT.resolve(strict=True))
    except ValueError:
        return resolved
    raise GroundingLineageError("lineage receipt must stay outside the repository")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GroundingLineageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise GroundingLineageError(f"non-canonical JSON number is not allowed: {value}")


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroundingLineageError(f"{field_name} must be a string")
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise GroundingLineageError(f"{field_name} must be a boolean")
    return value


__all__ = [
    "GroundingLineageError",
    "GroundingLineageReceipt",
    "ResolvedGroundingLineageReceipt",
    "load_grounding_lineage_receipt",
]
