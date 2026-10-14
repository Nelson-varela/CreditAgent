"""Raw extraction output, independent of the backend (Textract or local)."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from credit_agent.schemas import DocType, StrictModel


class RawLine(StrictModel):
    block_id: str
    page: int = Field(ge=1)
    text: str
    # None when the backend has no per-line confidence (the PDF text layer is not OCR).
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class RawKeyValue(StrictModel):
    """A label/value pair (Textract FORMS) or a query answer (Textract QUERIES)."""

    key: str
    value: str
    confidence: float = Field(ge=0.0, le=1.0)
    block_id: str | None = None
    page: int = Field(default=1, ge=1)


class RawExtraction(StrictModel):
    extractor: str
    extractor_version: str
    sha256: str
    doc_type: DocType
    page_count: int = Field(ge=1)
    # Billable features (e.g. ["FORMS"]); empty for free extractors. Basis of the cost per document.
    features: list[str] = Field(default_factory=list)
    lines: list[RawLine]
    key_values: list[RawKeyValue]

    @property
    def full_text(self) -> str:
        """All text of the page, footer included (input for the injection detector)."""
        return "\n".join(line.text for line in self.lines)


class Extractor(Protocol):
    name: str
    version: str  # bump when the extractor's logic changes: it invalidates cached results

    def extract(self, pdf: bytes, doc_type: DocType) -> RawExtraction: ...
