"""Builds the policy manual PDF from the policy YAML (the RAG knowledge base).

Nothing here hard-codes a threshold: every number comes from ``Policy.parameters``, so the manual,
the deterministic rules and the ground truth cannot contradict each other.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from credit_agent.finance import debt_to_income, monthly_installment
from credit_agent.generator.persona import add_months
from credit_agent.policy import Policy, PolicyParameters, PolicyRule

NOTICE = (
    "Synthetic policy manual for a reference implementation. Fictional rules and values; "
    "not financial, legal or lending advice."
)

_base = getSampleStyleSheet()["BodyText"]
BODY = ParagraphStyle("m_body", parent=_base, fontName="Helvetica", fontSize=10.5, leading=14.5)
SMALL = ParagraphStyle(
    "m_small", parent=BODY, fontSize=8.5, leading=11, textColor=colors.HexColor("#555555")
)
H0 = ParagraphStyle(
    "m_h0", parent=BODY, fontName="Helvetica-Bold", fontSize=28, leading=34, spaceAfter=10
)
H1 = ParagraphStyle(
    "m_h1", parent=BODY, fontName="Helvetica-Bold", fontSize=18, leading=22, spaceAfter=6
)
H2 = ParagraphStyle(
    "m_h2",
    parent=BODY,
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=15,
    spaceBefore=12,
    spaceAfter=2,
)
CELL = ParagraphStyle("m_cell", parent=BODY, fontSize=9, leading=12)
CELL_BOLD = ParagraphStyle("m_cellb", parent=CELL, fontName="Helvetica-Bold")


def _p(text: str, style: ParagraphStyle = BODY) -> Paragraph:
    return Paragraph(escape(text), style)


PARAM_LABELS = {
    "monthly_interest_rate": "Monthly interest rate",
    "income_tolerance": "Income tolerance (relative)",
    "max_dti": "Maximum debt-to-income ratio",
    "min_employment_months": "Minimum employment tenure",
    "min_amount_usd": "Minimum loan amount",
    "max_amount_usd": "Maximum loan amount",
    "mandatory_review_amount_usd": "Amount above which human review is mandatory",
    "max_term_months": "Maximum loan term",
    "payslip_max_age_days": "Maximum payslip age",
    "utility_bill_max_age_days": "Maximum utility bill age",
    "id_min_remaining_validity_days": "Minimum remaining ID validity",
    "required_payslips": "Required payslips",
    "required_bank_statements": "Required bank statements",
}
FINDING_LABELS = {
    "MISSING_DOC": "Missing document",
    "NAME_MISMATCH": "Name mismatch",
    "ID_MISMATCH": "ID number mismatch",
    "INCOME_MISMATCH": "Income mismatch",
    "ADDRESS_MISMATCH": "Address mismatch",
    "EXPIRED_DOC": "Expired document",
    "STALE_PAYSLIP": "Stale payslip",
    "POLICY_VIOLATION": "Policy violation",
    "INJECTION_ATTEMPT": "Embedded instructions in a document",
}


def format_param(name: str, value: float | int) -> str:
    if name.endswith("_usd"):
        return f"${int(value):,}"
    if name.endswith("_days"):
        return f"{value} days"
    if name.endswith("_months"):
        return f"{value} months"
    if name == "monthly_interest_rate":
        return f"{float(value):.2%} per month"
    if name in ("income_tolerance", "max_dti"):
        return f"{float(value):.0%}"
    return str(value)


def _rule_flowables(policy: Policy, rule: PolicyRule) -> list[Flowable]:
    if rule.defect_type is not None:
        assert rule.severity and rule.suggested_action
        meta = (
            f"Finding: {FINDING_LABELS[rule.defect_type.value]}  |  "
            f"Severity: {rule.severity.value}  |  "
            f"Suggested action: {rule.suggested_action.value}"
        )
    else:
        meta = "Informational rule: it does not raise a finding by itself."
    return [
        Paragraph(f"<b>{rule.rule_id}</b> &nbsp;{escape(rule.title)}", H2),
        _p(policy.render(rule.rule_id)),
        Spacer(1, 3),
        _p(meta, SMALL),
    ]


def _cover(policy: Policy) -> list[Flowable]:
    return [
        Spacer(1, 2.2 * inch),
        _p(policy.title, H0),
        _p(f"Policy version {policy.policy_version}", H1),
        _p(f"Effective date: {policy.effective_date.strftime('%B %d, %Y')}", BODY),
        _p(f"Currency: {policy.currency}", BODY),
        Spacer(1, 1.2 * inch),
        _p(NOTICE, SMALL),
        PageBreak(),
    ]


def _about(policy: Policy) -> list[Flowable]:
    p = policy.parameters
    story: list[Flowable] = [
        _p("About this manual", H1),
        _p(
            "This manual defines how consumer loan application files are reviewed. Every finding "
            "raised by the review system cites a rule of this manual by its identifier "
            "(for example "
            f"R-3.1) together with the policy version ({policy.policy_version})."
        ),
        Spacer(1, 6),
        _p(
            "All time limits are measured against the assessment date of the review run, never "
            "against the day on which a file is opened. The review system never approves or "
            "rejects an application: it proposes, and an analyst decides (rule R-7.2)."
        ),
        Spacer(1, 6),
        _p(
            f"A complete file contains {2 + p.required_payslips + p.required_bank_statements + 2} "
            f"documents: the application form, an identity document, {p.required_payslips} "
            f"payslips, an employment letter, {p.required_bank_statements} monthly bank statements "
            "and a utility bill."
        ),
        Spacer(1, 14),
        _p("Contents", H1),
    ]
    for section in policy.sections:
        first, last = section.rules[0].rule_id, section.rules[-1].rule_id
        story.append(_p(f"Section {section.section_id}. {section.title}  ({first} to {last})"))
    story += [
        _p("Appendix A. Policy parameters"),
        _p("Appendix B. Worked examples"),
        _p("Appendix C. Severity and suggested-action matrix"),
        PageBreak(),
    ]
    return story


def _sections(policy: Policy) -> list[Flowable]:
    story: list[Flowable] = []
    for section in policy.sections:
        story += [_p(f"Section {section.section_id}. {section.title}", H1), _p(section.intro)]
        for rule in section.rules:
            story += _rule_flowables(policy, rule)
        story.append(PageBreak())
    return story


def _table(rows: list[list[str]], widths: list[float], header: bool = True) -> Table:
    data = [
        [_p(cell, CELL_BOLD if header and i == 0 else CELL) for cell in row]
        for i, row in enumerate(rows)
    ]
    table = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style.append(("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")))
    table.setStyle(TableStyle(style))
    return table


def _appendix_parameters(policy: Policy) -> list[Flowable]:
    used_by: dict[str, list[str]] = {name: [] for name in PolicyParameters.model_fields}
    for rule in policy.rules:
        for name in rule.placeholders:
            used_by[name].append(rule.rule_id)
    rows = [["Parameter", "Value", "Used by"]]
    for name, value in policy.parameters.model_dump().items():
        rows.append(
            [PARAM_LABELS[name], format_param(name, value), ", ".join(sorted(used_by[name])) or "-"]
        )
    return [
        _p("Appendix A. Policy parameters", H1),
        _p(
            "Every threshold used by the rules in this manual is listed here, with the rules "
            "that cite it."
        ),
        Spacer(1, 8),
        _table(rows, [2.9 * inch, 1.7 * inch, 1.9 * inch]),
        PageBreak(),
    ]


def worked_examples(policy: Policy) -> list[tuple[str, str]]:
    """(title, text) pairs; all numbers derived from the policy parameters."""
    p = policy.parameters
    rate = p.monthly_interest_rate
    principal, term = 15_000, 36
    installment = monthly_installment(principal, term, rate)
    income, debt = Decimal("5000.00"), Decimal("600.00")
    ratio = debt_to_income(debt, installment, income)
    verdict = "within" if ratio <= Decimal(str(p.max_dti)) else "above"

    tol = Decimal(str(p.income_tolerance))
    documented = Decimal("5000.00")
    boundary = documented * (1 + tol)
    over = boundary + Decimal("1.00")

    assessed = date(2026, 6, 30)
    oldest_ok = assessed - timedelta(days=p.payslip_max_age_days)
    hire_ok = add_months(assessed, -p.min_employment_months)

    review = p.mandatory_review_amount_usd
    return [
        (
            "Installment (R-5.2)",
            f"A ${principal:,} loan over {term} months at {rate:.2%} per month has a monthly "
            f"installment of ${installment:,.2f}.",
        ),
        (
            "Debt-to-income (R-5.1)",
            f"With a verified monthly income of ${income:,.2f}, existing monthly debt payments of "
            f"${debt:,.2f} and the installment above, the ratio is "
            f"({debt:,.2f} + {installment:,.2f}) / {income:,.2f} = {ratio:.1%}, which is {verdict} "
            f"the {p.max_dti:.0%} limit.",
        ),
        (
            "Income tolerance (R-3.1, R-3.2)",
            f"For a documented income of ${documented:,.2f} and a tolerance of "
            f"{p.income_tolerance:.0%}, a declared income of up to ${boundary:,.2f} is accepted "
            f"(a difference exactly equal to the tolerance is accepted). A declared income of "
            f"${over:,.2f} is an income mismatch.",
        ),
        (
            "Payslip age (R-4.3)",
            f"If the assessment date is {assessed.strftime('%B %d, %Y')}, a payslip whose pay "
            f"period ended on {oldest_ok.strftime('%B %d, %Y')} is exactly "
            f"{p.payslip_max_age_days} days old and is accepted. One that ended a day earlier is "
            "stale.",
        ),
        (
            "Employment tenure (R-5.3)",
            f"If the assessment date is {assessed.strftime('%B %d, %Y')}, an employee who started "
            f"on {hire_ok.strftime('%B %d, %Y')} has exactly {p.min_employment_months} months of "
            "tenure and meets the minimum. A start date one day later does not.",
        ),
        (
            "Mandatory review (R-6.1)",
            f"A request for ${review:,} does not trigger mandatory review by amount; a request for "
            f"${review + 1:,} does.",
        ),
    ]


def _appendix_examples(policy: Policy) -> list[Flowable]:
    story: list[Flowable] = [_p("Appendix B. Worked examples", H1)]
    for title, text in worked_examples(policy):
        story += [_p(title, H2), _p(text)]
    story.append(PageBreak())
    return story


def _appendix_matrix(policy: Policy) -> list[Flowable]:
    rows = [["Rule", "Finding", "Severity", "Suggested action"]]
    for rule in policy.rules:
        if rule.defect_type and rule.severity and rule.suggested_action:
            rows.append(
                [
                    rule.rule_id,
                    FINDING_LABELS[rule.defect_type.value],
                    rule.severity.value,
                    rule.suggested_action.value,
                ]
            )
    return [
        _p("Appendix C. Severity and suggested-action matrix", H1),
        _p(
            "Each rule that can raise a finding has a severity and a suggested action for "
            "the analyst."
        ),
        Spacer(1, 8),
        _table(rows, [0.8 * inch, 2.4 * inch, 1.0 * inch, 2.3 * inch]),
    ]


def _page_decorations(policy: Policy) -> Callable[[Canvas, SimpleDocTemplate], None]:
    def draw(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillGray(0.4)
        canvas.drawString(
            0.9 * inch,
            0.5 * inch,
            f"{policy.title} v{policy.policy_version} - synthetic, fictional",
        )
        canvas.drawRightString(letter[0] - 0.9 * inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    return draw


def build_manual(policy: Policy, target: Path | io.BytesIO) -> int:
    """Write the manual PDF and return its page count."""
    template = SimpleDocTemplate(
        target if isinstance(target, io.BytesIO) else str(target),
        pagesize=letter,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title=f"{policy.title} v{policy.policy_version}",
        author="credit-file-agent synthetic generator",
        subject=NOTICE,
        invariant=1,
    )
    story = (
        _cover(policy)
        + _about(policy)
        + _sections(policy)
        + _appendix_parameters(policy)
        + _appendix_examples(policy)
        + _appendix_matrix(policy)
    )
    decorate = _page_decorations(policy)
    template.build(story, onFirstPage=lambda c, d: None, onLaterPages=decorate)
    return template.page
