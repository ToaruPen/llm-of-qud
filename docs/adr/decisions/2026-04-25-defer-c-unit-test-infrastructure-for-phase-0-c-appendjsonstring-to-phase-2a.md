# ADR Decision Record

timestamp: 2026-04-25T04:16:27Z
change: Defer C# unit-test infrastructure for Phase 0-C AppendJsonString to Phase 2a
adr_required: true
rationale: AppendJsonString is the one pure-functional seam in 0-C, but no C# test runner exists in the repo. Adding xUnit+csproj+CI gate for one helper is scope creep mid-Phase 0. Phase 0-C ships the helper defensively and adds a manual JSON-validity check on the latest state line. Six explicit re-open triggers documented.
files:
  - docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md
adr_paths:
  - docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md
