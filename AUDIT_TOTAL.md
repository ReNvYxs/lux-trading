# AUDIT TOTAL REPO - 3 Agustus 2026

Dokumen ini adalah hasil audit menyeluruh repo `lux-modul-trading` beserta semua
perbaikan yang dilakukan. Ditulis agar **sesi lain, akun lain, atau AI lain** bisa
memahami kondisi sistem tanpa membaca riwayat percakapan mana pun.

Urutan baca yang disarankan untuk pendatang baru:
`README.md` -> `KONFIGURASI.md` -> `ARSITEKTUR.md` -> dokumen ini -> `STATE.md`.

---

## 1. Ringkas: apa yang bisa dilakukan sistem ini sekarang

| Kemampuan | Status | Bukti |
|---|---|---|
| `python main.py` polos membuka menu & jalan | SIAP | dijalankan, menu tampil, keluar bersih |
| Backtest data historis CSV | SIAP | `reports/besar/` hasil 95 pair |
| Konektor Binance Futures Testnet | SIAP secara kode, **belum diadu server nyata** | unit test bermock |
| Konektor Binance Futures Live | SIAP secara kode + dua gerbang keamanan | unit test bermock |
| Kredensial terpusat & terpisah testnet/live | SIAP | 21 uji di `tests/test_konfigurasi.py` |
| Notifikasi Telegram | SIAP, opsional, fail-soft | uji notifier |
| Rantai end-to-end tanpa jaringan | LULUS | `python scripts/asap_e2e.py` |
| Seluruh unit test | 242 lulus / 0 gagal | `python scripts/jalankan_uji.py` |

---

## 2. Temuan audit dan perbaikannya

### GAP #1 - `python main.py` polos GAGAL (kritis, DIPERBAIKI)
`--mode` dulu `required=True`, sehingga `python main.py` langsung keluar dengan
error argparse. Target utama operator ("cukup `python main.py` dari PowerShell")
tidak terpenuhi.

**Perbaikan:** `--mode` jadi opsional. Tanpa argumen, `main.py` memuat `.env`,
mencetak panel status kredensial (tersamarkan), lalu membuka menu 6 pilihan + keluar.

### GAP #2 - Tidak ada tempat kredensial terpusat (kritis, DIPERBAIKI)
Sebelumnya hanya ada env var Binance yang dibaca tersebar; **Telegram belum ada
sama sekali** padahal diminta.

**Perbaikan:** modul baru `lux_modul/konfigurasi.py` (pemuat `.env` stdlib-only,
tanpa dependency pihak ketiga) + `.env.contoh` + `lux_modul/notifikasi/telegram.py`.
Prioritas nilai: **argumen CLI > env shell > berkas `.env` > default kode**.

### GAP #3 & #4 - `.gitignore` (DIPERBAIKI)
Pola `.env.*` ikut mengabaikan `.env.contoh`, sehingga template kredensial tidak
pernah sampai ke repo. Ditambah pengecualian `!.env.contoh`, plus `venv/` dan
`log_*.txt`.

### GAP #5 - Dokumentasi menyesatkan (DIPERBAIKI)
Docstring `live_runner.py` merujuk `tests/test_live_runner.py` yang **tidak pernah
ada**. Rujukan diganti ke berkas uji yang benar-benar ada dan lulus.

### GAP #6 - Sampah artefak (DIBERSIHKAN)
10 berkas `bt_*.log` / `log_*.txt` di akar dihapus dan polanya di-ignore.

### Catatan yang sengaja TIDAK diubah
- Versi `numpy`/`pandas` di `requirements.txt` dipin untuk CI dan berbeda dari
  versi sandbox. Ini tidak mengganggu karena inti hanya memakai API numpy dasar.
- Beberapa keterbatasan operasional masih terbuka, lihat bagian 6.

---

## 3. Bukti end-to-end (`scripts/asap_e2e.py`)

Skrip ini memutar **rantai yang sama persis dengan mode testnet/live**, hanya
konektornya diganti klien palsu berkursor waktu (tiap iterasi satu lilin baru
tutup, seperti pasar sungguhan). Hasil terakhir:

```
600 siklus, 600 bar baru diproses, 107 verdict,
35 eksekusi entry, 35 order SL, 0 galat
order terkirim: {'LIMIT': 35, 'STOP_MARKET': 35}
HASIL: LULUS
```

