#!/usr/bin/env python3
"""Bangun dashboard HTML mandiri (offline) dari payload dashboard.

Output:
  public/offline_dashboard.html  -> satu file, data tertanam, bisa dibuka file://
  public/dashboard_data.json     -> payload mentah untuk audit
  public/backtest_trades.csv     -> unduhan trade
  public/backtest_equity_daily.csv

Contoh:
  python3 scripts/build_offline_dashboard.py
  python3 scripts/build_offline_dashboard.py --source url --url https://.../api/dashboard
"""
import argparse
import json
import os
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.bot import dashboard_payload
from core.config import save_json
from core.storage import LocalStorage


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["local", "url"], default="local")
    ap.add_argument("--url", default=None)
    ap.add_argument("--out", default=os.path.join(ROOT, "public", "offline_dashboard.html"))
    a = ap.parse_args()

    if a.source == "url":
        if not a.url:
            raise SystemExit("--url wajib untuk --source url")
        payload = fetch_json(a.url)
    else:
        payload = dashboard_payload(LocalStorage())
        # Data yang sama di-commit ke repo dan dibundel ke Vercel; sebut sumber
        # sebenarnya, bukan sekadar "local", supaya dashboard tidak menyesatkan.
        payload.setdefault("meta", {})["storage"] = "repo git (data/local) + Upstash opsional"

    public = os.path.join(ROOT, "public")
    os.makedirs(public, exist_ok=True)
    save_json(os.path.join(public, "dashboard_data.json"), payload)

    for name in ["backtest_trades.csv", "backtest_equity_daily.csv"]:
        src = os.path.join(ROOT, "data", name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(public, name))

    with open(os.path.join(public, "index.html"), "r", encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(public, "styles.css"), "r", encoding="utf-8") as f:
        css = f.read()
    with open(os.path.join(public, "app.js"), "r", encoding="utf-8") as f:
        js = f.read()

    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data_json = (data_json.replace("</", "<\\/")
                 .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    js = js.replace("</script", "<\\/script")

    html = html.replace('<link rel="stylesheet" href="styles.css">', "<style>\n" + css + "\n</style>")
    inject = ('<script>window.__DASHBOARD_DATA__=' + data_json + ";</script>\n"
              "<script>\n" + js + "\n</script>")
    html = html.replace('<script src="app.js"></script>', inject)

    with open(a.out, "w", encoding="utf-8") as f:
        f.write(html)

    print("Payload  : %d pair, %d trade backtest, %d trade forward" % (
        len((payload.get("meta") or {}).get("universe") or []),
        len((payload.get("backtest") or {}).get("trades") or []),
        len((payload.get("forward") or {}).get("trades") or [])))
    print("Output   : %s (%.1f KB)" % (a.out, os.path.getsize(a.out) / 1024))
    print("CSV      : public/backtest_trades.csv, public/backtest_equity_daily.csv")
    print("Data JSON: public/dashboard_data.json")


if __name__ == "__main__":
    main()
