import pytest
from pydantic import ValidationError

from backend.config import Settings
from backend.llm import LLMError, make_llm
from backend.research_agent.schemas import Claim, HypothesisSpec
from backend.tests.research_fixtures import specification
from backend.validation_agent.schemas import Assessment


def test_production_requires_real_llm_configuration():
    with pytest.raises(LLMError, match='mock execution is disabled'):
        make_llm(Settings(_env_file=None, llm_mode='mock'))
    with pytest.raises(LLMError, match='required'):
        make_llm(Settings(_env_file=None, openai_api_key='', openai_model=''))


def test_comparative_claim_requires_both_sides():
    with pytest.raises(ValidationError):
        Claim(label='Comparison', kind='comparison', references=[{'experiment_id':'e', 'metric_path':'/metrics/a'}])


def test_temporal_specification_rejects_overlapping_windows():
    spec = specification('h','momentum').model_dump(mode='json')
    spec['evaluation_window']['test_start'] = '2020-01-01'
    with pytest.raises(ValidationError, match='non-overlapping'):
        HypothesisSpec.model_validate(spec)


def test_arbitrary_actions_are_not_research_tools():
    spec = specification('h','momentum').model_dump(mode='json')
    spec['required_actions'] = ['execute_python']
    with pytest.raises(ValidationError):
        HypothesisSpec.model_validate(spec)
