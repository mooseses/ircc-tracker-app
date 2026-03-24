"""
notifier.py — Multi-channel notification system
Supports: Email (SMTP), Slack webhook, Telegram bot, generic webhook, Web Push.
"""

import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests
from py_vapid import Vapid02
from pywebpush import webpush, WebPushException


def send_email(cfg: dict, subject: str, body: str):
    """Send an email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg["from_email"]
    msg["To"] = cfg["to_email"]
    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP(cfg["smtp_host"], int(cfg.get("smtp_port", 587))) as srv:
        srv.starttls()
        srv.login(cfg["smtp_user"], cfg["smtp_pass"])
        srv.sendmail(cfg["from_email"], cfg["to_email"], msg.as_string())


def send_slack(cfg: dict, subject: str, body: str):
    """Post to a Slack incoming webhook."""
    requests.post(
        cfg["webhook_url"],
        json={"text": f"*{subject}*\n{body}"},
        timeout=15,
    )


def send_telegram(cfg: dict, subject: str, body: str):
    """Send a message via Telegram Bot API."""
    plain_body = re.sub(r"<[^>]+>", "", body).strip()
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    resp = requests.post(
        url,
        json={
            "chat_id": cfg["chat_id"],
            "text": f"<b>{subject}</b>\n{plain_body}",
            "parse_mode": "HTML",
        },
        timeout=15,
    )
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result.get('description', resp.text)}")


def send_webhook(cfg: dict, subject: str, body: str):
    """POST to a generic webhook URL."""
    requests.post(
        cfg["url"],
        json={"subject": subject, "body": body},
        timeout=15,
    )


def send_web_push(cfg: dict, subject: str, body: str):
    """Send a Web Push notification to all subscribed browsers."""
    subscriptions = cfg.get("subscriptions", [])
    private_key = cfg.get("private_key", "")
    if not subscriptions or not private_key:
        return

    vapid = Vapid02.from_string(private_key)
    plain_body = re.sub(r"<[^>]+>", "", body).strip()
    payload = json.dumps({"title": subject, "body": plain_body})

    for sub in subscriptions:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": "mailto:noreply@ircc-tracker.local"},
            )
        except WebPushException as e:
            print(f"[notifier] web_push failed: {e}")


CHANNELS = {
    "email": send_email,
    "slack": send_slack,
    "telegram": send_telegram,
    "webhook": send_webhook,
    "web_push": send_web_push,
}


def notify(settings: dict, subject: str, body: str) -> dict:
    """
    Send notifications via all enabled channels.
    `settings` is the full notification config dict from config.json.
    Returns a dict mapping channel name to error string (empty string = success).
    """
    results = {}
    for channel_name, send_fn in CHANNELS.items():
        cfg = settings.get(channel_name, {})
        if not cfg.get("enabled"):
            continue
        try:
            send_fn(cfg, subject, body)
            results[channel_name] = None
        except Exception as e:
            print(f"[notifier] {channel_name} failed: {e}")
            results[channel_name] = str(e)
    return results
