#!/usr/bin/env python3
"""Bandingkan sinyal backtest dan bot forward pada jendela waktu yang sama.

Rubrik UAS meminta backtest dijalankan ulang pada jendela forward test memakai
candle yang sama, lalu sinyal masuk/keluar dibandingkan candle demi candle.
Skrip ini melakukan itu memakai fungsi sinyal yang sama (`core/strategy.py`).

Yang dibandingkan:
  - sinyal masuk (breakout, EMA, volume/ADV) per pair per candle;
  - candle yang diproses bot vs candle yang seharusnya ada;
  - trade backtest pada jendela itu vs trade forward (bila ada).

Candle live diambil dari API publik Indodax dan disimpan ke
`data/forward/<pair>_240.csv` supaya hasilnya bisa dihitung ulang. Data mentah
sebelum freeze tidak diubah.

Contoh:
  python3 scripts/forward_vs_backtest.py
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.backtest_engine import run_backtest
from core.config import load_json, load_strategy, parse_iso, save_json
from core.exchange import (RateLimiter, closed_bars, get_candles, get_server_time)
from core.storage import LocalStorage
from core.strategy import StrategyEngine, entry_reasons

TF = 14400
FORWARD_DIR = os.path.join(ROOT, "data", "forward")
RAW_DIR = os.path.join(ROOT, "data", "raw")


def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_csv(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append({"time": int(r["time"]), "open": float(r["open"]), "high": float(r["high"]),
                        "low": float(r["low"]), "close": float(r["close"]), "volume": float(r["volume"])})
    return out


def write_csv(path, bars):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["time", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for b in sorted(bars, key=lambda x: x["time"]):
            w.writerow({k: b[k] for k in w.fieldnames})


def merge_bars(old, new):
    by_time = {int(b["time"]): b for b in old}
    for b in new:
        by_time[int(b["time"])] = b
    return [by_time[t] for t in sorted(by_time)]


def first_expected_open(start_ts, tf):
    """Candle pertama yang ditutup setelah forward_start."""
    t = int(start_ts // tf * tf)
    while t + tf <= start_ts:
        t += tf
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--storage-dir", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "forward_vs_backtest.json"))
    ap.add_argument("--signals-out", default=os.path.join(ROOT, "data", "forward_signals.csv"))
    a = ap.parse_args()

    cfg = load_strategy()
    costs = load_json(os.path.join(ROOT, "data", "costs.json"))
    meta = (load_json(os.path.join(ROOT, "data", "pairs_meta_snapshot.json"), default={}) or {}).get("pairs", {})
    storage = LocalStorage(a.storage_dir)
    state = storage.get_state() or {}
    start_iso = state.get("forward_test_start")
    if not start_iso:
        raise SystemExit("forward_test_start belum ada; jalankan bot dulu.")

    start_ts = int(parse_iso(start_iso).timestamp())
    first_open = first_expected_open(start_ts, TF)
    limiter = RateLimiter(0.4)
    server_time = get_server_time(limiter=limiter)
    last_open = int(server_time // TF * TF) - TF

    data, fetch_meta = {}, {}
    for pair in cfg["universe"]:
        old = read_csv(os.path.join(RAW_DIR, "%s_240.csv" % pair))
        symbol = pair.upper()
        try:
            since = max(0, (old[-1]["time"] if old else first_open) - 300 * TF)
            fresh = get_candles(symbol, 240, since, int(server_time), limiter=limiter)
            fetch_meta[pair] = {"requests": 1, "bars": len(fresh), "ok": True}
        except Exception as e:
            fresh = []
            fetch_meta[pair] = {"requests": 1, "bars": 0, "ok": False, "error": str(e)}
        bars = merge_bars(old, fresh)
        bars = closed_bars(bars, TF, server_time)
        bars = [b for b in bars if b["time"] <= last_open]
        data[pair] = bars
        # simpan hanya jendela + warm-up 300 bar agar bisa diaudit tanpa
        # menimpa data mentah yang sudah dipakai backtest 4 tahun
        keep = [b for b in bars if b["time"] >= first_open - 300 * TF]
        write_csv(os.path.join(FORWARD_DIR, "%s_240.csv" % pair), keep)

    decisions = storage.read("decisions", 0)
    forward_trades = storage.read("trades", 0)
    forward_orders = storage.read("orders", 0)
    dec_by = {}
    for d in decisions:
        if d.get("pair") and d.get("candle_time") is not None:
            dec_by[(d["pair"], int(d["candle_time"]))] = d

    expected = list(range(first_open, last_open + 1, TF))
    rows, per_pair = [], {}
    total_match = total_checked = total_processed = 0
    total_comp_checks = total_comp_match = 0
    for pair in cfg["universe"]:
        bars = data.get(pair) or []
        if len(bars) < 150:
            per_pair[pair] = {"error": "data tidak cukup", "expected": len(expected)}
            continue
        engine = StrategyEngine(bars, cfg["params"])
        idx = {int(b["time"]): i for i, b in enumerate(bars)}
        stats = {"expected": len(expected), "processed": 0, "signal_match": 0,
                 "signal_mismatch": 0, "missing": 0, "invalid": 0,
                 "mismatch_samples": []}
        for t in expected:
            i = idx.get(t)
            if i is None:
                stats["missing"] += 1
                rows.append({"pair": pair, "candle_time": t, "candle_iso": iso(t),
                             "expected": 1, "processed": 0, "missing": 1,
                             "bt_entry_signal": "", "bt_components": "",
                             "fwd_entry_signal": "", "fwd_components": "", "match": ""})
                continue
            bt_entry = bool(engine.entry_signal(i))
            bt_comp = entry_reasons(engine, i)
            d = dec_by.get((pair, t))
            if not d:
                stats["missing"] += 1
                rows.append({"pair": pair, "candle_time": t, "candle_iso": iso(t),
                             "expected": 1, "processed": 0, "missing": 1,
                             "bt_entry_signal": int(bt_entry),
                             "bt_components": json.dumps(bt_comp, separators=(",", ":")),
                             "fwd_entry_signal": "", "fwd_components": "", "match": ""})
                continue
            total_processed += 1
            stats["processed"] += 1
            if not d.get("data_valid", True):
                stats["invalid"] += 1
            sig = d.get("signal") or {}
            fwd_entry = sig.get("entry_signal")
            fwd_comp = d.get("entry_components") or {}
            if fwd_entry is None:
                # keputusan tanpa sinyal (mis. data invalid) tidak dihitung cocok
                match = ""
            else:
                total_checked += 1
                comp_keys = sorted(set(bt_comp) | set(fwd_comp))
                total_comp_checks += len(comp_keys)
                total_comp_match += sum(1 for k in comp_keys if bt_comp.get(k) == fwd_comp.get(k))
                match = bool(fwd_entry) == bt_entry and fwd_comp == bt_comp
                if match:
                    total_match += 1
                    stats["signal_match"] += 1
                else:
                    stats["signal_mismatch"] += 1
                    if len(stats["mismatch_samples"]) < 10:
                        stats["mismatch_samples"].append({
                            "candle": iso(t), "bt_entry": bt_entry, "fwd_entry": fwd_entry,
                            "bt_components": bt_comp, "fwd_components": fwd_comp,
                        })
            rows.append({"pair": pair, "candle_time": t, "candle_iso": iso(t),
                         "expected": 1, "processed": 1, "missing": 0,
                         "bt_entry_signal": int(bt_entry),
                         "bt_components": json.dumps(bt_comp, separators=(",", ":")),
                         "fwd_entry_signal": "" if fwd_entry is None else int(bool(fwd_entry)),
                         "fwd_components": json.dumps(fwd_comp, separators=(",", ":")),
                         "match": "" if match == "" else int(bool(match))})
        stats["uptime"] = (stats["processed"] / stats["expected"]) if stats["expected"] else None
        stats["signal_match_rate"] = ((stats["signal_match"] / (stats["signal_match"] + stats["signal_mismatch"]))
                                      if (stats["signal_match"] + stats["signal_mismatch"]) else None)
        per_pair[pair] = stats

    # Backtest pada jendela yang sama (warm-up tetap dari data penuh).
    bt_window = {}
    try:
        r = run_backtest(data, cfg, costs, first_open, last_open,
                         params=cfg["params"], collect_orders=True, pairs_meta=meta,
                         with_benchmark=True)
        bt_window = {
            "start": iso(first_open), "end": iso(last_open),
            "metrics": r["metrics"],
            "trades": r["trades"],
            "open_positions": r["open_positions"],
            "orders": r.get("orders", []),
            "decision_counts": r.get("decision_counts"),
            "skipped": r.get("skipped"),
            "benchmark": {"pair": (r.get("benchmark") or {}).get("pair"),
                          "metrics": (r.get("benchmark") or {}).get("metrics")},
        }
    except Exception as e:
        bt_window = {"error": "%s: %s" % (type(e).__name__, e)}

    # Trade forward pada jendela (biasanya kosong; jangan diisi manual).
    fwd_window_trades = [t for t in forward_trades
                         if t.get("entry_time") and parse_iso(t["entry_time"]).timestamp() >= first_open]
    checked = total_match + sum((per_pair[p].get("signal_mismatch") or 0) for p in per_pair)
    out = {
        "generated_at": iso(datetime.now(timezone.utc).timestamp()),
        "definition": ("Backtest dijalankan ulang pada jendela forward memakai candle 4 jam yang sama. "
                       "Sinyal masuk dibandingkan candle demi candle. Candle yang tidak diproses bot "
                       "dihitung missing, bukan mismatch."),
        "storage": storage.name,
        "forward_start": start_iso,
        "window": {"first_candle": iso(first_open), "last_candle": iso(last_open),
                   "candles_per_pair": len(expected), "pairs": len(cfg["universe"]),
                   "expected_pair_candles": len(expected) * len(cfg["universe"])},
        "server_time": server_time,
        "fetch": fetch_meta,
        "summary": {
            "expected_pair_candles": len(expected) * len(cfg["universe"]),
            "processed_pair_candles": total_processed,
            "signal_checked": checked,
            "signal_match": total_match,
            "signal_mismatch": checked - total_match,
            "signal_match_rate": (total_match / checked) if checked else None,
            "component_checks": total_comp_checks,
            "component_match": total_comp_match,
            "component_match_rate": (total_comp_match / total_comp_checks) if total_comp_checks else None,
            "coverage_rate": (total_processed / (len(expected) * len(cfg["universe"])))
                             if expected and cfg["universe"] else None,
        },
        "per_pair": per_pair,
        "backtest_window": bt_window,
        "forward_window": {
            "trades": fwd_window_trades,
            "trade_count": len(fwd_window_trades),
            "orders": forward_orders,
            "note": "Trade forward hanya yang benar-benar tercatat di log; tidak ada trade rekaan.",
        },
        "gap_explanation": {
            "signal": ("Bila match rate < 100%, selisih berasal dari candle yang hilang/terlambat "
                       "atau perbedaan window data indikator. Contoh mismatch ada di per_pair."),
            "fill": ("Tidak ada trade pada jendela ini, sehingga selisih fill tidak dapat diukur. "
                     "Bila ada trade, selisih dihitung dari fill bid/ask vs open candle backtest."
                     if not fwd_window_trades else
                     "Selisih fill per trade dihitung dari fill order book forward vs open candle backtest."),
        },
    }
    save_json(a.out, out)
    with open(a.signals_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["pair"])
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print("Jendela       : %s -> %s (%d candle/pair)" % (iso(first_open), iso(last_open), len(expected)))
    print("Coverage      : %d/%d pair-candle (%.1f%%)" % (
        total_processed, len(expected) * len(cfg["universe"]),
        (total_processed / (len(expected) * len(cfg["universe"])) * 100) if expected else 0))
    print("Sinyal cocok  : %d/%d (%.1f%%)" % (
        total_match, checked, (total_match / checked * 100) if checked else 0))
    print("Komponen      : %d/%d identik (%.1f%%)" % (
        total_comp_match, total_comp_checks,
        (total_comp_match / total_comp_checks * 100) if total_comp_checks else 0))
    print("Backtest window: return %.2f%%, trade %d" % (
        (bt_window.get("metrics") or {}).get("total_return_pct") or 0,
        len(bt_window.get("trades") or [])))
    print("Forward window : return tercatat %d trade" % len(fwd_window_trades))
    print("-> %s" % a.out)
    print("-> %s" % a.signals_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
