"""R6 lifecycle verifier: probe evidence + harness ledgers + operator receipts -> per-case verdict.

    .venv/bin/python probes/R6-lifecycle/r6_verify.py \
        --evidence-dir PROFILE/r6-evidence --ledger RUN1/ledger.jsonl [--ledger RUN2/ledger.jsonl ...] \
        --receipts-dir RESULTS/receipts [--claims CLAIMS.json] [--require-recovery-claims] \
        [--cases menu_reenter,hotload,...] [--emit-recovery OUT.jsonl]

Deterministic and offline. Exit 0 only if every required case passed and no global check failed.
A pass here is a statement about the supplied files only; it is not a runtime claim by itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for entry in (str(HERE), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import r6_evidence as ev  # noqa: E402
from harness.verify import VerifyError, verify_ledger  # noqa: E402  (read-only reuse)

CASES = ("menu_reenter", "hotload", "checkpoint_reload", "save_quit_load", "crash_restart")
LOAD_CASES = frozenset({"menu_reenter", "checkpoint_reload", "save_quit_load", "crash_restart"})
LOSS_CASES = frozenset({"menu_reenter", "save_quit_load", "crash_restart", "hotload"})
PROCESS_CASES = frozenset({"save_quit_load", "crash_restart"})
LIST_KEYS = ("begin", "end", "end_single", "passed_ten", "after_render", "message")
OWN_EXPECTED = {"begin": 1, "end": 1, "end_single": 0, "passed_ten": 0, "after_render": 1, "message": 1}
PRODUCTION_EXPECTED = dict(OWN_EXPECTED)
RELOAD_LABEL = "Reload from checkpoint"
DEATH_RULE = "death_reload_checkpoint"
EXPECTED_FILE = {"checkpoint_reload": "Checkpoint", "menu_reenter": "Primary",
                 "save_quit_load": "Primary", "crash_restart": "Primary"}
RECEIPT_KINDS = frozenset({"crash", "exit", "fixture", "hashes"})
CLOCK_SLACK = timedelta(seconds=2)


class InputError(ValueError):
    """An input file is unreadable or malformed."""


@dataclass
class Event:
    pos: int
    sess_index: int
    session: ev.Session
    rec: dict

    @property
    def kind(self):
        return self.rec["kind"]

    @property
    def utc(self):
        return ev.parse_utc(self.rec["utc"])

    def ref(self):
        return {"session": self.rec["session"], "n": self.rec["n"], "kind": self.kind}


@dataclass
class Boundary:
    event: Event
    case: str | None
    before: list
    window: list
    detail: dict = field(default_factory=dict)


@dataclass
class LedgerRun:
    path: Path
    run_id: str
    rows: list


class Report:
    def __init__(self):
        self.global_errors = []

    def fail(self, code, detail, where=None):
        item = {"code": code, "detail": detail}
        if where is not None:
            item["where"] = where
        self.global_errors.append(item)


# ---------------------------------------------------------------- inputs

def load_ledgers(paths, report):
    runs = {}
    for path in paths:
        try:
            summary = verify_ledger(path)
        except (VerifyError, OSError) as exc:
            report.fail("ledger_invalid", f"{path}: {exc}")
            continue
        rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
        if summary["run_id"] is None:
            continue
        runs.setdefault(summary["run_id"], []).append(LedgerRun(Path(path), summary["run_id"], rows))
    return runs


def ledger_rows(runs, run_id, kind, seq=None):
    found = []
    for run in runs.get(run_id, []):
        for row in run.rows:
            if row["kind"] == kind and (seq is None or row["seq"] == seq):
                found.append((run, row))
    return found


def load_receipts(directory):
    receipts = []
    if directory is None:
        return receipts
    for path in sorted(Path(directory).glob("*.json")):
        try:
            value = ev.loads(path.read_text(encoding="utf-8"))
        except (OSError, ev.EvidenceError) as exc:
            raise InputError(f"receipt {path}: {exc}") from None
        if not isinstance(value, dict) or value.get("kind") not in RECEIPT_KINDS:
            raise InputError(f"receipt {path}: kind must be one of {sorted(RECEIPT_KINDS)}")
        value["_path"] = str(path)
        receipts.append(value)
    return receipts


def load_claims(path):
    if path is None:
        return None
    try:
        value = ev.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ev.EvidenceError) as exc:
        raise InputError(f"claims {path}: {exc}") from None
    claims = value.get("claims") if isinstance(value, dict) else None
    if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
        raise InputError("claims file must be {\"claims\": [ {case, index, ...}, ... ]}")
    return {(c.get("case"), c.get("index")): c for c in claims}


# ---------------------------------------------------------------- timeline

def build_timeline(sessions):
    timeline = []
    for index, session in enumerate(sessions):
        for record in session.records:
            timeline.append(Event(len(timeline), index, session, record))
    return timeline


def production_ctas(events):
    return [e for e in events if e.kind == "cta_begin" and e.rec.get("source") == "production_cta"]


def find_receipt(receipts, kind, session):
    for receipt in receipts:
        if receipt["kind"] == kind and receipt.get("session") == session.session:
            return receipt
    return None


def is_process_start(event):
    return event.kind == "init" and event.rec.get("reason") == "process_start"


def derive_boundaries(timeline, sessions, receipts):
    """Boundaries are init and game_loaded records. ``window`` runs to the next boundary; ``before``
    runs back to the previous boundary that is not a process start, so a restarted session's first
    load still sees the old session's tail (its save_quit, its last CTA)."""
    positions = [e.pos for e in timeline if e.kind in ("init", "game_loaded")]
    boundaries = []
    loaded_sessions = set()
    for i, pos in enumerate(positions):
        event = timeline[pos]
        prev = next((p for p in reversed(positions[:i]) if not is_process_start(timeline[p])), -1)
        nxt = positions[i + 1] if i + 1 < len(positions) else len(timeline)
        before = [e for e in timeline[prev + 1:pos] if not is_process_start(e)]
        window = timeline[pos + 1:nxt]
        case = None
        detail = {}
        if event.kind == "init":
            if event.rec.get("reason") != "process_start":
                case = "hotload"
        elif event.sess_index not in loaded_sessions:
            loaded_sessions.add(event.sess_index)
            if event.sess_index == 0:
                case = "initial"
            else:
                old = sessions[event.sess_index - 1]
                crash = find_receipt(receipts, "crash", old)
                exit_ = find_receipt(receipts, "exit", old)
                quit_seen = any(e.kind in ("fixture_begin", "fixture_done") and e.rec.get("fixture") == "save_quit"
                                for e in timeline if e.sess_index == event.sess_index - 1)
                if crash is not None:
                    case = "crash_restart"
                elif exit_ is not None or quit_seen:
                    case = "save_quit_load"
                else:
                    case = "crash_restart"
                detail = {"old_session": old.session, "old_pid": old.pid,
                          "crash_receipt": crash, "exit_receipt": exit_}
        else:
            death = any(e.kind in ("die_path", "death_menu_seen") or
                        (e.kind == "fixture_begin" and e.rec.get("fixture") == "death") for e in before)
            ended = any(e.kind in ("fixture_begin", "fixture_done") and e.rec.get("fixture") == "save_quit"
                        for e in before)
            loaded = event.rec.get("loaded_file")
            if death and (loaded == "Checkpoint" or not ended):
                case = "checkpoint_reload"
            elif ended:
                case = "menu_reenter"
            else:
                case = "other_load"
        boundaries.append(Boundary(event, case, before, window, detail))
    return boundaries


