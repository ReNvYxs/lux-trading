"""Kepemilikan posisi: memisahkan posisi milik mesin dari posisi manual user.

KENAPA MODUL INI ADA. Binance USDs-M pada mode satu arah MENJUMLAHKAN posisi
per simbol. Bursa tidak menyimpan siapa yang membuka: yang ada hanya
clientOrderId pada order, dan itu ikut hilang begitu order selesai. Jadi
kepemilikan posisi tidak bisa dibaca dari bursa. Ia harus dicatat oleh mesin
lalu diverifikasi ulang terhadap bursa setiap siklus.

ATURAN KERAS. Bila kepemilikan tidak bisa DIBUKTIKAN milik mesin, mesin tidak
menyentuh apa pun: tidak menutup, tidak mengubah, tidak membatalkan. Diam jauh
lebih aman daripada menutup posisi manual user.

ARAH KESALAHAN YANG DIPILIH SECARA SADAR. Kalau buku hilang (berkas keadaan
terhapus), posisi mesin akan tampak seperti posisi user. Mesin akan
membiarkannya lalu melapor, bukan menebak lalu menutup. Kesalahan ke arah
sebaliknya bisa melenyapkan posisi user.

BAHAYA YANG DITEMUKAN AUDIT. Endpoint /fapi/v1/allOpenOrders membatalkan
SELURUH order terbuka pada simbol, termasuk order manual user. Selama
kepemilikan diberlakukan, endpoint itu tidak boleh dipakai bila ada satu saja
order milik user. Lihat boleh_batal_semua().
"""
import json
import os
import time

from .jejak import perekam

AWALAN_MESIN_BAWAAN = ("lx",)
ENV_AWALAN = "LUX_CID_AWALAN"
ENV_BUKU = "LUX_BUKU_POSISI"
BUKU_BAWAAN = "keadaan/buku_posisi.json"

MILIK_MESIN = "mesin"
MILIK_USER = "user"
MILIK_CAMPUR = "campuran"
MILIK_KOSONG = "kosong"

UTUH = "utuh"
DIKURANGI_USER = "dikurangi_user"
DITAMBAH_USER = "ditambah_user"
DITUTUP_USER = "ditutup_user"
ARAH_BERUBAH_USER = "arah_berubah_user"
PROTEKSI_HILANG_USER = "proteksi_dihapus_user"
BUKU_HILANG = "buku_hilang"

TOLERANSI_QTY = 1e-9
TOLERANSI_RELATIF = 1e-6


class PosisiBukanMilikMesin(Exception):
    """Fail-safe: mesin menolak menyentuh posisi yang bukan miliknya.

    Membawa laporan enam fakta wajib: proses apa, penyebab, parameter,
    jawaban bursa, dampak, dan bagian mana yang perlu diperbaiki.
    """

    def __init__(self, laporan):
        self.laporan = dict(laporan or {})
        Exception.__init__(self, str(self.laporan.get("penyebab")
                                     or "posisi bukan milik mesin"))


def awalan_mesin(env=None):
    """Awalan clientOrderId yang menandai order buatan mesin.

    Bawaannya 'lx': buat_cid() memakai 'lx'+sha1 dan ice_breaker memakai 'lxs'.
    Bisa ditambah lewat LUX_CID_AWALAN (dipisah koma) untuk akun yang berbagi
    API key dengan bot lain.
    """
    lingkungan = os.environ if env is None else env
    teks = str(lingkungan.get(ENV_AWALAN) or "").strip()
    if not teks:
        return AWALAN_MESIN_BAWAAN
    bagian = tuple(x.strip() for x in teks.split(",") if x.strip())
    return bagian or AWALAN_MESIN_BAWAAN


def cid_mesin(cid, awalan=None):
    """True hanya bila cid jelas buatan mesin. Kosong berarti BUKAN milik mesin."""
    if cid is None:
        return False
    s = str(cid).strip()
    if not s:
        return False
    for a in (awalan or awalan_mesin()):
        if a and s.startswith(a):
            return True
    return False


def cid_dari_order(order):
    if not isinstance(order, dict):
        return None if order is None else str(order)
    for k in ("clientOrderId", "origClientOrderId", "newClientOrderId"):
        nilai = order.get(k)
        if nilai:
            return str(nilai)
    return None


def pemilik_order(order, awalan=None):
    """Kepemilikan satu order. Order UI Binance memakai cid seperti 'web_...'."""
    return MILIK_MESIN if cid_mesin(cid_dari_order(order), awalan) else MILIK_USER


def pisahkan_order(daftar_order, awalan=None):
    """Pisahkan order terbuka menjadi milik mesin dan milik user."""
    mesin, user = [], []
    for o in (daftar_order or []):
        (mesin if pemilik_order(o, awalan) == MILIK_MESIN else user).append(o)
    return {"mesin": mesin, "user": user,
            "jumlah_mesin": len(mesin), "jumlah_user": len(user)}


