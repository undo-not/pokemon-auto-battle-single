# ADR-0002: Keep large artifacts outside Git and enforce size limits

- Status: Accepted
- Date: 2026-08-17
- Legacy aliases: `PD-001`, `PD-002`, `PD-006`

## Context

Battle trajectories, source payloads, generated Catalogs, expanded assessments, models, arrays, captures, and videos can grow rapidly. Committing them makes every clone carry permanent history and can inadvertently distribute restricted or sensitive material. Small fixtures and manifests are still necessary for deterministic review and regression.

Git LFS would retain large pointers and introduce a separate availability dependency without solving permission, sensitivity, lineage, or retention decisions.

## Decision

Store raw and generated bulk artifacts in content-addressed external storage. Track only code, schemas, minimal fixtures, manifests, hashes, and small executable baselines.

Enforce these limits:

- any Git candidate file: 2 MiB;
- any path under `fixtures` or `golden`: 256 KiB.

Do not use Git LFS as the default artifact store. Require a superseding ADR before changing the limits or adopting a shared artifact backend.

Every retained external artifact must resolve from a manifest containing identity, byte size, SHA-256, lineage, version, permission, and sensitivity information appropriate to its consumer.

## Consequences

- Repository clones remain small and reviewable.
- Full experiments require the external artifact store or deterministic regeneration.
- A hash proves bytes, not permission or authority.
- Non-regenerable promoted evidence and counterexamples need explicit external retention.
- `scripts/check_repo_size.py` and governance tests enforce the limits.
