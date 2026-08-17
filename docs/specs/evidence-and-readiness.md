# Evidence and readiness

## Independent claims

Keep these claims separate:

1. upstream source and build byte identity;
2. upstream license and permitted use;
3. deterministic bridge behavior;
4. conformance with the Pokémon Champions client;
5. private-match operational readiness;
6. policy competitive strength.

The dependency manifest and hashes establish only the first claim. Showdown's project name, format label, popularity, or a passing local test does not establish client conformance.

## Engine evidence

An engineering-ready engine resolves the external checkout from bytes, verifies every manifest constraint, loads the exact singles format, rejects invalid teams/actions, isolates sessions and player observations, preserves live RNG during damage inspection, and reproduces canonical Replay identity.

Any unresolved engine identity or protocol failure is a hard error. The system must not continue through guessed data, an older local build, or the removed Python engine.

## Client grounding

Grounding compares a pinned Replay or expected public transition with an explicitly authorized private-match observation. `CaptureStore` content-addresses a screenshot and UI hierarchy outside Git. `GroundingTrace` binds the Showdown format, viewer, Replay hash when available, capture manifest hashes, interpreted fields, conformance checks, and blockers.

Ordinary BlueStacks diagnostics are read-only. Capture requires an already running player and externally verified ADB ownership; it performs only the exact screenshot and UI-hierarchy commands. Input automation is outside scope.

A conformant trace must contain evidence-backed matches and no unresolved check. An incomplete or nonconformant trace cannot support a Champions-grounded claim. Capture hashes establish bytes, not interpretation correctness or authorization.

## Private-match decision

A named-format private-match candidate requires:

- verified engine and build identity;
- deterministic integration and Replay checks;
- no opponent-private-information leak to the policy interface;
- explicitly authorized grounding for material supported behavior;
- an external active model compatible with the observation/action interface;
- bounded latency and an operational fail-closed path;
- no unresolved blocker relevant to the intended match.

Otherwise the decision is `NO-GO` with the blocker and restart condition recorded in the Issue or pull request. Rank-1-equivalent remains a separate evaluation claim.
