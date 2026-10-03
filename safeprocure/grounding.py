"""Grounding checks for agent prose: numbers in text must trace to numbers computed in code.

* ground_percents: strips percentages that match no computed figure (forward-looking claims need computed projections).
* ground_savings: rupee savings claims must equal a computed savings figure.
* check_vendor_claims: tier and KPI claims about a named vendor are compared with that vendor's data (used by the copilot).
"""
from __future__ import annotations

import re
from typing import Any

from . import analytics as A

# Percent claims in agent prose: "8-10%", "by ~1.5%", "to >95%", "↓15%", "from 68.5%".
_N = r"\d+(?:\.\d+)?"
_PCT = re.compile(rf"(?P<pre>\b(?:by|of|to|from|at)\s+)?(?P<cmp>(?:[~≈><≥≤↑↓]=?|approx(?:imately|\.)?|about|around|up to|over|under|"
                  rf"above|below|nearly|almost)\s*)?(?P<a>{_N})(?:\s*%?\s*[-–—]\s*(?P<b>{_N})|\s+to\s+(?P<c>{_N}))?\s*(?:%|\s?percent\b)", re.I)
_PROJ_BEFORE = re.compile(r"(improv|increas|rais|rise|rising|lift|boost|reduc|cut|lower|drop|fall|decreas|declin|achiev|reach|target|"
                          r"stabili[sz]|bring|gain|grow|shrink|mitigat|expect|project|will|down|up\b|[↑↓])(?:(?!\.\s|[;:,]).)*$", re.I)
_PROJ_AFTER = re.compile(r"^\s*(reduction|improvement|increase|decrease|drop|gain|rise|lower|higher|better|faster|fewer|less|more|cut|uplift)", re.I)
_VOLUME_BEFORE = re.compile(r"(shift|realloc|mov|transfer|transition|allocat|split)\w*\s+(?:\w+\s+){0,2}$", re.I)
_VOLUME_AFTER = re.compile(r"^\s*(?:of\s+(?:\w+\s+){0,2})?(volume|share|spend)\b", re.I)


def _known(v: str, pool: set[float]) -> bool:
    """Match at the claim's own precision: '1.5' covers 1.45-1.55; '96' covers 95.5-96.99 (rounded or truncated)."""
    x, half = float(v), 0.5 * 10 ** -len(v.partition(".")[2]) + 1e-9
    return any(x - half <= k < x + (half if "." in v else 1) for k in pool)


def _tidy(s: str) -> str:
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(rf"\bfrom\s+{_N}\s*%\s*(?=[,.;:)]|\band\b|$)", "", s)   # orphaned "from X%" once its "to Y%" went
    s = re.sub(r"\b(from|to|by|of|at)\s*(?=[,.;:)]|$)", "", s)
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ,;")


def ground_percents(text: str, general: set[float], projected: set[float]) -> tuple[str, list[str]]:
    """Remove percentages that do not trace to computed numbers. Forward-looking claims (improve, reduce, ↓, '...reduction')
    may only use computed projections; plain mentions may use any computed KPI. Returns (text, removed claims)."""
    if not isinstance(text, str) or "%" not in text and "percent" not in text.lower():
        return text, []
    removed: list[str] = []

    def fix(m: re.Match) -> str:
        before = text[max(0, m.start() - 60):m.start()] + (m.group("pre") or "") + (m.group("cmp") or "")
        after = text[m.end():m.end() + 25]
        # Forward-looking: a change verb in the clause, "...% reduction", "to/by X%", or a bound ("> 95%", "~1.5%", "up to").
        proj = bool(_PROJ_BEFORE.search(before) or _PROJ_AFTER.search(after) or (m.group("cmp") or "").strip()
                    or (m.group("pre") or "").strip().lower() in ("to", "by"))
        if _VOLUME_BEFORE.search(before) or _VOLUME_AFTER.search(after):
            proj = False   # a volume share being moved, not an outcome
        pool = projected if proj else general
        vals = [x for x in (m.group("a"), m.group("b"), m.group("c")) if x]
        if all(_known(v, pool) for v in vals):
            return m.group(0)
        removed.append(m.group(0).strip())
        return " "
    out = _PCT.sub(fix, text)
    return (_tidy(out), removed) if removed else (text, [])


