# Agent collaboration policy

## Roles

Assign one writer to an Issue branch. Other agents may act as consultant, investigator, or independent reviewer. The human user or designated integrator decides scope changes and merge readiness.

Codex and Claude Code may both work on the project, but neither agent's private memory, conversation, or task list is project state. Persist relevant state in the Issue or pull request.

## Consultation

Consultation is read-only. Give the consulting agent the Issue, relevant files, constraints, and a specific question without revealing the desired answer. Ask for evidence, alternatives, risks, and uncertainty.

For Claude Code, prefer:

```powershell
claude -p "<bounded question>" --permission-mode plan --output-format json
```

Do not automatically apply a consultant's recommendation. The branch writer evaluates it against current specifications, tests, and source evidence.

## Delegated implementation

Delegated edits require:

- an Issue with complete acceptance criteria;
- a dedicated `claude/<issue>-<slug>` or `codex/<issue>-<slug>` branch;
- an isolated Git worktree;
- explicit file and external-action scope;
- required validation commands;
- a pull-request handoff.

Never allow two writers to edit the same worktree or branch concurrently. Partition parallel work by independent Issue and file ownership.

## Independent review

Review the commit or complete diff, not the author's summary alone. Ask the reviewer to find correctness, contract, provenance, security, data-use, determinism, and test gaps. Do not provide suspected findings unless validating a specific fix.

The review handoff must include:

- reviewed commit SHA or pull-request URL;
- actionable findings with severity and file/line evidence;
- checks run by the reviewer;
- uncertainty and unreviewed surfaces.

Resolve findings in code or record the reason for rejection in the pull request. High-risk changes cannot rely solely on their author's self-review.

## Permissions and external effects

- Use plan/read-only permission mode for consultation and review.
- Use normal edit permissions only inside the delegated worktree.
- Do not use permission-bypass modes for this repository.
- Do not push, merge, publish, message third parties, download restricted data, or operate BlueStacks unless the Issue explicitly authorizes that external effect.
- Never provide secrets, private keys, credentials, raw captures, or restricted source payloads in prompts.

## Handoff format

Post the following to the Issue or pull request:

1. outcome and scope delivered;
2. commit and files changed;
3. exact validation commands and results;
4. external checks not run;
5. residual risks or blockers;
6. reviewer identity and findings disposition.
