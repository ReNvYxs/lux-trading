"""Penambal berjangkar untuk sisi PENGIRIM di eksekusi_aman/inti.py.

Temuan audit 25 Agu 2026 yang ditambal di sini, semuanya dari sumber:

D1. PengirimOrder.kirim mengembalikan hasil OK tanpa memeriksa apa pun. Klien
    REST mengembalikan {} untuk badan jawaban kosong, jadi {} bisa mengalir
    sebagai sukses lengkap dengan orderId None. Ini persis kondisi yang
    dilarang: melaporkan order berhasil padahal bursa belum mengonfirmasi.

D2. Loop retry mengulang APA PUN yang bukan permanen, termasuk -1003 dan HTTP
    418/429. Mengulang saat dibatasi laju memperpanjang pembatasan; mengulang
    saat status tak diketahui bisa menggandakan order.

D3. KODE_PERMANEN hanya memuat 9 kode yang pernah kita lihat sendiri. -2019
    margin tidak cukup dan -4164 notional di bawah minimum jelas permanen,
    tetapi diulang 3x dengan backoff - membuang waktu tepat saat fail-safe
    harus bergerak cepat.

D4. baca_status BERHENTI pada galat non -2013 apa pun, sehingga satu timeout
    sesaat membatalkan seluruh pembacaan status - padahal status order paling
    dibutuhkan justru saat jaringan sedang buruk.

Modul ini juga menyediakan `terapkan()` yang dipakai penambal proteksi.
"""
import json
import os
import sys

INTI = "lux_modul/eksekusi_aman/inti.py"


def terapkan(tambalan, label):
    """Mesin penambal: laporkan semua jangkar dulu, baru putuskan.

    Aturan: jangkar harus muncul PERSIS sejumlah yang dinyatakan, berkas
    dikompilasi sebelum ditulis, dan idempoten lewat sentinel 'tanda'.
    """
    isi = {}
    hilang = []
    for t in tambalan:
        b = t["berkas"]
        if b in isi:
            continue
        if not os.path.isfile(b):
            hilang.append(b)
            continue
        fh = open(b, "r", encoding="utf-8")
        isi[b] = fh.read()
        fh.close()
    if hilang:
        print(label + "=GAGAL")
        print("berkas_hilang=" + json.dumps(sorted(set(hilang))))
        return 2, isi

    laporan = []
    bermasalah = []
    for t in tambalan:
        teks = isi[t["berkas"]]
        sudah = t["tanda"] in teks
        n = teks.count(t["cari"])
        laporan.append({"nama": t["nama"], "jumlah": n,
                        "diharap": t["jumlah"], "sudah": sudah})
        if not sudah and n != t["jumlah"]:
            bermasalah.append(t["nama"])
    for r in laporan:
        print("jangkar=" + json.dumps(r, ensure_ascii=False))
    if bermasalah:
        print(label + "=GAGAL")
        print("jangkar_bermasalah=" + json.dumps(bermasalah))
        return 3, isi

    diterapkan = []
    for t in tambalan:
        teks = isi[t["berkas"]]
        if t["tanda"] in teks:
            continue
        isi[t["berkas"]] = teks.replace(t["cari"], t["ganti"], t["jumlah"])
        diterapkan.append(t["nama"])

    for b in sorted(isi):
        try:
            compile(isi[b], b, "exec")
        except SyntaxError as exc:
            print(label + "=GAGAL")
            print("sintaks_rusak=" + b + " " + repr(exc))
            return 4, isi
    for b in sorted(isi):
        fh = open(b, "w", encoding="utf-8")
        fh.write(isi[b])
        fh.close()
    print(label + "=SELESAI")
    print("diterapkan=" + json.dumps(diterapkan))
    return 0, isi


CARI_IMPOR = """import hashlib
import math
import time

ARAH_LONG = "LONG"
"""
GANTI_IMPOR = """import hashlib
import math
import time

from ..eksekusi.klasifikasi import KODE_PERMANEN as _KODE_PERMANEN_RUJUKAN
from ..eksekusi.klasifikasi import (
    GagalKonfirmasi,
    KELAS_KREDENSIAL,
    KELAS_LAJU,
    KELAS_PERMANEN,
    KELAS_TAK_DIKETAHUI,
    klasifikasikan,
    konfirmasi_batal,
    konfirmasi_order,
)

ARAH_LONG = "LONG"
"""

