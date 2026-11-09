"""GET /api/dashboard - data mentah + metrik yang dihitung ulang dari log."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import BaseHTTPRequestHandler

from core.api_utils import send_json
from core.bot import dashboard_payload
from core.storage import get_storage


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            payload = dashboard_payload(get_storage())
            return send_json(self, 200, payload, {"Access-Control-Allow-Origin": "*"})
        except Exception as e:
            return send_json(self, 500, {"ok": False, "error": "%s: %s" % (type(e).__name__, e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("api/dashboard: " + (fmt % args) + "\n")
