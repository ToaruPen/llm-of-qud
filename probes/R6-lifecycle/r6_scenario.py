"""Synthetic R6 scenarios for verifier tests (not runtime evidence).

Builds probe evidence in the exact on-disk format of ``mod/LifecycleProbe.cs`` and real harness
ledgers through ``harness.ledger.Ledger`` / ``harness.wire``. The golden scenario walks all five
R6 cases; tests mutate the returned record handles to produce each failure.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import r6_evidence as ev
import r6_verify as rv
from harness import wire
from harness.ledger import Ledger

GAME_ID = "5f0e2a4c-9a1b-4d7e-8c33-0123456789ab"
ZONE = "JoppaWorld.11.22.1.1.10"
PROFILE = "/tmp/r6-profile"


def sha(label):
    return ev.sha256_hex(label.encode())


class Scenario:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.evidence = self.root / "evidence"
        self.ledgers = self.root / "ledgers"
        self.receipts = self.root / "receipts"
        for path in (self.evidence, self.ledgers, self.receipts):
            path.mkdir(parents=True)
        self.clock = datetime(2026, 9, 27, 12, 0, 0, tzinfo=timezone.utc)
        self.sessions = []
        self.game = {"game_id": GAME_ID, "turns": 10, "mode": "Roleplay", "running": True,
                     "zone": ZONE, "x": 37, "y": 22, "hp": 18, "checkpointing": True}
        self.files = {}
        self.own = dict(rv.OWN_EXPECTED)
        self.prod = dict(rv.PRODUCTION_EXPECTED)
        self.production = {"state": 0, "run_id": None, "seq": 0, "pending_seq": None, "ctas": 0}
        self.bridge_live = 0
        self.ledger = None
        self.ledger_paths = []
        self.request_row = self.decision_row = None
        self.map_frame = 0
        self.marks = {}
        self.claims = []

    # ---------------------------------------------------------------- records
    def utc(self):
        self.clock += timedelta(seconds=1)
        return self.clock.strftime("%Y-%m-%dT%H:%M:%S.") + f"{self.clock.microsecond // 1000:03d}Z"

    @property
    def session(self):
        return self.sessions[-1]

    def rec(self, kind, thread="game", **fields):
        session = self.session
        record = {"v": 1, "session": session["id"], "n": len(session["records"]), "prev": None,
                  "utc": self.utc(), "kind": kind, "thread": thread, "epoch": session["epoch"],
                  "boundary": session["boundary"]}
        record.update(fields)
        session["records"].append(record)
        return record

    def callbacks(self):
        return {"own": dict(self.own), "production": dict(self.prod),
                "total": {k: self.own[k] + self.prod[k] for k in rv.LIST_KEYS},
                "production_methods": {"begin": ["OnBeginTurn"], "end": ["OnEndTurn"],
                                       "after_render": ["AfterRender"], "message": ["OnMessage"]},
                "production_assemblies": ["LlmOfQudM1"], "error": None}

    def prod_state(self):
        p = self.production
        return {"present": True, "types": 1, "state": p["state"], "run_id": p["run_id"], "seq": p["seq"],
                "ctas": p["ctas"], "pending_seq": p["pending_seq"], "bridge_set": self.bridge_live > 0,
                "fatal": False, "missing": [], "turn_system": True}

    def snapshot(self):
        return dict(self.game)

    # ---------------------------------------------------------------- lifecycle
    def start_session(self, pid):
        self.sessions.append({"id": str(uuid.uuid4()), "pid": pid, "records": [], "epoch": 1, "boundary": 1})
        self.production = {"state": 0, "run_id": None, "seq": 0, "pending_seq": None, "ctas": 0}
        self.bridge_live = 0
        self.first_marked = False
        argv = ["/Games/CoQ.app/Contents/MacOS/CoQ", "-savepath", PROFILE,
                "-sharedpath", PROFILE + "/Local", "-syncedpath", PROFILE + "/Synced"]
        return self.rec("init", thread="ui", reason="process_start", pid=pid, argv=argv,
                        process_start_utc=None, savepath=PROFILE, optin_nonce="n" * 32,
                        game_version="2.0.211.56", sentinel_reset=True, lists_replaced=None,
                        frames=["XRL.ModManager::Init"], hotload_frame=False, wish_frame=False,
                        registration=dict.fromkeys(("begin", "end", "after_render", "message"), "added"),
                        callbacks=self.callbacks(), bridge_live=None, production=self.prod_state(), game=None)

    def load(self, file, turns):
        self.game["turns"] = turns
        self.session["boundary"] += 1
        self.first_marked = False
        self.cta_index = 0
        candidates = {name: {"sha256": value[0], "size": 1000, "mtime_utc": "2026-09-27T12:00:00.000Z",
                             "json_turn": value[1]} for name, value in self.files.items()}
        matching = [name for name, value in self.files.items() if value[1] == turns]
        return self.rec("game_loaded", thread="worker", game=self.snapshot(), candidates=candidates,
                        loaded_file=file, matching_files=matching, loaded_file_basis="json_turn_unique",
                        callbacks=self.callbacks(), bridge_live=self.bridge_live,
                        production=self.prod_state(), frames=[])

    def save(self, file, digest, turns, baseline=False):
        self.files[file] = (digest, turns)
        return self.rec("save_observed", thread="watcher", game_id=GAME_ID, file=file, sha256=digest,
                        size=1000, mtime_utc="2026-09-27T12:00:00.000Z", json_turn=turns, baseline=baseline)

    def heartbeat(self):
        return self.rec("heartbeat", thread="ui", game=self.snapshot(), callbacks=self.callbacks(),
                        bridge_live=self.bridge_live, production=self.prod_state(), view="Stage")

    # ---------------------------------------------------------------- production + ledger
    def arm(self):
        run_id = str(uuid.uuid4())
        path = self.ledgers / f"{len(self.ledger_paths)}-{run_id}.jsonl"
        if self.ledger is not None:
            self.ledger.close()
        self.ledger = Ledger.create(path)
        self.ledger_paths.append(path)
        self.production.update(state=1, run_id=run_id, seq=0, pending_seq=None)
        self.bridge_live = 1
        return run_id

    def observation(self):
        self.map_frame += 1
        return {"vitals": {"hp": self.game["hp"], "max_hp": 18, "x": self.game["x"], "y": self.game["y"],
                           "turn": self.game["turns"], "energy": 1000, "zone": self.game["zone"]},
                "threats": [], "digest": [], "map": [" " * 80] * 25, "map_frame": self.map_frame}

    def telemetry(self):
        return {"cta": self.production["ctas"], "end_player_turns": 0, "player_turn_entries": 0,
                "ui_tasks": 0, "unknown_tasks": 0, "game_queue": []}

    def cta(self):
        p = self.production
        p["state"] = 2
        p["ctas"] += 1
        first = not self.first_marked
        self.first_marked = True
        record = self.rec("cta_begin", source="production_cta", first_after_boundary=first,
                          index_in_boundary=self.cta_index, game=self.snapshot(), callbacks=self.callbacks(),
                          bridge_live=self.bridge_live, production=self.prod_state())
        self.cta_index += 1
        run_id = p["run_id"]
        if p["pending_seq"] is not None:
            seq = p["pending_seq"]
            message = {"kind": "result", "run_id": run_id, "seq": seq, "action": "wait", "executed": True,
                       "reason": "executed", "observation": self.observation(), "telemetry": self.telemetry(),
                       "energy_before": 1000, "energy_after": 0, "turns_elapsed": 1, "steps": 1}
            frame = json.dumps(message)
            self.ledger.append("result", seq, run_id, wire.result_body(message, frame, self.decision_row["hash"]))
            p["pending_seq"] = None
        p["seq"] += 1
        message = {"kind": "request", "run_id": run_id, "seq": p["seq"], "observation": self.observation(),
                   "telemetry": self.telemetry()}
        self.request_row = self.ledger.append("request", p["seq"], run_id,
                                              wire.request_body(message, json.dumps(message)))
        return record

    def decide(self, turns=1):
        p = self.production
        self.decision_row = self.ledger.append("decision", p["seq"], p["run_id"],
                                               wire.decision_body(self.request_row["hash"], "wait", None, 1))
        p["pending_seq"] = p["seq"]
        self.game["turns"] += turns

    def modal_auto_death(self):
        p = self.production
        modal = {"type": "popup", "title": "", "text": "You died.", "input_kind": "none", "constraints": {},
                 "choices": [{"id": "option:0", "label": rv.RELOAD_LABEL},
                             {"id": "option:1", "label": "View final messages"},
                             {"id": "option:2", "label": "Retire character"},
                             {"id": "option:3", "label": "Quit to main menu"}]}
        body = {"token": "death-1", "rule": rv.DEATH_RULE, "modal": modal, "accepted": True, "reason": "rule",
                "frame_sha256": "a" * 64}
        self.ledger.append("modal_auto", p["seq"], p["run_id"], body)

    # ---------------------------------------------------------------- fixtures
    def accept(self, kind, **params):
        fixture_id = str(uuid.uuid4())
        self.rec("fixture_accepted", fixture_id=fixture_id, fixture=kind, params=params, source="production_cta")
        return fixture_id

    def fixture_begin(self, fixture_id, kind):
        return self.rec("fixture_begin", fixture_id=fixture_id, fixture=kind, game=self.snapshot(),
                        accepted_session=self.session["id"], accepted_game_id=GAME_ID)

    def fixture_done(self, fixture_id, kind, **result):
        return self.rec("fixture_done", fixture_id=fixture_id, fixture=kind, result=result)

    def hotload(self, fixture_id, **overrides):
        self.fixture_begin(fixture_id, "reload")
        self.session["epoch"] += 1
        self.session["boundary"] += 1
        self.first_marked = False
        self.cta_index = 0
        fields = dict(reason="reinit", pid=self.session["pid"], argv=[], process_start_utc=None,
                      savepath=PROFILE, optin_nonce="n" * 32, game_version="2.0.211.56",
                      sentinel_reset=True, lists_replaced=True,
                      frames=["XRL.Core.XRLCore::HotloadConfiguration",
                              "XRL.World.Capabilities.Wishing+<>c::<HandleWish>b__1_0"],
                      hotload_frame=True, wish_frame=True,
                      registration=dict.fromkeys(("begin", "end", "after_render", "message"), "added"),
                      callbacks=self.callbacks(), bridge_live=self.bridge_live,
                      production=self.prod_state(), game=self.snapshot())
        fields.update(overrides)
        init = self.rec("init", thread="ui", **fields)
        self.rec("message", text="Hotload complete.")
        self.fixture_done(fixture_id, "reload", epoch_before=self.session["epoch"] - 1,
                          epoch_after=self.session["epoch"])
        return init

    def death(self, fixture_id, answered_by_probe=True):
        begin = self.fixture_begin(fixture_id, "death")
        die = self.rec("die_path", fixture_id=fixture_id, game=self.snapshot(),
                       frames=["XRL.World.GameObject::Die", "LlmOfQud.ProbeR6.Probe::RunFixture"])
        labels = [rv.RELOAD_LABEL, "View final messages", "Retire character", "Quit to main menu"]
        self.rec("death_menu_seen", thread="ui", fixture_id=fixture_id, labels=labels, reload_index=0,
                 token=77, default_view_final=False)
        answer = None
        if answered_by_probe:
            answer = self.rec("death_menu_answered", thread="ui", fixture_id=fixture_id,
                              label=rv.RELOAD_LABEL, index=0, token=77)
        self.rec("death_menu_closed", thread="ui", fixture_id=fixture_id, token=77,
                 answered_by="probe" if answered_by_probe else "external")
        self.fixture_done(fixture_id, "death", die_returned=True, load_command_queued=True)
        return begin, die, answer

    def save_quit(self, fixture_id, digest):
        self.fixture_begin(fixture_id, "save_quit")
        self.save("Primary", digest, self.game["turns"])
        self.fixture_done(fixture_id, "save_quit", saved=True)

    # ---------------------------------------------------------------- receipts / output
    def receipt(self, name, **fields):
        path = self.receipts / f"{name}.json"
        path.write_text(json.dumps(fields, indent=2))
        return path

    def crash_receipt(self, **overrides):
        session = self.session
        last_turns = ev.last_game(session["records"])["turns"]
        self.clock += timedelta(seconds=1)
        kill = self.clock.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        fields = {"v": 1, "kind": "crash", "pid": session["pid"], "session": session["id"],
                  "signal": "SIGKILL", "dry_run": False, "kill_utc": kill, "gone_utc": kill,
                  "process_gone": True, "verified": {"profile": True, "argv": True, "heartbeat": True},
                  "last_probe_turn": last_turns, "game_id": GAME_ID,
                  "saves": {name: {"sha256": value[0], "json_turn": value[1]} for name, value in self.files.items()}}
        fields.update(overrides)
        return self.receipt("crash-" + session["id"], **fields)

    def exit_receipt(self, **overrides):
        session = self.session
        fields = {"v": 1, "kind": "exit", "pid": session["pid"], "session": session["id"], "graceful": True,
                  "signal": None, "process_gone": True, "game_id": GAME_ID,
                  "saves": {name: {"sha256": value[0], "json_turn": value[1]} for name, value in self.files.items()}}
        fields.update(overrides)
        return self.receipt("exit-" + session["id"], **fields)

    def write(self, claims=True):
        if self.ledger is not None:
            self.ledger.close()
            self.ledger = None
        for index, session in enumerate(self.sessions):
            prev = ev.GENESIS
            lines = []
            for n, record in enumerate(session["records"]):
                record["n"] = n
                record["prev"] = prev
                raw = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode()
                prev = ev.sha256_hex(raw)
                lines.append(raw)
            path = self.evidence / f"{index:02d}-{session['pid']}-{session['id'][:8]}.jsonl"
            path.write_bytes(b"\n".join(lines) + b"\n")
        claims_path = None
        if claims:
            claims_path = self.root / "claims.json"
            claims_path.write_text(json.dumps({"claims": self.claims}))
        return {"evidence_dir": self.evidence, "ledger_paths": list(self.ledger_paths),
                "receipts_dir": self.receipts, "claims_path": claims_path}


def golden(root, death_by_probe=True, lifecycle_recovery=False, recovery_overrides=None,
           checkpoint_advance=0):
    """All five cases, continuing runs inside a process and new runs after each process restart."""
    s = Scenario(root)
    s.start_session(4101)
    s.files = {"Primary": (sha("P0"), 10), "Checkpoint": (sha("C0"), 5)}
    s.load("Primary", 10)
    s.save("Primary", sha("P0"), 10, baseline=True)
    s.save("Checkpoint", sha("C0"), 5, baseline=True)
    s.arm()
    s.cta(); s.decide()
    s.cta(); f1 = s.accept("save_quit"); s.decide()
    s.save_quit(f1, sha("P1"))
    s.marks["menu_load"] = s.load("Primary", 12)
    s.marks["menu_cta"] = s.cta(); f2 = s.accept("reload"); s.decide()
    s.heartbeat()
    s.marks["hotload_init"] = s.hotload(f2)
    s.marks["hotload_cta"] = s.cta(); f3 = s.accept("death", death_answer="probe_label"); s.decide()
    if not death_by_probe:
        s.modal_auto_death()
    begin, die, answer = s.death(f3, answered_by_probe=death_by_probe)
    s.marks.update(death_begin=begin, die_path=die, death_answer=answer)
    death_turn = s.game["turns"]
    s.game["turns"] = 5
    s.marks["checkpoint_load"] = s.load("Checkpoint", 5)
    if lifecycle_recovery:
        p = s.production
        frame = {"kind":"recovery", "run_id":p["run_id"], "seq":p["seq"],
                 "recovery_id":str(uuid.uuid4()), "reason":"checkpoint_reload", "game_id":GAME_ID,
                 "save_file":"Checkpoint", "save_sha256":sha("C0"), "turn_before":death_turn,
                 "loaded_turn":5, "lost_turns":max(0, death_turn - 5)}
        frame.update(recovery_overrides or {})
        s.ledger.append("recovery", p["seq"], p["run_id"],
                        wire.recovery_body(frame, json.dumps(frame), s.request_row["hash"], s.decision_row["hash"]))
        p["pending_seq"] = None
    s.save("Primary", sha("C0"), 5)
    s.game["turns"] += checkpoint_advance
    s.marks["checkpoint_heartbeat"] = s.heartbeat()
    s.marks["checkpoint_cta"] = s.cta(); f4 = s.accept("save_quit"); s.decide()
    s.save_quit(f4, sha("P2"))
    s.marks["exit_receipt"] = s.exit_receipt()

    s.start_session(4102)
    s.marks["process_load"] = s.load("Primary", 6 + checkpoint_advance)
    s.save("Primary", sha("P2"), 6 + checkpoint_advance, baseline=True)
    s.save("Checkpoint", sha("C0"), 5, baseline=True)
    s.arm()
    s.marks["process_cta"] = s.cta(); f5 = s.accept("autosave"); s.decide()
    s.fixture_begin(f5, "autosave"); s.fixture_done(f5, "autosave", issued=True)
    s.save("Primary", sha("P3"), 7 + checkpoint_advance)
    s.cta(); s.decide()
    s.cta(); s.decide()
    s.cta()
    s.heartbeat()
    s.marks["crash_receipt"] = s.crash_receipt()

    s.start_session(4103)
    s.marks["crash_load"] = s.load("Primary", 7 + checkpoint_advance)
    s.arm()
    s.marks["crash_cta"] = s.cta(); s.decide()
    s.cta()
    s.claims = [{"case": "menu_reenter", "index": 0, "lost_turns": 0, "loaded_sha256": sha("P1"),
                 "game_id": GAME_ID},
                {"case": "hotload", "index": 0, "lost_turns": 0, "game_id": GAME_ID},
                {"case": "checkpoint_reload", "index": 0, "checkpoint_rewind_turns": 9,
                 "loaded_sha256": sha("C0"), "game_id": GAME_ID},
                {"case": "save_quit_load", "index": 0, "lost_turns": 0, "loaded_sha256": sha("P2"),
                 "game_id": GAME_ID},
                {"case": "crash_restart", "index": 0, "lost_turns": 2, "loaded_sha256": sha("P3"),
                 "game_id": GAME_ID}]
    return s
