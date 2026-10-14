"""Renders a DocumentContent as a single-page US Letter PDF.

Layout is chosen for Textract: clear "Label: value" pairs in a ruled table (FORMS), and a prose
letter for the employment letter (QUERIES). Hidden instructions (``footer_text``) are printed as
tiny grey text at the bottom of the page, the way an attacker would hide them.

Output is deterministic (``invariant=1``): same input, byte-identical PDF.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.platypus.doctemplate import LayoutError

from credit_agent.extraction.schema import LABELS
from credit_agent.generator.models import DocumentContent
from credit_agent.normalize import normalize_date
from credit_agent.schemas import DocType

LENDER = "Cedar Ridge Lending Co."
MOTOR_VEHICLES = "State Department of Motor Vehicles"
SYNTHETIC_NOTICE = "Synthetic sample document - fictional data, not a real record"

TITLES = {
    DocType.APPLICATION_FORM: "PERSONAL LOAN APPLICATION",
    DocType.ID_DOCUMENT: "DRIVER LICENSE / STATE IDENTIFICATION CARD",
    DocType.PAYSLIP: "EARNINGS STATEMENT (PAY STUB)",
    DocType.EMPLOYMENT_LETTER: "EMPLOYMENT VERIFICATION LETTER",
    DocType.BANK_STATEMENT: "MONTHLY ACCOUNT STATEMENT",
    DocType.UTILITY_BILL: "UTILITY BILL",
}

_styles = getSampleStyleSheet()
_BODY = ParagraphStyle(
    "body", parent=_styles["BodyText"], fontName="Helvetica", fontSize=10.5, leading=14
)
_LABEL = ParagraphStyle("label", parent=_BODY, textColor=colors.HexColor("#444444"))
_TITLE = ParagraphStyle("title", parent=_BODY, fontName="Helvetica-Bold", fontSize=13, spaceAfter=4)
_ISSUER = ParagraphStyle(
    "issuer", parent=_BODY, fontName="Helvetica-Bold", fontSize=16, spaceAfter=2
)
_NOTICE = ParagraphStyle("notice", parent=_BODY, fontSize=7, textColor=colors.HexColor("#888888"))


def _p(text: str, style: ParagraphStyle = _BODY) -> Paragraph:
    return Paragraph(escape(text), style)


def _issuer(doc: DocumentContent) -> str:
    f = doc.fields
    return {
        DocType.APPLICATION_FORM: LENDER,
        DocType.ID_DOCUMENT: MOTOR_VEHICLES,
        DocType.PAYSLIP: f.get("employer", ""),
        DocType.EMPLOYMENT_LETTER: f.get("employer", ""),
        DocType.BANK_STATEMENT: f.get("bank_name", ""),
        DocType.UTILITY_BILL: f.get("provider", ""),
    }[doc.doc_type]


def _kv_table(doc: DocumentContent) -> Table:
    rows = [
        [_p(f"{label}:", _LABEL), _p(doc.fields[key])]
        for key, label in LABELS[doc.doc_type].items()
        if key in doc.fields
    ]
    table = Table(rows, colWidths=[2.4 * inch, 4.1 * inch])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F4F4F4")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _letter_body(doc: DocumentContent) -> list[Flowable]:
    f = doc.fields
    return [
        _p(f["letter_date"]),
        Spacer(1, 10),
        _p("To whom it may concern:"),
        Spacer(1, 8),
        _p(
            f"This letter confirms that {f['full_name']} is currently employed by {f['employer']} "
            f"as {f['job_title']}. The employee's start date is {f['hire_date']}."
        ),
        Spacer(1, 6),
        _p(f"The employee's current monthly net salary is {f['monthly_salary']}."),
        Spacer(1, 6),
        _p("Please contact our Human Resources department if you require further verification."),
        Spacer(1, 18),
        _p("Sincerely,"),
        _p(f"Human Resources Department, {f['employer']}"),
    ]


def _transactions(doc: DocumentContent) -> Table:
    start = normalize_date(doc.fields["period_start"])
    rows = [
        [_p("Date", _LABEL), _p("Description", _LABEL), _p("Amount", _LABEL)],
        [
            _p((start + timedelta(days=4)).strftime("%m/%d/%Y")),
            _p("Loan / credit payments"),
            _p("-" + doc.fields["existing_debt_payments"]),
        ],
        [
            _p((start + timedelta(days=14)).strftime("%m/%d/%Y")),
            _p("Direct deposit - PAYROLL"),
            _p("+" + doc.fields["payroll_deposits"]),
        ],
    ]
    table = Table(rows, colWidths=[1.3 * inch, 3.6 * inch, 1.6 * inch])
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC"))]))
    return table


def _story(doc: DocumentContent) -> list[Flowable]:
    story: list[Flowable] = [
        _p(_issuer(doc), _ISSUER),
        _p(TITLES[doc.doc_type], _TITLE),
        _p(SYNTHETIC_NOTICE, _NOTICE),
        Spacer(1, 14),
    ]
    if doc.doc_type is DocType.EMPLOYMENT_LETTER:
        story += _letter_body(doc)
    else:
        story.append(_kv_table(doc))
        if doc.doc_type is DocType.BANK_STATEMENT:
            story += [Spacer(1, 16), _p("Account activity", _TITLE), _transactions(doc)]
        if doc.doc_type is DocType.APPLICATION_FORM:
            story += [Spacer(1, 22), _p("Applicant signature: ______________________________")]
    return story


def _draw_footer(footer_text: str | None) -> Callable[[Canvas, SimpleDocTemplate], None]:
    def draw(canvas: Canvas, _doc: SimpleDocTemplate) -> None:
        if not footer_text:
            return
        canvas.saveState()
        canvas.setFont("Helvetica", 5.5)
        canvas.setFillGray(0.62)
        lines = simpleSplit(footer_text, "Helvetica", 5.5, letter[0] - 1.5 * inch)
        y = 0.55 * inch + 7 * (len(lines) - 1)
        for line in lines:
            canvas.drawString(0.75 * inch, y, line)
            y -= 7
        canvas.restoreState()

    return draw


def render_document(doc: DocumentContent, target: Path | io.BytesIO) -> int:
    """Write the PDF and return its page count (always 1; asserted)."""
    template = SimpleDocTemplate(
        target if isinstance(target, io.BytesIO) else str(target),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=1.0 * inch,
        title=f"{TITLES[doc.doc_type]} ({doc.filename})",
        author="credit-file-agent synthetic generator",
        subject=SYNTHETIC_NOTICE,
        invariant=1,
    )
    footer = _draw_footer(doc.footer_text)
    try:
        template.build(_story(doc), onFirstPage=footer, onLaterPages=footer)
    except LayoutError as exc:  # a single flowable is taller than the page
        raise ValueError(f"{doc.filename} does not fit on one page") from exc
    if template.page != 1:
        raise ValueError(f"{doc.filename} does not fit on one page (pages: {template.page})")
    return template.page


def render_bytes(doc: DocumentContent) -> bytes:
    buffer = io.BytesIO()
    render_document(doc, buffer)
    return buffer.getvalue()
