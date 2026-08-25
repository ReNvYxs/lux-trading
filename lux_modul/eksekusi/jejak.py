"""Jejak audit terstruktur untuk setiap sentuhan dana di bursa.

KENAPA MODUL INI ADA. Audit 25 Agu 2026 menemukan lapisan REST
(lux_modul/eksekusi/binance_client.py) tidak punya satu baris log pun:
_permintaan mengirim, membaca, melempar galat, lalu tidak meninggalkan jejak
apa pun. Ketika Binance mengubah endpoint atau parameter - dan itu sudah
terjadi, lihat -4120 pada seluruh tipe order kondisional - satu-satunya cara
mendiagnosis adalah menebak. Modul ini menghapus tebakan itu.

BENTUK JSONL, satu baris satu peristiwa. Alasannya bukan selera: JSONL bisa
di-grep saat panik dan di-parse saat tenang, tanpa memuat seluruh berkas ke
memori.

KORELASI. Setiap permintaan mendapat id acak pendek. Baris permintaan, baris
jawaban, dan baris galat memakai korelasi yang sama, jadi satu order yang
bermasalah bisa ditarik utuh dengan satu grep - lengkap dengan parameter yang
dikirim dan balasan mentah bursa. Inilah yang menjawab enam pertanyaan wajib:
apa yang gagal, kenapa, parameter apa, jawaban apa, dampaknya, bagian mana.

ATURAN KERAS: modul ini TIDAK BOLEH melempar galat. Kegagalan mencatat tidak
boleh menjadi kegagalan bertransaksi. Semua IO dibungkus, dan kegagalan
pencatatan dihitung di `gagal_tulis` supaya tetap terlihat tanpa merusak apa pun.

REDAKSI. `signature` dan kunci apa pun yang namanya mengandung secret/key/token
dibuang sebelum ditulis, karena berkas jejak memang dimaksudkan untuk
dilampirkan ke laporan bug.

VOLUME. Jalur dana dicatat UTUH: payload order kecil dan justru bagian itulah
yang perlu dibedah. Jalur data pasar hanya dicatat ringkasannya, karena satu
jawaban exchangeInfo bisa jutaan karakter dan menenggelamkan jejak yang penting.
"""
import json
import os
import time
import uuid

PERISTIWA_PERMINTAAN = "permintaan"
PERISTIWA_JAWABAN = "jawaban"
PERISTIWA_GALAT = "galat"
PERISTIWA_KEPUTUSAN = "keputusan"
PERISTIWA_FAILSAFE = "failsafe"

ENV_DIREKTORI = "LUX_JEJAK_DIR"
ENV_AKTIF = "LUX_JEJAK_AKTIF"
ENV_STDOUT = "LUX_JEJAK_STDOUT"
DIREKTORI_BAWAAN = "jejak"

BATAS_TEKS = 1400
BATAS_INGATAN_BAWAAN = 500

# Jalur yang menyentuh dana atau posisi. Daftar ini sengaja eksplisit: kalau
# Binance menambah endpoint order baru, ia HARUS didaftarkan di sini secara
# sadar, bukan lolos diam-diam sebagai "jalur biasa".
JALUR_DANA = frozenset({
    "/fapi/v1/order",
    "/fapi/v1/order/test",
    "/fapi/v1/batchOrders",
    "/fapi/v1/allOpenOrders",
    "/fapi/v1/openOrders",
    "/fapi/v1/leverage",
    "/fapi/v1/marginType",
    "/fapi/v1/positionMargin",
    "/fapi/v2/positionRisk",
    "/fapi/v2/balance",
})

_PENANDA_RAHASIA = ("signature", "secret", "apikey", "api_key", "token",
                    "password", "passphrase")


def jalur_dana(path):
    """True bila endpoint ini bisa mengubah dana, posisi, atau order."""
    return str(path) in JALUR_DANA


def redaksi(params):
    """Buang nilai rahasia, pertahankan namanya supaya bentuk request tetap terbaca.

    Namanya dipertahankan dengan sengaja: saat Binance menolak karena parameter,
    yang perlu diketahui adalah parameter APA SAJA yang ikut dikirim, bukan
    isinya.
    """
    if not isinstance(params, dict):
        return params
    keluar = {}
    for k, v in params.items():
        nama = str(k).lower()
        if any(p in nama for p in _PENANDA_RAHASIA):
            keluar[str(k)] = "[disunting]"
        elif isinstance(v, dict):
            keluar[str(k)] = redaksi(v)
        else:
            keluar[str(k)] = v
    return keluar


def _potong(teks, batas=BATAS_TEKS):
    s = str(teks)
    if len(s) <= batas:
        return s
    return s[:batas] + "...[dipotong " + str(len(s) - batas) + " karakter]"


