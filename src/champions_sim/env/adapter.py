"""Policy-free deterministic reset/step adapter over :class:`BattleEngine`.

The adapter owns complete simulator state but returns only centrally filtered
``PlayerObservation`` values and an allowlisted public event history.  Replay
export is deliberately a separate, privileged operation because Replay v2 is
an unredacted record.
"""

from __future__ import annotations

from typing import Mapping

from champions_sim.core import (
    REPLAY_SCHEMA_VERSION,
    RNG_ALGORITHM_ID,
    SIMULATOR_VERSION,
    ActionSelection,
    BattleEvent,
    BattleEventKind,
    BattlePhase,
    BattleState,
    DecisionRequestSet,
    ExplicitRNG,
    PlayerId,
    ReplayBundle,
    ReplayInitialState,
    ReplayOutcome,
    ReplayRecord,
    ReplayRedaction,
    ReplayResult,
    ReplayStep,
    ReplayVisibility,
    TransitionResult,
    canonical_hash,
)
from champions_sim.engine import BattleEngine
from champions_sim.grounding import LegalActionMask, PublicEvent

from .models import (
    AI_ENV_ADAPTER_SCHEMA_VERSION,
    AI_ENV_ADAPTER_VERSION,
    NO_REWARD_MODEL_ID,
    EnvironmentScope,
    EnvironmentSnapshot,
    EnvironmentVersionIdentity,
    EvidenceStatus,
    JointChoice,
    ResetInfo,
    ResetResult,
    SealedEnvironmentInput,
    StepResult,
    TransitionInfo,
    rng_state_hash,
)


class EnvironmentStateError(RuntimeError):
    """The caller used an environment before reset or with stale lineage."""


class EnvironmentNotActionable(EnvironmentStateError):
    """The environment is fail-closed because trusted evidence is unavailable."""


