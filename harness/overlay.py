"""Read-only loopback overlay for OBS (M2 v0): status, sitrep, last decision, ledger head.

    GET /            static page (Japanese UI; data is set with textContent only)
    GET /overlay.js  GET /overlay.css
    GET /state       one JSON snapshot
    GET /events      text/event-stream: a snapshot on every change and every heartbeat

Only GET is served. Host must be exactly 127.0.0.1:<port> or localhost:<port>, and an
Origin, when sent, the matching http origin. No CORS headers are ever sent, and nothing
here can advance the game. The feed reads the broker's status code (never its reason
texts, which can carry exception or game text) and projects each ledger row, as it is
appended, into bounded public fields: observation vitals/place/digest and decision/result
metadata. Telemetry, audit links, save identities, tokens and paths never enter a
snapshot. The head hash and row count are read from the ledger object, not the file.

Decisions may carry a short action purpose in ``rationale``; absent values are
shown as 未記録. The engine's ``result.reason`` is exposed separately as ``engine_reason``.
"""

import asyncio
import contextlib
import json
import logging

log = logging.getLogger("harness.overlay")

DIGEST_LINES = 6
TEXT_MAX = 160
INT_LIMIT = 2 ** 53
STATUSES = frozenset({"awaiting_decision", "modal", "pending", "not_ready", "result_recorded",
                      "suspended", "disconnected", "recovering", "unhandled_modal", "faulted",
                      "shutdown"})
# Statuses in which the game is paused at the latest recorded observation.
CURRENT_STATUSES = frozenset({"awaiting_decision", "modal", "result_recorded"})
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def _text(value, limit=TEXT_MAX):
    if type(value) is not str:
        return None
    clean = "".join(ch if ch.isprintable() else "�" for ch in value[:limit + 1])
    return clean if len(clean) <= limit else clean[:limit - 1] + "…"


def _int(value):
    return value if type(value) is int and -INT_LIMIT <= value <= INT_LIMIT else None


def _bool(value):
    return value if type(value) is bool else None


def _sitrep(seq, basis, observation):
    vitals = observation["vitals"]
    place = observation.get("place")
    return {
        "seq": seq,
        "basis": basis,
        "hp": _int(vitals["hp"]),
        "max_hp": _int(vitals["max_hp"]),
        "turn": _int(vitals["turn"]),
        "x": _int(vitals["x"]),
        "y": _int(vitals["y"]),
        "zone": _text(vitals["zone"]),
        "place": None if place is None else {
            "name": _text(place["name"]),
            "world_map": _bool(place["world_map"]),
            "lost": _bool(place["lost"]),
        },
        "digest": [_text(line) for line in observation["digest"][-DIGEST_LINES:]],
    }


def _status(state):
    if state.get("ok") is True:
        return "modal" if "modal" in state else "awaiting_decision"
    status = state.get("status")
    if status == "not_ready" and _int(state.get("suspended_seq")) is not None:
        # The game stopped running (e.g. exited to the main menu); only a reload resumes it.
        return "suspended"
    if status == "not_ready" and "last_op_id" in state:
        return "result_recorded"
    return status if status in STATUSES else "unknown"


