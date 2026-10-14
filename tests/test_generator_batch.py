"""Ground-truth truthfulness: an independent oracle re-evaluates the policy on every generated
file and must agree EXACTLY with the labels the generator wrote."""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

import pytest

from credit_agent.finance import debt_to_income, monthly_installment
from credit_agent.generator.build import generate_batch
from credit_agent.generator.defects import INJECTION_TEXTS
from credit_agent.generator.models import DocumentContent, GeneratedFile
from credit_agent.generator.persona import add_months
from credit_agent.generator.variations import VARIATIONS
from credit_agent.normalize import addresses_equivalent, names_equivalent
from credit_agent.policy import Policy, load_policy
from credit_agent.schemas import ApplicationStatus, DefectType, DocType

AS_OF = date(2026, 6, 30)
ALL_TEXTS = [text for _, text in INJECTION_TEXTS]


@pytest.fixture(scope="module")
def policy() -> Policy:
    return load_policy()


@lru_cache
def _batch(n: int, seed: int, as_of: date = AS_OF) -> list[GeneratedFile]:
    return generate_batch(n, seed, load_policy(), as_of)


def _of(file: GeneratedFile, doc_type: DocType) -> list[DocumentContent]:
    return [d for d in file.documents if d.doc_type is doc_type]


def oracle_rules(file: GeneratedFile, policy: Policy, as_of: date) -> set[str]:
    """Policy rules violated by the file, computed only from canonical values."""
    p = policy.parameters
    tol = Decimal(str(p.income_tolerance))
    violated: set[str] = set()
    form = _of(file, DocType.APPLICATION_FORM)[0]
    ids, letters = _of(file, DocType.ID_DOCUMENT), _of(file, DocType.EMPLOYMENT_LETTER)
    bills = _of(file, DocType.UTILITY_BILL)
    slips, stmts = _of(file, DocType.PAYSLIP), _of(file, DocType.BANK_STATEMENT)

    # R-1 checklist
    if not (ids and letters and bills):
        violated.add("R-1.1")
    if len(slips) < p.required_payslips:
        violated.add("R-1.2")
    if len(stmts) < p.required_bank_statements:
        violated.add("R-1.3")

    # R-2 consistency
    for doc in file.documents:
        name = doc.fields.get("full_name") or doc.fields.get("account_holder")
        if name and not names_equivalent(form.fields["full_name"], name):
            violated.add("R-2.1")
    if ids and form.canonical["id_number"] != ids[0].canonical["id_number"]:
        violated.add("R-2.2")
    if bills and not addresses_equivalent(
        form.fields["address"], bills[0].fields["service_address"]
    ):
        violated.add("R-2.3")

    # R-3 income
    declared = Decimal(form.canonical["declared_monthly_income"])
    verified = sum((Decimal(s.canonical["net_salary"]) for s in slips), Decimal(0)) / len(slips)
    if abs(declared - verified) / verified > tol:
        violated.add("R-3.1")
    if letters:
        salary = Decimal(letters[0].canonical["monthly_salary"])
        if abs(declared - salary) / salary > tol:
            violated.add("R-3.2")

    # R-4 freshness
    if ids and date.fromisoformat(ids[0].canonical["expiry_date"]) < as_of + timedelta(
        days=p.id_min_remaining_validity_days
    ):
        violated.add("R-4.1")
    if bills and (as_of - date.fromisoformat(bills[0].canonical["bill_date"])).days > (
        p.utility_bill_max_age_days
    ):
        violated.add("R-4.2")
    if any(
        (as_of - date.fromisoformat(s.canonical["pay_period_end"])).days > p.payslip_max_age_days
        for s in slips
    ):
        violated.add("R-4.3")

    # R-5 affordability, tenure; R-6 limits
    amount = int(Decimal(form.canonical["requested_amount"]))
    term = int(form.canonical["term_months"])
    if stmts:
        existing = sum((Decimal(s.canonical["existing_debt_payments"]) for s in stmts), Decimal(0))
        existing /= len(stmts)
        installment = monthly_installment(amount, term, p.monthly_interest_rate)
        if debt_to_income(existing, installment, verified) > Decimal(str(p.max_dti)):
            violated.add("R-5.1")
    if (
        letters
        and add_months(
            date.fromisoformat(letters[0].canonical["hire_date"]), p.min_employment_months
        )
        > as_of
    ):
        violated.add("R-5.3")
    if not (p.min_amount_usd <= amount <= p.max_amount_usd) or term > p.max_term_months:
        violated.add("R-6.2")
    return violated


def _injected_docs(file: GeneratedFile) -> set[tuple[str, int]]:
    found = set()
    for doc in file.documents:
        blob = " ".join([*doc.fields.values(), doc.footer_text or ""])
        if any(text in blob for text in ALL_TEXTS):
            found.add((doc.doc_type.value, doc.index))
    return found


