import pytest
from pydantic import ValidationError

from backend.a2a_transport.client import ValidationUnavailable
from backend.config import Settings
from backend.llm import MockLLM
from backend.research_agent.graph import build_research_graph
from backend.research_agent.schemas import ResearchPlan
from backend.research_agent.tools import mock_research
from backend.validation_agent.graph import build_validation_graph
from backend.validation_agent.schemas import ValidationResult

QUERY = "Research whether a momentum-based strategy could work for gold trading."


async def fixture_research():
    plan = await MockLLM().generate(ResearchPlan, "", {"query": QUERY})
    return mock_research(QUERY, plan)


async def test_research_graph_decomposes_query_and_validates_once():
    class StubValidator:
        calls = 0

        async def validate(self, research, report):
            self.calls += 1
            assert research.evidence_kind == "synthetic"
            return ValidationResult(verdict="insufficient_evidence", issues=["No empirical evidence"], recommendations=["Run historical tests"], confidence=0.9)

    validator = StubValidator()
    result = await build_research_graph(MockLLM(), validator).ainvoke({"query": QUERY})
    assert validator.calls == 1
    assert "gold" in result["plan"].hypothesis
    assert "20-day" in result["plan"].hypothesis
    assert len(result["plan"].tasks) >= 3
    assert "3.0%" in result["research"].evidence[1]
    assert "Final research conclusion" in result["reply"]
    assert "does not establish strategy profitability" in result["reply"]


async def test_research_graph_preserves_result_when_validator_fails():
    class Offline:
        async def validate(self, research, report):
            raise ValidationUnavailable("Validation Agent timed out.")

    result = await build_research_graph(MockLLM(), Offline()).ainvoke({"query": QUERY})
    assert result["validation"] is None
    assert result["research"].evidence
    assert "No independent verdict was obtained" in result["reply"]


async def test_validation_graph_flags_vague_hypothesis_and_unsupported_claim():
    research = (await fixture_research()).model_copy(update={"hypothesis": "Gold works", "evidence": [], "findings": ["Guaranteed profitable"]})
    result = await build_validation_graph(MockLLM()).ainvoke({"research": research})
    validation = result["validation"]
    assert validation.verdict == "insufficient_evidence"
    assert any("precise signal" in issue for issue in validation.issues)
    assert any("unsupported" in issue for issue in validation.issues)
    assert any("No evidence" in issue for issue in validation.issues)


async def test_validation_graph_overrides_llm_pass_for_synthetic_data():
    class OverconfidentLLM:
        async def generate(self, schema, instructions, payload):
            return ValidationResult(verdict="pass", issues=[], recommendations=[], confidence=1)

    result = await build_validation_graph(OverconfidentLLM()).ainvoke({"research": await fixture_research()})
    assert result["validation"].verdict == "insufficient_evidence"
    assert result["validation"].issues
    assert result["validation"].recommendations


@pytest.mark.parametrize("confidence", [-0.1, 1.1, float("nan")])
def test_confidence_is_bounded(confidence):
    with pytest.raises(ValidationError):
        ValidationResult(verdict="pass", issues=[], recommendations=[], confidence=confidence)


def test_real_llm_mode_requires_configuration():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_mode="openai", openai_api_key="", openai_model="")
