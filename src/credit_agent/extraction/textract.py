"""Amazon Textract extractor (synchronous ``AnalyzeDocument``, one page per call).

* Structured documents use FORMS (label/value pairs with confidence).
* The employment letter is prose, so it uses QUERIES (natural-language questions).
Textract is not an LLM, so text hidden in a document cannot instruct it: injection is a
downstream problem (the text is delivered to the model as data), not an extraction one.

Parsing is a pure function tested against real responses stored in ``tests/fixtures/textract``.
"""

from __future__ import annotations

import hashlib
import io
from decimal import Decimal
from typing import Any

import boto3
from botocore.config import Config
from pypdf import PdfReader

from credit_agent.config import Settings, get_settings
from credit_agent.extraction.schema import LETTER_QUERIES
from credit_agent.extraction.types import RawExtraction, RawKeyValue, RawLine
from credit_agent.schemas import DocType

# Documented limit of the synchronous API (see D-023).
MAX_SYNC_BYTES = 10 * 1024 * 1024


def make_textract_client(settings: Settings | None = None) -> Any:
    s = settings or get_settings()
    session = boto3.Session(profile_name=s.aws_profile, region_name=s.aws_region)
    return session.client(
        "textract",
        config=Config(
            retries={"mode": "adaptive", "max_attempts": s.max_retries + 1},
            connect_timeout=10,
            read_timeout=s.llm_timeout_s,
        ),
    )


def _unit(confidence: float | None) -> float:
    """Textract reports 0-100; the project uses 0-1."""
    return min(max((confidence or 0.0) / 100.0, 0.0), 1.0)


def _words(block: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    parts: list[str] = []
    for rel in block.get("Relationships", []):
        if rel["Type"] == "CHILD":
            parts += [index[i]["Text"] for i in rel["Ids"] if index[i]["BlockType"] == "WORD"]
    return " ".join(parts)


def parse_analyze_response(
    response: dict[str, Any], *, pdf_sha256: str, doc_type: DocType, features: list[str]
) -> RawExtraction:
    blocks: list[dict[str, Any]] = response["Blocks"]
    index = {b["Id"]: b for b in blocks}

    lines = [
        RawLine(
            block_id=b["Id"],
            page=b.get("Page", 1),
            text=b["Text"],
            confidence=_unit(b.get("Confidence")),
        )
        for b in blocks
        if b["BlockType"] == "LINE"
    ]

    pairs: list[RawKeyValue] = []
    for b in blocks:
        if b["BlockType"] == "KEY_VALUE_SET" and "KEY" in b.get("EntityTypes", []):
            value_block = next(
                (
                    index[i]
                    for r in b.get("Relationships", [])
                    if r["Type"] == "VALUE"
                    for i in r["Ids"]
                ),
                None,
            )
            if value_block is None:
                continue
            key, value = _words(b, index), _words(value_block, index)
            if key and value:  # an empty value (e.g. an unsigned signature line) is simply absent
                confidence = min(b.get("Confidence", 0.0), value_block.get("Confidence", 0.0))
                pairs.append(
                    RawKeyValue(
                        key=key,
                        value=value,
                        confidence=_unit(confidence),
                        block_id=value_block["Id"],
                        page=value_block.get("Page", 1),
                    )
                )
        elif b["BlockType"] == "QUERY":
            answer = next(
                (
                    index[i]
                    for r in b.get("Relationships", [])
                    if r["Type"] == "ANSWER"
                    for i in r["Ids"]
                ),
                None,
            )
            if answer is not None and answer.get("Text"):
                pairs.append(
                    RawKeyValue(
                        key=b["Query"]["Alias"],
                        value=answer["Text"],
                        confidence=_unit(answer.get("Confidence")),
                        block_id=answer["Id"],
                        page=answer.get("Page", 1),
                    )
                )

    return RawExtraction(
        extractor=TextractExtractor.name,
        extractor_version=TextractExtractor.version,
        sha256=pdf_sha256,
        doc_type=doc_type,
        page_count=response["DocumentMetadata"]["Pages"],
        features=features,
        lines=lines,
        key_values=pairs,
    )


def textract_cost(features: list[str], settings: Settings | None = None) -> Decimal:
    """Cost of one page; an unknown feature combination raises instead of reporting zero."""
    s = settings or get_settings()
    key = "+".join(sorted(f.lower() for f in features))
    try:
        return Decimal(str(s.textract_price_per_page_usd[key]))
    except KeyError:
        raise KeyError(f"no Textract price configured for features '{key}'") from None


class TextractExtractor:
    name = "textract"
    version = "1"

    def __init__(self, client: Any, queries: dict[str, str] | None = None) -> None:
        self._client = client
        self._queries = queries or LETTER_QUERIES

    def extract(self, pdf: bytes, doc_type: DocType) -> RawExtraction:
        if len(pdf) > MAX_SYNC_BYTES:
            raise ValueError("document exceeds the 10 MB limit of the synchronous API")
        pages = len(PdfReader(io.BytesIO(pdf)).pages)
        if pages != 1:  # fail before paying for a request Textract would reject
            raise ValueError(f"expected a single-page PDF, got {pages} pages")

        kwargs: dict[str, Any] = {}
        if doc_type is DocType.EMPLOYMENT_LETTER:
            features = ["QUERIES"]
            kwargs["QueriesConfig"] = {
                "Queries": [{"Text": text, "Alias": alias} for alias, text in self._queries.items()]
            }
        else:
            features = ["FORMS"]
        response = self._client.analyze_document(
            Document={"Bytes": pdf}, FeatureTypes=features, **kwargs
        )
        return parse_analyze_response(
            response,
            pdf_sha256=hashlib.sha256(pdf).hexdigest(),
            doc_type=doc_type,
            features=features,
        )
