"""Models for generated synthetic files and their ground-truth labels."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import Field

from credit_agent.schemas import (
    Application,
    ApplicationStatus,
    DefectType,
    DocType,
    StrictModel,
)

Split = Literal["dev", "test"]


class DocumentContent(StrictModel):
    """One single-page document: what is printed, and the canonical truth of its key fields."""

    doc_type: DocType
    index: int = Field(default=1, ge=1)  # 1-based among documents of the same type
    fields: dict[str, str]  # as printed on the page (includes decorative fields)
    canonical: dict[str, str]  # normalized truth, ONLY for fields scored in extraction evals
    footer_text: str | None = None  # small print at the bottom (used to hide injection text)

    @property
    def filename(self) -> str:
        return f"{self.doc_type.value}_{self.index}.pdf"


class DefectLabel(StrictModel):
    defect_type: DefectType
    rule_ids: list[str]
    doc_types: list[DocType]
    field: str | None = None
    description: str
    near_threshold: bool = False


class HardNegativeLabel(StrictModel):
    """A legitimate variation that a good system must NOT report as a defect."""

    kind: str
    doc_type: DocType
    field: str
    description: str


class GroundTruth(StrictModel):
    application_id: str
    owner_id: str
    split: Split
    seed: int
    policy_version: str
    as_of_date: date
    defects: list[DefectLabel] = Field(default_factory=list)
    hard_negatives: list[HardNegativeLabel] = Field(default_factory=list)
    requires_mandatory_review: bool
    expected_status: Literal[ApplicationStatus.CLEAN, ApplicationStatus.NEEDS_REVIEW]


class GeneratedFile(StrictModel):
    application: Application
    documents: list[DocumentContent]
    ground_truth: GroundTruth
