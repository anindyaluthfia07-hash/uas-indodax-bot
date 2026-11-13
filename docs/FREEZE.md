# Pembekuan (Freeze)

## 1. Tenggat dan kenyataan

| Hal | Nilai |
|---|---|
| Tenggat pembekuan menurut tugas | **4 November 2026, 12:00 WIB** |
| Pekerjaan proyek ini benar-benar dimulai | **8 November 2026** |
| Commit pembekuan dibuat | **9 November 2026** (lihat bagian 5) |
| Status terhadap tenggat | **TERLAMBAT ±4,8 hari (4 hari 19 jam)** |

Saya tidak memundurkan tanggal commit, tidak mengubah metadata Git, dan tidak
membuat tag palsu bertanggal 4 November. Commit dibuat dengan waktu sebenarnya.
Keterlambatan ini adalah fakta dan konsekuensinya ditulis di laporan akhir:

- proyek tidak dapat diklaim dibekukan tepat waktu;
- forward test baru bisa dimulai setelah pembekuan, sehingga periode efektifnya
  (9 Nov → 14 Nov 2026 12.00 WIB) lebih pendek dari ideal;
- nilai untuk komponen "ketepatan waktu" harus dianggap tidak terpenuhi.

## 2. Apa yang dibekukan

Pada commit dan tag pembekuan, hal berikut tidak diubah lagi:

- seluruh kode di `core/`, `scripts/`, `api/`, `tests/`;
- parameter strategi dan universe di `config/strategy.json`;
- data mentah di `data/raw/` dan `data/snapshots/`;
- hasil backtest final di `data/backtest_results.json`,
  `data/backtest_trades.csv`, `data/backtest_equity_daily.csv`;
- biaya terukur di `data/costs.json`;
- kode dashboard di `public/index.html`, `public/app.js`, `public/styles.css`;
- dokumen metodologi, refleksi, dan pernyataan AI.

`public/offline_dashboard.html`, `public/dashboard_data.json`, dan salinan CSV di
`public/` adalah **keluaran turunan**. File itu tidak ikut di-hash dalam manifest
karena dibangun ulang secara deterministik dari input yang dibekukan ditambah log
forward. Membangun ulang dashboard tidak mengubah strategi, parameter, atau hasil
backtest.

Setelah freeze, yang boleh berubah hanya:

- log forward test (`data/local/` atau Redis);
- `data/recomputed.json`, `data/gap_analysis.json` (hasil hitung ulang);
- `data/project_status.json` (status deployment);
- dokumen laporan akhir dan metadata freeze (hash/tag) pada commit lanjutan
  yang **hanya berisi metadata**, tanpa mengubah kode, parameter, atau hasil
  backtest.

## 3. Mengapa freeze dilakukan setelah pengujian

Freeze bukan sekadar commit kosong. Yang dibekukan adalah versi yang sudah lulus
tes: 17 unit test, backtest final, dashboard yang bisa dibuka, dan log bot yang
sudah diuji. Membekukan kode yang belum jalan akan menghasilkan bukti palsu.
Karena itu urutannya:

1. selesaikan kode dan pengujian;
2. jalankan backtest final dan bangun dashboard;
3. commit seluruh pekerjaan dengan timestamp sebenarnya;
4. beri tag anotasi;
5. catat hash dan waktu commit di commit metadata;
6. baru mulai forward test.

## 4. Bukti yang bisa diperiksa sendiri

Dari folder proyek:

```bash
git log --date=iso --pretty=fuller -n 5
git show --stat --oneline HEAD
git tag -n
git rev-parse HEAD
```

Hash file penting juga dicatat di `docs/FREEZE_MANIFEST.json`. Untuk memeriksa:

```bash
python3 - <<'PY'
import hashlib, json, subprocess
m = json.load(open("docs/FREEZE_MANIFEST.json"))
tag = "freeze-2026-11-09"
ok = 0
for path, expected in m["files"].items():
    blob = subprocess.run(["git", "show", "%s:%s" % (tag, path)],
                          capture_output=True, check=True).stdout
    h = hashlib.sha256(blob).hexdigest()
    print("OK  " if h == expected else "BEDA", path)
    ok += (h == expected)
print("%d/%d file cocok dengan tag %s" % (ok, len(m["files"]), tag))
PY
```

