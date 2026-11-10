from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.a2a_transport.client import ValidationUnavailable
from backend.llm import StructuredLLM
from backend.research_agent.schemas import ResearchPlan, ResearchResult
from backend.research_agent.tools import mock_research
from backend.trace import Reporter, TraceEvent, no_report
from backend.validation_agent.schemas import ValidationResult


class Validator(Protocol):
    async def validate(self, research: ResearchResult, report: Reporter) -> ValidationResult: ...


class ResearchState(TypedDict, total=False):
    query: str
    plan: ResearchPlan
    research: ResearchResult
    validation: ValidationResult | None
    validation_error: str | None
    reply: str


def build_research_graph(llm: StructuredLLM, validator: Validator, report: Reporter = no_report):
    async def intent(state: ResearchState):
        await report(TraceEvent(agent="research", stage="planning", detail="Defining objective, research tasks and a testable hypothesis"))
        plan = await llm.generate(
            ResearchPlan,
            "Decompose this quantitative research query into tasks and a testable hypothesis with a signal, horizon, benchmark and falsifiable outcome. Propose a methodology. No market data is available. Do not invent observations or backtest results.",
            {"query": state["query"]},
        )
        return {"plan": plan}

    async def research(state: ResearchState):
        await report(TraceEvent(agent="research", stage="researching", detail="Inspecting a synthetic fixture; no historical backtest"))
        return {"research": mock_research(state["query"], state["plan"])}

    async def validate(state: ResearchState):
        try:
            result = await validator.validate(state["research"], report)
            return {"validation": result, "validation_error": None}
        except ValidationUnavailable as exc:
            return {"validation": None, "validation_error": str(exc)}

    async def summarize(state: ResearchState):
        await report(TraceEvent(agent="research", stage="summarizing", detail="Preparing final conclusion with validation limitations"))
        plan, result, validation = state["plan"], state["research"], state["validation"]

        def bullets(items):
            return "\n".join(f"- {item}" for item in items)

        reply = (
            f"### Research Agent\n\n**Objective:** {plan.objective}\n\n"
            f"**Tasks**\n{bullets(plan.tasks)}\n\n"
            f"**Proposed hypothesis (unvalidated):** {result.hypothesis}\n\n"
            f"**Methodology:** {result.methodology}\n\n"
            f"**Synthetic evidence**\n{bullets(result.evidence)}\n\n"
            f"**Findings**\n{bullets(result.findings)}\n\n"
            f"**Limitations**\n{bullets(result.limitations)}\n\n"
            "### Validation Agent\n\n"
        )
        if validation:
            reply += (
                f"**Verdict:** {validation.verdict}\n\n"
                f"{bullets(validation.issues)}\n\n**Required next tests**\n{bullets(validation.recommendations)}\n\n"
                f"Assessment confidence: {validation.confidence:.0%}. This is not a probability of investment success.\n\n"
            )
        else:
            reply += f"**Validation unavailable:** {state['validation_error']} No independent verdict was obtained.\n\n"
        reply += (
            "### Final research conclusion\n\n"
            + ("The independent review found insufficient empirical evidence. " if validation and validation.verdict == "insufficient_evidence" else "The hypothesis remains empirically unvalidated. ")
            + "This run demonstrates a research workflow using synthetic inputs. It does not establish strategy profitability or describe current market conditions. Historical out-of-sample testing with costs is still required."
        )
        return {"reply": reply}

    graph = StateGraph(ResearchState)
    for name, node in [("intent", intent), ("research", research), ("validate", validate), ("summarize", summarize)]:
        graph.add_node(name, node)
    graph.add_edge(START, "intent")
    graph.add_edge("intent", "research")
    graph.add_edge("research", "validate")
    graph.add_edge("validate", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()