# ---------------------------------------------------------------- checks

def counts_errors(rec, expected_own, expected_production, strict):
    """strict: equality (at the first CTA); otherwise only duplicates (count above expected)."""
    errors = []
    callbacks = rec.get("callbacks")
    if not isinstance(callbacks, dict):
        return [("callbacks_unreadable", "record has no callbacks snapshot")]
    if callbacks.get("error"):
        return [("callbacks_unreadable", str(callbacks["error"]))]
    for group, expected, code in (("own", expected_own, "own_callback_count"),
                                  ("production", expected_production, "production_callback_count")):
        counts = callbacks.get(group)
        if not isinstance(counts, dict):
            errors.append(("callbacks_unreadable", f"callbacks.{group} missing"))
            continue
        for key in LIST_KEYS:
            actual = counts.get(key)
            want = expected[key]
            if not isinstance(actual, int) or (actual != want if strict else actual > want):
                errors.append((code, f"{group}.{key}={actual!r}, expected {want} at "
                                     f"{rec['kind']} n={rec['n']}"))
    return errors


def bridge_errors(rec, strict):
    live = rec.get("bridge_live")
    if live is None:
        return [("bridge_count_unavailable", f"bridge_live is null at {rec['kind']} n={rec['n']} "
                                             "(production Bridge.LiveCount not found)")] if strict else []
    if not isinstance(live, int) or (live != 1 if strict else live > 1):
        return [("bridge_count", f"bridge_live={live!r} at {rec['kind']} n={rec['n']}")]
    return []


