# Laporan perbaikan otomatis

- Dijalankan: 2026-08-04 19:14:34 UTC
- Commit pemicu: 3705eb8b64745901bd8837b70562159748b6dec5
- Status akhir: ok
- Log lengkap: LOG_PERBAIKAN.txt

## Ringkasan pytest
```
242 passed in 43.11s
.  test_binance_client.py::test_http_error_dilempar_sebagai_binance_api_error
.  test_live_runner.py::test_bracket_tanpa_tp_order_id_sl_tertrigger_tidak_error
```

## Ringkasan verifikasi & kesiapan live
```
== RINGKASAN PATCH 4 ==
JUMLAH_GAGAL_IMPOR= 0
POLA_SALAH_BERSIH
TP_DARI_VERDICT_OK harga= 110.0
HORIZON_AUTO_ENTRY= ('scalping', 'intraday')
KONTRAK_AUTO_ENTRY_OK
RATE_LIMIT_OK batas_resmi= 2400
TF_DINAMIS_OK 1m= 1440 5m= 288
STRATEGI_TERDAFTAR= 26
TOTAL_FUNGSI_UJI= 242
===== RINGKASAN VERIFIKASI =====
STATUS_VERIFIKASI= LULUS
JUMLAH_ENTRY_POINT= 18
GALAT_KONTRAK_IMPOR= 0
  TOTAL_MODEL                     :    122.1 bobot/menit
  ANGGARAN_PENGATUR_LAJU          :   1200.0 bobot/menit
  MODEL_BEBAN_OK margin= 1077.9
===== RINGKASAN KESIAPAN LIVE =====
STATUS_KESIAPAN= SIAP
RINGKASAN: 242 lulus, 0 gagal, total 242
```

## Cakupan perbaikan
1. Ban IP 418/-1003: pengatur laju berbasis bobot (jendela 60 detik) yang menahan SEBELUM permintaan dikirim; cache TTL untuk exchangeInfo, leverageBracket, klines, dan waktu server; gerbang ban lokal di client; gerbang ban di engine sehingga siklus dilewati tanpa satu pun permintaan.
2. Bug P0: order Take Profit tidak pernah dikirim ke bursa karena membaca atribut `tp` yang tidak ada pada StrategyVerdict (yang benar `tps[0].harga`).
3. Id strategi selalu kosong di Telegram/dashboard karena membaca `strategi`, bukan `strategy_id`.
4. Penjadwalan runner per TF; runner dengan entry pending atau bracket aktif tetap dipoll setiap siklus agar SL/TP tetap terpantau.
5. Hygiene: import mati (dihapus hanya setelah dibuktikan tak terpakai), TF dinamis di pivot_reversal, README diselaraskan dengan implementasi.
6. Kontrak auto-entry dikunci uji: Scalp DAN Intraday boleh auto-entry, Swing dilarang.
7. Gerbang kesiapan live: kontrak impor SEMUA entry point (main.py + scripts/) diverifikasi, karena pytest tidak pernah mengimpor berkas itu.
