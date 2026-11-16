from datetime import datetime
from uuid import uuid4

from backend.market_data.provider import GoldQuote, SOURCE
from backend.storage.sqlite import Database, utc_iso, utc_now


class GoldRepository:
    def __init__(self, db: Database, stale_after_seconds: int = 7200):
        self.db, self.stale_after_seconds = db, stale_after_seconds

    def view(self, row: dict, now: datetime | None = None) -> dict:
        now = now or utc_now()
        quoted = datetime.fromisoformat(row['quoted_at_utc'])
        fetched = datetime.fromisoformat(row['fetched_at_utc'])
        age = (now - quoted).total_seconds()
        fetch_age = (now - fetched).total_seconds()
        return dict(row, stale_at_ingestion=bool(row['is_stale']),
                    is_stale=bool(row['is_stale']) or age > self.stale_after_seconds or
                        fetch_age > self.stale_after_seconds or age < -300,
                    quote_age_seconds=max(0, age), fetch_age_seconds=max(0, fetch_age),
                    stale_after_seconds=self.stale_after_seconds, as_of_utc=utc_iso(now))

    def save(self, quote: GoldQuote, fetched_at: datetime | None = None) -> dict:
        fetched_at = fetched_at or utc_now()
        fetched = utc_iso(fetched_at)
        hour = datetime.fromisoformat(fetched).replace(minute=0, second=0, microsecond=0).isoformat()
        age = (fetched_at - quote.updated_at).total_seconds()
        if age < -300:
            raise ValueError('Future quotes are not eligible observations')
        with self.db.connect() as conn:
            conn.execute("""INSERT INTO gold_price_snapshots VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source,symbol,currency,observed_hour_utc) DO NOTHING""",
                (str(uuid4()), quote.symbol, SOURCE, quote.currency, 'troy_ounce', str(quote.price),
                 utc_iso(quote.updated_at), fetched, hour, int(age > self.stale_after_seconds)))
            row = dict(conn.execute("""SELECT * FROM gold_price_snapshots
                WHERE source=? AND symbol=? AND currency=? AND observed_hour_utc=?""",
                (SOURCE, quote.symbol, quote.currency, hour)).fetchone())
        return self.view(row, fetched_at)

    def latest(self, now: datetime | None = None) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute("""SELECT * FROM gold_price_snapshots WHERE symbol='XAU' AND currency='USD'
                ORDER BY observed_hour_utc DESC LIMIT 1""").fetchone()
        return self.view(dict(row), now) if row else None

    def history(self, limit: int = 24, now: datetime | None = None) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("SELECT * FROM gold_price_snapshots ORDER BY observed_hour_utc DESC LIMIT ?", (limit,)).fetchall()
        return [self.view(dict(row), now) for row in rows]


def describe_observation(snapshot: dict | None) -> str:
    if snapshot is None:
        return 'Current XAU/USD price unavailable: no successfully ingested market observation is stored.'
    label = ('STALE — last known observation; a current price is unavailable' if snapshot['is_stale']
             else 'Latest stored observation (within the configured freshness window; not a live tick)')
    return (f"{label}: {snapshot['price']} USD per troy ounce. "
            f"Source: {snapshot['source']}; quote timestamp: {snapshot['quoted_at_utc']}; "
            f"fetched: {snapshot['fetched_at_utc']}; quote age: {snapshot['quote_age_seconds']:.0f} seconds; "
            f"stale: {str(snapshot['is_stale']).lower()}. "
            'This external spot observation is separate from the synthetic research evidence and does not validate a strategy.')
