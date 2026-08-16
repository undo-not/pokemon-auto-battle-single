---
name: update-regulation
description: Process a Pokémon Champions singles regulation change through official-source intake, permission review, exact TargetPool diff, Catalog and mechanics evidence, deterministic rehearsal, grounding, and a private-match candidate or reasoned NO-GO. Use when a regulation is announced, revised, activated, or rehearsed from a sealed historical snapshot.
---

# Update a regulation

## Freeze the intake

1. Open an objective Issue and record `t0`, intended game mode, acceptance criteria, source policy, and authorized external actions.
2. Retrieve current regulation facts from official primary sources. Record notice URL, retrieval time, effective interval, revision, byte hash, and semantic scope.
3. Keep downloaded payloads outside Git. Do not automate reacquisition until source-specific collection and use policy is reviewed.
4. Freeze RegulationSnapshot, exact TargetPool, source manifests, policy register, and external artifact locators before compilation.

## Rebuild evidence

1. Generate the before/after regulation and TargetPool diff without top-N or popularity filtering.
2. Build one namespace/form mapping row for every target member; keep candidate, conflict, unresolved, and verified states distinct.
3. Build field-level Catalog evidence and retain missing, conflict, unknown semantics, and permission gaps.
4. Lower only approved structured effects to registered handlers.
5. Generate or bind capability-specific development scenarios, positive Replay evidence, and probes.
6. Preserve source, transform, mapping, field, handler, scenario, and partition lineage.

## Validate deployment evidence

1. Derive the exact TargetCapabilitySet and six-dimensional execution matrix.
2. Keep development and external holdout isolated. Open the holdout only after sealing development artifacts.
3. Obtain authorized private-match grounding for required new or changed semantics.
4. Re-resolve source policy, artifacts, trust enrollment, signatures, time, revocation, and ledger state.
5. Run the risk-based checks in `$validate-simulator-change`.

## Decide

- By `t0 + 48h`, emit a verified candidate or sorted `NO-GO` with blocker, evidence requirement, and restart condition.
- By `t0 + 7d`, complete the private-match deployment decision.
- Count a timely reasoned `NO-GO` as operational success only.
- Never meet the deadline by shrinking denominators, guessing values, accepting LLM output as evidence, contaminating holdout, or bypassing permission, trust, grounding, or Replay checks.

Post progress and results to the Issue or pull request. Commit only current manifests, specifications, code, schemas, minimal fixtures, and executable baselines.
