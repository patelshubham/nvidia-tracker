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


def make_intraday(sessions=8, today_close_mult=1.0, today_vol_mult=1.0):
    """5-minute bars 09:30-15:55 ET; the final session is 'today'."""
    days = pd.bdate_range(end="2026-11-20", periods=sessions, tz="America/New_York")
    rows = []
    for k, day in enumerate(days):
        today = k == sessions - 1
        for b in range(78):
            ts = day.replace(hour=9, minute=30) + pd.Timedelta(minutes=5 * b)
            px = 100.0
            if today and b >= 72:  # last 30 minutes of the day are the move
                px = 100.0 * (1 + (today_close_mult - 1) * (b - 71) / 6)
            vol = 1000.0 * (today_vol_mult if today and b >= 75 else 1.0)
            rows.append((ts, px, px, vol))
    return pd.DataFrame(rows, columns=["t", "Open", "Close", "Volume"]).set_index("t")


def test_velocity_flags_fast_move_while_live():
    out = signals.detect_velocity(make_intraday(today_close_mult=1.04), True, CFG, "NVDA")
    assert out and out[0].intraday and "jumped" in out[0].title


def test_velocity_quiet_and_silent_when_closed():
    assert signals.detect_velocity(make_intraday(), True, CFG, "NVDA") == []
    assert signals.detect_velocity(make_intraday(today_close_mult=1.2), False, CFG, "NVDA") == []


def test_volume_burst_detected():
    out = signals.detect_volume_burst(make_intraday(today_vol_mult=5), True, CFG, "NVDA")
    assert out and out[0].intraday
    assert signals.detect_volume_burst(make_intraday(), True, CFG, "NVDA") == []


def test_price_alert_escalates_as_move_extends():
    d = make_daily()
    prev = float(d["Close"].iloc[-2])
    k1 = signals.detect_price(d, prev * 1.08, CFG, "NVDA")[0].key
    k2 = signals.detect_price(d, prev * 1.20, CFG, "NVDA")[0].key
    assert k1 != k2


def test_stale_intraday_alerts_dropped_after_close():
    from nvda_tracker.models import Alert
    from nvda_tracker.runner import drop_stale
    mixed = [Alert("a", "x", "y", intraday=True), Alert("b", "news", "y")]
    assert [a.key for a in drop_stale(mixed, live=False)] == ["b"]
    assert len(drop_stale(mixed, live=True)) == 2


def test_telegram_message_is_escaped_and_silent_for_info(monkeypatch):
    from nvda_tracker import notify
    from nvda_tracker.models import INFO, Alert
    sent = {}
    monkeypatch.setattr(notify, "telegram_api", lambda tok, m, p=None: sent.update(m=m, p=p))
    notify._telegram("T", "42", Alert("k", "NVDA <b>&", "x < y", severity=INFO, url="http://a/?q=1&r=2"))
    assert sent["m"] == "sendMessage" and sent["p"]["chat_id"] == "42"
    assert "&lt;b&gt;&amp;" in sent["p"]["text"] and sent["p"]["disable_notification"] is True


def test_save_local_notify_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LOCAL_PATH", tmp_path / "local.toml")
    config.save_local_notify({"telegram_token": "abc:123", "telegram_chat_id": "42"})
    config.save_local_notify({"ntfy_topic": ""})
    import tomllib
    got = tomllib.loads((tmp_path / "local.toml").read_text())["notify"]
    assert got == {"telegram_token": "abc:123", "telegram_chat_id": "42", "ntfy_topic": ""}


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
