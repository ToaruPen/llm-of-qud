"""Persistent, source-linked player notes and searchable public ledger projections.

The game ledger remains authoritative and unchanged. SQLite contains a rebuildable
source index, versioned player-authored notes, and retrieval/write audit records.
No game state is inferred from notes. A new run or recovery invalidates state claims.
Only one harness may own a memory directory at a time.
"""

import fcntl
import json
import os
import re
import sqlite3
import time
from pathlib import Path

from harness.ledger import GENESIS_HASH, canonical_bytes, row_hash

NOTE_KINDS = {"plan", "fact", "hypothesis", "lesson", "summary"}
MAX_TEXT = 6000
FOCUS_SECTIONS = ("plan", "hazards", "reconsider_when")


def _matching_text(text, words, limit):
    positions = [text.lower().find(word.lower()) for word in words]
    first = min((pos for pos in positions if pos >= 0), default=0)
    start = max(0, first - 60) if len(text) > limit else 0
    return ("…" if start else "") + text[start:start + limit] + ("…" if start + limit < len(text) else "")


def _excerpt(record, words):
    """Keep tactical context ahead of matching detail; never cut serialized JSON."""
    if "observation" not in record:
        return json.dumps({k: str(v)[:700] for k, v in record.items()}, ensure_ascii=False)[:6000]
    obs = record["observation"]
    selected = {"vitals": obs["vitals"], "threats": [], "digest": []}
    def relevance(value):
        text = json.dumps(value, ensure_ascii=False).lower()
        return sum(word.lower() in text for word in words)
    threats = sorted(obs.get("threats", []), key=lambda t: (relevance(t), t["hostile"]), reverse=True)
    selected["threats"] = [{**t, "name": t["name"][:180]} for t in threats[:4]]
    if "place" in obs:
        selected["place"] = {**obs["place"], "name": obs["place"]["name"][:180]}
    if "status" in obs:
        selected["status"] = str(obs["status"])[:250]
    digest = sorted(enumerate(obs.get("digest", [])), key=lambda p: (relevance(p[1]), p[0]), reverse=True)
    selected["digest"] = [text[:240] for _, text in digest[:3]]
    matching_items = [item for item in obs.get("kit", []) if relevance(item)]
    if matching_items:
        selected["kit"] = [{**item, "name": item["name"][:180]} for item in matching_items[:2]]
    matching_ground = [item for item in obs.get("ground", []) if relevance(item)]
    if matching_ground:
        selected["ground"] = [{**item, "name": _matching_text(item["name"], words, 180)}
                              for item in matching_ground[:2]]
    goals = obs.get("goals")
    if goals and relevance(goals["text"]):
        selected["goals"] = {"text": _matching_text(goals["text"], words, 600),
                             "truncated": goals["truncated"] or len(goals["text"]) > 600}
    result = {"observation": selected, **{k: v for k, v in record.items() if k != "observation"},
              "excerpt_only": True}
    return json.dumps(result, ensure_ascii=False)


def _public_record(row):
    body = row["body"]
    if row["kind"] in {"request", "result"}:
        observation = {k: v for k, v in body["observation"].items()
                       if k not in {"map", "map_frame"}}
        result = {"observation": observation}
        if row["kind"] == "result":
            result.update({k: body[k] for k in ("action", "executed", "reason", "turns_elapsed", "steps")})
        return result
    if row["kind"] == "decision":
        return {k: v for k, v in body.items() if k in {
            "action", "dir", "budget", "target", "until", "item", "rationale"}}
    if row["kind"] == "recovery":
        return {k: body[k] for k in ("reason", "turn_before", "loaded_turn", "lost_turns")}
    # Modal content is already visible to the player; internal audit links are not.
    return {k: v for k, v in body.items() if k not in {
        "frame_sha256", "request_hash", "decision_hash", "answer_hash", "telemetry",
        "save_sha256", "game_id", "save_file"}}


