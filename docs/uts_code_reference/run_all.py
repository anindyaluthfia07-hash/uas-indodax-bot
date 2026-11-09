#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Jalankan seluruh alur backtest kuantitatif dengan satu perintah:

  Pakai CSV harian:            python3 run_all.py --csv kompas100_harian.csv --freeze 2026-09-01
  Atau unduh ulang dari Yahoo: python3 run_all.py --download --freeze 2026-09-01
"""
import argparse, os, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument("--csv", help="file CSV harga harian (kolom Date,Open,High,Low,Close,Volume,symbol)")
ap.add_argument("--download", action="store_true", help="unduh dari Yahoo Finance (butuh internet + yfinance)")
ap.add_argument("--freeze", default="2026-09-01", help="tanggal pembekuan strategi, default 2026-09-01")
a = ap.parse_args()
py = sys.executable

csv_file = a.csv
if not a.download and not csv_file:
    if not os.path.exists(os.path.join("data", "prices.csv")):
        candidates = [
            "kompas100_harian.csv",
            os.path.join("..", "Data awal", "kompas100_harian.csv"),
            os.path.join("Data awal", "kompas100_harian.csv"),
        ]
        for c in candidates:
            if os.path.exists(c):
                csv_file = c
                print(f"Mendeteksi file CSV data: {c}")
                break

if a.download:
    steps = [[py, "download_data.py"]]
elif csv_file:
    steps = [[py, "prepare_data.py", csv_file, "data"]]
elif not os.path.exists(os.path.join("data", "prices.csv")):
    sys.exit("File data harga belum ditemukan. Masukkan parameter --csv <path_ke_file_csv> atau letakkan kompas100_harian.csv di folder aktif.")
else:
    steps = []

steps += [
    [py, "backtest.py", "--data", "data", "--out", "results.json", "--freeze", a.freeze],
    [py, "build_dashboard.py", "--results", "results.json"]
]

for s in steps:
    print("\n>>> " + " ".join(s), flush=True)
    if subprocess.call(s) != 0:
        sys.exit("Gagal di langkah: " + " ".join(s))

print("\nSELESAI. Buka UTS_25110200036_AnindyaRahmaLuthfia.html di browser (dobel klik).")
