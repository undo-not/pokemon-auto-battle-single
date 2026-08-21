"""Immutable contracts for local capture artifacts and partial grounding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from champions_sim.core import canonical_json, to_canonical_data

from .adb import AdbServerIdentity
from .android_client import AndroidClientBuild


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = (
    JsonScalar | tuple["JsonValue", ...] | Mapping[str, "JsonValue"]
)

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CAPTURE_ID_PATTERN = re.compile(r"^capture-[0-9a-f]{64}$")
_ANDROID_PACKAGE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+$"
)
_MAX_ARTIFACT_SKEW = timedelta(seconds=30)


def _require_stable_id(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) > 240
        or _STABLE_ID_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} must be a stable ID")


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a sha256-prefixed lowercase digest")


def _require_capture_id(value: str, field_name: str) -> None:
    if _CAPTURE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a content-addressed capture ID")


def _require_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _require_integer(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be non-empty and unique")


def _freeze_json(value: Any, field_name: str) -> JsonValue:
    try:
        canonical = to_canonical_data(value)
    except TypeError as error:
        raise ValueError(f"{field_name} must be canonical JSON") from error

    def freeze(item: Any) -> JsonValue:
        if isinstance(item, list):
            return tuple(freeze(value) for value in item)
        if isinstance(item, dict):
            return MappingProxyType(
                {key: freeze(value) for key, value in item.items()}
            )
        return item

    return freeze(canonical)


class ArtifactKind(str, Enum):
    SCREENSHOT = "screenshot"
    UI_HIERARCHY = "ui_hierarchy"


class RedactionStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    ANNOTATED = "annotated"
    CLEARED_LOCAL_ONLY = "cleared_local_only"


class AnnotationSource(str, Enum):
    HUMAN = "human"
    DETECTOR = "detector"
    UI_METADATA = "ui_metadata"


@dataclass(frozen=True, slots=True)
class BoundingBox:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        for field_name in ("x", "y", "width", "height"):
            _require_integer(getattr(self, field_name), field_name)
        if self.x < 0 or self.y < 0:
            raise ValueError("bounding-box coordinates must be non-negative")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("bounding-box dimensions must be positive")


@dataclass(frozen=True, slots=True)
class RedactionRegion:
    region_id: str
    box: BoundingBox
    reason: str

    def __post_init__(self) -> None:
        _require_stable_id(self.region_id, "region_id")
        if not self.reason:
            raise ValueError("redaction reason is required")


@dataclass(frozen=True, slots=True)
class CaptureAnnotation:
    annotation_id: str
    label: str
    source: AnnotationSource
    confidence_ppm: int
    artifact_id: str
    box: BoundingBox | None = None
    value: JsonValue = None

    def __post_init__(self) -> None:
        _require_stable_id(self.annotation_id, "annotation_id")
        _require_stable_id(self.artifact_id, "artifact_id")
        if not isinstance(self.source, AnnotationSource):
            raise ValueError("annotation source is invalid")
        if not self.label:
            raise ValueError("annotation label is required")
        _require_integer(self.confidence_ppm, "confidence_ppm")
        if not 0 <= self.confidence_ppm <= 1_000_000:
            raise ValueError("confidence_ppm must be between 0 and 1,000,000")
        object.__setattr__(
            self,
            "value",
            _freeze_json(self.value, "capture annotation value"),
        )


@dataclass(frozen=True, slots=True)
class CaptureArtifact:
    artifact_id: str
    kind: ArtifactKind
    relative_path: str
    media_type: str
    byte_size: int
    sha256: str

    def __post_init__(self) -> None:
        _require_stable_id(self.artifact_id, "artifact_id")
        if not isinstance(self.kind, ArtifactKind):
            raise ValueError("artifact kind is invalid")
        path = PurePosixPath(self.relative_path)
        if (
            not self.relative_path
            or "\\" in self.relative_path
            or self.relative_path.startswith("/")
            or ":" in self.relative_path
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise ValueError("artifact relative_path must stay inside its capture directory")
        if not self.media_type:
            raise ValueError("artifact media_type is required")
        _require_integer(self.byte_size, "artifact byte_size")
        if self.byte_size < 0:
            raise ValueError("artifact byte_size must be non-negative")
        _require_sha256(self.sha256, "artifact sha256")


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    schema_version: str
    capture_id: str
    captured_at: str
    ui_hierarchy_before_captured_at: str
    screenshot_captured_at: str
    ui_hierarchy_captured_at: str
    ui_state_sha256: str
    instance_name: str
    adb_serial: str
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
    game_input_performed: bool
    adb_server_ownership_verified: bool
    adb_server: AdbServerIdentity
    artifacts: tuple[CaptureArtifact, ...]
    redaction_status: RedactionStatus
    redaction_regions: tuple[RedactionRegion, ...]
    annotations: tuple[CaptureAnnotation, ...]
    contains_sensitive_content: bool | None
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "2.0.0":
            raise ValueError("only capture manifest schema 2.0.0 is supported")
        _require_capture_id(self.capture_id, "capture_id")
        completed = _require_timestamp(self.captured_at, "captured_at")
        hierarchy_before_at = _require_timestamp(
            self.ui_hierarchy_before_captured_at,
            "ui_hierarchy_before_captured_at",
        )
        screenshot_at = _require_timestamp(
            self.screenshot_captured_at, "screenshot_captured_at"
        )
        hierarchy_at = _require_timestamp(
            self.ui_hierarchy_captured_at, "ui_hierarchy_captured_at"
        )
        if not hierarchy_before_at <= screenshot_at <= hierarchy_at <= completed:
            raise ValueError("capture artifact timestamps are not ordered")
        if hierarchy_at - hierarchy_before_at > _MAX_ARTIFACT_SKEW:
            raise ValueError("capture artifacts exceed the maximum temporal skew")
        _require_sha256(self.ui_state_sha256, "ui_state_sha256")
        _require_stable_id(self.instance_name, "instance_name")
        if not self.adb_serial:
            raise ValueError("capture adb serial is required")
        serial_match = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", self.adb_serial)
        if serial_match is None or int(serial_match.group(1)) > 65_535:
            raise ValueError("capture ADB serial must be a valid loopback endpoint")
        _require_stable_id(self.format_id, "format_id")
        _require_stable_id(self.plan_id, "plan_id")
        _require_sha256(self.plan_hash, "plan_hash")
        _require_sha256(self.lineage_receipt_sha256, "lineage_receipt_sha256")
        if re.fullmatch(
            r"https://github\.com/[^/]+/[^/]+/issues/[1-9][0-9]*"
            r"#issuecomment-[1-9][0-9]*",
            self.plan_seal_comment_url,
        ) is None:
            raise ValueError("capture plan-seal comment URL is invalid")
        _require_sha256(
            self.plan_seal_receipt_sha256, "plan_seal_receipt_sha256"
        )
        if self.partition not in {"development", "holdout"}:
            raise ValueError("capture partition is invalid")
        if (
            len(self.target_package) > 240
            or _ANDROID_PACKAGE_PATTERN.fullmatch(self.target_package) is None
        ):
            raise ValueError("capture target_package is invalid")
        if not isinstance(self.client_build, AndroidClientBuild):
            raise ValueError("capture client_build identity is invalid")
        _require_stable_id(self.capture_store_id, "capture_store_id")
        _require_sha256(
            self.capture_store_identity_sha256,
            "capture_store_identity_sha256",
        )
        _require_stable_id(self.authorization_id, "authorization_id")
        _require_sha256(self.authorization_sha256, "authorization_sha256")
        if not isinstance(self.adb_server, AdbServerIdentity):
            raise ValueError("capture ADB server identity is invalid")
        if self.game_input_performed is not False:
            raise ValueError("observation captures must declare game_input_performed=false")
        if self.adb_server_ownership_verified is not True:
            raise ValueError(
                "capture manifests require externally verified ADB server ownership"
            )
        if not self.artifacts or any(
            not isinstance(value, CaptureArtifact) for value in self.artifacts
        ):
            raise ValueError("capture manifest requires artifacts")
        if not isinstance(self.redaction_status, RedactionStatus):
            raise ValueError("capture redaction status is invalid")
        if any(not isinstance(value, RedactionRegion) for value in self.redaction_regions):
            raise ValueError("capture redaction regions are invalid")
        if any(not isinstance(value, CaptureAnnotation) for value in self.annotations):
            raise ValueError("capture annotations are invalid")
        _require_unique(tuple(value.artifact_id for value in self.artifacts), "artifact IDs")
        _require_unique(
            tuple(value.region_id for value in self.redaction_regions), "redaction region IDs"
        )
        _require_unique(
            tuple(value.annotation_id for value in self.annotations), "annotation IDs"
        )
        artifact_ids = {value.artifact_id for value in self.artifacts}
        expected_artifacts = {
            "screenshot": (ArtifactKind.SCREENSHOT, "screenshot.png", "image/png"),
            "ui-hierarchy-before": (
                ArtifactKind.UI_HIERARCHY,
                "ui-hierarchy-before.xml",
                "application/xml",
            ),
            "ui-hierarchy": (
                ArtifactKind.UI_HIERARCHY,
                "ui-hierarchy.xml",
                "application/xml",
            ),
        }
        if artifact_ids != set(expected_artifacts) or any(
            (artifact.kind, artifact.relative_path, artifact.media_type)
            != expected_artifacts[artifact.artifact_id]
            for artifact in self.artifacts
        ):
            raise ValueError(
                "capture manifest requires the canonical screenshot and bracketed UI hierarchies"
            )
        if any(value.artifact_id not in artifact_ids for value in self.annotations):
            raise ValueError("annotations must reference a manifest artifact")
        if (
            self.redaction_status is RedactionStatus.UNREVIEWED
            and self.contains_sensitive_content is not None
        ):
            raise ValueError("unreviewed capture sensitivity must remain unknown")
        if self.local_research_only is not True or self.distribution_allowed is not False:
            raise ValueError("capture artifacts are local research only and non-distributable")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value


class GroundingSource(str, Enum):
    SCREEN_REGION = "screen_region"
    UI_METADATA = "ui_metadata"
    PUBLIC_HISTORY = "public_history"
    MANUAL = "manual"
    INFERENCE = "inference"


class GroundingStatus(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class GroundedField:
    path: str
    status: GroundingStatus
    source: GroundingSource
    value: JsonValue
    confidence_ppm: int
    artifact_ids: tuple[str, ...]
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("grounded field path must be an absolute JSON pointer")
        if not isinstance(self.status, GroundingStatus):
            raise ValueError("grounded field status is invalid")
        if not isinstance(self.source, GroundingSource):
            raise ValueError("grounded field source is invalid")
        _require_integer(self.confidence_ppm, "confidence_ppm")
        if not 0 <= self.confidence_ppm <= 1_000_000:
            raise ValueError("confidence_ppm must be between 0 and 1,000,000")
        object.__setattr__(
            self,
            "value",
            _freeze_json(self.value, "grounded field value"),
        )
        _require_unique(self.artifact_ids, "grounding artifact IDs")
        if self.status is GroundingStatus.UNKNOWN:
            if self.value is not None or self.confidence_ppm != 0:
                raise ValueError("unknown fields require null value and zero confidence")
        else:
            if not self.artifact_ids:
                raise ValueError(
                    "observed, inferred, or conflicting fields require evidence artifacts"
                )
            if self.status is GroundingStatus.OBSERVED and self.confidence_ppm == 0:
                raise ValueError("observed fields require positive confidence")
        if (self.status is GroundingStatus.INFERRED) != (
            self.source is GroundingSource.INFERENCE
        ):
            raise ValueError(
                "only inferred fields may use the inference source"
            )


class ConformanceVerdict(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ConformanceCheck:
    path: str
    verdict: ConformanceVerdict
    expected: JsonValue
    observed: JsonValue
    artifact_ids: tuple[str, ...]
    note: str | None = None

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("conformance path must be an absolute JSON pointer")
        if not isinstance(self.verdict, ConformanceVerdict):
            raise ValueError("conformance verdict is invalid")
        object.__setattr__(
            self,
            "expected",
            _freeze_json(self.expected, "conformance expected value"),
        )
        object.__setattr__(
            self,
            "observed",
            _freeze_json(self.observed, "conformance observed value"),
        )
        _require_unique(self.artifact_ids, "conformance artifact IDs")
        if self.verdict in {ConformanceVerdict.MATCH, ConformanceVerdict.MISMATCH}:
            if not self.artifact_ids:
                raise ValueError("match and mismatch checks require capture evidence")
        values_equal = canonical_json(self.expected) == canonical_json(self.observed)
        if self.verdict is ConformanceVerdict.MATCH and not values_equal:
            raise ValueError("match verdict requires equal expected and observed values")
        if self.verdict is ConformanceVerdict.MISMATCH and values_equal:
            raise ValueError("mismatch verdict requires different values")
        if self.verdict is ConformanceVerdict.UNKNOWN and self.observed is not None:
            raise ValueError("unknown verdict requires null observed value")


@dataclass(frozen=True, slots=True)
class GroundingFrame:
    frame_id: str
    capture_id: str
    capture_manifest_hash: str
    observed_at: str
    fields: tuple[GroundedField, ...]
    conformance: tuple[ConformanceCheck, ...]

    def __post_init__(self) -> None:
        _require_stable_id(self.frame_id, "frame_id")
        _require_capture_id(self.capture_id, "capture_id")
        _require_sha256(self.capture_manifest_hash, "capture_manifest_hash")
        _require_timestamp(self.observed_at, "observed_at")
        if any(not isinstance(value, GroundedField) for value in self.fields):
            raise ValueError("grounding frame fields are invalid")
        if any(not isinstance(value, ConformanceCheck) for value in self.conformance):
            raise ValueError("grounding frame conformance checks are invalid")
        _require_unique(tuple(value.path for value in self.fields), "grounded field paths")
        _require_unique(tuple(value.path for value in self.conformance), "conformance paths")
        fields_by_path = {value.path: value for value in self.fields}
        for check in self.conformance:
            if check.verdict not in {
                ConformanceVerdict.MATCH,
                ConformanceVerdict.MISMATCH,
            }:
                continue
            field = fields_by_path.get(check.path)
            if field is None:
                raise ValueError(
                    "evidence-backed conformance requires an observed field at the same path"
                )
            if field.status is not GroundingStatus.OBSERVED:
                raise ValueError(
                    "evidence-backed conformance requires observed field status"
                )
            if canonical_json(field.value) != canonical_json(check.observed):
                raise ValueError(
                    "grounded field value differs from the conformance observation"
                )
            if frozenset(field.artifact_ids) != frozenset(check.artifact_ids):
                raise ValueError(
                    "grounded field provenance differs from the conformance evidence"
                )
        allowed_artifact_ids = {
            "screenshot",
            "ui-hierarchy-before",
            "ui-hierarchy",
        }
        referenced_artifact_ids = {
            artifact_id
            for value in (*self.fields, *self.conformance)
            for artifact_id in value.artifact_ids
        }
        if not referenced_artifact_ids <= allowed_artifact_ids:
            raise ValueError("grounding frame evidence must reference capture manifest artifacts")


class GroundingTraceStatus(str, Enum):
    INCOMPLETE = "incomplete"
    CONFORMANT = "conformant"
    NONCONFORMANT = "nonconformant"


@dataclass(frozen=True, slots=True)
class GroundingTrace:
    """Untrusted draft until validated against a CaptureStore resolver."""

    schema_version: str
    trace_id: str
    plan_id: str
    plan_hash: str
    lineage_receipt_sha256: str
    partition: str
    requirement_id: str
    capture_store_id: str
    format_id: str
    viewer: str
    reference_replay_hash: str | None
    frames: tuple[GroundingFrame, ...]
    status: GroundingTraceStatus
    blockers: tuple[str, ...]
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "2.0.0":
            raise ValueError("only grounding trace schema 2.0.0 is supported")
        _require_stable_id(self.trace_id, "trace_id")
        _require_stable_id(self.plan_id, "plan_id")
        _require_sha256(self.plan_hash, "plan_hash")
        _require_sha256(self.lineage_receipt_sha256, "lineage_receipt_sha256")
        if self.partition not in {"development", "holdout"}:
            raise ValueError("grounding trace partition is invalid")
        _require_stable_id(self.requirement_id, "requirement_id")
        _require_stable_id(self.capture_store_id, "capture_store_id")
        _require_stable_id(self.format_id, "format_id")
        if self.viewer not in {"p1", "p2"}:
            raise ValueError("viewer must be p1 or p2")
        if not isinstance(self.status, GroundingTraceStatus):
            raise ValueError("grounding trace status is invalid")
        if self.reference_replay_hash is not None:
            if re.fullmatch(r"[0-9a-f]{64}", self.reference_replay_hash) is None:
                raise ValueError("reference_replay_hash must be lowercase SHA-256")
        if not self.frames or any(
            not isinstance(value, GroundingFrame) for value in self.frames
        ):
            raise ValueError("grounding trace requires at least one frame")
        _require_unique(tuple(value.frame_id for value in self.frames), "frame IDs")
        capture_manifest_bindings: dict[str, str] = {}
        for frame in self.frames:
            previous = capture_manifest_bindings.setdefault(
                frame.capture_id, frame.capture_manifest_hash
            )
            if previous != frame.capture_manifest_hash:
                raise ValueError("one capture ID cannot bind to multiple manifest hashes")
        _require_unique(self.blockers, "grounding blockers")
        verdicts = [check.verdict for frame in self.frames for check in frame.conformance]
        if self.status is GroundingTraceStatus.CONFORMANT:
            if (
                self.blockers
                or not verdicts
                or ConformanceVerdict.MATCH not in verdicts
                or any(
                    verdict
                    not in {
                        ConformanceVerdict.MATCH,
                        ConformanceVerdict.NOT_APPLICABLE,
                    }
                    for verdict in verdicts
                )
            ):
                raise ValueError(
                    "conformant traces require evidence-backed matches and no unresolved checks"
                )
        if self.status is GroundingTraceStatus.NONCONFORMANT:
            if ConformanceVerdict.MISMATCH not in verdicts:
                raise ValueError("nonconformant traces require a mismatch")
        if self.local_research_only is not True or self.distribution_allowed is not False:
            raise ValueError("grounding traces are local research only and non-distributable")

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value
