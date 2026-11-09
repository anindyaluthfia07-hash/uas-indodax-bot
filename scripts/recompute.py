#!/usr/bin/env python3
"""Hitung ulang metrik forward test dari log mentah dan periksa konsistensi.

Sumber:
  local (default) : data/local/*.jsonl
  url             : endpoint /api/export di Vercel (butuh CRON_SECRET)

Contoh:
  python3 scripts/recompute.py --source local
  CRON_SECRET=xxx python3 scripts/recompute.py --source url \
      --url https://proyek.vercel.app/api/export

Output: data/recomputed.json + ringkasan PASS/FAIL di terminal.
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.bot import dashboard_payload
from core.config import load_strategy, parse_iso, save_json
from core.metrics import compute_metrics
from core.storage import LocalStorage


def fetch_json(url, secret=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def load_source(args):
    if args.source == "url":
        if not args.url:
            raise SystemExit("--url wajib untuk --source url")
        secret = args.secret or os.environ.get("CRON_SECRET")
        data = fetch_json(args.url, secret)
        dashboard = None
        dash_url = args.dashboard_url
        if not dash_url:
            dash_url = args.url.replace("/api/export", "/api/dashboard")
        try:
            dashboard = fetch_json(dash_url)
        except Exception as e:
            print("Peringatan: dashboard tidak bisa diambil (%s)" % e)
        return data, dashboard
    storage = LocalStorage()
    data = {
        "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "config": load_strategy(),
        "state": storage.get_state() or {},
        "kill_switch": storage.get_kill(),
        "logs": {k: storage.read(k, 0) for k in
                 ["ticks", "decisions", "orders", "trades", "errors", "equity",
                  "daily_equity", "snapshots", "kill_log"]},
    }
    return data, dashboard_payload(storage)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "url"], default="local")
    ap.add_argument("--url", default=None)
    ap.add_argument("--dashboard-url", default=None)
    ap.add_argument("--secret", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "recomputed.json"))
    a = ap.parse_args()

    data, dashboard = load_source(a)
    cfg = data.get("config") or load_strategy()
    logs = data.get("logs") or {}
    state = data.get("state") or {}
    trades = logs.get("trades") or []
    equity_log = logs.get("equity") or []
    points = [{"t": x["t"], "equity": x["equity"]} for x in equity_log
              if x.get("t") is not None and x.get("equity") is not None]
    points.sort(key=lambda p: p["t"])
    initial = float(cfg.get("capital_idr") or 100000000)
    forward_start = state.get("forward_test_start")
    start = forward_start or (points[0]["t"] if points else None)
    end = points[-1]["t"] if points else None
    m = compute_metrics(points, trades, initial, start=start, end=end, include_cagr=False)

    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    check("ada titik ekuitas", len(points) > 0, "%d titik" % len(points))
    check("ada state forward", bool(forward_start), forward_start or "belum ada")
    check("final equity == metrik", abs(m["final_equity"] - (points[-1]["equity"] if points else initial)) < 1e-6,
          "equity=%s" % m["final_equity"])

    # integritas per trade: net = gross - fee - spread - slippage
    bad = []
    for i, t in enumerate(trades):
        calc = (float(t.get("gross_pnl") or 0) - float(t.get("fee_total") or 0)
                - float(t.get("spread_cost") or 0) - float(t.get("slippage_cost") or 0))
        if abs(calc - float(t.get("net_pnl") or 0)) > 0.01:
            bad.append(i)
    check("net_pnl = gross - fee - spread - slippage", not bad,
          "%d trade diperiksa, %d menyimpang" % (len(trades), len(bad)))

    # total biaya
    fee_sum = sum(float(t.get("fee_total") or 0) for t in trades)
    spread_sum = sum(float(t.get("spread_cost") or 0) for t in trades)
    slip_sum = sum(float(t.get("slippage_cost") or 0) for t in trades)
    check("total fee konsisten", abs(fee_sum - m["fee_idr"]) < 0.01,
          "trades=%.2f metrik=%.2f" % (fee_sum, m["fee_idr"]))
    check("total spread konsisten", abs(spread_sum - m["spread_cost_idr"]) < 0.01,
          "trades=%.2f metrik=%.2f" % (spread_sum, m["spread_cost_idr"]))
    check("total slippage konsisten", abs(slip_sum - m["slippage_cost_idr"]) < 0.01,
          "trades=%.2f metrik=%.2f" % (slip_sum, m["slippage_cost_idr"]))

    # rekonsiliasi ekuitas: modal + net trade + unrealized posisi terbuka
    prices = state.get("last_prices") or {}
    open_unreal = 0.0
    for pair, pos in (state.get("positions") or {}).items():
        last = prices.get(pair) or pos.get("entry_ref") or 0
        basis = float(pos.get("qty", 0)) * float(pos.get("entry_fill", 0)) + float(pos.get("entry_fee", 0))
        open_unreal += float(pos.get("qty", 0)) * float(last) - basis
    recon = initial + sum(float(t.get("net_pnl") or 0) for t in trades) + open_unreal
    final = points[-1]["equity"] if points else initial
    tol = max(10.0, abs(final) * 1e-9)
    check("rekonsiliasi ekuitas", abs(final - recon) <= tol,
          "final=%.2f rekonstruksi=%.2f selisih=%.2f" % (final, recon, final - recon))

    # tidak ada order ganda dengan order_id sama
    order_ids = [o.get("order_id") for o in (logs.get("orders") or []) if o.get("order_id")]
    check("order_id unik", len(order_ids) == len(set(order_ids)),
          "%d order, %d unik" % (len(order_ids), len(set(order_ids))))

    # tidak ada dua aksi beli/jual untuk pair+candle yang sama
    seen = {}
    dups = []
    for d in logs.get("decisions") or []:
        if d.get("action") in ("buy", "sell") and d.get("pair") and d.get("candle_time"):
            key = (d["pair"], int(d["candle_time"]), d["action"])
            if key in seen:
                dups.append(key)
            seen[key] = True
    check("tidak ada eksekusi ganda per pair+candle", not dups, str(dups[:5]))

    # bandingkan dengan yang disajikan dashboard
    if dashboard:
        fm = ((dashboard.get("forward") or {}).get("metrics") or {})
        pairs_cmp = ["total_return_pct", "final_equity", "trades", "fee_idr",
                     "spread_cost_idr", "slippage_cost_idr", "max_drawdown_pct"]
        diffs = {}
        for k in pairs_cmp:
            a1, b1 = m.get(k), fm.get(k)
            if a1 is None and b1 is None:
                continue
            if a1 is None or b1 is None or abs(float(a1) - float(b1)) > 1e-6:
                diffs[k] = {"recompute": a1, "dashboard": b1}
        check("dashboard == hasil hitung ulang", not diffs, json.dumps(diffs, default=str))
    else:
        check("dashboard tersedia untuk dibandingkan", False, "dilewati")

    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": a.source,
        "forward_start": forward_start,
        "forward_end": end,
        "initial_capital": initial,
        "metrics": m,
        "trade_count": len(trades),
        "checks": checks,
        "all_pass": all(c["ok"] for c in checks),
        "logs": {k: len(v) for k, v in logs.items() if isinstance(v, list)},
        "state": {
            "cash": state.get("cash"),
            "equity": state.get("last_equity"),
            "positions": len(state.get("positions") or {}),
            "tick_count": state.get("tick_count"),
            "kill_switch": data.get("kill_switch"),
        },
    }
    save_json(a.out, out)

    print("Sumber        : %s" % a.source)
    print("Forward mulai : %s" % (forward_start or "belum"))
    print("Titik ekuitas : %d" % len(points))
    print("Trade         : %d" % len(trades))
    print("Return        : %+.4f%%" % (m.get("total_return_pct") or 0))
    print("Final equity  : Rp%s" % format(m.get("final_equity") or 0, ",.0f"))
    print("")
    for c in checks:
        print("  [%s] %-42s %s" % ("PASS" if c["ok"] else "FAIL", c["check"], c["detail"]))
    print("\nSemua pemeriksaan: %s" % ("PASS" if out["all_pass"] else "ADA YANG GAGAL"))
    print("-> %s" % a.out)
    return 0 if out["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
