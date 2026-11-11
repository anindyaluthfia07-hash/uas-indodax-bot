# Panduan Deploy (GitHub + Vercel + Upstash)

Panduan ini ditulis untuk orang yang **belum pernah** memakai Git, GitHub, atau
Vercel. Ikuti berurutan. Bagian yang harus dikerjakan manual di browser diberi
tanda **[MANUAL]**. Jangan pernah menaruh password, token, atau isi `.env` di
dalam repo.

> Ringkas: GitHub = tempat menyimpan kode. Vercel = tempat menjalankan kode dan
> dashboard. Upstash Redis = tempat menyimpan state/log karena Vercel tidak punya
> hard disk permanen.

---

## 0. Yang perlu disiapkan

- Akun GitHub (gratis): https://github.com/signup
- Akun Vercel (gratis, bisa daftar dengan akun GitHub): https://vercel.com/signup
- Git sudah terpasang di laptop (proyek ini dibuat dengan Git bawaan macOS).
- Folder proyek: `/Users/mac/Documents/Default Project/uas-indodax-bot`

Cek Git:

```bash
git --version
```

---

## 1. Buat repository GitHub **[MANUAL]**

1. Buka https://github.com/new
2. Isi **Repository name**, misalnya `uas-indodax-bot`.
3. Pilih **Private** (disarankan) atau Public.
4. **Jangan** centang "Add a README", "Add .gitignore", atau "Choose a license".
5. Klik **Create repository**.
6. Di halaman berikutnya, salin alamat repo. Bentuknya:
   `https://github.com/USERNAME/uas-indodax-bot.git`

---

## 2. Hubungkan folder lokal ke GitHub

Di terminal, dari folder proyek:

```bash
cd "/Users/mac/Documents/Default Project/uas-indodax-bot"

# ganti USERNAME dengan username GitHub Anda
git remote add origin https://github.com/USERNAME/uas-indodax-bot.git

# cek
git remote -v
```

Saat pertama kali `push`, Git akan meminta username dan password. GitHub
**tidak menerima password akun** untuk operasi Git. Gunakan **Personal Access
Token**:

1. Buka https://github.com/settings/tokens **[MANUAL]**
2. **Generate new token (classic)**.
3. Beri nama, pilih masa berlaku, centang scope **repo**.
4. Klik **Generate token**, lalu **salin token** (hanya ditampilkan sekali).
5. Saat Git meminta password, tempel token tersebut (bukan password akun).

Lalu:

```bash
git push -u origin main
```

Kalau berhasil, buka halaman repo di GitHub dan pastikan file muncul.

> Alternatif tanpa terminal: di halaman repo GitHub, klik **Add file → Upload
> files**, lalu seret seluruh isi folder proyek. Cara ini tidak menyimpan riwayat
> commit, jadi kurang baik untuk bukti freeze. Utamakan `git push`.

---

## 3. Buat database Upstash Redis **[MANUAL]**

Vercel menghapus file sementara setiap function selesai. Tanpa database, state
bot dan log akan hilang. Kode sengaja **menolak berjalan** di Vercel bila
variabel Redis tidak ada.

1. Buka dashboard Vercel → tab **Storage** (atau **Marketplace**).
2. Pilih **Upstash Redis** → **Create Database**.
3. Pilih region terdekat (misalnya Singapore), paket gratis.
4. Setelah dibuat, klik **Connect Project** dan pilih proyek Vercel Anda.
5. Buka tab **Environment Variables** proyek di Vercel. Pastikan ada dua nama
   berikut (nilainya diisi otomatis oleh integrasi):
   - `UPSTASH_REDIS_REST_URL`
   - `UPSTASH_REDIS_REST_TOKEN`

Bila integrasi memberi nama lain (misalnya `KV_REST_API_URL` dan
`KV_REST_API_TOKEN`), buka dashboard Upstash → **REST API** → salin URL dan
token, lalu tambahkan sendiri di Vercel dengan nama `UPSTASH_REDIS_REST_URL`
dan `UPSTASH_REDIS_REST_TOKEN`. Kode hanya membaca dua nama itu.

---

## 3b. Pindahkan forward test lokal ke Upstash (disarankan)

Kalau Anda sudah menjalankan forward test di laptop dan ingin melanjutkannya di
cloud **tanpa memulai dari nol**, salin state/log lokal ke Upstash. Skrip ini
mempertahankan `forward_test_start` asli dan tidak mengarang data.

