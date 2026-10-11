"""Deterministic R2 peer. This is a transport experiment, not an LLM harness."""

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path


class ReplayOracle:
    def __init__(self, count=1000, drop_seq=501):
        if not 1 <= drop_seq <= count:
            raise ValueError("drop_seq must be within the run")
        self.count = count
        self.drop_seq = drop_seq
        self.completed = 0
        self.replayed = False
        self.pending = None

    @property
    def complete(self):
        return self.completed == self.count and self.replayed

    def accept(self, raw):
        data = json.loads(raw)
        if (not isinstance(data, dict) or data.get("kind") != "observation"
                or type(data.get("seq")) is not int
                or not isinstance(data.get("observation"), dict)):
            raise ValueError("invalid observation envelope")
        seq = data["seq"]
        if seq != self.completed + 1 or seq > self.count:
            raise ValueError(f"expected seq {self.completed + 1}, received {seq}")
        if seq == self.drop_seq and not self.replayed:
            if self.pending is None:
                self.pending = raw
                return None
            if raw != self.pending:
                raise ValueError("pending request changed across reconnect")
            self.replayed = True
        self.completed += 1
        return {"kind": "decision", "seq": seq, "action": "probe_ack"}


async def run(args):
    from websockets.asyncio.server import serve
    from websockets.exceptions import ConnectionClosed

    oracle = ReplayOracle(args.count, args.drop_seq)
    finished = asyncio.Event()
    failure = []
    connections = 0
    resume_at = 0.0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as output:
        def record(kind, **fields):
            output.write(json.dumps({"kind": kind, "time": time.time(), **fields}, ensure_ascii=False) + "\n")
            output.flush()

        async def handle(ws):
            nonlocal connections, resume_at
            connections += 1
            connection = connections
            record("connection", connection=connection)
            try:
                async for raw in ws:
                    await asyncio.sleep(max(0, resume_at - time.monotonic()))
                    reply = oracle.accept(raw)
                    record("observation", connection=connection, seq=oracle.completed + (reply is None),
                           sha256=hashlib.sha256(raw.encode()).hexdigest(), bytes=len(raw.encode()))
                    if reply is None:
                        record("disconnect", seq=args.drop_seq, connection=connection)
                        resume_at = time.monotonic() + args.pause_seconds
                        ws.transport.abort()
                        return
                    await ws.send(json.dumps(reply))
                    if oracle.complete:
                        record("server_result", count=oracle.completed, replayed=oracle.replayed,
                               connections=connections, passed=True)
                        finished.set()
                        return
            except ConnectionClosed as exc:
                record("closed", connection=connection, error=str(exc))
            except Exception as exc:
                failure.append(str(exc))
                record("server_error", error=str(exc))
                finished.set()

        async with serve(handle, "127.0.0.1", args.port, ping_interval=None):
            record("listening", port=args.port, count=args.count, drop_seq=args.drop_seq)
            print(f"R2 listening on 127.0.0.1:{args.port}", flush=True)
            await asyncio.wait_for(finished.wait(), args.timeout)
        if failure or not oracle.complete:
            raise RuntimeError(failure or "incomplete run")
        print(f"R2 server PASS: {oracle.completed} decisions, identical pending request replayed", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4040)
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--drop-seq", type=int, default=501)
    parser.add_argument("--pause-seconds", type=float, default=2)
    parser.add_argument("--timeout", type=float, default=300)
    asyncio.run(run(parser.parse_args()))
