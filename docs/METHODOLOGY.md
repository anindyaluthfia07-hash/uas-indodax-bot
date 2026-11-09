# Metodologi

Dokumen ini menjelaskan **apa yang benar-benar dihitung oleh kode**, bukan versi
yang lebih bagus dari kenyataan. Semua angka di laporan berasal dari
`data/backtest_results.json`, yang dihasilkan ulang oleh
`python3 scripts/backtest.py --final`.

## 1. Sumber data

| Hal | Nilai |
|---|---|
| Sumber candle | API publik Indodax `https://indodax.com/tradingview/history_v2` |
| Sumber order book | API publik Indodax `/api/depth/{pair}` |
| Sumber fee & minimum order | `/api/pairs`, `/api/price_increments`, halaman biaya resmi Indodax |
| Timeframe | 4 jam (`tf=240`) |
| Periode backtest | 2022-11-08 s/d 2026-11-08 (4,00 tahun) |
| Warm-up indikator | data mulai 2022-08-01, tidak dipakai untuk menghitung return |
| Modal awal | Rp100.000.000 |
| API key | tidak ada; seluruh endpoint bersifat publik |

Candle mentah disimpan di `data/raw/{pair}_240.csv`. Metadata unduhan
(termasuk hash file dan waktu akses) ada di `data/raw/download_meta_240.json`.
Data tidak diubah tangan. `scripts/download_history.py` mengunduh mundur dengan
pagination karena endpoint `history_v2` mengembalikan bar sebelum parameter `to`.

## 2. Pemilihan universe (3–10 pair)

Kandidat: 35 pair IDR di `config/candidates.json`. Kriteria dihitung pada
**60 hari pertama periode backtest**, bukan pada hari ini:

1. Pair sudah punya candle pada awal periode.
2. Coverage candle ≥ 95% pada jendela 60 hari.
3. Median nilai transaksi harian (`close × volume`, dalam IDR) tertinggi.

Hasil: `btcidr, dogeidr, ethidr, xrpidr, bnbidr, trxidr` (6 pair). Stablecoin
(`usdtidr`, `usdcidr`, `daiidr`) dikeluarkan karena harga dipatok sehingga bukan
peluang trend following. Pair yang baru listed setelah 2022 (SOL, ADA baru,
ARB, OP, SUI, TON, SHIB, PEPE, dll.) tidak masuk karena tidak punya data pada
awal periode.

**Keterbatasan survivorship:** daftar pair historis yang pernah delisted tidak
disediakan API. Kandidat diambil dari daftar pair yang masih ada pada 8 Nov 2026.
Karena itu hasil bisa sedikit lebih optimistis daripada kenyataan. Ini tidak
ditutupi.

## 3. Aturan strategi (persis seperti kode)

Strategi mengadaptasi UTS (Donchian breakout + EMA trend filter) ke pasar kripto
IDR. Satu mesin aturan dipakai bersama oleh backtest dan bot:
`core/strategy.py`.

### Masuk — dievaluasi pada penutupan candle 4 jam `t`

1. `close[t] > highest(high[t-40 .. t-1])` — breakout Donchian 40 bar.
2. `close[t] > EMA100[t]` — harga di atas tren jangka panjang.
3. `EMA20[t] > EMA100[t]` — tren naik.
4. `volume[t] > 0` dan `ADV20[t] > 0` — likuiditas dasar.

### Keluar — dievaluasi pada penutupan candle `t`

1. **Time stop:** setelah ≥ 3 bar sejak masuk dan return terhadap harga fill
   ≤ −2%.
2. **ATR trailing stop:** `close[t] < stop`, dengan
   `stop = max(stop_lama, close[t] − 3,0 × ATR14[t])`.
3. **EMA cross exit:** EMA20 memotong ke bawah EMA100.

Tidak ada short, margin, atau leverage. Posisi selalu long.

### Eksekusi dan ukuran posisi

- Backtest: sinyal di close `t`, order dieksekusi di **open `t+1`**.
- Bot dry-run: sinyal di close candle yang sudah tertutup, order disimulasikan
  segera pada **bid/ask order book aktual** (walk the book).
- Maksimal 5 posisi terbuka. Setiap posisi memakai 20% ekuitas saat sinyal.
- Batas partisipasi: 5% dari ADV20 (nilai transaksi rata-rata 20 bar).
- Minimum order Rp25.000 (ketentuan mode Pro; API hanya mensyaratkan Rp10.000,
  kode memakai aturan yang lebih ketat).
- Bila sinyal lebih banyak daripada slot, kandidat diurutkan berdasarkan
  kekuatan breakout (`close / Donchian − 1`), bukan berdasarkan return masa depan.