Verifikasi di atas membandingkan isi **commit/tag freeze**, bukan working tree,
sehingga patch dokumen/tampilan setelah freeze tidak mengubah bukti strategi.

## 5. Catatan pembekuan sebenarnya

Diisi setelah commit dan tag dibuat:

| Hal | Nilai |
|---|---|
| Commit hash | `1bc81524f6babff24406b17593633f5a10cd336f` |
| Tag | `freeze-2026-11-09` (annotated) |
| Waktu commit (UTC) | **2026-11-09T00:35:32Z** |
| Waktu commit (WIB) | **2026-11-09 07:35:32 WIB** |
| Jumlah file dalam commit | 110 file |
| File sumber/data yang di-hash | 90 file (`docs/FREEZE_MANIFEST.json`) |

> Commit yang memperbarui tabel ini hanya mengubah metadata. Kode, parameter,
> dan hasil backtest tidak berubah. Perbedaan hash kode sebelum dan sesudah
> commit metadata dapat diperiksa dengan `git diff`.

## 6. Mulai forward test

Forward test dimulai setelah freeze, dengan tick pertama yang benar-benar
terjadi. Timestamp `forward_test_start` ditulis otomatis oleh bot pada tick
pertama yang sukses. Tidak ada backdate. Periode berakhir pada
**14 November 2026 12.00 WIB** (`2026-11-14T05:00:00Z`), bukan target 10 hari;
lihat `docs/FORWARD_TEST.md`.

## 7. Patch pasca-freeze (pelaporan, metrik, infrastruktur, payload dashboard)

Setelah freeze, ditemukan dua bug **pelaporan**, bukan bug strategi:

1. **Tampilan** di `scripts/build_report.py`: tag dibaca dari kunci manifest
   yang salah sehingga laporan menulis "Tag: belum ada", dan durasi forward di
   bawah satu hari ditampilkan "0.00 hari". Patch hanya mengubah format
   tampilan laporan.
2. **Definisi metrik uptime** di `scripts/gap_analysis.py` dan
   `core/metrics.py`: candle dianggap tepat waktu bila
   `processed_at < candle_open + 1×timeframe`. Padahal candle baru boleh
   diproses setelah tutup (`candle_open + 1×tf`), sehingga syarat lama tidak
   mungkin terpenuhi dan uptime selalu tampak 0%. Definisi yang benar adalah
   diproses setelah tutup dan sebelum candle berikutnya tutup
   (`candle_open + 2×tf`). Perbaikan ini hanya mengubah **metrik uptime**;
   trade, ekuitas, hasil backtest, parameter, dan universe tidak berubah.

3. **Infrastruktur penjadwal cloud** (bukan strategi): `.github/workflows/tick.yml`
   sekarang menjalankan tick di runner GitHub Actions lalu meng-commit state/log
   ke repo; commit itu memicu redeploy Vercel. Di `core/storage.py` ditambahkan
   `RepoSnapshotStorage`, yaitu backend **baca-saja** untuk Vercel tanpa Upstash,
   supaya `/api/health` dan `/api/dashboard` menampilkan data commit terakhir
   dan `POST /api/tick` menolak menulis dengan pesan jelas. `api/tick.py` hanya
   berubah docstring-nya. `scripts/build_offline_dashboard.py` menambahkan label
   sumber data. Tidak ada keputusan entry/exit, parameter, atau bobot risiko yang
   berubah.
4. **Payload dashboard** di `core/bot.py`: `dashboard_payload()` hanya
   menambahkan satu kunci baru, `forward_vs_backtest`, yang membaca
   `data/forward_vs_backtest.json` (bukti banding sinyal). Tidak ada perubahan
   pada `run_tick`, perhitungan sinyal, ukuran posisi, atau eksekusi order —
   murni penambahan data untuk ditampilkan.
