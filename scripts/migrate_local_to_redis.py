#!/usr/bin/env python3
"""Salin state dan log forward test lokal ke Upstash Redis.

Dipakai sekali saat memindahkan forward test dari laptop ke Vercel/GitHub
Actions **tanpa mengubah** `forward_test_start`. Skrip ini tidak menghapus data
lokal dan tidak mengarang candle/tick yang hilang: isi Redis sama persis dengan
isi `data/local/`.

Contoh:
  # lihat apa yang akan disalin (tanpa menulis)
  UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... \
      python3 scripts/migrate_local_to_redis.py --dry-run

  # benar-benar menulis (Redis harus kosong untuk kunci UAS)
  UPSTASH_REDIS_REST_URL=... UPSTASH_REDIS_REST_TOKEN=... \
      python3 scripts/migrate_local_to_redis.py --write

  # timpa kunci UAS yang sudah ada (hapus dulu, lalu tulis)
  ... python3 scripts/migrate_local_to_redis.py --write --force
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.storage import (  # noqa: E402
    KILL_KEY, LOG_KEYS, LOG_RETENTION, ORDER_IDS_KEY, STATE_KEY,
    LocalStorage, RedisStorage,
)

BATCH = 200


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _all_keys():
    return [STATE_KEY, ORDER_IDS_KEY, KILL_KEY] + list(LOG_KEYS.values())


def _clear_remote(remote):
    cmds = [["DEL", k] for k in _all_keys()]
    remote.pipeline(cmds)


def migrate(local, remote, write=False, force=False):
    """Salin seluruh state/log. Mengembalikan ringkasan yang bisa dicetak.

    write=False hanya membaca dan menghitung (dry-run).
    """
    state = local.get_state() or {}
    if not state.get("forward_test_start"):
        raise SystemExit("State lokal tidak punya forward_test_start; tidak ada yang bisa dimigrasi.")

    logs = {}
    for kind in LOG_KEYS:
        rows = local.read(kind, limit=0)
        if rows:
            logs[kind] = rows

    order_ids = []
    order_path = os.path.join(local.root, "order_ids.json")
    if os.path.exists(order_path):
        try:
            with open(order_path, "r", encoding="utf-8") as f:
                order_ids = (json.load(f) or {}).get("ids") or []
        except Exception:
            order_ids = []

    kill_on = False
    kill_path = os.path.join(local.root, "kill_switch.json")
    if os.path.exists(kill_path):
        try:
            with open(kill_path, "r", encoding="utf-8") as f:
                kill_on = bool((json.load(f) or {}).get("on"))
        except Exception:
            kill_on = False

    summary = {
        "forward_test_start": state.get("forward_test_start"),
        "tick_count": state.get("tick_count"),
        "logs": {k: len(v) for k, v in logs.items()},
        "order_ids": len(order_ids),
        "kill_on": kill_on,
        "written": False,
    }
    if not write:
        return summary

    existing = remote.pipeline([["EXISTS", k] for k in _all_keys()]) or []
    if any(int(x or 0) for x in existing):
        if not force:
            raise SystemExit(
                "Redis sudah berisi kunci UAS. Hentikan dulu penjadwal cloud, lalu "
                "jalankan dengan --force bila memang ingin menimpa."
            )
        _clear_remote(remote)

    remote.set_state(state)
    for kind, rows in logs.items():
        key = LOG_KEYS.get(kind, "uas:log:" + kind)
        for part in _chunks(rows, BATCH):
            remote.pipeline([["RPUSH", key, json.dumps(r, ensure_ascii=False, separators=(",", ":"))]
                             for r in part])
        remote.pipeline([["LTRIM", key, -LOG_RETENTION, -1]])

    for part in _chunks(order_ids, BATCH):
        remote.pipeline([["SADD", ORDER_IDS_KEY] + [str(x) for x in part]])
    remote.cmd("SET", KILL_KEY, "1" if kill_on else "0")

    # verifikasi baca ulang
    got_state = remote.get_state() or {}
    if got_state.get("forward_test_start") != state.get("forward_test_start"):
        raise SystemExit("Verifikasi gagal: forward_test_start di Redis berbeda.")
    counts = {}
    for kind, rows in logs.items():
        counts[kind] = len(remote.read(kind, limit=0))
        if counts[kind] != len(rows):
            raise SystemExit("Verifikasi gagal: jumlah log %s tidak sama (%d != %d)." % (
                kind, counts[kind], len(rows)))

    summary["written"] = True
    summary["verified_counts"] = counts
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="benar-benar menulis ke Redis")
    ap.add_argument("--force", action="store_true", help="hapus kunci UAS yang sudah ada lalu tulis")
    ap.add_argument("--dry-run", action="store_true", help="hanya tampilkan ringkasan")
    a = ap.parse_args()
    if not a.write and not a.dry_run:
        ap.error("pilih --dry-run atau --write")

    local = LocalStorage()
    url = os.environ.get("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if a.dry_run and (not url or not token):
        # dry-run tetap butuh Redis untuk memeriksa kunci yang sudah ada,
        # tetapi ringkasan lokal bisa dicetak tanpa koneksi.
        fake = type("NoRedis", (), {
            "pipeline": lambda self, cmds: [0] * len(cmds),
        })()
        summary = migrate(local, fake, write=False)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print("\n(dry-run lokal; env Redis belum diset, jadi tidak ada pemeriksaan tujuan)")
        return 0
    if not url or not token:
        raise SystemExit("UPSTASH_REDIS_REST_URL dan UPSTASH_REDIS_REST_TOKEN wajib diset.")

    remote = RedisStorage(url, token)
    summary = migrate(local, remote, write=a.write, force=a.force)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if not a.write:
        print("\n(dry-run: tidak ada yang ditulis)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
