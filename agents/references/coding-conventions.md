# coding-conventions.md
# Purpose: Coding style, naming, and verify-first rules for all components.
# Referenced from: root AGENTS.md, mod/AGENTS.md, brain/AGENTS.md.

## Verify-First Rule (applies everywhere)

Before writing any CoQ API reference — type signature, method parameter order,
field name, event name, manifest schema, loader flow — read the relevant file
under `decompiled/` and cite path + line number.

Do not fill gaps with plausible-looking guesses. If the decompiled source is
ambiguous, write: `# TODO: verify against installed binary at implementation time`
and stop.

Source of this rule: `docs/memo/feedback_verify_not_guess.md` and
`~/.claude/projects/…/memory/feedback_verify_not_guess.md`

## C# (mod/)

- Target: C# compatible with CoQ's bundled Roslyn compiler (verify version from `ModManager.cs`).
- Namespace: `LLMOfQud` for all MOD classes.
- `[Serializable]` on all `IPlayerSystem` and `IGameSystem` subclasses.
- No prebuilt DLL in `mod/LLMOfQud/`. No `.csproj` inside the mod directory.
- Log prefix: `[LLMOfQud]` for all runtime log lines.
- Static guards for one-time registration (e.g., `_loadMarkerLogged`) to survive body swap.
- Harmony patches: use only for methods without public event hooks.
  Always cite the target method with decompiled path + line before writing the patch.

### Naming

| Concept | Convention | Example |
|---------|-----------|---------|
| System class | PascalCase | `LLMOfQudSystem` |
| Handler class | `<Role>Handler` | `InspectHandler`, `ChoiceHandler` |
| Private fields | `_camelCase` | `_beginTurnCount` |
| Constants | SCREAMING_SNAKE or `const PascalCase` | `VERSION` |

## Python (brain/)

- Follow `ruff` defaults. Max line length: 88.
- Type annotations required on all public functions (mypy strict + basedpyright).
- Pydantic v2 for all wire-format models (`BaseModel`).
- `structlog` for structured logging; no bare `print()` in production paths.
- Async-first: `async def` + `await` for I/O. No blocking calls in async context.

### Module-Level Docstrings

Required on every new module:
```python
"""<one-sentence description of this module's responsibility>."""
```

### Naming

| Concept | Convention | Example |
|---------|-----------|---------|
| Module | `snake_case.py` | `tool_loop.py` |
| Class | PascalCase | `CodexProvider` |
| Async function | `snake_case` | `async def run_tool_loop()` |
| Pydantic model | PascalCase + suffix | `TurnStartMessage` |
| Constants | SCREAMING_SNAKE | `MAX_TOOL_CALLS_PER_TURN` |

## Separation of Concerns

- State lives in `session/manager.py`; logic lives in `tool_loop.py`.
- DB writes are async and isolated to `db/writer.py`.
- Overlay state is isolated to `overlay/stream_state.py`.
- Tool schemas are defined once in `tool_schemas.py`; never duplicated inline.

## Scope Discipline

Edit only within the ticket/Issue scope. If a related issue is found outside
scope, create a GitHub issue for it (use `auto-issue` skill) rather than fixing
it in the same branch.

## Future sections

<!-- Phase 1: add WebSocket message serialization conventions -->
<!-- Phase 2: add Pydantic model naming for provider client types -->
