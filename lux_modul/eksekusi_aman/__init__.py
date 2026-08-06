"""Lapisan eksekusi proteksi yang sudah divalidasi di Binance Testnet.

Status 6 Agu 2026: TERPASANG di jalur live lewat lux_modul/live_runner.py,
dipilih oleh lux_modul/eksekusi_aman/saklar.py berdasarkan jawaban bursa
(LUX_EKSEKUSI, bawaan 'otomatis'). Bukan lagi lapisan cadangan yang menganggur.

Isi:
  inti.py    SpekSimbol, KebijakanRisiko, hitung_ukuran, PengirimOrder,
             DataPasar, Proteksi, Entry, jalankan_siklus, KontrakEksekutor.
  saklar.py  pemilih mode, probe dukungan tipe stop, dan cek kewajaran harga
             TP/SL yang tidak disediakan bursa.

Bukti jalannya di bursa sungguhan ada di bukti/live/ pada repo ini: entry
terisi, TP LIMIT reduceOnly terlihat di openOrders, dan fail-safe menutup
posisi nyata ketika pemasangan TP dipaksa gagal.

Catatan sejarah: berkas penjaga proteksi versi lama dihapus 6 Agu 2026 setelah
alat/impor_dalam.py membuktikan tidak ada satu pun pengimpor di seluruh pohon,
dan alat/buang_mati.py memverifikasi ulang tepat sebelum menghapus. Dua
implementasi proteksi yang bersaing di satu repo siap-mainnet adalah jebakan,
bukan cadangan: yang satu diadu dengan bursa sungguhan, yang satu tidak pernah.
"""
