# Laporan kesiapan uji live (cabang main)

- Dijalankan: 2026-08-05 06:24:20 UTC
- Commit: bdee02e0b7f6be2254dcaf85e9fec5bb449fe4c8
- Status akhir: ok
- Log lengkap: LOG_KESIAPAN.txt

## Bukti
```
== RINGKASAN PATCH 5 (dokumen) ==
PATCH5_SELESAI
JUMLAH_GAGAL_IMPOR= 0
POLA_SALAH_BERSIH
HORIZON_AUTO_ENTRY= ('scalping', 'intraday')
KONTRAK_AUTO_ENTRY_OK
STRATEGI_TERDAFTAR= 26
TOTAL_FUNGSI_UJI= 242
===== RINGKASAN VERIFIKASI =====
STATUS_VERIFIKASI= LULUS
JUMLAH_ENTRY_POINT= 19
GALAT_KONTRAK_IMPOR= 0
  TOTAL_MODEL                     :    122.1 bobot/menit
  ANGGARAN_PENGATUR_LAJU          :   1200.0 bobot/menit
  MODEL_BEBAN_OK margin= 1077.9
===== RINGKASAN KESIAPAN LIVE =====
STATUS_KESIAPAN= SIAP
KLAIM_ANGKA_DIPERIKSA= 8
JUMLAH_MISMATCH_DOKUMEN= 0
STATUS_DOKUMEN= BERSIH
242 passed in 43.11s
RINGKASAN: 242 lulus, 0 gagal, total 242
```

Catatan jujur: model beban API adalah aritmetika memakai fungsi bobot milik kode sendiri, bukan trafik nyata. Yang menjamin plafon di runtime adalah pengatur laju, bukan model ini. Uji di CI juga tidak menyentuh bursa sungguhan - perilaku sisi bursa hanya bisa dibuktikan lewat testnet.
