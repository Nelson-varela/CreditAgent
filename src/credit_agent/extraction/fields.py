"""Maps a raw extraction to typed ``ExtractedField`` objects for one document type."""

from __future__ import annotations

from difflib import SequenceMatcher

from credit_agent.extraction.schema import LABELS, canonicalize
from credit_agent.extraction.types import RawExtraction, RawKeyValue
from credit_agent.schemas import DocType, ExtractedField

# OCR can garble a few characters of a label ("Declared monthly net incme"); below this similarity a
# key is treated as unrelated rather than guessed.
LABEL_MATCH_THRESHOLD = 0.85


def _clean(text: str) -> str:
    return " ".join(text.casefold().rstrip(":").split())


def match_field(key: str, doc_type: DocType) -> str | None:
    """Field name for a printed label or a query alias; None when nothing matches well enough."""
    labels = LABELS[doc_type]
    if key in labels:  # query alias (employment letter)
        return key
    cleaned = _clean(key)
    best_name, best_score = None, 0.0
    for name, label in labels.items():
        score = SequenceMatcher(None, cleaned, _clean(label)).ratio()
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score >= LABEL_MATCH_THRESHOLD else None


def extract_fields(raw: RawExtraction) -> list[ExtractedField]:
    """One field per name (the most confident pair wins).

    A value that cannot be parsed is kept raw with ``normalized_value`` None, so it can be flagged.
    """
    best: dict[str, RawKeyValue] = {}
    for kv in raw.key_values:
        name = match_field(kv.key, raw.doc_type)
        if name is not None and (name not in best or kv.confidence > best[name].confidence):
            best[name] = kv

    fields: list[ExtractedField] = []
    for name, kv in best.items():
        try:
            normalized: str | None = canonicalize(name, kv.value)
        except ValueError:
            normalized = None
        fields.append(
            ExtractedField(
                name=name,
                value=kv.value,
                normalized_value=normalized,
                confidence=kv.confidence,
                doc_type=raw.doc_type,
                page=kv.page,
                source_block_id=kv.block_id,
            )
        )
    return fields


def low_confidence_fields(
    fields: list[ExtractedField], min_confidence: float
) -> list[ExtractedField]:
    """Fields below the threshold, or that could not be parsed: they need human review."""
    return [f for f in fields if f.confidence < min_confidence or f.normalized_value is None]
