#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistem Backtest & Pengujian Validitas Kuantitatif Algoritma Trading Saham BEI (Kompas100).

Mekanisme Utama:
  1. Multi-Timeframe Momentum & Breakout:
     - Sinyal beli pada penutupan hari t: Breakout tertinggi N-hari (Lookback)
       dikonfirmasi oleh Fast EMA > Trend EMA dan harga penutupan > Trend EMA.
       Volume TIDAK menjadi filter masuk; volume relatif (V / ADV20) hanya dipakai
       untuk mengurutkan antrean beli bila sinyal lebih banyak daripada slot kosong.
     - Eksekusi pembelian: Pada HARGA BUKA hari t+1 (09:00 WIB) + 1 fraksi bid-ask spread.
  2. Trailing Stop Waktu & ATR (Dual Protection):
     - Time Stop (pada praktiknya stop-loss -2% yang aktif mulai bar ke-3): pada setiap
       penutupan, bila posisi sudah ditahan >= 3 bar dan return terhadap harga beli <= -2.0%,
       posisi dijual pada pembukaan hari t+1.
     - ATR Trailing Stop (Ratchet): stop = max(stop sebelumnya, Close_t - ATR_mult * ATR14_t);
       dipicu bila harga PENUTUPAN < stop, dijual pada pembukaan hari berikutnya.
     - Death cross Fast EMA < Trend EMA sebagai sinyal keluar tren.
     - Eksekusi penjualan: Pada HARGA BUKA hari t+1 (09:00 WIB) - 1 fraksi bid-ask spread.
  3. Alokasi Modal & Realitas Mikrostruktur BEI:
     - Maksimal 5 posisi (masing-masing 20% ekuitas, compounding).
     - Likuiditas: Nilai order <= 5% ADV20.
     - Fraksi harga resmi BEI (1, 2, 5, 10, 25) dan pembulatan kelipatan 1 lot (100 lembar).
     - Pembatasan ARA/ARB: tidak membeli saat terkunci ARA, tidak menjual saat terkunci ARB.
     - 0 Look-Ahead Bias: sinyal close t dieksekusi di open t+1.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
import platform
import sys
import time
from datetime import datetime

import numpy as np
import pandas as pd

# ====================== KONFIGURASI TETAP ======================
MODAL = 100000000          # Rp100.000.000 modal awal
MAX_POS = 5                # maksimal 5 posisi terfokus (20% alokasi per posisi)
POS_FRAC = 0.20            # 20% ekuitas per posisi untuk efisiensi modal optimal
LIQ_FRAC = 0.05            # nilai order <= 5% rata-rata nilai transaksi harian 20 hari
ADV_N = 20
LOT = 100                  # 1 lot = 100 lembar saham
FEE_BUY = 0.0015           # 0,15% fee beli
FEE_SELL = 0.0025          # 0,25% fee jual (termasuk PPh final 0,1%)
ATR_N = 14
LOCK_MOVE = 0.065          # bar datar (H=L) dengan gerak >= 6,5% dianggap terkunci ARA/ARB
RF_ANNUAL = 0.06           # asumsi BI Rate 6%
BENCH = "^JKSE"

# Parameter yang dioptimasi (hanya 4 parameter, <= 5 sesuai ketentuan)
KEYS = ("lookback", "fast", "trend", "atr")
GRID = {
    "lookback": [20, 25, 30, 40],
    "fast": [10, 15, 20, 25],
    "trend": [50, 75, 100, 150],
    "atr": [2.5, 3.0, 3.5, 4.0],
}
FALLBACK = (25, 20, 100, 3.5)
IS_MIN_TRADES = 60
WF_MIN_TRADES = 15
MULTS = [0.5, 0.8, 1.0, 1.2, 1.5]

TIME_STOP_DAYS = 3
TIME_STOP_LOSS = -0.02     # cut jika setelah 3 hari return <= -2%

TRADE_COLS = ["sym", "entry_date", "exit_date", "lots", "ref_buy", "buy_price", "ref_sell",
              "sell_price", "fee", "spread", "gross", "net", "pct", "days", "reason"]


# ====================== FRAKSI HARGA BEI ======================
def tick1(p):
    return 1 if p < 200 else 2 if p < 500 else 5 if p < 2000 else 10 if p < 5000 else 25


def rtick1(p):
    t = tick1(p)
    return float(round(p / t) * t)


