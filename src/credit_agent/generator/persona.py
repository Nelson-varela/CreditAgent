"""A fictional US applicant whose facts are consistent with the policy by construction."""

from __future__ import annotations

import calendar
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from faker import Faker

from credit_agent.finance import monthly_installment
from credit_agent.policy import Policy

# Names with diacritics, so "accents are not a defect" is exercised by real cases.
_DIACRITIC_NAMES = [
    ("José", "Luis", "Muñoz"),
    ("Zoë", "Marie", "Brennan"),
    ("Renée", "Claire", "Dubois"),
    ("André", "Paul", "Gómez"),
    ("Inés", "Marisol", "Peña"),
    ("Chloé", "Anne", "Tremblay"),
    ("Martín", "Alejandro", "Núñez"),
    ("Aimée", "Rose", "Lefèvre"),
]

_STREET_NAMES = [
    "Maple",
    "Oak",
    "Cedar",
    "Pine",
    "Elm",
    "Willow",
    "Lakeview",
    "Sunset",
    "Hillcrest",
]
_STREET_TYPES = {
    "Street": "St",
    "Avenue": "Ave",
    "Boulevard": "Blvd",
    "Road": "Rd",
    "Drive": "Dr",
    "Lane": "Ln",
    "Court": "Ct",
}
_CITIES = [
    ("Springfield", "IL", "627"),
    ("Austin", "TX", "787"),
    ("Denver", "CO", "802"),
    ("Columbus", "OH", "432"),
    ("Charlotte", "NC", "282"),
    ("Portland", "OR", "972"),
    ("Tampa", "FL", "336"),
    ("Madison", "WI", "537"),
    ("Albany", "NY", "122"),
    ("Phoenix", "AZ", "850"),
]
_PURPOSES = [
    "Debt consolidation",
    "Home improvement",
    "Medical expenses",
    "Vehicle repair",
    "Education costs",
    "Moving expenses",
]
_UTILITY_PROVIDERS = ["Lakeside Electric", "Metro Water & Power", "Northgate Gas & Electric"]
_BANKS = ["First Prairie Bank", "Harbor Trust Bank", "Summit Valley Credit Union"]


class AddressStyle(StrEnum):
    FULL = "full"  # 123 Main Street, Apt 4B, ...
    ABBREVIATED = "abbreviated"  # 123 Main St, Apt 4B, ...
    ABBREVIATED_HASH = "abbreviated_hash"  # 123 Main St #4B, ...


@dataclass(frozen=True)
class Address:
    number: int
    street_name: str
    street_type: str  # full word, e.g. "Street"
    unit: str | None
    city: str
    state: str
    zip_code: str

    def format(self, style: AddressStyle = AddressStyle.FULL) -> str:
        street_type = (
            self.street_type if style is AddressStyle.FULL else _STREET_TYPES[self.street_type]
        )
        street = f"{self.number} {self.street_name} {street_type}"
        if self.unit:
            street += (
                f" #{self.unit}" if style is AddressStyle.ABBREVIATED_HASH else f", Apt {self.unit}"
            )
        return f"{street}, {self.city}, {self.state} {self.zip_code}"


