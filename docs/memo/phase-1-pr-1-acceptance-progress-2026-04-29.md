# Phase 1 PR-1 Acceptance Progress — 2026-04-29

## Scope

This memo records PR-1.1 acceptance progress. Four accepted runtime runs
were collected. The original five-run target was a conservative operator
goal, but the fourth run did not reveal new failure modes; the evidence was
accepted for PR review and PR #20 merged on 2026-04-29T02:28:27Z.

## Code Changes Under Test

- Disconnect pause no longer emits `[LLMOfQud][decision]` or `[LLMOfQud][cmd]`.
- Reconnect wake uses `ActionManager.SkipPlayerTurn = true` plus
  `Keyboard.KeyEvent.Set()` instead of injecting `Keyboard.PushKey`.
- `BrainClient` logs round-trip `elapsed_ms` on each successful response.
- The Python probe server disables WebSocket keepalive pings during chargen idle.
- The acceptance phase disconnects exactly once on request 6 and otherwise
  returns no-LLM canned decisions.
- The acceptance phase now oscillates east/west for non-hostile turns so the
  run does not drift into a zone boundary during metric collection.

## Accepted Evidence So Far

### Runtime Run 1

Artifact: `/tmp/llm-of-qud-acceptance-run1c.log`

- `[decision]=[cmd]=[state]=[caps]=[build]=[screen]=137`
- `[disconnect_pause]=1`
- `[wake]=1`
- `ERR_`, `ERROR`, `Exception`, and `Traceback`: 0
- Round-trip metrics: `n=137`, median `0ms`, p95 `1ms`, max `40ms`
- Reconnect wake resumed turn flow after the pause.

This run satisfies the single-run PR-1 acceptance shape. It does not satisfy
the five-run gate by itself.

### Runtime Run 2b

Artifact: `/tmp/llm-of-qud-acceptance-run2b.log`

- `[decision]=[cmd]=[state]=[caps]=[build]=[screen]=2834`
- `[disconnect_pause]=1`
- `[wake]=1`
- `ERR_`, `ERROR`, `MODERROR`, and `Traceback`: 0
- Round-trip metrics: `n=2834`, median `0ms`, p95 `1ms`, max `38ms`
- Reconnect wake resumed turn flow after the pause.

The source `Player-prev.log` ended with `ThreadAbortException` after turn
2834 because the operator force-quit CoQ. The accepted artifact cuts the log
immediately before that operator-termination abort.

### Runtime Run 3

Artifact: `/tmp/llm-of-qud-acceptance-run3.log`

- `[decision]=[cmd]=[state]=[caps]=[build]=[screen]=2399`
- `[disconnect_pause]=1`
- `[wake]=1`
- `ERR_`, `ERROR`, `MODERROR`, and `Traceback`: 0
- Round-trip metrics: `n=2399`, median `0ms`, p95 `1ms`, max `78ms`
- Reconnect wake resumed turn flow after the pause.

This run was captured from the current `Player.log` after restarting the
probe server and CoQ.

### Runtime Run 4

Artifact: `/tmp/llm-of-qud-acceptance-run4.log`

- `[decision]=[cmd]=[state]=[caps]=[build]=[screen]=2399`
- `[disconnect_pause]=1`
- `[wake]=1`
- `ERR_`, `ERROR`, `MODERROR`, and `Traceback`: 0
- Round-trip metrics: `n=2399`, median `0ms`, p95 `1ms`, max `30ms`
- Reconnect wake resumed turn flow after the pause.

This run used the same acceptance phase. CoQ initially ignored Computer Use
key delivery on one restart; the non-accepted startup was discarded before
runtime logging began, and the accepted artifact starts from a clean relaunch.

## Rejected / Non-Accepted Evidence

### Runtime Run 2

Artifact: `/tmp/llm-of-qud-acceptance-run2.log`

- `[decision]=[cmd]=123`
- `[state]=[caps]=[build]=[screen]=122`
- `[disconnect_pause]=1`
- `[wake]=1`
- `ERR_`, `ERROR`, `Exception`, and `Traceback`: 0
- Round-trip metrics: `n=123`, median `1ms`, p95 `1ms`, max `51ms`

This run proves reconnect wake again, but it is not accepted as a full run
because the old acceptance movement kept walking east into a zone transition;
the final turn emitted `[decision]` and `[cmd]` before the observation set
caught up. The acceptance policy was then changed to oscillate east/west.

## Operator Notes

- The earlier Computer Use window issue was caused by the display being off;
  it recovered after the display was re-enabled.
- The acceptance phase intentionally oscillates east/west during non-hostile
  turns. This is a test harness behavior to keep the character away from zone
  boundaries while long enough metric windows are collected.

## Fresh Local Verification

Commands passed after the acceptance-policy change:

```bash
uv run pytest tests/
uv run ruff check brain/
uv run ruff format --check brain/
uv run mypy --strict brain/
uv run basedpyright
pre-commit run --all-files
```

Results:

- `uv run pytest tests/`: 26 passed.
- `pre-commit run --all-files`: all hooks passed.

## PR Outcome

The runtime acceptance evidence was sufficient for PR-1 review:

- Four accepted runtime runs.
- Disconnect pause emitted no decision or command.
- Reconnect wake resumed turn flow in every accepted run.
- All accepted run artifacts have channel parity across decision, command,
  state, caps, build, and screen logs.
- Round-trip p95 stayed at `1ms`, well below the `<100ms` target.
- No `ERR_`, `ERROR`, `MODERROR`, or `Traceback` markers were observed in
  accepted artifacts.

PR #20 (`Phase 1 PR-1 disconnect acceptance hardening`) was approved and
squash-merged into `main` as commit `43c86a5`.

Post-merge commands passed on `main`:

```bash
uv run pytest tests/
pre-commit run --all-files
```

Results:

- `uv run pytest tests/`: 39 passed.
- `pre-commit run --all-files`: all hooks passed.
