# Forward Test (Dry-Run)

Forward test adalah bagian yang **tidak bisa dipercepat atau dipalsukan**. Bot
hanya boleh memakai data yang benar-benar terjadi setelah tanggal mulai, dan
setiap tick harus tercatat dengan timestamp aslinya.

## Status saat ini

Status aktual selalu ada di dashboard (`Bagian Forward Test`) dan di
`data/gap_analysis.json`. Jangan mengisi angka dari dokumen ini secara manual.

Yang dicatat secara otomatis saat tick sukses pertama:

- `forward_test_start` di state bot, dengan timestamp UTC saat itu;
- baris `forward_test_start` di `data/local/decisions.jsonl`;
- baris ekuitas pertama di `data/local/equity.jsonl`.

Tidak ada backdate. Bila forward test baru dimulai setelah tenggat freeze, itu
ditulis di laporan dan tidak diubah menjadi tanggal yang lebih awal.

## Cara menjalankan

### A. Di laptop (paling sederhana, laptop harus menyala)

Satu tick:

```bash
python3 scripts/run_tick.py
```

Loop mengikuti candle 4 jam (default 10 hari, tick 90 detik setelah candle
ditutup):

```bash
python3 scripts/forward_loop.py --days 10 --offset-seconds 90
```

Hentikan dengan `Ctrl+C`; log yang sudah ada tetap tersimpan. Untuk melihat
progres:

```bash
python3 scripts/gap_analysis.py --source local
python3 scripts/recompute.py --source local
```

### B. Di cloud (setelah deploy)

- **GitHub Actions** menjalankan tick setiap 4 jam pada menit ke-7 UTC, langsung di
  runner, lalu meng-commit state/log ke repo. Commit itu memicu redeploy Vercel,
  jadi dashboard ikut diperbarui tanpa server yang harus menyala 24 jam.
- **Vercel Cron** tidak diaktifkan pada deployment ini. `config/strategy.json`
  masih mencantumkannya sebagai rencana cadangan harian, tetapi Hobby hanya
  mengizinkan cron harian dan endpoint `/api/tick` butuh Upstash; karena itu
  jadwal sepenuhnya ditangani GitHub Actions. Bila Upstash dihubungkan, cron
  cadangan bisa diaktifkan lagi dari `vercel.json`.
- Kalau memakai jalur `/api/tick`, keduanya memakai `CRON_SECRET` yang sama.
- Idempotensi per candle mencegah order ganda bila dua penjadwal bertemu.

Aktifkan workflow dari tab **Actions** di repo GitHub (workflow `tick.yml`),
lalu isi secret/variable yang dijelaskan di `docs/DEPLOYMENT.md`.

## Definisi yang dipakai

- **Candle yang diharapkan:** candle 4 jam yang tertutup di antara
  `forward_test_start` dan waktu data terakhir.
- **Uptime per pair:** candle yang diproses tepat waktu dibagi candle yang
  diharapkan. "Tepat waktu" = keputusan tercatat sebelum candle berikutnya
  tertutup.
- **Uptime scheduler:** tick yang terjadi dalam ±45 menit dari
  `candle close + 7 menit`, dibagi jumlah tick yang diharapkan.
- **Gap:** candle atau tick yang tidak punya catatan. Gap **tidak diisi** dengan
  data buatan; hanya dihitung dan dilaporkan.

## Menghitung ulang dari log mentah

```bash
python3 scripts/recompute.py --source local
```

Skrip ini membaca `data/local/*.jsonl`, menghitung ulang ekuitas, return,
drawdown, fee, spread, slippage, dan mencocokkan trade dengan order. Hasilnya
`data/recomputed.json` beserta status PASS/FAIL. Dashboard memakai payload yang
sama, jadi angka di dashboard dapat diaudit ulang tanpa mempercayai tampilan.

Untuk data yang berjalan di Vercel:

```bash
CRON_SECRET=... python3 scripts/recompute.py --source url \
  --url https://NAMA-PROYEK.vercel.app/api/export
```

## Aturan main yang penting

1. **Jangan mengubah parameter** selama forward test. Kalau diubah, mulai
   hitungan baru dan catat alasannya.
2. **Jangan menghapus tick yang merugi.** Log yang tidak lengkap adalah data,
   bukan kesalahan yang boleh dibersihkan.
3. **Jangan mengisi gap** dengan candle atau trade rekaan.
4. **Jangan mengklaim durasi** yang belum terjadi. Durasi dihitung dari
   `forward_test_start` sampai waktu export, bukan dari rencana.
5. **Kill switch** hanya memblokir entry baru; exit tetap dievaluasi supaya
   posisi bisa ditutup.

## Ekspektasi yang jujur

Backtest OOS pada 30% terakhir bernilai negatif. Forward test yang pendek
(cenderung < 1 bulan saat laporan ini disusun) **tidak cukup** untuk menyimpulkan
strategi layak. Yang bisa disimpulkan hanya: bot berjalan, order tercatat, biaya
terukur, dan tidak ada error fatal. Itu tetap ditulis sebagai hasil apa adanya.
