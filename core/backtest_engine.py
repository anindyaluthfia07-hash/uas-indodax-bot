"""Mesin backtest portofolio multi-pair.

Aturan eksekusi:
  - sinyal dihitung pada CLOSE candle t
  - order dieksekusi pada OPEN candle t+1 (default; delay_bars bisa 1 untuk uji)
  - beli di ask sintetis = open*(1+half_spread), lalu slippage
  - jual di bid sintetis = open*(1-half_spread), lalu slippage
  - fee taker all-in terpisah
  - tidak ada short, margin, atau leverage
"""
import math
from datetime import datetime, timezone

from .config import WIB
from .metrics import compute_metrics, buy_and_hold
from .strategy import StrategyEngine, entry_reasons

TF_SECONDS = 14400


def iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pair_costs(costs, pair):
    p = (costs.get("pairs") or {}).get(pair) or {}
    fb = costs.get("fallback") or {}
    return {
        "half_spread": p.get("half_spread") if p.get("half_spread") is not None else fb.get("half_spread", 0.0025),
        "slippage_buy": p.get("slippage_buy") if p.get("slippage_buy") is not None else fb.get("slippage_buy", 0.002),
        "slippage_sell": p.get("slippage_sell") if p.get("slippage_sell") is not None else fb.get("slippage_sell", 0.002),
    }


def round_tick(price, tick, side):
    if not tick or tick <= 0:
        return price
    if side == "buy":
        return math.ceil(price / tick) * tick
    return math.floor(price / tick) * tick


def execution(side, ref_price, qty, half_spread, slippage, fee_pct, tick=None):
    """Return dict fill, spread_cost, slippage_cost, fee, notional."""
    if side == "buy":
        best = ref_price * (1.0 + half_spread)
        fill = best * (1.0 + slippage)
        if tick:
            fill = round_tick(fill, tick, "buy")
        spread_cost = qty * (best - ref_price)
        slippage_cost = qty * (fill - best)
        fee = qty * fill * fee_pct
    else:
        best = ref_price * (1.0 - half_spread)
        fill = best * (1.0 - slippage)
        if tick:
            fill = round_tick(fill, tick, "sell")
        spread_cost = qty * (ref_price - best)
        slippage_cost = qty * (best - fill)
        fee = qty * fill * fee_pct
    return {"fill": fill, "spread_cost": spread_cost, "slippage_cost": slippage_cost,
            "fee": fee, "notional": qty * fill}


def daily_points(equity_points, initial_capital):
    """Equity pada panggilan pertama setelah 00:00 WIB tiap hari."""
    by_day = {}
    for p in equity_points:
        d = datetime.fromtimestamp(int(p["t"]), WIB).strftime("%Y-%m-%d")
        if d not in by_day:
            by_day[d] = p
    return [{"date_wib": d, "t": by_day[d]["t"], "equity": by_day[d]["equity"]} for d in sorted(by_day)]


