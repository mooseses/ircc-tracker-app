# IRCC Tracker App 🍁

A Flask web application for tracking IRCC (Immigration, Refugees and Citizenship Canada) application statuses with real-time updates and multi-channel notifications.

## Features

- **Graphical Interface** — Clean dark glassmorphism UI served on `localhost:5001`
- **Multi-Account Support** — Save and quickly switch between multiple IRCC accounts
- **Application Dashboard** — View all linked applications at a glance with status badges
- **Detailed Status View** — Activities breakdown, decoded history timeline with human-readable labels
- **Auto-Refresh** — Background polling via APScheduler detects status changes automatically
- **Notifications** — Get alerted via Email (SMTP), Slack, Telegram, or custom Webhooks
- **Cross-Platform** — Runs anywhere Python does (macOS, Windows, Linux)

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Then open **http://localhost:5001** in your browser.

## Project Structure

```
ircc-tracker-app/
├── app.py              # Flask server & routes
├── tracker.py          # IRCC API client (Cognito auth, data fetching)
├── notifier.py         # Multi-channel notification system
├── scheduler.py        # Background polling with APScheduler
├── requirements.txt    # Python dependencies
├── config.json         # Local config (auto-generated, gitignored)
└── templates/
    ├── base.html        # Dark glassmorphism layout
    ├── login.html       # Login with multi-account support
    ├── applications.html # Application card grid
    ├── detail.html      # Status details & history timeline
    └── settings.html    # Notification configuration
```

## Screenshots

### Login
Sign in with your UCI/Client ID. Saved accounts appear for quick one-click access.

### Applications
Your linked applications displayed as glass cards with live status badges.

### Detail View
Full activity breakdown and decoded correspondence history timeline.

### Settings
Configure polling interval and notification channels (Email, Slack, Telegram, Webhook).

## Configuration

All settings are stored locally in `config.json` (auto-created, gitignored). This includes:
- Saved account credentials
- Tracked application data
- Notification channel settings
- Polling interval

## Tech Stack

- **Backend:** Python, Flask, APScheduler, Requests
- **Frontend:** HTML, CSS (glassmorphism), vanilla JavaScript
- **Auth:** AWS Cognito (IRCC's authentication provider)
- **APIs:** IRCC Application Status Tracker API

## License

MIT
