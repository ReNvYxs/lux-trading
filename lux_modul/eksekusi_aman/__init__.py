"""Lapisan eksekusi proteksi yang sudah divalidasi di Binance Testnet.

Status 6 Agu 2026: TERPASANG di jalur live lewat lux_modul/live_runner.py,
dipilih oleh lux_modul/eksekusi_aman/saklar.py berdasarkan jawaban bursa
(LUX_EKSEKUSI, bawaan 'otomatis'). Bukan lagi lapisan cadangan yang menganggur.

Isi:
  inti.py    SpekSimbol, KebijakanRisiko, hitung_ukuran, PengirimOrder,
             DataPasar, Proteksi, Entry, jalankan_siklus, KontrakEksekutor.
  saklar.py  pemilih mode + probe dukungan stop + cek kewajaran harga TP/SL.

Bukti jalannya di bursa sungguhan ada di bukti/live/ pada repo ini:
entry terisi, TP LIMIT reduceOnly terlihat di openOrders, dan fail-safe
menutup posisi nyata ketika pemasangan TP dipaksa gagal.

Catatan sejarah: proteksi.py (PenjagaProteksi) dihapus 6 Agu 2026 setelah
alat/impor_dalam.py membuktikan tidak ada satu pun pengimpor di seluruh pohon.
Dua implementasi proteksi yang bersaing di satu repo adalah jebakan, bukan
cadangan.
"""