Invariant yang ditegakkan skrip (gagal = keluar dengan kode 1):
1. Semua order LIMIT wajib `timeInForce=GTX` (**post-only**).
2. **Order MARKET diharamkan** - satu pun tidak boleh terkirim.
3. Semua SL wajib `STOP_MARKET` dengan `closePosition`/`reduceOnly`.
4. Entry terisi tanpa SL menyusul = GAGAL.
5. Loop harus benar-benar berputar (>= 100 bar diproses), bukan sekali jalan.

Rantai yang terbukti tersambung:

```
main.py -> konfigurasi(.env) -> kredensial(mode) -> BinanceFuturesClient
  -> klines REST -> DataPlane (buang bar belum tutup) -> FeatureStore
  -> 26 unit strategi/pola/indikator -> arbiter (ambang, skor, margin konflik)
  -> risk management (sizing) -> rencana eksekusi post-only + ice-breaker
  -> order entry -> order SL STOP_MARKET -> SiklusHasil.ringkas()
  -> stdout JSON + notifikasi Telegram
```

---

## 4. Perilaku `main.py` yang sudah diverifikasi

| Perintah | Hasil aktual |
|---|---|
| `python main.py` | menu tampil, pilihan `0` keluar bersih |
| `python main.py --mode konfigurasi` | panel status, semua kredensial `(kosong)`, gerbang live tertutup |
| menu pilih `3` (testnet) tanpa kunci | ditolak + instruksi mengisi `.env` + tautan testnet |
| menu pilih `4` (live) tanpa kunci | banner peringatan + ditolak (`kredensial LIVE belum lengkap`) |
| `python main.py --mode uji` | 242 lulus / 0 gagal |

Kode keluar alur live: `2` = kredensial live kosong, `3` = gerbang env tertutup,
`4` = frasa konfirmasi tidak cocok.

---

## 5. Cara menjalankan (ringkas - detail di `KONFIGURASI.md`)

```powershell
pip install -r requirements.txt
copy .env.contoh .env       # isi kredensial
python main.py
```

Urutan uji yang diwajibkan: **menu 1 (uji) -> menu 2 (backtest) -> menu 3
(testnet, mulai dengan `LUX_MAKS_SIKLUS` kecil) -> baru menu 4 (live)**.

Mode live butuh DUA gerbang bersamaan:
1. konfirmasi eksplisit (`--konfirmasi-live` atau ketik ulang frasa di menu), DAN
2. `LUX_LIVE_KONFIRMASI=SAYA_PAHAM_INI_AKUN_LIVE_DANA_ASLI` di `.env`.

---

## 6. Keterbatasan yang MASIH ADA (jujur, jangan dilewatkan)

1. **Konektor belum pernah menyentuh server Binance sungguhan.** Sandbox
   pengembangan tidak punya akses internet keluar. Semua bukti berasal dari mock.
   Uji testnet dengan siklus terbatas adalah langkah wajib berikutnya.
2. **Belum ada pelacakan posisi/PnL real-time maupun rekonsiliasi posisi dari
   exchange.** Sistem mengirim entry + SL, tetapi tidak menarik ulang state posisi
   dari akun tiap siklus.
3. **Belum ada persistensi state antar-restart.** Proses yang dimatikan lalu
   dijalankan lagi memulai pembukuan internal dari nol (order & posisi di exchange
   tentu tetap ada).
4. **Belum ada equity-floor / batas notional harian** sebagai rem darurat.
5. **Edge strategi belum diseleksi.** Backtest 95 pair menunjukkan PnL bersih
   negatif di kelima konfigurasi TF setelah biaya. Jangan pakai modal berarti di
   mode live sebelum tahap seleksi strategi selesai.

---

## 7. Langkah berikutnya yang disepakati

1. Operator mengisi `.env` dengan kunci **testnet**, menjalankan `python main.py`
   -> menu 3, dengan `LUX_MAKS_SIKLUS` kecil.
2. Setelah testnet terbukti (order tampil di dashboard testnet Binance), evaluasi.
3. Baru sesudah itu: backtest 95 pair untuk seleksi strategi.
4. Live trading dengan modal kecil hanya setelah 1-3 beres.