def vitals_match(game, row):
    vitals = row["body"]["observation"]["vitals"]
    return (game.get("turns"), game.get("zone"), game.get("x"), game.get("y")) == \
        (vitals["turn"], vitals["zone"], vitals["x"], vitals["y"])


def link_request(first, runs):
    """Return (errors, run_id, seq, rows) for the ledger request published at probe CTA ``first``."""
    production = first.rec.get("production") or {}
    run_id, seq = production.get("run_id"), production.get("seq")
    game = first.rec.get("game") or {}
    if isinstance(run_id, str) and isinstance(seq, int):
        rows = ledger_rows(runs, run_id, "request", seq + 1)
        if not rows:
            return [("first_request_missing", f"no ledger request for run {run_id} seq {seq + 1}")], run_id, seq, rows
        if len(rows) > 1:
            return [("first_request_duplicated", f"{len(rows)} ledger request rows for run {run_id} "
                                                 f"seq {seq + 1}")], run_id, seq, rows
        if not vitals_match(game, rows[0][1]):
            return [("first_request_mismatch", f"ledger request {run_id}/{seq + 1} vitals differ from "
                                               "the probe snapshot at that CTA")], run_id, seq, rows
        return [], run_id, seq, rows
    # Fallback: production private fields were unreadable; link by the exact vitals tuple.
    rows = [(run, row) for key in runs for run in runs[key] for row in run.rows
            if row["kind"] == "request" and vitals_match(game, row)]
    if len(rows) != 1:
        return [("unlinkable", f"production run_id/seq unavailable and {len(rows)} ledger requests "
                               "match the probe vitals")], None, None, rows
    run, row = rows[0]
    return [], run.run_id, row["seq"] - 1, rows


def death_label_evidence(before, runs, run_id, since_seq):
    for e in before:
        if e.kind == "death_menu_answered" and e.rec.get("label") == RELOAD_LABEL:
            return "probe_label"
    if run_id is None:
        return None
    modals = {}
    for _, row in ledger_rows(runs, run_id, "modal"):
        modals[row["body"].get("token")] = row["body"].get("modal") or {}
    for _, row in ledger_rows(runs, run_id, "modal_auto"):
        body = row["body"]
        if row["seq"] >= since_seq and body.get("rule") == DEATH_RULE and body.get("accepted") is True:
            return "ledger_modal_auto"
    for _, row in ledger_rows(runs, run_id, "modal_answer"):
        body = row["body"]
        choice = (body.get("response") or {}).get("choice")
        modal = modals.get(body.get("token"), {})
        labels = {c.get("id"): c.get("label") for c in modal.get("choices", [])}
        if row["seq"] >= since_seq and labels.get(choice) == RELOAD_LABEL:
            return "ledger_modal_answer"
    return None


