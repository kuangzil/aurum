from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json

import httpx
import pytest

from backend.api.main import create_app
from backend.config import Settings
from backend.market_data.provider import ENDPOINT, GoldAPIProvider, GoldQuote, MarketDataUnavailable
from backend.market_data.repository import GoldRepository, describe_observation
from backend.market_data.service import sync_gold_price
from backend.research_agent.graph import build_research_graph
from backend.storage.memory import make_memory
from backend.storage.sqlite import Database, utc_iso, utc_now
from backend.research_agent.service import ChatRequest, run_research


def payload(**updates):
    return dict({'symbol': 'XAU', 'currency': 'USD', 'price': '2650.123456',
                 'updatedAt': utc_iso(utc_now())}, **updates)


@pytest.fixture
def market(tmp_path):
    return GoldRepository(Database(tmp_path / 'gold.sqlite3'))


async def test_provider_and_sync_preserve_precision_source_and_timestamps(market):
    quoted = utc_now() - timedelta(minutes=5)

    def handler(request):
        assert str(request.url) == ENDPOINT
        return httpx.Response(200, text='{"symbol":"XAU","currency":"USD","price":2650.123456789123,'
                              f'"updatedAt":"{quoted.isoformat()}"}}')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await sync_gold_price(market, GoldAPIProvider(client=client))
    assert snapshot['price'] == '2650.123456789123'
    assert snapshot['source'] == 'gold-api.com'
    assert snapshot['symbol'] == 'XAU' and snapshot['currency'] == 'USD'
    assert snapshot['unit'] == 'troy_ounce'
    assert snapshot['quoted_at_utc'] == quoted.isoformat()
    assert snapshot['fetched_at_utc'] != snapshot['quoted_at_utc']
    assert snapshot['observed_hour_utc'].endswith(':00:00+00:00')
    assert snapshot['is_stale'] is False
    restarted = GoldRepository(Database(market.db.path))
    assert restarted.latest()['id'] == snapshot['id']


def test_hourly_idempotency_concurrency_and_unchanged_quote_history(market):
    now = utc_now().replace(minute=10)
    quote = GoldQuote.model_validate(payload(updatedAt=now.isoformat()))
    with ThreadPoolExecutor(max_workers=6) as pool:
        snapshots = list(pool.map(lambda _: market.save(quote, now), range(12)))
    assert len({row['id'] for row in snapshots}) == 1
    assert len(market.history()) == 1
    changed = GoldQuote.model_validate(payload(price='2999', updatedAt=now.isoformat()))
    assert market.save(changed, now)['price'] == str(quote.price)
    next_hour = market.save(quote, now + timedelta(hours=1))
    assert next_hour['id'] != snapshots[0]['id']
    assert next_hour['quoted_at_utc'] == snapshots[0]['quoted_at_utc']
    assert len(market.history()) == 2


def test_staleness_recomputed_on_read_and_not_presented_as_current(market):
    now = utc_now()
    quote = GoldQuote.model_validate(payload(updatedAt=now.isoformat()))
    stored = market.save(quote, now)
    assert not stored['is_stale']
    old = market.latest(now + timedelta(hours=3))
    assert old['is_stale'] and not old['stale_at_ingestion']
    assert old['quote_age_seconds'] == 10800
    assert 'current price is unavailable' in describe_observation(old)
    assert 'no successfully ingested' in describe_observation(None)
    stale = GoldQuote.model_validate(payload(updatedAt=(now - timedelta(days=3)).isoformat()))
    saved = market.save(stale, now + timedelta(hours=1))
    assert saved['stale_at_ingestion'] and saved['is_stale']


def test_timestamp_normalization_and_invalid_future(market):
    quote = GoldQuote.model_validate(payload(updatedAt='2026-01-01T03:30:00+03:30'))
    assert quote.updated_at.isoformat() == '2026-01-01T00:00:00+00:00'
    with pytest.raises(ValueError, match='Future quotes'):
        market.save(GoldQuote.model_validate(payload(updatedAt=utc_iso(utc_now() + timedelta(days=1)))))
    assert market.history() == []


@pytest.mark.parametrize('changes', [
    {'price': 'NaN'}, {'price': 'Infinity'}, {'price': '-Infinity'}, {'price': 0}, {'price': -2},
    {'price': None}, {'price': 'abc'}, {'symbol': 'XAG'}, {'currency': 'EUR'},
    {'updatedAt': 'invalid'}, {'updatedAt': None}, {'updatedAt': 12345},
    {'updatedAt': '2026-01-01T00:00:00'}, {'updatedAt': '2099-01-01T00:00:00Z'},
])
async def test_invalid_provider_data_never_creates_snapshot(market, changes):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload(**changes)))) as client:
        with pytest.raises(MarketDataUnavailable):
            await sync_gold_price(market, GoldAPIProvider(client=client))
    assert market.latest() is None


@pytest.mark.parametrize('missing', ['symbol', 'currency', 'price', 'updatedAt'])
async def test_required_fields(market, missing):
    body = payload()
    del body[missing]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body))) as client:
        with pytest.raises(MarketDataUnavailable):
            await sync_gold_price(market, GoldAPIProvider(client=client))
    assert market.history() == []


