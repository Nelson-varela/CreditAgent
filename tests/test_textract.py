"""Textract extractor tested against REAL responses captured on 2026-10-14 (no AWS calls)."""

import io
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter

from credit_agent.config import Settings, get_settings
from credit_agent.extraction.fields import extract_fields, low_confidence_fields
from credit_agent.extraction.schema import LETTER_QUERIES
from credit_agent.extraction.scoring import score_document
from credit_agent.extraction.textract import (
    TextractExtractor,
    parse_analyze_response,
    textract_cost,
)
from credit_agent.generator.models import DocumentContent, GeneratedFile
from credit_agent.generator.render import render_bytes
from credit_agent.schemas import DocType, ExtractedField

FIXTURES = Path(__file__).parent / "fixtures" / "textract"
TRUTH = Path(__file__).parents[1] / "data" / "ground_truth" / "APP-0001.json"


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def truth() -> GeneratedFile:
    return GeneratedFile.model_validate_json(TRUTH.read_text(encoding="utf-8"))


def _doc(truth: GeneratedFile, doc_type: DocType) -> DocumentContent:
    return next(d for d in truth.documents if d.doc_type is doc_type)


class FakeClient:
    """Stands in for boto3's Textract client and records the request."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response, self.calls = response, []

    def analyze_document(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


# --------------------------------------------------------------------- parsing (FORMS)


def test_forms_response_yields_every_form_field(truth: GeneratedFile) -> None:
    raw = parse_analyze_response(
        _fixture("application_form_1.forms.json"),
        pdf_sha256="x",
        doc_type=DocType.APPLICATION_FORM,
        features=["FORMS"],
    )
    doc = _doc(truth, DocType.APPLICATION_FORM)
    score = score_document(extract_fields(raw), doc.canonical, doc.filename)
    assert score.wrong == [] and score.total == 7
    assert raw.page_count == 1 and raw.features == ["FORMS"]


def test_empty_values_and_spurious_pairs_do_not_become_fields() -> None:
    raw = parse_analyze_response(
        _fixture("application_form_1.forms.json"),
        pdf_sha256="x",
        doc_type=DocType.APPLICATION_FORM,
        features=["FORMS"],
    )
    keys = {kv.key for kv in raw.key_values}
    assert "Applicant signature:" not in keys  # empty value: dropped
    assert "Synthetic sample document" in keys  # real pair from the notice line...
    names = {f.name for f in extract_fields(raw)}  # ...but it maps to no field
    assert names == {
        "application_date",
        "full_name",
        "id_number",
        "date_of_birth",
        "address",
        "declared_monthly_income",
        "requested_amount",
        "term_months",
        "loan_purpose",
    }


def test_all_text_lines_are_kept_for_the_injection_detector() -> None:
    raw = parse_analyze_response(
        _fixture("application_form_1.forms.json"),
        pdf_sha256="x",
        doc_type=DocType.APPLICATION_FORM,
        features=["FORMS"],
    )
    assert len(raw.lines) == 22
    assert "PERSONAL LOAN APPLICATION" in raw.full_text
    assert all(0.0 <= (line.confidence or 0) <= 1.0 for line in raw.lines)


# -------------------------------------------------------------------- parsing (QUERIES)


def _letter_fields() -> dict[str, ExtractedField]:
    raw = parse_analyze_response(
        _fixture("employment_letter_1.queries.json"),
        pdf_sha256="x",
        doc_type=DocType.EMPLOYMENT_LETTER,
        features=["QUERIES"],
    )
    return {f.name: f for f in extract_fields(raw)}


def test_query_answers_are_mapped_and_scored(truth: GeneratedFile) -> None:
    fields = _letter_fields()
    doc = _doc(truth, DocType.EMPLOYMENT_LETTER)
    wrong = {name for name, _, _ in score_document(list(fields.values()), doc.canonical, "l").wrong}
    assert wrong == {"employer"}  # the real failure captured on 2026-10-14


def test_a_wrong_low_confidence_answer_is_routed_to_human_review() -> None:
    fields = _letter_fields()
    employer = fields["employer"]
    assert employer.normalized_value == "barbara daniel lewis"  # the employee's name, wrongly
    assert employer.confidence == pytest.approx(0.54, abs=0.01)
    flagged = {f.name for f in low_confidence_fields(list(fields.values()), 0.8)}
    assert "employer" in flagged  # caught by the threshold
    assert "job_title" in flagged  # a CORRECT answer at 75% is also flagged: the cost of the rule
    assert "full_name" not in flagged


def test_unparseable_values_are_flagged_even_with_high_confidence() -> None:
    fields = list(_letter_fields().values())
    broken = fields[0].model_copy(update={"normalized_value": None, "confidence": 0.99})
    assert low_confidence_fields([broken], 0.8) == [broken]


# ---------------------------------------------------------------------- the extractor


def test_extractor_asks_for_forms_on_structured_documents(truth: GeneratedFile) -> None:
    doc = _doc(truth, DocType.PAYSLIP)
    client = FakeClient(_fixture("application_form_1.forms.json"))
    TextractExtractor(client).extract(render_bytes(doc), DocType.PAYSLIP)
    call = client.calls[0]
    assert call["FeatureTypes"] == ["FORMS"] and "QueriesConfig" not in call
    assert isinstance(call["Document"]["Bytes"], bytes)


def test_extractor_sends_the_letter_queries(truth: GeneratedFile) -> None:
    client = FakeClient(_fixture("employment_letter_1.queries.json"))
    raw = TextractExtractor(client).extract(
        render_bytes(_doc(truth, DocType.EMPLOYMENT_LETTER)), DocType.EMPLOYMENT_LETTER
    )
    call = client.calls[0]
    assert call["FeatureTypes"] == ["QUERIES"]
    sent = {q["Alias"]: q["Text"] for q in call["QueriesConfig"]["Queries"]}
    assert sent == LETTER_QUERIES and len(sent) <= 15  # the sync API allows 15 queries per page
    assert raw.features == ["QUERIES"]


def test_extractor_rejects_multi_page_and_oversized_files_before_calling_aws() -> None:
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    writer.add_blank_page(612, 792)
    buffer = io.BytesIO()
    writer.write(buffer)

    client = FakeClient({})
    extractor = TextractExtractor(client)
    with pytest.raises(ValueError, match="single-page"):
        extractor.extract(buffer.getvalue(), DocType.PAYSLIP)
    with pytest.raises(ValueError, match="10 MB"):
        extractor.extract(b"0" * (10 * 1024 * 1024 + 1), DocType.PAYSLIP)
    assert client.calls == []  # nothing was sent, nothing was paid


# -------------------------------------------------------------------------------- cost


def test_prices_are_dated_and_match_the_official_price_list() -> None:
    s = get_settings()
    assert s.pricing_checked_on is not None
    assert textract_cost(["FORMS"]) == Decimal("0.05")
    assert textract_cost(["QUERIES"]) == Decimal("0.015")
    assert textract_cost(["QUERIES", "FORMS"]) == Decimal("0.055")


def test_cost_of_a_full_file_and_of_the_whole_batch() -> None:
    per_file = 8 * textract_cost(["FORMS"]) + textract_cost(["QUERIES"])
    assert per_file == Decimal("0.415")
    assert 40 * per_file == Decimal(
        "16.600"
    )  # upper bound: files with a missing document cost less


def test_unknown_feature_combination_fails_loudly() -> None:
    with pytest.raises(KeyError, match="no Textract price"):
        textract_cost(["TABLES"], Settings(_env_file=None))