CARI_KODE = 'KODE_PERMANEN = {-1102, -1111, -4003, -4014, -4120, -2022, -5022, -1116, -1121}\n'
GANTI_KODE = """# DIPERLUAS 25 Agu 2026. Daftar lama hanya memuat 9 kode yang pernah kita lihat
# sendiri di p01-p10. Kode yang jelas permanen seperti -2019 (margin tidak
# cukup) dan -4164 (notional di bawah minimum) tidak ada di dalamnya, sehingga
# diulang 3x dengan backoff - membuang waktu tepat saat fail-safe harus cepat.
# Sumber tunggal sekarang eksekusi/klasifikasi.py, lengkap dengan rujukannya.
KODE_PERMANEN = set(_KODE_PERMANEN_RUJUKAN)
# Berapa kali harga boleh gagal dibaca berturut-turut sebelum posisi ditutup.
# SL perangkat lunak tanpa harga BUKAN proteksi, jadi buta berulang harus
# berakhir pada penutupan, bukan pada siklus yang dilewati diam-diam.
BATAS_GAGAL_HARGA = 3
"""

CARI_KIRIM = """                self.jumlah_permintaan += 1
                order = self.klien.kirim_order(payload)
                self._catat("order_terkirim", niat=niat, cid=cid,
                            percobaan=percobaan, orderId=order.get("orderId"))
                return {"hasil": "OK", "order": order, "cid": cid,
                        "percobaan": percobaan}
"""
GANTI_KIRIM = """                self.jumlah_permintaan += 1
                order = self.klien.kirim_order(payload)
                # Jawaban apa pun TIDAK cukup untuk menyebut order berhasil.
                # Klien REST mengembalikan {} untuk badan jawaban kosong, dan
                # blok ini dulu mengembalikan OK untuk {} itu juga, dengan
                # orderId None. Sekarang jawaban wajib lolos konfirmasi:
                # ada orderId atau clientOrderId, DAN status yang dikenal.
                try:
                    ringkas = konfirmasi_order(
                        order, simbol=payload.get("symbol"),
                        sisi=payload.get("side"), cid=cid)
                except GagalKonfirmasi as gk:
                    self._catat("tidak_terkonfirmasi", niat=niat, cid=cid,
                                percobaan=percobaan, pesan=str(gk)[:200])
                    # Belum tentu gagal: order bisa sudah masuk. Tanya bursa.
                    ada = self.cari_lewat_cid(payload["symbol"], cid)
                    if ada:
                        try:
                            ringkas2 = konfirmasi_order(ada, cid=cid)
                        except GagalKonfirmasi:
                            ringkas2 = None
                        if ringkas2 is not None:
                            self._catat("terkonfirmasi_lewat_cid", niat=niat,
                                        cid=cid, status=ringkas2.get("status"))
                            return {"hasil": "PULIH_LEWAT_CID", "order": ada,
                                    "ringkas": ringkas2, "cid": cid,
                                    "percobaan": percobaan}
                    return {"hasil": "TIDAK_TERKONFIRMASI", "order": order,
                            "cid": cid, "percobaan": percobaan,
                            "pesan": str(gk)[:300]}
                self._catat("order_terkirim", niat=niat, cid=cid,
                            percobaan=percobaan, orderId=ringkas.get("orderId"),
                            status=ringkas.get("status"))
                return {"hasil": "OK", "order": order, "ringkas": ringkas,
                        "cid": cid, "percobaan": percobaan}
"""

