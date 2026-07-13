"""Resolver-backed promotion gates for untrusted grounding/AI drafts."""

from __future__ import annotations

from dataclasses import dataclass

from .env import EnvObservation, ObservationSource
from .models import GroundedField, GroundingTrace, GroundingTraceStatus
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


@dataclass(frozen=True, slots=True, init=False)
class ValidatedEnvObservation:
    """A grounded observation resolved against both its trace and capture store."""

    observation: EnvObservation
    grounding: ValidatedGroundingTrace

    def __init__(
        self,
        observation: EnvObservation,
        grounding: ValidatedGroundingTrace,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _VALIDATION_TOKEN:
            raise GroundingValidationError(
                "ValidatedEnvObservation must be created by the resolver gate"
            )
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "grounding", grounding)

    @property
    def actionable(self) -> bool:
        return (
            self.grounding.trace.status is GroundingTraceStatus.CONFORMANT
            and not self.observation.blockers
            and self.observation.legal_action_mask.actionable
        )


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


def validate_env_observation_against_trace_and_store(
    observation: EnvObservation,
    trace: GroundingTrace,
    store: CaptureStore,
) -> ValidatedEnvObservation:
    """Promote a grounded draft only after trace/store/provenance resolution."""

    if observation.provenance.source is not ObservationSource.GROUNDED_CAPTURE:
        raise GroundingValidationError(
            "resolver-backed grounding validation only accepts grounded capture observations"
        )
    grounding = validate_grounding_trace_against_store(trace, store)
    if observation.provenance.grounding_trace_id != trace.trace_id:
        raise GroundingValidationError("observation references a different or nonexistent trace")
    if observation.ruleset_id != trace.ruleset_id or observation.viewer != trace.viewer:
        raise GroundingValidationError("observation ruleset/viewer does not match its trace")
    if trace.status is GroundingTraceStatus.NONCONFORMANT:
        raise GroundingValidationError("nonconformant traces cannot promote AI observations")

    frame_capture_ids = {frame.capture_id for frame in trace.frames}
    provenance_capture_ids = set(observation.provenance.capture_ids)
    if not provenance_capture_ids <= frame_capture_ids:
        raise GroundingValidationError("observation references a capture absent from its trace")

    artifact_capture_ids = {
        reference.rsplit("/", 1)[0] for reference in observation.provenance.artifact_refs
    }
    if artifact_capture_ids != provenance_capture_ids:
        raise GroundingValidationError(
            "observation capture IDs must equal its qualified artifact-reference captures"
        )

    trace_artifact_refs = {
        f"{frame.capture_id}/{artifact_id}"
        for frame in trace.frames
        for value in (*frame.fields, *frame.conformance)
        for artifact_id in value.artifact_ids
    }
    if not set(observation.provenance.artifact_refs) <= trace_artifact_refs:
        raise GroundingValidationError(
            "observation provenance references evidence absent from its trace"
        )

    observation_refs = {
        artifact_id
        for field in observation.instant_fields
        for artifact_id in field.artifact_ids
    }
    observation_refs.update(
        artifact_id
        for event in observation.public_history
        for artifact_id in event.evidence_artifact_ids
    )
    observation_refs.update(observation.legal_action_mask.evidence_artifact_ids)
    if not observation_refs <= trace_artifact_refs:
        raise GroundingValidationError(
            "observation evidence does not resolve through its grounding trace"
        )

    for field in observation.instant_fields:
        if not _field_resolves_to_trace(field, trace, provenance_capture_ids):
            raise GroundingValidationError(
                f"observation field is not supported by its grounding trace: {field.path}"
            )

    if trace.status is GroundingTraceStatus.INCOMPLETE:
        if not observation.blockers or observation.legal_action_mask.actionable:
            raise GroundingValidationError(
                "incomplete traces require blocked, non-actionable observations"
            )
    return ValidatedEnvObservation(
        observation=observation,
        grounding=grounding,
        _token=_VALIDATION_TOKEN,
    )


def _field_resolves_to_trace(
    field: GroundedField,
    trace: GroundingTrace,
    capture_ids: set[str],
) -> bool:
    for frame in trace.frames:
        if frame.capture_id not in capture_ids:
            continue
        for candidate in frame.fields:
            qualified = {
                f"{frame.capture_id}/{artifact_id}"
                for artifact_id in candidate.artifact_ids
            }
            if (
                candidate.path == field.path
                and candidate.status is field.status
                and candidate.source is field.source
                and candidate.value == field.value
                and candidate.confidence_ppm == field.confidence_ppm
                and qualified == set(field.artifact_ids)
            ):
                return True
    return False
