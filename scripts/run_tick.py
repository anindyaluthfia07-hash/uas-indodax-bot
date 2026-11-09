#!/usr/bin/env python3
"""Jalankan satu tick bot dry-run dari terminal.

Contoh:
  python3 scripts/run_tick.py
  python3 scripts/run_tick.py --trigger manual --no-snapshots
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.bot import run_tick
from core.config import load_strategy
from core.storage import get_storage


def main():
    ap = argparse.ArgumentParser(description="Satu tick bot dry-run Indodax")
    ap.add_argument("--trigger", default="local_cli")
    ap.add_argument("--no-snapshots", action="store_true",
                    help="jangan simpan order book mentah (hemat ruang)")
    ap.add_argument("--lock-ttl", type=int, default=600)
    a = ap.parse_args()
    cfg = load_strategy()
    storage = get_storage()
    print("Storage : %s" % storage.name)
    print("Universe: %s" % ", ".join(cfg["universe"]))
    print("Timeframe: %s menit" % cfg["timeframe_minutes"])
    summary = run_tick(storage, trigger=a.trigger,
                       save_snapshots=not a.no_snapshots, lock_ttl=a.lock_ttl)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    if summary.get("status") == "ok":
        print("\nOK  equity=%s  cash=%s  posisi=%s  order=%s" % (
            summary.get("equity"), summary.get("cash"),
            summary.get("positions"), summary.get("orders")))
        return 0
    if summary.get("status") == "locked":
        print("\nSKIP: tick lain sedang berjalan.")
        return 3
    print("\nGAGAL: %s" % summary.get("error", "lihat log errors"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
