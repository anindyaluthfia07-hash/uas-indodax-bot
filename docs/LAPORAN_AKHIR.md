# Laporan Akhir UAS — Bot Dry-Run Indodax

**Nama:** Anindya Rahma Luthfia  
**NIM:** 25110200036  
**Mata kuliah:** Algoritma Trading  
**Tanggal laporan:** 2026-11-14 08:09 WIB (2026-11-14T01:09:12Z)  
**Strategi:** Donchian Breakout + EMA Trend Filter + ATR Trailing Stop (adaptasi UTS ke kripto IDR)  
**Timeframe:** 4 jam · **Universe:** 6 pair IDR · **Modal simulasi:** Rp100.000.000

> Laporan ini dihasilkan oleh `scripts/build_report.py` dari file hasil. Angka tidak ditulis tangan. Bagian yang belum terjadi ditulis apa adanya.

## A. Yang sudah selesai

| Komponen | Status | Bukti |
|---|---|---|
| Data candle 4 jam, 35 kandidat, 2022-08-01 s/d 2026-11-08 | Selesai | `data/raw/*_240.csv`, `download_meta_240.json` |
| Pemilihan universe pada 60 hari pertama (bukan hari ini) | Selesai | `data/universe.json` |
| Strategi tunggal dipakai backtest + bot | Selesai | `core/strategy.py` |
| Backtest portofolio 4 tahun + biaya per transaksi | Selesai | `data/backtest_results.json` |
| Pengukuran fee resmi + spread + slippage order book | Selesai | `data/costs.json`, `docs/evidence/` |
| Uji in-sample / out-of-sample sekali | Selesai | bagian B |
| Stress test fee 2×, biaya 2×, delay 1 bar | Selesai | bagian B |
| Bot dry-run: tick, idempotensi, lock, kill switch, log | Selesai | `core/bot.py`, `data/local/` |
| API Vercel: tick, dashboard, health, kill, export | Selesai (kode) | `api/*.py` |
| Dashboard HTML offline + versi online | Selesai | `public/offline_dashboard.html`, `dashboard_offline.html`, `public/index.html` |
| Skrip hitung ulang & analisis gap | Selesai | `scripts/recompute.py`, `scripts/gap_analysis.py` |
| Unit test | 17 tes lulus | `tests/test_core.py` |
| `.env.example`, `.gitignore`, tanpa secret di repo | Selesai | root repo |
| Pembekuan (freeze) | **Terlambat** | `docs/FREEZE.md` |
| Forward test (freeze → 14 Nov 2026 12.00 WIB) | Berjalan 5.02 hari dari 5.18 hari | `data/local/`, `data/gap_analysis.json` |
| Deploy Vercel/GitHub | Sudah | `data/project_status.json` |

## B. Hasil backtest

Periode: **2022-11-08T00:00:00Z s/d 2026-11-08T00:00:00Z** (4.00 tahun), modal awal Rp100.000.000, tanpa leverage.

### B.1 Metrik utama (setelah fee + spread + slippage)

| Metrik | Nilai |
|---|---:|
| Ekuitas akhir | Rp214.510.697 |
| Return total | +114.51% |
| CAGR | +21.02% |
| Max drawdown | -19.45% |
| Profit factor | 1.57 |
| Win rate | 30.03% |
| Jumlah trade tertutup | 383 |
| Fee total | Rp55.670.588 |
| Spread total | Rp12.566.256 |
| Slippage total | Rp3.414.736 |
| Biaya total | Rp71.651.581 |
| Biaya / laba kotor | 21.23% |

### B.2 In-sample vs out-of-sample

Parameter dipilih **hanya** dari 70% awal. OOS dievaluasi sekali dan tidak dipakai memilih ulang.

