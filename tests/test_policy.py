import copy
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from credit_agent.config import get_settings
from credit_agent.policy import Policy, load_policy, parse_policy
from credit_agent.schemas import DefectType


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy()


@pytest.fixture
def raw() -> dict[str, Any]:
    with get_settings().policy_path.open(encoding="utf-8") as handle:
        return copy.deepcopy(yaml.safe_load(handle))


def test_real_policy_loads(policy: Policy) -> None:
    assert policy.policy_version == "1.0.0"
    assert policy.currency == "USD"


def test_every_defect_type_has_a_rule(policy: Policy) -> None:
    for defect in DefectType:
        assert policy.rules_for(defect), defect


def test_every_rule_renders_without_leftover_placeholders(policy: Policy) -> None:
    for rule in policy.rules:
        rendered = policy.render(rule.rule_id)
        assert "{" not in rendered and "}" not in rendered, rule.rule_id


def test_rendered_text_uses_parameter_values(policy: Policy) -> None:
    assert "10%" in policy.render("R-3.1")
    assert "40%" in policy.render("R-5.1")
    assert "1.00%" in policy.render("R-5.2")
    assert "$25,000" in policy.render("R-6.1")


def test_unknown_rule_raises(policy: Policy) -> None:
    with pytest.raises(KeyError):
        policy.rule("R-9.9")


def test_informational_rules_have_no_severity(policy: Policy) -> None:
    for rule_id in ("R-1.4", "R-2.4", "R-3.3", "R-5.2", "R-6.1", "R-7.2"):
        rule = policy.rule(rule_id)
        assert rule.defect_type is None and rule.severity is None


def test_unknown_placeholder_is_rejected(raw: dict[str, Any]) -> None:
    raw["sections"][2]["rules"][0]["text"] = "Tolerance is {not_a_parameter}."
    with pytest.raises(ValidationError, match="unknown parameters"):
        parse_policy(raw)


def test_duplicate_rule_id_is_rejected(raw: dict[str, Any]) -> None:
    raw["sections"][0]["rules"][1]["rule_id"] = "R-1.1"
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        parse_policy(raw)


def test_rule_must_live_in_its_section(raw: dict[str, Any]) -> None:
    raw["sections"][0]["rules"][0]["rule_id"] = "R-2.9"
    with pytest.raises(ValidationError, match="does not belong to section"):
        parse_policy(raw)


def test_malformed_rule_id_is_rejected(raw: dict[str, Any]) -> None:
    raw["sections"][0]["rules"][0]["rule_id"] = "rule-1"
    with pytest.raises(ValidationError, match="invalid rule_id"):
        parse_policy(raw)


def test_defect_without_severity_is_rejected(raw: dict[str, Any]) -> None:
    del raw["sections"][0]["rules"][0]["severity"]
    with pytest.raises(ValidationError, match="must be set together"):
        parse_policy(raw)


def test_uncovered_defect_type_is_rejected(raw: dict[str, Any]) -> None:
    raw["sections"][6]["rules"] = [r for r in raw["sections"][6]["rules"] if "defect_type" not in r]
    with pytest.raises(ValidationError, match="INJECTION_ATTEMPT"):
        parse_policy(raw)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("income_tolerance", 1.5),
        ("max_dti", 0),
        ("max_amount_usd", 500),  # below min_amount_usd
        ("mandatory_review_amount_usd", 200_000),  # above max_amount_usd
    ],
)
def test_invalid_parameters_are_rejected(raw: dict[str, Any], field: str, value: float) -> None:
    raw["parameters"][field] = value
    with pytest.raises(ValidationError):
        parse_policy(raw)


def test_unknown_parameter_is_rejected(raw: dict[str, Any]) -> None:
    raw["parameters"]["surprise"] = 1
    with pytest.raises(ValidationError):
        parse_policy(raw)
