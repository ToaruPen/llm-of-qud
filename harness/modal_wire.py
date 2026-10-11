"""Additive modal frames; legacy request/decision/result envelopes remain unchanged."""
from harness import wire

GAME_KINDS = frozenset({"modal", "modal_result", "modal_clear", "modal_auto", "modal_watchdog"})
TYPES = frozenset({"popup", "conversation", "string", "number", "direction", "cell", "field",
                   "pick_item", "book", "trade", "status", "terminal", "summary", "tutorial", "unknown"})
INPUTS = frozenset({"none", "string", "number", "direction", "cell", "field"})
BASE = {"kind", "run_id", "seq", "token"}
EXTRAS = {"modal": {"modal"}, "modal_result": {"answer_id", "accepted", "reason"},
          "modal_clear": {"reason"}, "modal_auto": {"rule", "modal", "accepted", "reason"}}


def bounded_text(value, name, limit=65536):
    wire._str(value, name)
    wire._require(len(value) <= limit, f"{name} is too long")


def validate_modal(modal):
    wire._exact_keys(modal, {"type", "title", "text", "choices", "input_kind", "constraints"}, "modal")
    wire._require(isinstance(modal["type"], str) and modal["type"] in TYPES, "unsupported modal type")
    wire._require(isinstance(modal["input_kind"], str) and modal["input_kind"] in INPUTS, "unsupported modal input kind")
    for key in ("title", "text"):
        bounded_text(modal[key], key)
    choices = modal["choices"]
    wire._require(isinstance(choices, list) and len(choices) <= 512, "invalid modal choices")
    ids = set()
    for item in choices:
        wire._exact_keys(item, {"id", "label"}, "choice")
        bounded_text(item["id"], "choice id", 128)
        bounded_text(item["label"], "choice label")
        wire._require(bool(item["id"]) and item["id"] not in ids, "duplicate or empty choice id")
        ids.add(item["id"])
    constraints = modal["constraints"]
    wire._require(isinstance(constraints, dict), "constraints must be an object")
    wire._require(not set(constraints) - {"min", "max", "restrict_chars", "required_text", "range"},
                  "unknown modal constraint")
    for key, value in constraints.items():
        if key in {"min", "max", "range"}:
            wire._int(value, key)
        else:
            bounded_text(value, key, 4096)
    if "min" in constraints and "max" in constraints:
        wire._require(constraints["min"] <= constraints["max"], "reversed numeric range")


def parse_optional(frame):
    if not isinstance(frame, str) or len(frame.encode("utf-8")) > wire.MAX_FRAME_BYTES:
        raise wire.WireError("frame must be bounded text")
    value = wire.loads_strict(frame)
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str) or value["kind"] not in GAME_KINDS:
        return None
    kind = value["kind"]
    if kind == "modal_watchdog":
        wire._exact_keys(value, {"kind", "run_id", "seq", "reason", "view", "type", "elapsed_ms"}, kind)
        wire._run_id(value["run_id"])
        wire._int(value["seq"], "seq", 1)
        wire._int(value["elapsed_ms"], "elapsed_ms", 30000)
        for key in ("reason", "view", "type"):
            bounded_text(value[key], key, 1024)
        return value
    wire._exact_keys(value, BASE | EXTRAS[kind], kind)
    wire._run_id(value["run_id"])
    wire._int(value["seq"], "seq", 1)
    bounded_text(value["token"], "token", 256)
    wire._require(bool(value["token"]), "empty modal token")
    if "modal" in value:
        validate_modal(value["modal"])
    if "accepted" in value:
        wire._require(type(value["accepted"]) is bool, "accepted must be boolean")
    if "answer_id" in value:
        wire._int(value["answer_id"], "answer_id", 1)
    for key in ("reason", "rule"):
        if key in value:
            bounded_text(value[key], key, 1024)
    return value


def validate_response(modal, response):
    wire._require(isinstance(response, dict) and len(response) == 1, "supply exactly one response")
    key, value = next(iter(response.items()))
    if key == "cancel":
        wire._require(value is True, "cancel must be true")
        return
    if key == "choice":
        wire._require(isinstance(value, str) and value in {c["id"] for c in modal["choices"]},
                      "choice is not in this modal")
        return
    expected = {"string": "text", "number": "number", "direction": "direction",
                "cell": "target", "field": "field"}.get(modal["input_kind"])
    wire._require(key == expected, "response does not match this modal's input")
    constraints = modal["constraints"]
    if key == "text":
        bounded_text(value, "input text", 4096)
        required = constraints.get("required_text", "")
        wire._require(len(value) <= constraints.get("max", 4096), "input text too long")
        wire._require(not required or value == required, "input does not match required text")
        allowed = constraints.get("restrict_chars", "")
        wire._require(not allowed or all(char in allowed for char in value), "input contains restricted characters")
    elif key == "number":
        wire._int(value, "number")
        wire._require(constraints.get("min", value) <= value <= constraints.get("max", value), "number out of range")
    elif key == "direction":
        wire._require(isinstance(value, str) and value in wire.ATTACK_DIRS, "invalid direction")
    else:
        targets = [value] if key == "target" else value
        wire._require(isinstance(targets, list) and 1 <= len(targets) <= 80, "invalid target list")
        for target in targets:
            wire._exact_keys(target, {"x", "y"}, "target")
            wire._int(target["x"], "x", 0)
            wire._int(target["y"], "y", 0)
            wire._require(target["x"] < 80 and target["y"] < 25, "target outside map")


def frame_body(message, frame):
    return {**{key: value for key, value in message.items() if key not in {"kind", "run_id", "seq"}},
            "frame_sha256": wire.frame_sha256(frame)}
