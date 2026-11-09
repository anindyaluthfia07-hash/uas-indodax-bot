"""Aturan strategi tunggal yang dipakai backtest DAN bot dry-run.

Aturan (adaptasi langsung dari strategi UTS):
  MASUK (dihitung pada penutupan candle t):
    1. close[t] > highest(high[t-lookback : t])   -> Donchian breakout
    2. close[t] > EMA_trend[t]
    3. EMA_fast[t] > EMA_trend[t]
    4. volume[t] > 0 dan ADV20[t] > 0
  KELUAR (dihitung pada penutupan candle t):
    a. time stop: bars_held >= time_stop_bars dan return <= time_stop_loss_pct
    b. trailing stop ATR: close[t] < stop, stop = max(stop_lama, close-ATR_MULT*ATR)
    c. EMA_fast memotong ke bawah EMA_trend
  Eksekusi selalu pada bar berikutnya (backtest: open t+1; bot: bid/ask live
  segera setelah candle t ditutup). Tidak ada short/margin/leverage.
"""
from .indicators import atr_series, ema_series, rolling_max_prev


class StrategyEngine:
    def __init__(self, bars, params):
        if not bars:
            raise ValueError("bars kosong")
        self.bars = bars
        self.p = dict(params)
        self.close = [float(b["close"]) for b in bars]
        self.high = [float(b["high"]) for b in bars]
        self.low = [float(b["low"]) for b in bars]
        self.volume = [float(b.get("volume") or 0.0) for b in bars]
        self.times = [int(b["time"]) for b in bars]
        self.ema_fast = ema_series(self.close, int(params["fast_ema"]))
        self.ema_trend = ema_series(self.close, int(params["trend_ema"]))
        self.atr = atr_series(bars, int(params["atr_period"]))
        self.donchian = rolling_max_prev(self.high, int(params["lookback"]))
        adv_n = int(params.get("adv_bars", 20))
        qv = [c * v for c, v in zip(self.close, self.volume)]
        self.adv = [None] * len(qv)
        running = 0.0
        for i, v in enumerate(qv):
            running += v
            if i >= adv_n:
                running -= qv[i - adv_n]
            if i >= adv_n - 1:
                self.adv[i] = running / float(adv_n)
        self.warmup = max(
            int(params["lookback"]) + 1,
            int(params["trend_ema"]),
            int(params["atr_period"]) + 1,
            int(params.get("adv_bars", 20)),
        )

    def _valid(self, i):
        return (0 <= i < len(self.bars)
                and self.close[i] > 0 and self.high[i] > 0 and self.low[i] > 0
                and self.volume[i] > 0)

    def entry_signal(self, i):
        if i < self.warmup or not self._valid(i):
            return False
        h = self.donchian[i]
        ef, et = self.ema_fast[i], self.ema_trend[i]
        if h is None or ef is None or et is None or self.adv[i] is None:
            return False
        return (self.close[i] > h
                and self.close[i] > et
                and ef > et
                and self.adv[i] > 0)

    def initial_stop(self, i):
        a = self.atr[i]
        if a is None:
            return None
        return self.close[i] - float(self.p["atr_mult"]) * a

    def exit_signal(self, i, position):
        """Kembalikan (reason, new_stop). reason None = tetap pegang."""
        if not self._valid(i):
            return None, position.get("stop")
        c = self.close[i]
        stop = position.get("stop")
        held = i - int(position["entry_i"])
        reason = None

        if held >= int(self.p["time_stop_bars"]):
            ret = c / float(position["entry_fill"]) - 1.0
            if ret <= float(self.p["time_stop_loss_pct"]):
                reason = "time_stop"

        if reason is None and stop is not None and c < float(stop):
            reason = "atr_trailing_stop"

        if reason is None and i > 0:
            ef, et = self.ema_fast[i], self.ema_trend[i]
            ef0, et0 = self.ema_fast[i - 1], self.ema_trend[i - 1]
            if None not in (ef, et, ef0, et0) and ef < et and ef0 >= et0:
                reason = "ema_cross_exit"

        new_stop = stop
        if reason is None:
            a = self.atr[i]
            if a is not None:
                cand = c - float(self.p["atr_mult"]) * a
                if stop is None or cand > float(stop):
                    new_stop = cand
        return reason, new_stop

    def snapshot(self, i):
        """Ringkasan sinyal untuk log keputusan (bukan untuk eksekusi)."""
        return {
            "time": self.times[i] if 0 <= i < len(self.times) else None,
            "close": self.close[i] if 0 <= i < len(self.close) else None,
            "donchian_high": self.donchian[i] if 0 <= i < len(self.donchian) else None,
            "ema_fast": self.ema_fast[i] if 0 <= i < len(self.ema_fast) else None,
            "ema_trend": self.ema_trend[i] if 0 <= i < len(self.ema_trend) else None,
            "atr": self.atr[i] if 0 <= i < len(self.atr) else None,
            "adv20_idr": self.adv[i] if 0 <= i < len(self.adv) else None,
            "entry_signal": self.entry_signal(i) if 0 <= i < len(self.bars) else False,
        }


def entry_reasons(engine, i):
    """Penjelasan per komponen sinyal masuk, untuk audit log."""
    if i < 0 or i >= len(engine.bars):
        return {}
    c = engine.close[i]
    h = engine.donchian[i]
    ef, et = engine.ema_fast[i], engine.ema_trend[i]
    return {
        "breakout": bool(h is not None and c > h),
        "above_trend_ema": bool(et is not None and c > et),
        "fast_above_trend": bool(ef is not None and et is not None and ef > et),
        "volume_positive": bool(engine.volume[i] > 0),
        "adv_positive": bool(engine.adv[i] is not None and engine.adv[i] > 0),
    }
