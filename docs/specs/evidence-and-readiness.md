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

An engineering-ready engine resolves the external checkout from bytes, verifies every manifest constraint, and checks selected source identity against both canonical Git blobs and the LF-normalized worktree so Windows checkout conversion cannot change the pin. It loads the exact singles format, rejects invalid teams/actions, isolates sessions and player observations, preserves the complete live state during damage inspection, and reproduces canonical Replay identity.

Any unresolved engine identity or protocol failure is a hard error. The system must not continue through guessed data, an older local build, or the removed Python engine.

## Client grounding

Grounding compares a pinned Replay or expected public transition with an
explicitly authorized private-match observation. `CaptureStore`
content-addresses a screenshot, the target-package UI hierarchies immediately
before and after it, and canonical GroundingTrace bytes in a canonical store
outside the repository. A trace must be re-resolved by its byte hash before it
can enter the validation gate. `GroundingTrace` binds the Showdown format,
viewer, Replay hash when available, capture manifest hashes, interpreted fields,
conformance checks, and blockers.

Ordinary BlueStacks diagnostics are read-only. Capture requires an already
running player, a current external `ObservationAuthorization`, a live GitHub
plan-seal receipt, and verified ownership of an already-running BlueStacks ADB
server. The capture path never executes an ADB client. It connects directly to
the existing loopback server, binds the exact server-side established connection
four-tuple to the previously verified listener process before sending any ADB
request, performs only screenshot and UI-hierarchy services, and verifies the
listener owner after each stream. Before and after those artifacts it also uses
strictly allowlisted read-only package queries to resolve `versionCode`,
`versionName`, every installed base/split APK path, and each APK's SHA-256. No
APK path is persisted; the plan and evidence retain only version metadata, APK
count, and the canonical APK-set digest. Any APK or signing-byte change changes
that digest. Input automation is outside scope.

A conformant trace must contain evidence-backed matches and no unresolved check.
A match or mismatch check must agree with an observed field at the same path,
with the same value and artifact provenance. An incomplete or nonconformant
trace cannot support a Champions-grounded claim. Capture hashes establish bytes,
not interpretation correctness or authorization.

Before opening observation evidence, resolve the tracked material-behavior
catalog for the exact regulation and format, then seal an external
`GroundingPlan` for the authorizing Issue/actor, Android target package, exact
installed client build, engine manifest, physical capture-store identity,
external lineage-receipt hash, and development or holdout partition. The
current M-B catalog is versioned and
content-addressed and requires all eight material behaviors; a plan cannot
replace them with placeholder exclusions.

Resolve the client-build value before sealing with the explicit read-only
client-build inspection command. Unlike ordinary diagnostics, this is a
human-triggered ADB metadata operation: it requires an affirmative CLI flag,
connects only to an already-running owned server, captures no UI, persists no
device path, and performs no input. Its output is a plan input, not evidence of
client conformance; the authorized capture independently re-resolves the same
identity on both sides of the UI artifacts.

Development and holdout plans must have identical denominators but different
plan IDs, capture stores, source artifacts, and source, collection, authoring,
and execution lineage. The external canonical lineage receipt binds those
identities to the exact plan and store. Reusing a receipt, source store, source
artifact, or role identity, or using different collection methods, fails closed.
The receipt is an auditable attestation, not proof that an independent activity
occurred; independent collection and review remain required before a fidelity
claim. At the environment gate, each receipt's source-artifact set must exactly
equal the byte hashes of the Replay files actually re-executed for that
partition.

Post the exact plan ID/hash/partition marker to the authorizing GitHub Issue
before authorization or capture. The live comment must contain only that marker,
be unedited, belong to the Issue, and come from the configured repository actor.
Development and holdout must use different seal comments. A capture or
authorization timestamp earlier than its external receipt is inadmissible.
Plans, lineage receipts, and expanded results remain outside Git; tracked schemas
define only their current contract.

