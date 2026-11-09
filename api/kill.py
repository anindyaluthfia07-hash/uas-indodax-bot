"""GET/POST /api/kill - baca atau ubah kill switch (butuh CRON_SECRET).

POST body: {"on": true|false, "note": "alasan"}
Kill switch memblokir entry baru; exit tetap dievaluasi agar posisi bisa ditutup.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from core.api_utils import send_json, require_secret, read_json_body
from core.storage import get_storage


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ok, err = require_secret(self)
        if not ok:
            return send_json(self, 401 if err == "unauthorized" else 503, {"ok": False, "error": err})
        try:
            s = get_storage()
            return send_json(self, 200, {"ok": True, "kill_switch": s.get_kill(),
                                         "log": s.read("kill_log", 50)})
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def do_POST(self):
        ok, err = require_secret(self)
        if not ok:
            return send_json(self, 401 if err == "unauthorized" else 503, {"ok": False, "error": err})
        try:
            body = read_json_body(self)
            if "on" not in body or not isinstance(body["on"], bool):
                return send_json(self, 400, {"ok": False, "error": "body wajib berisi boolean 'on'"})
            s = get_storage()
            on = s.set_kill(body["on"], actor="api", note=str(body.get("note") or "")[:500])
            return send_json(self, 200, {"ok": True, "kill_switch": on})
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("api/kill: " + (fmt % args) + "\n")
