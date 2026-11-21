from backend.api.main import create_app
from backend.config import Settings
from backend.tests.research_fixtures import TestEngine, TestLLM, research_settings
from backend.validation_agent.service import create_app as create_validation


def research_app():
    return create_app(Settings(), engine=TestEngine(), llm=TestLLM(), research_settings=research_settings())


def validation_app():
    return create_validation(Settings(), llm=TestLLM())
