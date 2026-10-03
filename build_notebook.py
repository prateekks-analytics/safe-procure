"""Build Safe_Procure.ipynb from the real source files (single source of truth).

The notebook is self-contained for Google Colab: it writes the package and web app with
%%writefile cells, asks for API keys securely, collects dynamic input with a form, runs the
10-agent CrewAI flow with a live trace, renders an inline dashboard, and launches the full
web app inside Colab.
"""
from pathlib import Path

import nbformat as nbf

ROOT = Path(__file__).parent
PKG = ROOT / "safeprocure"
nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip("\n")))  # noqa: E731
code = lambda s, hide=False: cells.append(nbf.v4.new_code_cell(s.strip("\n"), metadata={"cellView": "form"} if hide else {}))  # noqa: E731

# ------------------------------------------------------------------ intro
md(r"""
# Safe Procure
### Multi-agent vendor risk intelligence built on CrewAI

**CrewAI final assignment · FORE School of Management · Group No. 16**  
Prateek Kumar Singh · Shardul Anil Awate · Sanatan Jain

**Business problem.** Procurement teams score suppliers on internal performance data, but the risks that stop a
production line are usually a mix of *internal* signals (slipping on-time delivery, rising defects, compliance incidents)
and *external* ones (commodity shortages, port congestion, regional disruption). Spreadsheet scorecards miss the second
half and never say *what to do*.

**Safe Procure** answers a plain-English sourcing question (for example *"Which vendors put our Q4 production at risk, and
what should we do about each one?"*) with a crew of **10 specialist agents** that audit the data, analyse performance and
spend in parallel, read **live news**, forecast next quarter, decide **Keep / Watch / Develop / Replace** for every vendor,
plan mitigation, **self-review**, and write a board-ready brief, plus a **Procurement Copilot** for follow-up questions.

| Assignment requirement | How Safe Procure meets it |
|---|---|
| Minimum 2 sub-agents | **10 agents + 1 copilot**, orchestrated with a CrewAI **Flow**: parallel fan-out, router, QA revision loop |
| Minimum 1 tool | **8 custom tools**: data audit, scorecard, vendor profile, spend analytics, forecasting, **live web news search**, alternative sourcing, scenario re-scoring |
| Dashboard / report | Inline dashboard in this notebook, a **9-tab web app** with live agent mission control, a downloadable **HTML executive report** and CSV |
| Dynamic agent input | Free-text question + form (weights, scope, thresholds, dataset size/seed) **or your own CSV/Excel upload**; the Intake agent re-plans the work for each question |
| Colab notebook | This notebook runs top to bottom and shows the workflow, sub-agents, tools, inputs and final output |

> All vendor names in the sample data are fictional. The market news is real and fetched live on every run.
""")

