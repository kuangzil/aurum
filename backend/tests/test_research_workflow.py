import json
import sqlite3

import pytest
from pydantic import ValidationError

from backend.a2a_transport.client import ValidationUnavailable
from backend.config import Settings, ResearchSettings
from backend.research_agent.evidence import metric_value, verify_evidence
from backend.research_agent.graph import build_research_graph
from backend.research_agent.schemas import Hypotheses
from backend.storage.memory import make_memory
from backend.storage.research import ResearchRepository, ReviewRepository
from backend.tests.research_fixtures import TestEngine, TestLLM, TestValidator, specification


@pytest.fixture
def workflow(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path/'db.sqlite', chroma_path=tmp_path/'chroma', memory_embedding_adapter='fake')
    memory = make_memory(settings)
    repo = ResearchRepository(memory.messages.db)
    engine = TestEngine(repo)
    validator = TestValidator(repo.db)
    rid = repo.create_run('session', 'Research gold factors', None, 'test-dataset', 2, .05, '')
    return memory, repo, engine, validator, rid


async def run(workflow, llm=None, validator=None):
    memory, repo, engine, actual, rid = workflow
    graph = build_research_graph(llm if llm is not None else TestLLM(), validator if validator is not None else actual,
                                repo, engine, memory=memory)
    return await graph.ainvoke({'round_id':rid}, {'recursion_limit':100})


async def test_full_registered_family_and_independent_reviews(workflow):
    await run(workflow)
    memory, repo, engine, validator, rid = workflow
    assert repo.run(rid)['state'] == 'completed'
    hypotheses = repo.hypotheses(rid)
    assert len(hypotheses) == 2
    assert {h['status'] for h in hypotheses} == {'validated'}
    assert len(validator.calls) == 2
    assert len(engine.calls) == 5
    for request in validator.calls:
        result = repo.result(request.result_id)
        assert not verify_evidence(repo, request.result_id, request.hypothesis_id)
        for claim in json.loads(result['claims_json']):
            for ref in claim['references']:
                metric_value(json.loads(repo.experiment(ref['experiment_id'])['result_json']), ref['metric_path'])
    assert len(repo.lessons('test-v1')) == 2


def test_exactly_two_distinct_hypotheses():
    a, b = specification('a','momentum'), specification('b','liquidity')
    for items in ([a], [a,b,a], [a,a], [a,b.model_copy(update={'mechanism':'MOMENTUM'})]):
        with pytest.raises(ValidationError):
            Hypotheses(hypotheses=items)


async def test_frozen_records_cannot_be_overwritten_or_deleted(workflow):
    await run(workflow)
    _, repo, _, validator, _ = workflow
    with repo.db.connect() as conn:
        for sql in ["UPDATE factor_hypotheses SET factor_spec_json='{}'", "DELETE FROM factor_hypotheses",
                    "UPDATE factor_experiments SET result_json='{}'", "DELETE FROM factor_experiments",
                    "UPDATE research_results SET claims_json='[]'", "DELETE FROM research_results"]:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(sql)


async def test_diagnostic_budget_enforced_by_python(workflow):
    llm = TestLLM(diagnostics=100)
    await run(workflow, llm)
    _, repo, engine, _, rid = workflow
    for h in repo.hypotheses(rid):
        diagnostics = [e for e in repo.experiments(h['hypothesis_id']) if e['phase']=='diagnostic']
        assert len(diagnostics) == 2
        assert all(e['classification']=='exploratory' for e in diagnostics)
        with pytest.raises(ValueError, match='budget exhausted'):
            repo.register_experiment(rid,h['hypothesis_id'],'lag_decay',{'lag_sessions':999},'diagnostic',engine.engine_version,'extra')


async def test_failure_is_recorded_and_only_explicit_resume_reexecutes(workflow):
    _, repo, engine, _, rid = workflow
    engine.fail_action = 'walk_forward'
    with pytest.raises(RuntimeError, match='execution failed'):
        await run(workflow)
    assert repo.run(rid)['state'] == 'blocked'
    hid = repo.hypotheses(rid)[0]['hypothesis_id']
    assert [e['execution_status'] for e in repo.experiments(hid)] == ['success','failed']
    await run(workflow)
    assert len(engine.calls)==2
    with pytest.raises(ValueError, match='retry_failed'):
        repo.resume(rid,'session',False)
    engine.fail_action = None
    repo.resume(rid,'session',True)
    await run(workflow)
    assert len([e for e in repo.experiments(hid) if e['action']=='evaluate_factor'])==1
    assert [e['execution_status'] for e in repo.experiments(hid) if e['action']=='walk_forward']==['failed','success']


async def test_waiting_review_durable_resume_without_experiment_replay(workflow):
    class Offline:
        async def validate(self,*args):
            raise ValidationUnavailable('Validation timed out')
    await run(workflow, validator=Offline())
    _, repo, engine, _, rid=workflow
    state=repo.run(rid)
    assert state['state']=='waiting_review' and state['next_node']=='validate'
    assert all(h['status']=='testing' for h in repo.hypotheses(rid))
    assert not repo.lessons('test-v1')
    before=list(engine.calls)
    repo.resume(rid,'session',False)
    await run(workflow)
    assert engine.calls==before
    assert repo.run(rid)['state']=='completed'


