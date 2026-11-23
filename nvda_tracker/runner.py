from __future__ import annotations

import traceback
from datetime import datetime, timezone

from . import data, news, notify, signals
from .models import CRITICAL, Alert
from .state import State, log_alert


def collect(cfg: dict, state: State) -> tuple[list[Alert], dict]:
    """Run every detector. A failing detector never blocks the others."""
    sym, bench = cfg["general"]["symbol"], cfg["general"]["benchmark"]
    alerts: list[Alert] = []
    snap: dict = {}

    def guard(name, fn):
        try:
            return fn()
        except Exception:
            print(f"[warn] {name} failed:\n{traceback.format_exc(limit=2)}")
            return None

    d = guard("daily data", lambda: data.daily(sym))
    i = guard("intraday data", lambda: data.intraday(sym))
    if d is not None and len(d) > 30:
        live, mins = data.market_status(i if i is not None else d.iloc[0:0])
        price = float(i["Close"].iloc[-1]) if (i is not None and not i.empty
                and i.index[-1].date() == d.index[-1].date()) else float(d["Close"].iloc[-1])
        snap.update(price=price, live=live, prev_close=float(d["Close"].iloc[-2]),
                    session=str(d.index[-1].date()))
        alerts += guard("price", lambda: signals.detect_price(d, price, cfg, sym)) or []
        alerts += guard("gap", lambda: signals.detect_gap(d, cfg, sym)) or []
        alerts += guard("volume", lambda: signals.detect_volume(
            d, i if i is not None else d.iloc[0:0], live, mins, cfg, sym)) or []
        alerts += guard("momentum", lambda: signals.detect_momentum(d, price, cfg, sym)) or []

        bd = guard("benchmark data", lambda: data.daily(bench))
        if bd is not None and len(bd) > 2:
            bp = float(bd["Close"].iloc[-1])
            alerts += guard("relative strength", lambda: signals.detect_relative_strength(
                d, price, bd, bp, cfg, sym, bench)) or []

        ne = guard("earnings", lambda: data.next_earnings(sym))
        alerts += signals.detect_earnings(ne, datetime.now(timezone.utc).astimezone(data.NY), sym)

    hl = guard("news", lambda: news.fetch_all(sym))
    if hl is not None:
        na, seen_ids = news.detect_news(hl, set(state.seen_news), cfg, sym,
                                        first_run=state.first_run)
        alerts += na
        state.seen_news = list(dict.fromkeys(state.seen_news + list(seen_ids)))
        snap["headlines"] = len(hl)

    return alerts, snap


def run_once(cfg: dict, notify_on: bool = True, quiet: bool = False) -> list[Alert]:
    state = State()
    alerts, snap = collect(cfg, state)
    fresh = [a for a in alerts if not state.already_fired(a.key)]
    fresh.sort(key=lambda a: -a.severity)
    for a in fresh:
        if notify_on:
            notify.send(a, cfg)
            state.mark(a.key)
            log_alert(a)
        else:
            print(f"[dry-run] {a.severity} {a.kind}: {a.title}\n    {a.body}")
    if notify_on:
        notify.send_digest(fresh, cfg)
    state.save()
    if not quiet:
        print(f"{datetime.now():%H:%M:%S} {cfg['general']['symbol']} "
              f"${snap.get('price', float('nan')):.2f} "
              f"({'live' if snap.get('live') else 'market closed'}) "
              f"- {len(fresh)} new alert(s)")
    return fresh
