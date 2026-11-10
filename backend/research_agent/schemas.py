from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResearchPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    objective: str = Field(min_length=1, max_length=2000)
    tasks: list[str] = Field(min_length=1, max_length=10)
    hypothesis: str = Field(min_length=1, max_length=2000)
    methodology: str = Field(min_length=1, max_length=4000)


class ResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=4000)
    hypothesis: str = Field(min_length=1, max_length=2000)
    methodology: str = Field(min_length=1, max_length=4000)
    evidence: list[str] = Field(max_length=30)
    findings: list[str] = Field(max_length=30)
    limitations: list[str] = Field(max_length=30)
    # No empirical evidence ingestion exists in this MVP. Provenance cannot be
    # promoted by an LLM or by an A2A caller claiming that a fixture is real.
    evidence_kind: Literal["synthetic"] = "synthetic"