async def test_one_supplementary_round_and_versioned_results(workflow):
    memory,repo,engine,_,rid=workflow
    validator=TestValidator(repo.db,TestLLM(verdict='needs_more_evidence',followup=True))
    await run(workflow,validator=validator)
    assert len(validator.calls)==4
    for h in repo.hypotheses(rid):
        assert h['status']=='needs_more_data'
        assert len([e for e in repo.experiments(h['hypothesis_id']) if e['phase']=='supplementary'])==1
        results=repo.results(h['hypothesis_id'])
        assert len(results)==2 and results[1]['supersedes_result_id']==results[0]['result_id']


async def test_insufficient_sample_cannot_be_validated(workflow):
    workflow[2].insufficient=True
    await run(workflow)
    repo=workflow[1]
    assert all(h['status']=='needs_more_data' for h in repo.hypotheses(workflow[4]))
    assert not repo.lessons('test-v1')


async def test_repeat_delivery_returns_existing_success_and_review(workflow):
    await run(workflow)
    _,repo,engine,validator,rid=workflow
    request=validator.calls[0]
    review=await validator.validate(request,None)
    assert review==repo.review(request.result_id)
    first=repo.experiments(request.hypothesis_id)[0]
    saved,should_run=repo.register_experiment(rid,request.hypothesis_id,first['action'],{},'primary',engine.engine_version,'duplicate')
    assert not should_run and saved['experiment_id']==first['experiment_id']


async def test_unknown_action_fails_explicitly(workflow):
    from backend.research_agent.schemas import DiagnosticDecision
    class BadLLM(TestLLM):
        async def generate(self,schema,instructions,payload):
            if schema is DiagnosticDecision:
                return DiagnosticDecision(action='correlation',parameters={},reason='not registered')
            return await super().generate(schema,instructions,payload)
    with pytest.raises(ValueError,match='Unimplemented'):
        await run(workflow,BadLLM())


async def test_synthetic_and_missing_metrics_block_provenance(workflow):
    await run(workflow)
    _,repo,_,validator,_=workflow
    request=validator.calls[0]
    # Corrupt the archive deliberately, bypassing its append-only protection in this test only.
    with repo.db.connect() as conn:
        conn.execute('DROP TRIGGER final_experiment')
        experiment=repo.experiments(request.hypothesis_id)[0]
        result=json.loads(experiment['result_json'])
        result['evidence_kind']='synthetic'
        del result['metrics']['oos']['ic']
        conn.execute('UPDATE factor_experiments SET result_json=? WHERE experiment_id=?',(json.dumps(result),experiment['experiment_id']))
    errors=verify_evidence(repo,request.result_id,request.hypothesis_id)
    assert any('Synthetic' in error for error in errors)
    assert any('Unsupported claim' in error for error in errors)


def test_research_configuration_is_explicit():
    with pytest.raises(ValidationError):
        ResearchSettings(_env_file=None)
    for budget in (-1,11):
        with pytest.raises(ValidationError):
            ResearchSettings(_env_file=None,dataset_id='d',diagnostic_budget=budget,significance_level=.05)


async def test_reused_diagnostic_still_consumes_supplementary_allowance(workflow):
    from backend.research_agent.schemas import DiagnosticDecision
    class SameDiagnostic(TestLLM):
        async def generate(self, schema, instructions, payload):
            if schema is DiagnosticDecision:
                return DiagnosticDecision(action='lag_decay', parameters={'lag_sessions':10}, reason='Existing diagnostic')
            return await super().generate(schema,instructions,payload)
    _,repo,engine,_,rid=workflow
    validator=TestValidator(repo.db,TestLLM(verdict='needs_more_evidence',followup=True))
    await run(workflow,SameDiagnostic(),validator)
    assert len(validator.calls)==4
    assert repo.run(rid)['state']=='completed'
    for h in repo.hypotheses(rid):
        assert h['supplementary_json'] is not None
        assert len([e for e in repo.experiments(h['hypothesis_id']) if e['action']=='lag_decay'])==1
        assert len(repo.results(h['hypothesis_id']))==2


async def test_invalid_diagnostic_arguments_do_not_execute(workflow):
    from backend.research_agent.schemas import DiagnosticDecision
    class InvalidArguments(TestLLM):
        async def generate(self,schema,instructions,payload):
            if schema is DiagnosticDecision:
                return DiagnosticDecision(action='lag_decay',parameters={'lag_sessions':'invalid'},reason='Bad arguments')
            return await super().generate(schema,instructions,payload)
    with pytest.raises(ValidationError):
        await run(workflow,InvalidArguments())
    assert len(workflow[2].calls)==5


