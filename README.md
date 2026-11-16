# Aurum: A2A research demo

Aurum keeps its existing quantitative research dashboard, sidebar, navigation, and browser-local research sessions. The chat runs a Python Research Agent and contacts an independent Validation Agent over the official A2A protocol. New conversations are persisted in SQLite, with local Chroma semantic retrieval and an application context cache. An independent hourly job collects external XAU/USD spot observations.

## Quick start

Requirements: Python **3.11+**, Node.js compatible with the installed Next.js version, and npm. Run all commands below from the repository root. The default deterministic research mode requires no API key and makes no external research or LLM calls. Semantic memory uses a real local embedding model; download its weights once before starting the Research API. The separate gold ingestion job calls the public price API.

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

Provision the embedding model once (internet required; weights stay in the Hugging Face cache outside Git):

```bash
backend/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

After setup, embeddings run locally on CPU with `local_files_only=True`. `MEMORY_EMBEDDING_MODEL` can also name a provisioned local model directory. If weights or Chroma are unavailable, SQLite messages remain durable, semantic retrieval reports a miss, and bounded recent history still works. Errors are logged and failed indexing can be retried; there is no silent fake embedding fallback. `MEMORY_EMBEDDING_ADAPTER=fake` is an explicit test-only token-hashing adapter, independent of `LLM_MODE=mock`.

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

See the [architecture diagram](./docs/architecture.md) for the frontend, API, agent workflow, A2A message flow, and memory boundaries.

There are two Python services. The Research Agent is hosted by the frontend-facing FastAPI process; a third Python API gateway is unnecessary for this MVP. Only the validator exposes an A2A server. The Research Agent is its A2A client and is separately addressable through `/chat`.

The implementation pins **a2a-sdk 1.3.0** and uses its native **A2A 1.0 JSON-RPC** APIs: Agent Card discovery, `ClientConfig`, `create_client`, `SendMessageRequest`, `DefaultRequestHandler`, `AgentExecutor`, and SDK route factories. Request and response payloads use standard structured `Part.data` fields. A single response Message is used; there are no long-running A2A tasks, polling loops, retries, or autonomous revision cycles. The validator is called once per research run.

Application schemas are Pydantic models; the A2A 1.0 wire models are SDK Protobuf messages. `backend/a2a_transport/` deliberately avoids shadowing the SDK's `a2a` package. The two agents share schema definitions, but no graph state or direct agent invocation. The validator process imports and runs its own compiled graph.

Main files:

- `backend/research_agent/`: research graph, synthetic tool, schemas, service orchestration.
- `backend/validation_agent/`: independent review graph, schema, A2A server.
- `backend/a2a_transport/client.py`: official discovery/client, bounded timeout, structured response validation.
- `backend/api/main.py`: JSON API and optional live NDJSON progress stream.
- `backend/llm.py`: injectable deterministic fixtures and OpenAI-compatible JSON adapter.
- `backend/storage/`: SQLite message repository, local embedding adapters, persistent Chroma, semantic cache, retrieval and reconciliation.
- `backend/market_data/`: validated HTTP provider, immutable hourly observations, ingestion service and CLI.
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
| `SQLITE_PATH` | `backend/data/aurum.sqlite3` | Authoritative sessions, messages and market observations. |
| `CHROMA_PATH` | `backend/data/chroma` | Rebuildable persistent conversation vectors. |
| `MEMORY_EMBEDDING_ADAPTER` | `sentence_transformers` | Real local embeddings; `fake` is explicitly for offline tests. |
| `MEMORY_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Provisioned model name or local path. |
| `MEMORY_TOP_K` | `5` | Maximum semantic messages per query. |
| `MEMORY_SIMILARITY_THRESHOLD` | `0.45` | Minimum cosine similarity for Chroma results. |
| `MEMORY_CACHE_SIMILARITY_THRESHOLD` | `0.92` | Minimum cosine similarity for semantic cache matches. |
| `MEMORY_CACHE_MAX_ENTRIES` | `128` | Global per-process LRU bound, with session isolation. |
| `MEMORY_MAX_CONTEXT_CHARS` | `6000` | Combined semantic and chronological context budget. |
| `MEMORY_RECENT_MESSAGES` | `4` | Recent session messages, separate from semantic retrieval. Set `0` to disable. |
| `GOLD_STALE_AFTER_SECONDS` | `7200` | Max quote/fetch age for freshness; checked on every read. |
| `GOLD_HTTP_TIMEOUT_SECONDS` | `10` | Per-attempt provider HTTP timeout. |
| `GOLD_HTTP_ATTEMPTS` | `3` | Bounded attempts with 1s/2s backoff on transient errors. |
| `INTERNAL_JOB_TOKEN` | empty | Server-only bearer token; empty disables HTTP sync. |

