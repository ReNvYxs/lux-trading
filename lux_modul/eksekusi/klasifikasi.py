"""Taksonomi galat bursa dan konfirmasi order.

MODUL INI MENJAWAB SATU PERTANYAAN: boleh atau tidak kita menyebut sebuah
perintah ke bursa sebagai berhasil, gagal, atau belum jelas.

Tiga keadaan, bukan dua. Inilah inti seluruh modul ini. Kode lama hanya kenal
berhasil dan gagal, sehingga timeout dipetakan ke gagal - padahal justru itu
keadaan paling berbahaya.

RUJUKAN yang menentukan rancangan ini:

1. Dokumentasi resmi Binance USD-M Futures, bagian General Info, tentang HTTP
   503 varian A: pesan "Unknown error, please check your request or try again
   later." berarti "Request accepted but no response before timeout; execution
   MAY HAVE SUCCEEDED" dengan status eksekusi UNKNOWN. Jadi bursa sendiri
   menyatakan hasilnya tidak diketahui. Menyebutnya gagal adalah kebohongan.
   Sumber: developers.binance.com, derivatives-trading-usds-futures/general-info

2. nautilus_trader mendokumentasikan kebijakan produksi yang sama: setiap
   perintah submit, modify, dan cancel dikirim SEKALI; tidak pernah diulang
   buta setelah timeout, kegagalan jaringan, atau jawaban unknown-status,
   karena permintaan pertama mungkin sudah mencapai matching engine. Hasil
   transport yang ambigu dibiarkan inflight dan diselesaikan lewat rekonsiliasi,
   dan adaptor TIDAK memancarkan penolakan palsu selama hasil di bursa belum
   diketahui. Sumber: github.com/nautechsystems/nautilus_trader,
   docs/integrations/binance.md

3. -4120 pada seluruh tipe order kondisional BUKAN keanehan testnet kita.
   Freqtrade mencatat kegagalan identik sejak pembaruan API Binance 9 Des 2025
   dan menyebutnya migrasi wajib ke Algo Order API.
   Sumber: github.com/freqtrade/freqtrade/issues/12610
   Konsekuensinya untuk kita: p09 membuktikan endpoint Algo TIDAK ADA di host
   testnet, jadi di testnet SL perangkat lunak adalah satu-satunya jalan. Di
   mainnet endpoint itu mungkin ada. Saklar `otomatis` sudah memutuskan ini dari
   jawaban bursa, bukan dari asumsi, dan gagal ke sisi aman.

4. -2010 NEW_ORDER_REJECTED adalah keranjang serbaguna: alasan sebenarnya ada di
   field msg, bukan di kode. Karena itu jejak.py mencatat msg utuh untuk jalur
   dana - tanpa itu -2010 tidak bisa didiagnosis sama sekali.

5. -1008 dikecualikan untuk order reduce-only, close-position, dan cancel
   menurut dokumentasi Binance. Artinya jalur penyelamatan posisi tidak ikut
   tercekik saat sistem sedang membatasi - fakta yang dipakai fail-safe kita.
"""

KELAS_PERMANEN = "permanen"
KELAS_SEMENTARA = "sementara"
KELAS_LAJU = "laju"
KELAS_WAKTU = "waktu"
KELAS_TAK_DIKETAHUI = "tak_diketahui"
KELAS_DUPLIKAT = "duplikat"
KELAS_TIDAK_ADA = "tidak_ada"
KELAS_KREDENSIAL = "kredensial"

METODE_TULIS = ("POST", "PUT", "DELETE")

