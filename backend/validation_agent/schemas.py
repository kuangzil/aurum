from typing import Literal

from pydantic import Field, JsonValue, field_validator

from backend.research_agent.schemas import Record


class ValidationRequest(Record):
    result_id: str
    hypothesis_id: str
    focus: str


class Followup(Record):
    action: Literal['regime_breakdown', 'lag_decay', 'capacity_proxy', 'correlation']
    parameters: dict[str, JsonValue]
    reason: str = Field(min_length=1)
    conclusion_impact: int = Field(ge=1, le=3)

    @field_validator('reason')
    @classmethod
    def qualitative_reason(cls, value):
        if any(character.isdigit() for character in value):
            raise ValueError('Put numerical followup settings in parameters, not narrative claims')
        return value


class Assessment(Record):
    unsupported_claims: list[str]
    strengths: list[str]
    critiques: list[str]
    statistical_assessment: str
    attribution_agreement: Literal['agree', 'partly_agree', 'disagree']
    suggested_verdict: Literal['accept', 'accept_with_caveats', 'needs_more_evidence', 'reject']
    requested_followups: list[Followup] = Field(max_length=3)


class ValidationResult(Assessment):
    review_id: str
    result_id: str
    provenance_check: Literal['passed', 'failed']
    provenance_errors: list[str]
