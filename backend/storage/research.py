import hashlib
import json
from contextlib import contextmanager
from uuid import uuid4

from backend.research_agent.schemas import Hypotheses, HypothesisSpec, ResearchResult
from backend.storage.sqlite import Database, utc_iso, utc_now
from backend.validation_agent.schemas import ValidationResult


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


class EvidenceReader:
    """Read interface, not database-level access control."""

    def __init__(self, db: Database):
        self.db = db

    def run(self, round_id: str) -> dict:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM research_runs WHERE round_id=?', (round_id,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown research run: {round_id}')
        return dict(row)

    def hypotheses(self, round_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM factor_hypotheses WHERE round_id=? ORDER BY rowid', (round_id,)).fetchall()
        return [dict(row) for row in rows]

    def hypothesis(self, hypothesis_id: str, version: int = 1) -> dict:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM factor_hypotheses WHERE hypothesis_id=? AND spec_version=?',
                               (hypothesis_id, version)).fetchone()
        if row is None:
            raise KeyError(f'Unknown hypothesis version: {hypothesis_id}/{version}')
        return dict(row)

    def experiments(self, hypothesis_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM factor_experiments WHERE hypothesis_id=? ORDER BY rowid',
                                (hypothesis_id,)).fetchall()
        return [dict(row) for row in rows]

    def experiment(self, experiment_id: str) -> dict:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM factor_experiments WHERE experiment_id=?', (experiment_id,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown experiment: {experiment_id}')
        return dict(row)

    def result(self, result_id: str) -> dict:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM research_results WHERE result_id=?', (result_id,)).fetchone()
        if row is None:
            raise KeyError(f'Unknown research result: {result_id}')
        return dict(row)

    def results(self, hypothesis_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM research_results WHERE hypothesis_id=? ORDER BY rowid', (hypothesis_id,)).fetchall()
        return [dict(row) for row in rows]

    def review(self, result_id: str) -> ValidationResult | None:
        with self.db.connect() as conn:
            row = conn.execute('SELECT * FROM validation_reviews WHERE result_id=?', (result_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        for key in ('unsupported_claims', 'strengths', 'critiques', 'requested_followups', 'provenance_errors'):
            data[key] = json.loads(data[key])
        return ValidationResult.model_validate(data)

    def lessons(self, dataset_version: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute('''SELECT m.* FROM research_memory m
                JOIN validation_reviews v ON v.review_id=m.review_id
                JOIN research_results r ON r.result_id=v.result_id
                JOIN factor_hypotheses h ON h.hypothesis_id=r.hypothesis_id AND h.spec_version=r.spec_version
                JOIN research_runs run ON run.round_id=h.round_id WHERE run.dataset_version=?''',
                (dataset_version,)).fetchall()
        return [dict(row) for row in rows]

    def prior_research(self, dataset_version: str, exclude_round_id: str) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("""SELECT h.* FROM factor_hypotheses h
                JOIN research_runs r ON r.round_id=h.round_id
                WHERE r.dataset_version=? AND r.round_id!=? ORDER BY h.rowid""",
                (dataset_version, exclude_round_id)).fetchall()
        return [dict(row) for row in rows]


class ResearchRepository(EvidenceReader):
    def create_run(self, session_id, question, request_id, dataset_id, budget, alpha, user_message_id) -> str:
        with self.db.connect() as conn:
            if request_id is not None:
                row = conn.execute('SELECT * FROM research_runs WHERE request_id=?', (request_id,)).fetchone()
                if row is not None:
                    if (row['session_id'], row['question']) != (session_id, question):
                        raise ValueError('request_id belongs to a different request')
                    return row['round_id']
            round_id = 'ROUND-' + uuid4().hex
            conn.execute('''INSERT INTO research_runs
                (round_id,session_id,question,request_id,dataset_id,diagnostic_budget,significance_level,user_message_id,state,next_node,created_at)
                VALUES (?,?,?,?,?,?,?,?,'queued','context_build_up',?)''',
                (round_id, session_id, question, request_id, dataset_id, budget, alpha, user_message_id, utc_iso(utc_now())))
        return round_id

    @contextmanager
    def step(self, round_id, next_node, **changes):
        # Evidence and its continuation point commit in the same transaction.
        with self.db.connect() as conn:
            yield conn
            values = {'next_node': next_node, **changes}
            conn.execute('UPDATE research_runs SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE round_id=?',
                         (*values.values(), round_id))

    def freeze(self, round_id: str, hypotheses: Hypotheses):
        with self.step(round_id, 'execute_main_experiments') as conn:
            for spec in hypotheses.hypotheses:
                conn.execute('''INSERT INTO factor_hypotheses
                    (hypothesis_id,round_id,mechanism,rationale,factor_spec_json,spec_version,status)
                    VALUES (?,?,?,?,?,1,'proposed')''',
                    (spec.hypothesis_id, round_id, spec.mechanism, spec.rationale, spec.model_dump_json()))

    def register_experiment(self, round_id, hypothesis_id, action, parameters, phase, engine_version, reason):
        hypothesis = self.hypothesis(hypothesis_id)
        run = self.run(round_id)
        spec = HypothesisSpec.model_validate_json(hypothesis['factor_spec_json'])
        key = hashlib.sha256(encode([round_id, hypothesis_id, hypothesis['spec_version'],
                                    action, run['dataset_version'], parameters]).encode()).hexdigest()
        with self.db.connect() as conn:
            rows = conn.execute('SELECT * FROM factor_experiments WHERE run_key=? ORDER BY rowid DESC', (key,)).fetchall()
            for row in rows:
                if row['execution_status'] in ('success', 'insufficient_sample'):
                    return dict(row), False
            if rows and rows[0]['execution_status'] == 'running':
                raise RuntimeError('An experiment is already running or was interrupted; explicit recovery is required')
            if phase in ('diagnostic', 'supplementary'):
                used = conn.execute('''SELECT COUNT(DISTINCT run_key) FROM factor_experiments
                    WHERE hypothesis_id=? AND phase=?''', (hypothesis_id, phase)).fetchone()[0]
                limit = run['diagnostic_budget'] if phase == 'diagnostic' else 1
                if not rows and used >= limit:
                    raise ValueError(f'{phase} budget exhausted')
            experiment_id = 'EXP-' + uuid4().hex
            conn.execute('''INSERT INTO factor_experiments
                (experiment_id,run_key,hypothesis_id,action,spec_version,dataset_version,engine_version,params_json,
                 execution_status,run_at,phase,classification,reason) VALUES (?,?,?,?,?,?,?,?,'running',?,?,?,?)''',
                (experiment_id,key,hypothesis_id,action,hypothesis['spec_version'],run['dataset_version'],engine_version,
                 encode(parameters),utc_iso(utc_now()),phase,
                 'exploratory' if phase in ('diagnostic','supplementary') or json.loads(run['manifest_json'])['previously_observed'] else 'registered',reason))
            conn.execute("UPDATE factor_hypotheses SET status='testing' WHERE hypothesis_id=?", (spec.hypothesis_id,))
        return self.experiment(experiment_id), True

    def finish_experiment(self, round_id, experiment_id, output, error=None):
        with self.db.connect() as conn:
            conn.execute('''UPDATE factor_experiments SET result_json=?,execution_status=?,error_code=?
                WHERE experiment_id=?''',
                (output.model_dump_json() if output is not None else None,
                 output.execution_status if output is not None else 'failed', error, experiment_id))
            if error is not None:
                conn.execute("UPDATE research_runs SET state='blocked',error_code=? WHERE round_id=?", (error, round_id))

    def submit(self, round_id, hypothesis_id, result: ResearchResult, previous_id):
        result_id = 'RESULT-' + uuid4().hex
        with self.step(round_id, 'validate', result_id=result_id, review_id=None) as conn:
            conn.execute('INSERT INTO research_results VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (result_id, previous_id, hypothesis_id, 1, encode(result.evidence_experiment_ids),
                 encode([claim.model_dump() for claim in result.claims]), encode(result.exploration_path),
                 result.proposed_verdict,result.attribution_status,result.attribution_detail,encode(result.caveats)))
        return result_id

    def resume(self, round_id, session_id, retry_failed: bool):
        run = self.run(round_id)
        if run['session_id'] != session_id:
            raise ValueError('Research run belongs to another session')
        if run['state'] not in ('blocked', 'waiting_review'):
            raise ValueError('Only blocked or waiting_review runs can be explicitly resumed')
        if run['state'] == 'blocked' and not retry_failed:
            raise ValueError('Resuming a blocked run requires retry_failed=true')
        with self.step(round_id, run['next_node'], state='running', error_code=None) as conn:
            # Only an explicit resume marks interrupted attempts failed; finalized records stay immutable.
            conn.execute('''UPDATE factor_experiments SET execution_status='failed',error_code='interrupted'
                WHERE execution_status='running' AND hypothesis_id IN
                (SELECT hypothesis_id FROM factor_hypotheses WHERE round_id=?)''', (round_id,))


class ReviewRepository(EvidenceReader):
    def save(self, review: ValidationResult) -> ValidationResult:
        data = review.model_dump()
        for key in ('unsupported_claims','strengths','critiques','requested_followups','provenance_errors'):
            data[key] = encode(data[key])
        with self.db.connect() as conn:
            conn.execute('INSERT INTO validation_reviews (' + ','.join(data) + ') VALUES (' +
                         ','.join('?' for _ in data) + ') ON CONFLICT(result_id) DO NOTHING', tuple(data.values()))
        return self.review(review.result_id)
