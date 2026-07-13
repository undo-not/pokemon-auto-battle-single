"""AI-facing partial-observation, public-history, and legal-mask contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from champions_sim.core import DecisionRequest, to_canonical_data

from .models import (
    GroundedField,
    JsonScalar,
    _require_capture_id,
    _require_stable_id,
    _require_unique,
)


_EVENT_DETAIL_KEYS: dict[str, frozenset[str]] = {
    "action_failed": frozenset({"reason"}),
    "ability_revealed": frozenset({"ability_id"}),
    "battle_ended": frozenset({"winner"}),
    "battle_started": frozenset({"ruleset_id"}),
    "critical_hit": frozenset(),
    "damage": frozenset({"cause", "hp_bar_range_millionths"}),
    "fainted": frozenset(),
    "healed": frozenset({"cause", "hp_bar_range_millionths"}),
    "item_revealed": frozenset({"item_id"}),
    "item_consumed": frozenset({"item_id"}),
    "mega_evolved": frozenset({"pokemon_id", "mega_pokemon_id"}),
    "move_used": frozenset({"move_id"}),
    "move_missed": frozenset({"move_id"}),
    "pokemon_revealed": frozenset({"pokemon_id"}),
    "stat_stage_changed": frozenset({"stat", "stages"}),
    "status_changed": frozenset({"status_id"}),
    "switched": frozenset({"pokemon_id"}),
    "turn_started": frozenset(),
}
_COMMON_FIELD_PATHS = frozenset({"/turn", "/phase", "/field/conditions"})
_VISIBLE_MEMBER_FIELD_RE = re.compile(
    r"^/(?:own|opponent)/(?:active|team/[0-9]+)/"
    r"(?:pokemon_id|level|status_id|stat_stages|types|item_id|ability_id|moves|"
    r"mega_evolved|hp_bar_range_millionths)$"
)
_SIMULATOR_EXACT_FIELD_RE = re.compile(
    r"^/(?:own|opponent)/(?:active|team/[0-9]+)/"
    r"(?:hp|max_hp|hp_fraction_millionths|stats|move_pp)$"
)
_ARTIFACT_REF_RE = re.compile(
    r"^(?P<capture>capture-[0-9a-f]{64})/"
    r"(?P<artifact>screenshot|ui-hierarchy)$"
)


def _field_path_allowed(path: str, source: "ObservationSource") -> bool:
    if path in _COMMON_FIELD_PATHS or _VISIBLE_MEMBER_FIELD_RE.fullmatch(path):
        return True
    return source is ObservationSource.SIMULATOR and _SIMULATOR_EXACT_FIELD_RE.fullmatch(path) is not None


def _artifact_capture_id(reference: str) -> str:
    match = _ARTIFACT_REF_RE.fullmatch(reference)
    if match is None:
        raise ValueError(
            "artifact evidence must be qualified as capture_id/screenshot or capture_id/ui-hierarchy"
        )
    return match.group("capture")


def _validate_hp_bar_range(field: GroundedField) -> None:
    if not field.path.endswith("/hp_bar_range_millionths"):
        return
    value = field.value
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(item, int) or isinstance(item, bool) for item in value)
    ):
        raise ValueError("HP-bar range must be a two-integer [lower, upper] value")
    lower, upper = value
    if not 0 <= lower <= upper <= 1_000_000:
        raise ValueError("HP-bar range must stay between 0 and 1,000,000")
    if (
        field.path.startswith("/opponent/")
        and lower == upper
        and lower not in {0, 1_000_000}
    ):
        raise ValueError("opponent HP-bar evidence cannot claim an ungrounded exact fraction")


class MaskStatus(str, Enum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ALL_ILLEGAL = "all_illegal"


class ObservationSource(str, Enum):
    SIMULATOR = "simulator"
    GROUNDED_CAPTURE = "grounded_capture"


@dataclass(frozen=True, slots=True)
class PublicEvent:
    sequence: int
    turn: int
    kind: str
    actor: str | None
    subject: str | None
    details: tuple[tuple[str, JsonScalar], ...]
    evidence_artifact_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.turn < 0:
            raise ValueError("public event sequence and turn must be non-negative")
        _require_stable_id(self.kind, "public event kind")
        if self.kind not in _EVENT_DETAIL_KEYS:
            raise ValueError("public event kind is outside the AI environment allowlist")
        if self.actor not in {None, "p1", "p2"}:
            raise ValueError("public event actor must be p1, p2, or null")
        if self.subject is not None:
            _require_stable_id(self.subject, "public event subject")
        keys = tuple(key for key, _ in self.details)
        _require_unique(keys, "public event detail keys")
        if not set(keys) <= _EVENT_DETAIL_KEYS[self.kind]:
            raise ValueError("public event details contain keys outside the kind allowlist")
        _require_unique(self.evidence_artifact_ids, "public event evidence IDs")


@dataclass(frozen=True, slots=True)
class LegalActionMask:
    status: MaskStatus
    request_id: str | None
    action_ids: tuple[str, ...]
    legal: tuple[bool, ...]
    source: ObservationSource
    evidence_artifact_ids: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if len(self.action_ids) != len(self.legal):
            raise ValueError("action_ids and legal mask must have equal lengths")
        _require_unique(self.action_ids, "action IDs")
        _require_unique(self.evidence_artifact_ids, "legal-mask evidence IDs")
        if self.source is ObservationSource.SIMULATOR and self.evidence_artifact_ids:
            raise ValueError("simulator legal masks cannot claim capture evidence")
        if self.status is MaskStatus.KNOWN:
            if not self.request_id or not self.action_ids or not any(self.legal):
                raise ValueError("known legal mask requires a request and at least one legal action")
            if self.reason is not None:
                raise ValueError("known legal mask must not carry an unknown reason")
            if (
                self.source is ObservationSource.GROUNDED_CAPTURE
                and not self.evidence_artifact_ids
            ):
                raise ValueError("grounded known legal masks require capture evidence")
        elif self.status is MaskStatus.UNKNOWN:
            if self.request_id is not None or self.action_ids or self.legal or not self.reason:
                raise ValueError("unknown legal mask must be empty and explain why")
            if self.source is not ObservationSource.GROUNDED_CAPTURE:
                raise ValueError("unknown legal masks belong to grounded capture observations")
        else:
            if not self.action_ids or any(self.legal) or not self.reason:
                raise ValueError(
                    "all-illegal masks require a non-empty action space, no legal actions, and a reason"
                )
            if (
                self.source is ObservationSource.GROUNDED_CAPTURE
                and not self.evidence_artifact_ids
            ):
                raise ValueError("grounded all-illegal masks require capture evidence")

    @classmethod
    def from_request(
        cls,
        request: DecisionRequest,
        action_space: tuple[str, ...],
    ) -> "LegalActionMask":
        _require_unique(action_space, "action space IDs")
        legal_ids = {action.action_id for action in request.legal_actions}
        missing = legal_ids - set(action_space)
        if missing:
            raise ValueError(f"action space is missing legal actions: {sorted(missing)}")
        return cls(
            status=MaskStatus.KNOWN,
            request_id=request.request_id,
            action_ids=action_space,
            legal=tuple(action_id in legal_ids for action_id in action_space),
            source=ObservationSource.SIMULATOR,
            evidence_artifact_ids=(),
        )

    @classmethod
    def unknown(cls, reason: str) -> "LegalActionMask":
        return cls(
            status=MaskStatus.UNKNOWN,
            request_id=None,
            action_ids=(),
            legal=(),
            source=ObservationSource.GROUNDED_CAPTURE,
            evidence_artifact_ids=(),
            reason=reason,
        )

    @classmethod
    def all_illegal(
        cls,
        action_space: tuple[str, ...],
        reason: str,
        *,
        request_id: str | None = None,
        source: ObservationSource = ObservationSource.SIMULATOR,
        evidence_artifact_ids: tuple[str, ...] = (),
    ) -> "LegalActionMask":
        _require_unique(action_space, "action space IDs")
        return cls(
            status=MaskStatus.ALL_ILLEGAL,
            request_id=request_id,
            action_ids=action_space,
            legal=tuple(False for _ in action_space),
            source=source,
            evidence_artifact_ids=evidence_artifact_ids,
            reason=reason,
        )

    @property
    def actionable(self) -> bool:
        return self.status is MaskStatus.KNOWN and any(self.legal)


@dataclass(frozen=True, slots=True)
class ObservationProvenance:
    source: ObservationSource
    capture_ids: tuple[str, ...]
    artifact_refs: tuple[str, ...]
    grounding_trace_id: str | None

    def __post_init__(self) -> None:
        _require_unique(self.capture_ids, "observation capture IDs")
        for capture_id in self.capture_ids:
            _require_capture_id(capture_id, "observation capture ID")
        _require_unique(self.artifact_refs, "observation artifact references")
        if self.source is ObservationSource.GROUNDED_CAPTURE:
            if not self.capture_ids or not self.artifact_refs or not self.grounding_trace_id:
                raise ValueError("grounded observations require capture, artifact, and trace IDs")
            capture_ids = set(self.capture_ids)
            if any(_artifact_capture_id(value) not in capture_ids for value in self.artifact_refs):
                raise ValueError("artifact references must bind to provenance capture IDs")
        elif self.capture_ids or self.artifact_refs or self.grounding_trace_id is not None:
            raise ValueError("simulator observations must not claim capture provenance")


@dataclass(frozen=True, slots=True)
class EnvObservation:
    """Observation draft; grounded actionability requires a validated wrapper."""

    schema_version: str
    observation_id: str
    battle_id: str
    ruleset_id: str
    viewer: str
    turn: int | None
    phase: str | None
    instant_fields: tuple[GroundedField, ...]
    public_history: tuple[PublicEvent, ...]
    legal_action_mask: LegalActionMask
    provenance: ObservationProvenance
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != "1.0.0":
            raise ValueError("only AI env observation schema 1.0.0 is supported")
        _require_stable_id(self.observation_id, "observation_id")
        _require_stable_id(self.battle_id, "battle_id")
        _require_stable_id(self.ruleset_id, "ruleset_id")
        if self.viewer not in {"p1", "p2"}:
            raise ValueError("viewer must be p1 or p2")
        if self.turn is not None and self.turn < 0:
            raise ValueError("turn must be non-negative or unknown")
        if self.phase is None and self.turn is not None:
            raise ValueError("known turn requires a known phase")
        if self.phase is not None:
            _require_stable_id(self.phase, "observation phase")
        _require_unique(tuple(value.path for value in self.instant_fields), "instant field paths")
        if any(
            not _field_path_allowed(value.path, self.provenance.source)
            for value in self.instant_fields
        ):
            raise ValueError("instant field path is outside the observation-source allowlist")
        for field in self.instant_fields:
            _validate_hp_bar_range(field)
        sequences = [value.sequence for value in self.public_history]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("public history sequences must be strictly increasing")
        _require_unique(self.blockers, "observation blockers")
        if self.legal_action_mask.source is not self.provenance.source:
            raise ValueError("legal-mask source must match observation provenance")

        if self.provenance.source is ObservationSource.SIMULATOR:
            if any(
                value.source.value != ObservationSource.SIMULATOR.value
                for value in self.instant_fields
            ):
                raise ValueError("simulator observations require simulator-sourced fields")
            if any(value.evidence_artifact_ids for value in self.public_history):
                raise ValueError("simulator public history cannot claim capture evidence")
        else:
            if any(
                value.source.value == ObservationSource.SIMULATOR.value
                for value in self.instant_fields
            ):
                raise ValueError("grounded observations cannot claim simulator-exact fields")
            if any(not value.evidence_artifact_ids for value in self.public_history):
                raise ValueError("grounded public history requires capture evidence")
            declared = set(self.provenance.artifact_refs)
            referenced = {
                artifact_id
                for field in self.instant_fields
                for artifact_id in field.artifact_ids
            }
            referenced.update(
                artifact_id
                for event in self.public_history
                for artifact_id in event.evidence_artifact_ids
            )
            referenced.update(self.legal_action_mask.evidence_artifact_ids)
            if not referenced <= declared:
                raise ValueError("observation evidence is not bound to provenance artifacts")
            known_fields = {
                field.path: field
                for field in self.instant_fields
                if field.status.value != "unknown"
            }
            if self.turn is not None and (
                "/turn" not in known_fields or known_fields["/turn"].value != self.turn
            ):
                raise ValueError("grounded known turn requires matching /turn evidence")
            if self.phase is not None and (
                "/phase" not in known_fields or known_fields["/phase"].value != self.phase
            ):
                raise ValueError("grounded known phase requires matching /phase evidence")
        if self.blockers and self.legal_action_mask.actionable:
            raise ValueError("blocked observations cannot expose an actionable mask")

    @property
    def actionable(self) -> bool:
        if self.provenance.source is ObservationSource.GROUNDED_CAPTURE:
            return False
        return not self.blockers and self.legal_action_mask.actionable

    def to_dict(self) -> dict[str, Any]:
        value = to_canonical_data(self)
        assert isinstance(value, dict)
        return value
