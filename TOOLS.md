# Tools

## Choose the primary language tool

| Language | Primary tool | Configuration |
|---|---|---|
| Python | Ruff | [ruff.toml](tools/quality/ruff.toml) |
| C# | Roslyn compiler + .NET SDK code-quality analyzers | [quality.globalconfig](tools/quality/roslyn/quality.globalconfig), [units.json](tools/quality/roslyn/units.json) |
| Swift | SwiftLint | [swiftlint.yml](tools/quality/swiftlint.yml) |

Use the primary tool's existing rules first. Use ast-grep for supplementary syntax patterns that those rules do not cover, including repository-specific constraints and migrations. Rules requiring types, symbols, or data flow belong in a semantic analyzer. Do not duplicate a dedicated analyzer rule in ast-grep. The current AST hints are optional and are not part of the main gate.

## Quality commands

| Command | Purpose |
|---|---|
| `just anti-slop [paths...]` | Run all primary language tools |
| `just anti-slop-python [paths...]` | Python only |
| `just anti-slop-csharp [paths...]` | Roslyn; expand selected C# files to complete analysis units |
| `just anti-slop-swift [paths...]` | Swift only |
| `just anti-slop-structural [paths...]` | Optional C# AST hints; no semantic or compile validation |
| `just anti-slop-test` | Test real analyzers, fixtures, scope, and failure handling |
| `just quality-tools` | Show installed tool versions |
| `just secretlint` | Scan tracked files for credentials and home-directory paths |
| `just secretlint-test` | Test the home-path rule and the missing-dependency failure |
| `just` | List recipes |

Paths are relative to the repository root. Omit paths for all current source, including untracked files. Detections are review candidates; classify them before changing code. Main checks never silently fall back from Roslyn to ast-grep.

## Secret and path scan

Run `just secretlint` before committing or pushing. It passes exactly `git ls-files` to secretlint (literal paths, `.gitignore` not applied) and fails on any finding. Setup is local and explicit: `npm ci` installs the pinned versions from [package-lock.json](package-lock.json) into ignored `node_modules/`. When they are missing, the recipe exits 2 instead of installing.

[.secretlintrc.json](.secretlintrc.json) uses `@secretlint/secretlint-rule-preset-recommend` plus a pattern rule for absolute home paths: macOS `/Users/<name>`, Linux `/home/<name>`, Windows `C:\Users\<name>`, and encoded forms such as `-Users-<name>-`. Placeholders containing `<`, `~/...`, and `$(HOME)` do not match. The only allowance is the leak-test sentinel `/Users/someone` in `tests/test_overlay.py`. No git hook or CI job runs this scan.

## C# setup and scope

The analysis-local [global.json](tools/quality/roslyn/global.json) selects .NET SDK 10.0.100 with patch roll-forward; it does not change the SDK selection of game/test projects. The SDK already includes Roslyn and the analyzers. No additional NuGet analyzer package or game mod is installed.

```sh
just quality-setup-csharp /absolute/path/to/fixed-game/Managed
just anti-slop-csharp
```

Setup stores the machine-specific path in ignored `.runtime/quality/settings.json`. `QUD_MANAGED` overrides that path; `--managed /absolute/path/to/Managed` overrides both when passed to an `anti-slop` recipe. Use the fixed game's DLLs, not arbitrary Unity assemblies.

Game units compile against those DLLs, following the existing direct `csc` compile-check approach. Test units use the .NET 10 reference pack and their declared support files. Outputs and SARIF diagnostics live in temporary directories and are removed after reporting. Source is never rewritten; compiled output is never executed or deployed.

The selected unit's dependencies and all its diagnostics are included even for a single-file scope. When adding a new C# location or changing test dependencies, update [units.json](tools/quality/roslyn/units.json); unmapped C# files fail instead of being skipped. This manifest describes analysis units, not deployment or runtime test discovery.

The runner returns 0 for no findings, 1 for findings, and 2 for setup/compilation/analyzer failures. Compiler warnings are also reported. A nonzero result is not automatically an anti-slop defect. In particular, reflection, callbacks, and cross-thread state require manual review.

Full exclusions, rule coverage, installation notes, and limitations: [quality reference](tools/quality/README.md).

## Behavior and compatibility checks

- Harness: `uv run python -m unittest discover -s tests -v`.
- Policy: `dotnet run --project mod/tests/PolicyTests.csproj`.
- Modal policy: `dotnet run --project mod/modal-tests/ModalTests.csproj`.
- Fixed-game compile: `python3 mod/check_compile.py --managed /absolute/path/to/Managed`.

Static analysis does not replace these checks or real-game acceptance. Do not launch games, input helpers, or live probes as part of quality scans.
