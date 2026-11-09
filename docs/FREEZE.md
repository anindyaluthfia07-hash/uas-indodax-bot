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
- forward test baru bisa dimulai setelah pembekuan, sehingga durasinya jauh
  lebih pendek dari 10 hari saat laporan disusun;
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
pertama yang sukses. Tidak ada backdate. Lihat `docs/FORWARD_TEST.md`.

## 7. Patch pasca-freeze (hanya tampilan laporan)

Setelah freeze, ditemukan bug **tampilan** di `scripts/build_report.py`: tag
dibaca dari kunci manifest yang salah sehingga laporan menulis "Tag: belum ada",
dan durasi forward di bawah satu hari ditampilkan "0.00 hari". Patch hanya
mengubah format tampilan laporan.

Yang **tidak** berubah pada patch ini: strategi, parameter, universe, model
biaya, hasil backtest, dan data mentah. Untuk memeriksa:

```bash
# tidak ada perubahan pada inti strategi dan hasil backtest
git diff 1bc8152..HEAD -- core config data/backtest_results.json data/costs.json

# commit patch hanya menyentuh file pelaporan/dokumen
git log --oneline 1bc8152..HEAD -- scripts/build_report.py README.md docs/PERNYATAAN_AI.md
```

Manifest tetap merujuk versi pada commit freeze. Versi beku skrip laporan dapat
diperiksa dengan `git show 1bc8152:scripts/build_report.py`. Perbedaan hash
`scripts/build_report.py` antara manifest dan HEAD adalah konsekuensi patch
tampilan ini dan dicatat, bukan disembunyikan.

Patch tampilan tersebut adalah commit `21cbd32` dan commit lanjutan yang hanya
menyentuh file pelaporan/dokumen; daftar lengkapnya dapat dilihat dengan
`git log --oneline 1bc8152..HEAD`. Commit-commit itu juga menyimpan log forward
test aktual dan membangun ulang dashboard/laporan.

Pada working tree saat laporan ini dibuat, ada **3 file** yang berbeda dari
manifest: `README.md`, `docs/PERNYATAAN_AI.md`, dan `scripts/build_report.py`.
Ketiganya adalah dokumen/tampilan. Verifikasi terhadap tag (bagian 4) tetap
menghasilkan **90/90 file cocok**, sehingga bukti bahwa strategi, parameter,
universe, biaya, dan hasil backtest tidak berubah tetap kuat.
