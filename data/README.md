# Data

Folder ini berisi data mentah, data turunan, dan log. **Jangan mengedit angka
dengan tangan.** Semua file hasil dihitung ulang oleh skrip.

## Data mentah (disimpan di repo)

| File | Isi | Dibuat oleh |
|---|---|---|
| `raw/{pair}_240.csv` | candle 4 jam Indodax, 35 kandidat, 2022-08-01 s/d 2026-11-08 | `scripts/download_history.py` |
| `raw/download_meta_240.json` | waktu unduh, jumlah request, hash SHA-256 tiap file | idem |
| `snapshots/orderbook_20261108.jsonl` | snapshot order book mentah (20 level, bid/ask, spread) | `scripts/collect_snapshots.py` |
| `pairs_meta_snapshot.json` | fee, minimum order, tick size dari API | `scripts/select_universe.py` |
| `universe.json` | peringkat likuiditas 60 hari pertama dan universe terpilih | idem |

Candle adalah data publik. Tidak ada data masa depan yang dimasukkan ke
perhitungan; backtest memakai warm-up sebelum periode dan hanya candle tertutup.

## Data hasil (boleh dihapus lalu dibuat ulang)

| File | Isi |
|---|---|
| `backtest_results.json` | hasil lengkap backtest final (metrik, trade, kurva ekuitas, stress test, benchmark) |
| `backtest_search.json` | hasil pencarian parameter in-sample |
| `backtest_trades.csv` | daftar trade backtest untuk audit |
| `backtest_equity_daily.csv` | ekuitas harian backtest |
| `costs.json` | median spread dan slippage per pair dari snapshot |
| `recomputed.json` | hasil hitung ulang metrik forward test dari log mentah |
| `gap_analysis.json` | candle/tick yang hilang selama forward test |
| `project_status.json` | status GitHub/Vercel yang diisi manual setelah deploy |

## Log runtime (lokal)

`local/` berisi JSONL yang ditulis bot saat dijalankan di laptop:

| File | Isi |
|---|---|
| `state.json` | kas, posisi, candle terakhir yang diproses, kill switch, timestamp mulai forward test |
| `ticks.jsonl` | ringkasan setiap tick |
| `decisions.jsonl` | keputusan per pair (termasuk alasan skip dan komponen sinyal) |
| `orders.jsonl` | order simulasi: harga bid/ask, fill VWAP, fee, spread, slippage |
| `trades.jsonl` | trade tertutup dengan PnL bersih |
| `equity.jsonl` | ekuitas setiap tick |
| `daily_equity.jsonl` | ekuitas pertama setiap hari WIB |
| `snapshots.jsonl` | snapshot order book yang diambil saat tick |
| `errors.jsonl` | error API atau eksekusi |
| `kill_log.jsonl` | riwayat kill switch |
| `forward_loop.log` | log loop forward test (tidak masuk repo) |

File `state.json` dan JSONL adalah bukti. Jangan menghapus baris yang tidak
menguntungkan. Bila perlu memulai ulang, arsipkan foldernya, jangan menimpa.

## Cara membuat ulang

```bash
# 1. data candle (butuh internet, sekitar 1-2 menit)
python3 scripts/download_history.py --tf 240 --start 2022-08-01 --end 2026-11-08

# 2. universe (menulis ulang config/strategy.json)
python3 scripts/select_universe.py

# 3. snapshot order book (biarkan beberapa menit/jam)
python3 scripts/collect_snapshots.py --interval 60 --duration 3600
python3 scripts/calibrate_costs.py

# 4. backtest
python3 scripts/backtest.py --search
python3 scripts/backtest.py --final

# 5. dashboard offline
python3 scripts/build_offline_dashboard.py
```

Hasil backtest bersifat deterministik untuk data dan biaya yang sama. Perbedaan
kecil bisa muncul bila snapshot order book ditambah, karena `costs.json`
berubah.
