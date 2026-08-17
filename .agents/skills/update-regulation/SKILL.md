---
name: update-regulation
description: Process a Pokémon Champions singles regulation change by freezing official facts, assessing the pinned Showdown Champions format, updating the external engine pin when justified, validating deterministic behavior, and producing a private-match candidate or reasoned NO-GO. Use when a regulation is announced, revised, activated, or rehearsed.
---

# Update a regulation

## Freeze the regulation facts

1. Open an objective Issue and record `t0`, intended game mode, acceptance criteria, source policy, and authorized external actions.
2. Retrieve the current rules from official primary sources and record URLs, retrieval time, effective interval, revision, format, team sizes, clauses, and special mechanics in the Issue.
3. Keep downloaded payloads and captures outside Git. Record hashes and permission limits without copying raw content into the repository.
4. Identify the exact Showdown format ID and candidate upstream commit. If no matching format exists, record a `NO-GO`; do not synthesize mechanics or revive the removed Catalog pipeline.

## Assess and pin Showdown

1. Compare the candidate commit with the current pin for format configuration, the relevant Champions mod, inherited simulator behavior, package lock, and license.
2. Confirm the format name, mod, singles mode, team validation, preview cardinality, and required mechanics through the bridge.
3. Build outside the workspace and update the tracked manifest with exact commit, tree, source hashes, compiled-file count, and build fingerprint.
4. Update only current specifications, schemas, minimal fixtures, bridge compatibility, and tests required by the new pin.
5. Treat upstream Showdown support as an engineering candidate, not official Champions conformance.

## Validate and ground

1. Follow the `validate-simulator-change` project Skill, including deterministic Replay, privacy, legal-action, damage, failure, and multiple-session tests.
2. Re-run representative policy evaluations with runs, trajectories, and models in the external artifact store.
3. Obtain explicitly authorized private-match grounding for material new or changed mechanics before calling the environment grounded.
4. Keep model and evaluation evidence separate from engine identity and grounding evidence.

## Decide

- By `t0 + 48h`, emit a verified candidate or sorted `NO-GO` with blocker, evidence requirement, and restart condition.
- By `t0 + 7d`, complete the private-match deployment decision.
- Count a timely reasoned `NO-GO` as operational success only.
- Never meet the deadline by guessing mechanics, treating the Showdown label as official evidence, accepting LLM output as rule truth, contaminating holdout, or bypassing permission, grounding, or Replay checks.

Post progress and results to the Issue or pull request. Commit only current manifests, specifications, code, schemas, and minimal deterministic fixtures.
