"""Immutable contracts for local capture artifacts and partial grounding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, TypeAlias

from champions_sim.core import to_canonical_data


JsonScalar: TypeAlias = str | int | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_CAPTURE_ID_PATTERN = re.compile(r"^capture-[0-9a-f]{64}$")


def _require_stable_id(value: str, field_name: str) -> None:
    if _STABLE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a stable ID")


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a sha256-prefixed lowercase digest")


def _require_capture_id(value: str, field_name: str) -> None:
    if _CAPTURE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a content-addressed capture ID")


def _require_unique(values: tuple[str, ...], field_name: str) -> None:
    if any(not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{field_name} values must be non-empty and unique")


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
        if not self.label:
            raise ValueError("annotation label is required")
        if not 0 <= self.confidence_ppm <= 1_000_000:
            raise ValueError("confidence_ppm must be between 0 and 1,000,000")


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
        if self.byte_size < 0:
            raise ValueError("artifact byte_size must be non-negative")
        _require_sha256(self.sha256, "artifact sha256")


@dataclass(frozen=True, slots=True)
class CaptureManifest:
    schema_version: str
    capture_id: str
    captured_at: str
    instance_name: str
    adb_serial: str
    game_input_performed: bool
    adb_server_ownership_verified: bool
    artifacts: tuple[CaptureArtifact, ...]
    redaction_status: RedactionStatus
    redaction_regions: tuple[RedactionRegion, ...]
    annotations: tuple[CaptureAnnotation, ...]
    contains_sensitive_content: bool | None
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("only capture manifest schema 1.0.0 is supported")
        _require_capture_id(self.capture_id, "capture_id")
        if not self.captured_at or not self.instance_name or not self.adb_serial:
            raise ValueError("capture timestamp, instance name, and adb serial are required")
        if self.game_input_performed is not False:
            raise ValueError("observation captures must declare game_input_performed=false")
        if self.adb_server_ownership_verified is not True:
            raise ValueError(
                "capture manifests require externally verified ADB server ownership"
            )
        if not self.artifacts:
            raise ValueError("capture manifest requires artifacts")
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
            raise ValueError("capture manifest requires the canonical screenshot and UI hierarchy")
        if any(value.artifact_id not in artifact_ids for value in self.annotations):
            raise ValueError("annotations must reference a manifest artifact")
        if self.redaction_status is RedactionStatus.UNREVIEWED and self.contains_sensitive_content is not None:
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
        if not 0 <= self.confidence_ppm <= 1_000_000:
            raise ValueError("confidence_ppm must be between 0 and 1,000,000")
        _require_unique(self.artifact_ids, "grounding artifact IDs")
        if self.status is GroundingStatus.UNKNOWN:
            if self.value is not None or self.confidence_ppm != 0:
                raise ValueError("unknown fields require null value and zero confidence")
        elif not self.artifact_ids:
            raise ValueError("observed, inferred, or conflicting fields require evidence artifacts")
        if self.status is GroundingStatus.INFERRED and self.source is not GroundingSource.INFERENCE:
            raise ValueError("inferred fields must use the inference source")


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
        _require_unique(self.artifact_ids, "conformance artifact IDs")
        if self.verdict in {ConformanceVerdict.MATCH, ConformanceVerdict.MISMATCH}:
            if not self.artifact_ids:
                raise ValueError("match and mismatch checks require capture evidence")
        if self.verdict is ConformanceVerdict.MATCH and self.expected != self.observed:
            raise ValueError("match verdict requires equal expected and observed values")
        if self.verdict is ConformanceVerdict.MISMATCH and self.expected == self.observed:
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
        if not self.observed_at:
            raise ValueError("observed_at is required")
        _require_unique(tuple(value.path for value in self.fields), "grounded field paths")
        _require_unique(tuple(value.path for value in self.conformance), "conformance paths")
        allowed_artifact_ids = {"screenshot", "ui-hierarchy"}
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
    format_id: str
    viewer: str
    reference_replay_hash: str | None
    frames: tuple[GroundingFrame, ...]
    status: GroundingTraceStatus
    blockers: tuple[str, ...]
    local_research_only: bool
    distribution_allowed: bool

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("only grounding trace schema 1.0.0 is supported")
        _require_stable_id(self.trace_id, "trace_id")
        _require_stable_id(self.format_id, "format_id")
        if self.viewer not in {"p1", "p2"}:
            raise ValueError("viewer must be p1 or p2")
        if self.reference_replay_hash is not None:
            if re.fullmatch(r"[0-9a-f]{64}", self.reference_replay_hash) is None:
                raise ValueError("reference_replay_hash must be lowercase SHA-256")
        if not self.frames:
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
                verdict not in {ConformanceVerdict.MATCH, ConformanceVerdict.NOT_APPLICABLE}
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
