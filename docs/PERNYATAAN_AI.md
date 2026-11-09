# Pernyataan Penggunaan AI

> **Catatan:** dokumen ini adalah pernyataan yang harus dibaca, diperiksa, dan
> disetujui mahasiswa sebelum dikumpulkan. Jika ada bagian yang tidak sesuai
> dengan kenyataan, ubah. Jangan menandatangani pernyataan yang tidak Anda
> pahami.

**Nama:** Anindya Rahma Luthfia
**NIM:** 25110200036
**Mata kuliah:** Algoritma Trading
**Proyek:** Bot dry-run Indodax + backtest 4 tahun
**Tanggal:** 8 November 2026

## 1. Alat AI yang dipakai

- **OpenCode** — agen coding AI yang berjalan di laptop, model **Big Pickle**
  (sesi 8 November 2026). Dipakai untuk menulis, menjalankan, dan men-debug kode,
  serta menyusun draf dokumentasi.
- Bila saya juga memakai alat lain (misalnya ChatGPT, Claude, Gemini) pada
  bagian tertentu, alat tersebut saya sebutkan di sini:
  `..............................................................`

## 2. Bagian yang dibantu AI

Hampir seluruh kode dan draf dokumen pada proyek ini disusun dengan bantuan agen
AI, yaitu:

- kerangka backtest portofolio multi-pair dan model biaya (fee, spread,
  slippage);
- modul strategi, indikator, metrics, storage, exchange client, dan bot tick;
- API Vercel, dashboard HTML/CSS/JS, skrip hitung ulang, analisis gap, dan
  pembuat laporan;
- pengunduhan data publik Indodax dan pemilihan universe;
- debugging (idempotensi, holding bar, redraw canvas, lock storage);
- draf dokumentasi, README, dan laporan akhir.

## 3. Bagian yang saya putuskan sendiri

- Batasan tugas: mengikuti PDF UAS, memakai API publik tanpa API key, long-only,
  minimal 3 tahun, biaya diukur, dan **tidak boleh memalsukan** data, tanggal
  freeze, log, atau hasil.
- Memilih mengadaptasi strategi UTS (Donchian + EMA + ATR trailing stop) ke
  pair kripto IDR, bukan menyalin mentah aturan saham.
- Menolak backdate commit dan menolak mengisi log forward test yang belum
  terjadi.
- Memeriksa dan menyetujui parameter serta universe yang diusulkan agen
  (lookback 40, EMA 20/100, ATR 3,0; 6 pair IDR likuid).
- Menentukan bahwa hasil OOS yang negatif tetap dilaporkan, bukan disembunyikan.

## 4. Referensi konsep

Donchian breakout, EMA trend following, ATR trailing stop, walk-the-book,
idempotensi, out-of-sample testing, dan analisis biaya transaksi.

## 5. Pernyataan

Saya menyatakan bahwa:

1. Pekerjaan ini adalah karya saya sendiri dengan bantuan alat yang disebutkan
   di atas, bukan salinan karya orang lain.
2. Saya dapat menjelaskan setiap aturan strategi dan setiap angka yang
   dilaporkan.
3. Saya tidak memalsukan data, hasil backtest, log forward test, tanggal
   pembekuan, atau status deployment.
4. Keterbatasan dan hasil yang kurang baik dilaporkan apa adanya.

...................., .................... 2026

Tanda tangan: ..........................................

Nama: Anindya Rahma Luthfia
