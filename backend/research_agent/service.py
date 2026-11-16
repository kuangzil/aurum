import asyncio
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.a2a_transport.client import ValidationClient
from backend.config import Settings
from backend.llm import StructuredLLM, make_llm
from backend.market_data.repository import GoldRepository
from backend.research_agent.graph import build_research_graph
from backend.research_agent.schemas import ResearchPlan, ResearchResult
from backend.trace import Reporter, TraceEvent, logger, no_report
from backend.storage.memory import MemoryService, make_memory
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
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    context_source: str = 'empty'
    retrieved_message_ids: list[str] = Field(default_factory=list)
    market_observation: dict | None = None


async def run_research(request: ChatRequest, settings: Settings, report: Reporter = no_report,
                       llm: StructuredLLM | None = None, memory: MemoryService | None = None,
                       market: GoldRepository | None = None) -> ChatResponse:
    memory = memory or make_memory(settings)
    market = market or GoldRepository(memory.messages.db, settings.gold_stale_after_seconds)
    user_message = await asyncio.to_thread(memory.messages.save, request.session_id, 'user', request.message)
    trace: list[TraceEvent] = []

    async def record(event: TraceEvent):
        trace.append(event)
        logger.info("%s", event.model_dump_json())
        await report(event)

    graph = build_research_graph(
        llm or make_llm(settings),
        ValidationClient(settings.validation_agent_url, settings.a2a_timeout_seconds),
        record,
        memory, market,
    )
    async with asyncio.timeout(settings.research_timeout_seconds):
        state = await graph.ainvoke({"query": request.message, 'session_id': request.session_id,
                                    'user_message_id': user_message['message_id']})
    await record(TraceEvent(agent="research", stage="completed", detail="Research conclusion ready"))
    response = ChatResponse(
        session_id=request.session_id, reply=state["reply"],
        status="completed" if state["validation"] else "validation_unavailable",
        mode=settings.llm_mode, plan=state["plan"], research=state["research"],
        validation=state["validation"], trace=trace,
        user_message_id=user_message['message_id'], context_source=state['context_source'],
        retrieved_message_ids=state['retrieved_message_ids'], market_observation=state.get('market_observation'),
        assistant_message_id=str(uuid4()),
    )
    await asyncio.to_thread(memory.messages.save, request.session_id, 'assistant', response.reply,
                            message_id=response.assistant_message_id, metadata_json=response.model_dump_json())
    await asyncio.to_thread(memory.completed_turn, request.session_id, request.message,
                            user_message['message_id'], response.assistant_message_id)
    # SQLite commits before indexing. Failure leaves pending/failed records for reconciliation.
    await asyncio.to_thread(memory.reconcile, request.session_id, 2)
    return response