# Ditolak permanen: mengulang hanya menghasilkan galat yang sama. Tanda (p..)
# artinya terbukti sendiri di probe kita, (dok) artinya dari dokumentasi.
KODE_PERMANEN = {
    -1022: "tanda tangan tidak sah (dok)",
    -1100: "karakter ilegal di parameter (dok)",
    -1101: "parameter terlalu banyak (dok)",
    -1102: "parameter wajib kosong atau salah bentuk (p07)",
    -1103: "parameter tidak dikenal (dok)",
    -1104: "tidak semua parameter dibaca (dok) - payload memuat kunci asing",
    -1105: "parameter kosong (dok)",
    -1106: "parameter tidak diperlukan dikirim (dok)",
    -1111: "presisi melebihi batas aset (p07)",
    -1116: "tipe order tidak sah (p02)",
    -1117: "sisi order tidak sah (dok)",
    -1121: "simbol tidak sah (p07)",
    -1130: "nilai parameter tidak didukung (dok)",
    -2010: "order ditolak - alasan sebenarnya ada di msg (dok)",
    -2018: "saldo tidak cukup (dok)",
    -2019: "margin tidak cukup (dok)",
    -2020: "tidak bisa diisi pada batas harga ini (dok)",
    -2021: "order akan langsung tersentuh (dok)",
    -2022: "reduceOnly ditolak (p07)",
    -2023: "akun sedang dilikuidasi (dok)",
    -2024: "posisi tidak cukup untuk reduceOnly (dok)",
    -2025: "jumlah order terbuka maksimum terlampaui (dok)",
    -2026: "tipe order reduceOnly tidak didukung (dok)",
    -2027: "melebihi rasio leverage maksimum (dok)",
    -2028: "di bawah rasio leverage minimum (dok)",
    -4003: "kuantitas kurang dari nol atau salah presisi (p07)",
    -4014: "harga tidak sesuai kelipatan tick (p07)",
    -4120: "tipe order tidak didukung endpoint ini (p02/p03/p08 + freqtrade)",
    -4131: "harga terbaik lawan melanggar filter PERCENT_PRICE (dok)",
    -4164: "notional order di bawah minimum (dok)",
    -5022: "order post-only GTX ditolak karena tidak bisa jadi maker (p08)",
}

# Boleh diulang: gangguan sesaat di sisi bursa, dan permintaan hampir pasti
# TIDAK diterima. Untuk jalur tulis, keraguan tetap dimenangkan oleh
# rekonsiliasi - lihat `klasifikasikan`.
KODE_SEMENTARA = {
    -1001: "koneksi terputus di tengah permintaan (dok)",
    -1008: "dicekik proteksi tingkat sistem; reduce-only dan cancel dikecualikan (dok)",
    -1016: "layanan sedang dimatikan (dok)",
}

# Hasil TIDAK DIKETAHUI. Ini bukan gagal. Wajib rekonsiliasi, dilarang diulang
# buta pada jalur tulis.
KODE_TAK_DIKETAHUI = {
    -1000: "galat tak dikenal di sisi bursa; status eksekusi tidak diketahui (dok)",
    -1006: "jawaban tak terduga dari message bus; status eksekusi tidak diketahui (dok)",
    -1007: "timeout menunggu server backend; status kirim DAN eksekusi tidak diketahui (dok)",
}

KODE_LAJU = {
    -1003: "terlalu banyak permintaan; IP bisa dibanned (p13)",
    -1015: "terlalu banyak order (dok)",
}

KODE_KREDENSIAL = {
    -1002: "tidak terotorisasi (dok)",
    -2014: "format kunci API salah (dok)",
    -2015: "kunci ditolak: IP tidak diizinkan atau kunci mati (dok)",
}

KODE_DUPLIKAT = -4116
KODE_ORDER_TIDAK_ADA = -2013
KODE_BATAL_DITOLAK = -2011
KODE_WAKTU = -1021

STATUS_LAJU = (418, 429)
STATUS_TAK_DIKETAHUI = (503,)

# Status order menurut Binance USD-M. Status di luar daftar ini TIDAK boleh
# dianggap sukses: bila Binance menambah status baru, mesin harus berhenti dan
# bertanya, bukan menebak.
STATUS_HIDUP = frozenset({"NEW", "PARTIALLY_FILLED"})
STATUS_SELESAI = frozenset({"FILLED", "CANCELED", "REJECTED", "EXPIRED",
                            "EXPIRED_IN_MATCH"})