md(r"""
## Architecture

```
                         ┌──────────────────────┐
  your question + form ─▶│ 1  Intake Router      │  turns the request into a plan
                         └──────────┬───────────┘
                         ┌──────────▼───────────┐
                         │ 2  Data Quality Audit │  tool: audit_dataset
                         └──────────┬───────────┘
          ┌─────────────────────────┼─────────────────────────┐   (run in parallel)
┌─────────▼─────────┐   ┌───────────▼──────────┐   ┌───────────▼──────────┐
│ 3 Performance     │   │ 4 Cost & Spend       │   │ 5 Market Risk        │
│   Analyst         │   │   Analyst            │   │   Researcher         │
│ scorecard,profile │   │ spend_analytics      │   │ live news search     │
└─────────┬─────────┘   └───────────┬──────────┘   └───────────┬──────────┘
          └─────────────────────────┼─────────────────────────┘   (join: and_)
                         ┌──────────▼───────────┐
                         │ 6  Forecast Agent     │  tool: forecast_performance
                         └──────────┬───────────┘
                         ┌──────────▼───────────┐◀─────────────┐
                         │ 7  Strategist         │  scenario    │ revise (max 1)
                         └──────────┬───────────┘  re-scoring   │
                              ◇ risk gate ◇                     │
                  high risk ┌───────┴────────┐ low risk         │
                 ┌──────────▼──────────┐     │                  │
                 │ 8 Mitigation Planner │    │                  │
                 └──────────┬──────────┘     │                  │
                         ┌──▼────────────────▼──┐               │
                         │ 9  QA Reviewer (router)│──────────────┘
                         └──────────┬───────────┘  approve
                         ┌──────────▼───────────┐
                         │ 10 Executive Writer   │  board-ready brief
                         └──────────────────────┘
```

**Engineering highlights**

* **Deterministic numbers, agentic reasoning.** Every KPI, score, forecast and savings figure is computed in Python
  (pandas/numpy). Agents reason over tool outputs, so the numbers are auditable.
* **Grounding guard.** After every agent, code checks that each vendor it names exists, that savings figures stay
  within what the data supports, and that key numbers trace back to computed facts. Anything else is removed and logged.
* **Resilient multi-provider router.** Free-tier limits (measured: Groq 8,000 tokens/min per model; Gemini Flash 20
  requests/day) would stall a 10-agent crew. A custom `ResilientLLM` gives each agent a home model, paces a
  sliding-window token budget per model, skips models whose per-request ceiling is too small, and fails over across
  **5 models on 2 providers** (Groq GPT-OSS 120B/20B, Qwen 3.8, Gemini Flash-Lite, Gemma) without losing the
  conversation.
* **Self-correction.** Guardrails plus an independent QA agent on a different model family can send the strategy
  back for one revision.
""")

# ------------------------------------------------------------------ setup
md("## 1 · Setup\nInstalls the pinned libraries (about one minute on Colab).")
code(r"""
import sys, os, subprocess
IN_COLAB = "google.colab" in sys.modules
if IN_COLAB:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "crewai==1.15.23", "ddgs", "fastapi",
                    "uvicorn[standard]", "python-multipart", "plotly", "openpyxl"], check=True)
os.environ["CREWAI_TRACING_ENABLED"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.makedirs("safeprocure/web", exist_ok=True)
print("Python", sys.version.split()[0], "| Colab" if IN_COLAB else "| local")
""")

md(r"""## 2 · API keys
**For the reviewer:** keys for this submission are already filled in below, so *Runtime › Run all* works with no setup.
They are dedicated free-tier keys that will be revoked after grading.

Otherwise keys are read from **Colab Secrets** (key icon in the left sidebar: add `GROQ_API_KEY` and `GEMINI_API_KEY`),
or you are prompted with a hidden input. They are never printed or written to disk. Both providers have free tiers:
[console.groq.com](https://console.groq.com) and [aistudio.google.com](https://aistudio.google.com). One key is enough;
two give the router more capacity.""")
code(r"""
# Submission keys (dedicated free-tier keys, revoked after grading). Empty = use Colab Secrets or a prompt.
GROQ_KEY = ""
GEMINI_KEY = ""

from getpass import getpass
for name, pasted in (("GROQ_API_KEY", GROQ_KEY), ("GEMINI_API_KEY", GEMINI_KEY)):
    if os.environ.get(name):
        continue
    val = pasted.strip() or None
    if not val and IN_COLAB:
        try:
            from google.colab import userdata
            val = userdata.get(name)
        except Exception:
            val = None
    if not val:
        val = getpass(f"{name} (press Enter to skip): ").strip()
    if val:
        os.environ[name] = val
print({n: ("set" if os.environ.get(n) else "missing") for n in ("GROQ_API_KEY", "GEMINI_API_KEY")})
""")

