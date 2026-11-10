import asyncio
import logging
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message, Part, Role
from a2a.utils.errors import InternalError, InvalidParamsError, UnsupportedOperationError
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from pydantic import ValidationError
from starlette.applications import Starlette

from backend.config import Settings
from backend.llm import LLMError, StructuredLLM, make_llm
from backend.research_agent.schemas import ResearchResult
from backend.validation_agent.graph import build_validation_graph

logger = logging.getLogger("aurum.validation")


class ValidationExecutor(AgentExecutor):
    def __init__(self, llm: StructuredLLM, timeout: float):
        self.graph = build_validation_graph(llm)
        self.timeout = timeout

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        if message is None or message.role != Role.ROLE_USER:
            raise InvalidParamsError("A user Message with a structured ResearchResult is required")
        parts = [p for p in message.parts if p.HasField("data")]
        if len(parts) != 1:
            raise InvalidParamsError("Exactly one data Part containing ResearchResult is required")
        try:
            research = ResearchResult.model_validate(MessageToDict(parts[0].data))
        except ValidationError as exc:
            raise InvalidParamsError("ResearchResult schema validation failed") from exc
        logger.info("A2A received message_id=%s; independent validation started", message.message_id)
        try:
            async with asyncio.timeout(self.timeout):
                state = await self.graph.ainvoke({"research": research})
        except (LLMError, TimeoutError) as exc:
            raise InternalError("Validation assessment failed or timed out") from exc
        result = state["validation"]
        await event_queue.enqueue_event(Message(
            message_id=uuid4().hex, context_id=message.context_id,
            role=Role.ROLE_AGENT,
            parts=[Part(data=ParseDict(result.model_dump(), Value()))],
        ))
        logger.info("A2A replied message_id=%s verdict=%s", message.message_id, result.verdict)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError("This service uses single request/response messages, not persistent tasks")


def create_app(settings: Settings | None = None, llm: StructuredLLM | None = None):
    settings = settings or Settings()
    card = AgentCard(
        name="Aurum Validation Agent", version="1.0.0",
        description="Independent LangGraph review of synthetic research, hypothesis clarity and missing evidence.",
        supported_interfaces=[AgentInterface(
            url=f"{settings.validation_agent_url.rstrip('/')}/a2a/jsonrpc",
            protocol_binding="JSONRPC", protocol_version="1.0",
        )],
        capabilities=AgentCapabilities(streaming=False, push_notifications=False),
        default_input_modes=["application/json"], default_output_modes=["application/json"],
        skills=[AgentSkill(
            id="validate-research", name="Validate research evidence",
            description="Returns a structured assessment; synthetic research cannot establish profitability.",
            tags=["research", "validation", "synthetic"],
        )],
    )
    handler = DefaultRequestHandler(
        agent_executor=ValidationExecutor(llm or make_llm(settings), settings.llm_timeout_seconds + 2),
        task_store=InMemoryTaskStore(), agent_card=card,
    )
    return Starlette(routes=[
        *create_agent_card_routes(card),
        *create_jsonrpc_routes(handler, rpc_url="/a2a/jsonrpc"),
    ])
