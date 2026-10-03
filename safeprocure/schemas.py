"""Structured (Pydantic) outputs for every agent. Typed outputs make the dashboard reliable."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IntakePlan(BaseModel):
    objective: str = Field(..., description="One-sentence restatement of what the user needs")
    question_type: Literal["portfolio_review", "cost_reduction", "risk_scan", "vendor_specific", "consolidation"]
    priority_pillars: list[str] = Field(default_factory=list, description="Pillars that matter most: delivery, quality, cost, responsiveness, compliance")
    vendors_of_interest: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list, description="2-4 measurable criteria for a good answer")
    instructions_for_team: str = Field(..., description="Short brief to the analyst agents on what to emphasise")


class AuditFindings(BaseModel):
    verdict: Literal["fit_for_analysis", "usable_with_caveats", "not_reliable"]
    summary: str
    caveats: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    vendor: str
    headline: str = Field(..., description="Short finding, <= 14 words")
    evidence: str = Field(..., description="Specific numbers from the tools")
    severity: Literal["positive", "low", "medium", "high", "critical"] = "medium"


class PerformanceFindings(BaseModel):
    summary: str
    top_performers: list[Finding] = Field(default_factory=list)
    underperformers: list[Finding] = Field(default_factory=list)
    trend_alerts: list[Finding] = Field(default_factory=list)


class SavingsLever(BaseModel):
    lever: str
    categories: list[str] = Field(default_factory=list)
    vendors: list[str] = Field(default_factory=list)
    estimated_annual_value_inr: float = 0
    rationale: str


class CostFindings(BaseModel):
    summary: str
    concentration_risks: list[Finding] = Field(default_factory=list)
    savings_levers: list[SavingsLever] = Field(default_factory=list)


class MarketSignal(BaseModel):
    category: str
    region: str = "All India"
    risk_score: float = Field(..., ge=0, le=100, description="0 = calm, 100 = severe disruption")
    direction: Literal["rising", "stable", "easing"] = "stable"
    headline: str
    source: str = ""
    date: str = ""
    url: str = ""
    implication: str


class MarketFindings(BaseModel):
    summary: str
    signals: list[MarketSignal] = Field(default_factory=list)


class EarlyWarning(BaseModel):
    vendor: str
    metric: Literal["on_time", "defects", "both"]
    projection: str = Field(..., description="e.g. 'OTD 80.1% -> 70.2% by 2026-12'")
    confidence: Literal["low", "medium", "high"]
    recommended_trigger: str


class ForecastFindings(BaseModel):
    summary: str
    early_warnings: list[EarlyWarning] = Field(default_factory=list)
    improving: list[str] = Field(default_factory=list)


class VendorDecision(BaseModel):
    vendor: str
    decision: Literal["Keep", "Watch", "Develop", "Replace"]
    confidence: float = Field(..., ge=0, le=1)
    rationale: str = Field(..., description="One sentence (<= 30 words) citing the decisive numbers")
    actions: list[str] = Field(default_factory=list, description="1-2 concrete next actions, <= 12 words each")


class StrategyDecision(BaseModel):
    portfolio_summary: str
    robustness_note: str = Field("", description="Result of scenario re-scoring: is the ranking robust?")
    decisions: list[VendorDecision]


class ShiftPlan(BaseModel):
    to_vendor: str
    share_of_volume_pct: float


class MitigationPlan(BaseModel):
    vendor: str
    risk: str
    alternatives: list[ShiftPlan] = Field(default_factory=list)
    days_30: list[str] = Field(default_factory=list)
    days_60: list[str] = Field(default_factory=list)
    days_90: list[str] = Field(default_factory=list)
    expected_impact: str


class MitigationFindings(BaseModel):
    summary: str
    plans: list[MitigationPlan] = Field(default_factory=list)


class QACheck(BaseModel):
    claim: str
    status: Literal["verified", "corrected", "unsupported"]
    note: str


class QAReview(BaseModel):
    verdict: Literal["approve", "revise"]
    confidence: float = Field(..., ge=0, le=1)
    checks: list[QACheck] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)


class KeyNumber(BaseModel):
    label: str
    value: str


class Action(BaseModel):
    action: str
    owner: str
    timeline: str
    impact: str


class ExecutiveBrief(BaseModel):
    headline: str = Field(..., description="<= 16 words")
    answer: str = Field(..., description="Direct answer to the user's question, 2-4 sentences")
    summary: list[str] = Field(..., description="3 short paragraphs")
    key_numbers: list[KeyNumber] = Field(default_factory=list)
    top_actions: list[Action] = Field(default_factory=list)
