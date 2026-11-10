import asyncio
import contextlib
import json
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.config import Settings
from backend.llm import LLMError
from backend.research_agent.service import ChatRequest, ChatResponse, run_research


def create_app():
    settings = Settings()
    logging.getLogger("aurum").setLevel(logging.INFO)
    if not logging.getLogger("aurum").handlers:
        logging.getLogger("aurum").addHandler(logging.StreamHandler())
    app = FastAPI(title="Aurum Research Agent API")

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": "research", "mode": settings.llm_mode}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest, request: Request):
        if "application/x-ndjson" not in request.headers.get("accept", ""):
            try:
                return await run_research(body, settings)
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
                    result = await run_research(body, settings, report)
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
