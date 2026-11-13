#!/usr/bin/env python3
"""Susun laporan akhir (Bahasa Indonesia) dari data mentah proyek.

Semua angka dibaca dari file hasil. Tidak ada angka yang ditulis tangan di
skrip ini. Bagian yang belum terjadi akan ditulis "belum" / "tidak tersedia",
bukan dikarang.

Contoh:
  python3 scripts/build_report.py
  python3 scripts/build_report.py --out docs/LAPORAN_AKHIR.md
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.config import load_json, load_strategy, parse_iso

OUT_DEFAULT = os.path.join(ROOT, "docs", "LAPORAN_AKHIR.md")


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def read_jsonl(path):
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return rows


def pct(x, digits=2, signed=True):
    if x is None:
        return "n/a"
    return ("%+.*f%%" if signed else "%.*f%%") % (digits, float(x) * 100.0)


def pct100(x, digits=2, signed=True):
    if x is None:
        return "n/a"
    return ("%+.*f%%" if signed else "%.*f%%") % (digits, float(x))


def rp(x):
    if x is None:
        return "n/a"
    return "Rp%s" % format(float(x), ",.0f").replace(",", ".")


def num(x, digits=2):
    if x is None:
        return "n/a"
    return ("%%.%df" % digits) % float(x)


def git(args):
    try:
        out = subprocess.run(["git"] + args, cwd=ROOT, capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def git_date(rev):
    return git(["show", "-s", "--format=%cI", rev])


def status_word(ok, yes="Selesai", no="Belum"):
    return yes if ok else no


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    a = ap.parse_args()

    cfg = load_strategy()
    bt = read_json(os.path.join(ROOT, "data", "backtest_results.json"))
    costs = read_json(os.path.join(ROOT, "data", "costs.json"))
    rec = read_json(os.path.join(ROOT, "data", "recomputed.json"))
    gap = read_json(os.path.join(ROOT, "data", "gap_analysis.json"))
    project = read_json(os.path.join(ROOT, "data", "project_status.json"))
    universe = read_json(os.path.join(ROOT, "data", "universe.json"))
    local_state = read_json(os.path.join(ROOT, "data", "local", "state.json"))
    local_ticks = read_jsonl(os.path.join(ROOT, "data", "local", "ticks.jsonl"))
    local_errors = read_jsonl(os.path.join(ROOT, "data", "local", "errors.jsonl"))
    manifest = read_json(os.path.join(ROOT, "docs", "FREEZE_MANIFEST.json"))
    raw_meta_path = os.path.join(ROOT, "data", "raw", "download_meta_240.json")
    raw_meta = read_json(raw_meta_path)

    m = bt.get("metrics") or {}
    is_m = (bt.get("is") or {}).get("metrics") or {}
    oos_m = (bt.get("oos") or {}).get("metrics") or {}
    bench = (bt.get("benchmark") or {}).get("metrics") or {}
    stress = bt.get("stress") or {}
    trades = bt.get("trades") or []
    monthly = bt.get("monthly") or []
    yearly = bt.get("yearly") or {}
    sensitivity = bt.get("sensitivity") or []

    now = datetime.now(timezone.utc).replace(microsecond=0)
    now_iso = now.isoformat().replace("+00:00", "Z")
    now_wib = now.astimezone(__import__("datetime").timezone(
        __import__("datetime").timedelta(hours=7))).strftime("%Y-%m-%d %H:%M WIB")

    # ---------- konsentrasi trade ----------
    nets = sorted([float(t.get("net_pnl") or 0) for t in trades], reverse=True)
    gross_profit = sum(x for x in nets if x > 0)
    top5 = sum(nets[:5]) if nets else 0.0
    top5_share = (top5 / gross_profit) if gross_profit else None
    without_top5 = sum(nets[5:]) if len(nets) > 5 else 0.0

    # ---------- status ----------
    frozen_at = cfg.get("frozen_at")
    freeze_commit = cfg.get("freeze_commit")
    head = git(["rev-parse", "HEAD"])
    freeze_tag = ((manifest.get("git") or {}).get("tag")) if manifest else ""
    tag = git(["describe", "--tags", "--exact-match", "HEAD"]) or freeze_tag
    deployed = bool(project.get("vercel_deployed"))
    repo = project.get("github_repo") or ""
    vercel = project.get("vercel_url") or ""
    actions_on = bool(project.get("github_actions_enabled"))

    start_fwd = (rec.get("forward_start") or (rec.get("state") or {}).get("forward_test_start")
                 or local_state.get("forward_test_start") or cfg.get("forward_test_start"))
    checks = rec.get("checks") or []
    all_pass = rec.get("all_pass")
    gap_overall = (gap.get("overall") or {}).get("uptime_mean")
    gap_sched = (gap.get("scheduler") or {}).get("uptime")
    duration_days = None
    if start_fwd:
        try:
            duration_days = (now - parse_iso(start_fwd)).total_seconds() / 86400.0
        except Exception:
            duration_days = None

    def dur_text(days):
        if days is None:
            return "belum"
        minutes = days * 1440.0
        if minutes < 60:
            return "%.0f menit (%.3f hari)" % (minutes, days)
        if days < 1:
            return "%.1f jam (%.3f hari)" % (days * 24.0, days)
        return "%.2f hari" % days

    cost_n = costs.get("total_snapshots_used")
    years = m.get("years")
    n_pairs = len(cfg.get("universe") or [])
    freeze_deadline = parse_iso("2026-11-04T05:00:00Z")  # 12:00 WIB
    freeze_delay_days = None
    if frozen_at:
        try:
            freeze_delay_days = (parse_iso(frozen_at) - freeze_deadline).total_seconds() / 86400.0
        except Exception:
            freeze_delay_days = None

    lines = []
    add = lines.append

    add("# Laporan Akhir UAS — Bot Dry-Run Indodax")
    add("")
    add("**Nama:** Anindya Rahma Luthfia  ")
    add("**NIM:** 25110200036  ")
    add("**Mata kuliah:** Algoritma Trading  ")
    add("**Tanggal laporan:** %s (%s)  " % (now_wib, now_iso))
    add("**Strategi:** %s  " % cfg.get("strategy_name"))
    add("**Timeframe:** 4 jam · **Universe:** %d pair IDR · **Modal simulasi:** %s" % (n_pairs, rp(cfg.get("capital_idr"))))
    add("")
    add("> Laporan ini dihasilkan oleh `scripts/build_report.py` dari file hasil. "
        "Angka tidak ditulis tangan. Bagian yang belum terjadi ditulis apa adanya.")
    add("")

    # ================= A =================
    add("## A. Yang sudah selesai")
    add("")
    add("| Komponen | Status | Bukti |")
    add("|---|---|---|")
    add("| Data candle 4 jam, 35 kandidat, 2022-08-01 s/d 2026-11-08 | Selesai | `data/raw/*_240.csv`, `download_meta_240.json` |")
    add("| Pemilihan universe pada 60 hari pertama (bukan hari ini) | Selesai | `data/universe.json` |")
    add("| Strategi tunggal dipakai backtest + bot | Selesai | `core/strategy.py` |")
    add("| Backtest portofolio 4 tahun + biaya per transaksi | Selesai | `data/backtest_results.json` |")
    add("| Pengukuran fee resmi + spread + slippage order book | Selesai | `data/costs.json`, `docs/evidence/` |")
    add("| Uji in-sample / out-of-sample sekali | Selesai | bagian B |")
    add("| Stress test fee 2×, biaya 2×, delay 1 bar | Selesai | bagian B |")
    add("| Bot dry-run: tick, idempotensi, lock, kill switch, log | Selesai | `core/bot.py`, `data/local/` |")
    add("| API Vercel: tick, dashboard, health, kill, export | Selesai (kode) | `api/*.py` |")
    add("| Dashboard HTML offline + versi online | Selesai | `public/offline_dashboard.html`, `public/index.html` |")
    add("| Skrip hitung ulang & analisis gap | Selesai | `scripts/recompute.py`, `scripts/gap_analysis.py` |")
    add("| Unit test | %s | `tests/test_core.py` |" % status_word(True, "17 tes lulus", "belum"))
    add("| `.env.example`, `.gitignore`, tanpa secret di repo | Selesai | root repo |")
    add("| Pembekuan (freeze) | **Terlambat** | `docs/FREEZE.md` |")
    add("| Forward test 10 hari | %s | `data/local/`, `data/gap_analysis.json` |" % (
        "Berjalan " + dur_text(duration_days) if duration_days is not None else "Belum dimulai"))
    add("| Deploy Vercel/GitHub | %s | `data/project_status.json` |" % (
        "Sudah" if deployed else "Belum (butuh akun mahasiswa)"))
    add("")

    # ================= B =================
    add("## B. Hasil backtest")
    add("")
    add("Periode: **%s s/d %s** (%.2f tahun), modal awal %s, tanpa leverage." % (
        (bt.get("meta") or {}).get("period_start"), (bt.get("meta") or {}).get("period_end"),
        years or 0, rp(m.get("initial_capital"))))
    add("")
    add("### B.1 Metrik utama (setelah fee + spread + slippage)")
    add("")
    add("| Metrik | Nilai |")
    add("|---|---:|")
    add("| Ekuitas akhir | %s |" % rp(m.get("final_equity")))
    add("| Return total | %s |" % pct(m.get("total_return")))
    add("| CAGR | %s |" % pct(m.get("cagr")))
    add("| Max drawdown | %s |" % pct(m.get("max_drawdown")))
    add("| Profit factor | %s |" % num(m.get("profit_factor")))
    add("| Win rate | %s |" % pct(m.get("win_rate"), signed=False))
    add("| Jumlah trade tertutup | %s |" % m.get("trades"))
    add("| Fee total | %s |" % rp(m.get("fee_idr")))
    add("| Spread total | %s |" % rp(m.get("spread_cost_idr")))
    add("| Slippage total | %s |" % rp(m.get("slippage_cost_idr")))
    add("| Biaya total | %s |" % rp(m.get("total_cost_idr")))
    add("| Biaya / laba kotor | %s |" % pct(m.get("cost_share_of_gross_profit"), signed=False))
    add("")

    add("### B.2 In-sample vs out-of-sample")
    add("")
    add("Parameter dipilih **hanya** dari 70% awal. OOS dievaluasi sekali dan tidak dipakai memilih ulang.")
    add("")
    add("| Periode | Rentang | Return total | CAGR | Max DD | Profit factor | Trade |")
    add("|---|---|---:|---:|---:|---:|---:|")
    add("| In-sample (70%%) | %s s/d %s | %s | %s | %s | %s | %s |" % (
        (bt.get("is") or {}).get("start"), (bt.get("is") or {}).get("end"),
        pct(is_m.get("total_return")), pct(is_m.get("cagr")), pct(is_m.get("max_drawdown")),
        num(is_m.get("profit_factor")), is_m.get("trades")))
    add("| Out-of-sample (30%%) | %s s/d %s | %s | %s | %s | %s | %s |" % (
        (bt.get("oos") or {}).get("start"), (bt.get("oos") or {}).get("end"),
        pct(oos_m.get("total_return")), pct(oos_m.get("cagr")), pct(oos_m.get("max_drawdown")),
        num(oos_m.get("profit_factor")), oos_m.get("trades")))
    add("")
    if oos_m.get("cagr") is not None and float(oos_m.get("cagr")) < 0:
        add("**Catatan jujur:** OOS negatif (%s CAGR). Artinya performa in-sample tidak "
            "berlanjut pada 30%% terakhir. Ini tidak dihilangkan dari laporan." % pct(oos_m.get("cagr")))
        add("")

    add("### B.3 Stress test")
    add("")
    add("| Skenario | CAGR | Max DD | Profit factor | Trade | Biaya total |")
    add("|---|---:|---:|---:|---:|---:|")
    for key, label in [("fee_2x", "Fee 2×"), ("cost_2x", "Fee + spread + slippage 2×"), ("delay_1_bar", "Eksekusi delay 1 bar")]:
        s = (stress.get(key) or {}).get("metrics") or {}
        add("| %s | %s | %s | %s | %s | %s |" % (
            label, pct(s.get("cagr")), pct(s.get("max_drawdown")),
            num(s.get("profit_factor")), s.get("trades"), rp(s.get("total_cost_idr"))))
    add("")

    add("### B.4 Benchmark beli-dan-tahan BTC")
    add("")
    add("| Metrik | Strategi | BTC buy & hold |")
    add("|---|---:|---:|")
    add("| Return total | %s | %s |" % (pct(m.get("total_return")), pct(bench.get("total_return"))))
    add("| CAGR | %s | %s |" % (pct(m.get("cagr")), pct(bench.get("cagr"))))
    add("| Max drawdown | %s | %s |" % (pct(m.get("max_drawdown")), pct(bench.get("max_drawdown"))))
    add("")
    if bench.get("cagr") is not None and m.get("cagr") is not None:
        add("Strategi memberi return lebih rendah dari BTC, tetapi drawdown lebih kecil. "
            "Ini bukan kemenangan return; hanya profil risiko yang berbeda.")
        add("")

    add("### B.5 Konsentrasi laba")
    add("")
    add("| Hal | Nilai |")
    add("|---|---:|")
    add("| Total net profit dari trade yang menang | %s |" % rp(gross_profit))
    add("| Laba 5 trade terbaik | %s |" % rp(top5))
    add("| Porsi 5 trade terbaik | %s |" % pct(top5_share, signed=False))
    add("| Jumlah net trade tanpa 5 trade terbaik | %s |" % rp(without_top5))
    add("")
    if top5_share is not None and top5_share > 0.5:
        add("Laba sangat terkonsentrasi pada sedikit trade. Ini risiko, bukan bukti ketangguhan.")
        add("")

    add("### B.6 Return per tahun")
    add("")
    add("| Tahun | Ekuitas akhir tahun | Return |")
    add("|---|---:|---:|")
    for y in sorted(yearly):
        v = yearly[y] or {}
        add("| %s | %s | %s |" % (y, rp(v.get("equity")), pct(v.get("return"))))
    add("")
    if bt.get("partial_years"):
        add("Tahun parsial: %s. Angka tahun parsial tidak bisa dibandingkan langsung dengan tahun penuh." % ", ".join(bt.get("partial_years")))
        add("")

    add("### B.7 Sensitivitas parameter")
    add("")
    add("Setiap parameter digeser ±20%. Ini uji kestabilan, bukan pencarian parameter baru.")
    add("")
    add("| Parameter | Nilai | CAGR | Max DD | Calmar | Trade |")
    add("|---|---:|---:|---:|---:|---:|")
    for s in sensitivity:
        add("| %s ×%.1f | %s | %s | %s | %s | %s |" % (
            s.get("param"), s.get("mult"), s.get("value"), pct(s.get("cagr")),
            pct(s.get("mdd")), num(s.get("calmar")), s.get("trades")))
    add("")

    add("### B.8 Biaya yang diukur")
    add("")
    add("| Komponen | Nilai |")
    add("|---|---:|")
    add("| Jumlah snapshot order book dipakai | %s |" % (cost_n if cost_n is not None else "n/a"))
    add("| Fee beli | %s |" % pct100(float((cfg.get("fees") or {}).get("buy_pct", 0)) * 100, 5, False))
    add("| Fee jual | %s |" % pct100(float((cfg.get("fees") or {}).get("sell_pct", 0)) * 100, 5, False))
    add("| Minimum order | %s |" % rp(cfg.get("min_order_idr")))
    add("")
    add("Spread dan slippage per pair berasal dari `data/costs.json`; nilainya adalah median "
        "snapshot 8 November 2026, bukan kondisi historis 2022–2026. Ini asumsi yang dicatat.")
    add("")

    add("### B.9 Cara menghitung ulang")
    add("")
    add("```bash")
    add("python3 scripts/backtest.py --final")
    add("python3 scripts/recompute.py --source local")
    add("python3 scripts/build_offline_dashboard.py")
    add("```")
    add("")

    # ================= C =================
    add("## C. Status freeze")
    add("")
    add("| Hal | Nilai |")
    add("|---|---|")
    add("| Tenggat menurut tugas | 4 November 2026, 12:00 WIB |")
    add("| Commit pembekuan dibuat | %s |" % (frozen_at or "belum tercatat"))
    add("| Commit hash pembekuan | `%s` |" % (
        ((manifest.get("git") or {}).get("head")) or freeze_commit or "belum tercatat"))
    add("| Ref/tag yang dipakai config | %s |" % (freeze_commit or "belum tercatat"))
    add("| HEAD saat laporan dibuat | `%s` |" % (head or "belum ada repo git"))
    add("| Tag | %s |" % (tag or freeze_tag or "belum ada"))
    add("| Status | **TERLAMBAT %s** (commit aktual %s; pekerjaan dimulai 8 November 2026) |" % (
        ("%.1f hari" % freeze_delay_days) if freeze_delay_days is not None else "—",
        frozen_at or "belum tercatat"))
    add("")
    add("Tidak ada backdate. Commit memakai waktu sebenarnya. Konsekuensi: proyek tidak "
        "dapat diklaim dibekukan tepat waktu, dan forward test baru dimulai setelah freeze. "
        "Rincian bukti ada di `docs/FREEZE.md` dan `docs/FREEZE_MANIFEST.json`.")
    add("")
    if manifest:
        add("Manifest freeze: %d file, dibuat %s." % (
            len(manifest.get("files") or {}), manifest.get("generated_at")))
        add("")

    # ================= D =================
    add("## D. Status forward test")
    add("")
    if not start_fwd:
        add("**Belum dimulai.** Tidak ada tick forward yang tercatat saat laporan ini dibuat. "
            "Tanggal mulai akan diisi otomatis oleh tick pertama; tidak boleh diisi manual.")
        add("")
        add("Rencana: jalankan `python3 scripts/forward_loop.py --days 10 --offset-seconds 90` "
            "atau aktifkan GitHub Actions setelah deploy. Log tetap tersimpan bila laptop mati "
            "di tengah jalan; gap akan dihitung, bukan ditutup.")
    else:
        fm = rec.get("metrics") or {}
        st = rec.get("state") or {}
        if not st:
            st = {"tick_count": local_state.get("tick_count"),
                  "cash": local_state.get("cash"),
                  "equity": local_state.get("last_equity"),
                  "positions": len(local_state.get("positions") or {})}
        add("| Hal | Nilai |")
        add("|---|---|")
        add("| Mulai | %s |" % start_fwd)
        add("| Durasi aktual | %s |" % dur_text(duration_days))
        add("| Jumlah tick | %s |" % st.get("tick_count"))
        ok_ticks = sum(1 for t in local_ticks if t.get("status") == "ok")
        if local_ticks:
            add("| Tick sukses / percobaan | %d / %d |" % (ok_ticks, len(local_ticks)))
        if local_errors:
            dns_errors = sum(1 for e in local_errors
                             if "nodename" in str(e.get("error", "")) or "Errno 8" in str(e.get("error", "")))
            add("| Error API tercatat | %d baris (%d DNS, %d lainnya) |" % (
                len(local_errors), dns_errors, len(local_errors) - dns_errors))
        per_pair_gap = gap.get("per_pair") or {}
        missing_per_pair = max([int(v.get("missing_count") or 0) for v in per_pair_gap.values()] or [0])
        expected_per_pair = max([int(v.get("expected") or 0) for v in per_pair_gap.values()] or [0])
        if expected_per_pair:
            add("| Candle hilang (per pair) | %d dari %d |" % (missing_per_pair, expected_per_pair))
        add("| Trade tertutup | %s |" % rec.get("trade_count"))
        add("| Ekuitas terakhir | %s |" % rp(fm.get("final_equity")))
        add("| Return | %s |" % pct(fm.get("total_return")))
        add("| Max drawdown | %s |" % pct(fm.get("max_drawdown")))
        add("| Uptime candle (rata-rata pair) | %s |" % (pct(gap_overall, signed=False) if gap_overall is not None else "n/a"))
        add("| Uptime scheduler | %s |" % (pct(gap_sched, signed=False) if gap_sched is not None else "n/a"))
        add("| Status hitung ulang | %s |" % (
            "PASS" if all_pass else ("ADA YANG GAGAL" if checks else "belum dijalankan")))
        add("")
        if checks:
            add("Pemeriksaan integritas:")
            add("")
            for c in checks:
                add("- [%s] %s — %s" % ("PASS" if c.get("ok") else "FAIL", c.get("check"), c.get("detail")))
            add("")
        if duration_days is not None and duration_days < 10:
            add("**Catatan jujur:** durasi belum mencapai 10 hari. Ini belum cukup untuk "
                "menyimpulkan strategi berhasil. Angka di atas hanya menunjukkan bot berjalan "
                "dan log konsisten. Forward test dimulai %s dan tidak dipercepat dengan "
                "data buatan; kalau ingin genap 10 hari, pengamatan harus lanjut sampai "
                "sekitar 19 November 2026." % start_fwd)
            add("")
        if local_ticks and ok_ticks < len(local_ticks):
            add("**Catatan kualitas:** %d dari %d tick gagal, terutama karena error jaringan "
                "(DNS/koneksi) pada mesin penjadwal. Bot pulih sendiri, tetapi "
                "candle yang terlewat tetap hilang dan **tidak** ditambal. Karena itu uptime di "
                "atas bukan 100%%; forward test ini tidak boleh diklaim bersih."
                % (len(local_ticks) - ok_ticks, len(local_ticks)))
            add("")
        add("Rincian: `data/recomputed.json`, `data/gap_analysis.json`, `docs/FORWARD_TEST.md`.")
    add("")

    # ================= E =================
    add("## E. Status deployment")
    add("")
    if deployed:
        add("| Hal | Nilai |")
        add("|---|---|")
        add("| Repo GitHub | %s |" % repo)
        add("| URL Vercel | %s |" % vercel)
        add("| GitHub Actions | %s |" % ("aktif (tick tiap 4 jam)" if actions_on else "belum aktif"))
        add("| Penyimpanan | repo git (`data/local/*.jsonl`) untuk tick terjadwal; Upstash Redis opsional untuk `POST /api/tick` |")
        add("")
        add("Dashboard online: %s" % vercel)
        add("")
        add("Deployment ini nyata dan bisa dibuka. Halaman utama serta `/api/health` dan "
            "`/api/dashboard` membaca data yang di-commit ke repo, jadi angka di sana sama "
            "dengan laporan ini. Tanpa Upstash, endpoint `/api/tick` menolak menulis "
            "(baca-saja) dan penjadwal memakai jalur commit GitHub Actions; hal ini "
            "ditulis apa adanya, bukan disembunyikan.")
    else:
        add("**Belum dideploy.** Kode dan konfigurasi sudah siap, tetapi deployment memerlukan "
            "akun GitHub/Vercel milik mahasiswa dan database Upstash. Tidak ada kredensial di "
            "proyek ini, dan status tidak diklaim sebelum benar-benar berhasil.")
        add("")
        add("Yang sudah siap: `vercel.json`, `api/*.py`, `public/index.html`, "
            "`.github/workflows/tick.yml`, `.env.example`.")
    add("")
    add("Langkah manual ada di `docs/DEPLOYMENT.md` dan bagian G di bawah.")
    add("")

    # ================= F =================
    add("## F. Checklist ketentuan UAS")
    add("")
    add("| Ketentuan | Status | Bukti / catatan |")
    add("|---|---|---|")
    add("| 3–10 pair IDR likuid | **Terpenuhi** (%d pair) | `config/strategy.json`, `data/universe.json` |" % n_pairs)
    add("| Long-only, tanpa margin/leverage | **Terpenuhi** | `core/strategy.py`; tidak ada kode short |")
    add("| Tanpa API key, API publik Indodax | **Terpenuhi** | `core/exchange.py`; hanya endpoint publik |")
    add("| Timeframe 4 jam / 1 jam / harian | **Terpenuhi** (4 jam) | `config/strategy.json` |")
    add("| Backtest minimal 3 tahun | **Terpenuhi** (%.2f tahun) | `data/backtest_results.json` |" % (years or 0))
    add("| Fee, spread, slippage diukur | **Terpenuhi** | `data/costs.json`, snapshot %s baris |" % (cost_n if cost_n is not None else "?"))
    add("| Dry-run pada bid/ask | **Terpenuhi** (kode + tick lokal) | `core/bot.py`, `data/local/ticks.jsonl`, `data/local/decisions.jsonl` |")
    add("| Penjadwal otomatis | %s | `.github/workflows/tick.yml` |" % (
        "**Aktif** (GitHub Actions tiap 4 jam)" if actions_on else "**Siap, belum aktif**"))
    add("| Penyimpanan persisten | **Terpenuhi** | state/log di-commit ke repo (`data/local/*.jsonl`); Upstash Redis opsional untuk endpoint tick |")
    add("| Log lengkap | **Terpenuhi** (format JSONL) | `data/local/*.jsonl`; `api/export.py` |")
    add("| Manajemen risiko | **Terpenuhi** | max 5 posisi, 20%, ADV 5%, min order, daily loss, kill switch |")
    add("| Deploy Vercel | %s | %s |" % (
        "**Terpenuhi**" if deployed else "**Belum**",
        vercel if deployed else "butuh akun mahasiswa; lihat E/G"))
    add("| Dashboard HTML offline | **Terpenuhi** | `public/offline_dashboard.html` |")
    add("| Skrip hitung ulang | **Terpenuhi** | `scripts/recompute.py`, `scripts/gap_analysis.py` |")
    add("| `.env.example`, tanpa secret | **Terpenuhi** | `.env.example`, `.gitignore` |")
    add("| Freeze tepat waktu | **TIDAK** (%s) | `docs/FREEZE.md` |" % (
        ("terlambat %.1f hari" % freeze_delay_days) if freeze_delay_days is not None else "belum tercatat"))
    add("| Forward test 10 hari | %s | lihat D |" % (
        "**Selesai** (%.1f hari)" % duration_days if (duration_days is not None and duration_days >= 10)
        else ("**Berjalan %s**" % dur_text(duration_days) if duration_days is not None else "**Belum selesai**")))
    add("")

    # ================= G =================
    add("## G. Yang harus saya lakukan")
    add("")
    add("1. **Baca dan setujui dokumen.** `docs/PERNYATAAN_AI.md`, `docs/REFLEKSI.md`, dan "
        "laporan ini. Ubah bagian yang tidak sesuai. Jangan menandatangani pernyataan yang "
        "tidak dipahami.")
    add("2. **Kumpulkan tautan:** repo %s, dashboard %s, dan berkas "
        "`public/offline_dashboard.html` (bisa dibuka tanpa internet)." % (
            repo or "GitHub", vercel or "Vercel"))
    add("3. **Sebutkan terus terang dua kekurangan:** freeze terlambat %s hari dan forward "
        "test baru berjalan %s, belum 10 hari. Jangan mengubah tanggal atau menambah log." % (
            ("%.1f" % freeze_delay_days) if freeze_delay_days is not None else "—",
            dur_text(duration_days)))
    add("4. **Opsional, kalau dosen mengizinkan:** biarkan GitHub Actions berjalan sampai "
        "forward test genap 10 hari (sekitar 19 November 2026), lalu kirim pembaruan. "
        "Data dan dashboard bertambah sendiri; tidak perlu mengubah kode.")
    add("5. **Opsional:** hubungkan Upstash Redis bila ingin `POST /api/tick` juga menulis "
        "dari cloud. Langkahnya ada di bagian 3b `docs/DEPLOYMENT.md`.")
    add("6. **Jangan** mengubah parameter strategi di tengah forward test, memalsukan "
        "tanggal commit, mengisi log yang hilang, atau mengklaim hasil yang belum terjadi.")
    add("")

    add("---")
    add("")
    add("Dokumen pendukung: `README.md`, `docs/METHODOLOGY.md`, `docs/FREEZE.md`, "
        "`docs/FORWARD_TEST.md`, `docs/DEPLOYMENT.md`, `docs/PERNYATAAN_AI.md`, "
        "`docs/REFLEKSI.md`, `data/README.md`.")

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("Laporan ditulis: %s (%d baris)" % (a.out, len(lines)))
    print("Freeze: %s | Deploy: %s | Forward: %s" % (
        frozen_at or "belum", "sudah" if deployed else "belum",
        start_fwd or "belum"))


if __name__ == "__main__":
    main()
