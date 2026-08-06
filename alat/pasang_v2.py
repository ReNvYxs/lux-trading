"""Tambalan berjangkar tahap 2.

Isi: saklar otomatis di LiveRunner, pemulihan proteksi setelah restart,
koreksi klaim palsu di docstring order.py, pelurusan MODUL_WAJIB gerbang,
dan penambahan blok LUX_EKSEKUSI di .env.contoh.

Aturan sama seperti alat/pasang_saklar.py: jangkar harus muncul PERSIS
sejumlah yang dinyatakan, seluruh berkas .py dikompilasi sebelum ditulis, dan
alat ini idempoten. Lebih baik tidak mengubah apa pun daripada mengubah
tempat yang salah. Jumlah kemunculan SEMUA jangkar dilaporkan lebih dulu,
baru diputuskan, supaya satu kali jalan cukup untuk tahu keadaan sebenarnya.
"""
import json
import os
import sys

RUNNER = "lux_modul/live_runner.py"
ORDER = "lux_modul/eksekusi/order.py"
GERBANG = "alat/gerbang.py"
IMPOR_DALAM = "alat/impor_dalam.py"
ENVC = ".env.contoh"

CARI_IMPOR = "from .eksekusi_aman.saklar import aman_aktif, pasang_proteksi_aman\n"
GANTI_IMPOR = (
    "from .eksekusi_aman.saklar import aman_aktif_untuk, pasang_proteksi_aman\n"
)

CARI_A = """        if aman_aktif():
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=self.simbol, arah=v.arah,
"""
GANTI_A = """        if aman_aktif_untuk(self.client, self.simbol):
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=self.simbol, arah=v.arah,
"""

CARI_B = """        if aman_aktif():
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=ep.simbol, arah=ep.arah,
"""
GANTI_B = """        if aman_aktif_untuk(self.client, ep.simbol):
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=ep.simbol, arah=ep.arah,
"""

CARI_PULIH = """    # SL pada jalur aman tidak ada di bursa, jadi harus dipantau tiap siklus.
    def _periksa_sl_aman(self) -> List[str]:
        galat: List[str] = []
        peta = getattr(self, "_proteksi_aman", None)
        if not peta:
            return galat
"""

GANTI_PULIH = """    # Pemulihan setelah restart atau reconnect. SL jalur aman hidup di dalam
    # proses; kalau proses mati, SL ikut mati. Sekali saja, pada siklus
    # pertama, keadaan bursa dibaca ulang supaya posisi lama tidak jadi yatim.
    def _pulihkan_proteksi_aman(self) -> List[str]:
        galat: List[str] = []
        self._pulih_dijalankan = True
        try:
            if not aman_aktif_untuk(self.client, self.simbol):
                return galat
            from .eksekusi_aman.inti import (
                DataPasar,
                PengirimOrder,
                Proteksi,
                SpekSimbol,
            )
            tidur = getattr(self, "_tidur", None)
            spek = SpekSimbol.dari_exchange_info(
                self.client.exchange_info(self.simbol), self.simbol)
            prot = Proteksi(
                self.client,
                PengirimOrder(self.client, tidur=tidur),
                spek,
                self.simbol,
                data=DataPasar(self.client),
                tidur=tidur,
            )
            self._pulih_hasil = prot.pulihkan_dari_bursa()
            self._proteksi_aman[self.simbol] = prot
            cek = prot.periksa_sl()
            self._pulih_cek = cek
            aksi = cek.get("aksi") if isinstance(cek, dict) else None
            if aksi in ("sl_dieksekusi", "tidak_ada"):
                self._proteksi_aman.pop(self.simbol, None)
        except Exception as exc:  # noqa: BLE001
            getattr(self, "_proteksi_aman", {}).pop(self.simbol, None)
            galat.append("pulih_proteksi_" + str(self.simbol) + ": " + str(exc))
        return galat

    # SL pada jalur aman tidak ada di bursa, jadi harus dipantau tiap siklus.
    def _periksa_sl_aman(self) -> List[str]:
        galat: List[str] = []
        peta = getattr(self, "_proteksi_aman", None)
        if peta is not None and not peta and not getattr(
                self, "_pulih_dijalankan", False):
            galat.extend(self._pulihkan_proteksi_aman())
        if not peta:
            return galat
"""

CARI_GERBANG = """    "lux_modul.eksekusi_aman.inti",
    "lux_modul.eksekusi_aman.proteksi",
]
"""
GANTI_GERBANG = """    "lux_modul.eksekusi.binance_client",
    "lux_modul.eksekusi.kredensial",
    "lux_modul.eksekusi.order",
    "lux_modul.eksekusi_aman.inti",
    "lux_modul.eksekusi_aman.saklar",
    "lux_modul.live_runner",
]
"""

