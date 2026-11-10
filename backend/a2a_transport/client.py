import asyncio
from uuid import uuid4

import httpx
from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils.errors import A2AError
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value
from pydantic import ValidationError

from backend.research_agent.schemas import ResearchResult
from backend.trace import Reporter, TraceEvent, no_report
from backend.validation_agent.schemas import ValidationResult


class ValidationUnavailable(RuntimeError):
    pass


class ValidationClient:
    def __init__(self, url: str, timeout: float):
        self.url = url.rstrip("/")
        self.timeout = timeout

    async def validate(self, research: ResearchResult, report: Reporter = no_report) -> ValidationResult:
        message_id = uuid4().hex

        async def emit(agent, stage, detail):
            await report(TraceEvent(agent=agent, stage=stage, detail=detail, message_id=message_id))

        try:
            # One deadline covers discovery AND messaging, including slow peers.
            async with asyncio.timeout(self.timeout):
                async with httpx.AsyncClient(timeout=self.timeout) as http:
                    await emit("a2a", "discovering", "GET /.well-known/agent-card.json")
                    card = await A2ACardResolver(httpx_client=http, base_url=self.url).get_agent_card()
                    if not any(i.protocol_binding == "JSONRPC" and i.protocol_version == "1.0" for i in card.supported_interfaces):
                        raise ValueError("Validator must advertise A2A 1.0 JSONRPC")
                    await emit("a2a", "discovered", "Validation Agent Card resolved; A2A 1.0 JSONRPC")
                    config = ClientConfig(streaming=False, httpx_client=http, supported_protocol_bindings=["JSONRPC"])
                    async with await create_client(card, client_config=config) as client:
                        request = SendMessageRequest(message=Message(
                            message_id=message_id, role=Role.ROLE_USER,
                            parts=[Part(data=ParseDict(research.model_dump(), Value()))],
                        ))
                        await emit("a2a", "sent", "SendMessage: structured synthetic ResearchResult")
                        await emit("validation", "waiting", "Awaiting independent hypothesis and evidence review")
                        result = None
                        async for chunk in client.send_message(request):
                            if not chunk.HasField("message"):
                                raise ValueError("Expected the validator's single response Message")
                            parts = [p for p in chunk.message.parts if p.HasField("data")]
                            if len(parts) != 1 or result is not None:
                                raise ValueError("Expected exactly one structured validation response")
                            result = ValidationResult.model_validate(MessageToDict(parts[0].data))
                        if result is None:
                            raise ValueError("Validator returned no structured result")
                        await emit("a2a", "received", f"ValidationResult received: {result.verdict}")
                        return result
        except (TimeoutError, httpx.HTTPError, A2AError, ValidationError, ValueError) as exc:
            reason = "Validation Agent timed out." if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "Validation Agent unavailable or returned an invalid A2A response."
            await emit("a2a", "failed", reason)
            raise ValidationUnavailable(reason) from exc
