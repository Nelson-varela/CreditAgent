"""On-disk cache so every document is extracted only once (cost control, reproducible evals).

Key = SHA-256 of the PDF bytes + document type, under the extractor's name and version. Changing
an extractor's logic (bumping ``version``) invalidates its cache without touching the others.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

from pydantic import ValidationError

from credit_agent.extraction.types import Extractor, RawExtraction
from credit_agent.schemas import DocType

log = logging.getLogger(__name__)


class CachedExtractor:
    def __init__(self, inner: Extractor, cache_dir: Path) -> None:
        self.inner = inner
        self.name = inner.name
        self.version = inner.version
        self._dir = cache_dir / inner.name / f"v{inner.version}"
        self.hits = 0
        self.misses = 0

    def _path(self, pdf: bytes, doc_type: DocType) -> Path:
        return self._dir / f"{hashlib.sha256(pdf).hexdigest()}-{doc_type.value}.json"

    def extract(self, pdf: bytes, doc_type: DocType) -> RawExtraction:
        path = self._path(pdf, doc_type)
        if path.exists():
            try:
                result = RawExtraction.model_validate_json(path.read_text(encoding="utf-8"))
            except (ValidationError, OSError, ValueError):
                log.warning("unreadable cache entry %s: extracting again", path.name)
            else:
                self.hits += 1
                return result
        result = self.inner.extract(pdf, doc_type)
        self.misses += 1
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json(indent=2), encoding="utf-8", newline="\n")
        os.replace(tmp, path)  # atomic: a crash never leaves a half-written entry
        return result