To use an LLM, set `LLM_MODE=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL` in `backend/.env`, then restart both Python services. The adapter calls `/chat/completions` with `response_format: {"type":"json_object"}` and validates the result with Pydantic. The chosen endpoint/model must support JSON mode. Provider errors produce explicit failures; they never silently switch to fixtures. The live-provider path is tested with deterministic HTTP responses; no paid provider calls are required by the tests.

## Evidence and scope

The mock research tool uses six hand-authored price-index points. Its 3% index change is simple synthetic arithmetic, **not a strategy return**. The tool never fetches current market prices or performs a backtest. LLM mode changes the research planning and independent assessment, not the synthetic data provenance.

The validation schema supports `pass`, `needs_revision`, and `insufficient_evidence`. This MVP accepts only synthetic research, so the validator enforces `insufficient_evidence` even if an LLM suggests a pass. A future genuine empirical-data integration would need an explicit provenance contract and a revised gate. Confidence measures confidence in the assessment, not a calibrated chance of investment success.

Mock mode uses transparent fixture-based planning and heuristic review. It covers the gold momentum example, a volatility hypothesis, and a generic research fallback that explicitly flags an undefined signal. Use configured LLM mode for broader query decomposition. Neither mode establishes profitability.

Browser-local sessions remain available. Only new messages received by the Python API and successful assistant replies become authoritative SQLite records; browser history is not uploaded or silently imported. Prior conversations are unverified context for research intent, never financial evidence. Spot snapshots are labeled external observations, separate from synthetic research. No backtesting, order execution, or trading is implemented. The internal write trigger is token-protected; chat and market reads remain local-demo endpoints without user authentication.

## Persistent context

The graph runs `START → context_build_up → intent → research → validate → summarize → END`.

`context_build_up` retries pending indexing and embeds the query. It first checks a session-scoped application semantic cache for an exact or sufficiently similar query. A hit avoids another Chroma search. A miss searches `aurum_conversation_memory` with a mandatory session filter, applies the relevance threshold, and resolves IDs back to authoritative SQLite text. SQLite checks session ownership again. Useful matches enter the cache; no relevant match yields empty semantic context. Recent chronological history is supplied separately. Both share a strict character budget, which also bounds token usage; this is not model-specific tokenizer accounting.

The application cache stores query embeddings and message references, **not LLM Transformer KV tensors or final answers**. LRU evict entries, and changes to the session's message/index revision invalidate cached context (including changes written by another process). Consequently, cache reuse is conservative and a new completed turn normally invalidates earlier entries. Cache hits still execute research and independent A2A validation. Trace stages are `context_cache_hit`, `context_cache_miss`, `context_rag_hit`, `context_rag_miss`, and `context_build_complete` within the existing JSON/NDJSON event schema.

Planning receives explicitly labeled prior conversation and external observations. Mock planning resolves simple follow-ups from earlier user statements; configured LLM planning receives the same bounded context. Final replies identify referenced messages. Price/current/latest/now questions conservatively bypass conversation retrieval. Every graph run reads market data separately; market snapshots never enter the context cache. Price responses identify the source quote timestamp, fetch timestamp, age and stale status. A stale or absent record never becomes a fabricated current price.

SQLite uses foreign keys, WAL, a 10-second busy timeout, parameterized queries and short-lived connections. Its tables are:

| Table | Durable fields and constraints |
| --- | --- |
| `sessions` | `session_id` primary key, `created_at_utc`, `updated_at_utc`. |
| `messages` | `message_id` primary key, session foreign key, `role`, original `content`, UTC creation time, `embedding_status` (`pending`/`indexed`/`failed`), optional response/trace `metadata_json`. Session/time and indexing-status indexes. |
| `gold_price_snapshots` | ID, symbol, source, currency, unit, exact decimal price stored as text, quote/fetch UTC times, UTC observed hour, ingestion-time stale flag. Unique `(source, symbol, currency, observed_hour_utc)`; hourly index. |

