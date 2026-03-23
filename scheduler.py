"""
scheduler.py — Background polling for status changes using APScheduler.
"""

import json
import os
from apscheduler.schedulers.background import BackgroundScheduler

from tracker import authenticate, fetch_application_detail, fetch_applications
from notifier import notify

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

_scheduler = BackgroundScheduler(daemon=True)


def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def _build_change_body(app_num: str, old: dict, new: dict) -> str:
    """Build an HTML body describing what changed."""
    lines = [f"<p>Application <b>{app_num}</b> has been updated.</p>"]

    old_status = old.get("app", {}).get("status", "unknown")
    new_status = new.get("app", {}).get("status", "unknown")
    if old_status != new_status:
        lines.append(f"<p>Status: {old_status} → <b>{new_status}</b></p>")

    old_acts = (old.get("relations", [{}])[0] if old.get("relations") else {}).get("activities", {})
    new_acts = (new.get("relations", [{}])[0] if new.get("relations") else {}).get("activities", {})
    for key in new_acts:
        if old_acts.get(key) != new_acts.get(key):
            lines.append(f"<p>{key}: {old_acts.get(key, 'N/A')} → <b>{new_acts[key]}</b></p>")

    old_updated = old.get("app", {}).get("lastUpdated", "")
    new_updated = new.get("app", {}).get("lastUpdated", "")
    if old_updated != new_updated:
        lines.append(f"<p>Last updated: <b>{new_updated}</b></p>")

    return "\n".join(lines)


def poll_for_changes():
    """Check all tracked applications for status changes."""
    cfg = _load_config()
    accounts = cfg.get("accounts", [])
    tracked = cfg.get("tracked_apps", {})
    notif_settings = cfg.get("notifications", {})

    if not accounts or not tracked:
        return

    # Use the first saved account for polling
    creds = accounts[0]

    try:
        auth = authenticate(creds["uci"], creds["password"])
        id_token = auth["IdToken"]
    except Exception as e:
        print(f"[scheduler] Auth failed: {e}")
        return

    for app_num, old_data in tracked.items():
        try:
            new_data = fetch_application_detail(id_token, app_num, creds["uci"])
        except Exception as e:
            print(f"[scheduler] Fetch failed for {app_num}: {e}")
            continue

        old_updated = old_data.get("app", {}).get("lastUpdated", "")
        new_updated = new_data.get("app", {}).get("lastUpdated", "")

        if old_updated != new_updated:
            subject = f"IRCC Update: {app_num}"
            body = _build_change_body(app_num, old_data, new_data)
            notify(notif_settings, subject, body)
            tracked[app_num] = new_data

    cfg["tracked_apps"] = tracked
    _save_config(cfg)


def start_scheduler(interval_minutes: int = 30):
    """Start the background polling scheduler."""
    if _scheduler.running:
        return
    _scheduler.add_job(
        poll_for_changes,
        "interval",
        minutes=interval_minutes,
        id="ircc_poll",
        replace_existing=True,
    )
    _scheduler.start()


def stop_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