class DeterministicBattleEnv:
    """One viewer's deterministic, policy-free interface to a battle engine.

    ``JointChoice`` covers every player currently requested by the engine.  It
    is supplied by a trusted multi-agent coordinator; this adapter never picks
    an action and never exposes the opponent's decision request to the viewer.
    """

    def __init__(self, engine: BattleEngine, viewer: PlayerId) -> None:
        self.engine = engine
        self.viewer = viewer
        self._sealed: SealedEnvironmentInput | None = None
        self._identity: EnvironmentVersionIdentity | None = None
        self._initial_rng: ExplicitRNG | None = None
        self._initialized: TransitionResult | None = None
        self._state: BattleState | None = None
        self._rng: ExplicitRNG | None = None
        self._requests: DecisionRequestSet | None = None
        self._public_history: tuple[PublicEvent, ...] = ()
        self._action_space: tuple[str, ...] = ()
        self._steps: list[ReplayStep] = []
        self._step_index = 0
        self._blockers: tuple[str, ...] = ()

    def reset(self, *, seed: int, sealed: SealedEnvironmentInput) -> ResetResult:
        """Start an isolated episode from an integrity-bound immutable input."""

        self._validate_bundle(sealed)
        initial_rng = ExplicitRNG.seeded(seed)
        episode_digest = canonical_hash(
            {
                "sealed_input_hash": sealed.sealed_input_hash,
                "seed": initial_rng.seed,
                "viewer": self.viewer.value,
            }
        )
        identity = EnvironmentVersionIdentity(
            adapter_schema_version=AI_ENV_ADAPTER_SCHEMA_VERSION,
            bundle=sealed.bundle,
            bundle_identity_hash=sealed.bundle.identity_hash,
            fixture_id=sealed.fixture.fixture_id,
            fixture_hash=sealed.fixture.fixture_hash,
            sealed_input_hash=sealed.sealed_input_hash,
            episode_id=f"episode:{episode_digest}",
            viewer=self.viewer,
            seed=initial_rng.seed,
            rng_algorithm_id=RNG_ALGORITHM_ID,
        )

        initialized = self.engine.initialize(sealed.fixture.initial_state, initial_rng)
        public_history = self._append_public_events((), initialized.events, initialized.state)

        # Assign only after initialization succeeds.  Every reset replaces all
        # mutable episode containers, so no history or replay step can leak.
        self._sealed = sealed
        self._identity = identity
        self._initial_rng = initial_rng
        self._initialized = initialized
        self._state = initialized.state
        self._rng = initialized.rng
        self._requests = initialized.next_decisions
        self._public_history = public_history
        self._action_space = self._with_current_viewer_actions(
            self._build_action_space(sealed.fixture.initial_state),
            initialized.next_decisions,
        )
        self._steps = []
        self._step_index = 0
        self._blockers = self._external_evidence_blockers(sealed)

        snapshot = self._snapshot()
        return ResetResult(
            schema_version=AI_ENV_ADAPTER_SCHEMA_VERSION,
            kind="reset",
            snapshot=snapshot,
            info=ResetInfo(
                reset_id=f"reset:{canonical_hash({'episode_id': identity.episode_id})}",
                initial_state_hash=canonical_hash(sealed.fixture.initial_state),
                initialized_state_hash=canonical_hash(initialized.state),
                initial_events_hash=canonical_hash(initialized.events),
                public_history_hash=canonical_hash(public_history),
                rng_seed=initial_rng.seed,
                rng_cursor_before=initial_rng.cursor,
                rng_cursor_after=initialized.rng.cursor,
                rng_state_hash_before=rng_state_hash(initial_rng),
                rng_state_hash_after=rng_state_hash(initialized.rng),
                reward_model_id=NO_REWARD_MODEL_ID,
            ),
        )

    def make_joint_choice(self, action_ids: Mapping[PlayerId, str]) -> JointChoice:
        """Bind caller-provided action IDs to the current engine request IDs."""

        self._require_reset()
        if self._requests is None:
            raise EnvironmentStateError("episode has no pending decision request")
        expected = {request.player for request in self._requests.requests}
        if set(action_ids) != expected:
            raise EnvironmentStateError("joint action IDs must cover every requested player")
        selections = tuple(
            ActionSelection(
                request_id=request.request_id,
                player=request.player,
                action_id=action_ids[request.player],
            )
            for request in sorted(self._requests.requests, key=lambda item: item.player.value)
        )
        commitment = self._decision_commitment()
        assert commitment is not None
        assert self._identity is not None
        return JointChoice(
            episode_id=self._identity.episode_id,
            step_index=self._step_index,
            decision_commitment=commitment,
            selections=selections,
        )

    def step(self, choice: JointChoice) -> StepResult:
        """Advance exactly one engine decision window with no reward policy."""

        self._require_reset()
        assert self._identity is not None
        assert self._state is not None
        assert self._rng is not None
        assert self._requests is not None or self._state.phase is BattlePhase.FINISHED
        if self._blockers:
            raise EnvironmentNotActionable("; ".join(self._blockers))
        if self._state.phase is BattlePhase.FINISHED or self._requests is None:
            raise EnvironmentStateError("episode is terminated")
        current_commitment = self._decision_commitment()
        if choice.episode_id != self._identity.episode_id:
            raise EnvironmentStateError("choice belongs to another episode")
        if choice.step_index != self._step_index:
            raise EnvironmentStateError("choice step_index is stale")
        if choice.decision_commitment != current_commitment:
            raise EnvironmentStateError("choice decision commitment is stale")

        state_before = self._state
        rng_before = self._rng
        requests_before = self._requests
        result = self.engine.advance(state_before, choice.selections, rng_before)
        replay_step = ReplayStep(
            requests=requests_before,
            selections=choice.selections,
            rng_before=rng_before,
            rng_after=result.rng,
            events=result.events,
            result_state_hash=canonical_hash(result.state),
            terminal=result.terminal,
            provisional_decision_ids=self.engine.ruleset.provisional_decision_ids,
        )
        history = self._append_public_events(self._public_history, result.events, result.state)

        self._steps.append(replay_step)
        self._state = result.state
        self._rng = result.rng
        self._requests = result.next_decisions
        self._public_history = history
        self._action_space = self._with_current_viewer_actions(
            self._action_space,
            result.next_decisions,
        )
        self._step_index += 1

        snapshot = self._snapshot()
        transition_payload = {
            "episode_id": self._identity.episode_id,
            "step_index": choice.step_index,
            "decision_commitment": choice.decision_commitment,
            "choice_hash": choice.choice_hash,
            "result_state_hash": canonical_hash(result.state),
            "rng_cursor_after": result.rng.cursor,
        }
        return StepResult(
            schema_version=AI_ENV_ADAPTER_SCHEMA_VERSION,
            kind="step",
            snapshot=snapshot,
            reward=None,
            terminated=result.terminal,
            truncated=False,
            info=TransitionInfo(
                transition_id=f"transition:{canonical_hash(transition_payload)}",
                state_hash_before=canonical_hash(state_before),
                state_hash_after=canonical_hash(result.state),
                decision_commitment_before=choice.decision_commitment,
                choice_hash=choice.choice_hash,
                events_hash=canonical_hash(result.events),
                public_history_hash=canonical_hash(history),
                rng_seed=result.rng.seed,
                rng_cursor_before=rng_before.cursor,
                rng_cursor_after=result.rng.cursor,
                rng_state_hash_before=rng_state_hash(rng_before),
                rng_state_hash_after=rng_state_hash(result.rng),
                reward_model_id=NO_REWARD_MODEL_ID,
                provisional_decision_ids=self._identity.bundle.provisional_decision_ids,
                source_manifest_ids=self._identity.bundle.source_manifest_ids,
            ),
        )

    def export_replay(self) -> ReplayRecord:
        """Export the completed unredacted Replay v2 record (privileged API)."""

        self._require_reset()
        assert self._sealed is not None
        assert self._identity is not None
        assert self._initial_rng is not None
        assert self._initialized is not None
        assert self._state is not None
        assert self._rng is not None
        if self._state.phase is not BattlePhase.FINISHED or not self._steps:
            raise EnvironmentStateError("Replay v2 export requires a completed episode")
        reason = self._result_reason(self._steps[-1].events)
        return ReplayRecord(
            schema_version=REPLAY_SCHEMA_VERSION,
            replay_id=f"{self._state.battle_id}:env:{self._identity.seed:016x}",
            bundle=ReplayBundle(
                simulator_version=SIMULATOR_VERSION,
                engine_semantics_version=self.engine.ruleset.engine_semantics_version,
                ruleset_id=self.engine.ruleset.ruleset_id,
                ruleset_content_hash=self.engine.ruleset.snapshot_hash,
                catalog_id=self.engine.catalog.catalog_id,
                catalog_content_hash=self.engine.catalog.snapshot_hash,
            ),
            rng_algorithm_id=RNG_ALGORITHM_ID,
            initial_rng=self._initial_rng,
            rng_after_initialization=self._initialized.rng,
            final_rng=self._rng,
            initial_state=ReplayInitialState.capture(self._sealed.fixture.initial_state),
            initial_events=self._initialized.events,
            initialized_state_hash=canonical_hash(self._initialized.state),
            steps=tuple(self._steps),
            result=ReplayResult(
                outcome=(
                    ReplayOutcome.PLAYER_WIN
                    if self._state.winner is not None
                    else ReplayOutcome.DRAW
                ),
                winner=self._state.winner,
                reason=reason,
            ),
            final_state_hash=canonical_hash(self._state),
            visibility=ReplayVisibility(
                contains_private_state=True,
                redaction=ReplayRedaction.NONE,
            ),
            provisional_decision_ids=self._identity.bundle.provisional_decision_ids,
            source_manifest_ids=self._identity.bundle.source_manifest_ids,
        )

    def _require_reset(self) -> None:
        if self._identity is None or self._state is None or self._rng is None:
            raise EnvironmentStateError("reset must be called before using the environment")

    def _validate_bundle(self, sealed: SealedEnvironmentInput) -> None:
        bundle = sealed.bundle
        expected_sources = tuple(
            sorted(
                {
                    self.engine.catalog.source_manifest_id,
                    *self.engine.ruleset.source_manifest_ids,
                }
            )
        )
        checks = (
            ("adapter_version", bundle.adapter_version, AI_ENV_ADAPTER_VERSION),
            ("simulator_version", bundle.simulator_version, SIMULATOR_VERSION),
            (
                "engine_semantics_version",
                bundle.engine_semantics_version,
                self.engine.ruleset.engine_semantics_version,
            ),
            ("catalog_id", bundle.catalog_id, self.engine.catalog.catalog_id),
            ("catalog_hash", bundle.catalog_hash, self.engine.catalog.snapshot_hash),
            ("ruleset_id", bundle.ruleset_id, str(self.engine.ruleset.ruleset_id)),
            ("ruleset_hash", bundle.ruleset_hash, self.engine.ruleset.snapshot_hash),
            ("source_manifest_ids", bundle.source_manifest_ids, expected_sources),
            (
                "provisional_decision_ids",
                bundle.provisional_decision_ids,
                self.engine.ruleset.provisional_decision_ids,
            ),
        )
        mismatches = [name for name, actual, expected in checks if actual != expected]
        if mismatches:
            raise ValueError(f"sealed environment bundle mismatches engine: {mismatches}")

    @staticmethod
    def _external_evidence_blockers(sealed: SealedEnvironmentInput) -> tuple[str, ...]:
        bundle = sealed.bundle
        if bundle.scope is EnvironmentScope.PURE_SIMULATOR_LOCAL:
            return ()
        blockers: list[str] = []
        if bundle.capability_status is not EvidenceStatus.VERIFIED:
            blockers.append("capability_evidence_not_verified")
        if bundle.grounding_status is not EvidenceStatus.VERIFIED:
            blockers.append("grounding_evidence_not_verified")
        return tuple(blockers)

    def _build_action_space(self, initial_state: BattleState) -> tuple[str, ...]:
        side = initial_state.side(self.viewer)
        action_ids: set[str] = {f"{self.viewer.value}:forfeit"}
        for member in side.team:
            action_ids.add(f"{self.viewer.value}:switch:{member.instance_id}")
            for slot in member.moves:
                action_ids.add(f"{self.viewer.value}:move:{slot.move_id}")
                if member.mega_evolution_profile is not None:
                    action_ids.add(
                        f"{self.viewer.value}:move:{slot.move_id}:mega:"
                        f"{member.mega_evolution_profile.target_pokemon_id}"
                    )
        return tuple(sorted(action_ids))

    def _with_current_viewer_actions(
        self,
        action_space: tuple[str, ...],
        requests: DecisionRequestSet | None,
    ) -> tuple[str, ...]:
        """Keep semantic action IDs stable while accepting new decision kinds."""

        values = set(action_space)
        if requests is not None:
            request = requests.for_player(self.viewer)
            if request is not None:
                values.update(action.action_id for action in request.legal_actions)
        return tuple(sorted(values))

    def _decision_commitment(self) -> str | None:
        if self._identity is None or self._state is None or self._requests is None:
            return None
        viewer_request = self._requests.for_player(self.viewer)
        # Commit only to the viewer-visible request boundary.  Hashing the full
        # request set here would create a dictionary oracle for hidden moves.
        return canonical_hash(
            {
                "episode_id": self._identity.episode_id,
                "step_index": self._step_index,
                "battle_id": self._state.battle_id,
                "turn": self._state.turn,
                "phase": self._state.phase,
                "viewer_request_id": (
                    viewer_request.request_id if viewer_request is not None else None
                ),
            }
        )

    def _snapshot(self) -> EnvironmentSnapshot:
        assert self._identity is not None
        assert self._state is not None
        viewer_request = (
            self._requests.for_player(self.viewer) if self._requests is not None else None
        )
        if self._blockers:
            mask = LegalActionMask.all_illegal(
                self._action_space,
                ";".join(self._blockers),
                request_id=viewer_request.request_id if viewer_request else None,
            )
        elif self._state.phase is BattlePhase.FINISHED:
            mask = LegalActionMask.all_illegal(self._action_space, "episode_terminated")
        elif viewer_request is None:
            mask = LegalActionMask.all_illegal(
                self._action_space,
                "viewer_not_requested",
            )
        else:
            mask = LegalActionMask.from_request(viewer_request, self._action_space)
        return EnvironmentSnapshot(
            schema_version=AI_ENV_ADAPTER_SCHEMA_VERSION,
            identity=self._identity,
            step_index=self._step_index,
            observation=self._state.observation_for(self.viewer),
            public_history=self._public_history,
            legal_action_mask=mask,
            decision_commitment=self._decision_commitment(),
            actionable=not self._blockers and mask.actionable,
            blockers=self._blockers,
        )

    @staticmethod
    def _append_public_events(
        history: tuple[PublicEvent, ...],
        events: tuple[BattleEvent, ...],
        state: BattleState,
    ) -> tuple[PublicEvent, ...]:
        output = list(history)
        current_turn = state.turn if history else 0
        for event in events:
            details = dict(event.details)
            if event.kind is BattleEventKind.TURN_STARTED:
                raw_turn = details.get("turn")
                if isinstance(raw_turn, int):
                    current_turn = raw_turn
            converted = DeterministicBattleEnv._public_event(
                len(output), current_turn, event, details, state
            )
            if converted is not None:
                output.append(converted)
        return tuple(output)

    @staticmethod
    def _public_event(
        sequence: int,
        turn: int,
        event: BattleEvent,
        details: dict[str, object],
        state: BattleState,
    ) -> PublicEvent | None:
        mapping: dict[BattleEventKind, tuple[str, dict[str, object]]] = {
            BattleEventKind.BATTLE_STARTED: (
                "battle_started",
                {"ruleset_id": str(state.ruleset_id)},
            ),
            BattleEventKind.TURN_STARTED: ("turn_started", {}),
            BattleEventKind.REVEALED: (
                "pokemon_revealed",
                {"pokemon_id": details.get("pokemon_id")},
            ),
            BattleEventKind.MOVE_USED: (
                "move_used",
                {"move_id": details.get("move_id")},
            ),
            BattleEventKind.MOVE_MISSED: (
                "move_missed",
                {"move_id": details.get("move_id")},
            ),
            BattleEventKind.ACTION_FAILED: (
                "action_failed",
                {"reason": details.get("reason")},
            ),
            BattleEventKind.CRITICAL_HIT: ("critical_hit", {}),
            BattleEventKind.SWITCHED: (
                "switched",
                {"pokemon_id": DeterministicBattleEnv._pokemon_id(state, event.subject)},
            ),
            BattleEventKind.DAMAGE: ("damage", {"cause": details.get("source")}),
            BattleEventKind.HEALED: ("healed", {"cause": details.get("source")}),
            BattleEventKind.FAINTED: ("fainted", {}),
            BattleEventKind.ABILITY_TRIGGERED: (
                "ability_revealed",
                {"ability_id": details.get("ability_id")},
            ),
            BattleEventKind.ITEM_TRIGGERED: (
                "item_revealed",
                {"item_id": details.get("item_id")},
            ),
            BattleEventKind.ITEM_CONSUMED: (
                "item_consumed",
                {"item_id": details.get("item_id")},
            ),
            BattleEventKind.MEGA_EVOLVED: (
                "mega_evolved",
                {
                    "pokemon_id": details.get("from_pokemon_id"),
                    "mega_pokemon_id": details.get("to_pokemon_id"),
                },
            ),
            BattleEventKind.STATUS_CHANGED: (
                "status_changed",
                {"status_id": details.get("new_status")},
            ),
            BattleEventKind.STAT_STAGE_CHANGED: (
                "stat_stage_changed",
                {"stat": details.get("stat"), "stages": details.get("new")},
            ),
            BattleEventKind.BATTLE_ENDED: (
                "battle_ended",
                {"winner": details.get("winner")},
            ),
        }
        item = mapping.get(event.kind)
        if item is None:
            return None
        kind, safe_details = item
        canonical_details = tuple(
            (key, value) for key, value in safe_details.items() if value is not None
        )
        return PublicEvent(
            sequence=sequence,
            turn=turn,
            kind=kind,
            actor=event.actor.value if event.actor is not None else None,
            subject=str(event.subject) if event.subject is not None else None,
            details=canonical_details,  # type: ignore[arg-type]
        )

    @staticmethod
    def _pokemon_id(state: BattleState, subject: object | None) -> str | None:
        if subject is None:
            return None
        for side in state.sides:
            for pokemon in side.team:
                if pokemon.instance_id == subject:
                    return str(pokemon.pokemon_id)
        return None

    @staticmethod
    def _result_reason(events: tuple[BattleEvent, ...]) -> str:
        for event in reversed(events):
            if event.kind is BattleEventKind.BATTLE_ENDED:
                reason = dict(event.details).get("reason")
                if isinstance(reason, str) and reason:
                    return reason
        raise EnvironmentStateError("terminal transition lacks a battle-ended reason")
