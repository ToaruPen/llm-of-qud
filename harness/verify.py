"""Verify a harness ledger: hash chain plus request -> decision -> result order and links.

    python -m harness.verify PATH [--require-completed N] [--m1]

A valid chain proves only that the ledger is internally consistent. It is not an M1
claim; ``--m1`` adds the acceptance checks (a completed executed action, zero
EndPlayerTurn / PlayerTurn entries in every recorded telemetry, next request present).
A trailing request (awaiting a decision) or a trailing decision (awaiting its result)
is allowed and reported as ``pending``.

A ``recovery`` row (the game reloaded a save/checkpoint) interrupts the current request
and its decision, if any, without a result; the next action row must be the request for
seq+1. A ``game_fault`` row is terminal: no row may follow it. Both bodies link to the
current request (``request_hash``) and to its decision (``decision_hash``, null when none
was accepted). A ``suspended`` row (the game stopped running, e.g. it exited to the main
menu) voids the current request before its result, at most once, with the same links; after
it only modal rows and the recovery or game_fault of that seq may follow. Ledgers without
these rows verify exactly as before.
"""

import argparse
import json
import sys
from pathlib import Path

from harness import modal_wire, wire
from harness.modal_verify import ModalVerifier
from harness.ledger import GENESIS_HASH, ROW_FIELDS, canonical_bytes, row_hash

KINDS = ("request", "decision", "result")
LIFECYCLE_KINDS = ("recovery", "game_fault", "suspended")
ZERO_COUNTERS = ("end_player_turns", "player_turn_entries")


class VerifyError(Exception):
    pass


def _check_lifecycle_body(kind, body):
    if kind == "recovery":
        wire._exact_keys(body, wire.RECOVERY_BODY_KEYS, "recovery body")
        wire.validate_recovery_fields(body)
    elif kind == "suspended":
        wire._exact_keys(body, wire.SUSPENDED_BODY_KEYS, "suspended body")
        wire.validate_suspended_reason(body["reason"])
    else:
        wire._exact_keys(body, wire.GAME_FAULT_BODY_KEYS, "game_fault body")
        wire.validate_game_fault_reason(body["reason"])
    wire.sha256_hex(body["frame_sha256"], f"{kind} frame_sha256")


def _check_body(index, kind, body):
    try:
        if kind == "request":
            wire._exact_keys(body, wire.REQUEST_BODY_KEYS, "request body")
            wire.validate_observation(body["observation"])
            wire.validate_telemetry(body["telemetry"])
        elif kind == "decision":
            extra = {"target"} if body.get("action") == "goto" else {"until"} if body.get("action") == "rest" else set()
            if body.get("action") in wire.ITEM_ACTIONS:
                extra = {"item"}
            if body.get("action") in wire.GROWTH_ACTIONS:
                extra = {"skill" if body["action"] == "learn_skill" else "attribute"}
            if "rationale" in body:
                extra.add("rationale")
                wire._require(body["rationale"] is not None, "recorded rationale must contain text")
                wire.validate_rationale(body["rationale"])
            wire._exact_keys(body, wire.DECISION_BODY_KEYS | extra, "decision body")
            wire.validate_wire_decision(body["action"], body["dir"], body["budget"], body.get("target"), body.get("until"),
                                        body.get("item"), body.get("skill"), body.get("attribute"))
        else:
            wire._exact_keys(body, wire.RESULT_BODY_KEYS, "result body")
            wire.validate_result_fields(body)
            wire.validate_observation(body["observation"])
            wire.validate_telemetry(body["telemetry"])
    except wire.WireError as exc:
        raise VerifyError(f"row {index}: {exc}") from None


def _parse_rows(path):
    data = Path(path).read_bytes()
    if data and not data.endswith(b"\n"):
        raise VerifyError("ledger ends with a truncated line")
    rows = []
    for index, line in enumerate(data.split(b"\n")[:-1] if data else []):
        try:
            row = wire.loads_strict(line.decode("utf-8"))
        except (UnicodeDecodeError, wire.WireError) as exc:
            raise VerifyError(f"row {index}: invalid JSON ({exc})") from None
        if not isinstance(row, dict) or set(row) != set(ROW_FIELDS):
            raise VerifyError(f"row {index}: fields must be exactly {list(ROW_FIELDS)}")
        if canonical_bytes(row) != line:
            raise VerifyError(f"row {index}: line is not in canonical form")
        rows.append(row)
    return rows


