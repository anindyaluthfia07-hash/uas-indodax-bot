"""Unit test inti: indikator, strategi, metrik, backtest, storage, bot.

Jalankan:
  python3 -m unittest discover -s tests -v
"""
import json
import math
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import Mock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core import bot as botmod
from core.backtest_engine import run_backtest
from core.config import load_strategy
from core.indicators import atr_series, ema_series, rolling_max_prev
from core.metrics import compute_metrics, compute_uptime
from core.storage import LocalStorage
from core.strategy import StrategyEngine

TF = 14400


def make_bars(n=240, start=1794000000, step=0.0015, last_jump=0.03, last_drop=None):
    start = int(start) - (int(start) % TF)
    bars = []
    price = 1000.0
    for i in range(n):
        o = price
        if i == n - 1 and last_drop is not None:
            c = o * (1.0 - last_drop)
        elif i == n - 1:
            c = o * (1.0 + last_jump)
        else:
            c = o * (1.0 + step)
        h = max(o, c) * 1.004
        l = min(o, c) * 0.996
        bars.append({"time": start + i * TF, "open": o, "high": h, "low": l,
                     "close": c, "volume": 100000.0})
        price = c
    return bars


def cfg_for(pairs):
    cfg = json.loads(json.dumps(load_strategy()))
    cfg["universe"] = list(pairs)
    return cfg


@contextmanager
def mock_market(bars_by_pair, spread=0.001, depth_qty=1e7):
    state = {"bars": bars_by_pair}

    def candles(symbol, tf, frm, to, limiter=None, error_log=None):
        pair = symbol.lower()
        return list(state["bars"][pair])

    def depth(pair, limiter=None, error_log=None):
        b = state["bars"][pair][-1]["close"]
        return {"pair": pair, "bid": b * (1 - spread / 2), "ask": b * (1 + spread / 2),
                "bids": [(b * (1 - spread / 2), depth_qty)],
                "asks": [(b * (1 + spread / 2), depth_qty)], "fetched_at": 0}

    def server_time(limiter=None, error_log=None):
        return max(v[-1]["time"] for v in state["bars"].values()) + TF + 10

    meta = {}
    for pair in bars_by_pair:
        meta[pair] = {"symbol": pair.upper(), "pricescale": 1, "quantity_increment": 1e-8,
                      "trade_min_base_currency": 10000, "trade_fee_percent_taker": 0.2}
    inc = {p.replace("idr", "_idr"): "1" for p in bars_by_pair}
    with patch.multiple(botmod,
                        get_server_time=Mock(side_effect=server_time),
                        get_pairs=Mock(return_value=meta),
                        get_price_increments=Mock(return_value=inc),
                        get_depth=Mock(side_effect=depth),
                        get_candles=Mock(side_effect=candles)):
        yield state


class TestIndicators(unittest.TestCase):
    def test_ema_matches_manual(self):
        vals = [1, 2, 3, 4, 5]
        out = ema_series(vals, 3)
        alpha = 2 / 4
        exp = [1.0]
        for v in vals[1:]:
            exp.append(alpha * v + (1 - alpha) * exp[-1])
        for a, b in zip(out, exp):
            self.assertAlmostEqual(a, b, places=12)

    def test_donchian_excludes_current_bar(self):
        vals = [10, 9, 8, 11, 12, 7]
        out = rolling_max_prev(vals, 3)
        self.assertIsNone(out[0])
        self.assertIsNone(out[2])
        self.assertEqual(out[3], max(vals[0:3]))  # 10, bukan 11
        self.assertEqual(out[4], max(vals[1:4]))  # 11, bukan 12
        self.assertEqual(out[5], max(vals[2:5]))  # 12, bukan 7
        # nilai bar saat ini tidak boleh bocor ke output
        self.assertNotEqual(out[3], 11)

    def test_atr_positive(self):
        bars = make_bars(50)
        a = atr_series(bars, 14)
        self.assertTrue(all(x > 0 for x in a))


