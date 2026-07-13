"""External holdout gate for a frozen TargetCapability denominator."""

from __future__ import annotations

from champions_sim.core import canonical_hash

from .models import (
    ConstructionSelectionCorpus,
    HoldoutGapReport,
    ObservationStatus,
    SCHEMA_VERSION,
    TargetCapabilitySet,
)


def evaluate_external_holdout(
    capability_set: TargetCapabilitySet,
    holdout: ConstructionSelectionCorpus,
) -> HoldoutGapReport:
    if holdout.corpus_role != "external_holdout":
        raise ValueError("holdout gate requires an external_holdout corpus")

    development_hashes = {value.record_hash for value in capability_set.development_records}
    holdout_hashes = {value.record_hash for value in holdout.records}
    overlap = tuple(sorted(development_hashes & holdout_hashes))
    known_entities = {
        (value.entity_kind, value.entity_id)
        for value in capability_set.entity_capability_refs
    }
    known_entities.update(
        ("pokemon", value.owner_entity_id)
        for value in capability_set.entity_capability_refs
        if value.owner_entity_id is not None
    )
    known_capabilities = {value.capability_id for value in capability_set.capabilities}
    new_entities: set[str] = set()
    new_capabilities: set[str] = set()
    unknowns: set[str] = set()
    quality: set[str] = set()
    for record in holdout.records:
        quality.update(f"{record.record_id}:{value}" for value in record.blockers)
        for entity in record.entities:
            if entity.status is not ObservationStatus.CONFIRMED or entity.entity_id is None:
                unknowns.add(f"{record.record_id}:{entity.field}")
                continue
            kind = "pokemon" if entity.field == "mega_target" else entity.field
            if (kind, entity.entity_id) not in known_entities:
                new_entities.add(f"{kind}:{entity.entity_id}")
        for signature in record.observed_capabilities:
            if signature.capability_id not in known_capabilities:
                new_capabilities.add(signature.capability_id)
    reasons = []
    reasons.extend(f"holdout_lineage_overlap:{value}" for value in overlap)
    reasons.extend(f"holdout_new_entity:{value}" for value in sorted(new_entities))
    reasons.extend(f"holdout_new_capability:{value}" for value in sorted(new_capabilities))
    reasons.extend(f"holdout_unknown:{value}" for value in sorted(unknowns))
    reasons.extend(f"holdout_quality:{value}" for value in sorted(quality))
    clean = not reasons
    return HoldoutGapReport(
        schema_version=SCHEMA_VERSION,
        report_id="holdout-" + canonical_hash(
            (capability_set.capability_set_hash, holdout.snapshot_hash)
        ),
        target_capability_set_id=capability_set.capability_set_id,
        target_capability_set_hash=capability_set.capability_set_hash,
        holdout_corpus_id=holdout.corpus_id,
        holdout_corpus_hash=holdout.snapshot_hash,
        overlapping_record_hashes=overlap,
        new_entity_refs=tuple(sorted(new_entities)),
        new_capability_ids=tuple(sorted(new_capabilities)),
        unknown_observation_refs=tuple(sorted(unknowns)),
        quality_blockers=tuple(sorted(quality)),
        holdout_clean=clean,
        blocking_reasons=tuple(sorted(reasons)),
    )