def verify_ledger(path, require_completed=0, m1=False):
    rows = _parse_rows(path)
    prev_hash = GENESIS_HASH
    run_id = None
    expect = "request"
    expected_seq = 1
    request_row = decision_row = None
    completed = 0
    executed_seqs = []
    request_seqs = set()
    modals = ModalVerifier()
    telemetry_max = dict.fromkeys(wire.TELEMETRY_COUNTERS, 0)
    stray_keys = None
    stray_complete = True
    recovery_ids = set()
    recoveries = interrupted_decisions = lost_turns = 0
    recovering_seq = None
    suspended_seq = None
    suspensions = 0
    game_fault = None

    for index, row in enumerate(rows):
        if type(row["index"]) is not int or row["index"] != index:
            raise VerifyError(f"row {index}: index is {row['index']!r}")
        if row["prev_hash"] != prev_hash:
            raise VerifyError(f"row {index}: prev_hash does not match previous row hash")
        unhashed = {key: value for key, value in row.items() if key != "hash"}
        if row_hash(unhashed) != row["hash"]:
            raise VerifyError(f"row {index}: hash mismatch (row was modified)")
        prev_hash = row["hash"]

        if run_id is None:
            try:
                run_id = wire._run_id(row["run_id"])
            except wire.WireError as exc:
                raise VerifyError(f"row {index}: {exc}") from None
        elif row["run_id"] != run_id:
            raise VerifyError(f"row {index}: run_id changed within the ledger")
        if game_fault is not None:
            raise VerifyError(f"row {index}: row after the terminal game_fault of seq {game_fault['seq']}")

        kind, seq, body = row["kind"], row["seq"], row["body"]
        if isinstance(kind, str) and kind in modal_wire.GAME_KINDS | {"modal_answer"}:
            try:
                modals.check(row, request_seqs)
            except wire.WireError as exc:
                raise VerifyError(f"row {index}: {exc}") from None
            continue
        if isinstance(kind, str) and kind in LIFECYCLE_KINDS:
            try:
                _check_lifecycle_body(kind, body)
            except wire.WireError as exc:
                raise VerifyError(f"row {index}: {exc}") from None
            current = request_row["seq"] if request_row is not None else None
            if type(seq) is not int or current is None or seq != current:
                raise VerifyError(f"row {index}: {kind} seq {seq!r} is not the current request "
                                  f"seq {current}")
            if body["request_hash"] != request_row["hash"]:
                raise VerifyError(f"row {index}: {kind} request_hash does not link to request seq {seq}")
            expected_decision = decision_row["hash"] if decision_row is not None else None
            if body["decision_hash"] != expected_decision:
                raise VerifyError(f"row {index}: {kind} decision_hash does not link to the decision "
                                  f"of seq {seq} (null when none was accepted)")
            if kind == "game_fault":
                game_fault = {"seq": seq, "reason": body["reason"]}
                continue
            if kind == "suspended":
                if expect not in ("decision", "result") or suspended_seq is not None:
                    raise VerifyError(f"row {index}: suspended must void request seq {seq} "
                                      "before its result and only once")
                suspended_seq = seq
                suspensions += 1
                continue
            if expect not in ("decision", "result"):
                raise VerifyError(f"row {index}: recovery must interrupt request seq {seq} "
                                  "before its result and only once")
            recovery_id = wire.canonical_uuid(body["recovery_id"])
            if recovery_id in recovery_ids:
                raise VerifyError(f"row {index}: recovery_id {recovery_id} is reused")
            recovery_ids.add(recovery_id)
            recoveries += 1
            interrupted_decisions += decision_row is not None
            lost_turns += body["lost_turns"]
            modals.interrupt(seq)
            recovering_seq = seq
            suspended_seq = None
            expect = "request"
            expected_seq = seq + 1
            continue
        if kind not in KINDS:
            raise VerifyError(f"row {index}: unknown kind {kind!r}")
        if suspended_seq is not None:
            raise VerifyError(f"row {index}: {kind} after request seq {suspended_seq} was suspended; "
                              "only modal rows, its recovery or a game_fault may follow")
        if kind != expect:
            raise VerifyError(f"row {index}: expected {expect} for seq {expected_seq}, found {kind}")
        if type(seq) is not int or seq != expected_seq:
            raise VerifyError(f"row {index}: expected seq {expected_seq}, found {seq!r}")
        _check_body(index, kind, body)
        if kind in ("request", "result"):
            count = body["telemetry"].get("stray_keys")
            if count is None:
                stray_complete = False
            else:
                if stray_keys is not None and count < stray_keys:
                    raise VerifyError(f"row {index}: stray_keys decreased")
                stray_keys = count

        if kind == "request":
            request_row = row
            decision_row = None
            recovering_seq = None
            request_seqs.add(seq)
            expect = "decision"
        elif kind == "decision":
            if body["request_hash"] != request_row["hash"]:
                raise VerifyError(f"row {index}: request_hash does not link to request seq {seq}")
            try:
                wire.validate_observed_item(body["action"], body.get("item"), request_row["body"]["observation"])
                wire.validate_observed_growth(body["action"], body.get("skill"), body.get("attribute"),
                                               request_row["body"]["observation"])
            except wire.WireError as exc:
                raise VerifyError(f"row {index}: {exc}") from None
            decision_row = row
            expect = "result"
        else:
            if body["decision_hash"] != decision_row["hash"]:
                raise VerifyError(f"row {index}: decision_hash does not link to decision seq {seq}")
            if body["action"] != decision_row["body"]["action"]:
                raise VerifyError(f"row {index}: result action differs from decision action")
            completed += 1
            if body["executed"]:
                executed_seqs.append(seq)
            expect = "request"
            expected_seq = seq + 1

        if kind in ("request", "result"):
            for key in wire.TELEMETRY_COUNTERS:
                telemetry_max[key] = max(telemetry_max[key], body["telemetry"][key])

    pending = None
    if game_fault is not None:
        recovering_seq = suspended_seq = None  # terminal: nothing is pending or being recovered
    # A suspended request is void (the game stopped running), not awaiting a decision.
    elif suspended_seq is None and expect == "decision":
        pending = "request"
    elif suspended_seq is None and expect == "result":
        pending = "decision"

    if completed < require_completed:
        raise VerifyError(f"{completed} completed actions, {require_completed} required")

    summary = {
        "ok": True,
        "rows": len(rows),
        "run_id": run_id,
        "completed": completed,
        "pending": pending,
        "pending_seq": expected_seq if pending else None,
        "head_hash": prev_hash,
        "telemetry_max": telemetry_max,
        "recoveries": recoveries,
        "interrupted_decisions": interrupted_decisions,
        "lost_turns": lost_turns,
        "recovering_seq": recovering_seq,
        "suspensions": suspensions,
        "suspended_seq": suspended_seq,
        "game_fault": game_fault,
        "external_answers": modals.external_answers,
        "modal_watchdogs": modals.watchdogs,
        "stray_keys": stray_keys if stray_complete else None,
        "m1": None,
    }
    if m1:
        nonzero = [key for key in ZERO_COUNTERS if telemetry_max[key] != 0]
        if nonzero:
            raise VerifyError(f"M1 not met: telemetry counters not zero: {nonzero}")
        candidates = [seq for seq in executed_seqs if seq + 1 in request_seqs]
        if not candidates:
            raise VerifyError("M1 not met: no executed action followed by the next request")
        summary["m1"] = True
        summary["m1_seq"] = candidates[0]
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m harness.verify", description=__doc__.splitlines()[0])
    parser.add_argument("path", type=Path)
    parser.add_argument("--require-completed", type=int, default=0, metavar="N")
    parser.add_argument("--m1", action="store_true", help="also apply the M1 acceptance checks")
    args = parser.parse_args(argv)
    try:
        summary = verify_ledger(args.path, args.require_completed, args.m1)
    except (VerifyError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
