# Refleksi

**Nama:** Anindya Rahma Luthfia
**NIM:** 25110200036

## 1. Apa yang saya pelajari dari hasil backtest?

Backtest 4 tahun terlihat bagus di permukaan: return +114,51%, CAGR 21,02%,
max drawdown −19,45%, profit factor 1,57. Tetapi hasil itu **tidak** berarti
strategi sudah bagus.

Yang paling penting saya pelajari adalah bedanya in-sample dan out-of-sample.
Pada 70% awal periode (in-sample) CAGR 34,94%, sedangkan pada 30% terakhir
(out-of-sample) CAGR **−6,37%** dengan drawdown −21,53%. Artinya performa bagus
di masa lalu tidak otomatis berlanjut. Saya juga melihat bahwa strategi ini kalah
dari beli-dan-tahan BTC dalam hal return (CAGR 21,02% vs 43,21%), meskipun
drawdown strategi lebih kecil (−19,45% vs −49,43%). Jadi risiko lebih rendah,
tetapi imbal hasil absolutnya lebih rendah.

Biaya juga bukan angka kecil. Total biaya Rp71,65 juta, atau sekitar 21,2% dari
laba kotor. Fee saja Rp55,67 juta. Kalau fee digandakan, CAGR turun ke 10,72%.
Kalau semua biaya digandakan, CAGR 18,30%, dan hasilnya makin rapuh. Ini pelajaran
bahwa strategi frekuensi tinggi dengan win rate 30,03% sangat bergantung pada
biaya.

## 2. Apa kelemahan utama strategi ini?

1. **OOS negatif.** Pada 30% data terakhir strategi rugi. Ini sinyal bahwa
   parameter yang bagus di 2022–2025 tidak bertahan pada rezim pasar 2025–2026.
2. **Win rate rendah (30,03%).** Sebagian besar trade rugi kecil karena stop.
   Laba bergantung pada sedikit trade besar. Distribusi seperti ini rapuh.
3. **Biaya besar.** Fee, spread, dan slippage menghabiskan sekitar seperlima
   laba kotor. Di pair dengan spread lebar, edge bisa hilang.
4. **Rentan whipsaw.** Breakout 40 bar sering gagal saat pasar sideways; stop
   ATR 3× cukup lebar sehingga kerugian per trade bisa menumpuk.
5. **Asumsi eksekusi.** Backtest memakai open candle berikutnya, sedangkan bot
   memakai bid/ask saat tick. Order book historis tidak tersedia, jadi spread
   dan slippage masa lalu tidak benar-benar diukur.
6. **Survivorship bias.** Kandidat pair diambil dari daftar yang masih ada pada
   November 2026. Pair yang delisted tidak masuk.
7. **Forward test pendek.** Saat laporan disusun, forward test baru berjalan
   beberapa jam, bukan 10 hari. Ini tidak cukup untuk menyimpulkan apa pun.

## 3. Apa yang saya ubah dari UTS dan mengapa?

- Aturan saham (lot 100 lembar, fraksi harga BEI, ARA/ARB) diganti aturan kripto:
  tick size dan quantity increment dari API Indodax, minimum order Rp25.000.
- Universe tidak lagi 100 saham, tetapi 6 pair IDR likuid yang dipilih pada
  **awal** periode, bukan pada hari ini.
- Fee saham diganti fee taker all-in Indodax (beli 0,20555%, jual 0,41555%),
  ditambah spread dan slippage yang diukur dari order book.
- Saya menambahkan idempotensi per candle, lock tick, kill switch, batas rugi
  harian, dan analisis gap. Tujuannya agar bot tidak dobel order dan kegagalan
  terlihat, bukan disembunyikan.
- Saya memisahkan in-sample dan out-of-sample, lalu **melaporkan OOS negatif**
  tanpa memilih ulang parameter setelah melihatnya.
- Saya tidak memakai tanggal freeze palsu. Pekerjaan baru dimulai 8 November
  2026, setelah tenggat 4 November 2026, dan itu dicatat di `docs/FREEZE.md`.

## 4. Apakah strategi ini layak dipakai?

**Belum.** Untuk modal nyata, saya belum akan memakainya karena:

- OOS negatif dan forward test masih sangat pendek;
- hasil bergantung pada sedikit trade besar;
- biaya dan slippage bisa lebih buruk dari asumsi;
- belum ada bukti eksekusi nyata (fill, antrean, kegagalan API).

Yang perlu dilakukan sebelum dipertimbangkan:

1. Forward test minimal 1–3 bulan dengan log lengkap dan uptime tinggi.
2. Uji pada pair dan periode yang belum pernah dilihat, termasuk pasar sideways.
3. Filter rezim (misalnya hanya entry saat volatilitas/ tren pasar mendukung).
4. Batas kontribusi per trade dan diversifikasi yang lebih baik.
5. Evaluasi biaya nyata dari trade dry-run, bukan hanya snapshot satu jam.
6. Uji kegagalan: API down, candle hilang, order book tipis, maintenance pair.

## 5. Apa yang saya pelajari tentang proses?

Kejujuran lebih sulit daripada membuat angka terlihat bagus. Mengakui OOS
negatif, freeze yang terlambat, dan forward test yang belum selesai terasa tidak
nyaman, tetapi itu satu-satunya cara agar hasil bisa dipercaya. Saya juga belajar
bahwa kode yang bisa dihitung ulang (log mentah + skrip recompute) lebih berharga
daripada dashboard yang hanya menampilkan angka cantik.
