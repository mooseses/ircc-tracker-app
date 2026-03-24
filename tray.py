"""
tray.py — System tray launcher for IRCC Tracker
Double-click to run: starts Flask in the background, shows a tray icon,
and auto-opens the dashboard in the default browser.
"""

import os
import sys
import threading
import webbrowser
import time

from PIL import Image, ImageDraw
import pystray

# ─── Configuration ────────────────────────────────────────────────────────────

HOST = "127.0.0.1"
PORT = 9001
URL = f"http://{HOST}:{PORT}"


def _resource_path(relative: str) -> str:
    """Resolve path for both dev and PyInstaller frozen bundles."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def _create_icon_image() -> Image.Image:
    """Create a simple maple-leaf-red circle icon for the tray."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, size - 4, size - 4], fill=(220, 38, 38))
    # White "I" in the center
    draw.text((size // 2 - 4, size // 2 - 10), "I", fill="white")
    return img


def _start_server():
    """Start Flask + scheduler in this thread (blocks)."""
    # Ensure templates/static are found when frozen
    template_dir = _resource_path("templates")
    static_dir = _resource_path("static")

    from app import app, _load_config
    from scheduler import start_scheduler

    app.template_folder = template_dir
    app.static_folder = static_dir

    cfg = _load_config()
    interval = cfg.get("poll_interval", 30)
    start_scheduler(interval)

    # Use waitress if available, else fall back to Flask dev server
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT, _quiet=True)
    except ImportError:
        app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


def _open_dashboard(icon=None, item=None):
    webbrowser.open(URL)


def _quit(icon, item):
    icon.stop()
    os._exit(0)


def main():
    # Start the server in a background daemon thread
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # Give the server a moment to boot
    time.sleep(1.5)
    _open_dashboard()

    # Build tray icon
    icon = pystray.Icon(
        name="IRCC Tracker",
        icon=_create_icon_image(),
        title="IRCC Tracker",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", _open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        ),
    )
    icon.run()


if __name__ == "__main__":
    main()
