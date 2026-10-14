"""Contract between document templates and extraction.

``LABELS`` lists, per document type, the label printed next to each field (in print order). The
renderer prints these labels and the extractors look for them, so both sides share one source.
``canonicalize`` is the single place that turns a raw string into the canonical form used by the
ground truth and by the rule checks.

Limitation, stated on purpose: the synthetic templates are fixed, so extraction accuracy measured
here does not show how well the system generalizes to layouts it has never seen.
"""

from __future__ import annotations

import re

from credit_agent.normalize import (
    normalize_address,
    normalize_date,
    normalize_id,
    normalize_money,
    normalize_name,
    normalize_text,
)
from credit_agent.schemas import DocType

LABELS: dict[DocType, dict[str, str]] = {
    DocType.APPLICATION_FORM: {
        "application_date": "Application date",
        "full_name": "Full name",
        "id_number": "State ID / driver license no.",
        "date_of_birth": "Date of birth",
        "address": "Residential address",
        "declared_monthly_income": "Declared monthly net income",
        "requested_amount": "Requested amount",
        "term_months": "Term (months)",
        "loan_purpose": "Purpose of loan",
    },
    DocType.ID_DOCUMENT: {
        "full_name": "Name",
        "id_number": "ID No.",
        "date_of_birth": "Date of birth",
        "issue_date": "Issued",
        "expiry_date": "Expires",
    },
    DocType.PAYSLIP: {
        "employer": "Employer",
        "full_name": "Employee",
        "pay_period_start": "Pay period start",
        "pay_period_end": "Pay period end",
        "net_salary": "Net pay",
    },
    DocType.BANK_STATEMENT: {
        "account_holder": "Account holder",
        "account_last4": "Account ending in",
        "period_start": "Statement period start",
        "period_end": "Statement period end",
        "payroll_deposits": "Total payroll deposits",
        "existing_debt_payments": "Total loan / credit payments",
    },
    DocType.UTILITY_BILL: {
        "account_holder": "Account holder",
        "service_address": "Service address",
        "bill_date": "Bill date",
        "amount_due": "Amount due",
    },
    # The employment letter is prose: its fields are located with questions (Textract QUERIES) or
    # patterns, not printed labels. The aliases below are the names used for those answers.
    DocType.EMPLOYMENT_LETTER: {
        "letter_date": "Letter date",
        "full_name": "Employee full name",
        "employer": "Employer",
        "job_title": "Job title",
        "hire_date": "Employment start date",
        "monthly_salary": "Monthly net salary",
    },
}

# Natural-language questions for Textract QUERIES, keyed by field alias (employment letter only).
LETTER_QUERIES: dict[str, str] = {
    "full_name": "What is the employee's full name?",
    "employer": "What is the name of the employer?",
    "job_title": "What is the employee's job title?",
    "hire_date": "What is the employee's start date?",
    "monthly_salary": "What is the employee's monthly net salary?",
    "letter_date": "What is the date of the letter?",
}

_NAME_FIELDS = {"full_name", "account_holder"}
_DATE_FIELDS = {
    "application_date",
    "date_of_birth",
    "issue_date",
    "expiry_date",
    "pay_period_start",
    "pay_period_end",
    "period_start",
    "period_end",
    "hire_date",
    "bill_date",
    "letter_date",
}
_MONEY_FIELDS = {
    "declared_monthly_income",
    "requested_amount",
    "net_salary",
    "monthly_salary",
    "payroll_deposits",
    "existing_debt_payments",
    "amount_due",
}
_ADDRESS_FIELDS = {"address", "service_address"}
_TEXT_FIELDS = {"employer", "job_title"}


def canonicalize(field: str, raw: str) -> str:
    """Canonical form of a raw extracted value; raises ValueError when it cannot be parsed."""
    if field in _NAME_FIELDS:
        return normalize_name(raw)
    if field == "id_number":
        return normalize_id(raw)
    if field in _ADDRESS_FIELDS:
        return normalize_address(raw)
    if field in _DATE_FIELDS:
        return normalize_date(raw).isoformat()
    if field in _MONEY_FIELDS:
        return f"{normalize_money(raw):.2f}"
    if field == "term_months":
        return str(int(raw.strip()))
    if field in _TEXT_FIELDS:
        return normalize_text(raw)
    return raw.strip()


_FILENAME = re.compile(r"^(?P<type>[a-z_]+?)_\d+\.pdf$")


def doc_type_from_filename(name: str) -> DocType:
    """``payslip_2.pdf`` -> PAYSLIP. Classification is out of scope: the upload names the type."""
    match = _FILENAME.match(name)
    if not match:
        raise ValueError(f"unrecognized document file name: {name!r}")
    return DocType(match["type"])
