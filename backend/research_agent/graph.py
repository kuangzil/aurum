import asyncio
import json
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.a2a_transport.client import ValidationUnavailable
from backend.llm import StructuredLLM
from backend.market_data.repository import GoldRepository, describe_observation
from backend.research_agent.evidence import metric_value, numerical_paths, verify_evidence
from backend.research_agent.schemas import (Claim, CorrectionMetrics, DatasetManifest, DiagnosticDecision,
    ExperimentOutput, Hypotheses, HypothesisSpec, MetricReference, MultipleTestingInput,
    PrimaryFamilyMember, ResearchPlan, ResearchResult, ResearchInterpretation, DIAGNOSTICS)
from backend.research_agent.tools import QuantEngine
from backend.research_agent.report import research_report
from backend.storage.memory import MemoryService, time_sensitive
from backend.storage.research import ResearchRepository, encode
from backend.trace import Reporter, TraceEvent, no_report
from backend.validation_agent.schemas import Followup, ValidationRequest, ValidationResult


class Validator(Protocol):
    async def validate(self, request: ValidationRequest, report: Reporter) -> ValidationResult: ...


class ResearchState(TypedDict):
    round_id: str


def review_router(review: ValidationResult, supplementary_used: bool, actions: set[str]) -> str:
    if review.suggested_verdict == 'needs_more_evidence' and not supplementary_used:
        if any(item.action in actions for item in review.requested_followups):
            return 'supplementary_test'
    return 'finalize_hypothesis'


def hypothesis_router(hypotheses: list[dict]) -> str:
    return 'select_current_hypothesis' if any(h['status'] in ('proposed', 'testing') for h in hypotheses) else 'summarize'


