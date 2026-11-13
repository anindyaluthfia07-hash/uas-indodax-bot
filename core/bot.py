"""Bot dry-run Indodax: satu tick = baca state -> data live -> sinyal -> eksekusi simulasi -> simpan state/log.

Tidak memakai API key. Order hanya disimulasikan pada order book publik.
"""
import hashlib
import math
import os
import time
import uuid
from datetime import datetime, timezone

from .config import load_strategy, iso_utc, utc_now, wib_date, WIB
from .exchange import (RateLimiter, get_server_time, get_pairs, get_price_increments,
                       get_depth, get_candles, closed_bars, spread_pct, walk_book_notional,
                       walk_book_qty, validate_bars)
from .metrics import compute_metrics, compute_uptime
from .period import forward_period
from .strategy import StrategyEngine, entry_reasons


def _iso(ts):
    return datetime.fromtimestamp(int(ts), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def initial_state(cfg):
    return {
        "version": 1,
        "initialized": True,
        "cash": float(cfg["capital_idr"]),
        "positions": {},
        "last_processed": {},
        "last_prices": {},
        "last_tick": None,
        "tick_count": 0,
        "day_date_wib": None,
        "day_start_equity": float(cfg["capital_idr"]),
        "daily_loss_blocked": False,
        "daily_loss_block_date": None,
        "forward_test_start": None,
        "last_equity": float(cfg["capital_idr"]),
        "meta_cache": {},
    }


def current_equity(state, prices):
    invested = 0.0
    for pair, pos in state.get("positions", {}).items():
        px = prices.get(pair) or state.get("last_prices", {}).get(pair) or pos.get("entry_ref")
        invested += float(pos.get("qty", 0.0)) * float(px or 0.0)
    return float(state.get("cash", 0.0)) + invested


def _error(storage, tick_id, context, exc, pair=None):
    try:
        storage.append("errors", {
            "at": iso_utc(), "tick_id": tick_id, "context": context, "pair": pair,
            "error": str(exc), "type": type(exc).__name__,
        })
    except Exception:
        pass


def _tick_id(now):
    return "tick_" + now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:6]


def _next_index(engine, candle_time):
    for i in range(len(engine.times) - 1, -1, -1):
        if engine.times[i] == candle_time:
            return i
    return None


