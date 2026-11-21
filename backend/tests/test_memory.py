import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from backend.config import Settings
from backend.research_agent.graph import build_research_graph
from backend.storage.cache import SemanticCache
from backend.storage.embeddings import FakeEmbeddings
from backend.storage.memory import MemoryService
from backend.storage.sqlite import Database, MessageRepository


@pytest.fixture
def memory(tmp_path):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / 'memory.sqlite3',
                        chroma_path=tmp_path / 'chroma', memory_embedding_adapter='fake',
                        memory_recent_messages=0, memory_similarity_threshold=0.5)
    return MemoryService(settings, MessageRepository(Database(settings.sqlite_path)), FakeEmbeddings())


def test_message_storage_utc_idempotency_and_restart(memory):
    row = memory.messages.save('s1', 'user', 'gold momentum', 'stable-id')
    assert row['session_id'] == 's1'
    assert datetime.fromisoformat(row['created_at_utc']).utcoffset().total_seconds() == 0
    again = memory.messages.save('s1', 'user', 'gold momentum', 'stable-id')
    assert again == row
    with pytest.raises(ValueError, match='different immutable'):
        memory.messages.save('s2', 'user', 'gold momentum', 'stable-id')
    with pytest.raises(ValueError, match='timezone-aware'):
        memory.messages.save('s1', 'user', 'bad date', created_at=datetime(2026, 1, 1))
    repo = MessageRepository(Database(memory.settings.sqlite_path))
    assert repo.history('s1') == [row]
    assert repo.history('s2') == []
    assert repo.get('s2', 'stable-id') is None
    with repo.db.connect() as conn:
        assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
        assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == 10000


