# Evidence and claims policy

## Separate the claims

Never infer one of these from another:

- a Git commit, tree, file hash, or build fingerprint proves byte identity only;
- an upstream license governs permitted use but does not prove game fidelity;
- the Showdown Champions format is an engineering implementation, not official client authority;
- deterministic tests prove repeatability for the pin, not completeness;
- authorized client captures may ground observed behavior, not unobserved mechanics;
- evaluation measures a named policy and distribution, not universal rank-1 strength.

Unknown, conflicting, unsupported, or ungrounded behavior stays explicit. Do not replace it with a default, older engine, normal-damage assumption, no-op, model confidence, or LLM guess.

## External sources

Record source-specific collection, local use, training, private-match use, and redistribution limits in the authorizing Issue or external manifest. Downloaded payloads remain outside Git. A prior local file or fetch script does not authorize reacquisition.

The tracked Showdown manifest may contain public repository identity, hashes, format labels, and license metadata. It must not contain copied upstream source, credentials, private captures, or mutable local paths.

## Claim language

- `engineering verified`: the exact pinned build passed the stated deterministic integration checks.
- `Champions grounded`: named behavior matched authorized client evidence through a resolved grounding trace.
- `private-match candidate`: engine, grounding, model compatibility, latency, and operational gates passed for the named format.
- `rank-1 equivalent`: the separate external competitive-strength contract was satisfied.

Use `NO-GO` when evidence required by the intended claim is missing. Record the decision and restart condition in the Issue or pull request, not a tracked report.

## Product-use boundary

Game-facing work is limited to explicitly authorized private friend matches. Ranked-match automation and unattended input automation are prohibited. Read-only diagnostics and captures must follow the ownership, sensitivity, and external-storage rules.
