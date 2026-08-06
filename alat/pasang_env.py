"""Tambahkan blok LUX_EKSEKUSI ke .env.contoh.

Dipisah dari alat/pasang_v2.py karena .env.contoh bukan berkas Python dan
tidak boleh ikut dikompilasi. Idempoten: kalau LUX_EKSEKUSI sudah ada,
tidak melakukan apa-apa.
"""
import os
import sys

BERKAS = ".env.contoh"
JANGKAR = "LUX_RR_BERSIH_MIN=\n"
TANDA = "LUX_EKSEKUSI="

BLOK = """LUX_RR_BERSIH_MIN=

# ---------------------------------------------------------------------
# 7. LAPISAN EKSEKUSI PROTEKSI TP/SL   (baru 6 Agu 2026)
# ---------------------------------------------------------------------
# Menentukan CARA TP dan SL dipasang di bursa. Ini bukan setelan strategi:
# logika sinyal, ukuran posisi, dan harga TP/SL tidak berubah sedikit pun.
#
#   otomatis  (BAWAAN, disarankan)
#       Sekali di awal, bursa ditanya lewat endpoint order/test - tanpa order
#       nyata - apakah tipe stop kondisional diterima.
#         diterima  -> jalur lama: STOP_MARKET/TAKE_PROFIT_MARKET di bursa,
#                      stop tetap hidup walaupun proses mati.
#         ditolak   -> jalur aman: TP = LIMIT reduceOnly di bursa, SL dipantau
#                      perangkat lunak, gagal pasang proteksi = posisi DITUTUP.
#         tak jelas -> jalur aman (fail-closed).
#   lama      Paksa jalur lama. Pakai HANYA bila Anda sudah membuktikan sendiri
#             bursa Anda menerima STOP_MARKET closePosition.
#   aman      Paksa jalur aman.
#
# Latar: 6 Agu 2026 Binance Futures Testnet menolak STOP_MARKET DAN
# TAKE_PROFIT_MARKET dengan -4120. Di bursa seperti itu jalur lama
# meninggalkan posisi tanpa proteksi apa pun. Perilaku mainnet belum pernah
# diverifikasi, karena itu bawaannya bertanya, bukan menebak.
LUX_EKSEKUSI=otomatis

# Batas kewajaran jarak TP/SL terhadap harga acuan, sebagai pecahan (0 - 5).
# Kosong = 0.5 (50 persen). Bursa TIDAK menjaga hal ini: PRICE_FILTER.maxPrice
# BTCUSDT tercatat 809484.0, sekitar 12.5x harga pasar, dan TP di 10x harga
# pasar DITERIMA bursa. Order salah hitung tidak ditolak, ia hanya tidak pernah
# tersentuh - posisi terlihat terlindungi padahal tidak. Pemeriksaan ini ada di
# sisi kita justru karena tidak ada di sisi bursa.
LUX_BATAS_JARAK_PROTEKSI=
"""


def main():
    if not os.path.isfile(BERKAS):
        print("ENV=GAGAL berkas_tidak_ada")
        return 2
    fh = open(BERKAS, "r", encoding="utf-8")
    isi = fh.read()
    fh.close()
    if TANDA in isi:
        print("ENV=SUDAH_ADA")
        return 0
    n = isi.count(JANGKAR)
    print("jangkar_jumlah=" + str(n))
    if n != 1:
        print("ENV=GAGAL jangkar_tidak_tunggal")
        return 3
    isi = isi.replace(JANGKAR, BLOK, 1)
    fh = open(BERKAS, "w", encoding="utf-8")
    fh.write(isi)
    fh.close()
    print("ENV=SELESAI")
    print("panjang=" + str(len(isi)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