Messages have immutable UUIDs, and repository writes/upserts with the same ID are idempotent; conflicting reuse is rejected. Each accepted HTTP chat submission gets a new message ID (network retries are separate submissions). Chroma uses the SQLite ID, explicit cosine embeddings, and session/role/time/source/type metadata. SQLite commits first. If indexing fails or the process stops between the two writes, reconciliation retries stable-ID upserts without losing text or duplicating vectors.

Inspect authoritative history or retry indexing from the repository root:

```bash
backend/.venv/bin/python -m backend.storage history --session-id demo-gold --limit 20
backend/.venv/bin/python -m backend.storage reconcile --limit 1000
# Rebuild after losing the vector directory, or changing to a new empty CHROMA_PATH:
backend/.venv/bin/python -m backend.storage reconcile --reindex --limit 1000
```

The reconcile command exits `1` when pending records remain; rerun without `--reindex` to continue a larger batch. A model change requires a new empty Chroma directory plus reindexing; mixed model collections are rejected.

## Hourly gold observations

The reusable `sync_gold_price` service and CLI fetch [`GET https://api.gold-api.com/price/XAU`](https://gold-api.com/llms.txt) with httpx. Responses must contain XAU, USD, a finite positive Decimal price, and a timezone-aware quote timestamp. The provider defines prices as USD per troy ounce and timestamps as UTC. Invalid responses and exhausted HTTP retries create no record. Source and fetch timestamps are distinct. Prices are serialized as decimal strings to preserve precision.

Run one manual collection:

```bash
backend/.venv/bin/python -m backend.market_data
curl -s http://127.0.0.1:8000/market/gold/latest
curl -s 'http://127.0.0.1:8000/market/gold/history?limit=24'
```

Latest returns `404` until a valid quote is stored; history returns `{"snapshots": [...]}` newest hour first, with limits from 1 to 1000. Both report dynamic quote/fetch age, `is_stale`, `stale_at_ingestion`, and the evaluation time. Repeated/concurrent runs within an hour return the first stored snapshot without overwriting it. Unchanged quotes in later hours still create new collection records. Stale provider quotes are retained and explicitly flagged. Failed requests leave the last successful snapshot accessible with its actual age.

Configure an hourly external scheduler, for example this crontab entry (replace the absolute path and ensure the log directory exists):

```cron
0 * * * * cd /absolute/path/to/aurum && /absolute/path/to/aurum/backend/.venv/bin/python -m backend.market_data >> /absolute/path/to/aurum/backend/data/gold-sync.log 2>&1
```

Set the scheduler's timezone to UTC where supported; stored hour slots are always UTC regardless of the host timezone. A deployment scheduler can run the same CLI or call the protected endpoint once per hour. No scheduler starts inside FastAPI workers. Cron cannot run while its host is stopped or asleep; missed hours remain gaps, with no fabricated backfill.

For an HTTP scheduler, configure `INTERNAL_JOB_TOKEN` in the backend environment, then use the matching server-side secret:

```bash
curl -s -X POST http://127.0.0.1:8000/internal/jobs/sync-gold-price \
  -H "Authorization: Bearer $INTERNAL_JOB_TOKEN"
```

An unset token yields `404`, a missing/wrong bearer token yields `401`, and a provider failure yields `502`. Never use a `NEXT_PUBLIC_` variable for this token or put it in browser code. The CLI does not require the HTTP token.

For this local MVP, use one Research API process with persistent local disk. SQLite supports concurrent readers and serialized writers, including the separate ingestion job. Embedded Chroma is intended for local persistence, not shared network filesystems or uncoordinated multi-worker vector writes. Back up SQLite consistently (including WAL state) and retain or rebuild Chroma. Runtime databases, model weights and env files are ignored by Git. User authentication, session ownership enforcement at the HTTP boundary, retention/deletion, encryption, distributed scheduling and historical backfill remain deployment work. Session filtering prevents retrieval mixing; a client-supplied session ID is not an authentication credential. Freshness is an explicit age threshold, not a market-hours calendar. The model truncates long embedding inputs to its token window, while SQLite preserves full text.

## API and failure behavior

The existing request and primary response fields remain intact:

```json
{"session_id":"demo-gold","message":"Research whether a momentum-based strategy could work for gold trading."}
```

The response retains `session_id`, Markdown `reply`, `status`, `mode`, `plan`, `research`, `validation`, and `trace`. Additive fields are `user_message_id`, `assistant_message_id`, `context_source`, `retrieved_message_ids`, and `market_observation`. By default it is ordinary JSON. The chat requests `Accept: application/x-ndjson`, which emits progress events followed by one final result or an error. This UI progress stream is separate from the A2A transport, which uses standard non-streaming request/response messaging.

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
research   context_cache_miss     No eligible cached context
research   context_rag_miss       No relevant authoritative messages
research   context_build_complete Context ready before planning
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

Tests use deterministic LLM outputs, injected fake embeddings, actual temporary SQLite/Chroma directories, mocked gold HTTP responses and ephemeral loopback ports; all subprocesses are cleaned up. Restart tests launch separate interpreter processes. No test needs paid APIs, downloaded model weights, or live internet. The normal pytest command skips the production frontend test unless `--e2e` is supplied. Integration requires permission to bind local ports. The production build fetches the existing Geist fonts, so it needs access to Google Fonts. Python 3.14 can show third-party LangSmith/Chroma deprecation warnings; they do not affect test results.

Protocol and API references used: [official A2A SDK](https://github.com/a2aproject/a2a-python), [A2A 1.0 migration/API guide](https://a2aproject.github.io/a2a-python/docs/migrations/v1_0/), [LangGraph StateGraph](https://reference.langchain.com/python/langgraph/graph/state/StateGraph), and [OpenAI JSON output documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=chat). Next.js implementation follows the guides installed in `node_modules/next/dist/docs/`.

## Conservative working-memory router

Before the existing SemanticCache, MemoryService now checks a bounded, process-local working set per session. `MEMORY_WORKING_MAX_SESSIONS=128`, `MEMORY_WORKING_MAX_MESSAGES=20`, and `MEMORY_WORKING_MAX_CHARS=12000` configure it. Original SQLite IDs, text, role, timestamp, insertion order and retrieval source are retained. Oversized/incomplete sets are discarded; a hit must fit the final context budget without truncating evidence.

The first supported coverage rule is deliberately narrow: English ordinal risk questions such as “What risks does the third strategy have?” and Chinese “第三个策略有什么风险？”. Reuse requires a unique explicitly numbered list and a concrete risk explanation on the referenced item. Retrieval rank is never treated as strategy numbering. Unknown or ambiguous references, new topics/documents/time ranges, changed source text or reordered generated lists fall back to retrieval. Recognized ordinal questions without coverage bypass SemanticCache as well. Broader follow-up wording currently falls back conservatively; no routing LLM call is added.

Working memory compares the message-count/row-ID portion of the revision and rechecks every source against SQLite; indexing-status-only changes do not invalidate unchanged raw context. SemanticCache retains its original full revision, LRU and locking behavior. At successful turn completion, a single SQLite statement verifies that only the expected user/assistant writes advanced the session before advancing the working revision. Neither in-memory layer expires entries by elapsed time; capacity/LRU, revisions, explicit invalidation and process restart bound their lifetime. Original evidence stays labeled unverified conversation context.

Each request emits a `memory_route` trace with `retrieval_skipped`, `retrieval_latency_ms`, and `context_message_count`. Normal routes are `working_memory`, `exact_cache`, `semantic_cache`, and `chroma`. Freshness-sensitive market questions use the explicit `market_data` bypass and return no historical conversation context. Miss logs include reasons such as `message_revision_changed`, `missing_or_ambiguous_ordinal`, `missing_risk_evidence`, `authoritative_message_changed`, and `context_budget_insufficient`. `MemoryService.statistics()` returns process-local working/exact/semantic hit counts, actual Chroma calls and retrieval skips. It is an inspection method, not a new public endpoint.

`backend/tests/test_memory_router.py` exercises actual two-turn `run_research` calls: the working-memory path makes one Chroma call, versus two with L1 cleared between the same turns. Tests also cover missing risk evidence, wrong ordinal, session isolation, revision changes, source tampering, concurrent writes, response reordering and bounded context. Further coverage rules should use explicit item-to-source mappings rather than relaxing the current grammar or relying on query similarity alone.
