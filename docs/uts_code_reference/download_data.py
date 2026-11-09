#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Langkah 1 — Unduh harga harian saham Kompas100 + IHSG (^JKSE) dari Yahoo Finance.

    python3 download_data.py            # default 11 tahun (10 tahun uji + 1 tahun pemanasan indikator)

Hasil:
    data/prices.csv   kolom: date,ticker,open,high,low,close,volume
    data/_meta.json   sumber data, tanggal unduh, daftar saham yang gagal

Catatan harga: kolom 'close' dari Yahoo (auto_adjust=False) sudah disesuaikan untuk
stock split, tetapi TIDAK disesuaikan dividen. Dividen tidak dihitung (lihat README).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

# Komponen Kompas100 (sumber daftar nama: id.investing.com/indices/kompas-100-components,
# dicocokkan ke kode saham). Ini anggota SAAT INI -> ada survivorship bias (dijelaskan di dashboard).
KOMPAS100 = (
    "EMTK ACES ADRO AKRA ANTM ASII BNBR BBNI BMRI BBRI "
    "BBTN BRPT BIPI BFIN BBCA BULL BUVA BRMS BUMI BSDE "
    "TPIA CPIN CTRA DEWA DSNG ELSA ENRG ERAA GGRM HRUM "
    "INKP INDY ITMG ICBP INDF ISAT PSAB JPFA JSMR KIJA "
    "KLBF LSIP MYOR MEDC MAPI KPIG PGAS PWON PNLF PTRO "
    "RAJA TOWR SMGR BKSL AMRT SMRA SCMA ESSA SSIA PTBA "
    "TLKM TINS TOBA UNVR UNTR INCO EXCL IMPC BBYB MIKA "
    "MDKA ARTO MINA HRTA BRIS HEAL MAPA PANI SGER TAPG "
    "ARCI BUKA WIFI CMRY RMKE ADMR WIRG GOTO PGEO CUAN "
    "NCKL MBMA SMIL AMMN INET AADI RATU CBDK COIN EMAS"
).split()
BENCH = "^JKSE"


def fetch_one(sym, start, tries=3):
    for k in range(tries):
        try:
            h = yf.Ticker(sym).history(start=start, interval="1d", auto_adjust=False, actions=False)
            if h is not None and len(h) > 0:
                return h
        except Exception as e:  # noqa
            print("   %s percobaan %d gagal: %s" % (sym, k + 1, e), file=sys.stderr)
        time.sleep(1.5 * (k + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=11.0, help="panjang data yang diunduh (tahun)")
    ap.add_argument("--out", default="data")
    a = ap.parse_args()

    os.makedirs(a.out, exist_ok=True)
    start = (datetime.now() - timedelta(days=int(a.years * 365.25))).strftime("%Y-%m-%d")
    rows, ok, failed = [], [], []
    syms = [s + ".JK" for s in KOMPAS100] + [BENCH]
    for i, sym in enumerate(syms, 1):
        h = fetch_one(sym, start)
        if h is None:
            failed.append(sym)
            print("[%3d/%d] %-9s TIDAK ADA DATA" % (i, len(syms), sym))
            continue
        d = h.index.strftime("%Y-%m-%d")
        df = pd.DataFrame({
            "date": d, "ticker": sym,
            "open": h["Open"].values, "high": h["High"].values, "low": h["Low"].values,
            "close": h["Close"].values, "volume": h["Volume"].values,
        })
        df = df.dropna(subset=["close"])
        rows.append(df)
        ok.append(sym)
        print("[%3d/%d] %-9s %d baris (%s s/d %s)" % (i, len(syms), sym, len(df), df["date"].iloc[0], df["date"].iloc[-1]))

    if not rows:
        print("Tidak ada data yang berhasil diunduh. Cek koneksi internet.", file=sys.stderr)
        sys.exit(1)
    allp = pd.concat(rows, ignore_index=True)
    allp.to_csv(os.path.join(a.out, "prices.csv"), index=False)
    meta = {
        "source": "Yahoo Finance (via yfinance %s)" % getattr(yf, "__version__", "?"),
        "download_datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "download_date": datetime.now().strftime("%Y-%m-%d"),
        "start_requested": start,
        "price_basis": "Close disesuaikan stock split, tanpa penyesuaian dividen",
        "tickers_ok": [s for s in ok if s != BENCH],
        "tickers_failed": failed,
        "bench_ok": BENCH in ok,
        "synthetic": False,
    }
    with open(os.path.join(a.out, "_meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("\nSelesai: %d saham + IHSG tersimpan di %s/prices.csv" % (len([s for s in ok if s != BENCH]), a.out))
    if failed:
        print("TIDAK ADA DATA untuk: " + ", ".join(failed))
        print("(Kode ini dilewati dari backtest. Catat di bagian keterbatasan dashboard.)")


if __name__ == "__main__":
    main()
