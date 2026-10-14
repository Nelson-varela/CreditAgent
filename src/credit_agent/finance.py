"""Loan arithmetic defined by the policy (rules R-5.1 and R-5.2)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")


def monthly_installment(principal: Decimal | int, months: int, monthly_rate: float) -> Decimal:
    """Constant installment of a standard amortized loan: P*r / (1 - (1+r)^-n)."""
    if months <= 0:
        raise ValueError("months must be positive")
    p = Decimal(principal)
    r = Decimal(str(monthly_rate))
    if r == 0:
        return (p / months).quantize(_CENT, ROUND_HALF_UP)
    installment = p * r / (1 - (1 + r) ** -months)
    return installment.quantize(_CENT, ROUND_HALF_UP)


def debt_to_income(
    existing_monthly_debt: Decimal, installment: Decimal, verified_income: Decimal
) -> Decimal:
    """(existing monthly debt + new installment) / verified monthly income."""
    if verified_income <= 0:
        raise ValueError("verified income must be positive")
    return (existing_monthly_debt + installment) / verified_income
