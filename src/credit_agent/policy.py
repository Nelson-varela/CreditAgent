"""Typed loader for the risk policy (``data/policies/policy_v1.yaml``).

The YAML is the single source of truth: deterministic rules, the policy manual PDF and the
synthetic ground truth all read from it, so they cannot contradict each other.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from string import Formatter
from typing import Any

import yaml
from pydantic import Field, model_validator

from credit_agent.config import get_settings
from credit_agent.schemas import DefectType, Severity, StrictModel, SuggestedAction

_RULE_ID = re.compile(r"^R-\d+\.\d+$")


class PolicyParameters(StrictModel):
    """Every business threshold. Rules and generators read these, never literals."""

    monthly_interest_rate: float = Field(gt=0, lt=0.1)
    income_tolerance: float = Field(gt=0, lt=1)
    max_dti: float = Field(gt=0, lt=1)
    min_employment_months: int = Field(ge=0)
    min_amount_cop: int = Field(gt=0)
    max_amount_cop: int = Field(gt=0)
    mandatory_review_amount_cop: int = Field(gt=0)
    max_term_months: int = Field(gt=0)
    payslip_max_age_days: int = Field(gt=0)
    utility_bill_max_age_days: int = Field(gt=0)
    id_min_remaining_validity_days: int = Field(ge=0)
    required_payslips: int = Field(gt=0)
    required_bank_statements: int = Field(gt=0)

    @model_validator(mode="after")
    def _amounts_are_coherent(self) -> PolicyParameters:
        if self.min_amount_cop >= self.max_amount_cop:
            raise ValueError("min_amount_cop must be below max_amount_cop")
        if self.mandatory_review_amount_cop > self.max_amount_cop:
            raise ValueError("mandatory_review_amount_cop cannot exceed max_amount_cop")
        return self


class PolicyRule(StrictModel):
    rule_id: str
    title: str
    text: str  # template: placeholders are rendered from PolicyParameters
    # Informational rules (no defect_type) carry no severity or action.
    defect_type: DefectType | None = None
    severity: Severity | None = None
    suggested_action: SuggestedAction | None = None

    @model_validator(mode="after")
    def _defect_fields_go_together(self) -> PolicyRule:
        if not _RULE_ID.match(self.rule_id):
            raise ValueError(f"invalid rule_id '{self.rule_id}' (expected R-<section>.<n>)")
        has_defect = self.defect_type is not None
        if has_defect != (self.severity is not None) or has_defect != (
            self.suggested_action is not None
        ):
            raise ValueError(
                f"{self.rule_id}: defect_type, severity and suggested_action must be set together"
            )
        return self

    @property
    def placeholders(self) -> set[str]:
        return {name for _, name, _, _ in Formatter().parse(self.text) if name}


class PolicySection(StrictModel):
    section_id: str
    title: str
    intro: str
    rules: list[PolicyRule] = Field(min_length=1)

    @model_validator(mode="after")
    def _rule_ids_match_section(self) -> PolicySection:
        for rule in self.rules:
            if not rule.rule_id.startswith(f"R-{self.section_id}."):
                raise ValueError(f"{rule.rule_id} does not belong to section {self.section_id}")
        return self


class Policy(StrictModel):
    policy_version: str
    title: str
    effective_date: date
    currency: str
    parameters: PolicyParameters
    sections: list[PolicySection] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> Policy:
        rules = self.rules
        ids = [r.rule_id for r in rules]
        duplicated = {i for i in ids if ids.count(i) > 1}
        if duplicated:
            raise ValueError(f"duplicate rule ids: {sorted(duplicated)}")

        known = set(PolicyParameters.model_fields)
        for rule in rules:
            unknown = rule.placeholders - known
            if unknown:
                raise ValueError(f"{rule.rule_id} uses unknown parameters: {sorted(unknown)}")

        uncovered = set(DefectType) - {r.defect_type for r in rules}
        if uncovered:
            raise ValueError(f"defect types without a rule: {sorted(d.value for d in uncovered)}")
        return self

    @property
    def rules(self) -> list[PolicyRule]:
        return [rule for section in self.sections for rule in section.rules]

    def rule(self, rule_id: str) -> PolicyRule:
        for candidate in self.rules:
            if candidate.rule_id == rule_id:
                return candidate
        raise KeyError(f"unknown policy rule '{rule_id}'")

    def rules_for(self, defect_type: DefectType) -> list[PolicyRule]:
        return [r for r in self.rules if r.defect_type is defect_type]

    def render(self, rule_id: str) -> str:
        """Rule text with every parameter placeholder replaced by its value."""
        return self.rule(rule_id).text.format(**self.parameters.model_dump())


def parse_policy(raw: dict[str, Any]) -> Policy:
    return Policy.model_validate(raw)


def load_policy(path: Path | None = None) -> Policy:
    path = path or get_settings().policy_path
    with path.open(encoding="utf-8") as handle:
        return parse_policy(yaml.safe_load(handle))