class MemoryStore:
    def __init__(self, directory, broker):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.broker = broker
        self.db = None
        self._lock = (self.directory / "writer.lock").open("a")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise ValueError("memory directory is already in use") from None
        self.cursors = {}
        try:
            path = self.directory / "memory.sqlite3"
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            self.db = sqlite3.connect(path)
            self.db.row_factory = sqlite3.Row
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS ledgers(path TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS records(
                    id TEXT PRIMARY KEY, ledger TEXT, row_index INTEGER, run_id TEXT,
                    seq INTEGER, epoch INTEGER, turn INTEGER, kind TEXT, record TEXT);
                CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS notes(
                    id INTEGER PRIMARY KEY, section TEXT, kind TEXT, text TEXT, sources TEXT,
                    run_id TEXT, epoch INTEGER, seq INTEGER, decisions INTEGER, created_at REAL);
                CREATE TABLE IF NOT EXISTS calls(
                    id INTEGER PRIMARY KEY, tool TEXT, request TEXT, response TEXT,
                    run_id TEXT, seq INTEGER, head_hash TEXT, duration_ms REAL, created_at REAL);
            """)
            self.db.execute("INSERT OR IGNORE INTO ledgers VALUES (?)",
                            (str(Path(broker.ledger.path).resolve()),))
            self.db.commit()
            self.sync()
        except Exception:
            self.close()
            raise

    def sync(self):
        """Import durable rows, including any unindexed tail of an earlier process."""
        cursors = dict(self.cursors)
        with self.db:
            for entry in self.db.execute("SELECT path FROM ledgers").fetchall():
                path = entry[0]
                offset, index, previous, epoch = cursors.get(path, (0, 0, GENESIS_HASH, 0))
                with open(path, "rb") as handle:
                    if os.fstat(handle.fileno()).st_size < offset:
                        raise ValueError("source ledger shrank")
                    handle.seek(offset)
                    for line in handle:
                        if not line.endswith(b"\n"):
                            raise ValueError("source ledger has a truncated row")
                        row = json.loads(line)
                        unhashed = {k: v for k, v in row.items() if k != "hash"}
                        if (row["index"] != index or row["prev_hash"] != previous
                                or row_hash(unhashed) != row["hash"]
                                or canonical_bytes(row) + b"\n" != line):
                            raise ValueError("source ledger hash chain mismatch")
                        if row["kind"] == "recovery":
                            epoch += 1
                        record = _public_record(row)
                        encoded = json.dumps(record, ensure_ascii=False)
                        turn = record.get("observation", {}).get("vitals", {}).get("turn")
                        inserted = self.db.execute(
                            "INSERT OR IGNORE INTO records VALUES (?,?,?,?,?,?,?,?,?)",
                            (row["hash"], path, index, row["run_id"], row["seq"], epoch,
                             turn, row["kind"], encoded)).rowcount
                        if inserted:
                            self.db.execute("INSERT INTO search_index VALUES (?,?)", (row["hash"], encoded))
                        index, previous = index + 1, row["hash"]
                    cursors[path] = (handle.tell(), index, previous, epoch)
        self.cursors = cursors

    def _epoch(self):
        return self.cursors[str(Path(self.broker.ledger.path).resolve())][3]

    def _current_source(self):
        state = self.broker.get_state()
        if not state.get("ok") or "modal" in state:
            return None
        row = self.db.execute("SELECT id FROM records WHERE run_id=? AND seq=? AND kind='request'",
                              (self.broker.run_id, state["seq"])).fetchone()
        return row[0] if row else None

    def _decisions(self):
        return self.db.execute("SELECT count(*) FROM records WHERE run_id=? AND kind='decision'",
                               (self.broker.run_id,)).fetchone()[0]

    def _lifecycle(self):
        """Game evidence survives even when a player summary mislabels a death."""
        deaths, recoveries = {}, []
        for row in self.db.execute("SELECT * FROM records WHERE kind IN ('recovery','modal_auto') ORDER BY rowid"):
            record = json.loads(row["record"])
            source = {"source_id": row["id"], "run_id": row["run_id"], "seq": row["seq"]}
            if row["kind"] == "recovery":
                recoveries.append({**source, **record})
            elif record.get("rule") == "death_reload_checkpoint":
                # More than one UI notice for a single interrupted seq is one death.
                deaths[(row["run_id"], row["seq"])] = {**source, "text": record["modal"]["text"]}
        return {"scope": "campaign", "death_count": len(deaths),
                "recovery_count": len(recoveries),
                "lost_turns": sum(row["lost_turns"] for row in recoveries),
                "recent_deaths": list(deaths.values())[-5:],
                "recent_recoveries": recoveries[-5:]}

    def _audit_call(self, tool, request, response, started):
        self.db.execute("INSERT INTO calls VALUES (NULL,?,?,?,?,?,?,?,?)", (
            tool, json.dumps(request), json.dumps(response, ensure_ascii=False),
            self.broker.run_id, self.broker.seq, self.broker.ledger.head_hash,
            (time.monotonic() - started) * 1000, time.time()))

    def _call(self, tool, request, operation):
        started = time.monotonic()
        try:
            self.sync()
            # Note changes and their audit commit together, or neither is saved.
            with self.db:
                response = operation()
                self._audit_call(tool, request, response, started)
            return response
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            response = {"ok": False, "status": "memory_error", "reason": str(exc)}
        try:
            with self.db:
                self._audit_call(tool, request, response, started)
        except sqlite3.Error:
            return {"ok": False, "status": "memory_error", "reason": "cannot persist memory call audit"}
        return response

    def status(self):
        def read_status():
            notes = {}
            rows = self.db.execute("SELECT * FROM notes WHERE id IN (SELECT max(id) FROM notes GROUP BY section)")
            for row in rows:
                note = dict(row)
                note["sources"] = json.loads(note["sources"])
                same = note["run_id"] == self.broker.run_id and note["epoch"] == self._epoch()
                note["same_timeline"] = same
                note["validity"] = "player_report" if same else "needs_revalidation"
                notes[note["section"]] = note
            summary = self.db.execute(
                "SELECT decisions FROM notes WHERE kind='summary' AND run_id=? ORDER BY id DESC LIMIT 1",
                (self.broker.run_id,)).fetchone()
            decisions = self._decisions()
            return {"ok": True, "run_id": self.broker.run_id, "epoch": self._epoch(),
                    "current_source": self._current_source(), "notes": notes,
                    "focus": {key: notes[key] for key in FOCUS_SECTIONS if key in notes},
                    "lifecycle": self._lifecycle(),
                    "decisions_since_summary": decisions - (summary[0] if summary else 0),
                    "episode_due": decisions - (summary[0] if summary else 0) >= 10,
                    "warning": "Notes are player reports, not game state. Lifecycle counts come from game evidence and override contradictory notes; reload alone does not imply death. Recheck inventory, position and quests in get_state; old item and modal IDs expire."}
        return self._call("status", {}, read_status)

    def write(self, expect_seq, section, kind, text, sources):
        request = dict(expect_seq=expect_seq, section=section, kind=kind, text=text, sources=sources)
        def write_note():
            current = self._current_source()
            if current is None or type(expect_seq) is not int or expect_seq != self.broker.seq:
                return {"ok": False, "status": "stale", "reason": "write requires a live current seq"}
            if (not isinstance(section, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", section)
                    or kind not in NOTE_KINDS or not isinstance(text, str)
                    or not text.strip() or len(text) > MAX_TEXT
                    or not isinstance(sources, list) or not 1 <= len(sources) <= 20
                    or any(not isinstance(source, str) for source in sources)):
                return {"ok": False, "status": "invalid", "reason": "invalid note or source list"}
            evidence = [self.db.execute("SELECT run_id, epoch FROM records WHERE id=?", (source,)).fetchone()
                        for source in sources]
            if any(row is None for row in evidence):
                return {"ok": False, "status": "invalid", "reason": "unknown evidence source"}
            if kind == "fact" and (current not in sources or any(
                    row["run_id"] != self.broker.run_id or row["epoch"] != self._epoch() for row in evidence)):
                return {"ok": False, "status": "invalid", "reason": "current facts require current observation and same-timeline sources"}
            cursor = self.db.execute("INSERT INTO notes VALUES (NULL,?,?,?,?,?,?,?,?,?)", (
                section, kind, text, json.dumps(sources), self.broker.run_id,
                self._epoch(), expect_seq, self._decisions(), time.time()))
            return {"ok": True, "note_id": cursor.lastrowid, "section": section}
        return self._call("write", request, write_note)

    def checkpoint(self, expect_seq, summary, plan, hazards, reconsider_when, sources):
        """One short handoff transaction; existing long-term notes are left intact."""
        request = dict(expect_seq=expect_seq, summary=summary, plan=plan, hazards=hazards,
                       reconsider_when=reconsider_when, sources=sources)
        def save():
            current = self._current_source()
            if current is None or type(expect_seq) is not int or expect_seq != self.broker.seq:
                return {"ok": False, "status": "stale", "reason": "checkpoint requires current seq"}
            texts = {"summary": summary, "plan": plan, "hazards": hazards, "reconsider_when": reconsider_when}
            if any(not isinstance(t, str) or not t.strip() or len(t) > 1200 for t in texts.values()):
                return {"ok": False, "status": "invalid", "reason": "each handoff field is 1..1200 characters"}
            if (not isinstance(sources, list) or not 1 <= len(sources) <= 20
                    or any(not isinstance(s, str) for s in sources) or current not in sources
                    or any(self.db.execute("SELECT 1 FROM records WHERE id=?", (s,)).fetchone() is None for s in sources)):
                return {"ok": False, "status": "invalid", "reason": "cite current observation and real sources"}
            ids = {}
            for section, text in texts.items():
                cursor = self.db.execute("INSERT INTO notes VALUES (NULL,?,?,?,?,?,?,?,?,?)", (
                    section, "summary" if section == "summary" else "plan", text,
                    json.dumps(sources), self.broker.run_id, self._epoch(), expect_seq,
                    self._decisions(), time.time()))
                ids[section] = cursor.lastrowid
            return {"ok": True, "note_ids": ids}
        return self._call("checkpoint", request, save)

    def _source(self, row, *, full=False, words=()):
        result = {key: row[key] for key in ("id", "run_id", "seq", "epoch", "turn", "kind")}
        result["row_index"] = row["row_index"]
        result["same_timeline"] = row["run_id"] == self.broker.run_id and row["epoch"] == self._epoch()
        record = json.loads(row["record"])
        result["record" if full else "excerpt"] = record if full else _excerpt(record, words)
        return result

    def search(self, query, limit=5, zone=None, current_timeline=False):
        def search_sources():
            if not isinstance(query, str) or not query.strip() or len(query) > 300 or type(limit) is not int or not 1 <= limit <= 10:
                return {"ok": False, "status": "invalid", "reason": "query is 1..300 characters; limit is 1..10"}
            if (zone is not None and (not isinstance(zone, str) or not 1 <= len(zone) <= 256)) or type(current_timeline) is not bool:
                return {"ok": False, "status": "invalid", "reason": "invalid zone or timeline filter"}
            words = re.findall(r"\w+", query)
            if not words:
                return {"ok": False, "status": "invalid", "reason": "query needs a word"}
            match = " OR ".join('"' + word + '"' for word in words)
            rows = self.db.execute("""SELECT r.* FROM search_index s JOIN records r ON r.id=s.id
                WHERE search_index MATCH ? AND r.kind != 'decision'
                AND (? IS NULL OR json_extract(r.record, '$.observation.vitals.zone')=?)
                AND (?=0 OR (r.run_id=? AND r.epoch=?))
                ORDER BY bm25(search_index), r.row_index DESC LIMIT 200""",
                (match, zone, zone, current_timeline, self.broker.run_id, self._epoch())).fetchall()
            # Replace a next-request duplicate with the outcome that explains the action.
            hits = {}
            for row in rows:
                record = json.loads(row["record"])
                key = (row["run_id"], row["epoch"], row["seq"] - (row["kind"] == "request"),
                       json.dumps(record["observation"], sort_keys=True)) if "observation" in record else row["id"]
                if key not in hits or row["kind"] == "result":
                    hits[key] = row
            return {"ok": True, "backend": "fts5", "candidate_limit_reached": len(rows) == 200,
                    "results": [self._source(row, words=words) for row in list(hits.values())[:limit]]}
        return self._call("search", {"query": query, "limit": limit, "zone": zone,
                                     "current_timeline": current_timeline}, search_sources)

    def read(self, source_id):
        def read_source():
            row = self.db.execute("SELECT * FROM records WHERE id=?", (source_id,)).fetchone()
            if row is None:
                return {"ok": False, "status": "not_found"}
            return {"ok": True, **self._source(row, full=True)}
        return self._call("read", {"source_id": source_id}, read_source)

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if not self._lock.closed:
            self._lock.close()
