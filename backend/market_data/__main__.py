"""Run once; schedule externally with cron or a deployment scheduler."""
import asyncio
import json
import sys

from backend.config import Settings
from backend.market_data.provider import GoldAPIProvider, MarketDataUnavailable
from backend.market_data.repository import GoldRepository
from backend.market_data.service import sync_gold_price
from backend.storage.sqlite import Database


async def main() -> int:
    settings = Settings()
    repository = GoldRepository(Database(settings.sqlite_path), settings.gold_stale_after_seconds)
    try:
        snapshot = await sync_gold_price(repository, GoldAPIProvider(
            settings.gold_http_timeout_seconds, settings.gold_http_attempts))
    except MarketDataUnavailable as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(snapshot))
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