def check_case(boundary, timeline, runs, receipts, claims, occurrence, options):
    case = boundary.case
    rec = boundary.event.rec
    errors, facts = [], {"case": case, "index": occurrence, "boundary": boundary.event.ref()}

    def fail(code, detail):
        errors.append({"code": code, "detail": detail})

    before_all = timeline[:boundary.event.pos]
    prior_game = ev.last_game([e.rec for e in before_all])
    expected_game_id = prior_game.get("game_id") if prior_game else None
    facts["expected_game_id"] = expected_game_id

    # --- lifecycle-specific evidence before the first CTA
    if case == "hotload":
        fixture_open = False
        for e in boundary.before:
            if e.kind == "fixture_begin" and e.rec.get("fixture") == "reload":
                fixture_open = True
            elif e.kind in ("fixture_done", "fixture_error"):
                fixture_open = False
        real = (rec.get("lists_replaced") is True and rec.get("sentinel_reset") is True and
                rec.get("hotload_frame") is True and (rec.get("wish_frame") is True or fixture_open))
        facts["hotload_evidence"] = {key: rec.get(key) for key in
                                     ("lists_replaced", "sentinel_reset", "hotload_frame", "wish_frame")}
        facts["hotload_evidence"]["fixture_bracket"] = fixture_open
        if not real:
            fail("hotload_not_real", "reinit lacks replaced XRLCore lists, reset sentinel, "
                                     "HotloadConfiguration frame, or reload-wish evidence")
        own = (rec.get("callbacks") or {}).get("own") or {}
        if any(own.get(k) != OWN_EXPECTED[k] for k in LIST_KEYS):
            fail("own_callback_count", f"probe callbacks after re-registration: {own}")

    loaded = None
    if case in LOAD_CASES:
        loaded = rec
        game = rec.get("game") or {}
        facts["loaded_game"] = game
        want = EXPECTED_FILE[case]
        facts["loaded_file"] = rec.get("loaded_file")
        candidate = (rec.get("candidates") or {}).get(want)
        if rec.get("loaded_file_basis") not in ("json_turn_unique", "json_turn_tie_identical_hash"):
            fail("save_hash", "loaded save identity is ambiguous or unproven")
        if rec.get("loaded_file") != want or not isinstance(candidate, dict):
            fail("save_hash", f"loaded file is {rec.get('loaded_file')!r}, expected {want}")
        else:
            facts["loaded_sha256"] = candidate.get("sha256")
            if candidate.get("json_turn") != game.get("turns"):
                fail("save_hash", f"{want}.json Turn {candidate.get('json_turn')} != loaded Turns {game.get('turns')}")
            saves = [e for e in before_all if e.kind == "save_observed" and e.rec.get("file") == want
                     and e.rec.get("game_id") == game.get("game_id")
                     and (e.rec.get("baseline") is not True or e.rec["session"] != rec["session"]
                          or e.rec["boundary"] < rec["boundary"])]
            if not saves:
                fail("save_hash", f"no recorded {want} save before this load")
            else:
                last = saves[-1].rec
                facts["last_saved_sha256"] = last.get("sha256")
                if last.get("sha256") != candidate.get("sha256"):
                    fail("save_hash", f"loaded {want} sha256 {candidate.get('sha256')} differs from the last "
                                      f"recorded save {last.get('sha256')}")
        if expected_game_id is not None and game.get("game_id") != expected_game_id:
            fail("game_identity", f"loaded game_id {game.get('game_id')!r} != {expected_game_id!r}")

    if case == "checkpoint_reload":
        die = [e for e in boundary.before if e.kind == "die_path"]
        menu = [e for e in boundary.before if e.kind == "death_menu_seen"]
        fixture = [e for e in boundary.before if e.kind == "fixture_begin" and e.rec.get("fixture") == "death"]
        facts["artificial_death"] = bool(fixture)
        if not die:
            fail("real_death_absent", "no die_path record (GameObject.Die frame at AfterRender) before the reload")
        if not menu:
            fail("real_death_absent", "no Roleplay death menu was observed before the reload")
        pre = production_ctas(before_all)
        run_id = (pre[-1].rec.get("production") or {}).get("run_id") if pre else None
        since = ((pre[-1].rec.get("production") or {}).get("seq") or 0) + 1 if pre else 1
        label = death_label_evidence(boundary.before, runs, run_id, since)
        facts["reload_label_evidence"] = label
        if label is None:
            fail("death_label_absent", f"no evidence that '{RELOAD_LABEL}' was chosen by label")
        if fixture:
            after = [e for e in boundary.before if e.pos > fixture[-1].pos]
            if production_ctas(after):
                fail("fixture_created_decision", "a production CTA ran between the death fixture and the reload")
        death_game = ev.last_game([e.rec for e in boundary.before])
        if death_game and loaded:
            facts["checkpoint_rewind_turns"] = death_game["turns"] - (loaded.get("game") or {}).get("turns", 0)

    if case in ("menu_reenter", "save_quit_load"):
        quits = [e for e in boundary.before if e.kind == "fixture_begin" and e.rec.get("fixture") == "save_quit"]
        if quits and production_ctas([e for e in boundary.before if e.pos > quits[-1].pos]):
            fail("fixture_created_decision", "a production CTA ran between save_quit and the reload")

    if case in PROCESS_CASES:
        old_pid = boundary.detail.get("old_pid")
        old_session = boundary.detail.get("old_session")
        old_events = [e for e in timeline if e.rec["session"] == old_session]
        new_session_first = next(e for e in timeline if e.rec["session"] == rec["session"])
        if case == "crash_restart":
            receipt = boundary.detail.get("crash_receipt")
            if receipt is None:
                fail("crash_receipt_absent", f"no crash receipt for session {old_session} (pid {old_pid})")
            else:
                facts["crash_receipt"] = receipt["_path"]
                problems = []
                if receipt.get("pid") != old_pid:
                    problems.append("pid differs from the crashed session")
                if receipt.get("signal") != "SIGKILL" or receipt.get("dry_run"):
                    problems.append("not a SIGKILL (or dry run)")
                verified = receipt.get("verified") or {}
                for key in ("profile", "argv", "heartbeat"):
                    if verified.get(key) is not True:
                        problems.append(f"verified.{key} is not true")
                if receipt.get("process_gone") is not True:
                    problems.append("process not confirmed gone")
                try:
                    killed = ev.parse_utc(receipt.get("kill_utc"))
                    if killed + CLOCK_SLACK < old_events[-1].utc or killed > new_session_first.utc + CLOCK_SLACK:
                        problems.append("kill time is outside the crashed and restarted sessions")
                except ev.EvidenceError as exc:
                    problems.append(str(exc))
                last_game = ev.last_game([e.rec for e in old_events])
                if last_game is None or receipt.get("last_probe_turn") != last_game.get("turns"):
                    problems.append("last_probe_turn differs from the crashed session evidence")
                if problems:
                    fail("crash_receipt_absent", "crash receipt invalid: " + "; ".join(problems))
        else:
            receipt = boundary.detail.get("exit_receipt")
            if receipt is None:
                fail("exit_receipt_absent", f"no graceful-exit receipt for session {old_session}")
            else:
                facts["exit_receipt"] = receipt["_path"]
                if (receipt.get("pid") != old_pid or receipt.get("graceful") is not True or
                        receipt.get("signal") is not None or receipt.get("process_gone") is not True):
                    fail("exit_receipt_absent", "exit receipt does not show a graceful exit of the old session")
        if receipt is not None and "loaded_sha256" in facts:
            external = ((receipt.get("saves") or {}).get(EXPECTED_FILE[case]) or {}).get("sha256")
            facts["receipt_sha256"] = external
            if external != facts["loaded_sha256"]:
                fail("save_hash", f"receipt hash {external} of {EXPECTED_FILE[case]} differs from the loaded hash")

    # --- first production CTA after the boundary
    ctas = production_ctas(boundary.window)
    first = ctas[0] if ctas else None
    pre_ctas = production_ctas(before_all)
    last_pre = pre_ctas[-1] if pre_ctas else None
    if first is None:
        fail("first_request_missing", "no production CTA after this boundary")
    else:
        frec = first.rec
        game = frec.get("game") or {}
        production = frec.get("production") or {}
        facts["first_cta"] = {"ref": first.ref(), "turns": game.get("turns"), "game_id": game.get("game_id"),
                              "run_id": production.get("run_id"), "request_seq":
                              production["seq"] + 1 if isinstance(production.get("seq"), int) else None,
                              "pending_seq": production.get("pending_seq")}
        facts["callbacks_at_first_cta"] = (frec.get("callbacks") or {})
        facts["bridge_live_at_first_cta"] = frec.get("bridge_live")
        if frec.get("first_after_boundary") is not True:
            fail("first_request_mismatch", "probe did not mark the first CTA after the boundary")
        for code, detail in counts_errors(frec, OWN_EXPECTED, PRODUCTION_EXPECTED, strict=True):
            fail(code, detail)
        for code, detail in bridge_errors(frec, strict=True):
            fail(code, detail)
        for e in boundary.window:
            if e is first or not isinstance(e.rec.get("callbacks"), dict):
                continue
            for code, detail in counts_errors(e.rec, OWN_EXPECTED, PRODUCTION_EXPECTED, strict=False):
                fail(code, detail)
            for code, detail in bridge_errors(e.rec, strict=False):
                fail(code, detail)
        marked = [e for e in boundary.window if e.kind == "cta_begin" and e.rec.get("first_after_boundary")]
        if len(marked) > 1:
            fail("first_request_duplicated", f"{len(marked)} CTAs marked first after one boundary")
        link_errors, run_id, seq, rows = link_request(first, runs)
        for code, detail in link_errors:
            fail(code, detail)
        if len(rows) == 1:
            telemetry = rows[0][1]["body"]["telemetry"]
            counters = {key: telemetry[key] for key in ("player_turn_entries", "end_player_turns")}
            facts["input_counters_at_first_cta"] = counters
            if any(counters.values()):
                fail("unexpected_player_turn", f"controlled player input counters must be zero: {counters}")
        same = [e for e in ctas[1:] if (e.rec.get("production") or {}).get("run_id") == run_id
                and (e.rec.get("production") or {}).get("seq") == seq]
        if run_id is not None and same:
            fail("first_request_duplicated", f"{len(same) + 1} production CTAs published run {run_id} seq {seq + 1}")
        if expected_game_id is not None and game.get("game_id") != expected_game_id:
            fail("game_identity", f"first CTA game_id {game.get('game_id')!r} != {expected_game_id!r}")
        if loaded is not None:
            loaded_turn = (loaded.get("game") or {}).get("turns")
            first_turn = game.get("turns")
            facts["loaded_turn"] = loaded_turn
            # Runtime run11 loads energy 138, then reaches CTA at 1038 after nine
            # speed increments. Static SegCount survives loads, so this can cross
            # a world turn. The save timestamp and first decision are distinct;
            # never alter energy or Turns to make them equal.
            if type(loaded_turn) is not int or type(first_turn) is not int or first_turn < loaded_turn:
                fail("game_identity", "first CTA Turns must not precede the independently observed load")
            else:
                facts["load_to_cta_turns"] = first_turn - loaded_turn
        # pending seq continuity
        prev_same = [e for e in pre_ctas if (e.rec.get("production") or {}).get("run_id") == run_id]
        if run_id is not None and seq is not None:
            pending = production.get("pending_seq")
            if prev_same:
                p_seq = (prev_same[-1].rec.get("production") or {}).get("seq")
                facts["run_continuity"] = "continued"
                recovery = ledger_rows(runs, run_id, "recovery", seq)
                if recovery:
                    if len(recovery) != 1 or case not in LOAD_CASES:
                        fail("recovery_mismatch", "recovery must identify exactly one actual load boundary")
                    else:
                        body = recovery[0][1]["body"]
                        facts["recovery"] = body
                        expected = {"game_id": expected_game_id, "save_file": EXPECTED_FILE[case],
                                    "save_sha256": facts.get("loaded_sha256"),
                                    "loaded_turn": (loaded.get("game") or {}).get("turns"),
                                    "reason": "checkpoint_reload" if case == "checkpoint_reload" else "save_reload"}
                        if any(body.get(key) != value for key, value in expected.items()):
                            fail("recovery_mismatch", "recovery metadata differs from the independently observed load")
                    if not isinstance(p_seq, int) or seq != p_seq + 1 or pending is not None:
                        fail("stale_pending_seq", "a recovery must clear the old pending decision and retain seq continuity")
                    if ledger_rows(runs, run_id, "result", seq):
                        fail("stale_pending_seq", "an interrupted request must not have a result")
                elif not isinstance(p_seq, int) or seq != p_seq + 1 or pending != p_seq + 1:
                    fail("stale_pending_seq", f"continuing run {run_id}: first CTA seq {seq}, pending {pending}; "
                                              f"expected seq {None if p_seq is None else p_seq + 1} and pending "
                                              f"{None if p_seq is None else p_seq + 1}")
                elif len(ledger_rows(runs, run_id, "result", seq)) != 1:
                    fail("stale_pending_seq", f"ledger lacks exactly one result for pending seq {seq}")
            else:
                facts["run_continuity"] = "new_run"
                if seq != 0 or pending is not None:
                    fail("stale_pending_seq", f"new run {run_id} must start at request seq 1 without a pending "
                                              f"decision (seq {seq}, pending {pending})")
        # lost turns
        prev_run = (last_pre.rec.get("production") or {}).get("run_id") if last_pre else None
        prev_seq = (last_pre.rec.get("production") or {}).get("seq") if last_pre else None
        if case in LOSS_CASES and prev_run is not None and isinstance(prev_seq, int):
            last_rows = ledger_rows(runs, prev_run, "request", prev_seq + 1)
            if len(last_rows) != 1:
                fail("lost_turns_unknown", f"ledger lacks the last request {prev_run}/{prev_seq + 1} before the boundary")
            else:
                last_turn = last_rows[0][1]["body"]["observation"]["vitals"]["turn"]
                raw = last_turn - game.get("turns", 0)
                facts["ledger_last_turn"] = last_turn
                facts["raw_turn_delta"] = raw
                facts["lost_turns"] = max(0, raw)
        elif case in LOSS_CASES:
            fail("lost_turns_unknown", "no production CTA before the boundary to anchor lost turns")

    # --- recovery claims (parent's recovery ledger)
    claim = claims.get((case, occurrence)) if claims is not None else None
    if claim is None:
        if options.require_claims:
            fail("recovery_claims_absent", f"no recovery claim for {case}[{occurrence}]")
    else:
        for key in ("lost_turns", "loaded_sha256", "game_id", "checkpoint_rewind_turns"):
            if key not in claim:
                continue
            actual = facts.get(key) if key != "game_id" else (facts.get("first_cta") or {}).get("game_id")
            if claim[key] != actual:
                code = "lost_turns_claim" if key == "lost_turns" else "recovery_claim_mismatch"
                fail(code, f"claim {key}={claim[key]!r} but evidence gives {actual!r}")
    return errors, facts


