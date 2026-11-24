from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config.toml"
LOCAL_PATH = ROOT / "config.local.toml"  # git-ignored: put secrets like ntfy_topic here


def _merge(base: dict, over: dict) -> dict:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def save_local_notify(values: dict[str, str]) -> None:
    """Merge string settings into [notify] of config.local.toml (the git-ignored secrets file)."""
    current: dict = {}
    if LOCAL_PATH.exists():
        with open(LOCAL_PATH, "rb") as f:
            current = tomllib.load(f)
    notify = {**current.get("notify", {}), **values}
    lines = ["[notify]"] + [f'{k} = "{str(v).replace(chr(34), "")}"' for k, v in notify.items()]
    LOCAL_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def load(path: Path | None = None) -> dict:
    """config.toml, overridden by config.local.toml, then env vars (NTFY_TOPIC, NVDA_TOAST=0)."""
    with open(Path(path) if path else DEFAULT_PATH, "rb") as f:
        cfg = tomllib.load(f)
    if path is None and LOCAL_PATH.exists():
        with open(LOCAL_PATH, "rb") as f:
            _merge(cfg, tomllib.load(f))
    if os.environ.get("NTFY_TOPIC"):
        cfg["notify"]["ntfy_topic"] = os.environ["NTFY_TOPIC"]
    if os.environ.get("NVDA_TOAST") == "0":
        cfg["notify"]["toast"] = False
    return cfg