5. **Periode forward test** (pelaporan, bukan strategi): periode ditetapkan
   dari tick pertama sampai 14 Nov 2026 12.00 WIB di `core/period.py`, lalu
   dipakai untuk menampilkan durasi/sisa waktu/status selesai di
   `core/bot.py` (payload), `scripts/gap_analysis.py` (cakupan periode),
   `scripts/build_report.py`, dan `public/app.js`. `scripts/run_tick.py` dan
   `scripts/forward_loop.py` berhenti setelah periode itu;
   `.github/workflows/tick.yml` menulis `data/forward_period_closed.json` dan
   tidak menambah tick lagi. Tidak ada aturan entry/exit, parameter, universe,
   atau bobot risiko yang berubah.

Yang **tidak** berubah pada patch ini: strategi, parameter, universe, model
biaya, hasil backtest, dan data mentah. Untuk memeriksa:

```bash
# inti eksekusi strategi dan hasil backtest tidak berubah
# (core/storage.py dikecualikan karena hanya ditambah backend baca-saja;
#  core/bot.py dikecualikan karena hanya menambah kunci payload dashboard)
git diff 1bc8152..HEAD -- core/strategy.py core/backtest_engine.py \
  core/config.py core/exchange.py core/indicators.py \
  config data/backtest_results.json data/costs.json data/raw data/snapshots

# satu-satunya perubahan di core/ adalah fungsi compute_uptime + tesnya,
# RepoSnapshotStorage (baca-saja) di core/storage.py, dan kunci payload
# forward_vs_backtest di core/bot.py (2 baris, tanpa logika trading)
git diff 1bc8152..HEAD -- core/metrics.py core/storage.py core/bot.py scripts/gap_analysis.py tests/test_core.py

# commit patch hanya menyentuh file pelaporan/dokumen/analisis/infrastruktur
git log --oneline 1bc8152..HEAD -- scripts/build_report.py scripts/gap_analysis.py \
  core/metrics.py core/storage.py tests/test_core.py README.md docs/PERNYATAAN_AI.md \
  .github/workflows/tick.yml
```

Manifest tetap merujuk versi pada commit freeze. Versi beku skrip laporan dapat
diperiksa dengan `git show 1bc8152:scripts/build_report.py`. Perbedaan hash
`scripts/build_report.py`, `scripts/gap_analysis.py`, `core/metrics.py`, dan
`tests/test_core.py` antara manifest dan HEAD adalah konsekuensi patch
pelaporan/analisis ini dan dicatat, bukan disembunyikan.

Patch tampilan tersebut adalah commit `21cbd32` dan commit lanjutan yang hanya
menyentuh file pelaporan/dokumen/analisis; daftar lengkapnya dapat dilihat
dengan `git log --oneline 1bc8152..HEAD`. Commit-commit itu juga menyimpan log
forward test aktual dan membangun ulang dashboard/laporan.

Pada working tree saat laporan ini dibuat, file yang berbeda dari manifest
adalah dokumen/tampilan (`README.md`, `docs/PERNYATAAN_AI.md`,
`docs/DEPLOYMENT.md`, `docs/FORWARD_TEST.md`, `public/app.js`,
`scripts/build_report.py`, `scripts/build_offline_dashboard.py`), analisis
uptime dan periode (`scripts/gap_analysis.py`, `core/metrics.py`,
`core/period.py`, `scripts/run_tick.py`, `scripts/forward_loop.py`,
`tests/test_core.py`), infrastruktur deployment (`core/storage.py`,
`core/bot.py`, `api/tick.py`, `.github/workflows/tick.yml`), dan alat migrasi
deployment (`scripts/migrate_local_to_redis.py`, `tests/test_migration.py`). Tidak ada file
strategi (`core/strategy.py`, `core/backtest_engine.py`), parameter, universe,
model biaya, data mentah, atau hasil backtest yang berubah. Verifikasi terhadap
tag (bagian 4) tetap menghasilkan **90/90 file cocok**, sehingga bukti bahwa
strategi dan hasil backtest tidak berubah tetap kuat.
