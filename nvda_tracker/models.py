from __future__ import annotations

from dataclasses import dataclass

INFO, WARN, CRITICAL = 1, 2, 3
SEVERITY_NAMES = {INFO: "INFO", WARN: "WARNING", CRITICAL: "CRITICAL"}

# kind: what the alert means for you
OPPORTUNITY = "opportunity"
RISK = "risk"
WATCH = "watch"


@dataclass
class Alert:
    key: str          # unique per event; used for de-duplication
    title: str
    body: str
    severity: int = WARN
    kind: str = WATCH
    url: str = ""
    # True for alerts about what the price/volume is doing *right now*. These are only useful
    # while the market is open; after the close they are just a late recap, so they're dropped.
    intraday: bool = False