# ------------------------------------------------------------------ source
order = [
    ("config.py", "Model roster and measured free-tier limits. Each agent gets a *home* model; agents that run in parallel get different homes."),
    ("telemetry.py", "Thread-safe event log. Every stage, tool call, model call and failover is recorded; the web app streams it live."),
    ("llm.py", "**ResilientLLM**: a CrewAI `BaseLLM` that paces token budgets, routes by latency and capacity, and fails over across providers without losing tool-calling history."),
    ("data.py", "Synthetic vendor data with realistic planted patterns (a deteriorating supplier, a cheap-but-defective one, spend concentration, compliance trouble) and data-quality defects for the auditor. Also maps arbitrary uploaded CSV/Excel columns onto the schema."),
    ("analytics.py", "Deterministic analytics engine: cleaning, spend-weighted KPIs, 5-pillar weighted scorecard, risk, Pareto/HHI spend analysis, damped-trend forecasts with 80% bands, alternative sourcing."),
    ("tools.py", "The **8 custom CrewAI tools**, including live news search that runs several queries in parallel."),
    ("schemas.py", "Pydantic output schemas: every agent returns typed, validated JSON."),
    ("agents.py", "The agent roster: role, goal, backstory, model tier and tools for each specialist."),
    ("grounding.py", "Grounding checks in code: percentages, rupee savings and vendor tier/KPI claims in agent prose must match computed numbers."),
    ("flow.py", "**SafeProcureFlow**: the CrewAI Flow with parallel fan-out (`and_`), the risk-gate `@router`, the QA revision loop, guardrails, the grounding guard and deterministic fallbacks for every stage."),
    ("copilot.py", "Procurement Copilot: a tool-using agent for follow-up questions on a finished run."),
    ("report.py", "Self-contained HTML executive report."),
    ("server.py", "FastAPI backend for the web app: datasets, what-if re-scoring, background runs, Server-Sent Events, copilot, downloads."),
]
md("## 3 · The Safe Procure package\nEach cell below writes one module. Expand a cell to read the code.")
for fname, desc in order:
    md(f"**`safeprocure/{fname}`** · {desc}")
    src = (PKG / fname).read_text(encoding="utf-8")
    code(f"%%writefile safeprocure/{fname}\n{src}", hide=True)
code('%%writefile safeprocure/__init__.py\n"""Safe Procure: multi-agent vendor risk intelligence."""', hide=True)

md("**Web app**: hand-built single-page app (no UI framework): agent mission control, 9 insight tabs, copilot. Expand to view.")
for fname in ["index.html", "styles.css", "ui.js", "graph.js", "fx.js", "orbit.js", "palette.js", "app.js", "insights.js"]:
    src = (PKG / "web" / fname).read_text(encoding="utf-8")
    code(f"%%writefile safeprocure/web/{fname}\n{src}", hide=True)

# ------------------------------------------------------------------ input
md(r"""## 4 · Dynamic input
Ask anything about your supplier base and set what matters. Change the form and re-run the cells below; the Intake
agent re-plans the analysis for every question. To use your own data, tick **Upload my own CSV / Excel**: columns such
as *Supplier, Month, OTD %, Rejection %, PPV, Spend* are mapped automatically.""")
code(r"""
import importlib, json, time
import pandas as pd
import safeprocure
from safeprocure import data as D, analytics as A
from safeprocure.config import DEFAULT_WEIGHTS
try:
    import ipywidgets as W
    from IPython.display import display, HTML
    HAVE_W = True
except ImportError:
    HAVE_W = False

form = {}
if HAVE_W:
    style = {"description_width": "150px"}
    lay = W.Layout(width="520px")
    form["question"] = W.Textarea(value="Which vendors put our Q4 production at risk, and what should we do about each one?",
                                  description="Your question", style=style, layout=W.Layout(width="760px", height="64px"))
    form["weights"] = {k: W.IntSlider(value=v, min=0, max=60, description=f"Weight: {k}", style=style, layout=lay) for k, v in DEFAULT_WEIGHTS.items()}
    form["threshold"] = W.IntSlider(value=55, min=35, max=75, description="Risk tolerance", style=style, layout=lay)
    form["otd"] = W.IntSlider(value=85, min=75, max=95, description="On-time floor %", style=style, layout=lay)
    form["defect"] = W.FloatSlider(value=3.0, min=1, max=6, step=0.5, description="Defect ceiling %", style=style, layout=lay)
    form["cats"] = W.SelectMultiple(options=list(D.CATEGORIES), value=list(D.CATEGORIES), description="Categories", style=style, layout=W.Layout(width="520px", height="110px"))
    form["n"] = W.IntSlider(value=20, min=5, max=25, description="Sample vendors", style=style, layout=lay)
    form["months"] = W.IntSlider(value=18, min=6, max=36, description="Months of history", style=style, layout=lay)
    form["seed"] = W.IntText(value=42, description="Random seed", style=style)
    form["upload"] = W.Checkbox(value=False, description="Upload my own CSV / Excel instead")
    display(W.VBox([form["question"], W.HTML("<b>What matters most</b>"), *form["weights"].values(),
                    W.HTML("<b>Scope and tolerance</b>"), form["threshold"], form["otd"], form["defect"], form["cats"],
                    W.HTML("<b>Data</b>"), form["n"], form["months"], form["seed"], form["upload"]]))
else:
    print("ipywidgets not available: defaults will be used (edit CONFIG in the next cell).")
""")

