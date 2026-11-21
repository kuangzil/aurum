CREATE TABLE IF NOT EXISTS research_runs (
    round_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, question TEXT NOT NULL, user_message_id TEXT NOT NULL,
    request_id TEXT UNIQUE, dataset_id TEXT, dataset_version TEXT, manifest_json TEXT,
    plan_json TEXT, proposal_json TEXT, report_text TEXT, context_json TEXT, diagnostic_budget INTEGER,
    significance_level REAL, state TEXT NOT NULL CHECK(state IN
        ('queued','running','waiting_review','blocked','completed')),
    next_node TEXT NOT NULL, current_hypothesis_id TEXT, result_id TEXT, review_id TEXT,
    error_code TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS factor_hypotheses (
    hypothesis_id TEXT NOT NULL, round_id TEXT NOT NULL REFERENCES research_runs(round_id),
    parent_hypothesis_id TEXT, mechanism TEXT NOT NULL, rationale TEXT NOT NULL,
    factor_spec_json TEXT NOT NULL, spec_version INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('proposed','testing','validated','rejected','needs_more_data','decayed')),
    evidence_summary TEXT, supplementary_json TEXT, PRIMARY KEY(hypothesis_id,spec_version)
);
CREATE TABLE IF NOT EXISTS factor_experiments (
    experiment_id TEXT PRIMARY KEY, run_key TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL, action TEXT NOT NULL, spec_version INTEGER NOT NULL,
    dataset_version TEXT NOT NULL, engine_version TEXT NOT NULL, params_json TEXT NOT NULL,
    result_json TEXT, execution_status TEXT NOT NULL CHECK(execution_status IN
        ('running','success','insufficient_sample','failed')),
    error_code TEXT, run_at TEXT NOT NULL,
    phase TEXT NOT NULL CHECK(phase IN ('primary','correction','diagnostic','supplementary')),
    classification TEXT NOT NULL CHECK(classification IN ('registered','exploratory')),
    reason TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id,spec_version) REFERENCES factor_hypotheses(hypothesis_id,spec_version)
);
CREATE UNIQUE INDEX IF NOT EXISTS experiment_success ON factor_experiments(run_key)
    WHERE execution_status IN ('success','insufficient_sample');
CREATE UNIQUE INDEX IF NOT EXISTS experiment_running ON factor_experiments(run_key)
    WHERE execution_status='running';
CREATE INDEX IF NOT EXISTS experiment_hypothesis ON factor_experiments(hypothesis_id);
CREATE TABLE IF NOT EXISTS research_results (
    result_id TEXT PRIMARY KEY, supersedes_result_id TEXT UNIQUE REFERENCES research_results(result_id),
    hypothesis_id TEXT NOT NULL, spec_version INTEGER NOT NULL,
    evidence_experiment_ids TEXT NOT NULL, claims_json TEXT NOT NULL,
    exploration_path TEXT NOT NULL, proposed_verdict TEXT NOT NULL,
    attribution_status TEXT NOT NULL, attribution_detail TEXT NOT NULL, caveats TEXT NOT NULL,
    FOREIGN KEY(hypothesis_id,spec_version) REFERENCES factor_hypotheses(hypothesis_id,spec_version)
);
CREATE UNIQUE INDEX IF NOT EXISTS initial_result ON research_results(hypothesis_id)
    WHERE supersedes_result_id IS NULL;
CREATE TABLE IF NOT EXISTS validation_reviews (
    review_id TEXT PRIMARY KEY, result_id TEXT NOT NULL UNIQUE REFERENCES research_results(result_id),
    provenance_check TEXT NOT NULL, unsupported_claims TEXT NOT NULL,
    strengths TEXT NOT NULL, critiques TEXT NOT NULL, statistical_assessment TEXT NOT NULL,
    attribution_agreement TEXT NOT NULL, suggested_verdict TEXT NOT NULL,
    requested_followups TEXT NOT NULL, provenance_errors TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_memory (
    memory_id TEXT PRIMARY KEY, type TEXT NOT NULL, topic TEXT NOT NULL, lesson TEXT NOT NULL,
    evidence_experiment_ids TEXT NOT NULL, review_id TEXT NOT NULL REFERENCES validation_reviews(review_id),
    confidence TEXT NOT NULL, UNIQUE(review_id,type,topic)
);
CREATE TRIGGER IF NOT EXISTS frozen_spec BEFORE UPDATE OF
    factor_spec_json,spec_version,mechanism,rationale,hypothesis_id,round_id ON factor_hypotheses
BEGIN SELECT RAISE(ABORT,'Frozen specifications are immutable; insert a new version'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_spec BEFORE DELETE ON factor_hypotheses
BEGIN SELECT RAISE(ABORT,'Frozen specifications cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS final_experiment BEFORE UPDATE ON factor_experiments
WHEN OLD.execution_status!='running'
BEGIN SELECT RAISE(ABORT,'Finalized experiments are append-only'); END;
CREATE TRIGGER IF NOT EXISTS registered_experiment BEFORE UPDATE OF
    run_key,hypothesis_id,action,spec_version,dataset_version,engine_version,params_json,phase,classification,reason
    ON factor_experiments
BEGIN SELECT RAISE(ABORT,'Registered experiment parameters are immutable'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_experiment BEFORE DELETE ON factor_experiments
BEGIN SELECT RAISE(ABORT,'Experiments cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS immutable_result BEFORE UPDATE ON research_results
BEGIN SELECT RAISE(ABORT,'Research results are immutable'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_result BEFORE DELETE ON research_results
BEGIN SELECT RAISE(ABORT,'Research results cannot be deleted'); END;
CREATE TRIGGER IF NOT EXISTS immutable_review BEFORE UPDATE ON validation_reviews
BEGIN SELECT RAISE(ABORT,'Validation reviews are immutable'); END;
CREATE TRIGGER IF NOT EXISTS no_delete_review BEFORE DELETE ON validation_reviews
BEGIN SELECT RAISE(ABORT,'Validation reviews cannot be deleted'); END;
