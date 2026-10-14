"""Builds documents and a clean (defect-free) generated file from a persona."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from faker import Faker

from credit_agent.generator.models import (
    DefectLabel,
    DocumentContent,
    GeneratedFile,
    GroundTruth,
    HardNegativeLabel,
    Split,
)
from credit_agent.generator.persona import Persona, add_months, build_persona
from credit_agent.normalize import (
    normalize_address,
    normalize_id,
    normalize_name,
    normalize_text,
)
from credit_agent.policy import Policy
from credit_agent.schemas import Application, ApplicationStatus, DocType, DocumentRef

FAKE = Faker("en_US")


def file_rng(seed: int, index: int) -> random.Random:
    """Independent, deterministic RNG per file: batch size never changes other files."""
    return random.Random(f"credit-file-agent:{seed}:{index}")


def us_date(d: date) -> str:
    return d.strftime("%m/%d/%Y")


def money(value: Decimal | int) -> str:
    return f"${Decimal(value):,.2f}"


def canon_money(value: Decimal | int) -> str:
    return f"{Decimal(value):.2f}"


def document_ref(application_id: str, doc: DocumentContent) -> DocumentRef:
    return DocumentRef(
        doc_type=doc.doc_type,
        s3_key=f"applications/{application_id}/{doc.filename}",
    )


def build_documents(persona: Persona) -> list[DocumentContent]:
    """The six document types of the checklist, all consistent with each other."""
    p = persona
    name_title, name_upper = p.full_name, p.full_name.upper()
    docs: list[DocumentContent] = []

    docs.append(
        DocumentContent(
            doc_type=DocType.APPLICATION_FORM,
            fields={
                "full_name": name_title,
                "id_number": p.id_number,
                "date_of_birth": us_date(p.dob),
                "address": p.address.format(),
                "declared_monthly_income": money(p.net_monthly_salary),
                "requested_amount": money(p.requested_amount),
                "term_months": str(p.term_months),
                "loan_purpose": p.loan_purpose,
                "application_date": us_date(p.form_date),
            },
            canonical={
                "full_name": normalize_name(name_title),
                "id_number": normalize_id(p.id_number),
                "date_of_birth": p.dob.isoformat(),
                "address": normalize_address(p.address.format()),
                "declared_monthly_income": canon_money(p.net_monthly_salary),
                "requested_amount": canon_money(p.requested_amount),
                "term_months": str(p.term_months),
            },
        )
    )

    docs.append(
        DocumentContent(
            doc_type=DocType.ID_DOCUMENT,
            fields={
                "full_name": name_upper,
                "id_number": p.id_number,
                "date_of_birth": us_date(p.dob),
                "issue_date": us_date(p.id_issue_date),
                "expiry_date": us_date(p.id_expiry_date),
            },
            canonical={
                "full_name": normalize_name(name_upper),
                "id_number": normalize_id(p.id_number),
                "date_of_birth": p.dob.isoformat(),
                "expiry_date": p.id_expiry_date.isoformat(),
            },
        )
    )

    for i, end in enumerate(p.payslip_period_ends, start=1):
        start = _period_start(end)
        fields = {
            "full_name": name_title,
            "employer": p.employer,
            "net_salary": money(p.net_monthly_salary),
            "pay_period_start": us_date(start),
            "pay_period_end": us_date(end),
        }
        docs.append(
            DocumentContent(
                doc_type=DocType.PAYSLIP,
                index=i,
                fields=fields,
                canonical={
                    "full_name": normalize_name(name_title),
                    "employer": normalize_text(p.employer),
                    "net_salary": canon_money(p.net_monthly_salary),
                    "pay_period_start": start.isoformat(),
                    "pay_period_end": end.isoformat(),
                },
            )
        )

    docs.append(
        DocumentContent(
            doc_type=DocType.EMPLOYMENT_LETTER,
            fields={
                "full_name": name_title,
                "employer": p.employer,
                "job_title": p.job_title,
                "hire_date": us_date(p.hire_date),
                "monthly_salary": money(p.net_monthly_salary),
                "letter_date": us_date(p.letter_date),
            },
            canonical={
                "full_name": normalize_name(name_title),
                "employer": normalize_text(p.employer),
                "job_title": normalize_text(p.job_title),
                "hire_date": p.hire_date.isoformat(),
                "monthly_salary": canon_money(p.net_monthly_salary),
            },
        )
    )

    for i, (start, end) in enumerate(p.statement_months, start=1):
        docs.append(
            DocumentContent(
                doc_type=DocType.BANK_STATEMENT,
                index=i,
                fields={
                    "account_holder": name_upper,
                    "period_start": us_date(start),
                    "period_end": us_date(end),
                    "payroll_deposits": money(p.net_monthly_salary),
                    "existing_debt_payments": money(p.existing_debt_monthly),
                    "bank_name": p.bank_name,
                    "account_last4": p.account_last4,
                },
                canonical={
                    "account_holder": normalize_name(name_upper),
                    "period_start": start.isoformat(),
                    "period_end": end.isoformat(),
                    "payroll_deposits": canon_money(p.net_monthly_salary),
                    "existing_debt_payments": canon_money(p.existing_debt_monthly),
                },
            )
        )

    docs.append(
        DocumentContent(
            doc_type=DocType.UTILITY_BILL,
            fields={
                "account_holder": name_title,
                "service_address": p.address.format(),
                "bill_date": us_date(p.utility_bill_date),
                "provider": p.utility_provider,
                "amount_due": money(
                    (p.net_monthly_salary * Decimal("0.025")).quantize(Decimal("0.01"))
                ),
            },
            canonical={
                "account_holder": normalize_name(name_title),
                "service_address": normalize_address(p.address.format()),
                "bill_date": p.utility_bill_date.isoformat(),
            },
        )
    )
    return docs


def _period_start(period_end: date) -> date:
    """Monthly period: the day after the previous month's period end."""
    return add_months(period_end, -1) + timedelta(days=1)


