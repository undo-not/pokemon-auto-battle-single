"""Resolver-backed validation gates for untrusted grounding drafts."""

from __future__ import annotations

from dataclasses import dataclass

from .models import GroundingTrace, GroundingTraceStatus
from .store import CaptureStore


class GroundingValidationError(ValueError):
    """Raised when draft evidence cannot be resolved to local capture artifacts."""


_VALIDATION_TOKEN = object()


@dataclass(frozen=True, slots=True)
class ValidatedCaptureBinding:
    capture_id: str
    manifest_hash: str
    artifact_ids: frozenset[str]


@dataclass(frozen=True, slots=True, init=False)
class ValidatedGroundingTrace:
    """A trace whose frame bindings were resolved against a CaptureStore."""

    trace: GroundingTrace
    capture_bindings: tuple[ValidatedCaptureBinding, ...]

    def __init__(
        self,
        trace: GroundingTrace,
        capture_bindings: tuple[ValidatedCaptureBinding, ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _VALIDATION_TOKEN:
            raise GroundingValidationError(
                "ValidatedGroundingTrace must be created by the resolver gate"
            )
        object.__setattr__(self, "trace", trace)
        object.__setattr__(self, "capture_bindings", capture_bindings)

    @property
    def promotable(self) -> bool:
        return self.trace.status is GroundingTraceStatus.CONFORMANT


def validate_grounding_trace_against_store(
    trace: GroundingTrace,
    store: CaptureStore,
) -> ValidatedGroundingTrace:
    """Resolve every frame manifest hash and local artifact reference."""

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
        )
    return ValidatedGroundingTrace(
        trace=trace,
        capture_bindings=tuple(bindings[key] for key in sorted(bindings)),
        _token=_VALIDATION_TOKEN,
    )
