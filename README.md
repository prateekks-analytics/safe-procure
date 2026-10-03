# Safe Procure

Multi-agent vendor risk intelligence built on [CrewAI](https://github.com/crewAIInc/crewAI).

Ask a plain-English sourcing question ("Which vendors put our Q4 production at risk, and what should we do about each one?") and a crew of 10 specialist agents audits the vendor data, analyses performance, spend and live market news, forecasts, decides **Keep / Watch / Develop / Replace** for every vendor, plans mitigation, and has an independent QA agent check the result before an executive brief is written.

CrewAI final assignment, FORE School of Management, Group No. 16: Prateek Kumar Singh, Shardul Anil Awate, Sanatan Jain.

## What is inside

| Path | What it is |
|---|---|
| `Safe_Procure.ipynb` | The full project as one notebook: setup, agents, tools, dynamic input form, live run, dashboard, report, copilot, and the web app. Saved with the outputs of a real run. |
| `safeprocure/` | The same code as a Python package: CrewAI Flow (`flow.py`), 10 agents + copilot (`agents.py`, `copilot.py`), 8 custom tools (`tools.py`), deterministic analytics, multi-provider LLM router (`llm.py`), FastAPI server and web app (`server.py`, `web/`). |
| `build_notebook.py` | Rebuilds the notebook from the package source. |
| `run_local.py` | Runs the web app locally. |
| `runs/latest.json` | A saved sample run, so the web app can show results before you run anything. |

The sample data is synthetic (fictional vendors). Market risk comes from live news search.

## API keys

Uses free-tier models from two providers; one key is enough, two give more capacity:

- `GROQ_API_KEY` from [console.groq.com](https://console.groq.com)
- `GEMINI_API_KEY` from [aistudio.google.com](https://aistudio.google.com)

Keys are never stored in this repo. Do not commit yours.

## Run in Google Colab (easiest)

1. Open [Colab](https://colab.research.google.com) → File › Upload notebook → `Safe_Procure.ipynb`.
2. Add your keys in **Secrets** (key icon in the left bar) with notebook access on, or paste them into the `GROQ_KEY` / `GEMINI_KEY` lines of the "API keys" cell (don't share the notebook afterwards).
3. Runtime › Run all (about 2–3 minutes). The last cell opens the web app.

## Run locally

Python 3.12:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
set GROQ_API_KEY=...            # macOS/Linux: export GROQ_API_KEY=...
set GEMINI_API_KEY=...
python run_local.py             # http://127.0.0.1:8765
```

Or put the keys in a `KEY=value` file outside the repo and point `SAFE_PROCURE_KEYS` at it.

## Limitations

Synthetic sample data; external risk is an LLM reading of news headlines (sources shown); forecasts are short-horizon damped trends; free-tier rate limits can slow a run.
