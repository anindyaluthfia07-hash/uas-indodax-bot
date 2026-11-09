# UAS Algoritma Trading — Bot Dry-Run Indodax

**Anindya Rahma Luthfia · NIM 25110200036**

Bot trading kripto **dry-run** (tanpa uang, tanpa API key) untuk pair IDR di
Indodax, dengan backtest 4 tahun, biaya nyata (fee + spread + slippage), log
mentah, dashboard offline/online, dan skrip hitung ulang.

> **Status jujur:** freeze **terlambat 4,8 hari** (tenggat 4 Nov 2026 12.00 WIB;
> commit aktual **9 Nov 2026 07.35 WIB**, hash `1bc8152…`, tag
> `freeze-2026-11-09`), forward test **baru berjalan** (mulai 9 Nov 2026
> 07.35 WIB, belum 10 hari), dan deployment Vercel **belum** dilakukan karena
> membutuhkan akun mahasiswa. Semua status aktual ada di
> [`docs/LAPORAN_AKHIR.md`](docs/LAPORAN_AKHIR.md), bukan di README ini.

---

## Hasil backtest (4 tahun, setelah biaya)

Periode **2022-11-08 s/d 2026-11-08**, modal Rp100.000.000, 6 pair IDR, long-only.

| Metrik | Nilai |
|---|---:|
| Return total | **+114,51%** |
| CAGR | **+21,02%** |
| Max drawdown | **−19,45%** |
| Profit factor | 1,57 |
| Win rate | 30,03% (115/383) |
| Trade tertutup | 383 |
| Fee + spread + slippage | **Rp71.651.581** (21,23% laba kotor) |
| In-sample CAGR (70%) | +34,94% |
| **Out-of-sample CAGR (30%)** | **−6,37%** |
| BTC buy & hold CAGR | +43,21% (MDD −49,43%) |

Angka di atas berasal dari `data/backtest_results.json`. **OOS negatif** dan
strategi kalah return dari BTC; ini dilaporkan apa adanya, bukan disembunyikan.
Lihat [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) untuk aturan dan asumsi.

---

## Cara menjalankan (lokal, Python 3.9+)

Tidak perlu `pip install` apa pun. Seluruh kode memakai standard library.

```bash
cd uas-indodax-bot

# 1. satu tick bot (butuh internet)
python3 scripts/run_tick.py

# 2. loop forward test 10 hari (laptop harus menyala)
python3 scripts/forward_loop.py --days 10 --offset-seconds 90

# 3. backtest ulang
python3 scripts/backtest.py --final

# 4. hitung ulang metrik dari log mentah
python3 scripts/recompute.py --source local
python3 scripts/gap_analysis.py --source local

# 5. bangun dashboard offline
python3 scripts/build_offline_dashboard.py

# 6. susun laporan akhir
python3 scripts/build_report.py

# 7. unit test
python3 -m unittest discover -s tests -v
```

Dashboard offline: buka `public/offline_dashboard.html` langsung di browser
(tanpa server). Versi online memakai `public/index.html` + `/api/dashboard`
setelah deploy.

---

## Strategi

Adaptasi UTS ke kripto: **Donchian breakout 40 bar + filter EMA20/EMA100 +
ATR trailing stop 3× + time stop**.

- **Masuk:** close > tertinggi 40 bar sebelumnya, close > EMA100, EMA20 > EMA100,
  volume > 0.
- **Keluar:** time stop (≥3 bar dan return ≤ −2%), close < trailing stop
  (`max(stop lama, close − 3×ATR14)`), atau EMA20 memotong ke bawah EMA100.
- **Ukuran:** maksimal 5 posisi, 20% ekuitas per posisi, maksimal 5% ADV20,
  minimum order Rp25.000.
- **Biaya:** fee taker all-in beli 0,20555%, jual 0,41555%; spread dan slippage
  dari median order book 8 Nov 2026.
- **Eksekusi:** backtest di open candle berikutnya; bot di bid/ask aktual
  (walk the book).

Detail lengkap: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

---

## Struktur

