# llm-of-qud

## Quick checks

- Start with [TOOLS.md](TOOLS.md) for commands, setup, and tool selection.
- `just anti-slop [paths...]` uses Ruff for Python, Roslyn for C#, and SwiftLint for Swift. ast-grep is an optional structural supplement, not the primary C# analyzer.
- `just anti-slop-test` verifies the tooling. Missing prerequisites fail checks; nothing is auto-installed or auto-fixed.

Treat detections as review candidates, not proof of AI authorship or permission to delete code. Classify candidates as REMOVE (proven behavior-preserving surplus), RETAIN (intentional/externally used/not safely owned), or DEFECT (requires a behavior change). Preserve justified boundary handling, Unity callbacks, reflection entry points, and test assertions. Do not introduce blanket suppressions to make scans pass.

## Purpose and layout

This project connects Caves of Qud to an external LLM harness. The game-side C# mod is a WebSocket client; the Python harness hosts the local server and MCP interface. The current target uses Modern UI without Harmony.

- [harness/README.md](harness/README.md): Python harness, protocol, ledger, and operational commands; [pyproject.toml](pyproject.toml) pins Python 3.12.
- [mod/README.md](mod/README.md): production C# mod, fixed game build, deployment, and verification limits.
- `tests/`: Python harness tests. `mod/tests/` and `mod/modal-tests/`: isolated C# policy tests.
- `probes/`: runtime experiments and verification scripts; the Swift hover helper is an input-producing program, not a test to execute casually.
- `docs/`: design and investigation records. `archives/`: historical reference, excluded from default quality scans.

## Verification and concurrent work

- Test and fixed-game compile commands are listed in [TOOLS.md](TOOLS.md#behavior-and-compatibility-checks).
- Static candidate scans do not establish runtime correctness. Preserve the distinction between fixture tests, scripted probes, and autonomous LLM play.
- Preserve concurrent changes and experiment evidence. Scope checks to owned files or an isolated snapshot when another task is editing source. Do not launch games, hover helpers, or live probes as part of anti-slop checks.

Respond and write specifications in Japanese unless requested otherwise. Write AI-facing instructions in English.