# ------------------------------------------------------------------ rupees
_INR = re.compile(r"(?:₹|INR|Rs\.?)\s?(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>Cr\b|crore|L\b|lakh|lac\b)?|(?P<v2>\d[\d,]*(?:\.\d+)?)\s*(?P<u2>Cr\b|crore|L\b|lakh)\s*(?:INR|rupees)?", re.I)
_SAVING = re.compile(r"sav|opportunit|captur|unlock|recover", re.I)


def parse_inr(raw: str, unit: str | None) -> float:
    v = float(raw.replace(",", ""))
    u = (unit or "").lower()
    return v * 1e7 if u in ("cr", "crore") else v * 1e5 if u in ("l", "lakh", "lac") else v


def ground_savings(text: str, allowed: list[float], replacement: float) -> tuple[str, list[str]]:
    """A rupee amount in a savings sentence must equal a computed savings figure (to its shown precision);
    otherwise it is replaced by the computed figure. Returns (text, corrected claims)."""
    if not isinstance(text, str) or not _SAVING.search(text):
        return text, []
    fixed: list[str] = []

    def fix(m: re.Match) -> str:
        raw, unit = (m.group("v"), m.group("u")) if m.group("v") else (m.group("v2"), m.group("u2"))
        left = re.split(r"[,;]|\.\s|\b(?:while|and|but|whereas)\b", text[max(0, m.start() - 70):m.start()])[-1]
        right = re.split(r"[,;]|\.\s|\.$|\b(?:while|and|but|whereas)\b", text[m.end():m.end() + 40])[0]
        if not _SAVING.search(left + right):   # only amounts in a savings clause are checked
            return m.group(0)
        val = parse_inr(raw, unit)
        step = parse_inr("0." + "0" * (len(raw.partition(".")[2]) - 1) + "5", unit) if "." in raw else parse_inr("0.5", unit) * 2
        if any(abs(val - a) <= step + 1 for a in allowed):
            return m.group(0)
        fixed.append(m.group(0).strip())
        return A.inr(replacement)
    out = _INR.sub(fix, text)
    return (out, fixed) if fixed else (text, [])


def savings_figures(result_or_cost: dict, total: float) -> list[float]:
    levers = [float(lv.get("estimated_annual_value_inr") or 0) for lv in result_or_cost.get("savings_levers", [])]
    return [total, *levers, sum(levers)]


# ------------------------------------------------------- vendor-specific claims
_METRICS = [("on_time_pct", "on-time delivery", r"on[\s-]?time|\bOTD\b|deliver"), ("defect_rate_pct", "defect rate", r"defect"),
            ("price_variance_pct", "price variance", r"price\s+variance|overpa"), ("fill_rate_pct", "fill rate", r"fill"),
            ("capacity_utilization_pct", "capacity utilisation", r"capacity|utili[sz]")]
_TIER = re.compile(r"\btier[\s-]?(?P<t>[A-D])\b|\b(?P<t2>[A-D])[\s-]tier\b")
_SCENARIO = re.compile(r"\b(would|could|if|scenario|weight\w*|re-?scor\w*|drops?|dropping|falls?|moves?|becomes?|rises?|climbs?|"
                       r"improves?|to tier|into tier)\b", re.I)
_REFERENCE = re.compile(r"\b(threshold|mark|target|floor|ceiling|limit|benchmark|standard|cut-?off|bar|criteri\w*|requirement|"
                        r"minimum|maximum|tolerance|goal)\b", re.I)
_NEGATED = re.compile(r"\b(not|nor|no|never|fails?|failing|misses|missing)\b|n't\b", re.I)
_ALL = re.compile(r"\b(both|all|each|either)\b[^.;]{0,60}$", re.I)
_UPPER = re.compile(r"[>≥]|above|over|more than|at least|exceed", re.I)
_LOWER = re.compile(r"[<≤]|below|under|less than|at most", re.I)