| Periode | Rentang | Return total | CAGR | Max DD | Profit factor | Trade |
|---|---|---:|---:|---:|---:|---:|
| In-sample (70%) | 2022-11-08T00:00:00Z s/d 2025-08-26T16:00:00Z | +131.39% | +34.94% | -18.96% | 1.97 | 280 |
| Out-of-sample (30%) | 2025-08-27T00:00:00Z s/d 2026-11-08T00:00:00Z | -7.59% | -6.37% | -21.53% | 0.77 | 103 |

**Catatan jujur:** OOS negatif (-6.37% CAGR). Artinya performa in-sample tidak berlanjut pada 30% terakhir. Ini tidak dihilangkan dari laporan.

### B.3 Stress test

| Skenario | CAGR | Max DD | Profit factor | Trade | Biaya total |
|---|---:|---:|---:|---:|---:|
| Fee 2× | +10.72% | -25.47% | 1.25 | 383 | Rp107.241.516 |
| Fee + spread + slippage 2× | +18.30% | -21.15% | 1.48 | 387 | Rp83.492.812 |
| Eksekusi delay 1 bar | +19.51% | -20.66% | 1.55 | 372 | Rp66.157.189 |

### B.4 Benchmark beli-dan-tahan BTC

| Metrik | Strategi | BTC buy & hold |
|---|---:|---:|
| Return total | +114.51% | +320.66% |
| CAGR | +21.02% | +43.21% |
| Max drawdown | -19.45% | -49.43% |

Strategi memberi return lebih rendah dari BTC, tetapi drawdown lebih kecil. Ini bukan kemenangan return; hanya profil risiko yang berbeda.

### B.5 Konsentrasi laba

| Hal | Nilai |
|---|---:|
| Total net profit dari trade yang menang | Rp315.162.804 |
| Laba 5 trade terbaik | Rp97.159.367 |
| Porsi 5 trade terbaik | 30.83% |
| Jumlah net trade tanpa 5 trade terbaik | Rp17.351.330 |

### B.6 Return per tahun

| Tahun | Ekuitas akhir tahun | Return |
|---|---:|---:|
| 2022 | Rp97.342.334 | -2.66% |
| 2023 | Rp99.875.941 | +2.60% |
| 2024 | Rp202.986.548 | +103.24% |
| 2025 | Rp233.199.892 | +14.88% |
| 2026 | Rp214.510.697 | -8.01% |

Tahun parsial: 2022, 2026. Angka tahun parsial tidak bisa dibandingkan langsung dengan tahun penuh.

### B.7 Sensitivitas parameter

Setiap parameter digeser ±20%. Ini uji kestabilan, bukan pencarian parameter baru.

| Parameter | Nilai | CAGR | Max DD | Calmar | Trade |
|---|---:|---:|---:|---:|---:|
| lookback ×0.8 | 32 | +23.45% | -20.99% | 1.12 | 405 |
| lookback ×1.2 | 48 | +20.68% | -20.44% | 1.01 | 373 |
| fast_ema ×0.8 | 16 | +21.65% | -19.76% | 1.10 | 392 |
| fast_ema ×1.2 | 24 | +20.90% | -19.72% | 1.06 | 375 |
| trend_ema ×0.8 | 80 | +19.61% | -22.39% | 0.88 | 403 |
| trend_ema ×1.2 | 120 | +21.51% | -18.66% | 1.15 | 372 |
| atr_mult ×0.8 | 2.4 | +19.10% | -22.78% | 0.84 | 427 |
| atr_mult ×1.2 | 3.6 | +24.52% | -21.45% | 1.14 | 356 |

### B.8 Biaya yang diukur

| Komponen | Nilai |
|---|---:|
| Jumlah snapshot order book dipakai | 366 |
| Fee beli | 0.20555% |
| Fee jual | 0.41555% |
| Minimum order | Rp25.000 |

Spread dan slippage per pair berasal dari `data/costs.json`; nilainya adalah median snapshot 8 November 2026, bukan kondisi historis 2022–2026. Ini asumsi yang dicatat.

### B.9 Cara menghitung ulang

