# ADR-0005: Require externally enrolled asymmetric trust and anti-rollback state

- Status: Superseded by ADR-0007
- Date: 2026-08-17
- Legacy aliases: `PD-010`, `PD-011`

## Context

A compiler caller that supplies a key, policy, expected hash, and allowlist can create a self-consistent signature without proving that an independent authority enrolled the policy. Shared HMAC secrets similarly make the compiler machine an issuer. Workspace-local registry and ledger state can be copied, replaced, or rolled back with the artifacts they are supposed to authorize.

Python's standard library does not provide an Ed25519 verifier, while the Windows environment provides OpenSSH verification.

## Decision

Use OpenSSH `ssh-keygen -Y verify` with Ed25519, a dedicated signature namespace, and canonical UTF-8 JSON. Keep signing keys outside the compiler machine.

Accept production-shaped verification only through a fixed per-user enrollment registry outside the workspace. Bind registry, enrollment, policy, issuer/key, OpenSSH executable, minimum policy epoch, validity interval, and a pre-provisioned SQLite ledger instance/path. Revalidate pre-, post-, and current-context state using externally supplied trusted time.

Portable output omits volatile verification time and raw local paths from stable identity but remains `not_authorization` until current-context revalidation. The compiler never creates actual registry, ledger, or secret-key state implicitly.

## Consequences

- A caller cannot authorize an arbitrary self-created policy merely by signing it.
- Missing, changed, revoked, expired, rolled-back, workspace-local, or unresolvable trust state fails closed.
- OpenSSH availability and binary identity become operational dependencies.
- The local mechanism does not by itself protect against compromise of the same OS user, Python process, filesystem ACLs, trusted clock, or executable code.
- Successful trust verification still does not prove source meaning, permission, client fidelity, or competitive strength.

ADR-0007 removed the custom compiler, promotion, and production-trust implementation
that applied this decision. Reintroducing a deployment authorization boundary requires
a new ADR against the current Showdown-based architecture.
