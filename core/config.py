"""Konfigurasi dan util waktu.

Semua modul (backtest, bot, dashboard, skrip hitung ulang) membaca aturan dari
config/strategy.json supaya tidak ada duplikasi parameter.
"""
import json
import os
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "strategy.json")
WIB = timezone(timedelta(hours=7), name="WIB")


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def save_json(path, obj):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_strategy(path=None):
    path = path or CONFIG_PATH
    return load_json(path)


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(dt=None):
    dt = dt or utc_now()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def wib_date(dt=None):
    dt = dt or utc_now()
    return dt.astimezone(WIB).strftime("%Y-%m-%d")


def wib_day_start_utc(dt=None):
    """00:00 WIB pada tanggal WIB dari dt, dikembalikan sebagai datetime UTC."""
    dt = (dt or utc_now()).astimezone(WIB)
    start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc)


def parse_timeframe_seconds(value):
    v = str(value).upper().strip()
    if v.endswith("D"):
        return int(float(v[:-1]) * 86400)
    if v.endswith("H"):
        return int(float(v[:-1]) * 3600)
    return int(v) * 60
