"""Deterministic test doubles; never imported by production code."""
import json

from pydantic import ConfigDict

from backend.config import ResearchSettings
from backend.research_agent.schemas import (DatasetManifest, DiagnosticDecision, ExperimentOutput, Hypotheses,
    HypothesisSpec, MultipleTestingInput, Record, ResearchPlan, ResearchInterpretation)
from backend.storage.research import ReviewRepository
from backend.validation_agent.graph import build_validation_graph
from backend.validation_agent.schemas import Assessment


class NoArguments(Record):
    pass


class LagArguments(Record):
    lag_sessions: int


def research_settings(**changes):
    return ResearchSettings(_env_file=None, dataset_id='test-dataset', diagnostic_budget=2,
                            significance_level=.05, **changes)


def specification(hid, mechanism):
    return HypothesisSpec(hypothesis_id=hid, mechanism=mechanism, rationale='A test mechanism',
        factor='test_factor', factor_parameters={}, signal_direction='positive', holding_period=5,
        execution_timing={'signal_available_at': 'close', 'execution_price': 'next_open', 'delay_sessions': 1,
            'rebalance_sessions': 5, 'tradability_policy': 'skip_untradable', 'missing_data_policy': 'exclude',
            'return_label': 'next_open_to_exit_open'},
        asset_universe='test-universe', transaction_costs={'commission_bps': 1, 'slippage_bps': 2, 'tax_bps': 0},
        benchmark='same_universe', evaluation_window={'train_start': '2020-01-01', 'train_end': '2021-12-31',
            'test_start': '2022-01-01', 'test_end': '2023-12-31'}, primary_metric='/metrics/oos/ic',
        primary_p_value='/metrics/oos/p', required_actions=['evaluate_factor','walk_forward'], relevant_data_fields=['close'])


class TestLLM:
    __test__ = False
    def __init__(self, verdict='accept', diagnostics=0, followup=False):
        self.verdict, self.diagnostics, self.followup = verdict, diagnostics, followup
        self.calls = []

    async def generate(self, schema, instructions, payload):
        self.calls.append((schema, payload))
        if schema is ResearchPlan:
            return ResearchPlan(objective=payload['query'], tasks=['Freeze hypotheses', 'Evaluate evidence'])
        if schema is Hypotheses:
            return Hypotheses(hypotheses=[specification(payload['round_id'] + '-A', 'momentum'),
                                          specification(payload['round_id'] + '-B', 'liquidity')])
        if schema is DiagnosticDecision:
            action = 'lag_decay' if self.diagnostics else 'stop'
            self.diagnostics = max(0, self.diagnostics - 1)
            return DiagnosticDecision(action=action, parameters={'lag_sessions': self.diagnostics + 1}, reason='Check lag sensitivity')
        if schema is ResearchInterpretation:
            return ResearchInterpretation(claims=[], exploration_path=['Retain the registered primary path'],
                proposed_verdict='supported', attribution_status='unresolved',
                attribution_detail='Causal interpretation remains unresolved', caveats=['Limited test coverage'])
        if schema is Assessment:
            return Assessment(unsupported_claims=[], strengths=['Archived evidence'], critiques=['Limited scope'],
                statistical_assessment='Assessment based on archived primary and corrected evidence.', attribution_agreement='agree',
                suggested_verdict=self.verdict, requested_followups=[{'action': 'lag_decay', 'parameters': {'lag_sessions': 10},
                    'reason': 'Check execution sensitivity', 'conclusion_impact': 3}] if self.followup else [])
        raise AssertionError(schema)


class TestEngine:
    __test__ = False
    engine_version = 'test-engine-v1'
    actions = {'evaluate_factor': NoArguments, 'walk_forward': NoArguments,
               'multiple_testing': MultipleTestingInput, 'lag_decay': LagArguments}

    def __init__(self, repository=None):
        self.repository = repository
        self.calls = []
        self.fail_action = None
        self.insufficient = False

    def list_datasets(self):
        return [DatasetManifest(dataset_id='test-dataset', dataset_version='test-v1', source='TEST ONLY',
            file_checksums={'test-only': 'fixture-sha'}, field_units={'close':'USD'}, trading_calendar='test-calendar',
            coverage_start='2020-01-01', coverage_end='2023-12-31', universe_version='test-universe-v1',
            previously_observed=False, evidence_kind='empirical')]

    def validate_spec(self, spec, dataset):
        assert spec.factor == 'test_factor'
        assert spec.relevant_data_fields == ['close']

    def run_experiment(self, action, spec, dataset_version, overrides):
        self.calls.append((action, spec.hypothesis_id, overrides))
        if self.repository is not None:
            h = self.repository.hypothesis(spec.hypothesis_id)
            assert len(self.repository.hypotheses(h['round_id'])) == 2
        if action == self.fail_action:
            raise RuntimeError('quantitative execution failed')
        if action == 'multiple_testing':
            ids = [member['hypothesis_id'] for member in overrides['members']]
            assert len({(call[0], call[1]) for call in self.calls
                        if call[0] in ('evaluate_factor','walk_forward') and call[1] in ids}) == 4
            metrics = {'hypothesis_ids': ids, 'adjusted_p_values': {hid: .04 for hid in ids}, 'omissions': {}}
        else:
            metrics = {'oos': {'ic': .1, 'p': .02}, 'benchmark': {'ic': .01}}
        return ExperimentOutput(execution_status='insufficient_sample' if self.insufficient else 'success',
            dataset_version=dataset_version, engine_version=self.engine_version, spec_version=1,
            evidence_kind='empirical', metrics=metrics, limitations=['Test fixture only'])


class TestValidator:
    __test__ = False
    def __init__(self, db, llm=None):
        self.repository = ReviewRepository(db)
        self.llm = llm if llm is not None else TestLLM()
        self.calls = []

    async def validate(self, request, report):
        self.calls.append(request)
        result = await build_validation_graph(self.llm, self.repository).ainvoke({'request': request})
        return result['validation']
