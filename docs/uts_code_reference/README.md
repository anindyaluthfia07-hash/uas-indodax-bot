# Dashboard Algoritma Trading
Anindya Rahma Luthfia

Strategi: **Breakout Donchian + EMA Trend Following + Stop-Loss -2% (aktif mulai bar ke-3) + ATR Trailing Stop**, saham Kompas100 (100 saham), data harian Yahoo Finance (unduh 2026-10-16), backtest 2016-08-31 s/d 2026-09-01, tanggal pembekuan 2026-09-01, modal Rp100.000.000 (compounding).

## Isi paket
| File | Fungsi |
|---|---|
| `UTS_25110200036_AnindyaRahmaLuthfia.html` | Dashboard mandiri (offline, data dan JSON tertanam) |
| `backtest.py` | Mesin backtest, pemilihan parameter in-sample, walk-forward, sensitivitas, uji biaya/keterlambatan, Monte Carlo, forward test |
| `prepare_data.py` | Mengubah `kompas100_harian.csv` menjadi `data/prices.csv` |
| `build_dashboard.py`, `dashboard_template.html` | Merakit `results.json` menjadi HTML |
| `run_all.py` | Menjalankan semua langkah dengan satu perintah |
| `download_data.py`, `Data awal/unduh_data.py` | Skrip unduh data dari Yahoo Finance (opsional) |
| `Data awal/kompas100_harian.csv` | Data harga yang dipakai (kolom `Date,Open,High,Low,Close,Volume,symbol`; harga auto_adjust) |
| `results.json` | Hasil backtest yang tertanam di HTML |

## Menjalankan ulang
```bash
pip install numpy pandas            # yfinance hanya untuk unduh data
python3 run_all.py --csv "Data awal/kompas100_harian.csv"
```
Waktu jalan sekitar 20–30 detik; hasil deterministik (tanpa angka acak kecuali seed Monte Carlo = 42).
Untuk menguji data lain, siapkan CSV dengan kolom yang sama (simbol saham berakhiran `.JK`, indeks `^JKSE`) dan jalankan perintah yang sama dengan `--csv <file>`.
Langkah manual: `python3 prepare_data.py <csv> data` → `python3 backtest.py --data data --out results.json --freeze 2026-09-01` → `python3 build_dashboard.py`.

## Aturan strategi (persis seperti di kode)
**Masuk** (dicek di penutupan hari t, dibeli di harga buka t+1 + 1 fraksi spread): (1) Close > tertinggi 30 hari sebelumnya; (2) Close > EMA150; (3) EMA25 > EMA150. Tidak ada filter volume; bila sinyal lebih banyak daripada slot, saham dengan volume/rata-rata volume 20 hari tertinggi didahulukan.
**Keluar** (dicek di penutupan, dijual di harga buka t+1 − 1 fraksi spread): (a) sejak bar ke-3 setelah beli, bila return ≤ −2%; (b) trailing stop ATR: stop = max(stop lama, Close − 4 × ATR14), dipicu bila Close < stop; (c) EMA25 memotong ke bawah EMA150.
**Ukuran posisi**: maksimal 5 posisi, tiap posisi 20% ekuitas saat sinyal, maksimal 5% dari rata-rata nilai transaksi harian 20 hari, kelipatan 100 lembar, tanpa short dan margin.
**Biaya**: fee beli 0,15%, jual 0,25%, spread 1 fraksi per transaksi, fraksi harga BEI (Rp1/2/5/10/25), bar datar dengan gerak ≥ 6,5% dianggap terkunci ARA/ARB.
Parameter (30 / 25 / 150 / 4,0) dipilih dari in-sample 70% awal dengan plateau Calmar (grid 4×4×4×4 = 256 kombinasi).

## Hasil (setelah biaya)
CAGR 45,1% (IHSG 2,1%), MDD −42,3% (IHSG −41,5%), win ratio 20,2%, payoff 9,29×, profit factor 1,86, 496 trade. In-sample 33,7% · out-of-sample 93,0% · walk-forward gabungan 26,8% · tunda 1 bar 44,5% · biaya 2× 12,8% · forward test 6,4 minggu −3,2% (IHSG −21,4%).

## Keterbatasan penting
- Laba sangat terkonsentrasi: BUVA dan WIFI (2025) = 111% laba bersih; tanpa 5 trade terbaik strategi rugi.
- Rentan biaya, terutama spread: biaya 2× → 12,8%, 3× → negatif. Uji ulang dosen pada data lain: CAGR 26,6% dan 6,7% pada biaya 2×.
- Survivorship bias (anggota Kompas100 saat ini), harga auto_adjust (bukan harga transaksi asli), tanggal pembekuan ditetapkan setelah data diunduh, forward test hanya 34 hari bursa / 5 trade.
Rincian lengkap ada di bagian "Keterbatasan & Risiko" pada dashboard.
