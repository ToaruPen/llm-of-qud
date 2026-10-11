"""Exercise the production modal bridge through MCP in a disposable development run.

Bootstrap and arm with development:true before calling this operator-only driver.
This is deterministic integration evidence, never an LLM gameplay claim.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import time

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

CASES = ("notice", "yesno", "option", "string", "required", "number_keyboard",
         "number_controller", "direction", "cell", "field", "item", "book", "status",
         "number_controller_cancel", "direction_cancel", "cell_cancel", "field_cancel", "item_cancel")
AUTO = {"notice", "book", "status"}


def results_since(path, offset, name):
    with path.open(encoding="utf-8", errors="replace") as stream:
        stream.seek(offset)
        lines = stream.read().splitlines()
    found = []
    for line in lines:
        marker = line.find("[LLM] ")
        if marker < 0:
            continue
        try:
            value = json.loads(line[marker + 6:])
        except json.JSONDecodeError:
            continue
        if value.get("kind") == "development_probe_result" and value.get("name") == name:
            found.append(value)
    return found


def control(profile, payload):
    path = profile / "llm-control.json"
    if path.exists():
        raise RuntimeError("Another operator command is pending")
    temp = path.with_suffix(".integration.tmp")
    with temp.open("x") as stream:
        os.chmod(temp, 0o600)
        json.dump(payload, stream)
    temp.replace(path)


def response_for(name, modal, observation):
    if name.endswith("_cancel"):
        return {"cancel": True}
    if name in {"yesno", "option"}:
        label = "No" if name == "yesno" else "gamma"
        matches = [c["id"] for c in modal["choices"] if c["label"] == label]
        assert len(matches) == 1, (name, modal)
        return {"choice": matches[0]}
    if name == "item":
        return {"choice": modal["choices"][-1]["id"]}
    if name in {"string", "required"}:
        return {"text": "名は café 🌿" if name == "string" else "ENTOMB"}
    if name.startswith("number_"):
        return {"number": 7}
    if name == "direction":
        return {"direction": "E"}
    v = observation["vitals"]
    x = v["x"] + (1 if v["x"] < 79 else -1)
    if name == "cell":
        return {"target": {"x": x, "y": v["y"]}}
    if name == "field":
        return {"field": [{"x": v["x"], "y": v["y"]}, {"x": x, "y": v["y"]}]}
    raise ValueError(name)


async def run(args):
    ready = json.loads((args.run_dir / "ready.json").read_text())
    report = {"driver": "deterministic_modal_integration", "llm_gameplay": False,
              "profile": str(args.profile), "player_log": str(args.player_log), "cases": []}
    started = time.monotonic()
    try:
        async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + (args.run_dir / "token").read_text()}) as http:
            async with Client(streamable_http_client(ready["mcp_url"], http_client=http)) as client:
                async def call(name, **kwargs):
                    result = await client.call_tool(name, kwargs)
                    assert not result.is_error, result
                    return result.structured_content

                names = sorted(t.name for t in (await client.list_tools()).tools)
                assert names == ["act", "get_state", "respond", "wait_for_turn"], names
                state = await call("get_state")
                assert state.get("ok") and not state.get("modal"), state
                initial_seq = state["seq"]
                old_token = None
                for name in args.cases:
                    case = {"name": name, "ok": False}
                    report["cases"].append(case)
                    offset = args.player_log.stat().st_size
                    control(args.profile, {"command": "probe_modal", "case": name})
                    async with asyncio.timeout(45 + (args.hold_seconds if name == "yesno" else 0)):
                        if name not in AUTO:
                            while True:
                                state = await call("get_state")
                                assert state.get("ok"), state
                                modal = state.get("modal")
                                if modal and modal["token"] != old_token:
                                    break
                                await asyncio.sleep(0.1)
                            token = modal["token"]
                            case["modal"] = modal
                            assert state["seq"] == initial_seq, state
                            if old_token:
                                stale = await call("respond", expect_seq=initial_seq, token=old_token, response={"cancel": True})
                                assert stale.get("status") == "stale_modal", stale
                                case["stale_rejected"] = True
                            if name == "yesno":
                                denied = await call("act", expect_seq=initial_seq, action="wait")
                                assert denied.get("status") == "modal_required", denied
                                denied = await call("respond", expect_seq=initial_seq, token=token, response={"choice": "missing"})
                                assert denied.get("status") == "invalid", denied
                                before = state["observation"]["vitals"]["turn"]
                                hold_started = time.monotonic()
                                while time.monotonic() - hold_started < args.hold_seconds:
                                    await asyncio.sleep(1)
                                    held = await call("get_state")
                                    assert held.get("ok") and held.get("modal", {}).get("token") == token, held
                                    assert held["seq"] == initial_seq and held["observation"]["vitals"]["turn"] == before, held
                                case["held_seconds"] = time.monotonic() - hold_started
                            if name == "required":
                                denied = await call("respond", expect_seq=initial_seq, token=token, response={"text": "entomb"})
                                assert denied.get("status") == "invalid", denied
                            answer = await call("respond", expect_seq=initial_seq, token=token,
                                                response=response_for(name, modal, state["observation"]))
                            while answer.get("pending"):
                                await asyncio.sleep(0.1)
                                current = await call("get_state")
                                last = current.get("last_modal_result", {})
                                if last.get("answer_id") == answer["answer_id"]:
                                    answer = last
                            case["answer"] = answer
                            assert answer.get("accepted") is True, answer
                            old_token = token
                        while not (records := results_since(args.player_log, offset, name)):
                            await asyncio.sleep(0.1)
                        assert len(records) == 1, records
                        actual = records[0]
                        case["engine_result"] = actual
                        assert actual.get("ok") is True, actual
                        assert actual["turn_before"] == actual["turn_after"], actual
                        assert actual["energy_before"] == actual["energy_after"], actual
                        case["ok"] = True
                        print(json.dumps({"case": name, "ok": True}, ensure_ascii=False), flush=True)
                    await asyncio.sleep(0.2)
                state = await call("get_state")
                assert state.get("ok") and state["seq"] == initial_seq and not state.get("modal"), state
                result = await call("act", expect_seq=initial_seq, action="wait")
                async with asyncio.timeout(50):
                    while result.get("pending"):
                        result = await call("wait_for_turn", op_id=result["op_id"], timeout_s=10)
                assert result.get("completed") and result["result"]["executed"], result
                report["post_modal_action"] = result
                report["ok"] = True
    except BaseException as exc:
        report["ok"] = False
        report["error"] = repr(exc)
        raise
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        output = args.run_dir / "modal-integration.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        output.chmod(0o600)
        print(json.dumps({"ok": report.get("ok", False), "report": str(output)}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--player-log", type=Path, required=True)
    parser.add_argument("--case", dest="cases", choices=CASES, action="append")
    parser.add_argument("--hold-seconds", type=int, default=60)
    args = parser.parse_args()
    args.cases = args.cases or CASES
    if not 0 <= args.hold_seconds <= 120:
        parser.error("--hold-seconds must be between 0 and 120")
    asyncio.run(run(args))
