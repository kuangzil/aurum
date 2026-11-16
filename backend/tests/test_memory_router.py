import logging

import pytest

from backend.tests.test_memory import memory, Validator
from backend.research_agent.service import ChatRequest, run_research

EVIDENCE = ('Gold strategies:\n1. Momentum. Risk: whipsaws in sideways markets.\n'
            '2. Mean reversion. Risk: losses during sustained trends.\n'
            '3. Breakout. Risk: false breakouts and slippage.')
FOLLOWUP = '第三个策略有什么风险？'


async def seed(memory):
    memory.messages.save('s', 'user', EVIDENCE, 'evidence')
    memory.reconcile()
    result = await memory.build_context('s', EVIDENCE)
    assert result['memory_route'] == 'chroma'
    return result


async def test_indexing_only_revision_change_is_not_content_change(memory, caplog):
    await seed(memory)
    memory.messages.save('s', 'user', EVIDENCE, 'question')
    memory.messages.save('s', 'assistant', 'See the three recorded strategies.', 'answer')
    memory.completed_turn('s', EVIDENCE, 'question', 'answer')
    before = memory.messages.revision('s')
    memory.reconcile()
    after = memory.messages.revision('s')
    assert before[:2] == after[:2] and before[2] < after[2]
    with caplog.at_level(logging.INFO, logger='aurum.trace'):
        result = await memory.build_context('s', FOLLOWUP)
    assert result['memory_route'] == 'working_memory'
    assert 'false breakouts and slippage' in result['retrieved_context']
    assert result['retrieved_message_ids'] == ['evidence']
    assert result['message_sources'] == {'evidence': 'chroma'}
    assert memory.statistics()['chroma_calls'] == 1


async def test_real_service_two_turns_saves_one_chroma_call(memory, monkeypatch):
    monkeypatch.setattr('backend.research_agent.service.ValidationClient', lambda *args: Validator())
    memory.messages.save('s', 'user', EVIDENCE, 'evidence')
    first = await run_research(ChatRequest(session_id='s', message=EVIDENCE), memory.settings, memory=memory)
    assert first.context_source == 'rag'
    second = await run_research(ChatRequest(session_id='s', message=FOLLOWUP), memory.settings, memory=memory)
    assert second.context_source == 'working_memory'
    assert any(e.stage == 'memory_route' and 'retrieval_skipped=True' in e.detail for e in second.trace)
    assert second.validation.verdict == 'insufficient_evidence'
    assert memory.statistics()['chroma_calls'] == 1
    # Same two requests with L1 disabled: existing L2 invalidates on turn writes.
    memory.messages.save('baseline', 'user', EVIDENCE, 'baseline-evidence')
    await run_research(ChatRequest(session_id='baseline', message=EVIDENCE), memory.settings, memory=memory)
    memory.working.invalidate('baseline')
    await run_research(ChatRequest(session_id='baseline', message=FOLLOWUP), memory.settings, memory=memory)
    assert memory.statistics()['chroma_calls'] == 3  # optimized=1, baseline=2


@pytest.mark.parametrize('query', ['What risks does the fifth strategy have?',
    'What risks does the third bitcoin strategy have?', '第三个策略在2025年有什么风险？',
    'Read a new document about gold', 'Research bitcoin mining energy costs',
    '它有什么风险？'])
async def test_unsupported_reference_or_new_scope_retrieves(memory, query):
    await seed(memory)
    result = await memory.build_context('s', query)
    assert result['memory_route'] == 'chroma'
    assert memory.statistics()['chroma_calls'] == 2


async def test_working_reuse_and_revision_misses_are_diagnosed(memory, caplog):
    await seed(memory)
    assert (await memory.build_context('s', FOLLOWUP))['memory_route'] == 'working_memory'
    memory.messages.save('s', 'user', 'Additional document', 'new')
    with caplog.at_level(logging.INFO, logger='aurum.trace'):
        assert (await memory.build_context('s', 'What risk does the second one have?'))['memory_route'] == 'chroma'
    assert 'reason=message_revision_changed' in caplog.text


async def test_isolation_tampered_snapshot_and_budget(memory, caplog):
    await seed(memory)
    other = await memory.build_context('other', FOLLOWUP)
    assert other['retrieved_context'] == '' and other['memory_route'] == 'chroma'
    memory.working.entries['s'].messages['evidence']['content'] += ' altered'
    with caplog.at_level(logging.INFO, logger='aurum.trace'):
        result = await memory.build_context('s', FOLLOWUP)
    assert result['memory_route'] == 'chroma'
    assert 'reason=authoritative_message_changed' in caplog.text
    await memory.build_context('s', EVIDENCE)
    memory.settings.memory_max_context_chars = 200
    result = await memory.build_context('s', FOLLOWUP)
    assert result['memory_route'] != 'working_memory'


async def test_concurrent_write_cannot_be_blessed_by_completed_turn(memory, caplog):
    await seed(memory)
    memory.messages.save('s', 'user', EVIDENCE, 'q')
    memory.messages.save('s', 'assistant', 'answer', 'a')
    memory.messages.save('s', 'user', 'concurrent unrelated change', 'other')
    with caplog.at_level(logging.INFO, logger='aurum.trace'):
        memory.completed_turn('s', EVIDENCE, 'q', 'a')
    assert 's' not in memory.working.entries
    assert 'reason=concurrent_turn' in caplog.text


async def test_ambiguous_list_and_missing_risk_fail_coverage(memory):
    for text in [EVIDENCE.replace('Risk: false breakouts and slippage.', 'Risk: unknown'),
                 EVIDENCE + '\n' + EVIDENCE]:
        memory.working.invalidate('s')
        row = memory.messages.save('s', 'user', text)
        memory.working.put('s', text, memory.messages.revision('s'), [row], {row['message_id']: 'chroma'})
        assert memory.working.get('s', FOLLOWUP, memory.messages.revision('s')) is None


async def test_freshness_bypasses_all_history(memory):
    await seed(memory)
    result = await memory.build_context('s', 'What is the current gold price?')
    assert result['retrieved_context'] == result['recent_history'] == ''
    assert result['memory_route'] == 'market_data'
    assert memory.statistics()['chroma_calls'] == 1


async def test_failed_ordinal_coverage_cannot_be_rescued_by_semantic_cache(memory):
    await seed(memory)
    memory.working.invalidate('s')
    vector = memory.embeddings.embed([FOLLOWUP])[0]
    memory.cache.put('s', FOLLOWUP, vector, memory.messages.revision('s'), [('evidence', 1.0)])
    assert (await memory.build_context('s', FOLLOWUP))['memory_route'] == 'chroma'


async def test_generated_list_cannot_silently_reorder_evidence(memory):
    await seed(memory)
    memory.messages.save('s', 'user', EVIDENCE, 'q')
    memory.messages.save('s', 'assistant', '1. Breakout\n2. Momentum\n3. Mean reversion', 'a')
    memory.completed_turn('s', EVIDENCE, 'q', 'a')
    assert 's' not in memory.working.entries
    assert (await memory.build_context('s', FOLLOWUP))['memory_route'] == 'chroma'
