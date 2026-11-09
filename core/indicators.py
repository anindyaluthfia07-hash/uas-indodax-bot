"""Indikator teknikal murni Python (tanpa numpy/pandas).

Dibuat sendiri supaya backtest dan bot memakai implementasi yang persis sama
dan supaya fungsi Vercel tidak membutuhkan dependency berat.
"""


def ema_series(values, period):
    """EMA dengan alpha = 2/(period+1), seed = nilai valid pertama.

    Sama dengan pandas ewm(span=period, adjust=False) untuk data tanpa NaN.
    """
    out = [None] * len(values)
    if period <= 0:
        raise ValueError("period harus > 0")
    alpha = 2.0 / (period + 1.0)
    prev = None
    for i, v in enumerate(values):
        if v is None:
            out[i] = prev
            continue
        prev = float(v) if prev is None else alpha * float(v) + (1.0 - alpha) * prev
        out[i] = prev
    return out


def atr_series(bars, period):
    """ATR memakai EMA atas True Range dengan alpha = 1/period.

    Sama dengan ewm(alpha=1/ATR_N, adjust=False) pada kode UTS.
    """
    n = len(bars)
    out = [None] * n
    if n == 0:
        return out
    alpha = 1.0 / float(period)
    prev_close = None
    prev_atr = None
    for i, b in enumerate(bars):
        high, low, close = float(b["high"]), float(b["low"]), float(b["close"])
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        prev_atr = tr if prev_atr is None else alpha * tr + (1.0 - alpha) * prev_atr
        out[i] = prev_atr
        prev_close = close
    return out


def rolling_max_prev(values, n):
    """Nilai tertinggi dari n bar SEBELUM bar i (tidak termasuk bar i).

    Implementasi deque O(n). Ini yang mencegah look-ahead: breakout dihitung
    terhadap high historis, bukan high bar yang sedang dievaluasi.
    """
    from collections import deque

    out = [None] * len(values)
    dq = deque()
    for i, v in enumerate(values):
        # dq menyimpan index dengan values menurun, untuk jendela [i-n, i)
        if i >= n:
            out[i] = values[dq[0]] if dq else None
        if v is None:
            continue
        while dq and values[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
        # buang index yang sudah keluar dari jendela untuk i+1
        while dq and dq[0] <= i - n:
            dq.popleft()
    return out


def rolling_mean_inclusive(values, n, i):
    """Rata-rata n nilai terakhir sampai i (termasuk i). None bila belum cukup."""
    if i < n - 1:
        return None
    window = values[i - n + 1:i + 1]
    if any(v is None for v in window):
        return None
    return sum(float(v) for v in window) / float(n)