```bash
python3 scripts/backtest.py --final
python3 scripts/recompute.py --source local
python3 scripts/build_offline_dashboard.py
```

## C. Status freeze

| Hal | Nilai |
|---|---|
| Tenggat menurut tugas | 4 November 2026, 12:00 WIB |
| Commit pembekuan dibuat | 2026-11-09T00:35:31Z |
| Commit hash pembekuan | `1bc81524f6babff24406b17593633f5a10cd336f` |
| Ref/tag yang dipakai config | freeze-2026-11-09 |
| HEAD saat laporan dibuat | `ab199b4f1983af82765c0a5639e39c280c07ce35` |
| Tag | freeze-2026-11-09 |
| Status | **TERLAMBAT 4.8 hari** (commit aktual 2026-11-09T00:35:31Z; pekerjaan dimulai 8 November 2026) |

Tidak ada backdate. Commit memakai waktu sebenarnya. Konsekuensi: proyek tidak dapat diklaim dibekukan tepat waktu, dan forward test baru dimulai setelah freeze. Rincian bukti ada di `docs/FREEZE.md` dan `docs/FREEZE_MANIFEST.json`.

Manifest freeze: 90 file, dibuat 2026-11-09T00:35:37Z.

## D. Status forward test

| Hal | Nilai |
|---|---|
| Mulai | 2026-11-09T00:35:58Z |
| Batas akhir periode | 2026-11-14T05:00:00Z (14 Nov 2026 12.00 WIB) |
| Durasi periode | 5.18 hari |
| Status periode | Berjalan, sisa 3.8 jam |
| Durasi berjalan | 5.02 hari |
| Jumlah tick | 20 |
| Tick sukses / percobaan | 20 / 31 |
| Error API tercatat | 45 baris (44 DNS, 1 lainnya) |
| Candle hilang (per pair) | 16 dari 30 |
| Trade tertutup | 0 |
| Ekuitas terakhir | Rp100.000.000 |
| Return | +0.00% |
| Max drawdown | +0.00% |
| Uptime candle (rata-rata pair) | 46.67% |
| Uptime scheduler | 63.33% |
| Status hitung ulang | PASS |

Pemeriksaan integritas:

- [PASS] ada titik ekuitas — 20 titik
- [PASS] ada state forward — 2026-11-09T00:35:58Z
- [PASS] final equity == metrik — equity=100000000.0
- [PASS] net_pnl = gross - fee - spread - slippage — 0 trade diperiksa, 0 menyimpang
- [PASS] total fee konsisten — trades=0.00 metrik=0.00
- [PASS] total spread konsisten — trades=0.00 metrik=0.00
- [PASS] total slippage konsisten — trades=0.00 metrik=0.00
- [PASS] rekonsiliasi ekuitas — final=100000000.00 rekonstruksi=100000000.00 selisih=0.00
- [PASS] order_id unik — 0 order, 0 unik
- [PASS] tidak ada eksekusi ganda per pair+candle — []
- [PASS] dashboard == hasil hitung ulang — {}

**Catatan periode:** periode forward test ditetapkan dari tick pertama (2026-11-09T00:35:58Z) sampai **14 November 2026 12.00 WIB** (total 5.18 hari). Saat laporan ini dibuat, periode masih berjalan (sisa 3.8 jam). Durasi dan gap dihitung dari log yang benar-benar terjadi; tidak ada candle yang ditambal dan tidak ada tanggal yang dimundurkan.

**Catatan kualitas:** 11 dari 31 tick gagal, terutama karena error jaringan (DNS/koneksi) pada mesin penjadwal. Bot pulih sendiri, tetapi candle yang terlewat tetap hilang dan **tidak** ditambal. Karena itu uptime di atas bukan 100%; forward test ini tidak boleh diklaim bersih.

Rincian: `data/recomputed.json`, `data/gap_analysis.json`, `docs/FORWARD_TEST.md`.

