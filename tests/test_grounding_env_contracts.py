from __future__ import annotations

import json
from pathlib import Path

import pytest

from champions_sim.core import (
    ActionKind,
    DecisionKind,
    DecisionRequest,
    LegalAction,
    MoveId,
    PlayerId,
)
from champions_sim.grounding import (
    ConformanceCheck,
    ConformanceVerdict,
    EnvObservation,
    GroundedField,
    GroundingFrame,
    GroundingSource,
    GroundingStatus,
    GroundingTrace,
    GroundingTraceStatus,
    LegalActionMask,
    MaskStatus,
    ObservationProvenance,
    ObservationSource,
    PublicEvent,
)
from scripts.validate_sim01_bundle import validate_document_contract


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_1 = "capture-" + "1" * 64
CAPTURE_2 = "capture-" + "2" * 64
MANIFEST_HASH = "sha256:" + "a" * 64


def _schema(name: str) -> dict[str, object]:
    return json.loads((ROOT / "data/schemas" / name).read_text(encoding="utf-8"))


def _observed_field(
    *,
    path: str = "/turn",
    value: object = 3,
    artifact_ids: tuple[str, ...] = ("screenshot", "ui-hierarchy"),
) -> GroundedField:
    return GroundedField(
        path=path,
        status=GroundingStatus.OBSERVED,
        source=GroundingSource.UI_METADATA,
        value=value,
        confidence_ppm=1_000_000,
        artifact_ids=artifact_ids,
    )


def test_unknown_grounding_is_explicit_and_cannot_claim_a_value() -> None:
    unknown = GroundedField(
        path="/opponent/active/item_id",
        status=GroundingStatus.UNKNOWN,
        source=GroundingSource.SCREEN_REGION,
        value=None,
        confidence_ppm=0,
        artifact_ids=(),
        note="not revealed",
    )
    assert unknown.value is None

    with pytest.raises(ValueError, match="null value and zero confidence"):
        GroundedField(
            path="/opponent/active/item_id",
            status=GroundingStatus.UNKNOWN,
            source=GroundingSource.SCREEN_REGION,
            value="leftovers",
            confidence_ppm=0,
            artifact_ids=(),
        )


def test_grounding_trace_serializes_conformance_and_mismatch_statuses() -> None:
    match_frame = GroundingFrame(
        frame_id="frame-1",
        capture_id=CAPTURE_1,
        capture_manifest_hash=MANIFEST_HASH,
        observed_at="2026-07-13T00:00:00Z",
        fields=(_observed_field(),),
        conformance=(
            ConformanceCheck(
                path="/turn",
                verdict=ConformanceVerdict.MATCH,
                expected=3,
                observed=3,
                artifact_ids=("screenshot",),
            ),
        ),
    )
    trace = GroundingTrace(
        schema_version="1.0.0",
        trace_id="trace-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        reference_replay_hash="a" * 64,
        frames=(match_frame,),
        status=GroundingTraceStatus.CONFORMANT,
        blockers=(),
        local_research_only=True,
        distribution_allowed=False,
    )
    validate_document_contract(
        trace.to_dict(), _schema("grounding-trace.schema.json"), "grounding trace"
    )

    mismatch_frame = GroundingFrame(
        frame_id="frame-2",
        capture_id=CAPTURE_2,
        capture_manifest_hash=MANIFEST_HASH,
        observed_at="2026-07-13T00:00:01Z",
        fields=(_observed_field(),),
        conformance=(
            ConformanceCheck(
                path="/turn",
                verdict=ConformanceVerdict.MISMATCH,
                expected=2,
                observed=3,
                artifact_ids=("screenshot",),
            ),
        ),
    )
    nonconformant = GroundingTrace(
        schema_version="1.0.0",
        trace_id="trace-2",
        ruleset_id="ruleset-1",
        viewer="p1",
        reference_replay_hash=None,
        frames=(mismatch_frame,),
        status=GroundingTraceStatus.NONCONFORMANT,
        blockers=(),
        local_research_only=True,
        distribution_allowed=False,
    )
    validate_document_contract(
        nonconformant.to_dict(), _schema("grounding-trace.schema.json"), "grounding trace"
    )


def test_conformant_trace_requires_an_evidence_backed_match() -> None:
    with pytest.raises(ValueError, match="require capture evidence"):
        ConformanceCheck(
            path="/turn",
            verdict=ConformanceVerdict.MATCH,
            expected=1,
            observed=1,
            artifact_ids=(),
        )

    empty_frame = GroundingFrame(
        frame_id="frame-empty",
        capture_id=CAPTURE_1,
        capture_manifest_hash=MANIFEST_HASH,
        observed_at="2026-07-13T00:00:00Z",
        fields=(),
        conformance=(),
    )
    with pytest.raises(ValueError, match="evidence-backed matches"):
        GroundingTrace(
            schema_version="1.0.0",
            trace_id="trace-empty",
            ruleset_id="ruleset-1",
            viewer="p1",
            reference_replay_hash=None,
            frames=(empty_frame,),
            status=GroundingTraceStatus.CONFORMANT,
            blockers=(),
            local_research_only=True,
            distribution_allowed=False,
        )


