#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Langkah 1 (alternatif): ubah file CSV Yahoo Finance milik sendiri (kompas100_harian.csv)
menjadi data/prices.csv yang dipakai backtest.py.

    python3 prepare_data.py kompas100_harian.csv
"""
import json, os, sys
from datetime import datetime
import pandas as pd

src = sys.argv[1] if len(sys.argv) > 1 else "kompas100_harian.csv"
out = sys.argv[2] if len(sys.argv) > 2 else "data"
d = pd.read_csv(src)
d = d.rename(columns={"Date": "date", "Open": "open", "High": "high", "Low": "low",
                      "Close": "close", "Volume": "volume", "symbol": "ticker"})
d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
d = d.dropna(subset=["close"]).drop_duplicates(["date", "ticker"]).sort_values(["ticker", "date"])
os.makedirs(out, exist_ok=True)
d[["date", "ticker", "open", "high", "low", "close", "volume"]].to_csv(os.path.join(out, "prices.csv"), index=False)
st = sorted(t for t in d["ticker"].unique() if t != "^JKSE")
json.dump({"source": "Yahoo Finance (yfinance), file %s" % os.path.basename(src),
           "download_datetime": datetime.fromtimestamp(os.path.getmtime(src)).strftime("%Y-%m-%d %H:%M:%S"),
           "price_basis": "Harga disesuaikan (split & dividen) dari Yahoo Finance, auto_adjust",
           "tickers_ok": st, "tickers_failed": [], "bench_ok": "^JKSE" in set(d["ticker"]),
           "synthetic": False}, open(os.path.join(out, "_meta.json"), "w"), indent=1)
print("OK: %d saham, %s s/d %s, %d baris -> %s/prices.csv" % (len(st), d["date"].min(), d["date"].max(), len(d), out))
