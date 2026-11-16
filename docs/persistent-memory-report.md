# Persistent memory and hourly gold ingestion: implementation report

## Changes

- `backend/storage/{sqlite,embeddings,vectors,cache,memory}.py`, `__init__.py`, `__main__.py`: authoritative SQLite messages; explicit local sentence-transformer and test embedding adapters; persistent Chroma; bounded session-scoped semantic cache; retrieval and reconciliation; history/reindex CLI.
- `backend/market_data/{provider,repository,service}.py`, `__init__.py`, `__main__.py`: validated gold-api.com JSON adapter, precise immutable hourly snapshots, dynamic freshness, shared ingestion function and one-shot CLI.
- `backend/research_agent/graph.py`, `service.py`, `backend/llm.py`: context before planning, durable received messages and successful replies, simple deterministic follow-up resolution, separate external market observations, and freshness rechecked after validation.
- `backend/api/main.py`, `backend/config.py`, `backend/.env.example`: shared injectable dependencies, market endpoints, protected trigger and persistence/cache/provider settings.
- `backend/requirements.txt`, `requirements-dev.txt`: ChromaDB 1.5.9 and sentence-transformers 5.7.0; offline test setup.
- `backend/tests/test_memory.py`, `test_market_data.py`, `conftest.py`, `test_integration.py`: persistence/restart, isolation, recovery, cache, freshness, precision, hourly concurrency/idempotency, provider failures, API contracts, temporary service storage and updated first-node assertion.
- `lib/chat-api.ts`, `lib/chat-api.test.mjs`: new-message-only browser payload; historical browser-local records remain local.
- `.gitignore`, `eslint.config.mjs`: exclude runtime databases/model weights and vendor JavaScript in the Python virtual environment.
- `README.md`, `docs/architecture.md`: setup, architecture, inspection/recovery, scheduler and deployment guidance. Existing README/architecture work was preserved and extended.

## Durable schema and graph

SQLite contains `sessions` (session ID and creation/update UTC timestamps), `messages` (immutable message ID, session foreign key, role, raw content, creation time, indexing status, optional response/trace JSON), and `gold_price_snapshots` (ID, source, symbol, currency, unit, decimal price text, quote/fetch/hour UTC timestamps, ingestion stale flag). Market snapshots are unique by source/symbol/currency/hour. Foreign keys, WAL, busy timeout and indexes are enabled. Chroma's `aurum_conversation_memory` holds explicit embeddings and message metadata; original text is always resolved from SQLite.

`START → context_build_up → intent → research → validate → summarize → END`

The context node checks an application semantic cache, then falls back to session-filtered Chroma retrieval and authoritative SQLite reads. Recent history is separately bounded. Cache LRU and session revisions prevent reuse after relevant storage changes. Time-sensitive queries bypass conversation context. Market observations are read independently and their freshness is rechecked before the final reply. A2A discovery/JSON-RPC, validator-unavailable behavior, JSON/NDJSON contracts and synthetic `insufficient_evidence` enforcement remain intact.

## Endpoints and configuration

- `GET /market/gold/latest`: latest collected snapshot with current age/staleness; `404` before first successful ingestion.
- `GET /market/gold/history?limit=24`: newest hourly snapshots, limit 1–1000.
- `POST /internal/jobs/sync-gold-price`: bearer-token-protected sync; `404` when token is unset, `401` for invalid authorization, `502` on provider failure.
- Existing `/chat` adds message IDs, context source/retrieved IDs and market observation fields without removing prior fields.

Default paths: `SQLITE_PATH=backend/data/aurum.sqlite3`, `CHROMA_PATH=backend/data/chroma`. Default model: `sentence-transformers/all-MiniLM-L6-v2`. Retrieval: top-k 5, minimum similarity 0.45, cache similarity 0.92, maximum 128 entries, combined context 6000 characters and up to 4 recent messages. Gold freshness: 7200 seconds; HTTP timeout 10 seconds with up to 3 attempts. `INTERNAL_JOB_TOKEN` is empty/disabled by default. All settings are server-side.

## Local commands

From the repository root, install dependencies and provision the model once:

```bash
uv pip install --python backend/.venv/bin/python -r backend/requirements-dev.txt
backend/.venv/bin/python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"
```

Start each service in a separate terminal:

```bash
backend/.venv/bin/python -m uvicorn backend.validation_agent.service:create_app --factory --host 127.0.0.1 --port 8001
backend/.venv/bin/python -m uvicorn backend.api.main:create_app --factory --host 127.0.0.1 --port 8000
npm run dev
```

Collect once, inspect messages, or retry pending indexing:

```bash
backend/.venv/bin/python -m backend.market_data
backend/.venv/bin/python -m backend.storage history --session-id demo-gold
backend/.venv/bin/python -m backend.storage reconcile --limit 1000
curl -s http://127.0.0.1:8000/market/gold/latest
```

The README provides an hourly cron entry and HTTP scheduler instructions. No system crontab was changed.

## Executed validation

| Command | Result |
| --- | --- |
| `backend/.venv/bin/python -m pytest -q` | 59 passed, 1 expected e2e skip at that stage. |
| `backend/.venv/bin/python -m pytest -q --e2e` | Final suite: 62 passed, including two later adapter/freshness boundary tests. |
| `node --test lib/chat-api.test.mjs` | 5 passed. |
| `npm run lint` | Passed after excluding Python vendor JavaScript. |
| `npx tsc --noEmit` | Passed. |
| `npm run build` | Passed, production Next.js build. |
| `git diff --check` | Passed. |

The e2e run launched a production Next.js server and independent Research/Validation services, checked JSON and streamed replies, malformed requests and service outages. Python tests used real temporary SQLite/Chroma storage, separate restart processes, injected embeddings and mocked provider HTTP. Only third-party Python 3.14 deprecation warnings remain.

## Limitations and operational setup

The local embedding weights were not downloaded during implementation, and no live gold provider request was made; production model inference and live provider availability were not smoke-tested. Dependencies were installed and adapter behavior was verified offline. Provision the model and schedule the CLI to enable normal semantic retrieval and ongoing collections.

Use one Research API process with embedded Chroma on durable local disk. Cache reuse is conservative: new completed turns invalidate prior context entries. Model changes/vector-directory loss require reindexing. A stopped host cannot collect, and missed hours are not backfilled. HTTP chat retries create new submissions; repository/index writes are idempotent by stable ID. Public-demo session IDs are not authentication credentials; multi-user authentication, retention and deployment hardening remain outside this MVP. Spot observations do not implement strategy validation, historical backtesting or trading.
