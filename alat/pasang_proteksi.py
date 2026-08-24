"""Penambal berjangkar untuk sisi PROTEKSI di eksekusi_aman/inti.py.

Temuan audit 25 Agu 2026 yang ditambal di sini:

D5. batalkan_proteksi MENELAN galat lalu tetap mengosongkan self.order_tp,
    seolah pembatalan berhasil. Itu klaim sukses tanpa konfirmasi pada jalur
    dana - tepat yang dilarang - dan meninggalkan order TP yatim di bursa tanpa
    ada yang tahu.

D9. periksa_sl membiarkan galat pembacaan harga merambat ke pemanggil, sehingga
    siklus itu MELEWATI pemeriksaan SL. Posisi tetap terbuka sementara SL-nya
    tidak dievaluasi, dan tidak ada hitungan berapa kali itu terjadi.

D10. rekonsiliasi MENDETEKSI orphan_proteksi, posisi_tanpa_proteksi, dan
    ukuran_proteksi_tidak_cocok - lalu hasilnya hanya disimpan di dict dan
    TIDAK PERNAH ditindaklanjuti siapa pun. Masalah terdeteksi, lalu didiamkan.

D-bentuk. order_terbuka mengembalikan apa pun dari _permintaan tanpa jaminan
    bentuk. Bila bursa mengembalikan objek alih-alih larik, iterasinya
    menghasilkan string dan pemanggil jatuh dengan AttributeError di jalur
    proteksi - tempat paling buruk untuk jatuh.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pasang_inti import INTI, terapkan  # noqa: E402

CARI_TERBUKA = """    def order_terbuka(self):
        return self.klien._permintaan("GET", "/fapi/v1/openOrders",
                                      {"symbol": self.simbol}, signed=True)
"""
GANTI_TERBUKA = """    def order_terbuka(self):
        # Bentuk jawaban DIJAMIN larik objek. Tanpa jaminan ini, jawaban
        # berbentuk objek membuat iterasi menghasilkan string, lalu pemanggil
        # jatuh dengan AttributeError persis di jalur proteksi.
        # Metode bertipe klien dipakai bila ada; _permintaan tetap jadi cadangan
        # supaya klien uji lama tidak ikut rusak.
        fn = getattr(self.klien, "order_terbuka", None)
        if callable(fn):
            hasil = fn(self.simbol)
        else:
            hasil = self.klien._permintaan("GET", "/fapi/v1/openOrders",
                                           {"symbol": self.simbol}, signed=True)
        if isinstance(hasil, dict):
            return [hasil] if hasil.get("orderId") is not None else []
        if not hasil:
            return []
        return [o for o in hasil if isinstance(o, dict)]
"""

CARI_BATAL = """    def batalkan_proteksi(self):
        try:
            self.klien.batalkan_semua_order(self.simbol)
        except Exception as exc:
            self._catat("gagal_batalkan", pesan=str(exc)[:140])
        self.order_tp = None
"""
GANTI_BATAL = """    def batalkan_proteksi(self):
        # Versi lama menelan galat lalu mengosongkan state lokal seolah
        # pembatalan berhasil. Sekarang: hasilnya dikembalikan, dikonfirmasi
        # dari jawaban bursa, DAN diverifikasi ulang dengan membaca openOrders.
        # Yang menentukan bukan jawaban, tapi keadaan.
        h = {"diminta": True, "terkonfirmasi": False, "galat": None,
             "sisa_order": None, "bersih": None}
        try:
            jawaban = self.klien.batalkan_semua_order(self.simbol)
            h["konfirmasi"] = konfirmasi_batal(jawaban, simbol=self.simbol)
            h["terkonfirmasi"] = True
        except Exception as exc:
            h["galat"] = str(exc)[:200]
            try:
                h["kelas"] = klasifikasikan(
                    exc, jalur="/fapi/v1/allOpenOrders", metode="DELETE",
                    dana=True).ringkas()
            except Exception:
                h["kelas"] = None
            self._catat("gagal_batalkan", pesan=h["galat"], kelas=h["kelas"])
        try:
            sisa = [o for o in self.order_terbuka() if o.get("reduceOnly")]
            h["sisa_order"] = len(sisa)
            h["bersih"] = not sisa
            if sisa:
                h["masalah"] = "orphan_proteksi_masih_hidup"
                h["order_yatim"] = [
                    {"orderId": o.get("orderId"), "type": o.get("type"),
                     "side": o.get("side"), "origQty": o.get("origQty"),
                     "price": o.get("price")} for o in sisa[:8]]
        except Exception as exc:
            h["galat_verifikasi"] = str(exc)[:200]
        self._catat("proteksi_dibatalkan", **h)
        self.order_tp = None
        return h
