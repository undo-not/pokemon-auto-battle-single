"""Gitignored, content-addressed local store for raw capture artifacts."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from champions_sim.core import canonical_json

from .bluestacks import CapturePayload
from .models import (
    AnnotationSource,
    ArtifactKind,
    BoundingBox,
    CaptureAnnotation,
    CaptureArtifact,
    CaptureManifest,
    RedactionRegion,
    RedactionStatus,
)


_CAPTURE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_KEYS = {
    "schema_version",
    "capture_id",
    "captured_at",
    "instance_name",
    "adb_serial",
    "game_input_performed",
    "adb_server_ownership_verified",
    "artifacts",
    "redaction_status",
    "redaction_regions",
    "annotations",
    "contains_sensitive_content",
    "local_research_only",
    "distribution_allowed",
}


def _digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class ResolvedCapture:
    """A capture whose manifest identity and every artifact were revalidated."""

    manifest: CaptureManifest
    manifest_hash: str
    artifact_ids: frozenset[str]


class CaptureStore:
    """Store unreviewed captures locally; raw data is never distribution-ready."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = (
            Path(root)
            if root is not None
            else _REPOSITORY_ROOT / "artifacts" / "bluestacks"
        )

    def save(
        self,
        payload: CapturePayload,
        *,
        capture_id: str | None = None,
    ) -> CaptureManifest:
        expected_capture_id = self.content_capture_id(payload)
        capture_id = capture_id or expected_capture_id
        if _CAPTURE_ID_RE.fullmatch(capture_id) is None:
            raise ValueError("capture_id must be a stable ID without path separators")
        if capture_id != expected_capture_id:
            raise ValueError("capture_id must equal the content-addressed capture identity")

        screenshot = payload.screenshot_png
        hierarchy = payload.ui_hierarchy_xml
        artifacts = (
            CaptureArtifact(
                artifact_id="screenshot",
                kind=ArtifactKind.SCREENSHOT,
                relative_path="screenshot.png",
                media_type="image/png",
                byte_size=len(screenshot),
                sha256=_digest(screenshot),
            ),
            CaptureArtifact(
                artifact_id="ui-hierarchy",
                kind=ArtifactKind.UI_HIERARCHY,
                relative_path="ui-hierarchy.xml",
                media_type="application/xml",
                byte_size=len(hierarchy),
                sha256=_digest(hierarchy),
            ),
        )
        manifest = CaptureManifest(
            schema_version="1.0.0",
            capture_id=capture_id,
            captured_at=payload.captured_at,
            instance_name=payload.instance_name,
            adb_serial=payload.adb_serial,
            game_input_performed=False,
            adb_server_ownership_verified=payload.adb_server_ownership_verified,
            artifacts=artifacts,
            redaction_status=RedactionStatus.UNREVIEWED,
            redaction_regions=(),
            annotations=(),
            contains_sensitive_content=None,
            local_research_only=True,
            distribution_allowed=False,
        )

        self.root.mkdir(parents=True, exist_ok=True)
        final_dir = self.root / capture_id
        if final_dir.exists():
            raise FileExistsError(f"capture already exists: {capture_id}")
        partial_dir = self.root / f".{capture_id}.partial.{uuid.uuid4().hex}"
        partial_dir.mkdir()
        try:
            (partial_dir / "screenshot.png").write_bytes(screenshot)
            (partial_dir / "ui-hierarchy.xml").write_bytes(hierarchy)
            (partial_dir / "manifest.json").write_text(
                canonical_json(manifest) + "\n",
                encoding="utf-8",
            )
            partial_dir.rename(final_dir)
        except BaseException:
            if partial_dir.exists():
                shutil.rmtree(partial_dir)
            raise
        return manifest

    @staticmethod
    def content_capture_id(payload: CapturePayload) -> str:
        digest = hashlib.sha256()
        metadata = canonical_json(
            {
                "instance_name": payload.instance_name,
                "adb_serial": payload.adb_serial,
                "captured_at": payload.captured_at,
                "adb_server_ownership_verified": payload.adb_server_ownership_verified,
            }
        ).encode("utf-8")
        for label, value in (
            (b"metadata", metadata),
            (b"screenshot.png", payload.screenshot_png),
            (b"ui-hierarchy.xml", payload.ui_hierarchy_xml),
        ):
            digest.update(len(label).to_bytes(4, "big"))
            digest.update(label)
            digest.update(len(value).to_bytes(8, "big"))
            digest.update(value)
        return "capture-" + digest.hexdigest()

    def verify(self, capture_id: str) -> bool:
        try:
            self.resolve(capture_id)
            return True
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False

    def resolve(self, capture_id: str) -> ResolvedCapture:
        """Resolve a capture only after schema/domain/identity/hash verification."""

        if _CAPTURE_ID_RE.fullmatch(capture_id) is None:
            raise ValueError("capture_id must be a stable ID without path separators")
        capture_dir = self.root / capture_id
        raw = json.loads((capture_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest = _load_manifest(raw)
        if manifest.capture_id != capture_id:
            raise ValueError("manifest capture_id does not match the requested capture")

        payloads: dict[str, bytes] = {}
        for artifact in manifest.artifacts:
            candidate = capture_dir / artifact.relative_path
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(capture_dir.resolve(strict=True))
            if not resolved.is_file():
                raise ValueError("capture artifact is not a regular file")
            payload = resolved.read_bytes()
            if len(payload) != artifact.byte_size or _digest(payload) != artifact.sha256:
                raise ValueError("capture artifact size or hash mismatch")
            payloads[artifact.artifact_id] = payload

        capture = CapturePayload(
            instance_name=manifest.instance_name,
            adb_serial=manifest.adb_serial,
            captured_at=manifest.captured_at,
            adb_server_ownership_verified=manifest.adb_server_ownership_verified,
            screenshot_png=payloads["screenshot"],
            ui_hierarchy_xml=payloads["ui-hierarchy"],
        )
        if self.content_capture_id(capture) != capture_id:
            raise ValueError("capture content identity mismatch")
        return ResolvedCapture(
            manifest=manifest,
            manifest_hash=_digest(canonical_json(manifest).encode("utf-8")),
            artifact_ids=frozenset(payloads),
        )

    def manifest_hash(self, capture_id: str) -> str:
        """Return the semantic manifest hash only for a fully verified capture."""

        return self.resolve(capture_id).manifest_hash


def _require_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ValueError(f"{label} has missing or unexpected fields")


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    return value


def _integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    return value


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be a boolean")
    return value


def _box(value: Any) -> BoundingBox:
    raw = _mapping(value, "bounding box")
    _require_keys(raw, {"x", "y", "width", "height"}, "bounding box")
    return BoundingBox(
        x=_integer(raw["x"], "box.x"),
        y=_integer(raw["y"], "box.y"),
        width=_integer(raw["width"], "box.width"),
        height=_integer(raw["height"], "box.height"),
    )


def _load_manifest(value: Any) -> CaptureManifest:
    raw = _mapping(value, "capture manifest")
    _require_keys(raw, _MANIFEST_KEYS, "capture manifest")

    artifacts: list[CaptureArtifact] = []
    artifact_keys = {"artifact_id", "kind", "relative_path", "media_type", "byte_size", "sha256"}
    for index, value in enumerate(_array(raw["artifacts"], "artifacts")):
        artifact = _mapping(value, f"artifacts[{index}]")
        _require_keys(artifact, artifact_keys, f"artifacts[{index}]")
        artifacts.append(
            CaptureArtifact(
                artifact_id=_string(artifact["artifact_id"], "artifact_id"),
                kind=ArtifactKind(_string(artifact["kind"], "artifact kind")),
                relative_path=_string(artifact["relative_path"], "relative_path"),
                media_type=_string(artifact["media_type"], "media_type"),
                byte_size=_integer(artifact["byte_size"], "byte_size"),
                sha256=_string(artifact["sha256"], "sha256"),
            )
        )

    regions: list[RedactionRegion] = []
    for index, value in enumerate(_array(raw["redaction_regions"], "redaction_regions")):
        region = _mapping(value, f"redaction_regions[{index}]")
        _require_keys(region, {"region_id", "box", "reason"}, f"redaction_regions[{index}]")
        regions.append(
            RedactionRegion(
                region_id=_string(region["region_id"], "region_id"),
                box=_box(region["box"]),
                reason=_string(region["reason"], "redaction reason"),
            )
        )

    annotations: list[CaptureAnnotation] = []
    annotation_keys = {
        "annotation_id",
        "label",
        "source",
        "confidence_ppm",
        "artifact_id",
        "box",
        "value",
    }
    for index, value in enumerate(_array(raw["annotations"], "annotations")):
        annotation = _mapping(value, f"annotations[{index}]")
        _require_keys(annotation, annotation_keys, f"annotations[{index}]")
        box_value = annotation["box"]
        annotations.append(
            CaptureAnnotation(
                annotation_id=_string(annotation["annotation_id"], "annotation_id"),
                label=_string(annotation["label"], "annotation label"),
                source=AnnotationSource(_string(annotation["source"], "annotation source")),
                confidence_ppm=_integer(annotation["confidence_ppm"], "confidence_ppm"),
                artifact_id=_string(annotation["artifact_id"], "artifact_id"),
                box=None if box_value is None else _box(box_value),
                value=annotation["value"],
            )
        )

    sensitive = raw["contains_sensitive_content"]
    if sensitive is not None and not isinstance(sensitive, bool):
        raise TypeError("contains_sensitive_content must be boolean or null")
    return CaptureManifest(
        schema_version=_string(raw["schema_version"], "schema_version"),
        capture_id=_string(raw["capture_id"], "capture_id"),
        captured_at=_string(raw["captured_at"], "captured_at"),
        instance_name=_string(raw["instance_name"], "instance_name"),
        adb_serial=_string(raw["adb_serial"], "adb_serial"),
        game_input_performed=_boolean(raw["game_input_performed"], "game_input_performed"),
        adb_server_ownership_verified=_boolean(
            raw["adb_server_ownership_verified"], "adb_server_ownership_verified"
        ),
        artifacts=tuple(artifacts),
        redaction_status=RedactionStatus(_string(raw["redaction_status"], "redaction_status")),
        redaction_regions=tuple(regions),
        annotations=tuple(annotations),
        contains_sensitive_content=sensitive,
        local_research_only=_boolean(raw["local_research_only"], "local_research_only"),
        distribution_allowed=_boolean(raw["distribution_allowed"], "distribution_allowed"),
    )
