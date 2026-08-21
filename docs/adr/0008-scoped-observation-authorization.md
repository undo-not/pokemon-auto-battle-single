# ADR-0008: Use scoped operator authorization and an existing-server ADB transport

- Status: Accepted
- Date: 2026-08-21

## Context

ADR-0007 removed the custom production compiler, promotion pipeline, enrollment
registry, and anti-rollback ledger. The current system still needs a narrow
authorization boundary for potentially sensitive Pokémon Champions observations,
but it does not perform unattended input or ranked-match operation.

An Android package name alone cannot identify the observed client. An old
version, an auto-updated version, and a replaced APK can share the same package
name, so package-only evidence cannot support a named-client fidelity claim.

The previous capture prototype invoked `HD-Adb.exe` after checking that a
BlueStacks ADB process existed. An ADB client can start a replacement server if
the checked process exits before the command, so a process-name preflight cannot
prove that observation has no server-start side effect. A workspace-local capture
directory also cannot be the canonical evidence store under the artifact policy.

## Decision

Initialize the external physical CaptureStore before authoring the GroundingPlan.
Resolve the tracked, content-addressed material-behavior catalog for the exact
regulation and format, and require the plan to instantiate every required entry
without placeholder exclusions. Bind the store identity, an external canonical
lineage-receipt hash, the authorizing Issue/actor, and the Android application
package plus exact installed client build into that plan. The build contains
`versionCode`, `versionName`, APK count, and a canonical digest of the SHA-256
for every installed base/split APK. This byte-set identity also changes when APK
signing bytes change. Seal the exact plan ID/hash/partition as the complete
body of an unedited GitHub Issue comment. Development and holdout use different
seal comments, physical stores, source artifacts, and role identities.
The capture path resolves that live third-party timestamp receipt and refuses a
missing, edited, wrong-Issue, wrong-actor, or backdated comment.

Provide a separate, explicitly confirmed pre-seal client-build inspection. It
uses the same existing-server ownership and command allowlist, emits only the
package/build identity, and never captures UI or performs input. This avoids a
circular plan dependency while keeping ordinary diagnosis free of ADB traffic.

Require every capture to resolve a short-lived, external
`ObservationAuthorization` document. It binds the authorizing GitHub Issue,
operator assertion, validity interval, Showdown format, BlueStacks instance,
sealed GroundingPlan ID/hash/partition, GitHub receipt, Android package,
exact client build, external capture-store identity, and exactly three read-only
operation classes: client identity, screenshot, and UI hierarchy. Ranked-match use
and input automation are fixed to false. The
runtime has no command that creates an authorization document and rejects a
document inside the repository, outside its validity interval, or outside the
requested scope. Re-read the external document before each allowed operation
and before admitting the result; deletion or any content change revokes the
loaded authorization. Issue authorization only after the GitHub receipt. Bind
the manifest to the exact authorization-file byte
SHA-256 rather than a normalized or semantic digest.

Treat this document as an explicit local operator assertion, not an independently
enrolled cryptographic production credential. Because the permitted operation is
read-only, human-triggered, short-lived, and incapable of game input, do not
restore the superseded key registry, ledger, or anti-rollback compiler. Current
authorization and claim scope are rechecked during capture and independently in
the pull request. Clock uncertainty, revocation, unattended operation, or a need
for stronger deployment authority produces `NO-GO` and requires a superseding
decision.

Never execute an ADB client from the capture path. Connect directly to an already
running ADB server over IPv4 loopback using the documented length-prefixed ADB
client/server protocol. Permit only `exec:screencap -p` and
`exec:uiautomator dump /dev/tty`, plus package-scoped `dumpsys`/`cmd package
path` and `sha256sum` for syntactically constrained `/data/app/...apk` paths,
with time and byte limits. Resolve the exact installed build before the first UI
artifact and after the last one, and reject a mismatch against the sealed build
or any change during capture. Do not persist device APK paths.

Bind the loopback listener to one Windows process before connecting. After the
TCP connection is established but before any ADB request bytes are sent, query
the exact server-side established connection four-tuple and require its owner to
equal that listener identity. Use the same socket for the stream and verify the
listener owner again after it. Require that its executable path matches the
installed BlueStacks `HD-Adb.exe`. Bind the capture manifest to the listener PID,
process start time, executable SHA-256, endpoint, authorization hash, and external
store identity. A
missing listener, changed owner, changed process identity, changed binary,
protocol error, timeout, or oversized response fails closed.

Use `%LOCALAPPDATA%/pokemon-auto-battle-single/captures/development` as the
default canonical development store. An override and every holdout root must be
explicit, absolute, and outside the repository. Each store persists a random
physical identity manifest and cannot be reopened under another logical ID or
partition. Development and
holdout stores must have distinct physical identities and paths; reused capture
identities or manifests, authorization bytes, Replay bytes, or plan-seal
receipts across them fail the environment gate. A static screenshot or
UI-hierarchy file may legitimately be byte-identical after an independent
capture, so individual artifact equality is not treated as reuse without shared
capture provenance. Raw bytes remain local-research-only and non-distributable.

Capture the UI hierarchy before the screenshot and again afterward. Record every
completion time, require the screenshot to remain bracketed within 30 seconds,
require both hierarchies to show the sealed Android package in the foreground,
and require their exact target-package node projections to match. Evidence
declared as both kinds must come from one capture and one conformance assertion.
That assertion must agree with an observed field at the same path, value, and
artifact provenance. Parse and verify the full PNG structure, chunk CRCs,
dimensions, terminal IEND, bounded IDAT expansion, and scanline filters before
admitting a screenshot.

For non-manual expectations, bind every requirement in one partition to one
scenario Replay hash and a catalog-constrained locator. Re-execute that Replay
with the active pinned bridge and resolve the declared public-log or
player-request value before evidence coverage can be constructed. Require the
scenario to bind Mega ordering, Hypnosis miss provenance, both-player turn
ordering, and odd-HP Super Fang damage to the selected request Pokémon rather
than accepting arbitrary log indexes or numerically plausible HP. Manual
expectations remain limited to affirmative UI context.
Resolve the plan-bound external lineage receipt from canonical bytes. Reject
development/holdout reuse of the receipt, source store, source artifacts,
collection role identities, or execution role identities. The receipt records
an auditable independence assertion but does not replace independent collection
or review. Require its source-artifact set to equal the byte hashes of the Replay
files actually re-executed for that partition.

## Consequences

- Ordinary diagnosis and tests cannot start ADB, BlueStacks, capture, or input.
- The capture implementation cannot create an ADB server because it never runs
  an ADB executable.
- A server replacement during either observation is detected and invalidates the
  whole capture.
- An old, updated, or replaced client APK set is rejected before it can support
  a sealed plan, and a build change during capture invalidates the capture.
- A listener that accepts the socket under a different process identity is
  rejected before the first ADB byte.
- Authorization remains intentionally proportional to read-only local research;
  it does not authorize unattended operation or establish independent trust.
- Windows listener inspection and a pre-existing BlueStacks `HD-Adb` server are
  operational dependencies for real capture.
- Capture manifest schema 2 binds authorization, external-store, and ADB-owner
  identity; schema 1 artifacts are not promotable by the current resolver.
- A GitHub outage, edited plan-seal comment, wrong target package, excessive
  artifact skew, changed client build, changed bracketed UI state, unresolved
  lineage, or unresolved Replay expectation produces `NO-GO`.
