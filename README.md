# Aurum: evidence-based research workflow

Aurum keeps its existing quantitative research dashboard, sidebar, navigation, and browser-local research sessions. The chat runs a Python Research Agent and contacts an independent Validation Agent over the official A2A protocol. New conversations are persisted in SQLite, with local Chroma semantic retrieval and an application context cache. An independent hourly job collects external XAU/USD spot observations.

## Quick start

Requirements: Python **3.11+**, Node.js compatible with the installed Next.js version, and npm. Run all commands below from the repository root. Research planning and assessment require a configured OpenAI-compatible provider. No mock model or synthetic research tool is available in the production path. Until a quantitative engine is registered, chat records an explicit blocked run without executing experiments. Semantic memory uses a real local embedding model; download its weights once before starting the Research API. The separate gold ingestion job calls the public price API.

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

After setup, embeddings run locally on CPU with `local_files_only=True`. `MEMORY_EMBEDDING_MODEL` can also name a provisioned local model directory. If weights or Chroma are unavailable, SQLite messages remain durable, semantic retrieval reports a miss, and bounded recent history still works. Errors are logged and failed indexing can be retried; there is no silent fake embedding fallback. `MEMORY_EMBEDDING_ADAPTER=fake` is an explicit test-only token-hashing adapter, independent of the configured LLM provider.

Before starting Validation, configure `OPENAI_API_KEY` and `OPENAI_MODEL` in `backend/.env`. A quantitative engine and explicit `RESEARCH_*` settings are also required for experimental execution; without an engine, Research returns a persisted blocked run.

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

The implementation pins **a2a-sdk 1.3.0** and uses its native **A2A 1.0 JSON-RPC** APIs: Agent Card discovery, `ClientConfig`, `create_client`, `SendMessageRequest`, `DefaultRequestHandler`, `AgentExecutor`, and SDK route factories. Request and response payloads use standard structured `Part.data` fields. A single response Message is used per review; there are no long-running A2A tasks, polling loops or automatic retries. The validator independently reviews each hypothesis, with at most one supplementary result and review per hypothesis.

Application schemas are Pydantic models; the A2A 1.0 wire models are SDK Protobuf messages. `backend/a2a_transport/` deliberately avoids shadowing the SDK's `a2a` package. The two agents share schema definitions, but no graph state or direct agent invocation. The validator process imports and runs its own compiled graph.

Main files:

- `backend/research_agent/`: research graph, quantitative integration contract, evidence checks, reports and schemas.
- `backend/validation_agent/`: independent review graph, schema, A2A server.
- `backend/a2a_transport/client.py`: official discovery/client, bounded timeout, structured response validation.
- `backend/api/main.py`: JSON API and optional live NDJSON progress stream.
- `backend/llm.py`: OpenAI-compatible structured JSON adapter; test doubles live only in backend/tests/.
- `backend/storage/`: SQLite message repository, local embedding adapters, persistent Chroma, semantic cache, retrieval and reconciliation.
- `backend/market_data/`: validated HTTP provider, immutable hourly observations, ingestion service and CLI.
- `backend/mcp/`: standalone web scraping MCP server and client; [usage and limits](./backend/mcp/README.md). Not yet connected to the research graph.
- `backend/mcp/tools/`: one package per MCP tool, containing its client, server, schemas and helper scripts.
- `backend/skills/`: one Skill folder per capability; [web-scraping](./backend/skills/web-scraping/SKILL.md) maps to `scrape_webpage` and is advertised in its MCP metadata.
- `app/api/chat/route.ts`, `lib/chat-api.ts`, `components/ChatInterface.tsx`, `app/types.ts`: minimal frontend integration.

## Web scraping MCP tool

The optional `scrape_webpage` tool fetches one public static webpage and returns its
title, body text, links, source URL, and retrieval timestamp. Results are labeled
`external_web_unverified`. No LLM or API key is needed. From the repository root:

```bash
# Starts a local MCP stdio subprocess, invokes the tool, then closes it.
backend/.venv/bin/python -m backend.mcp.tools.web_scraping.client https://example.com
```

See [MCP instructions](./backend/mcp/README.md) for dependency installation,
Streamable HTTP hosting, Python usage, and tests. The existing chat workflow does
not automatically invoke this tool.

## Configuration

