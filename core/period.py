"""Periode forward test yang disepakati.

Periode ini **bukan** parameter strategi: tidak ada keputusan entry/exit yang
bergantung padanya. Nilainya hanya dipakai untuk menampilkan durasi, sisa
waktu, dan status "selesai/berjalan" pada laporan dan dashboard.

Periode ditetapkan: dari tick forward pertama (yang tercatat otomatis di
`state.forward_test_start`, tidak dimundurkan) sampai **14 November 2026
12:00 WIB** = **2026-11-14T05:00:00Z**.
"""
from datetime import datetime, timezone

from .config import parse_iso

# 14 November 2026 12:00 WIB (UTC+7)
FORWARD_TEST_END = "2026-11-14T05:00:00Z"
FORWARD_TEST_END_WIB = "2026-11-14T12:00:00+07:00"


def forward_period(start=None, now=None):
    """Ringkasan periode forward test.

    Args:
        start: timestamp ISO mulai (`state.forward_test_start`), boleh None.
        now: datetime UTC; default sekarang.

    Returns:
        dict dengan target_end, complete, period_days, elapsed_days,
        remaining_hours.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    end = parse_iso(FORWARD_TEST_END)
    out = {
        "target_end": FORWARD_TEST_END,
        "target_end_wib": FORWARD_TEST_END_WIB,
        "complete": now >= end,
        "period_days": None,
        "elapsed_days": None,
        "remaining_hours": max(0.0, (end - now).total_seconds() / 3600.0),
    }
    started = parse_iso(start) if start else None
    if started:
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        out["period_days"] = (end - started).total_seconds() / 86400.0
        finished = min(now, end)
        out["elapsed_days"] = max(0.0, (finished - started).total_seconds() / 86400.0)
    return out