Urutan yang aman:

1. Selesaikan satu tick lokal terakhir, lalu hentikan loop lokal:
   ```bash
   kill "$(cat data/local/forward_loop.pid)"
   kill "$(cat data/local/caffeinate.pid)" 2>/dev/null || true
   ```
2. Salin URL dan token dari dashboard Upstash ke terminal (jangan commit):
   ```bash
   export UPSTASH_REDIS_REST_URL="https://....upstash.io"
   export UPSTASH_REDIS_REST_TOKEN="...."
   ```
3. Cek dulu tanpa menulis:
   ```bash
   python3 scripts/migrate_local_to_redis.py --dry-run
   ```
4. Tulis ke Redis:
   ```bash
   python3 scripts/migrate_local_to_redis.py --write
   ```
5. Baru setelah itu panggil `/api/tick` atau aktifkan GitHub Actions.

Skrip menolak menimpa Redis yang sudah berisi kunci UAS. Bila terpaksa (misalnya
Vercel Cron sempat tick lebih dulu), gunakan `--force`; skrip hanya menghapus
kunci UAS lalu menyalin ulang dari log lokal, tidak menyentuh data lain.

> Tanpa migrasi, tick cloud akan menulis `forward_test_start` baru. Itu tidak
> salah, tetapi durasi forward test cloud menjadi lebih pendek dan berbeda dari
> laporan lokal.

---

## 4. Import proyek ke Vercel **[MANUAL]**

1. Buka https://vercel.com/new
2. Pilih **Import Git Repository** → izinkan Vercel mengakses GitHub bila diminta.
3. Pilih repo `uas-indodax-bot`.
4. **Framework Preset:** Other (jangan pilih Next.js).
5. **Root Directory:** biarkan kosong (root repo).
6. **Build Command:** biarkan kosong.
7. **Output Directory:** biarkan kosong (Vercel otomatis memakai `public/`).
8. Buka **Environment Variables**, tambahkan:

| Nama | Nilai | Wajib |
|---|---|---|
| `CRON_SECRET` | string acak panjang, buat sendiri | ya |
| `UPSTASH_REDIS_REST_URL` | dari Upstash | ya |
| `UPSTASH_REDIS_REST_TOKEN` | dari Upstash | ya |
| `KILL_SWITCH` | `0` | tidak |

Membuat `CRON_SECRET` acak (jalankan di terminal):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(40))"
```

Simpan nilai itu di tempat aman. Nilai yang sama dipakai di GitHub Actions.

9. Klik **Deploy** dan tunggu selesai.
10. Catat URL produksi, misalnya `https://uas-indodax-bot.vercel.app`.

---

## 5. Uji endpoint **[MANUAL + terminal]**

> **Penting:** kalau ingin melanjutkan forward test lokal, lakukan migrasi di
> bagian **3b** sebelum memanggil `/api/tick`. Tick pertama di cloud akan
> menulis state baru bila Redis masih kosong.

Ganti `URL` dan `SECRET` dengan milik Anda.

```bash
URL="https://uas-indodax-bot.vercel.app"
SECRET="isi-CRON_SECRET-anda"

# health: boleh tanpa secret
curl -s "$URL/api/health" | python3 -m json.tool

# dashboard: publik, dipakai halaman HTML
curl -s "$URL/api/dashboard" | python3 -m json.tool | head -30

# tick: butuh secret
curl -s -X POST "$URL/api/tick" \
  -H "Authorization: Bearer $SECRET" | python3 -m json.tool

# export log mentah: butuh secret
curl -s "$URL/api/export" \
  -H "Authorization: Bearer $SECRET" | python3 -m json.tool | head -30
```

Yang diharapkan:

- `/api/health` → `"ok": true` setelah tick pertama.
- `/api/tick` → `"ok": true`, ada ringkasan `decisions` dan `equity`.
- Bila muncul `UPSTASH_REDIS_REST_URL dan UPSTASH_REDIS_REST_TOKEN belum diset`,
  berarti environment variable belum masuk atau belum redeploy.

Dashboard publik: `https://URL/` (halaman `public/index.html`). Halaman ini
mengambil data dari `/api/dashboard`. Versi offline ada di
`public/offline_dashboard.html` dan bisa dibuka langsung dari file.