STATUS_DIKENAL = STATUS_HIDUP | STATUS_SELESAI | frozenset(
    {"NEW_INSURANCE", "NEW_ADL"})


class GagalKonfirmasi(Exception):
    """Bursa belum mengonfirmasi. Pemanggil DILARANG melanjutkan."""


class Keputusan:
    """Hasil klasifikasi satu galat, beserta apa yang boleh dilakukan."""

    def __init__(self, kelas, kode=None, status=None, pesan="", alasan="",
                 boleh_ulang=False, wajib_rekonsiliasi=False,
                 wajib_sinkron_waktu=False, jeda_ms=0):
        self.kelas = kelas
        self.kode = kode
        self.status = status
        self.pesan = pesan
        self.alasan = alasan
        self.boleh_ulang = bool(boleh_ulang)
        self.wajib_rekonsiliasi = bool(wajib_rekonsiliasi)
        self.wajib_sinkron_waktu = bool(wajib_sinkron_waktu)
        self.jeda_ms = int(jeda_ms)

    def ringkas(self):
        return {"kelas": self.kelas, "kode": self.kode, "status": self.status,
                "pesan": str(self.pesan)[:300], "alasan": self.alasan,
                "boleh_ulang": self.boleh_ulang,
                "wajib_rekonsiliasi": self.wajib_rekonsiliasi,
                "wajib_sinkron_waktu": self.wajib_sinkron_waktu,
                "jeda_ms": self.jeda_ms}

    def __repr__(self):
        return "Keputusan(" + repr(self.ringkas()) + ")"


