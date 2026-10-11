"""R9 observation-leak verifier over a private audit JSONL (and optionally the harness ledger).

    python3 probes/R9-observation/r9_verify.py AUDIT.jsonl [--ledger LEDGER.jsonl] [--min-turns 200]

Each audit record holds the exact outbound request string captured at a CTA and an oracle
built on the game thread through different enumeration paths. Coverage counts are derived
from oracle rows here, never from counters reported by the mod. Exit 0 only when every
check passes, every required case occurred at least once and enough distinct advancing
world turns were audited. Standard library plus harness.wire.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness import wire  # noqa: E402

REQUIRED_CASES = ("unidentified_item", "nonvisible_creature", "nonscanned_visible_creature")
NUMERIC_HP = re.compile(r"\d+\s*/\s*\d+")
MARKUP = re.compile(r"\{\{[^|{}]*\||\}\}|&[A-Za-z]|\^[A-Za-z]")


def plain(text):
    return MARKUP.sub("", text or "").strip().lower()


def public_text(obs):
    """Observation text that could carry names: everything but the digest and map glyphs."""
    rest = {k: v for k, v in obs.items() if k not in ("digest", "map")}
    return plain(json.dumps(rest, ensure_ascii=False))


def load_jsonl(path):
    rows = []
    for index, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines()):
        if line.strip():
            try:
                rows.append(wire.loads_strict(line))
            except wire.WireError as exc:
                raise SystemExit(f"{path}:{index}: {exc}") from None
    return rows


def ledger_requests(path):
    return {row["seq"]: row["body"] for row in load_jsonl(path) if row.get("kind") == "request"}


def _check_record(i, rec, prev, fail):
    request = rec["request"]
    if hashlib.sha256(request.encode("utf-8")).hexdigest() != rec["request_sha256"]:
        fail(i, "request_sha256 does not match captured request text")
    try:
        message = wire.parse_game_frame(request)
    except wire.WireError as exc:
        fail(i, f"request violates wire contract: {exc}")
        return None
    if message["seq"] != rec["header"]["seq"]:
        fail(i, "header seq differs from request seq")
    obs, oracle = message["observation"], rec["oracle"]

    ov = oracle["vitals"]
    for key in wire.VITALS_KEYS:
        if obs["vitals"][key] != ov[key]:
            fail(i, f"vitals.{key} {obs['vitals'][key]!r} != oracle {ov[key]!r}")

    entities = oracle["entities"]
    visible = [e for e in entities if e["visible"]]
    hidden = [e for e in entities if not e["visible"]]
    expected = Counter((e["x"], e["y"], e["shown"], e["wound"], e["hostile"]) for e in visible)
    actual = Counter((t["x"], t["y"], t["name"], t["wound"], t["hostile"]) for t in obs["threats"])
    if expected != actual:
        fail(i, f"threats differ from visible oracle (missing={list(expected - actual)[:3]}, "
                f"unexpected={list(actual - expected)[:3]})")
    visible_pos = {(e["x"], e["y"]) for e in visible}
    visible_names = {e["shown"] for e in visible}
    for e in hidden:
        for t in obs["threats"]:
            if (t["x"], t["y"]) == (e["x"], e["y"]) and (e["x"], e["y"]) not in visible_pos:
                fail(i, f"hidden entity leaked at ({e['x']},{e['y']})")
            if t["name"] == e["shown"] and e["shown"] not in visible_names:
                fail(i, f"hidden entity name leaked: {e['shown']!r}")
    by_pos = {}
    for e in visible:
        by_pos.setdefault((e["x"], e["y"]), []).append(e)
    for t in obs["threats"]:
        if NUMERIC_HP.search(t["wound"]):
            owners = [e for e in by_pos.get((t["x"], t["y"]), []) if e["shown"] == t["name"]]
            if not owners or not all(e["scanned"] for e in owners):
                fail(i, f"numeric HP shown without Scanning for {t['name']!r}")
    for e in visible:
        if not e["scanned"] and e["hp"] is not None and e["max_hp"] is not None:
            pattern = re.compile(rf"(?<!\d){e['hp']}\s*/\s*{e['max_hp']}(?!\d)")
            for t in obs["threats"]:
                if (t["x"], t["y"]) == (e["x"], e["y"]) and pattern.search(t["wound"]):
                    fail(i, f"non-scanned creature HP {e['hp']}/{e['max_hp']} leaked")

    text = public_text(obs)
    unknown = [k for k in oracle["kit"] if not k["understood"] and plain(k["true_name"]) != plain(k["shown"])]
    unknown += [e for e in visible if plain(e["true_name"]) != plain(e["shown"])]
    for item in unknown:
        true = plain(item["true_name"])
        if true and true not in plain(item["shown"]) and true in text:
            fail(i, f"true name leaked: {item['true_name']!r}")

    if "kit" in obs:
        if len(oracle["kit"]) <= wire.KIT_MAX:
            exp = Counter((k["shown"], k["slot"]) for k in oracle["kit"])
            act = Counter((k["name"], k["slot"]) for k in obs["kit"])
            if exp != act:
                fail(i, f"kit differs (missing={list(exp - act)[:3]}, unexpected={list(act - exp)[:3]})")
    if "place" in obs:
        p = obs["place"]
        if (p["name"], p["world_map"], p["lost"]) != (oracle["zone_name"], oracle["world_map"], oracle["lost"]):
            fail(i, "place differs from oracle")
    if "status" in obs:
        exp_effects = [e["description"] for e in oracle["effects"] if e["description"]][:32]
        if obs["status"]["effects"] != exp_effects:
            fail(i, "status.effects differ from oracle")

    digest, tail, modal = obs["digest"], oracle["digest_log_tail"], set(oracle["modal_notices"])
    if len(digest) > wire.DIGEST_MAX:
        fail(i, "digest over limit")
    filtered = [d for d in digest if d not in modal]
    if filtered and filtered != tail[-len(filtered):]:
        fail(i, "digest order/content differs from message log tail")
    if not modal and (digest != tail or len(digest) != min(wire.DIGEST_MAX, oracle["digest_log_since_arm"])):
        fail(i, "digest is not the last message log entries")

    if prev is not None and obs["map_frame"] <= prev["map_frame"]:
        fail(i, f"stale map: map_frame {obs['map_frame']} did not advance")
    if rec["renders_after"] <= rec["renders_before"]:
        fail(i, "stale map: no AfterRender between capture points")
    return obs


def verify(records, ledger=None, min_turns=200):
    failures = []

    def fail(i, msg):
        failures.append(f"record {i}: {msg}")

    cases = dict.fromkeys(REQUIRED_CASES, 0)
    turns, max_turn, prev, run_ids, seqs = 0, None, None, set(), set()
    for i, rec in enumerate(records):
        if rec.get("kind") != "r9_audit":
            fail(i, "not an r9_audit record")
            continue
        run_ids.add(rec["header"]["run_id"])
        seq = rec["header"]["seq"]
        if seq in seqs:
            fail(i, f"duplicate seq {seq}")
        seqs.add(seq)
        if ledger is not None:
            body = ledger.get(seq)
            if body is None:
                fail(i, f"seq {seq} missing from ledger")
            elif body["frame_sha256"] != rec["request_sha256"]:
                fail(i, f"seq {seq} ledger frame_sha256 differs from audited request")
        obs = _check_record(i, rec, prev, fail)
        if obs is None:
            continue
        prev = obs
        oracle = rec["oracle"]
        turn = oracle["vitals"]["turn"]
        if max_turn is None or turn > max_turn:
            if max_turn is not None:
                turns += 1
            max_turn = turn
        ents = oracle["entities"]
        if any(not k["understood"] and plain(k["true_name"]) != plain(k["shown"]) for k in oracle["kit"]):
            cases["unidentified_item"] += 1
        if any(not e["visible"] for e in ents):
            cases["nonvisible_creature"] += 1
        if any(e["visible"] and not e["scanned"] for e in ents):
            cases["nonscanned_visible_creature"] += 1
    if len(run_ids) > 1:
        failures.append("audit mixes run_ids")
    for name, count in cases.items():
        if count == 0:
            failures.append(f"required case absent: {name}")
    if turns < min_turns:
        failures.append(f"only {turns} distinct advancing world turns, {min_turns} required")
    return {"ok": not failures, "records": len(records), "advancing_turns": turns,
            "case_records": cases, "failures": failures[:50], "failure_count": len(failures)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audit", type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--min-turns", type=int, default=200)
    args = parser.parse_args(argv)
    if args.min_turns < 200:
        print("warning: --min-turns below 200 cannot establish R9", file=sys.stderr)
    ledger = ledger_requests(args.ledger) if args.ledger else None
    summary = verify(load_jsonl(args.audit), ledger, args.min_turns)
    summary["r9_claimable"] = summary["ok"] and args.min_turns >= 200 and ledger is not None
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
