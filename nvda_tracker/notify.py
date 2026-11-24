from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.request

from .models import CRITICAL, INFO, OPPORTUNITY, RISK, SEVERITY_NAMES, Alert

_TOAST_PS = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$n = $t.GetElementsByTagName('text')
$n.Item(0).AppendChild($t.CreateTextNode($env:NVDA_TITLE)) | Out-Null
$n.Item(1).AppendChild($t.CreateTextNode($env:NVDA_BODY)) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($t)
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show($toast)
"""

_EMOJI = {OPPORTUNITY: "🟢", RISK: "🔴"}
_NTFY_TAGS = {OPPORTUNITY: "chart_with_upwards_trend", RISK: "warning"}


def _toast(title: str, body: str) -> None:
    enc = base64.b64encode(_TOAST_PS.encode("utf-16-le")).decode()
    env = {**os.environ, "NVDA_TITLE": title, "NVDA_BODY": body}
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
        env=env, check=False, capture_output=True, timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no console flash from pythonw
    )


def _ntfy(topic: str, alert: Alert) -> None:
    # Header values must be latin-1, so keep the emoji out of the title and use tags instead.
    headers = {
        "Title": alert.title.encode("ascii", "ignore").decode(),
        "Priority": {INFO: "2", CRITICAL: "5"}.get(alert.severity, "4"),
        "Tags": _NTFY_TAGS.get(alert.kind, "mag"),
    }
    if alert.url:
        headers["Click"] = alert.url
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=alert.body.encode(), headers=headers)
    urllib.request.urlopen(req, timeout=10).close()


def telegram_api(token: str, method: str, payload: dict | None = None) -> dict:
    """Call the Telegram Bot API. Raises on HTTP/network errors."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _telegram(token: str, chat_id: str, alert: Alert) -> None:
    import html

    text = f"{_EMOJI.get(alert.kind, '🟡')} <b>{html.escape(alert.title)}</b>\n{html.escape(alert.body)}"
    if alert.url:
        text += f'\n<a href="{html.escape(alert.url, quote=True)}">Read more</a>'
    telegram_api(token, "sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": True,
        # INFO alerts arrive silently; warnings and criticals make a sound.
        "disable_notification": alert.severity <= INFO,
    })


def snapshot_md(snap: dict, sym: str) -> str:
    """The 'what's going on with the stock right now' block shown at the top of every alert."""
    if "pct" not in snap:
        return ""
    rv = snap.get("rel_volume")
    if snap.get("live"):
        state = f"live, data as of {snap.get('bar_time', '?')} ({snap.get('data_age_min', 0):.0f} min old)"
    else:
        state = f"market closed, last session {snap.get('session')}"
    rows = [
        f"**{sym} ${snap['price']:.2f} ({snap['pct']:+.1f}% today)** · {state}",
        f"- Volume: {rv:.1f}x normal" if rv else "- Volume: n/a",
        f"- 5-day {snap['ret5d']:+.1f}% · 1-month {snap['ret20d']:+.1f}%",
        f"- {snap['from_high']:.0f}% from 52-week high (${snap['high52']:.2f}); "
        f"52-week low ${snap['low52']:.2f}",
        f"- vs 50-day avg ${snap['ma50']:.2f} ({snap['vs_ma50']:+.1f}%), "
        f"vs 200-day avg ${snap['ma200']:.2f} ({snap['vs_ma200']:+.1f}%)",
        f"- RSI(14): {snap['rsi']:.0f}",
    ]
    top = snap.get("top_news") or []
    if top:
        rows.append("\n**Top headlines**")
        rows += [f"- [{h.title}]({h.link}) ({h.source})" for h in top]
    return "\n".join(rows) + "\n\n---\n\n"


def send_digest(alerts: list[Alert], cfg: dict, snap: dict | None = None) -> None:
    """One GitHub issue per run. GitHub then emails/pushes the repo owner. Needs no extra secrets
    in Actions (GITHUB_TOKEN + GITHUB_REPOSITORY are provided), and is skipped everywhere else."""
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not (alerts and cfg["notify"].get("github_issues") and token and repo):
        return
    top = max(alerts, key=lambda a: a.severity)
    icon = _EMOJI.get(top.kind, "🟡")
    sym = cfg["general"]["symbol"]
    head = f"{sym} ${snap['price']:.2f} ({snap['pct']:+.1f}%): " if snap and "pct" in snap else ""
    title = f"{icon} {head}{top.title}" + (f" (+{len(alerts) - 1} more)" if len(alerts) > 1 else "")
    lines = []
    for a in sorted(alerts, key=lambda a: -a.severity):
        link = f" — [link]({a.url})" if a.url else ""
        lines.append(f"- {_EMOJI.get(a.kind, '🟡')} **[{SEVERITY_NAMES[a.severity]}] {a.title}**\n  {a.body}{link}")
    # Assigning the repo owner is what makes GitHub notify them: a bot-created issue otherwise only
    # notifies people who are watching the repo, and owners are not auto-subscribed.
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER") or repo.split("/")[0]
    body = snapshot_md(snap or {}, sym) + "**Why you're being alerted**\n" + "\n".join(lines)
    payload = json.dumps({"title": title[:250], "body": body, "assignees": [owner],
                          "labels": ["alert", f"sev-{SEVERITY_NAMES[top.severity].lower()}"]}).encode()
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues", data=payload, method="POST",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json", "User-Agent": "nvda-tracker"})
    try:
        urllib.request.urlopen(req, timeout=15).close()
    except Exception as e:
        print(f"  (github issue failed: {e})")


def send(alert: Alert, cfg: dict, snap: dict | None = None) -> None:
    n = cfg["notify"]
    if snap and "pct" in snap:  # put the price in the pop-up so it's useful without opening anything
        alert = Alert(**{**alert.__dict__,
                         "body": f"${snap['price']:.2f} ({snap['pct']:+.1f}% today). {alert.body}"})
    tag = f"[{SEVERITY_NAMES[alert.severity]}]"
    print(f"{_EMOJI.get(alert.kind, '🟡')} {tag} {alert.title}\n    {alert.body}"
          + (f"\n    {alert.url}" if alert.url else ""))
    if n.get("toast"):
        try:
            _toast(f"{_EMOJI.get(alert.kind, '🟡')} {alert.title}", alert.body)
        except Exception as e:
            print(f"  (toast failed: {e})")
    if n.get("telegram_token") and n.get("telegram_chat_id"):
        try:
            _telegram(n["telegram_token"], str(n["telegram_chat_id"]), alert)
        except Exception as e:  # never print the URL: it contains the bot token
            print(f"  (telegram failed: {type(e).__name__})")
    if n.get("ntfy_topic"):
        try:
            _ntfy(n["ntfy_topic"], alert)
        except Exception as e:
            print(f"  (ntfy failed: {e})")
