from datetime import date
from decimal import Decimal

import pytest

from credit_agent.finance import debt_to_income, monthly_installment
from credit_agent.normalize import (
    addresses_equivalent,
    names_equivalent,
    normalize_address,
    normalize_date,
    normalize_id,
    normalize_money,
    normalize_name,
)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("José Antonio Muñoz", "JOSE ANTONIO MUNOZ"),  # accents and case
        ("John Adam Smith", "John A. Smith"),  # abbreviated middle name
        ("John Adam Smith", "John Smith"),  # omitted middle name
        ("Smith, John Adam", "John Adam Smith"),  # "surname, given name"
        ("Zoë O'Brien", "ZOE OBRIEN"),
        ("Mary Anne Lee-Jones", "Mary A Lee Jones"),
    ],
)
def test_legitimate_name_variations_are_equivalent(a: str, b: str) -> None:
    assert names_equivalent(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("John Adam Smith", "Jon Adam Smith"),  # different given name
        ("John Adam Smith", "John Adam Smyth"),  # different surname
        ("John Adam Smith", "John Brian Smith"),  # conflicting middle names
        ("John Adam Smith", "John B. Smith"),  # conflicting middle initial
        ("John Smith", "Smith"),
    ],
)
def test_real_name_differences_are_not_equivalent(a: str, b: str) -> None:
    assert not names_equivalent(a, b)


def test_normalize_name_reorders_and_strips() -> None:
    assert normalize_name("MUÑOZ, José A.") == "jose a munoz"


def test_id_normalization_ignores_separators_only() -> None:
    assert normalize_id("D123-456.789") == normalize_id("d123 456 789") == "D123456789"
    assert normalize_id("D123456789") != normalize_id("D123456798")  # transposed digits


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("123 Main St, Springfield, IL 62704", "123 Main Street, Springfield, IL 62704"),
        ("45 Oak Ave Apt 4B, Austin, TX 73301", "45 Oak Avenue #4B, Austin, TX 73301"),
        ("9 Elm Blvd., Denver, CO 80202", "9 elm boulevard, Denver, CO 80202"),
        ("77 N Pine Rd, Reno, NV 89501", "77 North Pine Road, Reno, NV 89501"),
    ],
)
def test_address_format_variations_are_equivalent(a: str, b: str) -> None:
    assert addresses_equivalent(a, b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("123 Main St, Springfield, IL 62704", "124 Main St, Springfield, IL 62704"),
        ("123 Main St, Springfield, IL 62704", "123 Main St, Peoria, IL 62704"),
        ("123 Main St, Springfield, IL 62704", "123 Oak St, Springfield, IL 62704"),
    ],
)
def test_different_addresses_are_not_equivalent(a: str, b: str) -> None:
    assert not addresses_equivalent(a, b)


def test_normalize_address_is_idempotent() -> None:
    once = normalize_address("45 Oak Ave Apt 4B, Austin, TX")
    assert normalize_address(once) == once


def test_money_and_dates() -> None:
    assert normalize_money("$5,200.5") == Decimal("5200.50")
    assert normalize_money("1,234") == Decimal("1234.00")
    assert normalize_date("06/15/2026") == date(2026, 6, 15)
    assert normalize_date("2026-06-15") == date(2026, 6, 15)
    assert normalize_date("June 15, 2026") == date(2026, 6, 15)
    assert normalize_date("Jun 15, 2026") == date(2026, 6, 15)
    with pytest.raises(ValueError):
        normalize_money("abc")
    with pytest.raises(ValueError):
        normalize_date("15th of June")


def test_installment_matches_known_value() -> None:
    # 10,000 over 12 months at 1% monthly: 10000*0.01 / (1 - 1.01^-12) = 888.49
    assert monthly_installment(10_000, 12, 0.01) == Decimal("888.49")


def test_installment_with_zero_rate_and_invalid_term() -> None:
    assert monthly_installment(1_200, 12, 0.0) == Decimal("100.00")
    with pytest.raises(ValueError):
        monthly_installment(1_000, 0, 0.01)


def test_debt_to_income() -> None:
    ratio = debt_to_income(Decimal("500"), Decimal("500"), Decimal("4000"))
    assert ratio == Decimal("0.25")
    with pytest.raises(ValueError):
        debt_to_income(Decimal("1"), Decimal("1"), Decimal("0"))
