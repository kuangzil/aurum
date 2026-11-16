import asyncio
import contextlib
import json
import logging
import secrets

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import Settings
from backend.llm import LLMError
from backend.market_data.provider import GoldAPIProvider, MarketDataUnavailable
from backend.market_data.repository import GoldRepository
from backend.market_data.service import sync_gold_price
from backend.research_agent.service import ChatRequest, ChatResponse, run_research
from backend.storage.memory import MemoryService, make_memory


def create_app(settings: Settings | None = None, memory: MemoryService | None = None,
               market: GoldRepository | None = None, provider: GoldAPIProvider | None = None):
    settings = settings or Settings()
    memory = memory or make_memory(settings)
    market = market or GoldRepository(memory.messages.db, settings.gold_stale_after_seconds)
    provider = provider or GoldAPIProvider(settings.gold_http_timeout_seconds, settings.gold_http_attempts)
    logging.getLogger("aurum").setLevel(logging.INFO)
    if not logging.getLogger("aurum").handlers:
        logging.getLogger("aurum").addHandler(logging.StreamHandler())
    app = FastAPI(title="Aurum Research Agent API")

    @app.get('/market/gold/latest')
    async def latest_gold():
        snapshot = await asyncio.to_thread(market.latest)
        if snapshot is None:
            raise HTTPException(404, 'No successfully ingested gold observation is available.')
        return JSONResponse(snapshot, headers={'Cache-Control': 'no-store'})

    @app.get('/market/gold/history')
    async def gold_history(limit: int = Query(default=24, ge=1, le=1000)):
        return JSONResponse({'snapshots': await asyncio.to_thread(market.history, limit)},
                            headers={'Cache-Control': 'no-store'})

    @app.post('/internal/jobs/sync-gold-price')
    async def sync_gold(authorization: str | None = Header(default=None)):
        token = settings.internal_job_token.get_secret_value()
        if not token:
            raise HTTPException(404, 'HTTP market-data trigger is disabled.')
        if not secrets.compare_digest((authorization or '').encode(), f'Bearer {token}'.encode()):
            raise HTTPException(401, 'Invalid job authorization.')
        try:
            return await sync_gold_price(market, provider)
        except MarketDataUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "research", "mode": settings.llm_mode}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        if "application/x-ndjson" not in request.headers.get("accept", ""):
            try:
                return await run_research(body, settings, memory=memory, market=market)
            except TimeoutError:
                return JSONResponse({"error": "Research request timed out."}, status_code=504)
            except LLMError as exc:
                return JSONResponse({"error": str(exc)}, status_code=502)

        async def stream():
            queue: asyncio.Queue = asyncio.Queue()

            async def report(event):
                await queue.put({"type": "progress", "event": event.model_dump()})

            async def produce():
                try:
                    result = await run_research(body, settings, report, memory=memory, market=market)
                    await queue.put({"type": "result", "result": result.model_dump()})
                except TimeoutError:
                    await queue.put({"type": "error", "error": "Research request timed out."})
                except LLMError as exc:
                    await queue.put({"type": "error", "error": str(exc)})
                except Exception:
                    logging.getLogger("aurum").exception("Research workflow failed")
                    await queue.put({"type": "error", "error": "Research workflow failed."})
                finally:
                    await queue.put(None)

            task = asyncio.create_task(produce())
            try:
                while (item := await queue.get()) is not None:
                    yield json.dumps(item) + "\n"
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    return app