CARI_RETRY = """                galat = exc
                if percobaan < self.coba_maks:
"""
GANTI_RETRY = """                galat = exc
                # Tidak semua galat boleh diulang. Dibatasi laju: mengulang
                # memperpanjang pembatasan dan bisa memicu ban IP. Status tak
                # diketahui: mengulang bisa MENGGANDAKAN order, karena
                # permintaan pertama mungkin sudah mencapai matching engine.
                # Keduanya dihentikan di sini dan diserahkan ke rekonsiliasi.
                kep = klasifikasikan(exc, jalur="/fapi/v1/order",
                                     metode="POST", dana=True)
                if kep.kelas in (KELAS_LAJU, KELAS_TAK_DIKETAHUI):
                    self._catat("berhenti_tanpa_ulang", niat=niat, cid=cid,
                                kelas=kep.kelas, alasan=kep.alasan,
                                jeda_disarankan_ms=kep.jeda_ms)
                    return {"hasil": "TIDAK_TERKONFIRMASI", "cid": cid,
                            "percobaan": percobaan, "kelas": kep.kelas,
                            "pesan": kep.alasan, "galat": str(exc)[:200],
                            "wajib_rekonsiliasi": kep.wajib_rekonsiliasi}
                if kep.wajib_sinkron_waktu:
                    # -1021 tidak akan pernah sembuh dengan diulang saja:
                    # offset waktu harus disinkronkan lebih dulu.
                    try:
                        self.klien.sinkron_waktu()
                        self._catat("waktu_disinkronkan", niat=niat, cid=cid)
                    except Exception as exc_w:
                        self._catat("sinkron_waktu_gagal", niat=niat, cid=cid,
                                    pesan=str(exc_w)[:160])
                if percobaan < self.coba_maks:
"""

CARI_STATUS = """                terakhir = exc
                kode = getattr(exc, "kode", None)
                if kode is not None and kode != KODE_ORDER_TIDAK_ADA:
                    break
"""
GANTI_STATUS = """                terakhir = exc
                kode = getattr(exc, "kode", None)
                # Versi lama BERHENTI pada galat non -2013 apa pun, sehingga
                # satu timeout sesaat membatalkan seluruh pembacaan status -
                # padahal status order paling dibutuhkan justru saat jaringan
                # sedang buruk. Sekarang hanya galat permanen yang menghentikan;
                # galat sementara dan status tak diketahui tetap dicoba lagi.
                kep_st = klasifikasikan(exc, jalur="/fapi/v1/order",
                                        metode="GET")
                if (kode is not None and kode != KODE_ORDER_TIDAK_ADA
                        and kep_st.kelas in (KELAS_PERMANEN, KELAS_KREDENSIAL)):
                    break
"""

TAMBALAN = [
    {"nama": "inti_impor_klasifikasi", "berkas": INTI, "cari": CARI_IMPOR,
     "ganti": GANTI_IMPOR, "jumlah": 1,
     "tanda": "from ..eksekusi.klasifikasi import"},
    {"nama": "inti_kode_permanen_diperluas", "berkas": INTI, "cari": CARI_KODE,
     "ganti": GANTI_KODE, "jumlah": 1,
     "tanda": "KODE_PERMANEN = set(_KODE_PERMANEN_RUJUKAN)"},
    {"nama": "kirim_wajib_konfirmasi", "berkas": INTI, "cari": CARI_KIRIM,
     "ganti": GANTI_KIRIM, "jumlah": 1,
     "tanda": "\"hasil\": \"TIDAK_TERKONFIRMASI\", \"order\": order"},
    {"nama": "retry_hormati_klasifikasi", "berkas": INTI, "cari": CARI_RETRY,
     "ganti": GANTI_RETRY, "jumlah": 1,
     "tanda": "berhenti_tanpa_ulang"},
    {"nama": "baca_status_tahan_sementara", "berkas": INTI,
     "cari": CARI_STATUS, "ganti": GANTI_STATUS, "jumlah": 1,
     "tanda": "kep_st = klasifikasikan("},
]


def main():
    rc, isi = terapkan(TAMBALAN, "INTI")
    if rc != 0:
        return rc
    teks = isi.get(INTI, "")
    print("panjang_inti=" + str(len(teks)))
    print("punya_konfirmasi=" + str("konfirmasi_order(" in teks))
    print("punya_berhenti_tanpa_ulang=" + str("berhenti_tanpa_ulang" in teks))
    print("punya_batas_gagal_harga=" + str("BATAS_GAGAL_HARGA" in teks))
    print("sisa_klaim_ok_polos=" + str(teks.count(
        'return {"hasil": "OK", "order": order, "cid": cid,')))
    return 0


if __name__ == "__main__":
    sys.exit(main())