md("Read the form, load the data and preview the **instant deterministic scorecard** (before any AI is involved).")
code(r"""
def read_form():
    if not HAVE_W:
        return {"question": "Which vendors put our Q4 production at risk, and what should we do about each one?",
                "weights": dict(DEFAULT_WEIGHTS), "threshold": 55, "otd": 85, "defect": 3.0,
                "cats": list(D.CATEGORIES), "n": 20, "months": 18, "seed": 42, "upload": False}
    return {"question": form["question"].value, "weights": {k: s.value for k, s in form["weights"].items()},
            "threshold": form["threshold"].value, "otd": form["otd"].value, "defect": form["defect"].value,
            "cats": list(form["cats"].value), "n": form["n"].value, "months": form["months"].value,
            "seed": form["seed"].value, "upload": form["upload"].value}

CONFIG = read_form()
notes = []
if CONFIG["upload"] and IN_COLAB:
    from google.colab import files
    up = files.upload()
    name, raw = next(iter(up.items()))
    df_raw, notes = D.normalise_upload(raw, name)
else:
    df_raw = D.generate(D.GenSpec(n_vendors=CONFIG["n"], months=CONFIG["months"], seed=CONFIG["seed"],
                                  categories=tuple(CONFIG["cats"]) or tuple(D.CATEGORIES)))
    notes = ["Synthetic dataset: all vendor names are fictional."]

clean_df, quality = A.clean(df_raw)
preview = A.score(A.vendor_kpis(clean_df), CONFIG["weights"])
print(f"{quality['vendors']} vendors · {quality['n_months']} months · {A.inr(quality['total_spend'])} spend · "
      f"data quality {quality['quality_score']}/100 · {len(quality['issues'])} issue types auto-cleaned")
for n in notes:
    print("note:", n)
display(preview[["vendor_name", "category", "composite", "tier", "internal_risk", "on_time_pct", "defect_rate_pct",
                 "price_variance_pct", "otd_trend"]].round(2).head(20))
""")

