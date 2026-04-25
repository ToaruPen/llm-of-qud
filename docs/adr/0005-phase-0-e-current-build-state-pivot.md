# ADR 0005: Phase 0-E pivot from BirthBuildProfile to current build state

Status: Accepted (2026-04-25)

## Context

`docs/architecture-v5.md:2802` (v5.9 freeze) framed Phase 0-E as
"BirthBuildProfile capture (genotype, calling, attributes)". The frozen
spec section that consumes this data — `check_status`
(`docs/architecture-v5.md:443-468`) — returns CURRENT attributes,
level, hunger, thirst on each call, not birth-time values.
Implementing literal "Birth" capture would either (a) be unused by the
nearest downstream consumer, or (b) require a parallel "current state"
capture path that duplicates Birth's data shape with different
freshness semantics.

The retrospective use case for actual birth-time capture (DeathLogger
/ cross-run learning per `:1683-1687`) is real, but is gated by phases
that have not yet started (Phase 0-? death recording, Phase 1+ Brain
that compares cross-run trajectories). Implementing literal Birth
capture in 0-E would either ship dead code or commit to a
specification that the only near-term consumer (Phase 1+ `check_status`)
does not benefit from.

The codex 2026-04-25 design consultation (recorded in
`docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md`)
weighed three options and recommended pivoting Phase 0-E to "current
build state" with deferred retrospective capture. The spec PASSed all
codex review rounds at commit `8861358`.

## Decision

Phase 0-E captures the **current** player build state, not
BirthBuildProfile. The emitted line `[LLMOfQud][build] {...}` carries
`{turn, schema, genotype_kind, genotype_id, subtype_id, level,
attributes, hunger, thirst}` per the schema lock `current_build.v1`
documented in the design spec.

The Phase 0-? retrospective birth-profile capture (DeathLogger
substrate) remains an open future phase, NOT subsumed by Phase 0-E.

## Consequences

- The `:2802` spec line is reinterpreted: "BirthBuildProfile" naming in
  the v5.9 freeze remains historically accurate but is overridden for
  Phase 0-E semantics by this ADR. Future phase enumeration MUST
  reference both `:2802` (frozen text) and ADR 0005 (override) when
  citing Phase 0-E scope.
- A separate `[build]` line is added (NOT a `runtime_caps.v2` schema
  bump). `runtime_caps.v1` lock from Phase 0-D is preserved.
- The `check_status` Phase 1+ adapter assembles its return contract
  from per-turn observation lines: `[caps]` supplies effects /
  abilities / equipment; `[state]` supplies hp / position; `[build]`
  supplies level / attributes / hunger / thirst directly. See the
  design spec's "check_status adapter responsibility" hazard for the
  field-name mapping the adapter must perform.
- A future Phase 0-? for retrospective birth capture remains in the
  phase enumeration. When that phase lands it will need to either
  reuse `[build]` cadence (capture-once at birth, persist to a memo
  file, replay on Brain reconnect) or introduce a parallel `[birth]`
  line + ADR re-open.

## Alternatives Considered

1. **Literal BirthBuildProfile capture, write-once at first
   `BeginTakeActionEvent`.** Rejected because (a) Brain hot-resume
   mid-run has no birth event to replay against, (b) `check_status`
   returns CURRENT values so a write-once snapshot would still
   require a parallel current-state path, doubling implementation
   surface for no near-term consumer benefit.
2. **`runtime_caps.v2` schema bump folding build state into the
   existing `[caps]` line.** Rejected because (a) it re-opens the
   v1 schema lock landed in Phase 0-D for a payload (~200 bytes)
   that would benefit from a separate growth boundary, (b) the
   `[caps]` line is already ~5 KB observed; expanding the same
   line again hurts cache reuse + parser robustness more than a
   parallel line does.
3. **Event-driven emission (`[build]` only on detected change).**
   Rejected after enumerating CoQ event coverage: bypass paths
   (direct `Stomach.HungerLevel` writes, `Statistic._Value`
   backing-field writes, `Statistic.Load` deserialization,
   `SetStringProperty` / `RemoveStringProperty` for genotype/subtype
   without a canonical event) make event-driven robust capture
   require force-emit on multiple anchors anyway; per-turn full
   dump is simpler for a payload this small. See the design spec's
   "Cadence" section for the full bypass enumeration with citations.

## References

- `docs/architecture-v5.md:443-468` (`check_status` consumer
  contract — drove the pivot).
- `docs/architecture-v5.md:2802` (Phase 0-E line being
  reinterpreted).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that
  required this ADR.
- `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md`
  — design spec at commit `8861358`.
- `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md`
  — implementation plan (this directory, lands in the same docs PR).
- `docs/memo/phase-0-d-exit-2026-04-25.md` — Phase 0-D exit memo
  whose "Feed-forward for Phase 0-E" section seeded the design
  questions resolved by this ADR.
