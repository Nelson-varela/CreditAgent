from datetime import date
from decimal import Decimal

import pytest

from credit_agent.finance import debt_to_income, monthly_installment
from credit_agent.generator.files import build_clean_file
from credit_agent.generator.models import DocumentContent, GeneratedFile
from credit_agent.generator.persona import add_months, month_bounds
from credit_agent.normalize import addresses_equivalent, names_equivalent, normalize_date
from credit_agent.policy import Policy, load_policy
from credit_agent.schemas import ApplicationStatus, DocType

AS_OF = date(2026, 6, 30)


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy()


def _make(policy: Policy, index: int, **kw: object) -> GeneratedFile:
    return build_clean_file(
        seed=42,
        index=index,
        policy=policy,
        as_of=kw.pop("as_of", AS_OF),  # type: ignore[arg-type]
        owner_id="analyst_1",
        split="test",
        **kw,  # type: ignore[arg-type]
    )


def _docs(file: GeneratedFile, doc_type: DocType) -> list[DocumentContent]:
    return [d for d in file.documents if d.doc_type is doc_type]


def _money(value: str) -> Decimal:
    return Decimal(value)


def assert_file_is_clean(file: GeneratedFile, policy: Policy, as_of: date) -> None:
    """Independent re-statement of the policy over canonical values."""
    p = policy.parameters
    form = _docs(file, DocType.APPLICATION_FORM)[0]
    id_doc = _docs(file, DocType.ID_DOCUMENT)[0]
    payslips = _docs(file, DocType.PAYSLIP)
    letter = _docs(file, DocType.EMPLOYMENT_LETTER)[0]
    statements = _docs(file, DocType.BANK_STATEMENT)
    bill = _docs(file, DocType.UTILITY_BILL)[0]

    # R-1: checklist
    assert len(payslips) == p.required_payslips
    assert len(statements) == p.required_bank_statements
    assert len(file.documents) == 1 + 1 + len(payslips) + 1 + len(statements) + 1

    # R-2: name, id, address consistency
    base_name = form.fields["full_name"]
    for doc in file.documents:
        name = doc.fields.get("full_name") or doc.fields.get("account_holder")
        if name:
            assert names_equivalent(base_name, name), (doc.filename, name)
    assert form.canonical["id_number"] == id_doc.canonical["id_number"]
    assert addresses_equivalent(form.fields["address"], bill.fields["service_address"])

    # R-3: income
    declared = _money(form.canonical["declared_monthly_income"])
    verified = sum((_money(d.canonical["net_salary"]) for d in payslips), Decimal(0)) / len(
        payslips
    )
    letter_salary = _money(letter.canonical["monthly_salary"])
    assert abs(declared - verified) / verified <= Decimal(str(p.income_tolerance))
    assert abs(declared - letter_salary) / letter_salary <= Decimal(str(p.income_tolerance))

    # R-4: freshness
    assert normalize_date(id_doc.fields["expiry_date"]) >= as_of
    assert (as_of - normalize_date(bill.fields["bill_date"])).days <= p.utility_bill_max_age_days
    for slip in payslips:
        age = (as_of - normalize_date(slip.fields["pay_period_end"])).days
        assert 0 <= age <= p.payslip_max_age_days

    # R-5: affordability and tenure
    existing = sum(
        (_money(d.canonical["existing_debt_payments"]) for d in statements), Decimal(0)
    ) / len(statements)
    amount = int(Decimal(form.canonical["requested_amount"]))
    installment = monthly_installment(
        amount, int(form.canonical["term_months"]), p.monthly_interest_rate
    )
    assert debt_to_income(existing, installment, verified) <= Decimal(str(p.max_dti))
    hire = normalize_date(letter.fields["hire_date"])
    assert add_months(hire, p.min_employment_months) <= as_of

    # R-6: product limits
    assert p.min_amount_usd <= amount <= p.max_amount_usd
    assert int(form.canonical["term_months"]) <= p.max_term_months


def test_clean_files_satisfy_the_policy(policy: Policy) -> None:
    for index in range(1, 301):
        assert_file_is_clean(_make(policy, index), policy, AS_OF)


def test_clean_files_satisfy_the_policy_with_other_reference_dates(policy: Policy) -> None:
    for as_of in (date(2026, 3, 1), date(2026, 7, 10), date(2026, 2, 28), date(2027, 1, 31)):
        for index in range(1, 40):
            assert_file_is_clean(_make(policy, index, as_of=as_of), policy, as_of)


