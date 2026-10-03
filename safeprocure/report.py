"""Self-contained executive report (single HTML file, print-ready, no external assets)."""
from __future__ import annotations

import html
from collections import Counter
from typing import Any

from .analytics import inr

DEC_COLOR = {"Keep": "#0B7A4E", "Watch": "#A85A06", "Develop": "#0A6B9E", "Replace": "#BE2A21"}


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def _short(n: str) -> str:
    return str(n).replace(" Pvt Ltd", "")


def _risk_color(r: float) -> str:
    return "#0B7A4E" if r < 25 else "#6E8F1A" if r < 40 else "#C08A05" if r < 55 else "#D7600F" if r < 70 else "#BE2A21"


def render_report(r: dict[str, Any]) -> str:
    b, qa, u = r.get("brief", {}), r.get("qa", {}), r.get("usage", {})
    vendors = [v for v in r["vendors"] if v.get("in_scope", True)]
    dec = Counter((v.get("decision") or {}).get("decision", "—") for v in vendors)
    total = sum(dec[k] for k in DEC_COLOR) or 1
    bar = "".join(f'<span style="flex:{dec[k]};background:{c}">{dec[k]}</span>' for k, c in DEC_COLOR.items() if dec[k])
    legend = " ".join(f'<i style="background:{c}"></i>{k} {dec[k]}' for k, c in DEC_COLOR.items())
    facts = "".join(f"<div><dt>{_e(k['label'])}</dt><dd>{_e(k['value'])}</dd></div>" for k in b.get("key_numbers", []))
    paras = "".join(f"<p>{_e(p)}</p>" for p in b.get("summary", []))
    actions = "".join(
        f"<tr><td class=n>{i + 1:02d}</td><td><b>{_e(a['action'])}</b></td><td>{_e(a['owner'])}</td><td>{_e(a['timeline'])}</td><td>{_e(a['impact'])}</td></tr>"
        for i, a in enumerate(b.get("top_actions", [])))
    rows = "".join(
        f"<tr><td class=n>{v['rank']}</td><td><b>{_e(_short(v['vendor']))}</b><br><small>{_e(v['category'])} · {_e(v['region'])}</small></td>"
        f"<td class=n>{v['composite']:.1f} ({v['tier']})</td>"
        f"<td class=n><span class=dot style='background:{_risk_color(v['combined_risk'])}'></span>{v['combined_risk']:.0f}</td>"
        f"<td class=n>{v['kpis']['on_time_pct']:.1f}%</td><td class=n>{v['kpis']['defect_rate_pct']:.2f}%</td>"
        f"<td class=n>{v['kpis']['price_variance_pct']:+.1f}%</td><td class=n>{_e(inr(v['spend_total']))}</td>"
        f"<td><span class=chip style='color:{DEC_COLOR.get((v.get('decision') or {}).get('decision'), '#555')}'>{_e((v.get('decision') or {}).get('decision', '—'))}</span>"
        f"<br><small>{_e((v.get('decision') or {}).get('rationale', ''))}</small></td></tr>"
        for v in sorted(vendors, key=lambda x: -x["combined_risk"]))
    plans = "".join(
        f"<div class=plan><h3>{_e(_short(p['vendor']))}</h3><p class=muted>{_e(p.get('risk'))}</p>"
        f"<p><b>Shift volume to:</b> {', '.join(f'{_e(_short(a['to_vendor']))} ({a['share_of_volume_pct']:.0f}%)' for a in p.get('alternatives', [])) or 'no qualified alternative'}</p>"
        f"<div class=phases>{''.join(f'<div><h4>{lbl}</h4><ul>' + ''.join(f'<li>{_e(x)}</li>' for x in p.get(key, [])) + '</ul></div>' for lbl, key in (('30 days', 'days_30'), ('60 days', 'days_60'), ('90 days', 'days_90')))}</div>"
        f"<p><b>Expected impact:</b> {_e(p.get('expected_impact'))}</p></div>"
        for p in r.get("mitigation", {}).get("plans", []))
    signals = "".join(
        f"<tr><td><b>{_e(s['category'] if s['category'] != 'All' else s['region'])}</b></td><td class=n>{s['risk_score']:.0f}</td><td>{_e(s.get('direction'))}</td>"
        f"<td>{_e(s.get('headline'))}<br><small>{_e(s.get('source'))} {_e(s.get('date'))}"
        + (f" · <a href='{_e(s['url'])}'>source</a>" if s.get("url") else "") + "</small></td></tr>"
        for s in sorted(r.get("market", {}).get("signals", []), key=lambda s: -s["risk_score"]))
    checks = "".join(f"<li><b>{_e(c['status'])}</b>: {_e(c['claim'])} <small>{_e(c['note'])}</small></li>" for c in qa.get("checks", []))
    grounding = "".join(f"<li>{_e(g)}</li>" for g in r.get("grounding", [])) or "<li>No ungrounded claims were found.</li>"
    models = ", ".join(f"{k.split(':', 1)[1]} ({v['calls']} calls)" for k, v in u.get("per_model", {}).items())

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Safe Procure report {_e(r['run_id'])}</title>
<style>
:root{{--ink:#15171C;--ink2:#474C58;--ink3:#676D7B;--line:#E4E1D9;--bg:#F4F3EF;--brand:#3E3AE0}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:40px 28px 60px}} .sheet{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:40px 44px;margin-bottom:18px}}
header.top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:22px;color:var(--ink3);font-size:13px}}
header.top b{{color:var(--ink);font-size:15px}} h1{{font:400 40px/1.05 Georgia,"Times New Roman",serif;letter-spacing:-.01em;margin:6px 0 16px;max-width:26ch}}
h2{{font-size:17px;margin:0 0 14px}} h3{{font-size:15px;margin:0}} h4{{font-size:12px;color:var(--ink3);margin:0 0 6px}}
.q{{color:var(--ink3);font-style:italic}} .answer{{font-size:16.5px;max-width:68ch}} p{{max-width:72ch;color:var(--ink2)}}
dl.facts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));border-top:1px solid var(--line);margin:22px 0 0}}
dl.facts div{{padding:12px 12px 0 0}} dt{{font-size:12px;color:var(--ink3)}} dd{{margin:2px 0 0;font:500 21px ui-monospace,Consolas,monospace}}
.dist{{display:flex;height:30px;border-radius:8px;overflow:hidden;gap:3px;margin:8px 0}} .dist span{{display:grid;place-items:center;color:#fff;font:600 12px ui-monospace,monospace}}
.legend i{{display:inline-block;width:9px;height:9px;border-radius:3px;margin:0 5px 0 12px}} table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;color:var(--ink3);font-weight:600;font-size:12px;border-bottom:1px solid var(--line);padding:7px 8px}} td{{border-bottom:1px solid var(--line);padding:9px 8px;vertical-align:top}}
td.n{{font-family:ui-monospace,Consolas,monospace;white-space:nowrap}} small{{color:var(--ink3)}} .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.chip{{font-weight:700}} .plan{{border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:12px}} .muted{{color:var(--ink3)}}
.phases{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:10px 0}} .phases ul{{margin:0;padding-left:18px;color:var(--ink2)}}
ul{{color:var(--ink2)}} footer{{color:var(--ink3);font-size:12px;text-align:center}}
@media print{{body{{background:#fff}} .sheet{{border:0;padding:0;break-inside:avoid-page}} main{{padding:0}}}}
@media (max-width:700px){{.sheet{{padding:24px 20px}} .phases{{grid-template-columns:1fr}} h1{{font-size:30px}}}}
</style></head><body><main>
<section class="sheet">
<header class="top"><span><b>Safe Procure</b> · Executive vendor risk brief</span><span>Run {_e(r['run_id'])} · {_e(r.get('created'))}</span></header>
<div class="q">“{_e(r.get('question') or r.get('plan', {}).get('objective'))}”</div>
<h1>{_e(b.get('headline'))}</h1>
<p class="answer">{_e(b.get('answer'))}</p>{paras}
<dl class="facts">{facts}</dl>
</section>
<section class="sheet"><h2>Decisions</h2><div class="dist">{bar}</div><div class="legend">{legend}</div>
<h2 style="margin-top:26px">Priority actions</h2><table><thead><tr><th>#</th><th>Action</th><th>Owner</th><th>Timeline</th><th>Impact</th></tr></thead><tbody>{actions}</tbody></table></section>
<section class="sheet"><h2>Vendor scorecard (sorted by combined risk)</h2><table><thead><tr><th>Rank</th><th>Vendor</th><th>Score</th><th>Risk</th><th>On-time</th><th>Defects</th><th>Price var.</th><th>Spend</th><th>Decision</th></tr></thead><tbody>{rows}</tbody></table></section>
{'<section class="sheet"><h2>Mitigation plans</h2>' + plans + '</section>' if plans else ''}
<section class="sheet"><h2>Market intelligence (live news)</h2><table><thead><tr><th>Area</th><th>Risk</th><th>Trend</th><th>Signal</th></tr></thead><tbody>{signals}</tbody></table></section>
<section class="sheet"><h2>Assurance</h2><p>Independent QA verdict: <b>{_e(qa.get('verdict'))}</b> · {r.get('revisions', 0)} revision round(s).</p><ul>{checks}</ul>
<h4 style="margin-top:16px">Grounding guard</h4><ul>{grounding}</ul>
<p class="muted">Data quality score {r['quality']['quality_score']}/100 · {u.get('llm_calls')} model calls · {u.get('total_tokens')} tokens · {u.get('failovers')} automatic failovers · {u.get('elapsed')} s. Models: {_e(models)}.</p></section>
<footer>Generated by Safe Procure, a 10-agent CrewAI workflow. Vendor names in the sample dataset are fictional.</footer>
</main></body></html>"""
