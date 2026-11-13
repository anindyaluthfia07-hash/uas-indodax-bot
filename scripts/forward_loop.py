#!/usr/bin/env python3
"""Loop forward test lokal.

Menjalankan tick pada setiap candle 4 jam ditutup (default: 90 detik setelah
close) sampai periode forward test berakhir, yaitu **14 November 2026 12.00 WIB**
(`2026-11-14T05:00:00Z`). Untuk produksi, gunakan GitHub Actions; loop ini
untuk laptop yang harus tetap menyala.

Contoh:
  python3 scripts/forward_loop.py --offset-seconds 90

Satu tick sekarang lalu keluar:
  python3 scripts/forward_loop.py --once
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.bot import run_tick
from core.config import load_strategy, iso_utc, utc_now, parse_iso
from core.period import FORWARD_TEST_END, forward_period
from core.storage import get_storage


def log_line(msg):
    line = "%s %s" % (iso_utc(), msg)
    print(line, flush=True)
    try:
        path = os.path.join(ROOT, "data", "local", "forward_loop.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def next_candle_tick(now, tf_seconds, offset):
    epoch = int(now.timestamp())
    boundary = (epoch // tf_seconds + 1) * tf_seconds
    return datetime.fromtimestamp(boundary + offset, timezone.utc)


def sleep_until(target_ts, stop_at):
    while True:
        now = time.time()
        left = min(target_ts - now, stop_at - now)
        if left <= 0:
            return
        if now >= stop_at:
            return
        time.sleep(min(30.0, left))


def main():
    ap = argparse.ArgumentParser(description="Forward test loop lokal")
    ap.add_argument("--once", action="store_true", help="jalankan satu tick lalu keluar")
    ap.add_argument("--days", type=float, default=None,
                    help="opsional: batasi durasi lebih pendek; default sampai akhir periode")
    ap.add_argument("--offset-seconds", type=int, default=90,
                    help="tunggu berapa detik setelah candle close (default 90)")
    ap.add_argument("--no-snapshots", action="store_true")
    a = ap.parse_args()

    cfg = load_strategy()
    tf = int(cfg["timeframe_seconds"])
    storage = get_storage()
    period_end = parse_iso(FORWARD_TEST_END)
    fp = forward_period()
    if fp["complete"]:
        log_line("periode forward test sudah berakhir pada %s; tidak ada tick baru." % FORWARD_TEST_END)
        return 0
    log_line("loop mulai storage=%s timeframe=%ss sampai=%s (%s) offset=%ss" % (
        storage.name, tf, FORWARD_TEST_END, fp["target_end_wib"], a.offset_seconds))

    if a.once:
        summary = run_tick(storage, trigger="forward_loop_once",
                           save_snapshots=not a.no_snapshots)
        log_line("tick status=%s equity=%s orders=%s" % (
            summary.get("status"), summary.get("equity"), summary.get("orders")))
        return 0 if summary.get("status") == "ok" else 1

    # Tick awal: setelah loop/restart, jangan menunggu 4 jam berikutnya.
    # Idempotensi per candle mencegah pemrosesan ganda. Ini perbaikan
    # infrastruktur penjadwal, bukan perubahan aturan strategi.
    summary = run_tick(storage, trigger="forward_loop_start",
                       save_snapshots=not a.no_snapshots)
    log_line("tick awal status=%s equity=%s posisi=%s order=%s error=%s" % (
        summary.get("status"), summary.get("equity"), summary.get("positions"),
        summary.get("orders"), summary.get("errors")))
    for attempt in range(1, 3):
        if summary.get("status") == "ok":
            break
        log_line("tick awal gagal (%s), coba ulang %d/2 dalam 60 detik" % (
            summary.get("status"), attempt))
        time.sleep(60)
        summary = run_tick(storage, trigger="forward_loop_start_retry",
                           save_snapshots=not a.no_snapshots)
        log_line("tick awal retry %d status=%s equity=%s" % (
            attempt, summary.get("status"), summary.get("equity")))

    started = utc_now()
    stop_at = period_end.timestamp()
    if a.days is not None:
        stop_at = min(stop_at, started.timestamp() + a.days * 86400.0)
    log_line("batas loop: %s" % iso_utc(datetime.fromtimestamp(stop_at, timezone.utc)))
    n = 0
    while True:
        now = utc_now()
        if now.timestamp() >= stop_at:
            break
        target = next_candle_tick(now, tf, a.offset_seconds)
        if target.timestamp() >= stop_at:
            break
        log_line("menunggu candle berikutnya: %s" % iso_utc(target))
        sleep_until(target.timestamp(), stop_at)
        if time.time() >= stop_at:
            break
        n += 1
        summary = run_tick(storage, trigger="forward_loop",
                           save_snapshots=not a.no_snapshots)
        log_line("tick %d status=%s equity=%s posisi=%s order=%s error=%s" % (
            n, summary.get("status"), summary.get("equity"),
            summary.get("positions"), summary.get("orders"), summary.get("errors")))
        for attempt in range(1, 3):
            if summary.get("status") == "ok":
                break
            # Masih ada waktu sebelum candle berikutnya ditutup (4 jam), jadi
            # kegagalan jaringan sesaat tidak perlu mengorbankan candle ini.
            log_line("tick %d gagal (%s), coba ulang %d/2 dalam 60 detik" % (
                n, summary.get("status"), attempt))
            time.sleep(60)
            summary = run_tick(storage, trigger="forward_loop_retry",
                               save_snapshots=not a.no_snapshots)
            log_line("retry %d status=%s equity=%s" % (
                attempt, summary.get("status"), summary.get("equity")))
    log_line("loop selesai: %d tick" % n)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nDihentikan oleh pengguna. Log tetap tersimpan.")
        sys.exit(130)