```
uas-indodax-bot/
├── api/                  # Vercel Python functions (tick, dashboard, health, kill, export)
├── config/
│   ├── strategy.json     # parameter, universe, fee, risk, freeze metadata
│   └── candidates.json   # 35 kandidat pair IDR
├── core/                 # strategi, indikator, exchange, storage, bot, metrics, backtest
├── data/
│   ├── raw/              # candle 4 jam + metadata unduhan
│   ├── snapshots/        # order book mentah
│   ├── local/            # state + log JSONL forward test (dibuat saat bot jalan)
│   ├── backtest_results.json
│   ├── costs.json
│   └── project_status.json
├── docs/
│   ├── LAPORAN_AKHIR.md  # laporan A–G
│   ├── METHODOLOGY.md
│   ├── FREEZE.md
│   ├── FORWARD_TEST.md
│   ├── DEPLOYMENT.md
│   ├── PERNYATAAN_AI.md
│   ├── REFLEKSI.md
│   └── evidence/         # tangkapan layar biaya Indodax
├── public/               # dashboard online + offline
├── scripts/              # unduh, pilih universe, backtest, tick, recompute, laporan
├── tests/
├── .env.example
├── vercel.json
└── .github/workflows/    # tick tiap 4 jam + tests
```

---

## Dashboard

- **Offline:** `public/offline_dashboard.html` — satu file, data tertanam, bisa
  dibuka via `file://`.
- **Online:** `public/index.html` — mengambil `/api/dashboard`; angka forward
  test dihitung ulang dari log, bukan ditulis tangan.
- **Data mentah:** `public/dashboard_data.json`.
- **CSV:** `public/backtest_trades.csv`, `public/backtest_equity_daily.csv`.

Dashboard menampilkan status freeze, deployment, forward test, biaya yang
dipakai, dan peringatan bila data belum tersedia. Tidak ada klaim deployment
sebelum `data/project_status.json` diisi.

---

## Deploy

Ikuti [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md). Ringkas:

1. Buat repo GitHub, push kode.
2. Buat Upstash Redis dari Vercel Marketplace.
3. Import repo ke Vercel, isi `CRON_SECRET` + dua variabel Upstash.
4. Uji `/api/health`, `/api/tick`, `/api/dashboard`.
5. Aktifkan GitHub Actions (tick tiap 4 jam) dan isi `VERCEL_URL`.
6. Perbarui `data/project_status.json` hanya setelah deploy berhasil.

Vercel Cron hanya harian (Hobby); penjadwal 4 jam utama ada di GitHub Actions.
Tanpa Upstash, function Vercel sengaja gagal keras agar tidak menyimpan state
sementara yang hilang.

---

## Batasan penting

- Order book historis tidak tersedia; spread/slippage masa lalu **tidak diukur**.
  Yang dipakai adalah snapshot 8 Nov 2026.
- OOS 30% terakhir **negatif**; parameter tidak dipilih ulang setelah melihat OOS.
- Survivorship bias: pair delisted tidak ada di daftar kandidat.
- Backtest memakai open candle berikutnya; bot memakai bid/ask saat tick.
- Freeze terlambat 4,8 hari; forward test baru berjalan dan belum 10 hari.
- Belum ada deployment Vercel/GitHub karena menunggu akun mahasiswa.

---

## Dokumen

| Dokumen | Isi |
|---|---|
| [`docs/LAPORAN_AKHIR.md`](docs/LAPORAN_AKHIR.md) | Laporan A–G, checklist, langkah manual |
| [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) | Data, aturan, biaya, IS/OOS, keterbatasan |
| [`docs/FREEZE.md`](docs/FREEZE.md) | Bukti freeze dan keterlambatannya |
| [`docs/FORWARD_TEST.md`](docs/FORWARD_TEST.md) | Cara jalan, definisi uptime, aturan |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Panduan GitHub/Vercel/Upstash untuk pemula |
| [`docs/PERNYATAAN_AI.md`](docs/PERNYATAAN_AI.md) | Penggunaan AI (wajib diperiksa) |
| [`docs/REFLEKSI.md`](docs/REFLEKSI.md) | Refleksi hasil dan kelemahan |
| [`data/README.md`](data/README.md) | Arti setiap file data dan cara membuat ulang |