# ------------------------------------------------------------------ run
md(r"""## 5 · Run the 10-agent crew
The trace below is the live event stream: which agent is working, which tool it calls, which model answers, and when the
router fails over. A full run takes about 1.5 to 3 minutes on free-tier models.""")
code(r"""
from safeprocure.flow import prepare_context, run_analysis
from safeprocure.telemetry import RunTelemetry

def printer(ev):
    t, kind = ev["t"], ev["type"]
    a = ev.get("agent", "")
    if kind == "stage_start":
        print(f"{t:6.1f}s  ▶ {a}")
    elif kind == "tool_start":
        args = ", ".join(f"{k}={str(v)[:50]}" for k, v in (ev.get("args") or {}).items())
        print(f"{t:6.1f}s      tool  {ev['tool']}({args})")
    elif kind == "llm_end":
        print(f"{t:6.1f}s      model {ev['model']}  {ev['prompt_tokens']}→{ev['completion_tokens']} tokens  {ev['seconds']}s")
    elif kind == "failover":
        print(f"{t:6.1f}s      router: {a} → {ev['to_model']} ({ev['reason']})")
    elif kind == "stage_end":
        out = ev.get("output") or {}
        summary = out.get("headline") or out.get("summary") or out.get("portfolio_summary") or out.get("objective") or out.get("verdict", "")
        print(f"{t:6.1f}s  ✓ {a} [{ev['status']}, {ev['seconds']}s]  {str(summary)[:150]}")
    elif kind == "route":
        print(f"{t:6.1f}s  ◇ {ev['stage']} → {ev['route']}")
    elif kind == "grounding":
        print(f"{t:6.1f}s  ⚑ grounding guard removed: {ev.get('dropped')}")

ctx = prepare_context(df_raw, weights=CONFIG["weights"], risk_threshold=CONFIG["threshold"], question=CONFIG["question"],
                      otd_floor=CONFIG["otd"], defect_ceiling=CONFIG["defect"], telemetry=RunTelemetry("colab", printer))
RESULT = run_analysis(ctx)
u = RESULT["usage"]
print(f"\nDone in {u['elapsed']} s · {u['llm_calls']} model calls · {u['total_tokens']:,} tokens · {u['failovers']} failovers · "
      f"degraded stages: {RESULT['degraded'] or 'none'}")
os.makedirs("runs", exist_ok=True)
json.dump(RESULT, open("runs/latest.json", "w"), default=str)
""")

# ------------------------------------------------------------------ results
md("## 6 · Executive brief")
code(r"""
b = RESULT["brief"]
from collections import Counter
dec = Counter((v.get("decision") or {}).get("decision") for v in RESULT["vendors"] if v["in_scope"])
html_out = f'''
<div style="font-family:system-ui;max-width:900px;border:1px solid #ddd;border-radius:14px;padding:24px 28px">
<div style="color:#777;font-style:italic">“{RESULT['question']}”</div>
<h2 style="font-family:Georgia,serif;font-weight:400;font-size:30px;margin:8px 0">{b.get('headline','')}</h2>
<p style="font-size:16px">{b.get('answer','')}</p>
{''.join(f'<p style="color:#444">{p}</p>' for p in b.get('summary', []))}
<p><b>Key numbers:</b> {' · '.join(f"{k['label']}: <b>{k['value']}</b>" for k in b.get('key_numbers', []))}</p>
<p><b>Decisions:</b> {' · '.join(f'{k} {dec.get(k, 0)}' for k in ('Keep','Watch','Develop','Replace'))}</p>
<ol>{''.join(f"<li><b>{a['action']}</b> · {a['owner']} · {a['timeline']} · {a['impact']}</li>" for a in b.get('top_actions', []))}</ol>
<p style="color:#777">QA verdict: {RESULT['qa'].get('verdict')} · revisions: {RESULT['revisions']} · grounding fixes: {len(RESULT.get('grounding', []))}</p>
</div>'''
display(HTML(html_out))
""")

