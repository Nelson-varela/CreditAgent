"""Hard negatives: legitimate variations a good system must NOT report as defects.

Each variation keeps the file compliant with the policy (R-2.4 and boundary conventions) and is
recorded in the ground truth, so the evals can measure the hard-negative false-positive rate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import ROUND_DOWN, Decimal

from credit_agent.finance import monthly_installment
from credit_agent.generator.defects import shift_payslips
from credit_agent.generator.files import us_date
from credit_agent.generator.models import DocumentContent, HardNegativeLabel
from credit_agent.generator.mutate import (
    Ctx,
    NotApplicable,
    address_text,
    current_dti,
    name_field,
    set_address,
    set_date,
    set_money,
    set_name,
    set_text,
)
from credit_agent.generator.persona import AddressStyle, add_months
from credit_agent.normalize import strip_accents
from credit_agent.schemas import DefectType, DocType

_TITLE_STYLE = (
    DocType.APPLICATION_FORM,
    DocType.PAYSLIP,
    DocType.EMPLOYMENT_LETTER,
    DocType.UTILITY_BILL,
)


def _label(ctx: Ctx, kind: str, doc_type: DocType, field: str, description: str) -> None:
    ctx.hard_negatives.append(
        HardNegativeLabel(kind=kind, doc_type=doc_type, field=field, description=description)
    )


def _pick_name_doc(ctx: Ctx, only_title_style: bool = False) -> DocumentContent:
    candidates = [
        d
        for d in ctx.docs
        if not ctx.is_touched(d, name_field(d))
        and (not only_title_style or d.doc_type in _TITLE_STYLE)
    ]
    if not candidates:
        raise NotApplicable
    return ctx.rng.choice(candidates)


def name_accents_case(ctx: Ctx) -> None:
    p = ctx.persona
    if not p.full_name.isascii():
        doc, new = _pick_name_doc(ctx), strip_accents(p.full_name)
        what = "accents removed"
    else:
        doc, new = _pick_name_doc(ctx, only_title_style=True), p.full_name.upper()
        what = "upper case"
    set_name(ctx, doc, new)
    _label(ctx, "name_accents_case", doc.doc_type, name_field(doc), f"name printed with {what}")


def name_middle_initial(ctx: Ctx) -> None:
    p = ctx.persona
    doc = _pick_name_doc(ctx)
    set_name(ctx, doc, f"{p.first_name} {p.middle_name[0]}. {p.last_name}")
    _label(ctx, "name_middle_initial", doc.doc_type, name_field(doc), "middle name abbreviated")


def name_middle_omitted(ctx: Ctx) -> None:
    p = ctx.persona
    doc = _pick_name_doc(ctx)
    set_name(ctx, doc, f"{p.first_name} {p.last_name}")
    _label(ctx, "name_middle_omitted", doc.doc_type, name_field(doc), "middle name omitted")


def name_last_first(ctx: Ctx) -> None:
    p = ctx.persona
    doc = _pick_name_doc(ctx)
    set_name(ctx, doc, f"{p.last_name}, {p.first_name} {p.middle_name}")
    _label(ctx, "name_last_first", doc.doc_type, name_field(doc), "'Surname, Given' order")


def address_abbreviated(ctx: Ctx) -> None:
    if ctx.has_defect(DefectType.ADDRESS_MISMATCH):
        raise NotApplicable
    bill, form = ctx.doc(DocType.UTILITY_BILL), ctx.doc(DocType.APPLICATION_FORM)
    if bill is not None and not ctx.is_touched(bill, "service_address"):
        doc, field = bill, "service_address"
    elif form is not None and not ctx.is_touched(form, "address"):
        doc, field = form, "address"
    else:
        raise NotApplicable
    addr = ctx.persona.address
    hash_style = addr.unit is not None and ctx.rng.random() < 0.5
    style = AddressStyle.ABBREVIATED_HASH if hash_style else AddressStyle.ABBREVIATED
    set_address(ctx, doc, field, address_text(addr, style))
    _label(ctx, "address_abbreviated", doc.doc_type, field, f"address in {style.value} format")


def _income_variation(ctx: Ctx, kind: str, low: float, high: float) -> None:
    form = ctx.doc(DocType.APPLICATION_FORM)
    if form is None or ctx.has_defect(DefectType.INCOME_MISMATCH):
        raise NotApplicable
    if ctx.is_touched(form, "declared_monthly_income"):
        raise NotApplicable
    tol, salary = (
        Decimal(str(ctx.policy.parameters.income_tolerance)),
        ctx.persona.net_monthly_salary,
    )
    diff = tol * Decimal(str(round(ctx.rng.uniform(low, high), 3)))
    sign = 1 if ctx.rng.random() < 0.5 else -1
    new = (salary * (1 + sign * diff)).quantize(Decimal("0.01"))
    if abs(new - salary) / salary > tol:
        raise NotApplicable
    set_money(ctx, form, "declared_monthly_income", new)
    pct = f"{abs(new - salary) / salary:.2%}"
    _label(ctx, kind, DocType.APPLICATION_FORM, "declared_monthly_income", f"differs by {pct}")


def income_within_tolerance(ctx: Ctx) -> None:
    _income_variation(ctx, "income_within_tolerance", 0.3, 0.8)


def income_just_under_tolerance(ctx: Ctx) -> None:
    _income_variation(ctx, "income_just_under_tolerance", 0.9, 0.98)


def payslip_age_at_limit(ctx: Ctx) -> None:
    slips = ctx.docs_of(DocType.PAYSLIP)
    max_age = ctx.policy.parameters.payslip_max_age_days
    if (
        not slips
        or ctx.has_defect(DefectType.STALE_PAYSLIP)
        or any(ctx.doc_touched(s) for s in slips)
    ):
        raise NotApplicable
    oldest = max(
        (ctx.as_of - date.fromisoformat(s.canonical["pay_period_end"])).days for s in slips
    )
    shift_payslips(ctx, slips, max_age - oldest)
    _label(
        ctx,
        "payslip_age_at_limit",
        DocType.PAYSLIP,
        "pay_period_end",
        f"oldest payslip is exactly {max_age} days old",
    )


def utility_bill_age_at_limit(ctx: Ctx) -> None:
    bill = ctx.doc(DocType.UTILITY_BILL)
    max_age = ctx.policy.parameters.utility_bill_max_age_days
    if bill is None or ctx.is_touched(bill, "bill_date"):
        raise NotApplicable
    set_date(ctx, bill, "bill_date", ctx.as_of - timedelta(days=max_age))
    _label(
        ctx,
        "utility_bill_age_at_limit",
        DocType.UTILITY_BILL,
        "bill_date",
        f"bill is exactly {max_age} days old",
    )


def id_expires_soon(ctx: Ctx) -> None:
    id_doc = ctx.doc(DocType.ID_DOCUMENT)
    if id_doc is None or ctx.is_touched(id_doc, "expiry_date"):
        raise NotApplicable
    days = ctx.policy.parameters.id_min_remaining_validity_days + ctx.rng.randint(0, 3)
    expiry = ctx.as_of + timedelta(days=days)
    set_date(ctx, id_doc, "expiry_date", expiry)
    set_text(ctx, id_doc, "issue_date", us_date(add_months(expiry, -96)))
    _label(
        ctx, "id_expires_soon", DocType.ID_DOCUMENT, "expiry_date", f"valid for {days} more days"
    )


def dti_near_limit(ctx: Ctx) -> None:
    p = ctx.policy.parameters
    form = ctx.doc(DocType.APPLICATION_FORM)
    statements = ctx.docs_of(DocType.BANK_STATEMENT)
    if (
        form is None
        or not statements
        or ctx.has_defect(DefectType.POLICY_VIOLATION)
        or any(ctx.doc_touched(s) for s in statements)
        or ctx.is_touched(form, "requested_amount")
    ):
        raise NotApplicable
    gap = Decimal(ctx.rng.randint(50, 300)) / 10_000
    installment = monthly_installment(
        int(Decimal(form.canonical["requested_amount"])),
        int(form.canonical["term_months"]),
        p.monthly_interest_rate,
    )
    debt = (
        ctx.persona.net_monthly_salary * (Decimal(str(p.max_dti)) - gap) - installment
    ).quantize(Decimal("0.01"), ROUND_DOWN)
    if debt <= ctx.persona.existing_debt_monthly:
        raise NotApplicable
    for s in statements:
        set_money(ctx, s, "existing_debt_payments", debt)
    ratio = current_dti(ctx)
    assert ratio <= Decimal(str(p.max_dti))
    _label(
        ctx,
        "dti_near_limit",
        DocType.BANK_STATEMENT,
        "existing_debt_payments",
        f"debt-to-income is {ratio:.1%}, just under the {p.max_dti:.0%} limit",
    )


def tenure_at_limit(ctx: Ctx) -> None:
    p = ctx.policy.parameters
    letter = ctx.doc(DocType.EMPLOYMENT_LETTER)
    if letter is None or ctx.is_touched(letter, "hire_date"):
        raise NotApplicable
    hire = add_months(ctx.as_of, -p.min_employment_months) - timedelta(days=ctx.rng.randint(0, 10))
    if add_months(hire, p.min_employment_months) > ctx.as_of:
        raise NotApplicable
    set_date(ctx, letter, "hire_date", hire)
    _label(
        ctx,
        "tenure_at_limit",
        DocType.EMPLOYMENT_LETTER,
        "hire_date",
        f"employed for just over {p.min_employment_months} months",
    )


VARIATIONS: dict[str, Callable[[Ctx], None]] = {
    "name_accents_case": name_accents_case,
    "name_middle_initial": name_middle_initial,
    "name_middle_omitted": name_middle_omitted,
    "name_last_first": name_last_first,
    "address_abbreviated": address_abbreviated,
    "income_within_tolerance": income_within_tolerance,
    "income_just_under_tolerance": income_just_under_tolerance,
    "payslip_age_at_limit": payslip_age_at_limit,
    "utility_bill_age_at_limit": utility_bill_age_at_limit,
    "id_expires_soon": id_expires_soon,
    "dti_near_limit": dti_near_limit,
    "tenure_at_limit": tenure_at_limit,
}


def apply_variation(kind: str, ctx: Ctx) -> bool:
    """Apply one variation; False when it does not fit the current state of the file."""
    try:
        VARIATIONS[kind](ctx)
    except NotApplicable:
        return False
    return True
