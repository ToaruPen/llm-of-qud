# Lint Policy — llm-of-qud

> Any suppression (`# noqa:`, `# type: ignore`, `# pragma: no cover`, XML `<NoWarn>`) MUST
> include a written justification on the same line. Suppressions without justification fail CI.

## Reference URLs

- ruff rules index: <https://docs.astral.sh/ruff/rules/>
- basedpyright config: <https://docs.basedpyright.com/latest/configuration/config-files/>
- mypy config: <https://mypy.readthedocs.io/en/stable/config_file.html>
- .NET code analysis overview: <https://learn.microsoft.com/en-us/dotnet/fundamentals/code-analysis/overview>
- StyleCop.Analyzers: <https://github.com/DotNetAnalyzers/StyleCopAnalyzers>
- Roslynator: <https://josefpihrt.github.io/docs/roslynator/>
- Meziantou.Analyzer: <https://github.com/meziantou/Meziantou.Analyzer>
- vulture (dead-code): <https://github.com/jendrikseipp/vulture>
- semgrep rules overview: <https://semgrep.dev/docs/writing-rules/overview>

---

## Severity levels

| Level | Meaning |
|-------|---------|
| **fatal** | CI blocker — build fails, no merge possible |
| **warn** | Review blocker — visible in CI, suppression requires justification |
| **info** | Advisory only — does not block CI |

---

## Python — ruff rule families

### fatal

**ERA (eradicate — ERA001)**
Flags commented-out code. Commented-out code is the most common sign of AI-generated
scaffolding left in commits; removal is always preferable to leaving dead code under a comment.

**F (pyflakes — F401, F811, F821…)**
Undefined names, unused imports, and redefined symbols are the first signals that generated
code was assembled from unrelated contexts without integration testing.

**BLE (flake8-blind-except — BLE001)**
`except Exception:` without a cause or re-raise is a placeholder error handler that hides
bugs; every broad except must name a specific exception type or log and re-raise.

**TRY (tryceratops — TRY002, TRY003, TRY301)**
Forbids raising bare `Exception("message")` and mandates structured exception hierarchies;
AI frequently raises `Exception("something went wrong")` as a placeholder.

**ARG (flake8-unused-arguments — ARG001–ARG005)**
Unused function and method parameters are AI "future-proofing" that adds noise to every
call site without delivering value; remove or replace with `_`.

**IDE0005 / IDE0051 / IDE0052 / IDE0060 (C# IDE rules)**
Unused using directives, unused private members, and unused parameters in C# have the same
meaning as their Python counterparts — AI adds them speculatively.

**MA0025 (Meziantou)**
`throw new NotImplementedException()` in a concrete method is a stub placeholder; it must
either be implemented or promoted to an abstract method.

### warn

**PLR (pylint refactor — PLR0912, PLR0913, PLR0914, PLR0915, PLR2004, C90)**
Too-many-branches, too-many-arguments, too-many-locals, too-many-statements, and magic
values flag AI code that was never decomposed into understandable units; max complexity = 8.

**B (flake8-bugbear — B006, B007, B008, B023…)**
Common design anti-patterns such as mutable default arguments, loop-variable capture, and
function calls in default argument position; AI generates these routinely from pattern-matching.

**SIM (flake8-simplify)**
Redundant constructs (`if x == True`, `not x in y`) are AI verbosity that reduces
readability without adding clarity.

**ANN (flake8-annotations)**
Missing type annotations allow AI-generated code to escape the type system; all public
function signatures must be fully annotated.

**FBT (flake8-boolean-trap — FBT003)**
Boolean positional arguments make call sites unreadable; AI adds `flag=True` parameters
without considering the API ergonomics.

**FIX (flake8-fixme)**
TODO/FIXME/HACK/XXX markers in committed code indicate unfinished work left by AI; each
must be resolved or tracked as a GitHub issue before merge.

**CA2007 (C# — ConfigureAwait)**
Missing `ConfigureAwait(false)` in library-like async code causes deadlocks in Unity's
synchronization context; AI omits it consistently.

**reportDeprecated (basedpyright)**
AI generates calls to deprecated APIs from training data; treating this as a warning
ensures deprecations are visible without blocking the build entirely.

### info

**UP (pyupgrade)**
Enforces Python 3.13 syntax idioms; AI trained on older Python versions produces
unnecessary backward-compat patterns.

**PERF (perflint)**
Performance anti-patterns such as list membership in tight loops; advisory only because
premature optimization is also a concern.

**SLOP-004 / SLOP-005 (semgrep custom)**
`raise NotImplementedError` in concrete methods and potentially-unused TypeVars are
advisory signals that require manual verification before escalation.

---

## Python — mypy

**`strict = true`**
Enables `disallow_untyped_defs`, `warn_redundant_casts`, `warn_return_any`,
`warn_unused_ignores`, `no_implicit_reexport`, and related options; unannotated code
cannot be type-checked and allows AI errors to pass silently.

**`disallow_any_explicit = true`**
Forbids `Any` in annotations; `Any` is the most common AI escape hatch when it cannot
infer the correct type. Known escape valve: Pydantic `model_validate(data)` and httpx
`response.json()` both return `Any` from the library side — use a typed intermediate
(e.g., `TypeAdapter`) or suppress with `# type: ignore[misc]  -- pydantic boundary`.

**`warn_unreachable = true`**
Dead code paths (often AI-generated defensive branches that can never execute) are flagged
at type-check time.

---

## Python — basedpyright

**`reportUnusedImport / reportUnusedVariable / reportUnusedFunction / reportUnusedParameter`**
All set to `error`; unused symbols in every category indicate AI-generated boilerplate
that was never integrated.

**`reportUnnecessaryIsInstance / reportUnnecessaryCast / reportUnnecessaryComparison`**
All set to `error`; redundant type-guard calls are a direct signal that AI added defensive
checks without understanding the type flow.

**`reportExplicitAny`**
Set to `error`; complements mypy's `disallow_any_explicit` — both checkers must agree.

---

## C# — analyzer families

**Microsoft.CodeAnalysis.NetAnalyzers (`AnalysisMode=All`)**
All CA rules enabled; IDE0* code-style rules enforced on build via
`EnforceCodeStyleInBuild=true`; individual noisy rules tuned in `.editorconfig`.

**StyleCop.Analyzers**
Enforces consistent formatting and naming; documentation (SA16xx) suppressed because this
is a private game mod, not a public API.

**Roslynator.Analyzers**
Structural simplification rules catch redundant constructs that analyzers miss.

**Meziantou.Analyzer**
MA0025 (NotImplementedException), MA0037 (empty statement), MA0090 (empty else/catch),
MA0140 (identical if/else branches) are the four rules most likely to catch AI stub code.

---

## Suppression policy

Every suppression must include a written rationale on the same line:

```python
# Python
result = cast(str, value)  # noqa: RUF100 — cast needed because third-party API returns Any
```

```csharp
// C#
#pragma warning disable CA1031  // catch-all required: CoQ callback cannot propagate exceptions
```

Suppressions without justification fail the `ERA001` / `PGH003` unfixable rules in ruff
and will be flagged during code review.
