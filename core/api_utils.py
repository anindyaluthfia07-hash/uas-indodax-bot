"""Utilitas kecil untuk Vercel Python Functions (stdlib saja)."""
import hmac
import json
import os


def require_secret(handler, env_name="CRON_SECRET"):
    """Cek Authorization: Bearer <secret> atau header x-cron-secret.

    Mengembalikan (ok, pesan_error). Tidak pernah menuliskan nilai secret ke log.
    """
    expected = (os.environ.get(env_name) or "").strip()
    if not expected:
        return False, "%s belum diset di environment" % env_name
    auth = (handler.headers.get("Authorization") or "").strip()
    token = ""
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    if not token:
        token = (handler.headers.get("x-cron-secret") or "").strip()
    if token and hmac.compare_digest(token, expected):
        return True, None
    return False, "unauthorized"


def read_json_body(handler, max_bytes=65536):
    try:
        n = int(handler.headers.get("Content-Length") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        return {}
    if n > max_bytes:
        raise ValueError("body terlalu besar")
    raw = handler.rfile.read(n)
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError("body harus objek JSON")
    return data


def send_json(handler, status, obj, extra_headers=None):
    body = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, max-age=0")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    for k, v in (extra_headers or {}).items():
        handler.send_header(k, v)
    handler.end_headers()
    handler.wfile.write(body)


def client_ip(handler):
    fwd = (handler.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    return fwd or handler.client_address[0]
