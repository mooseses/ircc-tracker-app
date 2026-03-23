"""
app.py — Flask web app for IRCC Application Status Tracker
Run:  python app.py      (serves on http://localhost:5000)
"""

import json
import os
import secrets
from functools import wraps

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, jsonify,
)

from tracker import (
    authenticate, fetch_applications,
    fetch_application_detail, fetch_history_map,
    decode_history_key,
)
from notifier import notify
from scheduler import start_scheduler

# ─── App Setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def _save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "id_token" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─── Province / City maps (from IRCC numeric codes) ──────────────────────────

PROVINCE_MAP = {
    1: "Alberta", 2: "British Columbia", 3: "Manitoba",
    4: "New Brunswick", 5: "Newfoundland and Labrador",
    6: "Ontario", 7: "Nova Scotia", 8: "Prince Edward Island",
    9: "Quebec", 10: "Saskatchewan",
    11: "Northwest Territories", 12: "Nunavut", 13: "Yukon",
}

LOB_MAP = {
    "PV2": "Provincial Nominee Program",
    "FC1": "Family Class (Spouse)",
    "FC2": "Family Class (Parent/Grandparent)",
    "FC3": "Family Class (Other)",
    "EE1": "Express Entry",
    "RR1": "Refugee",
    "TR1": "Temporary Residence",
    "TRV": "Visitor Visa (Temporary Resident Visa)",
    "WP1": "Work Permit",
    "SP1": "Study Permit",
    "CR1": "Citizenship",
}

STATUS_LABELS = {
    "inProgress": "In Progress",
    "approved": "Approved",
    "completed": "Completed",
    "closed": "Closed",
    "refused": "Refused",
    "withdrawn": "Withdrawn",
}

ACTIVITY_ICONS = {
    "eligibility": "📋",
    "medical": "🏥",
    "background": "🔍",
    "biometrics": "🖐️",
}

