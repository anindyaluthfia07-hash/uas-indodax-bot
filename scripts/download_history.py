#!/usr/bin/env python3
"""Unduh candle historis Indodax secara mundur (pagination).

Contoh:
  python3 scripts/download_history.py --tf 240 --start 2022-08-01 --end 2026-11-08
  python3 scripts/download_history.py --tf 240 --pairs btcidr ethidr --force

API history_v2 mengembalikan bar terakhir sebelum `to` (bukan seluruh from..to).
Karena itu `to` digeser mundur ke bar paling awal yang sudah didapat, berulang.
Request sekuensial, maksimal 2.5/detik.
"""
import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.exchange import RateLimiter, get_candles, get_server_time, closed_bars
from core.config import load_json

RAW = os.path.join(ROOT, "data", "raw")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_existing(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [{"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"])}
                for r in csv.DictReader(f)]


def write_csv(path, bars):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for b in sorted(bars, key=lambda x: x["time"]):
            w.writerow({k: b[k] for k in w.fieldnames})


def download_pair(pair, tf, start_ts, end_ts, server_time, limiter, force=False, max_requests=12):
    path = os.path.join(RAW, "%s_%s.csv" % (pair, tf))
    existing = [] if force else read_existing(path)
    if existing:
        first, last = existing[0]["time"], existing[-1]["time"]
        if first <= start_ts + int(tf) * 60 and last >= end_ts - int(tf) * 60 * 3:
            return existing, {"status": "cached", "requests": 0, "first": first, "last": last}
    collected = {b["time"]: b for b in existing}
    to_ts = int(end_ts)
    requests = 0
    errors = []
    while requests < max_requests:
        try:
            raw = get_candles(pair, tf, start_ts, to_ts, limiter=limiter,
                              error_log=lambda e: errors.append(e))
        except Exception as e:
            errors.append({"error": str(e)})
            break
        requests += 1
        if not raw:
            break
        before = len(collected)
        for b in raw:
            if start_ts <= b["time"] <= end_ts:
                collected[b["time"]] = b
        earliest = min(b["time"] for b in raw)
        if earliest <= start_ts:
            break
        next_to = earliest - 1
        if next_to >= to_ts:
            break
        to_ts = next_to
        if len(collected) == before and requests > 1:
            # tidak ada kemajuan; hentikan agar tidak loop
            break
    bars = sorted(collected.values(), key=lambda x: x["time"])
    # hanya candle tertutup
    bars = closed_bars(bars, int(tf) * 60, server_time)
    write_csv(path, bars)
    return bars, {"status": "ok", "requests": requests, "first": bars[0]["time"] if bars else None,
                  "last": bars[-1]["time"] if bars else None, "errors": errors[:5],
                  "sha256": sha256_file(path) if bars else None}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tf", default="240", help="1,15,30,60,240,1D")
    ap.add_argument("--start", default="2022-08-01", help="tanggal awal (UTC)")
    ap.add_argument("--end", default=None, help="tanggal akhir (UTC), default sekarang")
    ap.add_argument("--pairs", nargs="*", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--min-interval", type=float, default=0.4)
    a = ap.parse_args()

    if a.pairs:
        pairs = a.pairs
    else:
        pairs = load_json(os.path.join(ROOT, "config", "candidates.json"))["candidates"]
    start_dt = datetime.strptime(a.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = (datetime.strptime(a.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              if a.end else datetime.now(timezone.utc))
    start_ts, end_ts = int(start_dt.timestamp()), int(end_dt.timestamp())
    limiter = RateLimiter(a.min_interval)
    server_time = get_server_time(limiter=limiter)
    os.makedirs(RAW, exist_ok=True)
    meta = {
        "source": "Indodax public API history_v2",
        "url_template": "https://indodax.com/tradingview/history_v2?symbol={SYMBOL}&tf={tf}&from={from}&to={to}",
        "downloaded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "requested_start": a.start, "requested_end": a.end or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "start_epoch": start_ts, "end_epoch": end_ts, "server_time": server_time,
        "tf": a.tf, "pairs": {}, "rate_limit": "sequential, min interval %.2fs (<=2.5 req/s)" % a.min_interval,
    }
    print("Server time Indodax:", datetime.fromtimestamp(server_time, timezone.utc).isoformat())
    for i, pair in enumerate(pairs, 1):
        bars, info = download_pair(pair, a.tf, start_ts, end_ts, server_time, limiter, a.force)
        meta["pairs"][pair] = info
        if bars:
            first = datetime.fromtimestamp(bars[0]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
            last = datetime.fromtimestamp(bars[-1]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M")
            print("[%2d/%d] %-9s %5d bar  %s -> %s  req=%s" %
                  (i, len(pairs), pair, len(bars), first, last, info.get("requests")))
        else:
            print("[%2d/%d] %-9s TIDAK ADA DATA" % (i, len(pairs), pair))
    meta["requests_total"] = sum(v.get("requests", 0) for v in meta["pairs"].values())
    with open(os.path.join(RAW, "download_meta_%s.json" % a.tf), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    ok = sum(1 for v in meta["pairs"].values() if v.get("status") == "ok" or v.get("first"))
    print("\nSelesai: %d/%d pair punya data. Total request: %d" % (ok, len(pairs), meta["requests_total"]))
    print("Meta -> data/raw/download_meta_%s.json" % a.tf)


if __name__ == "__main__":
    main()