def _run_tick_body(storage, trigger="manual", now=None, config=None, limiter=None,
                   max_retries=3, save_snapshots=True):
    cfg = config or load_strategy()
    now = now or utc_now()
    tick_id = _tick_id(now)
    started = time.time()
    limiter = limiter or RateLimiter(0.35)
    state = storage.get_state() or {}
    if not state.get("initialized"):
        state = initial_state(cfg)
        storage.set_state(state)

    summary = {"tick_id": tick_id, "trigger": trigger, "started_at": iso_utc(now),
               "status": "running", "decisions": 0, "orders": 0, "errors": 0,
               "pairs": [], "equity": None}
    errors = {"n": 0}

    def errlog(e):
        errors["n"] += 1
        try:
            storage.append("errors", {"at": iso_utc(), "tick_id": tick_id, "context": "api",
                                      "url": e.get("url"), "attempt": e.get("attempt"),
                                      "error": e.get("error"), "status": e.get("status")})
        except Exception:
            pass

    try:
        server_time = get_server_time(limiter=limiter, error_log=errlog)
    except Exception as e:
        _error(storage, tick_id, "server_time", e)
        summary.update({"status": "error", "errors": 1, "error": str(e)})
        try:
            storage.append("ticks", dict(summary, finished_at=iso_utc(), elapsed_ms=int((time.time() - started) * 1000)))
        except Exception:
            pass
        return summary

    # metadata pair (fee/min order/price tick/qty increment)
    try:
        pairs_meta = get_pairs(limiter=limiter, error_log=errlog)
        increments = get_price_increments(limiter=limiter, error_log=errlog)
        cache = {}
        for p in cfg["universe"]:
            m = pairs_meta.get(p, {})
            cache[p] = {
                "symbol": m.get("symbol", p.upper()),
                "pricescale": m.get("pricescale"),
                "quantity_increment": m.get("quantity_increment", 1e-8),
                "trade_min_base_currency": m.get("trade_min_base_currency"),
                "trade_fee_percent_taker": m.get("trade_fee_percent_taker"),
                "increment": increments.get(p.replace("idr", "_idr"), None),
            }
        state["meta_cache"] = cache
    except Exception as e:
        _error(storage, tick_id, "metadata", e)
        cache = state.get("meta_cache") or {}
        if not cache:
            summary.update({"status": "error", "errors": 1, "error": "metadata pair tidak tersedia: %s" % e})
            storage.append("ticks", dict(summary, finished_at=iso_utc(),
                                         elapsed_ms=int((time.time() - started) * 1000)))
            return summary

    # ---------- ambil depth + candle semua pair dulu ----------
    universe = [p for p in cfg["universe"] if p in cache]
    depths, candles, bars_closed, data_ok = {}, {}, {}, {}
    for pair in universe:
        try:
            d = get_depth(pair, limiter=limiter, error_log=errlog)
            depths[pair] = d
            if save_snapshots and d.get("bid") and d.get("ask"):
                est = walk_book_notional(d["asks"][:20], 0.2 * float(cfg["capital_idr"])) if d["asks"] else {}
                storage.append("snapshots", {
                    "ts": int(time.time()), "at_utc": iso_utc(), "pair": pair,
                    "bid": d["bid"], "ask": d["ask"], "spread_pct": spread_pct(d),
                    "bids": d["bids"][:20], "asks": d["asks"][:20],
                    "target_notional_idr": 0.2 * float(cfg["capital_idr"]),
                    "est_fill_vwap_buy": est.get("vwap"), "est_complete": est.get("complete"),
                    "tick_id": tick_id,
                })
        except Exception as e:
            _error(storage, tick_id, "depth", e, pair)
            depths[pair] = {}
        try:
            raw = get_candles(cache[pair]["symbol"], cfg["timeframe"],
                              int(server_time - 900 * int(cfg["timeframe_seconds"])),
                              int(server_time), limiter=limiter, error_log=errlog)
            cb = closed_bars(raw, int(cfg["timeframe_seconds"]), server_time)
            candles[pair] = raw
            bars_closed[pair] = cb
            lookback = max(180, int(cfg["params"]["trend_ema"]) + 10)
            ok, reasons, info = validate_bars(cb, int(cfg["timeframe_seconds"]), server_time, lookback)
            sp = spread_pct(depths[pair]) if depths[pair] else None
            if not depths[pair] or not depths[pair].get("bid") or not depths[pair].get("ask"):
                ok = False
                reasons.append("order book kosong")
            if sp is None:
                ok = False
                reasons.append("bid/ask tidak valid")
            elif sp > float(cfg["max_spread_pct"]):
                reasons.append("spread %.3f%% > %.1f%%" % (sp * 100, cfg["max_spread_pct"] * 100))
                # spread lebar memblokir entry, bukan exit; simpan flag terpisah
            data_ok[pair] = {"ok": ok, "reasons": reasons, "info": info, "spread": sp,
                             "spread_block_entry": bool(sp is not None and sp > float(cfg["max_spread_pct"]))}
        except Exception as e:
            _error(storage, tick_id, "candles", e, pair)
            bars_closed[pair] = []
            data_ok[pair] = {"ok": False, "reasons": ["gagal mengambil candle: %s" % e],
                             "info": {}, "spread": None, "spread_block_entry": True}

    prices = {p: (depths.get(p, {}).get("bid")) for p in universe}
    for p, px in prices.items():
        if px:
            state.setdefault("last_prices", {})[p] = px
    equity = current_equity(state, prices)
    state["last_equity"] = equity

    # ---------- daily rollover WIB 00:00 ----------
    today_wib = wib_date(now)
    if state.get("day_date_wib") != today_wib:
        state["day_date_wib"] = today_wib
        state["day_start_equity"] = equity
        state["daily_loss_blocked"] = False
        storage.append("daily_equity", {"date_wib": today_wib, "t": int(now.timestamp()), "at": iso_utc(now),
                                        "equity": equity, "note": "panggilan pertama setelah 00:00 WIB"})
    day_start = float(state.get("day_start_equity") or equity)
    if day_start > 0 and equity / day_start - 1.0 <= float(cfg["daily_loss_limit_pct"]):
        if not state.get("daily_loss_blocked"):
            state["daily_loss_blocked"] = True
            state["daily_loss_block_date"] = today_wib
            storage.append("decisions", {"at": iso_utc(), "tick_id": tick_id, "pair": None,
                                         "action": "risk_block", "processed": True,
                                         "reason": "daily_loss_limit",
                                         "day_start_equity": day_start, "equity": equity,
                                         "loss_pct": equity / day_start - 1.0})
    if state.get("daily_loss_blocked") and state.get("daily_loss_block_date") != today_wib:
        state["daily_loss_blocked"] = False

    kill = storage.get_kill()
    if kill:
        storage.append("decisions", {"at": iso_utc(), "tick_id": tick_id, "pair": None,
                                     "action": "kill_switch_active", "processed": True,
                                     "reason": "kill switch aktif: entry diblokir, exit tetap dievaluasi"})

    if state.get("forward_test_start") is None:
        state["forward_test_start"] = iso_utc(now)
        storage.append("decisions", {"at": iso_utc(), "tick_id": tick_id, "pair": None,
                                     "action": "forward_test_start", "processed": True,
                                     "reason": "tick sukses pertama; timestamp aktual, bukan backdate",
                                     "forward_test_start": state["forward_test_start"]})

    storage.set_state(state)

    # ---------- proses per pair ----------
    for pair in universe:
        dc = data_ok.get(pair, {"ok": False, "reasons": ["tidak diproses"], "spread": None})
        d = depths.get(pair, {})
        cb = bars_closed.get(pair, [])
        decision = {
            "at": iso_utc(), "processed_at": iso_utc(), "processed_at_epoch": int(time.time()),
            "tick_id": tick_id, "pair": pair, "action": "skip", "processed": False,
            "exit_reason": None, "signal": None, "entry_components": None,
            "reason": "", "data_valid": bool(dc.get("ok")), "validation_reasons": dc.get("reasons"),
            "best_bid": d.get("bid"), "best_ask": d.get("ask"), "spread_pct": dc.get("spread"),
            "equity": equity, "cash": state.get("cash"), "positions": len(state.get("positions", {})),
        }
        if not cb:
            decision["reason"] = "tidak ada candle tertutup"
            storage.append("decisions", decision)
            summary["decisions"] += 1
            continue
        candle_time = int(cb[-1]["time"])
        decision["candle_time"] = candle_time
        decision["candle_time_iso"] = _iso(candle_time)
        decision["candle_close"] = cb[-1]["close"]

        last_done = int(state.get("last_processed", {}).get(pair, 0) or 0)
        if candle_time <= last_done:
            decision["action"] = "duplicate_candle_skip"
            decision["processed"] = True
            decision["reason"] = "candle %s sudah diproses (idempotency)" % _iso(candle_time)
            storage.append("decisions", decision)
            summary["decisions"] += 1
            continue

        if not dc.get("ok"):
            decision["reason"] = "data tidak valid: " + "; ".join(dc.get("reasons") or [])
            storage.append("decisions", decision)
            summary["decisions"] += 1
            summary["pairs"].append({"pair": pair, "action": "invalid", "reason": decision["reason"]})
            continue

        engine = StrategyEngine(cb, cfg["params"])
        i = len(cb) - 1
        snap = engine.snapshot(i)
        decision["signal"] = snap
        decision["entry_components"] = entry_reasons(engine, i)
        decision["warmup_bars"] = engine.warmup
        decision["bars_fetched"] = len(cb)

        pos = (state.get("positions") or {}).get(pair)
        sold_now = False
        # ---------- EXIT ----------
        if pos:
            try:
                # Indeks array candle bergeser tiap tick (window 900 bar), jadi
                # holding bar harus dihitung dari waktu candle masuk, bukan dari
                # entry_i yang tersimpan. Tanpa ini time stop tidak pernah jalan.
                entry_ct = pos.get("entry_candle_time")
                if entry_ct:
                    held_bars = int(round((candle_time - int(entry_ct))
                                          / float(cfg["timeframe_seconds"])))
                    exit_pos = dict(pos, entry_i=i - held_bars)
                else:
                    held_bars = i - int(pos.get("entry_i", i))
                    exit_pos = pos
                reason, new_stop = engine.exit_signal(i, exit_pos)
                pos["stop"] = new_stop
                decision["position"] = {"qty": pos.get("qty"), "entry_time": pos.get("entry_time"),
                                        "entry_fill": pos.get("entry_fill"), "stop": new_stop}
                if reason:
                    # claim order idempotency
                    order_id = "%s:sell:%s:%s" % (pair, candle_time, pos.get("entry_time"))
                    if not storage.claim_order(order_id):
                        decision["reason"] = "order sell sudah pernah diklaim (idempotency)"
                    else:
                        mid = (float(d["bid"]) + float(d["ask"])) / 2.0
                        target_qty = float(pos["qty"])
                        fill = walk_book_qty(d["bids"][:20], target_qty)
                        if not fill["qty"] or not fill["vwap"]:
                            decision["reason"] = "order book bid tidak cukup untuk sell"
                        else:
                            sold_qty = min(target_qty, fill["qty"])
                            frac = sold_qty / target_qty if target_qty else 1.0
                            notional = fill["notional"]
                            fee_sell = notional * float(cfg["fees"]["sell_pct"])
                            cash_add = notional - fee_sell
                            state["cash"] = float(state.get("cash", 0.0)) + cash_add
                            entry_fee_alloc = float(pos.get("entry_fee", 0.0)) * frac
                            entry_spread_alloc = float(pos.get("entry_spread_cost", 0.0)) * frac
                            entry_slip_alloc = float(pos.get("entry_slippage_cost", 0.0)) * frac
                            spread_cost = sold_qty * (mid - float(d["bid"]))
                            slip_cost = sold_qty * (float(d["bid"]) - fill["vwap"])
                            gross = sold_qty * (mid - float(pos["entry_ref"]))
                            net = gross - entry_fee_alloc - fee_sell - entry_spread_alloc - entry_slip_alloc - spread_cost - slip_cost
                            trade = {
                                "pair": pair, "entry_time": pos.get("entry_time"), "exit_time": iso_utc(),
                                "qty": sold_qty, "entry_ref": pos.get("entry_ref"),
                                "entry_fill": pos.get("entry_fill"), "exit_ref": mid,
                                "exit_fill": fill["vwap"], "gross_pnl": gross,
                                "fee_entry": entry_fee_alloc, "fee_exit": fee_sell,
                                "fee_total": entry_fee_alloc + fee_sell,
                                "spread_cost": entry_spread_alloc + spread_cost,
                                "slippage_cost": entry_slip_alloc + slip_cost,
                                "net_pnl": net,
                                "net_pct": (net / (sold_qty * float(pos["entry_ref"]))) * 100.0,
                                "holding_bars": held_bars,
                                "exit_reason": reason, "partial": not fill["complete"],
                                "order_id": order_id, "tick_id": tick_id,
                            }
                            storage.append("trades", trade)
                            storage.append("orders", {
                                "at": iso_utc(), "tick_id": tick_id, "order_id": order_id,
                                "pair": pair, "side": "sell", "qty": sold_qty,
                                "best_bid": d["bid"], "best_ask": d["ask"],
                                "fill_price": fill["vwap"], "fee": fee_sell,
                                "spread_cost": spread_cost, "slippage_cost": slip_cost,
                                "signal_price": cb[-1]["close"],
                                "deviation_vs_signal_pct": (fill["vwap"] / cb[-1]["close"] - 1.0) * 100.0,
                                "levels_used": fill["levels_used"], "complete": fill["complete"],
                                "reason": reason, "candle_time": candle_time,
                            })
                            state["cash"] = state["cash"]
                            state.setdefault("positions", {})
                            if fill["complete"] and sold_qty >= target_qty * (1 - 1e-9):
                                del state["positions"][pair]
                            else:
                                state["positions"][pair]["qty"] = target_qty - sold_qty
                                state["positions"][pair]["entry_fee"] = float(pos.get("entry_fee", 0.0)) - entry_fee_alloc
                                state["positions"][pair]["entry_spread_cost"] = float(pos.get("entry_spread_cost", 0.0)) - entry_spread_alloc
                                state["positions"][pair]["entry_slippage_cost"] = float(pos.get("entry_slippage_cost", 0.0)) - entry_slip_alloc
                            decision["action"] = "sell"
                            decision["reason"] = reason
                            decision["exit_reason"] = reason
                            decision["fill"] = {"qty": sold_qty, "vwap": fill["vwap"],
                                                "fee": fee_sell, "levels_used": fill["levels_used"],
                                                "complete": fill["complete"]}
                            summary["orders"] += 1
                            sold_now = True
            except Exception as e:
                _error(storage, tick_id, "exit", e, pair)
                decision["reason"] = "error exit: %s" % e

        # ---------- ENTRY ----------
        if not pos and not sold_now and not state.get("positions", {}).get(pair):
            if engine.entry_signal(i):
                if kill:
                    decision["reason"] = "kill switch aktif"
                elif state.get("daily_loss_blocked"):
                    decision["reason"] = "daily loss limit aktif sampai hari WIB berikutnya"
                elif len(state.get("positions", {})) >= int(cfg["max_positions"]):
                    decision["reason"] = "max posisi tercapai"
                elif dc.get("spread_block_entry"):
                    decision["reason"] = "spread > %.1f%%" % (float(cfg["max_spread_pct"]) * 100)
                else:
                    try:
                        equity_now = current_equity(state, prices)
                        target = min(equity_now * float(cfg["position_fraction"]),
                                     float(engine.adv[i] or 0.0) * float(cfg["max_participation_adv"]),
                                     float(state.get("cash", 0.0)))
                        if target < float(cfg["min_order_idr"]):
                            decision["reason"] = "target notional < minimum order Rp25.000"
                        else:
                            order_id = "%s:buy:%s" % (pair, candle_time)
                            if not storage.claim_order(order_id):
                                decision["reason"] = "order buy sudah pernah diklaim (idempotency)"
                            else:
                                mid = (float(d["bid"]) + float(d["ask"])) / 2.0
                                fill = walk_book_notional(d["asks"][:20], target)
                                if not fill["qty"] or not fill["vwap"]:
                                    decision["reason"] = "order book ask kosong"
                                else:
                                    qty_inc = float(cache[pair].get("quantity_increment") or 1e-8)
                                    qty = math.floor((fill["notional"] / fill["vwap"]) / qty_inc) * qty_inc
                                    notional = qty * fill["vwap"]
                                    fee_buy = notional * float(cfg["fees"]["buy_pct"])
                                    total = notional + fee_buy
                                    # batasi dengan cash
                                    if total > float(state.get("cash", 0.0)):
                                        qty = math.floor((float(state["cash"]) / (fill["vwap"] * (1 + float(cfg["fees"]["buy_pct"])))) / qty_inc) * qty_inc
                                        notional = qty * fill["vwap"]
                                        fee_buy = notional * float(cfg["fees"]["buy_pct"])
                                        total = notional + fee_buy
                                    if qty <= 0 or notional < float(cfg["min_order_idr"]):
                                        decision["reason"] = "notional setelah pembulatan < Rp25.000"
                                    else:
                                        spread_cost = qty * (float(d["ask"]) - mid)
                                        slip_cost = qty * (fill["vwap"] - float(d["ask"]))
                                        state["cash"] = float(state["cash"]) - total
                                        state.setdefault("positions", {})[pair] = {
                                            "qty": qty, "entry_ref": mid, "entry_fill": fill["vwap"],
                                            "entry_fee": fee_buy, "entry_spread_cost": spread_cost,
                                            "entry_slippage_cost": slip_cost, "entry_i": i,
                                            "entry_time": iso_utc(), "entry_candle_time": candle_time,
                                            "entry_equity": equity_now, "stop": engine.initial_stop(i),
                                        }
                                        storage.append("orders", {
                                            "at": iso_utc(), "tick_id": tick_id, "order_id": order_id,
                                            "pair": pair, "side": "buy", "qty": qty,
                                            "best_bid": d["bid"], "best_ask": d["ask"],
                                            "fill_price": fill["vwap"], "fee": fee_buy,
                                            "spread_cost": spread_cost, "slippage_cost": slip_cost,
                                            "signal_price": cb[-1]["close"],
                                            "deviation_vs_signal_pct": (fill["vwap"] / cb[-1]["close"] - 1.0) * 100.0,
                                            "levels_used": fill["levels_used"], "complete": fill["complete"],
                                            "reason": "entry", "candle_time": candle_time,
                                        })
                                        decision["action"] = "buy"
                                        decision["reason"] = "entry signal"
                                        decision["fill"] = {"qty": qty, "vwap": fill["vwap"],
                                                            "fee": fee_buy, "notional": notional,
                                                            "levels_used": fill["levels_used"],
                                                            "complete": fill["complete"]}
                                        summary["orders"] += 1
                    except Exception as e:
                        _error(storage, tick_id, "entry", e, pair)
                        decision["reason"] = "error entry: %s" % e

        if decision["action"] == "skip" and not decision["reason"]:
            decision["reason"] = "tidak ada sinyal"
        if decision["action"] in ("buy", "sell") or decision["processed"] is False:
            if decision["action"] in ("buy", "sell") or decision["reason"].startswith("entry signal"):
                pass
        # candle valid diproses (dengan atau tanpa trade) -> tandai idempotency
        if dc.get("ok"):
            state.setdefault("last_processed", {})[pair] = candle_time
            decision["processed"] = True
        storage.append("decisions", decision)
        summary["decisions"] += 1
        summary["pairs"].append({"pair": pair, "action": decision["action"], "reason": decision["reason"],
                                 "candle_time": candle_time})
        storage.set_state(state)

    # ---------- akhir tick ----------
    prices_end = {p: depths.get(p, {}).get("bid") for p in universe}
    for p, px in prices_end.items():
        if px:
            state.setdefault("last_prices", {})[p] = px
    equity_end = current_equity(state, prices_end)
    state["last_equity"] = equity_end
    state["last_tick"] = iso_utc(now)
    state["tick_count"] = int(state.get("tick_count", 0)) + 1
    storage.set_state(state)
    storage.append("equity", {"t": int(now.timestamp()), "at": iso_utc(now), "tick_id": tick_id,
                              "equity": equity_end, "cash": state.get("cash"),
                              "invested": equity_end - float(state.get("cash", 0.0)),
                              "positions": len(state.get("positions", {})),
                              "day_date_wib": state.get("day_date_wib"),
                              "daily_loss_blocked": bool(state.get("daily_loss_blocked"))})
    summary.update({
        "status": "ok", "finished_at": iso_utc(), "equity": equity_end,
        "cash": state.get("cash"), "positions": len(state.get("positions", {})),
        "errors": errors["n"] + sum(1 for p in summary["pairs"] if p["action"] == "invalid"),
        "elapsed_ms": int((time.time() - started) * 1000),
        "forward_test_start": state.get("forward_test_start"),
        "kill_switch": bool(kill), "daily_loss_blocked": bool(state.get("daily_loss_blocked")),
    })
    storage.append("ticks", summary)
    return summary


