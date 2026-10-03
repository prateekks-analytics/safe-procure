"""SafeProcureFlow: the multi-agent workflow (CrewAI Flow).

    intake -> audit -> [performance | cost | market]  (parallel)
           -> forecast -> strategy -> (risk gate) -> mitigation? -> QA -> (revise loop?) -> brief

* Parallel fan-out/fan-in with and_().
* A router sends high-risk portfolios through the Mitigation Planner, low-risk ones straight to QA.
* The QA Reviewer can send the strategy back for ONE revision with required changes.
* Every stage has a deterministic fallback, so a run always completes (degraded stages are labelled).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from difflib import get_close_matches
from typing import Any

import pandas as pd
from crewai import Crew, Process, Task
from crewai.flow import Flow, and_, listen, or_, router, start
from pydantic import BaseModel

from . import analytics as A
from .agents import ROSTER, build_agent
from .grounding import ground_percents, ground_savings, savings_figures
from .schemas import (AuditFindings, CostFindings, ExecutiveBrief, ForecastFindings, IntakePlan, MarketFindings,
                      MitigationFindings, PerformanceFindings, QAReview, StrategyDecision)
from .telemetry import RunTelemetry
from .tools import RunContext, make_tools


def _quarter() -> str:
    t = time.localtime()
    q = (t.tm_mon - 1) // 3 + 1
    nq, ny = (q % 4) + 1, t.tm_year + (1 if q == 4 else 0)
    names = {1: "Jan-Mar", 2: "Apr-Jun", 3: "Jul-Sep", 4: "Oct-Dec"}
    return f"current quarter Q{q} {t.tm_year} = {names[q]} {t.tm_year}; next quarter Q{nq} {ny}"


class SPState(BaseModel):
    plan: dict = {}
    audit: dict = {}
    performance: dict = {}
    cost: dict = {}
    market: dict = {}
    forecast: dict = {}
    strategy: dict = {}
    mitigation: dict = {}
    qa: dict = {}
    brief: dict = {}
    revisions: int = 0
    degraded: list[str] = []
    stage_seconds: dict = {}
    path: list[str] = []
    grounding: list[str] = []


def _j(x: Any, limit: int = 3500) -> str:
    s = json.dumps(x, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "...(truncated)"


def _coerce(raw: str, model: type[BaseModel]) -> dict | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        return model.model_validate_json(m.group(0)).model_dump()
    except Exception:
        return None


class SafeProcureFlow(Flow[SPState]):
    def __init__(self, ctx: RunContext, **kw: Any):
        super().__init__(**kw)
        self._ctx = ctx

    # ------------------------------------------------------------ plumbing
    @property
    def ctx(self) -> RunContext:
        return self._ctx

    def _vendor_names(self) -> list[str]:
        return self.ctx.in_scope.vendor_name.tolist()

    def _match_vendor(self, name: str) -> str | None:
        names = self.ctx.scored.vendor_name.tolist()
        if name in names:
            return name
        low = {n.lower(): n for n in names}
        key = name.lower().strip()
        for n_low, n in low.items():
            if key and (key in n_low or n_low.replace(" pvt ltd", "") in key):
                return n
        hit = get_close_matches(key, list(low), n=1, cutoff=0.6)
        return low[hit[0]] if hit else None

    def _ground(self, stage: str, items: list[dict], key: str = "vendor") -> list[dict]:
        """Drop findings about vendors that do not exist; canonicalise the rest."""
        kept, dropped = [], []
        for it in items or []:
            m = self._match_vendor(str(it.get(key, "")))
            if m:
                kept.append({**it, key: m})
            else:
                dropped.append(str(it.get(key, "")))
        if dropped:
            self.ctx.telemetry.emit("grounding", stage=stage, dropped=dropped)
            self.state.grounding.extend(f"{stage}: removed finding about unknown vendor '{d}'" for d in dropped)
        return kept

    def _project(self, plan: dict) -> dict | None:
        """Blended OTD/defects on the at-risk vendor's volume once the chosen shares move to the alternatives."""
        s = self.ctx.scored.set_index("vendor_name")
        if plan.get("vendor") not in s.index:
            return None
        r = s.loc[plan["vendor"]]
        shares = [(a["to_vendor"], max(0.0, float(a.get("share_of_volume_pct") or 0))) for a in plan.get("alternatives", [])
                  if a.get("to_vendor") in s.index]
        total = sum(sh for _, sh in shares)
        if total <= 0:
            return None
        if total > 100:
            shares, total = [(v, sh * 100 / total) for v, sh in shares], 100.0
        keep = 100 - total
        otd = (keep * r.on_time_pct + sum(sh * s.loc[v].on_time_pct for v, sh in shares)) / 100
        dfx = (keep * r.defect_rate_pct + sum(sh * s.loc[v].defect_rate_pct for v, sh in shares)) / 100
        return {"shift_pct": round(total, 1), "otd_now": round(float(r.on_time_pct), 1), "otd_after": round(float(otd), 1),
                "defect_now": round(float(r.defect_rate_pct), 2), "defect_after": round(float(dfx), 2)}

    @staticmethod
    def _projection_text(p: dict) -> str:
        return (f"OTD {p['otd_now']:.1f}% → {p['otd_after']:.1f}%, defects {p['defect_now']:.2f}% → {p['defect_after']:.2f}% "
                f"on this volume after shifting {p['shift_pct']:g}% (computed from current KPIs)")

    def _pct_pools(self, plans: list[dict]) -> tuple[set[float], set[float]]:
        """(general, projected): percentages an agent may cite in plain statements vs. in forward-looking claims."""
        c = self.ctx
        rules = {float(c.otd_floor), float(c.defect_ceiling), float(c.risk_threshold)}
        setup = {65.0, 35.0} | {float(w) for w in (c.weights or {}).values()}   # risk blend + pillar weights
        targets = {p.get("vendor") for p in plans}
        fc: set[float] = set()        # forecast end points of projected breaches + recent history of planned vendors
        hist: set[float] = set()      # any vendor's recent history (plain mentions only)
        for f in A.forecast(c.df, otd_floor=c.otd_floor, defect_ceiling=c.defect_ceiling):
            for m in ("otd", "defect"):
                recent = {float(x) for x in f[m].get("history", [])[-3:]}
                hist |= recent
                if f["otd_breach"] or f["defect_breach"]:
                    fc.add(float(f[m]["forecast"][-1]))
                if f["vendor_name"] in targets:
                    fc |= recent
        plan_vals: set[float] = set()
        s = c.scored.set_index("vendor_name")
        moved: set[float] = set()   # volume shares are plan inputs, not outcomes: plain mentions only
        for p in plans:
            moved |= {float(a.get("share_of_volume_pct") or 0) for a in p.get("alternatives", [])}
            pr = p.get("projection") or {}
            moved.add(float(pr.get("shift_pct", 0)))
            plan_vals |= {float(v) for k, v in pr.items() if k != "shift_pct"}
            if p.get("vendor") in s.index:
                plan_vals |= {float(s.loc[p["vendor"]][k]) for k in ("on_time_pct", "defect_rate_pct")}
        pct_cols = ("on_time_pct", "defect_rate_pct", "price_variance_pct", "fill_rate_pct", "capacity_utilization_pct")
        kpis = {float(x) for col in pct_cols if col in c.scored.columns for x in c.scored[col].dropna()}
        shares = {x["top_share"] * 100 for x in A.spend_analysis(c.df, c.kpis)["categories"]}
        projected = rules | fc | plan_vals
        return projected | kpis | shares | moved | hist | setup, projected

    def _ground_text(self, stage: str, x: Any, general: set[float], projected: set[float], drop_sentences: bool = False) -> Any:
        if isinstance(x, str):
            if drop_sentences:   # secondary prose: drop a sentence with an unsupported claim rather than patch it
                kept, removed = [], []
                for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z])", x):
                    bad = ground_percents(sent, general, projected)[1]
                    if bad:
                        removed.extend(bad)
                    else:
                        kept.append(sent)
                out = " ".join(kept)
            else:
                out, removed = ground_percents(x, general, projected)
            if removed:
                self.state.grounding.extend(f"{stage}: removed unsupported projection '{r}'" for r in removed)
                self.ctx.telemetry.emit("grounding_pct", stage=stage, removed=removed)
            return out
        if isinstance(x, list):
            return [self._ground_text(stage, i, general, projected) for i in x]
        if isinstance(x, dict):
            return {k: self._ground_text(stage, v, general, projected) for k, v in x.items()}
        return x

    def _stage(self, key: str, description: str, expected: str, out_model: type[BaseModel], fallback) -> dict:
        tel: RunTelemetry = self.ctx.telemetry
        spec = ROSTER[key]
        tel.emit("stage_start", stage=key, agent=spec.name, tier=spec.tier, tools=list(spec.tools))
        t = time.time()
        status, data = "ok", None
        try:
            agent = build_agent(key, self.ctx)
            task = Task(description=description, agent=agent, output_pydantic=out_model,
                        expected_output=expected + " Give the final answer as plain JSON text, never as a tool call.")
            res = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False).kickoff()
            if getattr(res, "pydantic", None) is not None:
                data = res.pydantic.model_dump()
            else:
                data = _coerce(res.raw, out_model)
            if data is None:
                raise ValueError("Agent did not return valid structured output")
        except Exception as err:  # noqa: BLE001 - never let a stage kill the run
            tel.emit("stage_error", stage=key, agent=spec.name, message=str(err)[:300])
            status, data = "degraded", fallback()
            self.state.degraded.append(key)
        secs = round(time.time() - t, 1)
        self.state.stage_seconds[key] = secs
        self.state.path.append(key)
        tel.emit("stage_end", stage=key, agent=spec.name, status=status, seconds=secs, output=data)
        return data

    async def _astage(self, *a, **kw) -> dict:
        return await asyncio.to_thread(self._stage, *a, **kw)

    def _scope_note(self) -> str:
        c = self.ctx
        cats = ", ".join(c.focus_categories) if c.focus_categories else "all categories"
        today = time.strftime("%Y-%m-%d")
        return (f"Today is {today} (calendar: {_quarter()}). Scope: {cats}. Vendors in scope: {len(c.in_scope)}. "
                f"Pillar weights: {c.weights}. Risk threshold (combined risk 0-100): {c.risk_threshold}. "
                f"On-time floor {c.otd_floor}%, defect ceiling {c.defect_ceiling}%.\n"
                f"The ONLY vendors that exist (use these exact names, never invent others): {', '.join(self._vendor_names())}.\n"
                "Money is INR; write amounts with L (lakh) or Cr (crore) exactly as the tools show them, never M or bn.")

    # ------------------------------------------------------------ 1 intake
    @start()
    def intake(self):
        c = self.ctx
        q = c.question or "Run a full vendor portfolio risk review and recommend what to do with each vendor."
        desc = (f"User request: \"{q}\"\n{self._scope_note()}\n"
                f"Dataset: {c.quality['vendors']} vendors, categories {c.quality['categories']}, "
                f"months {c.quality['months']}, total spend {A.inr(c.quality['total_spend'])}.\n"
                f"Vendor names: {', '.join(self._vendor_names())}.\n"
                "Produce the analysis plan. Classify the question, pick the pillars that matter most for THIS request, "
                "list any vendors explicitly mentioned, define 2-4 success criteria, and write a short brief for the team.")

        def fb():
            ql = q.lower()
            qt = ("cost_reduction" if any(w in ql for w in ("cost", "sav", "cheap", "price")) else
                  "risk_scan" if "risk" in ql else "consolidation" if "consolidat" in ql else "portfolio_review")
            return IntakePlan(objective=q, question_type=qt, priority_pillars=["delivery", "quality", "cost"],
                              success_criteria=["Every vendor has a decision", "Risks quantified"],
                              instructions_for_team="Full portfolio review.").model_dump()
        self.state.plan = self._stage("intake", desc, "An IntakePlan JSON object.", IntakePlan, fb)
        return self.state.plan

    # ------------------------------------------------------------- 2 audit
    @listen(intake)
    def audit(self):
        desc = ("Call audit_dataset once. Judge whether the data is fit for sourcing decisions. "
                "Summarise the issues found and the cleaning applied, and list caveats the decision-makers must know.")

        def fb():
            q = self.ctx.quality
            v = "fit_for_analysis" if q["quality_score"] >= 90 else "usable_with_caveats" if q["quality_score"] >= 70 else "not_reliable"
            return AuditFindings(verdict=v, summary=f"Quality score {q['quality_score']}/100; {len(q['issues'])} issue types auto-cleaned.",
                                 caveats=[i["action"] for i in q["issues"]]).model_dump()
        self.state.audit = self._stage("audit", desc, "An AuditFindings JSON object.", AuditFindings, fb)
        return self.state.audit

    # ---------------------------------------------- 3a/3b/3c parallel analysts
    @listen(audit)
    async def performance(self):
        desc = (f"{self._scope_note()}\nTeam brief: {self.state.plan.get('instructions_for_team', '')}\n"
                "Call vendor_scorecard ONCE (sort_by internal_risk) and vendor_profile for at most 2 of the most "
                "concerning vendors. Report top performers, underperformers and trend alerts (deteriorating or improving "
                "momentum). Every finding must cite exact numbers from the tools.")

        def fb():
            s = self.ctx.in_scope
            top = [{"vendor": r.vendor_name, "headline": f"Tier {r.tier}, score {r.composite:.0f}", "evidence": f"OTD {r.on_time_pct:.1f}%, defects {r.defect_rate_pct:.2f}%", "severity": "positive"} for r in s.head(3).itertuples()]
            bot = [{"vendor": r.vendor_name, "headline": f"Tier {r.tier}, risk {r.internal_risk:.0f}", "evidence": f"OTD {r.on_time_pct:.1f}%, defects {r.defect_rate_pct:.2f}%", "severity": "high"} for r in s.sort_values("internal_risk", ascending=False).head(3).itertuples()]
            return PerformanceFindings(summary="Rule-based summary (agent unavailable).", top_performers=top, underperformers=bot).model_dump()
        out = await self._astage("performance", desc, "A PerformanceFindings JSON object.", PerformanceFindings, fb)
        for k in ("top_performers", "underperformers", "trend_alerts"):
            out[k] = self._ground("performance", out.get(k, []))
        self.state.performance = out
        return self.state.performance

    @listen(audit)
    async def cost(self):
        desc = (f"{self._scope_note()}\nTeam brief: {self.state.plan.get('instructions_for_team', '')}\n"
                "Call spend_analytics. Identify categories with dangerous single-vendor concentration (share > 45% or HHI > 2500) "
                "and quantify 2-4 savings levers (renegotiation of positive price variance, volume consolidation to best-value "
                "vendors, etc.) in INR per year. Every lever value must be derived from the tool's per-category savings opportunity; "
                "the levers together cannot exceed the tool's annualised savings opportunity. Use only vendor names from the tools.")

        def fb():
            sp = A.spend_analysis(self.ctx.df, self.ctx.kpis)
            conc = [{"vendor": c["top_vendor"], "headline": f"{c['top_share']:.0%} of {c['category']} spend", "evidence": f"HHI {c['hhi']}", "severity": "high"} for c in sp["categories"] if c["concentration_flag"]]
            lev = [{"lever": "Renegotiate positive price variance", "categories": [c["category"] for c in sp["categories"]], "vendors": [], "estimated_annual_value_inr": sp["savings_opportunity_total"], "rationale": "Bring prices to best-in-category variance."}]
            return CostFindings(summary="Rule-based summary (agent unavailable).", concentration_risks=conc, savings_levers=lev).model_dump()
        out = await self._astage("cost", desc, "A CostFindings JSON object.", CostFindings, fb)
        sp = A.spend_analysis(self.ctx.df, self.ctx.kpis)
        # Concentration facts are computed, not generated: exact and never hallucinated.
        out["concentration_risks"] = [
            {"vendor": c["top_vendor"], "headline": f"{c['top_share']:.0%} of {c['category']} spend with one vendor",
             "evidence": f"HHI {c['hhi']:,} across {c['vendors']} vendors; category spend {A.inr(c['spend'])}",
             "severity": "high" if c["top_share"] > 0.6 else "medium"}
            for c in sp["categories"] if c["concentration_flag"]]
        # One savings basis everywhere: the annualised renegotiation opportunity (also the brief's key number).
        # Full overpayment is a different, larger figure; adding it on top double-counted the same variance.
        cap = sp["savings_opportunity_total"]
        known_cats = {c["category"] for c in sp["categories"]}
        levers = []
        for lv in out.get("savings_levers", []):
            vs = [m for m in (self._match_vendor(v) for v in lv.get("vendors", [])) if m]
            bad = [v for v in lv.get("vendors", []) if not self._match_vendor(v)]
            text = lv.get("rationale", "")
            if bad:
                self.ctx.telemetry.emit("grounding", stage="cost", dropped=bad)
                self.state.grounding.extend(f"cost: removed unknown vendor '{b}' from a savings lever" for b in bad)
                text = "Consolidate volume toward the best-value existing vendors in this category."
            val = float(lv.get("estimated_annual_value_inr") or 0)
            room = max(0.0, cap - sum(x["estimated_annual_value_inr"] for x in levers))   # cap applies to the levers together
            if val > room:
                self.state.grounding.append(f"cost: capped '{lv.get('lever')}' from {A.inr(val)} to {A.inr(room)} "
                                            f"(levers together cannot exceed the data-supported {A.inr(cap)})")
                val = room
            if val < 1:   # rounding residue counts as nothing left
                self.state.grounding.append(f"cost: dropped '{lv.get('lever')}' (no data-supported savings left after earlier levers)")
                continue
            levers.append({**lv, "vendors": vs, "rationale": text, "estimated_annual_value_inr": round(val),
                           "categories": [c for c in lv.get("categories", []) if c in known_cats] or lv.get("categories", [])})
        out["savings_levers"] = levers
        self.state.cost = out
        return self.state.cost

    @listen(audit)
    async def market(self):
        s = self.ctx.in_scope
        cats = sorted(s.category.unique().tolist())
        top_regions = s.groupby("region").spend_total.sum().sort_values(ascending=False).head(2).index.tolist()
        desc = (f"Today is {time.strftime('%Y-%m-%d')}. Categories in scope: {cats}. Highest-spend regions: {top_regions}.\n"
                "Call market_intel_search ONCE with a list of queries: one per category (e.g. '<category> India supply prices "
                f"shortage') and one per listed region about logistics or disruption (at most {len(cats) + 2} queries). "
                "Then output one signal per category (region 'All India') plus one per region searched (category 'All'). "
                "Score risk 0-100 from the evidence (35 = normal baseline, >60 = material disruption). Quote the real headline, "
                "source, date and url from the results; ignore results unrelated to Indian supply chains. "
                "Never invent news; if nothing relevant was found, say so and score 35.")

        def fb():
            return MarketFindings(summary="Live market search unavailable; baseline risk assumed.",
                                  signals=[{"category": c, "region": "All India", "risk_score": 35, "headline": "No live signal",
                                            "implication": "Baseline risk"} for c in cats]).model_dump()
        tel = self.ctx.telemetry
        mark = len(tel.events)
        out = await self._astage("market", desc, "A MarketFindings JSON object.", MarketFindings, fb)
        searched = any(e["type"] == "tool_start" and e.get("tool") == "market_intel_search" for e in tel.events[mark:])
        if not searched:
            # The agent answered without searching: run the search ourselves, then let it reason over real results.
            self.state.grounding.append("market: agent skipped the news search; search was run by the guard and the agent re-ran on real results")
            tool = make_tools(self.ctx, ROSTER["market"].name, ["search"])[0]
            queries = [f"{c} India supply prices shortage" for c in cats] + [f"{r.split(',')[0]} logistics disruption India" for r in top_regions]
            results = await asyncio.to_thread(tool._run, queries=queries)
            out = await self._astage("market", desc + "\n\nSearch results already retrieved by market_intel_search (cite only these):\n"
                                     + results[:6000], "A MarketFindings JSON object.", MarketFindings, fb)
        # Citation check: a signal may only cite an article that was actually retrieved in this run.
        by_url = {s["url"]: s for s in self.ctx.sources if s.get("url")}
        for sig in out.get("signals", []):
            url = (sig.get("url") or "").strip()
            if url in by_url:
                src = by_url[url]
                sig["source"], sig["date"] = src.get("source", sig.get("source")), src.get("date", sig.get("date"))
                continue
            area = f"{sig.get('category')}/{sig.get('region')}"
            key = (sig.get("category") if sig.get("category") not in ("All", "") else sig.get("region", "")).split(",")[0].split("&")[0].strip().lower()
            match = next((s for s in self.ctx.sources if key and key in s.get("query", "").lower()
                          and (not sig.get("headline") or s["title"][:40].lower() in str(sig.get("headline")).lower()
                               or str(sig.get("headline"))[:40].lower() in s["title"].lower())), None)                 or next((s for s in self.ctx.sources if key and key in s.get("query", "").lower()), None)
            if match:
                if url or sig.get("source"):
                    self.state.grounding.append(f"market: re-linked the {area} citation to a retrieved article (agent's link did not match)")
                sig.update(headline=match["title"], source=match["source"], date=match["date"], url=match["url"])
            else:
                if url or sig.get("source"):
                    self.state.grounding.append(f"market: removed unverifiable citation '{sig.get('source') or url}' for {area}")
                    tel.emit("grounding", stage="market", dropped=[sig.get("source") or url])
                sig.update(source="", url="", date="", risk_score=min(float(sig.get("risk_score", 35)), 35.0),
                           headline="No verified news signal in the last 30 days", direction="stable")
        out["sources"] = list(self.ctx.sources)
        self.state.market = out
        return out

    # ---------------------------------------------------------- 4 forecast
    @listen(and_(performance, cost, market))
    def forecast(self):
        # Blend external risk into the scorecard now that market signals exist.
        mk: dict[str, float] = {}
        for sig in self.state.market.get("signals", []):
            cat, reg = sig.get("category", ""), sig.get("region", "")
            if cat and cat.lower() not in ("all", "all categories"):
                mk[cat] = float(sig["risk_score"])
            elif reg:
                mk[reg] = float(sig["risk_score"])
        for col in ("market_risk", "combined_risk"):
            if col in self.ctx.scored.columns:
                self.ctx.scored = self.ctx.scored.drop(columns=[col])
        scored = self.ctx.scored.copy()
        cat_map = {c: v for c, v in mk.items() if c in set(scored.category)}
        reg_map = {r: v for r, v in mk.items() if r in set(scored.region)}

        def ext(row):
            vals = [cat_map.get(row.category, 35.0)]
            if row.region in reg_map:
                vals.append(reg_map[row.region])
            return 0.7 * vals[0] + 0.3 * vals[-1] if len(vals) > 1 else vals[0]
        scored["market_risk"] = scored.apply(ext, axis=1)
        scored["combined_risk"] = 0.65 * scored.internal_risk + 0.35 * scored.market_risk
        self.ctx.scored = scored
        self.ctx.telemetry.emit("risk_blend", flagged=int((scored.combined_risk >= self.ctx.risk_threshold).sum()))

        desc = (f"{self._scope_note()}\nCall forecast_performance once (all vendors). Raise early warnings for vendors projected "
                "to breach the on-time floor or defect ceiling within 3 months, with a concrete monitoring trigger for each. "
                "Note the 80% band: low confidence when the band is wide. List improving vendors separately.")

        def fb():
            fc = A.forecast(self.ctx.df, otd_floor=self.ctx.otd_floor, defect_ceiling=self.ctx.defect_ceiling)
            ew = [{"vendor": f["vendor_name"], "metric": "both" if f["otd_breach"] and f["defect_breach"] else "on_time" if f["otd_breach"] else "defects",
                   "projection": f"OTD {f['otd']['forecast'][-1]}%, defects {f['defect']['forecast'][-1]}%", "confidence": "medium",
                   "recommended_trigger": "Weekly review"} for f in fc if f["otd_breach"] or f["defect_breach"]]
            return ForecastFindings(summary="Rule-based projection (agent unavailable).", early_warnings=ew,
                                    improving=[f["vendor_name"] for f in fc if f["outlook"] == "improving"]).model_dump()
        out = self._stage("forecast", desc, "A ForecastFindings JSON object.", ForecastFindings, fb)
        out["early_warnings"] = self._ground("forecast", out.get("early_warnings", []))
        # Every projected breach from the model is guaranteed to appear, whatever the agent wrote.
        have = {w["vendor"] for w in out["early_warnings"]}
        for f in A.forecast(self.ctx.df, otd_floor=self.ctx.otd_floor, defect_ceiling=self.ctx.defect_ceiling):
            if (f["otd_breach"] or f["defect_breach"]) and f["vendor_name"] not in have and f["vendor_name"] in set(self.ctx.in_scope.vendor_name):
                band = max(u - l for u, l in zip(f["otd"]["upper"], f["otd"]["lower"]))
                metric = "both" if f["otd_breach"] and f["defect_breach"] else "on_time" if f["otd_breach"] else "defects"
                proj = (f"OTD {f['otd']['history'][-1]:.1f}% -> {f['otd']['forecast'][-1]:.1f}% by {f['future_months'][-1]}" if f["otd_breach"]
                        else f"Defects {f['defect']['history'][-1]:.2f}% -> {f['defect']['forecast'][-1]:.2f}% by {f['future_months'][-1]}")
                out["early_warnings"].append({"vendor": f["vendor_name"], "metric": metric, "projection": proj,
                                              "confidence": "high" if band < 8 else "medium" if band < 16 else "low",
                                              "recommended_trigger": "Weekly performance review; escalate if the next month misses the threshold",
                                              "source": "model"})
        out["improving"] = [m for m in (self._match_vendor(v) for v in out.get("improving", [])) if m]
        self.state.forecast = out
        return self.state.forecast

    # ---------------------------------------------------------- 5 strategy
    def _strategy_table(self) -> str:
        fc = {f["vendor_name"]: f["outlook"] for f in A.forecast(self.ctx.df, otd_floor=self.ctx.otd_floor, defect_ceiling=self.ctx.defect_ceiling)}
        s = self.ctx.in_scope.copy()
        s["outlook"] = s.vendor_name.map(fc)
        return A.table_for_llm(s, ["vendor_name", "category", "composite", "tier", "internal_risk", "market_risk", "combined_risk",
                                   "on_time_pct", "defect_rate_pct", "price_variance_pct", "otd_trend", "compliance_incidents",
                                   "capacity_utilization_pct", "outlook"], 40)

    def _rule_decisions(self) -> list[dict]:
        th = self.ctx.risk_threshold
        out = []
        for r in self.ctx.in_scope.itertuples():
            cr = r.combined_risk
            if cr >= th + 12 or (r.tier == "D"):
                d, conf = "Replace", 0.7
            elif cr >= th:
                d, conf = "Watch", 0.65
            elif r.composite < 72 and r.otd_trend > 0.4:
                d, conf = "Develop", 0.6
            elif r.composite < 70:
                d, conf = "Watch", 0.55
            else:
                d, conf = "Keep", 0.75
            out.append({"vendor": r.vendor_name, "decision": d, "confidence": conf,
                        "rationale": f"Rule-based: composite {r.composite:.0f}, combined risk {cr:.0f} vs threshold {th:.0f}.",
                        "actions": [], "source": "rule"})
        return out

    @listen(or_(forecast, "revise"))
    def strategy(self):
        st = self.state
        revision = ""
        if st.revisions and st.qa:
            revision = ("\nREVISION REQUIRED by the QA Reviewer. Fix these issues:\n- " + "\n- ".join(st.qa.get("required_changes", []))
                        + f"\nYour previous decisions: {_j([{k: d[k] for k in ('vendor', 'decision')} for d in st.strategy.get('decisions', [])], 1800)}")
        desc = (f"User objective: {st.plan.get('objective')}\nPriority pillars: {st.plan.get('priority_pillars')}\n{self._scope_note()}\n"
                f"Data audit: {st.audit.get('verdict')} - {_j(st.audit.get('caveats', []), 400)}\n"
                f"Performance findings: {_j(st.performance, 1500)}\nCost findings: {_j(st.cost, 1300)}\n"
                f"Market signals: {_j([{k: s.get(k) for k in ('category', 'region', 'risk_score', 'direction', 'headline')} for s in st.market.get('signals', [])], 1300)}\n"
                f"Forecast warnings: {_j(st.forecast.get('early_warnings', []), 1100)}\n\n"
                f"Decision table (combined_risk = 65% internal + 35% market):\n{self._strategy_table()}\n{revision}\n\n"
                "Decide for EVERY vendor in the table with this rubric. Keep: tier A or B, combined_risk at least 8 below the "
                "threshold and no deteriorating outlook. Watch: combined_risk within 8 of the threshold, a deteriorating outlook, "
                "or rising market risk. Develop: tier C with an improving or stable outlook and meaningful spend (worth fixing). "
                "Replace: combined_risk above the threshold with a deteriorating or volatile record, or repeated compliance breaches. "
                "Vendors with combined_risk above the threshold must not be 'Keep' unless you justify it. "
                "Before finalising, call scenario_rescore once with a delivery-heavy and once with a cost-heavy weighting and "
                "report in robustness_note whether your Replace/Watch calls survive. Cite numbers in every rationale. "
                "Use the exact vendor names.")
        data = self._stage("strategy", desc, "A StrategyDecision JSON object covering every vendor.", StrategyDecision,
                           lambda: StrategyDecision(portfolio_summary="Rule-based decisions (agent unavailable).",
                                                    decisions=self._rule_decisions()).model_dump())
        # Reconcile names and fill any vendor the agent skipped with the rule engine.
        rules = {d["vendor"]: d for d in self._rule_decisions()}
        fixed, seen = [], set()
        for d in data.get("decisions", []):
            m = self._match_vendor(d.get("vendor", ""))
            if m and m not in seen and m in rules:
                fixed.append({**d, "vendor": m, "source": d.get("source", "agent")})
                seen.add(m)
        for v, d in rules.items():
            if v not in seen:
                fixed.append(d)
        data["decisions"] = fixed
        st.strategy = data
        return data

    @router(strategy)
    def risk_gate(self):
        th = self.ctx.risk_threshold
        decisions = self.state.strategy.get("decisions", [])
        replace = sorted(d["vendor"] for d in decisions if d["decision"] == "Replace")
        high = self.ctx.in_scope[self.ctx.in_scope.combined_risk >= th + 8].vendor_name.tolist()
        targets = sorted(set(replace) | set(high))
        prev = sorted(p.get("vendor") for p in self.state.mitigation.get("plans", []))
        route = "mitigate" if targets and targets != prev else "review"
        reason = "high_risk" if route == "mitigate" else ("already_planned" if targets else "no_high_risk")
        self.ctx.telemetry.emit("route", stage="risk_gate", route=route, targets=targets, reason=reason)
        self._mitigation_targets = targets
        return route

    # -------------------------------------------------------- 6 mitigation
    @listen("mitigate")
    def mitigation(self):
        targets = getattr(self, "_mitigation_targets", [])[:5]
        decisions = {d["vendor"]: d for d in self.state.strategy.get("decisions", [])}
        alt_facts = {t: [{k: a[k] for k in ("vendor_name", "composite", "headroom_pct", "on_time_pct", "defect_rate_pct")}
                         for a in A.alternatives(self.ctx.scored, t, 3)] for t in targets}
        desc = (f"{self._scope_note()}\nHigh-risk vendors needing a continuity plan: {targets}.\nStrategist view: "
                f"{_j([decisions.get(t, {}) for t in targets], 1500)}\n"
                f"Data-supported alternatives in the same category (ONLY these may receive volume): {_j(alt_facts, 1600)}\n"
                "For EACH vendor: call find_alternatives, choose 1-2 alternatives and the % of volume to shift (respect their "
                "headroom), and write concrete 30/60/90-day actions (e.g. qualification audit, trial PO, contract clauses, "
                "safety stock). State the expected impact qualitatively: the system computes the blended OTD/defect "
                "projection from the shares you choose, so do not invent percentage improvements.")

        def fb():
            plans = []
            for t in targets:
                alts = A.alternatives(self.ctx.scored, t, 2)
                plans.append({"vendor": t, "risk": "Combined risk above tolerance",
                              "alternatives": [{"to_vendor": a["vendor_name"], "share_of_volume_pct": min(40.0, a["headroom_pct"] * 2)} for a in alts],
                              "days_30": ["Qualification audit of alternatives", "Raise safety stock"], "days_60": ["Trial POs"],
                              "days_90": ["Shift agreed volume"], "expected_impact": "Reduced single-source exposure"})
            return MitigationFindings(summary="Rule-based plan (agent unavailable).", plans=plans).model_dump()
        out = self._stage("mitigation", desc, "A MitigationFindings JSON object.", MitigationFindings, fb)
        out["plans"] = self._ground("mitigation", out.get("plans", []))
        for plan in out["plans"]:
            allowed = {a["vendor_name"]: a for a in A.alternatives(self.ctx.scored, plan["vendor"], 4)}
            good, bad = [], []
            for a in plan.get("alternatives", []):
                m = self._match_vendor(str(a.get("to_vendor", "")))
                (good if m in allowed else bad).append({**a, "to_vendor": m or a.get("to_vendor")})
            if bad:
                names = [b["to_vendor"] for b in bad]
                self.ctx.telemetry.emit("grounding", stage="mitigation", dropped=names)
                self.state.grounding.extend(f"mitigation: replaced unsupported alternative '{n}' for {plan['vendor']}" for n in names)
                text = " ".join(sum([plan.get(k, []) for k in ("days_30", "days_60", "days_90")], []) + [plan.get("expected_impact", "")])
                if any(n and n in text for n in names):   # plan wording names an invented supplier: rewrite it
                    plan["days_30"] = ["Run qualification audits at the alternative vendors", "Raise safety stock for critical SKUs"]
                    plan["days_60"] = ["Issue trial purchase orders and track OTD/defects weekly"]
                    plan["days_90"] = ["Shift the agreed volume and amend contracts"]
            if not good:
                good = [{"to_vendor": a["vendor_name"], "share_of_volume_pct": round(min(40.0, a["headroom_pct"] * 2), 0)}
                        for a in list(allowed.values())[:2] if a["headroom_pct"] > 0]
            plan["alternatives"] = good
            plan["projection"] = self._project(plan)
        # Expected impact: the computed blend leads; agent prose keeps only percentages that trace to computed numbers.
        general, projected = self._pct_pools(out["plans"])
        for plan in out["plans"]:
            prose = self._ground_text("mitigation", plan.get("expected_impact", ""), general, projected, drop_sentences=bool(plan["projection"]))
            if plan["projection"]:
                plan["expected_impact"] = self._projection_text(plan["projection"]) +(f". {prose}" if prose else ".")
            else:
                plan["expected_impact"] = prose
        self.state.mitigation = out
        return self.state.mitigation

    # ----------------------------------------------------------------- 7 QA
    def _guardrails(self) -> list[str]:
        """Deterministic checks run before the QA agent (cheap, exact)."""
        th = self.ctx.risk_threshold
        s = self.ctx.scored.set_index("vendor_name")
        flags = []
        for d in self.state.strategy.get("decisions", []):
            if d["vendor"] not in s.index:
                continue
            r = s.loc[d["vendor"]]
            if d["decision"] == "Keep" and r.combined_risk >= th + 5:
                flags.append(f"{d['vendor']}: 'Keep' but combined risk {r.combined_risk:.0f} > threshold {th:.0f}")
            if d["decision"] == "Replace" and r.tier == "A":
                flags.append(f"{d['vendor']}: 'Replace' but tier A (score {r.composite:.0f})")
            for num in re.findall(r"(\d+\.\d+)\s*%", d.get("rationale", ""))[:2]:
                v = float(num)
                cands = [r.on_time_pct, r.defect_rate_pct, r.price_variance_pct, r.fill_rate_pct, r.capacity_utilization_pct]
                if all(abs(v - c) > 1.0 for c in cands) and v > 5:
                    flags.append(f"{d['vendor']}: rationale cites {v}% which matches no KPI for this vendor")
        return flags

    @router(or_("review", mitigation))
    def qa(self):
        st = self.state
        flags = self._guardrails()
        self.ctx.telemetry.emit("guardrails", stage="qa", flags=flags)
        decs = st.strategy.get("decisions", [])
        material = [d for d in decs if d["decision"] != "Keep" or any(d["vendor"] in f for f in flags)]
        keeps = [d["vendor"].replace(" Pvt Ltd", "") for d in decs if d not in material]
        lines = "\n".join(f"- {d['vendor']} | {d['decision']} | conf {d.get('confidence', 0):.2f} | {str(d.get('rationale', ''))[:150]}"
                          for d in material)
        desc = (f"Review the strategist's decisions as an independent auditor.\nNon-Keep decisions:\n{lines}\n"
                f"Keep decisions ({len(keeps)}): {', '.join(keeps)}\n"
                f"Mitigation summary: {_j(st.mitigation.get('summary', 'none'), 300)}\n"
                f"Automated guardrail flags: {flags or 'none'}\n{self._scope_note()}\n"
                "Use vendor_profile to verify the numbers behind at most 4 of the most consequential decisions (Replace calls "
                "first, then flagged vendors). Mark each check verified / corrected / unsupported. Choose 'revise' only for "
                "material errors (wrong numbers, decision contradicts data); otherwise 'approve'. List required changes if revising.")
        data = self._stage("qa", desc, "A QAReview JSON object.", QAReview,
                           lambda: QAReview(verdict="approve", confidence=0.6,
                                            checks=[{"claim": f, "status": "unsupported", "note": "Automated guardrail"} for f in flags],
                                            required_changes=[]).model_dump())
        data["guardrail_flags"] = flags
        data["round"] = st.revisions + 1
        st.qa = data
        if data.get("verdict") == "revise" and st.revisions < 1:
            st.revisions += 1
            self.ctx.telemetry.emit("route", stage="qa", route="revise")
            return "revise"
        self.ctx.telemetry.emit("route", stage="qa", route="publish")
        return "publish"

    # -------------------------------------------------------------- 8 brief
    @listen("publish")
    def brief(self):
        st, c = self.state, self.ctx
        sp = A.spend_analysis(c.df, c.kpis)
        dec = pd.Series([d["decision"] for d in st.strategy.get("decisions", [])]).value_counts().to_dict()
        at_risk = c.in_scope[c.in_scope.combined_risk >= c.risk_threshold]
        facts = {
            "total_spend": A.inr(sp["total_spend"]), "vendors": len(c.in_scope),
            "spend_at_risk": A.inr(at_risk.spend_total.sum()), "vendors_above_risk_threshold": len(at_risk),
            "annual_savings_opportunity": A.inr(sp["savings_opportunity_total"]),
            "concentrated_categories": [x["category"] for x in sp["categories"] if x["concentration_flag"]],
        }
        desc = (f"{self._scope_note()}\nUser question: \"{c.question or st.plan.get('objective')}\"\nKey facts (exact, use these): {_j(facts)}\n"
                f"Decision counts (shown separately in the UI; do not make it a key number): {dec}\n"
                f"FINAL decisions after QA (use exactly; do not call a Watch vendor 'Replace'): "
                + "; ".join(f"{k} = {', '.join(d['vendor'].replace(' Pvt Ltd', '') for d in st.strategy.get('decisions', []) if d['decision'] == k) or 'none'}"
                            for k in ("Replace", "Watch", "Develop")) + "\n"
                f"Strategy: {_j(st.strategy.get('portfolio_summary'), 600)} | Robustness: {_j(st.strategy.get('robustness_note'), 300)}\n"
                f"Replace/Watch: {_j([d for d in st.strategy.get('decisions', []) if d['decision'] in ('Replace', 'Watch')], 1800)}\n"
                f"Mitigation: {_j([{k: p.get(k) for k in ('vendor', 'alternatives', 'projection')} for p in st.mitigation.get('plans', [])], 1200)}\n"
                "Projected impact: cite ONLY the computed 'projection' numbers above (blended OTD/defects on the shifted vendor's "
                "volume) or forecast figures; never invent percentage improvements or risk reductions.\n"
                f"Savings levers: {_j(st.cost.get('savings_levers', []), 900)}\n"
                f"Savings: quote only {facts['annual_savings_opportunity']} (annual opportunity) or the lever values above, "
                "which are already capped to it; never another savings figure.\nMarket:{_j(st.market.get('summary'), 400)}\n"
                f"QA: {st.qa.get('verdict')} (confidence {st.qa.get('confidence')})\n"
                "Write the executive brief: answer the user's question directly first; 3 short paragraphs; 4-6 key numbers; "
                "3-5 actions with owner (role), timeline and quantified impact. Key number values must be short (max 14 characters, "
                "e.g. '₹5.63 Cr' or '2 of 20'). Timelines use real dates from today onward. No numbers or vendors that are not "
                "in the inputs.")

        def fb():
            return ExecutiveBrief(headline=f"{len(at_risk)} vendors above risk tolerance; {facts['spend_at_risk']} spend exposed",
                                  answer="See decisions and mitigation plans.", summary=[st.strategy.get("portfolio_summary", "")],
                                  key_numbers=[{"label": k.replace('_', ' '), "value": str(v)} for k, v in facts.items() if k != "decisions"]).model_dump()
        st.brief = self._stage("brief", desc, "An ExecutiveBrief JSON object.", ExecutiveBrief, fb)
        # Final scrub: any name the grounding guard removed upstream must not resurface in the brief.
        removed = {n for e in self.ctx.telemetry.events if e["type"] == "grounding" and e.get("stage") != "market"
                   for n in e.get("dropped", []) if len(n) > 3}
        if removed:
            def scrub(x):
                if isinstance(x, str):
                    for n in removed:
                        x = x.replace(n, "an alternative qualified vendor")
                    return x
                if isinstance(x, list):
                    return [scrub(i) for i in x]
                if isinstance(x, dict):
                    return {k: scrub(v) for k, v in x.items()}
                return x
            st.brief = scrub(st.brief)
        # Projected percentages must trace to computed numbers; a stripped action impact gets the computed blend instead.
        plans = st.mitigation.get("plans", [])
        general, projected = self._pct_pools(plans)
        for k in ("headline", "answer", "summary"):
            st.brief[k] = self._ground_text("brief", st.brief.get(k), general, projected)
        for a in st.brief.get("top_actions", []):
            before = a.get("impact", "")
            a["action"] = self._ground_text("brief", a.get("action", ""), general, projected)
            a["impact"] = self._ground_text("brief", before, general, projected)
            if a["impact"] != before or not a["impact"]:
                text = f"{a['action']} {before}".lower()
                hit = next((p for p in plans if p.get("projection") and any(
                    n.lower().replace(" pvt ltd", "") in text for n in [p["vendor"]] + [x["to_vendor"] for x in p.get("alternatives", [])])), None)
                if hit:   # the computed blend replaces the stripped claim outright
                    a["impact"] = self._projection_text(hit["projection"]).replace(" (computed from current KPIs)", "")
        # Rupee savings must be the computed opportunity or a (capped) lever: one savings story across key numbers and prose.
        allowed = savings_figures(st.cost, sp["savings_opportunity_total"])
        levers_total = allowed[-1] if len(allowed) > 2 else sp["savings_opportunity_total"]
        def fix_savings(x):
            if isinstance(x, list):
                return [fix_savings(i) for i in x]
            out, bad = ground_savings(x, allowed, levers_total)
            st.grounding.extend(f"brief: corrected savings figure '{b}' to {A.inr(levers_total)} (computed)" for b in bad)
            return out
        for k in ("headline", "answer", "summary"):
            st.brief[k] = fix_savings(st.brief.get(k))
        for a in st.brief.get("top_actions", []):
            a["impact"] = fix_savings(a.get("impact", ""))
        st.brief["facts"] = {**facts, "decisions": dec}
        # Key numbers must be traceable to computed facts (or the user's own thresholds); anything else is dropped.
        def norm(v):
            return re.sub(r"[\s₹,]", "", str(v)).lower()
        allowed = {norm(v) for v in facts.values()} | {norm(len(v)) for v in facts.values() if isinstance(v, list)} | {norm(f"{len(at_risk)} of {len(c.in_scope)}"), norm(f"{c.otd_floor:g}%"),
                                                        norm(f"{c.defect_ceiling:g}%"), norm(f"{c.risk_threshold:g}")}
        kept = [k for k in st.brief.get("key_numbers", []) if norm(k.get("value", "")) in allowed]
        dropped_kn = [k for k in st.brief.get("key_numbers", []) if k not in kept]
        if dropped_kn:
            st.grounding.extend(f"brief: removed key number '{k.get('label')}: {k.get('value')}' (not in computed facts)" for k in dropped_kn)
        if len(kept) < 4:
            labels = {"total_spend": "Total spend", "spend_at_risk": "Spend at risk", "vendors_above_risk_threshold": "Vendors above tolerance",
                      "annual_savings_opportunity": "Annual savings opportunity", "vendors": "Vendors analysed"}
            have = {norm(k["value"]) for k in kept}
            for key, label in labels.items():
                v = facts[key] if key != "vendors_above_risk_threshold" else f"{len(at_risk)} of {len(c.in_scope)}"
                if norm(v) not in have and len(kept) < 5:
                    kept.append({"label": label, "value": str(v)})
        st.brief["key_numbers"] = kept[:6]
        return st.brief