# ====================== DATA PASAR ======================
class Market(object):
    def __init__(self, df):
        df = df.drop_duplicates(["date", "ticker"])
        bench = df[df["ticker"] == BENCH].set_index("date")["close"].sort_index()
        st = df[df["ticker"] != BENCH]
        piv = {}
        for c in ("open", "high", "low", "close", "volume"):
            piv[c] = st.pivot(index="date", columns="ticker", values=c).sort_index()
        C0 = piv["close"]
        keep = C0.notna().sum(axis=1) >= 20
        idx = C0.index[keep]
        cols = list(C0.columns)

        def mat(c):
            return np.array(piv[c].reindex(index=idx, columns=cols).to_numpy(dtype=float))

        O, H, L, C, V = mat("open"), mat("high"), mat("low"), mat("close"), mat("volume")
        for a in (O, H, L, C):
            a[a <= 0] = np.nan
        V[np.isnan(V)] = 0.0
        self.dates = np.array(idx)
        self.sym = np.array(cols)
        self.T, self.N = C.shape
        self.O, self.H, self.L, self.C, self.V = O, H, L, C, V
        self.valid = ~np.isnan(C)
        self.hist = np.cumsum(self.valid, axis=0)
        self.Cf = np.array(pd.DataFrame(C).ffill().to_numpy())
        Cprev = np.vstack([np.full((1, self.N), np.nan), self.Cf[:-1]])
        flat = (H == L) & ~np.isnan(H)
        with np.errstate(invalid="ignore", divide="ignore"):
            mv = O / Cprev - 1.0
            lock_up = flat & (mv >= LOCK_MOVE)
            lock_dn = flat & (mv <= -LOCK_MOVE)
            opened = (O > 0) & (V > 0)
            self.can_buy = opened & ~lock_up
            self.can_sell = opened & ~lock_dn
            tr = np.fmax(np.fmax(H - L, np.abs(H - Cprev)), np.abs(L - Cprev))
        self.ATR = np.array(pd.DataFrame(tr).ewm(alpha=1.0 / ATR_N, adjust=False).mean().to_numpy())
        val = pd.DataFrame(np.where(np.isnan(self.Cf), np.nan, self.Cf * V))
        adv = np.array(val.rolling(ADV_N, min_periods=10).mean().to_numpy())
        adv[np.isnan(adv)] = 0.0
        self.ADV = adv
        self.vol_adv = V / (adv / self.Cf + 1e-6)

        self._ema = {}
        self._highs = {}

        # Benchmark IHSG
        self.bench_ok = len(bench) > 50
        if self.bench_ok:
            b = bench.reindex(idx).ffill()
            self.bench = b.to_numpy(dtype=float)
        else:
            self.bench = np.full(self.T, np.nan)

    def ema(self, n):
        if n not in self._ema:
            self._ema[n] = np.array(pd.DataFrame(self.Cf).ewm(span=n, adjust=False).mean().to_numpy())
        return self._ema[n]

    def high_channel(self, n):
        if n not in self._highs:
            min_p = max(5, int(n * 0.7))
            self._highs[n] = np.array(pd.DataFrame(self.H).rolling(n, min_periods=min_p).max().shift(1).to_numpy())
        return self._highs[n]

    def entries(self, p):
        lookback, fast, trend, _ = p
        h = self.high_channel(lookback)
        Ef = self.ema(fast)
        Et = self.ema(trend)
        # Sinyal: Close > N-day High, Close > Trend EMA, Fast EMA > Trend EMA, Volume > ADV, ADV > 0
        with np.errstate(invalid="ignore"):
            sig = (self.C > h) & (self.C > Et) & (Ef > Et) & (self.ADV > 0) & self.valid
        return sig


