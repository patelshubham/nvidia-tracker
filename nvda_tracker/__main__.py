from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import config, data, notify, runner
from .state import State
from .models import OPPORTUNITY, Alert, WARN


def _log_to_file_if_headless() -> None:
    """When started hidden by the scheduler (NVDA_HEADLESS=1, or no console at all), nobody can see
    stdout, so write it to data/watch.log instead."""
    if sys.stdout is None or sys.stderr is None or os.environ.get("NVDA_HEADLESS"):
        log = config.ROOT / "data" / "watch.log"
        log.parent.mkdir(exist_ok=True)
        if log.exists() and log.stat().st_size > 2_000_000:  # keep it from growing forever
            log.replace(log.with_suffix(".old"))
        f = open(log, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f


def _telegram_setup(cfg: dict) -> None:
    """Finish Telegram setup: verify the bot token from config.local.toml, find your chat id from the
    message you sent the bot, save it, and send a test. The token never passes through chat."""
    token = cfg["notify"].get("telegram_token", "")
    if not token or "PASTE" in token:
        sys.exit("No bot token yet. Paste it into config.local.toml between the quotes on the "
                 "telegram_token line, then run this again.")
    try:
        me = notify.telegram_api(token, "getMe")["result"]
        updates = notify.telegram_api(token, "getUpdates")["result"]
    except Exception as e:
        sys.exit(f"Telegram rejected the token ({type(e).__name__}). Check you copied all of it.")
    chats = [u["message"]["chat"] for u in updates if "message" in u]
    if not chats:
        sys.exit(f"Token OK (bot @{me['username']}). Now open that bot in Telegram, press Start / "
                 f"send it any message, then run this again.")
    chat_id = str(chats[-1]["id"])
    config.save_local_notify({"telegram_token": token, "telegram_chat_id": chat_id})
    notify.send(Alert(key="tg-test", title="NVDA tracker connected",
                      body="Telegram alerts are on. You'll get messages here when NVDA does "
                           "something unusual.", severity=WARN, kind=OPPORTUNITY),
                {**cfg, "notify": {**cfg["notify"], "toast": False, "ntfy_topic": "",
                                   "telegram_token": token, "telegram_chat_id": chat_id}})
    print(f"Saved. Test message sent to chat {chat_id} via @{me['username']}.")


def main() -> None:
    p = argparse.ArgumentParser(prog="nvda_tracker", description="NVIDIA abnormal-activity tracker")
    p.add_argument("command", nargs="?", default="check",
                   choices=["check", "watch", "dry-run", "test-notify", "status", "telegram-setup"],
                   help="check: run once (use with Task Scheduler). watch: loop forever. "
                        "dry-run: print alerts without notifying or recording them.")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--interval", type=int, default=90,
                   help="watch mode: seconds between checks during market hours")
    p.add_argument("--off-hours-interval", type=int, default=900,
                   help="watch mode: seconds between checks outside market hours (news only matters)")
    a = p.parse_args()
    cfg = config.load(a.config)

    if a.command == "telegram-setup":
        _telegram_setup(cfg)
    elif a.command == "status":
        _, snap = runner.collect(cfg, State())
        print(notify.snapshot_md(snap, cfg["general"]["symbol"]).rstrip("-\n "))
    elif a.command == "test-notify":
        _, snap = runner.collect(cfg, State())
        notify.send(Alert(key="test", title="NVDA tracker test",
                          body="If you can read this, notifications work.",
                          severity=WARN, kind=OPPORTUNITY), cfg)
        notify.send_digest([Alert(key="test", title="NVDA tracker test",
                                  body="If you got this by email, alerts reach you.",
                                  severity=WARN, kind=OPPORTUNITY)], cfg, snap)
    elif a.command == "dry-run":
        runner.run_once(cfg, notify_on=False)
    elif a.command == "watch":
        _log_to_file_if_headless()
        print(f"watching {cfg['general']['symbol']}: every {a.interval}s in market hours, "
              f"every {a.off_hours_interval}s otherwise", flush=True)
        while True:
            try:
                runner.run_once(cfg)
            except Exception as e:  # never let one bad tick (network blip) kill the watcher
                print(f"[error] {type(e).__name__}: {e}")
            sys.stdout.flush()
            time.sleep(a.interval if data.in_session() else a.off_hours_interval)
    else:
        runner.run_once(cfg)


if __name__ == "__main__":
    main()