Python loads `backend/.env`; environment variables take precedence. Next.js reads `.env.local`. The example files contain no credentials and are intentionally committed; real env files and the Python virtual environment are ignored.

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_MODE` | `openai` | Only the configured provider is supported in production. |
| `OPENAI_API_KEY` | empty | Required for `openai` mode; server-side only. |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Provider base URL, including `/v1` where applicable. |
| `OPENAI_MODEL` | empty | Your provider's model ID; required for `openai` mode. |
| `LLM_TIMEOUT_SECONDS` | `30` | Per-provider request timeout, up to 60 seconds. |
| `VALIDATION_AGENT_URL` | `http://127.0.0.1:8001` | Discovery URL and the validator's advertised origin. Match its actual port. |
| `A2A_TIMEOUT_SECONDS` | `45` | Combined discovery/messaging deadline, up to 70 seconds. |
| `RESEARCH_TIMEOUT_SECONDS` | `90` | Whole research workflow deadline, up to 100 seconds. |
| `RESEARCH_DATASET_ID` | required for an engine | Dataset identifier from the engine manifest registry. |
| `RESEARCH_DIAGNOSTIC_BUDGET` | required for an engine | Maximum diagnostic executions per hypothesis, 0–10. |
| `RESEARCH_SIGNIFICANCE_LEVEL` | required for an engine | Registered primary-family significance level, strictly between 0 and 1. |
| `RESEARCH_API_URL` | `http://127.0.0.1:8000` | Next.js server-only proxy target. |
| `SQLITE_PATH` | `backend/data/aurum.sqlite3` | Authoritative conversations, market observations, research evidence and reviews. |
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

The production research path contains no synthetic experiments. The quantitative engine is currently **not implemented or registered**. `panel.parquet` and `calendar.csv` alone do not provide factor computation, audited data manifests, backtesting or statistical correction. Chat persists `blocked` with `quantitative_engine_not_registered`; it does not manufacture results. Gold spot observations and conversation memory remain available independently.

The Agent orchestration, persistence and A2A boundary are implemented. Two distinct hypotheses are frozen before either primary experiment, both primary sequences precede family-wide correction, and optional diagnostic selections use the existing structured model interface. Python enforces action schemas and budgets. Independent validation retrieves archived evidence and cannot override mandatory provenance failures.

See [the quantitative integration contract](./docs/quantitative-workflow.md) for required engine interfaces, output paths, workflow continuation and limits. Test-only engines exercise orchestration; they do not establish mathematical correctness or empirical performance.

## Persistent context

The research graph pre-registers two hypotheses, executes their primary family, then processes bounded diagnostics and independent reviews. See the architecture and quantitative workflow documents for the full graph.

`context_build_up` retries pending indexing and embeds the query. It first checks a session-scoped application semantic cache for an exact or sufficiently similar query. A hit avoids another Chroma search. A miss searches `aurum_conversation_memory` with a mandatory session filter, applies the relevance threshold, and resolves IDs back to authoritative SQLite text. SQLite checks session ownership again. Useful matches enter the cache; no relevant match yields empty semantic context. Recent chronological history is supplied separately. Both share a strict character budget, which also bounds token usage; this is not model-specific tokenizer accounting.

The application cache stores query embeddings and message references, **not LLM Transformer KV tensors or final answers**. LRU evict entries, and changes to the session's message/index revision invalidate cached context (including changes written by another process). Consequently, cache reuse is conservative and a new completed turn normally invalidates earlier entries. Cache hits only avoid conversation retrieval; they do not skip the configured research workflow. Trace stages are `context_cache_hit`, `context_cache_miss`, `context_rag_hit`, `context_rag_miss`, and `context_build_complete` within the existing JSON/NDJSON event schema.

Planning receives explicitly labeled prior conversation and external observations. Configured LLM planning receives the bounded context. Final replies identify referenced messages. Price/current/latest/now questions conservatively bypass conversation retrieval. Every graph run reads market data separately; market snapshots never enter the context cache. Price responses identify the source quote timestamp, fetch timestamp, age and stale status. A stale or absent record never becomes a fabricated current price.

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

The existing chat submission remains:

```json
{"session_id":"demo-gold","message":"Research gold momentum."}
```

Responses include `round_id`, `reply`, workflow `status`, `mode`, `plan`, registered hypothesis records in `research`, persisted reviews in `validation`, and `trace`. Conversation and spot-observation fields remain available. Status is `queued`, `running`, `blocked`, `waiting_review` or `completed`; completed does not imply a validated hypothesis. The existing NDJSON stream remains progress events followed by one result or error.

An unavailable/invalid A2A peer leaves the run at `waiting_review` with `next_node=validate`. It is not a statistical rejection. Errors persist the run as `blocked` and remain visible. Resumption is explicit through `/chat` with the original `session_id`, `round_id`, a message, and `retry_failed: true` for a blocked run. Waiting review does not require `retry_failed`. There are no automatic retries. The Next.js proxy forwards these optional fields; no resume UI was added.

The Python API accepts an optional `request_id` to deduplicate the same submission. Reuse with a different session or question fails. Experiment run keys deduplicate completed computation and reviews are unique per result version. Research/LLM failures produce HTTP errors or an error event on an open stream. Next.js retains its existing request timeout; long-running engines must fit it or be invoked directly through the Python service.

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
research   freeze_hypotheses  Both specifications committed before primary experiments
research   evaluate_factor    Executing a registered experiment
research   multiple_testing   Correcting the complete registered family
research   validate           Submitting an archived result identifier
A2A        discovering        GET /.well-known/agent-card.json
A2A        sent               SendMessage: archived result and hypothesis references
A2A        received           Persisted independent review received
research   completed          All hypothesis branches finalized
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