def run_backtest(data, cfg, costs, start_ts, end_ts, params=None, fee_mult=1.0,
                 cost_mult=1.0, delay_bars=0, collect_orders=False, pairs_meta=None,
                 with_benchmark=True):
    params = params or cfg["params"]
    universe = [p for p in cfg["universe"] if p in data and len(data[p]) > 50]
    if not universe:
        raise ValueError("universe kosong / data tidak cukup")
    tf_sec = int(cfg["timeframe_seconds"])
    initial = float(cfg["capital_idr"])
    fee_buy = float(cfg["fees"]["buy_pct"]) * fee_mult
    fee_sell = float(cfg["fees"]["sell_pct"]) * fee_mult
    max_pos = int(cfg["max_positions"])
    pos_frac = float(cfg["position_fraction"])
    max_part = float(cfg["max_participation_adv"])
    min_order = float(cfg["min_order_idr"])
    qty_inc = 1e-8
    pairs_meta = pairs_meta or {}

    engines = {p: StrategyEngine(data[p], params) for p in universe}
    idx_by_time = {p: {int(b["time"]): i for i, b in enumerate(data[p])} for p in universe}
    timeline = sorted({int(b["time"]) for p in universe for b in data[p]
                       if start_ts <= int(b["time"]) <= end_ts})
    if not timeline:
        raise ValueError("tidak ada bar pada periode")

    cash = initial
    positions = {}
    pending_buy = {}
    pending_sell = {}
    last_close = {}
    equity_points = []
    trades = []
    orders = []
    skipped = {"no_slot": 0, "no_cash_or_min_order": 0, "no_next_bar": 0, "invalid": 0}
    decision_counts = {"entry_signals": 0, "exit_signals": 0}

    def next_time(pair, i):
        if i + 1 < len(data[pair]):
            return int(data[pair][i + 1]["time"])
        return None

    for t in timeline:
        # ---------- 1. eksekusi SELL yang jatuh tempo ----------
        for pair in list(pending_sell.keys()):
            po = pending_sell[pair]
            if po["due"] != t:
                continue
            if pair not in positions:
                del pending_sell[pair]
                continue
            pos = positions[pair]
            i = idx_by_time[pair].get(t)
            if i is None:
                continue
            c = pair_costs(costs, pair)
            ref = float(data[pair][i]["open"])
            tick = (pairs_meta.get(pair) or {}).get("pricescale") or None
            ex = execution("sell", ref, pos["qty"], c["half_spread"] * cost_mult,
                           c["slippage_sell"] * cost_mult, fee_sell, tick)
            proceeds = ex["notional"] - ex["fee"]
            cash += proceeds
            gross = pos["qty"] * (ref - pos["entry_ref"])
            spread_cost = pos["entry_spread_cost"] + ex["spread_cost"]
            slip_cost = pos["entry_slippage_cost"] + ex["slippage_cost"]
            fee_total = pos["entry_fee"] + ex["fee"]
            net = gross - fee_total - spread_cost - slip_cost
            trades.append({
                "pair": pair,
                "entry_time": iso(pos["entry_time"]),
                "exit_time": iso(t),
                "qty": pos["qty"],
                "entry_ref": pos["entry_ref"],
                "entry_fill": pos["entry_fill"],
                "exit_ref": ref,
                "exit_fill": ex["fill"],
                "gross_pnl": gross,
                "fee_entry": pos["entry_fee"],
                "fee_exit": ex["fee"],
                "fee_total": fee_total,
                "spread_cost": spread_cost,
                "slippage_cost": slip_cost,
                "net_pnl": net,
                "net_pct": (net / (pos["qty"] * pos["entry_ref"])) * 100.0 if pos["qty"] and pos["entry_ref"] else 0.0,
                "holding_bars": i - pos["entry_i"],
                "exit_reason": po["reason"],
                "entry_equity": pos["entry_equity"],
                "notional_entry": pos["qty"] * pos["entry_ref"],
            })
            del positions[pair]
            del pending_sell[pair]
            if collect_orders:
                orders.append({"time": iso(t), "pair": pair, "side": "sell", "qty": pos["qty"],
                               "ref_price": ref, "fill_price": ex["fill"], "fee": ex["fee"],
                               "spread_cost": ex["spread_cost"], "slippage_cost": ex["slippage_cost"],
                               "reason": po["reason"], "signal_time": iso(po["signal_time"])})

        # ---------- 2. eksekusi BUY yang jatuh tempo ----------
        for pair in sorted(list(pending_buy.keys()), key=lambda p: -pending_buy[p]["priority"]):
            po = pending_buy[pair]
            if po["due"] != t:
                continue
            del pending_buy[pair]
            if pair in positions or len(positions) >= max_pos:
                skipped["no_slot"] += 1
                continue
            i = idx_by_time[pair].get(t)
            if i is None:
                continue
            c = pair_costs(costs, pair)
            ref = float(data[pair][i]["open"])
            tick = (pairs_meta.get(pair) or {}).get("pricescale") or None
            target = min(po["equity"] * pos_frac, po["adv"] * max_part, cash)
            if target < min_order:
                skipped["no_cash_or_min_order"] += 1
                continue
            # qty dari target notional; fill dihitung dulu untuk fee
            probe = execution("buy", ref, 1.0, c["half_spread"] * cost_mult,
                              c["slippage_buy"] * cost_mult, fee_buy, tick)
            unit_cost = probe["fill"] * (1.0 + fee_buy)
            qty = math.floor((target / unit_cost) / qty_inc) * qty_inc
            if qty <= 0 or qty * probe["fill"] < min_order:
                skipped["no_cash_or_min_order"] += 1
                continue
            # batasi agar cash cukup
            if qty * unit_cost > cash:
                qty = math.floor((cash / unit_cost) / qty_inc) * qty_inc
            if qty <= 0 or qty * probe["fill"] < min_order:
                skipped["no_cash_or_min_order"] += 1
                continue
            ex = execution("buy", ref, qty, c["half_spread"] * cost_mult,
                           c["slippage_buy"] * cost_mult, fee_buy, tick)
            total = ex["notional"] + ex["fee"]
            if total > cash + 1e-6:
                skipped["no_cash_or_min_order"] += 1
                continue
            cash -= total
            positions[pair] = {
                "qty": qty, "entry_ref": ref, "entry_fill": ex["fill"],
                "entry_fee": ex["fee"], "entry_spread_cost": ex["spread_cost"],
                "entry_slippage_cost": ex["slippage_cost"], "entry_i": i,
                "entry_time": t, "entry_equity": po["equity"],
                "stop": po["stop"],
            }
            if collect_orders:
                orders.append({"time": iso(t), "pair": pair, "side": "buy", "qty": qty,
                               "ref_price": ref, "fill_price": ex["fill"], "fee": ex["fee"],
                               "spread_cost": ex["spread_cost"], "slippage_cost": ex["slippage_cost"],
                               "reason": "entry", "signal_time": iso(po["signal_time"])})

        # ---------- 3. mark-to-market pada close t ----------
        for pair in universe:
            i = idx_by_time[pair].get(t)
            if i is not None:
                last_close[pair] = float(data[pair][i]["close"])
        invested = sum(pos["qty"] * last_close.get(pair, pos["entry_ref"])
                       for pair, pos in positions.items())
        equity = cash + invested
        equity_points.append({"t": t, "equity": equity, "cash": cash,
                              "positions": len(positions),
                              "invested": invested})

        # ---------- 4. evaluasi EXIT pada close t ----------
        for pair in universe:
            i = idx_by_time[pair].get(t)
            if i is None or pair not in positions or pair in pending_sell:
                continue
            pos = positions[pair]
            eng = engines[pair]
            reason, new_stop = eng.exit_signal(i, pos)
            pos["stop"] = new_stop
            if reason:
                due = next_time(pair, i + delay_bars)
                if due is None or due > end_ts:
                    skipped["no_next_bar"] += 1
                    continue
                pending_sell[pair] = {"due": due, "reason": reason, "signal_time": t}
                decision_counts["exit_signals"] += 1

        # ---------- 5. evaluasi ENTRY pada close t ----------
        free = max_pos - len(positions) - len(pending_buy)
        if free > 0:
            cand = []
            held = set(positions.keys()) | set(pending_buy.keys()) | set(pending_sell.keys())
            for pair in universe:
                i = idx_by_time[pair].get(t)
                if i is None or pair in held:
                    continue
                eng = engines[pair]
                if not eng.entry_signal(i):
                    continue
                decision_counts["entry_signals"] += 1
                adv = eng.adv[i] or 0.0
                strength = (eng.close[i] / eng.donchian[i] - 1.0) if eng.donchian[i] else 0.0
                cand.append((strength, pair, i, adv))
            cand.sort(key=lambda x: -x[0])
            if len(cand) > free:
                skipped["no_slot"] += len(cand) - free
            for strength, pair, i, adv in cand[:free]:
                due = next_time(pair, i + delay_bars)
                if due is None or due > end_ts:
                    skipped["no_next_bar"] += 1
                    continue
                eng = engines[pair]
                pending_buy[pair] = {
                    "due": due, "signal_time": t, "equity": equity, "adv": adv,
                    "stop": eng.initial_stop(i), "priority": strength,
                }

    # ---------- posisi terbuka pada akhir ----------
    open_positions = []
    for pair, pos in positions.items():
        i = idx_by_time[pair].get(timeline[-1])
        last = last_close.get(pair, pos["entry_ref"])
        unreal = pos["qty"] * (last - pos["entry_fill"]) - pos["entry_fee"]
        open_positions.append({
            "pair": pair, "qty": pos["qty"], "entry_time": iso(pos["entry_time"]),
            "entry_fill": pos["entry_fill"], "last_price": last,
            "value": pos["qty"] * last, "unrealized_pnl": unreal,
            "unrealized_pct": (unreal / (pos["qty"] * pos["entry_fill"] + pos["entry_fee"])) * 100.0,
            "stop": pos["stop"],
        })

    metrics = compute_metrics(equity_points, trades, initial, start=timeline[0],
                              end=timeline[-1], include_cagr=True)
    daily = daily_points(equity_points, initial)
    # drawdown harian
    peak = initial
    dd_series = []
    for p in equity_points:
        peak = max(peak, p["equity"])
        dd_series.append(p["equity"] / peak - 1.0)

    # benchmark BTC
    bpair = cfg.get("benchmark_pair", "btcidr")
    bench = {"pair": bpair, "metrics": None, "equity": []}
    if with_benchmark and bpair in data:
        bb = [b for b in data[bpair] if start_ts <= int(b["time"]) <= end_ts]
        if len(bb) > 5:
            c = pair_costs(costs, bpair)
            bh = buy_and_hold(bb, initial, fee_buy, fee_sell,
                              c["half_spread"] * cost_mult, c["slippage_buy"] * cost_mult)
            bench = {"pair": bpair, "metrics": bh["metrics"],
                     "equity": [{"t": p["t"], "equity": p["equity"]} for p in bh["equity"]]}

    return {
        "params": params,
        "universe": universe,
        "start": iso(timeline[0]), "end": iso(timeline[-1]),
        "start_epoch": timeline[0], "end_epoch": timeline[-1],
        "metrics": metrics,
        "equity": equity_points,
        "daily_equity": daily,
        "drawdown": dd_series,
        "trades": trades,
        "open_positions": open_positions,
        "orders": orders,
        "benchmark": bench,
        "skipped": skipped,
        "decision_counts": decision_counts,
        "fee_buy_pct": fee_buy, "fee_sell_pct": fee_sell,
        "cost_mult": cost_mult,
    }


