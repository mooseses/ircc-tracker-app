"""
serve.py — Production entrypoint for Docker / waitress.
Starts the scheduler then serves via waitress.
"""

from app import app, _load_config
from scheduler import start_scheduler
from waitress import serve

cfg = _load_config()
start_scheduler(cfg.get("poll_interval", 30))
serve(app, host="0.0.0.0", port=9001)