def test_chronological_history_and_parameterized_session(memory):
    session = "x'; DROP TABLE messages; --"
    memory.messages.save(session, 'assistant', 'later', created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    memory.messages.save(session, 'user', 'earlier', created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert [row['content'] for row in memory.messages.history(session)] == ['earlier', 'later']


async def test_chroma_rag_session_isolation_cache_hit_and_miss(memory, monkeypatch):
    memory.messages.save('s1', 'user', 'gold momentum', 'gold-1')
    memory.messages.save('s2', 'user', 'gold momentum private account', 'private-2')
    memory.reconcile()
    calls = []
    search = memory.vectors.search

    def counted(*args):
        calls.append(args)
        return search(*args)

    monkeypatch.setattr(memory.vectors, 'search', counted)
    events = []

    async def report(event):
        events.append(event.stage)

    first = await memory.build_context('s1', 'gold momentum', report=report)
    assert first['context_source'] == 'rag'
    assert first['retrieved_message_ids'] == ['gold-1']
    assert 'private' not in first['retrieved_context']
    assert 'context_cache_miss' in events and 'context_rag_hit' in events
    second = await memory.build_context('s1', 'gold momentum', report=report)
    assert second['context_source'] == 'cache_exact'
    third = await memory.build_context('s1', 'momentum gold', report=report)
    assert third['context_source'] == 'cache_semantic'
    assert len(calls) == 1
    assert 'context_cache_hit' in events and events[-1] == 'context_build_complete'
    miss = await memory.build_context('s1', 'bananas orchard')
    assert miss['retrieved_context'] == '' and miss['context_source'] == 'empty'
    assert len(calls) == 2
    other = await memory.build_context('s2', 'gold momentum')
    assert other['retrieved_message_ids'] == ['private-2']


async def test_original_working_fixtures_have_no_ordinal_risk_evidence(memory):
    for session, text in [('first', 'The five gold strategies are momentum, mean reversion, breakout, carry and volatility.'),
                          ('second', 'gold momentum strategy and risk discussion')]:
        memory.messages.save(session, 'user', text, session + '-source')
        await memory.build_context(session, text)
        memory.messages.save(session, 'user', text, session + '-user')
        memory.messages.save(session, 'assistant', 'Risk differs by strategy.', session + '-answer')
        memory.completed_turn(session, text, session + '-user', session + '-answer')
        result = await memory.build_context(session, 'What risks does the third one have?')
        assert result['memory_route'] == 'chroma'


async def test_cache_invalidates_on_new_message_and_excludes_current_request(memory):
    memory.messages.save('s', 'user', 'gold momentum', 'first')
    assert (await memory.build_context('s', 'gold momentum'))['context_source'] == 'rag'
    memory.messages.save('s', 'user', 'gold momentum second', 'second')
    result = await memory.build_context('s', 'gold momentum')
    assert result['context_source'] == 'rag'
    assert set(result['retrieved_message_ids']) == {'first', 'second'}
    memory.messages.save('new', 'user', 'gold momentum', 'current')
    result = await memory.build_context('new', 'gold momentum', 'current')
    assert result['retrieved_context'] == ''


async def test_sqlite_ownership_rechecked_even_for_bad_vector_results(memory, monkeypatch):
    memory.messages.save('other', 'user', 'secret', 'secret-id')
    monkeypatch.setattr(memory.vectors, 'search', lambda *args: [('secret-id', 1.0)])
    result = await memory.build_context('mine', 'gold momentum')
    assert result['retrieved_context'] == '' and result['retrieved_message_ids'] == []


def test_failed_vector_write_recovers_without_duplicates(memory, monkeypatch):
    memory.messages.save('s', 'user', 'gold momentum', 'stable')
    original = memory.vectors.upsert

    def unavailable(message):
        raise RuntimeError('index offline')

    monkeypatch.setattr(memory.vectors, 'upsert', unavailable)
    assert memory.reconcile() == 0
    assert memory.messages.get('s', 'stable')['embedding_status'] == 'failed'
    assert memory.messages.get('s', 'stable')['content'] == 'gold momentum'
    monkeypatch.setattr(memory.vectors, 'upsert', original)
    assert memory.reconcile() == 1
    memory.index(memory.messages.get('s', 'stable'))
    assert memory.vectors.collection.count() == 1
    assert memory.messages.get('s', 'stable')['embedding_status'] == 'indexed'
    # Crash after Chroma upsert but before SQLite status update is also safe to retry.
    memory.messages.reset_index()
    assert memory.reconcile() == 1
    assert memory.vectors.collection.count() == 1


def test_local_adapter_uses_provisioned_model_and_never_falls_back(monkeypatch):
    from types import SimpleNamespace
    from backend.storage.embeddings import LocalEmbeddings
    calls = []

    class Model:
        def __init__(self, name, **kwargs):
            calls.append((name, kwargs))

        def encode(self, texts, **kwargs):
            assert kwargs == {'normalize_embeddings': True}
            return SimpleNamespace(tolist=lambda: [[.6, .8] for _ in texts])

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Model))
    adapter = LocalEmbeddings('provisioned-model')
    assert adapter.embed(['gold']) == [[.6, .8]]
    adapter.embed(['silver'])
    assert calls == [('provisioned-model', {'local_files_only': True, 'device': 'cpu'})]

    def unavailable(*args, **kwargs):
        raise OSError('missing model weights')

    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=unavailable))
    with pytest.raises(OSError, match='missing model weights'):
        LocalEmbeddings('missing').embed(['gold'])


def test_real_process_restart_preserves_sqlite_and_chroma(tmp_path):
    script = """
import json, os
from backend.config import Settings
from backend.storage.memory import make_memory
m = make_memory(Settings(_env_file=None))
if os.environ['PHASE'] == 'write':
    m.messages.save('restart', 'user', 'gold momentum', 'restart-message')
    assert m.reconcile() == 1
else:
    assert m.messages.history('restart')[0]['content'] == 'gold momentum'
    hits = m.vectors.search('restart', m.embeddings.embed(['gold momentum'])[0], 3)
    assert hits[0][0] == 'restart-message'
    assert hits[0][1] > .99
print('restart-ok')
"""
    env = dict(os.environ, MEMORY_EMBEDDING_ADAPTER='fake', SQLITE_PATH=str(tmp_path / 'restart.sqlite3'),
               CHROMA_PATH=str(tmp_path / 'chroma'))
    for phase in ['write', 'read']:
        result = subprocess.run([sys.executable, '-c', script], env=dict(env, PHASE=phase),
                                capture_output=True, text=True, timeout=45)
        assert result.returncode == 0, result.stderr
        assert 'restart-ok' in result.stdout


