"""News monitor: Google News RSS + keyword impact scoring."""
from __future__ import annotations

import hashlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .models import CRITICAL, OPPORTUNITY, RISK, WARN, WATCH, Alert

# (regex, weight). Negative = bearish, positive = bullish. |weight| drives severity.
KEYWORDS: list[tuple[str, int]] = [
    (r"export (ban|control|restriction|curb|licen[cs]e)s?", -4),
    (r"\b(antitrust|subpoena|doj|ftc|sec probe|investigation|probe)\b", -4),
    (r"\b(short[- ]seller|short report)\b", -2),
    (r"\bdowngrad(e|es|ed)\b", -2),
    (r"\b(ban|banned|blocks?|blocked|sanctions?)\b", -2),
    (r"\b(delay|delays|delayed|overheat\w*|defect\w*|recall)\b", -2),
    (r"\b(tariffs?)\b", -1),
    (r"\b(lawsuit|sued|sues)\b", -1),
    (r"\b(plunge[sd]?|tumble[sd]?|sink[s]?|crash\w*|selloff|sell-off)\b", -2),
    (r"\bupgrad(e|es|ed)\b", 2),
    (r"(raises?|raised|hikes?|lifts?) (its )?(price )?target", 2),
    (r"\b(beats?|tops?|smash(es)?) (estimates|expectations|forecasts)\b", 3),
    (r"record (revenue|sales|quarter|earnings|high)", 2),
    (r"\b(surge[sd]?|soar[s]?|rall(y|ies|ied)|jump[s]?)\b", 2),
    (r"\b(partnership|partners? with|strategic deal|multi-?billion|\$\d+(\.\d+)? ?billion (deal|order|contract|investment))\b", 2),
    (r"\b(acquires?|acquisition|buyback|stock split|dividend)\b", 2),
    (r"\b(guidance|outlook)\b", 1),
    (r"\bearnings\b", 1),
]
COMPILED = [(re.compile(p, re.I), w) for p, w in KEYWORDS]


@dataclass
class Headline:
    title: str
    source: str
    link: str
    published: datetime

    @property
    def uid(self) -> str:
        norm = re.sub(r"\W+", " ", self.title.lower()).strip()
        return hashlib.sha1(norm.encode()).hexdigest()[:16]


def score(title: str) -> tuple[int, list[str]]:
    """Return (signed score, matched phrases). Net sign = direction; sum of |w| = impact."""
    net, hits = 0, []
    for rx, w in COMPILED:
        m = rx.search(title)
        if m:
            net += w
            hits.append(m.group(0).lower())
    return net, hits


def impact(title: str) -> int:
    return sum(abs(w) for rx, w in COMPILED if rx.search(title))


def fetch(query: str = "NVIDIA OR NVDA", timeout: int = 15) -> list[Headline]:
    url = ("https://news.google.com/rss/search?q="
           + urllib.parse.quote(f"{query} when:1d") + "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        source = src_el.text if src_el is not None else ""
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3]
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate"))
        except (TypeError, ValueError):
            continue
        out.append(Headline(title, source, (it.findtext("link") or "").strip(), pub))
    return out


def fetch_yahoo(sym: str = "NVDA") -> list[Headline]:
    """Yahoo Finance headlines via yfinance. Works from cloud runners where Google News 429s."""
    import yfinance as yf

    out = []
    for item in yf.Ticker(sym).news or []:
        c = item.get("content") or {}
        title = (c.get("title") or "").strip()
        try:
            pub = datetime.fromisoformat((c.get("pubDate") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if not title:
            continue
        link = ((c.get("canonicalUrl") or {}).get("url")
                or (c.get("clickThroughUrl") or {}).get("url") or "")
        out.append(Headline(title, (c.get("provider") or {}).get("displayName", "Yahoo Finance"),
                            link, pub))
    return out


def fetch_all(sym: str = "NVDA") -> list[Headline]:
    """Merge every source that works; only raise if all of them fail."""
    results, errors = [], []
    for name, fn in (("google", fetch), ("yahoo", lambda: fetch_yahoo(sym))):
        try:
            results.extend(fn())
        except Exception as e:  # one blocked source must not hide the other
            errors.append(f"{name}: {e}")
    if not results and errors:
        raise RuntimeError("all news sources failed: " + "; ".join(errors))
    seen, merged = set(), []
    for h in results:  # same story from two sources -> keep once
        if h.uid not in seen:
            seen.add(h.uid)
            merged.append(h)
    return merged


def detect_news(headlines: list[Headline], seen: set[str], cfg: dict, sym: str,
                now: datetime | None = None, first_run: bool = False) -> tuple[list[Alert], set[str]]:
    """Return (alerts, uids to mark seen). On first run, nothing alerts (avoids flooding)."""
    c = cfg["news"]
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=c["max_age_hours"])
    new = [h for h in headlines if h.published >= cutoff and h.uid not in seen]
    new_ids = {h.uid for h in headlines}
    if first_run:
        return [], new_ids

    alerts: list[Alert] = []
    for h in new:
        net, hits = score(h.title)
        imp = impact(h.title)
        if imp < c["warn_score"]:
            continue
        sev = CRITICAL if imp >= c["critical_score"] else WARN
        kind = RISK if net < 0 else OPPORTUNITY if net > 0 else WATCH
        alerts.append(Alert(
            key=f"news:{h.uid}", severity=sev, kind=kind, url=h.link,
            title=f"{sym} news: {h.title[:110]}",
            body=f"{h.source}. Matched: {', '.join(hits)}.",
        ))

    if len(new) >= c["burst_count"]:
        alerts.append(Alert(
            key=f"newsburst:{now:%Y%m%d%H}", severity=WARN,
            title=f"{sym}: {len(new)} new headlines in {c['max_age_hours']}h",
            body="Unusual media attention. Latest: " + "; ".join(h.title[:70] for h in new[:3]),
        ))
    return alerts, new_ids