# Field yang menentukan saat membedah order atau posisi. Dipakai ketika
# jawaban terlalu panjang untuk disimpan utuh.
_KUNCI_PENTING = (
    "orderId", "clientOrderId", "origClientOrderId", "status", "symbol",
    "side", "type", "origType", "timeInForce", "price", "stopPrice",
    "origQty", "executedQty", "cumQuote", "avgPrice", "reduceOnly",
    "closePosition", "positionAmt", "entryPrice", "liquidationPrice",
    "leverage", "asset", "balance", "availableBalance", "code", "msg",
    "updateTime",
)


def _ringkas_besar(jawaban, teks):
    """Ringkasan TERSTRUKTUR untuk jawaban jalur dana yang terlalu panjang.

    Versi lama memotong teks JSON lalu memanggil json.loads. JSON yang
    dipotong di tengah tidak pernah sah, jadi jalur except SELALU kena dan
    hasilnya selalu repr Python. Akibatnya balance, positionRisk, dan
    openOrders tercatat sebagai teks repr, bukan data - padahal justru itu
    yang perlu dibaca saat endpoint atau parameter Binance berubah.
    """
    ringkas = {"dipangkas": True, "panjang_json": len(teks),
               "tipe": type(jawaban).__name__}
    try:
        if isinstance(jawaban, dict):
            ringkas["kunci"] = sorted(str(k) for k in jawaban)
            for k in _KUNCI_PENTING:
                if k in jawaban:
                    ringkas[k] = jawaban[k]
        elif isinstance(jawaban, (list, tuple)):
            ringkas["panjang"] = len(jawaban)
            entri = []
            for x in list(jawaban)[:8]:
                if isinstance(x, dict):
                    inti = {}
                    for k in _KUNCI_PENTING:
                        if k in x:
                            inti[k] = x[k]
                    entri.append(inti or {"kunci": sorted(str(k) for k in x)})
                else:
                    entri.append(_potong(repr(x), 120))
            ringkas["entri"] = entri
        else:
            ringkas["nilai"] = _potong(repr(jawaban), 400)
    except Exception:
        ringkas["nilai"] = "[tak terbaca]"
    return ringkas


def ringkas_jawaban(path, jawaban):
    """Jalur dana dicatat utuh; jalur lain hanya bentuknya."""
    if jalur_dana(path):
        try:
            teks = json.dumps(jawaban, default=str)
        except Exception:
            return {"tak_terserialisasi": _potong(repr(jawaban))}
        if len(teks) <= BATAS_TEKS:
            try:
                return json.loads(teks)
            except Exception:
                return {"tak_terserialisasi": _potong(teks)}
        return _ringkas_besar(jawaban, teks)
    ringkas = {"tipe": type(jawaban).__name__}
    try:
        if isinstance(jawaban, dict):
            ringkas["kunci"] = sorted(str(k) for k in list(jawaban)[:12])
            ringkas["jumlah_kunci"] = len(jawaban)
        elif isinstance(jawaban, (list, tuple)):
            ringkas["panjang"] = len(jawaban)
            if jawaban:
                ringkas["contoh_pertama"] = _potong(repr(jawaban[0]), 200)
        else:
            ringkas["nilai"] = _potong(repr(jawaban), 200)
    except Exception:
        ringkas["nilai"] = "[tak terbaca]"
    return ringkas


def _benar(teks, bawaan):
    if teks is None:
        return bawaan
    return str(teks).strip().lower() not in ("", "0", "false", "no", "off")


