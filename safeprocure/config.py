"""Model roster and runtime configuration for Safe Procure.

API keys are read from environment variables only (GROQ_API_KEY, GEMINI_API_KEY).
They are never written to disk by this package.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

GROQ_BASE = "https://api.groq.com/openai/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass(frozen=True)
class Endpoint:
    """One concrete model on one provider."""

    provider: str          # "groq" | "gemini"
    model: str
    tpm: int               # tokens-per-minute budget we pace against
    label: str             # short display name for the UI
    rpm: int = 25          # requests-per-minute budget we pace against
    latency: float = 3.0   # typical seconds per call (measured), used for latency-aware routing

    @property
    def base_url(self) -> str:
        return GROQ_BASE if self.provider == "groq" else GEMINI_BASE

    @property
    def api_key(self) -> str | None:
        env = "GROQ_API_KEY" if self.provider == "groq" else "GEMINI_API_KEY"
        return os.environ.get(env) or None

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}"


# Measured on this account (2026-10-02):
#   Groq: every model returns x-ratelimit-limit-tokens 8000/min and 1000 requests/day.
#   Gemini free tier: gemini-3.x-flash allows only 20 requests/day/model (error detail
#   GenerateRequestsPerDayPerProjectPerModel-FreeTier), so Flash is a last resort.
#   Flash-Lite and Gemma 4 accept tool calls and have larger free quotas
#   (exact RPM/TPM for these is UNVERIFIED - paced conservatively below).
# Gemma 4 measured 25-90 s per call (and empty replies), so it is kept only as a last resort.
# Each model has its own bucket, so giving parallel agents different primary models
# multiplies throughput instead of making them queue behind one another.
GROQ_120B = Endpoint("groq", "openai/gpt-oss-120b", 7000, "GPT-OSS 120B", 28, 2.5)
GROQ_QWEN = Endpoint("groq", "qwen/qwen3.8-27b", 7000, "Qwen 3.8 27B", 28, 1.5)
GROQ_20B = Endpoint("groq", "openai/gpt-oss-20b", 7000, "GPT-OSS 20B", 28, 1.5)
GEMMA_26B = Endpoint("gemini", "gemma-4-26b-a4b-it", 14_000, "Gemma 4 26B", 24, 25.0)
GEMMA_31B = Endpoint("gemini", "gemma-4-31b-it", 14_000, "Gemma 4 31B", 24, 35.0)
GEMINI_LITE = Endpoint("gemini", "gemini-3.1-flash-lite", 200_000, "Gemini 3.1 Flash-Lite", 12, 6.0)
GEMINI_FLASH = Endpoint("gemini", "gemini-3.8-flash", 200_000, "Gemini 3.8 Flash", 4, 15.0)

ENDPOINTS = (GROQ_120B, GROQ_QWEN, GROQ_20B, GEMMA_26B, GEMMA_31B, GEMINI_LITE, GEMINI_FLASH)


@dataclass(frozen=True)
class Tier:
    """An ordered failover chain. The first healthy endpoint with budget wins."""

    name: str
    chain: tuple[Endpoint, ...] = field(default_factory=tuple)


TIERS: dict[str, Tier] = {
    # Each agent has a "home" model (first entry). Agents that run at the same time get
    # different homes so they never queue behind each other.
    "intake": Tier("intake", (GROQ_20B, GEMINI_LITE, GROQ_QWEN)),
    # Flash-Lite hallucinated vendor names in tests, so it only leads tasks that do not name vendors.
    "lite": Tier("lite", (GEMINI_LITE, GROQ_20B, GROQ_QWEN, GROQ_120B, GEMMA_26B)),  # Gemma: last resort only
    "analysis_b": Tier("analysis_b", (GROQ_120B, GROQ_QWEN, GROQ_20B, GEMINI_LITE)),
    "analysis": Tier("analysis", (GROQ_QWEN, GROQ_120B, GROQ_20B, GEMINI_LITE)),
    "research": Tier("research", (GROQ_20B, GEMINI_LITE, GROQ_QWEN, GROQ_120B)),
    "reasoning": Tier("reasoning", (GROQ_120B, GROQ_QWEN, GEMINI_LITE, GEMINI_FLASH)),
    # Independent reviewer: a different model family from the strategist
    "review": Tier("review", (GROQ_QWEN, GROQ_120B, GROQ_20B, GEMINI_LITE)),
}


def keys_status() -> dict[str, bool]:
    return {
        "groq": bool(os.environ.get("GROQ_API_KEY")),
        "gemini": bool(os.environ.get("GEMINI_API_KEY")),
    }


DEFAULT_WEIGHTS = {
    "delivery": 30,
    "quality": 25,
    "cost": 20,
    "responsiveness": 10,
    "compliance": 15,
}