class OverlayFeed:
    """Bounded public projection of the run, fed by ``Ledger.on_append``."""

    def __init__(self, broker, ledger, *, poll_s=0.25, heartbeat_s=2.0, max_clients=8):
        if ledger.on_append is not None:
            raise ValueError("the ledger already has an append observer")
        self.broker = broker
        self.ledger = ledger
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s
        self.max_clients = max_clients
        self.clients = 0
        self.closed = False
        self._sitrep = None
        self._decision = None
        self._degraded = False
        self._waiters = set()
        ledger.on_append = self.observe

    def observe(self, row):
        """Ledger hook. Never raises: the row is already durable, and an exception here
        would be reported by the broker as a failed ledger write and fault the run."""
        try:
            self._project(row)
        except Exception as exc:
            self._degraded = True
            log.error("overlay projection failed (%s); sitrep and decision are hidden",
                      type(exc).__name__)
        self._wake()

    def _project(self, row):
        kind, seq, body = row["kind"], row["seq"], row["body"]
        decision = self._decision
        same = decision is not None and decision["seq"] == seq
        if kind == "request":
            self._sitrep = _sitrep(seq, "request", body["observation"])
        elif kind == "decision":
            self._decision = {"seq": seq, "action": _text(body["action"]), "dir": _text(body["dir"]),
                              "budget": _int(body["budget"]), "rationale": _text(body.get("rationale")),
                              "outcome": "pending", "result": None}
            if body["action"] == "goto":
                self._decision["target"] = {k: _int(body["target"][k]) for k in ("x", "y")}
            if body["action"] == "rest":
                self._decision["until"] = _text(body["until"])
            if "item" in body:
                self._decision["item"] = _text(body["item"])
        elif kind == "result":
            self._sitrep = _sitrep(seq, "result", body["observation"])
            if same:
                self._decision = {**decision, "outcome": "completed", "result": {
                    "executed": _bool(body["executed"]),
                    "engine_reason": _text(body["reason"]),
                    "turns_elapsed": _int(body["turns_elapsed"]),
                    "steps": _int(body["steps"]),
                }}
        elif kind == "suspended" and same and decision["outcome"] == "pending":
            self._decision = {**decision, "outcome": "suspended"}
        elif (kind in ("recovery", "game_fault") and same
              and decision["outcome"] in ("pending", "suspended")):
            self._decision = {**decision,
                              "outcome": "interrupted" if kind == "recovery" else "unknown"}
        # Modal rows change nothing shown here; the head hash covers every row.

    def snapshot(self):
        broker = self.broker
        status = _status(broker.get_state())
        seq = broker.seq
        connected = broker.game_connected
        sitrep = decision = None
        if not self._degraded:
            decision = self._decision
            if self._sitrep is not None:
                in_flight = (decision is not None and decision["seq"] == seq
                             and decision["outcome"] == "pending")
                current = (status in CURRENT_STATUSES and connected
                           and self._sitrep["seq"] == seq and not in_flight)
                sitrep = {**self._sitrep, "current": current}
        return {
            "v": 1,
            "status": status,
            "connected": connected,
            "seq": seq,
            "head_hash": self.ledger.head_hash,
            "rows": self.ledger.next_index,
            "projection_ok": not self._degraded,
            "heartbeat_ms": round(self.heartbeat_s * 1000),
            "sitrep": sitrep,
            "decision": decision,
        }

    def close(self):
        """End every event stream after one final snapshot."""
        self.closed = True
        self._wake()

    def _wake(self):
        for event in self._waiters:
            event.set()


def _json(value):
    """ASCII JSON on one line (no raw CR/LF/U+2028 can split an SSE event); markup
    characters, which can only occur inside strings, are escaped as defense in depth."""
    text = json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    return (text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .encode("ascii"))


def _headers(content_type, length=None, extra=()):
    headers = [
        (b"content-type", content_type.encode("ascii")),
        (b"cache-control", b"no-store"),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"no-referrer"),
        (b"cross-origin-resource-policy", b"same-origin"),
        (b"content-security-policy", CSP.encode("ascii")),
    ]
    if length is not None:
        headers.append((b"content-length", str(length).encode("ascii")))
    headers.extend(extra)
    return headers


async def _respond(send, status, content_type, body, extra=()):
    await send({"type": "http.response.start", "status": status,
                "headers": _headers(content_type, len(body), extra)})
    await send({"type": "http.response.body", "body": body})


async def _lifespan(receive, send):
    while True:
        message = await receive()
        if message["type"] == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message["type"] == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


async def _watch_disconnect(receive, wake):
    while (await receive())["type"] != "http.disconnect":
        pass
    wake.set()


