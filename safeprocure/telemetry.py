"""Thread-safe event log for one analysis run.

Every agent stage, tool call, LLM call and failover is recorded here. The web app
streams these events live (Server-Sent Events) to draw the mission-control view, and
the notebook prints them as a readable trace.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any, Callable


class RunTelemetry:
    def __init__(self, run_id: str, printer: Callable[[dict], None] | None = None):
        self.run_id = run_id
        self.t0 = time.time()
        self._events: list[dict[str, Any]] = []
        self._cond = threading.Condition()
        self._printer = printer
        self.usage: dict[str, dict[str, float]] = defaultdict(
            lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "seconds": 0.0, "failovers": 0}
        )
        self.closed = False

    # ------------------------------------------------------------------ write
    def emit(self, type_: str, **data: Any) -> dict[str, Any]:
        with self._cond:
            ev = {"seq": len(self._events), "t": round(time.time() - self.t0, 2), "type": type_, **data}
            self._events.append(ev)
            self._cond.notify_all()
        if self._printer:
            try:
                self._printer(ev)
            except Exception:
                pass
        return ev

    def record_usage(self, endpoint_key: str, prompt: int, completion: int, seconds: float) -> None:
        with self._cond:
            u = self.usage[endpoint_key]
            u["calls"] += 1
            u["prompt_tokens"] += prompt
            u["completion_tokens"] += completion
            u["seconds"] += seconds

    def record_failover(self, endpoint_key: str) -> None:
        with self._cond:
            self.usage[endpoint_key]["failovers"] += 1

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    # ------------------------------------------------------------------- read
    def since(self, seq: int, timeout: float = 15.0) -> list[dict[str, Any]]:
        """Block until events after `seq` exist (or timeout / closed)."""
        with self._cond:
            if len(self._events) <= seq and not self.closed:
                self._cond.wait(timeout)
            return self._events[seq:]

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._cond:
            return list(self._events)

    def usage_summary(self) -> dict[str, Any]:
        with self._cond:
            per = {k: dict(v) for k, v in self.usage.items()}
        total_in = sum(v["prompt_tokens"] for v in per.values())
        total_out = sum(v["completion_tokens"] for v in per.values())
        return {
            "per_model": per,
            "total_tokens": int(total_in + total_out),
            "prompt_tokens": int(total_in),
            "completion_tokens": int(total_out),
            "llm_calls": int(sum(v["calls"] for v in per.values())),
            "failovers": int(sum(v["failovers"] for v in per.values())),
            "elapsed": round(time.time() - self.t0, 1),
        }