---

## 6. Aktifkan penjadwal 4 jam **[MANUAL]**

Vercel Hobby hanya mengizinkan cron **harian**; karena itu penjadwal utama ada
di GitHub Actions.

1. Di repo GitHub → **Settings → Secrets and variables → Actions**.
2. Tab **Secrets** → **New repository secret**:
   - `CRON_SECRET` = sama dengan Vercel
   - `UPSTASH_REDIS_REST_URL` = sama dengan Vercel
   - `UPSTASH_REDIS_REST_TOKEN` = sama dengan Vercel
3. Tab **Variables** → **New repository variable**:
   - `VERCEL_URL` = `https://uas-indodax-bot.vercel.app` (tanpa garis miring di akhir)
4. Buka tab **Actions** → workflow **indodax-dry-run-tick** → **Enable workflow**
   bila diminta.
5. Klik **Run workflow** sekali untuk uji manual. Lihat log; harus ada respons
   JSON dari `/api/tick`.

Setelah itu workflow berjalan otomatis setiap 4 jam pada menit ke-7 UTC
(00:07, 04:07, 08:07, 12:07, 16:07, 20:07 UTC = 07:07, 11:07, 15:07, 19:07,
23:07, 03:07 WIB).

Vercel Cron tetap aktif sebagai cadangan harian `07:00 UTC`.

---

## 7. Perbarui status deployment di dashboard **[MANUAL]**

Dashboard membaca `data/project_status.json`. Setelah deploy berhasil, edit file
itu di repo (langsung di GitHub: klik file → ikon pensil → commit):

```json
{
  "github_repo": "https://github.com/USERNAME/uas-indodax-bot",
  "vercel_url": "https://uas-indodax-bot.vercel.app",
  "vercel_deployed": true,
  "github_actions_enabled": true,
  "updated_at": "2026-11-08T00:00:00Z",
  "note": "Diisi setelah akun GitHub/Vercel milik mahasiswa terhubung."
}
```

Ganti `updated_at` dengan waktu sebenarnya (UTC). Jangan mengisi `true` sebelum
benar-benar berhasil. Vercel akan otomatis redeploy setelah commit.

---

## 8. Perintah harian

```bash
# lihat status
curl -s "$URL/api/health" | python3 -m json.tool

# jalankan tick manual
curl -s -X POST "$URL/api/tick" -H "Authorization: Bearer $SECRET" | python3 -m json.tool

# matikan entry baru (exit tetap jalan)
curl -s -X POST "$URL/api/kill" \
  -H "Authorization: Bearer $SECRET" -H "Content-Type: application/json" \
  -d '{"on":true,"note":"maintenance"}' | python3 -m json.tool

# nyalakan lagi
curl -s -X POST "$URL/api/kill" \
  -H "Authorization: Bearer $SECRET" -H "Content-Type: application/json" \
  -d '{"on":false,"note":"selesai"}' | python3 -m json.tool
```

---

## 9. Masalah yang sering muncul

| Gejala | Penyebab | Solusi |
|---|---|---|
| `503 ... UPSTASH ... belum diset` | env var belum ada | tambahkan di Vercel, lalu **Redeploy** |
| `401 unauthorized` | secret beda | samakan `CRON_SECRET` di Vercel dan GitHub |
| Function timeout | API Indodax lambat | ulangi; kode punya retry dan rate limit |
| Cron tidak jalan | workflow belum di-enable | tab Actions → Enable workflow |
| Dashboard kosong | `/api/dashboard` error | buka URL itu langsung, baca pesan error |
| Data hilang setelah deploy | memakai storage lokal | pastikan Upstash terhubung, bukan filesystem |
| `git push` ditolak | password akun dipakai | pakai Personal Access Token |

---

## 10. Yang tidak boleh dilakukan

- Jangan commit `.env`, token, atau file berisi secret.
- Jangan mengubah `data/backtest_results.json` dengan tangan.
- Jangan menyalakan `KILL_SWITCH=1` lalu mengklaim bot berjalan normal.
- Jangan mengisi `project_status.json` dengan status palsu.
- Jangan menghapus log forward test yang merugi.

Semua langkah di atas memakai akun dan kredensial milik mahasiswa. Agen tidak
bisa dan tidak boleh membuat akun, memegang token, atau melakukan login atas
nama mahasiswa.
