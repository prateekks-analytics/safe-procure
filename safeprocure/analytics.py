"""Deterministic analytics engine.

All numbers the agents reason about come from here, never from the LLM. This makes the
scorecard auditable and lets the UI recompute rankings instantly for what-if scenarios.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import DEFAULT_WEIGHTS

PILLARS = ["delivery", "quality", "cost", "responsiveness", "compliance"]


def _lin(x, lo, hi):
    """Map x linearly: lo -> 0, hi -> 100 (works for inverted ranges)."""
    return float(np.clip((x - lo) / (hi - lo) * 100, 0, 100))


# ------------------------------------------------------------------ quality
def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    d = df.copy()
    issues: list[dict[str, Any]] = []
    n0 = len(d)

    dup = d.duplicated(subset=["vendor_id", "month"], keep="first")
    if dup.any():
        issues.append({"type": "duplicate", "column": "vendor_id+month", "count": int(dup.sum()),
                       "action": "Removed duplicate vendor-month rows",
                       "examples": d.loc[dup, ["vendor_name", "month"]].astype(str).agg(" / ".join, axis=1).head(3).tolist()})
        d = d.loc[~dup]

    neg = d["po_value_inr"] < 0
    if neg.any():
        issues.append({"type": "sign_error", "column": "po_value_inr", "count": int(neg.sum()),
                       "action": "Negative spend treated as sign error (absolute value)",
                       "examples": d.loc[neg, "vendor_name"].head(3).tolist()})
        d.loc[neg, "po_value_inr"] = d.loc[neg, "po_value_inr"].abs()

    for col in ["on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days", "price_variance_pct",
                "response_time_hrs", "capacity_utilization_pct"]:
        miss = d[col].isna()
        if miss.any() and not miss.all():
            issues.append({"type": "missing", "column": col, "count": int(miss.sum()),
                           "action": "Imputed with the vendor's own median",
                           "examples": d.loc[miss, ["vendor_name", "month"]].astype(str).agg(" / ".join, axis=1).head(3).tolist()})
            d[col] = d.groupby("vendor_id")[col].transform(lambda s: s.fillna(s.median()))
            d[col] = d[col].fillna(d[col].median())

    # robust outliers: > 6 MADs from the category median
    for col in ["lead_time_days", "response_time_hrs"]:
        med = d.groupby("category")[col].transform("median")
        mad = d.groupby("category")[col].transform(lambda s: (s - s.median()).abs().median()) + 1e-9
        out = (d[col] - med).abs() / mad > 6
        if out.any():
            issues.append({"type": "outlier", "column": col, "count": int(out.sum()),
                           "action": "Capped to category median (likely data-entry error)",
                           "examples": [f"{r.vendor_name} {r.month}: {getattr(r, col):.0f}" for r in d.loc[out].head(3).itertuples()]})
            d.loc[out, col] = med[out]

    pct_cols = ["on_time_pct", "fill_rate_pct", "capacity_utilization_pct"]
    for col in pct_cols:
        bad = (d[col] < 0) | (d[col] > 100)
        if bad.any():
            issues.append({"type": "range", "column": col, "count": int(bad.sum()),
                           "action": "Clipped to 0-100", "examples": []})
            d[col] = d[col].clip(0, 100)

    affected = sum(i["count"] for i in issues)
    report = {
        "rows_in": n0, "rows_out": len(d), "vendors": int(d["vendor_id"].nunique()),
        "categories": sorted(d["category"].unique().tolist()), "regions": sorted(d["region"].unique().tolist()),
        "months": [d["month"].min(), d["month"].max()], "n_months": int(d["month"].nunique()),
        "issues": issues, "quality_score": round(max(0.0, 100 - affected / max(1, n0) * 100 * 4), 1),
        "total_spend": float(d["po_value_inr"].sum()),
    }
    return d.sort_values(["vendor_id", "month"]).reset_index(drop=True), report


# ---------------------------------------------------------------- scorecard
def _slope(s: pd.Series) -> float:
    if len(s) < 3:
        return 0.0
    x = np.arange(len(s))
    return float(np.polyfit(x, s.values.astype(float), 1)[0])


def vendor_kpis(d: pd.DataFrame, window: int = 6) -> pd.DataFrame:
    """Spend-weighted KPIs over the recent window, plus trends vs the prior window."""
    out = []
    last = sorted(d["month"].unique())
    recent = set(last[-window:])
    prior = set(last[-2 * window:-window])
    for vid, g in d.groupby("vendor_id"):
        g = g.sort_values("month")
        r = g[g["month"].isin(recent)]
        p = g[g["month"].isin(prior)]
        w = r["po_value_inr"].clip(lower=1)
        wa = lambda c: float(np.average(r[c], weights=w)) if len(r) else float("nan")  # noqa: E731
        tail = g.tail(window)
        rec = {
            "vendor_id": vid, "vendor_name": g["vendor_name"].iloc[0], "category": g["category"].iloc[0],
            "region": g["region"].iloc[0],
            "spend_total": float(g["po_value_inr"].sum()), "spend_recent": float(r["po_value_inr"].sum()),
            "po_count": int(g["po_count"].sum()),
            "on_time_pct": wa("on_time_pct"), "fill_rate_pct": wa("fill_rate_pct"),
            "defect_rate_pct": wa("defect_rate_pct"), "lead_time_days": wa("lead_time_days"),
            "price_variance_pct": wa("price_variance_pct"), "response_time_hrs": wa("response_time_hrs"),
            "compliance_incidents": int(r["compliance_incidents"].sum()),
            "compliance_incidents_total": int(g["compliance_incidents"].sum()),
            "capacity_utilization_pct": float(r["capacity_utilization_pct"].mean()),
            "otd_trend": _slope(tail["on_time_pct"]),                 # pts / month
            "defect_trend": _slope(tail["defect_rate_pct"]),           # pts / month
            "otd_delta": float(r["on_time_pct"].mean() - p["on_time_pct"].mean()) if len(p) else 0.0,
            "defect_delta": float(r["defect_rate_pct"].mean() - p["defect_rate_pct"].mean()) if len(p) else 0.0,
            "otd_volatility": float(g["on_time_pct"].tail(12).std(ddof=0)),
            "otd_series": [round(float(v), 1) for v in g["on_time_pct"].tail(12)],
            "defect_series": [round(float(v), 2) for v in g["defect_rate_pct"].tail(12)],
        }
        out.append(rec)
    k = pd.DataFrame(out)
    k["lead_rel"] = k["lead_time_days"] / k.groupby("category")["lead_time_days"].transform("median")
    return k


def score(k: pd.DataFrame, weights: dict[str, float] | None = None) -> pd.DataFrame:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    tot = sum(max(0.0, float(w[p])) for p in PILLARS) or 1.0
    wn = {p: max(0.0, float(w[p])) / tot for p in PILLARS}
    s = k.copy()
    s["delivery"] = [0.6 * _lin(o, 70, 99) + 0.2 * _lin(f, 75, 100) + 0.2 * _lin(l, 1.6, 0.8)
                     for o, f, l in zip(s.on_time_pct, s.fill_rate_pct, s.lead_rel)]
    s["quality"] = [_lin(dr, 5.0, 0.3) for dr in s.defect_rate_pct]
    s["cost"] = [_lin(pv, 10.0, -4.0) for pv in s.price_variance_pct]
    s["responsiveness"] = [_lin(r, 60, 4) for r in s.response_time_hrs]
    s["compliance"] = [max(0.0, 100 - 22 * c) for c in s.compliance_incidents]
    s["composite"] = sum(s[p] * wn[p] for p in PILLARS)
    # internal risk: inverse score + momentum + volatility penalties
    momentum = np.clip(-s["otd_trend"] * 4.0, 0, 18) + np.clip(s["defect_trend"] * 22, 0, 14)
    vol = np.clip((s["otd_volatility"] - 2.5) * 2.0, 0, 10)
    s["internal_risk"] = np.clip(100 - s["composite"] + momentum + vol, 0, 100)
    s["rank"] = s["composite"].rank(ascending=False, method="min").astype(int)
    s["tier"] = pd.cut(s["composite"], [-1, 55, 70, 82, 101], labels=["D", "C", "B", "A"]).astype(str)
    s["weights_used"] = [wn] * len(s)
    return s.sort_values("composite", ascending=False).reset_index(drop=True)


# -------------------------------------------------------------------- spend
def spend_analysis(d: pd.DataFrame, k: pd.DataFrame) -> dict[str, Any]:
    total = float(d["po_value_inr"].sum())
    by_vendor = k[["vendor_name", "category", "spend_total", "price_variance_pct"]].sort_values("spend_total", ascending=False)
    by_vendor = by_vendor.assign(share=by_vendor.spend_total / total, cum_share=by_vendor.spend_total.cumsum() / total)
    pareto_n = int((by_vendor.cum_share <= 0.8).sum() + 1)
    cats = []
    for cat, g in k.groupby("category"):
        sh = g.spend_total / g.spend_total.sum()
        top = g.loc[sh.idxmax()]
        best_pv = float(g.price_variance_pct.min())
        # savings if volume above best-in-category price variance were renegotiated halfway
        gap = ((g.price_variance_pct - best_pv).clip(lower=0) / 100 * g.spend_recent).sum()
        cats.append({
            "category": cat, "spend": float(g.spend_total.sum()), "vendors": int(len(g)),
            "hhi": round(float((sh ** 2).sum() * 10000)), "top_vendor": top.vendor_name,
            "top_share": round(float(sh.max()), 3),
            "concentration_flag": bool(sh.max() > 0.45),
            "overpay_recent": float(((g.price_variance_pct.clip(lower=0) / 100) * g.spend_recent).sum()),
            "savings_opportunity": float(gap * 0.5 * 2),   # annualised (6-month window x2) at 50% capture
        })
    cats.sort(key=lambda c: -c["spend"])
    monthly = d.groupby("month")["po_value_inr"].sum()
    return {
        "total_spend": total, "pareto_vendors_80pct": pareto_n, "vendor_count": int(len(k)),
        "categories": cats,
        "vendors": by_vendor.round(4).to_dict("records"),
        "monthly": {"months": monthly.index.tolist(), "spend": [round(float(v)) for v in monthly.values]},
        "savings_opportunity_total": float(sum(c["savings_opportunity"] for c in cats)),
        "overpay_recent_total": float(sum(c["overpay_recent"] for c in cats)),
    }


# ----------------------------------------------------------------- forecast
def forecast(d: pd.DataFrame, horizon: int = 3, otd_floor: float = 85.0, defect_ceiling: float = 3.0) -> list[dict[str, Any]]:
    res = []
    for vid, g in d.groupby("vendor_id"):
        g = g.sort_values("month").tail(12)
        x = np.arange(len(g))
        months = g["month"].tolist()
        last = pd.Period(months[-1], "M")
        fut = [str(last + i) for i in range(1, horizon + 1)]
        rec = {"vendor_id": vid, "vendor_name": g["vendor_name"].iloc[0], "category": g["category"].iloc[0],
               "history_months": months, "future_months": fut}
        for col, key in [("on_time_pct", "otd"), ("defect_rate_pct", "defect")]:
            y = g[col].values.astype(float)
            # damped trend: fit on last 12, shrink slope 30% to avoid over-extrapolation
            b1, b0 = np.polyfit(x, y, 1) if len(g) >= 3 else (0.0, float(y.mean()))
            b1 *= 0.7
            resid = y - (b0 + b1 / 0.7 * x)
            sd = float(np.std(resid, ddof=1)) if len(y) > 2 else 1.0
            xf = np.arange(len(g), len(g) + horizon)
            fitted_last = b0 + b1 / 0.7 * (len(g) - 1)
            anchor = 0.6 * y[-1] + 0.4 * fitted_last          # start from where the vendor actually is
            pred = anchor + b1 * (xf - (len(g) - 1))
            band = 1.28 * sd * np.sqrt(1 + (xf - x.mean()) ** 2 / max(1, ((x - x.mean()) ** 2).sum()))
            lo, hi = (0, 100) if key == "otd" else (0, 20)
            rec[key] = {"history": [round(float(v), 2) for v in y],
                        "forecast": [round(float(np.clip(v, lo, hi)), 2) for v in pred],
                        "lower": [round(float(np.clip(v, lo, hi)), 2) for v in pred - band],
                        "upper": [round(float(np.clip(v, lo, hi)), 2) for v in pred + band],
                        "slope_per_month": round(float(b1 / 0.7), 3)}
        rec["otd_breach"] = bool(min(rec["otd"]["forecast"]) < otd_floor)
        rec["defect_breach"] = bool(max(rec["defect"]["forecast"]) > defect_ceiling)
        rec["outlook"] = ("deteriorating" if (rec["otd"]["slope_per_month"] < -0.6 or rec["defect"]["slope_per_month"] > 0.08)
                          else "improving" if (rec["otd"]["slope_per_month"] > 0.6 or rec["defect"]["slope_per_month"] < -0.08)
                          else "stable")
        res.append(rec)
    return res


# ------------------------------------------------------------- alternatives
def alternatives(s: pd.DataFrame, vendor_name: str, top: int = 3) -> list[dict[str, Any]]:
    row = s[s.vendor_name.str.lower() == vendor_name.lower()]
    if row.empty:
        row = s[s.vendor_name.str.lower().str.contains(vendor_name.lower().split(" pvt")[0][:12], regex=False)]
    if row.empty:
        return []
    r = row.iloc[0]
    peers = s[(s.category == r.category) & (s.vendor_name != r.vendor_name)].copy()
    peers["headroom_pct"] = (92 - peers.capacity_utilization_pct).clip(lower=0)
    peers["absorbable_spend"] = peers.spend_recent * peers.headroom_pct / peers.capacity_utilization_pct.clip(lower=1)
    peers["fit"] = peers.composite * 0.7 + peers.headroom_pct * 1.2 - peers.internal_risk * 0.2
    peers = peers.sort_values("fit", ascending=False).head(top)
    return [{"vendor_name": p.vendor_name, "region": p.region, "composite": round(p.composite, 1),
             "headroom_pct": round(p.headroom_pct, 1), "absorbable_spend_6m": round(p.absorbable_spend),
             "price_variance_pct": round(p.price_variance_pct, 2), "on_time_pct": round(p.on_time_pct, 1),
             "defect_rate_pct": round(p.defect_rate_pct, 2)} for p in peers.itertuples()]


# -------------------------------------------------------------- combine
def combine_risk(s: pd.DataFrame, market: dict[str, float], ext_weight: float = 0.35) -> pd.DataFrame:
    """Blend internal risk with external market risk for each vendor's category+region."""
    out = s.copy()

    def ext(r):
        for key in (f"{r.category}|{r.region}", r.category, r.region):
            if key in market:
                return float(market[key])
        cat = [v for kk, v in market.items() if kk.startswith(r.category)]
        return float(np.mean(cat)) if cat else 35.0

    out["market_risk"] = out.apply(ext, axis=1)
    out["combined_risk"] = (1 - ext_weight) * out.internal_risk + ext_weight * out.market_risk
    return out


def table_for_llm(s: pd.DataFrame, cols: list[str], n: int = 30) -> str:
    """Compact markdown table (keeps agent prompts small)."""
    t = s[cols].head(n).copy()
    for c in t.columns:
        if t[c].dtype.kind == "f":
            t[c] = t[c].round(1)
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in t.values)


def inr(v: float) -> str:
    v = float(v)
    if abs(v) >= 1e7:
        return f"₹{v / 1e7:.2f} Cr"
    if abs(v) >= 1e5:
        return f"₹{v / 1e5:.1f} L"
    return f"₹{v:,.0f}"
