#!/usr/bin/env python3
"""Hitung median spread & slippage dari snapshot order book mentah.

Output data/costs.json dipakai backtest. Bot live TIDAK memakai angka ini:
bot mengeksekusi langsung pada order book aktual (walk the book).
"""
import glob
import json
import os
import statistics
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_json, save_json
from core.exchange import walk_book_notional, walk_book_qty

SNAP = os.path.join(ROOT, "data", "snapshots")


def main():
    cfg = load_json(os.path.join(ROOT, "config", "strategy.json"))
    universe = cfg["universe"]
    target = 0.20 * float(cfg["capital_idr"])
    rows = []
    for path in sorted(glob.glob(os.path.join(SNAP, "orderbook_*.jsonl"))):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("pair") in universe and r.get("bid") and r.get("ask") and r.get("spread_pct") is not None:
                    rows.append(r)

    by_pair = {}
    for r in rows:
        by_pair.setdefault(r["pair"], []).append(r)
    out_pairs = {}
    all_spreads = []
    for pair in universe:
        rs = by_pair.get(pair, [])
        spreads = [float(x["spread_pct"]) for x in rs]
        slip_buy, slip_sell, voll = [], [], []
        for x in rs:
            mid = (float(x["bid"]) + float(x["ask"])) / 2.0
            b = walk_book_notional([(float(p), float(q)) for p, q in x.get("asks", [])[:20]], target)
            qty = target / mid
            s = walk_book_qty([(float(p), float(q)) for p, q in x.get("bids", [])[:20]], qty)
            if b.get("complete") and b.get("vwap"):
                slip_buy.append(b["vwap"] / float(x["ask"]) - 1.0)
            if s.get("complete") and s.get("vwap"):
                slip_sell.append(1.0 - s["vwap"] / float(x["bid"]))
            voll.append(1.0 if (b.get("complete") and s.get("complete")) else 0.0)
        if spreads:
            med_spread = statistics.median(spreads)
            half = med_spread / 2.0
            sb = statistics.median(slip_buy) if slip_buy else None
            ss = statistics.median(slip_sell) if slip_sell else None
            out_pairs[pair] = {
                "samples": len(rs), "target_notional_idr": target,
                "spread_median": med_spread,
                "spread_p25": statistics.quantiles(spreads, n=4)[0] if len(spreads) >= 4 else med_spread,
                "spread_p75": statistics.quantiles(spreads, n=4)[2] if len(spreads) >= 4 else med_spread,
                "half_spread": half,
                "slippage_buy": sb if sb is not None else 0.0,
                "slippage_sell": ss if ss is not None else 0.0,
                "slippage_samples_buy": len(slip_buy),
                "slippage_samples_sell": len(slip_sell),
                "depth_complete_share": (sum(voll) / len(voll)) if voll else 0.0,
                "first_snapshot": min(x["at_utc"] for x in rs),
                "last_snapshot": max(x["at_utc"] for x in rs),
            }
            all_spreads.extend(spreads)
        else:
            out_pairs[pair] = {"samples": 0, "target_notional_idr": target,
                               "spread_median": None, "half_spread": None,
                               "slippage_buy": None, "slippage_sell": None,
                               "depth_complete_share": 0.0}
    med_all = statistics.median(all_spreads) if all_spreads else 0.005
    slip_all_buy = [v["slippage_buy"] for v in out_pairs.values()
                    if v.get("slippage_buy") is not None and v.get("samples")]
    slip_all_sell = [v["slippage_sell"] for v in out_pairs.values()
                     if v.get("slippage_sell") is not None and v.get("samples")]
    fallback = {
        "spread_median": med_all,
        "half_spread": med_all / 2.0,
        "slippage_buy": statistics.median(slip_all_buy) if slip_all_buy else 0.002,
        "slippage_sell": statistics.median(slip_all_sell) if slip_all_sell else 0.002,
        "note": "fallback = median lintas pair yang punya snapshot; 0.2% slippage hanya jika tidak ada snapshot sama sekali",
    }
    out = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": "snapshot order book Indodax (scripts/collect_snapshots.py)",
        "method": "spread = (ask-bid)/mid pada best level; slippage = selisih VWAP hasil walk-the-book terhadap best level untuk notional 20% modal awal. Backtest memakai median seluruh snapshot yang terkumpul.",
        "target_notional_idr": target,
        "total_snapshots_used": len(rows),
        "pairs": out_pairs,
        "fallback": fallback,
        "universe_median": {
            "spread_median": med_all, "half_spread": med_all / 2.0,
            "slippage_buy": fallback["slippage_buy"],
            "slippage_sell": fallback["slippage_sell"],
        },
    }
    save_json(os.path.join(ROOT, "data", "costs.json"), out)
    print("Snapshot dipakai:", len(rows))
    for pair in universe:
        v = out_pairs[pair]
        if v["samples"]:
            print("  %-9s n=%-3d spread=%.4f%% half=%.4f%% slip_buy=%.4f%% slip_sell=%.4f%% depth_ok=%.1f%%" % (
                pair, v["samples"], v["spread_median"] * 100, v["half_spread"] * 100,
                (v["slippage_buy"] or 0) * 100, (v["slippage_sell"] or 0) * 100,
                v["depth_complete_share"] * 100))
        else:
            print("  %-9s BELUM ADA SNAPSHOT" % pair)
    print("-> data/costs.json")


if __name__ == "__main__":
    main()
