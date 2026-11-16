import asyncio

from backend.market_data.provider import GoldAPIProvider
from backend.market_data.repository import GoldRepository
from backend.storage.sqlite import utc_now
from backend.trace import logger


async def sync_gold_price(repository: GoldRepository, provider: GoldAPIProvider) -> dict:
    quote = await provider.fetch()
    snapshot = await asyncio.to_thread(repository.save, quote, utc_now())
    logger.info('gold_sync_complete snapshot_id=%s hour=%s stale=%s',
                snapshot['id'], snapshot['observed_hour_utc'], snapshot['is_stale'])
    return snapshot
