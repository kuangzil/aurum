# Aurum: A2A research demo

Aurum keeps its existing quantitative research dashboard, sidebar, navigation, and browser-local research sessions. The chat now runs a Python Research Agent and contacts an independent Validation Agent over the official A2A protocol.

## Quick start

Requirements: Python **3.11+**, Node.js compatible with the installed Next.js version, and npm. Run all commands below from the repository root. The default deterministic demo requires no API key and makes no external research or LLM calls.

```bash
npm install
python3.11 -m venv backend/.venv
source backend/.venv/bin/activate
python -m pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env
cp .env.example .env.local
```

Use an installed newer Python instead of `python3.11` if needed. Alternatively, with uv:

```bash
uv venv --python 3.11 backend/.venv
uv pip install --python backend/.venv/bin/python -r backend/requirements-dev.txt
```

Start these three processes in separate terminals, from the repository root:

```bash
# Terminal 1: independent Validation Agent, A2A JSON-RPC on port 8001
backend/.venv/bin/python -m uvicorn backend.validation_agent.service:create_app --factory --host 127.0.0.1 --port 8001
```

```bash
# Terminal 2: Research Agent + frontend-facing FastAPI, port 8000
backend/.venv/bin/python -m uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

```bash
# Terminal 3: existing frontend, port 3000
npm run dev
```

Open http://localhost:3000, choose Agent Chat, select or create a research session, and submit:

> Research whether a momentum-based strategy could work for gold trading.

The chat displays the proposed research, independent validation feedback, final conclusion, and an expandable timestamped A2A trace. During execution it shows the current agent and communication stage. The trace is saved with the message in the existing browser-local session storage.

## Architecture

```text
Existing ChatInterface
  → Next.js POST /api/chat (server-side proxy)
    → FastAPI POST /chat / Research Agent process (:8000)
      → LangGraph: intent → synthetic research → validate → summarize
        → official A2A client: discover Agent Card, SendMessage
          → independent Validation Agent process (:8001)
            → official A2A JSON-RPC server / AgentExecutor
              → separate LangGraph: assess → enforce provenance
            ← structured ValidationResult in an A2A Message data Part
      ← final research summary + research/validation schemas + trace
```

There are two Python services. The Research Agent is hosted by the frontend-facing FastAPI process; a third Python API gateway is unnecessary for this MVP. Only the validator exposes an A2A server. The Research Agent is its A2A client and is separately addressable through `/chat`.

The implementation pins **a2a-sdk 1.3.0** and uses its native **A2A 1.0 JSON-RPC** APIs: Agent Card discovery, `ClientConfig`, `create_client`, `SendMessageRequest`, `DefaultRequestHandler`, `AgentExecutor`, and SDK route factories. Request and response payloads use standard structured `Part.data` fields. A single response Message is used; there are no long-running A2A tasks, polling loops, retries, or autonomous revision cycles. The validator is called once per research run.

Application schemas are Pydantic models; the A2A 1.0 wire models are SDK Protobuf messages. `backend/a2a_transport/` deliberately avoids shadowing the SDK's `a2a` package. The two agents share schema definitions, but no graph state or direct agent invocation. The validator process imports and runs its own compiled graph.

Main files:

- `backend/research_agent/`: research graph, synthetic tool, schemas, service orchestration.
- `backend/validation_agent/`: independent review graph, schema, A2A server.
- `backend/a2a_transport/client.py`: official discovery/client, bounded timeout, structured response validation.
- `backend/api/main.py`: JSON API and optional live NDJSON progress stream.
- `backend/llm.py`: injectable deterministic fixtures and OpenAI-compatible JSON adapter.
- `app/api/chat/route.ts`, `lib/chat-api.ts`, `components/ChatInterface.tsx`, `app/types.ts`: minimal frontend integration.

## Configuration

Python loads `backend/.env`; environment variables take precedence. Next.js reads `.env.local`. The example files contain no credentials and are intentionally committed; real env files and the Python virtual environment are ignored.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_MODE` | `mock` | `mock` uses deterministic LLM fixtures; `openai` calls your compatible provider from both services. |
| `OPENAI_API_KEY` | empty | Required for `openai` mode; server-side only. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Provider base URL, including `/v1` where applicable. |
| `OPENAI_MODEL` | empty | Your provider's model ID; required for `openai` mode. |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-provider request timeout, up to 60 seconds. |
| `VALIDATION_AGENT_URL` | `http://127.0.0.1:8001` | Discovery URL and the validator's advertised origin. Match its actual port. |
| `A2A_TIMEOUT_SECONDS` | `45` | Combined discovery/messaging deadline, up to 70 seconds. |
| `RESEARCH_TIMEOUT_SECONDS` | `90` | Whole research workflow deadline, up to 100 seconds. |
| `RESEARCH_API_URL` | `http://127.0.0.1:8000` | Next.js server-only proxy target. |