# ---------------------------------------------------------------- global checks

def global_checks(timeline, sessions, runs, receipts, boundaries, report, options):
    for session in sessions:
        if session.truncated_tail and find_receipt(receipts, "crash", session) is None:
            report.fail("evidence_chain", f"{session.path.name} ends with a partial line but has no crash receipt")
    for e in timeline:
        if e.kind == "fixture_error":
            report.fail("fixture_failed", f"{e.rec.get('fixture')}: {e.rec.get('error')}", e.ref())
    for b in boundaries:
        if b.case in ("other_load",):
            report.fail("unexplained_boundary", f"{b.case} at {b.event.ref()}")
    games_by_run = {}
    for e in production_ctas(timeline):
        production = e.rec.get("production") or {}
        run_id = production.get("run_id")
        if run_id is not None:
            games_by_run.setdefault(run_id, set()).add((e.rec.get("game") or {}).get("game_id"))
    for run_id, games in sorted(games_by_run.items()):
        if len(games) != 1:
            report.fail("game_identity", f"run {run_id} spans game ids {sorted(map(str, games))}")
    # budget
    wall = (max(s.last_utc for s in sessions) - min(s.first_utc for s in sessions)).total_seconds()
    played = 0
    positions = [b.event.pos for b in boundaries] + [len(timeline)]
    start = 0
    for stop in positions:
        last = None
        for e in timeline[start:stop]:
            game = e.rec.get("game")
            if isinstance(game, dict) and isinstance(game.get("turns"), int):
                if last is not None and game["turns"] > last:
                    played += game["turns"] - last
                last = game["turns"]
        start = stop
    budget = {"wall_seconds": round(wall, 3), "played_turns": played,
              "max_wall_seconds": options.max_wall_seconds, "max_turns": options.max_turns}
    if wall > options.max_wall_seconds or played > options.max_turns:
        report.fail("budget_exceeded", f"wall {wall:.1f}s / turns {played} exceed "
                                       f"{options.max_wall_seconds}s / {options.max_turns}")
    return budget


