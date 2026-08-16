# Regulation and Catalog specification

## Regulation snapshot

A `RegulationSnapshot` is a versioned immutable document that identifies the official notice, rules revision, effective interval, battle format, team and selected-team sizes, level/item/species clauses, special mechanics, timers, and source manifests.

Effective dates and notice URLs are data, not timeless constants in Python. A snapshot is admitted only when its schema, source identity, byte hash, and review state are valid.

## Target pool

`TargetPool` contains the exact eligible entity/form/variant keys for one regulation revision. Its denominator is the complete frozen manifest, never a usage threshold, popularity top-N, available-data subset, or model-selected sample.

Stable target keys encode namespace, species/dex identity, form, and variant explicitly. Do not infer one namespace from another or collapse forms because names match.

## Namespace and form mapping

Each mapping row binds:

- target key and target-source record hash;
- source namespace and entity ID;
- form and variant identity;
- mapping basis and candidate set;
- review decision and evidence references;
- use-policy state required by the consumer.

Name equality, national-dex equality, legacy site-ID transformations, transitive crosswalks, usage listings, and LLM confidence may generate candidates but cannot generate `verified` mappings. Candidate, conflict, and unresolved rows remain in the denominator.

## Catalog

The runtime `Catalog` contains only fields that satisfy mapping, evidence, permission, and mechanics-lowering requirements. The review workbench may retain candidate values separately.

Species fields include identity, display name, types, six base stats, abilities, legal moves, and form relations. Move fields include type, category, power, accuracy, PP, priority, target, contact, and structured effect. Ability and item fields include trigger, target, and structured effect or explicit unknown status. Mega relations include base and target forms, required item, both stat/type/ability records, and regulation eligibility.

Every required field carries status and source references independent of its value. Missing, conflict, unknown semantics, or insufficient permission blocks runtime lowering.

## Evidence-promotion factory

Promotion is an explicit transformation from reviewed overlays to runtime assets. It must:

1. resolve the exact source artifact bytes and policy decision;
2. require a verified namespace/form mapping;
3. bind each approved field to its source record hash;
4. lower only registered structured effects;
5. generate or bind development scenarios, positive Replay evidence, and probes;
6. preserve source, transform, mapping, field, handler, and scenario lineage;
7. emit sorted blockers for every rejected field or capability;
8. produce no production materialization when any required authorization boundary is unresolved.

The transformation is deterministic. Equal overlays and artifacts produce byte-identical output and blocker identity.

## Capability coverage

Coverage uses an exact `TargetCapabilitySet` derived from the frozen TargetPool and reviewed Catalog. For every required capability, record six dimensions:

1. legality;
2. state transition;
3. RNG behavior, including explicit `rng:none`;
4. event sequence;
5. player observation;
6. Replay verification.

Execution coverage requires a capability-specific positive handler/probe. Silent fallback count must be zero, but zero fallback is not positive execution evidence. A rate is `null` when its denominator is not final.

## Regulation diff

The diff pipeline compares immutable before/after RegulationSnapshots, TargetPools, Catalogs, and RuleSets. It reports membership, rule, data, and unsupported-capability changes with content hashes. It does not mutate either input.

Synthetic deltas may validate pipeline wiring but are not deployable regulation evidence.

## One-week adaptation contract

At `t0`, freeze the reviewed regulation notice, TargetPool, source set, use policies, and external artifact locators.

- By `t0 + 48h`, emit either a verified candidate environment or a reasoned `NO-GO` containing exact blockers, evidence requirements, and restart conditions.
- By `t0 + 7d`, complete regression, artifact resolution, Replay verification, grounding requirements, and the private-match deployment decision.

External waiting time and manual work are recorded separately. Meeting the time limit never permits denominator reduction, unverified values, data-use assumptions, holdout contamination, or unsupported fallbacks. A timely, accurate `NO-GO` is operational success but not candidate success.

## Regulation-independent design

Keep engine handlers, observation contracts, Replay, evaluation, and learning interfaces independent of individual eligible lists. A regulation update replaces versioned manifests, reviewed overlays, and capability evidence; it does not rewrite invariant engine semantics merely to fit the new metagame.
