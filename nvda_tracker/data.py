from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

NY = ZoneInfo("America/New_York")


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
