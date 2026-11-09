"""Klien API publik Indodax + utilitas order book.

Tidak memakai API key. Semua request sekuensial dan dibatasi.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://indodax.com"
HISTORY_URL = "https://indodax.com/tradingview/history_v2"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 uas-algoritma-trading/1.0"


class ApiError(Exception):
    def __init__(self, message, url=None, status=None, body=None):
        super().__init__(message)
        self.url = url
        self.status = status
        self.body = body

    def to_dict(self):
        return {"message": str(self), "url": self.url, "status": self.status,
                "body": (self.body or "")[:500]}


class RateLimiter:
    """Jeda minimum antar-request, default 0.4 detik (maks 2.5 req/detik)."""

    def __init__(self, min_interval=0.4):
        self.min_interval = float(min_interval)
        self.last = 0.0
        self.count = 0

    def wait(self):
        now = time.monotonic()
        delta = now - self.last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last = time.monotonic()
        self.count += 1


def http_json(url, timeout=20, retries=3, limiter=None, error_log=None):
    """GET JSON dengan retry terbatas. error_log(dict) dipanggil tiap kegagalan."""
    last_exc = None
    for attempt in range(1, retries + 1):
        if limiter is not None:
            limiter.wait()
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw:
                    raise ApiError("respons kosong", url=url, status=resp.status)
                return json.loads(raw.decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            last_exc = ApiError("HTTP %s" % e.code, url=url, status=e.code, body=body)
            # 4xx selain 429 tidak akan sembuh dengan retry
            if 400 <= e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ApiError) as e:
            last_exc = e if isinstance(e, ApiError) else ApiError(str(e), url=url)
        if error_log:
            error_log({"at": int(time.time()), "url": url, "attempt": attempt,
                       "error": str(last_exc), "status": getattr(last_exc, "status", None)})
        if attempt < retries:
            time.sleep(min(4.0, 1.0 * (2 ** (attempt - 1))))
    if isinstance(last_exc, ApiError):
        raise last_exc
    raise ApiError(str(last_exc or "request gagal"), url=url)


def get_server_time(limiter=None, error_log=None):
    d = http_json(API_BASE + "/api/server_time", limiter=limiter, error_log=error_log)
    return int(d["server_time"]) / 1000.0


def get_pairs(limiter=None, error_log=None):
    data = http_json(API_BASE + "/api/pairs", limiter=limiter, error_log=error_log)
    if isinstance(data, dict):
        data = data.get("pairs") or data.get("data") or []
    return {str(x.get("id") or x.get("symbol", "").lower()): x for x in data}


def get_price_increments(limiter=None, error_log=None):
    d = http_json(API_BASE + "/api/price_increments", limiter=limiter, error_log=error_log)
    return d.get("increments", d if isinstance(d, dict) else {})


def get_depth(pair, limiter=None, error_log=None):
    """Return dict: bid, ask, bids [(price,qty)], asks [(price,qty)] descending/ascending."""
    d = http_json(API_BASE + "/api/depth/" + pair, limiter=limiter, error_log=error_log)
    bids = sorted(((float(p), float(q)) for p, q in d.get("buy", []) if float(q) > 0),
                  key=lambda x: -x[0])
    asks = sorted(((float(p), float(q)) for p, q in d.get("sell", []) if float(q) > 0),
                  key=lambda x: x[0])
    return {
        "pair": pair,
        "bid": bids[0][0] if bids else None,
        "ask": asks[0][0] if asks else None,
        "bids": bids,
        "asks": asks,
        "fetched_at": int(time.time()),
    }


def get_candles(symbol, tf, from_ts, to_ts, limiter=None, error_log=None):
    """Ambil candle history_v2. Return list bar {time,open,high,low,close,volume}."""
    q = urllib.parse.urlencode({"symbol": symbol.upper(), "tf": str(tf),
                                "from": int(from_ts), "to": int(to_ts)})
    data = http_json(HISTORY_URL + "?" + q, limiter=limiter, error_log=error_log)
    if isinstance(data, dict):
        data = data.get("data") or data.get("candles") or []
    bars = []
    for c in data:
        try:
            t = int(c["Time"])
            o, h, l, cl = float(c["Open"]), float(c["High"]), float(c["Low"]), float(c["Close"])
            v = float(c.get("Volume") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        bars.append({"time": t, "open": o, "high": h, "low": l, "close": cl, "volume": v})
    bars.sort(key=lambda x: x["time"])
    # buang duplikat time
    out = []
    for b in bars:
        if out and out[-1]["time"] == b["time"]:
            out[-1] = b
        else:
            out.append(b)
    return out


def closed_bars(bars, tf_seconds, server_time):
    """Buang candle yang belum ditutup: Time + durasi > server_time."""
    return [b for b in bars if int(b["time"]) + int(tf_seconds) <= int(server_time)]


def spread_pct(depth):
    bid, ask = depth.get("bid"), depth.get("ask")
    if not bid or not ask or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return (ask - bid) / mid


def mid_price(depth):
    bid, ask = depth.get("bid"), depth.get("ask")
    if bid and ask:
        return (bid + ask) / 2.0
    return bid or ask


def walk_book_notional(levels, target_notional):
    """Beli: habiskan level ask sampai target notional (IDR) terpenuhi."""
    remaining = float(target_notional)
    qty = 0.0
    notional = 0.0
    used = 0
    for price, available in levels:
        if remaining <= 1e-9:
            break
        take_notional = min(remaining, price * available)
        take_qty = take_notional / price
        qty += take_qty
        notional += take_notional
        remaining -= take_notional
        used += 1
    return {"qty": qty, "notional": notional, "vwap": (notional / qty) if qty else None,
            "complete": remaining <= max(1e-6, target_notional * 1e-9),
            "levels_used": used, "unfilled_notional": max(0.0, remaining)}


def walk_book_qty(levels, target_qty):
    """Jual: habiskan level bid sampai kuantitas base terpenuhi."""
    remaining = float(target_qty)
    qty = 0.0
    notional = 0.0
    used = 0
    for price, available in levels:
        if remaining <= 1e-12:
            break
        take = min(remaining, available)
        qty += take
        notional += take * price
        remaining -= take
        used += 1
    return {"qty": qty, "notional": notional, "vwap": (notional / qty) if qty else None,
            "complete": remaining <= max(1e-12, target_qty * 1e-9),
            "levels_used": used, "unfilled_qty": max(0.0, remaining)}


def validate_bars(bars, tf_seconds, server_time, lookback, max_age_multiple=2):
    """Validasi data sebelum sinyal. Return (ok, reasons, info)."""
    reasons = []
    info = {}
    if not bars:
        return False, ["tidak ada candle"], info
    times = [int(b["time"]) for b in bars]
    if any(times[i] >= times[i + 1] for i in range(len(times) - 1)):
        reasons.append("urutan waktu candle tidak naik")
    last_t = times[-1]
    age = int(server_time) - (last_t + int(tf_seconds))
    info["last_closed_age_seconds"] = age
    if age > int(max_age_multiple) * int(tf_seconds):
        reasons.append("candle tertutup terakhir lebih tua dari %dx timeframe (%s detik)" %
                       (max_age_multiple, age))
    n = max(2, int(lookback))
    window = bars[-n:]
    expected = [last_t - (n - 1 - k) * int(tf_seconds) for k in range(n)]
    have = set(int(b["time"]) for b in window)
    missing = [t for t in expected if t not in have]
    info["missing_candles"] = len(missing)
    if missing:
        reasons.append("ada %d candle hilang di jendela indikator" % len(missing))
    bad = 0
    for b in window:
        if min(b["open"], b["high"], b["low"], b["close"]) <= 0 or b["volume"] < 0:
            bad += 1
    info["invalid_price_volume_bars"] = bad
    if bad:
        reasons.append("%d candle dengan harga/volume nol atau negatif" % bad)
    info["bars"] = len(bars)
    return len(reasons) == 0, reasons, info
