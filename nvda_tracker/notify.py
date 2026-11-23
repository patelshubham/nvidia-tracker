from __future__ import annotations

import base64
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


def send(alert: Alert, cfg: dict) -> None:
    n = cfg["notify"]
    tag = f"[{SEVERITY_NAMES[alert.severity]}]"
    print(f"{_EMOJI.get(alert.kind, '🟡')} {tag} {alert.title}\n    {alert.body}"
          + (f"\n    {alert.url}" if alert.url else ""))
    if n.get("toast"):
        try:
            _toast(f"{_EMOJI.get(alert.kind, '🟡')} {alert.title}", alert.body)
        except Exception as e:
            print(f"  (toast failed: {e})")
    if n.get("ntfy_topic"):
        try:
            _ntfy(n["ntfy_topic"], alert)
        except Exception as e:
            print(f"  (ntfy failed: {e})")