def assemble(
    *,
    persona: Persona,
    documents: list[DocumentContent],
    application_id: str,
    owner_id: str,
    split: Split,
    seed: int,
    policy: Policy,
    as_of: date,
    defects: list[DefectLabel],
    hard_negatives: list[HardNegativeLabel],
) -> GeneratedFile:
    """Wrap documents into an application plus ground truth, derived from the FINAL documents."""
    form = next(d for d in documents if d.doc_type is DocType.APPLICATION_FORM)
    amount = int(Decimal(form.canonical["requested_amount"]))
    needs_review = amount > policy.parameters.mandatory_review_amount_usd
    application = Application(
        application_id=application_id,
        owner_id=owner_id,
        applicant_name=persona.full_name,
        amount_usd=amount,
        term_months=int(form.canonical["term_months"]),
        status=ApplicationStatus.RECEIVED,
        received_at=datetime(as_of.year, as_of.month, as_of.day, 12, 0, tzinfo=UTC),
        documents=[document_ref(application_id, d) for d in documents],
    )
    truth = GroundTruth(
        application_id=application_id,
        owner_id=owner_id,
        split=split,
        seed=seed,
        policy_version=policy.policy_version,
        as_of_date=as_of,
        defects=defects,
        hard_negatives=hard_negatives,
        requires_mandatory_review=needs_review,
        expected_status=(
            ApplicationStatus.NEEDS_REVIEW if defects or needs_review else ApplicationStatus.CLEAN
        ),
    )
    return GeneratedFile(application=application, documents=documents, ground_truth=truth)


def build_clean_file(
    *,
    seed: int,
    index: int,
    policy: Policy,
    as_of: date,
    owner_id: str,
    split: Split,
    high_amount: bool = False,
) -> GeneratedFile:
    """A file with no defects. High amounts still require human review (rule R-6.1)."""
    rng = file_rng(seed, index)
    FAKE.seed_instance(rng.randrange(2**32))
    persona = build_persona(rng, FAKE, policy, as_of, high_amount=high_amount)
    return assemble(
        persona=persona,
        documents=build_documents(persona),
        application_id=f"APP-{index:04d}",
        owner_id=owner_id,
        split=split,
        seed=seed,
        policy=policy,
        as_of=as_of,
        defects=[],
        hard_negatives=[],
    )
