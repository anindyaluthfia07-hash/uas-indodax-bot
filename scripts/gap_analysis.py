#!/usr/bin/env python3
"""Analisis gap jadwal dan candle yang hilang selama forward test.

Membandingkan candle 4 jam yang seharusnya diproses dengan keputusan yang
benar-benar tercatat, serta tick scheduler yang seharusnya terjadi.

Contoh:
  python3 scripts/gap_analysis.py --source local
  CRON_SECRET=xxx python3 scripts/gap_analysis.py --source url \
      --url https://proyek.vercel.app/api/export
"""
import argparse
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_strategy, parse_iso, save_json
from core.period import FORWARD_TEST_END, forward_period
from core.storage import LocalStorage

SCHEDULE_OFFSET = 7 * 60  # menit ke-7 setelah candle close (UTC)
SCHEDULE_TOLERANCE = 45 * 60


def expected_candles_between(start_ts, end_ts, tf):
    """Candle yang tutup di (start, end].

    Candle yang open sebelum start tetapi tutup setelah start tetap dihitung,
    karena candle itulah yang pertama bisa diproses bot setelah start.
    """
    first = int(math.floor(start_ts / tf) * tf)
    while first + tf <= start_ts:
        first += tf
    out = []
    t = first
    while t + tf <= end_ts + 1e-6:
        out.append(t)
        t += tf
    return out


def fetch_json(url, secret=None):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def load_data(args):
    if args.source == "url":
        if not args.url:
            raise SystemExit("--url wajib untuk --source url")
        d = fetch_json(args.url, args.secret or os.environ.get("CRON_SECRET"))
        return d.get("config") or load_strategy(), d.get("state") or {}, d.get("logs") or {}
    s = LocalStorage()
    return load_strategy(), s.get_state() or {}, {
        k: s.read(k, 0) for k in ["ticks", "decisions", "orders", "trades", "errors", "equity"]
    }