def test_grounding_trace_rejects_conflicting_manifest_hash_for_same_capture() -> None:
    check = ConformanceCheck(
        path="/turn",
        verdict=ConformanceVerdict.MATCH,
        expected=1,
        observed=1,
        artifact_ids=("screenshot",),
    )
    frames = (
        GroundingFrame(
            frame_id="frame-binding-1",
            capture_id=CAPTURE_1,
            capture_manifest_hash="sha256:" + "a" * 64,
            observed_at="2026-07-13T00:00:00Z",
            fields=(),
            conformance=(check,),
        ),
        GroundingFrame(
            frame_id="frame-binding-2",
            capture_id=CAPTURE_1,
            capture_manifest_hash="sha256:" + "b" * 64,
            observed_at="2026-07-13T00:00:01Z",
            fields=(),
            conformance=(check,),
        ),
    )
    with pytest.raises(ValueError, match="multiple manifest hashes"):
        GroundingTrace(
            schema_version="1.0.0",
            trace_id="trace-binding-conflict",
            ruleset_id="ruleset-1",
            viewer="p1",
            reference_replay_hash=None,
            frames=frames,
            status=GroundingTraceStatus.CONFORMANT,
            blockers=(),
            local_research_only=True,
            distribution_allowed=False,
        )


def test_legal_mask_keeps_unknown_distinct_from_all_illegal() -> None:
    request = DecisionRequest(
        request_id="request-1",
        player=PlayerId.P1,
        kind=DecisionKind.ACTION,
        legal_actions=(
            LegalAction(
                action_id="move-1",
                kind=ActionKind.MOVE,
                move_id=MoveId("move-a"),
            ),
        ),
    )
    known = LegalActionMask.from_request(request, ("move-1", "move-2", "switch-1"))
    unknown = LegalActionMask.unknown("decision controls not grounded")

    assert known.status is MaskStatus.KNOWN
    assert known.legal == (True, False, False)
    assert known.actionable
    assert unknown.status is MaskStatus.UNKNOWN
    assert unknown.legal == ()
    assert not unknown.actionable


def test_ai_env_contract_carries_public_history_mask_and_provenance() -> None:
    unknown_field = GroundedField(
        path="/opponent/active/item_id",
        status=GroundingStatus.UNKNOWN,
        source=GroundingSource.SCREEN_REGION,
        value=None,
        confidence_ppm=0,
        artifact_ids=(),
    )
    observation = EnvObservation(
        schema_version="1.0.0",
        observation_id="observation-1",
        battle_id="battle-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        turn=1,
        phase="awaiting_decisions",
        instant_fields=(
            _observed_field(
                value=1,
                artifact_ids=(f"{CAPTURE_1}/screenshot", f"{CAPTURE_1}/ui-hierarchy")
            ),
            _observed_field(
                path="/phase",
                value="awaiting_decisions",
                artifact_ids=(f"{CAPTURE_1}/ui-hierarchy",),
            ),
            unknown_field,
        ),
        public_history=(
            PublicEvent(
                sequence=0,
                turn=1,
                kind="move_used",
                actor="p2",
                subject="opponent-active",
                details=(("move_id", "move-a"),),
                evidence_artifact_ids=(f"{CAPTURE_1}/screenshot",),
            ),
        ),
        legal_action_mask=LegalActionMask.unknown("decision controls not grounded"),
        provenance=ObservationProvenance(
            source=ObservationSource.GROUNDED_CAPTURE,
            capture_ids=(CAPTURE_1,),
            artifact_refs=(f"{CAPTURE_1}/screenshot", f"{CAPTURE_1}/ui-hierarchy"),
            grounding_trace_id="trace-1",
        ),
        blockers=("legal_action_mask_unknown",),
    )
    assert not observation.actionable
    validate_document_contract(
        observation.to_dict(),
        _schema("ai-env-observation.schema.json"),
        "AI environment observation",
    )


def test_blockers_cannot_coexist_with_actionable_mask_and_history_is_ordered() -> None:
    request = DecisionRequest(
        request_id="request-1",
        player=PlayerId.P1,
        kind=DecisionKind.ACTION,
        legal_actions=(
            LegalAction(
                action_id="move-1",
                kind=ActionKind.MOVE,
                move_id=MoveId("move-a"),
            ),
        ),
    )
    mask = LegalActionMask.from_request(request, ("move-1",))
    provenance = ObservationProvenance(
        source=ObservationSource.SIMULATOR,
        capture_ids=(),
        artifact_refs=(),
        grounding_trace_id=None,
    )
    base = dict(
        schema_version="1.0.0",
        observation_id="observation-1",
        battle_id="battle-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        turn=1,
        phase="awaiting_decisions",
        instant_fields=(),
        legal_action_mask=mask,
        provenance=provenance,
    )

    with pytest.raises(ValueError, match="blocked observations"):
        EnvObservation(public_history=(), blockers=("unsafe_to_act",), **base)

    with pytest.raises(ValueError, match="strictly increasing"):
        EnvObservation(
            public_history=(
                PublicEvent(2, 1, "move_used", "p1", None, ()),
                PublicEvent(1, 1, "damage", "p1", None, ()),
            ),
            blockers=(),
            **base,
        )


