#!/usr/bin/env python3
"""Simpan snapshot order book Indodax (mentah) untuk estimasi spread & slippage.

  python3 scripts/collect_snapshots.py --once
  python3 scripts/collect_snapshots.py --loop --interval 60 --duration 3600

Output: data/snapshots/orderbook_YYYYMMDD_HHMMSS.jsonl
Setiap baris: waktu, pair, best bid/ask, spread, 20 level teratas, dan estimasi
slippage untuk notional acuan (default Rp20.000.000, yaitu 20% modal awal).
"""
import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_json
from core.exchange import RateLimiter, get_depth, get_pairs, get_price_increments, spread_pct, walk_book_notional

SNAP = os.path.join(ROOT, "data", "snapshots")
RUNNING = True


def stop(*_):
    global RUNNING
    RUNNING = False


def collect_once(pairs, limiter, target_notional, out_path, meta):
    rows = 0
    for pair in pairs:
        try:
            d = get_depth(pair, limiter=limiter)
        except Exception as e:
            row = {"ts": int(time.time()), "pair": pair, "error": str(e)}
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, separators=(",", ":")) + "\n")
            continue
        sp = spread_pct(d)
        est = walk_book_notional(d["asks"][:20], target_notional) if d["asks"] else {}
        row = {
            "ts": int(time.time()),
            "at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "pair": pair,
            "bid": d["bid"], "ask": d["ask"], "spread_pct": sp,
            "bids": d["bids"][:20], "asks": d["asks"][:20],
            "target_notional_idr": target_notional,
            "est_fill_vwap_buy": est.get("vwap"),
            "est_complete": est.get("complete"),
            "est_levels_used": est.get("levels_used"),
            "source": "https://indodax.com/api/depth/" + pair,
            "meta": meta,
        }
        with open(out_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        rows += 1
        print("snapshot %-9s bid=%s ask=%s spread=%s" % (
            pair, d["bid"], d["ask"], ("%.4f%%" % (sp * 100)) if sp is not None else "n/a"))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="*", default=None)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=60.0, help="detik antar putaran")
    ap.add_argument("--duration", type=float, default=0, help="detik total; 0 = tanpa batas")
    ap.add_argument("--target-notional", type=float, default=20000000)
    ap.add_argument("--min-interval", type=float, default=0.4)
    a = ap.parse_args()
    pairs = a.pairs or load_json(os.path.join(ROOT, "config", "candidates.json"))["candidates"]
    limiter = RateLimiter(a.min_interval)
    os.makedirs(SNAP, exist_ok=True)
    started = time.time()
    out_path = os.path.join(SNAP, "orderbook_%s.jsonl" % datetime.now(timezone.utc).strftime("%Y%m%d"))
    meta = {"tf_target": "240", "collector": "scripts/collect_snapshots.py",
            "target_notional_idr": a.target_notional}
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    total = 0
    while RUNNING:
        t0 = time.time()
        total += collect_once(pairs, limiter, a.target_notional, out_path, meta)
        if a.once:
            break
        if a.duration and (time.time() - started) >= a.duration:
            break
        sleep = max(1.0, a.interval - (time.time() - t0))
        time.sleep(sleep)
    print("Selesai. %d snapshot -> %s" % (total, out_path))


if __name__ == "__main__":
    main()
