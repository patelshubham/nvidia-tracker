# NVDA Tracker

Watches NVIDIA for abnormal activity and notifies you (Windows toast, optional phone push via ntfy).
Data: yfinance (free, ~15 min delayed at worst) + Google News RSS. No API keys.

## Run

```powershell
.\.venv\Scripts\python.exe -m nvda_tracker test-notify   # confirm notifications work
.\.venv\Scripts\python.exe -m nvda_tracker dry-run       # show what would alert, record nothing
.\.venv\Scripts\python.exe -m nvda_tracker check         # one real pass
.\.venv\Scripts\python.exe -m nvda_tracker watch         # loop (every 5 min)
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1   # run every 10 min in background
```

## What it detects

| Signal | Trigger (tune in `config.toml`) | Tagged |
|---|---|---|
| Price move | >= 2 std devs vs 60-day daily moves (and >= 2%) | watch |
| Open gap | >= 2.5% vs prev close | watch |
| Volume | >= 1.6x same-time-of-day average (live) or vs 20-day avg (after close) | watch |
| 5-day momentum | +/- 8% | watch |
| RSI | crosses 75 (risk) / 30 (opportunity) | risk / opportunity |
| 52-week high | new high | opportunity |
| 50/200-day MA | price crosses; golden/death cross | opportunity / risk |
| Dip setup | >= 15% off 52w high, RSI <= 40, near 200-day MA | opportunity |
| Relative strength | NVDA vs SMH 1-day gap >= 3 pts | info |
| Earnings | within 3 days | warning |
| News | keyword-scored headlines (export controls, antitrust, upgrades, beats, deals...) and headline bursts | risk / opportunity |

Alerts are de-duplicated (`data/state.json`) and logged to `data/alerts.jsonl`.
The first run seeds seen news without alerting, so you don't get flooded.

## Phone push (optional)

Install the ntfy app, subscribe to a long random topic, set `notify.ntfy_topic` in `config.toml`.
The topic name is the only secret, so don't use something guessable.

## Limits

- Regular-session data only; pre/after-market moves show up once the session opens.
- News scoring is keyword-based, so it can misread sarcasm/context. Treat it as a prompt to go read.
- Not financial advice. Signals flag unusual activity; they don't predict direction.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```
