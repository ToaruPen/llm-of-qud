# AGENTS.md — llm-of-qud (root)
# Purpose: project orientation + top-level rules. Subdir AGENTS.md add localized rules; they do not repeat root rules.

## Project

`llm-of-qud` is a harness that lets an LLM autonomously play *Caves of Qud* (CoQ) for live streaming. Architecture frozen at `docs/architecture-v5.md` (v5.9).

| Component | Path |
|-----------|------|
| C# MOD | `mod/LLMOfQud/` — Roslyn-compiled in-process by CoQ at launch |
| Python Brain | `brain/` — Python 3.13 |
| Streaming overlay | `brain/overlay/` — localhost:8080 |
| CoQ source reference | `decompiled/` — read-only, 5367 `.cs` files |

## Imperatives

1. **Verify, never guess.** Read `decompiled/<path>.cs:<line>` and cite before writing any CoQ API reference. See `agents/references/coding-conventions.md`.
2. **Spec is frozen.** `docs/architecture-v5.md` and `docs/superpowers/plans/*` are immutable without a new ADR under `docs/adr/`.
3. **Single-source rules.** Each rule lives in one file. Subdir AGENTS.md reference this root or `agents/references/`; they do not duplicate.
4. **Edit only within ticket scope.** No drive-by fixes. See `agents/references/coding-conventions.md`.
5. **Commit only when explicitly requested.** See `agents/references/commit-policy.md`.

## Paths

| Key | Path | Owner AGENTS.md |
|-----|------|----------------|
| Spec | `docs/architecture-v5.md` | `docs/AGENTS.md` |
| Plans | `docs/superpowers/plans/` | `docs/AGENTS.md` |
| Memos | `docs/memo/` | `docs/AGENTS.md` |
| ADRs + decision log | `docs/adr/` | `docs/AGENTS.md` |
| CoQ decompiled source | `decompiled/` | `decompiled/AGENTS.md` |
| C# MOD | `mod/LLMOfQud/` | `mod/AGENTS.md` |
| Python Brain | `brain/` | `brain/AGENTS.md` |
| Governance YAML | `harness/` | `harness/AGENTS.md` |
| Scripts (ADR, checks) | `scripts/` | `scripts/AGENTS.md` |
| Shared reference rules | `agents/references/` | — (leaf files) |
| Git hooks | `.githooks/` | `scripts/AGENTS.md` |
| CI workflows | `.github/workflows/` | `docs/ci-branch-protection.md` |
| Repo-level tests | `tests/` | `brain/AGENTS.md` |

External paths (macOS): `$COQ_SAVE_DIR=~/Library/Application Support/Freehold Games/CavesOfQud/` (writes `build_log.txt`; `Player.log` lives at `$PLAYER_LOG=~/Library/Logs/Freehold Games/CavesOfQud/Player.log` per Unity macOS log convention, NOT under `$COQ_SAVE_DIR`); `$MODS_DIR=$COQ_SAVE_DIR/Mods/` (symlink target for `mod/LLMOfQud/`); CoQ install at `~/Library/Application Support/Steam/steamapps/common/Caves of Qud/` (Steam still uses the legacy directory name post-rebrand).

## Tests and Checks

Single gate before pushing: `pre-commit run --all-files && uv run pytest tests/`.

CI runs the same set plus security, governance, and C# analyzer jobs — configured in `.github/workflows/`, documented in `docs/ci-branch-protection.md`. Full rule rationale in `docs/lint-policy.md`. Testing policy in `agents/references/testing-strategy.md`. Phase 0-A runtime acceptance is manual in-game verification per `docs/superpowers/plans/2026-04-23-phase-0-a-mod-skeleton.md` Task 4c / Task 6 / Task 7.

## Decompiled Source

Authoritative CoQ API reference. Read-only. Citation format `decompiled/<path>.cs:<line>`. Index and policy in `decompiled/AGENTS.md`; commonly-cited files (`ModInfo`, `ModManager`, `IPlayerSystem`, `Logger`, etc.) catalogued there.

## Future sections

<!-- Phase 0-B+: CI entry points once scripts/check-mod.sh exists -->
<!-- Phase 1: WebSocket protocol reference table -->
<!-- Phase 2+: multi-provider LLM routing rules -->
