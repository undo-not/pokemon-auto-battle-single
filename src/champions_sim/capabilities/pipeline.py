"""Builders for explicit TargetPool manifests and legal capability closure."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace

from champions_sim.catalog import CatalogSnapshot, RuleSetSnapshot
from champions_sim.core import canonical_hash
from champions_sim.regulations import RegulationDataBundle

from .models import (
    SCHEMA_VERSION,
    CapabilityReachability,
    ConstructionSelectionCorpus,
    DuplicateRecordAlias,
    EffectSemanticRegistry,
    EntityCapabilityRef,
    GroundingRequirement,
    MappingEvidenceSet,
    MappingResolutionStatus,
    RecordIdentity,
    SelectionPolicy,
    TargetCapability,
    TargetCapabilitySet,
    TargetPoolManifest,
    UnresolvedRequirement,
    VerificationStatus,
)


_CLOSURE_ALGORITHM_VERSION = "legal-fixed-point-v1"
_REACHABILITY_PRIORITY = {
    CapabilityReachability.LEGAL: 0,
    CapabilityReachability.OBSERVED: 1,
    CapabilityReachability.MANDATORY: 2,
}


def build_target_pool_manifest(
    bundle: RegulationDataBundle,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    mapping_evidence: MappingEvidenceSet,
    corpus: ConstructionSelectionCorpus,
) -> TargetPoolManifest:
    """Bind all official members and every sealed corpus record without filtering.

    This function intentionally has no name/legacy-ID fallback.  Every resolved
    mapping must be supplied by ``MappingEvidenceSet`` with an evidence reference.
    """

    regulation = bundle.regulation
    pool = bundle.target_pool
    if mapping_evidence.target_pool_hash != pool.snapshot_hash:
        raise ValueError("mapping evidence target-pool hash mismatch")
    if mapping_evidence.catalog_hash != catalog.snapshot_hash:
        raise ValueError("mapping evidence Catalog hash mismatch")
    if corpus.corpus_role != "development":
        raise ValueError("TargetPoolManifest requires a development corpus")
    if (
        corpus.regulation_id != regulation.regulation_id
        or corpus.regulation_revision != regulation.revision
        or corpus.regulation_hash != regulation.snapshot_hash
    ):
        raise ValueError("construction corpus regulation identity mismatch")

    official_keys = tuple(member.target_key for member in pool.members)
    mapping_by_key = {entry.target_key: entry for entry in mapping_evidence.entries}
    supplied_keys = set(mapping_by_key)
    if supplied_keys != set(official_keys):
        missing = sorted(set(official_keys) - supplied_keys)
        extra = sorted(supplied_keys - set(official_keys))
        raise ValueError(
            f"mapping evidence must cover the exact official pool; missing={missing}, extra={extra}"
        )
    ordered_mappings = tuple(mapping_by_key[key] for key in official_keys)
    catalog_ids = {str(value.pokemon_id) for value in catalog.species}
    resolved_ids: list[str] = []
    blockers: list[str] = []
    for entry in ordered_mappings:
        if entry.resolution_status is not MappingResolutionStatus.RESOLVED:
            blockers.append(f"mapping_{entry.resolution_status.value}:{entry.target_key}")
            continue
        assert entry.catalog_pokemon_id is not None
        if entry.catalog_pokemon_id not in catalog_ids:
            blockers.append(
                f"mapping_missing_catalog_entity:{entry.target_key}:{entry.catalog_pokemon_id}"
            )
        else:
            resolved_ids.append(entry.catalog_pokemon_id)
        if entry.verification_status is not VerificationStatus.VERIFIED:
            blockers.append(
                f"mapping_not_verified:{entry.target_key}:{entry.verification_status.value}"
            )
    if len(resolved_ids) != len(set(resolved_ids)):
        blockers.append("mapping_catalog_ids_not_one_to_one")

    records = tuple(
        RecordIdentity(value.record_id, value.record_hash)
        for value in sorted(corpus.records, key=lambda item: item.record_id)
    )
    by_hash: dict[str, list[str]] = defaultdict(list)
    for value in records:
        by_hash[value.record_hash].append(value.record_id)
    aliases: list[DuplicateRecordAlias] = []
    for record_hash, ids in sorted(by_hash.items()):
        canonical_id = min(ids)
        aliases.extend(
            DuplicateRecordAlias(canonical_id, duplicate_id, record_hash)
            for duplicate_id in sorted(ids)
            if duplicate_id != canonical_id
        )
    for record in corpus.records:
        blockers.extend(
            f"construction_record:{record.record_id}:{value}"
            for value in record.blockers
        )
        if any(value.status.value in {"unknown", "conflict"} for value in record.entities):
            blockers.append(f"construction_record_unresolved:{record.record_id}")

    source_ids = tuple(
        sorted(
            {
                *regulation.source_manifest_ids,
                *pool.source_manifest_ids,
                catalog.source_manifest_id,
                *ruleset.source_manifest_ids,
                *mapping_evidence.source_manifest_ids,
                *corpus.source_manifest_ids,
                *registry_source_ids(bundle),
            }
        )
    )
    return TargetPoolManifest(
        schema_version=SCHEMA_VERSION,
        manifest_id=f"target-pool-manifest:{regulation.regulation_id}:{regulation.revision}",
        regulation_id=regulation.regulation_id,
        regulation_revision=regulation.revision,
        regulation_hash=regulation.snapshot_hash,
        eligible_pool_id=pool.target_pool_id,
        eligible_pool_hash=pool.snapshot_hash,
        catalog_id=catalog.catalog_id,
        catalog_hash=catalog.snapshot_hash,
        ruleset_id=str(ruleset.ruleset_id),
        ruleset_hash=ruleset.snapshot_hash,
        construction_corpus_id=corpus.corpus_id,
        construction_corpus_hash=corpus.snapshot_hash,
        mapping_set_id=mapping_evidence.mapping_set_id,
        mapping_set_hash=mapping_evidence.snapshot_hash,
        selection_policy=SelectionPolicy(),
        eligible_member_count=pool.expected_member_count,
        required_mechanics=tuple(sorted(regulation.required_mechanics)),
        member_mappings=ordered_mappings,
        included_records=records,
        duplicate_aliases=tuple(aliases),
        source_manifest_ids=source_ids,
        restricted_source_manifest_ids=bundle.restricted_source_manifest_ids,
        blockers=tuple(sorted(set(blockers))),
    )


def registry_source_ids(bundle: RegulationDataBundle) -> tuple[str, ...]:
    """Return bundle manifest IDs through one narrow compatibility hook."""

    return tuple(value.manifest_id for value in bundle.manifests)


def build_target_capability_set(
    manifest: TargetPoolManifest,
    catalog: CatalogSnapshot,
    ruleset: RuleSetSnapshot,
    registry: EffectSemanticRegistry,
    corpus: ConstructionSelectionCorpus,
) -> TargetCapabilitySet:
    """Compute a deterministic full legal fixed-point and freeze its denominator.

    Corpus observations annotate or challenge the legal closure; they never remove
    legal entities.  Unknown selectors become explicit unresolved requirements.
    """

    if manifest.catalog_hash != catalog.snapshot_hash:
        raise ValueError("TargetPoolManifest Catalog hash mismatch")
    if manifest.ruleset_hash != ruleset.snapshot_hash:
        raise ValueError("TargetPoolManifest RuleSet hash mismatch")
    if manifest.construction_corpus_hash != corpus.snapshot_hash:
        raise ValueError("TargetPoolManifest corpus hash mismatch")
    if corpus.corpus_role != "development":
        raise ValueError("capability closure requires the development corpus")

    semantic_by_selector: dict[tuple[str, str], list] = defaultdict(list)
    interactions = []
    for definition in registry.definitions:
        if definition.entity_kind == "interaction":
            interactions.append(definition)
        else:
            semantic_by_selector[(definition.entity_kind, definition.selector_id)].append(
                definition
            )

    observations: dict[tuple[str, str], tuple[tuple[str, ...], tuple[str, ...]]] = {}
    observed_records: dict[tuple[str, str], set[str]] = defaultdict(set)
    observed_evidence: dict[tuple[str, str], set[str]] = defaultdict(set)
    observed_capability_ids: dict[str, set[str]] = defaultdict(set)
    unresolved: dict[str, UnresolvedRequirement] = {}
    for record in corpus.records:
        for entity in record.entities:
            if entity.entity_id is None:
                _add_unresolved(
                    unresolved,
                    "unknown_observation",
                    f"{record.record_id}:{entity.field}",
                    entity.evidence_ref_ids,
                )
                continue
            if entity.status.value != "confirmed":
                _add_unresolved(
                    unresolved,
                    f"{entity.status.value}_observation",
                    f"{record.record_id}:{entity.field}:{entity.entity_id}",
                    entity.evidence_ref_ids,
                )
                continue
            key = (_observed_kind(entity.field), entity.entity_id)
            observed_records[key].add(record.record_id)
            observed_evidence[key].update(entity.evidence_ref_ids)
        for signature in record.observed_capabilities:
            observed_capability_ids[signature.capability_id].add(record.record_id)
    observations = {
        key: (tuple(sorted(observed_records[key])), tuple(sorted(observed_evidence[key])))
        for key in observed_records
    }

    for blocker in manifest.blockers:
        _add_unresolved(unresolved, "manifest_blocker", blocker, ())

    species_by_id = {str(value.pokemon_id): value for value in catalog.species}
    known_pokemon_ids = {
        value.catalog_pokemon_id
        for value in manifest.member_mappings
        if value.catalog_pokemon_id is not None
    }
    known_pokemon_ids.update(
        str(value.mega_pokemon_id) for value in catalog.mega_evolutions
    )
    raw_origins: list[tuple[str, str, str, str | None, tuple[str, ...]]] = []
    for mapping in manifest.member_mappings:
        if mapping.resolution_status is not MappingResolutionStatus.RESOLVED:
            _add_unresolved(
                unresolved,
                "unmapped_target",
                mapping.target_key,
                mapping.evidence_ref_ids,
            )
            continue
        assert mapping.catalog_pokemon_id is not None
        species = species_by_id.get(mapping.catalog_pokemon_id)
        if species is None:
            _add_unresolved(
                unresolved,
                "missing_catalog_pokemon",
                f"{mapping.target_key}:{mapping.catalog_pokemon_id}",
                mapping.evidence_ref_ids,
            )
            continue
        owner = str(species.pokemon_id)
        for move_id in species.legal_move_ids:
            try:
                selector = str(catalog.move(move_id).effect.get("kind", ""))
            except KeyError:
                _add_unresolved(unresolved, "missing_move", f"{owner}:{move_id}", ())
                continue
            raw_origins.append(("move", str(move_id), selector, owner, mapping.evidence_ref_ids))
        for ability_id in species.ability_ids:
            try:
                selector = catalog.ability(ability_id).effect_id
            except KeyError:
                _add_unresolved(unresolved, "missing_ability", f"{owner}:{ability_id}", ())
                continue
            raw_origins.append(
                ("ability", str(ability_id), selector, owner, mapping.evidence_ref_ids)
            )

    # Held items are not narrowed by observed usage.  Every Catalog item is a
    # legally possible seed under the current held-item-enabled SIM-02 contract.
    for item in catalog.items:
        raw_origins.append(("item", str(item.item_id), item.effect_id, None, ()))
    for mechanic_id in manifest.required_mechanics:
        raw_origins.append(("mechanic", mechanic_id, mechanic_id, None, ()))

    tokens: set[str] = set()
    refs_by_capability: dict[str, list[EntityCapabilityRef]] = defaultdict(list)
    signatures = {}
    reachability: dict[str, CapabilityReachability] = {}
    semantic_by_capability = {}
    matched_observation_keys: set[tuple[str, str]] = set()

    for kind, entity_id, selector, owner, mapping_refs in sorted(raw_origins):
        definitions = semantic_by_selector.get((kind, selector), ())
        if not definitions:
            _add_unresolved(
                unresolved,
                "unknown_effect",
                f"{kind}:{entity_id}:{selector or 'empty'}",
                mapping_refs,
            )
            continue
        tokens.update((f"entity:{kind}:{entity_id}", f"effect:{kind}:{selector}"))
        for definition in definitions:
            cap_id = definition.signature.capability_id
            signatures[cap_id] = definition.signature
            semantic_by_capability[cap_id] = definition
            tokens.update(definition.produces_tokens)
            record_ids, corpus_refs = observations.get((kind, entity_id), ((), ()))
            if record_ids:
                matched_observation_keys.add((kind, entity_id))
            is_observed = bool(record_ids) or cap_id in observed_capability_ids
            current = (
                CapabilityReachability.MANDATORY
                if kind == "mechanic"
                else CapabilityReachability.OBSERVED
                if is_observed
                else CapabilityReachability.LEGAL
            )
            previous = reachability.get(cap_id)
            if previous is None or _REACHABILITY_PRIORITY[current] > _REACHABILITY_PRIORITY[previous]:
                reachability[cap_id] = current
            ref_key = (kind, entity_id, owner or "", cap_id)
            ref_id = "ref-" + canonical_hash(ref_key)
            evidence = tuple(sorted({*mapping_refs, *corpus_refs}))
            refs_by_capability[cap_id].append(
                EntityCapabilityRef(
                    ref_id=ref_id,
                    entity_kind=kind,
                    entity_id=entity_id,
                    owner_entity_id=owner,
                    capability_id=cap_id,
                    legal_status="legal",
                    observed_in_corpus=is_observed,
                    source_record_ids=record_ids,
                    evidence_ref_ids=evidence,
                )
            )

    remaining = sorted(interactions, key=lambda value: value.semantic_id)
    progress = True
    while progress:
        progress = False
        next_remaining = []
        for definition in remaining:
            if not set(definition.requires_tokens) <= tokens:
                next_remaining.append(definition)
                continue
            cap_id = definition.signature.capability_id
            if cap_id not in signatures:
                progress = True
            signatures[cap_id] = definition.signature
            semantic_by_capability[cap_id] = definition
            tokens.update(definition.produces_tokens)
            is_observed = cap_id in observed_capability_ids
            current = (
                CapabilityReachability.OBSERVED if is_observed else CapabilityReachability.LEGAL
            )
            previous = reachability.get(cap_id)
            if previous is None or _REACHABILITY_PRIORITY[current] > _REACHABILITY_PRIORITY[previous]:
                reachability[cap_id] = current
            ref_id = "ref-" + canonical_hash(("interaction", definition.semantic_id, cap_id))
            refs_by_capability[cap_id].append(
                EntityCapabilityRef(
                    ref_id=ref_id,
                    entity_kind="interaction",
                    entity_id=definition.semantic_id,
                    owner_entity_id=None,
                    capability_id=cap_id,
                    legal_status="legal",
                    observed_in_corpus=is_observed,
                    source_record_ids=tuple(sorted(observed_capability_ids.get(cap_id, ()))),
                    evidence_ref_ids=(),
                )
            )
        remaining = next_remaining

    for cap_id, record_ids in observed_capability_ids.items():
        if cap_id not in signatures:
            _add_unresolved(
                unresolved,
                "observed_capability_outside_legal_closure",
                f"{cap_id}:{','.join(sorted(record_ids))}",
                (),
            )
    for (kind, entity_id), (record_ids, evidence_ids) in observations.items():
        if kind == "pokemon" and entity_id in known_pokemon_ids:
            continue
        if (kind, entity_id) not in matched_observation_keys:
            _add_unresolved(
                unresolved,
                "observed_entity_outside_legal_closure",
                f"{kind}:{entity_id}:{','.join(record_ids)}",
                evidence_ids,
            )

    all_refs: list[EntityCapabilityRef] = []
    capabilities: list[TargetCapability] = []
    requirements: list[GroundingRequirement] = []
    for cap_id in sorted(signatures):
        refs = _dedupe_entity_refs(refs_by_capability[cap_id])
        all_refs.extend(refs)
        definition = semantic_by_capability[cap_id]
        boundaries = definition.grounding_boundaries or ("core_transition",)
        requirement_ids: list[str] = []
        for boundary in boundaries:
            if boundary.startswith("entity."):
                for ref in refs:
                    requirement = _grounding_requirement(cap_id, boundary, ref.ref_id)
                    requirements.append(requirement)
                    requirement_ids.append(requirement.requirement_id)
            else:
                requirement = _grounding_requirement(cap_id, boundary, None)
                requirements.append(requirement)
                requirement_ids.append(requirement.requirement_id)
        capabilities.append(
            TargetCapability(
                capability_id=cap_id,
                signature=signatures[cap_id],
                reachability=reachability[cap_id],
                entity_ref_ids=tuple(value.ref_id for value in refs),
                grounding_requirement_ids=tuple(sorted(requirement_ids)),
            )
        )

    unresolved_values = tuple(sorted(unresolved.values(), key=lambda value: value.requirement_id))
    return TargetCapabilitySet(
        schema_version=SCHEMA_VERSION,
        capability_set_id=f"target-capabilities:{manifest.regulation_id}:{manifest.regulation_revision}",
        target_pool_manifest_id=manifest.manifest_id,
        target_pool_manifest_hash=manifest.manifest_hash,
        catalog_hash=catalog.snapshot_hash,
        ruleset_hash=ruleset.snapshot_hash,
        semantic_registry_id=registry.registry_id,
        semantic_registry_hash=registry.registry_hash,
        closure_algorithm_version=_CLOSURE_ALGORITHM_VERSION,
        denominator_final=not unresolved_values,
        entity_capability_refs=tuple(sorted(all_refs, key=lambda value: value.ref_id)),
        capabilities=tuple(capabilities),
        grounding_requirements=tuple(
            sorted(requirements, key=lambda value: value.requirement_id)
        ),
        unresolved_requirements=unresolved_values,
        development_records=manifest.included_records,
        source_manifest_ids=tuple(
            sorted({*manifest.source_manifest_ids, *registry.source_manifest_ids})
        ),
    )


def _observed_kind(field: str) -> str:
    return "pokemon" if field == "mega_target" else field


def _add_unresolved(
    target: dict[str, UnresolvedRequirement],
    kind: str,
    subject: str,
    evidence_ref_ids: tuple[str, ...],
) -> None:
    requirement_id = "gap-" + canonical_hash((kind, subject, tuple(sorted(evidence_ref_ids))))
    target[requirement_id] = UnresolvedRequirement(
        requirement_id=requirement_id,
        kind=kind,
        subject_ref=subject,
        evidence_ref_ids=tuple(sorted(evidence_ref_ids)),
        blocker_code=f"{kind}:{subject}",
    )


def _grounding_requirement(
    capability_id: str,
    boundary: str,
    entity_ref_id: str | None,
) -> GroundingRequirement:
    requirement_id = "ground-" + canonical_hash(
        (capability_id, boundary, entity_ref_id or "shared")
    )
    return GroundingRequirement(
        requirement_id=requirement_id,
        capability_id=capability_id,
        boundary_id=boundary,
        scope="entity_reference" if entity_ref_id is not None else "shared_semantics",
        entity_ref_id=entity_ref_id,
        allowed_evidence_kinds=(
            "actual_bluestacks",
            "official_primary",
            "published_reference",
        ),
    )


def _dedupe_entity_refs(values: list[EntityCapabilityRef]) -> tuple[EntityCapabilityRef, ...]:
    merged: dict[str, EntityCapabilityRef] = {}
    for value in values:
        previous = merged.get(value.ref_id)
        if previous is None:
            merged[value.ref_id] = value
            continue
        merged[value.ref_id] = replace(
            previous,
            observed_in_corpus=previous.observed_in_corpus or value.observed_in_corpus,
            source_record_ids=tuple(
                sorted({*previous.source_record_ids, *value.source_record_ids})
            ),
            evidence_ref_ids=tuple(
                sorted({*previous.evidence_ref_ids, *value.evidence_ref_ids})
            ),
        )
    return tuple(merged[key] for key in sorted(merged))
