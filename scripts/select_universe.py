#!/usr/bin/env python3
"""Pilih universe 3-10 pair IDR likuid pada AWAL periode backtest.

Kriteria (dihitung pada 60 hari pertama periode, bukan hari ini):
  1. Pair IDR kandidat punya candle pada awal periode (data tersedia).
  2. Coverage candle >= 95% dari yang diharapkan.
  3. Median nilai transaksi harian (close x volume, IDR) tertinggi.
Survivorship bias tidak bisa dihilangkan 100% karena daftar pair historis
tidak disediakan API; keterbatasan dicatat di docs/METHODOLOGY.md.
"""
import csv
import json
import os
import statistics
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_json, save_json, WIB
from core.exchange import RateLimiter, get_pairs, get_price_increments

RAW = os.path.join(ROOT, "data", "raw")


def load_bars(pair, tf):
    path = os.path.join(RAW, "%s_%s.csv" % (pair, tf))
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [{"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                 "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"])}
                for r in csv.DictReader(f)]


def main():
    cfg = load_json(os.path.join(ROOT, "config", "strategy.json"))
    cand = load_json(os.path.join(ROOT, "config", "candidates.json"))["candidates"]
    tf = int(cfg["timeframe"])
    tf_sec = int(cfg["timeframe_seconds"])
    start = datetime.strptime(cfg["backtest"]["start"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(cfg["backtest"]["end"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start_ts, end_ts = int(start.timestamp()), int(end.timestamp())
    window_end = int((start + timedelta(days=int(cfg["backtest"]["liquidity_window_days"]))).timestamp())
    expected = int((window_end - start_ts) / tf_sec)

    limiter = RateLimiter(0.5)
    pairs_meta = get_pairs(limiter=limiter)
    increments = get_price_increments(limiter=limiter)
    save_json(os.path.join(ROOT, "data", "pairs_meta_snapshot.json"), {
        "accessed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "https://indodax.com/api/pairs dan /api/price_increments",
        "pairs": {k: {kk: v.get(kk) for kk in (
            "symbol", "trade_min_base_currency", "trade_fee_percent_taker",
            "trade_fee_percent_maker", "pricescale", "price_precision",
            "quantity_increment", "is_maintenance", "is_market_suspended")}
            for k, v in pairs_meta.items()},
        "increments": increments,
    })

    rows = []
    excluded = set(cfg["backtest"].get("exclude_pairs", []))
    for pair in cand:
        bars = load_bars(pair, tf)
        in_window = [b for b in bars if start_ts <= b["time"] < window_end]
        if pair in excluded:
            rows.append({"pair": pair, "eligible": False,
                         "reason": cfg["backtest"].get("exclude_reason", "dikecualikan")})
            continue
        if not bars or not in_window:
            rows.append({"pair": pair, "eligible": False, "reason": "tidak ada data pada awal periode"})
            continue
        first = bars[0]["time"]
        last = bars[-1]["time"]
        coverage = len(in_window) / float(expected) if expected else 0
        # nilai transaksi harian (WIB)
        by_day = {}
        for b in in_window:
            d = datetime.fromtimestamp(b["time"], WIB).strftime("%Y-%m-%d")
            by_day[d] = by_day.get(d, 0.0) + b["close"] * b["volume"]
        daily = list(by_day.values())
        med = statistics.median(daily) if daily else 0.0
        ok = coverage >= 0.95 and med > 0 and first <= start_ts + tf_sec and last >= end_ts - 5 * tf_sec
        reasons = []
        if coverage < 0.95:
            reasons.append("coverage %.1f%% < 95%%" % (coverage * 100))
        if med <= 0:
            reasons.append("volume nol")
        if first > start_ts + tf_sec:
            reasons.append("data baru mulai %s" % datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%d"))
        if last < end_ts - 5 * tf_sec:
            reasons.append("data berhenti %s" % datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d"))
        meta = pairs_meta.get(pair, {})
        rows.append({
            "pair": pair, "eligible": ok, "reason": "; ".join(reasons) or "ok",
            "median_daily_quote_volume_idr": med, "coverage": coverage,
            "bars_window": len(in_window), "expected_bars_window": expected,
            "first_bar_utc": datetime.fromtimestamp(first, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "last_bar_utc": datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "trade_min_base_currency": meta.get("trade_min_base_currency"),
            "trade_fee_percent_taker_api": meta.get("trade_fee_percent_taker"),
            "pricescale": meta.get("pricescale"),
            "quantity_increment": meta.get("quantity_increment"),
            "is_maintenance": meta.get("is_maintenance"),
        })

    eligible = [r for r in rows if r["eligible"]]
    eligible.sort(key=lambda r: -r["median_daily_quote_volume_idr"])
    n = int(cfg["backtest"]["universe_size"])
    selected = [r["pair"] for r in eligible[:n]]
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "backtest_start": cfg["backtest"]["start"], "backtest_end": cfg["backtest"]["end"],
        "liquidity_window": [cfg["backtest"]["start"], (start + timedelta(days=int(cfg["backtest"]["liquidity_window_days"]))).strftime("%Y-%m-%d")],
        "criteria": cfg["backtest"]["criteria"],
        "candidates": rows, "selected": selected,
        "selection_note": "Peringkat memakai median nilai transaksi harian pada 60 hari pertama. Pair dengan data mulai setelah awal periode atau coverage <95% dikeluarkan.",
    }
    save_json(os.path.join(ROOT, "data", "universe.json"), out)
    cfg["universe"] = selected
    save_json(os.path.join(ROOT, "config", "strategy.json"), cfg)

    print("Kandidat eligible:", len(eligible), "dari", len(rows))
    for r in eligible[:n]:
        print("  %-9s median Rp%15.0f/hari  coverage %.1f%%" %
              (r["pair"], r["median_daily_quote_volume_idr"], r["coverage"] * 100))
    print("Universe terpilih:", ", ".join(selected))
    print("-> data/universe.json ; config/strategy.json diperbarui")


if __name__ == "__main__":
    main()
