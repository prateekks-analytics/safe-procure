"""Custom CrewAI tools. Each wraps the deterministic analytics engine or live web search.

Tools are created per agent per run, so every call is attributed to an agent in the trace.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from . import analytics as A


@dataclass
class RunContext:
    """Everything one analysis run knows. Shared by tools, flow and the web API."""

    df: pd.DataFrame
    quality: dict[str, Any]
    kpis: pd.DataFrame
    scored: pd.DataFrame
    weights: dict[str, float]
    risk_threshold: float = 55.0
    otd_floor: float = 85.0
    defect_ceiling: float = 3.0
    question: str = ""
    focus_categories: list[str] = field(default_factory=list)
    telemetry: Any = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _search_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    @property
    def in_scope(self) -> pd.DataFrame:
        s = self.scored
        return s[s.category.isin(self.focus_categories)] if self.focus_categories else s


class _CtxTool(BaseTool):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    ctx: Any = Field(default=None, exclude=True)
    agent_label: str = Field(default="agent", exclude=True)

    def _trace(self, phase: str, **data: Any) -> None:
        if self.ctx is not None and self.ctx.telemetry is not None:
            self.ctx.telemetry.emit(f"tool_{phase}", agent=self.agent_label, tool=self.name, **data)

    def _run(self, **kwargs: Any) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def run_traced(self, fn, **kwargs: Any) -> str:
        t = time.time()
        self._trace("start", args={k: v for k, v in kwargs.items() if v not in (None, "", [])})
        try:
            out = fn(**kwargs)
        except Exception as err:  # noqa: BLE001
            out = f"Tool error: {err}"
        self._trace("end", seconds=round(time.time() - t, 2), chars=len(out), preview=out[:160])
        return out


# ----------------------------------------------------------------- 1 audit
class _NoArgs(BaseModel):
    # Groq rejects function schemas with an empty properties object, so expose one optional knob.
    detail: Optional[str] = Field("summary", description="'summary' (default) or 'full'")


class DataQualityTool(_CtxTool):
    name: str = "audit_dataset"
    description: str = ("Profiles the vendor dataset and returns detected data-quality issues "
                        "(duplicates, missing values, outliers, sign errors) and the cleaning applied.")
    args_schema: type[BaseModel] = _NoArgs

    def _run(self, **_: Any) -> str:
        def go() -> str:
            q = self.ctx.quality
            lines = [f"Rows in: {q['rows_in']}, rows after cleaning: {q['rows_out']}, vendors: {q['vendors']}, "
                     f"months: {q['months'][0]}..{q['months'][1]} ({q['n_months']}), quality score: {q['quality_score']}/100",
                     f"Categories: {', '.join(q['categories'])}", f"Regions: {', '.join(q['regions'])}",
                     f"Total spend: {A.inr(q['total_spend'])}", "Issues:"]
            for i in q["issues"] or []:
                lines.append(f"- {i['type']} in {i['column']}: {i['count']} rows -> {i['action']}. e.g. {'; '.join(i['examples'][:2])}")
            if not q["issues"]:
                lines.append("- none detected")
            return "\n".join(lines)
        return self.run_traced(go)


# ------------------------------------------------------------- 2 scorecard
class _ScoreArgs(BaseModel):
    category: Optional[str] = Field(None, description="Optional category filter, e.g. 'Packaging'")
    sort_by: Optional[str] = Field("composite", description="composite | internal_risk | on_time_pct | defect_rate_pct | price_variance_pct")
    top_n: Optional[int] = Field(20, description="Rows to return")


class VendorScorecardTool(_CtxTool):
    name: str = "vendor_scorecard"
    description: str = ("Returns the weighted vendor scorecard: pillar scores (0-100) for delivery, quality, cost, "
                        "responsiveness, compliance, composite score, internal risk, tier, key KPIs and 6-month trends.")
    args_schema: type[BaseModel] = _ScoreArgs

    def _run(self, category: str | None = None, sort_by: str | None = "composite", top_n: int | None = 25, **_: Any) -> str:
        def go(category=None, sort_by="composite", top_n=25) -> str:
            s = self.ctx.in_scope
            if category:
                s = s[s.category.str.lower().str.contains(category.lower()[:8])]
            col = sort_by if sort_by in s.columns else "composite"
            # on-time ascending shows the worst performers first; everything else descending
            s = s.sort_values(col, ascending=col == "on_time_pct")
            w = self.ctx.weights
            hdr = f"Weights: {json.dumps(w)}  (pillars 0-100, higher is better; internal_risk 0-100 higher is worse)\n"
            cols = ["vendor_name", "category", "composite", "tier", "internal_risk", "delivery", "quality", "cost",
                    "responsiveness", "compliance", "on_time_pct", "defect_rate_pct", "price_variance_pct",
                    "otd_trend", "compliance_incidents"]
            return hdr + A.table_for_llm(s, cols, int(top_n or 25))
        return self.run_traced(go, category=category, sort_by=sort_by, top_n=top_n)


# ---------------------------------------------------------- 3 vendor profile
class _VendorArgs(BaseModel):
    vendor_name: str = Field(..., description="Vendor name (partial match allowed)")


class VendorProfileTool(_CtxTool):
    name: str = "vendor_profile"
    description: str = "Returns every KPI, pillar score, trend and the last 12 months of on-time % and defect % for one vendor. Use to verify claims."
    args_schema: type[BaseModel] = _VendorArgs

    def _run(self, vendor_name: str = "", **_: Any) -> str:
        def go(vendor_name="") -> str:
            s = self.ctx.scored
            m = s[s.vendor_name.str.lower().str.contains(vendor_name.lower().replace(" pvt ltd", "")[:14], regex=False)]
            if m.empty:
                return f"No vendor matching '{vendor_name}'. Known: {', '.join(s.vendor_name.head(25))}"
            r = m.iloc[0]
            keys = ["vendor_name", "category", "region", "composite", "tier", "rank", "internal_risk", "delivery", "quality",
                    "cost", "responsiveness", "compliance", "on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days",
                    "price_variance_pct", "response_time_hrs", "compliance_incidents", "compliance_incidents_total",
                    "capacity_utilization_pct", "otd_trend", "defect_trend", "otd_delta", "defect_delta", "otd_volatility"]
            d = {k: (round(float(r[k]), 2) if isinstance(r[k], (float, int)) and not isinstance(r[k], bool) else r[k]) for k in keys}
            for k in ("market_risk", "combined_risk"):
                if k in r.index:
                    d[k] = round(float(r[k]), 1)
            # Unambiguous names: KPIs are spend-weighted averages of the last 6 months.
            for k in ("on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days", "price_variance_pct", "response_time_hrs"):
                d[f"{k}_6mo_avg"] = d.pop(k)
            d["spend_total"] = A.inr(r.spend_total)
            d["otd_monthly_last12"] = r.otd_series
            d["defect_monthly_last12"] = r.defect_series
            d["note"] = "combined_risk = 0.65*internal_risk + 0.35*market_risk; *_6mo_avg are spend-weighted 6-month averages"
            return json.dumps(d, default=str)
        return self.run_traced(go, vendor_name=vendor_name)


# ----------------------------------------------------------------- 4 spend
class SpendAnalyticsTool(_CtxTool):
    name: str = "spend_analytics"
    description: str = ("Spend analysis: total spend, Pareto (vendors holding 80% of spend), per-category HHI concentration, "
                        "top-vendor share, price-variance overpayment and annualised savings opportunity.")
    args_schema: type[BaseModel] = _NoArgs

    def _run(self, **_: Any) -> str:
        def go() -> str:
            sp = A.spend_analysis(self.ctx.df, self.ctx.kpis)
            lines = [f"Total spend: {A.inr(sp['total_spend'])} across {sp['vendor_count']} vendors. "
                     f"{sp['pareto_vendors_80pct']} vendors hold 80% of spend.",
                     f"Recent 6-month overpayment vs contract (positive price variance): {A.inr(sp['overpay_recent_total'])}. "
                     f"Annualised savings opportunity: {A.inr(sp['savings_opportunity_total'])}.",
                     "| category | spend | vendors | HHI | top vendor | top share | concentrated | savings/yr |", "|---|---|---|---|---|---|---|---|"]
            for c in sp["categories"]:
                lines.append(f"| {c['category']} | {A.inr(c['spend'])} | {c['vendors']} | {c['hhi']} | {c['top_vendor']} | "
                             f"{c['top_share']:.0%} | {'YES' if c['concentration_flag'] else 'no'} | {A.inr(c['savings_opportunity'])} |")
            lines.append("Top vendors by spend:")
            for v in sp["vendors"][:8]:
                lines.append(f"- {v['vendor_name']} ({v['category']}): {A.inr(v['spend_total'])}, {v['share']:.1%} share, price variance {v['price_variance_pct']:+.1f}%")
            return "\n".join(lines)
        return self.run_traced(go)


# -------------------------------------------------------------- 5 forecast
class _FcArgs(BaseModel):
    vendor_name: Optional[str] = Field(None, description="Optional vendor; omit for all vendors")


class ForecastTool(_CtxTool):
    name: str = "forecast_performance"
    description: str = ("Projects each vendor's on-time % and defect % for the next 3 months using a damped linear trend "
                        "with 80% prediction bands; flags projected breaches of the on-time floor and defect ceiling.")
    args_schema: type[BaseModel] = _FcArgs

    def _run(self, vendor_name: str | None = None, **_: Any) -> str:
        def go(vendor_name=None) -> str:
            fc = A.forecast(self.ctx.df, otd_floor=self.ctx.otd_floor, defect_ceiling=self.ctx.defect_ceiling)
            if vendor_name:
                fc = [f for f in fc if vendor_name.lower()[:10] in f["vendor_name"].lower()] or fc
            lines = [f"Thresholds: on-time floor {self.ctx.otd_floor}%, defect ceiling {self.ctx.defect_ceiling}%. Horizon: {fc[0]['future_months']}",
                     "| vendor | outlook | OTD slope/mo | OTD next 3m | OTD low band | defect next 3m | OTD breach | defect breach |",
                     "|---|---|---|---|---|---|---|---|"]
            fc = sorted(fc, key=lambda f: (f["outlook"] != "deteriorating", not f["otd_breach"], f["otd"]["slope_per_month"]))
            for f in fc:
                lines.append(f"| {f['vendor_name']} | {f['outlook']} | {f['otd']['slope_per_month']:+.2f} | {f['otd']['forecast']} | "
                             f"{min(f['otd']['lower']):.1f} | {f['defect']['forecast']} | {'YES' if f['otd_breach'] else 'no'} | "
                             f"{'YES' if f['defect_breach'] else 'no'} |")
            return "\n".join(lines)
        return self.run_traced(go, vendor_name=vendor_name)


# ---------------------------------------------------------- 6 market search
class _SearchArgs(BaseModel):
    queries: list[str] = Field(..., description="1-8 search queries run in parallel, e.g. ['steel prices supply India', 'Chennai port logistics disruption']")


def _news(query: str) -> list[dict[str, Any]]:
    try:
        from ddgs import DDGS
    except ImportError:
        return []
    for _ in range(2):
        try:
            raw = DDGS().news(query, max_results=4, region="in-en", timelimit="m")
            today = time.strftime("%Y-%m-%d")
            return [{"title": r.get("title", ""), "source": r.get("source", ""),
                     "date": d if (d := (r.get("date") or "")[:10]) <= today else "",
                     "snippet": (r.get("body") or "")[:160], "url": r.get("url", "")} for r in raw]
        except Exception:
            time.sleep(1.0)
    return []


class MarketIntelSearchTool(_CtxTool):
    name: str = "market_intel_search"
    description: str = ("Live web news search (last 30 days) for supply-chain risk signals: price moves, shortages, "
                        "regulation, strikes, weather, port/logistics disruption. Accepts a LIST of queries and runs them "
                        "in parallel. Returns dated headlines with sources, grouped by query.")
    args_schema: type[BaseModel] = _SearchArgs

    def _run(self, queries: list[str] | str | None = None, query: str | None = None, **_: Any) -> str:
        qs = queries if isinstance(queries, list) else [q for q in [queries, query] if q]
        qs = [q.strip() for q in qs if q and q.strip()][:8]

        def go(queries=None) -> str:
            from concurrent.futures import ThreadPoolExecutor
            todo = []
            with self.ctx._lock:
                for q in qs:
                    if q.lower() not in self.ctx._search_cache:
                        todo.append(q)
            with ThreadPoolExecutor(max_workers=min(8, len(todo) or 1)) as ex:
                fetched = dict(zip(todo, ex.map(_news, todo)))
            blocks = []
            with self.ctx._lock:
                for q, res in fetched.items():
                    self.ctx._search_cache[q.lower()] = res
                    for r in res:
                        if r["url"] and all(r["url"] != s["url"] for s in self.ctx.sources):
                            self.ctx.sources.append({**r, "query": q})
                for q in qs:
                    res = self.ctx._search_cache.get(q.lower(), [])
                    if not res:
                        blocks.append(f"## {q}\nNo recent news found. Treat as baseline risk (no specific signal).")
                    else:
                        lines = [f"[{r['date']}] {r['title'][:110]} ({r['source']}) - {r['snippet'][:130]} <{r['url'][:120]}>" for r in res[:3]]
                        blocks.append(f"## {q}\n" + "\n".join(lines))
            return "\n\n".join(blocks)
        return self.run_traced(go, queries=qs)


# ---------------------------------------------------------- 7 alternatives
class AlternativeSourcingTool(_CtxTool):
    name: str = "find_alternatives"
    description: str = ("For a vendor, finds alternative suppliers in the same category ranked by score, spare capacity "
                        "(headroom) and risk, with how much spend each could absorb.")
    args_schema: type[BaseModel] = _VendorArgs

    def _run(self, vendor_name: str = "", **_: Any) -> str:
        def go(vendor_name="") -> str:
            alts = A.alternatives(self.ctx.scored, vendor_name)
            if not alts:
                return f"No alternatives found for '{vendor_name}' (unknown vendor or sole supplier in category)."
            return json.dumps(alts)
        return self.run_traced(go, vendor_name=vendor_name)


# --------------------------------------------------------------- 8 what-if
class _WhatIfArgs(BaseModel):
    weights_json: str = Field(..., description='JSON of pillar weights, e.g. {"delivery":50,"quality":20,"cost":10,"responsiveness":5,"compliance":15}')


class ScenarioTool(_CtxTool):
    name: str = "scenario_rescore"
    description: str = ("Re-scores all vendors under an alternative weighting scenario and reports which vendors change rank "
                        "or tier. Use to test whether a recommendation is robust to different business priorities.")
    args_schema: type[BaseModel] = _WhatIfArgs

    def _run(self, weights_json: str = "{}", **_: Any) -> str:
        def go(weights_json="{}") -> str:
            try:
                w = json.loads(weights_json)
            except json.JSONDecodeError:
                return "weights_json must be valid JSON."
            base = self.ctx.scored.set_index("vendor_name")
            alt = A.score(self.ctx.kpis, w).set_index("vendor_name")
            rows = []
            for v in alt.index:
                rows.append((v, int(base.loc[v, "rank"]), int(alt.loc[v, "rank"]), base.loc[v, "tier"], alt.loc[v, "tier"],
                             round(float(alt.loc[v, "composite"]), 1)))
            moved = [r for r in rows if abs(r[1] - r[2]) >= 2 or r[3] != r[4]]
            out = [f"Scenario weights: {w}. {len(moved)} vendors materially change (>=2 ranks or tier):"]
            out += [f"- {v}: rank {a}->{b}, tier {ta}->{tb}, score {s}" for v, a, b, ta, tb, s in moved] or ["- none (ranking is robust)"]
            return "\n".join(out)
        return self.run_traced(go, weights_json=weights_json)


def make_tools(ctx: RunContext, agent_label: str, names: list[str]) -> list[BaseTool]:
    reg = {
        "audit": DataQualityTool, "scorecard": VendorScorecardTool, "profile": VendorProfileTool,
        "spend": SpendAnalyticsTool, "forecast": ForecastTool, "search": MarketIntelSearchTool,
        "alternatives": AlternativeSourcingTool, "scenario": ScenarioTool,
    }
    return [reg[n](ctx=ctx, agent_label=agent_label) for n in names]