def _vendor_aliases(vendors: list[dict]) -> list[tuple[str, dict]]:
    """(alias, vendor) pairs: full name, name without 'Pvt Ltd', and the first word when it is unique."""
    firsts: dict[str, int] = {}
    for v in vendors:
        firsts[v["vendor"].split()[0].lower()] = firsts.get(v["vendor"].split()[0].lower(), 0) + 1
    out = []
    for v in vendors:
        short = v["vendor"].replace(" Pvt Ltd", "")
        out += [(v["vendor"], v), (short, v)]
        first = v["vendor"].split()[0]
        if firsts[first.lower()] == 1 and len(first) > 3:
            out.append((first, v))
    return sorted(out, key=lambda a: -len(a[0]))


def _mentions(sentence: str, aliases: list[tuple[str, dict]]) -> list[tuple[int, dict]]:
    found, taken = [], []
    for alias, v in aliases:
        for m in re.finditer(rf"\b{re.escape(alias)}\b", sentence, re.I):
            if not any(s <= m.start() < e for s, e in taken):
                taken.append((m.start(), m.end()))
                found.append((m.start(), v))
    return sorted(found, key=lambda x: x[0])


def _subjects(sentence: str, pos: int, mentions: list[tuple[int, dict]]) -> list[dict]:
    before = [v for p, v in mentions if p < pos]
    if not before:
        return []
    m = _ALL.search(sentence[:pos])
    if m:
        uniq = list({v["vendor"]: v for v in before}.values())
        return uniq[-2:] if m.group(1).lower() in ("both", "either") else uniq
    return [before[-1]]


def check_vendor_claims(text: str, vendors: list[dict]) -> list[str]:
    """Compare tier and KPI claims about named vendors with their data. Each vendor dict needs 'vendor', 'tier', 'kpis'.
    Returns human-readable corrections (empty when every checked claim holds)."""
    aliases = _vendor_aliases(vendors)
    issues: list[str] = []
    for sent in re.split(r"(?<=[.!?;])\s+|\n+", text or ""):
        ments = _mentions(sent, aliases)
        if not ments:
            continue
        # What-if answers move vendors between tiers ("would fall to Tier D"); KPIs never change under re-weighting.
        tier_claims = [] if _SCENARIO.search(sent) else _TIER.finditer(sent)
        for m in tier_claims:
            claimed = m.group("t") or m.group("t2")
            for v in _subjects(sent, m.start(), ments):
                if v.get("tier") and v["tier"] != claimed:
                    issues.append(f"{v['vendor']} is tier {v['tier']}, not tier {claimed}")
        for m in _PCT.finditer(sent):
            if m.group("b") or m.group("c"):
                continue
            window = sent[max(0, m.start() - 45):m.start()]
            after = re.split(r",|;|\band\b|\bwhile\b", sent[m.end():m.end() + 25])[0]   # "96% and defect..." is not about defects
            near = []   # (distance, key, label): the metric word closest to the number wins
            for key, label, pat in _METRICS:
                near += [(len(window) - h.end(), key, label) for h in re.finditer(pat, window, re.I)]
                near += [(h.start() + 1, key, label) for h in re.finditer(pat, after, re.I)]
            if not near:
                continue
            metric = min(near)[1:]
            clause = re.split(r"[,;]|\bwhich\b|\bwhile\b", window)[-1]
            if _REFERENCE.search(clause + " " + after) or _NEGATED.search(clause):
                continue   # "the 95% threshold", "does not meet 95%": a yardstick, not the vendor's own value
            x, cmp_ = float(m.group("a")), (m.group("cmp") or "") + window[-12:]
            for v in _subjects(sent, m.start(), ments):
                actual = (v.get("kpis") or {}).get(metric[0])
                if actual is None:
                    continue
                ok = (actual >= x - 0.5 if _UPPER.search(cmp_) else actual <= x + 0.05 if _LOWER.search(cmp_)
                      else _known(m.group("a"), {float(actual)}))
                if not ok:
                    issues.append(f"{v['vendor']} {metric[1]} is {actual:g}%, not {m.group(0).strip()}")
    return list(dict.fromkeys(issues))
