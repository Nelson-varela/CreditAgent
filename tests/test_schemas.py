from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from credit_agent.schemas import (
    ALLOWED_TRANSITIONS,
    HUMAN_ONLY_TARGETS,
    ApplicationStatus,
    AuditEvent,
    DefectType,
    DocType,
    Evidence,
    ExtractedField,
    Finding,
    FindingSource,
    Proposal,
    ProposalAction,
    ProposalStatus,
    Severity,
    SuggestedAction,
    can_transition,
)

NOW = datetime(2026, 6, 30, tzinfo=UTC)


def _finding(**overrides: object) -> Finding:
    data: dict[str, object] = {
        "finding_id": "f1",
        "defect_type": DefectType.NAME_MISMATCH,
        "severity": Severity.HIGH,
        "message": "Names differ",
        "evidence": [Evidence(doc_type=DocType.ID_DOCUMENT, page=1, field="name")],
        "source": FindingSource.RULE,
        "grounded": True,
        "suggested_action": SuggestedAction.VERIFY_IDENTITY,
    }
    data.update(overrides)
    return Finding(**data)  # type: ignore[arg-type]


def test_finding_requires_evidence_or_rule() -> None:
    with pytest.raises(ValidationError, match="evidence or a policy_rule_id"):
        _finding(evidence=[])
    assert _finding(evidence=[], policy_rule_id="R-1.3").policy_rule_id == "R-1.3"


def test_models_forbid_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _finding(user_id="analyst_2")


def test_confidence_must_be_a_probability() -> None:
    with pytest.raises(ValidationError):
        ExtractedField(name="n", value="v", confidence=1.2, doc_type=DocType.PAYSLIP, page=1)


def test_confirmed_proposal_needs_confirmer() -> None:
    base = {
        "proposal_id": "p1",
        "application_id": "a1",
        "action": ProposalAction.APPROVE,
        "created_by_session": "s1",
        "created_at": NOW,
        "updated_at": NOW,
    }
    assert Proposal(**base).status is ProposalStatus.PENDING_CONFIRMATION  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="who confirmed"):
        Proposal(**base, status=ProposalStatus.CONFIRMED)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="only valid on CONFIRMED"):
        Proposal(**base, confirmed_by="analyst_1")  # type: ignore[arg-type]
    ok = Proposal(**base, status=ProposalStatus.CONFIRMED, confirmed_by="analyst_1")  # type: ignore[arg-type]
    assert ok.confirmed_by == "analyst_1"


def test_audit_event_is_immutable() -> None:
    event = AuditEvent(
        event_id="e1", actor="analyst_1", action="confirm", target="p1", timestamp=NOW
    )
    with pytest.raises(ValidationError):
        event.actor = "analyst_2"  # type: ignore[misc]


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="e1", actor="a", action="x", target="t", timestamp=datetime(2026, 6, 30)
        )


def test_every_status_has_a_transition_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(ApplicationStatus)


def test_agent_can_never_approve_reject_or_request() -> None:
    for target in HUMAN_ONLY_TARGETS:
        for current in ApplicationStatus:
            assert not can_transition(current, target, by_human=False)


def test_human_can_decide_on_clean_and_needs_review() -> None:
    for current in (ApplicationStatus.CLEAN, ApplicationStatus.NEEDS_REVIEW):
        for target in HUMAN_ONLY_TARGETS:
            assert can_transition(current, target, by_human=True)


def test_lifecycle_paths() -> None:
    S = ApplicationStatus
    assert can_transition(S.RECEIVED, S.PROCESSING, by_human=False)
    assert can_transition(S.PROCESSING, S.NEEDS_REVIEW, by_human=False)
    assert can_transition(S.DOCUMENTS_REQUESTED, S.PROCESSING, by_human=False)
    assert not can_transition(S.RECEIVED, S.CLEAN, by_human=False)
    assert not can_transition(S.APPROVED, S.PROCESSING, by_human=True)  # terminal
    assert not can_transition(S.PROCESSING_FAILED, S.CLEAN, by_human=True)  # terminal
