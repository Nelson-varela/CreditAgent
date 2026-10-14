from datetime import date
from pathlib import Path

import pytest

from credit_agent.extraction.cache import CachedExtractor
from credit_agent.extraction.fields import extract_fields, match_field
from credit_agent.extraction.schema import LABELS, canonicalize, doc_type_from_filename
from credit_agent.extraction.scoring import aggregate_accuracy, score_document
from credit_agent.extraction.text_layer import TextLayerExtractor
from credit_agent.extraction.types import RawExtraction, RawKeyValue
from credit_agent.generator.build import generate_batch
from credit_agent.generator.models import GeneratedFile
from credit_agent.generator.render import render_bytes
from credit_agent.policy import load_policy
from credit_agent.schemas import DocType, ExtractedField

AS_OF = date(2026, 6, 30)


@pytest.fixture(scope="module")
def batch() -> list[GeneratedFile]:
    return generate_batch(40, 42, load_policy(), AS_OF)


# ------------------------------------------------------------------------------ schema


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [
        ("declared_monthly_income", "$7,340.99", "7340.99"),
        ("requested_amount", "$23,400.00", "23400.00"),
        ("date_of_birth", "12/07/1981", "1981-12-07"),
        ("full_name", "MUÑOZ, José A.", "jose a munoz"),
        ("id_number", "D55-615.322", "D55615322"),
        ("address", "45 Oak Ave Apt 4B, Austin, TX 73301", "45 oak avenue unit 4b austin tx 73301"),
        ("term_months", " 48 ", "48"),
        ("employer", "Smith, Jones and Brown", "smith jones and brown"),
        ("account_last4", " 4917 ", "4917"),
    ],
)
def test_canonicalize(field: str, raw: str, expected: str) -> None:
    assert canonicalize(field, raw) == expected


def test_canonicalize_rejects_unparseable_values() -> None:
    with pytest.raises(ValueError):
        canonicalize("net_salary", "about five thousand")
    with pytest.raises(ValueError):
        canonicalize("pay_period_end", "next Friday")


def test_doc_type_from_filename() -> None:
    assert doc_type_from_filename("payslip_2.pdf") is DocType.PAYSLIP
    assert doc_type_from_filename("bank_statement_3.pdf") is DocType.BANK_STATEMENT
    with pytest.raises(ValueError):
        doc_type_from_filename("notes.txt")


# ------------------------------------------------------------------------ text layer


def test_text_layer_reads_every_scored_field_of_every_document(batch: list[GeneratedFile]) -> None:
    """Plumbing check, not a quality claim: digital PDFs are the easy case (see D-025)."""
    extractor, scores = TextLayerExtractor(), []
    for file in batch:
        for doc in file.documents:
            raw = extractor.extract(render_bytes(doc), doc.doc_type)
            scores.append(score_document(extract_fields(raw), doc.canonical, doc.filename))
    failures = [(s.filename, s.wrong) for s in scores if s.wrong]
    assert not failures, failures[:3]
    assert len(scores) > 300 and aggregate_accuracy(scores) == 1.0


def test_hidden_footer_text_is_kept_for_the_injection_detector(batch: list[GeneratedFile]) -> None:
    extractor, checked = TextLayerExtractor(), 0
    for file in batch:
        for doc in file.documents:
            if doc.footer_text:
                raw = extractor.extract(render_bytes(doc), doc.doc_type)
                assert " ".join(doc.footer_text.split()) in " ".join(raw.full_text.split())
                checked += 1
    assert checked >= 1


def test_injection_text_is_never_taken_as_a_field_value(batch: list[GeneratedFile]) -> None:
    extractor = TextLayerExtractor()
    for file in batch:
        for defect in file.ground_truth.defects:
            if defect.defect_type.value != "INJECTION_ATTEMPT":
                continue
            text = defect.details["text"]
            for doc in file.documents:
                raw = extractor.extract(render_bytes(doc), doc.doc_type)
                for field in extract_fields(raw):
                    if field.name in doc.canonical:  # scored fields only
                        assert text not in field.value


def test_text_layer_rejects_multi_page_pdfs() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    writer.add_blank_page(612, 792)
    import io

    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ValueError, match="single-page"):
        TextLayerExtractor().extract(buffer.getvalue(), DocType.PAYSLIP)


# ------------------------------------------------------------------------ field mapping