def _check_labels_match_oracle(file: GeneratedFile, policy: Policy, as_of: date) -> None:
    truth = file.ground_truth
    labeled = {r for d in truth.defects for r in d.rule_ids if r != "R-7.1"}
    assert oracle_rules(file, policy, as_of) == labeled, (
        truth.application_id,
        [d.description for d in truth.defects],
    )
    labeled_types = {
        d.doc_types[0].value for d in truth.defects if d.defect_type is DefectType.INJECTION_ATTEMPT
    }
    assert {doc_type for doc_type, _ in _injected_docs(file)} == labeled_types, truth.application_id


@pytest.mark.parametrize(("n", "seed"), [(40, 42), (40, 7), (80, 123), (25, 1)])
def test_labels_match_independent_oracle(policy: Policy, n: int, seed: int) -> None:
    for file in _batch(n, seed):
        _check_labels_match_oracle(file, policy, AS_OF)


def test_labels_match_oracle_for_other_reference_dates(policy: Policy) -> None:
    for as_of in (date(2026, 3, 1), date(2026, 8, 31), date(2027, 2, 28)):
        for file in _batch(40, 5, as_of):
            _check_labels_match_oracle(file, policy, as_of)


def test_distribution_matches_the_spec() -> None:
    files = _batch(40, 42)
    counts = Counter(len(f.ground_truth.defects) for f in files)
    assert counts[0] == 12 and counts[1] == 20 and counts[2] + counts[3] == 8
    injections = sum(
        any(d.defect_type is DefectType.INJECTION_ATTEMPT for d in f.ground_truth.defects)
        for f in files
    )
    assert injections >= 4
    owners = Counter(f.ground_truth.owner_id for f in files)
    assert owners == {"analyst_1": 24, "analyst_2": 16}
    splits = Counter(f.ground_truth.split for f in files)
    assert splits == {"dev": 10, "test": 30}


def test_every_defect_type_and_variation_is_covered() -> None:
    files = _batch(40, 42)
    types = Counter(d.defect_type for f in files for d in f.ground_truth.defects)
    assert set(types) == set(DefectType)
    assert min(types.values()) >= 2
    kinds = {h.kind for f in files for h in f.ground_truth.hard_negatives}
    assert kinds == set(VARIATIONS)


def test_hard_cases_exist() -> None:
    files = _batch(40, 42)
    defects = [d for f in files for d in f.ground_truth.defects]
    assert sum(d.near_threshold for d in defects) >= 5
    placements = {
        d.details["placement"] for d in defects if d.defect_type is DefectType.INJECTION_ATTEMPT
    }
    languages = {
        d.details["language"] for d in defects if d.defect_type is DefectType.INJECTION_ATTEMPT
    }
    assert placements == {"field", "footer"}
    assert languages - {"en"}, "needs at least one non-English injection"


def test_clean_files_carry_variations_and_defect_files_are_flagged_for_review() -> None:
    files = _batch(40, 42)
    clean = [f for f in files if not f.ground_truth.defects]
    assert sum(bool(f.ground_truth.hard_negatives) for f in clean) >= len(clean) // 2
    for f in files:
        t = f.ground_truth
        if t.defects or t.requires_mandatory_review:
            assert t.expected_status is ApplicationStatus.NEEDS_REVIEW
        else:
            assert t.expected_status is ApplicationStatus.CLEAN


def test_split_is_stratified_over_defect_profile() -> None:
    files = _batch(40, 42)
    dev = [f for f in files if f.ground_truth.split == "dev"]
    assert any(not f.ground_truth.defects for f in dev)
    assert any(len(f.ground_truth.defects) == 1 for f in dev)
    assert any(len(f.ground_truth.defects) >= 2 for f in dev)


def test_batch_is_deterministic_and_ids_unique() -> None:
    a = [f.model_dump_json() for f in generate_batch(40, 42, load_policy(), AS_OF)]
    b = [f.model_dump_json() for f in generate_batch(40, 42, load_policy(), AS_OF)]
    assert a == b
    ids = [f.application.application_id for f in _batch(40, 42)]
    assert len(set(ids)) == 40
    other_seed = [f.model_dump_json() for f in generate_batch(40, 43, load_policy(), AS_OF)]
    assert other_seed != a


def test_documents_removed_by_missing_doc_are_also_removed_from_the_application() -> None:
    for f in _batch(40, 42):
        filenames = {d.filename for d in f.documents}
        assert {r.s3_key.rsplit("/", 1)[-1] for r in f.application.documents} == filenames


def test_oracle_agrees_across_many_seeds_and_reference_dates(policy: Policy) -> None:
    """Stress: rare boundary cases (month-end clamping, rounding at tolerance) must not slip in."""
    for seed in range(100, 125):
        for as_of in (AS_OF, date(2026, 8, 31)):
            for file in generate_batch(40, seed, policy, as_of):
                _check_labels_match_oracle(file, policy, as_of)
