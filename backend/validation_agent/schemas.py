from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["pass", "needs_revision", "insufficient_evidence"]
    issues: list[str] = Field(max_length=30)
    recommendations: list[str] = Field(max_length=30)
    confidence: float = Field(
        ge=0, le=1,
        description="Confidence in this assessment, not probability of investment success",
    )
