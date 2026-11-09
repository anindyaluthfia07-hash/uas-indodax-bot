#!/usr/bin/env python3
"""Backtest Indodax 4 jam, minimal 3 tahun, dengan fee + spread + slippage.

Contoh:
  python3 scripts/backtest.py --final
  python3 scripts/backtest.py --search
  python3 scripts/backtest.py --search --quick

Pemilihan parameter HANYA dari in-sample 70% awal (plateau Calmar).
Out-of-sample 30% akhir dievaluasi sekali setelah parameter dipilih.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_json, save_json, load_strategy
from core.backtest_engine import run_backtest, split_ts, quick_metrics, plateau_pick, pair_costs
from core.metrics import compute_metrics
from core.strategy import StrategyEngine

RAW = os.path.join(ROOT, "data", "raw")


def load_data(pairs, tf, start_ts, end_ts, warmup_start_ts=None):
    data = {}
    quality = {}
    warmup_start = int(warmup_start_ts if warmup_start_ts is not None else start_ts - 35 * 86400)
    for pair in pairs:
        path = os.path.join(RAW, "%s_%s.csv" % (pair, tf))
        if not os.path.exists(path):
            quality[pair] = {"ok": False, "reason": "file tidak ada"}
            continue
        bars = []
        with open(path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                bars.append({"time": int(r["time"]), "open": float(r["open"]),
                             "high": float(r["high"]), "low": float(r["low"]),
                             "close": float(r["close"]), "volume": float(r["volume"])})
        bars.sort(key=lambda x: x["time"])
        # dedup
        dedup = []
        for b in bars:
            if dedup and dedup[-1]["time"] == b["time"]:
                dedup[-1] = b
            else:
                dedup.append(b)
        bars = dedup
        window = [b for b in bars if warmup_start <= b["time"] <= end_ts]
        data[pair] = window
        expected = int((end_ts - start_ts) / int(3600)) + 1
        diffs = [bars[i + 1]["time"] - bars[i]["time"] for i in range(len(bars) - 1)]
        bad = sum(1 for b in window if min(b["open"], b["high"], b["low"], b["close"]) <= 0 or b["volume"] < 0)
        quality[pair] = {
            "ok": len(window) > 100 and bad == 0,
            "bars": len(window), "bad_bars": bad,
            "first": datetime.fromtimestamp(window[0]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M") if window else None,
            "last": datetime.fromtimestamp(window[-1]["time"], timezone.utc).strftime("%Y-%m-%d %H:%M") if window else None,
            "gaps": sum(1 for d in diffs if d > 5 * 3600),
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
        }
    return data, quality


def period_table(daily, initial):
    """Return {yearly, monthly, years, partial} dari daily equity."""
    if not daily:
        return {"yearly": {}, "monthly": [], "partial_years": []}
    months = {}
    for p in daily:
        d = p["date_wib"]
        # overwrite: simpan equity hari terakhir tiap bulan, bukan hari pertama
        months[d[:7]] = p["equity"]
    keys = sorted(months)
    monthly = []
    prev = initial
    for k in keys:
        v = months[k]
        monthly.append({"month": k, "equity": v, "return": v / prev - 1.0})
        prev = v
    years = {}
    for k in keys:
        # overwrite: simpan equity bulan terakhir tiap tahun
        years[k[:4]] = months[k]
    yearly = {}
    prev = initial
    for y in sorted(years):
        yearly[y] = {"equity": years[y], "return": years[y] / prev - 1.0}
        prev = years[y]
    partial_years = []
    if keys:
        first_y, last_y = keys[0][:4], keys[-1][:4]
        if keys[0][5:7] != "01":
            partial_years.append(first_y)
        if keys[-1][5:7] != "12":
            partial_years.append(last_y)
    return {"yearly": yearly, "monthly": monthly, "partial_years": partial_years}


def compact_result(r):
    return {
        "params": r["params"], "start": r["start"], "end": r["end"],
        "metrics": r["metrics"],
        "daily_equity": r["daily_equity"],
        "trades": r["trades"],
        "open_positions": r["open_positions"],
        "benchmark": {"pair": r["benchmark"].get("pair"),
                      "metrics": r["benchmark"].get("metrics"),
                      "equity": [{"t": p["t"], "equity": p["equity"]} for p in r["benchmark"].get("equity", [])]},
        "skipped": r["skipped"], "decision_counts": r["decision_counts"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    t0 = time.time()
    cfg = load_strategy()
    tf = cfg["timeframe"]
    start_ts = int(datetime.strptime(a.start or cfg["backtest"]["start"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    end_ts = int(datetime.strptime(a.end or cfg["backtest"]["end"], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    warmup_name = cfg["backtest"].get("warmup_start")
    warmup_ts = (int(datetime.strptime(warmup_name, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
                 if warmup_name else start_ts - 35 * 86400)
    pairs = cfg["universe"]
    print("Universe:", ", ".join(pairs))
    print("Periode:", datetime.fromtimestamp(start_ts, timezone.utc).date(), "->",
          datetime.fromtimestamp(end_ts, timezone.utc).date())
    print("Warm-up:", datetime.fromtimestamp(warmup_ts, timezone.utc).date(), "(tidak dihitung return)")
    data, quality = load_data(pairs, tf, start_ts, end_ts, warmup_start_ts=warmup_ts)
    data = {p: b for p, b in data.items() if quality.get(p, {}).get("ok")}
    if len(data) < 3:
        raise SystemExit("Data valid < 3 pair. Periksa data/raw.")
    cfg_run = dict(cfg)
    cfg_run["universe"] = list(data.keys())
    costs = load_json(os.path.join(ROOT, "data", "costs.json"))
    meta = (load_json(os.path.join(ROOT, "data", "pairs_meta_snapshot.json"), default={}) or {}).get("pairs", {})

    if a.search:
        grid = {"lookback": [20, 30, 40], "fast_ema": [20, 25, 30],
                "trend_ema": [100, 150, 200], "atr_mult": [3.0, 4.0, 5.0]}
        if a.quick:
            grid = {"lookback": [20, 30], "fast_ema": [20, 30],
                    "trend_ema": [100, 200], "atr_mult": [3.0, 4.0]}
        is_end = split_ts(start_ts, end_ts, 0.70)
        results = {}
        combos = [(lb, fe, te, am) for lb in grid["lookback"] for fe in grid["fast_ema"]
                  for te in grid["trend_ema"] for am in grid["atr_mult"]]
        print("Grid search %d kombinasi pada in-sample %s -> %s" % (
            len(combos), datetime.fromtimestamp(start_ts, timezone.utc).date(),
            datetime.fromtimestamp(is_end, timezone.utc).date()))
        for n, combo in enumerate(combos, 1):
            p = dict(cfg["params"])
            p.update({"lookback": combo[0], "fast_ema": combo[1], "trend_ema": combo[2], "atr_mult": combo[3]})
            try:
                r = run_backtest(data, cfg_run, costs, start_ts, is_end, params=p,
                                 pairs_meta=meta, with_benchmark=False)
                results[combo] = quick_metrics(r)
            except Exception as e:
                results[combo] = {"error": str(e), "trades": 0, "calmar": None}
            if n % 10 == 0 or n == len(combos):
                print("  %d/%d (%.0f dtk)" % (n, len(combos), time.time() - t0), flush=True)
        selected, found, top = plateau_pick(grid, results, int(cfg.get("search", {}).get("min_trades", 30)))
        out = {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "method": "Plateau Calmar: rata-rata Calmar parameter + tetangga 1 langkah pada grid 4D; hanya kombinasi dengan trades >= min_trades. Parameter dipilih dari in-sample 70% awal; OOS 30% tidak dipakai memilih.",
            "grid": grid, "min_trades": int(cfg.get("search", {}).get("min_trades", 30)),
            "in_sample": {"start": datetime.fromtimestamp(start_ts, timezone.utc).strftime("%Y-%m-%d"),
                          "end": datetime.fromtimestamp(is_end, timezone.utc).strftime("%Y-%m-%d")},
            "out_of_sample": {"start": datetime.fromtimestamp(is_end + 14400, timezone.utc).strftime("%Y-%m-%d"),
                              "end": datetime.fromtimestamp(end_ts, timezone.utc).strftime("%Y-%m-%d")},
            "results": [{"params": dict(zip(["lookback", "fast_ema", "trend_ema", "atr_mult"], c)),
                         **results[c]} for c in combos],
            "selected_params": selected, "plateau_found": found, "top10_smooth": top,
        }
        save_json(os.path.join(ROOT, "data", "backtest_search.json"), out)
        print("\nParameter terpilih:", selected)
        print("Top plateau:")
        for x in top[:5]:
            print("  ", x["params"], "smooth Calmar %.2f CAGR %.1f%% MDD %.1f%% trades %d" % (
                x["smooth_calmar"], (x["cagr"] or 0) * 100, (x["mdd"] or 0) * 100, x["trades"]))
        print("-> data/backtest_search.json")
        if not a.final:
            return

    params = cfg["params"]
    if a.search:
        sp = load_json(os.path.join(ROOT, "data", "backtest_search.json")).get("selected_params")
        if sp:
            params = dict(cfg["params"])
            params.update(sp)
    print("\nBacktest final dengan parameter:", params)
    full = run_backtest(data, cfg_run, costs, start_ts, end_ts, params=params,
                        collect_orders=True, pairs_meta=meta)
    is_end = split_ts(start_ts, end_ts, 0.70)
    is_res = run_backtest(data, cfg_run, costs, start_ts, is_end, params=params,
                          pairs_meta=meta, with_benchmark=False)
    oos_res = run_backtest(data, cfg_run, costs, is_end + 14400, end_ts, params=params,
                           pairs_meta=meta, with_benchmark=False)
    stress_fee = run_backtest(data, cfg_run, costs, start_ts, end_ts, params=params,
                              fee_mult=2.0, pairs_meta=meta, with_benchmark=False)
    stress_cost = run_backtest(data, cfg_run, costs, start_ts, end_ts, params=params,
                               cost_mult=2.0, pairs_meta=meta, with_benchmark=False)
    delay = run_backtest(data, cfg_run, costs, start_ts, end_ts, params=params,
                         delay_bars=1, pairs_meta=meta, with_benchmark=False)

    # sensitivitas satu parameter (bukan untuk memilih ulang, hanya robustness)
    sens = []
    for key in ["lookback", "fast_ema", "trend_ema", "atr_mult"]:
        for mult in [0.8, 1.2]:
            p = dict(params)
            v = float(params[key]) * mult
            p[key] = round(v, 1) if key == "atr_mult" else max(2, int(round(v)))
            if p[key] == params[key]:
                continue
            r = run_backtest(data, cfg_run, costs, start_ts, end_ts, params=p,
                             pairs_meta=meta, with_benchmark=False)
            q = quick_metrics(r)
            sens.append({"param": key, "mult": mult, "value": p[key], **q})

    table = period_table(full["daily_equity"], cfg["capital_idr"])
    out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "strategy": cfg["strategy_name"], "timeframe": cfg["timeframe"],
            "timeframe_seconds": cfg["timeframe_seconds"],
            "period_start": full["start"], "period_end": full["end"],
            "years": full["metrics"]["years"],
            "capital_idr": cfg["capital_idr"], "universe": full["universe"],
            "params": params, "fees": cfg["fees"], "min_order_idr": cfg["min_order_idr"],
            "costs": costs.get("pairs", {}),
            "cost_fallback": costs.get("fallback"),
            "cost_method": costs.get("method"),
            "universe_selection": load_json(os.path.join(ROOT, "data", "universe.json"), default={}),
            "data_source": "Indodax public API history_v2",
            "data_quality": quality,
            "runtime_seconds": round(time.time() - t0, 1),
            "python": sys.version.split()[0],
            "code_sha256": hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:16],
        },
        "params": params,
        "metrics": full["metrics"],
        "is": {"start": is_res["start"], "end": is_res["end"], "metrics": is_res["metrics"]},
        "oos": {"start": oos_res["start"], "end": oos_res["end"], "metrics": oos_res["metrics"]},
        "stress": {
            "fee_2x": {"metrics": stress_fee["metrics"]},
            "cost_2x": {"metrics": stress_cost["metrics"]},
            "delay_1_bar": {"metrics": delay["metrics"]},
        },
        "sensitivity": sens,
        "benchmark": full["benchmark"],
        "daily_equity": full["daily_equity"],
        "monthly": table["monthly"],
        "yearly": table["yearly"],
        "partial_years": table["partial_years"],
        "trades": full["trades"],
        "open_positions": full["open_positions"],
        "orders_sample": full["orders"][:200],
        "skipped": full["skipped"],
        "decision_counts": full["decision_counts"],
    }
    out_path = a.out or os.path.join(ROOT, "data", "backtest_results.json")
    save_json(out_path, out)
    # CSV untuk audit manual
    with open(os.path.join(ROOT, "data", "backtest_trades.csv"), "w", newline="", encoding="utf-8") as f:
        cols = ["pair", "entry_time", "exit_time", "qty", "entry_ref", "entry_fill", "exit_ref",
                "exit_fill", "gross_pnl", "fee_total", "spread_cost", "slippage_cost", "net_pnl",
                "net_pct", "holding_bars", "exit_reason"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for t in full["trades"]:
            w.writerow(t)
    with open(os.path.join(ROOT, "data", "backtest_equity_daily.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date_wib", "t", "equity"])
        w.writeheader()
        w.writerows(full["daily_equity"])

    m = full["metrics"]
    bm = (full["benchmark"].get("metrics") or {})
    print("\n================ HASIL BACKTEST ================")
    print("Periode        : %s -> %s (%.2f tahun)" % (full["start"][:10], full["end"][:10], m["years"]))
    print("Total return   : %+.2f%%" % (m["total_return_pct"] or 0))
    print("CAGR           : %+.2f%%" % (m["cagr_pct"] or 0))
    print("Max drawdown   : %.2f%%" % (m["max_drawdown_pct"] or 0))
    print("Profit factor  : %s" % (("%.2f" % m["profit_factor"]) if m["profit_factor"] not in (None, float("inf")) else m["profit_factor"]))
    print("Win rate       : %.1f%% (%d/%d)" % (m["win_rate_pct"] or 0, m["wins"], m["trades"]))
    print("Avg win/loss   : Rp%s / Rp%s" % (format(m["avg_win_idr"] or 0, ",.0f"), format(m["avg_loss_idr"] or 0, ",.0f")))
    print("Biaya          : fee Rp%s | spread Rp%s | slippage Rp%s" % (
        format(m["fee_idr"], ",.0f"), format(m["spread_cost_idr"], ",.0f"), format(m["slippage_cost_idr"], ",.0f")))
    print("Benchmark BTC  : %+.2f%% (CAGR %+.2f%%, MDD %.2f%%)" % (
        bm.get("total_return_pct") or 0, bm.get("cagr_pct") or 0, bm.get("max_drawdown_pct") or 0))
    print("IS / OOS CAGR  : %+.2f%% / %+.2f%%" % (
        is_res["metrics"]["cagr_pct"] or 0, oos_res["metrics"]["cagr_pct"] or 0))
    print("Stress fee 2x  : CAGR %+.2f%%" % (stress_fee["metrics"]["cagr_pct"] or 0))
    print("Stress cost 2x : CAGR %+.2f%%" % (stress_cost["metrics"]["cagr_pct"] or 0))
    print("Delay 1 bar    : CAGR %+.2f%%" % (delay["metrics"]["cagr_pct"] or 0))
    print("\n-> %s (%.1f KB)" % (out_path, os.path.getsize(out_path) / 1024))
    if a.search:
        print("CATATAN: perbarui config/strategy.json dengan parameter final sebelum freeze.")


if __name__ == "__main__":
    main()
