from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.llm import StructuredLLM
from backend.research_agent.schemas import ResearchResult
from backend.validation_agent.schemas import ValidationResult


class ValidationState(TypedDict, total=False):
    research: ResearchResult
    assessment: ValidationResult
    validation: ValidationResult


def build_validation_graph(llm: StructuredLLM):
    async def assess(state: ValidationState):
        result = await llm.generate(
            ValidationResult,
            "Independently review hypothesis clarity, evidence provenance, logical support, unsupported claims and missing tests. Synthetic data cannot establish profitability. Confidence is confidence in your assessment only.",
            {"research": state["research"].model_dump()},
        )
        return {"assessment": result}

    def enforce_provenance(state: ValidationState):
        assessment = state["assessment"]
        # All accepted research is synthetic in this MVP. The LLM cannot turn
        # synthetic evidence into an empirical pass, even under prompt injection.
        issue = "Synthetic evidence cannot validate the hypothesis or establish profitability."
        return {"validation": assessment.model_copy(update={
            "verdict": "insufficient_evidence",
            "issues": list(dict.fromkeys([*assessment.issues, issue])),
            "recommendations": list(dict.fromkeys([*assessment.recommendations, "Test the hypothesis on genuine historical data out of sample, including costs."])),
        })}

    graph = StateGraph(ValidationState)
    graph.add_node("assess", assess)
    graph.add_node("enforce_provenance", enforce_provenance)
    graph.add_edge(START, "assess")
    graph.add_edge("assess", "enforce_provenance")
    graph.add_edge("enforce_provenance", END)
    return graph.compile()