# ====================== SIMULASI PORTOFOLIO ======================
def simulate(m, p, i0, i1, cap=MODAL, fee=1.0, spr=1, delay=0, use_stop=True, use_timestop=True):
    lookback, fast, trend, atrm = p
    sig = m.entries(p)
    Et = m.ema(trend)
    Ef = m.ema(fast)
    O, C, Cf, ATR, ADV, vol_adv = m.O, m.C, m.Cf, m.ATR, m.ADV, m.vol_adv
    can_buy, can_sell, dates = m.can_buy, m.can_sell, m.dates
    cash = float(cap)
    pos, pend_sell, pend_buy = {}, {}, []
    n = i1 - i0 + 1
    eq = np.empty(n)
    inv = np.empty(n)
    npos = np.empty(n, dtype=int)
    trades = []
    skipped = {"tanpa_slot": 0, "terkunci_atau_tanpa_transaksi": 0, "lot_nol_likuiditas_atau_kas": 0}

    for t in range(i0, i1 + 1):
        # --- 1. Eksekusi penjualan pada HARGA BUKA hari t (09:00 WIB) ---
        for j in list(pend_sell.keys()):
            if pend_sell[j] <= t and j in pos and can_sell[t, j]:
                ps = pos.pop(j)
                del pend_sell[j]
                ref = rtick1(O[t, j])
                tk = tick1(ref)
                price = max(ref - tk * spr, float(tk))
                sh = ps["sh"]
                val = sh * price
                fs = val * FEE_SELL * fee
                cash += val - fs
                gross = sh * (ref - ps["ref"])
                spread = sh * (ps["price"] - ps["ref"]) + sh * (ref - price)
                net = sh * (price - ps["price"]) - ps["fee"] - fs
                basis = sh * ps["price"] + ps["fee"]
                trades.append({
                    "sym": m.sym[j], "entry_date": dates[ps["i"]], "exit_date": dates[t],
                    "lots": sh // LOT, "ref_buy": ps["ref"], "buy_price": ps["price"],
                    "ref_sell": ref, "sell_price": price, "fee": ps["fee"] + fs, "spread": spread,
                    "gross": gross, "net": net, "pct": net / basis * 100.0,
                    "days": (pd.Timestamp(dates[t]) - pd.Timestamp(dates[ps["i"]])).days,
                    "reason": ps["reason"], "entry_i": ps["i"], "exit_i": t, "deq": ps["deq"],
                })

        # --- 2. Eksekusi pembelian pada HARGA BUKA hari t (09:00 WIB) ---
        if pend_buy:
            rest = []
            for (ex, j, di, deq, st) in pend_buy:
                if ex > t:
                    rest.append((ex, j, di, deq, st))
                    continue
                if ex < t:
                    continue
                if j in pos or len(pos) >= MAX_POS:
                    skipped["tanpa_slot"] += 1
                    continue
                if not can_buy[t, j]:
                    skipped["terkunci_atau_tanpa_transaksi"] += 1
                    continue
                ref = rtick1(O[t, j])
                tk = tick1(ref)
                price = ref + tk * spr
                target = min(deq * POS_FRAC, LIQ_FRAC * ADV[di, j])
                lots = int(target // (price * LOT))
                lots = min(lots, int(cash // (price * LOT * (1.0 + FEE_BUY * fee))))
                if lots <= 0:
                    skipped["lot_nol_likuiditas_atau_kas"] += 1
                    continue
                sh = lots * LOT
                fb = sh * price * FEE_BUY * fee
                cash -= sh * price + fb
                pos[j] = {"sh": sh, "ref": ref, "price": price, "fee": fb, "i": t, "stop": st,
                          "highest": price, "reason": "", "deq": deq}
            pend_buy = rest

        # --- 3. Nilai pasar portofolio penutupan hari t ---
        iv = sum(ps["sh"] * Cf[t, j] for j, ps in pos.items())
        e = cash + iv
        k = t - i0
        eq[k], inv[k], npos[k] = e, iv, len(pos)

        # --- 4. Evaluasi kondisi keluar (exit) pada penutupan hari t ---
        for j, ps in pos.items():
            if j in pend_sell:
                continue
            c = C[t, j]
            if c != c:
                continue
            ps["highest"] = max(ps["highest"], c)
            h_days = t - ps["i"]
            reason = None

            # Time-based stagnation cut: "3 hari tidak kena bagian sekian baru cut"
            if use_timestop and h_days >= TIME_STOP_DAYS:
                ret_since_entry = (c - ps["price"]) / ps["price"]
                if ret_since_entry <= TIME_STOP_LOSS:
                    reason = f"Time Stop ({TIME_STOP_DAYS}d <= {TIME_STOP_LOSS*100:.1f}%)"

            # ATR trailing stop
            if not reason and use_stop and c < ps["stop"]:
                reason = "Trailing stop ATR"
            # Trend breakdown: Fast EMA cross below Trend EMA
            elif not reason and Ef[t, j] < Et[t, j] and Ef[t-1, j] >= Et[t-1, j]:
                reason = "Trend EMA Cross Exit"

            if reason:
                pend_sell[j] = t + 1 + delay
                ps["reason"] = reason
            elif use_stop:
                a = ATR[t, j]
                if a == a:
                    s2 = c - atrm * a
                    if s2 > ps["stop"]:
                        ps["stop"] = s2

        # --- 5. Evaluasi sinyal masuk (entry) pada penutupan hari t ---
        if t < i1:
            free = MAX_POS - (len(pos) - len(pend_sell)) - len(pend_buy)
            if free > 0:
                cand = np.flatnonzero(sig[t])
                if cand.size:
                    held = set(pos.keys())
                    queued = set(b[1] for b in pend_buy)
                    cl = [int(j) for j in cand if int(j) not in held and int(j) not in queued and ADV[t, j] > 0]
                    if cl:
                        # Prioritas: Lonjakan volume institusi relatif terhadap rata-rata 20 hari
                        cl.sort(key=lambda j: -vol_adv[t, j])
                        if len(cl) > free:
                            skipped["tanpa_slot"] += len(cl) - free
                        for j in cl[:free]:
                            a = ATR[t, j]
                            st = C[t, j] - atrm * a if a == a else -np.inf
                            pend_buy.append((t + 1 + delay, j, t, e, st))

    openpos = []
    for j, ps in pos.items():
        last = float(Cf[i1, j])
        basis = ps["sh"] * ps["price"] + ps["fee"]
        openpos.append({
            "sym": m.sym[j].replace(".JK", ""),
            "entry_date": dates[ps["i"]] + " 09:00",
            "lots": ps["sh"] // LOT, "buy_price": ps["price"], "last": last,
            "value": ps["sh"] * last, "pnl": ps["sh"] * last - basis,
            "pct": (ps["sh"] * last / basis - 1) * 100.0,
            "stop": None if not np.isfinite(ps["stop"]) else float(ps["stop"]),
            "days": (pd.Timestamp(dates[i1]) - pd.Timestamp(dates[ps["i"]])).days
        })
    return {"eq": eq, "inv": inv, "npos": npos, "trades": trades, "open": openpos,
            "dates": dates[i0:i1 + 1], "skipped": skipped}


# ====================== METRIK ======================
def span_years(d0, d1):
    return max((pd.Timestamp(d1) - pd.Timestamp(d0)).days / 365.25, 1.0 / 365.25)


def quick(eq, yrs, trades, cap=MODAL):
    final = float(eq[-1])
    cagr = (final / cap) ** (1.0 / yrs) - 1.0 if final > 0 else -1.0
    peak = np.maximum.accumulate(np.maximum(eq, cap))
    mdd = float((eq / peak - 1.0).min())
    calmar = cagr / abs(mdd) if mdd < -1e-9 else float("nan")
    nets = np.array([t["net"] for t in trades]) if trades else np.array([])
    wins = nets[nets > 0].sum() if nets.size else 0.0
    losses = abs(nets[nets <= 0].sum()) if nets.size else 0.0
    pf = wins / losses if losses > 0 else float("nan")
    return {"cagr": cagr, "mdd": mdd, "calmar": calmar, "trades": len(trades), "pf": pf, "final": final}


def calc_metrics(dates, eq, trades, cap=MODAL, npos=None, inv=None):
    eq = np.asarray(eq, dtype=float)
    d = pd.to_datetime(pd.Series(list(dates)))
    yrs = span_years(d.iloc[0], d.iloc[-1])
    q = quick(eq, yrs, trades, cap)
    s = pd.Series(eq, index=pd.DatetimeIndex(d))
    me = s.groupby(s.index.to_period("M")).last()
    prev = np.concatenate([[cap], me.values[:-1]])
    mr = me.values / prev - 1.0
    peak_prev = np.maximum.accumulate(np.concatenate([[cap], me.values]))[:-1]
    rec = me.values >= peak_prev - 1e-9
    pct_rec = float(rec.mean())
    P, pdte, maxgap = cap, d.iloc[0], 0
    for i in range(len(eq)):
        if eq[i] >= P:
            maxgap = max(maxgap, (d.iloc[i] - pdte).days)
            P, pdte = eq[i], d.iloc[i]
        else:
            maxgap = max(maxgap, (d.iloc[i] - pdte).days)
    ongoing = bool(eq[-1] < P)

    T = len(trades)
    nets = np.array([t["net"] for t in trades], dtype=float)
    pcts = np.array([t["pct"] for t in trades], dtype=float)
    days = np.array([t["days"] for t in trades], dtype=float)
    win = nets > 0
    nw, nl = int(win.sum()), int((~win).sum())
    wr = nw / T if T else float("nan")
    avg_w = float(pcts[win].mean()) if nw else float("nan")
    avg_l = float(pcts[~win].mean()) if nl else float("nan")
    avg_w_rp = float(nets[win].mean()) if nw else float("nan")
    avg_l_rp = float(nets[~win].mean()) if nl else float("nan")
    sw, sl = float(nets[win].sum()) if nw else 0.0, float(abs(nets[~win].sum())) if nl else 0.0
    pf = sw / sl if sl > 0 else float("nan")
    z = lambda v: 0.0 if v != v else v
    exp_pct = z(wr) * z(avg_w) + (1 - z(wr)) * z(avg_l) if T else float("nan")
    exp_rp = z(wr) * z(avg_w_rp) + (1 - z(wr)) * z(avg_l_rp) if T else float("nan")
    payoff = avg_w / abs(avg_l) if (nl and nw and avg_l != 0) else float("nan")

    sd = float(np.std(mr, ddof=1)) if len(mr) > 1 else float("nan")
    sharpe = float(np.mean(mr) / sd * math.sqrt(12)) if sd and sd == sd and sd > 0 else float("nan")
    rfm = (1 + RF_ANNUAL) ** (1 / 12.0) - 1
    sharpe_rf = float((np.mean(mr) - rfm) / sd * math.sqrt(12)) if sd and sd == sd and sd > 0 else float("nan")
    dd_dev = math.sqrt(float(np.mean(np.minimum(mr, 0.0) ** 2))) if len(mr) else float("nan")
    sortino = float(np.mean(mr) / dd_dev * math.sqrt(12)) if dd_dev and dd_dev > 0 else float("nan")

    streak = cur = 0
    for t in sorted(trades, key=lambda x: (x["exit_i"], x["entry_i"])):
        if t["net"] <= 0:
            cur += 1
            streak = max(streak, cur)
        else:
            cur = 0
    total_net = float(nets.sum()) if T else 0.0
    top10 = float(np.sort(nets)[::-1][:10].sum() / total_net) if (T and total_net > 0) else float("nan")
    fees = float(sum(t["fee"] for t in trades))
    spread = float(sum(t["spread"] for t in trades))
    gross = float(sum(t["gross"] for t in trades))
    out = {
        "years": yrs, "final_equity": q["final"], "cagr": q["cagr"], "mdd": q["mdd"],
        "calmar": q["calmar"], "win_ratio": wr, "wins": nw, "losses": nl,
        "avg_profit_pct": avg_w, "avg_profit_rp": avg_w_rp, "avg_loss_pct": avg_l, "avg_loss_rp": avg_l_rp,
        "profit_factor": pf, "pct_record_months": pct_rec, "n_months": int(len(me)),
        "longest_no_record_months": maxgap / 30.4375, "no_record_ongoing": ongoing,
        "trades": T, "trades_per_year": T / yrs, "avg_hold_days": float(days.mean()) if T else float("nan"),
        "small_sample": bool(T < 100), "expectancy_pct": exp_pct, "expectancy_rp": exp_rp, "payoff": payoff,
        "sharpe": sharpe, "sharpe_rf": sharpe_rf, "sortino": sortino,
        "longest_losing_streak": streak, "top10_share": top10,
        "net_pnl": total_net, "gross_pnl": gross, "fees": fees, "spread_cost": spread,
        "cost_share": (fees + spread) / gross if gross > 0 else float("nan"),
        "exposure_days": float((npos > 0).mean()) if npos is not None else float("nan"),
        "avg_capital_used": float(np.mean(inv / eq)) if inv is not None else float("nan"),
        "gross_win_rp": sw, "gross_loss_rp": sl,
    }
    return out


def monthly_table(dates, eq, cap=MODAL):
    s = pd.Series(np.asarray(eq, float), index=pd.DatetimeIndex(pd.to_datetime(pd.Series(list(dates)))))
    me = s.groupby(s.index.to_period("M")).last()
    prev = np.concatenate([[cap], me.values[:-1]])
    r = me.values / prev - 1.0
    years = sorted(set(int(p.year) for p in me.index))
    grid = dict((y, [None] * 12) for y in years)
    for p, v in zip(me.index, r):
        grid[int(p.year)][int(p.month) - 1] = float(v)
    ye = s.groupby(s.index.year).last()
    yprev = np.concatenate([[cap], ye.values[:-1]])
    yr = ye.values / yprev - 1.0
    yearly = dict((int(y), float(v)) for y, v in zip(ye.index, yr))
    first, last = s.index[0], s.index[-1]
    partial = {}
    for y in years:
        partial[y] = bool((y == first.year and first.month > 1) or (y == last.year and last.month < 12))
    return {"years": years, "grid": grid, "yearly": yearly, "partial": partial}


# ====================== PEMILIHAN PARAMETER (HANYA IN-SAMPLE) ======================
def all_combos(grid=None):
    g = grid or GRID
    return list(itertools.product(*[g[k] for k in KEYS]))


def grid_scan(m, i0, i1, label="", grid=None):
    yrs = span_years(m.dates[i0], m.dates[i1])
    res = {}
    combos = all_combos(grid)
    t0 = time.time()
    for n, c in enumerate(combos, 1):
        r = simulate(m, c, i0, i1)
        res[c] = quick(r["eq"], yrs, r["trades"])
        if label and (n % 64 == 0 or n == len(combos)):
            print("   %s: %d/%d kombinasi (%.0f dtk)" % (label, n, len(combos), time.time() - t0), flush=True)
    return res


def plateau_pick(res, min_trades, grid=None):
    g = grid or GRID
    shape = tuple(len(g[k]) for k in KEYS)
    S = np.full(shape, np.nan)
    for idx in np.ndindex(*shape):
        c = tuple(g[k][i] for k, i in zip(KEYS, idx))
        q = res[c]
        if q["trades"] >= min_trades and q["cagr"] > 0 and q["calmar"] == q["calmar"]:
            S[idx] = q["calmar"]
    sm = np.full(shape, np.nan)
    for idx in np.ndindex(*shape):
        if np.isnan(S[idx]):
            continue
        vals = [S[idx]]
        for d in range(4):
            for dd in (-1, 1):
                j = list(idx)
                j[d] += dd
                if 0 <= j[d] < shape[d]:
                    v = S[tuple(j)]
                    vals.append(0.0 if np.isnan(v) else v)
        sm[idx] = float(np.mean(vals))
    if np.all(np.isnan(sm)):
        return FALLBACK, False, []
    best = np.unravel_index(int(np.nanargmax(sm)), shape)
    chosen = tuple(g[k][i] for k, i in zip(KEYS, best))
    order = np.argsort(-np.nan_to_num(sm, nan=-1e9), axis=None)[:8]
    top = []
    for o in order:
        idx = np.unravel_index(int(o), shape)
        if np.isnan(sm[idx]):
            continue
        c = tuple(g[k][i] for k, i in zip(KEYS, idx))
        top.append({"params": list(c), "calmar": float(S[idx]), "smooth": float(sm[idx]),
                    "cagr": res[c]["cagr"], "mdd": res[c]["mdd"], "trades": res[c]["trades"]})
    return chosen, True, top


def vary(p, key_i, mult):
    q = list(p)
    if key_i == 3:
        q[3] = round(p[3] * mult, 1)
    else:
        q[key_i] = int(round(p[key_i] * mult))
    return tuple(q)


# ====================== UTILITAS OUTPUT ======================
def clean(o):
    if isinstance(o, dict):
        return dict((str(k), clean(v)) for k, v in o.items())
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.bool_, bool)):
        return bool(o)
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        v = float(o)
        return v if math.isfinite(v) else None
    return o


def trade_rows(trades):
    rows = []
    for t in sorted(trades, key=lambda x: (x["exit_i"], x["entry_i"])):
        rows.append([t["sym"].replace(".JK", ""), t["entry_date"] + " 09:00", t["exit_date"] + " 09:00", int(t["lots"]),
                     t["ref_buy"], round(t["buy_price"], 2), t["ref_sell"], round(t["sell_price"], 2),
                     round(t["fee"]), round(t["spread"]), round(t["gross"]), round(t["net"]),
                     round(t["pct"], 3), int(t["days"]), t["reason"]])
    return rows


def short_metrics(k):
    keys = ["years", "final_equity", "cagr", "mdd", "calmar", "win_ratio", "profit_factor", "avg_profit_pct",
            "avg_loss_pct", "trades", "expectancy_pct", "sharpe", "net_pnl", "exposure_days"]
    return dict((a, k.get(a)) for a in keys)


# ====================== PROGRAM UTAMA ======================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="results.json")
    ap.add_argument("--freeze", default="2026-09-01", help="tanggal pembekuan strategi, default 2026-09-01")
    ap.add_argument("--years", type=float, default=10.0)
    ap.add_argument("--strategi", default="Breakout Donchian + EMA Trend Following + Stop-Loss -2% (bar ke-3) + ATR Trailing Stop")
    ap.add_argument("--quick", action="store_true", help="grid kecil untuk uji cepat")
    a = ap.parse_args()
    t_start = time.time()

    global GRID
    if a.quick:
        GRID = {"lookback": [20, 30], "fast": [15, 20], "trend": [75, 100], "atr": [3.0, 3.5]}

    print("Membaca data pasar ...", flush=True)
    df = pd.read_csv(os.path.join(a.data, "prices.csv"))
    meta_in = {}
    mp = os.path.join(a.data, "_meta.json")
    if os.path.exists(mp):
        with open(mp) as f:
            meta_in = json.load(f)
    m = Market(df)
    
    # Titik akhir backtest adalah tanggal pembekuan strategi (freeze date)
    b1 = int(np.searchsorted(m.dates, a.freeze))
    if b1 >= m.T:
        b1 = m.T - 1
    
    # Titik awal backtest: minimal 10.00 tahun kalender penuh sebelum freeze date
    freeze_date_val = m.dates[b1]
    target_start = (pd.Timestamp(freeze_date_val) - pd.DateOffset(years=int(a.years))).strftime("%Y-%m-%d")
    b0 = int(np.searchsorted(m.dates, target_start))
    while span_years(m.dates[b0], m.dates[b1]) < a.years and b0 > 0:
        b0 -= 1
    
    years_avail = span_years(m.dates[b0], m.dates[b1])
    print("Periode Backtest: %s s/d %s (%.2f tahun, %d hari bursa, %d saham)" %
          (m.dates[b0], m.dates[b1], years_avail, b1 - b0 + 1, m.N), flush=True)
    print("Periode Forward Test: %s s/d %s (%d hari bursa, %.1f minggu)" %
          (m.dates[b1], m.dates[-1], m.T - b1, (pd.Timestamp(m.dates[-1]) - pd.Timestamp(m.dates[b1])).days / 7.0), flush=True)

    split_i = b0 + int(0.70 * (b1 - b0 + 1)) - 1
    
    # ---------- 1. Pilih parameter dari IN-SAMPLE (70% awal) ----------
    print("[1/7] Memilih parameter dari in-sample (%s s/d %s) ..." % (m.dates[b0], m.dates[split_i]), flush=True)
    res_is = grid_scan(m, b0, split_i, "Grid In-Sample")
    P, found, is_top = plateau_pick(res_is, IS_MIN_TRADES)
    if not found:
        print("PERINGATAN: tak ada kombinasi memenuhi syarat; pakai parameter cadangan %s" % (FALLBACK,), file=sys.stderr)
        P = FALLBACK
    print("   Parameter terpilih (lookback, fast, trend, atr) = %s" % (P,), flush=True)
    n_is = len(res_is)

    # ---------- 2. Backtest utama + uji biaya + uji tunda 1 bar ----------
    print("[2/7] Backtest utama 10 tahun + uji biaya + uji tunda 1 bar ...", flush=True)
    base = simulate(m, P, b0, b1)
    kb = calc_metrics(base["dates"], base["eq"], base["trades"], MODAL, base["npos"], base["inv"])
    pre = simulate(m, P, b0, b1, fee=0.0, spr=0)
    kp = calc_metrics(pre["dates"], pre["eq"], pre["trades"], MODAL, pre["npos"], pre["inv"])
    x2 = simulate(m, P, b0, b1, fee=2.0, spr=2)
    kx = calc_metrics(x2["dates"], x2["eq"], x2["trades"], MODAL, x2["npos"], x2["inv"])
    dly = simulate(m, P, b0, b1, delay=1)
    kd = calc_metrics(dly["dates"], dly["eq"], dly["trades"], MODAL, dly["npos"], dly["inv"])
    notime = simulate(m, P, b0, b1, use_timestop=False)
    # Sapuan biaya: fee dikalikan f, spread = s fraksi per transaksi
    sweep = []
    for f_mult, s_ticks, lab in [(1.0, 1, "Biaya normal (fee 1x, spread 1 fraksi)"),
                                 (1.5, 1, "Fee 1,5x, spread 1 fraksi"),
                                 (2.0, 1, "Fee 2x, spread 1 fraksi"),
                                 (1.0, 2, "Fee 1x, spread 2 fraksi"),
                                 (2.0, 2, "Biaya stres 2x (fee 2x, spread 2 fraksi)"),
                                 (3.0, 3, "Biaya 3x (fee 3x, spread 3 fraksi)")]:
        rr = simulate(m, P, b0, b1, fee=f_mult, spr=s_ticks)
        qq = quick(rr["eq"], span_years(m.dates[b0], m.dates[b1]), rr["trades"])
        sweep.append({"label": lab, "fee_mult": f_mult, "spread_ticks": s_ticks, "cagr": qq["cagr"],
                      "mdd": qq["mdd"], "pf": qq["pf"], "trades": qq["trades"]})
    knt = calc_metrics(notime["dates"], notime["eq"], notime["trades"], MODAL, notime["npos"], notime["inv"])

    # Pembanding beli-dan-tahan IHSG
    bench_eq = None
    bm = {"name": "IHSG (^JKSE), indeks harga", "cagr": None, "mdd": None, "final": None}
    if m.bench_ok:
        bs = m.bench[b0:b1 + 1]
        if np.isfinite(bs).all():
            bench_eq = bs / bs[0] * MODAL
            qb = quick(bench_eq, years_avail, [], MODAL)
            bm.update({"cagr": qb["cagr"], "mdd": qb["mdd"], "final": qb["final"]})

    # ---------- 3. In-sample vs out-of-sample ----------
    print("[3/7] In-sample vs out-of-sample (70/30) ...", flush=True)
    r_is = simulate(m, P, b0, split_i)
    r_os = simulate(m, P, split_i + 1, b1)
    k_is = calc_metrics(r_is["dates"], r_is["eq"], r_is["trades"], MODAL, r_is["npos"], r_is["inv"])
    k_os = calc_metrics(r_os["dates"], r_os["eq"], r_os["trades"], MODAL, r_os["npos"], r_os["inv"])

    # ---------- 4. Walk-forward analysis (4 pasang latih -> uji) ----------
    print("[4/7] Walk-forward (5 jendela, 4 pasang latih -> uji) ...", flush=True)
    edges = np.linspace(b0, b1 + 1, 6).astype(int)
    wins = [(int(edges[i]), int(edges[i + 1]) - 1) for i in range(5)]
    wf_rows, st_dates, st_eq, st_trades = [], [], [], []
    run_eq = float(MODAL)
    for k in range(4):
        tr0, tr1 = wins[k]
        te0, te1 = wins[k + 1]
        rs = grid_scan(m, tr0, tr1, "WF Jendela #%d" % (k + 1))
        pk, ok_, _ = plateau_pick(rs, WF_MIN_TRADES)
        rt = simulate(m, pk, te0, te1)
        km = calc_metrics(rt["dates"], rt["eq"], rt["trades"], MODAL, rt["npos"], rt["inv"])
        trq = rs[pk]
        wf_rows.append({"window": k + 1, "train": [m.dates[tr0], m.dates[tr1]], "test": [m.dates[te0], m.dates[te1]],
                        "params": list(pk), "selected": bool(ok_), "train_cagr": trq["cagr"], "train_calmar": trq["calmar"],
                        "train_trades": trq["trades"], "test": {"start": m.dates[te0], "end": m.dates[te1], **short_metrics(km)}})
        scale = run_eq / MODAL
        for dte, ev in zip(rt["dates"], rt["eq"]):
            st_dates.append(dte)
            st_eq.append(float(ev) * scale)
        run_eq = st_eq[-1]
        st_trades.extend(rt["trades"])
    k_st = calc_metrics(st_dates, st_eq, st_trades, MODAL, None, None)
    n_wf = len(all_combos()) * 4

    # ---------- 5. Sensitivitas parameter ----------
    print("[5/7] Sensitivitas parameter (+-20%% dan +-50%%) ...", flush=True)
    cache = {P: quick(base["eq"], years_avail, base["trades"])}

    def sens(p):
        if p not in cache:
            r = simulate(m, p, b0, b1)
            cache[p] = quick(r["eq"], years_avail, r["trades"])
        return cache[p]

    oned = []
    labels = ["Breakout Lookback", "Fast EMA", "Trend EMA", "ATR Multiplier"]
    for ki in range(4):
        for mu in MULTS:
            p = vary(P, ki, mu)
            q = sens(p)
            oned.append({"param": labels[ki], "mult": mu, "value": p[ki], "valid": q is not None,
                         "cagr": q["cagr"] if q else None, "mdd": q["mdd"] if q else None,
                         "pf": q["pf"] if q else None, "calmar": q["calmar"] if q else None,
                         "trades": q["trades"] if q else None})

    def heat(ia, ib):
        rows, cols = [vary(P, ia, mu)[ia] for mu in MULTS], [vary(P, ib, mu)[ib] for mu in MULTS]
        cg, cl = [], []
        for mu_a in MULTS:
            r1, r2 = [], []
            for mu_b in MULTS:
                p = list(P)
                p[ia] = vary(P, ia, mu_a)[ia]
                p[ib] = vary(P, ib, mu_b)[ib]
                q = sens(tuple(p))
                r1.append(q["cagr"] if q else None)
                r2.append(q["calmar"] if q else None)
            cg.append(r1)
            cl.append(r2)
        return {"rows_label": labels[ia], "cols_label": labels[ib], "rows": rows, "cols": cols,
                "mults": MULTS, "cagr": cg, "calmar": cl}

    heat_fs = heat(0, 1)
    heat_ta = heat(2, 3)
    vals = [q for p, q in cache.items() if q is not None and p != P]
    pos_share = float(np.mean([1.0 if q["cagr"] > 0 else 0.0 for q in vals])) if vals else float("nan")
    med_cagr = float(np.median([q["cagr"] for q in vals])) if vals else float("nan")
    sens_summary = {"n_variants": len(vals), "share_positive": pos_share, "median_cagr": med_cagr,
                    "base_cagr": kb["cagr"], "plateau": bool(vals and pos_share >= 0.8 and med_cagr >= 0.5 * kb["cagr"])}
    n_sens = len([1 for p, q in cache.items() if q is not None])

    # ---------- 6. Ketahanan + Monte Carlo ----------
    print("[6/7] Uji ketahanan + Monte Carlo (bootstrap 2.000 iterasi) ...", flush=True)
    tr = base["trades"]
    nets = np.array([t["net"] for t in tr])
    order = np.argsort(-nets)
    top5_net = float(nets[order[:5]].sum()) if len(tr) >= 5 else float("nan")
    rest = nets[order[5:]] if len(tr) > 5 else np.array([])
    w5, l5 = rest[rest > 0].sum() if rest.size else 0.0, abs(rest[rest <= 0].sum()) if rest.size else 0.0
    mt = monthly_table(base["dates"], base["eq"])
    yrs_neg = [y for y, v in mt["yearly"].items() if v < 0]
    robust = {"net_total": float(nets.sum()), "top5_net": top5_net, "net_without_top5": float(nets.sum() - top5_net),
              "pf_without_top5": float(w5 / l5) if l5 > 0 else None,
              "top5": [{"sym": tr[i]["sym"].replace(".JK", ""), "exit": tr[i]["exit_date"], "net": float(nets[i])} for i in order[:5]],
              "loss_years": yrs_neg, "n_years": len(mt["yearly"])}
    rng = np.random.RandomState(42)
    contrib = np.array([t["net"] / t["deq"] for t in tr]) if tr else np.array([])
    mc = None
    if contrib.size >= 10:
        B = 2000
        draw = rng.randint(0, contrib.size, size=(B, contrib.size))
        cum = np.cumprod(1.0 + contrib[draw], axis=1)
        final = cum[:, -1]
        cg = np.where(final > 0, final, 1e-9) ** (1.0 / years_avail) - 1.0
        peak = np.maximum.accumulate(np.maximum(cum, 1.0), axis=1)
        mdd = (cum / peak - 1.0).min(axis=1)
        mc = {"runs": B, "cagr_p5": float(np.percentile(cg, 5)), "cagr_p50": float(np.percentile(cg, 50)),
              "mdd_p5": float(np.percentile(mdd, 5)), "mdd_p50": float(np.percentile(mdd, 50)),
              "share_positive": float((cg > 0).mean())}

    # ---------- 7. Forward test (Sept - Okt 2026, 4+ minggu) ----------
    print("[7/7] Forward test paper trading (%s s/d %s) ..." % (m.dates[b1], m.dates[-1]), flush=True)
    fwd_bars = m.T - b1
    rf = simulate(m, P, b1, m.T - 1)
    kf = calc_metrics(rf["dates"], rf["eq"], rf["trades"], MODAL, rf["npos"], rf["inv"])
    fwd_bench_eq = None
    fwd_bm = {"return": None, "mdd": None}
    if m.bench_ok:
        fbs = m.bench[b1:m.T]
        if np.isfinite(fbs).all():
            fwd_bench_eq = (fbs / fbs[0] * MODAL).tolist()
            fwd_bm["return"] = float(fbs[-1] / fbs[0] - 1.0)
            fwd_peak = np.maximum.accumulate(fbs)
            fwd_bm["mdd"] = float((fbs / fwd_peak - 1.0).min())
            
    fwd_dd = (rf["eq"] / np.maximum.accumulate(np.maximum(rf["eq"], MODAL)) - 1.0).tolist()
    fwd = {
        "status": "ok",
        "freeze_date": a.freeze,
        "start": m.dates[b1],
        "end": m.dates[-1],
        "n_bars": fwd_bars,
        "weeks": round((pd.Timestamp(m.dates[-1]) - pd.Timestamp(m.dates[b1])).days / 7.0, 1),
        "metrics": kf,
        "return_pct": float(rf["eq"][-1] / MODAL - 1.0) * 100.0,
        "bench": fwd_bm,
        "equity": {"dates": list(rf["dates"]), "eq": [round(float(v)) for v in rf["eq"]],
                   "bench": None if fwd_bench_eq is None else [round(float(v)) for v in fwd_bench_eq],
                   "dd": [round(float(v), 5) for v in fwd_dd]},
        "trades": trade_rows(rf["trades"]),
        "open": rf["open"],
        "short": bool(fwd_bars < 20)
    }

    # ---------- Tanda bahaya (Red Flags) ----------
    flags = []

    def add(name, trig, detail):
        flags.append({"name": name, "triggered": bool(trig), "detail": detail})

    f_ = lambda v: "n/a" if v is None or v != v else "%.1f%%" % (v * 100)
    add("CAGR jangka panjang di atas 100% per tahun", kb["cagr"] > 1.0, "CAGR = " + f_(kb["cagr"]))
    add("Win ratio di atas 80% dengan avg loss sangat kecil",
        kb["win_ratio"] == kb["win_ratio"] and kb["win_ratio"] > 0.8 and abs(kb["avg_loss_pct"] or 0) < 1.0,
        "win ratio = " + f_(kb["win_ratio"]))
    add("Profit factor di atas 3 pada periode panjang", (kb["profit_factor"] or 0) > 3, "PF = %.2f" % (kb["profit_factor"] or float("nan")))
    add("Kurva ekuitas hampir lurus tanpa drawdown berarti", abs(kb["mdd"]) < 0.05, "MDD = " + f_(kb["mdd"]))
    add("Hasil out-of-sample jauh lebih baik daripada in-sample",
        k_os["cagr"] > max(2.5 * k_is["cagr"], k_is["cagr"] + 0.35), "CAGR IS = %s, OOS = %s" % (f_(k_is["cagr"]), f_(k_os["cagr"])))
    add("Hasil runtuh saat eksekusi ditunda 1 bar", kd["cagr"] < 0 or kd["cagr"] < 0.5 * kb["cagr"],
        "CAGR dasar = %s, tunda 1 bar = %s" % (f_(kb["cagr"]), f_(kd["cagr"])))
    add("Tidak ada satu pun tahun rugi selama periode uji", len(yrs_neg) == 0 and len(mt["yearly"]) >= 5,
        "tahun rugi: %s" % (", ".join(str(y) for y in yrs_neg) if yrs_neg else "tidak ada"))
    add("Sebagian besar laba berasal dari 1-2 trade",
        len(tr) >= 2 and robust["net_total"] > 0 and (np.sort(nets)[::-1][:2].sum() / robust["net_total"]) > 0.5,
        "2 trade terbaik = %s dari laba bersih" % (f_(np.sort(nets)[::-1][:2].sum() / robust["net_total"]) if robust["net_total"] > 0 else "n/a"))

    # ---------- Rakit hasil ----------
    dd = (base["eq"] / np.maximum.accumulate(np.maximum(base["eq"], MODAL)) - 1.0)
    code_hash = hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()[:16]
    out = {
        "meta": {
            "nama": "Anindya Rahma Luthfia",
            "strategi": a.strategi, "freeze_date": a.freeze,
            "data_source": meta_in.get("source", "Yahoo Finance (kompas100_harian.csv)"),
            "data_download": meta_in.get("download_datetime", "2026-10-16"),
            "price_basis": meta_in.get("price_basis", "Harga disesuaikan (split & dividen) dari Yahoo Finance"),
            "synthetic": bool(meta_in.get("synthetic", False)),
            "tickers_failed": meta_in.get("tickers_failed", []),
            "universe_n": int(m.N), "period_start": m.dates[b0], "period_end": m.dates[b1],
            "years": years_avail, "bars": int(b1 - b0 + 1), "split_date": m.dates[split_i],
            "capital": MODAL, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "code_sha256": code_hash, "bench_name": bm["name"], "bench_ok": bool(m.bench_ok),
            "python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__,
            "runtime_s": round(time.time() - t_start, 1),
        },
        "config": {"max_pos": MAX_POS, "pos_frac": POS_FRAC, "liq_frac": LIQ_FRAC, "adv_n": ADV_N, "lot": LOT,
                   "fee_buy": FEE_BUY, "fee_sell": FEE_SELL, "atr_n": ATR_N,
                   "time_stop_days": TIME_STOP_DAYS, "time_stop_loss": TIME_STOP_LOSS,
                   "lock_move": LOCK_MOVE, "rf_annual": RF_ANNUAL, "grid": GRID, "is_min_trades": IS_MIN_TRADES,
                   "wf_min_trades": WF_MIN_TRADES},
        "params": {"lookback": P[0], "fast": P[1], "trend": P[2], "atr": P[3], "from_fallback": (not found)},
        "metrics": kb, "bench": bm,
        "equity": {"dates": list(base["dates"]), "eq": [round(float(v)) for v in base["eq"]],
                   "bench": None if bench_eq is None else [round(float(v)) for v in bench_eq],
                   "dd": [round(float(v), 5) for v in dd]},
        "trade_cols": TRADE_COLS, "trades": trade_rows(tr), "open_positions": base["open"],
        "monthly": mt, "skipped": base["skipped"],
        "isoos": {"split_date": m.dates[split_i], "is": {"start": m.dates[b0], "end": m.dates[split_i], "m": k_is},
                  "oos": {"start": m.dates[split_i + 1], "end": m.dates[b1], "m": k_os}},
        "is_top": is_top,
        "walkforward": {"rows": wf_rows, "stitched": {"dates": st_dates, "eq": [round(v) for v in st_eq]}, "stitched_metrics": k_st},
        "sensitivity": {"oned": oned, "heat_fs": heat_fs, "heat_ta": heat_ta, "summary": sens_summary},
        "search": {"is_grid": n_is, "wf_grid": n_wf, "sens": n_sens,
                   "total": n_is + n_wf + n_sens, "optimised_params": 4, "grid": GRID},
        "robust": robust, "mc": mc,
        "costs": {"pre": kp, "base": kb, "x2": kx},
        "delay": {"base": kb, "delayed": kd},
        "ablation": {"no_timestop": knt}, "cost_sweep": sweep,
        "forward": fwd, "flags": flags,
    }
    with open(a.out, "w") as f:
        json.dump(clean(out), f, separators=(",", ":"))
    kbs = kb
    print("\n================ RINGKASAN ================")
    print("Parameter terpilih : lookback=%s fast=%s trend=%s atr=%s" % P)
    print("CAGR %.1f%% | MDD %.1f%% | PF %.2f | win %.1f%% | trade %d | Sharpe %.2f" %
          (kbs["cagr"] * 100, kbs["mdd"] * 100, kbs["profit_factor"] or float("nan"), kbs["win_ratio"] * 100, kbs["trades"], kbs["sharpe"]))
    print("IS CAGR %.1f%% | OOS CAGR %.1f%% | tunda-1-bar CAGR %.1f%% | biaya 2x CAGR %.1f%%" %
          (k_is["cagr"] * 100, k_os["cagr"] * 100, kd["cagr"] * 100, kx["cagr"] * 100))
    print("IHSG buy&hold CAGR %s | MDD %s" % (f_(bm["cagr"]), f_(bm["mdd"])))
    print("Forward test (%.1f wks): Return %+.2f%% | Trade %d | Open %d" %
          (fwd["weeks"], fwd["return_pct"], len(fwd["trades"]), len(fwd["open"])))
    print("Selesai dalam %.0f detik -> %s" % (time.time() - t_start, a.out))


if __name__ == "__main__":
    main()
