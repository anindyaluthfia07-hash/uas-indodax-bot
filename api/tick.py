"""POST/GET /api/tick - jalankan satu siklus bot (dry-run).

Jalur utama penjadwalan adalah GitHub Actions yang menjalankan tick di runner
lalu meng-commit state ke repo. Endpoint ini dipakai bila Upstash dihubungkan
(atau dipanggil manual). Wajib menyertakan CRON_SECRET. Idempotensi candle
mencegah order ganda bila dua penjadwal memanggil pada candle yang sama.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from core.api_utils import send_json, require_secret
from core.bot import run_tick
from core.storage import get_storage


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._run()

    def do_POST(self):
        self._run()

    def _run(self):
        ok, err = require_secret(self)
        if not ok:
            code = 401 if err == "unauthorized" else 503
            return send_json(self, code, {"ok": False, "error": err})
        try:
            storage = get_storage()
            trigger = "vercel_cron" if self.headers.get("x-vercel-cron") else "http"
            if (self.headers.get("User-Agent") or "").lower().startswith("github-actions"):
                trigger = "github_actions"
            summary = run_tick(storage, trigger=trigger)
            status = 200 if summary.get("status") == "ok" else 500
            return send_json(self, status, {"ok": status == 200, "summary": summary})
        except Exception as e:
            return send_json(self, 500, {
                "ok": False, "error": "%s: %s" % (type(e).__name__, e),
                "trace": traceback.format_exc()[-1500:],
            })

    def log_message(self, fmt, *args):
        # Jangan log header (bisa memuat secret).
        sys.stderr.write("api/tick: " + (fmt % args) + "\n")