def test_generation_is_deterministic_and_independent_of_batch(policy: Policy) -> None:
    a = _make(policy, 7).model_dump_json()
    _make(policy, 8)  # generating another file must not change file 7
    b = _make(policy, 7).model_dump_json()
    assert a == b
    assert a != _make(policy, 9).model_dump_json()
    different_seed = build_clean_file(
        seed=43, index=7, policy=policy, as_of=AS_OF, owner_id="analyst_1", split="test"
    )
    assert different_seed.model_dump_json() != a


def test_ground_truth_roundtrips_through_json(policy: Policy) -> None:
    file = _make(policy, 3)
    assert GeneratedFile.model_validate_json(file.model_dump_json()) == file


def test_canonical_fields_are_a_subset_of_printed_fields(policy: Policy) -> None:
    for doc in _make(policy, 5).documents:
        assert set(doc.canonical) <= set(doc.fields), doc.filename


def test_clean_file_has_no_labels_and_starts_received(policy: Policy) -> None:
    file = _make(policy, 1)
    assert file.ground_truth.defects == [] and file.ground_truth.hard_negatives == []
    assert file.application.status is ApplicationStatus.RECEIVED
    assert file.ground_truth.expected_status is ApplicationStatus.CLEAN
    assert {ref.s3_key.rsplit("/", 1)[-1] for ref in file.application.documents} == {
        d.filename for d in file.documents
    }


def test_high_amount_requires_review_even_without_defects(policy: Policy) -> None:
    for index in range(1, 30):
        file = _make(policy, index, high_amount=True)
        assert_file_is_clean(file, policy, AS_OF)
        assert file.application.amount_usd > policy.parameters.mandatory_review_amount_usd
        assert file.ground_truth.requires_mandatory_review
        assert file.ground_truth.expected_status is ApplicationStatus.NEEDS_REVIEW


def test_normal_amounts_never_trigger_mandatory_review(policy: Policy) -> None:
    for index in range(1, 100):
        file = _make(policy, index)
        assert file.application.amount_usd <= policy.parameters.mandatory_review_amount_usd
        assert not file.ground_truth.requires_mandatory_review


def test_names_with_diacritics_appear(policy: Policy) -> None:
    names = [_make(policy, i).application.applicant_name for i in range(1, 100)]
    assert any(not n.isascii() for n in names)


def test_statement_months_are_complete_and_consecutive(policy: Policy) -> None:
    for as_of, last_month in ((date(2026, 6, 30), 6), (date(2026, 7, 10), 6)):
        file = _make(policy, 1, as_of=as_of)
        statements = _docs(file, DocType.BANK_STATEMENT)
        assert len(statements) == 3
        for i, stmt in enumerate(statements):
            start, end = month_bounds(2026, last_month - (len(statements) - 1 - i))
            assert stmt.canonical["period_start"] == start.isoformat()
            assert stmt.canonical["period_end"] == end.isoformat()


@pytest.mark.parametrize(
    ("doc_type", "field", "bad_value"),
    [
        (DocType.APPLICATION_FORM, "declared_monthly_income", "$99,999.00"),  # income mismatch
        (DocType.APPLICATION_FORM, "full_name", "Totally Different Person"),  # name mismatch
        (DocType.ID_DOCUMENT, "expiry_date", "01/01/2020"),  # expired ID
        (DocType.UTILITY_BILL, "bill_date", "01/01/2026"),  # old utility bill
        (DocType.EMPLOYMENT_LETTER, "hire_date", "06/01/2026"),  # tenure too short
        (DocType.UTILITY_BILL, "service_address", "1 Nowhere Rd, Reno, NV 89501"),
    ],
)
def test_cleanliness_check_detects_broken_files(
    policy: Policy, doc_type: DocType, field: str, bad_value: str
) -> None:
    """Guards the guard: the independent policy check must be able to fail."""
    file = _make(policy, 1)
    doc = _docs(file, doc_type)[0]
    # The check recomputes from canonical values for income and printed values for the rest.
    doc.fields[field] = bad_value
    if field in doc.canonical:
        doc.canonical[field] = "99999.00" if field == "declared_monthly_income" else bad_value
    with pytest.raises(AssertionError):
        assert_file_is_clean(file, policy, AS_OF)
