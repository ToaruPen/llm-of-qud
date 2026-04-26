# Phase 0-G: Heuristic Bot — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Layer the smallest defensible decision policy on top of Phase 0-F's `CommandTakeActionEvent` direct-action path: each turn, pick `flee` (if `hurt && adjacent_hostile`), `attack` (if `adjacent_hostile`), or `explore` (otherwise). Emit one `[LLMOfQud][decision] {...}` JSON line per dispatch — a sixth per-turn observation primitive. Phase 0-G inherits Phase 0-F's CTA hook, direct `Move`/`AttackDirection` API, ADR 0007 `PreventAction` scope, and 3-layer drain posture; the new logic is purely additive within the existing handler structure.

**Architecture (per design spec `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`):**

- **Game thread (`HandleEvent(CommandTakeActionEvent E)`)**: extends Phase 0-F's `mod/LLMOfQud/LLMOfQudSystem.cs:181-378`. The handler now runs Decide → Execute. Decide reads HP, scans hostiles, classifies hurt, picks branch + direction, emits `[decision]`. Execute dispatches the chosen action, falls through 3-layer drain on failure, emits `[cmd]` (unchanged from Phase 0-F).
- **`PreventAction` scope unchanged from ADR 0007.** Success path leaves `PreventAction = false`; render fallback at `decompiled/XRL.Core/ActionManager.cs:1806-1808` flushes `[screen]/[state]/[caps]/[build]` per turn. `[decision]` and `[cmd]` emit on the game thread independently.
- **Per-turn output: 7 lines** = 2 (`[screen]` BEGIN/END) + 1 `[state]` + 1 `[caps]` + 1 `[build]` + 1 `[decision]` + 1 `[cmd]`. **Parser correlation contract: correlate by `turn` field, never adjacency or count parity.** Same rule extended from Phase 0-F.
- **Hook is `CommandTakeActionEvent`**, unchanged. Direct API (`Move`/`AttackDirection`/`PassTurn`), unchanged. ADR 0006 + ADR 0007 inherited verbatim.
- **Schema lock: `decision.v1`** — full record fields: `{turn, schema, branch, hp, max_hp, hurt, adjacent_hostile_dir, adjacent_hostile_id, chosen_dir, fallback, error}`. Sentinel reduced shape: `{turn, schema, error}`. `command_issuance.v1` is NOT touched (no v2 bump).