def build_research_graph(llm: StructuredLLM | None, validator: Validator, repository: ResearchRepository,
                         engine: QuantEngine | None, report: Reporter = no_report,
                         *, memory: MemoryService, market: GoldRepository | None = None):
    async def event(stage, detail):
        await report(TraceEvent(agent='research', stage=stage, detail=detail))

    def advance(round_id, next_node, **changes):
        with repository.step(round_id, next_node, **changes):
            pass

    def spec_for(hypothesis_id):
        return HypothesisSpec.model_validate_json(repository.hypothesis(hypothesis_id)['factor_spec_json'])

    async def execute(round_id, hypothesis_id, action, parameters, phase, reason):
        if action not in engine.actions:
            raise ValueError(f'Unimplemented research action: {action}')
        if phase in ('diagnostic', 'supplementary'):
            if action not in DIAGNOSTICS:
                raise ValueError('Only registered diagnostic actions are allowed')
            if set(parameters) & (set(HypothesisSpec.model_fields) | {'spec', 'dataset_version', 'spec_version'}):
                raise ValueError('Diagnostics cannot redefine a frozen specification')
        parameters = engine.actions[action].model_validate(parameters).model_dump(mode='json')
        experiment, should_run = repository.register_experiment(
            round_id, hypothesis_id, action, parameters, phase, engine.engine_version, reason)
        if not should_run:
            return experiment
        await event(action, f"Executing registered experiment {experiment['experiment_id']}")
        try:
            spec = spec_for(hypothesis_id)
            original = spec.model_dump_json()
            output = await asyncio.to_thread(engine.run_experiment, action, spec,
                                             experiment['dataset_version'], parameters)
            output = ExperimentOutput.model_validate(output)
            if spec.model_dump_json() != original:
                raise ValueError('Quantitative tool mutated its frozen specification')
            if (output.dataset_version != experiment['dataset_version'] or
                    output.engine_version != engine.engine_version or output.spec_version != experiment['spec_version']):
                raise ValueError('Quantitative output version mismatch')
            if action == 'multiple_testing':
                corrected = CorrectionMetrics.model_validate(output.metrics)
                expected = {member['hypothesis_id'] for member in parameters['members']}
                if set(corrected.hypothesis_ids) != expected:
                    raise ValueError('Correction must retain the complete primary family')
            repository.finish_experiment(round_id, experiment['experiment_id'], output)
        except BaseException as exc:
            repository.finish_experiment(round_id, experiment['experiment_id'], None, f'{type(exc).__name__}: {exc}')
            raise
        return repository.experiment(experiment['experiment_id'])

    async def context_build_up(state):
        run = repository.run(state['round_id'])
        context = await memory.build_context(run['session_id'], run['question'], run['user_message_id'], report)
        snapshot = await asyncio.to_thread(market.latest) if market is not None else None
        context['market_context'] = describe_observation(snapshot) if (
            time_sensitive(run['question']) or any(word in run['question'].lower() for word in ('gold','xau'))) else ''
        with repository.step(run['round_id'], 'intent', state='running') as conn:
            conn.execute('UPDATE research_runs SET context_json=? WHERE round_id=?', (encode(context), run['round_id']))
        return state

    async def intent(state):
        run = repository.run(state['round_id'])
        if engine is None:
            advance(run['round_id'], 'intent', state='blocked', error_code='quantitative_engine_not_registered')
            await event('blocked', 'No quantitative engine is registered; no experiments were performed')
            return state
        await event('planning', 'Defining the research objective without observing experimental results')
        context = json.loads(run['context_json'])
        plan = await llm.generate(ResearchPlan,
            'Interpret the research request into an objective and tasks. Prior conversation is unverified context '
            'for intent only, never experimental evidence. Do not invent numerical results.',
            {'query': run['question'], 'prior_conversation_unverified': context['retrieved_context'],
             'recent_conversation_unverified': context['recent_history'], 'external_spot_observation': context['market_context']})
        with repository.step(run['round_id'], 'load_research_context') as conn:
            conn.execute('UPDATE research_runs SET plan_json=? WHERE round_id=?', (plan.model_dump_json(), run['round_id']))
        return state

    async def load_research_context(state):
        run = repository.run(state['round_id'])
        missing = {'evaluate_factor', 'walk_forward', 'multiple_testing'} - engine.actions.keys()
        if missing:
            advance(run['round_id'], 'load_research_context', state='blocked', error_code='missing_actions: ' + ', '.join(sorted(missing)))
            return state
        for schema in engine.actions.values():
            if schema.model_config.get('extra') != 'forbid':
                raise ValueError('Quantitative argument schemas must reject unknown fields')
        datasets = await asyncio.to_thread(engine.list_datasets)
        matches = [DatasetManifest.model_validate(d) for d in datasets if d.dataset_id == run['dataset_id']]
        if len(matches) != 1:
            advance(run['round_id'], 'load_research_context', state='blocked', error_code='dataset_unavailable_or_ambiguous')
            return state
        dataset = matches[0]
        if dataset.evidence_kind != 'empirical':
            advance(run['round_id'], 'load_research_context', state='blocked', error_code='synthetic_dataset_not_permitted')
            return state
        with repository.step(run['round_id'], 'generate_hypotheses') as conn:
            conn.execute('UPDATE research_runs SET dataset_version=?,manifest_json=? WHERE round_id=?',
                         (dataset.dataset_version, dataset.model_dump_json(), run['round_id']))
        await event('load_research_context', f'Frozen dataset manifest: {dataset.dataset_version}')
        return state

    async def generate_hypotheses(state):
        run = repository.run(state['round_id'])
        proposals = await llm.generate(Hypotheses,
            'Pre-register exactly two hypotheses with different quantitative mechanisms. Use distinct IDs prefixed '
            'by round_id. Define all factor, timing, cost, universe, benchmark, train/test and metric fields before '
            'experimentation. Both hypotheses must use the same evaluation window and primary metric family. '
            'required_actions must be evaluate_factor then walk_forward. Metric paths begin /metrics/. '
            'Use only fields and operations accepted by the quantitative engine. No experimental results are available.',
            {'round_id': run['round_id'], 'plan': json.loads(run['plan_json']),
             'dataset': json.loads(run['manifest_json']), 'lessons': repository.lessons(run['dataset_version']),
             'prior_research': repository.prior_research(run['dataset_version'], run['round_id'])})
        with repository.step(run['round_id'], 'freeze_hypotheses') as conn:
            conn.execute('UPDATE research_runs SET proposal_json=? WHERE round_id=?', (proposals.model_dump_json(), run['round_id']))
        return state

    async def freeze_hypotheses(state):
        run = repository.run(state['round_id'])
        proposals = Hypotheses.model_validate_json(run['proposal_json'])
        dataset = DatasetManifest.model_validate_json(run['manifest_json'])
        left, right = proposals.hypotheses
        if left.evaluation_window != right.evaluation_window or left.primary_metric != right.primary_metric:
            raise ValueError('Primary hypotheses must share an evaluation window and metric family')
        for spec in proposals.hypotheses:
            if not set(spec.relevant_data_fields).issubset(dataset.field_units):
                raise ValueError('Hypothesis references unavailable data fields')
            await asyncio.to_thread(engine.validate_spec, spec, dataset)
        repository.freeze(run['round_id'], proposals)
        await event('freeze_hypotheses', 'Both specifications committed before either primary experiment')
        return state

    async def execute_main_experiments(state):
        run = repository.run(state['round_id'])
        for hypothesis in repository.hypotheses(run['round_id']):
            for action in spec_for(hypothesis['hypothesis_id']).required_actions:
                await execute(run['round_id'], hypothesis['hypothesis_id'], action, {}, 'primary', 'Pre-registered primary experiment')
        advance(run['round_id'], 'multiple_testing_correction')
        return state

    async def multiple_testing_correction(state):
        run = repository.run(state['round_id'])
        hypotheses = repository.hypotheses(run['round_id'])
        members = []
        for hypothesis in hypotheses:
            primary = [e for e in repository.experiments(hypothesis['hypothesis_id'])
                       if e['action'] == 'evaluate_factor' and e['phase'] == 'primary'
                       and e['execution_status'] in ('success', 'insufficient_sample')][0]
            spec = spec_for(hypothesis['hypothesis_id'])
            p_value = metric_value(json.loads(primary['result_json']), spec.primary_p_value) if primary['execution_status'] == 'success' else None
            members.append(PrimaryFamilyMember(hypothesis_id=hypothesis['hypothesis_id'],
                experiment_id=primary['experiment_id'], metric_path=spec.primary_p_value,
                execution_status=primary['execution_status'], p_value=p_value))
        parameters = MultipleTestingInput(members=members, method='bonferroni', alpha=run['significance_level'])
        await execute(run['round_id'], hypotheses[0]['hypothesis_id'], 'multiple_testing', parameters.model_dump(),
                      'correction', 'Correction across both registered primary hypotheses, retaining missing members')
        advance(run['round_id'], 'select_current_hypothesis')
        return state

    def select_current_hypothesis(state):
        run = repository.run(state['round_id'])
        current = next(h for h in repository.hypotheses(run['round_id']) if h['status'] in ('proposed','testing'))
        advance(run['round_id'], 'research_diagnostics', current_hypothesis_id=current['hypothesis_id'], result_id=None, review_id=None)
        return state

    async def research_diagnostics(state):
        run = repository.run(state['round_id'])
        hid = run['current_hypothesis_id']
        actions = {key: schema.model_json_schema() for key, schema in engine.actions.items() if key in DIAGNOSTICS}
        used = len({e['run_key'] for e in repository.experiments(hid) if e['phase'] == 'diagnostic'})
        for _ in range(used, run['diagnostic_budget']):
            if not actions:
                break
            decision = await llm.generate(DiagnosticDecision,
                'Choose one registered diagnostic action or stop. Inherit the frozen specification; never redefine '
                'primary settings. Arguments must match the supplied action schema. Every new diagnostic is exploratory. '
                'Use observed tool results to decide whether another diagnostic can address an unresolved limitation.',
                {'spec': spec_for(hid).model_dump(mode='json'), 'actions': actions,
                 'observations': repository.experiments(hid), 'remaining_calls': run['diagnostic_budget'] - used})
            if decision.action == 'stop':
                break
            await execute(run['round_id'], hid, decision.action, decision.parameters, 'diagnostic', decision.reason)
            used += 1
        advance(run['round_id'], 'submit_result')
        return state

    async def submit_result(state):
        run = repository.run(state['round_id'])
        hid = run['current_hypothesis_id']
        experiments = repository.experiments(hid)
        for hypothesis in repository.hypotheses(run['round_id']):
            if hypothesis['hypothesis_id'] != hid:
                experiments.extend(e for e in repository.experiments(hypothesis['hypothesis_id']) if e['phase'] == 'correction')
        claims = [Claim(label=e['action'] + ': ' + path, kind='observation',
                        references=[MetricReference(experiment_id=e['experiment_id'], metric_path=path)])
                  for e in experiments if e['execution_status'] == 'success'
                  for path in numerical_paths(json.loads(e['result_json'])['metrics'])]
        interpretation = await llm.generate(ResearchInterpretation,
            'Assess the frozen hypothesis using only these persisted experiments. Describe retained and abandoned '
            'paths, alternative explanations, limitations and a provisional verdict. Quantitative claims must use '
            'experiment_id and metric_path references; comparisons require both sides. Never supply numbers or '
            'identifiers in prose: Python renders them from structured references. Do not claim confirmation from '
            'exploratory diagnostics. Leave attribution unresolved when the evidence cannot distinguish explanations.',
            {'spec': spec_for(hid).model_dump(mode='json'), 'experiments': experiments,
             'available_claims': [claim.model_dump() for claim in claims]})
        evidence = {e['experiment_id']: e for e in experiments}
        for claim in interpretation.claims:
            for ref in claim.references:
                experiment = evidence[ref.experiment_id]
                if experiment['execution_status'] != 'success':
                    raise ValueError('Research interpretation references an unsuccessful experiment')
                metric_value(json.loads(experiment['result_json']), ref.metric_path)
        result = ResearchResult(evidence_experiment_ids=list(evidence),
            **interpretation.model_dump(exclude={'claims', 'exploration_path', 'caveats'}),
            claims=claims + interpretation.claims,
            exploration_path=[f"{e['experiment_id']}: {e['phase']}; {e['reason']}" for e in experiments]
                             + interpretation.exploration_path,
            caveats=interpretation.caveats + [limitation for e in experiments if e['result_json'] is not None
                     for limitation in json.loads(e['result_json'])['limitations']] +
                    ['Diagnostics and supplementary tests on observed data are exploratory.'])
        repository.submit(run['round_id'], hid, result, run['result_id'])
        return state

    async def validate(state):
        run = repository.run(state['round_id'])
        await event('validate', f"Submitting persisted result {run['result_id']} for independent A2A review")
        try:
            review = await validator.validate(ValidationRequest(result_id=run['result_id'],
                hypothesis_id=run['current_hypothesis_id'], focus='Timing, provenance, primary family correction and methodology'), report)
            saved = repository.review(run['result_id'])
            if saved is None or saved != review or review.result_id != run['result_id']:
                raise ValidationUnavailable('A2A review does not match an independently persisted review')
        except ValidationUnavailable as exc:
            advance(run['round_id'], 'validate', state='waiting_review', error_code=str(exc))
            return state
        advance(run['round_id'], 'review_router', review_id=review.review_id)
        return state

    def route_review(state):
        run = repository.run(state['round_id'])
        used = repository.hypothesis(run['current_hypothesis_id'])['supplementary_json'] is not None
        destination = review_router(repository.review(run['result_id']), used, set(engine.actions))
        advance(run['round_id'], destination)
        return state

    async def supplementary_test(state):
        run = repository.run(state['round_id'])
        review = repository.review(run['result_id'])
        hypothesis = repository.hypothesis(run['current_hypothesis_id'])
        if hypothesis['supplementary_json'] is None:
            recommendation = max((item for item in review.requested_followups if item.action in engine.actions),
                                 key=lambda item: item.conclusion_impact)
            with repository.step(run['round_id'], 'supplementary_test') as conn:
                conn.execute('UPDATE factor_hypotheses SET supplementary_json=? WHERE hypothesis_id=?',
                             (recommendation.model_dump_json(), run['current_hypothesis_id']))
        else:
            recommendation = Followup.model_validate_json(hypothesis['supplementary_json'])
        await execute(run['round_id'], run['current_hypothesis_id'], recommendation.action,
                      recommendation.parameters, 'supplementary', recommendation.reason)
        advance(run['round_id'], 'submit_result')
        return state

    def finalize_hypothesis(state):
        run = repository.run(state['round_id'])
        hid = run['current_hypothesis_id']
        review = repository.review(run['result_id'])
        errors = verify_evidence(repository, run['result_id'], hid)
        if errors or review.provenance_check != 'passed':
            status = 'needs_more_data'
        elif review.suggested_verdict in ('accept','accept_with_caveats'):
            status = 'validated'
        elif review.suggested_verdict == 'reject':
            status = 'rejected'
        else:
            status = 'needs_more_data'
        response = {'result_id': run['result_id'], 'review_id': review.review_id,
                    'review_outcome': review.suggested_verdict, 'provenance_errors': errors,
                    'critiques': review.critiques, 'attribution_agreement': review.attribution_agreement,
                    'supplementary_registration': repository.hypothesis(hid)['supplementary_json'],
                    'followups': [{'recommendation': item.model_dump(),
                        'experiments': [e['experiment_id'] for e in repository.experiments(hid)
                            if e['action'] == item.action
                            and json.loads(e['params_json']) == item.parameters]} for item in review.requested_followups]}
        with repository.step(run['round_id'], 'hypothesis_router') as conn:
            conn.execute('UPDATE factor_hypotheses SET status=?,evidence_summary=? WHERE hypothesis_id=?',
                         (status, encode(response), hid))
        return state

    def route_hypothesis(state):
        rid = state['round_id']
        advance(rid, hypothesis_router(repository.hypotheses(rid)))
        return state

    def summarize(state):
        reply = research_report(repository, state['round_id'], status='completed')
        advance(state['round_id'], 'update_memory', report_text=reply)
        return state

    def update_memory(state):
        rid = state['round_id']
        with repository.step(rid, 'END', state='completed') as conn:
            for hypothesis in repository.hypotheses(rid):
                summary = json.loads(hypothesis['evidence_summary'])
                review = repository.review(summary['result_id'])
                if review.provenance_check != 'passed':
                    continue
                result = repository.result(review.result_id)
                # Store traceable observations, never LLM explanations as established knowledge.
                lesson = encode({'status': hypothesis['status'], 'claims': json.loads(result['claims_json'])})
                conn.execute('''INSERT INTO research_memory VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(review_id,type,topic) DO NOTHING''',
                    ('MEM-' + review.review_id, 'observation', hypothesis['mechanism'], lesson,
                     result['evidence_experiment_ids'], review.review_id, 'independently_reviewed'))
        return state

    nodes = {'context_build_up': context_build_up, 'intent': intent, 'load_research_context': load_research_context,
        'generate_hypotheses': generate_hypotheses, 'freeze_hypotheses': freeze_hypotheses,
        'execute_main_experiments': execute_main_experiments, 'multiple_testing_correction': multiple_testing_correction,
        'select_current_hypothesis': select_current_hypothesis, 'research_diagnostics': research_diagnostics,
        'submit_result': submit_result, 'validate': validate, 'review_router': route_review,
        'supplementary_test': supplementary_test, 'finalize_hypothesis': finalize_hypothesis,
        'hypothesis_router': route_hypothesis, 'summarize': summarize, 'update_memory': update_memory}

    def next_node(state):
        run = repository.run(state['round_id'])
        if run['state'] in ('waiting_review','blocked','completed'):
            return END
        return run['next_node']

    graph = StateGraph(ResearchState)
    for name, node in nodes.items():
        graph.add_node(name, node)
        graph.add_conditional_edges(name, next_node, [*nodes, END])
    graph.add_conditional_edges(START, next_node, [*nodes, END])
    return graph.compile()
