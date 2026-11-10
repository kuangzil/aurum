import asyncio
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.a2a_transport.client import ValidationClient
from backend.config import Settings
from backend.llm import StructuredLLM, make_llm
from backend.research_agent.graph import build_research_graph
from backend.research_agent.schemas import ResearchPlan, ResearchResult
from backend.trace import Reporter, TraceEvent, logger, no_report
from backend.validation_agent.schemas import ValidationResult


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    session_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    status: Literal["completed", "validation_unavailable"]
    mode: Literal["mock", "openai"]
    plan: ResearchPlan
    research: ResearchResult
    validation: ValidationResult | None
    trace: list[TraceEvent]


async def run_research(request: ChatRequest, settings: Settings, report: Reporter = no_report, llm: StructuredLLM | None = None) -> ChatResponse:
    trace: list[TraceEvent] = []

    async def record(event: TraceEvent):
        trace.append(event)
        logger.info("%s", event.model_dump_json())
        await report(event)

    graph = build_research_graph(
        llm or make_llm(settings),
        ValidationClient(settings.validation_agent_url, settings.a2a_timeout_seconds),
        record,
    )
    async with asyncio.timeout(settings.research_timeout_seconds):
        state = await graph.ainvoke({"query": request.message})
    await record(TraceEvent(agent="research", stage="completed", detail="Research conclusion ready"))
    return ChatResponse(
        session_id=request.session_id, reply=state["reply"],
        status="completed" if state["validation"] else "validation_unavailable",
        mode=settings.llm_mode, plan=state["plan"], research=state["research"],
        validation=state["validation"], trace=trace,
    )
