# AGENTS.md — brain/
# Purpose: Rules for working in the Python Brain directory.
# Root rules still apply; this file adds Python-specific constraints.

## Tech Stack

| Tool | Version / constraint |
|------|---------------------|
| Python | 3.13 |
| Package manager | uv |
| Type checker | basedpyright + mypy strict |
| Linter/formatter | ruff |
| Data models | Pydantic v2 |
| HTTP client | httpx |
| WebSocket | websockets 16.0 |
| Async DB | aiosqlite |
| Logging | structlog |
| Tests | pytest |

All changes must pass `basedpyright` and `mypy --strict`. Ruff must report zero errors.

## Directory Layout

Canonical layout: `docs/architecture-v5.md:1838-1864`. Do not add modules without a spec reference from that section.

## Test Commands

```bash
# Run all tests
uv run pytest tests/

# Type check
uv run basedpyright
uv run mypy --strict brain/

# Lint
uv run ruff check brain/
uv run ruff format --check brain/
```

## Tool-Schema to MOD-Handler Mapping

| Tool name | C# handler | Spec reference |
|-----------|-----------|----------------|
| `inspect_surroundings` | `InspectHandler.cs` | arch-v5.md:1733 |
| `check_status` | `InspectHandler.cs` | arch-v5.md:1733 |
| `check_inventory` | `InspectHandler.cs` | arch-v5.md:1733 |
| `assess_threat` | `AssessmentHandler.cs` (Phase 2) | arch-v5.md:1734 |
| `request_candidates` | `CandidateGenerator.cs` | arch-v5.md:1719 |
| `navigate_to` | `AutoActHandler.cs` | arch-v5.md:1735 |
| `execute` | `ToolExecutor.cs` | arch-v5.md:1721 |
| `choose` / `cancel_or_back` | `ChoiceHandler.cs` | arch-v5.md:1736 |
| `write_note` / `read_notes` | `notes_manager.py` (Python-only) | arch-v5.md:1843 |

## Tool Loop Constants

Defined in `tool_loop.py` (see `docs/architecture-v5.md:1885-1898`):

```
MAX_TOOL_CALLS_PER_TURN = 8
TURN_TIMEOUT_S = 10.0
FORCE_ACTION_AFTER = 6
AUTOACT_HARD_TIMEOUT_S = 15.0
```

Do not change these without updating the spec.

## Testing Strategy

Preferred: game-as-harness (MOD scripted test mode, Phase 2+). See `agents/references/testing-strategy.md`.
Phase 0: manual in-game verification. Pure Python logic (parsers, transformations): pytest.
Do not write tests that require the CoQ runtime to be imported from Python.

## Lint Policy

See `docs/lint-policy.md` for the full rule rationale and suppression policy.
All changes must pass: `ruff check brain/`, `ruff format --check brain/`, `mypy --strict brain/src`, `basedpyright`.

## Future sections

<!-- Phase 1: add WebSocket message schema table (session_start, turn_start, tool_call_result) -->
<!-- Phase 2: add CodexProvider client API reference and SSE parsing rules -->
<!-- Phase 2: add notes_manager validation rules (7 fixed keys, 400-token budget) -->
<!-- Phase 3: add multi-provider routing rules (Claude, Gemini) -->