def test_cache_lru_and_revision():
    cache = SemanticCache(2, 0.9)
    cache.put('a', 'one', [1., 0.], (1,), [('1', 1.)])
    cache.put('b', 'two', [0., 1.], (1,), [('2', 1.)])
    assert cache.get('a', 'one', [1., 0.], (1,))
    cache.put('c', 'three', [1., 0.], (1,), [('3', 1.)])
    assert cache.get('b', 'two', [0., 1.], (1,)) is None
    assert cache.get('c', 'three', [1., 0.], (2,)) is None
    assert cache.get('a', 'one', [1., 0.], (1,)) is not None


async def test_context_changes_planning_and_validation_still_runs(memory, monkeypatch):
    from backend.research_agent.service import ChatRequest, run_research
    from backend.tests.research_fixtures import TestLLM, TestEngine, TestValidator, research_settings
    memory.settings.memory_recent_messages = 4
    memory.messages.save('s', 'user', 'Research gold momentum', 'prior')
    validator = TestValidator(memory.messages.db)
    monkeypatch.setattr('backend.research_agent.service.ValidationClient', lambda *args: validator)
    llm = TestLLM()
    response = await run_research(ChatRequest(session_id='s', message='Continue that study'), memory.settings,
        llm=llm, engine=TestEngine(), research_settings=research_settings(), memory=memory)
    assert 'gold momentum' in llm.calls[0][1]['recent_conversation_unverified']
    assert 'prior' in response.reply
    stages = [event.stage for event in response.trace]
    assert stages.index('context_build_complete') < stages.index('planning')
    assert len(validator.calls) == 2


async def test_context_budget_and_price_bypass(memory):
    memory.settings.memory_max_context_chars = 400
    memory.settings.memory_recent_messages = 4
    memory.messages.save('s', 'user', 'gold momentum ' * 1000)
    result = await memory.build_context('s', 'gold momentum')
    assert len(result['retrieved_context']) + len(result['recent_history']) <= 400
    result = await memory.build_context('s', 'What is the current gold price?')
    assert result['retrieved_context'] == result['recent_history'] == ''


async def test_embedding_outage_preserves_recent_history(memory, monkeypatch):
    memory.settings.memory_recent_messages = 2
    memory.messages.save('s', 'user', 'Research gold momentum')

    def broken(texts):
        raise OSError('model unavailable')

    monkeypatch.setattr(memory.embeddings, 'embed', broken)
    result = await memory.build_context('s', 'Continue that study')
    assert result['retrieved_context'] == ''
    assert 'Research gold momentum' in result['recent_history']


async def test_chat_persists_success_and_failed_user_request(memory, monkeypatch):
    from backend.llm import LLMError
    from backend.research_agent.service import ChatRequest, run_research
    request = ChatRequest(session_id='persist', message='gold momentum')
    response = await run_research(request, memory.settings, memory=memory)
    rows = memory.messages.history('persist')
    assert [row['role'] for row in rows] == ['user', 'assistant']
    assert rows[0]['message_id'] == response.user_message_id
    assert rows[1]['message_id'] == response.assistant_message_id
    assert rows[1]['content'] == response.reply
    assert json.loads(rows[1]['metadata_json'])['status'] == 'blocked'

    class FailedLLM:
        async def generate(self, *args):
            raise LLMError('offline')

    with pytest.raises(LLMError):
        from backend.tests.research_fixtures import TestEngine, research_settings
        await run_research(request, memory.settings, llm=FailedLLM(), memory=memory,
                           engine=TestEngine(), research_settings=research_settings())
    assert [row['role'] for row in memory.messages.history('persist')] == ['user', 'assistant', 'user']