class TestStrategy(unittest.TestCase):
    def test_breakout_entry_and_no_lookahead(self):
        bars = make_bars(240)
        eng = StrategyEngine(bars, load_strategy()["params"])
        self.assertTrue(eng.entry_signal(len(bars) - 1))
        # Mengubah bar terakhir tidak boleh mengubah donchian/EMA bar sebelumnya
        before = eng.snapshot(len(bars) - 2)
        bars2 = [dict(b) for b in bars]
        bars2[-1]["close"] *= 0.5
        eng2 = StrategyEngine(bars2, load_strategy()["params"])
        after = eng2.snapshot(len(bars) - 2)
        for k in ("donchian_high", "ema_fast", "ema_trend", "atr"):
            self.assertAlmostEqual(before[k], after[k], places=9)

    def test_time_stop(self):
        bars = make_bars(240, last_drop=0.05)
        eng = StrategyEngine(bars, load_strategy()["params"])
        pos = {"entry_fill": bars[-2]["close"], "stop": 1e-9, "entry_i": len(bars) - 4}
        reason, _ = eng.exit_signal(len(bars) - 1, pos)
        self.assertEqual(reason, "time_stop")

    def test_trailing_stop(self):
        bars = make_bars(240)
        eng = StrategyEngine(bars, load_strategy()["params"])
        stop = bars[-1]["close"] * 1.10
        pos = {"entry_fill": bars[-2]["close"], "stop": stop, "entry_i": len(bars) - 2}
        reason, _ = eng.exit_signal(len(bars) - 1, pos)
        self.assertEqual(reason, "atr_trailing_stop")


