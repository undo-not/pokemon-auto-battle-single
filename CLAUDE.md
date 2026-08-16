@AGENTS.md

# Claude Code additions

- Use `--permission-mode plan` for consultation and independent review.
- Use an Issue-specific `claude/<issue>-<slug>` branch and isolated worktree for delegated edits.
- Do not edit a worktree owned by Codex or another Claude session.
- Do not treat Claude auto memory as project state or decision authority.
- Do not use `--dangerously-skip-permissions` for this repository.
- Discover Claude wrappers in `.claude/skills/`; each wrapper points to the canonical project Skill in `.agents/skills/`.
