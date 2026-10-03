"""The Safe Procure agent roster: 10 specialists + 1 copilot.

Each agent has a role, goal and backstory (CrewAI's persona model), a model tier
(see config.TIERS) and the tools it is allowed to use.
"""
from __future__ import annotations

from dataclasses import dataclass

from crewai import Agent

from .llm import ResilientLLM
from .tools import RunContext, make_tools


@dataclass(frozen=True)
class AgentSpec:
    key: str
    name: str
    role: str
    goal: str
    backstory: str
    tier: str
    tools: tuple[str, ...]
    max_iter: int = 6
    max_completion: int = 1800


ROSTER: dict[str, AgentSpec] = {s.key: s for s in [
    AgentSpec("intake", "Intake Router", "Procurement Intake Router",
              "Translate the user's request into a precise analysis plan the team can execute.",
              "A chief-of-staff to the CPO who turns vague asks into crisp, measurable briefs.", "intake", ()),
    AgentSpec("audit", "Data Quality Auditor", "Vendor Data Quality Auditor",
              "Decide whether the vendor dataset is reliable enough to base sourcing decisions on.",
              "An ex-internal-auditor who never lets a decision rest on dirty data.", "lite", ("audit",), 3),
    AgentSpec("performance", "Performance Analyst", "Supplier Performance Analyst",
              "Identify the best and worst performing vendors and the trends behind them, with numbers.",
              "A supplier-quality engineer who reads OTD, defect and lead-time data like an ECG.", "analysis",
              ("scorecard", "profile"), 5),
    AgentSpec("cost", "Cost & Spend Analyst", "Category Spend Analyst",
              "Find spend concentration risk and quantified savings levers.",
              "A category manager obsessed with Pareto charts, HHI and price variance.", "analysis_b", ("spend", "scorecard"), 4),
    AgentSpec("market", "Market Risk Researcher", "Supply Market Risk Researcher",
              "Score current external supply risk for each category and key region from live news.",
              "A supply-market intelligence analyst who scans news daily for disruptions before they hit the plant.",
              "research", ("search",), 4, 2200),
    AgentSpec("forecast", "Forecast Agent", "Supplier Performance Forecaster",
              "Project next-quarter vendor performance and raise early warnings before thresholds are breached.",
              "A demand-and-supply planner who trusts trends but respects uncertainty bands.", "analysis_b", ("forecast",), 4),
    AgentSpec("strategy", "Procurement Strategist", "Chief Procurement Strategist",
              "Assign every vendor a Keep / Watch / Develop / Replace decision that balances performance, cost and risk.",
              "A CPO with 20 years of sourcing experience who defends every call with evidence.", "reasoning",
              ("profile", "scenario"), 6, 3200),
    AgentSpec("mitigation", "Mitigation Planner", "Supply Risk Mitigation Planner",
              "For each high-risk vendor, design a dual-sourcing shift and a 30/60/90-day action plan.",
              "A supply-continuity lead who has rescued production lines from supplier failures.", "analysis",
              ("alternatives", "profile"), 6, 2400),
    AgentSpec("qa", "QA Reviewer", "Independent Decision QA Reviewer",
              "Verify every material claim against the data and reject recommendations the numbers do not support.",
              "A sceptical internal-audit partner. Runs on a different model family from the strategist to avoid shared blind spots.",
              "review", ("profile", "scorecard"), 6, 2200),
    AgentSpec("brief", "Executive Writer", "Executive Briefing Writer",
              "Write a board-ready brief that answers the user's question directly with numbers and actions.",
              "A former strategy consultant who writes for CFOs: short, quantified, decisive.", "reasoning", (), 3, 2400),
    AgentSpec("copilot", "Procurement Copilot", "Procurement Copilot",
              "Answer follow-up questions about this analysis accurately, using tools to check numbers.",
              "The team's always-on analyst who knows every number in the report.", "analysis",
              ("profile", "scorecard", "scenario", "alternatives"), 5),
]}

FLOW_ORDER = ["intake", "audit", "performance", "cost", "market", "forecast", "strategy", "mitigation", "qa", "brief"]


def build_agent(key: str, ctx: RunContext) -> Agent:
    s = ROSTER[key]
    llm = ResilientLLM(s.tier, s.name, telemetry=ctx.telemetry, max_completion=s.max_completion)
    return Agent(
        role=s.role, goal=s.goal, backstory=s.backstory, llm=llm,
        tools=make_tools(ctx, s.name, list(s.tools)), max_iter=s.max_iter,
        allow_delegation=False, verbose=False, respect_context_window=True,
    )