## 4. Model biaya

Biaya dimasukkan **per transaksi**, bukan sebagai potongan di akhir:

| Komponen | Nilai yang dipakai | Cara ukur |
|---|---|---|
| Fee beli | 0,20555% | taker all-in IDR Market PRO (service + pajak + CFX), halaman resmi per 1 Okt 2026 |
| Fee jual | 0,41555% | idem |
| Half-spread | median `(ask−bid)/2` per pair | 20 level order book, snapshot 8 Nov 2026 |
| Slippage beli | median `VWAP ask / best ask − 1` | walk the book untuk notional 20% modal (Rp20 juta) |
| Slippage jual | median `1 − VWAP bid / best bid` | idem |

Sumber angka: `data/costs.json`, dihasilkan `scripts/calibrate_costs.py` dari
`data/snapshots/orderbook_20261108.jsonl`. Snapshot diambil dengan
`scripts/collect_snapshots.py` selama sekitar satu jam pada 8 Nov 2026, 35 pair,
interval 60 detik. Jumlah snapshot yang benar-benar dipakai tercatat di field
`total_snapshots_used` dan ditampilkan di dashboard.

Catatan penting: order book historis 2022–2026 tidak tersedia. Spread dan
slippage masa lalu **tidak diketahui**; yang dipakai adalah median kondisi
order book pada 8 Nov 2026. Ini asumsi, bukan pengukuran historis. Bila spread
masa lalu lebih lebar, hasil backtest terlalu optimistis.

Fee resmi juga dicek dari `/api/pairs` (`trade_fee_percent_taker = 0,2%`), lalu
dinaikkan ke angka all-in dari halaman biaya resmi. Bukti tangkapan layar ada di
`docs/evidence/indodax_fee_table_2026-11-08.png`.

## 5. Pemilihan parameter (tanpa melihat OOS)

- 70% awal periode = in-sample (2022-11-08 s/d 2025-08-26).
- 30% akhir = out-of-sample (2025-08-27 s/d 2026-11-08), dievaluasi **sekali**
  setelah parameter dipilih.
- Grid pencarian: `lookback`, `fast_ema`, `trend_ema`, `atr_mult` (lihat
  `scripts/backtest.py --search`).
- Pemilihan memakai **plateau Calmar**: bukan nilai tertinggi tunggal, tetapi
  parameter yang tetap baik pada tetangganya. Tujuannya mengurangi overfitting.
- Parameter final: `lookback=40, fast_ema=20, trend_ema=100, atr_period=14,
  atr_mult=3.0, time_stop_bars=3, time_stop_loss_pct=-0.02`.

OOS **tidak** dipakai untuk memilih parameter. Hasil OOS negatif dan dilaporkan
apa adanya.

## 6. Uji ketahanan

1. **Fee 2×** — semua fee dikalikan dua.
2. **Biaya 2×** — fee, spread, dan slippage dikalikan dua.
3. **Delay 1 bar** — order dieksekusi satu candle lebih lambat.
4. **Sensitivitas parameter** — setiap parameter digeser ±20%; hanya untuk
   melihat kestabilan, bukan memilih ulang.
5. **Benchmark** — beli-dan-tahan BTC pada periode dan biaya yang sama.

## 7. Metrik

- Return total dan CAGR memakai 365,25 hari/tahun.
- Max drawdown dihitung dari kurva ekuitas per candle 4 jam (bukan hanya
  penutupan harian). Ini lebih konservatif karena menangkap penurunan intrahari;
  kurva harian juga disimpan untuk tabel bulanan/tahunan.
- Profit factor = total laba kotor / total rugi kotor (hanya trade tertutup).
- Win rate = trade dengan `net_pnl > 0` / semua trade tertutup.
- Biaya total = fee + spread + slippage yang tercatat pada trade.
- Sharpe tidak dipakai karena periode forward masih terlalu pendek dan tidak
  ada risk-free rate IDR yang konsisten; menghindari angka yang tidak bermakna.

## 8. Yang tidak dimodelkan

- Order book historis dan perubahan spread dari waktu ke waktu.
- Antrean order (limit order tidak langsung terisi).
- Market impact untuk ukuran order lebih besar dari Rp20 juta.
- Perubahan aturan bursa, maintenance pair, atau pair yang delisted.
- Pajak akhir tahun dan biaya penarikan.
- Likuiditas intraday di luar 20 level teratas.
- Perbedaan jam server Indodax dan jam lokal (kode memakai waktu server untuk
  memilih candle tertutup).

Semua keterbatasan ini memengaruhi interpretasi hasil dan ditulis juga di
laporan akhir.