md("## 7 · Inline dashboard")
code(r"""
import plotly.express as px, plotly.graph_objects as go
from plotly.subplots import make_subplots
vd = pd.DataFrame([{**{k: v[k] for k in ("vendor", "category", "composite", "internal_risk", "market_risk", "combined_risk", "spend_total")},
                    "decision": (v.get("decision") or {}).get("decision", "n/a"), **v["pillars"]} for v in RESULT["vendors"]])
colors = {"Keep": "#0B7A4E", "Watch": "#A85A06", "Develop": "#0A6B9E", "Replace": "#BE2A21", "n/a": "#999"}
th = RESULT["config"]["risk_threshold"]
fig = px.scatter(vd, x="internal_risk", y="market_risk", size="spend_total", color="decision", color_discrete_map=colors,
                 hover_name="vendor", size_max=46, range_x=[0, 100], range_y=[0, 100],
                 title="Risk matrix: internal performance risk vs live market risk (bubble = spend)")
fig.add_shape(type="line", x0=th / 0.65, y0=0, x1=(th - 35) / 0.65, y1=100, line=dict(dash="dash", color="#BE2A21"))
fig.update_layout(template="plotly_white", height=480)
fig.show()

hm = vd.sort_values("combined_risk", ascending=False)
fig = go.Figure(go.Heatmap(z=hm[["delivery", "quality", "cost", "responsiveness", "compliance"]].values, x=["Delivery", "Quality", "Cost", "Responsiveness", "Compliance"],
                           y=hm["vendor"].str.replace(" Pvt Ltd", ""), colorscale="RdYlGn", zmin=0, zmax=100, text=hm[["delivery", "quality", "cost", "responsiveness", "compliance"]].round(0).values, texttemplate="%{text}"))
fig.update_layout(title="Pillar scores (0-100) sorted by combined risk", template="plotly_white", height=620, yaxis_autorange="reversed")
fig.show()

sp = RESULT["spend"]; sv = pd.DataFrame(sp["vendors"])
fig = make_subplots(specs=[[{"secondary_y": True}]])
fig.add_bar(x=sv.vendor_name.str.replace(" Pvt Ltd", ""), y=sv.spend_total, name="Spend (INR)", marker_color="#3E3AE0")
fig.add_scatter(x=sv.vendor_name.str.replace(" Pvt Ltd", ""), y=sv.cum_share * 100, name="Cumulative %", secondary_y=True, line_color="#A85A06")
fig.update_layout(title=f"Spend Pareto: {sp['pareto_vendors_80pct']} of {sp['vendor_count']} vendors hold 80% of spend", template="plotly_white", height=440)
fig.show()

worst = sorted([v for v in RESULT["vendors"] if v.get("forecast")], key=lambda v: v["forecast"]["otd"]["slope_per_month"])[:3]
fig = go.Figure()
for v in worst:
    f = v["forecast"]; name = v["vendor"].replace(" Pvt Ltd", "")
    fig.add_scatter(x=f["history_months"], y=f["otd"]["history"], name=f"{name} (actual)")
    fig.add_scatter(x=f["future_months"], y=f["otd"]["forecast"], name=f"{name} (forecast)", line_dash="dash")
fig.add_hline(y=RESULT["config"]["otd_floor"], line_dash="dot", line_color="#BE2A21", annotation_text="on-time floor")
fig.update_layout(title="On-time delivery: 12-month history and 3-month forecast (worst trends)", template="plotly_white", height=420)
fig.show()
""")

md("### Decisions, mitigation and market intelligence")
code(r"""
table = pd.DataFrame([{"vendor": v["vendor"].replace(" Pvt Ltd", ""), "category": v["category"], "score": v["composite"], "tier": v["tier"],
                       "combined_risk": v["combined_risk"], "decision": (v.get("decision") or {}).get("decision"),
                       "rationale": (v.get("decision") or {}).get("rationale")} for v in RESULT["vendors"]]).sort_values("combined_risk", ascending=False)
def _risk_bg(v):
    c = "#E2F3EA" if v < 40 else "#FBF0DF" if v < RESULT["config"]["risk_threshold"] else "#FBE6E3"
    return f"background-color:{c}"
display(table.style.map(_risk_bg, subset=["combined_risk"]).format({"score": "{:.1f}", "combined_risk": "{:.0f}"}).hide(axis="index"))
for p in RESULT["mitigation"].get("plans", []):
    print(f"\nMitigation for {p['vendor']}: shift → " + ", ".join(f"{a['to_vendor']} ({a['share_of_volume_pct']:.0f}%)" for a in p["alternatives"]))
    for k in ("days_30", "days_60", "days_90"):
        print(f"  {k.replace('_', ' ')}: " + "; ".join(p.get(k, [])))
print("\nLive market signals:")
for s in sorted(RESULT["market"].get("signals", []), key=lambda s: -s["risk_score"]):
    print(f"  {s['risk_score']:>3.0f}  {s['category'] if s['category'] != 'All' else s['region']:<24} {s['headline'][:90]}  ({s.get('source','')} {s.get('date','')})")
print("\nGrounding guard:", RESULT.get("grounding") or "no ungrounded claims found")
""")