def _f(x, bawaan=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return bawaan


def arah_dari_qty(qty):
    q = _f(qty)
    if q > TOLERANSI_QTY:
        return "LONG"
    if q < -TOLERANSI_QTY:
        return "SHORT"
    return None


def qty_posisi(posisi):
    """Ambil positionAmt dari satu baris positionRisk, apa pun bentuknya."""
    if posisi is None:
        return 0.0
    if isinstance(posisi, dict):
        for k in ("positionAmt", "positionAmount", "qty"):
            if k in posisi:
                return _f(posisi.get(k))
        return 0.0
    return _f(posisi)


class BukuPosisi:
    """Buku besar posisi milik mesin. Tahan restart, tidak pernah melempar.

    Ditulis dengan tulis-lalu-ganti (os.replace) supaya berkas tidak pernah
    setengah tertulis kalau proses mati di tengah penyimpanan.
    """

    def __init__(self, jalur=None, env=None, jam=None):
        lingkungan = os.environ if env is None else env
        self.jalur = (jalur if jalur is not None
                      else (lingkungan.get(ENV_BUKU) or BUKU_BAWAAN))
        self._jam = jam or time.time
        self.gagal_tulis = 0
        self.gagal_baca = 0
        self.entri = {}
        self.muat()

    # ----------------------------------------------------------------- #
    def muat(self):
        if not self.jalur:
            return self.entri
        try:
            fh = open(self.jalur, "r", encoding="utf-8")
            isi = json.load(fh)
            fh.close()
            data = isi.get("entri") if isinstance(isi, dict) else None
            if isinstance(data, dict):
                self.entri = {str(k): dict(v) for k, v in data.items()
                              if isinstance(v, dict)}
        except FileNotFoundError:
            pass
        except Exception:
            self.gagal_baca += 1
        return self.entri

    def simpan(self):
        if not self.jalur:
            return False
        try:
            direktori = os.path.dirname(self.jalur)
            if direktori:
                os.makedirs(direktori, exist_ok=True)
            sementara = self.jalur + ".tmp"
            fh = open(sementara, "w", encoding="utf-8")
            json.dump({"versi": 1, "diperbarui": round(float(self._jam()), 3),
                       "entri": self.entri}, fh, ensure_ascii=False,
                      default=str, sort_keys=True)
            fh.close()
            os.replace(sementara, self.jalur)
            return True
        except Exception:
            self.gagal_tulis += 1
            return False

    # ----------------------------------------------------------------- #
    def ambil(self, simbol):
        e = self.entri.get(str(simbol))
        return dict(e) if isinstance(e, dict) else None

    def daftar(self):
        return {k: dict(v) for k, v in self.entri.items()}

    def milik_mesin(self, simbol):
        e = self.ambil(simbol)
        return bool(e) and not e.get("ditutup")

    def catat_pembukaan(self, simbol, arah, qty, harga=None, cid=None,
                        order_id=None, **rinci):
        """Dipanggil SETELAH bursa mengonfirmasi entry, bukan sebelum."""
        e = {"simbol": str(simbol), "arah": str(arah),
             "qty": abs(_f(qty)), "qty_awal": abs(_f(qty)),
             "harga_masuk": None if harga is None else _f(harga),
             "cid_entry": None if cid is None else str(cid),
             "order_id_entry": order_id, "dibuka_pada": round(float(self._jam()), 3),
             "ditutup": False, "cid_sl": None, "cid_tp": None,
             "order_sl": None, "order_tp": None, "revisi": 0}
        e.update(rinci)
        self.entri[str(simbol)] = e
        self.simpan()
        return dict(e)

    def catat_proteksi(self, simbol, cid_sl=None, cid_tp=None, order_sl=None,
                       order_tp=None):
        e = self.entri.get(str(simbol))
        if not isinstance(e, dict):
            return None
        if cid_sl is not None:
            e["cid_sl"] = str(cid_sl)
        if cid_tp is not None:
            e["cid_tp"] = str(cid_tp)
        if order_sl is not None:
            e["order_sl"] = order_sl
        if order_tp is not None:
            e["order_tp"] = order_tp
        e["revisi"] = int(e.get("revisi") or 0) + 1
        self.simpan()
        return dict(e)

    def selaraskan_qty(self, simbol, qty_bursa, alasan="selaras_bursa"):
        """Bursa adalah sumber kebenaran ukuran. Kepemilikan TIDAK berubah."""
        e = self.entri.get(str(simbol))
        if not isinstance(e, dict):
            return None
        e["qty"] = abs(_f(qty_bursa))
        e["alasan_selaras"] = str(alasan)
        e["revisi"] = int(e.get("revisi") or 0) + 1
        self.simpan()
        return dict(e)

    def tutup(self, simbol, alasan="ditutup"):
        e = self.entri.pop(str(simbol), None)
        if isinstance(e, dict):
            e["ditutup"] = True
            e["alasan_tutup"] = str(alasan)
            e["ditutup_pada"] = round(float(self._jam()), 3)
        self.simpan()
        return e


def klasifikasi_posisi(simbol, posisi, catatan=None, order_terbuka=None,
                       awalan=None):
    """Tentukan pemilik satu posisi dan apakah mesin boleh mengelolanya.

    Kepemilikan dikunci pada catatan buku, BUKAN pada ukuran posisi. Itu yang
    membuat identitas tetap konsisten walau user memodifikasi SL/TP atau
    menutup sebagian: ukuran berubah, pemilik tetap.
    """
    awal = awalan or awalan_mesin()
    qty = qty_posisi(posisi)
    arah = arah_dari_qty(qty)
    pecah = pisahkan_order(order_terbuka, awal)
    hasil = {"simbol": str(simbol), "qty_bursa": qty, "arah_bursa": arah,
             "qty_tercatat": None, "arah_tercatat": None, "selisih_qty": None,
             "order_mesin_terlihat": pecah["jumlah_mesin"],
             "order_user_terlihat": pecah["jumlah_user"],
             "proteksi_hilang": False, "buku_hilang": False,
             "perubahan_user": UTUH, "perlu_tindakan": None}

    if arah is None:
        hasil["pemilik"] = MILIK_KOSONG
        hasil["boleh_dikelola_mesin"] = True
        if catatan:
            hasil["perubahan_user"] = DITUTUP_USER
            hasil["perlu_tindakan"] = "tutup_buku_dan_batalkan_proteksi_mesin"
            hasil["alasan"] = ("buku mencatat posisi tetapi bursa kosong: "
                              "posisi sudah tertutup (user, SL/TP, atau likuidasi)")
        else:
            hasil["alasan"] = "tidak ada posisi pada simbol ini"
        return hasil

    if not catatan:
        ada_cid_mesin = pecah["jumlah_mesin"] > 0
        hasil["buku_hilang"] = ada_cid_mesin
        hasil["pemilik"] = MILIK_CAMPUR if ada_cid_mesin else MILIK_USER
        hasil["boleh_dikelola_mesin"] = False
        if ada_cid_mesin:
            hasil["perubahan_user"] = BUKU_HILANG
            hasil["perlu_tindakan"] = "rekonsiliasi_manual"
            hasil["alasan"] = ("posisi tanpa catatan buku tetapi ada order ber-cid "
                              "mesin di simbol ini: buku kemungkinan hilang, "
                              "kepemilikan tidak bisa dibuktikan")
        else:
            hasil["alasan"] = ("posisi tidak ada di buku mesin: dianggap dibuka "
                              "manual oleh user dan tidak boleh disentuh")
        return hasil

    qty_catat = abs(_f(catatan.get("qty")))
    arah_catat = str(catatan.get("arah") or "").upper() or None
    hasil["qty_tercatat"] = qty_catat
    hasil["arah_tercatat"] = arah_catat
    hasil["selisih_qty"] = round(abs(qty) - qty_catat, 12)

    if arah_catat and arah != arah_catat:
        hasil["pemilik"] = MILIK_CAMPUR
        hasil["boleh_dikelola_mesin"] = False
        hasil["perubahan_user"] = ARAH_BERUBAH_USER
        hasil["perlu_tindakan"] = "rekonsiliasi_manual"
        hasil["alasan"] = ("arah posisi di bursa " + str(arah) + " berbeda dari "
                          "buku " + str(arah_catat) + ": posisi sudah dibalik "
                          "di luar mesin")
        return hasil

    batas = qty_catat * TOLERANSI_RELATIF + TOLERANSI_QTY
    ids_terbuka = set()
    for o in (order_terbuka or []):
        if isinstance(o, dict) and o.get("orderId") is not None:
            ids_terbuka.add(str(o.get("orderId")))
    for kunci in ("order_sl", "order_tp"):
        oid = catatan.get(kunci)
        if oid is not None and str(oid) not in ids_terbuka:
            hasil["proteksi_hilang"] = True

    if abs(qty) > qty_catat + batas:
        hasil["pemilik"] = MILIK_CAMPUR
        hasil["boleh_dikelola_mesin"] = False
        hasil["perubahan_user"] = DITAMBAH_USER
        hasil["perlu_tindakan"] = "rekonsiliasi_manual"
        hasil["alasan"] = ("posisi bursa lebih besar dari catatan mesin: mode "
                          "satu arah menggabungkan tambahan manual user ke "
                          "posisi yang sama, jadi ukurannya tidak lagi murni "
                          "milik mesin")
        return hasil

    hasil["pemilik"] = MILIK_MESIN
    hasil["boleh_dikelola_mesin"] = True
    if abs(qty) < qty_catat - batas:
        hasil["perubahan_user"] = DIKURANGI_USER
        hasil["perlu_tindakan"] = "selaraskan_qty_dan_perbarui_proteksi"
        hasil["alasan"] = ("posisi milik mesin tetapi ukurannya berkurang di luar "
                          "mesin: user menutup sebagian. Kepemilikan tetap, "
                          "ukuran wajib diselaraskan ke bursa")
    elif hasil["proteksi_hilang"]:
        hasil["perubahan_user"] = PROTEKSI_HILANG_USER
        hasil["perlu_tindakan"] = "pasang_ulang_proteksi"
        hasil["alasan"] = ("posisi milik mesin masih ada tetapi order proteksi "
                          "yang dicatat buku tidak ada lagi di bursa: "
                          "kemungkinan dibatalkan user")
    else:
        hasil["alasan"] = "posisi cocok dengan buku mesin"
    return hasil


class PenjagaKepemilikan:
    """Gerbang tunggal: setiap tindakan yang menyentuh posisi lewat sini."""

    def __init__(self, buku=None, awalan=None, rekam=None):
        self.buku = buku if buku is not None else BukuPosisi()
        self.awalan = awalan or awalan_mesin()
        self._rekam = rekam

    def _jejak(self):
        return self._rekam if self._rekam is not None else perekam()

    def periksa(self, simbol, posisi, order_terbuka=None):
        hasil = klasifikasi_posisi(simbol, posisi, self.buku.ambil(simbol),
                                   order_terbuka, self.awalan)
        try:
            self._jejak().catat_keputusan(
                "kepemilikan", alasan=hasil.get("alasan"), simbol=str(simbol),
                pemilik=hasil.get("pemilik"),
                boleh_dikelola_mesin=hasil.get("boleh_dikelola_mesin"),
                perubahan_user=hasil.get("perubahan_user"),
                qty_bursa=hasil.get("qty_bursa"),
                qty_tercatat=hasil.get("qty_tercatat"),
                perlu_tindakan=hasil.get("perlu_tindakan"))
        except Exception:
            pass
        return hasil

    def laporan_gagal(self, tindakan, hasil, parameter=None, jawaban=None):
        """Enam fakta wajib untuk setiap penolakan."""
        return {"proses": str(tindakan), "simbol": hasil.get("simbol"),
                "penyebab": hasil.get("alasan"),
                "pemilik": hasil.get("pemilik"),
                "perubahan_user": hasil.get("perubahan_user"),
                "parameter": parameter or {"simbol": hasil.get("simbol"),
                                           "tindakan": str(tindakan)},
                "jawaban_api": jawaban if jawaban is not None else {
                    "positionAmt": hasil.get("qty_bursa"),
                    "order_user_terlihat": hasil.get("order_user_terlihat")},
                "dampak": ("tindakan dibatalkan; posisi dan order tidak disentuh "
                           "sama sekali sehingga posisi user tetap utuh"),
                "perlu_diperbaiki": ("PenjagaKepemilikan: "
                                     + str(hasil.get("perlu_tindakan")
                                           or "rekonsiliasi_manual"))}

    def pastikan_boleh_kelola(self, simbol, posisi, order_terbuka=None,
                              tindakan="kelola"):
        hasil = self.periksa(simbol, posisi, order_terbuka)
        if hasil.get("boleh_dikelola_mesin"):
            return hasil
        laporan = self.laporan_gagal(tindakan, hasil)
        try:
            self._jejak().catat_failsafe("kepemilikan_bukan_mesin",
                                         "tolak_" + str(tindakan),
                                         berhasil=False, **laporan)
        except Exception:
            pass
        raise PosisiBukanMilikMesin(laporan)

    def boleh_batalkan_order(self, order):
        """Mesin hanya boleh membatalkan order yang ia sendiri buat."""
        return pemilik_order(order, self.awalan) == MILIK_MESIN

    def boleh_batal_semua(self, simbol, order_terbuka):
        """allOpenOrders membatalkan order user juga. Izinkan hanya bila bersih."""
        pecah = pisahkan_order(order_terbuka, self.awalan)
        boleh = pecah["jumlah_user"] == 0
        if not boleh:
            try:
                self._jejak().catat_keputusan(
                    "tolak_batal_semua",
                    alasan=("ada " + str(pecah["jumlah_user"]) + " order milik "
                            "user pada simbol ini; batalkan satu per satu "
                            "dengan orderId milik mesin"),
                    simbol=str(simbol), jumlah_user=pecah["jumlah_user"],
                    jumlah_mesin=pecah["jumlah_mesin"])
            except Exception:
                pass
        return boleh

    def order_mesin(self, order_terbuka):
        return pisahkan_order(order_terbuka, self.awalan)["mesin"]