@pytest.mark.parametrize('failure', ['invalid_json', 'http', 'timeout', 'network'])
async def test_failure_preserves_last_successful_observation(market, failure):
    original = market.save(GoldQuote.model_validate(payload()))

    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('timeout', request=request)
        if failure == 'network':
            raise httpx.ConnectError('unavailable', request=request)
        return httpx.Response(503) if failure == 'http' else httpx.Response(200, text='not json')

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MarketDataUnavailable):
            await sync_gold_price(market, GoldAPIProvider(attempts=1, client=client))
    assert market.latest()['id'] == original['id']
    assert len(market.history()) == 1


async def test_bounded_retries(market, monkeypatch):
    calls, delays = [], []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr('backend.market_data.provider.asyncio.sleep', sleep)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MarketDataUnavailable):
            await sync_gold_price(market, GoldAPIProvider(attempts=3, client=client))
    assert len(calls) == 3 and delays == [1., 2.]


async def test_market_reads_protected_trigger_and_json_ndjson_contracts(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / 'api.sqlite3',
                        chroma_path=tmp_path / 'chroma', memory_embedding_adapter='fake',
                        internal_job_token='server-only-test-token')
    memory = make_memory(settings)
    market = GoldRepository(memory.messages.db)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as provider_client:
        provider = GoldAPIProvider(client=provider_client)
        app = create_app(settings, memory, market, provider)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.get('/market/gold/latest')).status_code == 404
            assert (await client.get('/market/gold/history')).json() == {'snapshots': []}
            assert (await client.get('/market/gold/history?limit=0')).status_code == 422
            assert (await client.get('/market/gold/history?limit=1001')).status_code == 422
            assert (await client.post('/internal/jobs/sync-gold-price')).status_code == 401
            assert (await client.post('/internal/jobs/sync-gold-price', headers={'Authorization': 'Bearer wrong'})).status_code == 401
            assert not calls
            response = await client.post('/internal/jobs/sync-gold-price', headers={'Authorization': 'Bearer server-only-test-token'})
            assert response.status_code == 200
            assert (await client.get('/market/gold/latest')).json()['price'] == '2650.123456'
            assert len((await client.get('/market/gold/history')).json()['snapshots']) == 1
            assert 'server-only-test-token' not in response.text
            body = {'session_id': 'api', 'message': 'What is the current gold price?'}
            for accept in ['application/json', 'application/x-ndjson']:
                response = await client.post('/chat', json=body, headers={'Accept': accept})
                assert response.status_code == 200
                result = response.json() if accept == 'application/json' else json.loads(response.text.splitlines()[-1])['result']
                assert result['research'] == [] and result['status'] == 'blocked'
                assert result['validation'] == []
                assert result['market_observation']['price'] == '2650.123456'
                assert 'within the configured freshness window' in result['reply']
            settings.internal_job_token = settings.internal_job_token.__class__('')
            assert (await client.post('/internal/jobs/sync-gold-price')).status_code == 404
    assert len(memory.messages.history('api')) == 4


async def test_stale_and_missing_prices_cannot_come_from_memory(tmp_path, market):
    settings = Settings(_env_file=None, sqlite_path=tmp_path / 'memory.sqlite3',
                        chroma_path=tmp_path / 'chroma', memory_embedding_adapter='fake')
    memory = make_memory(settings)
    memory.messages.save('s', 'assistant', 'The current gold price is 999999 USD.', 'old-price')
    missing = (await run_research(ChatRequest(session_id='s', message='What is the current gold price?'),
        settings, memory=memory, market=market)).model_dump()
    assert '999999' not in missing['reply']
    assert 'Current XAU/USD price unavailable' in missing['reply']
    market.save(GoldQuote.model_validate(payload(updatedAt=utc_iso(utc_now() - timedelta(days=2)))))
    stale = (await run_research(ChatRequest(session_id='s', message='What is the current gold price?'),
        settings, memory=memory, market=market)).model_dump()
    assert 'STALE' in stale['reply'] and 'current price is unavailable' in stale['reply']
    assert '999999' not in stale['reply']
    assert stale['validation'] == [] and stale['status'] == 'blocked'


async def test_freshness_rechecked_before_report(market, monkeypatch, tmp_path):
    now = utc_now()
    market.save(GoldQuote.model_validate(payload(updatedAt=utc_iso(now))), now)
    read = market.latest
    reads = []

    def latest():
        reads.append(True)
        return read(now if len(reads) == 1 else now + timedelta(hours=3))

    monkeypatch.setattr(market, 'latest', latest)
    settings = Settings(_env_file=None, sqlite_path=tmp_path/'memory.sqlite3',
                        chroma_path=tmp_path/'chroma', memory_embedding_adapter='fake')
    result = (await run_research(ChatRequest(session_id='s',message='current gold price'),
        settings, market=market)).model_dump()
    assert len(reads) == 2
    assert result['market_observation']['is_stale']
    assert 'current price is unavailable' in result['reply']
