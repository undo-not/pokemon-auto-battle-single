# Evidence and claims policy

## Independent claim dimensions

Never infer one of these dimensions from another:

1. byte identity and integrity;
2. semantic authority for a fact;
3. permission for collection, transformation, training, private-match use, or redistribution;
4. namespace and form mapping correctness;
5. structured mechanics meaning;
6. executable handler and positive scenario evidence;
7. actual-client grounding;
8. environment readiness;
9. policy strength and rank-1 equivalence.

Official authorship may support semantic authority but does not automatically grant an open-data license. Openly licensed general Pokémon data does not establish Pokémon Champions-specific event order. Hash equality does not establish either property.

## Evidence states

- `missing`: no suitable evidence exists.
- `candidate`: a possible value or mapping exists but lacks the required review binding.
- `conflict`: multiple incompatible candidates remain.
- `verified`: the value is bound to an approved source record, namespace/form identity, use policy, and reviewer decision required by its consumer.
- `grounded`: verified executable behavior conforms to an authorized client observation under the grounding contract.

Uncertainty and negative status propagate downstream. Do not replace `missing`, `conflict`, unknown semantics, or unsupported mechanics with a default value, normal damage, no-op, or LLM guess.

## Source-use review

Record source-specific decisions independently for collection, local candidate use, private-match use, training, redistribution, and production promotion. Until explicit permission or an applicable reviewed license exists, use the conservative restricted-local classification defined by ADR-0006.

Automated reacquisition requires a reviewed Issue that identifies the exact source, method, applicable terms, storage boundary, and use dimensions. Existing local bytes or a previously working fetcher do not authorize reacquisition.

## Promotion and authorization

Workbench, Compilation, mapping, Catalog, and readiness hashes are identities, not authorization. Candidate extraction may continue when policy is unresolved only if its output is marked non-authorizing and cannot enter the production materializer.

Trust verification must use an externally enrolled policy and current context. Caller-supplied keys, policies, allowlists, registry paths, or self-reported `official`/`verified` fields cannot establish production authorization.

## Claim language

Use precise scopes:

- `engineering verified` means a bounded test fixture traversed the intended implementation path;
- `operational rehearsal success` means the system produced a candidate or reasoned `NO-GO` within its SLA;
- `Champions grounded` requires actual authorized client conformance evidence;
- `private-match deployable` requires the complete environment and operational gates;
- `rank-1 equivalent` requires a separately specified external competitive benchmark.

Synthetic win rate, self-play Elo, silent-fallback count, deterministic execution, model confidence, or LLM review cannot substitute for external fidelity or strength evidence.

## Product-use boundary

Game-facing testing is limited to private friend matches. Ranked-match automation and unattended input automation are prohibited repository scopes. Read-only capture must also follow the authorization, ownership, sensitivity, and artifact-storage rules.
