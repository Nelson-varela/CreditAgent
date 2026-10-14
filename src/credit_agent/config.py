"""Runtime configuration.

Defaults live here, overridable through environment variables or `.env`
(names are case-insensitive: ``AS_OF_DATE`` sets ``as_of_date``).

Business thresholds (income tolerance, DTI limit, document age limits, ...) do NOT
live here: they belong to ``data/policies/policy_v1.yaml``, the single source of truth.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Simulated identities accepted in the `X-User-Id` header (see docs/decisions.md).
ANALYST_IDS: tuple[str, ...] = ("analyst_1", "analyst_2")


class ModelPrice(BaseModel):
    """USD per 1M tokens for one Bedrock model."""

    input_per_mtok_usd: float
    output_per_mtok_usd: float


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- AWS ---
    aws_profile: str = "credit-agent"
    aws_region: str = "us-east-2"

    # --- Reference date: every age-based rule is computed against this, never "today" ---
    as_of_date: date = date(2026, 6, 30)
    policy_path: Path = REPO_ROOT / "data" / "policies" / "policy_v1.yaml"

    # --- Orchestrator / session limits ---
    max_tool_steps: int = 6
    request_time_budget_s: int = 30
    session_token_budget: int = 20_000
    session_ttl_min: int = 30
    history_turns: int = 6

    # --- Extraction ---
    textract_min_confidence: float = 0.8

    # --- Model gateway ---
    # Must stay below request_time_budget_s so a slow call cannot eat the whole request.
    llm_timeout_s: int = 20
    max_retries: int = 3
    circuit_breaker_failures: int = 5

    # --- Batch pipeline / API ---
    batch_concurrency: int = 4
    rate_limit: str = "30/minute"

    # --- Semantic cache (Tier 2). Initial guess, to be tuned against policy_qa.jsonl ---
    cache_similarity_threshold: float = 0.92

    # --- Prices, always from the official pricing sources and dated by `pricing_checked_on`.
    # Model prices stay empty until the gateway pins model IDs. A missing price must fail
    # loudly instead of silently reporting a cost of zero. ---
    pricing_checked_on: date | None = date(2026, 10, 14)
    model_prices: dict[str, ModelPrice] = {}
    # Textract synchronous AnalyzeDocument, US East (Ohio), from the official AWS Price List API
    # (publication 2026-09-11). Key = "+".join(sorted lower-case features).
    textract_price_per_page_usd: dict[str, float] = {
        "forms": 0.05,
        "queries": 0.015,
        "forms+queries": 0.055,
    }

    # --- Langfuse ---
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    def model_price(self, model_id: str) -> ModelPrice:
        try:
            return self.model_prices[model_id]
        except KeyError:
            raise KeyError(
                f"No price configured for model '{model_id}'. "
                "Add it to model_prices with a pricing_checked_on date."
            ) from None


@lru_cache
def get_settings() -> Settings:
    return Settings()