def test_fuzzy_label_matching_tolerates_ocr_noise() -> None:
    assert match_field("Declared monthly net incme:", DocType.APPLICATION_FORM) == (
        "declared_monthly_income"
    )
    assert match_field("FULL NAME", DocType.APPLICATION_FORM) == "full_name"
    assert match_field("Residential adress", DocType.APPLICATION_FORM) == "address"


def test_unrelated_keys_are_ignored_not_guessed() -> None:
    assert match_field("Applicant signature", DocType.APPLICATION_FORM) is None
    assert match_field("Total", DocType.BANK_STATEMENT) is None


def test_every_label_maps_to_its_own_field() -> None:
    for doc_type, labels in LABELS.items():
        for name, label in labels.items():
            assert match_field(label, doc_type) == name, (doc_type, name)


def test_most_confident_pair_wins_and_bad_values_are_flagged() -> None:
    def kv(value: str, conf: float) -> RawKeyValue:
        return RawKeyValue(key="Net pay", value=value, confidence=conf)

    raw = RawExtraction(
        extractor="x",
        extractor_version="1",
        sha256="0",
        doc_type=DocType.PAYSLIP,
        page_count=1,
        lines=[],
        key_values=[
            kv("$1,000.00", 0.60),
            kv("$1,200.00", 0.95),
            RawKeyValue(key="Pay period end", value="someday", confidence=0.9),
        ],
    )
    by_name = {f.name: f for f in extract_fields(raw)}
    assert by_name["net_salary"].normalized_value == "1200.00"
    assert by_name["pay_period_end"].normalized_value is None  # kept raw, flagged unparseable


def test_score_document_reports_wrong_and_missing_fields() -> None:
    fields = [
        ExtractedField(
            name="net_salary",
            value="$1",
            normalized_value="1.00",
            confidence=1.0,
            doc_type=DocType.PAYSLIP,
            page=1,
        )
    ]
    score = score_document(fields, {"net_salary": "2.00", "employer": "acme"}, "payslip_1.pdf")
    assert (score.correct, score.total) == (0, 2)
    assert ("employer", "acme", None) in score.wrong
    assert score.accuracy == 0.0


# ----------------------------------------------------------------------------- cache


class CountingExtractor:
    name, version = "counting", "1"

    def __init__(self) -> None:
        self.calls = 0

    def extract(self, pdf: bytes, doc_type: DocType) -> RawExtraction:
        self.calls += 1
        return (
            TextLayerExtractor().extract(pdf, doc_type).model_copy(update={"extractor": "counting"})
        )


def test_cache_extracts_each_document_once(tmp_path: Path, batch: list[GeneratedFile]) -> None:
    doc = batch[0].documents[0]
    pdf = render_bytes(doc)
    inner = CountingExtractor()
    cached = CachedExtractor(inner, tmp_path)
    first = cached.extract(pdf, doc.doc_type)
    second = cached.extract(pdf, doc.doc_type)
    assert first == second and inner.calls == 1
    assert (cached.hits, cached.misses) == (1, 1)

    # a new process (new instance) still hits the persisted entry
    again = CachedExtractor(CountingExtractor(), tmp_path)
    again.extract(pdf, doc.doc_type)
    assert again.hits == 1 and again.inner.calls == 0  # type: ignore[attr-defined]


def test_cache_key_separates_documents_types_and_versions(
    tmp_path: Path, batch: list[GeneratedFile]
) -> None:
    pdf = render_bytes(batch[0].documents[0])
    inner = CountingExtractor()
    cached = CachedExtractor(inner, tmp_path)
    cached.extract(pdf, DocType.APPLICATION_FORM)
    cached.extract(pdf, DocType.ID_DOCUMENT)  # same bytes, other type: separate entry
    cached.extract(render_bytes(batch[1].documents[0]), DocType.APPLICATION_FORM)
    assert inner.calls == 3

    inner.version = "2"  # logic changed: old entries must not be reused
    bumped = CachedExtractor(inner, tmp_path)
    bumped.extract(pdf, DocType.APPLICATION_FORM)
    assert inner.calls == 4


def test_corrupted_cache_entry_is_re_extracted(tmp_path: Path, batch: list[GeneratedFile]) -> None:
    doc = batch[0].documents[0]
    pdf = render_bytes(doc)
    inner = CountingExtractor()
    cached = CachedExtractor(inner, tmp_path)
    cached.extract(pdf, doc.doc_type)
    entry = next(tmp_path.rglob("*.json"))
    entry.write_text("{not json", encoding="utf-8")
    cached.extract(pdf, doc.doc_type)
    assert inner.calls == 2
    RawExtraction.model_validate_json(entry.read_text(encoding="utf-8"))  # healed
