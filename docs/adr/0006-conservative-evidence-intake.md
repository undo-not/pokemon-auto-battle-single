# ADR-0006: Separate semantic authority from permission and promote conservatively

- Status: Accepted
- Date: 2026-08-17
- Legacy aliases: `PD-012`, `PD-013`

## Context

Official Pokémon Champions pages, third-party reference sites, private observations, and legacy local data provide different kinds of evidence. Public availability, official authorship, local possession, record count, and hash identity do not individually grant collection, transformation, training, private-match use, redistribution, or production-promotion permission.

Legacy snapshots also lack uniform payload manifests, namespace-safe mappings, and complete transform lineage. Known file or record counts can detect accidental truncation but cannot prove source completeness or accuracy.

## Decision

Represent semantic authority and each use-permission dimension separately. Until a source-specific review establishes applicable permission, classify candidate intake as restricted local, prohibit redistribution, and block production materialization.

Treat names, national-dex values, site IDs, usage crosswalks, counts, and LLM suggestions as candidate evidence only. Require reviewed namespace/form mapping and field-level record hashes for verification.

Allow route-local minimum file and record counts only as anomaly floors sealed in a versioned acquisition plan. Reaching a floor never means complete, verified, reproduced, permitted, or regulation-ready.

## Consequences

- Candidate inventories can be built without falsely authorizing their use.
- Source-specific permission review or independently produced evidence is required for promotion.
- Conservative classification may block material that later proves usable; that is preferred to silent rights assumptions.
- This decision is an engineering gate, not legal advice or a statement from a rights holder.
