import asyncio
import json
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from backend.a2a_transport.client import ValidationClient
from backend.config import ResearchSettings, Settings
from backend.llm import StructuredLLM, make_llm
from backend.market_data.repository import GoldRepository, describe_observation
from backend.research_agent import tools
from backend.research_agent.graph import build_research_graph
from backend.research_agent.report import research_report
from backend.research_agent.schemas import ResearchPlan
from backend.storage.research import ResearchRepository
from backend.trace import Reporter, TraceEvent, logger, no_report
from backend.storage.memory import MemoryService, make_memory, time_sensitive
from backend.validation_agent.schemas import ValidationResult


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra='forbid')
    session_id: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    request_id: str | None = None
    round_id: str | None = None
    retry_failed: bool = False


class ChatResponse(BaseModel):
    session_id: str
    round_id: str
    reply: str
    status: Literal['queued', 'running', 'waiting_review', 'blocked', 'completed']
    mode: Literal['openai']
    plan: ResearchPlan | None
    research: list[dict]
    validation: list[ValidationResult]
    trace: list[TraceEvent]
    user_message_id: str
    assistant_message_id: str
    context_source: str
    retrieved_message_ids: list[str]
    market_observation: dict | None


async def run_research(request: ChatRequest, settings: Settings, report: Reporter = no_report,
                       llm: StructuredLLM | None = None, memory: MemoryService | None = None,
                       market: GoldRepository | None = None, engine: tools.QuantEngine | None = None,
                       research_settings: ResearchSettings | None = None) -> ChatResponse:
    memory = memory if memory is not None else make_memory(settings)
    market = market if market is not None else GoldRepository(memory.messages.db, settings.gold_stale_after_seconds)
    repository = ResearchRepository(memory.messages.db)
    engine = engine if engine is not None else tools.engine
    user_message = await asyncio.to_thread(memory.messages.save, request.session_id, 'user', request.message,
        message_id='USER-' + request.request_id if request.request_id is not None else None)
    config = research_settings
    if engine is not None and config is None:
        config = ResearchSettings()
    if request.round_id is None:
        round_id = repository.create_run(request.session_id, request.message, request.request_id,
            config.dataset_id if config is not None else None, config.diagnostic_budget if config is not None else None,
            config.significance_level if config is not None else None, user_message["message_id"])
    else:
        round_id = request.round_id
        repository.resume(round_id, request.session_id, request.retry_failed)
        if config is not None and repository.run(round_id)['diagnostic_budget'] is None:
            run = repository.run(round_id)
            with repository.step(round_id, run['next_node'], dataset_id=config.dataset_id,
                    diagnostic_budget=config.diagnostic_budget, significance_level=config.significance_level):
                pass
    trace: list[TraceEvent] = []

    async def record(event: TraceEvent):
        trace.append(event)
        logger.info('%s', event.model_dump_json())
        await report(event)

    try:
        model = llm if llm is not None else make_llm(settings) if engine is not None else None
        graph = build_research_graph(model, ValidationClient(settings.validation_agent_url, settings.a2a_timeout_seconds),
                                     repository, engine, record, memory=memory, market=market)
        async with asyncio.timeout(settings.research_timeout_seconds):
            await graph.ainvoke({'round_id': round_id}, {'recursion_limit': 100})
    except BaseException as exc:
        run = repository.run(round_id)
        logger.exception('Research run %s failed at %s', round_id, run['next_node'])
        with repository.step(round_id, run['next_node'], state='blocked', error_code=f'{type(exc).__name__}: {exc}'):
            pass
        raise
    run = repository.run(round_id)
    await record(TraceEvent(agent='research', stage=run['state'], detail=f"Research run {round_id}: {run['state']}"))
    reply = run['report_text'] if run['state'] == 'completed' else research_report(repository, round_id)
    snapshot = await asyncio.to_thread(market.latest)
    if time_sensitive(run['question']) or any(word in run['question'].lower() for word in ('gold', 'xau')):
        reply = '### External market observation\n\n' + describe_observation(snapshot) + '\n\n' + reply
    context = json.loads(run['context_json'])
    hypotheses = repository.hypotheses(round_id)
    reviews = [repository.review(result['result_id']) for h in hypotheses for result in repository.results(h['hypothesis_id'])]
    response = ChatResponse(session_id=request.session_id, round_id=round_id, reply=reply, status=run['state'],
        mode='openai', plan=ResearchPlan.model_validate_json(run['plan_json']) if run['plan_json'] is not None else None,
        research=hypotheses, validation=[review for review in reviews if review is not None], trace=trace,
        user_message_id=user_message['message_id'], assistant_message_id=str(uuid4()),
        context_source=context['context_source'], retrieved_message_ids=context['retrieved_message_ids'], market_observation=snapshot)
    await asyncio.to_thread(memory.messages.save, request.session_id, 'assistant', response.reply,
                            message_id=response.assistant_message_id, metadata_json=response.model_dump_json())
    await asyncio.to_thread(memory.completed_turn, request.session_id, request.message,
                            user_message['message_id'], response.assistant_message_id)
    await asyncio.to_thread(memory.reconcile, request.session_id, 2)
    return response
