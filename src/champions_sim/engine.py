"""Deterministic SIM-01 battle transition engine.

The engine is intentionally bounded by the fixture catalog.  It resolves no
network data, LLM output, wall clock, UI coordinate, or global RNG state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Iterable, Mapping

from .catalog import (
    CatalogSnapshot,
    MegaEvolutionDefinition,
    MoveDefinition,
    RuleSetSnapshot,
    SnapshotValidationError,
    validate_mega_stat_profile,
    validate_snapshot_pair,
)
from .core import (
    ActionKind,
    ActionSelection,
    BattleEvent,
    BattleEventKind,
    BattlePhase,
    BattleState,
    DecisionKind,
    DecisionRequest,
    DecisionRequestSet,
    ExplicitRNG,
    LegalAction,
    MoveId,
    MoveSlotState,
    PlayerId,
    PokemonInstanceId,
    PokemonState,
    SideState,
    StatStages,
    TransitionResult,
    UnsupportedMechanic,
)
from .damage import DamageCategory, DamageInput, DamageStats, calculate_damage


class IllegalAction(ValueError):
    """Raised when submitted decisions do not match the current request set."""


_SUPPORTED_MOVE_EFFECTS = frozenset(
    {
        "damage",
        "damage_drain",
        "damage_secondary_flinch",
        "damage_secondary_stage",
        "damage_secondary_status",
        "heal_self",
        "inflict_status",
        "raise_self",
    }
)
_SUPPORTED_ABILITIES = frozenset(
    {"rough_skin", "natural_cure", "technician", "intimidate", "overgrow", "blaze"}
)
_SUPPORTED_ITEMS = frozenset(
    {"leftovers", "sitrus_berry", "focus_sash", "mega_stone"}
)
_SUPPORTED_STATUSES = frozenset({"burn", "poison"})
_SUPPORTED_VOLATILE_STATUSES = frozenset({"flinch"})
_STAGE_FIELDS = {
    "atk": "attack",
    "def": "defense",
    "spa": "special_attack",
    "spd": "special_defense",
    "spe": "speed",
    "accuracy": "accuracy",
    "evasion": "evasion",
}


@dataclass
class _EventLog:
    events: list[BattleEvent]

    @classmethod
    def empty(cls) -> "_EventLog":
        return cls([])

    def add(
        self,
        kind: BattleEventKind,
        *,
        actor: PlayerId | None = None,
        subject: PokemonInstanceId | None = None,
        details: Mapping[str, str | int | bool | None] | None = None,
    ) -> None:
        pairs = tuple(sorted((details or {}).items()))
        self.events.append(
            BattleEvent(
                sequence=len(self.events),
                kind=kind,
                actor=actor,
                subject=subject,
                details=pairs,
            )
        )


class BattleEngine:
    """Resolve one deterministic decision window at a time."""

    def __init__(self, catalog: CatalogSnapshot, ruleset: RuleSetSnapshot) -> None:
        validate_snapshot_pair(catalog, ruleset)
        if ruleset.critical_multiplier != Fraction(3, 2):
            raise UnsupportedMechanic(
                "critical_multiplier",
                ruleset_id=ruleset.ruleset_id,
                context=str(ruleset.critical_multiplier),
            )
        self.catalog = catalog
        self.ruleset = ruleset
        self._validate_catalog_effects()

    def initialize(self, state: BattleState, rng: ExplicitRNG) -> TransitionResult:
        self._validate_state_mechanics(state)
        if state.phase is not BattlePhase.TEAM_PREVIEW or state.turn != 0:
            raise ValueError("initialize requires the fixture TEAM_PREVIEW state")
        log = _EventLog.empty()
        log.add(BattleEventKind.BATTLE_STARTED, details={"battle_id": state.battle_id})
        working = state
        for player in (PlayerId.P1, PlayerId.P2):
            working = self._reveal_active(working, player, log)
        for player in (PlayerId.P1, PlayerId.P2):
            working = self._trigger_switch_in_ability(working, player, log)
        working = replace(working, turn=1, phase=BattlePhase.AWAITING_DECISIONS)
        log.add(BattleEventKind.TURN_STARTED, details={"turn": 1})
        requests = self.required_decisions(working)
        return TransitionResult(
            state=working,
            events=tuple(log.events),
            next_decisions=requests,
            rng=rng,
            terminal=False,
            winner=None,
        )

    def required_decisions(self, state: BattleState) -> DecisionRequestSet | None:
        self._validate_state_mechanics(state)
        if state.phase is BattlePhase.FINISHED:
            return None
        if state.phase is BattlePhase.AWAITING_DECISIONS:
            requests = tuple(
                DecisionRequest(
                    request_id=f"turn:{state.turn}:{player.value}",
                    player=player,
                    kind=DecisionKind.ACTION,
                    legal_actions=self.legal_actions(state, player, DecisionKind.ACTION),
                )
                for player in (PlayerId.P1, PlayerId.P2)
            )
            return DecisionRequestSet(requests)
        if state.phase is BattlePhase.FORCED_SWITCH:
            requests: list[DecisionRequest] = []
            for player in (PlayerId.P1, PlayerId.P2):
                if state.side(player).active.fainted:
                    legal = self.legal_actions(state, player, DecisionKind.FORCED_SWITCH)
                    if legal:
                        requests.append(
                            DecisionRequest(
                                request_id=f"forced:{state.turn}:{player.value}",
                                player=player,
                                kind=DecisionKind.FORCED_SWITCH,
                                legal_actions=legal,
                            )
                        )
            return DecisionRequestSet(tuple(requests)) if requests else None
        raise ValueError(f"state phase does not accept decisions: {state.phase.value}")

    def legal_actions(
        self,
        state: BattleState,
        player: PlayerId,
        kind: DecisionKind = DecisionKind.ACTION,
    ) -> tuple[LegalAction, ...]:
        side = state.side(player)
        switches = tuple(
            LegalAction(
                action_id=f"{player.value}:switch:{pokemon.instance_id}",
                kind=ActionKind.SWITCH,
                switch_to=pokemon.instance_id,
            )
            for pokemon in side.team
            if pokemon.instance_id != side.active_instance_id and not pokemon.fainted
        )
        if kind is DecisionKind.FORCED_SWITCH:
            return switches
        active = side.active
        moves = tuple(
            LegalAction(
                action_id=f"{player.value}:move:{slot.move_id}",
                kind=ActionKind.MOVE,
                move_id=slot.move_id,
            )
            for slot in active.moves
            if slot.pp > 0 and not active.fainted
        )
        mega_definition = self._eligible_mega_evolution(state, player)
        mega_moves = (
            tuple(
                LegalAction(
                    action_id=(
                        f"{player.value}:move:{slot.move_id}:mega:"
                        f"{mega_definition.mega_pokemon_id}"
                    ),
                    kind=ActionKind.MOVE,
                    move_id=slot.move_id,
                )
                for slot in active.moves
                if slot.pp > 0 and not active.fainted
            )
            if mega_definition is not None
            else ()
        )
        if not active.fainted and not moves:
            # Struggle has its own recoil and targeting contract. Omitting it
            # from the action set would silently change the game, so SIM-01
            # rejects this state until that mechanic is implemented.
            raise UnsupportedMechanic(
                "struggle",
                ruleset_id=self.ruleset.ruleset_id,
                context=str(active.instance_id),
            )
        forfeit = LegalAction(
            action_id=f"{player.value}:forfeit",
            kind=ActionKind.FORFEIT,
        )
        return moves + mega_moves + switches + (forfeit,)

    def advance(
        self,
        state: BattleState,
        selections: Iterable[ActionSelection],
        rng: ExplicitRNG,
    ) -> TransitionResult:
        requests = self.required_decisions(state)
        if requests is None:
            raise IllegalAction("the battle is not awaiting decisions")
        chosen = self._validate_selections(requests, tuple(selections))
        if state.phase is BattlePhase.AWAITING_DECISIONS:
            return self._resolve_turn(state, chosen, rng)
        if state.phase is BattlePhase.FORCED_SWITCH:
            return self._resolve_forced_switches(state, chosen, rng)
        raise IllegalAction(f"unsupported decision phase: {state.phase.value}")

    def _resolve_turn(
        self,
        state: BattleState,
        chosen: dict[PlayerId, LegalAction],
        rng: ExplicitRNG,
    ) -> TransitionResult:
        log = _EventLog.empty()
        forfeits = {player for player, action in chosen.items() if action.kind is ActionKind.FORFEIT}
        if forfeits:
            if len(forfeits) == 2:
                return self._finish(state, None, rng, log, reason="double_forfeit")
            loser = next(iter(forfeits))
            return self._finish(state, loser.opponent, rng, log, reason="forfeit")

        working = replace(state, phase=BattlePhase.RESOLVING)
        working = self._prepare_mega_evolutions(working, chosen, log)
        ordered, rng = self._order_actions(working, chosen, rng, log)
        for index, (player, action) in enumerate(ordered):
            remaining = {future_player for future_player, _ in ordered[index + 1 :]}
            if action.kind is ActionKind.SWITCH:
                assert action.switch_to is not None
                working = self._switch(working, player, action.switch_to, log, forced=False)
            elif action.kind is ActionKind.MOVE:
                working, rng = self._execute_move(working, player, action, remaining, rng, log)
            else:
                raise IllegalAction(f"unsupported turn action: {action.kind.value}")

        working = self._clear_flinch(working)
        working = self._resolve_end_turn(working, log)
        log.add(BattleEventKind.TURN_ENDED, details={"turn": state.turn})
        return self._after_resolution(working, rng, log)

    def _resolve_forced_switches(
        self,
        state: BattleState,
        chosen: dict[PlayerId, LegalAction],
        rng: ExplicitRNG,
    ) -> TransitionResult:
        log = _EventLog.empty()
        working = state
        # Order is deliberately deterministic and registered as provisional.
        for player in (PlayerId.P1, PlayerId.P2):
            action = chosen.get(player)
            if action is None:
                continue
            if action.kind is not ActionKind.SWITCH or action.switch_to is None:
                raise IllegalAction("forced decisions only accept switches")
            working = self._switch(working, player, action.switch_to, log, forced=True)
        working = replace(
            working,
            turn=state.turn + 1,
            phase=BattlePhase.AWAITING_DECISIONS,
        )
        log.add(BattleEventKind.TURN_STARTED, details={"turn": working.turn})
        return TransitionResult(
            state=working,
            events=tuple(log.events),
            next_decisions=self.required_decisions(working),
            rng=rng,
            terminal=False,
            winner=None,
        )

    def _order_actions(
        self,
        state: BattleState,
        chosen: dict[PlayerId, LegalAction],
        rng: ExplicitRNG,
        log: _EventLog,
    ) -> tuple[list[tuple[PlayerId, LegalAction]], ExplicitRNG]:
        left = (PlayerId.P1, chosen[PlayerId.P1])
        right = (PlayerId.P2, chosen[PlayerId.P2])
        left_key = self._order_key(state, *left)
        right_key = self._order_key(state, *right)
        if left_key > right_key:
            ordered = [left, right]
        elif right_key > left_key:
            ordered = [right, left]
        else:
            draw, rng = self._draw(rng, 2, "speed_tie", log)
            ordered = [left, right] if draw == 0 else [right, left]
        for position, (player, action) in enumerate(ordered):
            log.add(
                BattleEventKind.ACTION_ORDERED,
                actor=player,
                subject=state.side(player).active_instance_id,
                details={"action_id": action.action_id, "position": position},
            )
        return ordered, rng

    def _eligible_mega_evolution(
        self,
        state: BattleState,
        player: PlayerId,
    ) -> MegaEvolutionDefinition | None:
        if "mega_evolution" not in self.ruleset.supported_mechanics:
            return None
        side = state.side(player)
        if any(pokemon.mega_evolved for pokemon in side.team):
            return None
        active = side.active
        if active.fainted or active.item_id is None or active.mega_evolved:
            return None
        try:
            definition = self.catalog.mega_evolution(
                active.pokemon_id,
                active.item_id,
            )
        except KeyError:
            return None
        if active.mega_evolution_profile is None:
            raise UnsupportedMechanic(
                "mega_evolution_stat_profile",
                ruleset_id=self.ruleset.ruleset_id,
                context=str(active.instance_id),
            )
        return definition

    def _mega_definition_for_action(
        self,
        state: BattleState,
        player: PlayerId,
        action: LegalAction,
    ) -> MegaEvolutionDefinition | None:
        definition = self._eligible_mega_evolution(state, player)
        if definition is None or action.kind is not ActionKind.MOVE:
            return None
        expected = (
            f"{player.value}:move:{action.move_id}:mega:"
            f"{definition.mega_pokemon_id}"
        )
        return definition if action.action_id == expected else None

    def _prepare_mega_evolutions(
        self,
        state: BattleState,
        chosen: Mapping[PlayerId, LegalAction],
        log: _EventLog,
    ) -> BattleState:
        """Apply explicit Mega choices before move ordering and resolution."""

        working = state
        requested = tuple(
            (player, definition)
            for player in (PlayerId.P1, PlayerId.P2)
            if (
                definition := self._mega_definition_for_action(
                    state,
                    player,
                    chosen[player],
                )
            )
            is not None
        )
        if len(requested) > 1:
            # Champions-specific ordering of simultaneous transformations and
            # newly acquired ability triggers is not grounded yet.  Never
            # encode tuple/P1 order as battle semantics by accident.
            raise UnsupportedMechanic(
                "mega_evolution:simultaneous_order",
                ruleset_id=self.ruleset.ruleset_id,
                context=f"turn:{state.turn}",
            )
        for player, definition in requested:
            active = working.side(player).active
            profile = active.mega_evolution_profile
            if profile is None or profile.stats.max_hp != active.stats.max_hp:
                raise UnsupportedMechanic(
                    "mega_evolution_stat_profile",
                    ruleset_id=self.ruleset.ruleset_id,
                    context=str(active.instance_id),
                )
            transformed = replace(
                active,
                pokemon_id=definition.mega_pokemon_id,
                stats=profile.stats,
                types=definition.types,
                ability_id=definition.ability_id,
                item_revealed_to_opponent=True,
                ability_revealed_to_opponent=True,
                mega_evolved=True,
            )
            working = self._put_pokemon(working, player, transformed)
            log.add(
                BattleEventKind.MEGA_EVOLVED,
                actor=player,
                subject=transformed.instance_id,
                details={
                    "ability_id": str(definition.ability_id),
                    "from_pokemon_id": str(active.pokemon_id),
                    "item_id": str(definition.required_item_id),
                    "to_pokemon_id": str(definition.mega_pokemon_id),
                },
            )
            working = self._trigger_switch_in_ability(working, player, log)
        return working

    def _order_key(
        self,
        state: BattleState,
        player: PlayerId,
        action: LegalAction,
    ) -> tuple[int, int]:
        if action.kind is ActionKind.SWITCH:
            return (6, self._effective_speed(state.side(player).active))
        if action.kind is ActionKind.MOVE:
            assert action.move_id is not None
            move = self.catalog.move(action.move_id)
            return (move.priority, self._effective_speed(state.side(player).active))
        return (-100, 0)

    def _execute_move(
        self,
        state: BattleState,
        player: PlayerId,
        action: LegalAction,
        remaining_players: set[PlayerId],
        rng: ExplicitRNG,
        log: _EventLog,
    ) -> tuple[BattleState, ExplicitRNG]:
        actor = state.side(player).active
        if actor.fainted:
            log.add(
                BattleEventKind.ACTION_FAILED,
                actor=player,
                subject=actor.instance_id,
                details={"reason": "actor_fainted"},
            )
            return state, rng
        if "flinch" in actor.volatile_statuses:
            actor = replace(
                actor,
                volatile_statuses=tuple(value for value in actor.volatile_statuses if value != "flinch"),
            )
            state = self._put_pokemon(state, player, actor)
            log.add(
                BattleEventKind.ACTION_FAILED,
                actor=player,
                subject=actor.instance_id,
                details={"reason": "flinch"},
            )
            return state, rng
        assert action.move_id is not None
        move = self.catalog.move(action.move_id)
        actor, old_pp, new_pp = self._consume_pp(actor, move.move_id)
        state = self._put_pokemon(state, player, actor)
        log.add(
            BattleEventKind.MOVE_USED,
            actor=player,
            subject=actor.instance_id,
            details={"move_id": str(move.move_id)},
        )
        log.add(
            BattleEventKind.PP_CHANGED,
            actor=player,
            subject=actor.instance_id,
            details={"move_id": str(move.move_id), "old_pp": old_pp, "new_pp": new_pp},
        )
        effect_kind = str(move.effect["kind"])
        if (
            effect_kind not in {"raise_self", "heal_self"}
            and state.side(player.opponent).active.fainted
        ):
            # In singles, a replacement is chosen after the queued turn has
            # finished. A remaining target-directed move still spends PP but
            # has no target and must not consume accuracy/damage RNG.
            log.add(
                BattleEventKind.ACTION_FAILED,
                actor=player,
                subject=actor.instance_id,
                details={"move_id": str(move.move_id), "reason": "no_target"},
            )
            return state, rng
        hit, rng = self._move_hits(state, player, move, rng, log)
        if not hit:
            log.add(
                BattleEventKind.MOVE_MISSED,
                actor=player,
                subject=actor.instance_id,
                details={"move_id": str(move.move_id)},
            )
            return state, rng

        if effect_kind == "raise_self":
            state = self._apply_stage_changes(
                state, player, player, move.effect["stages"], log, source=str(move.move_id)
            )
            return state, rng
        if effect_kind == "heal_self":
            state = self._heal_fraction(
                state,
                player,
                int(move.effect["numerator"]),
                int(move.effect["denominator"]),
                log,
                source=str(move.move_id),
            )
            return state, rng
        if effect_kind == "inflict_status":
            state = self._inflict_status(
                state, player.opponent, str(move.effect["status"]), log, source=str(move.move_id)
            )
            return state, rng

        target = state.side(player.opponent).active
        if target.fainted:
            return state, rng
        critical_draw, rng = self._draw(
            rng,
            self.ruleset.critical_chance.denominator,
            "critical_hit",
            log,
            actor=player,
            subject=actor.instance_id,
        )
        critical = critical_draw < self.ruleset.critical_chance.numerator
        roll_index, rng = self._draw(
            rng,
            len(self.ruleset.damage_rolls),
            "damage_roll",
            log,
            actor=player,
            subject=target.instance_id,
        )
        state, damage = self._deal_move_damage(
            state,
            player,
            move,
            roll_index,
            critical,
            log,
        )
        if critical and damage > 0:
            log.add(
                BattleEventKind.CRITICAL_HIT,
                actor=player,
                subject=target.instance_id,
                details={"move_id": str(move.move_id)},
            )

        target = state.side(player.opponent).active
        if damage > 0:
            # Drain is based on damage actually dealt and still resolves when
            # that damage knocks the target out. Secondary effects do not.
            if effect_kind == "damage_drain":
                state = self._heal_amount(
                    state,
                    player,
                    max(1, damage * int(move.effect["numerator"]) // int(move.effect["denominator"])),
                    log,
                    source=str(move.move_id),
                )
            elif not target.fainted and effect_kind == "damage_secondary_status":
                occurred, rng = self._secondary_occurs(rng, move, log, player, target.instance_id)
                if occurred:
                    state = self._inflict_status(
                        state,
                        player.opponent,
                        str(move.effect["status"]),
                        log,
                        source=str(move.move_id),
                    )
            elif not target.fainted and effect_kind == "damage_secondary_stage":
                occurred, rng = self._secondary_occurs(rng, move, log, player, target.instance_id)
                if occurred:
                    target_player = player.opponent if move.effect.get("target") == "opponent" else player
                    state = self._apply_stage_changes(
                        state,
                        player,
                        target_player,
                        move.effect["stages"],
                        log,
                        source=str(move.move_id),
                    )
            elif (
                not target.fainted
                and effect_kind == "damage_secondary_flinch"
                and player.opponent in remaining_players
            ):
                occurred, rng = self._secondary_occurs(rng, move, log, player, target.instance_id)
                if occurred:
                    state = self._add_volatile(state, player.opponent, "flinch", log)

        if move.contact and damage > 0:
            state = self._trigger_rough_skin(state, player, log)
        return state, rng

    def _move_hits(
        self,
        state: BattleState,
        player: PlayerId,
        move: MoveDefinition,
        rng: ExplicitRNG,
        log: _EventLog,
    ) -> tuple[bool, ExplicitRNG]:
        if move.accuracy is None:
            return True, rng
        actor = state.side(player).active
        target = state.side(player.opponent).active
        stage = max(-6, min(6, actor.stat_stages.accuracy - target.stat_stages.evasion))
        modifier = Fraction(stage + 3, 3) if stage >= 0 else Fraction(3, 3 - stage)
        chance = min(Fraction(1, 1), Fraction(move.accuracy, 100) * modifier)
        draw, next_rng = self._draw(
            rng,
            chance.denominator,
            "accuracy",
            log,
            actor=player,
            subject=target.instance_id,
        )
        return draw < chance.numerator, next_rng

    def _deal_move_damage(
        self,
        state: BattleState,
        player: PlayerId,
        move: MoveDefinition,
        roll_index: int,
        critical: bool,
        log: _EventLog,
    ) -> tuple[BattleState, int]:
        actor = state.side(player).active
        target = state.side(player.opponent).active
        if move.power is None or move.category not in {"physical", "special"}:
            raise UnsupportedMechanic(
                "ordinary_damage_contract",
                ruleset_id=self.ruleset.ruleset_id,
                context=str(move.move_id),
            )
        power = move.power
        actor, power = self._apply_offensive_ability(state, player, actor, move, power, log)
        state = self._put_pokemon(state, player, actor)
        result = calculate_damage(
            DamageInput(
                level=actor.level,
                power=power,
                category=DamageCategory(move.category),
                attacker=DamageStats(
                    attack=actor.stats.attack,
                    defense=actor.stats.defense,
                    special_attack=actor.stats.special_attack,
                    special_defense=actor.stats.special_defense,
                ),
                defender=DamageStats(
                    attack=target.stats.attack,
                    defense=target.stats.defense,
                    special_attack=target.stats.special_attack,
                    special_defense=target.stats.special_defense,
                ),
                attack_rank=(
                    actor.stat_stages.attack
                    if move.category == "physical"
                    else actor.stat_stages.special_attack
                ),
                defense_rank=(
                    target.stat_stages.defense
                    if move.category == "physical"
                    else target.stat_stages.special_defense
                ),
                stab=move.type_id in actor.types,
                type_effectiveness=self.catalog.type_effectiveness(move.type_id, target.types),
                critical=critical,
                burn_physical_modifier=(
                    move.category == "physical" and actor.status_id == "burn"
                ),
                defender_hp=target.hp,
            )
        )
        damage = result.rolls[roll_index]
        state, damage = self._apply_focus_sash(state, player.opponent, damage, log)
        damage = min(damage, state.side(player.opponent).active.hp)
        state = self._apply_damage(
            state,
            player.opponent,
            damage,
            log,
            source=str(move.move_id),
            actor=player,
        )
        state = self._trigger_sitrus(state, player.opponent, log)
        return state, damage

    def _apply_offensive_ability(
        self,
        state: BattleState,
        player: PlayerId,
        actor: PokemonState,
        move: MoveDefinition,
        power: int,
        log: _EventLog,
    ) -> tuple[PokemonState, int]:
        ability = self._ability_effect(actor)
        triggered = False
        if ability == "technician" and power <= int(
            self.ruleset.rule("ability_rules", "technician", "power_limit")
        ):
            rule = self.ruleset.rule("ability_rules", "technician")
            power = power * int(rule["multiplier_numerator"]) // int(
                rule["multiplier_denominator"]
            )
            triggered = True
        elif ability in {"overgrow", "blaze"}:
            rule = self.ruleset.rule("ability_rules", ability)
            required_type = "grass" if ability == "overgrow" else "fire"
            threshold_met = actor.hp * int(rule["hp_denominator"]) <= (
                actor.stats.max_hp * int(rule["hp_numerator"])
            )
            if move.type_id == required_type and threshold_met:
                power = power * int(rule["multiplier_numerator"]) // int(
                    rule["multiplier_denominator"]
                )
                triggered = True
        if triggered:
            actor = replace(actor, ability_revealed_to_opponent=True)
            log.add(
                BattleEventKind.ABILITY_TRIGGERED,
                actor=player,
                subject=actor.instance_id,
                details={
                    "ability_id": str(actor.ability_id),
                    "effect_id": ability,
                    "move_id": str(move.move_id),
                },
            )
        return actor, power

    def _secondary_occurs(
        self,
        rng: ExplicitRNG,
        move: MoveDefinition,
        log: _EventLog,
        player: PlayerId,
        subject: PokemonInstanceId,
    ) -> tuple[bool, ExplicitRNG]:
        denominator = int(move.effect["chance_denominator"])
        numerator = int(move.effect["chance_numerator"])
        draw, rng = self._draw(
            rng,
            denominator,
            "secondary_effect",
            log,
            actor=player,
            subject=subject,
        )
        return draw < numerator, rng

    def _resolve_end_turn(self, state: BattleState, log: _EventLog) -> BattleState:
        working = state
        ordered_players = sorted(
            (PlayerId.P1, PlayerId.P2),
            key=lambda player: (-self._effective_speed(working.side(player).active), player.value),
        )
        for player in ordered_players:
            active = working.side(player).active
            if active.fainted:
                continue
            if active.status_id in {"burn", "poison"}:
                rule = self.ruleset.rule("residuals", active.status_id)
                amount = max(
                    1,
                    active.stats.max_hp * int(rule["numerator"]) // int(rule["denominator"]),
                )
                working = self._apply_damage(
                    working,
                    player,
                    amount,
                    log,
                    source=active.status_id,
                    actor=None,
                )
                working = self._trigger_sitrus(working, player, log)
            active = working.side(player).active
            if active.fainted:
                continue
            if self._item_effect(active) == "leftovers" and active.hp < active.stats.max_hp:
                working = self._reveal_item(working, player)
                log.add(
                    BattleEventKind.ITEM_TRIGGERED,
                    actor=player,
                    subject=active.instance_id,
                    details={"item_id": str(active.item_id)},
                )
                rule = self.ruleset.rule("residuals", "leftovers")
                working = self._heal_fraction(
                    working,
                    player,
                    int(rule["numerator"]),
                    int(rule["denominator"]),
                    log,
                    source="leftovers",
                )
        return working

    def _after_resolution(
        self,
        state: BattleState,
        rng: ExplicitRNG,
        log: _EventLog,
    ) -> TransitionResult:
        exhausted = {
            player: all(pokemon.fainted for pokemon in state.side(player).team)
            for player in (PlayerId.P1, PlayerId.P2)
        }
        if exhausted[PlayerId.P1] and exhausted[PlayerId.P2]:
            winner, reason = self._simultaneous_faint_winner(state, log)
            return self._finish(state, winner, rng, log, reason=reason)
        if exhausted[PlayerId.P1]:
            return self._finish(state, PlayerId.P2, rng, log, reason="all_fainted")
        if exhausted[PlayerId.P2]:
            return self._finish(state, PlayerId.P1, rng, log, reason="all_fainted")
        if state.turn >= self.ruleset.max_turns:
            return self._finish(state, None, rng, log, reason="max_turns")
        if any(state.side(player).active.fainted for player in (PlayerId.P1, PlayerId.P2)):
            forced = replace(state, phase=BattlePhase.FORCED_SWITCH)
            return TransitionResult(
                state=forced,
                events=tuple(log.events),
                next_decisions=self.required_decisions(forced),
                rng=rng,
                terminal=False,
                winner=None,
            )
        next_state = replace(
            state,
            turn=state.turn + 1,
            phase=BattlePhase.AWAITING_DECISIONS,
        )
        log.add(BattleEventKind.TURN_STARTED, details={"turn": next_state.turn})
        return TransitionResult(
            state=next_state,
            events=tuple(log.events),
            next_decisions=self.required_decisions(next_state),
            rng=rng,
            terminal=False,
            winner=None,
        )

    def _simultaneous_faint_winner(
        self,
        state: BattleState,
        log: _EventLog,
    ) -> tuple[PlayerId, str]:
        fainted = [event for event in log.events if event.kind is BattleEventKind.FAINTED]
        rough_skin = next(
            (
                event
                for event in reversed(fainted)
                if dict(event.details).get("source") == "rough_skin"
                and event.actor is not None
            ),
            None,
        )
        if rough_skin is not None:
            return rough_skin.actor, "rough_skin_simultaneous_faint"
        if not fainted or fainted[-1].subject is None:
            raise UnsupportedMechanic(
                "simultaneous_faint_resolution",
                ruleset_id=self.ruleset.ruleset_id,
                context="missing ordered faint events",
            )
        last_subject = fainted[-1].subject
        for player in (PlayerId.P1, PlayerId.P2):
            if last_subject in {
                pokemon.instance_id for pokemon in state.side(player).team
            }:
                return player, "ordered_simultaneous_faint"
        raise UnsupportedMechanic(
            "simultaneous_faint_resolution",
            ruleset_id=self.ruleset.ruleset_id,
            context=str(last_subject),
        )

    def _finish(
        self,
        state: BattleState,
        winner: PlayerId | None,
        rng: ExplicitRNG,
        log: _EventLog,
        *,
        reason: str,
    ) -> TransitionResult:
        finished = replace(state, phase=BattlePhase.FINISHED, winner=winner)
        log.add(
            BattleEventKind.BATTLE_ENDED,
            actor=winner,
            details={"reason": reason, "winner": winner.value if winner else None},
        )
        return TransitionResult(
            state=finished,
            events=tuple(log.events),
            next_decisions=None,
            rng=rng,
            terminal=True,
            winner=winner,
        )

    def _switch(
        self,
        state: BattleState,
        player: PlayerId,
        switch_to: PokemonInstanceId,
        log: _EventLog,
        *,
        forced: bool,
    ) -> BattleState:
        side = state.side(player)
        incoming = side.pokemon(switch_to)
        if incoming.fainted or incoming.instance_id == side.active_instance_id:
            raise IllegalAction("switch target must be a living bench Pokemon")
        outgoing = side.active
        if self._ability_effect(outgoing) == "natural_cure" and outgoing.status_id is not None:
            outgoing = replace(
                outgoing,
                status_id=None,
                ability_revealed_to_opponent=True,
            )
            state = self._put_pokemon(state, player, outgoing)
            log.add(
                BattleEventKind.ABILITY_TRIGGERED,
                actor=player,
                subject=outgoing.instance_id,
                details={"ability_id": str(outgoing.ability_id)},
            )
            log.add(
                BattleEventKind.STATUS_CHANGED,
                actor=player,
                subject=outgoing.instance_id,
                details={"new_status": None, "source": "natural_cure"},
            )
        outgoing = state.side(player).active
        outgoing = replace(outgoing, stat_stages=StatStages(), volatile_statuses=())
        state = self._put_pokemon(state, player, outgoing)
        incoming = state.side(player).pokemon(switch_to)
        incoming = replace(
            incoming,
            stat_stages=StatStages(),
            volatile_statuses=(),
            revealed_to_opponent=True,
        )
        state = self._put_pokemon(state, player, incoming)
        side = state.side(player)
        state = self._put_side(state, replace(side, active_instance_id=switch_to))
        log.add(
            BattleEventKind.SWITCHED,
            actor=player,
            subject=switch_to,
            details={"forced": forced, "from": str(outgoing.instance_id)},
        )
        state = self._trigger_switch_in_ability(state, player, log)
        return state

    def _trigger_switch_in_ability(
        self,
        state: BattleState,
        player: PlayerId,
        log: _EventLog,
    ) -> BattleState:
        active = state.side(player).active
        if self._ability_effect(active) != "intimidate" or active.fainted:
            return state
        active = replace(active, ability_revealed_to_opponent=True)
        state = self._put_pokemon(state, player, active)
        log.add(
            BattleEventKind.ABILITY_TRIGGERED,
            actor=player,
            subject=active.instance_id,
            details={"ability_id": str(active.ability_id)},
        )
        target = state.side(player.opponent).active
        if not target.fainted:
            state = self._apply_stage_changes(
                state,
                player,
                player.opponent,
                {"atk": -1},
                log,
                source="intimidate",
            )
        return state

    def _trigger_rough_skin(
        self,
        state: BattleState,
        attacker_player: PlayerId,
        log: _EventLog,
    ) -> BattleState:
        defender_player = attacker_player.opponent
        defender = state.side(defender_player).active
        attacker = state.side(attacker_player).active
        if self._ability_effect(defender) != "rough_skin" or attacker.fainted:
            return state
        defender = replace(defender, ability_revealed_to_opponent=True)
        state = self._put_pokemon(state, defender_player, defender)
        log.add(
            BattleEventKind.ABILITY_TRIGGERED,
            actor=defender_player,
            subject=defender.instance_id,
            details={"ability_id": str(defender.ability_id)},
        )
        rule = self.ruleset.rule("ability_rules", "rough_skin")
        amount = max(
            1,
            attacker.stats.max_hp * int(rule["numerator"]) // int(rule["denominator"]),
        )
        state = self._apply_damage(
            state,
            attacker_player,
            amount,
            log,
            source="rough_skin",
            actor=defender_player,
        )
        return self._trigger_sitrus(state, attacker_player, log)

    def _apply_focus_sash(
        self,
        state: BattleState,
        player: PlayerId,
        damage: int,
        log: _EventLog,
    ) -> tuple[BattleState, int]:
        pokemon = state.side(player).active
        if (
            self._item_effect(pokemon) == "focus_sash"
            and pokemon.hp == pokemon.stats.max_hp
            and damage >= pokemon.hp
        ):
            damage = pokemon.hp - int(self.ruleset.rule("item_rules", "focus_sash", "surviving_hp"))
            consumed_item_id = pokemon.item_id
            assert consumed_item_id is not None
            pokemon = replace(
                pokemon,
                item_id=None,
                consumed_item_id=consumed_item_id,
                item_revealed_to_opponent=True,
            )
            state = self._put_pokemon(state, player, pokemon)
            log.add(
                BattleEventKind.ITEM_TRIGGERED,
                actor=player,
                subject=pokemon.instance_id,
                details={"item_id": str(consumed_item_id)},
            )
            log.add(
                BattleEventKind.ITEM_CONSUMED,
                actor=player,
                subject=pokemon.instance_id,
                details={"item_id": str(consumed_item_id)},
            )
        return state, max(0, damage)

    def _trigger_sitrus(
        self,
        state: BattleState,
        player: PlayerId,
        log: _EventLog,
    ) -> BattleState:
        pokemon = state.side(player).active
        if self._item_effect(pokemon) != "sitrus_berry" or pokemon.fainted:
            return state
        rule = self.ruleset.rule("item_rules", "sitrus_berry")
        threshold_met = (
            pokemon.hp * int(rule["activation_hp_denominator"])
            <= pokemon.stats.max_hp * int(rule["activation_hp_numerator"])
        )
        if not threshold_met:
            return state
        consumed_item_id = pokemon.item_id
        assert consumed_item_id is not None
        pokemon = replace(
            pokemon,
            item_id=None,
            consumed_item_id=consumed_item_id,
            item_revealed_to_opponent=True,
        )
        state = self._put_pokemon(state, player, pokemon)
        log.add(
            BattleEventKind.ITEM_TRIGGERED,
            actor=player,
            subject=pokemon.instance_id,
            details={"item_id": str(consumed_item_id)},
        )
        log.add(
            BattleEventKind.ITEM_CONSUMED,
            actor=player,
            subject=pokemon.instance_id,
            details={"item_id": str(consumed_item_id)},
        )
        return self._heal_fraction(
            state,
            player,
            int(rule["heal_numerator"]),
            int(rule["heal_denominator"]),
            log,
            source="sitrus_berry",
        )

    def _inflict_status(
        self,
        state: BattleState,
        target_player: PlayerId,
        status: str,
        log: _EventLog,
        *,
        source: str,
    ) -> BattleState:
        target = state.side(target_player).active
        if target.status_id is not None or target.fainted:
            return state
        immune = (
            (status == "burn" and "fire" in target.types)
            or (status == "poison" and bool({"poison", "steel"} & set(target.types)))
        )
        if immune:
            log.add(
                BattleEventKind.ACTION_FAILED,
                actor=target_player.opponent,
                subject=target.instance_id,
                details={"reason": "status_immunity", "status": status, "source": source},
            )
            return state
        if status not in {"burn", "poison"}:
            raise UnsupportedMechanic(
                f"status:{status}", ruleset_id=self.ruleset.ruleset_id, context=source
            )
        target = replace(target, status_id=status)
        state = self._put_pokemon(state, target_player, target)
        log.add(
            BattleEventKind.STATUS_CHANGED,
            actor=target_player.opponent,
            subject=target.instance_id,
            details={"new_status": status, "source": source},
        )
        return state

    def _apply_stage_changes(
        self,
        state: BattleState,
        source_player: PlayerId,
        target_player: PlayerId,
        changes: Mapping[str, object],
        log: _EventLog,
        *,
        source: str,
    ) -> BattleState:
        pokemon = state.side(target_player).active
        stages = pokemon.stat_stages
        updates: dict[str, int] = {}
        for short_name, raw_delta in changes.items():
            if short_name not in _STAGE_FIELDS:
                raise UnsupportedMechanic(
                    f"stat_stage:{short_name}", ruleset_id=self.ruleset.ruleset_id
                )
            field_name = _STAGE_FIELDS[short_name]
            old = getattr(stages, field_name)
            new = max(-6, min(6, old + int(raw_delta)))
            updates[field_name] = new
            log.add(
                BattleEventKind.STAT_STAGE_CHANGED,
                actor=source_player,
                subject=pokemon.instance_id,
                details={"stat": field_name, "old": old, "new": new, "source": source},
            )
        pokemon = replace(pokemon, stat_stages=replace(stages, **updates))
        return self._put_pokemon(state, target_player, pokemon)

    def _add_volatile(
        self,
        state: BattleState,
        player: PlayerId,
        value: str,
        log: _EventLog,
    ) -> BattleState:
        pokemon = state.side(player).active
        if value not in pokemon.volatile_statuses:
            pokemon = replace(pokemon, volatile_statuses=pokemon.volatile_statuses + (value,))
            state = self._put_pokemon(state, player, pokemon)
            log.add(
                BattleEventKind.VOLATILE_CHANGED,
                actor=player.opponent,
                subject=pokemon.instance_id,
                details={"added": value},
            )
        return state

    def _clear_flinch(self, state: BattleState) -> BattleState:
        working = state
        for player in (PlayerId.P1, PlayerId.P2):
            pokemon = working.side(player).active
            if "flinch" in pokemon.volatile_statuses:
                pokemon = replace(
                    pokemon,
                    volatile_statuses=tuple(value for value in pokemon.volatile_statuses if value != "flinch"),
                )
                working = self._put_pokemon(working, player, pokemon)
        return working

    def _apply_damage(
        self,
        state: BattleState,
        target_player: PlayerId,
        amount: int,
        log: _EventLog,
        *,
        source: str,
        actor: PlayerId | None,
    ) -> BattleState:
        pokemon = state.side(target_player).active
        old_hp = pokemon.hp
        new_hp = max(0, old_hp - max(0, amount))
        pokemon = replace(pokemon, hp=new_hp)
        state = self._put_pokemon(state, target_player, pokemon)
        log.add(
            BattleEventKind.DAMAGE,
            actor=actor,
            subject=pokemon.instance_id,
            details={"amount": old_hp - new_hp, "old_hp": old_hp, "new_hp": new_hp, "source": source},
        )
        if old_hp > 0 and new_hp == 0:
            log.add(
                BattleEventKind.FAINTED,
                actor=actor,
                subject=pokemon.instance_id,
                details={"source": source},
            )
        return state

    def _heal_fraction(
        self,
        state: BattleState,
        player: PlayerId,
        numerator: int,
        denominator: int,
        log: _EventLog,
        *,
        source: str,
    ) -> BattleState:
        pokemon = state.side(player).active
        amount = max(1, pokemon.stats.max_hp * numerator // denominator)
        return self._heal_amount(state, player, amount, log, source=source)

    def _heal_amount(
        self,
        state: BattleState,
        player: PlayerId,
        amount: int,
        log: _EventLog,
        *,
        source: str,
    ) -> BattleState:
        pokemon = state.side(player).active
        if pokemon.fainted:
            return state
        old_hp = pokemon.hp
        new_hp = min(pokemon.stats.max_hp, old_hp + max(0, amount))
        pokemon = replace(pokemon, hp=new_hp)
        state = self._put_pokemon(state, player, pokemon)
        log.add(
            BattleEventKind.HEALED,
            actor=player,
            subject=pokemon.instance_id,
            details={"amount": new_hp - old_hp, "old_hp": old_hp, "new_hp": new_hp, "source": source},
        )
        return state

    def _consume_pp(self, pokemon: PokemonState, move_id: MoveId) -> tuple[PokemonState, int, int]:
        updated: list[MoveSlotState] = []
        old_pp = -1
        for slot in pokemon.moves:
            if slot.move_id == move_id:
                if slot.pp <= 0:
                    raise IllegalAction(f"move has no PP: {move_id}")
                old_pp = slot.pp
                updated.append(
                    replace(slot, pp=slot.pp - 1, revealed_to_opponent=True)
                )
            else:
                updated.append(slot)
        if old_pp < 0:
            raise IllegalAction(f"active Pokemon does not know move: {move_id}")
        return replace(pokemon, moves=tuple(updated)), old_pp, old_pp - 1

    def _effective_speed(self, pokemon: PokemonState) -> int:
        stage = pokemon.stat_stages.speed
        if stage >= 0:
            return pokemon.stats.speed * (stage + 2) // 2
        return pokemon.stats.speed * 2 // (2 - stage)

    def _reveal_active(
        self,
        state: BattleState,
        player: PlayerId,
        log: _EventLog,
    ) -> BattleState:
        active = state.side(player).active
        if not active.revealed_to_opponent:
            active = replace(active, revealed_to_opponent=True)
            state = self._put_pokemon(state, player, active)
            log.add(
                BattleEventKind.REVEALED,
                actor=player,
                subject=active.instance_id,
                details={"pokemon_id": str(active.pokemon_id)},
            )
        return state

    def _reveal_item(self, state: BattleState, player: PlayerId) -> BattleState:
        pokemon = state.side(player).active
        if pokemon.item_revealed_to_opponent:
            return state
        return self._put_pokemon(
            state, player, replace(pokemon, item_revealed_to_opponent=True)
        )

    def _draw(
        self,
        rng: ExplicitRNG,
        upper: int,
        label: str,
        log: _EventLog,
        *,
        actor: PlayerId | None = None,
        subject: PokemonInstanceId | None = None,
    ) -> tuple[int, ExplicitRNG]:
        before = rng.cursor
        value, next_rng = rng.randbelow(upper)
        log.add(
            BattleEventKind.RNG_DRAW,
            actor=actor,
            subject=subject,
            details={
                "label": label,
                "upper": upper,
                "value": value,
                "cursor_before": before,
                "cursor_after": next_rng.cursor,
            },
        )
        return value, next_rng

    def _validate_selections(
        self,
        requests: DecisionRequestSet,
        selections: tuple[ActionSelection, ...],
    ) -> dict[PlayerId, LegalAction]:
        if len(selections) != len(requests.requests):
            raise IllegalAction("one selection is required for every decision request")
        request_by_player = {request.player: request for request in requests.requests}
        chosen: dict[PlayerId, LegalAction] = {}
        for selection in selections:
            if selection.player in chosen or selection.player not in request_by_player:
                raise IllegalAction("selection player does not match pending requests")
            request = request_by_player[selection.player]
            if selection.request_id != request.request_id:
                raise IllegalAction("selection request_id mismatch")
            matches = [
                action for action in request.legal_actions if action.action_id == selection.action_id
            ]
            if len(matches) != 1:
                raise IllegalAction(f"illegal action_id: {selection.action_id}")
            chosen[selection.player] = matches[0]
        return chosen

    def _put_pokemon(
        self,
        state: BattleState,
        player: PlayerId,
        pokemon: PokemonState,
    ) -> BattleState:
        side = state.side(player)
        if pokemon.instance_id not in {member.instance_id for member in side.team}:
            raise KeyError(pokemon.instance_id)
        team = tuple(
            pokemon if member.instance_id == pokemon.instance_id else member
            for member in side.team
        )
        return self._put_side(state, replace(side, team=team))

    def _put_side(self, state: BattleState, replacement: SideState) -> BattleState:
        sides = tuple(
            replacement if side.player is replacement.player else side
            for side in state.sides
        )
        return replace(state, sides=sides)  # type: ignore[arg-type]

    def _ability_effect(self, pokemon: PokemonState) -> str:
        if pokemon.ability_id is None:
            return ""
        return self.catalog.ability(pokemon.ability_id).effect_id

    def _item_effect(self, pokemon: PokemonState) -> str:
        if pokemon.item_id is None:
            return ""
        return self.catalog.item(pokemon.item_id).effect_id

    def _validate_catalog_effects(self) -> None:
        for move in self.catalog.moves:
            kind = str(move.effect.get("kind", ""))
            if kind not in _SUPPORTED_MOVE_EFFECTS:
                raise UnsupportedMechanic(
                    f"move_effect:{kind}",
                    ruleset_id=self.ruleset.ruleset_id,
                    context=str(move.move_id),
                )
        for ability in self.catalog.abilities:
            if ability.effect_id not in _SUPPORTED_ABILITIES:
                raise UnsupportedMechanic(
                    f"ability_effect:{ability.effect_id}",
                    ruleset_id=self.ruleset.ruleset_id,
                    context=str(ability.ability_id),
                )
        for item in self.catalog.items:
            if item.effect_id not in _SUPPORTED_ITEMS:
                raise UnsupportedMechanic(
                    f"item_effect:{item.effect_id}",
                    ruleset_id=self.ruleset.ruleset_id,
                    context=str(item.item_id),
                )

    def _validate_state_mechanics(self, state: BattleState) -> None:
        if state.ruleset_id != self.ruleset.ruleset_id:
            raise ValueError("state ruleset_id does not match the engine")
        if state.field_conditions:
            raise UnsupportedMechanic(
                f"field_condition:{state.field_conditions[0]}",
                ruleset_id=self.ruleset.ruleset_id,
            )
        for side in state.sides:
            if len(side.team) != self.ruleset.team_size:
                raise ValueError(
                    f"{side.player.value} must have {self.ruleset.team_size} Pokemon"
                )
            mega_evolved = tuple(
                pokemon for pokemon in side.team if pokemon.mega_evolved
            )
            if len(mega_evolved) > 1:
                raise ValueError(
                    f"{side.player.value} used Mega Evolution more than once"
                )
            if mega_evolved and "mega_evolution" not in self.ruleset.supported_mechanics:
                raise UnsupportedMechanic(
                    "mega_evolution",
                    ruleset_id=self.ruleset.ruleset_id,
                    context=side.player.value,
                )
            if state.phase is BattlePhase.TEAM_PREVIEW and mega_evolved:
                raise ValueError("a TEAM_PREVIEW state cannot start Mega-Evolved")
            original_items = tuple(
                pokemon.item_id or pokemon.consumed_item_id
                for pokemon in side.team
                if pokemon.item_id is not None or pokemon.consumed_item_id is not None
            )
            if self.ruleset.item_clause and len(original_items) != len(set(original_items)):
                raise ValueError(f"{side.player.value} violates the item clause")
            for pokemon in side.team:
                is_catalog_mega_form = any(
                    definition.mega_pokemon_id == pokemon.pokemon_id
                    for definition in self.catalog.mega_evolutions
                )
                if is_catalog_mega_form and not pokemon.mega_evolved:
                    raise UnsupportedMechanic(
                        "mega_evolution:unmarked_target_form",
                        ruleset_id=self.ruleset.ruleset_id,
                        context=str(pokemon.instance_id),
                    )
                if pokemon.mega_evolved:
                    matching_targets = tuple(
                        definition
                        for definition in self.catalog.mega_evolutions
                        if definition.mega_pokemon_id == pokemon.pokemon_id
                        and definition.required_item_id == pokemon.item_id
                    )
                    if len(matching_targets) != 1:
                        raise UnsupportedMechanic(
                            "mega_evolution:unknown_transformation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    profile = pokemon.mega_evolution_profile
                    definition = matching_targets[0]
                    if profile is None:
                        raise UnsupportedMechanic(
                            "mega_evolution_stat_profile",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    if (
                        profile.target_pokemon_id != pokemon.pokemon_id
                        or profile.level != pokemon.level
                        or profile.source_manifest_id != definition.source_manifest_id
                        or profile.stats != pokemon.stats
                    ):
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_mismatch",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    try:
                        _, derived_mega_stats = validate_mega_stat_profile(
                            definition,
                            profile,
                        )
                    except SnapshotValidationError as error:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_derivation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                    if derived_mega_stats != pokemon.stats:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_derivation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                elif pokemon.mega_evolution_profile is not None:
                    if "mega_evolution" not in self.ruleset.supported_mechanics:
                        raise UnsupportedMechanic(
                            "mega_evolution",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    if pokemon.item_id is None:
                        raise UnsupportedMechanic(
                            "mega_evolution:missing_item",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    try:
                        definition = self.catalog.mega_evolution(
                            pokemon.pokemon_id,
                            pokemon.item_id,
                        )
                    except KeyError as error:
                        raise UnsupportedMechanic(
                            "mega_evolution:unknown_transformation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                    profile = pokemon.mega_evolution_profile
                    if profile.target_pokemon_id != definition.mega_pokemon_id:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_target",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    if profile.level != pokemon.level:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_level",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    if profile.source_manifest_id != definition.source_manifest_id:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_source",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    try:
                        derived_base_stats, _ = validate_mega_stat_profile(
                            definition,
                            profile,
                        )
                    except SnapshotValidationError as error:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_derivation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                    if derived_base_stats != pokemon.stats:
                        raise UnsupportedMechanic(
                            "mega_evolution:profile_derivation",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                    if profile.stats.max_hp != pokemon.stats.max_hp:
                        raise UnsupportedMechanic(
                            "mega_evolution:max_hp_change",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                elif (
                    "mega_evolution" in self.ruleset.supported_mechanics
                    and pokemon.item_id is not None
                ):
                    try:
                        self.catalog.mega_evolution(
                            pokemon.pokemon_id,
                            pokemon.item_id,
                        )
                    except KeyError:
                        pass
                    else:
                        raise UnsupportedMechanic(
                            "mega_evolution_stat_profile",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        )
                try:
                    species = self.catalog.pokemon(pokemon.pokemon_id)
                except KeyError as error:
                    raise UnsupportedMechanic(
                        f"pokemon:{pokemon.pokemon_id}",
                        ruleset_id=self.ruleset.ruleset_id,
                    ) from error
                if pokemon.types != species.types:
                    raise UnsupportedMechanic(
                        f"type_override:{pokemon.instance_id}",
                        ruleset_id=self.ruleset.ruleset_id,
                    )
                if pokemon.level != self.ruleset.level:
                    raise ValueError(
                        f"{pokemon.instance_id} must be level {self.ruleset.level}"
                    )
                if pokemon.ability_id not in species.ability_ids:
                    raise ValueError(
                        f"{pokemon.instance_id} has an illegal ability for {species.pokemon_id}"
                    )
                if len(pokemon.moves) != 4 or not {
                    move.move_id for move in pokemon.moves
                } <= set(species.legal_move_ids):
                    raise ValueError(
                        f"{pokemon.instance_id} has an illegal move set for {species.pokemon_id}"
                    )
                if pokemon.status_id is not None and pokemon.status_id not in _SUPPORTED_STATUSES:
                    raise UnsupportedMechanic(
                        f"status:{pokemon.status_id}",
                        ruleset_id=self.ruleset.ruleset_id,
                        context=str(pokemon.instance_id),
                    )
                unsupported_volatile = next(
                    (
                        value
                        for value in pokemon.volatile_statuses
                        if value not in _SUPPORTED_VOLATILE_STATUSES
                    ),
                    None,
                )
                if unsupported_volatile is not None:
                    raise UnsupportedMechanic(
                        f"volatile_status:{unsupported_volatile}",
                        ruleset_id=self.ruleset.ruleset_id,
                        context=str(pokemon.instance_id),
                    )
                if pokemon.ability_id is not None:
                    try:
                        self.catalog.ability(pokemon.ability_id)
                    except KeyError as error:
                        raise UnsupportedMechanic(
                            f"ability:{pokemon.ability_id}",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                if pokemon.item_id is not None:
                    try:
                        self.catalog.item(pokemon.item_id)
                    except KeyError as error:
                        raise UnsupportedMechanic(
                            f"item:{pokemon.item_id}",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                if pokemon.consumed_item_id is not None:
                    try:
                        self.catalog.item(pokemon.consumed_item_id)
                    except KeyError as error:
                        raise UnsupportedMechanic(
                            f"item:{pokemon.consumed_item_id}",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
                for move in pokemon.moves:
                    try:
                        self.catalog.move(move.move_id)
                    except KeyError as error:
                        raise UnsupportedMechanic(
                            f"move:{move.move_id}",
                            ruleset_id=self.ruleset.ruleset_id,
                            context=str(pokemon.instance_id),
                        ) from error
