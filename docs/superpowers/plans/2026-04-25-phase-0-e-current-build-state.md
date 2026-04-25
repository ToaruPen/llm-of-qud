# Phase 0-E: Current Build State Observation (genotype, subtype, attributes, level, hunger, thirst) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit one structured `[LLMOfQud][build] {...}` JSON line per player decision point, alongside the existing `[screen]` (0-B), `[state]` (0-C), and `[caps]` (0-D) frames. The new line carries the **current** build identity (genotype + subtype) and current attribute / level / hunger / thirst values — the fields Phase 2 `check_status` (`docs/architecture-v5.md:443-468`) consumes that are NOT already in `[state]` or `[caps]`. The Brain (Phase 1+) consumes this as the fourth per-turn observation primitive.

**Architecture (Phase 0-D mirror):**

- **Game thread** (`HandleEvent(BeginTakeActionEvent)`): build the build JSON from `The.Player.GetGenotype()` / `GetSubtype()` / `GetStat(...)` / `GetPart<Stomach>()`. Same `try/catch` posture as 0-D's caps JSON: any exception becomes a sentinel `{"turn":N,"schema":"current_build.v1","error":{...}}` valid-JSON line.
- **`PendingSnapshot` extension, NOT a parallel slot.** Per `docs/memo/phase-0-c-exit-2026-04-25.md:117` (carried into 0-D): any new field threads through `PendingSnapshot`. `PendingSnapshot` gains one new field: `string BuildJson`. The atomic publish becomes `(Turn, StateJson, DisplayMode, CapsJson, BuildJson)` as one ref-typed object swap.
- **Render thread** (`AfterRenderCallback`): emit a fourth `MetricsManager.LogInfo` call: `[LLMOfQud][build] {...}` in its own `try` scope. The existing `AfterRenderCallback` (`mod/LLMOfQud/LLMOfQudSystem.cs:205-269`) wraps `[screen]+[state]` in one try (`:220-253`) and `[caps]` in a separate try (`:260-268`). Phase 0-E adds a third try for `[build]`. **`[caps]` and `[build]` are independently fault-isolated; `[screen]+[state]` share a try, an inherited 0-C/0-D constraint not re-litigated here.**
- **Per-turn output: 5 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]`.

**Cadence: every-turn full dump (provisional, same posture as 0-D).** Event-driven emission was evaluated and rejected (codex consultation 2026-04-25); see the design spec `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` for the bypass-paths enumeration. Re-open if measured constraints (Player.log size, prompt cache hit rate, WebSocket bandwidth, snapshot_hash design) justify it. The `[build]` payload is small (~200 bytes) compared to `[caps]` (~5 KB observed).

**Schema lock: `current_build.v1`.**

```json
{
  "turn": 47,
  "schema": "current_build.v1",
  "genotype_kind": "mutant",
  "genotype_id": "Mutated Human",
  "subtype_id": "Warden",
  "level": 3,
  "attributes": {
    "strength": 18, "agility": 16, "toughness": 14,
    "intelligence": 12, "willpower": 14, "ego": 12
  },
  "hunger": "sated",
  "thirst": "quenched"
}
```

Field semantics, error posture, normalization rules, and out-of-scope deferrals are locked in the design spec; this plan implements that contract verbatim and references back to the spec rather than restating it.

**Tech Stack:** Same as Phase 0-A / 0-B / 0-C / 0-D. CoQ Roslyn-compiles `mod/LLMOfQud/*.cs` at game launch (`decompiled/XRL/ModInfo.cs:478, 757-823`). Manual in-game verification against `Player.log` is the acceptance gate.

- New `using` directives needed in `mod/LLMOfQud/SnapshotState.cs`: none. `XRL.World.Parts` (already imported) covers `Stomach`. `XRL.World` (already imported) covers `Statistic`.
- Environment paths (verified 2026-04-25, unchanged from 0-D):
  - `$MODS_DIR=$HOME/Library/Application Support/Kitfox Games/Caves of Qud/Mods`
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Kitfox Games/Caves of Qud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach (mirrors 0-D, ADR 0004 in force):**

- Manual in-game verification on two character runs: a primary Mutant Joppa run (>=100 turns) and a secondary True Kin smoke run (10–20 turns). C# unit tests for `BuildBuildJson` / `AppendBuildIdentity` / `AppendBuildAttributes` / `AppendBuildResources` are deferred to Phase 2a per ADR 0004; substitute is the latest-line + every-line manual JSON-validity probe documented in Task 7.
- Acceptance counts: `[screen] BEGIN == [screen] END == [state] == [caps] == [build]` per run, with `>=100` on primary and `>=10` on secondary. `ERR_SCREEN == 0` is the hard gate; `ERR_STATE / ERR_CAPS / ERR_BUILD == 0` are soft gates.
- Spot-check semantic invariants: 6-key attribute set, integer-only attribute values, `genotype_kind` enum membership, `genotype_id`/`subtype_id` non-null on both runs, `level >= 1`, `hunger != null` and `thirst != null` for both Mutant and True Kin runs, hunger / thirst bucket strings match the closed enum (treated as a hard failure if a new bucket is observed empirically).

**Reference:**

- `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` (spec — locked at `8861358`).
- `docs/architecture-v5.md` (v5.9): `:443-468` (`check_status` consumer contract that drove the pivot), `:1787-1790` (game-queue routing rule), `:2802` (Phase 0-E line being reinterpreted by ADR 0005).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0005.
- `docs/adr/0002-phase-0-b-render-callback-pivot.md:55-66, 106-108` — render-callback emit pattern this plan extends to 4 lines/turn.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/memo/phase-0-d-exit-2026-04-25.md` — Phase 0-D outcomes; `:42-58` provisional cadence trigger list inherited.
- `docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md` — precedent plan structure modeled here.
- CoQ APIs (verified 2026-04-25; re-confirm before each citation per root AGENTS.md §Imperatives item 1):
  - **Player identity**: `GameObject.GetGenotype()` (`decompiled/XRL.World/GameObject.cs:10019`), `GetSubtype()` (`:10024`), `IsTrueKin()` (`:10029-10031`), `IsMutant()` (`:10034-10036`).
  - **Statistics**: `GameObject.GetStat(string)` (`decompiled/XRL.World/GameObject.cs:4373-4383`) returns `null` if the stat is missing. `Statistic.Value` getter (`decompiled/XRL.World/Statistic.cs:238-252`) — clamped, modifier-applied effective value. `Statistic.Attributes` canonical names (`:51-53`): `"Strength"`, `"Agility"`, `"Toughness"`, `"Intelligence"`, `"Willpower"`, `"Ego"`.
  - **Level**: `GameObject.Level` (`decompiled/XRL.World/GameObject.cs:642`) returns `GetStat("Level")?.Value ?? 1`.
  - **Hunger / thirst**: `Stomach.FoodStatus()` (`decompiled/XRL.World.Parts/Stomach.cs:87-102`) returns markup-wrapped strings (`{{g|Sated}}`, `{{W|Hungry}}`, `{{R|Wilted!}}` for `PhotosyntheticSkin`, `{{R|Famished!}}`). `Stomach.WaterStatus()` (`:104-143`) returns markup-wrapped strings for non-amphibious bodies (`{{R|Dehydrated!}}`, `{{r|Parched}}`, `{{Y|Thirsty}}`, `{{g|Quenched}}`, `{{G|Tumescent}}`) and a separate amphibious family (`{{R|Desiccated!}}`, `{{r|Dry}}`, `{{c|Moist}}`, `{{b|Wet}}`, `{{B|Soaked}}`).
  - **MetricsManager.LogInfo**: `decompiled/MetricsManager.cs:407-409` (unchanged, same `Player.log` sink as 0-B/0-C/0-D).

---

## Prerequisites (one-time per session)

Before starting any task, confirm:

1. Phase 0-D is landed on `main` (commit `9a9a3cf feat(mod): Phase 0-D RuntimeCapabilityProfile observation` or a successor). Verify `mod/LLMOfQud/SnapshotState.cs` has the `BuildCapsJson` + `AppendMutations / AppendAbilities / AppendEffects / AppendEquipment` helpers and `mod/LLMOfQud/LLMOfQudSystem.cs` has the `[caps]` emission in its own try scope.
2. The symlink `$MODS_DIR/LLMOfQud` still resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling, re-create per Phase 0-A Task 1.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Kitfox Games/Caves of Qud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Kitfox Games/Caves of Qud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. Two clean save slots for acceptance runs (Task 6): one Mutant build (Warden or any Mutant calling) and one True Kin build (Praetorian or any True Kin calling). Reusing the Phase 0-D Warden as the primary keeps the spot-check character familiar; the secondary need only be a fresh True Kin to exercise the `genotype_kind == "true_kin"` branch.
5. **Disable any coexisting user mod for the acceptance runs.** Phase 0-D's 112-turn run was performed with `QudJP` disabled (single-mod load order: `1: LLMOfQud`). Re-verify the in-game Mods list reflects single-mod load before starting Task 6.

---

## File Structure

ADR / docs created in Task 0; one C# file modified per branch in Tasks 1–5; one memo + one PR in Task 7.

**Docs-only PR (PR-E1, on branch `feat/phase-0-e-design`):**

- Create: `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — ADR documenting the spec pivot from "BirthBuildProfile" (`docs/architecture-v5.md:2802`) to current build state (`:443-468` consumer contract).
- Add: `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` — this plan.
- Append to: `docs/adr/decision-log.md` — index entry for ADR 0005.

**Implementation PR (PR-E2, on branch `feat/phase-0-e-impl` cut from `main` after PR-E1 merges):**

- Modify: `mod/LLMOfQud/SnapshotState.cs`
  - Add `string BuildJson` field to `PendingSnapshot`.
  - Add `BuildBuildJson(int turn, GameObject player)` static method (returns the value of the `[LLMOfQud][build]` line; caller adds the prefix).
  - Add `AppendBuildIdentity(StringBuilder, GameObject)` (genotype_kind + genotype_id + subtype_id), `AppendBuildAttributes(StringBuilder, GameObject)` (6 lowercase keys + integer values), `AppendBuildResources(StringBuilder, GameObject)` (hunger + thirst, normalized strings, nullable when no Stomach).
  - Add `NormalizeStomachStatus(string)` private static helper (markup-strip + trailing-`!`-strip + lowercase) shared by hunger and thirst.
  - Reuse the existing `AppendJsonString` for all string escapes.
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Extend `HandleEvent(BeginTakeActionEvent)`: build `buildJson` on the game thread in a separate `try/catch`, populate `PendingSnapshot.BuildJson`. The `[caps]` build path is unchanged.
  - Extend `AfterRenderCallback`: emit the fourth `MetricsManager.LogInfo("[LLMOfQud][build] " + buildJson)` after the existing `[caps]` emission. The new call sits in its own `try` scope so a `[build]` emission failure does not blank `[screen]` / `[state]` / `[caps]`.

External (created during execution):

- `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `phase-0-d-exit-2026-04-25.md`'s shape.

No manifest edits. No symlink changes. No new dependencies. The Roslyn compile set stays at 3 files (`LLMOfQudSystem.cs`, `SnapshotState.cs`, plus any future split — unchanged for this phase).

---

## Task 0: ADR 0005 + plan landing (docs-only PR-E1, Phase 0-C precedent)

**Why this task exists:** The design spec's "ADR 0005 timing" section (option 1) records the decision: a separate prerequisite docs-only PR lands ADR 0005 + this plan BEFORE the implementation PR opens. Phase 0-C precedent: PR #7 (`ab96d30`) was a docs-only PR that landed `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` + the Phase 0-C plan body before the Phase 0-C implementation PR #9 (`1afbf01`). The ADR re-opens the v5.9 freeze for the `:2802` Phase 0-E line and changes the consumer-facing surface; reviewing it independently of the C# diff is the safer ordering.

**Files:**

- Create: `docs/adr/0005-phase-0-e-current-build-state-pivot.md`
- Modify: `docs/adr/decision-log.md` (append index entry)
- Add: `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` (this plan, when staged for the docs PR)

**Branch:** `feat/phase-0-e-design` (the spec is already committed at `8861358` here; ADR + this plan are added to the same branch and the branch is opened as PR-E1).

- [ ] **Step 1: Verify the branch state.**

```bash
git branch --show-current
git log --oneline feat/phase-0-e-design -5
```

Expected: current branch is `feat/phase-0-e-design`; `git log` shows the spec commits (`035b62a`, `1f4250d`, `d399612`, `8861358`) on top of `9a9a3cf` (Phase 0-D merge to main). If not on `feat/phase-0-e-design`, `git switch feat/phase-0-e-design` first.

- [ ] **Step 2: Read the existing ADR template and ADR 0004 for shape.**

```bash
cat docs/adr/0000-adr-template.md
cat docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md
```

ADR 0005 mirrors ADR 0004's shape: front-matter (Status, Date), Context, Decision, Consequences, Alternatives Considered, References. Length ~80–150 lines.

- [ ] **Step 3: Write `docs/adr/0005-phase-0-e-current-build-state-pivot.md`.**

```markdown
# ADR 0005: Phase 0-E pivot from BirthBuildProfile to current build state

Status: Accepted (<YYYY-MM-DD>)

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
```

Replace `<YYYY-MM-DD>` with the actual date the ADR is finalized (use `date -u +%Y-%m-%d`).

- [ ] **Step 4: Append the index entry to `docs/adr/decision-log.md`.**

Read the existing `decision-log.md` and append (after the latest entry, preserving any existing format):

```markdown
| 0005 | <YYYY-MM-DD> | Accepted | Phase 0-E pivot from BirthBuildProfile to current build state |
```

Match the table column style of the existing entries (`| 0004 | ... | Accepted | ... |`). If the existing log uses a bulleted format instead of a table, mirror that.

- [ ] **Step 5: Run the static checks gate.**

```bash
pre-commit run --all-files
```

Expected: all hooks PASS. The `check_adr_decision.py` hook may require a machine-readable decision record; if it fires, run:

```bash
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Phase 0-E pivot from BirthBuildProfile to current build state" \
  --rationale "check_status (architecture-v5.md:443-468) consumes CURRENT attributes/level/hunger/thirst, not birth-time values; literal Birth capture would ship dead code" \
  --adr docs/adr/0005-phase-0-e-current-build-state-pivot.md
```

Re-run `pre-commit run --all-files` to confirm green.

- [ ] **Step 6: Commit ADR 0005.**

```bash
git add docs/adr/0005-phase-0-e-current-build-state-pivot.md \
        docs/adr/decision-log.md \
        docs/adr/decisions/
git commit -m "docs(adr): ADR 0005 — Phase 0-E pivot from BirthBuildProfile to current build state

Re-opens the docs/architecture-v5.md:2802 Phase 0-E line semantics
under the freeze rule of ADR 0001. The pivot is driven by the
check_status consumer at :443-468 returning CURRENT
attributes/level/hunger/thirst, not birth-time values. Retrospective
birth capture (DeathLogger / cross-run learning) is deferred to a
future Phase 0-?."
```

- [ ] **Step 7: Add this plan to the docs PR.**

```bash
git add docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md
git commit -m "docs(plan): Phase 0-E implementation plan — current build state observation

Mirrors the Phase 0-D plan structure
(docs/superpowers/plans/2026-04-25-phase-0-d-runtime-capability-profile.md).
Two-PR landing per ADR 0005 / spec timing decision: this docs PR lands
ADR + plan + design spec; the implementation PR opens against main
after this PR merges."
```

- [ ] **Step 8: Open PR-E1 (docs-only).**

```bash
git push -u origin feat/phase-0-e-design
gh pr create --title "docs: Phase 0-E readiness — ADR 0005, plan, design spec" \
  --body "$(cat <<'EOF'
## Summary
- ADR 0005 documenting the Phase 0-E pivot from BirthBuildProfile to
  current build state (driven by check_status consumer at
  architecture-v5.md:443-468).
- Phase 0-E design spec (committed earlier on this branch, codex PASS
  at commit 8861358 after 4 review rounds).
- Phase 0-E implementation plan
  (docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md).

## Test plan
- [x] pre-commit run --all-files green
- [x] No source code changes (docs-only PR)
- [ ] CodeRabbit review applied (path_instructions enforcement on the
  spec / plan / ADR)
- [ ] Codex review (already PASS on the spec; expect minor nits on the
  plan and ADR)

## Merge order
After this PR merges, the implementation branch (feat/phase-0-e-impl)
will be cut from main and PR-E2 will open with the C# changes per the
plan.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The PR will be reviewed via CodeRabbit (path_instructions enforce inline `decompiled/<path>.cs:<line>` citations on any CoQ API claim); apply findings until CI is green, then merge per `feedback_docs_pr_merge_policy.md`.

- [ ] **Step 9: Wait for PR-E1 to merge.**

After PR-E1 is merged:

```bash
git checkout main
git pull
git log --oneline -5
```

Expected: `main` HEAD is the squash-merge commit of PR-E1 (something like `<hash> docs: Phase 0-E readiness — ADR 0005, plan, design spec (#N)`).

---

## Implementation branch setup (between Task 0 and Task 1)

After PR-E1 merges and `main` is pulled:

- [ ] **Step 1: Cut the implementation branch from updated `main`.**

```bash
git switch -c feat/phase-0-e-impl
git log --oneline -3
```

Expected: HEAD is the PR-E1 merge commit.

- [ ] **Step 2: Verify the existing 0-D code is on `main`.**

```bash
grep -n "BuildCapsJson\|CapsJson" mod/LLMOfQud/SnapshotState.cs | head -5
grep -n "buildJson\|BuildJson" mod/LLMOfQud/SnapshotState.cs | head -5
```

Expected: `BuildCapsJson` / `CapsJson` are present (Phase 0-D); `buildJson` / `BuildJson` are NOT present yet (Phase 0-E adds them in Task 1).

---

## Task 1: End-to-end `[build]` line stub

**Files:**
- Modify: `mod/LLMOfQud/SnapshotState.cs:13-31` (`PendingSnapshot` class).
- Modify: `mod/LLMOfQud/SnapshotState.cs:592-618` (`BuildCapsJson` neighborhood — append `BuildBuildJson` immediately after).
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs:59-138` (`HandleEvent`).
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs:205-269` (`AfterRenderCallback`).

**Why this task exists:** Lock the threading + emission contract before adding any field-extraction logic. By the end of Task 1, an in-game session produces FOUR LogInfo lines per turn — `[screen]`, `[state]`, `[caps]`, `[build] {"turn":N,"schema":"current_build.v1"}` — with the same correlation contract Phase 0-D established. Field extraction (identity / attributes / resources) is added field-at-a-time in Tasks 2–4 against this stable scaffold. Spec rule per design spec line 10: any new field threads through `PendingSnapshot`, never as a parallel slot.

- [ ] **Step 1: Extend `PendingSnapshot` with `BuildJson`.**

In `mod/LLMOfQud/SnapshotState.cs:13-31`, replace the existing `PendingSnapshot` class with:

```csharp
    internal sealed class PendingSnapshot
    {
        public int Turn;
        public string StateJson;
        // Captured on the game thread alongside StateJson. AfterRenderCallback
        // MUST consume this rather than re-reading Options.UseTiles, which can
        // flip between turns and would otherwise produce inconsistent
        // mode= (in [screen]) vs display_mode= (in [state]) framing for the
        // same turn. See ADR 0002 + game-thread routing rule
        // docs/architecture-v5.md:1787-1790.
        public string DisplayMode;
        // Phase 0-D: RuntimeCapabilityProfile JSON for this turn. Built on the
        // game thread inside HandleEvent so all CoQ API reads stay on the
        // game queue (docs/architecture-v5.md:1787-1790). Render thread emits
        // verbatim. Per docs/memo/phase-0-c-exit-2026-04-25.md:117, future
        // observation fields thread through this object, never as parallel
        // Interlocked.Exchange slots.
        public string CapsJson;
        // Phase 0-E: current build state JSON for this turn. Built on the
        // game thread inside HandleEvent (same routing rule as CapsJson).
        // Schema current_build.v1, locked at design spec commit 8861358 +
        // ADR 0005. Render thread emits verbatim.
        public string BuildJson;
    }
```

- [ ] **Step 2: Add the `BuildBuildJson` stub.**

In `mod/LLMOfQud/SnapshotState.cs`, append immediately AFTER the existing `BuildCapsJson` method (which ends near line 618), still inside the `SnapshotState` static class:

```csharp
        // Entry point used by HandleEvent to build the build line payload
        // (the value of the [LLMOfQud][build] line; caller adds the prefix).
        // Phase 0-E Task 1: stub returning {"turn":N,"schema":"current_build.v1"}.
        // Tasks 2-4 fill in identity / attributes / resources. Schema bumps
        // (v2+) require an ADR. Field order is locked; reordering requires
        // an ADR. See docs/superpowers/specs/2026-04-25-phase-0-e-current-build-
        // state-design.md for the schema and field semantics.
        internal static string BuildBuildJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"current_build.v1\"");
            sb.Append('}');
            return sb.ToString();
        }
```

The `GameObject player` parameter is unused in the stub but locked into the signature so Tasks 2–4 do not need to retouch the caller. CS0219 does not fire on unused method parameters under the Roslyn-CSharp build CoQ ships, so no suppression should be needed.

- [ ] **Step 3: Wire `BuildBuildJson` into `HandleEvent`.**

In `mod/LLMOfQud/LLMOfQudSystem.cs`, replace lines 123–130 inclusive (the existing `PendingSnapshot pending = new PendingSnapshot { Turn=..., CapsJson=capsJson, };` block plus the immediately following `Interlocked.Exchange(ref _pendingSnapshot, pending);` call) with:

```csharp
            // Phase 0-E: build build JSON on the game thread in a separate
            // try/catch. Failure here MUST NOT kill [state] or [caps]
            // emission; produce a valid-JSON sentinel so downstream parsers
            // always see a parseable [build] line for this turn. Use the
            // existing SnapshotState.AppendJsonString helper so control
            // characters (newline / tab / U+0000-U+001F) in ex.Message are
            // escaped RFC-8259 correctly.
            string buildJson;
            try
            {
                buildJson = SnapshotState.BuildBuildJson(_beginTurnCount, The.Player);
            }
            catch (Exception ex)
            {
                StringBuilder errSb = new StringBuilder(256);
                errSb.Append("{\"turn\":").Append(_beginTurnCount.ToString())
                    .Append(",\"schema\":\"current_build.v1\"")
                    .Append(",\"error\":{\"type\":");
                SnapshotState.AppendJsonString(errSb, ex.GetType().Name);
                errSb.Append(",\"message\":");
                SnapshotState.AppendJsonString(errSb, ex.Message ?? "");
                errSb.Append("}}");
                buildJson = errSb.ToString();
                MetricsManager.LogInfo(
                    "[LLMOfQud][build] ERROR turn=" + _beginTurnCount +
                    " " + ex.GetType().Name + ": " + ex.Message);
            }

            PendingSnapshot pending = new PendingSnapshot
            {
                Turn = _beginTurnCount,
                StateJson = stateJson,
                DisplayMode = displayMode,
                CapsJson = capsJson,
                BuildJson = buildJson,
            };
            Interlocked.Exchange(ref _pendingSnapshot, pending);
```

The new `try` block is structurally identical to the existing 0-D `[caps]` build try/catch (the `capsJson` block immediately above it in the file). The only differences are the variable name (`buildJson`), the schema literal (`current_build.v1`), and the log prefix (`[LLMOfQud][build] ERROR`).

- [ ] **Step 4: Extend `AfterRenderCallback` to emit `[build]`.**

In `mod/LLMOfQud/LLMOfQudSystem.cs:212-219`, add `string buildJson = pending.BuildJson;` to the existing snapshot-field unpacking block:

```csharp
            int turn = pending.Turn;
            string stateJson = pending.StateJson;
            string capsJson = pending.CapsJson;
            string buildJson = pending.BuildJson;
            // Reuse the game-thread-captured DisplayMode so the [screen] mode=
            // header and the embedded [state] display_mode= for the same turn
            // are guaranteed to agree even if Options.UseTiles flipped between
            // HandleEvent and AfterRenderCallback.
            string displayMode = pending.DisplayMode;
```

Then in `mod/LLMOfQud/LLMOfQudSystem.cs:260-268`, immediately after the existing `[caps]` try/catch block (which ends near line 268 with the closing `}` of its catch), append a fourth try/catch block:

```csharp

            // Phase 0-E: emit [build] in its own try scope. A [build] failure
            // here MUST NOT blank [screen]/[state]/[caps] for this turn (those
            // have already emitted above). The buildJson value was prepared
            // on the game thread; if its build threw, buildJson is already an
            // error sentinel and this block just emits it verbatim.
            try
            {
                MetricsManager.LogInfo("[LLMOfQud][build] " + buildJson);
            }
            catch (Exception ex)
            {
                MetricsManager.LogInfo(
                    "[LLMOfQud][build] ERROR turn=" + turn + " " + ex.GetType().Name + ": " + ex.Message);
            }
```

The block sits at the same indentation as the `[caps]` try/catch, inside the `AfterRenderCallback` method body, before the method's closing `}`.

- [ ] **Step 5: Compile probe.**

Restart Caves of Qud (full quit + relaunch — mod assembly is cached for the process). Then:

```bash
grep -E "^\[[^]]+\] (=== LLM OF QUD ===|Compiling [0-9]+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$COQ_SAVE_DIR/build_log.txt" | tail -10
```

Expected: a `Compiling 3 files...` (or `Compiling 1 file...` if CoQ batches differently — the regex tolerates either) followed by `Success :)`. **No `COMPILER ERRORS`.** Note: BSD `grep -E` on macOS does NOT recognise `\d`; the pattern uses `[0-9]+` for portability. If the compile fails, the next run won't load the mod; fix and re-launch before proceeding to Step 6.

- [ ] **Step 6: Smoke run — verify all four lines emit per turn.**

Load any save, take 5 player-turn actions (move 5 steps), then quit. Then:

```bash
LOG="$PLAYER_LOG"
echo "screen BEGIN: $(grep -c 'INFO - \[LLMOfQud\]\[screen\] BEGIN' "$LOG")"
echo "screen END:   $(grep -c '^\[LLMOfQud\]\[screen\] END'   "$LOG")"
echo "state:        $(grep -c 'INFO - \[LLMOfQud\]\[state\]'        "$LOG")"
echo "caps:         $(grep -c 'INFO - \[LLMOfQud\]\[caps\]'         "$LOG")"
echo "build:        $(grep -c 'INFO - \[LLMOfQud\]\[build\]'        "$LOG")"
echo "ERROR:        $(grep -c '\[LLMOfQud\]\[\(screen\|state\|caps\|build\)\] ERROR' "$LOG")"
```

Expected: all five counts equal (5 ± 1 — CoQ may pump an extra render-callback after the last move), ERROR=0.

- [ ] **Step 7: JSON validity probe.**

```bash
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "import sys, json; d = json.loads(sys.stdin.read()); print('OK turn=' + str(d['turn']) + ' schema=' + d['schema'])"
```

Expected: `OK turn=5 schema=current_build.v1` (or whatever turn count Step 6 ended at). If `python3` raises `json.JSONDecodeError`, the stub line is malformed; fix before proceeding.

- [ ] **Step 8: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "feat(mod): Phase 0-E Task 1 — [build] line stub end-to-end

PendingSnapshot gains BuildJson field; HandleEvent builds a stub build
JSON on the game thread in its own try/catch; AfterRenderCallback emits
a fourth LogInfo line per turn. Stub payload is
{\"turn\":N,\"schema\":\"current_build.v1\"}. Field extraction
(identity / attributes / resources) added in Tasks 2-4."
```

---

## Task 2: `AppendBuildIdentity` — genotype_kind + genotype_id + subtype_id

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendBuildIdentity` helper, wire into `BuildBuildJson`.

**Why this task exists:** Identity is the first field group because it has the cleanest dependency surface: three string-or-null reads (`GetGenotype()`, `GetSubtype()`, derived `genotype_kind`) with one explicit-null path each. Implementing identity first lets Tasks 3–4 reuse the StringBuilder + `BuildBuildJson` wiring without re-touching the spec's null-handling rule from spec line 58.

- [ ] **Step 1: Add `AppendBuildIdentity` to `SnapshotState`.**

In `mod/LLMOfQud/SnapshotState.cs`, append inside the `SnapshotState` static class, immediately above the `BuildBuildJson` method added in Task 1 Step 2:

```csharp
        // Schema slice (current_build.v1):
        //   "genotype_kind": "mutant" | "true_kin" | "unknown",
        //   "genotype_id": <string or null>,
        //   "subtype_id": <string or null>
        // genotype_kind is derived from IsTrueKin/IsMutant (mutually
        // exclusive in normal CoQ play). "unknown" is exposed honestly
        // rather than silently coerced; acceptance criterion 8 hard-gates
        // count("unknown") == 0 across both runs.
        // Per spec line 58: AppendJsonString(null) emits "" (empty string),
        // NOT JSON null; for the genotype_id/subtype_id null case we MUST
        // emit sb.Append("null") explicitly.
        // decompiled/XRL.World/GameObject.cs:10019 (GetGenotype)
        // decompiled/XRL.World/GameObject.cs:10024 (GetSubtype)
        // decompiled/XRL.World/GameObject.cs:10029-10031 (IsTrueKin)
        // decompiled/XRL.World/GameObject.cs:10034-10036 (IsMutant)
        internal static void AppendBuildIdentity(StringBuilder sb, GameObject player)
        {
            string kind;
            if (player == null)
            {
                kind = "unknown";
            }
            else if (player.IsTrueKin())
            {
                kind = "true_kin";
            }
            else if (player.IsMutant())
            {
                kind = "mutant";
            }
            else
            {
                kind = "unknown";
            }
            sb.Append("\"genotype_kind\":");
            AppendJsonString(sb, kind);

            sb.Append(",\"genotype_id\":");
            string genotypeId = player?.GetGenotype();
            if (genotypeId == null)
            {
                sb.Append("null");
            }
            else
            {
                AppendJsonString(sb, genotypeId);
            }

            sb.Append(",\"subtype_id\":");
            string subtypeId = player?.GetSubtype();
            if (subtypeId == null)
            {
                sb.Append("null");
            }
            else
            {
                AppendJsonString(sb, subtypeId);
            }
        }
```

- [ ] **Step 2: Wire `AppendBuildIdentity` into `BuildBuildJson`.**

In `mod/LLMOfQud/SnapshotState.cs`, replace the `BuildBuildJson` method (added in Task 1 Step 2) with:

```csharp
        // Entry point used by HandleEvent to build the build line payload
        // (the value of the [LLMOfQud][build] line; caller adds the prefix).
        // Schema current_build.v1: {turn, schema, genotype_kind, genotype_id,
        // subtype_id, level, attributes, hunger, thirst}. Schema bumps (v2+)
        // require an ADR. Field order is locked; reordering requires an ADR.
        internal static string BuildBuildJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"current_build.v1\",");
            AppendBuildIdentity(sb, player);
            sb.Append('}');
            return sb.ToString();
        }
```

The trailing `,` after `"current_build.v1"` is the separator before `genotype_kind`; `AppendBuildIdentity` does NOT emit a leading comma (it owns the `genotype_kind` key first).

- [ ] **Step 3: Compile probe.**

Restart CoQ. Then:

```bash
grep -E "^\[[^]]+\] (Compiling [0-9]+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$COQ_SAVE_DIR/build_log.txt" | tail -5
```

Expected: `Compiling N files... Success :)`, no `COMPILER ERRORS`.

- [ ] **Step 4: Smoke run — identity line shape.**

Load a save (Mutant for the first run — identity reads on a Warden produce `genotype_kind="mutant", genotype_id="Mutated Human", subtype_id="Warden"`), take 3 player turns, quit. Then:

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
assert d['schema'] == 'current_build.v1', 'schema: ' + d['schema']
assert d['genotype_kind'] in {'mutant', 'true_kin', 'unknown'}, 'kind: ' + d['genotype_kind']
assert d['genotype_id'] is None or isinstance(d['genotype_id'], str), 'genotype_id type'
assert d['subtype_id']  is None or isinstance(d['subtype_id'],  str), 'subtype_id type'
print('OK turn=' + str(d['turn']) + ' kind=' + d['genotype_kind'] + ' geno=' + str(d['genotype_id']) + ' sub=' + str(d['subtype_id']))
"
```

Expected on a Warden save: `OK turn=N kind=mutant geno=Mutated Human sub=Warden`. On a True Kin save: `OK turn=N kind=true_kin geno=True Kin sub=<calling>`. If genotype/subtype come back null on a normal-play save, that's a CoQ API miss; investigate before continuing.

- [ ] **Step 5: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-E Task 2 — AppendBuildIdentity (genotype + subtype)

genotype_kind derived from IsTrueKin/IsMutant; genotype_id/subtype_id
read via GetGenotype/GetSubtype; explicit null emission per spec line 58
(AppendJsonString(null) emits empty string, not JSON null)."
```

---

## Task 3: `AppendBuildAttributes` — 6 lowercase keys, integer values

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `AppendBuildAttributes` helper, wire into `BuildBuildJson`.

**Why this task exists:** Attributes are the largest field of the `[build]` line by character count (`{"strength":18,"agility":16,...}`). Per spec line 61, CoQ's canonical attribute names are CapsCase (`Statistic.Attributes` at `decompiled/XRL.World/Statistic.cs:51-53`); the JSON output is lowercase. The implementation reads `player.GetStat("Strength")` (CapsCase key) and emits the JSON key in lowercase. `Statistic.Value` is the clamped, modifier-applied effective value combat math uses (spec line 61); `_Value + _Bonus - _Penalty` semantics. `level` is captured here too because it's structurally an integer-typed attribute even though it's a separate top-level key in the schema; co-locating the read keeps the `GetStat` calls in one helper.

- [ ] **Step 1: Add `AppendBuildAttributes` to `SnapshotState`.**

In `mod/LLMOfQud/SnapshotState.cs`, append inside the `SnapshotState` static class, immediately AFTER `AppendBuildIdentity` and BEFORE `BuildBuildJson`:

```csharp
        // The 6 canonical attribute names CoQ stores under (CapsCase per
        // Statistic.Attributes at decompiled/XRL.World/Statistic.cs:51-53).
        // Output JSON uses lowercase keys per current_build.v1 schema lock.
        // Order matches Statistic.Attributes (Strength/Agility/Toughness/
        // Intelligence/Willpower/Ego), preserved here so the JSON object
        // key ordering is stable across turns.
        private static readonly string[] _AttrCoqNames = new string[]
        {
            "Strength", "Agility", "Toughness",
            "Intelligence", "Willpower", "Ego",
        };
        private static readonly string[] _AttrJsonKeys = new string[]
        {
            "strength", "agility", "toughness",
            "intelligence", "willpower", "ego",
        };

        // Schema slice (current_build.v1):
        //   "level": <int>,
        //   "attributes": {
        //     "strength": <int>, "agility": <int>, "toughness": <int>,
        //     "intelligence": <int>, "willpower": <int>, "ego": <int>
        //   }
        // Statistic.Value is the clamped, modifier-applied effective value
        // (decompiled/XRL.World/Statistic.cs:238-252); _Value+_Bonus-_Penalty.
        // Consumers do NOT need to recompute. base_value/modifier_total were
        // dropped from v1 per spec line 61.
        // GetStat returns null if the stat is missing
        // (decompiled/XRL.World/GameObject.cs:4373-4383); on null we emit
        // 0 for that attribute and continue (no sentinel) — a missing stat
        // is informative-by-zero, not a build error.
        // GameObject.Level (decompiled/XRL.World/GameObject.cs:642) is
        // GetStat("Level")?.Value ?? 1; we read it through the same path.
        internal static void AppendBuildAttributes(StringBuilder sb, GameObject player)
        {
            // Level is a top-level field per current_build.v1, not nested
            // under attributes. Co-located here only for Stat-read locality.
            int level = player?.Level ?? 1;
            sb.Append("\"level\":").Append(level.ToString(CultureInfo.InvariantCulture));

            sb.Append(",\"attributes\":{");
            for (int i = 0; i < _AttrCoqNames.Length; i++)
            {
                if (i > 0) sb.Append(',');
                AppendJsonString(sb, _AttrJsonKeys[i]);
                sb.Append(':');
                Statistic stat = player?.GetStat(_AttrCoqNames[i]);
                int value = stat?.Value ?? 0;
                sb.Append(value.ToString(CultureInfo.InvariantCulture));
            }
            sb.Append('}');
        }
```

- [ ] **Step 2: Wire `AppendBuildAttributes` into `BuildBuildJson`.**

Replace the `BuildBuildJson` method (last touched in Task 2) with:

```csharp
        internal static string BuildBuildJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"current_build.v1\",");
            AppendBuildIdentity(sb, player);
            sb.Append(',');
            AppendBuildAttributes(sb, player);
            sb.Append('}');
            return sb.ToString();
        }
```

The single comma between `AppendBuildIdentity` and `AppendBuildAttributes` is the separator between the identity block (`subtype_id`) and the attributes block (`level`); `AppendBuildAttributes` owns the `level` key first (no leading comma).

- [ ] **Step 3: Compile probe.**

Same as Task 2 Step 3.

- [ ] **Step 4: Smoke run — attribute line shape.**

Load a save, take 3 player turns, quit. Then:

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
expected = {'strength', 'agility', 'toughness', 'intelligence', 'willpower', 'ego'}
got = set(d['attributes'].keys())
assert got == expected, 'attribute keys: ' + str(got ^ expected)
for k, v in d['attributes'].items():
    assert isinstance(v, int), k + ' not int: ' + str(type(v))
assert isinstance(d['level'], int) and d['level'] >= 1, 'level: ' + str(d['level'])
print('OK turn=' + str(d['turn']) + ' level=' + str(d['level']) + ' attrs=' + str(d['attributes']))
"
```

Expected: `OK turn=N level=L attrs={'strength': S, 'agility': A, 'toughness': T, 'intelligence': I, 'willpower': W, 'ego': E}` with all values integers and `level >= 1`. If a attribute key set mismatch fires, the helper has a typo; if `level == 0`, `player?.Level` returned the default for a null player, indicating a save that didn't fully load before the first BeginTakeActionEvent.

- [ ] **Step 5: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-E Task 3 — AppendBuildAttributes (level + 6 attributes)

CapsCase-to-lowercase mapping per Statistic.Attributes
(decompiled/XRL.World/Statistic.cs:51-53). Statistic.Value emitted
(clamped + modifier-applied per spec line 61); level read via
GameObject.Level (GetStat(\"Level\")?.Value ?? 1)."
```

---

## Task 4: `AppendBuildResources` — hunger + thirst (markup-stripped, nullable)

**Files:**

- Modify: `mod/LLMOfQud/SnapshotState.cs` — add `NormalizeStomachStatus` private helper + `AppendBuildResources` helper, wire into `BuildBuildJson`.

**Why this task exists:** Hunger / thirst are the only fields requiring string normalization (CoQ wraps display strings in `{{<color>|...}}` markup with trailing `!` on famished / wilted / dehydrated / desiccated, per spec line 62–63). Per spec line 118 (Stomach-less body hazard), both fields are emitted as JSON `null` when `player.GetPart<Stomach>()` is null (robot bodies, body-swap to non-creature). The shared `NormalizeStomachStatus` helper avoids duplicating the markup-strip + trailing-`!`-strip + lowercase logic in two places.

- [ ] **Step 1: Add `NormalizeStomachStatus` private helper.**

In `mod/LLMOfQud/SnapshotState.cs`, append inside the `SnapshotState` static class, immediately AFTER `AppendBuildAttributes` and BEFORE `BuildBuildJson`:

```csharp
        // Strip CoQ {{<color>|...}} markup, drop a trailing "!" if present,
        // and lowercase. Used by AppendBuildResources for hunger/thirst.
        // Examples (decompiled/XRL.World.Parts/Stomach.cs:87-143):
        //   "{{g|Sated}}"        -> "sated"
        //   "{{W|Hungry}}"       -> "hungry"
        //   "{{R|Wilted!}}"      -> "wilted"     (PhotosyntheticSkin only)
        //   "{{R|Famished!}}"    -> "famished"
        //   "{{R|Dehydrated!}}"  -> "dehydrated"
        //   "{{r|Parched}}"      -> "parched"
        //   "{{Y|Thirsty}}"      -> "thirsty"
        //   "{{g|Quenched}}"     -> "quenched"
        //   "{{G|Tumescent}}"    -> "tumescent"
        // Returns null if input is null (caller emits JSON null in that
        // case, NOT empty string). Returns input verbatim (lowercased)
        // if no markup matched, so future markup style changes do not
        // silently drop content — they show up as a non-enum bucket
        // and trip acceptance criterion 8.
        private static string NormalizeStomachStatus(string raw)
        {
            if (raw == null) return null;
            string s = raw;
            // Strip leading "{{<C>|" if present.
            if (s.Length >= 5 && s[0] == '{' && s[1] == '{' && s.IndexOf('|') > 2)
            {
                int barIdx = s.IndexOf('|');
                s = s.Substring(barIdx + 1);
            }
            // Strip trailing "}}" if present.
            if (s.EndsWith("}}"))
            {
                s = s.Substring(0, s.Length - 2);
            }
            // Strip trailing "!" if present (Famished!/Wilted!/Dehydrated!/Desiccated!).
            if (s.Length > 0 && s[s.Length - 1] == '!')
            {
                s = s.Substring(0, s.Length - 1);
            }
            return s.ToLowerInvariant();
        }
```

- [ ] **Step 2: Add `AppendBuildResources` helper.**

In `mod/LLMOfQud/SnapshotState.cs`, append inside the `SnapshotState` static class, immediately AFTER `NormalizeStomachStatus` and BEFORE `BuildBuildJson`:

```csharp
        // Schema slice (current_build.v1):
        //   "hunger": <string-or-null>,
        //   "thirst": <string-or-null>
        // Both emitted as JSON null when player.GetPart<Stomach>() is null
        // (robot body, body-swap to non-creature object) per spec line 118.
        // For non-amphibious bodies the bucket sets are:
        //   hunger: {sated, hungry, wilted, famished}
        //     (wilted only for PhotosyntheticSkin)
        //   thirst: {tumescent, quenched, thirsty, parched, dehydrated}
        // Amphibious bodies use a separate thirst bucket family
        // (desiccated/dry/moist/wet/soaked) which the v1 acceptance gate
        // does not assert (spec hazard "Hunger/thirst bucket stability").
        // decompiled/XRL.World.Parts/Stomach.cs:87-102 (FoodStatus)
        // decompiled/XRL.World.Parts/Stomach.cs:104-143 (WaterStatus)
        internal static void AppendBuildResources(StringBuilder sb, GameObject player)
        {
            Stomach stomach = player?.GetPart<Stomach>();
            string hunger = (stomach != null) ? NormalizeStomachStatus(stomach.FoodStatus()) : null;
            string thirst = (stomach != null) ? NormalizeStomachStatus(stomach.WaterStatus()) : null;

            sb.Append("\"hunger\":");
            if (hunger == null) sb.Append("null"); else AppendJsonString(sb, hunger);

            sb.Append(",\"thirst\":");
            if (thirst == null) sb.Append("null"); else AppendJsonString(sb, thirst);
        }
```

- [ ] **Step 3: Wire `AppendBuildResources` into `BuildBuildJson` (final form).**

Replace the `BuildBuildJson` method (last touched in Task 3) with:

```csharp
        internal static string BuildBuildJson(int turn, GameObject player)
        {
            StringBuilder sb = new StringBuilder(512);
            sb.Append("{\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
            sb.Append(",\"schema\":\"current_build.v1\",");
            AppendBuildIdentity(sb, player);
            sb.Append(',');
            AppendBuildAttributes(sb, player);
            sb.Append(',');
            AppendBuildResources(sb, player);
            sb.Append('}');
            return sb.ToString();
        }
```

- [ ] **Step 4: Compile probe.**

Same as Task 2 Step 3.

- [ ] **Step 5: Smoke run — full line shape.**

Load a Mutant save (Warden), take 3 player turns, quit. Then:

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
expected_keys = {'turn', 'schema', 'genotype_kind', 'genotype_id', 'subtype_id',
                 'level', 'attributes', 'hunger', 'thirst'}
got_keys = set(d.keys())
assert got_keys == expected_keys, 'top-level keys: ' + str(got_keys ^ expected_keys)
hunger_set = {None, 'sated', 'hungry', 'wilted', 'famished'}
thirst_set = {None, 'tumescent', 'quenched', 'thirsty', 'parched', 'dehydrated'}
assert d['hunger'] in hunger_set, 'hunger: ' + str(d['hunger'])
assert d['thirst'] in thirst_set, 'thirst: ' + str(d['thirst'])
print('OK turn=' + str(d['turn']) + ' kind=' + d['genotype_kind'] + ' level=' + str(d['level']) + ' hunger=' + str(d['hunger']) + ' thirst=' + str(d['thirst']))
"
```

Expected on a non-amphibious Warden: `OK turn=N kind=mutant level=L hunger=sated thirst=quenched` (or whatever bucket the Warden is in). If `hunger`/`thirst` come back as a non-enum string (e.g., `"sated}}"` or `"famished!"`), the markup / trailing-`!` strip is wrong; if they come back null on a Mutant save, `GetPart<Stomach>()` returned null on a body that should have one — investigate.

- [ ] **Step 6: Commit.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git commit -m "feat(mod): Phase 0-E Task 4 — AppendBuildResources (hunger + thirst)

NormalizeStomachStatus shared helper strips {{<C>|...}} markup +
trailing ! + lowercases; emits JSON null when GetPart<Stomach>()
returns null (robot/body-swap policy per spec line 118). Hunger from
FoodStatus(), thirst from WaterStatus()."
```

---

## Task 5: Final wire-up sanity check + every-line schema gate

**Files:** none (no source changes; this task is a checkpoint between Task 4 and the long acceptance run in Task 6).

**Why this task exists:** Task 4 left `BuildBuildJson` in its final form; running a quick 5-turn smoke + every-line gate before sinking 100+ turns into the primary acceptance run catches "schema name typo committed in Task 1, missed in Task 2/3/4 because every commit re-emits the same typo" class bugs cheaply.

- [ ] **Step 1: Restart CoQ, load any save, take 5 turns, quit.**

(No code change between Task 4 and here; the CoQ process is already running the Task 4 binary if you didn't quit. If you did quit between tasks, restart CoQ now.)

- [ ] **Step 2: Every-line JSON validity gate.**

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
normal_required = {'turn', 'schema', 'genotype_kind', 'genotype_id', 'subtype_id',
                   'level', 'attributes', 'hunger', 'thirst'}
sentinel_required = {'turn', 'schema', 'error'}
fail = 0
total = 0
sentinels = 0
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    total += 1
    try:
        d = json.loads(line)
        assert d.get('schema') == 'current_build.v1', 'unexpected schema: ' + str(d.get('schema'))
        if 'error' in d:
            missing = sentinel_required - set(d.keys())
            assert not missing, 'sentinel missing keys at turn ' + str(d.get('turn','?')) + ': ' + str(missing)
            sentinels += 1
            print('SENTINEL turn=' + str(d.get('turn','?')) + ' type=' + d['error'].get('type',''))
        else:
            got = set(d.keys())
            assert got == normal_required, 'turn ' + str(d.get('turn','?')) + ' key set mismatch: ' + str(got ^ normal_required)
    except Exception as exc:
        fail += 1
        print('FAIL line=' + line[:120] + ' err=' + str(exc))
if fail:
    sys.exit(1)
print('OK ' + str(total) + ' lines parsed clean (' + str(sentinels) + ' sentinels)')
"
```

Expected: `OK N lines parsed clean (0 sentinels)`. Any FAIL is a hard gate; investigate before continuing.

- [ ] **Step 3: No commit.** Task 5 is checkpoint-only.

---

## Task 6: Acceptance runs (primary >=100 + secondary smoke 10–20)

**Files:** none (acceptance runs produce no source changes; the exit memo in Task 7 records the run outcomes).

**Why this task exists:** Lock the `current_build.v1` contract empirically against two character builds before declaring the implementation complete. Per spec criterion 9 (two-build smoke), the primary run is a Mutant build (>=100 turns) and the secondary is a True Kin build (10–20 turns). Justification per spec: `BuildBuildJson` does NOT branch on genotype, but the True Kin run exercises the `genotype_kind == "true_kin"` enum branch and a True-Kin-side `subtype_id`.

### Primary run (Mutant, >=100 turns)

- [ ] **Step 1: Setup — Mutant save.**

Reuse the Phase 0-D Warden save if available (the True Mutant 8-mutation Warden), or create a new Mutant character of any calling. Verify single-mod load order: in-game Mods list shows only `LLMOfQud` enabled.

- [ ] **Step 2: Truncate Player.log to isolate the run.**

```bash
> "$PLAYER_LOG"
```

(Truncates Player.log; CoQ will re-open and append on next emission.)

- [ ] **Step 3: Play >=100 player turns.**

Do whatever in-game is convenient — Joppa exploration, combat, ability use, equipment shuffles. Save / load round-trips are encouraged (Step 6 / spec hazard "Save/load resilience" requires the exit memo to record whether at least one save → load occurred). Quit cleanly when done.

- [ ] **Step 4: Counts gate.**

```bash
LOG="$PLAYER_LOG"
SBEGIN=$(grep -c 'INFO - \[LLMOfQud\]\[screen\] BEGIN' "$LOG")
SEND=$(grep -c '^\[LLMOfQud\]\[screen\] END'   "$LOG")
STATE=$(grep -c 'INFO - \[LLMOfQud\]\[state\]'        "$LOG")
CAPS=$(grep -c 'INFO - \[LLMOfQud\]\[caps\]'          "$LOG")
BUILD=$(grep -c 'INFO - \[LLMOfQud\]\[build\]'        "$LOG")
ERR_SCREEN=$(grep -c '\[LLMOfQud\]\[screen\] ERROR' "$LOG")
ERR_STATE=$(grep -c '\[LLMOfQud\]\[state\] ERROR' "$LOG")
ERR_CAPS=$(grep -c '\[LLMOfQud\]\[caps\] ERROR' "$LOG")
ERR_BUILD=$(grep -c '\[LLMOfQud\]\[build\] ERROR' "$LOG")
echo "BEGIN=$SBEGIN END=$SEND STATE=$STATE CAPS=$CAPS BUILD=$BUILD"
echo "ERR_SCREEN=$ERR_SCREEN ERR_STATE=$ERR_STATE ERR_CAPS=$ERR_CAPS ERR_BUILD=$ERR_BUILD"
```

Expected per spec criterion 2:
- `BEGIN == END == STATE == CAPS == BUILD >= 100`.
- `ERR_SCREEN == 0`. **Hard gate.**
- `ERR_STATE / ERR_CAPS / ERR_BUILD == 0`. Soft gates; non-zero values are recorded in the exit memo.

If counts drift > 1 against each other, the `[build]` emission lost adjacency contract — investigate before declaring acceptance.

- [ ] **Step 5: Latest-line + every-line + key-set gate (spec criteria 5, 6).**

```bash
LOG="$PLAYER_LOG"
# Criterion 5: latest line non-sentinel.
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | tail -1 | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
d = json.loads(sys.stdin.read())
assert 'error' not in d, 'latest line is sentinel; criterion 5 fail'
required = {'turn', 'schema', 'genotype_kind', 'genotype_id', 'subtype_id',
            'level', 'attributes', 'hunger', 'thirst'}
got = set(d.keys())
assert got == required, 'latest key set: ' + str(got ^ required)
assert d['schema'] == 'current_build.v1', 'schema: ' + d['schema']
print('LATEST OK turn=' + str(d['turn']))
"

# Criterion 6: every line schema + key set.
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
normal_required = {'turn', 'schema', 'genotype_kind', 'genotype_id', 'subtype_id',
                   'level', 'attributes', 'hunger', 'thirst'}
sentinel_required = {'turn', 'schema', 'error'}
fail = 0
total = 0
sentinels = 0
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    total += 1
    try:
        d = json.loads(line)
        assert d.get('schema') == 'current_build.v1', 'turn ' + str(d.get('turn','?')) + ' schema: ' + str(d.get('schema'))
        if 'error' in d:
            missing = sentinel_required - set(d.keys())
            assert not missing, 'sentinel missing keys: ' + str(missing)
            sentinels += 1
        else:
            got = set(d.keys())
            assert got == normal_required, 'turn ' + str(d.get('turn','?')) + ' key set mismatch: ' + str(got ^ normal_required)
    except Exception as exc:
        fail += 1
        print('FAIL line=' + line[:120] + ' err=' + str(exc))
if fail:
    sys.exit(1)
print('EVERY OK ' + str(total) + ' lines parsed clean (' + str(sentinels) + ' sentinels)')
"
```

Expected: `LATEST OK turn=N` and `EVERY OK N lines parsed clean (0 sentinels)` (or with ≤ a small documented sentinel count if `ERR_BUILD > 0` was investigated). Any FAIL is a hard gate.

- [ ] **Step 6: Shape parity (spec criterion 7).**

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json
non_sentinel = []
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    d = json.loads(line)
    if 'error' in d: continue
    non_sentinel.append(d)
assert non_sentinel, 'no non-sentinel lines'
first = non_sentinel[0]
last  = non_sentinel[-1]
assert sorted(first.keys()) == sorted(last.keys()), 'top-level keys diverged: ' + str(set(first.keys()) ^ set(last.keys()))
assert sorted(first['attributes'].keys()) == sorted(last['attributes'].keys()), 'attributes keys diverged'
print('SHAPE OK first turn=' + str(first['turn']) + ' last turn=' + str(last['turn']))
"
```

Expected: `SHAPE OK first turn=F last turn=L`. Catches conditional field omission (e.g. an `if (x) sb.Append(",foo:...")` that only emits a key when present).

- [ ] **Step 7: Semantic invariants gate (spec criterion 8).**

```bash
LOG="$PLAYER_LOG"
grep 'INFO - \[LLMOfQud\]\[build\] ' "$LOG" | sed 's/^.*\[LLMOfQud\]\[build\] //' \
  | python3 -c "
import sys, json, collections
turns = []
for line in sys.stdin:
    line = line.rstrip('\n')
    if not line: continue
    d = json.loads(line)
    if 'error' in d: continue
    turns.append(d)

# 1. attributes: exactly 6 lowercase keys, all integer values.
expected_attrs = {'strength', 'agility', 'toughness', 'intelligence', 'willpower', 'ego'}
for t in turns:
    got = set(t['attributes'].keys())
    assert got == expected_attrs, 'turn ' + str(t['turn']) + ' attribute keys: ' + str(got ^ expected_attrs)
    for k, v in t['attributes'].items():
        assert isinstance(v, int), 'turn ' + str(t['turn']) + ' attribute ' + k + ' not int: ' + str(type(v))

# 2. genotype_kind enum + zero unknowns.
unknown = [t['turn'] for t in turns if t['genotype_kind'] == 'unknown']
assert not unknown, 'genotype_kind=unknown on turns: ' + str(unknown[:5])
for t in turns:
    assert t['genotype_kind'] in {'mutant', 'true_kin'}, 'turn ' + str(t['turn']) + ' kind: ' + t['genotype_kind']

# 3. level positive integer.
for t in turns:
    assert isinstance(t['level'], int) and t['level'] >= 1, 'turn ' + str(t['turn']) + ' level: ' + str(t['level'])

# 4. genotype_id / subtype_id non-null on acceptance runs.
for t in turns:
    assert t['genotype_id'] is not None, 'turn ' + str(t['turn']) + ' genotype_id null'
    assert t['subtype_id']  is not None, 'turn ' + str(t['turn']) + ' subtype_id null'

# 5. hunger/thirst non-null + closed enum membership (Mutant + True Kin both have Stomach).
hunger_set = {'sated', 'hungry', 'wilted', 'famished'}
thirst_set = {'tumescent', 'quenched', 'thirsty', 'parched', 'dehydrated'}
for t in turns:
    assert t['hunger'] is not None, 'turn ' + str(t['turn']) + ' hunger null on Stomach-bearing build'
    assert t['thirst'] is not None, 'turn ' + str(t['turn']) + ' thirst null on Stomach-bearing build'
    assert t['hunger'] in hunger_set, 'turn ' + str(t['turn']) + ' hunger: ' + t['hunger']
    assert t['thirst'] in thirst_set, 'turn ' + str(t['turn']) + ' thirst: ' + t['thirst']

print('INVARIANTS OK across ' + str(len(turns)) + ' non-sentinel turns')
"
```

Expected: `INVARIANTS OK across N non-sentinel turns`. Any assertion failure is a hard gate fail per spec criterion 8.

- [ ] **Step 8: Save the primary run log artifact.**

```bash
mkdir -p /tmp/phase-0-e-acceptance
cp "$PLAYER_LOG" /tmp/phase-0-e-acceptance/Player.log.primary-mutant
ls -la /tmp/phase-0-e-acceptance/
```

(So Task 7 exit memo can reference exact line counts and the True Kin secondary run can run from a clean log.)

### Secondary run (True Kin, 10–20 turns)

- [ ] **Step 9: Setup — True Kin save.**

Create a new True Kin character (any calling — Praetorian, Apostle, Esper, etc.) or load an existing True Kin save. Verify single-mod load order again.

- [ ] **Step 10: Truncate Player.log.**

```bash
> "$PLAYER_LOG"
```

- [ ] **Step 11: Play 10–20 player turns.**

Joppa exploration is fine; the run only needs to exercise `genotype_kind == "true_kin"` and produce a non-null True Kin `subtype_id`.

- [ ] **Step 12: Counts gate (>=10).**

Same as Step 4 but with `>=10` threshold and noting this is the True Kin run.

- [ ] **Step 13: Every-line gate + invariants gate.**

Re-run Steps 5 + 7 against the True Kin log. The invariants gate from Step 7 still applies — `genotype_kind` should resolve to `"true_kin"` for every non-sentinel turn (caught by the `t['genotype_kind'] in {'mutant', 'true_kin'}` assertion).

- [ ] **Step 14: Save the secondary run log artifact.**

```bash
cp "$PLAYER_LOG" /tmp/phase-0-e-acceptance/Player.log.secondary-truekin
```

- [ ] **Step 15: No commit.** Task 6 produces no source changes.

---

## Task 7: Exit memo + implementation PR (PR-E2)

**Files:**

- Create: `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` (today's date in `YYYY-MM-DD`).

**Why this task exists:** Phase 0-A / 0-B / 0-C / 0-D precedent. The exit memo locks the empirical state for downstream phases to reference, records open hazards that survived this phase, and feeds-forward design questions to the next phase.

- [ ] **Step 1: Write the exit memo.**

Create `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` with the following structure (mirrors `phase-0-d-exit-2026-04-25.md`):

```markdown
# Phase 0-E Exit — <YYYY-MM-DD>

## Outcome
- Primary Mutant Joppa run: BEGIN == END == [state] == [caps] == [build] == N (>=100). ERROR=0 across screen/state/caps/build.
- Secondary True Kin smoke run: BEGIN == END == [state] == [caps] == [build] == M (10-20). ERROR=0.
- Latest [build] line on each run passes json.loads, is non-sentinel, has all 9 top-level keys, schema == "current_build.v1".
- Every-line gate clean on both runs (0 sentinels).
- Shape parity OK on the primary run.
- Semantic invariants OK on both runs (6 lowercase attribute keys, integer values, genotype_kind enum, level >= 1, hunger/thirst non-null + closed enum).
- Save/load round-trip: <occurred N times during primary run | did not occur — coverage gap recorded>.

## Acceptance counts
| Frame | Primary (Mutant) | Secondary (True Kin) |
|---|---|---|
| [screen] BEGIN | <N> | <M> |
| [screen] END | <N> | <M> |
| [state] | <N> | <M> |
| [caps] | <N> | <M> |
| [build] | <N> | <M> |
| ERROR (any frame) | 0 | 0 |

## Verified environment
- CoQ build: `BUILD_2_0_<...>` (re-grep `build_log.txt`)
- Single-mod load order: `1: LLMOfQud` (QudJP / others disabled or absent)
- macOS path layout: unchanged from Phase 0-D exit memo

## Phase 0-E-specific implementation rules (carry forward to next phases)
1. Build JSON build runs on the game thread inside `HandleEvent(BeginTakeActionEvent)`. Render thread emits prepared strings only. Same routing rule as Phase 0-C/0-D.
2. `PendingSnapshot.BuildJson` is the single threading slot for build payload. Future build fields (e.g. retrospective birth profile) thread through this object, never as a parallel slot.
3. Per-turn cadence is full dump. Provisional clause: migrate to a better cadence if measured constraints justify it (see "Open hazards / future revisit" below + spec line 28).
4. Schema is `current_build.v1`. Field additions require a v2 bump + ADR. Reordering existing fields requires an ADR.
5. `[build]` failure is independent of `[caps]` and `[screen]+[state]` (which share a try, an inherited 0-C/0-D constraint). Sentinel JSON (always parseable) replaces the data on a build error.
6. Hunger/thirst observation is post-`UpdateHunger()` / post-water-update on the game-thread `BeginTakeActionEvent`. Bucket strings are CoQ's display values normalized (markup-stripped, trailing-`!`-stripped, lowercased).
7. ADR 0005 records the pivot from BirthBuildProfile (`docs/architecture-v5.md:2802` literal) to current build state (`:443-468` consumer contract).

## Provisional cadence — future revisit triggers (inherited from 0-D + extended)
The every-turn full dump approach is provisional. Re-open the cadence design when ANY of the following becomes empirically true:
1. Phase 1 WebSocket boundary lands and per-turn payload becomes a measurable bandwidth or token-cost item.
2. `Player.log` size becomes a deployment-blocker on long streaming sessions.
3. Provider-neutral request / token / cache-cost metrics show the redundant stable-list portion harms cost or cache reuse.
4. Phase 0-H `snapshot_hash` design needs separated stable / volatile components.
5. A future phase introduces inventory full dump and per-turn payload doubles.
6. Game-thread frame-time or GC pressure regression attributable to `BuildBuildJson` allocations (full StringBuilder + boxed numerics every turn).
7. Save/load round-trip semantics become load-bearing: spec hazard "Save/load resilience" trips (build values inconsistent with pre-save state on the first non-sentinel turn after `AfterGameLoadedEvent`).
8. The Brain becomes a programmatic `[build]` consumer (parses every line, not only the latest). At that point latest-line manual JSON validity is no longer sufficient; gate must move to "every line parses cleanly" as a CI step.
9. **Phase 0-E specific:** a non-sentinel `[build]` line emits `genotype_kind == "unknown"` in normal play (currently hard-gated as count == 0; if the body-swap / non-creature path becomes reachable, the schema needs a v2 + clarification on hunger/thirst null semantics for those bodies).

## Feed-forward for the next phase
Phase 0-F (TBD per `docs/architecture-v5.md:2810+`). Open design questions surfaced during 0-E that may feed forward:
- Whether retrospective birth-profile capture (DeathLogger / cross-run learning per `docs/architecture-v5.md:1683-1687`) lands as a parallel `[birth]` line, a write-once memo file replayed on Brain reconnect, or via reuse of `[build]` cadence with a "captured_at_birth" snapshot.
- Whether `check_status` adapter responsibility documented in the spec hazard ("check_status adapter responsibility") materializes in Phase 1+ as a Python adapter class or as a Brain prompt-template responsibility.

## Open hazards (still tracked from earlier phases)
- Render-thread exception spam dedup: zero ERROR lines across 0-B / 0-C / 0-D / 0-E runs. Continue to defer.
- Multi-mod coexistence: untested across all phases. Revisit when a phase needs multi-mod observation.
- Stomach-less body / amphibious body run: out of v1 acceptance scope (spec hazard). Both runs in this phase had Stomach.

## Files modified / created in Phase 0-E
| Path | Change |
|---|---|
| `mod/LLMOfQud/SnapshotState.cs` | Added `BuildJson` field to `PendingSnapshot`; added `BuildBuildJson` + `AppendBuildIdentity` + `AppendBuildAttributes` + `AppendBuildResources` + `NormalizeStomachStatus` helpers. ~120 lines. |
| `mod/LLMOfQud/LLMOfQudSystem.cs` | Extended `HandleEvent` to build build JSON in a separate `try/catch` and populate `PendingSnapshot.BuildJson`. Extended `AfterRenderCallback` to emit a fourth LogInfo line `[LLMOfQud][build]` in its own try scope. |
| `docs/adr/0005-phase-0-e-current-build-state-pivot.md` | Created in PR-E1. |
| `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` | Created in PR-E1 (spec was committed earlier on the same branch). |
| `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` | Created in PR-E1. |
| `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` | This file. |

## References
- `docs/architecture-v5.md` (v5.9): `:1787-1790`, `:2802` (Phase 0-E line, reinterpreted by ADR 0005), `:443-468` (`check_status` consumer).
- `docs/adr/0005-phase-0-e-current-build-state-pivot.md` — pivot ADR.
- `docs/superpowers/specs/2026-04-25-phase-0-e-current-build-state-design.md` — design spec.
- `docs/superpowers/plans/2026-04-25-phase-0-e-current-build-state.md` — implementation plan.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate.
- `mod/LLMOfQud/SnapshotState.cs` — build JSON build helpers.
- `mod/LLMOfQud/LLMOfQudSystem.cs` — game-thread / render-thread split (4 lines/turn).
- CoQ APIs (verified 2026-04-25): see Phase 0-E plan "Reference" section.
```

- [ ] **Step 2: Commit the exit memo.**

```bash
git add docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md
git commit -m "docs(memo): Phase 0-E exit memo — current build state observation

N+M-turn manual acceptance on Mutant + True Kin: BEGIN == END ==
[state] == [caps] == [build] per run, ERROR=0, latest [build] passes
json.loads with all 9 v1 keys, every-line + shape-parity + invariants
gates green. Records the provisional every-turn cadence + revisit
triggers (inherited from 0-D + 1 new), feeds forward to Phase 0-F."
```

- [ ] **Step 3: Open PR-E2 (implementation).**

```bash
git push -u origin feat/phase-0-e-impl
gh pr create --title "feat(mod): Phase 0-E current build state observation" \
  --body "$(cat <<'EOF'
## Summary
- New `[LLMOfQud][build] {"turn":N,"schema":"current_build.v1",...}` line per player decision point, alongside 0-B `[screen]`, 0-C `[state]`, 0-D `[caps]`.
- Captures genotype_kind / genotype_id / subtype_id (identity), level + 6 lowercase attributes (Statistic.Value, clamped), hunger / thirst (Stomach.FoodStatus / WaterStatus normalized).
- Schema lock current_build.v1; ADR 0005 in main records the BirthBuildProfile → current build state pivot.
- Two-build acceptance: primary Mutant Joppa run (>=100 turns) + secondary True Kin smoke (10-20 turns). ERROR=0 on both.

## Test plan
- [x] Manual acceptance runs (Task 6).
- [x] Latest [build] line non-sentinel + 9 keys (criterion 5).
- [x] Every-line schema/key-set check on both runs (criterion 6).
- [x] Shape parity first vs last non-sentinel (criterion 7).
- [x] Semantic invariants: 6-key attribute set, integer values, genotype_kind enum + 0 unknowns, level >= 1, hunger/thirst non-null + closed enum (criterion 8).
- [x] Two-build smoke (criterion 9).

## Merge order
This PR opens against main after PR-E1 (docs-only ADR + plan + spec) merged. Codex spec PASS recorded at design spec commit 8861358 (4 review rounds).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

The PR will be reviewed via CodeRabbit (path_instructions enforce inline `decompiled/<path>.cs:<line>` citations on any CoQ API claim) + `/codex review` + `/cavendish` per session instructions. Address findings, push fixes, merge per `feedback_docs_pr_merge_policy.md` if applicable (this is NOT a docs-only PR; full convergence loop applies).

---

## Acceptance criteria (rollup, mirrors spec lines 92–113)

A Phase 0-E acceptance run is PASS iff all of the following hold:

1. **Compile clean.** `build_log.txt` shows `Compiling 3 file(s)... Success :)` for `LLMOfQud`. No `COMPILER ERRORS` for the mod. No `MODWARN CS0618`.
2. **Counts — primary run.** Mutant Joppa: `[screen] BEGIN == [screen] END == [state] == [caps] == [build] >= 100`.
3. **Counts — secondary smoke run.** True Kin: same equality, `>= 10`.
4. **Hard error gate.** `ERR_SCREEN == 0` on both runs. Soft gates `ERR_STATE / ERR_CAPS / ERR_BUILD == 0` recorded; non-zero values investigated and logged in the exit memo.
5. **Latest-line JSON validity.** Latest `[build]` line on each run passes `json.loads` AND is non-sentinel AND `schema == "current_build.v1"` AND has the 9 required keys.
6. **Every-line JSON validity + key-set.** All `[build]` lines parse cleanly; non-sentinel lines have exactly the 9-key set; sentinels tolerated and reported.
7. **Shape parity.** First non-sentinel vs last non-sentinel `[build]` line on the primary run have identical top-level keys.
8. **Semantic invariants.** Across both runs: exact 6 lowercase attribute keys with integer values; `genotype_kind ∈ {mutant, true_kin}` (count of unknown == 0); `level >= 1`; `genotype_id` / `subtype_id` non-null; `hunger != null` and `thirst != null` with closed-enum bucket membership.
9. **Two-build smoke.** Primary Mutant + secondary True Kin both pass criteria 2–8 within their thresholds; `genotype_kind` matches the build per run.
10. **Single-mod load order.** Acceptance runs performed with only `LLMOfQud` enabled.
11. **Spec-correction ADR landed.** ADR 0005 is on `main` before PR-E2 merges (Task 0 produced PR-E1 which landed it).
12. **Exit memo committed.** `docs/memo/phase-0-e-exit-<YYYY-MM-DD>.md` exists on the branch.

---

## Open hazards / future revisit

Provisional decisions in this plan that may need revisiting (inherited from 0-D plan + spec-specific additions):

- **Cadence (every-turn full dump).** Re-open at any of the 9 provisional-cadence triggers documented in the exit memo template above.
- **Stomach-less body / amphibious body.** The schema allows `hunger: string | null` and `thirst: string | null` but the v1 acceptance gate hard-asserts non-null on the two runs (both have Stomach). A Stomach-less acceptance run is out of scope for v1; if Phase 1+ needs robot/amphibious coverage, schema is forward-compatible and the gate is conditioned, not changed.
- **Hunger/thirst bucket stability.** Buckets are derived from `Stomach.FoodStatus()` / `Stomach.WaterStatus()` + `RuleSettings` thresholds. If a CoQ update adds a new bucket name, the v1 acceptance gate hard-fails — schema documentation update + acceptance re-run, not a silent extension.
- **Subtype display divergence.** v1 emits `subtype_id` only. If a future build path produces `subtype_id != display_name`, the v1 line silently emits the canonical id only. v2 + ADR if Brain prompts need the displayed string.
- **Level monotonicity.** Treated as monotonic non-decreasing in v1. If a path is found that decreases level, exit memo records the empirical case; semantic invariants are NOT updated to require monotonicity.
- **`Statistic.Value` clamp invisibility.** `Value` already applies CoQ's hard clamps (cybernetic limits, mutation bonuses). If a Phase 1+ Brain finds it needs unclamped raw `_Value`, schema v2 + ADR.
- **Multi-mod coexistence.** Untested across all five phases. Same posture as 0-B/0-C/0-D.
- **Save/load resilience re-open trigger.** If the first non-sentinel `[build]` line after `AfterGameLoadedEvent` shows values inconsistent with the pre-save state, that's an acceptance failure → re-evaluate cadence / capture point. Exit memo MUST state whether at least one save → load round-trip occurred during the primary run; if zero, exit memo records this as a coverage gap, not a passing trigger.
- **`check_status` adapter responsibility.** Phase 1+ Python adapter must synthesize `equipment_summary` from `[caps].equipment[]`, map `[caps].effects[].display_name_stripped` → `active_effects[].name`, etc. The 0-E `[build]` line directly supplies `level / attributes / hunger / thirst`. If the consumer prefers `"satiated"` over our normalized `"sated"`, harmonization happens in the adapter, not in the mod.
