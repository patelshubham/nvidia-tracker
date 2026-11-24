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


def main() -> None:
    p = argparse.ArgumentParser(prog="nvda_tracker", description="NVIDIA abnormal-activity tracker")
    p.add_argument("command", nargs="?", default="check",
                   choices=["check", "watch", "dry-run", "test-notify", "status"],
                   help="check: run once (use with Task Scheduler). watch: loop forever. "
                        "dry-run: print alerts without notifying or recording them.")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--interval", type=int, default=90,
                   help="watch mode: seconds between checks during market hours")
    p.add_argument("--off-hours-interval", type=int, default=900,
                   help="watch mode: seconds between checks outside market hours (news only matters)")
    a = p.parse_args()
    cfg = config.load(a.config)

    if a.command == "status":
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