async def test_new_review_cannot_override_missing_evidence(workflow):
    from backend.validation_agent.schemas import ValidationRequest
    from backend.research_agent.schemas import ResearchResult
    await run(workflow)
    _,repo,_,validator,rid=workflow
    old=validator.calls[0]
    result=ResearchResult(evidence_experiment_ids=['missing-experiment'],claims=[],exploration_path=[],
        proposed_verdict='supported',attribution_status='unresolved',attribution_detail='Unresolved',caveats=[])
    new_id=repo.submit(rid,old.hypothesis_id,result,old.result_id)
    review=await validator.validate(ValidationRequest(result_id=new_id,hypothesis_id=old.hypothesis_id,focus='Provenance'),None)
    assert review.provenance_check=='failed'
    assert review.suggested_verdict=='needs_more_evidence'
    assert repo.review(new_id)==review


async def test_previously_observed_primary_data_remains_exploratory(workflow):
    engine=workflow[2]
    manifest=engine.list_datasets()[0].model_copy(update={'previously_observed':True})
    engine.list_datasets=lambda: [manifest]
    await run(workflow)
    repo=workflow[1]
    assert all(h['status']=='needs_more_data' for h in repo.hypotheses(workflow[4]))


async def test_restarted_repository_resumes_pending_review(workflow):
    from backend.storage.sqlite import Database
    class Offline:
        async def validate(self,*args):
            raise ValidationUnavailable('temporarily offline')
    await run(workflow,validator=Offline())
    memory,old,engine,_,rid=workflow
    repo=ResearchRepository(Database(old.db.path))
    repo.resume(rid,'session',False)
    calls=len(engine.calls)
    restarted=(memory,repo,engine,TestValidator(repo.db),rid)
    await run(restarted)
    assert len(engine.calls)==calls
    assert repo.run(rid)['state']=='completed'


async def test_zero_diagnostic_budget_never_calls_decision_model(workflow):
    from backend.research_agent.schemas import DiagnosticDecision
    _,repo,_,_,rid=workflow
    with repo.step(rid,'context_build_up',diagnostic_budget=0):
        pass
    llm=TestLLM(diagnostics=100)
    await run(workflow,llm)
    assert all(schema is not DiagnosticDecision for schema,_ in llm.calls)


async def test_wrong_dataset_or_output_version_is_recorded_failure(workflow):
    engine=workflow[2]
    original=engine.run_experiment
    def changed(*args):
        return original(*args).model_copy(update={'dataset_version':'wrong-version'})
    engine.run_experiment=changed
    with pytest.raises(ValueError,match='version mismatch'):
        await run(workflow)
    repo=workflow[1]
    hypothesis=repo.hypotheses(workflow[4])[0]
    assert repo.experiments(hypothesis['hypothesis_id'])[0]['execution_status']=='failed'


async def test_request_id_and_experiment_success_are_idempotent(workflow):
    _,repo,_,_,rid=workflow
    first=repo.create_run('session','question','request-id','test-dataset',0,.05,'')
    assert repo.create_run('session','question','request-id','test-dataset',0,.05,'')==first
    with pytest.raises(ValueError,match='different request'):
        repo.create_run('other-session','question','request-id','test-dataset',0,.05,'')


async def test_llm_cannot_insert_unreferenced_numbers_in_result(workflow):
    from backend.research_agent.schemas import ResearchInterpretation
    class InventedReturn(TestLLM):
        async def generate(self,schema,instructions,payload):
            if schema is ResearchInterpretation:
                return ResearchInterpretation(claims=[],exploration_path=[],proposed_verdict='supported',
                    attribution_status='unresolved',attribution_detail='The return is 999 percent',caveats=[])
            return await super().generate(schema,instructions,payload)
    with pytest.raises(ValidationError,match='structured references'):
        await run(workflow,InventedReturn())
    assert not workflow[3].calls


async def test_unresolvable_llm_claim_cannot_be_submitted(workflow):
    from backend.research_agent.schemas import Claim, ResearchInterpretation
    class InventedMetric(TestLLM):
        async def generate(self,schema,instructions,payload):
            if schema is ResearchInterpretation:
                result=await super().generate(schema,instructions,payload)
                return result.model_copy(update={'claims': [Claim(
                    label='Unsupported metric',kind='observation',references=[{'experiment_id':payload['experiments'][0]['experiment_id'],
                    'metric_path':'/metrics/nonexistent'}])]})
            return await super().generate(schema,instructions,payload)
    with pytest.raises(KeyError,match='nonexistent'):
        await run(workflow,InventedMetric())
    assert not workflow[3].calls


@pytest.mark.parametrize('verdict,status', [('reject','rejected'),('accept_with_caveats','validated'),
                                          ('needs_more_evidence','needs_more_data')])
async def test_review_outcomes_have_distinct_final_states(workflow, verdict, status):
    repo=workflow[1]
    await run(workflow,validator=TestValidator(repo.db,TestLLM(verdict=verdict)))
    assert all(h['status']==status for h in repo.hypotheses(workflow[4]))
    assert repo.run(workflow[4])['state']=='completed'
