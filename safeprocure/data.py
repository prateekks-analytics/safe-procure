"""Vendor performance data: synthetic generator + upload normaliser.

All vendor names are fictional. The generator plants realistic business patterns
(a deteriorating supplier, a cheap-but-defective supplier, spend concentration,
compliance trouble, a recovering supplier) plus a few data-quality defects, so the
agents have genuine findings to discover rather than a uniform table.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd

CATEGORIES = {
    "Steel & Metals": ["Apex Metalworks", "Sahyadri Steel Forge", "Kaveri Alloys", "Indus Castings", "Vajra Metal Traders"],
    "Packaging": ["NovaPack Solutions", "GreenWrap Packaging", "Shree Corrugators", "PolyShield Films", "Kraftline Boxes"],
    "Electronic Components": ["Vidyut Components", "Quantix Electronics", "Circuitra Systems", "Pinnacle Semicon Traders", "Nexa PCB Works"],
    "Logistics & Freight": ["SwiftHaul Logistics", "Bharat Freight Lines", "Coastal Cargo Movers", "TransEast Carriers", "Ghat Road Express"],
    "Chemicals & Plastics": ["Rasayan Chemicals", "Polymer Hub India", "AquaResin Industries", "Zenith Specialty Chem", "Narmada Polymers"],
}
REGIONS = ["Pune, Maharashtra", "Chennai, Tamil Nadu", "Delhi NCR", "Kolkata, West Bengal", "Ahmedabad, Gujarat"]

COLUMNS = [
    "vendor_id", "vendor_name", "category", "region", "month", "po_count", "po_value_inr",
    "on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days", "price_variance_pct",
    "response_time_hrs", "compliance_incidents", "capacity_utilization_pct",
]
KPI_COLUMNS = ["on_time_pct", "fill_rate_pct", "defect_rate_pct", "lead_time_days", "price_variance_pct",
               "response_time_hrs", "compliance_incidents", "capacity_utilization_pct"]

ARCHETYPES = {
    "star":          dict(otd=96, defect=0.6, lead=0.85, pv=0.5, resp=6, comp=0.02, util=78),
    "steady":        dict(otd=91, defect=1.3, lead=1.0, pv=1.5, resp=14, comp=0.05, util=70),
    "deteriorating": dict(otd=94, defect=1.0, lead=1.0, pv=1.0, resp=10, comp=0.05, util=93),
    "cheap_poor":    dict(otd=84, defect=4.2, lead=1.1, pv=-4.0, resp=30, comp=0.12, util=65),
    "premium":       dict(otd=97, defect=0.4, lead=0.9, pv=7.5, resp=5, comp=0.0, util=60),
    "compliance":    dict(otd=89, defect=1.8, lead=1.05, pv=0.0, resp=20, comp=0.55, util=72),
    "improving":     dict(otd=78, defect=3.2, lead=1.2, pv=2.0, resp=26, comp=0.1, util=58),
    "volatile":      dict(otd=86, defect=2.2, lead=1.15, pv=3.0, resp=22, comp=0.15, util=68),
}
BASE_LEAD = {"Steel & Metals": 21, "Packaging": 9, "Electronic Components": 35,
             "Logistics & Freight": 4, "Chemicals & Plastics": 14}
BASE_SPEND = {"Steel & Metals": 5.2e6, "Packaging": 1.4e6, "Electronic Components": 4.1e6,
              "Logistics & Freight": 1.9e6, "Chemicals & Plastics": 2.3e6}


@dataclass
class GenSpec:
    n_vendors: int = 20
    months: int = 18
    categories: tuple[str, ...] = tuple(CATEGORIES)
    seed: int = 42
    end_month: str = "2026-09"
    inject_quality_issues: bool = True


def generate(spec: GenSpec | None = None) -> pd.DataFrame:
    spec = spec or GenSpec()
    rng = np.random.default_rng(spec.seed)
    cats = [c for c in spec.categories if c in CATEGORIES] or list(CATEGORIES)
    per_cat = max(2, min(5, round(spec.n_vendors / len(cats))))
    end = pd.Period(spec.end_month, "M")
    months = [str(end - i) for i in range(spec.months - 1, -1, -1)]

    # Make sure the headline archetypes always appear, then fill with a realistic mix.
    must = ["deteriorating", "cheap_poor", "star", "compliance", "improving", "premium"]
    pool = ["steady", "steady", "star", "volatile", "steady", "premium", "volatile"]
    rows, vid = [], 0
    archetype_of: dict[str, str] = {}
    for ci, cat in enumerate(cats):
        names = CATEGORIES[cat][:per_cat]
        # one vendor per category dominates spend (concentration risk in some categories)
        shares = rng.dirichlet(np.ones(len(names)) * 1.4)
        if ci % 2 == 0:
            shares = np.sort(shares)[::-1]
            shares[0] += 0.25
            shares /= shares.sum()
        for vi, name in enumerate(names):
            vid += 1
            arche = must[(vid - 1)] if vid - 1 < len(must) else pool[int(rng.integers(len(pool)))]
            archetype_of[name] = arche
            a = ARCHETYPES[arche]
            region = REGIONS[int(rng.integers(len(REGIONS)))]
            monthly_spend = BASE_SPEND[cat] * shares[vi]
            n = len(months)
            for mi, month in enumerate(months):
                prog = mi / max(1, n - 1)                 # 0 -> 1 across the window
                late = max(0.0, (mi - (n - 7)) / 6)       # 0 until last 6 months, then 0 -> 1
                otd, defect, pv, resp, comp_rate, util = a["otd"], a["defect"], a["pv"], a["resp"], a["comp"], a["util"]
                if arche == "deteriorating":
                    otd -= 24 * late ** 1.3
                    defect += 2.6 * late
                    resp += 18 * late
                    util = min(99, util + 5 * late)
                elif arche == "improving":
                    otd += 15 * prog
                    defect -= 2.2 * prog
                    resp -= 14 * prog
                elif arche == "compliance" and mi >= n - 5:
                    comp_rate += 0.6
                noise = 2.6 if arche == "volatile" else 1.1
                season = 1.6 * np.sin(2 * np.pi * (int(month[-2:]) - 6) / 12)   # monsoon dip Jun-Sep
                otd_v = float(np.clip(otd + rng.normal(0, noise * 1.6) - (season if "Logistics" in cat else season * 0.4), 40, 100))
                defect_v = float(np.clip(defect + rng.normal(0, noise * 0.28), 0.05, 15))
                lead_v = float(max(1, BASE_LEAD[cat] * a["lead"] * (1 + (100 - otd_v) / 160) + rng.normal(0, BASE_LEAD[cat] * 0.06)))
                pv_v = float(pv + rng.normal(0, noise * 0.9))
                resp_v = float(max(1, resp + rng.normal(0, noise * 2.2)))
                comp_v = int(rng.poisson(max(0.0, comp_rate)))
                spend = float(max(5e4, monthly_spend * (1 + 0.12 * np.sin(mi / 2.0)) * rng.lognormal(0, 0.12)))
                po_count = int(max(1, round(spend / rng.uniform(1.6e5, 3.4e5))))
                fill_v = float(np.clip(otd_v + rng.normal(4, 2), 50, 100))
                rows.append([f"V{vid:03d}", f"{name} Pvt Ltd", cat, region, month, po_count, round(spend, -2),
                             round(otd_v, 1), round(fill_v, 1), round(defect_v, 2), round(lead_v, 1), round(pv_v, 2),
                             round(resp_v, 1), comp_v, round(float(np.clip(util + rng.normal(0, 3), 20, 100)), 1)])

    df = pd.DataFrame(rows, columns=COLUMNS)
    if spec.inject_quality_issues and len(df) > 40:
        idx = rng.choice(df.index, size=6, replace=False)
        df.loc[idx[:3], "defect_rate_pct"] = np.nan                       # missing values
        df.loc[idx[3], "lead_time_days"] = df.loc[idx[3], "lead_time_days"] * 18   # data-entry outlier
        df.loc[idx[4], "po_value_inr"] = -abs(df.loc[idx[4], "po_value_inr"])        # sign error
        df = pd.concat([df, df.loc[[idx[5]]]], ignore_index=True)                    # duplicate row
    df.attrs["archetypes"] = {f"{k} Pvt Ltd": v for k, v in archetype_of.items()}
    return df


# ------------------------------------------------------------------ uploads
ALIASES = {
    "vendor_name": ["vendor", "supplier", "supplier_name", "vendor name", "name", "company"],
    "vendor_id": ["supplier_id", "id", "vendor code", "vendor_code", "supplier code"],
    "category": ["commodity", "category_name", "segment", "material_group"],
    "region": ["location", "city", "state", "geography", "zone"],
    "month": ["period", "date", "month_year", "po_month"],
    "po_value_inr": ["spend", "po_value", "value", "amount", "spend_inr", "purchase_value"],
    "po_count": ["orders", "po_count", "number_of_pos", "pos"],
    "on_time_pct": ["otd", "otd_pct", "on_time", "on_time_delivery", "on time delivery %", "otd %", "delivery_pct"],
    "fill_rate_pct": ["fill_rate", "fill rate", "infull_pct"],
    "defect_rate_pct": ["defect", "defects", "defect_rate", "rejection_rate", "rejection %", "quality_defect_pct"],
    "lead_time_days": ["lead_time", "lead time", "leadtime"],
    "price_variance_pct": ["price_variance", "ppv", "price variance %", "cost_variance"],
    "response_time_hrs": ["response_time", "response hrs", "responsiveness_hrs"],
    "compliance_incidents": ["compliance", "incidents", "non_compliance", "audit_findings"],
    "capacity_utilization_pct": ["capacity", "utilization", "capacity_utilisation", "utilisation"],
}
NEUTRAL = {"po_count": 1, "fill_rate_pct": None, "lead_time_days": 14.0, "price_variance_pct": 0.0,
           "response_time_hrs": 24.0, "compliance_incidents": 0, "capacity_utilization_pct": 70.0}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.strip().lower()).strip("_")


def normalise_upload(raw: bytes, filename: str = "upload.csv") -> tuple[pd.DataFrame, list[str]]:
    """Map arbitrary column names onto the Safe Procure schema. Returns (df, notes)."""
    if filename.lower().endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(raw))
    else:
        df = pd.read_csv(io.BytesIO(raw))
    notes: list[str] = []
    lookup = {_norm(c): c for c in df.columns}
    mapping = {}
    for target, alts in ALIASES.items():
        for cand in [target] + alts:
            if _norm(cand) in lookup:
                mapping[lookup[_norm(cand)]] = target
                break
    df = df.rename(columns=mapping)
    if "vendor_name" not in df.columns:
        raise ValueError("Could not find a vendor/supplier name column.")
    present_kpis = [c for c in ["on_time_pct", "defect_rate_pct", "price_variance_pct", "lead_time_days"] if c in df.columns]
    if len(present_kpis) < 2:
        raise ValueError("Need at least two KPI columns (e.g. on-time %, defect %, price variance %, lead time).")
    if "month" not in df.columns:
        df["month"] = "2026-09"
        notes.append("No date column: treated all rows as a single period (trend & forecast limited).")
    else:
        df["month"] = pd.to_datetime(df["month"], errors="coerce").dt.to_period("M").astype(str)
    if "vendor_id" not in df.columns:
        ids = {n: f"V{i + 1:03d}" for i, n in enumerate(sorted(df["vendor_name"].astype(str).unique()))}
        df["vendor_id"] = df["vendor_name"].astype(str).map(ids)
    for col, default in [("category", "General"), ("region", "Unspecified")]:
        if col not in df.columns:
            df[col] = default
            notes.append(f"No {col} column: defaulted to '{default}'.")
    if "po_value_inr" not in df.columns:
        df["po_value_inr"] = 100000.0
        notes.append("No spend column: equal spend assumed for every row.")
    for col, default in NEUTRAL.items():
        if col not in df.columns:
            df[col] = df["on_time_pct"] if (col == "fill_rate_pct" and "on_time_pct" in df.columns) else default
            notes.append(f"Missing '{col}': filled with neutral default.")
    for col in ["on_time_pct", "defect_rate_pct"]:
        if col not in df.columns:
            df[col] = np.nan
            notes.append(f"Missing '{col}': pillar scored as neutral.")
    mapped = [f"{src} -> {dst}" for src, dst in mapping.items() if src != dst]
    if mapped:
        notes.insert(0, "Mapped columns: " + ", ".join(mapped))
    return df[COLUMNS], notes