The current denominator has one required catalog entry for each of UI
observation, team preview, legal actions, event ordering, rounding, observable
RNG boundaries, Mega Evolution, and simultaneous interactions. UI observation
identifies the private friend-match client state. Manual scope may define only
that UI expectation; it cannot establish battle-rule values. All other values in
one partition come from one hash-bound scenario Replay. The active pinned bridge
re-executes the exact external Replay and resolves the specified public-log or
player-request value; a hand-entered value that differs from the resolved value
fails. The catalog additionally requires a complete ordered public sequence, a
Mega event before the same actor's move, a Hypnosis miss tied to its actor and
target, both players acting in one turn, and an odd-maximum-HP request whose
selected Pokémon is the target of the immediately associated Super Fang damage
event. Development and holdout use distinct Replay bytes for the same scenario
denominator and expected behavior.

The exact plan ID, hash, lineage-receipt hash, partition, GitHub receipt, Android
package, and physical store identity are copied into the short-lived
authorization and capture manifest before observation. The client build means
the positive `versionCode`, non-empty `versionName`, installed APK count, and
canonical SHA-256 of all base/split APK byte hashes. It is resolved again before
and after every capture and must equal the sealed value; development and holdout
must use that same build. Initialize the store
before sealing the plan; the capture command only opens that store and cannot
silently create a replacement. A persistent external store manifest prevents
reopening one physical root under another logical ID or partition. Holdout roots
must be explicit. Development and holdout coverage must also have distinct
physical store identities, capture IDs and manifests, authorizations, Replay
bytes, and plan-seal receipts. Equality of one static screenshot or UI-hierarchy
file is not by itself evidence of reuse: deterministic client rendering can
produce byte-identical observations. Independence is evaluated from complete
capture/store provenance and must still be reviewed externally.

Each capture records separate pre-hierarchy, screenshot, post-hierarchy, and
completion times. Both hierarchies must show the plan-bound Android package as
the foreground package. Their exact target-package node projection must match,
the screenshot must be bracketed by them, and total skew must not exceed 30
seconds. PNG evidence must have a complete, CRC-valid chunk stream, supported
nonzero dimensions, a terminal IEND, and a fully decodable bounded IDAT stream.
A requirement using both evidence kinds must cite all three artifacts
in one conformance check from one capture; artifacts from separate checks cannot
be combined to pass.

Each `GroundingTrace` binds one plan hash, lineage-receipt hash, partition,
requirement ID, capture store, and format. Resolver-backed coverage accepts a
requirement only when its trace resolves every capture byte and the exact
external authorization bytes, the authorization covered every observation
timestamp and Issue/format/instance/store scope and the live plan receipt, the
authorization, manifest, and capture all bind the same installed client build,
the trace is conformant, it matches the plan's exact path and expected value, it
supplies the planned artifact kind, and it binds the required Replay when one is
declared. Both partitions must cover the complete denominator before environment
evidence can be constructed.

## Environment and private-match decisions

A named-format grounded environment candidate requires:

- verified engine and build identity;
- deterministic integration and Replay checks;
- no opponent-private-information leak to the policy interface;
- explicitly authorized grounding for every declared material behavior;
- an independent external holdout with no unresolved overlap or unsupported behavior;
- bounded observation latency and an operational fail-closed path;
- no unresolved blocker relevant to the environment claim.

An `observed` grounded field must cite capture artifacts and carry a positive
`confidence_ppm`. Zero confidence cannot support an evidence-backed conformance
verdict or environment-readiness claim.

This environment claim does not require or evaluate a competitive policy.

A named-format private-match candidate requires:

- a grounded environment candidate for the same engine and format identity;
- an external active model compatible with the observation/action interface;
- policy latency and operational gates for the intended match.

Otherwise the decision is `NO-GO` with the blocker and restart condition recorded in the Issue or pull request. Rank-1-equivalent remains a separate evaluation claim.