md("### Downloadable executive report")
code(r"""
from safeprocure.report import render_report
open("safe_procure_report.html", "w", encoding="utf-8").write(render_report(RESULT))
print("Saved safe_procure_report.html")
if IN_COLAB:
    from google.colab import files
    files.download("safe_procure_report.html")
""")

# ------------------------------------------------------------------ copilot
md("## 8 · Ask the Procurement Copilot\nA tool-using agent that re-checks numbers, runs what-if scenarios and finds alternatives. Edit the question and run again.")
code(r"""
from safeprocure.copilot import answer
q = "If delivery mattered twice as much as cost, would any vendor's decision change?"
r = answer(RESULT, q, [], ctx)
print("Q:", q, "\n\nA:", r["answer"], f"\n\n(tools used: {r['tools'] or 'none'} · models: {r['models']} · {r['seconds']} s)")
""")

# ------------------------------------------------------------------ web app
md(r"""## 9 · Launch the full web app (dashboard + live agent mission control)
Starts the FastAPI server inside this runtime and opens it in a Colab window. Everything is interactive: change data and
priorities, launch new runs and watch all 10 agents work live, explore 9 insight tabs, replay this run, and chat with the
copilot.""")
code(r"""
import threading, socket
import uvicorn
PORT = 8899
def _serve():
    uvicorn.run("safeprocure.server:app", host="0.0.0.0", port=PORT, log_level="warning")
if not any(t.name == "safe-procure" for t in threading.enumerate()):
    threading.Thread(target=_serve, name="safe-procure", daemon=True).start()
for _ in range(40):
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout=0.5).close(); break
    except OSError:
        time.sleep(0.25)
if IN_COLAB:
    from google.colab import output
    output.serve_kernel_port_as_window(PORT, anchor_text="Open Safe Procure in a new tab")
    output.serve_kernel_port_as_iframe(PORT, height=900)
else:
    print(f"Safe Procure is running at http://127.0.0.1:{PORT}")
""")

md(r"""## 10 · Business value and observations

* **From score to decision.** The output is a defended **Keep / Watch / Develop / Replace** call for every vendor, with
  owners, dates and a mitigation plan, not just a ranked list.
* **Internal and external risk in one view.** Live news shifts vendor risk: a strong supplier in a disrupted category or
  region is flagged before its own KPIs slip.
* **Early warning.** Forecasts flag vendors projected to breach the on-time floor or defect ceiling next quarter.
* **Savings with evidence.** Price-variance overpayment and concentration (HHI) analysis quantify negotiable savings,
  capped at what the data supports.
* **Trustworthy AI.** Numbers come from code; a grounding guard removes invented vendors and figures; an independent QA
  agent can force a revision; every run leaves a full audit trail of agents, tools, models and timings.
* **Resilient on free infrastructure.** Multi-provider routing keeps a 10-agent workflow inside free-tier limits
  (about 1.5 to 3 minutes per run in testing).

**Limitations.** The sample data is synthetic; external risk is scored by an LLM from news headlines (indicative, with
sources shown); forecasts are short-horizon damped linear trends with uncertainty bands, not causal models.
""")

nb["cells"] = cells
nb["metadata"] = {"colab": {"provenance": [], "toc_visible": True}, "kernelspec": {"name": "python3", "display_name": "Python 3"},
                  "language_info": {"name": "python"}}
out = ROOT / "Safe_Procure.ipynb"
nbf.write(nb, out)
print("wrote", out, len(cells), "cells")