@dataclass(frozen=True)
class Persona:
    first_name: str
    middle_name: str
    last_name: str
    dob: date
    id_number: str  # fictional state ID / driver license number (NOT an SSN)
    address: Address
    employer: str
    job_title: str
    hire_date: date
    net_monthly_salary: Decimal
    existing_debt_monthly: Decimal
    requested_amount: int
    term_months: int
    loan_purpose: str
    form_date: date
    letter_date: date
    id_issue_date: date
    id_expiry_date: date
    payslip_period_ends: tuple[date, ...]  # oldest -> newest
    statement_months: tuple[tuple[date, date], ...]  # (start, end), oldest -> newest
    utility_bill_date: date
    utility_provider: str
    bank_name: str
    account_last4: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.middle_name} {self.last_name}"


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def month_bounds(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _money(cents: int) -> Decimal:
    return Decimal(cents) / 100


def _pick_names(rng: random.Random, fake: Faker) -> tuple[str, str, str]:
    if rng.random() < 0.25:
        return rng.choice(_DIACRITIC_NAMES)
    first, last = fake.first_name(), fake.last_name()
    middle = fake.first_name()
    while middle == first:
        middle = fake.first_name()
    return first, middle, last


def _pick_pay_dates(
    rng: random.Random, as_of: date, count: int, max_age_days: int
) -> tuple[date, ...]:
    """Monthly pay periods ending on a fixed day; the oldest must stay safely inside the limit."""
    for _ in range(200):
        day = rng.randint(1, 28)
        newest = date(as_of.year, as_of.month, day)
        while newest > as_of - timedelta(days=2):
            newest = add_months(newest, -1)
        ends = tuple(add_months(newest, -k) for k in range(count - 1, -1, -1))
        if (as_of - ends[0]).days <= max_age_days - 3:
            return ends
    raise RuntimeError("could not place payslip periods inside the policy age limit")


def _statement_months(as_of: date, count: int) -> tuple[tuple[date, date], ...]:
    """The `count` most recent complete calendar months, oldest first."""
    first_of_month = as_of.replace(day=1)
    _, month_end = month_bounds(as_of.year, as_of.month)
    anchor = first_of_month if as_of == month_end else add_months(first_of_month, -1)
    months = (add_months(anchor, -k) for k in range(count - 1, -1, -1))
    return tuple(month_bounds(m.year, m.month) for m in months)


def build_persona(
    rng: random.Random,
    fake: Faker,
    policy: Policy,
    as_of: date,
    *,
    high_amount: bool = False,
) -> Persona:
    """Create a persona that satisfies every policy rule (a clean file)."""
    p = policy.parameters
    first, middle, last = _pick_names(rng, fake)

    # Income and loan sizing. Clean files stay well below the DTI limit.
    if high_amount:
        salary = _money(rng.randrange(650_000, 1_200_000))
        term = rng.choice([48, 60])
        lo, hi = p.mandatory_review_amount_usd + 1_000, p.max_amount_usd
    else:
        salary = _money(rng.randrange(280_000, 900_000))
        term = rng.choice([12, 24, 36, 48, 60])
        lo, hi = p.min_amount_usd * 2, p.mandatory_review_amount_usd
    existing_debt = (salary * Decimal(rng.randrange(5, 19)) / 100).quantize(Decimal("0.01"))
    max_installment = salary * Decimal("0.30") - existing_debt
    amount = rng.randrange(lo // 100, hi // 100 + 1) * 100
    while monthly_installment(amount, term, p.monthly_interest_rate) > max_installment:
        amount -= 500
    if amount < p.min_amount_usd or (high_amount and amount <= p.mandatory_review_amount_usd):
        raise RuntimeError("generated amount fell outside the intended range")

    unit = rng.choice([None, None, f"{rng.randint(1, 30)}{rng.choice('ABCD')}"])
    city, state, zip_prefix = rng.choice(_CITIES)
    address = Address(
        number=rng.randint(10, 9899),
        street_name=rng.choice(_STREET_NAMES),
        street_type=rng.choice(list(_STREET_TYPES)),
        unit=unit,
        city=city,
        state=state,
        zip_code=f"{zip_prefix}{rng.randint(0, 99):02d}",
    )

    id_expiry = as_of + timedelta(days=rng.randint(90, 2000))
    return Persona(
        first_name=first,
        middle_name=middle,
        last_name=last,
        dob=as_of - timedelta(days=rng.randint(22 * 365, 62 * 365)),
        id_number=f"D{rng.randint(10_000_000, 99_999_999)}",
        address=address,
        employer=fake.company(),
        job_title=fake.job(),
        hire_date=add_months(as_of, -rng.randint(p.min_employment_months + 3, 120)),
        net_monthly_salary=salary,
        existing_debt_monthly=existing_debt,
        requested_amount=amount,
        term_months=term,
        loan_purpose=rng.choice(_PURPOSES),
        form_date=as_of - timedelta(days=rng.randint(0, 5)),
        letter_date=as_of - timedelta(days=rng.randint(6, 40)),
        id_issue_date=add_months(id_expiry, -96),
        id_expiry_date=id_expiry,
        payslip_period_ends=_pick_pay_dates(
            rng, as_of, p.required_payslips, p.payslip_max_age_days
        ),
        statement_months=_statement_months(as_of, p.required_bank_statements),
        utility_bill_date=as_of - timedelta(days=rng.randint(3, p.utility_bill_max_age_days - 10)),
        utility_provider=rng.choice(_UTILITY_PROVIDERS),
        bank_name=rng.choice(_BANKS),
        account_last4=f"{rng.randint(0, 9999):04d}",
    )
