from datetime import date

import pytest

from credit_agent.config import ModelPrice, Settings


def test_defaults_match_spec() -> None:
    s = Settings(_env_file=None)
    assert s.max_tool_steps == 6
    assert s.session_token_budget == 20_000
    assert s.rate_limit == "30/minute"
    assert s.as_of_date == date(2026, 6, 30)
    assert s.llm_timeout_s < s.request_time_budget_s


def test_env_overrides_defaults_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AS_OF_DATE", "2026-01-15")
    monkeypatch.setenv("MAX_RETRIES", "5")
    s = Settings(_env_file=None)
    assert s.as_of_date == date(2026, 1, 15)
    assert s.max_retries == 5


def test_missing_model_price_fails_loudly() -> None:
    s = Settings(_env_file=None)
    with pytest.raises(KeyError, match="No price configured"):
        s.model_price("some.model")


def test_known_model_price_is_returned() -> None:
    price = ModelPrice(input_per_mtok_usd=1.0, output_per_mtok_usd=5.0)
    s = Settings(_env_file=None, model_prices={"m": price})
    assert s.model_price("m") == price


def test_secrets_are_not_leaked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-supersecret")
    s = Settings(_env_file=None)
    assert "supersecret" not in repr(s)
