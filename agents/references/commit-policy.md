# commit-policy.md
# Purpose: Commit, branch, and PR policy for llm-of-qud.
# Referenced from: root AGENTS.md.

## Core Rules

- Never commit unless explicitly requested by the user.
- Never amend an existing commit after a pre-commit hook failure; create a new commit.
- Never use `--no-verify` or skip the pre-commit hook.
- Never force-push to `main`.

## Pre-Commit Checks

Secret scanning is enforced via `npx secretlint .` on every commit.
If secretlint fails, remove the offending content and re-stage before creating a new commit.

## Commit Message Format

```
<type>(<scope>): <short imperative summary>

<body: why this change, not what — optional>

Co-Authored-By: <agent identity if applicable>
```

Types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`
Scopes: `mod`, `brain`, `docs`, `scripts`, `deps`, `ci`

Example:
```
feat(mod): RegisterPlayer subscribes to BeginTakeActionEvent

IGameSystem alone cannot receive object-level events. Explicit
Registrar.Register call verified against WanderSystem.cs:57-60.
```

## Branch Policy

- Feature work: create a branch from `main`.
- Branch naming: `<type>/<short-topic>` — e.g., `feat/phase-0-a-skeleton`
- Squash or rebase before merging; do not merge with a merge commit.

## PR Policy

- PR title: `<type>(<scope>): <summary>` (under 70 characters).
- PR body: summary bullets + test plan checklist.
- All static checks must pass before merge.
- Do not push to remote unless explicitly asked.

## Static Checks

Run before committing:

```bash
# Python Brain
uv run ruff check brain/
uv run basedpyright
uv run mypy --strict brain/

# Secret scanning (runs automatically via pre-commit, but can run manually)
npx secretlint .
```

MOD-specific checks (Phase 0-A2+):
```bash
# Compile-phase output lives in build_log.txt (Logger.buildLog), NOT Player.log.
# See mod/AGENTS.md §Logging.
grep -E "^\[[^]]+\] (Compiling \d+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$HOME/Library/Application Support/Kitfox Games/Caves of Qud/build_log.txt"
```

## Future sections

<!-- Phase 0-A2: add scripts/check-mod.sh as a pre-push check -->
<!-- CI: add GitHub Actions workflow matrix when configured -->