class TestMetrics(unittest.TestCase):
    def test_drawdown_and_return(self):
        pts = [{"t": 0, "equity": 100}, {"t": 86400, "equity": 120},
               {"t": 2 * 86400, "equity": 90}, {"t": 3 * 86400, "equity": 110}]
        m = compute_metrics(pts, [], 100, start=0, end=3 * 86400)
        self.assertAlmostEqual(m["total_return"], 0.10)
        self.assertAlmostEqual(m["max_drawdown"], -0.25)

    def test_profit_factor_and_costs(self):
        trades = [
            {"net_pnl": 100, "net_pct": 10, "gross_pnl": 130, "fee_total": 10, "spread_cost": 15, "slippage_cost": 5},
            {"net_pnl": -50, "net_pct": -5, "gross_pnl": -30, "fee_total": 8, "spread_cost": 10, "slippage_cost": 2},
        ]
        m = compute_metrics([{"t": 0, "equity": 100}, {"t": 1, "equity": 150}], trades, 100)
        self.assertAlmostEqual(m["profit_factor"], 2.0)
        self.assertEqual(m["trades"], 2)
        self.assertAlmostEqual(m["fee_idr"], 18)
        self.assertAlmostEqual(m["spread_cost_idr"], 25)
        self.assertAlmostEqual(m["slippage_cost_idr"], 7)

    def test_uptime_first_candle(self):
        start = 1794000000  # bukan kelipatan 4 jam
        start = start + 600
        tf = 14400
        first_open = (start // tf) * tf
        decisions = [{"candle_time": first_open, "processed_at_epoch": start + 60}]
        u = compute_uptime(decisions, start, first_open + tf + 10, tf)
        self.assertEqual(u["expected"], 1)
        self.assertEqual(u["on_time"], 1)

    def test_uptime_counts_each_pair(self):
        start = 1794000000 + 600
        tf = 14400
        first_open = (start // tf) * tf
        decisions = [
            {"pair": "btcidr", "candle_time": first_open, "processed_at_epoch": start + 60},
            {"pair": "ethidr", "candle_time": first_open, "processed_at_epoch": first_open + 2 * tf + 100},
        ]
        u = compute_uptime(decisions, start, first_open + tf + 10, tf,
                           pairs=["btcidr", "ethidr"])
        self.assertEqual(u["expected"], 2)
        self.assertEqual(u["on_time"], 1)
        self.assertAlmostEqual(u["uptime"], 0.5)

    def test_uptime_accepts_processing_after_candle_close(self):
        # Regresi: candle harus menunggu tutup (ct+tf), jadi "tepat waktu"
        # berarti sebelum candle berikutnya tutup (ct+2*tf).
        start = 1794000000 + 600
        tf = 14400
        first_open = (start // tf) * tf
        decisions = [
            {"pair": "btcidr", "candle_time": first_open, "processed_at_epoch": first_open + tf + 120},
            {"pair": "ethidr", "candle_time": first_open, "processed_at_epoch": first_open + 2 * tf - 1},
            {"pair": "trxidr", "candle_time": first_open, "processed_at_epoch": first_open + 2 * tf + 1},
        ]
        u = compute_uptime(decisions, start, first_open + tf + 10, tf,
                           pairs=["btcidr", "ethidr", "trxidr"])
        self.assertEqual(u["expected"], 3)
        self.assertEqual(u["on_time"], 2)
        self.assertAlmostEqual(u["uptime"], 2.0 / 3.0)


class TestStorage(unittest.TestCase):
    def test_roundtrip_claim_lock_kill(self):
        with tempfile.TemporaryDirectory() as d:
            s = LocalStorage(root=d)
            s.set_state({"a": 1})
            self.assertEqual(s.get_state()["a"], 1)
            s.append("decisions", {"x": 1})
            self.assertEqual(len(s.read("decisions")), 1)
            self.assertTrue(s.claim_order("o1"))
            self.assertFalse(s.claim_order("o1"))
            tok = s.acquire_lock("tick", 5)
            self.assertIsNotNone(tok)
            self.assertIsNone(s.acquire_lock("tick", 5))
            self.assertTrue(s.release_lock("tick", tok))
            self.assertIsNotNone(s.acquire_lock("tick", 5))
            self.assertFalse(s.get_kill())
            s.set_kill(True, note="test")
            self.assertTrue(s.get_kill())


class TestBacktest(unittest.TestCase):
    def test_backtest_runs_and_costs_reconcile(self):
        # 3 pair, 420 bar; satu breakout di bar 300 lalu drop untuk exit
        data = {}
        for pair in ("aaa" + "idr", "bbb" + "idr", "cccidr"):
            bars = make_bars(420, step=0.0008)
            # buat breakout kuat di bar 300
            bars[300]["close"] = bars[299]["close"] * 1.05
            bars[300]["high"] = bars[300]["close"] * 1.004
            # setelah itu turun agar exit
            for i in range(301, 420):
                bars[i]["close"] = bars[i - 1]["close"] * 0.999
                bars[i]["open"] = bars[i - 1]["close"]
                bars[i]["high"] = max(bars[i]["open"], bars[i]["close"]) * 1.002
                bars[i]["low"] = min(bars[i]["open"], bars[i]["close"]) * 0.998
            data[pair] = bars
        cfg = cfg_for(list(data.keys()))
        cfg["universe"] = list(data.keys())
        costs = {"pairs": {p: {"half_spread": 0.0005, "slippage_buy": 0.0005,
                               "slippage_sell": 0.0005} for p in data},
                 "fallback": {"half_spread": 0.0005, "slippage_buy": 0.0005, "slippage_sell": 0.0005}}
        start = data["aaaidr"][250]["time"]
        end = data["aaaidr"][-2]["time"]
        r = run_backtest(data, cfg, costs, start, end, pairs_meta={}, with_benchmark=False)
        self.assertGreater(len(r["equity"]), 0)
        self.assertGreaterEqual(len(r["trades"]), 1, "harus ada trade pada data sintetis")
        for t in r["trades"]:
            self.assertAlmostEqual(
                t["net_pnl"],
                t["gross_pnl"] - t["fee_total"] - t["spread_cost"] - t["slippage_cost"],
                places=6)
            self.assertGreater(t["qty"], 0)
        self.assertAlmostEqual(r["metrics"]["fee_idr"],
                               sum(t["fee_total"] for t in r["trades"]), places=6)
        # tidak ada posisi qty negatif
        for p in r["open_positions"]:
            self.assertGreater(p["qty"], 0)


class TestBot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(root=self.tmp.name)
        self.pairs = ["testidr"]
        self.cfg = cfg_for(self.pairs)

    def tearDown(self):
        self.tmp.cleanup()

    def test_buy_idempotent_and_sell(self):
        bars = make_bars(240)
        with mock_market({"testidr": bars}) as state:
            res1 = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
            self.assertEqual(res1["status"], "ok")
            self.assertEqual(res1["orders"], 1)
            st = self.storage.get_state()
            self.assertIn("testidr", st["positions"])
            pos = st["positions"]["testidr"]
            self.assertGreater(pos["qty"], 0)
            self.assertGreater(pos["stop"], 0)
            entry_ct = pos["entry_candle_time"]
            self.assertEqual(st["last_processed"]["testidr"], bars[-1]["time"])

            # tick kedua pada candle yang sama: tidak boleh membeli lagi
            res2 = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
            self.assertEqual(res2["orders"], 0)
            self.assertEqual(len(self.storage.read("orders")), 1)
            self.assertEqual(self.storage.get_state()["positions"]["testidr"]["qty"], pos["qty"])

            # candle berikutnya turun tajam -> trailing stop
            new = dict(bars[-1])
            new["time"] = bars[-1]["time"] + TF
            new["open"] = bars[-1]["close"]
            new["close"] = bars[-1]["close"] * 0.90
            new["high"] = new["open"]
            new["low"] = new["close"] * 0.995
            new["volume"] = 100000.0
            state["bars"]["testidr"] = bars + [new]
            res3 = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
            self.assertEqual(res3["orders"], 1)
            st = self.storage.get_state()
            self.assertNotIn("testidr", st["positions"])
            trades = self.storage.read("trades")
            self.assertEqual(len(trades), 1)
            self.assertLess(trades[0]["net_pnl"], 0)
            self.assertEqual(trades[0]["exit_reason"], "atr_trailing_stop")
            self.assertEqual(trades[0]["holding_bars"], 1)
            self.assertEqual(trades[0]["entry_time"][:10], trades[0]["exit_time"][:10])

    def test_kill_switch_blocks_entry(self):
        self.storage.set_kill(True)
        bars = make_bars(240)
        with mock_market({"testidr": bars}):
            res = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
            self.assertEqual(res["orders"], 0)
            self.assertEqual(self.storage.get_state()["positions"], {})
            dec = [d for d in self.storage.read("decisions") if d.get("pair") == "testidr"][-1]
            self.assertIn("kill switch", dec["reason"])

    def test_invalid_depth_does_not_mark_candle(self):
        bars = make_bars(240)
        with mock_market({"testidr": bars}):
            with patch.object(botmod, "get_depth", Mock(return_value={"bid": None, "ask": None, "bids": [], "asks": []})):
                res = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
                self.assertEqual(res["orders"], 0)
                st = self.storage.get_state()
                self.assertNotIn("testidr", st.get("last_processed", {}))
                dec = [d for d in self.storage.read("decisions") if d.get("pair") == "testidr"][-1]
                self.assertFalse(dec["processed"])
                self.assertFalse(dec["data_valid"])

    def test_lock_prevents_overlap(self):
        bars = make_bars(240)
        tok = self.storage.acquire_lock("tick", 60)
        self.assertIsNotNone(tok)
        with mock_market({"testidr": bars}):
            res = botmod.run_tick(self.storage, config=self.cfg, trigger="test")
            self.assertEqual(res["status"], "locked")
            self.assertEqual(res["orders"], 0)
        self.storage.release_lock("tick", tok)


class TestConfig(unittest.TestCase):
    def test_no_secret_and_official_costs(self):
        cfg = load_strategy()
        self.assertGreaterEqual(cfg["fees"]["buy_pct"], cfg["fees"]["api_pairs_taker_pct"])
        self.assertGreaterEqual(cfg["fees"]["sell_pct"], cfg["fees"]["api_pairs_taker_pct"])
        self.assertEqual(cfg["min_order_idr"], 25000)
        self.assertGreaterEqual(len(cfg["universe"]), 3)
        self.assertLessEqual(len(cfg["universe"]), 10)
        self.assertEqual(cfg["timeframe_seconds"], 14400)
        # tidak boleh ada nilai secret nyata di config
        raw = json.dumps(cfg).lower()
        for bad in ("upstash_redis_rest_token=", "cron_secret="):
            self.assertNotIn(bad, raw)


if __name__ == "__main__":
    unittest.main()