To use an LLM, set `LLM_MODE=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `backend/.env`, then restart both Python services. The adapter calls `/chat/completions` with `response_format: {"type":"json_object"}` and validates the result with Pydantic. The chosen endpoint/model must support JSON mode. Provider errors produce explicit failures; they never silently switch to fixtures. The live-provider path is tested with deterministic HTTP responses; no paid provider calls are required by the tests.

## Evidence and scope

The mock research tool uses six hand-authored price-index points. Its 3% index change is simple synthetic arithmetic, **not a strategy return**. The tool never fetches current market prices or performs a backtest. LLM mode changes the research planning and independent assessment, not the synthetic data provenance.

The validation schema supports `pass`, `needs_revision`, and `insufficient_evidence`. This MVP accepts only synthetic research, so the validator enforces `insufficient_evidence` even if an LLM suggests a pass. A future genuine empirical-data integration would need an explicit provenance contract and a revised gate. Confidence measures confidence in the assessment, not a calibrated chance of investment success.

Mock mode uses transparent fixture-based planning and heuristic review. It covers the gold momentum example, a volatility hypothesis, and a generic research fallback that explicitly flags an undefined signal. Use configured LLM mode for broader query decomposition. Neither mode establishes profitability.

Research sessions remain browser-local. `session_id` correlates responses; each backend query is independent. Prior chat history is not used as research evidence or backend memory. No RAG, database, MCP tools, real backtesting, order execution, or trading is implemented. These local demo endpoints have no authentication; deployment hardening is outside this MVP.

## API and failure behavior

The existing request and primary response fields remain intact:

```json
{"session_id":"demo-gold","message":"Research whether a momentum-based strategy could work for gold trading."}
```

The response includes `session_id`, Markdown `reply`, `status`, `mode`, `plan`, `research`, `validation`, and `trace`. By default it is ordinary JSON. The chat requests `Accept: application/x-ndjson`, which emits progress events followed by one final result or an error. This UI progress stream is separate from the A2A transport, which uses standard non-streaming request/response messaging.

If the validator is offline, times out, or returns an invalid response, research is retained with `status: "validation_unavailable"`, `validation: null`, and a failed trace event. No validation result is fabricated. Research/LLM failure produces an HTTP error for JSON callers or an error event for an already-open progress stream. Next.js bounds the entire upstream request to 110 seconds; deployment hosts must permit the configured 120-second route duration.

Check discovery and research health:

```bash
curl -s http://127.0.0.1:8001/.well-known/agent-card.json
curl -s http://127.0.0.1:8000/health
```

End-to-end example through the frontend API:

```bash
curl -s http://localhost:3000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-gold","message":"Research whether a momentum-based strategy could work for gold trading."}' \
  | python3 -m json.tool
```

Add `-N -H 'Accept: application/x-ndjson'` and omit the final pipe to see live progress.

Representative trace (timestamps and message UUID are generated per request):

```text
research   planning      Defining objective, research tasks and a testable hypothesis
research   researching   Inspecting a synthetic fixture; no historical backtest
a2a        discovering   GET /.well-known/agent-card.json
a2a        discovered    Validation Agent Card resolved; A2A 1.0 JSONRPC
a2a        sent          SendMessage: structured synthetic ResearchResult
validation waiting       Awaiting independent hypothesis and evidence review
a2a        received      ValidationResult received: insufficient_evidence
research   summarizing   Preparing final conclusion with validation limitations
research   completed     Research conclusion ready
```

All A2A events carry the same outgoing `message_id`. The research service logs these structured trace events; the validator's Uvicorn access log confirms the network request to `/a2a/jsonrpc`.

## Verification

```bash
# Unit tests plus real HTTP integration between separate subprocesses
backend/.venv/bin/python -m pytest -q
# Frontend stream parsing, Unicode chunk boundaries, errors and JSON compatibility
node --test lib/chat-api.test.mjs
npm run lint
npx tsc --noEmit
npm run build
# Adds a temporary production Next.js server; tests both JSON and streamed responses,
# malformed frontend inputs, validator outage, and research API outage.
backend/.venv/bin/python -m pytest -q --e2e
```

Tests use deterministic LLM outputs and ephemeral loopback ports; all subprocesses are cleaned up. The normal pytest command skips the production frontend test unless `--e2e` is supplied. Integration requires permission to bind local ports. The production build fetches the existing Geist fonts, so it needs access to Google Fonts. Python 3.14 can show a third-party LangSmith deprecation warning; it does not affect test results.

Protocol and API references used: [official A2A SDK](https://github.com/a2aproject/a2a-python), [A2A 1.0 migration/API guide](https://a2aproject.github.io/a2a-python/docs/migrations/v1_0/), [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph), and [OpenAI JSON output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat). Next.js implementation follows the guides installed in `node_modules/next/dist/docs/`.
