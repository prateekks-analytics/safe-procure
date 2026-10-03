"""Procurement Copilot: conversational follow-up on a finished run.

With a live run context, the copilot is a tool-using CrewAI agent (it can re-check any vendor,
re-score scenarios, find alternatives). For a saved run it answers from the result snapshot.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .agents import build_agent
from .grounding import _INR, check_vendor_claims, ground_savings, parse_inr, savings_figures
from .llm import ResilientLLM
from .telemetry import RunTelemetry


def _snapshot(result: dict[str, Any]) -> str:
    vendors = [{"vendor": v["vendor"], "category": v["category"], "tier": v["tier"], "score": v["composite"],
                "risk": v["combined_risk"], "otd": v["kpis"]["on_time_pct"], "defect": v["kpis"]["defect_rate_pct"],
                "price_var": v["kpis"]["price_variance_pct"], "decision": (v.get("decision") or {}).get("decision")}
               for v in result["vendors"]]
    brief = result.get("brief", {})
    return json.dumps({"question": result.get("question"), "headline": brief.get("headline"), "answer": brief.get("answer"),
                       "facts": brief.get("facts"), "vendors": vendors,
                       "mitigation": [{"vendor": p.get("vendor"), "alternatives": p.get("alternatives")} for p in result.get("mitigation", {}).get("plans", [])],
                       "market": [{k: s.get(k) for k in ("category", "region", "risk_score", "headline")} for s in result.get("market", {}).get("signals", [])]},
                      default=str)[:9000]


def answer(result: dict[str, Any], message: str, history: list[dict[str, str]], ctx: Any = None) -> dict[str, Any]:
    t = time.time()
    convo = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')[:500]}" for m in history)
    prompt = (f"You are the Safe Procure copilot. Analysis snapshot (authoritative): {_snapshot(result)}\n"
              f"Conversation so far:\n{convo}\nUser: {message}\n"
              "Answer in <= 120 words of plain prose or short bullet points (no tables, no headings), cite exact numbers, use the vendor names as written. If the user asks a what-if about "
              "weights, use the scenario tool when available. Never invent data.")
    tools_used: list[str] = []
    if ctx is not None:
        tel = RunTelemetry("chat")
        old = ctx.telemetry
        ctx.telemetry = tel
        try:
            agent = build_agent("copilot", ctx)
            with contextlib.redirect_stdout(io.StringIO()):   # hide CrewAI's console panels
                out = agent.kickoff(prompt)
                if inspect.iscoroutine(out):   # inside Jupyter/Flows CrewAI returns a coroutine: run it on a fresh loop
                    with ThreadPoolExecutor(1) as ex:
                        out = ex.submit(asyncio.run, out).result()
            text = getattr(out, "raw", None) or str(out)
        finally:
            ctx.telemetry = old
        tools_used = [e["tool"] for e in tel.events if e["type"] == "tool_start"]
        models = sorted({e["model"] for e in tel.events if e["type"] == "llm_end"})
    else:
        llm = ResilientLLM("analysis", "Procurement Copilot")
        text = llm.call(prompt)
        models = [getattr(llm, "label", llm.model)]
    text, corrections = _verified(str(text).strip(), prompt, result, models)
    return {"answer": text, "tools": tools_used, "models": models, "seconds": round(time.time() - t, 1),
            "corrections": corrections}


def _fact_check(text: str, result: dict[str, Any]) -> list[str]:
    return check_vendor_claims(text, result.get("vendors", []))


def _verified(text: str, prompt: str, result: dict[str, Any], models: list[str]) -> tuple[str, list[str]]:
    """Check vendor tier/KPI claims against the run data; on errors ask for one corrected rewrite, and if errors remain,
    state the correct figures under the answer. Savings amounts are pinned to the computed figures."""
    issues = _fact_check(text, result)
    if issues:
        try:
            llm = ResilientLLM("analysis", "Procurement Copilot")
            draft = str(llm.call(f"{prompt}\n\nYour draft answer:\n{text}\n\nA check against the data found errors: "
                                 f"{'; '.join(issues)}. Rewrite the answer with these facts corrected (same length, plain prose, "
                                 "do not mention the check).")).strip()
            label = getattr(llm, "label", llm.model)
            if label not in models:
                models.append(label)
            if draft and len(_fact_check(draft, result)) < len(issues):
                text = draft
        except Exception:  # noqa: BLE001 - the deterministic note below still corrects the answer
            pass
        left = _fact_check(text, result)
        if left:
            text += "\n\nData check: " + "; ".join(left) + "."
    m = _INR.search(str((result.get("brief", {}).get("facts") or {}).get("annual_savings_opportunity", "")))
    if m and m.group("v"):
        allowed = savings_figures(result.get("cost", {}), parse_inr(m.group("v"), m.group("u")))
        text, fixed = ground_savings(text, allowed, allowed[-1] if len(allowed) > 2 else allowed[0])
        issues += [f"savings figure {f} replaced with the computed value" for f in fixed]
    return text, issues