def run_tick(storage, trigger="manual", now=None, config=None, limiter=None,
             max_retries=3, save_snapshots=True, lock_ttl=600):
    """Wrapper dengan lock singkat supaya tick tidak tumpang tindih.

    Idempotensi per candle tetap menjadi pengaman utama; lock mencegah dua
    proses menulis state yang sama secara bersamaan.
    """
    cfg = config or load_strategy()
    now = now or utc_now()
    token = storage.acquire_lock("tick", ttl_seconds=lock_ttl)
    if not token:
        summary = {"tick_id": _tick_id(now), "trigger": trigger, "started_at": iso_utc(now),
                   "status": "locked", "decisions": 0, "orders": 0, "errors": 0,
                   "pairs": [], "equity": None,
                   "reason": "tick lain masih berjalan (lock aktif)"}
        try:
            storage.append("ticks", summary)
        except Exception:
            pass
        return summary
    try:
        return _run_tick_body(storage, trigger=trigger, now=now, config=cfg,
                              limiter=limiter, max_retries=max_retries,
                              save_snapshots=save_snapshots)
    finally:
        try:
            storage.release_lock("tick", token)
        except Exception:
            pass


def dashboard_payload(storage, cfg=None, now=None):
    """Data dashboard dari state + log mentah; metrik dihitung ulang di sini."""
    from .config import ROOT, load_json
    cfg = cfg or load_strategy()
    now = now or utc_now()
    state = storage.get_state() or {}
    ticks = storage.read("ticks", 10000)
    decisions = storage.read("decisions", 20000)
    orders = storage.read("orders", 10000)
    trades = storage.read("trades", 10000)
    equity_log = storage.read("equity", 20000)
    daily = storage.read("daily_equity", 2000)
    errors = storage.read("errors", 5000)
    snaps = storage.read("snapshots", 20000)
    kill_log = storage.read("kill_log", 2000)
    backtest = load_json(os.path.join(ROOT, "data", "backtest_results.json"), default={}) or {}
    costs = load_json(os.path.join(ROOT, "data", "costs.json"), default={}) or {}
    project_status = load_json(os.path.join(ROOT, "data", "project_status.json"), default={}) or {}
    forward_vs_backtest = load_json(os.path.join(ROOT, "data", "forward_vs_backtest.json"), default={}) or {}

    points = [{"t": x["t"], "equity": x["equity"]} for x in equity_log]
    initial = float(cfg["capital_idr"])
    if not points:
        points = [{"t": int(now.timestamp()), "equity": float(state.get("last_equity", initial))}]
    forward_start = state.get("forward_test_start")
    fwd_period = forward_period(forward_start, now)
    fwd_metrics = compute_metrics(points, trades, initial,
                                  start=forward_start or points[0]["t"],
                                  end=points[-1]["t"], include_cagr=False)
    # benchmark pada jendela forward (butuh candle; sediakan dari file gap analysis bila ada)
    gap = load_json(os.path.join(ROOT, "data", "gap_analysis.json"), default={}) or {}
    uptime = compute_uptime(decisions, forward_start, now.timestamp(), int(cfg["timeframe_seconds"]),
                            now_ts=now.timestamp(), pairs=cfg["universe"])
    prices = state.get("last_prices", {})
    positions = []
    for pair, pos in (state.get("positions") or {}).items():
        last = prices.get(pair) or pos.get("entry_ref")
        value = float(pos.get("qty", 0)) * float(last or 0)
        basis = float(pos.get("qty", 0)) * float(pos.get("entry_fill", 0)) + float(pos.get("entry_fee", 0))
        positions.append({
            "pair": pair, "qty": pos.get("qty"), "entry_time": pos.get("entry_time"),
            "entry_fill": pos.get("entry_fill"), "last_price": last, "value": value,
            "unrealized_pnl": value - basis, "unrealized_pct": ((value / basis - 1) * 100) if basis else None,
            "stop": pos.get("stop"), "entry_candle_time": pos.get("entry_candle_time"),
        })
    last_decisions = sorted(decisions, key=lambda d: d.get("processed_at_epoch") or 0)[-30:]
    return {
        "meta": {
            "student": "Anindya Rahma Luthfia", "nim": "25110200036",
            "generated_at": iso_utc(now), "storage": storage.name,
            "strategy": cfg["strategy_name"], "timeframe": cfg["timeframe"],
            "freeze": cfg.get("frozen_at"), "freeze_commit": cfg.get("freeze_commit"),
            "forward_test_start": forward_start,
            "universe": cfg["universe"], "params": cfg["params"],
            "capital_idr": initial, "fees": cfg["fees"],
            "min_order_idr": cfg["min_order_idr"],
        },
        "backtest": {
            "meta": backtest.get("meta", {}), "params": backtest.get("params"),
            "metrics": backtest.get("metrics"), "is": backtest.get("is"), "oos": backtest.get("oos"),
            "stress": backtest.get("stress"), "benchmark": backtest.get("benchmark", {}).get("metrics"),
            "daily_equity": backtest.get("daily_equity", []),
            "trades": backtest.get("trades", []), "open_positions": backtest.get("open_positions", []),
            "monthly": backtest.get("monthly", []), "yearly": backtest.get("yearly", {}),
            "sensitivity": backtest.get("sensitivity", []),
        },
        "forward": {
            "start": forward_start, "end": _iso(points[-1]["t"]),
            "duration_days": (fwd_period["elapsed_days"] or 0),
            "target_end": fwd_period["target_end"],
            "target_end_wib": fwd_period["target_end_wib"],
            "period_days": fwd_period["period_days"],
            "remaining_hours": fwd_period["remaining_hours"],
            "complete": fwd_period["complete"],
            "metrics": fwd_metrics, "equity": points, "trades": trades,
            "open_positions": positions, "orders": orders[-500:], "decisions": last_decisions,
            "errors": errors[-500:], "uptime": uptime,
            "kill_switch": storage.get_kill(), "kill_log": kill_log[-100:],
            "state": {"cash": state.get("cash"), "equity": state.get("last_equity"),
                      "tick_count": state.get("tick_count"), "last_tick": state.get("last_tick"),
                      "daily_loss_blocked": state.get("daily_loss_blocked"),
                      "day_start_equity": state.get("day_start_equity"),
                      "day_date_wib": state.get("day_date_wib")},
            "daily_equity": daily,
            "snapshots": {"count": len(snaps), "last": snaps[-1] if snaps else None},
        },
        "gap": gap,
        "forward_vs_backtest": forward_vs_backtest,
        "project_status": project_status,
        "costs_used": costs.get("total_snapshots_used", 0),
        "status": {
            "bot_active": bool(state.get("last_tick")),
            "last_tick": state.get("last_tick"),
            "kill_switch": storage.get_kill(),
            "daily_loss_blocked": bool(state.get("daily_loss_blocked")),
            "errors_total": len(errors),
            "ticks_total": len(ticks),
        },
    }
