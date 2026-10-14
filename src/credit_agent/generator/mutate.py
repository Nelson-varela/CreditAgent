"""Shared mutation context and typed setters used by defect injectors and variations.

Every setter writes BOTH the printed value and the canonical truth of what is now printed, and
records the field as touched so later steps never silently overwrite or contradict it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal

from faker import Faker

from credit_agent.finance import debt_to_income, monthly_installment
from credit_agent.generator.files import canon_money, money, us_date
from credit_agent.generator.models import DefectLabel, DocumentContent, HardNegativeLabel
from credit_agent.generator.persona import (
    _CITIES,
    _STREET_NAMES,
    Address,
    AddressStyle,
    Persona,
)
from credit_agent.normalize import (
    addresses_equivalent,
    normalize_address,
    normalize_id,
    normalize_name,
)
from credit_agent.policy import Policy
from credit_agent.schemas import DefectType, DocType

NAME_FIELDS = ("full_name", "account_holder")
_UPPER_STYLE = (DocType.ID_DOCUMENT, DocType.BANK_STATEMENT)


class NotApplicable(Exception):
    """A defect or variation cannot be applied to the current state of this file."""


@dataclass
class Ctx:
    rng: random.Random
    fake: Faker
    persona: Persona
    policy: Policy
    as_of: date
    docs: list[DocumentContent]
    touched: set[tuple[DocType, int, str]] = field(default_factory=set)
    required: set[tuple[DocType, int]] = field(default_factory=set)
    defects: list[DefectLabel] = field(default_factory=list)
    hard_negatives: list[HardNegativeLabel] = field(default_factory=list)
    injection_style: str = "footer_en"  # <placement>_<en|foreign>, chosen by the plan

    def doc(self, doc_type: DocType, index: int = 1) -> DocumentContent | None:
        return next((d for d in self.docs if d.doc_type is doc_type and d.index == index), None)

    def docs_of(self, doc_type: DocType) -> list[DocumentContent]:
        return [d for d in self.docs if d.doc_type is doc_type]

    def is_touched(self, doc: DocumentContent, field_name: str) -> bool:
        return (doc.doc_type, doc.index, field_name) in self.touched

    def doc_touched(self, doc: DocumentContent) -> bool:
        return any(t[:2] == (doc.doc_type, doc.index) for t in self.touched)

    def has_defect(self, defect_type: DefectType) -> bool:
        return any(d.defect_type is defect_type for d in self.defects)

    def require(self, *docs: DocumentContent) -> None:
        self.required.update((d.doc_type, d.index) for d in docs)


def name_field(doc: DocumentContent) -> str:
    return next(f for f in NAME_FIELDS if f in doc.fields)


def _set(ctx: Ctx, doc: DocumentContent, field_name: str, display: str, canon: str | None) -> None:
    doc.fields[field_name] = display
    if canon is not None:
        doc.canonical[field_name] = canon
    ctx.touched.add((doc.doc_type, doc.index, field_name))


def set_text(ctx: Ctx, doc: DocumentContent, field_name: str, text: str) -> None:
    """Decorative (non-scored) field."""
    _set(ctx, doc, field_name, text, None)


def set_date(ctx: Ctx, doc: DocumentContent, field_name: str, value: date) -> None:
    _set(ctx, doc, field_name, us_date(value), value.isoformat())


def set_money(ctx: Ctx, doc: DocumentContent, field_name: str, amount: Decimal | int) -> None:
    _set(ctx, doc, field_name, money(amount), canon_money(amount))


def set_int(ctx: Ctx, doc: DocumentContent, field_name: str, value: int) -> None:
    _set(ctx, doc, field_name, str(value), str(value))


def set_name(ctx: Ctx, doc: DocumentContent, name: str) -> None:
    shown = name.upper() if doc.doc_type in _UPPER_STYLE else name
    _set(ctx, doc, name_field(doc), shown, normalize_name(shown))


def set_address(ctx: Ctx, doc: DocumentContent, field_name: str, text: str) -> None:
    _set(ctx, doc, field_name, text, normalize_address(text))


def set_id(ctx: Ctx, doc: DocumentContent, value: str) -> None:
    _set(ctx, doc, "id_number", value, normalize_id(value))


def different_address(address: Address, rng: random.Random) -> Address:
    """An address that is genuinely a different place (not a formatting variant)."""
    for _ in range(50):
        choice = rng.choice(["number", "street", "city"])
        if choice == "number":
            candidate = replace(
                address, number=max(1, address.number + rng.choice([-1, 1]) * rng.randint(1, 40))
            )
        elif choice == "street":
            candidate = replace(address, street_name=rng.choice(_STREET_NAMES))
        else:
            city, state, prefix = rng.choice(_CITIES)
            candidate = replace(
                address, city=city, state=state, zip_code=f"{prefix}{rng.randint(0, 99):02d}"
            )
        if not addresses_equivalent(candidate.format(), address.format()):
            return candidate
    raise RuntimeError("could not build a different address")


def address_text(address: Address, style: AddressStyle = AddressStyle.FULL) -> str:
    return address.format(style)


def current_dti(ctx: Ctx) -> Decimal:
    """Debt-to-income computed from the CURRENT canonical values of the documents."""
    form = ctx.doc(DocType.APPLICATION_FORM)
    assert form is not None
    payslips, statements = ctx.docs_of(DocType.PAYSLIP), ctx.docs_of(DocType.BANK_STATEMENT)
    verified = sum((Decimal(d.canonical["net_salary"]) for d in payslips), Decimal(0)) / len(
        payslips
    )
    debt = sum(
        (Decimal(d.canonical["existing_debt_payments"]) for d in statements), Decimal(0)
    ) / len(statements)
    installment = monthly_installment(
        int(Decimal(form.canonical["requested_amount"])),
        int(form.canonical["term_months"]),
        ctx.policy.parameters.monthly_interest_rate,
    )
    return debt_to_income(debt, installment, verified)
