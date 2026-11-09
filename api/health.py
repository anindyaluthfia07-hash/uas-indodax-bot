"""GET /api/health - status storage, tick terakhir, kill switch, freeze info."""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from core.api_utils import send_json
from core.config import load_strategy, parse_iso
from core.storage import get_storage


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            cfg = load_strategy()
            storage = get_storage()
            state = storage.get_state() or {}
            ticks = storage.read("ticks", 1)
            last = ticks[-1] if ticks else None
            last_tick = state.get("last_tick")
            age = None
            if last_tick:
                dt = parse_iso(last_tick)
                if dt:
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
            healthy = bool(state.get("last_tick"))
            return send_json(self, 200 if healthy else 503, {
                "ok": healthy,
                "storage": storage.health(),
                "freeze": {"at": cfg.get("frozen_at"), "commit": cfg.get("freeze_commit")},
                "forward_test_start": state.get("forward_test_start"),
                "last_tick": last_tick,
                "last_tick_age_seconds": age,
                "tick_count": state.get("tick_count", 0),
                "kill_switch": storage.get_kill(),
                "daily_loss_blocked": bool(state.get("daily_loss_blocked")),
                "last_tick_summary": last,
                "server_time_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            })
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("api/health: " + (fmt % args) + "\n")