### D.1 Kecocokan backtest vs forward pada jendela yang sama

Backtest dijalankan ulang pada candle 4 jam yang sama dengan forward test, memakai fungsi sinyal yang sama (`core/strategy.py`). Angka dihitung oleh `scripts/forward_vs_backtest.py`.

| Hal | Nilai |
|---|---|
| Jendela | 2026-11-09T00:00:00Z s/d 2026-11-12T20:00:00Z |
| Candle per pair | 24 |
| Pair-candle diharapkan | 144 |
| Pair-candle diproses bot | 66 |
| Cakupan candle | 45.8% |
| Candle sinyal diperiksa | 60 |
| Komponen sinyal dibandingkan | 300 |
| Komponen sinyal identik | 300 |
| Sinyal cocok | 60 |
| Sinyal tidak cocok | 0 |
| **Match rate sinyal** | **100.0%** |
| Return backtest jendela | +0.00% |
| Trade backtest jendela | 0 |
| Return forward | +0.00% |
| Trade forward | 0 |

| Pair | Candle diharapkan | Diproses | Cocok | Mismatch | Missing | Match rate |
|---|---:|---:|---:|---:|---:|---:|
| btcidr | 24 | 11 | 10 | 0 | 13 | 100.0% |
| dogeidr | 24 | 11 | 10 | 0 | 13 | 100.0% |
| ethidr | 24 | 11 | 10 | 0 | 13 | 100.0% |
| xrpidr | 24 | 11 | 10 | 0 | 13 | 100.0% |
| bnbidr | 24 | 11 | 10 | 0 | 13 | 100.0% |
| trxidr | 24 | 11 | 10 | 0 | 13 | 100.0% |

**Interpretasi:** pada candle yang benar-benar diproses bot, sinyal masuk identik 100% dengan backtest. Perbandingan dilakukan bukan hanya pada keputusan akhir, tetapi juga pada 5 komponen sinyal (breakout Donchian, harga di atas EMA tren, EMA cepat di atas EMA tren, volume, dan A/D): 300 dari 300 komponen identik. Tidak ada perbedaan sinyal yang disebabkan kode. Selisih cakupan (45.8%) berasal dari candle yang tidak diproses karena jadwal terlewat/error jaringan, dan dicatat sebagai missing - bukan ditambal.

Rincian candle-per-candle: `data/forward_signals.csv`.


## E. Status deployment

| Hal | Nilai |
|---|---|
| Repo GitHub | https://github.com/anindyaluthfia07-hash/uas-indodax-bot |
| URL Vercel | https://uas-indodax-bot-25110200036.vercel.app |
| GitHub Actions | aktif (tick tiap 4 jam) |
| Penyimpanan | repo git (`data/local/*.jsonl`) untuk tick terjadwal; Upstash Redis opsional untuk `POST /api/tick` |

Dashboard online: https://uas-indodax-bot-25110200036.vercel.app

Deployment ini nyata dan bisa dibuka. Halaman utama serta `/api/health` dan `/api/dashboard` membaca data yang di-commit ke repo, jadi angka di sana sama dengan laporan ini. Tanpa Upstash, endpoint `/api/tick` menolak menulis (baca-saja) dan penjadwal memakai jalur commit GitHub Actions; hal ini ditulis apa adanya, bukan disembunyikan.

Langkah manual ada di `docs/DEPLOYMENT.md` dan bagian G di bawah.

## F. Checklist ketentuan UAS

