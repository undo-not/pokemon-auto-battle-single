# Evidence and readiness specification

## Evidence model

Every external value is evaluated along separate axes: artifact identity, semantic authority, use permission, namespace/form mapping, field meaning, executable behavior, actual-client grounding, partition independence, and trust authorization.

Evidence documents use strict schemas and deterministic canonical hashing. Duplicate keys, non-finite values, path escape, symlinks, NTFS alternate streams, reserved names, undeclared files, count drift, size drift, and hash drift fail closed.

## Source routes

A source route declares its source identities, evidence roles, acquisition plan, raw manifest, raw inventory, parsers or implementations, derived artifacts, lineage requirements, and known unrepresentable gaps.

Semantic authority and permission are independent. Source-route policy records collection, local candidate use, private-match use, training, redistribution, and production promotion separately.

Raw manifests and inventories must form an exactly-once projection of the same byte snapshot. Derived lineage binds route, source artifact, parent artifacts, registered transforms, and output hash. Cross-route, missing-parent, unknown-transform, intermediate, or runtime dependencies remain explicit gaps.

## Authoritative workbench

The non-authorizing intake compiler emits versioned forms of:

- source acquisition review;
- namespace/form mapping workbench;
- field-level Catalog workbench;
- all-blocker assessment over declared surfaces and known gap hints;
- portable Compilation summary.

These outputs always preserve `authorization_status: not_authorization` and must not enter a production materializer implicitly. Completeness claims identify their enumeration scope and never imply that undeclared external dependencies were enumerated.

A route may claim `snapshot_bound` only when its required raw and derived chain validates. Acquisition `reproduced` requires a separate causal execution-trace contract; snapshot hashes alone cannot establish it.

## Scenario evidence

Development scenarios bind exact capabilities, inputs, expected events, expected observations, and provenance. Positive probes execute the real engine handler and verify Replay; metadata-only or mocked success does not count.

Scenario partitions are semantic, not filename-based. Development, external holdout, and private grounding remain separated by source, collection, authoring, and execution lineage. Promotion seals partitions before opening a holdout. Any overlap, post-seal mutation, or unresolvable lineage fails the readiness gate.

## Grounding

Grounding compares simulator behavior with authorized private-match observations. A `CaptureStore` resolves exact manifest shape, capture identity, byte size, and hash. `GroundingTrace` binds capture, resolver, regulation, Catalog/RuleSet, interpreted public observations, actions, and simulator events.

Required grounding surfaces include UI observation, legal-action presentation, event order, rounding, RNG boundaries where observable, special mechanics, and simultaneous interactions material to supported capabilities.

Read-only diagnostics must not start ADB, capture, or emulator processes as a side effect. Capture requires explicit ownership, authorization, and sensitive-artifact handling. Input automation is outside the repository scope.

## Readiness layers

### Diagnostic compilation

Diagnostic compilers inventory sources, mappings, capabilities, and blockers. Their output is never a candidate seal.

### Engineering compilation

Engineering compilation demonstrates that controlled source, mapping, scenario, grounding, partition, and Replay evidence can traverse the resolver-backed pipeline. It fixes `champions_candidate: false` unless actual-source requirements are independently met.

### Production-shaped verification

Production-shaped verification requires external issuer enrollment, signed policy bindings, fixed registry identity, current trusted time, revocation state, OpenSSH binary identity, and a provisioned anti-rollback ledger. It re-resolves pre-, post-, and current-context state to detect drift.

Portable V3 output excludes volatile local paths and verification time from stable identity but remains `not_authorization` without current-context revalidation. Caller-supplied keys, policies, registry paths, or artifact-root allowlists are invalid trust roots.

## Readiness decision

The readiness metrics and required targets are:

| Metric | Definition | Candidate target |
|---|---|---|
| `target_pool_execution_coverage_rate` | fully supported target capabilities / declared target capabilities | `== 1.0` |
| `verified_grounding_conformance_rate` | passed verified grounding assertions / required verified grounding assertions | `== 1.0` |
| `silent_fallback_count` | unsupported, unknown, or unverified branches that continued without an explicit unsupported result, blocker, or `NO-GO` | `== 0` |

Return a null coverage or conformance rate when its denominator is not final; never remove missing capabilities or assertions to manufacture a rate.

A named-regulation environment can become a private-match candidate only when:

- target mappings and required Catalog fields are verified for the complete denominator;
- every required capability has a registered handler and six-dimensional positive execution evidence;
- required actual grounding passes;
- silent fallback is zero;
- development and holdout partitions are independent and the holdout has no novel unsupported gap;
- source and use policy permit the intended operation;
- production-shaped trust revalidates in the current context;
- artifact manifests and Replays resolve from bytes;
- the regulation adaptation contract completes with no unresolved deployment blocker.

Otherwise emit a sorted `NO-GO` assessment. Every blocker identifies stage, code, subject, required evidence, and restart condition.

## Version compatibility

Frozen diagnostic and V1/V2 artifacts may remain readable for deterministic regression. They cannot be reinterpreted as a stronger contract introduced by a later version. A stronger provenance or trust claim requires a new schema and explicit conversion path; it cannot be obtained by relabeling an older document.
