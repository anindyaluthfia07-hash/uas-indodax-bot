"""GET /api/export - ekspor state + seluruh log mentah (butuh CRON_SECRET).

Dipakai scripts/recompute.py untuk menghitung ulang metrik dari sumber mentah
tanpa mempercayai angka yang sudah tersaji di dashboard.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from core.api_utils import send_json, require_secret
from core.config import load_strategy
from core.storage import get_storage

KINDS = ["ticks", "decisions", "orders", "trades", "errors", "equity",
         "daily_equity", "snapshots", "kill_log"]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ok, err = require_secret(self)
        if not ok:
            return send_json(self, 401 if err == "unauthorized" else 503, {"ok": False, "error": err})
        try:
            s = get_storage()
            out = {
                "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "config": load_strategy(),
                "state": s.get_state() or {},
                "kill_switch": s.get_kill(),
                "logs": {k: s.read(k, 0) for k in KINDS},
            }
            return send_json(self, 200, out)
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("api/export: " + (fmt % args) + "\n")
