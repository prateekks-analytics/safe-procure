"""ResilientLLM: a CrewAI-compatible LLM that routes across providers.

Why: free-tier Groq allows ~8,000 tokens/minute per model. A 10-agent run needs far more.
This class gives every agent an ordered *failover chain* of (provider, model) endpoints and

  1. paces requests with a process-wide sliding-window token budget per endpoint,
  2. proactively skips an endpoint whose budget is exhausted (no wasted 429s),
  3. on a real error (429 / 5xx / timeout / bad tool format) puts that endpoint on
     cooldown and transparently retries on the next endpoint,
  4. reports every call, token count and failover to the run's telemetry.

Native tool calling is delegated to CrewAI's own OpenAI-compatible client, so agents keep
full function-calling support on Groq and Gemini.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from collections import deque
from typing import Any

from pydantic import ConfigDict, PrivateAttr

from crewai.llms.base_llm import BaseLLM
from crewai.llms.providers.openai.completion import OpenAICompletion

from .config import TIERS, Endpoint


class _QuietProviderErrors(logging.Filter):
    """CrewAI logs every provider error at ERROR level; the router already records and handles them."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not str(record.getMessage()).startswith(("OpenAI API call failed", "Error during"))


for _h in logging.getLogger().handlers or [logging.lastResort]:
    if _h is not None:
        _h.addFilter(_QuietProviderErrors())
logging.getLogger().addFilter(_QuietProviderErrors())
for _name in ("ddgs", "primp", "httpx"):
    logging.getLogger(_name).setLevel(logging.CRITICAL)
try:   # Safe Procure renders its own trace; switch off CrewAI's decorative console panels
    from crewai.events.event_listener import event_listener as _crewai_listener
    _crewai_listener.formatter.verbose = False
except Exception:  # pragma: no cover - internal API may move between CrewAI versions
    pass


class _Pacer:
    """Process-wide sliding 60s token window + cooldowns, one per endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._window: dict[str, deque[tuple[float, int]]] = {}
        self._cooldown: dict[str, float] = {}

    def _used(self, key: str, now: float) -> int:
        q = self._window.setdefault(key, deque())
        while q and now - q[0][0] > 60:
            q.popleft()
        return sum(t for _, t in q)

    def wait_needed(self, ep: Endpoint, est: int) -> float:
        """Seconds to wait before `est` tokens fit in this endpoint's budget (inf if cooling)."""
        now = time.time()
        with self._lock:
            cool = self._cooldown.get(ep.key, 0) - now
            if cool > 0:
                return cool
            used = self._used(ep.key, now)
            q = self._window[ep.key]
            if len(q) + 1 > ep.rpm:                       # request-rate budget
                return max(0.0, 60 - (now - q[0][0])) + 0.25
            if used + est <= ep.tpm:
                return 0.0
            # time until enough old entries expire
            freed, need = 0, used + est - ep.tpm
            for ts, toks in q:
                freed += toks
                if freed >= need:
                    return max(0.0, 60 - (now - ts)) + 0.25
            return 60.0

    def reserve(self, ep: Endpoint, tokens: int) -> None:
        with self._lock:
            self._window.setdefault(ep.key, deque()).append((time.time(), tokens))

    def settle(self, ep: Endpoint, est: int, actual: int) -> None:
        """Replace the reservation estimate with the real token count."""
        with self._lock:
            q = self._window.setdefault(ep.key, deque())
            for i in range(len(q) - 1, -1, -1):
                if q[i][1] == est:
                    q[i] = (q[i][0], actual)
                    return

    def cool(self, ep: Endpoint, seconds: float) -> None:
        with self._lock:
            self._cooldown[ep.key] = max(self._cooldown.get(ep.key, 0), time.time() + seconds)

    def snapshot(self) -> dict[str, dict[str, float]]:
        now = time.time()
        with self._lock:
            return {
                k: {"used": self._used(k, now), "cooldown": max(0.0, self._cooldown.get(k, 0) - now)}
                for k in list(self._window) + [c for c in self._cooldown if c not in self._window]
            }


PACER = _Pacer()
HOME_PATIENCE = 8.0     # seconds an agent will wait for its home model before re-routing
RETRY_SOON = 30.0       # a transiently failed endpoint ready within this beats a longer wait elsewhere


def _estimate_tokens(messages: Any) -> int:
    if isinstance(messages, str):
        chars = len(messages)
    else:
        chars = sum(len(str(m.get("content", ""))) for m in messages or [])
    return int(chars / 3.0) + 900  # + system prompt / tool schemas overhead