class PerekamJejak:
    """Penulis JSONL yang tidak pernah menjatuhkan pemanggilnya."""

    def __init__(self, direktori=None, nama_berkas=None, ke_stdout=None,
                 aktif=None, batas_ingatan=BATAS_INGATAN_BAWAAN, jam=None,
                 env=None):
        lingkungan = os.environ if env is None else env
        self.direktori = (direktori if direktori is not None
                          else lingkungan.get(ENV_DIREKTORI) or DIREKTORI_BAWAAN)
        self.aktif = _benar(lingkungan.get(ENV_AKTIF), True) if aktif is None else bool(aktif)
        self.ke_stdout = (_benar(lingkungan.get(ENV_STDOUT), False)
                          if ke_stdout is None else bool(ke_stdout))
        self._jam = jam or time.time
        self._nama_berkas = nama_berkas
        self.batas_ingatan = int(batas_ingatan)
        self.ingatan = []
        self.jumlah = {}
        self.gagal_tulis = 0
        self.berkas_terpakai = None

    # ---------------------------------------------------------------- #
    def korelasi_baru(self):
        return uuid.uuid4().hex[:12]

    def _jalur_berkas(self):
        if self._nama_berkas:
            return os.path.join(self.direktori, self._nama_berkas)
        hari = time.strftime("%Y%m%d", time.gmtime(float(self._jam())))
        return os.path.join(self.direktori, "jejak-" + hari + ".jsonl")

    def _tulis(self, rekaman):
        baris = json.dumps(rekaman, ensure_ascii=False, default=str,
                           sort_keys=True)
        if self.ke_stdout:
            try:
                print("JEJAK " + baris)
            except Exception:
                self.gagal_tulis += 1
        if not self.direktori:
            return
        try:
            os.makedirs(self.direktori, exist_ok=True)
            jalur = self._jalur_berkas()
            fh = open(jalur, "a", encoding="utf-8")
            fh.write(baris + "\n")
            fh.close()
            self.berkas_terpakai = jalur
        except Exception:
            # Sengaja bisu. Gagal mencatat tidak boleh menggagalkan order.
            self.gagal_tulis += 1

    def catat(self, peristiwa, **rinci):
        """Satu peristiwa. Selalu mengembalikan rekamannya, tidak pernah melempar."""
        try:
            rekaman = {"t": round(float(self._jam()), 6), "peristiwa": str(peristiwa)}
            rekaman.update(rinci)
            self.jumlah[str(peristiwa)] = self.jumlah.get(str(peristiwa), 0) + 1
            self.ingatan.append(rekaman)
            if len(self.ingatan) > self.batas_ingatan:
                del self.ingatan[0:len(self.ingatan) - self.batas_ingatan]
            if self.aktif:
                self._tulis(rekaman)
            return rekaman
        except Exception:
            self.gagal_tulis += 1
            return {}

    # ---------------------------------------------------------------- #
    def catat_permintaan(self, method, path, params=None, signed=False,
                         bobot=None, korelasi=None, konteks=None):
        kor = korelasi or self.korelasi_baru()
        self.catat(PERISTIWA_PERMINTAAN, korelasi=kor, metode=str(method),
                   jalur=str(path), dana=jalur_dana(path),
                   bertanda_tangan=bool(signed), bobot=bobot,
                   parameter=redaksi(params or {}), konteks=konteks)
        return kor

    def catat_jawaban(self, korelasi, method, path, status=None, jawaban=None,
                      ms=None, konteks=None):
        self.catat(PERISTIWA_JAWABAN, korelasi=korelasi, metode=str(method),
                   jalur=str(path), dana=jalur_dana(path), status=status,
                   ms=None if ms is None else round(float(ms), 2),
                   jawaban=ringkas_jawaban(path, jawaban), konteks=konteks)

    def catat_galat(self, korelasi, method, path, kelas=None, status=None,
                    kode=None, pesan=None, jawaban=None, ms=None,
                    parameter=None, konteks=None):
        """Galat dicatat dengan parameter aslinya, bukan hanya pesannya.

        Tanpa parameter, pesan seperti -1111 'Precision is over the maximum'
        tidak bisa didiagnosis: yang menentukan adalah angka mana yang salah
        presisi, dan itu hanya ada di parameter.
        """
        self.catat(PERISTIWA_GALAT, korelasi=korelasi, metode=str(method),
                   jalur=str(path), dana=jalur_dana(path), kelas=kelas,
                   status=status, kode=kode, pesan=_potong(pesan, 400),
                   ms=None if ms is None else round(float(ms), 2),
                   parameter=redaksi(parameter or {}),
                   jawaban=None if jawaban is None else ringkas_jawaban(path, jawaban),
                   konteks=konteks)

    def catat_keputusan(self, keputusan, alasan=None, korelasi=None, **rinci):
        """Keputusan mesin, bukan peristiwa jaringan. Contoh: retry, menyerah,
        fail-safe, tolak ukuran. Inilah yang menjelaskan MENGAPA mesin bertindak.
        """
        self.catat(PERISTIWA_KEPUTUSAN, korelasi=korelasi,
                   keputusan=str(keputusan), alasan=alasan, **rinci)

    def catat_failsafe(self, pemicu, tindakan, berhasil=None, **rinci):
        self.catat(PERISTIWA_FAILSAFE, pemicu=str(pemicu),
                   tindakan=str(tindakan), berhasil=berhasil, **rinci)

    # ---------------------------------------------------------------- #
    def terakhir(self, n=20, peristiwa=None):
        baris = self.ingatan
        if peristiwa is not None:
            baris = [r for r in baris if r.get("peristiwa") == peristiwa]
        return baris[-int(n):]

    def cari_korelasi(self, korelasi):
        return [r for r in self.ingatan if r.get("korelasi") == korelasi]

    def ringkas(self):
        return {"jumlah": dict(self.jumlah), "gagal_tulis": self.gagal_tulis,
                "berkas": self.berkas_terpakai, "aktif": self.aktif,
                "di_ingatan": len(self.ingatan)}


_PEREKAM = None


def perekam():
    """Perekam bersama satu proses. Dibuat saat pertama dipakai."""
    global _PEREKAM
    if _PEREKAM is None:
        _PEREKAM = PerekamJejak()
    return _PEREKAM


def pasang_perekam(p):
    """Ganti perekam global. Dipakai uji dan runner yang ingin berkas sendiri."""
    global _PEREKAM
    lama = _PEREKAM
    _PEREKAM = p
    return lama


def perekam_senyap():
    """Perekam tanpa berkas dan tanpa stdout, tetap mengingat di memori.

    Dipakai unit test: jejak tetap bisa diperiksa, tetapi suite tidak
    meninggalkan berkas di pohon kerja.
    """
    return PerekamJejak(direktori="", ke_stdout=False, aktif=True, env={})
