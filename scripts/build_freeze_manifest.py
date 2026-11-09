#!/usr/bin/env python3
"""Buat manifest SHA-256 untuk file yang dibekukan.

Manifest ini adalah bukti bahwa file pada commit freeze tidak berubah. File
metadata (FREEZE.md, LAPORAN_AKHIR.md, project_status.json, log forward) tidak
dimasukkan karena memang boleh berubah setelah freeze.

Keluaran turunan (public/offline_dashboard.html, public/dashboard_data.json,
public/backtest_*.csv) juga tidak dimasukkan. File itu dibangun ulang secara
deterministik dari input yang dibekukan (kode, config, data/backtest_results.json)
ditambah log forward; membangun ulang dashboard bukan perubahan strategi.

Contoh:
  python3 scripts/build_freeze_manifest.py
"""
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "FREEZE_MANIFEST.json")

INCLUDE_DIRS = ["core", "api", "scripts", "tests", "config", ".github", "docs/evidence"]
INCLUDE_FILES = [
    "README.md",
    "requirements.txt",
    "vercel.json",
    ".env.example",
    ".gitignore",
    "docs/METHODOLOGY.md",
    "docs/FORWARD_TEST.md",
    "docs/DEPLOYMENT.md",
    "docs/PERNYATAAN_AI.md",
    "docs/REFLEKSI.md",
    "data/README.md",
    "data/backtest_results.json",
    "data/backtest_trades.csv",
    "data/backtest_equity_daily.csv",
    "data/costs.json",
    "data/universe.json",
    "data/pairs_meta_snapshot.json",
    "public/index.html",
    "public/app.js",
    "public/styles.css",
]
INCLUDE_GLOBS = [
    ("data/raw", ".csv"),
    ("data/raw", ".json"),
    ("data/snapshots", ".jsonl"),
]
EXCLUDE_PARTS = {"__pycache__", ".git", ".vercel"}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def collect():
    files = []
    for d in INCLUDE_DIRS:
        base = os.path.join(ROOT, d)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(x for x in dirnames if x not in EXCLUDE_PARTS)
            for name in sorted(filenames):
                if name.endswith((".py", ".json", ".yml", ".yaml", ".png", ".txt", ".md")):
                    files.append(os.path.join(dirpath, name))
    for f in INCLUDE_FILES:
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            files.append(p)
    for d, ext in INCLUDE_GLOBS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            if name.endswith(ext):
                files.append(os.path.join(base, name))
    seen, out = set(), []
    for p in files:
        r = rel(p)
        if r not in seen and os.path.exists(p):
            seen.add(r)
            out.append(p)
    return sorted(out, key=rel)


def git(args):
    try:
        r = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def main():
    files = collect()
    data = {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "note": "Manifest ini hanya berisi file yang dibekukan. FREEZE.md, LAPORAN_AKHIR.md, project_status.json, dan log forward tidak termasuk karena boleh berubah setelah freeze.",
        "git": {
            "head": git(["rev-parse", "HEAD"]),
            "commit_date": git(["show", "-s", "--format=%cI", "HEAD"]),
            "tag": git(["describe", "--tags", "--exact-match", "HEAD"]),
            "status_short": git(["status", "--short"]),
        },
        "files": {rel(p): sha256(p) for p in files},
        "sizes": {rel(p): os.path.getsize(p) for p in files},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("Manifest: %d file -> %s" % (len(files), OUT))
    print("HEAD    : %s" % (data["git"]["head"] or "belum ada git"))
    if data["git"]["status_short"]:
        print("PERINGATAN: masih ada perubahan belum di-commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
