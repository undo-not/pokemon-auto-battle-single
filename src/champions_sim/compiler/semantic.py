"""Compile all Catalog selectors into source-bound capability semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from champions_sim.capabilities import (
    CapabilitySignature,
    ContextAtom,
    EffectSemanticRegistry,
    SemanticDefinition,
)
from champions_sim.catalog import (
    AbilityDefinition,
    CatalogSnapshot,
    ItemDefinition,
    MoveDefinition,
    RuleSetSnapshot,
)
from champions_sim.core import canonical_hash

from .models import SelectorDiagnostic, SemanticCompilation


_GROUNDING_BOUNDARIES = (
    "legality",
    "transition",
    "rng",
    "event",
    "observation",
    "replay",
)


@dataclass(frozen=True, slots=True)
class _EffectContract:
    effect_id: str
    trigger: str
    target: str
    required_mechanics: tuple[str, ...]
    rule_payload_required: bool = False


_MOVE_CONTRACTS = {
    "damage": _EffectContract(
        "move.damage", "on_move_resolution", "opponent",
        ("fixed_power_damage", "critical_hit", "damage_roll", "type_effectiveness", "stab", "stat_stages"),
    ),
    "damage_drain": _EffectContract(
        "move.damage_drain", "on_move_resolution", "opponent",
        ("fixed_power_damage", "critical_hit", "damage_roll", "type_effectiveness", "stab", "stat_stages", "drain"),
    ),
    "damage_secondary_flinch": _EffectContract(
        "move.damage_secondary_flinch", "on_move_resolution", "opponent",
        ("fixed_power_damage", "critical_hit", "damage_roll", "type_effectiveness", "stab", "stat_stages", "flinch"),
    ),
    "damage_secondary_stage": _EffectContract(
        "move.damage_secondary_stage", "on_move_resolution", "opponent",
        ("fixed_power_damage", "critical_hit", "damage_roll", "type_effectiveness", "stab", "stat_stages"),
    ),
    "damage_secondary_status": _EffectContract(
        "move.damage_secondary_status", "on_move_resolution", "opponent",
        ("fixed_power_damage", "critical_hit", "damage_roll", "type_effectiveness", "stab", "stat_stages"),
    ),
    "heal_self": _EffectContract(
        "move.heal_self", "on_move_resolution", "self", ("recovery",),
    ),
    "inflict_status": _EffectContract(
        "move.inflict_status", "on_move_resolution", "opponent", (),
    ),
    "raise_self": _EffectContract(
        "move.raise_self", "on_move_resolution", "self", ("stat_stages",),
    ),
}

_ABILITY_CONTRACTS = {
    "rough_skin": _EffectContract("ability.rough_skin", "after_contact_damage", "attacker", ("rough_skin",), True),
    "natural_cure": _EffectContract("ability.natural_cure", "on_switch_out", "self", ("natural_cure",)),
    "technician": _EffectContract("ability.technician", "before_damage", "self", ("technician",), True),
    "intimidate": _EffectContract("ability.intimidate", "on_switch_in", "opponent", ("intimidate", "stat_stages")),
    "overgrow": _EffectContract("ability.overgrow", "before_damage", "self", ("overgrow",), True),
    "blaze": _EffectContract("ability.blaze", "before_damage", "self", ("blaze",), True),
}

_ITEM_CONTRACTS = {
    "leftovers": _EffectContract("item.leftovers", "turn_end", "self", ("leftovers",), True),
    "sitrus_berry": _EffectContract("item.sitrus_berry", "after_hp_change", "self", ("sitrus_berry",), True),
    "focus_sash": _EffectContract("item.focus_sash", "before_faint", "self", ("focus_sash",), True),
    "mega_stone": _EffectContract("item.mega_stone", "on_mega_eligibility", "self", ("mega_evolution",), True),
}

_MECHANIC_CONTRACTS = {
    "mega_evolution": _EffectContract(
        "mechanic.mega_evolution", "before_move_order", "self", ("mega_evolution",), True,
    ),
}


def compile_effect_semantic_registry(
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    mandatory_mechanics: tuple[str, ...],
) -> SemanticCompilation:
    """Inventory and compile every Catalog selector, not only target closure hits.

    Uninterpreted selectors are retained as source-bound ``unsupported.*``
    capabilities.  This keeps them visible in diagnostics and lets execution
    probes distinguish an explicit ``UnsupportedMechanic`` from a silent no-op.
    """

    if catalog.engine_semantics_version != ruleset.engine_semantics_version:
        raise ValueError("Catalog and RuleSet engine semantics versions differ")
    if len(mandatory_mechanics) != len(set(mandatory_mechanics)):
        raise ValueError("mandatory mechanics must be unique")
    mandatory_mechanics = tuple(sorted(mandatory_mechanics))

    rows: list[
        tuple[
            str,
            str,
            str,
            Mapping[str, Any] | None,
            _EffectContract | None,
            bool,
        ]
    ] = []
    for move in catalog.moves:
        selector = str(move.effect.get("kind", ""))
        rows.append(
            (
                "move",
                str(move.move_id),
                selector,
                _move_payload(move),
                _move_contract(move),
                True,
            )
        )
    for ability in catalog.abilities:
        selector = ability.effect_id
        rule_payload = _rule_payload(ruleset, "ability_rules", selector)
        rows.append(
            (
                "ability",
                str(ability.ability_id),
                selector,
                _ability_payload(ability, rule_payload),
                _ABILITY_CONTRACTS.get(selector),
                rule_payload is not None,
            )
        )
    for item in catalog.items:
        selector = item.effect_id
        rule_payload = _item_rule_payload(ruleset, selector)
        rows.append(
            (
                "item",
                str(item.item_id),
                selector,
                _item_payload(item, rule_payload),
                _ITEM_CONTRACTS.get(selector),
                rule_payload is not None,
            )
        )
    for mechanic_id in mandatory_mechanics:
        rule_payload = _rule_payload(ruleset, mechanic_id)
        rows.append(
            (
                "mechanic",
                mechanic_id,
                mechanic_id,
                rule_payload,
                _MECHANIC_CONTRACTS.get(mechanic_id),
                rule_payload is not None,
            )
        )

    definitions: list[SemanticDefinition] = []
    diagnostics: list[SelectorDiagnostic] = []
    for kind, entity_id, selector, payload, contract, rule_payload_present in sorted(rows):
        reason_values: list[str] = []
        if contract is None:
            reason_values.append("uninterpreted_selector")
            digest = canonical_hash((kind, selector))[:20]
            contract = _EffectContract(
                f"unsupported.{kind}.{digest}", "unknown", "unknown", (),
            )
        if _catalog_declares_unsupported(kind, selector, payload):
            reason_values.append("catalog_declared_unsupported")
        reasons = tuple(sorted(set(reason_values)))
        required = _dynamic_required_mechanics(kind, selector, payload, contract)
        rng_contract = _rng_contract(
            kind, selector, payload, interpreted=not reasons
        )
        source_hash, source_reason = _selector_source_provenance(kind, payload)
        semantic_payload = _semantic_payload(
            kind=kind,
            entity_id=entity_id,
            selector=selector,
            payload=payload,
            explicit_unsupported=bool(reasons),
            source_record_sha256=source_hash,
        )
        context = _resolution_context(
            catalog=catalog,
            ruleset=ruleset,
            selector=selector,
            payload=semantic_payload,
            required_mechanics=required,
            rng_contract=rng_contract,
            rule_payload_required=contract.rule_payload_required,
            rule_payload_present=rule_payload_present,
        )
        branch_status = _branch_status(ruleset, required, reasons)
        branch = (
            "ruleset:"
            + canonical_hash(str(ruleset.ruleset_id))[:12]
            + f":{branch_status}:{kind}:"
            + canonical_hash(selector)[:12]
        )
        signature = CapabilitySignature(
            effect_id=contract.effect_id,
            trigger=contract.trigger,
            target=contract.target,
            resolution_context=context,
            ruleset_branch=branch,
        )
        semantic_id = "sem-" + canonical_hash(
            (catalog.snapshot_hash, ruleset.snapshot_hash, kind, entity_id, signature)
        )
        definitions.append(
            SemanticDefinition(
                semantic_id=semantic_id,
                entity_kind=kind,
                selector_id=f"entity:{entity_id}",
                signature=signature,
                requires_tokens=(),
                produces_tokens=("effect:" + canonical_hash((kind, selector))[:24],),
                grounding_boundaries=_GROUNDING_BOUNDARIES,
            )
        )
        diagnostics.append(
            SelectorDiagnostic(
                entity_kind=kind,
                entity_id=entity_id,
                selector_id=selector or "<empty>",
                capability_id=signature.capability_id,
                status="known" if not reasons else "explicit_unsupported",
                reason_codes=reasons,
                source_record_sha256=source_hash,
                source_reason=source_reason,
            )
        )

    source_ids = tuple(sorted({catalog.source_manifest_id, *ruleset.source_manifest_ids}))
    registry = EffectSemanticRegistry(
        registry_id="semantic-registry:" + canonical_hash(
            (catalog.snapshot_hash, ruleset.snapshot_hash, mandatory_mechanics)
        )[:24],
        semantics_version="compiler-v1:" + catalog.engine_semantics_version,
        definitions=tuple(definitions),
        source_manifest_ids=source_ids,
    )
    return SemanticCompilation(
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        registry=registry,
        inventory=tuple(diagnostics),
    )


def _move_contract(move: MoveDefinition) -> _EffectContract | None:
    return _MOVE_CONTRACTS.get(str(move.effect.get("kind", "")))


def _move_payload(move: MoveDefinition) -> Mapping[str, Any]:
    return {
        "type_id": move.type_id,
        "category": move.category,
        "power": move.power,
        "accuracy": move.accuracy,
        "pp": move.pp,
        "priority": move.priority,
        "contact": move.contact,
        "effect": _normalize_payload(move.effect),
    }


def _ability_payload(
    ability: AbilityDefinition,
    rule_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    return {
        "effect_id": ability.effect_id,
        "source_record_sha256": ability.source_record_sha256,
        "unsupported_reason": ability.unsupported_reason,
        "ruleset_rule": rule_payload,
    }


def _item_payload(
    item: ItemDefinition,
    rule_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    return {
        "consumable": item.consumable,
        "effect_id": item.effect_id,
        "source_record_sha256": item.source_record_sha256,
        "unsupported_reason": item.unsupported_reason,
        "ruleset_rule": rule_payload,
    }


def _rule_payload(ruleset: RuleSetSnapshot, *path: str) -> Mapping[str, Any] | None:
    current: Any = ruleset.raw
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return None
        current = current[key]
    normalized = _normalize_payload(current)
    return normalized if isinstance(normalized, Mapping) else {"value": normalized}


def _item_rule_payload(ruleset: RuleSetSnapshot, selector: str) -> Mapping[str, Any] | None:
    if selector == "leftovers":
        return _rule_payload(ruleset, "residuals", "leftovers")
    if selector in {"sitrus_berry", "focus_sash"}:
        return _rule_payload(ruleset, "item_rules", selector)
    if selector == "mega_stone":
        return _rule_payload(ruleset, "mega_evolution")
    return None


def _dynamic_required_mechanics(
    kind: str,
    selector: str,
    payload: Mapping[str, Any] | None,
    contract: _EffectContract,
) -> tuple[str, ...]:
    required = set(contract.required_mechanics)
    if kind == "move" and payload is not None:
        required.update(("priority", "speed_order"))
        if payload.get("accuracy") is not None:
            required.add("accuracy")
        effect = payload.get("effect")
        if isinstance(effect, Mapping):
            status = effect.get("status")
            if isinstance(status, str):
                required.add(status)
    return tuple(sorted(required))


def _rng_contract(
    kind: str,
    selector: str,
    payload: Mapping[str, Any] | None,
    *,
    interpreted: bool,
) -> str:
    if not interpreted:
        return "rng:unknown"
    if kind != "move" or payload is None:
        return "rng:none"
    components: list[str] = []
    if payload.get("accuracy") is not None:
        components.append("accuracy")
    if selector.startswith("damage"):
        components.extend(("critical", "damage-roll"))
    if selector.startswith("damage_secondary"):
        components.append("secondary")
    return "rng:" + ".".join(components) if components else "rng:none"


def _resolution_context(
    *,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    selector: str,
    payload: Mapping[str, Any] | None,
    required_mechanics: tuple[str, ...],
    rng_contract: str,
    rule_payload_required: bool,
    rule_payload_present: bool,
) -> tuple[ContextAtom, ...]:
    normalized_payload = _normalize_payload(payload)
    values: dict[str, str | int | bool | None] = {
        "catalog_hash": catalog.snapshot_hash,
        "catalog_source": catalog.source_manifest_id,
        "payload_hash": canonical_hash(normalized_payload),
        "rng_contract": rng_contract,
        "ruleset_hash": ruleset.snapshot_hash,
        "ruleset_rule_payload_present": rule_payload_present,
        "ruleset_rule_payload_required": rule_payload_required,
        "selector": selector,
    }
    for mechanic in required_mechanics:
        values[f"requires.{mechanic}"] = True
    if isinstance(normalized_payload, Mapping):
        _flatten_scalars("source", normalized_payload, values)
    return tuple(ContextAtom(key, values[key]) for key in sorted(values))


def _flatten_scalars(
    prefix: str,
    value: Mapping[str, Any],
    target: dict[str, str | int | bool | None],
) -> None:
    for raw_key in sorted(value):
        key = f"{prefix}.{raw_key}"
        item = value[raw_key]
        if isinstance(item, Mapping):
            _flatten_scalars(key, item, target)
        elif item is None or isinstance(item, (str, int, bool)):
            target[key] = item
        else:
            target[key] = canonical_hash(item)


def _normalize_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_payload(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return tuple(_normalize_payload(item) for item in value)
    raise ValueError(f"unsupported source payload type: {type(value).__name__}")


def _branch_status(
    ruleset: RuleSetSnapshot,
    required_mechanics: tuple[str, ...],
    unsupported_reasons: tuple[str, ...],
) -> str:
    if unsupported_reasons:
        return "explicit-unsupported"
    if set(required_mechanics) <= set(ruleset.supported_mechanics):
        return "supported"
    return "unsupported"


def _catalog_declares_unsupported(
    kind: str,
    selector: str,
    payload: Mapping[str, Any] | None,
) -> bool:
    if selector == "unsupported" or selector.startswith("unsupported:"):
        return True
    if payload is None:
        return False
    if kind == "move":
        effect = payload.get("effect")
        return isinstance(effect, Mapping) and bool(effect.get("reason"))
    return bool(payload.get("unsupported_reason"))


def _selector_source_provenance(
    kind: str,
    payload: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    if payload is None:
        return None, None
    if kind == "move":
        effect = payload.get("effect")
        if not isinstance(effect, Mapping):
            return None, None
        source_hash = effect.get("source_record_sha256")
        source_reason = effect.get("reason")
    else:
        source_hash = payload.get("source_record_sha256")
        source_reason = payload.get("unsupported_reason")
    return (
        source_hash if isinstance(source_hash, str) else None,
        source_reason if isinstance(source_reason, str) else None,
    )


def _semantic_payload(
    *,
    kind: str,
    entity_id: str,
    selector: str,
    payload: Mapping[str, Any] | None,
    explicit_unsupported: bool,
    source_record_sha256: str | None,
) -> Mapping[str, Any] | None:
    if payload is None:
        result: dict[str, Any] = {}
    else:
        normalized = _normalize_payload(payload)
        assert isinstance(normalized, Mapping)
        result = dict(normalized)
    if kind == "move":
        effect = result.get("effect")
        if isinstance(effect, Mapping):
            cleaned_effect = dict(effect)
            cleaned_effect.pop("source_record_sha256", None)
            cleaned_effect.pop("reason", None)
            result["effect"] = cleaned_effect
    else:
        result.pop("source_record_sha256", None)
        result.pop("unsupported_reason", None)
    if explicit_unsupported:
        result["unsupported_selector_identity"] = (
            source_record_sha256
            or canonical_hash((kind, entity_id, selector))
        )
    return result
