from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from nvda_tracker import config, news, signals
from nvda_tracker.models import CRITICAL, OPPORTUNITY, RISK

CFG = config.load()


def make_daily(n=300, drift=0.001, seed=1, last_vol_mult=1.0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-11-20", periods=n, tz="America/New_York")
    close = 100 * np.cumprod(1 + rng.normal(drift, 0.015, n))
    vol = rng.integers(90_000_000, 110_000_000, n).astype(float)
    vol[-1] *= last_vol_mult
    return pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": vol}, index=idx)


def test_price_move_flags_large_gap_up():
    d = make_daily()
    price = float(d["Close"].iloc[-2]) * 1.08
    alerts = signals.detect_price(d, price, CFG, "NVDA")
    assert alerts and alerts[0].severity == CRITICAL and "surging" in alerts[0].title


def test_price_move_ignores_normal_day():
    d = make_daily()
    assert signals.detect_price(d, float(d["Close"].iloc[-2]) * 1.004, CFG, "NVDA") == []


def test_closing_volume_spike():
    d = make_daily(last_vol_mult=3.0)
    out = signals.detect_volume(d, d.iloc[0:0], live=False, minutes_since_open=None, cfg=CFG, sym="NVDA")
    assert out and out[0].severity == CRITICAL


def test_volume_normal_is_quiet():
    d = make_daily()
    assert signals.detect_volume(d, d.iloc[0:0], False, None, CFG, "NVDA") == []


def test_intraday_relative_volume():
    days = pd.bdate_range(end="2026-11-20", periods=8, tz="America/New_York")
    rows = []
    for k, day in enumerate(days):
        for m in range(0, 60, 5):  # 10:00-10:55 bars
            rows.append((day.replace(hour=10, minute=m), 1000 * (3 if k == len(days) - 1 else 1)))
    df = pd.DataFrame(rows, columns=["t", "Volume"]).set_index("t")
    assert abs(signals.relative_volume_intraday(df) - 3.0) < 1e-6


def test_rsi_bounds():
    s = pd.Series(np.linspace(100, 200, 60))
    assert signals.rsi(s).iloc[-1] > 95


def test_new_52wk_high_is_opportunity():
    d = make_daily(drift=0.002)
    price = float(d["Close"].max()) * 1.02
    out = signals.detect_momentum(d, price, CFG, "NVDA")
    assert any(a.key.startswith("52wk-high") and a.kind == OPPORTUNITY for a in out)


def test_news_scoring_and_direction():
    assert news.score("US tightens export controls on Nvidia chips")[0] < 0
    assert news.score("Analyst upgrades Nvidia, raises price target")[0] > 0
    assert news.impact("Nvidia shares rise slightly") == 0


def _hl(title, hours_ago=1):
    return news.Headline(title, "Reuters", "http://x/" + title[:5],
                         datetime.now(timezone.utc) - timedelta(hours=hours_ago))


def test_news_alerts_dedupe_and_first_run():
    hls = [_hl("DOJ opens antitrust probe into Nvidia"), _hl("Nvidia holds event")]
    alerts, ids = news.detect_news(hls, set(), CFG, "NVDA")
    assert len(alerts) == 1 and alerts[0].kind == RISK and alerts[0].severity == CRITICAL
    again, _ = news.detect_news(hls, ids, CFG, "NVDA")
    assert again == []
    first, _ = news.detect_news(hls, set(), CFG, "NVDA", first_run=True)
    assert first == []


def test_fetch_all_survives_one_blocked_source(monkeypatch):
    def blocked(*a, **k):
        raise OSError("HTTP Error 429")
    monkeypatch.setattr(news, "fetch", blocked)
    monkeypatch.setattr(news, "fetch_yahoo", lambda sym="NVDA": [_hl("Nvidia upgraded by analyst")])
    assert len(news.fetch_all("NVDA")) == 1


def test_fetch_all_raises_when_every_source_fails(monkeypatch):
    def blocked(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(news, "fetch", blocked)
    monkeypatch.setattr(news, "fetch_yahoo", blocked)
    import pytest
    with pytest.raises(RuntimeError):
        news.fetch_all("NVDA")


def test_stale_news_ignored():
    alerts, _ = news.detect_news([_hl("Nvidia export ban announced", hours_ago=30)], set(), CFG, "NVDA")
    assert alerts == []