# =================================================================== runner
def prepare_context(df: pd.DataFrame, *, weights: dict | None = None, risk_threshold: float = 55, question: str = "",
                    focus_categories: list[str] | None = None, otd_floor: float = 85, defect_ceiling: float = 3.0,
                    telemetry: RunTelemetry | None = None) -> RunContext:
    d, q = A.clean(df)
    k = A.vendor_kpis(d)
    s = A.score(k, weights)
    s["market_risk"] = 35.0
    s["combined_risk"] = 0.65 * s.internal_risk + 0.35 * s.market_risk
    from .config import DEFAULT_WEIGHTS
    return RunContext(df=d, quality=q, kpis=k, scored=s, weights={**DEFAULT_WEIGHTS, **(weights or {})},
                      risk_threshold=risk_threshold, otd_floor=otd_floor, defect_ceiling=defect_ceiling, question=question,
                      focus_categories=[c for c in (focus_categories or []) if c in set(s.category)],
                      telemetry=telemetry or RunTelemetry(uuid.uuid4().hex[:8]))


def run_analysis(ctx: RunContext) -> dict[str, Any]:
    tel = ctx.telemetry
    tel.emit("run_start", question=ctx.question, vendors=len(ctx.in_scope), weights=ctx.weights)
    flow = SafeProcureFlow(ctx)
    try:
        flow.kickoff()
    except Exception as err:  # noqa: BLE001
        tel.emit("run_error", message=str(err)[:400])
    result = build_result(ctx, flow.state)
    tel.emit("run_end", usage=result["usage"], degraded=flow.state.degraded)
    tel.close()
    return result