**Tech Stack:** Same as Phase 0-A through 0-F. CoQ Roslyn-compiles `mod/LLMOfQud/*.cs` at game launch (`decompiled/XRL/ModInfo.cs:478, 757-823`). Manual in-game verification against `Player.log` is the acceptance gate (ADR 0004 in force — no C# unit test framework).

- No new `using` directives in `mod/LLMOfQud/LLMOfQudSystem.cs` beyond the Phase 0-F set (`XRL.World.Capabilities` already imported for `AutoAct.ClearAutoMoveStop()`). No new `using` directives in `SnapshotState.cs`.
- Environment paths (verified 2026-04-26 from `docs/memo/phase-0-f-exit-2026-04-26.md:36-40`):
  - `$MODS_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods`
  - `$COQ_SAVE_DIR=$HOME/Library/Application Support/Freehold Games/CavesOfQud`
  - `$PLAYER_LOG=$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log`

**Testing approach (mirrors 0-F, ADR 0004 still in force):**

- Manual in-game verification on five fresh-chargen Warden runs (Mutated Human + Warden subtype + Roleplay mode + standard preset mutations). 3-of-5 must survive ≥50 `[cmd]` records per `docs/architecture-v5.md:2812`.
- Pre-impl empirical probes (Task 1) must all PASS before opening PR-G2.
- Acceptance counts: 7-channel parity `[screen] BEGIN == [screen] END == [state] == [caps] == [build] == [decision] == [cmd] >= 50` per surviving run.
- `ERR_SCREEN == 0` is the hard gate; `ERR_STATE / ERR_CAPS / ERR_BUILD / ERR_DECISION / ERR_CMD == 0` are soft gates.
- Spot-check semantic invariants per spec criterion 9 (branch/hurt/fallback enums + branch↔action consistency).
- Manual 99% observation accuracy audit on 20 random turns (Task 6).
- **No C# unit tests** — deferred to Phase 2a per ADR 0004.

**Reference:**

- `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md` — design spec (locked at the commit PR-G1 squash-merges; spec amendments forced by Task 1 probe results land via a follow-up docs-only **PR-G1.5** PR cut from `main`, NOT via push to the deleted readiness branch).
- `docs/architecture-v5.md` (v5.9, frozen): `:2804` (Phase 0-G line being implemented), `:2811-2817` (Phase 0 exit criteria), `:2825-2834` (Phase 0b boundary preserved by ADR 0008), `:2836-2855` (Phase 1 WebSocket bridge consumer), `:1787-1790` (game-queue routing rule).
- `docs/adr/0001-architecture-v5-9-freeze.md` — freeze rule that requires ADR 0008.
- `docs/adr/0004-phase-0-c-csharp-test-infra-deferral.md` — manual JSON-validity gate inherited.
- `docs/adr/0006-phase-0-f-command-issuance-api-pivot.md` — direct-API path inherited; `command_issuance.v1` lock cited.
- `docs/adr/0007-phase-0-f-prevent-action-scoped-to-abnormal-energy.md` — `PreventAction` scope inherited verbatim.
- `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` — narrow ADR landing in Task 0.
- `docs/memo/phase-0-f-exit-2026-04-26.md` — Phase 0-F exit memo whose §"Feed-forward for Phase 0-G / Phase 1" seeded this design.
- `docs/superpowers/plans/2026-04-26-phase-0-f-command-issuance.md` — precedent plan structure modeled here.
- CoQ APIs (verified 2026-04-26):
  - **Decision-time read**: `GameObject.hitpoints` / `baseHitpoints` (`decompiled/XRL.World/GameObject.cs:1177-1198`), `Statistic.Value` / `BaseValue` (`decompiled/XRL.World/Statistic.cs:218-252`).
  - **Hostile scan** (unchanged): `Cell.GetCellFromDirection` (`decompiled/XRL.World/Cell.cs:7322-7324`), `Cell.GetCombatTarget` (`decompiled/XRL.World/Cell.cs:8511-8558`), `GameObject.IsHostileTowards` (`decompiled/XRL.World/GameObject.cs:10887-10894`).
  - **Safe-cell predicate**: `Cell.IsEmptyOfSolidFor` (`decompiled/XRL.World/Cell.cs:5290-5305`), `Cell.GetDangerousOpenLiquidVolume` (`decompiled/XRL.World/Cell.cs:8597-8607`).
  - **Action API** (unchanged): `GameObject.Move` (`decompiled/XRL.World/GameObject.cs:15274-15290, 15719-15722`), `GameObject.AttackDirection` (`decompiled/XRL.World/GameObject.cs:17882-17902`), `AutoAct.ClearAutoMoveStop` (`decompiled/XRL.World.Capabilities/AutoAct.cs:386-389`), `GameObject.PassTurn` (`decompiled/XRL.World/GameObject.cs:17543-17545`).
  - **CTA hook** (unchanged): `CommandTakeActionEvent` (`decompiled/XRL.World/CommandTakeActionEvent.cs:1-42`).
  - **MetricsManager.LogInfo** (unchanged): `decompiled/MetricsManager.cs:407-409`.

---

## Prerequisites (one-time per session)

Before starting any task, confirm:

1. Phase 0-F is landed on `main` (commit `9ab3036 feat(mod): Phase 0-F command issuance — Step A + Step B + ADR 0007 (#14)` or a successor). Verify `mod/LLMOfQud/LLMOfQudSystem.cs` has the `HandleEvent(CommandTakeActionEvent)` body and `mod/LLMOfQud/SnapshotState.cs` has `BuildCmdJson` + `BuildCmdSentinelJson` + `AppendJsonStringOrNull` + `AppendJsonIntOrNull`.
2. The symlink `$MODS_DIR/LLMOfQud` resolves to the repo's `mod/LLMOfQud/`. Verify with `readlink "$MODS_DIR/LLMOfQud"`. If dangling, re-create per Phase 0-A Task 1.
3. Env vars for the session:
   ```bash
   export MODS_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud/Mods"
   export COQ_SAVE_DIR="$HOME/Library/Application Support/Freehold Games/CavesOfQud"
   export PLAYER_LOG="$HOME/Library/Logs/Freehold Games/CavesOfQud/Player.log"
   ```
4. **Disable any coexisting user mod for the acceptance runs.** Phase 0-F's 505-record run was performed with `LLMOfQud` only. Re-verify the in-game Mods list reflects single-mod load before Tasks 1, 5, 6.
5. **Five clean save slots** are not strictly required (acceptance runs are sequential fresh chargens within a single CoQ launch where possible), but having them ready avoids slot-collision delays.

---

## File Structure

ADR + plan + spec land in a docs-only PR (Task 0). Empirical probes (Task 1) run on a sacrificial CoQ session with a stub MOD; probes do NOT modify the canonical `mod/LLMOfQud/` files. Implementation tasks (Tasks 2-4) modify the two existing C# files. Tasks 5-6 are manual in-game work with no code edits. Task 7 finalizes the exit memo.

**Docs-only PR (PR-G1, on branch `feat/phase-0-g-design`):**

- Add: `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md` — design spec (already on the branch when this plan starts; verify in Task 0 Step 1).
- Add: `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md` — this plan.
- Create: `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md` — ADR documenting the `:2817` interrupt-semantics interpretation, the new `[decision]` channel decision, and the heuristic-specifics lock.
- Append to: `docs/adr/decision-log.md` — index entry for ADR 0008.
- Create: `docs/adr/decisions/2026-04-26-phase-0-g-heuristic-interrupt-semantics-new-decision-channel-heuristic-specifics-lock.md` — machine-readable decision record produced by `scripts/create_adr_decision.py`.

**Empirical-probe stub (Task 1, NOT committed to main):**

- `mod/LLMOfQud/LLMOfQudSystem.cs` is temporarily patched with stub-heuristic code on a throwaway local branch `wip/phase-0-g-probe-1`. Probe results are captured in `/tmp/phase-0-g-probes/` (operator-local, not committed). After all probes pass, the throwaway branch is discarded; the implementation PR (PR-G2) opens fresh from `main`.

**Implementation PR (PR-G2, on branch `feat/phase-0-g-impl` cut from `main` after PR-G1 merges and probes pass):**

- Modify: `mod/LLMOfQud/SnapshotState.cs`
  - Add: `internal struct DecisionRecord` mirroring `CmdRecord` shape with `decision.v1` fields.
  - Add: `BuildDecisionJson(DecisionRecord r)` static — emits the 11-key `decision.v1` record.
  - Add: `BuildDecisionSentinelJson(int turn, Exception ex)` static — emits the reduced `{turn, schema, error}` record.
- Modify: `mod/LLMOfQud/LLMOfQudSystem.cs`
  - Add private static helpers: `IsSafeCell(Cell, GameObject)`, `ChooseFleeDir(Cell, GameObject hostileObj, GameObject player, out string fallback)`, `ChooseExploreDir(Cell, GameObject)`. The hostile-scan logic in the existing `HandleEvent(CommandTakeActionEvent)` is extracted into a private static helper `ScanAdjacentHostile(Cell, GameObject, out string dir, out GameObject obj)` for reuse.
  - Refactor `HandleEvent(CommandTakeActionEvent E)` body to the decision-then-execute flow per the spec's pseudocode. The 3-layer drain `try/catch/finally` outer structure is preserved verbatim; the new logic inserts BEFORE the existing action-dispatch.

External (created during execution):

- `docs/memo/phase-0-g-exit-<YYYY-MM-DD>.md` — exit memo, mirrors `docs/memo/phase-0-f-exit-2026-04-26.md`'s shape.

No manifest edits. No symlink changes. No new dependencies. The Roslyn compile set stays at 3 files (`LLMOfQudSystem.cs`, `SnapshotState.cs`, `LLMOfQudBootstrap.cs` — unchanged for this phase).

---

## Task 0: ADR 0008 + plan + spec landing (docs-only PR-G1, Phase 0-C / 0-E / 0-F precedent)

**Why this task exists:** ADR 0008 records the `docs/architecture-v5.md:2817` interpretation, the new `[decision]` channel decision, and the heuristic-specifics lock. Per ADR 0008's own Decision #4, the prerequisite docs-only PR pattern keeps the design under review independently of the C# diff and is the Phase 0-C / 0-E / 0-F precedent.

**Files:**

- Create: `docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md`
- Modify: `docs/adr/decision-log.md` (append index entry)
- Create: `docs/adr/decisions/2026-04-26-phase-0-g-heuristic-interrupt-semantics-new-decision-channel-heuristic-specifics-lock.md`
- Add: `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md` (this plan, when staged for the docs PR)
- Add: `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md` (already on the branch at Task 0 start)

**Branch:** `feat/phase-0-g-design`. The spec is committed first; ADR + plan land on the same branch and the branch opens as PR-G1.

- [ ] **Step 1: Verify the branch state.**

```bash
git branch --show-current
git log --oneline feat/phase-0-g-design -10
```

Expected: current branch is `feat/phase-0-g-design`; `git log` shows the spec commit on top of `9ab3036` (Phase 0-F merge to main) or its successor. If the branch does not exist, create it from `main`: `git switch -c feat/phase-0-g-design main`.

- [ ] **Step 2: Verify ADR 0008 file content.**

The ADR is already written in this readiness PR draft. Verify it's on disk:

```bash
ls docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
wc -l docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
```

Expected: file exists, ~180 lines. If absent, the spec author re-creates it from the inline draft in this PR description.

- [ ] **Step 3: Append ADR 0008 entry to `docs/adr/decision-log.md`.**

Open `docs/adr/decision-log.md`. Add a new row to the table (after the ADR 0007 row), maintaining the existing format:

```markdown
| 0008 | 2026-04-26 | Accepted | Phase 0-G heuristic interrupt semantics + new [decision] channel + heuristic specifics lock |
```

The exact column shape MUST match the prior rows in the file. If the file uses a different format (e.g., bullet list, append-only paragraphs), follow whatever the most recent entry looks like.

- [ ] **Step 4: Generate the machine-readable decision record.**

```bash
python3 scripts/create_adr_decision.py \
  --required true \
  --change "Phase 0-G heuristic interrupt semantics + new [decision] channel + heuristic specifics lock" \
  --rationale "Architecture-v5.md :2817 interrupt criterion is satisfied by heuristic same-turn branch interruption (NOT engine-level AutoAct.Interrupt, which remains Phase 0b). New [decision] channel keeps command_issuance.v1 untouched. Branch order, hurt threshold composite formula, flee tiebreak, and explore east-bias are locked." \
  --adr docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
```

Expected: a new file at `docs/adr/decisions/2026-04-26-phase-0-g-heuristic-interrupt-semantics-new-decision-channel-heuristic-specifics-lock.md` (date stamp + title slug). If the script produces a different filename pattern, accept it — the script's output is the authoritative path.

If the script fails with "decision already exists for this ADR", inspect `docs/adr/decisions/` for an existing `phase-0-g` record. If one is there from a prior attempt and is correct, reuse it; otherwise rename/remove it and re-run.

- [ ] **Step 5: Commit the ADR + decision record + plan + decision-log update.**

```bash
git add docs/adr/0008-phase-0-g-heuristic-interrupt-semantics.md
git add docs/adr/decision-log.md
git add docs/adr/decisions/2026-04-26-phase-0-g-heuristic-interrupt-semantics-new-decision-channel-heuristic-specifics-lock.md
git add docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md
git status   # verify only the four files above are staged
git commit -m "docs(adr): ADR 0008 — Phase 0-G heuristic interrupt semantics + [decision] channel"
```

If the pre-commit hook fails on `scripts/check_adr_decision.py`, ensure the decision record from Step 4 covers all docs-PR triggered files (only `docs/adr/`, `docs/superpowers/`, no `scripts/`/`harness/`/`pyproject.toml` changes), and re-stage / re-commit.

- [ ] **Step 6: Run the local pre-push gate.**

```bash
pre-commit run --all-files
uv run pytest tests/
```

Expected: all hooks pass. If `markdownlint-cli2` MD033 trips on the ADR (literal `<line>` / `<path>` placeholders inside text), use uppercase `LINE`/`PATH` placeholders or wrap them in backticks per the Phase 0-F PR convergence playbook lesson.

- [ ] **Step 7: Push and open PR-G1.**

```bash
git push -u origin feat/phase-0-g-design
gh pr create --base main --title "docs: Phase 0-G readiness — ADR 0008, plan, design spec" --body "$(cat <<'EOF'
## Summary
- ADR 0008 documents Phase 0-G's interrupt-semantics interpretation of `docs/architecture-v5.md:2817`, locks the heuristic specifics (branch order + hurt threshold + flee/explore tiebreak), and adds the new `[decision]` channel as the schema treatment.
- Design spec at `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md` defines `decision.v1`, the safe-cell predicate, and 13 acceptance criteria including the 5-run Warden survival gate, the 99% observation accuracy audit, and the same-turn interrupt verification.
- Implementation plan at `docs/superpowers/plans/2026-04-26-phase-0-g-heuristic-bot.md` lays out 8 tasks: ADR landing (this PR), 5 empirical probes (must pass before PR-G2 opens), `SnapshotState` JSON builders, helper extraction in `LLMOfQudSystem`, `HandleEvent(CTA)` decision-then-execute refactor, 5-run acceptance, observation audit, exit memo.

This PR is docs-only. The implementation PR (PR-G2) opens against `main` after this merges AND after Task 1 probes pass.

## Test plan
- [ ] CI green (pre-commit + pytest + governance + markdownlint)
- [ ] CodeRabbit review addressed
- [ ] ADR re-opens v5.9 freeze ONLY for the `:2817` interpretation (Decision #1) and adds a new channel (Decision #2); no architecture-v5.md text changed in this PR
EOF
)"
```

Capture the PR URL in the task output.

- [ ] **Step 8: Address CodeRabbit findings + merge.**

Watch for CodeRabbit review (typically within 5-10 minutes). Address each thread: docs-only changes per Phase 0-F precedent (`feedback_docs_pr_merge_policy.md`). Once findings are addressed AND CI green, merge using `gh pr merge --squash --admin` per the docs-PR fast-merge policy.

After merge, switch to `main` and pull:

```bash
git switch main
git pull origin main
git log --oneline -5   # confirm PR-G1 squash-merge commit at HEAD
```

---

## Task 1: Empirical probes (5 sub-probes, gate before PR-G2)

**Why this task exists:** Per `feedback_empirical_claim_probe_before_lock.md` and the spec's "Empirical probes required" section, the 5 load-bearing claims this design makes MUST be verified on a sacrificial CoQ session BEFORE the implementation PR opens. Phase 0-F's ADR 0007 was authored mid-implementation because such probes were skipped; we will not repeat that.

**Branch:** `wip/phase-0-g-probe-1` cut from `main` (post-PR-G1 merge). The branch is throwaway; commits stay local. After all 5 probes pass, the branch is discarded and PR-G2 opens fresh from `main`.

**Files:** Stub edits to `mod/LLMOfQud/LLMOfQudSystem.cs` for each probe. Probe captures live in `/tmp/phase-0-g-probes/<probe-N>/` (operator-local, not committed).

- [ ] **Step 1: Set up the probe scratch directory.**

```bash
mkdir -p /tmp/phase-0-g-probes/{probe-1,probe-2,probe-3,probe-4,probe-5}
git switch -c wip/phase-0-g-probe-1 main
```

### PROBE 1 — Joppa east-bias 50-turn survival (BASELINE ONLY)

**Hypothesis (descriptive, not gating):** Characterize how far Phase 0-F's existing east-Move + adjacent-Attack handler — run unchanged on `main` HEAD — gets on a fresh Warden chargen on Joppa.

**Framing:** PROBE 1 is a **baseline-characterization probe**, NOT a pass/fail entry gate for Tasks 2-4. The result informs how aggressive the heuristic must be, but Phase 0-G implementation proceeds regardless of the survived-turn count. PROBE 1 does NOT block PR-G2.
- If main HEAD survives 50 turns: documented; the heuristic adds resilience for outlier conditions only.
- If main HEAD dies before 50 turns: documented as the floor the heuristic must beat in Task 5 acceptance.
- The only PROBE 1 outcome that pauses the phase is "fundamentally impossible without resource management" — escalate to user; scope may need adjustment.

PROBE 2-4 retain pass/fail semantics because they validate spec-locked parameters (hurt threshold, safe-cell predicate, same-turn interrupt) that DO gate Tasks 2-4. PROBE 1 only validates a baseline observation.

- [ ] **Step 2: Run PROBE 1 (no code changes — test the existing main HEAD).**

The probe uses the unmodified `mod/LLMOfQud/` from `main`. No stub needed. Operator workflow:

1. Launch CoQ. Confirm `[LLMOfQud] loaded` appears in `build_log.txt`.
2. Start a new game: Mutated Human + Warden + Roleplay mode + standard preset mutations. Skip the tutorial.
3. Once in Joppa starting zone (`JoppaWorld.11.22.1.1.10@37,22` per `Base/EmbarkModules.xml:275-277`), let the existing handler run autonomously.
4. Run for up to 50 `[cmd]` records (or until the player dies). The autonomous east-walk should traverse Joppa's east lane.
5. Halt the game (Ctrl+C or in-game quit) once turn 50 is reached or the player dies.

Capture:

```bash
cp "$PLAYER_LOG" /tmp/phase-0-g-probes/probe-1/raw-player.log
grep "INFO - \[LLMOfQud\]\[cmd\]" /tmp/phase-0-g-probes/probe-1/raw-player.log > /tmp/phase-0-g-probes/probe-1/cmd-records.log
wc -l /tmp/phase-0-g-probes/probe-1/cmd-records.log
tail -5 /tmp/phase-0-g-probes/probe-1/cmd-records.log
```

Record (NOT pass/fail; baseline data):
- `N_cmd` (number of `[cmd]` lines reached)
- `last_hp` from the final `[state]` line (alive vs dead)
- If dead: which turn, identified killing entity from `[cmd].target_*` and the same-turn `[state]` line
- Whether the cause looks like "outlier we can fix with the heuristic" vs "scope hazard"

Only ONE outcome blocks: "fundamentally impossible without resource management (food/water/etc.)" → escalate to user before proceeding. Otherwise document and continue to PROBE 2.

Document the outcome in `/tmp/phase-0-g-probes/probe-1/result.md` (label: `BASELINE` — not PASS/FAIL).

### PROBE 2 — Hurt threshold sweet spot

**Hypothesis:** The composite formula `hp <= max(8, floor(max_hp * 0.60)) AND adjacent_hostile_dir != null` correctly classifies the player as `hurt` at survivable HP bands and the heuristic's `flee` branch reaches a safe cell within 3 turns.

**Why it matters:** The threshold ratio `0.60` is the codex-recommended starting point but may be too eager (flee triggers when attack would be safer) or too slow (flee triggers after lethal damage was inevitable). PROBE 2 tunes the ratio if needed.

- [ ] **Step 3: Add a temporary diagnostic stub to `LLMOfQudSystem.cs`.**

Stage a temporary probe-only patch on `wip/phase-0-g-probe-1`. Inside `HandleEvent(CommandTakeActionEvent)`, ABOVE the existing scan code, add:

```csharp
// PROBE 2 ONLY — DELETE AFTER ACCEPTANCE.
// Emit a [LLMOfQud][probe2] line per turn with hp / max_hp / hurt-classification
// at multiple ratio thresholds for comparison.
try
{
    int probeHp = player.hitpoints;
    int probeMax = player.baseHitpoints;
    bool hurt50 = probeHp <= System.Math.Max(8, (int)System.Math.Floor(probeMax * 0.50));
    bool hurt60 = probeHp <= System.Math.Max(8, (int)System.Math.Floor(probeMax * 0.60));
    bool hurt70 = probeHp <= System.Math.Max(8, (int)System.Math.Floor(probeMax * 0.70));
    MetricsManager.LogInfo(
        "[LLMOfQud][probe2] turn=" + turn +
        " hp=" + probeHp + " max=" + probeMax +
        " hurt50=" + hurt50 + " hurt60=" + hurt60 + " hurt70=" + hurt70);
}
catch { /* swallow — probe must never affect main path */ }
```

Compile via `git commit && in-game launch`. Confirm the probe line emits without breaking the main `[cmd]` flow.

- [ ] **Step 4: Run PROBE 2.**

Operator workflow (one CoQ launch, multiple HP scenarios via `wish`):
1. Fresh Warden, full HP. Note `max_hp` from the first `[probe2]` line (Warden baseline ~28-32 depending on Toughness roll).
2. Use the in-game wish console (`Ctrl+W`) to set HP. Available wishes: `wish damage:N` (deal N damage), `wish heal` (full restore). Verify the in-game HP matches the next `[probe2]` line's `hp` field.
3. Bring HP through bands: 90% → 70% → 60% → 50% → 40% → 30% of `max_hp`. At each band:
   - Spawn an adjacent hostile via `wish testhero:Snapjaw scavenger`.
   - Observe the next `[probe2]` line's `hurt50`/`hurt60`/`hurt70` values.
   - Note whether the player survives the next 3 turns (i.e., does flee-with-each-threshold succeed).
4. Halt and capture:

```bash
cp "$PLAYER_LOG" /tmp/phase-0-g-probes/probe-2/raw-player.log
grep "INFO - \[LLMOfQud\]\[probe2\]" /tmp/phase-0-g-probes/probe-2/raw-player.log > /tmp/phase-0-g-probes/probe-2/probe2-lines.log
```

PASS if:
- `60%` triggers `hurt = true` at survivable HP for at least 5 distinct damage scenarios.
- The implied flee branch (operator simulates by walking the player W/SW/NW manually) reaches a safe cell within 3 turns in 4-of-5 scenarios.
- `50%` is too slow (player dies before flee triggers in ≥2 scenarios).
- `70%` is too eager (flee triggers when the player could have safely killed the hostile in ≥3 scenarios).

If 60% fails the survivability test:
- Pick the next-best band per the `[probe2]` data and open a follow-up docs-only **PR-G1.5 spec-amendment** PR (NOT a re-open of PR-G1; PR-G1's `feat/phase-0-g-design` branch is squash-merged + deleted by this point).
  - Branch name convention: `docs/phase-0-g-spec-amendment-probe<N>` cut from `main`.
  - PR-G1.5 modifies: the `0.60` constant in spec section "Field semantics" → `hurt`, ADR 0008 Decision #3 (with a new Decision #7 documenting the empirical override), and the decision-log entry. NO C# changes (those happen in PR-G2 against the amended spec).
  - PR-G1.5 must merge BEFORE PR-G2 opens. Tasks 2-4 implement against the post-amendment spec.
- This same pattern (PR-G1.5 docs-amendment PR cut from `main`) applies to any PROBE 3 / PROBE 4 spec-amendment trigger; do NOT attempt to push to the deleted `feat/phase-0-g-design` branch.

Document the outcome in `/tmp/phase-0-g-probes/probe-2/result.md`. Note the chosen ratio (default `0.60` if probe confirms; alternative if probe forces amendment).

- [ ] **Step 5: Revert the PROBE 2 stub.**

```bash
git diff HEAD~1 -- mod/LLMOfQud/LLMOfQudSystem.cs    # confirm the stub diff
git revert HEAD --no-edit                              # OR git checkout main -- mod/LLMOfQud/LLMOfQudSystem.cs
```

The probe-only `[probe2]` LogInfo MUST NOT survive into PR-G2. Verify via `git diff main -- mod/LLMOfQud/LLMOfQudSystem.cs` showing zero changes after the revert.

### PROBE 3 — Flee safe-cell predicate

**Hypothesis:** The `IsSafeCell` predicate (`Cell.GetCellFromDirection != null && IsEmptyOfSolidFor && GetCombatTarget(hostile filter) == null && GetDangerousOpenLiquidVolume == null`) correctly identifies safe vs unsafe cells in 8 controlled scenarios.

- [ ] **Step 6: Add PROBE 3 stub.**

Add a temporary `[probe3]` LogInfo line that emits, for each of the 8 directions adjacent to the player, the four `IsSafeCell` sub-conditions. Stub:

```csharp
// PROBE 3 ONLY — DELETE AFTER ACCEPTANCE.
try
{
    Cell here = player.CurrentCell;
    if (here != null)
    {
        StringBuilder pb = new StringBuilder();
        pb.Append("[LLMOfQud][probe3] turn=").Append(turn);
        string[] dirs = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
        foreach (string d in dirs)
        {
            Cell adj = here.GetCellFromDirection(d, BuiltOnly: false);
            bool exists = adj != null;
            bool empty = exists && adj.IsEmptyOfSolidFor(player, IncludeCombatObjects: true);
            bool noHostile = exists && adj.GetCombatTarget(
                Attacker: player, IgnorePhase: false, Phase: 5,
                AllowInanimate: false,
                Filter: o => o != player && o.IsHostileTowards(player)) == null;
            bool noLiquid = exists && adj.GetDangerousOpenLiquidVolume() == null;
            pb.Append(" ").Append(d).Append("=")
              .Append(exists ? "1" : "0")
              .Append(empty ? "1" : "0")
              .Append(noHostile ? "1" : "0")
              .Append(noLiquid ? "1" : "0");
        }
        MetricsManager.LogInfo(pb.ToString());
    }
}
catch { /* swallow */ }
```

Each direction's emit is a 4-character flag string `<exists><empty><noHostile><noLiquid>`. `1111` = safe; `0XXX` / `X0XX` / `XX0X` / `XXX0` = unsafe (with which sub-condition failed encoded).

- [ ] **Step 7: Run PROBE 3.**

Operator workflow (three sub-cases):

**3a. Open-cell sub-test (per-direction verification).**
1. Fresh Warden, walk to an open cell with no walls in any of 8 adjacent directions. Record the cell coordinates.
2. Use `wish testhero:Snapjaw scavenger` repeatedly to spawn hostiles in each of the 8 adjacent cells, one direction at a time. After each spawn, take one turn (so `[probe3]` emits) and verify the corresponding `noHostile` flag flips to `0`.
3. Tally that all 8 directions correctly individually flip `noHostile=0` when a hostile is in that cell.

**3b. Wall-adjacent sub-test (`empty` predicate).**
1. Walk to a cell adjacent to a 1-tile wall segment (a building corner in Joppa works). Take one turn. Verify the `[probe3]` line shows `empty=0` for the direction(s) blocked by the wall.

**3c. Boxed-in sub-test (the spec's flee → boxed_in_attack escalation).** Per spec line 148, "boxed in" means NO safe cell exists in any of the 8 directions. The 7-of-8-hostiles framing leaves one safe cell and CANNOT exercise this branch. Use the wall-corner approach instead:

- Move the player into a 2-wall inside corner (e.g., the inside corner of a building — 3 of 8 cells are walls, 5 are open).
- Spawn hostiles via `wish testhero:Snapjaw scavenger` into the 5 open cells (one per turn; the wish-spawn places adjacent to the player). After all 5 spawns, the `[probe3]` line should show `1111` for ZERO directions (every direction is either wall or hostile).
- Verify: the "all-zero-safe" case correctly produces `1111` count = 0 across the 8 emitted direction codes. This is the runtime condition that the implementation's `ChooseFleeDir` branch detects to trigger `fallback="boxed_in_attack"`.

**3d. Liquid sub-test (optional).** If a liquid pool is reachable in Joppa starting zone, verify `noLiquid=0` for one cell over a dangerous liquid. Joppa surface has limited dangerous open liquids; skip if none reachable.

**Capture (after all sub-tests):**

```bash
cp "$PLAYER_LOG" /tmp/phase-0-g-probes/probe-3/raw-player.log
grep "INFO - \[LLMOfQud\]\[probe3\]" /tmp/phase-0-g-probes/probe-3/raw-player.log > /tmp/phase-0-g-probes/probe-3/probe3-lines.log
```

PASS if all four:
- 3a: All 8 directions correctly flip `noHostile=0` when a hostile is spawned in that cell.
- 3b: Wall-adjacent cells correctly show `empty=0`.
- 3c: The wall-corner-plus-spawn boxed-in scenario produces zero `1111` direction codes (no safe cell exists).
- 3d (if reachable): `noLiquid=0` for the cell over a dangerous liquid.

Document the outcome in `/tmp/phase-0-g-probes/probe-3/result.md`.

- [ ] **Step 8: Revert PROBE 3 stub.**

Same as PROBE 2 Step 5.

### PROBE 4 — Same-turn hostile interrupt

**Hypothesis:** When a hostile is spawned adjacent to the player on a turn where the player was previously not in combat, the next `CommandTakeActionEvent` dispatch sees the new hostile and the heuristic branches to `attack` (not `explore`).

- [ ] **Step 9: Add PROBE 4 stub.**

Replace the entire HandleEvent(CommandTakeActionEvent) Step B detection logic with a `[probe4]` emission that records what the scan sees but takes the EXISTING Phase 0-F action:

```csharp
// PROBE 4 ONLY — DELETE AFTER ACCEPTANCE.
// (Insert RIGHT AFTER the existing scan loop that sets targetDir/targetObj.)
try
{
    string what = (targetObj == null) ? "explore" : "attack";
    MetricsManager.LogInfo(
        "[LLMOfQud][probe4] turn=" + turn +
        " adjacent_hostile_dir=" + (targetDir ?? "null") +
        " heuristic_branch=" + what);
}
catch { /* swallow */ }
```

This stub does NOT change the existing action — it only records what the heuristic WOULD have chosen. The existing action proceeds (Move East or AttackDirection per Phase 0-F).

- [ ] **Step 10: Run PROBE 4.**

Operator workflow:
1. Fresh Warden in Joppa starting zone. Walk a few turns east in `explore` (no hostiles in adjacent cells). Note the `[probe4]` lines all show `heuristic_branch=explore`.
2. On a chosen turn N, use `wish testhero:Snapjaw scavenger` to spawn an adjacent hostile (the wish places the spawned actor next to the player).
3. Observe the `[probe4]` line for the immediate next turn. PASS if `adjacent_hostile_dir != null` AND `heuristic_branch == "attack"`.
4. Capture:

```bash
cp "$PLAYER_LOG" /tmp/phase-0-g-probes/probe-4/raw-player.log
grep "INFO - \[LLMOfQud\]\[probe4\]" /tmp/phase-0-g-probes/probe-4/raw-player.log > /tmp/phase-0-g-probes/probe-4/probe4-lines.log
```

PASS if:
- The first `[probe4]` line AFTER the wish-spawn shows `heuristic_branch == "attack"` (`attack` because PROBE 4 doesn't yet evaluate `hurt`; full HP guarantees `hurt == false`).
- ADR 0008 Decision #1's interpretation of `:2817` is empirically defensible.

Document the outcome in `/tmp/phase-0-g-probes/probe-4/result.md`.

- [ ] **Step 11: Revert PROBE 4 stub.**

Same as PROBE 2 Step 5.

### PROBE 5 — Channel correlation under branch mix

**Hypothesis:** During an actual heuristic-driven run with a mix of branches, every `[cmd]` line has a matching `[decision]` line by `turn` field, and the `branch ↔ action` invariant in spec criterion 10 holds.

PROBE 5 is the **integration probe** that runs against the FULL implementation (post-Tasks 2-4). It is captured here for symmetry with the spec but executes during Task 5 (acceptance run). The probe-1-through-probe-4 set is what's required pre-implementation.

- [ ] **Step 12: PROBE 5 deferred to Task 5.**

Verify by reading Task 5 Step 5: it includes the channel-correlation check that satisfies PROBE 5.

### Probe-set wrap-up

- [ ] **Step 13: Verify PROBE 1 BASELINE recorded + PROBE 2-4 PASS.**

```bash
ls /tmp/phase-0-g-probes/*/result.md
for p in /tmp/phase-0-g-probes/probe-{1,2,3,4}/result.md; do
  echo "=== $p ==="
  cat "$p"
done
```

Expected: 4 result.md files. PROBE 1's result is labeled `BASELINE` (informational only). PROBE 2-4 each marked PASS or FAIL. If any of PROBE 2-4 are FAIL with a spec-impacting finding, open a docs-only **PR-G1.5 spec-amendment** PR (branch `docs/phase-0-g-spec-amendment-probe<N>` from `main`) and merge it BEFORE proceeding to Task 2 — do NOT push to the deleted `feat/phase-0-g-design` branch.

- [ ] **Step 14: Discard the throwaway probe branch.**

```bash
git switch main
git branch -D wip/phase-0-g-probe-1
git status   # verify clean tree
```

Confirm `mod/LLMOfQud/LLMOfQudSystem.cs` is identical to `main` (no probe stubs leaked).

- [ ] **Step 15: Commit a probe-results memo (optional, recommended).**

If probe insights are operationally valuable beyond the immediate Phase 0-G work, capture them in a non-PR memo:

```bash
mkdir -p docs/memo
# Optional: docs/memo/phase-0-g-probe-results-<DATE>.md with summary table + links to /tmp/.../result.md (operator-local).
```

This step is optional; if the probes' results are unsurprising, skip and proceed to Task 2.

---

## Task 2: SnapshotState additions — DecisionRecord + builders

**Why this task exists:** The `decision.v1` JSON schema needs a typed builder mirroring Phase 0-F's `BuildCmdJson` pattern. Co-locating the new builder with the existing pure-data JSON helpers in `SnapshotState.cs` (rather than scattering builders across `LLMOfQudSystem.cs`) preserves the Phase 0-D/0-E/0-F separation between game-state-reading code (in `LLMOfQudSystem`) and pure-string-building code (in `SnapshotState`).

**Files:** Modify `mod/LLMOfQud/SnapshotState.cs` only.

**Branch:** `feat/phase-0-g-impl` cut from `main` after PR-G1 merges.

- [ ] **Step 1: Cut the implementation branch.**

```bash
git switch main
git pull origin main
git switch -c feat/phase-0-g-impl main
```

- [ ] **Step 2: Read the existing `CmdRecord` and `BuildCmdJson` to model the new struct on.**

```bash
grep -n "internal struct CmdRecord\|internal static string BuildCmdJson\|internal static string BuildCmdSentinelJson" mod/LLMOfQud/SnapshotState.cs
```

Open `mod/LLMOfQud/SnapshotState.cs` around the printed line numbers. Read the full `CmdRecord` struct and `BuildCmdJson` / `BuildCmdSentinelJson` methods. Note the ordering convention: struct field order is a hint, but `BuildCmdJson` dictates canonical JSON field order.

- [ ] **Step 3: Add `DecisionRecord` struct AFTER `CmdRecord` in `SnapshotState.cs`.**

Locate the closing `}` of `CmdRecord` and insert the new struct immediately after it. The struct fields cover the 11 `decision.v1` schema keys.

```csharp
// decision.v1 record. BuildDecisionJson serializes it. Field order in this struct is a hint
// to emission order but BuildDecisionJson dictates the canonical JSON field order — schema
// changes (field add/remove/rename, order) require a v2 bump + ADR per ADR 0008 + the
// command_issuance.v1 lock rule generalized to all observation channels.
internal struct DecisionRecord
{
    public int Turn;
    public string Branch;             // "flee" | "attack" | "explore"
    public int Hp;
    public int MaxHp;
    public bool Hurt;
    public string AdjacentHostileDir; // "N" | ... | "NW" | null
    public string AdjacentHostileId;  // GameObject.ID or null
    public string ChosenDir;          // direction the resulting action will use; null only when explore-no-safe
    public string Fallback;           // null | "boxed_in_attack" | "no_safe_cell_pass"
}
```

- [ ] **Step 4: Add `BuildDecisionJson` static method AFTER `BuildCmdJson`.**

Locate `BuildCmdJson` and insert `BuildDecisionJson` after its closing brace.

```csharp
// Builds the decision.v1 full record. Schema is locked at ADR 0008 + design spec
// docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md.
// Field order: turn, schema, branch, hp, max_hp, hurt, adjacent_hostile_dir,
// adjacent_hostile_id, chosen_dir, fallback, error.
internal static string BuildDecisionJson(DecisionRecord r)
{
    StringBuilder sb = new StringBuilder();
    sb.Append("{");
    sb.Append("\"turn\":").Append(r.Turn.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"schema\":\"decision.v1\"");
    sb.Append(",\"branch\":");
    AppendJsonString(sb, r.Branch);
    sb.Append(",\"hp\":").Append(r.Hp.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"max_hp\":").Append(r.MaxHp.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"hurt\":").Append(r.Hurt ? "true" : "false");
    sb.Append(",\"adjacent_hostile_dir\":");
    AppendJsonStringOrNull(sb, r.AdjacentHostileDir);
    sb.Append(",\"adjacent_hostile_id\":");
    AppendJsonStringOrNull(sb, r.AdjacentHostileId);
    sb.Append(",\"chosen_dir\":");
    AppendJsonStringOrNull(sb, r.ChosenDir);
    sb.Append(",\"fallback\":");
    AppendJsonStringOrNull(sb, r.Fallback);
    sb.Append(",\"error\":null");
    sb.Append("}");
    return sb.ToString();
}
```

- [ ] **Step 5: Add `BuildDecisionSentinelJson` static method AFTER `BuildCmdSentinelJson`.**

Locate `BuildCmdSentinelJson` and insert immediately after its closing brace.

```csharp
// Builds the decision.v1 sentinel (exception path). Reduced shape: {turn, schema, error}.
// Same posture as command_issuance.v1 sentinel.
internal static string BuildDecisionSentinelJson(int turn, Exception ex)
{
    StringBuilder sb = new StringBuilder();
    sb.Append("{");
    sb.Append("\"turn\":").Append(turn.ToString(CultureInfo.InvariantCulture));
    sb.Append(",\"schema\":\"decision.v1\"");
    sb.Append(",\"error\":{");
    sb.Append("\"type\":");
    AppendJsonString(sb, ex?.GetType().Name ?? "Unknown");
    sb.Append(",\"message\":");
    AppendJsonString(sb, ex?.Message ?? "");
    sb.Append("}");
    sb.Append("}");
    return sb.ToString();
}
```

- [ ] **Step 6: Compile-check via in-game launch.**

```bash
# Sync the symlink (if needed)
ls "$MODS_DIR/LLMOfQud" || ln -s "$(pwd)/mod/LLMOfQud" "$MODS_DIR/LLMOfQud"

# Launch CoQ from Steam. Then:
grep -E "^\[[^]]+\] (Compiling [0-9]+ files?\.\.\.|Success :\)|COMPILER ERRORS)" \
  "$COQ_SAVE_DIR/build_log.txt" | tail -10
```

Expected: latest entries show `Compiling 3 files...` then `Success :)` for `LLMOfQud`. No `COMPILER ERRORS`. The new struct + builders are not yet exercised at runtime (no caller), so no `[decision]` lines appear in `Player.log` yet.

If compile fails:
- Read the compiler error line in `build_log.txt`.
- Common issues: missing `using` for `CultureInfo` (already imported in SnapshotState.cs), wrong access modifier (use `internal`), typo in struct field name. Fix and re-launch.

- [ ] **Step 7: Commit Task 2.**

```bash
git add mod/LLMOfQud/SnapshotState.cs
git diff --cached -- mod/LLMOfQud/SnapshotState.cs   # verify only the new struct + 2 methods are added
git commit -m "feat(mod): SnapshotState DecisionRecord + BuildDecisionJson + BuildDecisionSentinelJson (Phase 0-G Task 2)"
```

---

## Task 3: LLMOfQudSystem helpers — IsSafeCell, ChooseFleeDir, ChooseExploreDir, ScanAdjacentHostile extraction

**Why this task exists:** The decision logic needs three new private helpers. Co-locating them in `LLMOfQudSystem.cs` (rather than `SnapshotState.cs`) keeps game-state-reading code together. The existing 8-direction hostile scan inside `HandleEvent(CommandTakeActionEvent)` is also extracted into `ScanAdjacentHostile` for reuse from the new decision logic.

**Files:** Modify `mod/LLMOfQud/LLMOfQudSystem.cs` only.

- [ ] **Step 1: Read the existing scan logic.**

```bash
sed -n '203,250p' mod/LLMOfQud/LLMOfQudSystem.cs
```

Identify the 8-direction scan (currently lines ~210-245 of the existing handler). The scan reads `cellBefore.GetCellFromDirection`, calls `Cell.GetCombatTarget` with the hostile filter, and breaks on first hit. Note the priority array `string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" }`.

- [ ] **Step 2: Add `ScanAdjacentHostile` private static helper.**

Insert ABOVE `HandleEvent(CommandTakeActionEvent)`:

```csharp
// Extracted from Phase 0-F HandleEvent(CommandTakeActionEvent). 8-direction priority scan
// for adjacent hostiles. Filter mirrors Combat.AttackCell at
// decompiled/XRL.World.Parts/Combat.cs:877-889. First non-null GetCombatTarget hit wins.
// Returns out targetDir / targetObj; both null on no-hostile-found.
private static void ScanAdjacentHostile(
    Cell here, GameObject player,
    out string targetDir, out GameObject targetObj)
{
    targetDir = null;
    targetObj = null;
    if (here == null) return;
    string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
    for (int i = 0; i < priority.Length; i++)
    {
        // decompiled/XRL.World/Cell.cs:7322: GetCellFromDirection(string Direction, bool BuiltOnly = true)
        Cell adj = here.GetCellFromDirection(priority[i], BuiltOnly: false);
        if (adj == null) continue;
        // decompiled/XRL.World/Cell.cs:8511-8558 GetCombatTarget signature.
        // decompiled/XRL.World/GameObject.cs:10887-10894 IsHostileTowards.
        GameObject t = adj.GetCombatTarget(
            Attacker: player,
            IgnoreFlight: false,
            IgnoreAttackable: false,
            IgnorePhase: false,
            Phase: 5,
            AllowInanimate: false,
            Filter: o => o != player && o.IsHostileTowards(player));
        if (t != null)
        {
            targetDir = priority[i];
            targetObj = t;
            return;
        }
    }
}
```

- [ ] **Step 3: Add `IsSafeCell` private static helper.**

Insert AFTER `ScanAdjacentHostile`:

```csharp
// Phase 0-G safe-cell predicate per design spec. Four short-circuited conditions:
//   1. cell != null
//   2. decompiled/XRL.World/Cell.cs:5290-5305 IsEmptyOfSolidFor (no solid, no locked door,
//      no NPC body)
//   3. decompiled/XRL.World/Cell.cs:8511-8558 GetCombatTarget with hostile filter returns null
//   4. decompiled/XRL.World/Cell.cs:8597-8607 GetDangerousOpenLiquidVolume returns null
// All four must hold for the cell to be considered safe to step into.
private static bool IsSafeCell(Cell cell, GameObject player)
{
    if (cell == null) return false;
    if (!cell.IsEmptyOfSolidFor(player, IncludeCombatObjects: true)) return false;
    if (cell.GetCombatTarget(
            Attacker: player,
            IgnoreFlight: false,
            IgnoreAttackable: false,
            IgnorePhase: false,
            Phase: 5,
            AllowInanimate: false,
            Filter: o => o != player && o.IsHostileTowards(player)) != null) return false;
    if (cell.GetDangerousOpenLiquidVolume() != null) return false;
    return true;
}
```

- [ ] **Step 4: Add inverse-direction lookup helper.**

Insert AFTER `IsSafeCell`:

```csharp
// 8-direction inverse lookup. Phase 0-G flee uses this to compute "directly away from hostile".
// Pure function; no CoQ API call.
private static string InverseDirection(string dir)
{
    switch (dir)
    {
        case "N":  return "S";
        case "NE": return "SW";
        case "E":  return "W";
        case "SE": return "NW";
        case "S":  return "N";
        case "SW": return "NE";
        case "W":  return "E";
        case "NW": return "SE";
        default:   return null;
    }
}
```

- [ ] **Step 5: Add `ChooseFleeDir` private static helper.**

Insert AFTER `InverseDirection`:

```csharp
// Phase 0-G flee direction picker. Two-stage scan + boxed-in escalation per design spec.
//   1. Inverse direction first. If safe, return it (fallback=null).
//   2. Farthest-safe scan. Among safe cells in any of the 8 directions, pick the one with
//      max Chebyshev distance to the hostile's cell. Tie-break by N->NE->E->SE->S->SW->W->NW
//      priority. If at least one safe cell exists, return its direction (fallback=null).
//   3. Boxed-in. No safe cell anywhere. Return hostileDir with fallback="boxed_in_attack";
//      the caller switches the action from Move to AttackDirection.
private static string ChooseFleeDir(
    Cell here, GameObject hostileObj, string hostileDir, GameObject player,
    out string fallback)
{
    fallback = null;
    if (here == null || hostileObj == null || hostileDir == null)
    {
        fallback = "no_safe_cell_pass";
        return null;
    }

    // Stage 1: inverse direction.
    string inverseDir = InverseDirection(hostileDir);
    if (inverseDir != null)
    {
        Cell inverseCell = here.GetCellFromDirection(inverseDir, BuiltOnly: false);
        if (IsSafeCell(inverseCell, player)) return inverseDir;
    }

    // Stage 2: farthest-safe scan with priority tie-break.
    Cell hostileCell = hostileObj.CurrentCell;
    int hx = hostileCell?.X ?? here.X;
    int hy = hostileCell?.Y ?? here.Y;
    string[] priority = new[] { "N", "NE", "E", "SE", "S", "SW", "W", "NW" };
    string bestDir = null;
    int bestDist = -1;
    for (int i = 0; i < priority.Length; i++)
    {
        Cell adj = here.GetCellFromDirection(priority[i], BuiltOnly: false);
        if (!IsSafeCell(adj, player)) continue;
        int dx = adj.X - hx;
        int dy = adj.Y - hy;
        int dist = System.Math.Max(System.Math.Abs(dx), System.Math.Abs(dy));
        if (dist > bestDist)
        {
            bestDist = dist;
            bestDir = priority[i];
        }
        // Equal-distance tie: priority order wins; do NOT update bestDir.
    }
    if (bestDir != null) return bestDir;

    // Stage 3: boxed-in escalation.
    fallback = "boxed_in_attack";
    return hostileDir;
}
```

- [ ] **Step 6: Add `ChooseExploreDir` private static helper.**

Insert AFTER `ChooseFleeDir`:

```csharp
// Phase 0-G explore direction picker. East-bias with priority fallback per design spec.
//   1. If East is safe, return "E".
//   2. Else iterate SE -> NE -> S -> N -> W -> SW -> NW; return first safe direction.
//   3. If no direction is safe, return null (caller treats as no-safe-cell-pass).
private static string ChooseExploreDir(Cell here, GameObject player)
{
    if (here == null) return null;
    string[] order = new[] { "E", "SE", "NE", "S", "N", "W", "SW", "NW" };
    for (int i = 0; i < order.Length; i++)
    {
        Cell adj = here.GetCellFromDirection(order[i], BuiltOnly: false);
        if (IsSafeCell(adj, player)) return order[i];
    }
    return null;
}
```

- [ ] **Step 7: Compile-check via in-game launch.**

Same procedure as Task 2 Step 6. Expected: `Success :)`, no errors. The new helpers are still unused at runtime (no caller); compilation alone validates the code.

- [ ] **Step 8: Commit Task 3.**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
git diff --cached -- mod/LLMOfQud/LLMOfQudSystem.cs   # verify only the 5 new helpers are added
git commit -m "feat(mod): LLMOfQudSystem helpers — IsSafeCell, ChooseFleeDir, ChooseExploreDir, ScanAdjacentHostile (Phase 0-G Task 3)"
```

---

## Task 4: HandleEvent(CommandTakeActionEvent) decision-then-execute refactor

**Why this task exists:** This is the load-bearing change — the existing handler body is replaced with the decision-then-execute flow that consumes the Task 3 helpers and emits both `[decision]` and `[cmd]` per turn. The 3-layer drain `try/catch/finally` outer structure (ADR 0006 + ADR 0007) is preserved verbatim.

**Files:** Modify `mod/LLMOfQud/LLMOfQudSystem.cs` only.

- [ ] **Step 1: Read the existing handler.**

```bash
sed -n '180,378p' mod/LLMOfQud/LLMOfQudSystem.cs
```

Identify the boundaries: the `try` block opens around line 197 (after the `if (player == null)` early return), the `catch` block opens around line 339, the `finally` block opens around line 358. The new logic replaces the body of the `try` block.

- [ ] **Step 2: Replace the `try` block with the decision-then-execute flow.**

Replace the existing scan + action-dispatch + cmd-emission code (roughly lines 197-338) with the following. Preserve the outer `try / catch / finally` exactly as it stands today; ONLY the `try` block body changes.

```csharp
try
{
    int energyBefore = player.Energy?.Value ?? 0;
    Cell cellBefore = player.CurrentCell;
    int posBeforeX = cellBefore?.X ?? -1;
    int posBeforeY = cellBefore?.Y ?? -1;
    string posBeforeZone = cellBefore?.ParentZone?.ZoneID;

    int hp = player.hitpoints;
    int maxHp = player.baseHitpoints;

    // ---- Decide ----
    string hostileDir;
    GameObject hostileObj;
    ScanAdjacentHostile(cellBefore, player, out hostileDir, out hostileObj);
    bool adjacentHostile = (hostileObj != null);

    // hurt = composite per ADR 0008 Decision #3.
    // PROBE 2 may amend the 0.60 ratio and 8 floor; the formula structure is locked.
    int hurtFloor = 8;
    double hurtRatio = 0.60;
    bool hurt = adjacentHostile
                && hp <= System.Math.Max(hurtFloor, (int)System.Math.Floor(maxHp * hurtRatio));

    string branch;
    string chosenDir;
    string decisionFallback = null;

    if (hurt)
    {
        branch = "flee";
        chosenDir = ChooseFleeDir(cellBefore, hostileObj, hostileDir, player, out decisionFallback);
    }
    else if (adjacentHostile)
    {
        branch = "attack";
        chosenDir = hostileDir;
    }
    else
    {
        branch = "explore";
        chosenDir = ChooseExploreDir(cellBefore, player);
        if (chosenDir == null) decisionFallback = "no_safe_cell_pass";
    }

    SnapshotState.DecisionRecord drec = new SnapshotState.DecisionRecord
    {
        Turn = turn,
        Branch = branch,
        Hp = hp,
        MaxHp = maxHp,
        Hurt = hurt,
        AdjacentHostileDir = hostileDir,
        AdjacentHostileId = hostileObj?.ID,
        ChosenDir = chosenDir,
        Fallback = decisionFallback,
    };
    MetricsManager.LogInfo("[LLMOfQud][decision] " + SnapshotState.BuildDecisionJson(drec));
    decisionEmitted = true;

    // ---- Execute ----
    bool result;
    string action;
    string dir;
    string targetId = null;
    string targetName = null;
    bool hasTargetPosBefore = false;
    int targetPosBeforeX = -1;
    int targetPosBeforeY = -1;
    string targetPosBeforeZone = null;
    int? targetHpBefore = null;

    bool actAsAttack = (branch == "attack")
                    || (branch == "flee" && decisionFallback == "boxed_in_attack");

    if (actAsAttack)
    {
        // Attack the hostile (chosenDir == hostileDir for both pure attack and boxed-in flee).
        targetId = hostileObj.ID;
        targetName = hostileObj.ShortDisplayNameStripped;
        Cell tCell = hostileObj.CurrentCell;
        if (tCell != null)
        {
            hasTargetPosBefore = true;
            targetPosBeforeX = tCell.X;
            targetPosBeforeY = tCell.Y;
            targetPosBeforeZone = tCell.ParentZone?.ZoneID;
        }
        targetHpBefore = hostileObj.hitpoints;
        result = player.AttackDirection(chosenDir);
        action = "AttackDirection";
        dir = chosenDir;
    }
    else if (chosenDir != null)
    {
        // Move (explore east-bias OR flee safe-cell).
        // AutoAct.ClearAutoMoveStop mirrors decompiled/XRL.Core/XRLCore.cs:1108 CmdMoveE wrapper.
        AutoAct.ClearAutoMoveStop();
        result = player.Move(chosenDir, DoConfirmations: false);
        action = "Move";
        dir = chosenDir;
    }
    else
    {
        // explore-no-safe-cell. Set up a "result=false to fall through to PassTurn" outcome.
        result = false;
        action = "Move";
        dir = "E"; // placeholder dir for the [cmd] line; actual action is PassTurn fallback below.
    }

    bool energySpent = (player.Energy != null && player.Energy.Value < energyBefore);
    string cmdFallback = null;
    if (!result && !energySpent)
    {
        player.PassTurn();
        energySpent = true;
        cmdFallback = "pass_turn";
    }
    else if (!result)
    {
        cmdFallback = "pass_turn";
    }

    int? targetHpAfter = (hostileObj != null && actAsAttack) ? (int?)hostileObj.hitpoints : null;
    int energyAfter = player.Energy?.Value ?? 0;
    Cell cellAfter = player.CurrentCell;

    SnapshotState.CmdRecord crec = new SnapshotState.CmdRecord
    {
        Turn = turn,
        Action = action,
        Dir = dir,
        Result = result,
        Fallback = cmdFallback,
        EnergyBefore = energyBefore,
        EnergyAfter = energyAfter,
        PosBeforeX = posBeforeX,
        PosBeforeY = posBeforeY,
        PosBeforeZone = posBeforeZone,
        PosAfterX = cellAfter?.X ?? -1,
        PosAfterY = cellAfter?.Y ?? -1,
        PosAfterZone = cellAfter?.ParentZone?.ZoneID,
        TargetId = targetId,
        TargetName = targetName,
        HasTargetPosBefore = hasTargetPosBefore,
        TargetPosBeforeX = targetPosBeforeX,
        TargetPosBeforeY = targetPosBeforeY,
        TargetPosBeforeZone = targetPosBeforeZone,
        TargetHpBefore = targetHpBefore,
        TargetHpAfter = targetHpAfter,
    };
    MetricsManager.LogInfo("[LLMOfQud][cmd] " + SnapshotState.BuildCmdJson(crec));
}
```

- [ ] **Step 3: Add `decisionEmitted` flag declaration ABOVE the `try` block.**

The new logic uses `decisionEmitted` to avoid emitting a duplicate `[decision]` sentinel from the `catch` block when the decision was already published. Insert immediately AFTER `int turn = _beginTurnCount;` and BEFORE the first `try`:

```csharp
bool decisionEmitted = false;
```

- [ ] **Step 4: Update the `catch` block to emit the `[decision]` sentinel only when not yet emitted.**

The existing `catch` block emits `[cmd]` sentinel + runs the 3-layer drain. Add a `[decision]` sentinel emission AT THE START of the `catch` block, gated by `!decisionEmitted`:

```csharp
catch (Exception ex)
{
    // Emit [decision] sentinel ONLY if the [decision] line for this turn was not yet
    // published. Both sentinels guarantee per-turn parity for parsers.
    if (!decisionEmitted)
    {
        MetricsManager.LogInfo("[LLMOfQud][decision] " + SnapshotState.BuildDecisionSentinelJson(turn, ex));
    }
    MetricsManager.LogInfo(
        "[LLMOfQud][cmd] " + SnapshotState.BuildCmdSentinelJson(turn, ex));
    // (existing 3-layer drain block unchanged from Phase 0-F)
    if (player?.Energy != null && player.Energy.Value >= 1000)
    {
        try { player.PassTurn(); } catch { /* swallow */ }
        if (player.Energy.Value >= 1000)
        {
            player.Energy.BaseValue = 0;
        }
    }
}
```

The `finally` block stays unchanged from Phase 0-F (ADR 0007 PreventAction scope).

- [ ] **Step 5: Update the `if (player == null)` early-return path.**

The existing early-return emits `[cmd]` sentinel only. For Phase 0-G parity, also emit `[decision]` sentinel. Locate the `if (player == null)` block (around line 186):

```csharp
if (player == null)
{
    MetricsManager.LogInfo(
        "[LLMOfQud][decision] " + SnapshotState.BuildDecisionSentinelJson(
            turn, new System.NullReferenceException("The.Player is null")));
    MetricsManager.LogInfo(
        "[LLMOfQud][cmd] {\"turn\":" + turn +
        ",\"schema\":\"command_issuance.v1\",\"error\":{\"type\":\"NullPlayer\",\"message\":\"The.Player is null\"}}");
    E.PreventAction = true;
    return true;
}
```

The `[cmd]` sentinel is left as the inline-string form for parity with Phase 0-F's existing posture (the canonical `BuildCmdSentinelJson` would also work; pick whichever matches the existing inline-vs-helper convention in the file).

- [ ] **Step 6: Compile-check via in-game launch.**

Same procedure as Task 2 Step 6. This time, the new code IS exercised at runtime. Expected:

- `build_log.txt`: `Success :)`, no errors.
- `Player.log`: per turn, ONE `[decision]` line and ONE `[cmd]` line. The `[decision]` line should always have `branch ∈ {"flee", "attack", "explore"}`.
- Manual spot-check: launch a fresh Joppa Warden, run for ~10 turns. Verify `branch == "explore"` for all turns where no hostile is adjacent.

```bash
grep "INFO - \[LLMOfQud\]\[decision\]" "$PLAYER_LOG" | head -10
grep "INFO - \[LLMOfQud\]\[cmd\]" "$PLAYER_LOG" | head -10
```

If `[decision]` lines do not appear:
- Check the Compile output for warnings about unused variables (the `decisionEmitted` flag may be flagged).
- Confirm the `MetricsManager.LogInfo("[LLMOfQud][decision] " + ...)` line is reachable (no early return / continue before it).

If `[decision]` and `[cmd]` line counts diverge per turn:
- Check the catch-path emission gating (the `if (!decisionEmitted)` should produce one decision sentinel per catch-path turn, AND one cmd sentinel always).

- [ ] **Step 7: Commit Task 4.**

```bash
git add mod/LLMOfQud/LLMOfQudSystem.cs
git diff --cached -- mod/LLMOfQud/LLMOfQudSystem.cs
git commit -m "feat(mod): HandleEvent(CommandTakeActionEvent) decision-then-execute refactor + [decision] channel emission (Phase 0-G Task 4)"
```

---

## Task 5: 5-run Warden acceptance

**Why this task exists:** The 5-run gate at `docs/architecture-v5.md:2812` is the canonical Phase 0-G acceptance. Three of five runs must survive ≥50 turns without a CoQ process crash. The runs also exercise PROBE 5 (channel correlation under branch mix).

**Files:** No code changes. All work is operator-driven.

- [ ] **Step 1: Verify single-mod load order.**

Launch CoQ once. Open the Mods menu and confirm only `LLMOfQud` is enabled. If other mods are enabled, disable them and re-launch to refresh the load.

- [ ] **Step 2: Set up the acceptance log capture script.**

```bash
mkdir -p /tmp/phase-0-g-acceptance/{run-1,run-2,run-3,run-4,run-5}
```

- [ ] **Step 3: Run RUN 1.**

Operator workflow:
1. Quit CoQ if running. Launch CoQ fresh.
2. Wait for `Player.log` to be created or rotated. Note the launch wall-time.
3. New Game → Mutated Human → Warden → Roleplay mode → Standard preset mutations. Skip the tutorial.
4. Once in Joppa, do NOT press any keys. The MOD's `HandleEvent(CommandTakeActionEvent)` will dispatch automatically.
5. Watch the in-game player. Note the turn the player dies (if any) or count `[cmd]` lines until the player crosses turn 50.
6. Once turn 50 is crossed (or the player dies), quit CoQ.

Capture all 6 per-turn channels (the spec criterion 6 ERR-count gate requires ALL of `[screen]`, `[state]`, `[caps]`, `[build]`, `[decision]`, `[cmd]`; missing any channel makes the soft gate uncheckable):

```bash
RUN=1
RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN
cp "$PLAYER_LOG" "$RUNDIR/raw-player.log"
for ch in screen state caps build decision cmd; do
  grep "INFO - \[LLMOfQud\]\[$ch\]" "$RUNDIR/raw-player.log" > "$RUNDIR/$ch.log"
done
echo "Run $RUN: $(for ch in screen state caps build decision cmd; do echo -n "$ch=$(wc -l < $RUNDIR/$ch.log) "; done)"
```

- [ ] **Step 4: Repeat Steps 1-3 for RUN 2 through RUN 5.**

Each run is a fresh chargen (new Mutated Human Warden). Within a single CoQ launch, multiple runs are possible by quitting back to the main menu and starting a new game (the `_beginTurnCount` resets per Phase 0-E's documented behavior at `docs/memo/phase-0-f-exit-2026-04-26.md:81`). Capture each run's `cmd.log` / `decision.log` / `state.log` separately.

- [ ] **Step 5: Validate per-run acceptance.**

The validator runs per-run and EXITS NON-ZERO on any HARD-gate failure. Soft-gate failures (ERR_* > 0 on non-screen channels) print warnings but do not fail the run; criterion 6 specifies `ERR_SCREEN == 0` is the only hard ERR gate.

For each run R in {1,2,3,4,5}, run:

```bash
RUN=R   # set R to 1, then 2, ...
RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN
RUN=$RUN RUNDIR=$RUNDIR python3 - <<'PY'
import json, os, sys

run = int(os.environ["RUN"])
rundir = os.environ["RUNDIR"]
hard_failures = []
soft_warnings = []

# ---------- 1. Load + parse channels ----------
# [screen] is INTENTIONALLY non-JSON: it emits "[LLMOfQud][screen] BEGIN turn=N w=... h=..."
# (multi-line LogInfo; the body + END are inside the same LogInfo call so only the BEGIN
# header carries the "INFO - [LLMOfQud][screen]" prefix). On error, it emits a separate
# "[LLMOfQud][screen] ERROR turn=N <ExceptionType>: <message>" line. See
# mod/LLMOfQud/LLMOfQudSystem.cs:475-497. The validator special-cases [screen] as text
# framing (count BEGIN-occurrences for per-turn parity; count ERROR-occurrences for
# ERR_SCREEN) and JSON-parses only the 5 structured channels.
def parse_json_line(line):
    """Strip the 'INFO - [LLMOfQud][chan] ' header and JSON-parse the payload."""
    parts = line.split("] ", 1)
    if len(parts) != 2:
        return None
    try: return json.loads(parts[1].strip())
    except json.JSONDecodeError: return None

def parse_screen_line(line):
    """Return ('begin', turn) | ('error', turn) | None for a [screen]-prefixed line."""
    # Body of the line after the "[LLMOfQud][screen] " prefix.
    parts = line.split("[LLMOfQud][screen] ", 1)
    if len(parts) != 2:
        return None
    body = parts[1].strip()
    # Try to extract turn=N from either BEGIN or ERROR shape.
    import re
    m = re.match(r"(BEGIN|ERROR)\s+turn=(\d+)", body)
    if not m:
        return None
    return (m.group(1).lower(), int(m.group(2)))

channels = {}
# Structured (JSON) channels.
for ch in ("state", "caps", "build", "decision", "cmd"):
    path = f"{rundir}/{ch}.log"
    raw = open(path).readlines()
    parsed = [parse_json_line(l) for l in raw]
    n_total = len(raw)
    n_valid = sum(1 for p in parsed if p is not None)
    n_invalid = n_total - n_valid
    channels[ch] = {"raw": raw, "parsed": parsed, "n_total": n_total, "n_valid": n_valid, "n_invalid": n_invalid}
    print(f"  [{ch}] total={n_total} json_valid={n_valid} json_invalid={n_invalid}")
    # Spec criterion 7: every emitted line MUST be JSON-valid for the structured channels
    # (the catch-path emits a sentinel JSON, NOT a partial line).
    if n_invalid > 0:
        hard_failures.append(f"[{ch}] has {n_invalid} JSON-invalid lines")

# Text-framed channel: [screen].
screen_raw = open(f"{rundir}/screen.log").readlines()
screen_parsed = [parse_screen_line(l) for l in screen_raw]
screen_begin_turns = sorted({t for kind, t in (p for p in screen_parsed if p) if kind == "begin"})
screen_error_turns = sorted({t for kind, t in (p for p in screen_parsed if p) if kind == "error"})
screen_unparsed = sum(1 for p in screen_parsed if p is None)
print(f"  [screen] total={len(screen_raw)} BEGIN={len(screen_begin_turns)} ERROR={len(screen_error_turns)} unparsed={screen_unparsed}")
if screen_unparsed > 0:
    # Unparsed [screen] lines are a parser-contract failure (BEGIN/ERROR/END shape changed).
    hard_failures.append(f"[screen] has {screen_unparsed} unparseable lines (expected BEGIN/ERROR pattern)")
channels["screen"] = {"n_total": len(screen_begin_turns), "n_invalid": 0, "begin_turns": screen_begin_turns, "error_turns": screen_error_turns}

# ---------- 2. Hard-gate: survival (criterion 1) ----------
state_parsed = [p for p in channels["state"]["parsed"] if p is not None]
last_state = state_parsed[-1] if state_parsed else None
last_hp = (last_state or {}).get("player", {}).get("hp")
n_cmd = channels["cmd"]["n_total"]
print(f"\nSurvival: n_cmd={n_cmd} last_hp={last_hp}")
if n_cmd < 50:
    hard_failures.append(f"survival: only {n_cmd} [cmd] lines (need ≥50)")
if last_hp is None or last_hp <= 0:
    hard_failures.append(f"survival: last_hp={last_hp!r} (need > 0)")

# ---------- 3. Hard-gate: ERR_SCREEN == 0 (criterion 6 hard gate) ----------
err_counts = {}
# Structured channels: error sentinel sets {"error": "<message>"} per Phase 0-D / 0-E / 0-F builders.
for ch in ("state", "caps", "build", "decision", "cmd"):
    err_counts[ch] = sum(1 for p in channels[ch]["parsed"] if p and p.get("error") is not None)
# [screen] error count comes from the BEGIN/ERROR text-frame parser above.
err_counts["screen"] = len(channels["screen"]["error_turns"])
print(f"\nERR counts (criterion 6): {err_counts}")
if err_counts["screen"] > 0:
    hard_failures.append(f"ERR_SCREEN={err_counts['screen']} (hard gate; must be 0)")
for ch in ("state", "caps", "build", "decision", "cmd"):
    if err_counts[ch] > 0:
        soft_warnings.append(f"ERR_{ch.upper()}={err_counts[ch]} (soft gate; record in exit memo)")

# ---------- 4. Hard-gate: channel parity (criterion 9 + PROBE 5) ----------
counts_by_ch = {ch: channels[ch]["n_total"] for ch in channels}
# Spec criterion 9: per-turn parity for the 6 per-turn channels (one line per channel per turn).
parity_ref = counts_by_ch["cmd"]
for ch in ("screen", "state", "caps", "build", "decision"):
    if counts_by_ch[ch] != parity_ref:
        # cmd vs decision is the strict-parity pair (PROBE 5); the other 4 channels emit per turn but ordering may differ — flag all deviations as warnings, escalate decision/cmd mismatch to hard.
        msg = f"channel parity: {ch}={counts_by_ch[ch]} vs cmd={parity_ref}"
        if ch == "decision":
            hard_failures.append(msg)
        else:
            soft_warnings.append(msg)

# ---------- 5. Branch ↔ action invariants (criterion 10) ----------
cmd_by_turn = {p["turn"]: p for p in channels["cmd"]["parsed"] if p and "turn" in p}
dec_by_turn = {p["turn"]: p for p in channels["decision"]["parsed"] if p and "turn" in p}
mismatches = 0
for t, dec in dec_by_turn.items():
    cmd = cmd_by_turn.get(t)
    if cmd is None:
        # criterion 9: every [decision] turn MUST have a [cmd] turn (parity is bidirectional).
        print(f"turn {t}: decision present but cmd MISSING")
        mismatches += 1
        continue
    branch = dec.get("branch")
    action = cmd.get("action")
    fallback = dec.get("fallback")
    if branch == "attack":
        if action != "AttackDirection":
            print(f"turn {t}: branch=attack but action={action!r} (expected AttackDirection)")
            mismatches += 1
    elif branch == "explore":
        if action != "Move":
            print(f"turn {t}: branch=explore but action={action!r} (expected Move)")
            mismatches += 1
    elif branch == "flee":
        if action not in ("Move", "AttackDirection"):
            print(f"turn {t}: branch=flee but action={action!r} (expected Move or AttackDirection)")
            mismatches += 1
        if action == "AttackDirection" and fallback != "boxed_in_attack":
            print(f"turn {t}: branch=flee + action=AttackDirection but fallback={fallback!r} (expected 'boxed_in_attack')")
            mismatches += 1
    else:
        print(f"turn {t}: unknown branch={branch!r}")
        mismatches += 1
    # Inverse invariant: fallback="boxed_in_attack" REQUIRES branch=flee AND action=AttackDirection.
    if fallback == "boxed_in_attack":
        if branch != "flee":
            print(f"turn {t}: fallback=boxed_in_attack but branch={branch!r} (expected flee)")
            mismatches += 1
        if action != "AttackDirection":
            print(f"turn {t}: fallback=boxed_in_attack but action={action!r} (expected AttackDirection)")
            mismatches += 1
# Cross-check: every [cmd] turn should have a [decision] turn too.
for t in cmd_by_turn:
    if t not in dec_by_turn:
        print(f"turn {t}: cmd present but decision MISSING")
        mismatches += 1
print(f"\nBranch/action mismatches: {mismatches}")
if mismatches > 0:
    hard_failures.append(f"branch/action invariant violations: {mismatches}")

# ---------- 6. Phase 0-F energy invariants (criterion 11) ----------
# Per ADR 0007 + Phase 0-F handler contract: every successful [cmd] turn MUST drain ≥1000 energy
# (the action API + PassTurn 3-layer drain pattern). Detect by checking that consecutive [state] turn
# numbers increment by exactly 1 (no turn skipped due to drain failure).
state_turns = sorted({p["turn"] for p in channels["state"]["parsed"] if p and "turn" in p})
gaps = []
for i in range(1, len(state_turns)):
    if state_turns[i] - state_turns[i-1] != 1:
        gaps.append((state_turns[i-1], state_turns[i]))
if gaps:
    soft_warnings.append(f"turn-gap detected (energy-invariant suspicious): {gaps[:5]}{'...' if len(gaps)>5 else ''}")

# ---------- 7. Final report + exit code ----------
print("\n" + "=" * 60)
if soft_warnings:
    print("SOFT WARNINGS (non-blocking):")
    for w in soft_warnings: print(f"  - {w}")
if hard_failures:
    print("HARD FAILURES (block run):")
    for f in hard_failures: print(f"  - {f}")
    print(f"\nRun {run}: FAIL")
    sys.exit(1)
else:
    print(f"Run {run}: PASS")
    sys.exit(0)
PY
```

The script's exit code is the per-run pass/fail signal — `$?` after the python heredoc gives the gate result. Re-running for RUN=1, RUN=2, ..., RUN=5 yields five exit codes; the 3-of-5 tally in Step 6 counts the zero exits.

- [ ] **Step 6: Tally the 3-of-5 gate.**

Re-run the Step 5 validator for each RUN and count the zero-exits. The validator already encodes survival + ERR_SCREEN + parity + branch/action + JSON-validity into its exit code, so the tally is just:

```bash
PASSING=0
for RUN in 1 2 3 4 5; do
  if RUN=$RUN RUNDIR=/tmp/phase-0-g-acceptance/run-$RUN bash -c '
    # Re-invoke the Step 5 validator (factor out into /tmp/phase-0-g-acceptance/validate.py to avoid heredoc duplication).
    python3 /tmp/phase-0-g-acceptance/validate.py
  ' > /tmp/phase-0-g-acceptance/run-$RUN/validate.out 2>&1; then
    PASSING=$((PASSING + 1))
    echo "Run $RUN: PASS"
  else
    echo "Run $RUN: FAIL — see /tmp/phase-0-g-acceptance/run-$RUN/validate.out"
  fi
done
echo "Passing: $PASSING/5"
```

Operator action before running this: copy the Step 5 python heredoc body to `/tmp/phase-0-g-acceptance/validate.py` (one-time setup; the heredoc body uses only `os.environ["RUN"]` and `os.environ["RUNDIR"]`).

PASS if `PASSING >= 3` (criterion 1: 3-of-5 gate). If FAIL, escalate to user with the failure summary; the heuristic may need tuning (Phase 0-G is a phase, not a feature — tuning is on the table).

- [ ] **Step 7: Commit acceptance results memo (optional).**

If acceptance produced surprising findings, capture in `docs/memo/phase-0-g-acceptance-findings-<DATE>.md` (operator-local; commit only if findings change the design).

---

## Task 6: 99% observation accuracy audit

**Why this task exists:** `docs/architecture-v5.md:2816` requires "All logged data matches in-game display (spot-check 20 random turns)". Phase 0-F's cross-channel parity gate does NOT discharge this — parity proves all channels emitted, not that the emitted data is semantically correct.

**Files:** No code changes. Operator-driven audit.

- [ ] **Step 1: Pick the audit run.**

Use one of the 5 surviving acceptance runs from Task 5 (preferably the longest-running one to maximize entity diversity). Or do a sixth dedicated run with screen recording enabled.

- [ ] **Step 2: Sample 20 random turns.**

```bash
RUN=1   # adjust to the chosen run
NSTATE=$(wc -l < /tmp/phase-0-g-acceptance/run-$RUN/state.log)
shuf -i 1-$NSTATE -n 20 | sort -n > /tmp/phase-0-g-acceptance/audit-turns.txt
cat /tmp/phase-0-g-acceptance/audit-turns.txt
```

If `shuf` is unavailable on macOS, use:

```bash
seq 1 $NSTATE | gshuf -n 20 | sort -n > /tmp/phase-0-g-acceptance/audit-turns.txt
# or:
python3 -c "import random; print('\n'.join(map(str, sorted(random.sample(range(1, $NSTATE+1), 20)))))" > /tmp/phase-0-g-acceptance/audit-turns.txt
```

- [ ] **Step 3: Capture in-game state for each sampled turn.**

This requires either:
- Replaying the same chargen with a screen recorder running and pausing at each sampled turn (manual).
- Re-running with `[state]` reasonable spot checks during a fresh acceptance run.

For the manual workflow:
1. Open `state.log` and `cmd.log` for the audit run.
2. For each sampled turn N in `audit-turns.txt`:
   - Find the line in `state.log` with `"turn":N`. Extract `player.hp`, `player.pos`, `entities[]`.
   - Recall (or replay if recorded) the in-game display at turn N.
   - Compare: HP integer matches the in-game HP display? `player.pos.{x,y,zone}` matches the player's on-screen position? Each `entities[]` member with `id != null` is visible on screen?
3. Tally matches and mismatches. Record in `/tmp/phase-0-g-acceptance/audit-results.md`.

- [ ] **Step 4: Validate ≥19/20 match (95% pass for manual audit).**

Per spec criterion 4 + ADR 0008 Decision #6: 19/20 = 95% is the per-sample-pass criterion at N=20 (99% is mathematically unreachable at N=20 since the smallest representable rate is 95%). If a tighter audit is required (e.g. CI-graded acceptance, or the 95% floor feels too lax for a particular run), escalate to **N=100 sampled turns** (allowing at most 1 mismatch = 99% per-sample-pass) — this preserves the architecture-v5.md `:2816` 99% spirit exactly.

If <19/20 match:
- Identify the failing field(s). If `player.hp` is wrong, the `[state]` builder has a bug. If `entities[]` is missing visible hostiles, the visibility filter is wrong.
- Open a follow-up issue and re-tune the offending code path. Re-run Task 5 + Task 6 after the fix.

- [ ] **Step 5: Commit audit-results memo (optional).**

Same as Task 5 Step 7. Commit only if the audit found something that changes design.

---

## Task 7: Exit memo

**Why this task exists:** Every phase ends with an exit memo per `docs/memo/`'s established pattern. The memo captures outcome, acceptance counts, verified environment, sample shapes, implementation rules carried forward, open observations, files modified, and references — exactly the shape Phase 0-F's `docs/memo/phase-0-f-exit-2026-04-26.md` set.

**Files:** Create `docs/memo/phase-0-g-exit-<YYYY-MM-DD>.md`.

- [ ] **Step 1: Generate the date-stamped filename.**

```bash
DATE=$(date -u +%Y-%m-%d)
MEMO="docs/memo/phase-0-g-exit-$DATE.md"
echo "Will write to: $MEMO"
```

- [ ] **Step 2: Draft the exit memo.**

Mirror `docs/memo/phase-0-f-exit-2026-04-26.md`'s shape. Sections:

1. **Outcome** (2-4 paragraphs): summarize what shipped, the 5-run survival results, the 99% audit outcome, any mid-implementation course corrections.
2. **Acceptance counts** (table): per-run `[cmd]` / `[decision]` / `[state]` / `[caps]` / `[build]` / `[screen]` counts. ERR counts per channel. 3-of-5 surviving.
3. **Verified environment**: CoQ build, mod load order, file paths.
4. **Sample shapes**: one example each of `[decision]` for each branch (flee, attack, explore), one sentinel.
5. **Phase 0-G-specific implementation rules** (carry forward to Phase 0-G+ / Phase 1):
   - Decision-then-execute order: `[decision]` always emits BEFORE `[cmd]` on the same turn from the same `HandleEvent` call.
   - `decisionEmitted` flag is the catch-path discriminator.
   - Hurt threshold formula (from PROBE 2 result, default `0.60` ratio + `8` floor).
   - Boxed-in escalation: `flee` → `AttackDirection` is a defensible cut, NOT a sentinel.
   - Safe-cell predicate's 4 conditions in short-circuit order.
   - `[decision]` channel additive to the parser correlation contract; per-turn output is now 7 lines.
6. **Provisional cadence — future revisit triggers**: same shape as Phase 0-F.
7. **Open observations** (recorded but not blocking).
8. **Open hazards (still tracked from earlier phases)**.
9. **Files modified / created in Phase 0-G** (table).
10. **References**: architecture-v5.md, ADRs, decompiled APIs verified.

- [ ] **Step 3: Commit and merge.**

```bash
git add "$MEMO"
git commit -m "docs(memo): Phase 0-G exit memo ($DATE)"
```

- [ ] **Step 4: Open PR-G2.**

```bash
git push -u origin feat/phase-0-g-impl
gh pr create --base main --title "feat(mod): Phase 0-G heuristic bot — [decision] channel + decision-then-execute + 5-run Warden acceptance" --body "$(cat <<'EOF'
## Summary
- `mod/LLMOfQud/SnapshotState.cs`: new `DecisionRecord` struct, `BuildDecisionJson`, `BuildDecisionSentinelJson` for the locked `decision.v1` schema (11 keys + sentinel).
- `mod/LLMOfQud/LLMOfQudSystem.cs`: extracted `ScanAdjacentHostile`, added `IsSafeCell`/`InverseDirection`/`ChooseFleeDir`/`ChooseExploreDir` private static helpers, refactored `HandleEvent(CommandTakeActionEvent)` to decision-then-execute. The 3-layer drain `try/catch/finally` outer structure (ADR 0006 + ADR 0007) is preserved verbatim.
- 5-run Warden acceptance: <FILL IN: surviving count out of 5> survived ≥50 turns; <FILL IN: ERR counts>; channel correlation (PROBE 5) PASS.
- 99% observation accuracy audit: <FILL IN: matches/20>.

Implementation per ADR 0008 + design spec at `docs/superpowers/specs/2026-04-26-phase-0-g-heuristic-bot-design.md`. PROBE 1-4 results: <FILL IN: brief PASS/PASS-WITH-NOTE summary>.

## Test plan
- [ ] CI green (pre-commit + pytest + governance + markdownlint + C# analyzer)
- [ ] CodeRabbit review addressed
- [ ] In-game acceptance attached: 5 runs, parity logs, audit results
EOF
)"
```

- [ ] **Step 5: Address CodeRabbit findings + merge.**

Same workflow as PR-G1 Task 0 Step 8, but for an impl PR (not docs-only). Code findings fix → push → CodeRabbit re-review → resolve threads → normal merge (NO `--admin`).

---

## Self-review checklist

Before opening PR-G1 (Task 0 Step 7):

- [ ] **Spec coverage:** Every Phase 0-G acceptance criterion in the spec maps to a task in this plan.
- [ ] **Placeholder scan:** No `TBD`, `TODO`, `<FILL IN>` in the spec or ADR. (The exception is the PR-G2 body's `<FILL IN>` placeholders for run-time numbers, which are filled in at Task 7 Step 4 time.)
- [ ] **Type consistency:** `DecisionRecord` field names match between `SnapshotState.cs` and the `BuildDecisionJson` shape. The `decisionEmitted` flag in `LLMOfQudSystem.cs` is referenced consistently.
- [ ] **Probe sequencing:** Tasks 1, 2, 3, 4, 5 are in order. Task 1 is the empirical-probe gate (PROBE 1-4); Task 5 includes PROBE 5.
- [ ] **No drive-by edits:** The implementation modifies ONLY `mod/LLMOfQud/SnapshotState.cs` and `mod/LLMOfQud/LLMOfQudSystem.cs`. No other files.
- [ ] **Phase 0-F invariants preserved:** `command_issuance.v1` schema untouched. ADR 0007 `PreventAction` scope untouched. 3-layer drain `try/catch/finally` outer structure untouched.

If any check fails, fix inline and re-circulate. The plan is then ready for execution.
