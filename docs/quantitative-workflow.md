# Quantitative workflow integration

The implementation follows `Aurum_Quant_Agent_MVP.md` and the supplied implementation requirements. The document was absent during the initial inspection and appeared in the repository before implementation of the database and workflow.

## Implemented boundary

`backend/research_agent/tools.py` defines `QuantEngine`. Its production `engine` is currently `None`; no quantitative functions were found in the repository. The quantitative contributor supplies an instance there, or injects it through `create_app(engine=...)`. This does not require changing the orchestration graph. No new dependencies, formulas, data ingestion or services were added.

The engine must provide:

- `engine_version`: stable implementation version.
- `actions`: implemented action names mapped to strict Pydantic override models (`extra='forbid'`). Do not advertise missing implementations.
- `list_datasets() -> list[DatasetManifest]`: audited, frozen manifests identifying source, file checksums, units, calendar, coverage, universe version and whether the data was previously observed. The engine owns file/checksum/data integrity verification.
- `validate_spec(spec, dataset)`: reject unsupported factor columns/operators, invalid execution clocks, overlapping labels, unavailable universe/benchmark data and incompatible windows. Both specifications pass this check before either is persisted/executed.
- `run_experiment(action, spec, dataset_version, overrides) -> ExperimentOutput`: synchronous deterministic computation, with no mutation of the supplied specification and no automatic retry.

Required actions are `evaluate_factor`, `walk_forward`, and `multiple_testing`. Optional diagnostics are `regime_breakdown`, `lag_decay`, `capacity_proxy`, and `correlation`. Only registered implementations can execute. `list_datasets` is the registry method, not an LLM-discretionary action.

Primary actions take the complete frozen specification and an empty override object. The engine must define a strict empty argument model for them. Diagnostics inherit the specification; override models describe diagnostic parameters only. Top-level keys that replace frozen fields are rejected. This implementation deliberately permits no supplementary specification changes. The archive has versioned specification keys, but no spec-changing diagnostic is exposed.

`ExperimentOutput` contains execution status (`success` or `insufficient_sample`), dataset/engine/specification versions, empirical/synthetic provenance, a JSON metrics tree and explicit limitations. Raise an exception for execution failure; the orchestrator records it as `failed` and propagates the error. The live workflow rejects a synthetic dataset before experimentation, and synthetic outputs cannot pass provenance verification.

Primary specifications register JSON Pointer paths into the complete output, beginning `/metrics/`, for their primary metric and p-value. Numerical claims contain references only; displayed values are resolved from archived JSON. Research interpretation and review prose reject numeric literals; proposed diagnostic settings belong in typed parameters. A fabricated metric path fails explicitly. Comparisons require two references. Failed and insufficient-sample records remain in the evidence history.

`multiple_testing` receives `MultipleTestingInput`: both registered primary hypothesis IDs, their primary experiment IDs, p-value paths, status and recorded p-values (null for insufficient samples), `method=bonferroni`, and the explicitly configured significance level. No correction formula is implemented by the Agent. Its `metrics` must satisfy `CorrectionMetrics`: the complete hypothesis ID family, `adjusted_p_values` keyed by hypothesis ID, and explicit `omissions`. Missing family members, missing adjusted values or omissions prevent acceptance. Supplementary testing does not replace this primary-family correction.

## Workflow and persistence

```text
context_build_up → intent → load_research_context → generate_hypotheses
→ freeze_hypotheses → execute_main_experiments → multiple_testing_correction
→ select_current_hypothesis → research_diagnostics → submit_result → validate
→ review_router
    supplementary_test → submit_result → validate → finalize_hypothesis
    finalize_hypothesis → hypothesis_router → next hypothesis / summarize
→ update_memory → END
```

SQLite contains `research_runs`, `factor_hypotheses`, `factor_experiments`, `research_results`, `validation_reviews`, and `research_memory`. `research.sql` initializes them through the existing `Database` connection management. Specifications, finalized experiments, result versions and reviews have immutable archive constraints. Evidence and continuation transitions use the same transaction; intermediate experiment completions retain the current execution node until its registered sequence finishes.

Run state contains `next_node`, current hypothesis/result/review IDs, explicit diagnostic budget and significance level, frozen dataset manifest, question/context, and archived plan/report. Graph state carries only `round_id`. SQLite, not Chroma, resolves experimental evidence. Conversation memory remains separate and is unverified planning context.

The diagnostic model chooses a structured action and validated parameters, observes persisted tool output, then chooses another action or stops. A Python loop bounds decisions, and the repository bounds executed experiments. Diagnostics and supplementary tests are exploratory. Previously observed primary data also remain exploratory and cannot independently confirm a hypothesis.

Each hypothesis has at most one persisted supplementary registration. A deterministic router selects the eligible review recommendation with greatest declared conclusion impact (ties retain review order). Identical completed work is reused by run key and still consumes the supplementary allowance. New submissions retain `supersedes_result_id`. The second review finalizes the branch; it cannot recursively request another test.

