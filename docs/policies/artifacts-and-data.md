# Artifacts and data policy

## Purpose

Keep Git small and reviewable without losing artifact identity, provenance, or reproducibility.

## Tracked content

Git may track:

- source code, current specifications, policies, ADRs, schemas, and configuration;
- minimal fixtures and golden references required by deterministic tests;
- source, license, use-policy, and content-hash manifests;
- small baselines consumed directly by validators;
- generators and validation scripts.

Git must not track task reports or generated experiment summaries merely to preserve project progress.

## External artifacts

Use storage outside the repository workspace as the canonical home for bulk
experiment data and model generations. Workspace-local ignored copies are
disposable caches or migration inputs, not unique evidence or a store of record.

Keep these paths and artifact classes outside Git:

- `data/raw/`, `data/processed/`, `replays/`, and `runs/`;
- checkpoints, weights, arrays, embeddings, LLM caches, and experiment-tracker output;
- screenshots, videos, UI hierarchies, and BlueStacks capture attachments;
- grounding denominator plans, lineage receipts, expanded traces, assessments, and holdout records;
- generated scenario corpora, expanded evaluations, probes, and trajectories;
- Pokemon Showdown checkouts, `node_modules`, compiled output, and package-manager caches;
- credentials, private keys, signing tokens, actual enrollment registries, and ledgers.

Do not copy the legacy `champions` project, Pokémon Showdown, or third-party corpora into this repository. Resolve the pinned Showdown build through its tracked manifest and read other permitted sources through explicit external locators.

## Active model materialization

The runtime may materialize at most one verified active model release bundle in
an ignored workspace directory when direct external loading is impractical. One
logical release may contain multiple role-specific models, such as policy,
value, or belief models. All other checkpoints, generations, and experiment
runs remain outside the workspace.

`Active` means explicitly promoted and pinned, not merely the newest training
output. Before atomic activation, its manifest must identify the release and
model roles and pin each file's SHA-256, model and feature-interface versions,
preprocessing identity, and runtime and numeric-precision compatibility. The
external artifact store remains canonical after materialization, and activation
removes the previously active workspace bundle.

## Size limits

- Any tracked file: at most 2 MiB (2,097,152 bytes).
- Any path under `fixtures` or `golden`: at most 256 KiB (262,144 bytes).

ADR-0002 defines the rationale and legacy aliases for these limits. `scripts/check_repo_size.py` enforces them. A change to either limit requires a superseding ADR and an updated test in the same pull request.

## Artifact identity

Every external artifact admitted to a build or evaluation must have a manifest containing, as applicable:

- stable logical artifact ID;
- source locator and acquisition time;
- media type, byte size, and SHA-256;
- source issuer and semantic authority;
- license and use-policy status;
- regulation and target-pool identity;
- parser, generator, engine, and policy version;
- parent artifacts, transforms, partition, and seed lineage;
- access-control or sensitivity classification.

Resolve the artifact from bytes at use time. A matching hash proves byte identity, not source authority, permission, game fidelity, or competitive strength.

## Retention

Use content-addressed storage for generated bundles. Retain an artifact when it is an active candidate, is required to reproduce an active candidate, or is a non-regenerable counterexample. Prune regenerable intermediate runs only after their inputs, generator identity, and checksums are preserved.

Development and external-holdout artifacts use distinct content namespaces and access controls. Never copy holdout raw artifacts into the development store.

Initialize a capture store before sealing its GroundingPlan. The default
development capture store is
`%LOCALAPPDATA%/pokemon-auto-battle-single/captures/development`. A configured
development root and every holdout root must be absolute and outside the
repository; holdout has no implicit default. Authorization and lineage files
are external artifacts too; store only their content hashes in capture manifests.
Canonical GroundingTrace bytes live in the capture store's `_traces` namespace
and must be re-resolved by SHA-256 before use. The root `store.json` assigns one
persistent random identity and partition to the physical store; do not edit,
copy, or relabel it. A capture opens the pre-existing store without initialization
and requires its physical identity to match the sealed plan and authorization.
External Replay files used to derive expectations remain in the same external
artifact regime; only their hashes and permitted locators belong in Issue or PR
evidence.

Partition independence is provenance-based. Development and holdout must use
different physical stores, capture IDs and manifests, authorizations, plan
seals, Replay bytes, and lineage roles. A byte-identical static screenshot or UI
hierarchy can result from an independent deterministic capture and is not alone
proof of copying; never use that allowance to move holdout material into the
development namespace.

## Sensitive and restricted data

Treat captures as potentially sensitive. Treat unverified-license material as `local_research_only` with redistribution prohibited. Apply the same restriction to a derived artifact when it can reconstruct or unlawfully redistribute the source.

A private GitHub repository does not itself grant source-data permission. Put only non-sensitive manifests and reviewable metadata in Issues and pull requests; do not attach raw restricted payloads.

## Pre-commit checks

```powershell
python scripts/check_repo_size.py
python scripts/bootstrap_showdown.py --verify-only
```