| Ketentuan | Status | Bukti / catatan |
|---|---|---|
| 3–10 pair IDR likuid | **Terpenuhi** (6 pair) | `config/strategy.json`, `data/universe.json` |
| Long-only, tanpa margin/leverage | **Terpenuhi** | `core/strategy.py`; tidak ada kode short |
| Tanpa API key, API publik Indodax | **Terpenuhi** | `core/exchange.py`; hanya endpoint publik |
| Timeframe 4 jam / 1 jam / harian | **Terpenuhi** (4 jam) | `config/strategy.json` |
| Backtest minimal 3 tahun | **Terpenuhi** (4.00 tahun) | `data/backtest_results.json` |
| Fee, spread, slippage diukur | **Terpenuhi** | `data/costs.json`, snapshot 366 baris |
| Dry-run pada bid/ask | **Terpenuhi** (kode + tick lokal) | `core/bot.py`, `data/local/ticks.jsonl`, `data/local/decisions.jsonl` |
| Penjadwal otomatis | **Aktif** (GitHub Actions tiap 4 jam) | `.github/workflows/tick.yml` |
| Penyimpanan persisten | **Terpenuhi** | state/log di-commit ke repo (`data/local/*.jsonl`); Upstash Redis opsional untuk endpoint tick |
| Log lengkap | **Terpenuhi** (format JSONL) | `data/local/*.jsonl`; `api/export.py` |
| Manajemen risiko | **Terpenuhi** | max 5 posisi, 20%, ADV 5%, min order, daily loss, kill switch |
| Deploy Vercel | **Terpenuhi** | https://uas-indodax-bot-25110200036.vercel.app |
| Dashboard HTML offline | **Terpenuhi** | `dashboard_offline.html` (root) + `public/offline_dashboard.html` |
| Skrip hitung ulang | **Terpenuhi** | `scripts/recompute.py`, `scripts/gap_analysis.py` |
| Backtest ulang jendela forward + banding sinyal | **Terpenuhi** (match 100.0%) | `data/forward_vs_backtest.json`, `data/forward_signals.csv` |
| `.env.example`, tanpa secret | **Terpenuhi** | `.env.example`, `.gitignore` |
| Freeze tepat waktu | **TIDAK** (terlambat 4.8 hari) | `docs/FREEZE.md` |
| Forward test sesuai periode (freeze → 14 Nov 2026 12.00 WIB) | **Berjalan 5.02 hari** dari 5.18 hari | lihat D |

## G. Yang harus saya lakukan

1. **Baca dan setujui dokumen.** `docs/PERNYATAAN_AI.md`, `docs/REFLEKSI.md`, dan laporan ini. Ubah bagian yang tidak sesuai. Jangan menandatangani pernyataan yang tidak dipahami.
2. **Kumpulkan tautan:** repo https://github.com/anindyaluthfia07-hash/uas-indodax-bot, dashboard https://uas-indodax-bot-25110200036.vercel.app, dan berkas `dashboard_offline.html` / `public/offline_dashboard.html` (bisa dibuka tanpa internet).
3. **Sebutkan terus terang dua kekurangan:** freeze terlambat 4.8 hari dan forward test berjalan 5.02 hari dari periode 5.18 hari (batas 14 Nov 2026 12.00 WIB). Jangan mengubah tanggal atau menambah log.
4. **Setelah 14 Nov 2026 12.00 WIB:** periode forward selesai dan penjadwal berhenti melakukan tick otomatis. Jalankan `python3 scripts/recompute.py --source local`, `python3 scripts/build_offline_dashboard.py`, dan `python3 scripts/build_report.py` sekali lagi dari log terakhir, lalu kumpulkan.
5. **Opsional:** hubungkan Upstash Redis bila ingin `POST /api/tick` juga menulis dari cloud. Langkahnya ada di bagian 3b `docs/DEPLOYMENT.md`.
6. **Jangan** mengubah parameter strategi di tengah forward test, memalsukan tanggal commit, mengisi log yang hilang, atau mengklaim hasil yang belum terjadi.

---

Dokumen pendukung: `README.md`, `docs/METHODOLOGY.md`, `docs/FREEZE.md`, `docs/FORWARD_TEST.md`, `docs/DEPLOYMENT.md`, `docs/PERNYATAAN_AI.md`, `docs/REFLEKSI.md`, `data/README.md`.