def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "url"], default="local")
    ap.add_argument("--url", default=None)
    ap.add_argument("--secret", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "gap_analysis.json"))
    a = ap.parse_args()

    cfg, state, logs = load_data(a)
    tf = int(cfg["timeframe_seconds"])
    start = state.get("forward_test_start")
    if not start:
        out = {"generated_at": iso(datetime.now(timezone.utc).timestamp()),
               "status": "belum_ada_forward_test", "note": "forward_test_start belum tercatat"}
        save_json(a.out, out)
        print("Forward test belum dimulai; tidak ada gap untuk dianalisis.")
        return 0

    start_ts = parse_iso(start).timestamp()
    decisions = logs.get("decisions") or []
    ticks = logs.get("ticks") or []
    tick_ts = []
    for t in ticks:
        ts = parse_iso(t.get("started_at") or t.get("finished_at") or "")
        if ts:
            tick_ts.append(ts.timestamp())
    tick_ts.sort()
    end_ts = max(tick_ts) if tick_ts else start_ts
    # kalau ada equity log lebih baru, pakai itu
    for e in logs.get("equity") or []:
        if e.get("t") and float(e["t"]) > end_ts:
            end_ts = float(e["t"])

    # Periode forward ditetapkan sampai 2026-11-14T05:00:00Z (12:00 WIB).
    # Candle yang diharapkan dihitung sampai min(sekarang, akhir periode),
    # bukan hanya sampai tick terakhir, supaya candle yang terlewat setelah
    # tick terakhir tetap terhitung sebagai gap.
    now = datetime.now(timezone.utc)
    period_end_ts = parse_iso(FORWARD_TEST_END).timestamp()
    analysis_end = min(now.timestamp(), period_end_ts)
    fp = forward_period(start, now)

    expected = expected_candles_between(start_ts, analysis_end, tf)
    period_expected = expected_candles_between(start_ts, period_end_ts, tf)
    expected_set = set(expected)

    by_pair = {}
    for d in decisions:
        pair = d.get("pair")
        ct = d.get("candle_time")
        if not pair or ct is None:
            continue
        ct = int(ct)
        pa = d.get("processed_at_epoch")
        if pa is None:
            dtv = parse_iso(d.get("processed_at") or d.get("at") or "")
            pa = dtv.timestamp() if dtv else None
        rec = by_pair.setdefault(pair, {"seen": set(), "on_time": set(), "late": {}, "duplicates": {}, "invalid": 0})
        rec["seen"].add(ct)
        if ct in expected_set and pa is not None:
            # Candle baru bisa diproses setelah tutup (ct+tf). Tepat waktu berarti
            # masih sebelum candle berikutnya tutup (ct+2*tf). Syarat lama
            # (pa < ct+tf) tidak mungkin terpenuhi setelah menunggu close.
            if pa < ct + 2 * tf:
                rec["on_time"].add(ct)
            else:
                rec["late"][ct] = pa - (ct + tf)
        if d.get("action") in ("buy", "sell"):
            rec["duplicates"][ct] = rec["duplicates"].get(ct, 0) + 1
        if d.get("data_valid") is False:
            rec["invalid"] += 1

    out_pairs = {}
    all_on = 0
    all_seen = 0
    for pair in cfg["universe"]:
        r = by_pair.get(pair, {"seen": set(), "on_time": set(), "late": {}, "duplicates": {}, "invalid": 0})
        missing = [x for x in expected if x not in r["seen"]]
        late = [(x, r["late"][x]) for x in expected if x in r["late"]]
        dup = {x: n for x, n in r["duplicates"].items() if n > 1}
        all_on += len(r["on_time"])
        all_seen += len(expected_set & r["seen"])
        out_pairs[pair] = {
            "expected": len(expected), "on_time": len(r["on_time"]),
            "uptime": (len(r["on_time"]) / len(expected)) if expected else None,
            "missing_count": len(missing), "late_count": len(late),
            "duplicate_actions": dup, "invalid_decisions": r["invalid"],
            "missing_sample": [iso(x) for x in missing[:50]],
            "late_sample": [{"candle": iso(x), "late_seconds": int(s)} for x, s in late[:50]],
        }

    # scheduler: tick diharapkan pada close + 7 menit
    sched_expected = [x + tf + SCHEDULE_OFFSET for x in expected]
    hits, misses, late_ticks = [], [], []
    for target in sched_expected:
        nearest = min(tick_ts, key=lambda x: abs(x - target)) if tick_ts else None
        if nearest is not None and abs(nearest - target) <= SCHEDULE_TOLERANCE:
            hits.append(target)
            if nearest - target > 60:
                late_ticks.append({"expected": iso(target), "actual": iso(nearest),
                                   "late_seconds": int(nearest - target)})
        else:
            misses.append(target)

    out = {
        "generated_at": iso(datetime.now(timezone.utc).timestamp()),
        "forward_start": start,
        "forward_end": iso(end_ts),
        "analysis_end": iso(analysis_end),
        "period_end": FORWARD_TEST_END,
        "period_end_wib": fp["target_end_wib"],
        "period_days": fp["period_days"],
        "elapsed_days": fp["elapsed_days"],
        "remaining_hours": fp["remaining_hours"],
        "complete": fp["complete"],
        "timeframe_seconds": tf,
        "duration_hours": (end_ts - start_ts) / 3600.0,
        "duration_days": (end_ts - start_ts) / 86400.0,
        "elapsed_hours": (analysis_end - start_ts) / 3600.0,
        "elapsed_days": (analysis_end - start_ts) / 86400.0,
        "expected_candles": len(expected),
        "expected_candles_period": len(period_expected),
        "pairs_expected": len(cfg["universe"]),
        "per_pair": out_pairs,
        "overall": {
            "uptime_mean": (all_on / (len(expected) * len(cfg["universe"]))) if expected and cfg["universe"] else None,
            "processed_pair_candles": all_seen,
            "coverage_of_elapsed": (all_seen / (len(expected) * len(cfg["universe"]))) if expected and cfg["universe"] else None,
            "coverage_of_period": (all_seen / (len(period_expected) * len(cfg["universe"]))) if period_expected and cfg["universe"] else None,
        },
        "scheduler": {
            "expected_ticks": len(sched_expected),
            "hit": len(hits),
            "missing": len(misses),
            "late": len(late_ticks),
            "uptime": (len(hits) / len(sched_expected)) if sched_expected else None,
            "missing_sample": [iso(x) for x in misses[:50]],
            "late_sample": late_ticks[:50],
            "definition": "tick dihitung tepat waktu bila terjadi dalam ±45 menit dari candle close + 7 menit",
        },
        "note": "Gap dihitung dari log mentah. Tidak ada candle atau tick yang ditambahkan untuk menutupi gap.",
    }
    save_json(a.out, out)

    print("Periode   : %s -> %s (%.2f hari; %s)" % (
        start, FORWARD_TEST_END, fp["period_days"] or 0,
        "selesai" if fp["complete"] else "berjalan, sisa %.1f jam" % fp["remaining_hours"]))
    print("Data      : %s -> %s (%.1f jam tercatat)" % (
        start, iso(end_ts), (end_ts - start_ts) / 3600.0))
    print("Candle    : %d diharapkan per pair (elapsed), %d per pair (satu periode)" % (
        len(expected), len(period_expected)))
    print("Cakupan   : %.1f%% dari candle yang sudah tutup, %.1f%% dari seluruh periode" % (
        (out["overall"]["coverage_of_elapsed"] or 0) * 100,
        (out["overall"]["coverage_of_period"] or 0) * 100))
    for pair in cfg["universe"]:
        p = out_pairs[pair]
        print("  %-9s uptime=%5.1f%% missing=%d late=%d duplikat=%d" % (
            pair, (p["uptime"] or 0) * 100, p["missing_count"], p["late_count"], len(p["duplicate_actions"])))
    s = out["scheduler"]
    print("Scheduler : %d/%d tick tepat waktu (%.1f%%), missing=%d late=%d" % (
        s["hit"], s["expected_ticks"], (s["uptime"] or 0) * 100, s["missing"], s["late"]))
    print("-> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
