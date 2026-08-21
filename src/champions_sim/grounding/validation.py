"""Resolver-backed validation gates for untrusted grounding drafts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .android_client import AndroidClientBuild
from .authorization import (
    ObservationAuthorizationError,
    load_observation_authorization,
)
from .models import GroundingTrace, GroundingTraceStatus
from .store import CaptureStore, ResolvedGroundingTraceArtifact


class GroundingValidationError(ValueError):
    """Raised when draft evidence cannot be resolved to local capture artifacts."""


_VALIDATION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ValidatedCaptureBinding:
    capture_id: str
    manifest_hash: str
    artifact_ids: frozenset[str]
    capture_store_id: str
    capture_store_identity_sha256: str
    capture_store_partition: str
    lineage_receipt_sha256: str
    authorization_sha256: str
    authorization_id: str
    authorization_issue_url: str
    authorization_granted_at: str
    authorization_expires_at: str
    plan_seal_comment_url: str
    plan_seal_receipt_sha256: str
    format_id: str
    target_package: str
    client_build: AndroidClientBuild
    captured_at: str
    ui_hierarchy_before_captured_at: str
    screenshot_captured_at: str
    ui_hierarchy_captured_at: str
    ui_state_sha256: str
    artifact_sha256: frozenset[str]


@dataclass(frozen=True, slots=True, init=False)
class ValidatedGroundingTrace:
    """A trace whose frame bindings were resolved against a CaptureStore."""

    trace: GroundingTrace
    source_trace_hash: str
    capture_bindings: tuple[ValidatedCaptureBinding, ...]

    def __init__(
        self,
        trace: GroundingTrace,
        source_trace_hash: str,
        capture_bindings: tuple[ValidatedCaptureBinding, ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _VALIDATION_TOKEN:
            raise GroundingValidationError(
                "ValidatedGroundingTrace must be created by the resolver gate"
            )
        object.__setattr__(self, "trace", trace)
        object.__setattr__(self, "source_trace_hash", source_trace_hash)
        object.__setattr__(self, "capture_bindings", capture_bindings)

    @property
    def promotable(self) -> bool:
        return self.trace.status is GroundingTraceStatus.CONFORMANT


def validate_grounding_trace_against_store(
    stored_trace: ResolvedGroundingTraceArtifact,
    store: CaptureStore,
    *,
    issue_url: str,
    authorization_paths: Mapping[str, Path | str],
) -> ValidatedGroundingTrace:
    """Re-resolve canonical trace bytes, manifests, and artifact references."""

    if not isinstance(stored_trace, ResolvedGroundingTraceArtifact):
        raise GroundingValidationError(
            "grounding trace must first resolve from the external trace store"
        )
    try:
        fresh = store.resolve_trace(stored_trace.trace_hash)
    except (OSError, TypeError, ValueError) as error:
        raise GroundingValidationError("grounding trace bytes do not re-resolve") from error
    if fresh != stored_trace:
        raise GroundingValidationError("grounding trace resolver identity changed")
    trace = fresh.trace
    if store.partition != trace.partition:
        raise GroundingValidationError("grounding trace partition does not match capture store")

    bindings: dict[str, ValidatedCaptureBinding] = {}
    for frame in trace.frames:
        try:
            resolved = store.resolve(frame.capture_id)
        except (OSError, TypeError, ValueError) as error:
            raise GroundingValidationError(
                f"capture does not resolve for frame {frame.frame_id}: {frame.capture_id}"
            ) from error
        if resolved.manifest_hash != frame.capture_manifest_hash:
            raise GroundingValidationError(
                f"capture manifest hash mismatch for frame {frame.frame_id}"
            )
        if resolved.manifest.capture_store_id != trace.capture_store_id:
            raise GroundingValidationError(
                f"capture store mismatch for frame {frame.frame_id}"
            )
        if resolved.manifest.format_id != trace.format_id:
            raise GroundingValidationError(f"capture format mismatch for frame {frame.frame_id}")
        if (
            resolved.manifest.plan_id != trace.plan_id
            or resolved.manifest.plan_hash != trace.plan_hash
            or resolved.manifest.lineage_receipt_sha256
            != trace.lineage_receipt_sha256
            or resolved.manifest.partition != trace.partition
        ):
            raise GroundingValidationError(
                f"capture plan binding mismatch for frame {frame.frame_id}"
            )
        if _instant(frame.observed_at) != _instant(resolved.manifest.captured_at):
            raise GroundingValidationError(
                f"capture timestamp mismatch for frame {frame.frame_id}"
            )
        authorization_path = authorization_paths.get(
            resolved.manifest.authorization_sha256
        )
        if authorization_path is None:
            raise GroundingValidationError(
                f"capture authorization is unavailable for frame {frame.frame_id}"
            )
        try:
            authorization = load_observation_authorization(
                authorization_path,
                now=_instant(resolved.manifest.ui_hierarchy_before_captured_at),
                issue_url=issue_url,
                format_id=resolved.manifest.format_id,
                plan_id=resolved.manifest.plan_id,
                plan_hash=resolved.manifest.plan_hash,
                lineage_receipt_sha256=(
                    resolved.manifest.lineage_receipt_sha256
                ),
                plan_seal_comment_url=resolved.manifest.plan_seal_comment_url,
                plan_seal_receipt_sha256=(
                    resolved.manifest.plan_seal_receipt_sha256
                ),
                partition=resolved.manifest.partition,
                instance_name=resolved.manifest.instance_name,
                target_package=resolved.manifest.target_package,
                client_build=resolved.manifest.client_build,
                capture_store_id=resolved.manifest.capture_store_id,
                capture_store_identity_sha256=(
                    resolved.manifest.capture_store_identity_sha256
                ),
            )
            for timestamp in (
                resolved.manifest.screenshot_captured_at,
                resolved.manifest.ui_hierarchy_captured_at,
                resolved.manifest.captured_at,
            ):
                authorization.assert_current(
                    now=_instant(timestamp),
                    issue_url=issue_url,
                    format_id=resolved.manifest.format_id,
                    plan_id=resolved.manifest.plan_id,
                    plan_hash=resolved.manifest.plan_hash,
                    lineage_receipt_sha256=(
                        resolved.manifest.lineage_receipt_sha256
                    ),
                    plan_seal_comment_url=resolved.manifest.plan_seal_comment_url,
                    plan_seal_receipt_sha256=(
                        resolved.manifest.plan_seal_receipt_sha256
                    ),
                    partition=resolved.manifest.partition,
                    instance_name=resolved.manifest.instance_name,
                    target_package=resolved.manifest.target_package,
                    client_build=resolved.manifest.client_build,
                    capture_store_id=resolved.manifest.capture_store_id,
                    capture_store_identity_sha256=(
                        resolved.manifest.capture_store_identity_sha256
                    ),
                )
        except ObservationAuthorizationError as error:
            raise GroundingValidationError(
                f"capture authorization does not resolve for frame {frame.frame_id}"
            ) from error
        if (
            authorization.authorization_hash
            != resolved.manifest.authorization_sha256
            or authorization.authorization.authorization_id
            != resolved.manifest.authorization_id
        ):
            raise GroundingValidationError(
                f"capture authorization identity mismatch for frame {frame.frame_id}"
            )
        referenced = {
            artifact_id
            for value in (*frame.fields, *frame.conformance)
            for artifact_id in value.artifact_ids
        }
        if not referenced <= resolved.artifact_ids:
            raise GroundingValidationError(
                f"frame {frame.frame_id} references a missing capture artifact"
            )
        bindings[frame.capture_id] = ValidatedCaptureBinding(
            capture_id=frame.capture_id,
            manifest_hash=resolved.manifest_hash,
            artifact_ids=resolved.artifact_ids,
            capture_store_id=resolved.manifest.capture_store_id,
            capture_store_identity_sha256=store.identity_hash,
            capture_store_partition=store.partition,
            lineage_receipt_sha256=resolved.manifest.lineage_receipt_sha256,
            authorization_sha256=resolved.manifest.authorization_sha256,
            authorization_id=resolved.manifest.authorization_id,
            authorization_issue_url=authorization.authorization.issue_url,
            authorization_granted_at=authorization.authorization.granted_at,
            authorization_expires_at=authorization.authorization.expires_at,
            plan_seal_comment_url=resolved.manifest.plan_seal_comment_url,
            plan_seal_receipt_sha256=(
                resolved.manifest.plan_seal_receipt_sha256
            ),
            format_id=resolved.manifest.format_id,
            target_package=resolved.manifest.target_package,
            client_build=resolved.manifest.client_build,
            captured_at=resolved.manifest.captured_at,
            ui_hierarchy_before_captured_at=(
                resolved.manifest.ui_hierarchy_before_captured_at
            ),
            screenshot_captured_at=resolved.manifest.screenshot_captured_at,
            ui_hierarchy_captured_at=resolved.manifest.ui_hierarchy_captured_at,
            ui_state_sha256=resolved.manifest.ui_state_sha256,
            artifact_sha256=frozenset(
                artifact.sha256 for artifact in resolved.manifest.artifacts
            ),
        )
    return ValidatedGroundingTrace(
        trace=trace,
        source_trace_hash=fresh.trace_hash,
        capture_bindings=tuple(bindings[key] for key in sorted(bindings)),
        _token=_VALIDATION_TOKEN,
    )


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise GroundingValidationError("capture timestamp is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GroundingValidationError("capture timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)
