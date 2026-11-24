# NVDA Tracker

Watches NVIDIA for abnormal activity and notifies you (Windows toast, optional phone push via ntfy).
Data: yfinance (free, ~15 min delayed at worst) + Google News RSS. No API keys.

## Run

The watcher runs on this PC: every 90 s during US market hours, every 15 min otherwise, and pops up
a Windows notification. It starts hidden at every logon.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1            # install + start
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1 -Remove    # stop + uninstall
Get-Content data\watch.log -Tail 20                                          # what it's doing
.\.venv\Scripts\python.exe -m nvda_tracker status        # price/volume/trend snapshot now
.\.venv\Scripts\python.exe -m nvda_tracker test-notify   # confirm the pop-up works
.\.venv\Scripts\python.exe -m nvda_tracker dry-run       # show what would alert, record nothing
```

If the PC is asleep or off, nothing is checked. The GitHub Actions workflow is manual-only: its cron
schedule was far too unreliable for timely alerts (it ran 2 of ~140 expected times in a day).

After the market closes, "right now" alerts (price move, volume) are suppressed because they would
only be a late recap; daily-signal and news alerts still go out.

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