# ---------------------------------------------------------------- driver

def verify(evidence_dir, ledger_paths, receipts_dir=None, claims_path=None, cases=CASES,
           require_claims=False, max_wall_seconds=1800, max_turns=110):
    options = argparse.Namespace(require_claims=require_claims, max_wall_seconds=max_wall_seconds,
                                 max_turns=max_turns)
    report = Report()
    try:
        sessions = ev.load_sessions(Path(evidence_dir))
    except (OSError, ev.EvidenceError) as exc:
        return {"ok": False, "global_errors": [{"code": "evidence_chain", "detail": str(exc)}], "cases": []}
    receipts = load_receipts(receipts_dir)
    claims = load_claims(claims_path)
    runs = load_ledgers(ledger_paths, report)
    timeline = build_timeline(sessions)
    boundaries = derive_boundaries(timeline, sessions, receipts)
    results = []
    seen = {}
    for boundary in boundaries:
        if boundary.case in (None, "initial", "other_load"):
            continue
        occurrence = seen.get(boundary.case, 0)
        seen[boundary.case] = occurrence + 1
        errors, facts = check_case(boundary, timeline, runs, receipts, claims, occurrence, options)
        results.append({"case": boundary.case, "index": occurrence, "ok": not errors,
                        "errors": errors, "facts": facts})
    budget = global_checks(timeline, sessions, runs, receipts, boundaries, report, options)
    missing = [case for case in cases if case not in seen]
    for case in missing:
        report.fail("case_missing", f"required case {case} has no boundary in the evidence")
    required = [r for r in results if r["case"] in cases]
    ok = not report.global_errors and all(r["ok"] for r in required)
    artificial = any(r["facts"].get("artificial_death") for r in results)
    return {
        "ok": ok,
        "cases": results,
        "missing_cases": missing,
        "global_errors": report.global_errors,
        "budget": budget,
        "sessions": [{"session": s.session, "pid": s.pid, "file": s.path.name, "records": len(s.records),
                      "truncated_tail": s.truncated_tail} for s in sessions],
        "ledgers": sorted(str(run.path) for group in runs.values() for run in group),
        "claims": "absent" if claims is None else "checked",
        "gameplay_claim_eligible": False,
        "not_claimable_because": ["development profile and fixtures"] +
                                 (["artificial death fixture"] if artificial else []),
    }


