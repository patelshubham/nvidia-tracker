from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT

STATE_PATH = ROOT / "data" / "state.json"
ALERT_LOG = ROOT / "data" / "alerts.jsonl"
RETAIN_DAYS = 7


class State:
    def __init__(self, path: Path = STATE_PATH):
        self.path = path
        self.fired: dict[str, str] = {}
        self.seen_news: list[str] = []
        self.first_run = True
        if path.exists():
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                self.fired = d.get("fired", {})
                self.seen_news = d.get("seen_news", [])
                self.first_run = False
            except (json.JSONDecodeError, OSError):
                pass

    def already_fired(self, key: str) -> bool:
        return key in self.fired

    def mark(self, key: str) -> None:
        self.fired[key] = datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)
        self.fired = {
            k: v for k, v in self.fired.items() if datetime.fromisoformat(v) > cutoff
        }
        self.seen_news = self.seen_news[-2000:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"fired": self.fired, "seen_news": self.seen_news}, indent=1),
            encoding="utf-8",
        )


def log_alert(alert, path: Path = ALERT_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": datetime.now(timezone.utc).isoformat(), **alert.__dict__}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
