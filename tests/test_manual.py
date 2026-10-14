import io
import re

import pytest
from pypdf import PdfReader

from credit_agent.finance import monthly_installment
from credit_agent.generator.manual import build_manual, worked_examples
from credit_agent.policy import Policy, load_policy


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy()


@pytest.fixture(scope="module")
def pdf(policy: Policy) -> tuple[bytes, int]:
    buffer = io.BytesIO()
    pages = build_manual(policy, buffer)
    return buffer.getvalue(), pages


def _text(data: bytes) -> str:
    return " ".join(
        " ".join((page.extract_text() or "").split()) for page in PdfReader(io.BytesIO(data)).pages
    )


def test_manual_has_between_8_and_12_pages(pdf: tuple[bytes, int]) -> None:
    data, pages = pdf
    assert 8 <= pages <= 12
    assert len(PdfReader(io.BytesIO(data)).pages) == pages


def test_every_rule_text_and_id_is_in_the_manual(policy: Policy, pdf: tuple[bytes, int]) -> None:
    text = _text(pdf[0])
    for rule in policy.rules:
        assert rule.rule_id in text
        assert " ".join(policy.render(rule.rule_id).split()) in text, rule.rule_id


def test_manual_states_version_and_key_parameters(policy: Policy, pdf: tuple[bytes, int]) -> None:
    text = _text(pdf[0])
    assert f"v{policy.policy_version}" in text
    assert "$25,000" in text and "10%" in text and "40%" in text and "1.00% per month" in text


def test_worked_examples_are_computed_from_the_policy(policy: Policy) -> None:
    examples = dict(worked_examples(policy))
    expected = monthly_installment(15_000, 36, policy.parameters.monthly_interest_rate)
    assert f"${expected:,.2f}" in examples["Installment (R-5.2)"]
    assert "$5,500.00" in examples["Income tolerance (R-3.1, R-3.2)"]
    assert "$25,001" in examples["Mandatory review (R-6.1)"]


def test_manual_has_no_leftover_template_placeholders(pdf: tuple[bytes, int]) -> None:
    assert not re.search(r"\{[a-z_]+(:[^}]*)?\}", _text(pdf[0]))


def test_manual_is_byte_deterministic(policy: Policy, pdf: tuple[bytes, int]) -> None:
    again = io.BytesIO()
    build_manual(policy, again)
    assert again.getvalue() == pdf[0]
