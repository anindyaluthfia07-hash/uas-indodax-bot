"""Perhitungan metrik dari equity curve dan daftar trade.

Dipakai oleh backtest, bot, dashboard, dan skrip hitung ulang supaya satu angka
hanya punya satu definisi.
"""
import math
from datetime import datetime, timezone


def _to_epoch(t):
    if isinstance(t, (int, float)):
        return float(t)
    if isinstance(t, datetime):
        return t.timestamp()
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def max_drawdown(equity_values, initial_capital):
    peak = float(initial_capital)
    worst = 0.0
    for v in equity_values:
        v = float(v)
        if v > peak:
            peak = v
        if peak > 0:
            dd = v / peak - 1.0
            if dd < worst:
                worst = dd
    return worst


def compute_metrics(equity_points, trades, initial_capital=100000000.0,
                    start=None, end=None, include_cagr=True):
    """equity_points: list dict {t, equity}. trades: list dict dengan net_pnl."""
    eq = [float(p["equity"]) for p in equity_points if p.get("equity") is not None]
    initial = float(initial_capital)
    final = eq[-1] if eq else initial
    if start is None and equity_points:
        start = equity_points[0].get("t")
    if end is None and equity_points:
        end = equity_points[-1].get("t")
    t0, t1 = _to_epoch(start), _to_epoch(end)
    years = max((t1 - t0) / (365.25 * 86400.0), 0.0) if (t0 is not None and t1 is not None) else 0.0
    total_return = final / initial - 1.0 if initial else None
    cagr = None
    if include_cagr and years > (1.0 / 365.25) and final > 0 and initial > 0:
        try:
            cagr = (final / initial) ** (1.0 / years) - 1.0
        except (OverflowError, ValueError, ZeroDivisionError):
            cagr = None

    nets = [float(t.get("net_pnl") or 0.0) for t in trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (None if not wins else float("inf"))
    pct_wins = [float(t.get("net_pct") or 0.0) for t in trades if float(t.get("net_pnl") or 0.0) > 0]
    pct_losses = [float(t.get("net_pct") or 0.0) for t in trades if float(t.get("net_pnl") or 0.0) <= 0]
    fees = sum(float(t.get("fee_total") or 0.0) for t in trades)
    spread = sum(float(t.get("spread_cost") or 0.0) for t in trades)
    slip = sum(float(t.get("slippage_cost") or 0.0) for t in trades)
    gross_pnl = sum(float(t.get("gross_pnl") or 0.0) for t in trades)
    total_costs = fees + spread + slip
    denominator = sum(max(0.0, float(t.get("gross_pnl") or 0.0)) for t in trades)
    return {
        "initial_capital": initial,
        "final_equity": final,
        "total_return": total_return,
        "total_return_pct": (total_return * 100.0) if total_return is not None else None,
        "cagr": cagr,
        "cagr_pct": (cagr * 100.0) if cagr is not None else None,
        "max_drawdown": max_drawdown(eq, initial),
        "max_drawdown_pct": max_drawdown(eq, initial) * 100.0,
        "profit_factor": pf,
        "win_rate": (len(wins) / len(nets)) if nets else None,
        "win_rate_pct": (len(wins) / len(nets) * 100.0) if nets else None,
        "trades": len(nets),
        "wins": len(wins),
        "losses": len(losses),
        "avg_win_idr": (sum(wins) / len(wins)) if wins else None,
        "avg_loss_idr": (sum(losses) / len(losses)) if losses else None,
        "avg_win_pct": (sum(pct_wins) / len(pct_wins)) if pct_wins else None,
        "avg_loss_pct": (sum(pct_losses) / len(pct_losses)) if pct_losses else None,
        "gross_profit_idr": gross_profit,
        "gross_loss_idr": gross_loss,
        "gross_pnl_idr": gross_pnl,
        "net_pnl_idr": sum(nets),
        "fee_idr": fees,
        "spread_cost_idr": spread,
        "slippage_cost_idr": slip,
        "total_cost_idr": total_costs,
        "cost_share_of_gross_profit": (total_costs / denominator) if denominator > 0 else None,
        "years": years,
        "start": start,
        "end": end,
        "cagr_note": None if include_cagr else "CAGR tidak dihitung untuk periode forward test pendek",
    }


def buy_and_hold(bars, initial_capital, fee_buy_pct, fee_sell_pct,
                 half_spread_pct=0.0, slippage_pct=0.0):
    """Benchmark beli di open pertama, nilai di close, likuidasi di close terakhir."""
    if not bars:
        return {"equity": [], "metrics": None}
    first, last = bars[0], bars[-1]
    entry = float(first["open"]) * (1.0 + half_spread_pct + slippage_pct)
    units = float(initial_capital) / (entry * (1.0 + fee_buy_pct))
    points = []
    exit_mult = (1.0 - half_spread_pct - slippage_pct) * (1.0 - fee_sell_pct)
    for b in bars:
        points.append({"t": int(b["time"]), "equity": units * float(b["close"]) * exit_mult})
    # nilai akhir memakai close terakhir (bukan open) dikurangi biaya likuidasi
    metrics = compute_metrics(points, [], initial_capital,
                              start=int(first["time"]), end=int(last["time"]),
                              include_cagr=True)
    return {"equity": points, "metrics": metrics, "units": units,
            "entry_fill": entry, "exit_value": points[-1]["equity"]}


def compute_uptime(decisions, forward_start, forward_end, tf_seconds, now_ts=None, pairs=None):
    """Uptime = candle per pair yang diproses sebelum candle berikutnya ditutup
    dibagi jumlah candle × jumlah pair yang diharapkan.

    pairs: daftar pair di universe. Bila tidak diberikan, pair disimpulkan dari
    log keputusan (bisa kurang lengkap bila ada pair yang tidak pernah tercatat).
    """
    if forward_start is None:
        return {"expected": 0, "on_time": 0, "uptime": None, "details": []}
    start = _to_epoch(forward_start)
    end = _to_epoch(forward_end) if forward_end else (now_ts or datetime.now(timezone.utc).timestamp())
    tf = int(tf_seconds)
    # Candle pertama yang ditutup setelah forward_start: open = floor(start/tf)*tf.
    # Contoh start 15:18 -> candle 12:00 yang tutup 16:00, bukan candle 16:00.
    first_open = int(math.floor(start / tf) * tf)
    while first_open + tf <= start:
        first_open += tf
    opens = []
    t = first_open
    while t + tf <= end + 1e-6:
        opens.append(t)
        t += tf
    log_pairs = set(d.get("pair") for d in decisions if d.get("pair"))
    pair_set = set(pairs) if pairs else (log_pairs or {None})
    on_time = set()
    seen = set()
    for d in decisions:
        ct = d.get("candle_time")
        if ct is None:
            continue
        ct = int(ct)
        key = (d.get("pair"), ct)
        seen.add(key)
        pa = d.get("processed_at_epoch")
        if pa is None and d.get("processed_at"):
            pa = _to_epoch(d.get("processed_at"))
        if pa is None:
            pa = _to_epoch(d.get("at"))
        # Candle diproses setelah tutup (ct+tf); tepat waktu bila masih sebelum
        # candle berikutnya tutup (ct+2*tf), bukan sebelum candle itu sendiri tutup.
        if pa is not None and ct in opens and pa < ct + 2 * tf:
            on_time.add(key)
    details = [{"candle_time": t, "on_time": t in on_time} for t in opens]
    expected = len(opens) * len(pair_set)
    return {
        "expected": expected,
        "on_time": len(on_time),
        "uptime": (len(on_time) / float(expected)) if expected else None,
        "processed_candles": len(seen),
        "pairs": sorted(str(p) for p in pair_set),
        "details": details,
        "definition": "candle per pair dihitung tepat waktu bila diproses setelah candle tutup (open+tf) dan sebelum candle berikutnya tutup (open+2*tf)",
    }
