"""Tambalan berjangkar tahap 2 untuk kode.

Isi: saklar otomatis di LiveRunner, pemulihan proteksi setelah restart,
koreksi klaim palsu di docstring order.py, dan pelurusan MODUL_WAJIB gerbang.
Blok .env.contoh ditangani terpisah oleh alat/pasang_env.py.

Aturan sama seperti alat/pasang_saklar.py: jangkar harus muncul PERSIS
sejumlah yang dinyatakan, berkas .py dikompilasi sebelum ditulis, dan alat ini
idempoten. Jumlah kemunculan SEMUA jangkar dilaporkan lebih dulu, baru
diputuskan, supaya satu kali jalan cukup untuk tahu keadaan sebenarnya.
"""
import json
import os
import sys

RUNNER = "lux_modul/live_runner.py"
ORDER = "lux_modul/eksekusi/order.py"
GERBANG = "alat/gerbang.py"
IMPOR_DALAM = "alat/impor_dalam.py"

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
]


def baca(jalur):
    fh = open(jalur, "r", encoding="utf-8")
    isi = fh.read()
    fh.close()
    return isi


def main():
    isi = {}
    hilang = []
    for t in TAMBALAN:
        b = t["berkas"]
        if b in isi:
            continue
        if not os.path.isfile(b):
            hilang.append(b)
            continue
        isi[b] = baca(b)
    if hilang:
        print("TAMBAL=GAGAL")
        print("berkas_hilang=" + json.dumps(sorted(set(hilang))))
        return 2

    laporan = []
    mismatch = []
    for t in TAMBALAN:
        teks = isi[t["berkas"]]
        sudah = t["tanda"] in teks
        n = teks.count(t["cari"])
        laporan.append({"nama": t["nama"], "jumlah": n,
                        "diharap": t["jumlah"], "sudah": sudah})
        if not sudah and n != t["jumlah"]:
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
    print("sisa_aman_aktif_polos=" + str(isi[RUNNER].count("aman_aktif()")))
    print("order_klaim_palsu=" + str(
        isi[ORDER].count("DITERIMA saat posisi terbuka")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