def _retry_after(err: Exception) -> float:
    if "PerDay" in str(err):                      # daily free-tier quota: park this model for an hour
        return 3600.0
    m = re.search(r"try again in ([\d.]+)\s*(ms|s|m)", str(err), re.I)
    if m:
        v = float(m.group(1))
        return v / 1000 if m.group(2).lower() == "ms" else v * 60 if m.group(2).lower() == "m" else v
    return 20.0


def _kind(err: Exception) -> str:
    s = f"{type(err).__name__} {err}".lower()
    if "413" in s or "request too large" in s:
        return "too_large"
    if "429" in s or "rate limit" in s or "rate_limit" in s or "quota" in s or "resource_exhausted" in s:
        return "rate_limit"
    if "401" in s or "403" in s or "api key" in s or "unauthorized" in s or "permission" in s:
        return "auth"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    if any(c in s for c in ("500", "502", "503", "504", "overloaded", "unavailable")):
        return "server"
    return "error"


class ResilientLLM(BaseLLM):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    llm_type: str = "resilient"
    tier: str = "analysis"
    agent_label: str = "agent"
    max_completion: int = 2600
    telemetry: Any = None

    _inner: dict[str, OpenAICompletion] = PrivateAttr(default_factory=dict)
    _last_endpoint: str = PrivateAttr(default="")

    def __init__(self, tier: str, agent_label: str, telemetry: Any = None, **kw: Any):
        chain = TIERS[tier].chain
        super().__init__(model=chain[0].model, tier=tier, agent_label=agent_label, telemetry=telemetry,
                         temperature=kw.pop("temperature", 0.2), **kw)

    # ------------------------------------------------------------- helpers
    @property
    def chain(self) -> tuple[Endpoint, ...]:
        return tuple(ep for ep in TIERS[self.tier].chain if ep.api_key)

    def _client(self, ep: Endpoint) -> OpenAICompletion:
        if ep.key not in self._inner:
            extra: dict[str, Any] = {}
            if ep.provider == "groq" and "gpt-oss" in ep.model:
                extra["reasoning_effort"] = "low"
            if ep.provider == "groq" and "qwen" in ep.model:
                extra["reasoning_effort"] = "none"   # no hidden thinking tokens: saves TPM budget
            if ep.model.startswith("gemini-"):
                extra["reasoning_effort"] = "low"
            self._inner[ep.key] = OpenAICompletion(
                model=ep.model, api_key=ep.api_key, base_url=ep.base_url, provider="openai",
                temperature=self.temperature, max_completion_tokens=self.max_completion,
                timeout=90, max_retries=0, **extra,
            )
        return self._inner[ep.key]

    def _emit(self, type_: str, **data: Any) -> None:
        if self.telemetry is not None:
            self.telemetry.emit(type_, agent=self.agent_label, **data)

    def _candidates(self, messages: Any, est: int) -> list[Endpoint]:
        """Endpoints allowed for this call, home lane first.

        * Mid tool-use, the model that started the loop goes first (sticky), so a
          conversation is not bounced between models without need.
        * Endpoints whose per-request ceiling is below this request are skipped
          (Groq free tier rejects any single request above its per-minute budget).
        """
        chain = [ep for ep in self.chain if est <= ep.tpm * 0.95] or [max(self.chain, key=lambda e: e.tpm)]
        has_tool_history = isinstance(messages, list) and any(
            m.get("role") == "tool" or m.get("tool_calls") for m in messages if isinstance(m, dict))
        if has_tool_history and self._last_endpoint:
            sticky = [ep for ep in chain if ep.key == self._last_endpoint]
            return sticky + [ep for ep in chain if ep.key != self._last_endpoint]
        return chain

    @staticmethod
    def _gemini_safe(messages: Any) -> Any:
        """Gemini 3 rejects tool calls produced by another model unless they carry a thought
        signature. Google documents a placeholder value for exactly this case."""
        if not isinstance(messages, list):
            return messages
        out = []
        for m in messages:
            if isinstance(m, dict) and m.get("tool_calls"):
                calls = []
                for tc in m["tool_calls"]:
                    if isinstance(tc, dict) and "extra_content" not in tc:
                        tc = {**tc, "extra_content": {"google": {"thought_signature": "skip_thought_signature_validator"}}}
                    calls.append(tc)
                m = {**m, "tool_calls": calls}
            out.append(m)
        return out

    def _pick(self, cands: list[Endpoint], est: int, tried: set[str]) -> tuple[Endpoint, float] | None:
        """Latency-aware choice: minimise (wait for budget + typical response time).

        The preferred (first) endpoint gets a small bonus so agents keep their home model
        when the difference is marginal; this keeps parallel agents on separate lanes.
        """
        home = cands[0]
        if home.key not in tried:
            w = PACER.wait_needed(home, est)
            if w <= HOME_PATIENCE:            # stay on the home lane unless it is clearly congested
                return home, w
        best, best_cost = None, float("inf")
        for ep in cands[1:]:
            if ep.key in tried:
                continue
            wait = PACER.wait_needed(ep, est)
            if wait > 900:            # cooling down for a long time (daily quota / auth)
                continue
            cost = wait + ep.latency
            if cost < best_cost:
                best, best_cost = (ep, wait), cost
        if best is None and home.key not in tried:
            w = PACER.wait_needed(home, est)
            if w <= 900:
                best = (home, w)
        if best is None or best[1] > RETRY_SOON:
            # Everything untried is far off: an endpoint that failed transiently (a 503 cools for seconds) beats
            # minutes of waiting for a rate-limited one. Rate-limited endpoints keep their long cooldown here.
            for ep in cands:
                if ep.key in tried:
                    wait = PACER.wait_needed(ep, est)
                    if wait <= RETRY_SOON and wait + ep.latency < (best_cost if best else float("inf")):
                        best, best_cost = (ep, wait), wait + ep.latency
        return best

    # ---------------------------------------------------------------- core
    def call(self, messages, tools=None, callbacks=None, available_functions=None,
             from_task=None, from_agent=None, response_model=None):
        if not self.chain:
            raise RuntimeError("No API keys configured. Set GROQ_API_KEY and/or GEMINI_API_KEY.")
        est = _estimate_tokens(messages) - 900 + self.max_completion
        last_err: Exception | None = None
        tried: set[str] = set()
        cands = self._candidates(messages, est)
        home = cands[0]
        for attempt in range(len(cands) + 3):
            pick = self._pick(cands, est, tried)
            if pick is None:
                if attempt >= len(cands) + 2:
                    break
                tried = set()                        # every endpoint failed once: wait, then retry all
                self._emit("throttle", model=home.label, wait=10)
                time.sleep(10)
                continue
            ep, wait = pick
            if wait > 0:
                if wait >= 2:
                    self._emit("throttle", model=ep.label, wait=round(wait, 1))
                time.sleep(wait)
            if True:
                if ep is not home and self._last_endpoint != ep.key:
                    self._emit("failover", to_model=ep.label, to_provider=ep.provider,
                               from_model=home.label, reason="budget" if not last_err else _kind(last_err))
                    if self.telemetry is not None:
                        self.telemetry.record_failover(ep.key)
                PACER.reserve(ep, est)
                client = self._client(ep)
                before = client.get_token_usage_summary()
                t = time.time()
                self._emit("llm_start", model=ep.label, provider=ep.provider)
                try:
                    msgs = self._gemini_safe(messages) if ep.model.startswith("gemini-") else messages
                    out = client.call(msgs, tools=tools, callbacks=callbacks,
                                      available_functions=available_functions, from_task=from_task,
                                      from_agent=from_agent, response_model=response_model)
                except Exception as err:  # noqa: BLE001 - classify and fail over
                    kind = _kind(err)
                    last_err = err
                    tried.add(ep.key)
                    if kind != "too_large":
                        PACER.cool(ep, _retry_after(err) if kind == "rate_limit" else 300 if kind == "auth" else 8)
                    self._emit("llm_error", model=ep.label, provider=ep.provider, kind=kind,
                               message=str(err)[:240])
                    continue
                dt = time.time() - t
                after = client.get_token_usage_summary()
                p = max(0, after.prompt_tokens - before.prompt_tokens)
                c = max(0, after.completion_tokens - before.completion_tokens)
                PACER.settle(ep, est, p + c if p + c else est)
                self._last_endpoint = ep.key
                self.model = ep.model
                self.label = ep.label
                if self.telemetry is not None:
                    self.telemetry.record_usage(ep.key, p, c, dt)
                self._emit("llm_end", model=ep.label, provider=ep.provider, prompt_tokens=p,
                           completion_tokens=c, seconds=round(dt, 2))
                return out
        raise RuntimeError(f"All model endpoints failed for {self.agent_label}: {last_err}")

    async def acall(self, messages, tools=None, callbacks=None, available_functions=None,
                    from_task=None, from_agent=None, response_model=None):
        return await asyncio.to_thread(self.call, messages, tools, callbacks, available_functions,
                                       from_task, from_agent, response_model)

    def supports_function_calling(self) -> bool:
        return True

    def supports_stop_words(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 60_000