CARI_SOROT = """SOROT = ["lux_modul.eksekusi_aman.inti", "lux_modul.eksekusi_aman.proteksi",
         "lux_modul.eksekusi_aman.saklar"]
"""
GANTI_SOROT = """SOROT = ["lux_modul.eksekusi_aman.inti", "lux_modul.eksekusi_aman.saklar",
         "lux_modul.live_runner"]
"""

BLOK_ENV = """LUX_RR_BERSIH_MIN=

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
#                      stop tetap hidup walau proses mati.
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

TAMBALAN = [
    {"nama": "runner_impor", "berkas": RUNNER, "cari": CARI_IMPOR,
     "ganti": GANTI_IMPOR, "jumlah": 1,
     "tanda": "import aman_aktif_untuk,"},
    {"nama": "runner_entry_langsung", "berkas": RUNNER, "cari": CARI_A,
     "ganti": GANTI_A, "jumlah": 1,
     "tanda": "aman_aktif_untuk(self.client, self.simbol)"},
    {"nama": "runner_entry_pending", "berkas": RUNNER, "cari": CARI_B,
     "ganti": GANTI_B, "jumlah": 1,
     "tanda": "aman_aktif_untuk(self.client, ep.simbol)"},
    {"nama": "runner_pemulihan", "berkas": RUNNER, "cari": CARI_PULIH,
     "ganti": GANTI_PULIH, "jumlah": 1,
     "tanda": "_pulihkan_proteksi_aman"},
    {"nama": "order_docstring_palsu", "berkas": ORDER,
     "cari": "DITERIMA saat posisi terbuka",
     "ganti": "DITOLAK -4120 pada 6 Agu 2026, lihat bukti/live/",
     "jumlah": 2, "tanda": "DITOLAK -4120 pada 6 Agu 2026"},
    {"nama": "gerbang_modul_wajib", "berkas": GERBANG, "cari": CARI_GERBANG,
     "ganti": GANTI_GERBANG, "jumlah": 1,
     "tanda": "lux_modul.eksekusi_aman.saklar"},
    {"nama": "impor_dalam_sorot", "berkas": IMPOR_DALAM, "cari": CARI_SOROT,
     "ganti": GANTI_SOROT, "jumlah": 1,
     "tanda": "lux_modul.live_runner"},
    {"nama": "env_contoh_saklar", "berkas": ENVC,
     "cari": "LUX_RR_BERSIH_MIN=\n", "ganti": BLOK_ENV, "jumlah": 1,
     "tanda": "LUX_EKSEKUSI="},
]


def baca(jalur):
    fh = open(jalur, "r", encoding="utf-8")
    isi = fh.read()
    fh.close()
    return isi


def main():
    isi = {}
    berkas_hilang = []
    for t in TAMBALAN:
        b = t["berkas"]
        if b in isi:
            continue
        if not os.path.isfile(b):
            berkas_hilang.append(b)
            continue
        isi[b] = baca(b)
    if berkas_hilang:
        print("TAMBAL=GAGAL")
        print("berkas_hilang=" + json.dumps(sorted(set(berkas_hilang))))
        return 2

    laporan = []
    mismatch = []
    for t in TAMBALAN:
        teks = isi[t["berkas"]]
        sudah = t["tanda"] in teks
        n = teks.count(t["cari"])
        laporan.append({"nama": t["nama"], "berkas": t["berkas"],
                        "jumlah": n, "diharap": t["jumlah"],
                        "sudah": sudah})
        if sudah:
            continue
        if n != t["jumlah"]:
            mismatch.append(t["nama"])

    for r in laporan:
        print("jangkar=" + json.dumps(r, ensure_ascii=False))

    if mismatch:
        print("TAMBAL=GAGAL")
        print("jangkar_bermasalah=" + json.dumps(mismatch))
        return 3

    diterapkan = []
    for t in TAMBALAN:
        teks = isi[t["berkas"]]
        if t["tanda"] in teks:
            continue
        isi[t["berkas"]] = teks.replace(t["cari"], t["ganti"], t["jumlah"])
        diterapkan.append(t["nama"])

    for b in sorted(isi):
        if not b.endswith(".py"):
            continue
        try:
            compile(isi[b], b, "exec")
        except SyntaxError as exc:
            print("TAMBAL=GAGAL")
            print("sintaks_rusak=" + b + " " + repr(exc))
            return 4

    for b in sorted(isi):
        fh = open(b, "w", encoding="utf-8")
        fh.write(isi[b])
        fh.close()

    print("TAMBAL=SELESAI")
    print("diterapkan=" + json.dumps(diterapkan))
    print("panjang_runner=" + str(len(isi[RUNNER])))
    print("punya_pulihkan=" + str("_pulihkan_proteksi_aman" in isi[RUNNER]))
    print("punya_aman_untuk=" + str("aman_aktif_untuk" in isi[RUNNER]))
    print("order