def build_result(ctx: RunContext, st: SPState) -> dict[str, Any]:
    s = ctx.scored
    dec = {d["vendor"]: d for d in st.strategy.get("decisions", [])}
    fc = {f["vendor_name"]: f for f in A.forecast(ctx.df, otd_floor=ctx.otd_floor, defect_ceiling=ctx.defect_ceiling)}
    vendors = []
    for r in s.itertuples():
        vendors.append({
            "vendor": r.vendor_name, "id": r.vendor_id, "category": r.category, "region": r.region,
            "in_scope": bool(r.vendor_name in set(ctx.in_scope.vendor_name)),
            "composite": round(r.composite, 1), "tier": r.tier, "rank": int(r.rank),
            "pillars": {p: round(getattr(r, p), 1) for p in A.PILLARS},
            "internal_risk": round(r.internal_risk, 1), "market_risk": round(r.market_risk, 1), "combined_risk": round(r.combined_risk, 1),
            "kpis": {k: round(float(getattr(r, k)), 2) for k in ("on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days",
                                                                   "price_variance_pct", "response_time_hrs", "capacity_utilization_pct",
                                                                   "otd_trend", "defect_trend")},
            "compliance_incidents": int(r.compliance_incidents), "spend_total": float(r.spend_total), "spend_recent": float(r.spend_recent),
            "otd_series": r.otd_series, "defect_series": r.defect_series,
            "forecast": fc.get(r.vendor_name), "decision": dec.get(r.vendor_name),
        })
    return {
        "run_id": ctx.telemetry.run_id, "created": time.strftime("%Y-%m-%d %H:%M"), "question": ctx.question,
        "config": {"weights": ctx.weights, "risk_threshold": ctx.risk_threshold, "otd_floor": ctx.otd_floor,
                   "defect_ceiling": ctx.defect_ceiling, "focus_categories": ctx.focus_categories},
        "quality": ctx.quality, "vendors": vendors, "spend": A.spend_analysis(ctx.df, ctx.kpis),
        "plan": st.plan, "audit": st.audit, "performance": st.performance, "cost": st.cost, "market": st.market,
        "forecast": st.forecast, "strategy": st.strategy, "mitigation": st.mitigation, "qa": st.qa, "brief": st.brief,
        "path": st.path, "grounding": st.grounding, "revisions": st.revisions, "degraded": st.degraded, "stage_seconds": st.stage_seconds,
        "usage": ctx.telemetry.usage_summary(), "events": ctx.telemetry.events,
    }