def split_ts(start_ts, end_ts, frac=0.70):
    return int(start_ts + (end_ts - start_ts) * frac)


def quick_metrics(result):
    m = result["metrics"]
    return {"cagr": m.get("cagr"), "mdd": m.get("max_drawdown"),
            "calmar": (m["cagr"] / abs(m["max_drawdown"])) if (m.get("cagr") is not None and m.get("max_drawdown")) else None,
            "trades": m.get("trades"), "pf": m.get("profit_factor"),
            "final": m.get("final_equity"), "win_rate": m.get("win_rate")}


def plateau_pick(grid, results, min_trades):
    """Pilih parameter dengan rata-rata Calmar tetangga (plateau, bukan puncak)."""
    keys = ["lookback", "fast_ema", "trend_ema", "atr_mult"]
    import itertools
    shape = tuple(len(grid[k]) for k in keys)
    score = {}
    for idx in itertools.product(*[range(s) for s in shape]):
        combo = tuple(grid[k][i] for k, i in zip(keys, idx))
        q = results.get(combo)
        if not q or q.get("trades", 0) < min_trades or q.get("calmar") is None:
            continue
        vals = [q["calmar"]]
        for d in range(len(keys)):
            for dd in (-1, 1):
                j = list(idx)
                j[d] += dd
                if 0 <= j[d] < shape[d]:
                    c2 = tuple(grid[k][i] for k, i in zip(keys, j))
                    q2 = results.get(c2)
                    vals.append(q2["calmar"] if (q2 and q2.get("trades", 0) >= min_trades and q2.get("calmar") is not None) else 0.0)
        score[combo] = sum(vals) / len(vals)
    if not score:
        return None, False, []
    best = max(score, key=score.get)
    top = sorted(score.items(), key=lambda kv: -kv[1])[:10]
    top_list = [{"params": dict(zip(keys, c)), "smooth_calmar": v,
                 "calmar": results[c].get("calmar"), "cagr": results[c].get("cagr"),
                 "mdd": results[c].get("mdd"), "trades": results[c].get("trades")} for c, v in top]
    return dict(zip(keys, best)), True, top_list
