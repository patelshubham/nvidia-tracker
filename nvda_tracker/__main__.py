from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import config, notify, runner
from .state import State
from .models import OPPORTUNITY, Alert, WARN


def main() -> None:
    p = argparse.ArgumentParser(prog="nvda_tracker", description="NVIDIA abnormal-activity tracker")
    p.add_argument("command", nargs="?", default="check",
                   choices=["check", "watch", "dry-run", "test-notify", "status"],
                   help="check: run once (use with Task Scheduler). watch: loop forever. "
                        "dry-run: print alerts without notifying or recording them.")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--interval", type=int, default=300, help="seconds between checks in watch mode")
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
        while True:
            try:
                runner.run_once(cfg)
            except Exception as e:
                print(f"[error] {e}")
            time.sleep(a.interval)
    else:
        runner.run_once(cfg)


if __name__ == "__main__":
    main()
