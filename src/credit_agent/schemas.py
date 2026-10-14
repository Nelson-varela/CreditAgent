"""Domain schemas (Pydantic).

All models forbid unknown fields: they also validate structured LLM output, where a
silently ignored extra field would hide a prompt/contract drift.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- enums


class DocType(StrEnum):
    APPLICATION_FORM = "application_form"
    ID_DOCUMENT = "id_document"
    PAYSLIP = "payslip"
    EMPLOYMENT_LETTER = "employment_letter"
    BANK_STATEMENT = "bank_statement"
    UTILITY_BILL = "utility_bill"


class DefectType(StrEnum):
    MISSING_DOC = "MISSING_DOC"
    NAME_MISMATCH = "NAME_MISMATCH"
    ID_MISMATCH = "ID_MISMATCH"
    INCOME_MISMATCH = "INCOME_MISMATCH"
    ADDRESS_MISMATCH = "ADDRESS_MISMATCH"
    EXPIRED_DOC = "EXPIRED_DOC"
    STALE_PAYSLIP = "STALE_PAYSLIP"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    INJECTION_ATTEMPT = "INJECTION_ATTEMPT"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SuggestedAction(StrEnum):
    REQUEST_DOCUMENT = "request_document"
    REVIEW_INCOME = "review_income"
    VERIFY_IDENTITY = "verify_identity"
    VERIFY_ADDRESS = "verify_address"
    ESCALATE_SECURITY = "escalate_security"
    REVIEW_POLICY = "review_policy"


class FindingSource(StrEnum):
    RULE = "rule"
    LLM = "llm"


class ApplicationStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    CLEAN = "clean"
    NEEDS_REVIEW = "needs_review"
    PROCESSING_FAILED = "processing_failed"
    APPROVED = "approved"
    REJECTED = "rejected"
    DOCUMENTS_REQUESTED = "documents_requested"


class ProposalAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_DOCUMENT = "request_document"


class ProposalStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    DISCARDED = "DISCARDED"


# ------------------------------------------------------------------------ lifecycle

# received -> processing -> clean | needs_review | processing_failed
# clean | needs_review -> approved | rejected | documents_requested   (human action only)
# documents_requested -> processing                                  (when the document arrives)
ALLOWED_TRANSITIONS: dict[ApplicationStatus, frozenset[ApplicationStatus]] = {
    ApplicationStatus.RECEIVED: frozenset({ApplicationStatus.PROCESSING}),
    ApplicationStatus.PROCESSING: frozenset(
        {
            ApplicationStatus.CLEAN,
            ApplicationStatus.NEEDS_REVIEW,
            ApplicationStatus.PROCESSING_FAILED,
        }
    ),
    ApplicationStatus.CLEAN: frozenset(
        {
            ApplicationStatus.APPROVED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.DOCUMENTS_REQUESTED,
        }
    ),
    ApplicationStatus.NEEDS_REVIEW: frozenset(
        {
            ApplicationStatus.APPROVED,
            ApplicationStatus.REJECTED,
            ApplicationStatus.DOCUMENTS_REQUESTED,
        }
    ),
    ApplicationStatus.DOCUMENTS_REQUESTED: frozenset({ApplicationStatus.PROCESSING}),
    ApplicationStatus.PROCESSING_FAILED: frozenset(),
    ApplicationStatus.APPROVED: frozenset(),
    ApplicationStatus.REJECTED: frozenset(),
}

# The agent never decides: only a human may move a file into one of these states.
HUMAN_ONLY_TARGETS: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.APPROVED,
        ApplicationStatus.REJECTED,
        ApplicationStatus.DOCUMENTS_REQUESTED,
    }
)


def can_transition(
    current: ApplicationStatus, target: ApplicationStatus, *, by_human: bool
) -> bool:
    if target not in ALLOWED_TRANSITIONS[current]:
        return False
    return by_human or target not in HUMAN_ONLY_TARGETS


# --------------------------------------------------------------------------- models


class DocumentRef(_Model):
    """A document attached to an application (one single-page PDF)."""

    doc_type: DocType
    s3_key: str
    page_count: int = Field(default=1, ge=1)


class ExtractedField(_Model):
    name: str
    value: str
    normalized_value: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    doc_type: DocType
    page: int = Field(ge=1)
    source_block_id: str | None = None


class Evidence(_Model):
    doc_type: DocType
    page: int = Field(ge=1)
    field: str
    extracted_value: str | None = None  # None when the evidence is an absence (missing doc)
    expected_value: str | None = None


class Finding(_Model):
    finding_id: str
    defect_type: DefectType
    severity: Severity
    message: str
    evidence: list[Evidence] = Field(default_factory=list)
    policy_rule_id: str | None = None
    source: FindingSource
    grounded: bool
    suggested_action: SuggestedAction

    @model_validator(mode="after")
    def _must_cite_something(self) -> Finding:
        # Principle 5: every claim carries verifiable evidence or a policy rule.
        if not self.evidence and not self.policy_rule_id:
            raise ValueError("a finding needs evidence or a policy_rule_id")
        return self


class Application(_Model):
    application_id: str
    owner_id: str
    applicant_name: str
    amount_cop: int = Field(gt=0)
    term_months: int = Field(gt=0)
    status: ApplicationStatus
    received_at: AwareDatetime
    documents: list[DocumentRef] = Field(default_factory=list)
    review_reasons: list[str] = Field(default_factory=list)


class Proposal(_Model):
    proposal_id: str
    application_id: str
    action: ProposalAction
    params: dict[str, Any] = Field(default_factory=dict)
    status: ProposalStatus = ProposalStatus.PENDING_CONFIRMATION
    created_by_session: str
    confirmed_by: str | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _confirmation_is_consistent(self) -> Proposal:
        if self.status is ProposalStatus.CONFIRMED and not self.confirmed_by:
            raise ValueError("a CONFIRMED proposal must record who confirmed it")
        if self.status is not ProposalStatus.CONFIRMED and self.confirmed_by:
            raise ValueError("confirmed_by is only valid on CONFIRMED proposals")
        return self


class AuditEvent(_Model):
    """Immutable by construction: the audit log is append-only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    actor: str
    action: str
    target: str
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = None
    timestamp: AwareDatetime
