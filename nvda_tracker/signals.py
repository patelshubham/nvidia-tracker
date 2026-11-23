"""Pure detectors: take price DataFrames + config, return Alerts. No network, no I/O."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from .models import CRITICAL, INFO, OPPORTUNITY, RISK, WARN, WATCH, Alert


# ---------- indicators ----------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down  # down == 0 -> inf -> RSI 100 (an unbroken rally)
    return 100 - 100 / (1 + rs)


def relative_volume_intraday(intraday: pd.DataFrame, lookback: int = 20) -> float | None:
    """Cumulative volume so far today / average cumulative volume at the same time of day."""
    if intraday.empty:
        return None
    dates = intraday.index.date
    today = dates[-1]
    last_t = intraday.index[-1].time()
    today_cum = intraday.loc[dates == today, "Volume"].sum()
    prior = []
    for d in sorted(set(dates) - {today})[-lookback:]:
        day = intraday[dates == d]
        prior.append(day.loc[day.index.time <= last_t, "Volume"].sum())
    prior = [p for p in prior if p > 0]
    if len(prior) < 5:
        return None
    return float(today_cum / (sum(prior) / len(prior)))


# ---------- detectors ----------

def detect_price(daily: pd.DataFrame, price: float, cfg: dict, sym: str) -> list[Alert]:
    c = cfg["price"]
    close = daily["Close"]
    if len(close) < 30:
        return []
    prev_close = float(close.iloc[-2])
    session = daily.index[-1].date()
    pct = (price / prev_close - 1) * 100
    rets = close.pct_change().iloc[-62:-1].dropna() * 100
    sd = float(rets.std()) or 1.0
    z = pct / sd
    out: list[Alert] = []

    if abs(pct) >= c["min_abs_pct"] and abs(z) >= c["z_warn"]:
        sev = CRITICAL if abs(z) >= c["z_critical"] else WARN
        up = pct > 0
        out.append(Alert(
            key=f"price:{session}:{'up' if up else 'down'}:{sev}",
            title=f"{sym} {'surging' if up else 'dropping'} {pct:+.1f}%",
            body=f"${price:.2f} vs prev close ${prev_close:.2f}. "
                 f"That is {abs(z):.1f} std devs vs its typical daily move ({sd:.1f}%).",
            severity=sev,
            kind=WATCH,
        ))
    return out


def detect_gap(daily: pd.DataFrame, cfg: dict, sym: str) -> list[Alert]:
    if len(daily) < 2:
        return []
    row, prev = daily.iloc[-1], daily.iloc[-2]
    gap = (float(row["Open"]) / float(prev["Close"]) - 1) * 100
    if abs(gap) < cfg["price"]["gap_pct"]:
        return []
    session = daily.index[-1].date()
    return [Alert(
        key=f"gap:{session}",
        title=f"{sym} gapped {gap:+.1f}% at the open",
        body=f"Opened ${row['Open']:.2f} vs prev close ${prev['Close']:.2f}.",
        severity=WARN,
    )]


def detect_volume(daily: pd.DataFrame, intraday: pd.DataFrame, live: bool,
                  minutes_since_open: float | None, cfg: dict, sym: str) -> list[Alert]:
    c = cfg["volume"]
    session = daily.index[-1].date()
    if live:
        if minutes_since_open is None or minutes_since_open < c["min_minutes_after_open"]:
            return []
        rv = relative_volume_intraday(intraday)
        label = "so far today vs same time on a typical day"
    else:
        vols = daily["Volume"]
        base = vols.iloc[-21:-1].mean()
        rv = float(vols.iloc[-1] / base) if base else None
        label = "full day vs 20-day average"
    if rv is None or rv < c["rel_warn"]:
        return []
    sev = CRITICAL if rv >= c["rel_critical"] else WARN
    day_pct = (float(daily["Close"].iloc[-1]) / float(daily["Close"].iloc[-2]) - 1) * 100
    if abs(day_pct) < 0.5:
        meaning = "Heavy volume with price going nowhere: possible accumulation/distribution."
    else:
        meaning = f"Price {day_pct:+.1f}% on this volume, so the move has conviction."
    return [Alert(
        key=f"volume:{session}:{'live' if live else 'close'}:{sev}",
        title=f"{sym} volume {rv:.1f}x normal",
        body=f"{rv:.1f}x ({label}). {meaning}",
        severity=sev,
    )]


def detect_momentum(daily: pd.DataFrame, price: float, cfg: dict, sym: str) -> list[Alert]:
    c = cfg["momentum"]
    close = daily["Close"].copy()
    if len(close) < 60:
        return []
    close.iloc[-1] = price
    session = daily.index[-1].date()
    out: list[Alert] = []

    r5 = (close.iloc[-1] / close.iloc[-6] - 1) * 100
    if abs(r5) >= c["return_5d_pct"]:
        out.append(Alert(
            key=f"mom5d:{session}:{'up' if r5 > 0 else 'down'}",
            title=f"{sym} 5-day move {r5:+.1f}%",
            body="Strong short-term momentum" + (" (check for chasing risk)." if r5 > 0 else " (selling pressure)."),
            severity=WARN,
        ))

    r = rsi(close)
    rsi_now, rsi_prev = float(r.iloc[-1]), float(r.iloc[-2])
    if rsi_now >= c["rsi_overbought"] and rsi_prev < c["rsi_overbought"]:
        out.append(Alert(key=f"rsi-hi:{session}", title=f"{sym} RSI crossed {rsi_now:.0f} (overbought)",
                         body="Stretched to the upside; pullbacks are common from here.",
                         severity=INFO, kind=RISK))
    if rsi_now <= c["rsi_oversold"] and rsi_prev > c["rsi_oversold"]:
        out.append(Alert(key=f"rsi-lo:{session}", title=f"{sym} RSI fell to {rsi_now:.0f} (oversold)",
                         body="Sold off hard; watch for a bounce.", severity=WARN, kind=OPPORTUNITY))

    # 52-week high breakout
    hi_52 = float(close.iloc[-253:-1].max())
    if price > hi_52:
        out.append(Alert(key=f"52wk-high:{session}", title=f"{sym} new 52-week high ${price:.2f}",
                         body=f"Broke above prior high ${hi_52:.2f}. Breakouts on high volume tend to continue.",
                         severity=WARN, kind=OPPORTUNITY))

    # moving-average crosses
    ma50, ma200 = close.rolling(50).mean(), close.rolling(200).mean()
    for name, ma in (("50-day", ma50), ("200-day", ma200)):
        if pd.isna(ma.iloc[-1]) or pd.isna(ma.iloc[-2]):
            continue
        was_above, is_above = close.iloc[-2] > ma.iloc[-2], close.iloc[-1] > ma.iloc[-1]
        if was_above != is_above:
            out.append(Alert(
                key=f"ma{name}:{session}:{'up' if is_above else 'down'}",
                title=f"{sym} {'reclaimed' if is_above else 'lost'} its {name} average",
                body=f"Price ${price:.2f} vs {name} MA ${ma.iloc[-1]:.2f}.",
                severity=WARN if name == "200-day" else INFO,
                kind=OPPORTUNITY if is_above else RISK,
            ))
    if not pd.isna(ma200.iloc[-2]):
        if ma50.iloc[-2] <= ma200.iloc[-2] and ma50.iloc[-1] > ma200.iloc[-1]:
            out.append(Alert(key=f"golden:{session}", title=f"{sym} golden cross (50d over 200d)",
                             body="Long-term trend signal turned bullish.", kind=OPPORTUNITY))
        if ma50.iloc[-2] >= ma200.iloc[-2] and ma50.iloc[-1] < ma200.iloc[-1]:
            out.append(Alert(key=f"death:{session}", title=f"{sym} death cross (50d under 200d)",
                             body="Long-term trend signal turned bearish.", kind=RISK))

    # oversold dip inside a longer-term uptrend: the classic buy-the-dip setup
    dd = (price / float(close.iloc[-253:].max()) - 1) * 100
    if dd <= -c["dip_drawdown_pct"] and rsi_now <= 40 and price > float(ma200.iloc[-1] or 0) * 0.95:
        out.append(Alert(
            key=f"dip:{session}", severity=WARN, kind=OPPORTUNITY,
            title=f"{sym} dip setup: {dd:.0f}% off 52w high, RSI {rsi_now:.0f}",
            body="Pulled back sharply but still near/above its 200-day average. Possible entry zone.",
        ))
    return out


def detect_relative_strength(daily: pd.DataFrame, price: float, bench_daily: pd.DataFrame,
                             bench_price: float, cfg: dict, sym: str, bench: str) -> list[Alert]:
    if len(daily) < 2 or len(bench_daily) < 2:
        return []
    own = (price / float(daily["Close"].iloc[-2]) - 1) * 100
    ref = (bench_price / float(bench_daily["Close"].iloc[-2]) - 1) * 100
    diff = own - ref
    if abs(diff) < cfg["momentum"]["relative_strength_pts"]:
        return []
    session = daily.index[-1].date()
    return [Alert(
        key=f"rel:{session}:{'out' if diff > 0 else 'under'}",
        title=f"{sym} {'outperforming' if diff > 0 else 'lagging'} {bench} by {abs(diff):.1f} pts",
        body=f"{sym} {own:+.1f}% vs {bench} {ref:+.1f}% today. "
             + ("Stock-specific catalyst, not just sector flow." if diff else ""),
        severity=INFO,
    )]


def detect_earnings(next_earnings: datetime | None, now: datetime, sym: str) -> list[Alert]:
    if next_earnings is None:
        return []
    days = (next_earnings - now).total_seconds() / 86400
    if not 0 <= days <= 3:
        return []
    return [Alert(
        key=f"earnings:{next_earnings.date()}",
        title=f"{sym} earnings in {days:.0f} day(s)",
        body=f"Expected {next_earnings:%a %d %b}. Expect elevated volatility and volume.",
        severity=WARN,
    )]