"""

CARI_MARK = """        m = mark_harga if mark_harga is not None else (
            self.data.mark(self.simbol) if self.data
            else float(self.klien.harga_sekarang(self.simbol)))
"""
GANTI_MARK = """        # Harga bisa gagal dibaca. Versi lama membiarkan galat merambat ke
        # pemanggil, sehingga siklus itu MELEWATI pemeriksaan SL tanpa jejak:
        # posisi tetap terbuka sementara SL-nya tidak dievaluasi. Sekarang
        # kegagalan dihitung, dan setelah BATAS_GAGAL_HARGA kali berturut-turut
        # posisi ditutup - SL perangkat lunak tanpa harga bukan proteksi.
        if mark_harga is not None:
            m = mark_harga
        else:
            try:
                m = (self.data.mark(self.simbol) if self.data
                     else float(self.klien.harga_sekarang(self.simbol)))
            except Exception as exc:
                self._gagal_harga = getattr(self, "_gagal_harga", 0) + 1
                self._catat("harga_gagal_dibaca", berturut=self._gagal_harga,
                            batas=BATAS_GAGAL_HARGA, pesan=str(exc)[:160])
                if self._gagal_harga >= BATAS_GAGAL_HARGA:
                    batal = self.batalkan_proteksi()
                    tutup = self.tutup_posisi("harga_tidak_terbaca")
                    return {"aksi": "failsafe_harga_buta",
                            "berturut": self._gagal_harga,
                            "pembatalan": batal, "penutupan": tutup,
                            "alasan": "mark price gagal dibaca berulang; SL "
                                      "perangkat lunak tidak dapat dievaluasi"}
                return {"aksi": "harga_tidak_terbaca",
                        "berturut": self._gagal_harga,
                        "pesan": str(exc)[:160]}
        if m is None:
            self._gagal_harga = getattr(self, "_gagal_harga", 0) + 1
            return {"aksi": "harga_tidak_terbaca", "berturut": self._gagal_harga,
                    "pesan": "mark price None"}
        self._gagal_harga = 0
"""

CARI_SL = """        self._catat("sl_tersentuh", mark=m, sl=self.sl_harga)
        self.batalkan_proteksi()
        return {"aksi": "sl_dieksekusi", "mark": m, "sl": self.sl_harga,
                "penutupan": self.tutup_posisi("sl_tersentuh")}
"""
GANTI_SL = """        self._catat("sl_tersentuh", mark=m, sl=self.sl_harga)
        # Urutan disengaja: TP dibatalkan dulu supaya tidak ada dua order
        # reduceOnly berebut posisi yang sama. Tetapi kalau pembatalan gagal,
        # penutupan TETAP dijalankan - posisi terbuka jauh lebih berbahaya
        # daripada order TP yatim - dan kegagalannya DILAPORKAN, bukan ditelan.
        batal = self.batalkan_proteksi()
        tutup = self.tutup_posisi("sl_tersentuh")
        h = {"aksi": "sl_dieksekusi", "mark": m, "sl": self.sl_harga,
             "pembatalan": batal, "penutupan": tutup}
        if not batal.get("terkonfirmasi") or batal.get("bersih") is False:
            h["peringatan"] = (
                "pembatalan proteksi tidak terkonfirmasi; periksa order yatim "
                "di bursa untuk " + str(self.simbol))
            h["perlu_diperbaiki"] = "Proteksi.batalkan_proteksi"
        if not tutup.get("bersih"):
            h["aksi"] = "sl_gagal_menutup"
            h["dampak"] = (
                "SL tersentuh tetapi posisi BELUM terbukti tertutup; risiko "
                "masih berjalan di pasar")
            h["perlu_diperbaiki"] = "Proteksi.tutup_posisi"
        return h