## Independent review

A2A 1.0 JSON-RPC still uses one request and one response Message per review. The request data is `ValidationRequest(result_id, hypothesis_id, focus)`. The validator reads the shared local SQLite archive independently through `ReviewRepository`, verifies ownership, all hypothesis experiment attempts, primary family completeness, dataset/engine/spec versions, empirical provenance, correction membership and numerical references. It persists and returns `ValidationResult`, including `review_id`, provenance findings and `accept`, `accept_with_caveats`, `needs_more_evidence` or `reject`.

Mandatory provenance failure produces a persisted `needs_more_evidence` review and cannot be overridden by the LLM. Valid evidence then receives methodological assessment. Research reads back the stored review and repeats provenance checks before finalization. Validated status requires passing provenance and independent acceptance. Inconsistent, synthetic, missing or exploratory-only primary evidence cannot become validated.

`ReviewRepository` exposes evidence-reading methods and review insertion. This is repository-level API separation, **not database-level security isolation**: both local processes have filesystem access to the same SQLite file.

Research memory stores reviewed metric references and branch outcomes, not unsupported causal explanations. Unresolved attribution remains explicitly unresolved in results and reports.

## Configuration and continuation

When an engine is present, configure `RESEARCH_DATASET_ID`, `RESEARCH_DIAGNOSTIC_BUDGET` (0–10), and `RESEARCH_SIGNIFICANCE_LEVEL` (between zero and one). Planning and methodological review require `LLM_MODE=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL`. Missing required configuration fails visibly; no default dataset, budget, provider substitution or mock experiment is used.

A2A timeout/invalid response persists `waiting_review`, preserving `next_node=validate`. A quantitative execution exception persists `blocked` with the current node and a failed experiment. Normal repeated delivery does not resume either state. Explicit continuation uses the existing Python `/chat` endpoint (also forwarded by `/api/chat`):

```json
{"session_id":"original-session","message":"Continue the archived run","round_id":"ROUND-…"}
```

For a blocked run, additionally send `"retry_failed":true`. Only an explicit continuation can mark an interrupted running attempt failed and start a new attempt. It never updates a finalized experiment. Successful run keys are reused; review requests return the existing review for that result. A run from another session is rejected. No recovery worker or scheduler is installed.

## Verification limits

Test fixtures are confined to `backend/tests/`. They exercise graph ordering, persistence, errors, bounded diagnostics/supplementation, independent provenance gates, A2A across separate processes, conversation memory and gold endpoints. They do not validate financial formulas or establish empirical results.

Still required from the quantitative contributor: audited manifest/data access, deterministic factor and account simulation, walk-forward, statistical testing/correction, and any registered diagnostics. No real-data end-to-end quantitative research is operational until those implementations and the provider configuration are supplied. The existing spot collector is unchanged and is not a historical backtest engine.

## Change inventory

- Research orchestration and contracts: `backend/research_agent/graph.py`, `schemas.py`, `service.py`, `tools.py`; new `evidence.py` and `report.py`.
- Durable evidence: new `backend/storage/research.sql`, `backend/storage/research.py`; initialization in `backend/storage/sqlite.py`.
- Independent review: `backend/validation_agent/graph.py`, `schemas.py`, `service.py`; `backend/a2a_transport/client.py`.
- Configuration/API: `backend/config.py`, `backend/llm.py`, `backend/.env.example`, `backend/api/main.py`.
- Minimal chat integration: `app/api/chat/route.ts` forwards continuation identifiers and requires the configured backend URL; `app/types.ts`, `lib/chat-api.ts`, and `components/ChatInterface.tsx` expose the actual workflow status.
- Tests: new `backend/tests/research_fixtures.py`, `research_fixture_server.py`, `test_research_workflow.py`; updated `conftest.py`, `test_agents.py`, `test_boundaries.py`, `test_integration.py`, `test_market_data.py`, `test_memory.py`, and `test_memory_router.py` for the new contract.
- Documentation: `README.md`, `docs/architecture.md`, and this document.

The dashboard, gold ingestion implementations, MCP work, quantitative data files and existing unrelated working-tree changes were not modified by this workflow task. No dependency was installed. No commit or push was made.

## Executed checks

- `backend/.venv/bin/python -m pytest -q --e2e --tb=short`: **136 passed**. Includes independent A2A subprocesses, production Next.js JSON/NDJSON proxy, validator outage, explicit resume without experiment replay, and the existing memory/market/MCP regression tests. Fourteen third-party Python deprecation warnings remain.
- `node --test lib/chat-api.test.mjs`: **5 passed**.
- `npm run lint`: passed.
- `npx tsc --noEmit`: passed.
- `npm run build`: passed. Turbopack required a sandbox-external build after its cached loopback-permission failure was cleared; project build settings were not changed.
- `git diff --check`: passed.

Live provider output, audited real-data engine execution, financial calculations and empirical research conclusions were not verified. No end-to-end quantitative validation is claimed.
