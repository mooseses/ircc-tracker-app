"""
notifier.py — Multi-channel notification system
Supports: Email (SMTP), Slack webhook, Telegram bot, generic webhook.
"""

import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests


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
    url = f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage"
    requests.post(
        url,
        json={
            "chat_id": cfg["chat_id"],
            "text": f"<b>{subject}</b>\n{body}",
            "parse_mode": "HTML",
        },
        timeout=15,
    )


def send_webhook(cfg: dict, subject: str, body: str):
    """POST to a generic webhook URL."""
    requests.post(
        cfg["url"],
        json={"subject": subject, "body": body},
        timeout=15,
    )


CHANNELS = {
    "email": send_email,
    "slack": send_slack,
    "telegram": send_telegram,
    "webhook": send_webhook,
}


def notify(settings: dict, subject: str, body: str):
    """
    Send notifications via all enabled channels.
    `settings` is the full notification config dict from config.json.
    """
    for channel_name, send_fn in CHANNELS.items():
        cfg = settings.get(channel_name, {})
        if not cfg.get("enabled"):
            continue
        try:
            send_fn(cfg, subject, body)
        except Exception as e:
            print(f"[notifier] {channel_name} failed: {e}")
