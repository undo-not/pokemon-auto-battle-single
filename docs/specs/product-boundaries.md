# Product boundaries

## Purpose

`champions_sim` provides a reproducible Pokémon Champions singles environment for rules research, team selection, decision-policy development, and private friend-match evaluation.

The product separates five concerns:

1. deterministic battle state transition;
2. versioned regulation and Catalog data;
3. evidence, permission, mapping, and readiness verification;
4. public-information policy and competitive evaluation;
5. optional read-only client grounding and explicitly authorized private-match integration.

No upper layer may weaken a lower-layer failure. Policy quality cannot compensate for missing rule evidence, and a valid artifact hash cannot compensate for missing permission.

## Game mode

- Battle format: singles.
- Team-preview contract: six registered Pokémon, three selected in an ordered lineup when the active regulation uses 6→3 preview.
- Game-facing use: private friend matches only.
- Ranked-match automation: prohibited.
- Unattended BlueStacks input automation: prohibited.
- Read-only capture: permitted only under the grounding and artifact policies.

The simulator may evaluate rank-1-level decision quality in private or offline settings, but it must not describe itself as rank-1-equivalent without the external benchmark defined in `ai-evaluation.md`.

## System boundaries

### Authoritative configuration

Battle rules, entity data, regulation membership, legal actions, and structured effects come from versioned `RuleSet`, `Catalog`, `RegulationSnapshot`, and `TargetPool` documents. Python code must not embed regulation membership or silently infer missing values.

### Deterministic engine

The engine consumes complete state, legal decisions, immutable configuration, and an explicit RNG seed. It emits state transitions and Replay events. Unknown mechanics fail closed.

### Policy adapter

The policy adapter exposes only information observable by the relevant player. It cannot deliver opponent private state, hidden RNG, sealed source lineage, or holdout labels.

### Evidence and readiness

Evidence compilation tracks source identity, semantic authority, use policy, namespace mapping, field meaning, executable coverage, grounding, partitions, and trust. Portable output is not authorization by itself.

### Client integration

Client-facing code observes authorized private-match behavior and translates verified public state. It remains outside the battle-rule oracle and cannot modify rule truth from pixels or LLM output.

## Claim scopes

Every report must use one explicit claim scope:

- `synthetic_local`: deterministic engineering fixture only;
- `restricted_local`: local research using data whose wider permission is unresolved;
- `engineering_candidate`: end-to-end implementation path verified with controlled evidence;
- `champions_grounded`: behavior checked against authorized actual-client observations;
- `private_match_candidate`: all environment and operational gates passed for a named regulation;
- `competitive_evaluation`: policy strength measured under the separate evaluation contract.

An upstream scope never upgrades automatically because a downstream model wins games.

## Quality invariants

- Equal versioned inputs, decisions, and seed produce byte-identical canonical Replay.
- Unsupported behavior produces a structured error or unsupported status, never a guessed approximation.
- Every external value retains source, hash, version, and use-policy lineage.
- Development and holdout evidence remain lineage-separated.
- Large or sensitive artifacts stay outside Git.
- Regulations can be replaced without retraining or rewriting regulation-neutral engine contracts.
- A regulation update yields a deployable candidate or a reasoned `NO-GO`; it never lowers evidence thresholds to meet a deadline.

## Technology constraints

- Python 3.10 or newer.
- Python standard library for runtime code unless an ADR changes the dependency policy.
- `pytest` for automated tests.
- JSON documents use strict schemas, unique keys, finite numbers, stable IDs, and canonical hashes.

## Change rules

Behavioral changes require specification, implementation, schema, fixture, and test updates in the same pull request. Backward-incompatible serialized changes require a new schema or semantics version. Stable historical IDs may remain in serialized formats for compatibility, but their current rationale must resolve to an ADR.
