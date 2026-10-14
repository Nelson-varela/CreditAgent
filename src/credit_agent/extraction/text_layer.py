"""Zero-cost extractor that reads the text layer of a digital PDF (no OCR, no AWS).

It is a deterministic baseline for tests, CI and development, and a fallback when Textract is not
available. It is NOT a substitute for Textract in the headline metrics:
  * digital PDFs are the easy case, so accuracy is optimistic;
  * there is no OCR confidence, so the "low-confidence -> human review" path cannot be exercised.
Confidence is reported as 1.0 (exact embedded text); the extractor name travels with every result.
"""

from __future__ import annotations

import hashlib
import io
import re

from pypdf import PdfReader

from credit_agent.extraction.schema import LABELS
from credit_agent.extraction.types import RawExtraction, RawKeyValue, RawLine
from credit_agent.schemas import DocType

_DATE = r"\d{2}/\d{2}/\d{4}"
_LETTER_BODY = re.compile(
    r"This letter confirms that (?P<full_name>.+?) is currently employed by (?P<employer>.+?) "
    r"as (?P<job_title>.+?)\. The employee's start date is (?P<hire_date>" + _DATE + r")\."
)
_LETTER_SALARY = re.compile(r"monthly net salary is (?P<monthly_salary>\$[\d,]+\.\d{2})\.")
_LETTER_DATE = re.compile(r"^(?P<letter_date>" + _DATE + r")$")


class TextLayerExtractor:
    name = "pdf_text_layer"
    version = "1"

    def extract(self, pdf: bytes, doc_type: DocType) -> RawExtraction:
        reader = PdfReader(io.BytesIO(pdf))
        if len(reader.pages) != 1:
            raise ValueError(f"expected a single-page PDF, got {len(reader.pages)} pages")
        # "layout" keeps a label and its value on one line; the default mode sometimes splits them.
        text = reader.pages[0].extract_text(extraction_mode="layout") or ""
        lines = [" ".join(raw.split()) for raw in text.splitlines()]
        lines = [line for line in lines if line]

        key_values = (
            self._letter_pairs(lines)
            if doc_type is DocType.EMPLOYMENT_LETTER
            else self._labeled_pairs(lines, doc_type)
        )
        return RawExtraction(
            extractor=self.name,
            extractor_version=self.version,
            sha256=hashlib.sha256(pdf).hexdigest(),
            doc_type=doc_type,
            page_count=1,
            lines=[RawLine(block_id=f"p1-l{i}", page=1, text=t) for i, t in enumerate(lines)],
            key_values=key_values,
        )

    @staticmethod
    def _labeled_pairs(lines: list[str], doc_type: DocType) -> list[RawKeyValue]:
        pairs: list[RawKeyValue] = []
        labels = list(LABELS[doc_type].values())
        for i, line in enumerate(lines):
            for label in labels:
                prefix = f"{label}:".casefold()
                if line.casefold().startswith(prefix) and line[len(prefix) :].strip():
                    pairs.append(
                        RawKeyValue(
                            key=label,
                            value=line[len(prefix) :].strip(),
                            confidence=1.0,
                            block_id=f"p1-l{i}",
                        )
                    )
                    break
        return pairs

    @staticmethod
    def _letter_pairs(lines: list[str]) -> list[RawKeyValue]:
        prose = " ".join(lines)
        found: dict[str, str] = {}
        for pattern in (_LETTER_BODY, _LETTER_SALARY):
            match = pattern.search(prose)
            if match:
                found.update(match.groupdict())
        for line in lines:
            match = _LETTER_DATE.match(line)
            if match:
                found.update(match.groupdict())
                break
        return [
            RawKeyValue(key=alias, value=value, confidence=1.0, block_id="p1-prose")
            for alias, value in found.items()
        ]