def klasifikasikan(exc, jalur=None, metode="GET", dana=None):
    """Petakan satu galat ke keputusan yang boleh diambil.

    `dana` menandai apakah endpoint ini menyentuh dana atau posisi. Bila None,
    disimpulkan dari jejak.jalur_dana.

    ATURAN BAWAAN YANG MENENTUKAN: kode yang TIDAK ADA di tabel mana pun, pada
    jalur TULIS ke endpoint dana, diklasifikasikan TAK_DIKETAHUI - bukan
    permanen, bukan sementara. Ini disengaja. Tabel ini pasti akan ketinggalan
    zaman; yang tidak boleh ketinggalan zaman adalah sikap amannya. Kode baru
    yang belum kita kenal tidak boleh dianggap gagal (bisa jadi order sudah
    masuk) dan tidak boleh diulang (bisa jadi menggandakan order).
    """
    if dana is None:
        try:
            from .jejak import jalur_dana
            dana = jalur_dana(jalur) if jalur else False
        except Exception:
            dana = False
    tulis = str(metode).upper() in METODE_TULIS
    tulis_dana = bool(tulis and dana)

    kode = getattr(exc, "kode", None)
    status = getattr(exc, "status", None)
    pesan = getattr(exc, "pesan", None) or str(exc)

    if status in STATUS_LAJU or kode in KODE_LAJU:
        return Keputusan(
            KELAS_LAJU, kode, status, pesan,
            alasan=KODE_LAJU.get(kode, "HTTP " + str(status) + " pembatasan laju"),
            boleh_ulang=False, wajib_rekonsiliasi=tulis_dana, jeda_ms=60_000)

    if kode in KODE_KREDENSIAL:
        return Keputusan(KELAS_KREDENSIAL, kode, status, pesan,
                         alasan=KODE_KREDENSIAL[kode], boleh_ulang=False)

    if kode == KODE_WAKTU:
        # Bisa disembuhkan, tapi HANYA setelah offset waktu disinkronkan ulang.
        # Mengulang tanpa sinkron akan gagal dengan galat yang sama persis.
        return Keputusan(KELAS_WAKTU, kode, status, pesan,
                         alasan="timestamp di luar recvWindow (dok)",
                         boleh_ulang=True, wajib_sinkron_waktu=True,
                         wajib_rekonsiliasi=tulis_dana)

    if kode == KODE_DUPLIKAT:
        return Keputusan(KELAS_DUPLIKAT, kode, status, pesan,
                         alasan="newClientOrderId sudah dipakai (p07): "
                                "percobaan sebelumnya SUDAH sampai",
                         boleh_ulang=False, wajib_rekonsiliasi=True)

    if kode in (KODE_ORDER_TIDAK_ADA, KODE_BATAL_DITOLAK):
        return Keputusan(KELAS_TIDAK_ADA, kode, status, pesan,
                         alasan="order tidak ditemukan matching engine; bisa "
                                "belum terlihat, bisa sudah selesai (p10/dok)",
                         boleh_ulang=False, wajib_rekonsiliasi=True)

    if kode in KODE_TAK_DIKETAHUI or status in STATUS_TAK_DIKETAHUI:
        return Keputusan(KELAS_TAK_DIKETAHUI, kode, status, pesan,
                         alasan=KODE_TAK_DIKETAHUI.get(
                             kode, "HTTP 503: permintaan diterima tanpa "
                                   "jawaban; eksekusi mungkin BERHASIL (dok)"),
                         boleh_ulang=False, wajib_rekonsiliasi=True)

    if kode in KODE_PERMANEN:
        return Keputusan(KELAS_PERMANEN, kode, status, pesan,
                         alasan=KODE_PERMANEN[kode], boleh_ulang=False,
                         wajib_rekonsiliasi=False)

    if kode in KODE_SEMENTARA:
        return Keputusan(KELAS_SEMENTARA, kode, status, pesan,
                         alasan=KODE_SEMENTARA[kode],
                         boleh_ulang=not tulis_dana,
                         wajib_rekonsiliasi=tulis_dana, jeda_ms=500)

    if kode is None and status is None:
        # Tidak ada jawaban sama sekali: timeout soket, koneksi direset, DNS.
        # Untuk jalur tulis dana inilah keadaan paling berbahaya - order bisa
        # sudah masuk. Untuk jalur baca, sekadar ulangi.
        if tulis_dana:
            return Keputusan(KELAS_TAK_DIKETAHUI, kode, status, pesan,
                             alasan="tidak ada jawaban pada jalur tulis dana; "
                                    "order mungkin SUDAH sampai ke bursa",
                             boleh_ulang=False, wajib_rekonsiliasi=True)
        return Keputusan(KELAS_SEMENTARA, kode, status, pesan,
                         alasan="kegagalan jaringan pada jalur baca",
                         boleh_ulang=True, jeda_ms=500)

    if tulis_dana:
        return Keputusan(KELAS_TAK_DIKETAHUI, kode, status, pesan,
                         alasan="kode belum dikenal pada jalur tulis dana; "
                                "ditahan ke sisi aman dan direkonsiliasi",
                         boleh_ulang=False, wajib_rekonsiliasi=True)
    return Keputusan(KELAS_SEMENTARA, kode, status, pesan,
                     alasan="kode belum dikenal pada jalur baca",
                     boleh_ulang=True, jeda_ms=500)