class OverlayApp:
    """ASGI app; ``port`` is the bound port, so Host/Origin can name it exactly."""

    def __init__(self, feed, port):
        self.feed = feed
        self._hosts = frozenset({f"127.0.0.1:{port}".encode("ascii"),
                                 f"localhost:{port}".encode("ascii")})
        self._origins = frozenset({b"http://" + host for host in self._hosts})

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await _lifespan(receive, send)
        elif scope["type"] == "http":
            await self._http(scope, receive, send)
        elif scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})

    def _refusal(self, scope):
        headers = scope.get("headers") or ()
        hosts = [value.lower() for name, value in headers if name.lower() == b"host"]
        if len(hosts) != 1 or hosts[0] not in self._hosts:
            return 421, b"misdirected request"
        origins = [value.lower() for name, value in headers if name.lower() == b"origin"]
        if len(origins) > 1 or (origins and origins[0] not in self._origins):
            return 403, b"forbidden origin"
        if scope.get("method") != "GET":
            return 405, b"method not allowed"
        return None

    async def _http(self, scope, receive, send):
        refusal = self._refusal(scope)
        if refusal is not None:
            status, text = refusal
            extra = [(b"allow", b"GET")] if status == 405 else []
            await _respond(send, status, "text/plain; charset=utf-8", text, extra)
            return
        path = scope.get("path")
        if path == "/events":
            await self._events(receive, send)
        elif path == "/state":
            await _respond(send, 200, "application/json", _json(self.feed.snapshot()))
        elif path in STATIC:
            await _respond(send, 200, *STATIC[path])
        else:
            await _respond(send, 404, "text/plain; charset=utf-8", b"not found")

    async def _events(self, receive, send):
        feed = self.feed
        if feed.closed or feed.clients >= feed.max_clients:
            await _respond(send, 503, "text/plain; charset=utf-8", b"overlay unavailable")
            return
        feed.clients += 1
        wake = asyncio.Event()
        feed._waiters.add(wake)
        watcher = asyncio.create_task(_watch_disconnect(receive, wake))
        try:
            await send({"type": "http.response.start", "status": 200,
                        "headers": _headers("text/event-stream; charset=utf-8")})
            await send({"type": "http.response.body", "body": b"retry: 2000\n\n", "more_body": True})
            loop = asyncio.get_running_loop()
            last = last_sent = None
            while not watcher.done():
                wake.clear()
                snapshot = feed.snapshot()
                now = loop.time()
                if snapshot != last or now - last_sent >= feed.heartbeat_s:
                    await send({"type": "http.response.body", "more_body": True,
                                "body": b"data: " + _json(snapshot) + b"\n\n"})
                    last, last_sent = snapshot, now
                if feed.closed:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), feed.poll_s)
            await send({"type": "http.response.body", "body": b""})
        finally:
            feed._waiters.discard(wake)
            feed.clients -= 1
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


def build_overlay_app(feed, port):
    return OverlayApp(feed, port)


PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>llm-of-qud オーバーレイ</title>
<link rel="stylesheet" href="/overlay.css">
<script src="/overlay.js" defer></script>
</head>
<body data-link="connecting">
<main>
<section id="top">
<span id="status">接続待ち</span>
<span id="game">—</span>
<span id="seq">—</span>
</section>
<section id="sitrep" data-fresh="none">
<h2>状況 <span id="sitrep-meta">—</span> <span id="sitrep-fresh" class="badge">—</span></h2>
<p id="vitals">—</p>
<p id="place">—</p>
<ul id="digest"></ul>
</section>
<section id="decision">
<h2>最後の判断 <span id="decision-meta">—</span></h2>
<p><span class="label">行動</span> <span id="decision-action">—</span></p>
<p><span class="label">判断理由</span> <span id="decision-rationale">未記録</span></p>
<p><span class="label">結果</span> <span id="decision-outcome">—</span></p>
<p><span class="label">ゲーム側の結果理由（モデルの判断理由ではありません）</span>
<span id="engine-reason">—</span></p>
</section>
<footer id="ledger">
<div><span id="hash-label">台帳の先頭ハッシュ</span> <span id="rows"></span></div>
<div id="head-hash">（未受信）</div>
<div id="link">オーバーレイに接続しています</div>
</footer>
</main>
</body>
</html>
"""

SCRIPT = r""""use strict";
(() => {
  const STATUS = {
    awaiting_decision: "判断待ち",
    modal: "UI への応答待ち",
    pending: "行動を実行中",
    not_ready: "ゲームの要求待ち",
    result_recorded: "結果を記録済み・次の要求待ち",
    suspended: "ゲーム停止中（セーブ再読込待ち）",
    disconnected: "ゲーム切断中",
    recovering: "セーブ再読込からの復帰待ち",
    unhandled_modal: "未対応の UI で停止中",
    faulted: "停止（障害）",
    shutdown: "ハーネス終了",
    unknown: "不明",
  };
  const ACTIONS = { move: "移動", attack: "攻撃", wait: "待機", explore: "探索", goto: "目的地へ移動", rest: "休息", talk: "会話", eat: "食事", drink: "飲水", apply: "品を使用", get: "拾う" };
  const OUTCOMES = {
    pending: "実行中",
    suspended: "停止（ゲーム終了・結果なし）",
    completed: "完了",
    interrupted: "中断（セーブ再読込・結果なし）",
    unknown: "不明（障害で停止）",
  };
  const HEX64 = /^[0-9a-f]{64}$/;
  const byId = (id) => document.getElementById(id);
  const put = (id, value) => {
    byId(id).textContent = value === null || value === undefined ? "—" : String(value);
  };
  const shown = (value) => (value === null || value === undefined ? "?" : String(value));
  let heartbeatMs = 2000;
  let lastAt = 0;
  let live = false;

  function setLink(isLive, text) {
    live = isLive;
    document.body.dataset.link = isLive ? "live" : "lost";
    put("link", text);
    put("hash-label", isLive ? "台帳の先頭ハッシュ" : "台帳の先頭ハッシュ（最終受信）");
    if (!isLive) {
      put("status", "オーバーレイ未接続（表示は最終受信の時点）");
      put("sitrep-fresh", "古い情報");
      byId("sitrep").dataset.fresh = "stale";
    }
  }

  function renderSitrep(s, status) {
    const box = byId("sitrep");
    if (!s) {
      put("sitrep-meta", "なし");
      put("sitrep-fresh", "—");
      put("vitals", "—");
      put("place", "—");
      byId("digest").replaceChildren();
      box.dataset.fresh = "none";
      return;
    }
    put("sitrep-meta", `seq ${shown(s.seq)}・${s.basis === "result" ? "行動結果の後" : "判断要求の時点"}`);
    put("sitrep-fresh", s.current ? "現在" : status === "pending" ? "行動前の状況" : "古い情報");
    box.dataset.fresh = s.current ? "current" : "stale";
    put("vitals", `HP ${shown(s.hp)}/${shown(s.max_hp)}　ターン ${shown(s.turn)}　座標 (${shown(s.x)}, ${shown(s.y)})`);
    const place = s.place && s.place.name ? s.place.name : "（名前なし）";
    const lost = s.place && s.place.lost ? "　迷子" : "";
    put("place", `${place}　[${shown(s.zone)}]${lost}`);
    const lines = Array.isArray(s.digest) ? s.digest : [];
    byId("digest").replaceChildren(...lines.map((line) => {
      const item = document.createElement("li");
      item.textContent = line === null || line === undefined ? "" : String(line);
      return item;
    }));
  }

  function renderDecision(d) {
    if (!d) {
      put("decision-meta", "まだありません");
      put("decision-action", "—");
      put("decision-rationale", "未記録");
      put("decision-outcome", "—");
      put("engine-reason", "—");
      return;
    }
    put("decision-meta", `seq ${shown(d.seq)}`);
    const action = Object.hasOwn(ACTIONS, d.action) ? ACTIONS[d.action] : shown(d.action);
    const dir = d.dir ? ` ${d.dir}` : "";
    const budget = ["explore", "goto", "rest"].includes(d.action) ? `（上限 ${shown(d.budget)} ターン）` : "";
    const target = d.target ? ` (${shown(d.target.x)}, ${shown(d.target.y)})` : "";
    const until = d.until === "morning" ? " 朝まで" : d.until === "healed" ? " 回復まで" : "";
    const item = d.item ? ` ${shown(d.item)}` : "";
    put("decision-action", `${action}${dir}${target}${until}${item}${budget}`);
    put("decision-rationale", d.rationale === null || d.rationale === undefined ? "未記録" : d.rationale);
    let outcome = Object.hasOwn(OUTCOMES, d.outcome) ? OUTCOMES[d.outcome] : "不明";
    if (d.result) {
      outcome += `　実行: ${d.result.executed ? "はい" : "いいえ"}　経過 ${shown(d.result.turns_elapsed)} ターン`;
    }
    put("decision-outcome", outcome);
    put("engine-reason", d.result ? d.result.engine_reason : null);
  }

  function render(snap) {
    const beat = Number(snap.heartbeat_ms);
    heartbeatMs = Number.isFinite(beat) && beat > 0 ? beat : 2000;
    put("status", Object.hasOwn(STATUS, snap.status) ? STATUS[snap.status] : STATUS.unknown);
    put("game", snap.connected ? "ゲーム接続中" : "ゲーム未接続");
    put("seq", `seq ${shown(snap.seq)}`);
    put("head-hash", HEX64.test(String(snap.head_hash)) ? snap.head_hash : "（不正な値）");
    put("rows", `${shown(snap.rows)} 行`);
    renderSitrep(snap.sitrep, snap.status);
    renderDecision(snap.decision);
    if (snap.projection_ok !== true) {
      put("sitrep-meta", "表示エラー（台帳の投影に失敗）");
      put("decision-meta", "表示エラー（台帳の投影に失敗）");
    }
  }

  const source = new EventSource("/events");
  source.onmessage = (event) => {
    let snap;
    try {
      snap = JSON.parse(event.data);
    } catch (_error) {
      return;
    }
    if (!snap || typeof snap !== "object") return;
    render(snap);
    lastAt = Date.now();
    setLink(true, "受信中");
  };
  source.onerror = () => setLink(false, "オーバーレイとの接続が切れています");
  setInterval(() => {
    if (live && Date.now() - lastAt > 3 * heartbeatMs) {
      setLink(false, "ハーネスから応答がありません");
    }
  }, 500);
})();
"""

STYLE = """html, body { margin: 0; background: transparent; }
body {
  color: #f2f2f2; font: 16px/1.4 "Hiragino Sans", "Noto Sans JP", sans-serif;
  text-shadow: 0 1px 2px #000;
}
main { background: rgba(10, 12, 16, 0.78); padding: 10px 14px; max-width: 760px; }
h2 { font-size: 15px; margin: 8px 0 4px; }
p { margin: 2px 0; }
ul { margin: 2px 0; padding-left: 18px; font-size: 13px; }
.label { color: #9fb3c8; }
.badge { font-size: 12px; padding: 0 6px; border: 1px solid #9fb3c8; border-radius: 3px; }
#top { display: flex; gap: 14px; font-weight: bold; }
#sitrep[data-fresh="stale"] { opacity: 0.55; }
body[data-link="lost"] #sitrep, body[data-link="lost"] #decision { opacity: 0.45; }
body[data-link="lost"] #link, body[data-link="lost"] #status { color: #ff9b73; }
#ledger { margin-top: 8px; font-size: 12px; }
#head-hash { font: 13px/1.3 ui-monospace, Menlo, monospace; word-break: break-all; opacity: 1; }
"""

STATIC = {
    "/": ("text/html; charset=utf-8", PAGE.encode("utf-8")),
    "/overlay.js": ("text/javascript; charset=utf-8", SCRIPT.encode("utf-8")),
    "/overlay.css": ("text/css; charset=utf-8", STYLE.encode("utf-8")),
}
