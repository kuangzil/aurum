# Aurum architecture

```mermaid
flowchart TD
    UI[Next.js chat and dashboard] --> Proxy[Next.js API routes]
    Proxy --> API[FastAPI Research service]
    API --> Context[context_build_up: conversation memory]
    Context --> Intent[intent]
    Intent --> Load[load_research_context: dataset manifest and archived lessons]
    Load --> Plan[generate_hypotheses: exactly two mechanisms]
    Plan --> Freeze[freeze_hypotheses: atomic registration]
    Freeze --> Main[execute_main_experiments: deterministic engine]
    Main --> Correction[multiple_testing_correction: complete primary family]
    Correction --> Select[select_current_hypothesis]
    Select --> Diagnose[research_diagnostics: bounded structured decisions]
    Diagnose --> Submit[submit_result: archived numerical references]
    Submit --> Validate[validate: A2A request with result_id]
    Validate --> Review{review_router}
    Review --> Supplement[supplementary_test: at most one per hypothesis]
    Supplement --> Submit
    Review --> Finalize[finalize_hypothesis: deterministic evidence gate]
    Finalize --> More{hypothesis_router}
    More --> Select
    More --> Summary[summarize: render persisted metrics]
    Summary --> Memory[update_memory: reviewed observations]
    Memory --> API
    Validate --> Waiting[waiting_review: persisted continuation]
    Load --> Blocked[blocked: missing engine or data]
    Main --> Blocked
    Waiting --> API
    Blocked --> API

    Validate --> Card[Validation Agent Card discovery]
    Card --> RPC[A2A JSON-RPC SendMessage]
    RPC --> Verify[Independent evidence retrieval and provenance checks]
    Verify --> Assessment[Methodological LLM assessment for eligible evidence]
    Assessment --> Gate[Mandatory provenance gate and persisted review]
    Verify --> Gate
    Gate --> Validate

    SQLite[(SQLite: conversations, spot observations,
    research runs, specifications, experiments, results, reviews, research memory)]
    Context --> SQLite
    Context --> Cache[Session working and semantic context caches]
    Cache --> Chroma[Chroma conversation vectors]
    Freeze --> SQLite
    Main --> SQLite
    Submit --> SQLite
    Verify --> SQLite
    Gate --> SQLite
    Memory --> SQLite
    GoldJob[Existing independent gold ingestion job] --> GoldAPI[External XAU/USD provider]
    GoldJob --> SQLite
    API --> SQLite
```

The existing two Python services and LangGraph orchestration remain. A2A is a non-streaming request/response exchange per review; the browser's NDJSON progress stream is separate. Both services use the same local SQLite file for independent evidence retrieval. Repository API separation is not database-level permission isolation.

The quantitative contributor implements the `QuantEngine` boundary. No engine is registered in production yet: research records an explicit blocked state. Test-only engines are never imported by production modules. See [the integration contract](./quantitative-workflow.md).

Frozen specifications precede experiments, and both registered primary sequences precede multiple-testing correction and review. Python, not the model, enforces execution order, numerical evidence references, diagnostic budget and supplementary allowance. Failed and insufficient-sample records remain archived. Models cannot turn mandatory provenance failures into accepted research.

Conversation memory retains its existing session-scoped SQLite, working-memory, semantic-cache and Chroma behavior. It supplies unverified context for interpreting requests. Research memory is separate, uses exact SQLite queries, and stores evidence/review references. Market observations remain separate from empirical strategy evidence; the collector, provider and market endpoints are unchanged.

Workflow state and continuation nodes are durable. Explicit resume can continue a waiting review or an acknowledged failed run. There are no automatic retries, distributed queues, additional agents or new services. The existing frontend receives truthful workflow status and the archived report; no dashboard redesign is involved.