def konfirmasi_order(jawaban, simbol=None, sisi=None, cid=None):
    """Pastikan jawaban ini benar-benar konfirmasi order dari bursa.

    Dibuat karena audit menemukan dua tempat yang menyebut order berhasil tanpa
    memeriksa apa pun: PengirimOrder.kirim mengembalikan hasil OK untuk jawaban
    apa saja termasuk dict kosong, dan IceBreakerExecutor menambahkan qty_terisi
    dari qty yang DIMINTA tanpa melihat jawaban sama sekali. Klien REST juga
    mengembalikan {} untuk badan jawaban kosong, sehingga {} bisa mengalir jauh
    sebagai "sukses".

    Melempar GagalKonfirmasi bila tidak sah. Mengembalikan bentuk ternormalisasi
    bila sah.
    """
    if jawaban is None:
        raise GagalKonfirmasi("jawaban bursa kosong (None)")
    if not isinstance(jawaban, dict):
        raise GagalKonfirmasi(
            "jawaban bursa bukan objek: " + type(jawaban).__name__)
    if not jawaban:
        raise GagalKonfirmasi(
            "jawaban bursa dict kosong - badan jawaban kosong bukan konfirmasi")

    oid = jawaban.get("orderId")
    cid_jawab = jawaban.get("clientOrderId")
    if oid in (None, "", 0) and not cid_jawab:
        raise GagalKonfirmasi(
            "jawaban tanpa orderId maupun clientOrderId: " + repr(jawaban)[:200])

    status = jawaban.get("status")
    if status is None:
        raise GagalKonfirmasi(
            "jawaban tanpa field status; tidak bisa disebut terkonfirmasi")
    status = str(status).upper()
    if status not in STATUS_DIKENAL:
        raise GagalKonfirmasi(
            "status order tidak dikenal: " + status + " - mesin berhenti, "
            "tidak menebak")

    if simbol and jawaban.get("symbol") and str(jawaban["symbol"]) != str(simbol):
        raise GagalKonfirmasi(
            "simbol jawaban " + str(jawaban.get("symbol")) +
            " tidak cocok dengan yang diminta " + str(simbol))
    if sisi and jawaban.get("side") and str(jawaban["side"]).upper() != str(sisi).upper():
        raise GagalKonfirmasi(
            "sisi jawaban " + str(jawaban.get("side")) +
            " tidak cocok dengan yang diminta " + str(sisi))
    if cid and cid_jawab and str(cid_jawab) != str(cid):
        raise GagalKonfirmasi(
            "clientOrderId jawaban " + str(cid_jawab) + " bukan milik kita " + str(cid))

    def angka(nama):
        try:
            return float(jawaban.get(nama) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    diminta = angka("origQty")
    terisi = angka("executedQty")
    return {"orderId": oid, "clientOrderId": cid_jawab, "status": status,
            "simbol": jawaban.get("symbol"), "sisi": jawaban.get("side"),
            "tipe": jawaban.get("type"), "harga_rata": angka("avgPrice"),
            "qty_diminta": diminta, "qty_terisi": terisi,
            "hidup": status in STATUS_HIDUP, "selesai": status in STATUS_SELESAI,
            "terisi_penuh": diminta > 0 and terisi >= diminta,
            "parsial": 0.0 < terisi < diminta}


def konfirmasi_batal(jawaban, simbol=None):
    """Pastikan pembatalan benar-benar dikonfirmasi bursa.

    Audit menemukan Proteksi.batalkan_proteksi menelan galat lalu membersihkan
    state lokal seolah pembatalan berhasil. Itu klaim sukses tanpa konfirmasi
    pada jalur dana, tepat yang dilarang.

    Jawaban /fapi/v1/allOpenOrders berbentuk {"code": 200, "msg": "The operation
    of cancel all open order is done."} - bentuk yang BERBEDA dari pembatalan
    satu order, jadi keduanya ditangani terpisah dan tidak saling menyamar.
    """
    if jawaban is None:
        raise GagalKonfirmasi("jawaban pembatalan kosong (None)")
    if not isinstance(jawaban, dict):
        raise GagalKonfirmasi(
            "jawaban pembatalan bukan objek: " + type(jawaban).__name__)
    kode = jawaban.get("code")
    if kode is not None and str(kode) == "200":
        return {"bentuk": "semua_order", "kode": 200,
                "pesan": jawaban.get("msg"), "terkonfirmasi": True}
    if not jawaban:
        raise GagalKonfirmasi("jawaban pembatalan dict kosong")
    status = str(jawaban.get("status") or "").upper()
    if status != "CANCELED":
        raise GagalKonfirmasi(
            "pembatalan tidak dikonfirmasi; status=" + (status or "[kosong]") +
            " jawaban=" + repr(jawaban)[:200])
    if simbol and jawaban.get("symbol") and str(jawaban["symbol"]) != str(simbol):
        raise GagalKonfirmasi(
            "simbol pembatalan tidak cocok: " + str(jawaban.get("symbol")))
    return {"bentuk": "satu_order", "orderId": jawaban.get("orderId"),
            "clientOrderId": jawaban.get("clientOrderId"),
            "status": status, "terkonfirmasi": True}