def recovery_rows(summary):
    """Rows the parent's recovery-ledger consumer can append (one per verified case)."""
    rows = []
    for result in summary["cases"]:
        facts = result["facts"]
        rows.append({"kind": "r6_recovery", "case": result["case"], "index": result["index"],
                     "verified": result["ok"], "boundary": facts.get("boundary"),
                     "game_id": (facts.get("first_cta") or {}).get("game_id"),
                     "loaded_file": facts.get("loaded_file"), "loaded_sha256": facts.get("loaded_sha256"),
                     "loaded_turn": facts.get("loaded_turn"), "load_to_cta_turns": facts.get("load_to_cta_turns"),
                     "lost_turns": facts.get("lost_turns"), "raw_turn_delta": facts.get("raw_turn_delta"),
                     "checkpoint_rewind_turns": facts.get("checkpoint_rewind_turns"),
                     "first_request": facts.get("first_cta"),
                     "artificial_death": facts.get("artificial_death", False)})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, action="append", default=[])
    parser.add_argument("--receipts-dir", type=Path)
    parser.add_argument("--claims", type=Path)
    parser.add_argument("--require-recovery-claims", action="store_true")
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--max-wall-seconds", type=float, default=1800)
    parser.add_argument("--max-turns", type=int, default=110)
    parser.add_argument("--emit-recovery", type=Path)
    args = parser.parse_args(argv)
    cases = tuple(c for c in args.cases.split(",") if c)
    unknown = sorted(set(cases) - set(CASES))
    if unknown:
        parser.error(f"unknown cases {unknown}")
    try:
        summary = verify(args.evidence_dir, args.ledger, args.receipts_dir, args.claims, cases,
                         args.require_recovery_claims, args.max_wall_seconds, args.max_turns)
    except InputError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.emit_recovery:
        with args.emit_recovery.open("x", encoding="utf-8") as out:
            for row in recovery_rows(summary):
                out.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