ACTIVITY_STATUS_CLASSES = {
    "completed": "completed",
    "inProgress": "in-progress",
    "notStarted": "not-started",
}


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if "id_token" in session:
        return redirect(url_for("applications"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    cfg = _load_config()
    saved_accounts = cfg.get("accounts", [])

    if request.method == "POST":
        uci = request.form["uci"].strip()
        password = request.form["password"].strip()
        remember = request.form.get("remember") == "on"

        # Step 1: Authenticate with Cognito
        try:
            auth = authenticate(uci, password)
        except RuntimeError as e:
            flash(str(e), "error")
            return render_template("login.html", accounts=saved_accounts)

        id_token = auth["IdToken"]

        # Step 2: Verify authentication by fetching profile
        try:
            apps = fetch_applications(id_token)
        except Exception:
            apps = []

        if not apps and not id_token:
            flash("Authentication succeeded but could not verify session.", "error")
            return render_template("login.html", accounts=saved_accounts)

        session["id_token"] = id_token
        session["uci"] = uci
        session.permanent = True

        # Step 3: Save account if "Remember account" is checked
        if remember:
            # Add to accounts list (avoid duplicates by UCI)
            existing = [a for a in saved_accounts if a.get("uci") != uci]
            existing.append({"uci": uci, "password": password})
            cfg["accounts"] = existing
            _save_config(cfg)

        return redirect(url_for("applications"))

    return render_template("login.html", accounts=saved_accounts)


@app.route("/login/quick/<uci>", methods=["POST"])
def quick_login(uci):
    """Quick login using a saved account."""
    cfg = _load_config()
    account = next((a for a in cfg.get("accounts", []) if a["uci"] == uci), None)
    if not account:
        flash("Account not found.", "error")
        return redirect(url_for("login"))

    try:
        auth = authenticate(account["uci"], account["password"])
    except RuntimeError as e:
        flash(f"Quick login failed: {e}", "error")
        return redirect(url_for("login"))

    session["id_token"] = auth["IdToken"]
    session["uci"] = account["uci"]
    session.permanent = True
    return redirect(url_for("applications"))


@app.route("/login/remove/<uci>", methods=["POST"])
def remove_account(uci):
    """Remove a saved account."""
    cfg = _load_config()
    cfg["accounts"] = [a for a in cfg.get("accounts", []) if a.get("uci") != uci]
    _save_config(cfg)
    flash("Account removed.", "success")
    return redirect(url_for("login"))


@app.route("/applications")
@login_required
def applications():
    try:
        apps = fetch_applications(session["id_token"])
    except Exception:
        flash("Session expired. Please log in again.", "error")
        session.clear()
        return redirect(url_for("login"))

    if not apps:
        # Token might have expired — try to re-auth using saved credentials
        cfg = _load_config()
        account = next(
            (a for a in cfg.get("accounts", []) if a["uci"] == session.get("uci")),
            None,
        )
        if account:
            try:
                auth = authenticate(account["uci"], account["password"])
                session["id_token"] = auth["IdToken"]
                apps = fetch_applications(session["id_token"])
            except Exception:
                pass

        if not apps:
            flash("No applications found, or session expired. Please log in again.", "error")
            session.clear()
            return redirect(url_for("login"))

    return render_template(
        "applications.html",
        apps=apps,
        lob_map=LOB_MAP,
        status_labels=STATUS_LABELS,
        province_map=PROVINCE_MAP,
    )


@app.route("/application/<app_number>")
@login_required
def application_detail(app_number):
    try:
        # Fetch both in parallel-ish (same thread, but fresh every time)
        data = fetch_application_detail(
            session["id_token"], app_number, session["uci"]
        )
        history_map = fetch_history_map()
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("applications"))

    # Save to tracked apps for scheduler
    cfg = _load_config()
    cfg.setdefault("tracked_apps", {})
    cfg["tracked_apps"][app_number] = data
    _save_config(cfg)

    app_info = data.get("app", {})
    relations = data.get("relations", [])
    rel = relations[0] if relations else {}
    activities = rel.get("activities", {})
    history = rel.get("history", [])

    # Decode history keys and sort by dateCreated descending
    for entry in history:
        entry["decoded"] = decode_history_key(entry.get("key", ""), history_map)

    history.sort(key=lambda x: x.get("dateCreated", ""), reverse=True)

    return render_template(
        "detail.html",
        app_info=app_info,
        rel=rel,
        activities=activities,
        history=history,
        lob_map=LOB_MAP,
        status_labels=STATUS_LABELS,
        province_map=PROVINCE_MAP,
        activity_icons=ACTIVITY_ICONS,
        activity_status_classes=ACTIVITY_STATUS_CLASSES,
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    cfg = _load_config()

    if request.method == "POST":
        notif = cfg.get("notifications", {})

        # Poll interval
        cfg["poll_interval"] = int(request.form.get("poll_interval", 30))

        # Email
        notif["email"] = {
            "enabled": request.form.get("email_enabled") == "on",
            "smtp_host": request.form.get("smtp_host", ""),
            "smtp_port": request.form.get("smtp_port", "587"),
            "smtp_user": request.form.get("smtp_user", ""),
            "smtp_pass": request.form.get("smtp_pass", ""),
            "from_email": request.form.get("from_email", ""),
            "to_email": request.form.get("to_email", ""),
        }

        # Slack
        notif["slack"] = {
            "enabled": request.form.get("slack_enabled") == "on",
            "webhook_url": request.form.get("slack_webhook", ""),
        }

        # Telegram
        notif["telegram"] = {
            "enabled": request.form.get("telegram_enabled") == "on",
            "bot_token": request.form.get("telegram_token", ""),
            "chat_id": request.form.get("telegram_chat_id", ""),
        }

        # Webhook
        notif["webhook"] = {
            "enabled": request.form.get("webhook_enabled") == "on",
            "url": request.form.get("webhook_url", ""),
        }

        cfg["notifications"] = notif
        _save_config(cfg)

        # Restart scheduler with new interval
        start_scheduler(cfg["poll_interval"])

        flash("Settings saved successfully.", "success")
        return redirect(url_for("settings"))

    return render_template("settings.html", cfg=cfg)


@app.route("/api/status/<app_number>")
@login_required
def api_status(app_number):
    """JSON endpoint for live-refresh."""
    try:
        data = fetch_application_detail(
            session["id_token"], app_number, session["uci"]
        )
        history_map = fetch_history_map()
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    relations = data.get("relations", [])
    rel = relations[0] if relations else {}
    for entry in rel.get("history", []):
        entry["decoded"] = decode_history_key(entry.get("key", ""), history_map)

    return jsonify(data)


@app.route("/api/test-notification", methods=["POST"])
@login_required
def test_notification():
    """Send a test notification through all enabled channels."""
    cfg = _load_config()
    notif_settings = cfg.get("notifications", {})
    try:
        notify(
            notif_settings,
            "IRCC Tracker — Test Notification",
            "<p>This is a test notification from your IRCC Tracker.</p>",
        )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = _load_config()
    interval = cfg.get("poll_interval", 30)
    start_scheduler(interval)
    app.run(host="0.0.0.0", port=5001, debug=True)
