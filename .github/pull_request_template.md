## What

<!-- One-paragraph summary of the change. -->

## Why (ADR link)

<!-- Link to the relevant ADR or decision record, e.g. docs/adr/0001-*.md -->
<!-- If no ADR applies, explain why (e.g. "trivial fix, no architectural impact"). -->

## How tested

<!-- Describe how you verified the change. -->
<!-- For brain/ changes: which pytest cases cover it? -->
<!-- For mod/ changes: which CoQ launch log line confirms compile success? -->
<!-- For docs/ changes: specify if any frozen-file guard applies. -->

- [ ] Unit / integration tests pass (`uv run pytest brain/tests/`)
- [ ] Pre-commit hooks pass locally (`pre-commit run --all-files`)
- [ ] C# compiles without errors (CoQ launch log shows no MOD error) — if applicable

## Risk

<!-- What could break? What's the blast radius? -->
<!-- Low / Medium / High, with justification. -->

## Rollback

<!-- How to revert if this goes wrong. E.g. "revert commit X", "re-deploy prior Brain image". -->

---

## Frozen-file changes?

- [ ] This PR modifies `docs/architecture-v5.md`
  - If checked: include the text **Amend v5.9** somewhere in this PR body to pass the frozen-file guard.
  - The spec is intentionally frozen at v5.9. Changes require explicit acknowledgement.
