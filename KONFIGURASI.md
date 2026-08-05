# KONFIGURASI - Kredensial & Parameter (baca ini lebih dulu)

Dokumen ini adalah SATU-SATUNYA rujukan untuk memasukkan kredensial ke modul
trading LUX. Tidak ada rahasia yang di-hardcode di source code; semuanya dibaca
dari variabel lingkungan, yang paling mudah diisi lewat berkas `.env`.

---

## 1. Mulai dalam 3 langkah (Windows PowerShell)

```powershell
cd lux-modul-trading
pip install -r requirements.txt
copy .env.contoh .env      # lalu buka .env dan isi nilainya
python main.py
```

`python main.py` tanpa argumen akan membuka **menu interaktif**: ia memuat
`.env`, menampilkan status kesiapan kredensial (nilainya selalu disamarkan),
lalu meminta Anda memilih mode. Tidak ada berkas lain yang perlu dijalankan
manual.

```
1) Uji modul (unit test)                - aman, tanpa jaringan
2) Backtest data historis (CSV lokal)   - aman, tanpa order
3) TESTNET Binance Futures              - order sungguhan, dana mainan
4) LIVE    Binance Futures              - DANA ASLI, dua gerbang keamanan
5) Uji koneksi Telegram
6) Bangkitkan ulang data dashboard
```

Untuk memeriksa konfigurasi saja tanpa menjalankan apa pun:

```powershell
python main.py --mode konfigurasi
```

---

## 2. Isi berkas `.env`

Template lengkap ada di [`.env.contoh`](.env.contoh). Ringkasannya:

| Variabel | Wajib untuk | Keterangan |
|---|---|---|
| `LUX_TELEGRAM_BOT_TOKEN` | notifikasi | Token dari @BotFather |
| `LUX_TELEGRAM_CHAT_ID` | notifikasi | ID chat/grup tujuan |
| `LUX_TELEGRAM_AKTIF` | - | `0` untuk membisukan tanpa menghapus token |
| `LUX_BINANCE_TESTNET_API_KEY` | mode testnet | Dari testnet.binancefuture.com |
| `LUX_BINANCE_TESTNET_API_SECRET` | mode testnet | idem |
| `LUX_BINANCE_LIVE_API_KEY` | mode live | Dari akun Binance asli |
| `LUX_BINANCE_LIVE_API_SECRET` | mode live | idem |
| `LUX_LIVE_KONFIRMASI` | mode live | Gerbang 2/2, lihat bagian 4 |
| `LUX_SIMBOL` | - | default `BTCUSDT` |
| `LUX_TF_ENTRY` | - | default `15m` |
| `LUX_TF_KONTEKS` | - | kosong = single-TF; `1h` atau `1h,4h` = multi-TF |
| `LUX_HORIZON` | - | `scalping` atau `intraday` (swing selamanya signal-only) |
| `LUX_LEVERAGE_MAKS` | - | default `20` |
| `LUX_MARGIN_KONFLIK` | - | default `5` poin skor |
| `LUX_INTERVAL_POLL` | - | default `15` detik |
| `LUX_BALANCE` | - | kosong = tarik saldo asli dari akun |
| `LUX_MAKS_SIKLUS` | - | kosong = jalan terus sampai Ctrl+C |
| `LUX_DATA_DIR` | backtest | folder CSV OHLCV |

**Urutan prioritas** (tertinggi menang):
`argumen CLI` > `variabel lingkungan shell` > `berkas .env` > `default di kode`.

Artinya Anda bisa menimpa sementara tanpa mengedit berkas:

```powershell
$env:LUX_SIMBOL="ETHUSDT"; python main.py
```

---

## 3. Pemisahan Testnet vs Live (penegakan teknis, bukan sekadar konvensi)

Aturan ini ditegakkan oleh kode di `lux_modul/eksekusi/kredensial.py`, bukan
hanya oleh dokumentasi:

1. **Nama variabel berbeda total.** Tidak ada mekanisme fallback dari testnet ke
   live maupun sebaliknya. Kunci testnet secara harfiah tidak bisa terbaca oleh
   jalur kode mode live.
2. **Base URL tidak bisa dikonfigurasi.** `testnet` selalu
   `https://testnet.binancefuture.com`, `live` selalu `https://fapi.binance.com`.
   Tidak ada variabel lingkungan atau argumen yang bisa mengubahnya, sehingga
   kunci testnet mustahil "nyasar" ke endpoint live.
3. **Deteksi salah salin-tempel.** Bila key ATAU secret testnet ternyata identik
   dengan yang live, sistem MENOLAK berjalan di kedua mode dan memberi pesan
   jelas - karena itu hampir pasti kesalahan konfigurasi.

---

## 4. Dua gerbang keamanan mode LIVE

Mode live hanya berjalan bila **KEDUA** gerbang lolos bersamaan:

| Gerbang | Cara membuka | Alasan |
|---|---|---|
| 1/2 - konfirmasi eksplisit | argumen `--konfirmasi-live`, atau mengetik ulang frasa lengkap di menu interaktif | mencegah salah pilih menu / salah ketik mode |
| 2/2 - variabel lingkungan | `LUX_LIVE_KONFIRMASI=SAYA_PAHAM_INI_AKUN_LIVE_DANA_ASLI` | mencegah skrip/cron lama menyalakan live sendiri |

Satu gerbang saja **tidak cukup**. Selama `LUX_LIVE_KONFIRMASI` kosong di `.env`,
tidak ada satu pun order dana asli yang bisa terkirim - bahkan bila Anda salah
memilih menu 4.

Alur yang disarankan: **menu 1 (uji) -> menu 2 (backtest) -> menu 3 (testnet,
beberapa hari) -> baru menu 4 (live) dengan modal kecil.**

---

## 5. Keamanan berkas `.env`

- `.env` sudah masuk `.gitignore` - tidak akan pernah ikut ter-commit.
- Yang ikut repo hanyalah `.env.contoh` (template kosong).
- Jangan pernah menempel isi `.env` ke chat, issue, atau screenshot.
- Untuk API key live, disarankan: aktifkan pembatasan IP, dan **jangan** beri
  izin penarikan (withdrawal). Cukup izin *Enable Futures*.
- Semua tampilan status di layar (`python main.py --mode konfigurasi`) dan semua
  log selalu menyamarkan nilai rahasia menjadi bentuk `abcd...yz`.

---

## 6. Notifikasi Telegram

Bersifat opsional. Bila token/chat ID kosong, sistem otomatis memakai notifier
nonaktif dan tetap berjalan normal (semua laporan tetap tercetak ke layar).

Yang dilaporkan ke Telegram saat mode testnet/live berjalan:
- pesan mulai memantau (simbol, TF, horizon, saldo),
- sinyal yang menang beserta skor dan mode-nya,
- sinyal yang **tidak** dieksekusi beserta alasannya,
- entry terisi (qty terisi, jumlah slice ice-breaker, pembatalan),
- order SL `STOP_MARKET` yang berhasil terpasang,
- galat siklus.

Uji koneksi lebih dulu lewat menu 5 - ia memanggil `getMe` lalu mengirim satu
pesan uji ke chat Anda.

Kegagalan Telegram **tidak pernah** menghentikan trading: semua galat jaringan
ditelan dan hanya dicatat ke stderr.
