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
    authenticate, refresh_id_token, fetch_applications,
    fetch_application_detail, fetch_history_map,
    decode_history_key,
)
from notifier import notify, send_web_push
from scheduler import start_scheduler

# ─── App Setup ────────────────────────────────────────────────────────────────

app = Flask(__name__)

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


def _get_or_create_secret_key() -> str:
    """Load the Flask secret key from config, generating one if absent."""
    cfg = _load_config()
    if "flask_secret_key" not in cfg:
        cfg["flask_secret_key"] = secrets.token_hex(32)
        _save_config(cfg)
    return cfg["flask_secret_key"]


app.secret_key = _get_or_create_secret_key()


def _ensure_vapid_keys() -> tuple:
    """Return (private_key_b64url, public_key_b64url), generating and saving if absent."""
    import base64
    from py_vapid import Vapid
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    cfg = _load_config()
    if "vapid" in cfg:
        priv = cfg["vapid"]["private_key"]
        pub  = cfg["vapid"]["public_key"]
        # Migrate old PEM format → raw base64url expected by pywebpush 2.x
        if priv.strip().startswith("-----"):
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            key = load_pem_private_key(priv.encode(), password=None)
            raw = key.private_numbers().private_value.to_bytes(32, "big")
            priv = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            cfg["vapid"]["private_key"] = priv
            _save_config(cfg)
        return priv, pub

    v = Vapid()
    v.generate_keys()
    raw_priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    private_key = base64.urlsafe_b64encode(raw_priv).rstrip(b"=").decode()
    raw_pub = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    public_key = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
    cfg["vapid"] = {"private_key": private_key, "public_key": public_key}
    _save_config(cfg)
    return private_key, public_key


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


ACT_STATUS_LABELS = {
    17: "Started",
    33: "Completed",
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
            # Save refresh token (not the password) so we never store credentials in plaintext
            existing = [a for a in saved_accounts if a.get("uci") != uci]
            existing.append({"uci": uci, "refresh_token": auth["RefreshToken"]})
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
        auth = refresh_id_token(account["refresh_token"])
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
        flash("No applications found, or session expired. Please log in again.", "error")
        session.clear()
        return redirect(url_for("login"))

    cfg = _load_config()
    tracked_app_nums = set(cfg.get("tracked_apps", {}).keys())
    from datetime import date
    today = date.today().isoformat()
    return render_template(
        "applications.html",
        apps=apps,
        tracked_app_nums=tracked_app_nums,
        lob_map=LOB_MAP,
        status_labels=STATUS_LABELS,
        province_map=PROVINCE_MAP,
        today=today,
    )


@app.route("/application/<app_number>")
@login_required
def application_detail(app_number):
    try:
        data = fetch_application_detail(
            session["id_token"], app_number, session["uci"]
        )
        history_map = fetch_history_map()
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("applications"))

    cfg = _load_config()
    is_tracked = app_number in cfg.get("tracked_apps", {})

    app_info = data.get("app", {})
    relations = data.get("relations", [])
    rel = relations[0] if relations else {}
    activities = rel.get("activities", {})
    history = rel.get("history", [])

    # Separate status entries (have actStatus) from regular history
    status_entries = []
    regular_history = []
    for entry in history:
        entry["decoded"] = decode_history_key(entry.get("key", ""), history_map)
        if "actStatus" in entry:
            entry["status_label"] = ACT_STATUS_LABELS.get(entry["actStatus"], f"Status {entry['actStatus']}")
            status_entries.append(entry)
        else:
            regular_history.append(entry)

    status_entries.sort(key=lambda x: x.get("dateCreated", ""), reverse=True)
    regular_history.sort(key=lambda x: x.get("dateCreated", ""), reverse=True)

    return render_template(
        "detail.html",
        app_info=app_info,
        rel=rel,
        activities=activities,
        history=regular_history,
        status_entries=status_entries,
        is_tracked=is_tracked,
        lob_map=LOB_MAP,
        status_labels=STATUS_LABELS,
        province_map=PROVINCE_MAP,
        activity_status_classes=ACTIVITY_STATUS_CLASSES,
    )


@app.route("/application/<app_number>/track", methods=["POST"])
@login_required
def toggle_track(app_number):
    """Toggle tracking on/off for a specific application."""
    cfg = _load_config()
    tracked = cfg.setdefault("tracked_apps", {})
    if app_number in tracked:
        del tracked[app_number]
        cfg["tracked_apps"] = tracked
        _save_config(cfg)
        return jsonify({"tracking": False})
    # Start tracking: fetch and store initial snapshot for change detection
    try:
        data = fetch_application_detail(session["id_token"], app_number, session["uci"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    tracked[app_number] = data
    cfg["tracked_apps"] = tracked
    _save_config(cfg)
    return jsonify({"tracking": True})


@app.route("/push/vapid-public-key")
@login_required
def vapid_public_key():
    _, pub = _ensure_vapid_keys()
    return jsonify({"public_key": pub})


@app.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    sub = request.get_json()
    if not sub or "endpoint" not in sub:
        return jsonify({"error": "invalid subscription"}), 400
    cfg = _load_config()
    subs = cfg.setdefault("push_subscriptions", [])
    if not any(s.get("endpoint") == sub["endpoint"] for s in subs):
        subs.append(sub)
        _save_config(cfg)
    return jsonify({"ok": True})


@app.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint")
    cfg = _load_config()
    subs = cfg.get("push_subscriptions", [])
    if endpoint:
        cfg["push_subscriptions"] = [s for s in subs if s.get("endpoint") != endpoint]
    else:
        cfg["push_subscriptions"] = []
    _save_config(cfg)
    return jsonify({"ok": True})


@app.route("/api/test-push", methods=["POST"])
@login_required
def test_push():
    """Send a test browser push notification only."""
    cfg = _load_config()
    subs = cfg.get("push_subscriptions", [])
    if not subs:
        return jsonify({"ok": False, "error": "No browser subscriptions found. Enable browser notifications first."}), 400
    private_key, _ = _ensure_vapid_keys()
    web_push_cfg = {
        "enabled": True,
        "subscriptions": subs,
        "private_key": private_key,
    }
    try:
        send_web_push(web_push_cfg, "IRCC Tracker \u2014 Test", "Browser push notifications are working!")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
    # Include web push subscriptions in the test
    notif_settings["web_push"] = {
        "enabled": bool(cfg.get("push_subscriptions")),
        "subscriptions": cfg.get("push_subscriptions", []),
        "private_key": cfg.get("vapid", {}).get("private_key", ""),
    }
    results = notify(
        notif_settings,
        "IRCC Tracker — Test Notification",
        "<p>This is a test notification from your IRCC Tracker.</p>",
    )
    if not results:
        return jsonify({"ok": False, "error": "No notification channels are enabled."}), 400
    failures = {ch: err for ch, err in results.items() if err is not None}
    if failures:
        # Build a readable error summary
        msg = "; ".join(f"{ch}: {err}" for ch, err in failures.items())
        return jsonify({"ok": False, "error": msg}), 500
    return jsonify({"ok": True})


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Start ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cfg = _load_config()
    interval = cfg.get("poll_interval", 30)
    start_scheduler(interval)
    app.run(host="0.0.0.0", port=9001, debug=True)