def test_env_rejects_unknown_paths_detail_keys_and_unbound_evidence() -> None:
    with pytest.raises(ValueError, match="detail.*allowlist"):
        PublicEvent(
            sequence=0,
            turn=1,
            kind="move_used",
            actor="p1",
            subject=None,
            details=(("private_damage_roll", 15),),
        )

    provenance = ObservationProvenance(
        source=ObservationSource.GROUNDED_CAPTURE,
        capture_ids=(CAPTURE_1,),
        artifact_refs=(f"{CAPTURE_1}/screenshot",),
        grounding_trace_id="trace-1",
    )
    base = dict(
        schema_version="1.0.0",
        observation_id="observation-adversarial",
        battle_id="battle-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        turn=None,
        phase=None,
        public_history=(),
        legal_action_mask=LegalActionMask.unknown("not grounded"),
        provenance=provenance,
        blockers=("not_grounded",),
    )
    with pytest.raises(ValueError, match="path.*allowlist"):
        EnvObservation(
            instant_fields=(
                _observed_field(
                    path="/complete_state/opponent/exact_hp",
                    value=73,
                    artifact_ids=(f"{CAPTURE_1}/screenshot",),
                ),
            ),
            **base,
        )

    with pytest.raises(ValueError, match="not bound"):
        EnvObservation(
            instant_fields=(
                _observed_field(
                    artifact_ids=(f"{CAPTURE_2}/screenshot",),
                ),
            ),
            **base,
        )


def test_grounded_capture_cannot_claim_simulator_exact_hp_fraction() -> None:
    provenance = ObservationProvenance(
        source=ObservationSource.GROUNDED_CAPTURE,
        capture_ids=(CAPTURE_1,),
        artifact_refs=(f"{CAPTURE_1}/screenshot",),
        grounding_trace_id="trace-1",
    )
    with pytest.raises(ValueError, match="path.*allowlist"):
        EnvObservation(
            schema_version="1.0.0",
            observation_id="observation-hp-leak",
            battle_id="battle-1",
            ruleset_id="ruleset-1",
            viewer="p1",
            turn=None,
            phase=None,
            instant_fields=(
                _observed_field(
                    path="/opponent/active/hp_fraction_millionths",
                    value=735_000,
                    artifact_ids=(f"{CAPTURE_1}/screenshot",),
                ),
            ),
            public_history=(),
            legal_action_mask=LegalActionMask.unknown("not grounded"),
            provenance=provenance,
            blockers=("not_grounded",),
        )

    with pytest.raises(ValueError, match="ungrounded exact fraction"):
        EnvObservation(
            schema_version="1.0.0",
            observation_id="observation-hp-range-spoof",
            battle_id="battle-1",
            ruleset_id="ruleset-1",
            viewer="p1",
            turn=None,
            phase=None,
            instant_fields=(
                _observed_field(
                    path="/opponent/active/hp_bar_range_millionths",
                    value=[735_000, 735_000],
                    artifact_ids=(f"{CAPTURE_1}/screenshot",),
                ),
            ),
            public_history=(),
            legal_action_mask=LegalActionMask.unknown("not grounded"),
            provenance=provenance,
            blockers=("not_grounded",),
        )


def test_simulator_env_may_preserve_its_exact_instantaneous_fraction() -> None:
    request = DecisionRequest(
        request_id="request-simulator",
        player=PlayerId.P1,
        kind=DecisionKind.ACTION,
        legal_actions=(
            LegalAction(
                action_id="move-1",
                kind=ActionKind.MOVE,
                move_id=MoveId("move-a"),
            ),
        ),
    )
    observation = EnvObservation(
        schema_version="1.0.0",
        observation_id="observation-simulator",
        battle_id="battle-1",
        ruleset_id="ruleset-1",
        viewer="p1",
        turn=1,
        phase="awaiting_decisions",
        instant_fields=(
            GroundedField(
                path="/own/active/hp_fraction_millionths",
                status=GroundingStatus.OBSERVED,
                source=GroundingSource.SIMULATOR,
                value=735_000,
                confidence_ppm=1_000_000,
                artifact_ids=(),
            ),
        ),
        public_history=(),
        legal_action_mask=LegalActionMask.from_request(request, ("move-1",)),
        provenance=ObservationProvenance(
            source=ObservationSource.SIMULATOR,
            capture_ids=(),
            artifact_refs=(),
            grounding_trace_id=None,
        ),
        blockers=(),
    )
    assert observation.actionable
    validate_document_contract(
        observation.to_dict(),
        _schema("ai-env-observation.schema.json"),
        "simulator AI environment observation",
    )
