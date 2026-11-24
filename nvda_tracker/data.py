from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

import time

NY = ZoneInfo("America/New_York")

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    """Return fn() but reuse the last result for `ttl` seconds. Lets a fast watch loop poll live
    prices every tick while slow-changing data (daily bars, earnings, news) is fetched rarely."""
    now = time.monotonic()
    hit = _cache.get(key)
    if ttl > 0 and hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def in_session(now: datetime | None = None) -> bool:
    """Weekday 09:00-16:15 ET (a little wider than the 09:30-16:00 session)."""
    now = (now or datetime.now(NY)).astimezone(NY)
    return now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (16, 15)


def daily(sym: str) -> pd.DataFrame:
    df = yf.Ticker(sym).history(period="2y", interval="1d", auto_adjust=False)
    return df.dropna(subset=["Close"])


def intraday(sym: str) -> pd.DataFrame:
    df = yf.Ticker(sym).history(period="1mo", interval="5m", auto_adjust=False)
    return df.dropna(subset=["Close"])


def next_earnings(sym: str) -> datetime | None:
    try:
        cal = yf.Ticker(sym).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            d = dates[0]
            return datetime(d.year, d.month, d.day, tzinfo=NY)
    except Exception:
        pass
    return None


def market_status(intra: pd.DataFrame, now: datetime | None = None) -> tuple[bool, float | None]:
    """(live, minutes since the 09:30 ET open). 'Live' = last 5m bar is fresh (handles holidays)."""
    if intra.empty:
        return False, None
    now = (now or datetime.now(NY)).astimezone(NY)
    last = intra.index[-1].to_pydatetime().astimezone(NY)
    live = (now - last).total_seconds() < 20 * 60 and last.date() == now.date()
    opened = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return live, (now - opened).total_seconds() / 60