"""

CARI_REKON = """    try:
        h["rekonsiliasi"] = proteksi.rekonsiliasi()
    except Exception as exc:
        h["rekonsiliasi"] = {"galat": str(exc)[:140]}
    h["objek_proteksi"] = proteksi
    return h
"""
GANTI_REKON = """    try:
        h["rekonsiliasi"] = proteksi.rekonsiliasi()
    except Exception as exc:
        h["rekonsiliasi"] = {"galat": str(exc)[:140]}
    # DULU hasil rekonsiliasi hanya DISIMPAN dan tidak pernah ditindaklanjuti
    # siapa pun: masalah terdeteksi, lalu didiamkan. Sekarang dua temuan paling
    # berbahaya diambil tindakannya, dan tindakannya ikut tercatat.
    masalah = (h.get("rekonsiliasi") or {}).get("masalah")
    if masalah == "posisi_tanpa_proteksi":
        try:
            h["tindakan_rekonsiliasi"] = {
                "masalah": masalah,
                "alasan": "posisi terbuka tanpa order proteksi di bursa",
                "penutupan": proteksi.tutup_posisi(
                    "rekonsiliasi_posisi_tanpa_proteksi")}
            h["kesimpulan"] = "posisi_tanpa_proteksi_ditutup"
        except Exception as exc:
            h["tindakan_rekonsiliasi"] = {"masalah": masalah,
                                          "galat": str(exc)[:160]}
            h["kesimpulan"] = "BAHAYA_posisi_mungkin_telanjang"
    elif masalah == "orphan_proteksi":
        try:
            h["tindakan_rekonsiliasi"] = {
                "masalah": masalah,
                "alasan": "order proteksi hidup tanpa posisi",
                "pembatalan": proteksi.batalkan_proteksi()}
        except Exception as exc:
            h["tindakan_rekonsiliasi"] = {"masalah": masalah,
                                          "galat": str(exc)[:160]}
    elif masalah:
        h["tindakan_rekonsiliasi"] = {
            "masalah": masalah, "tindakan": "dilaporkan_saja",
            "alasan": "tidak ada tindakan otomatis yang jelas lebih aman "
                      "daripada melaporkan"}
    h["objek_proteksi"] = proteksi
    return h
"""

TAMBALAN = [
    {"nama": "order_terbuka_bentuk_dijamin", "berkas": INTI,
     "cari": CARI_TERBUKA, "ganti": GANTI_TERBUKA, "jumlah": 1,
     "tanda": "fn = getattr(self.klien, \"order_terbuka\", None)"},
    {"nama": "batalkan_proteksi_terverifikasi", "berkas": INTI,
     "cari": CARI_BATAL, "ganti": GANTI_BATAL, "jumlah": 1,
     "tanda": "orphan_proteksi_masih_hidup"},
    {"nama": "periksa_sl_tahan_harga_buta", "berkas": INTI, "cari": CARI_MARK,
     "ganti": GANTI_MARK, "jumlah": 1, "tanda": "failsafe_harga_buta"},
    {"nama": "periksa_sl_lapor_kegagalan", "berkas": INTI, "cari": CARI_SL,
     "ganti": GANTI_SL, "jumlah": 1, "tanda": "sl_gagal_menutup"},
    {"nama": "rekonsiliasi_bertindak", "berkas": INTI, "cari": CARI_REKON,
     "ganti": GANTI_REKON, "jumlah": 1, "tanda": "tindakan_rekonsiliasi"},
]


def main():
    rc, isi = terapkan(TAMBALAN, "PROTEKSI")
    if rc != 0:
        return rc
    teks = isi.get(INTI, "")
    print("panjang_inti=" + str(len(teks)))
    print("punya_batal_terverifikasi=" + str("orphan_proteksi_masih_hidup" in teks))
    print("punya_failsafe_harga=" + str("failsafe_harga_buta" in teks))
    print("punya_tindakan_rekonsiliasi=" + str("tindakan_rekonsiliasi" in teks))
    print("sisa_batal_polos=" + str(teks.count(
        "self.klien.batalkan_semua_order(self.simbol)\n        except Exception")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
