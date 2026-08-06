"""Saklar pemilih lapisan eksekusi proteksi (TP/SL) untuk jalur live.

Tiga mode, dipilih lewat variabel lingkungan LUX_EKSEKUSI:

  otomatis (BAWAAN)
      Bursa yang sedang dipakai ditanya SEKALI, tanpa order nyata, lewat
      endpoint order/test: apakah tipe stop kondisional diterima?
        diterima  -> jalur lama (stop asli di bursa, tahan mati proses)
        -4120     -> jalur aman
        tak jelas -> jalur aman (fail-closed)
  lama
      Selalu jalur lama: STOP_MARKET + TAKE_PROFIT_MARKET closePosition.
  aman
      Selalu jalur aman: TP = LIMIT reduceOnly di bursa, SL dipantau
      perangkat lunak, dan gagal memasang proteksi berarti posisi DITUTUP.

Kenapa 'otomatis' jadi bawaan, bukan 'lama' atau 'aman'.
Bukti 6 Agu 2026 di Binance Futures Testnet, akun dan jam yang sama:
STOP_MARKET dan TAKE_PROFIT_MARKET dua-duanya dijawab
  -4120 Order type not supported for this endpoint.
Di bursa yang berperilaku begitu, jalur lama meninggalkan posisi TANPA
proteksi apa pun, sebab kegagalan hanya dicatat ke siklus.galat dan tidak
ditangani. Sebaliknya perilaku mainnet BELUM pernah diverifikasi; kalau di
sana stop diterima, memaksa jalur aman berarti membuang SL sisi bursa yang
tahan mati proses. Dua-duanya salah kalau ditebak. Maka modul ini tidak
menebak: ia bertanya ke bursa yang sedang dipakai, lalu memilih.

BATAS YANG DIAKUI JUJUR
  - Jalur aman menaruh SL di dalam proses. Kalau proses mati, SL ikut mati.
    LiveRunner memulihkan pemantauan lewat _pulihkan_proteksi_aman() pada
    siklus pertama, tetapi jendela antara proses mati dan proses hidup lagi
    tetap tidak terlindungi.
  - Bila kegagalan terjadi SEBELUM objek Proteksi sempat dibuat, fungsi ini
    tidak punya pegangan untuk menutup posisi. Kasus itu dilaporkan lewat
    kunci 'gagal' tanpa klaim bahwa posisi sudah aman.
"""
import math
import os
import time

MODE_LAMA = "lama"
MODE_AMAN = "aman"
MODE_OTOMATIS = "otomatis"
MODE_DIKENAL = (MODE_LAMA, MODE_AMAN, MODE_OTOMATIS)
MODE_BAWAAN = MODE_OTOMATIS

ENV_NAMA = "LUX_EKSEKUSI"
ENV_BATAS_JARAK = "LUX_BATAS_JARAK_PROTEKSI"

# -4120 = Order type not supported for this endpoint (terbukti di testnet).
# -1116 = Invalid orderType. Dua-duanya berarti TIPE-nya yang ditolak.
KODE_TIPE_TAK_DIDUKUNG = (-4120, -1116)

JALUR_UJI_ORDER = "/fapi/v1/order/test"
JEDA_PROBE_ULANG_DETIK = 60.0
BATAS_JARAK_BAWAAN = 0.5
JARAK_MIN_REL = 0.0001
FAKTOR_STOP_PROBE = 0.8

_probe_hasil = {}
_probe_waktu = {}


def bersihkan_cache_probe():
    """Dipakai uji, dan berguna kalau kredensial/bursa diganti saat proses hidup."""
    _probe_hasil.clear()
    _probe_waktu.clear()


def mode_eksekusi(env=None):
    sumber = os.environ if env is None else env
    nilai = str(sumber.get(ENV_NAMA, "") or "").strip().lower()
    if nilai in MODE_DIKENAL:
        return nilai
    return MODE_BAWAAN


def _kunci_klien(klien):
    """Kunci cache per BURSA, bukan per simbol: -4120 adalah sifat endpoint,
    bukan sifat pair. Testnet dan live tidak boleh berbagi kunci."""
    for nama in ("base_url", "_base_url"):
        nilai = getattr(klien, nama, None)
        if isinstance(nilai, str) and nilai:
            return nilai
    for nama in ("kredensial", "_kredensial", "kred"):
        kr = getattr(klien, nama, None)
        nilai = getattr(kr, "base_url", None)
        if isinstance(nilai, str) and nilai:
            return nilai
    return "klien:" + str(id(klien))


def _harga_stop_probe(klien, simbol):
    from .inti import SpekSimbol

    spek = SpekSimbol.dari_exchange_info(klien.exchange_info(simbol), simbol)
    harga = float(klien.harga_sekarang(simbol))
    if harga <= 0:
        raise ValueError("harga acuan tidak valid untuk probe")
    stop = harga * FAKTOR_STOP_PROBE
    tick = float(getattr(spek, "tick", 0.0) or 0.0)
    if tick > 0:
        stop = math.floor(stop / tick) * tick
    presisi = getattr(spek, "presisi_harga", None)
    try:
        presisi = int(presisi)
    except (TypeError, ValueError):
        presisi = 8
    return round(stop, max(0, presisi))


def deteksi_dukungan_stop(klien, simbol, log=None, paksa=False):
    """Tanya bursa sekali: apakah STOP_MARKET closePosition diterima?

    Memakai endpoint order/test sehingga TIDAK ada order nyata yang dibuat.
    Stop price sengaja ditaruh jauh di bawah pasar untuk sisi SELL supaya
    penolakan 'would immediately trigger' tidak mengaburkan jawaban.

    Aturan penafsiran:
      sukses                      -> tipe didukung
      kode -4120 / -1116          -> tipe TIDAK didukung
      kode Binance lain           -> tipe dikenal endpoint, yang ditolak hal
                                     lain, jadi dianggap didukung
      bukan galat Binance         -> tidak bisa disimpulkan, tidak dicache
    """
    kunci = _kunci_klien(klien)
    if not paksa and kunci in _probe_hasil:
        return {"didukung": _probe_hasil[kunci], "sumber": "cache",
                "kunci": kunci}

    sekarang = time.time()
    if not paksa:
        terakhir = _probe_waktu.get(kunci)
        if terakhir is not None and (sekarang - terakhir) < JEDA_PROBE_ULANG_DETIK:
            return {"didukung": None, "sumber": "jeda", "kunci": kunci}
    _probe_waktu[kunci] = sekarang

    hasil = {"sumber": "probe", "kunci": kunci, "simbol": simbol}
    try:
        stop = _harga_stop_probe(klien, simbol)
        params = {
            "symbol": simbol,
            "side": "SELL",
            "type": "STOP_MARKET",
            "stopPrice": stop,
            "closePosition": "true",
        }
        hasil["stopPrice"] = stop
        hasil["jawaban"] = klien._permintaan(
            "POST", JALUR_UJI_ORDER, params, signed=True)
        hasil["didukung"] = True
        _probe_hasil[kunci] = True
    except Exception as exc:  # noqa: BLE001
        kode = getattr(exc, "kode", None)
        hasil["galat"] = type(exc).__name__ + ": " + str(exc)
        hasil["kode"] = kode
        if kode in KODE_TIPE_TAK_DIDUKUNG:
            hasil["didukung"] = False
            _probe_hasil[kunci] = False
        elif kode is not None:
            hasil["didukung"] = True
            _probe_hasil[kunci] = True
        else:
            hasil["didukung"] = None

    if log is not None:
        try:
            log.append({"probe_stop": hasil})
        except Exception:  # noqa: BLE001
            pass
    return hasil


def mode_efektif(klien=None, simbol=None, env=None, log=None):
    mode = mode_eksekusi(env)
    if mode in (MODE_LAMA, MODE_AMAN):
        return mode
    if klien is None or not simbol:
        return MODE_AMAN
    hasil = deteksi_dukungan_stop(klien, simbol, log=log)
    return MODE_LAMA if hasil.get("didukung") is True else MODE_AMAN


def aman_aktif_untuk(klien=None, simbol=None, env=None, log=None):
    return mode_efektif(klien, simbol, env, log) == MODE_AMAN


def aman_aktif(env=None):
    """Bentuk lama, tanpa klien. Tanpa klien 'otomatis' tidak bisa membuktikan
    apa pun, jadi jatuh ke jalur yang punya fail-safe."""
    return mode_efektif(None, None, env) == MODE_AMAN


def batas_jarak(env=None):
    sumber = os.environ if env is None else env
    mentah = str(sumber.get(ENV_BATAS_JARAK, "") or "").strip()
    if not mentah:
        return BATAS_JARAK_BAWAAN
    try:
        nilai = float(mentah)
    except ValueError:
        return BATAS_JARAK_BAWAAN
    if nilai <= 0 or nilai > 5:
        return BATAS_JARAK_BAWAAN
    return nilai


def periksa_kewajaran(arah, harga_acuan, tp_harga, sl_harga, batas=None,
                      env=None):
    """Kembalikan daftar masalah; daftar kosong berarti wajar.

    Kenapa ini ada. Bursa TIDAK menjaga kewajaran harga proteksi. Bukti
    6 Agu 2026: PRICE_FILTER.maxPrice BTCUSDT = 809484.0, sekitar 12.5x harga
    pasar, dan TP di 10x harga pasar DITERIMA bursa. Order salah hitung tidak
    ditolak, ia hanya tidak pernah tersentuh, sehingga posisi berjalan tanpa
    TP nyata sambil terlihat 'terlindungi'. Penolakan -4002 baru muncul di
    luar maxPrice, jauh terlambat untuk berguna.
    """
    batas = batas_jarak(env) if batas is None else float(batas)
    masalah = []
    a = str(arah).upper()
    try:
        acuan = float(harga_acuan)
    except (TypeError, ValueError):
        acuan = 0.0
    if acuan <= 0:
        return ["harga_acuan_tidak_valid"]

    try:
        sl = float(sl_harga)
    except (TypeError, ValueError):
        sl = 0.0
    try:
        tp = float(tp_harga)
    except (TypeError, ValueError):
        tp = 0.0

    if sl <= 0:
        masalah.append("sl_tidak_valid")
    else:
        jarak_sl = abs(sl - acuan) / acuan
        if jarak_sl < JARAK_MIN_REL:
            masalah.append("sl_terlalu_dekat")
        if jarak_sl > batas:
            masalah.append("sl_terlalu_jauh")
        if a == "LONG" and sl >= acuan:
            masalah.append("sl_di_sisi_salah")
        if a == "SHORT" and sl <= acuan:
            masalah.append("sl_di_sisi_salah")

    if tp > 0:
        jarak_tp = abs(tp - acuan) / acuan
        if jarak_tp < JARAK_MIN_REL:
            masalah.append("tp_terlalu_dekat")
        if jarak_tp > batas:
            masalah.append("tp_terlalu_jauh")
        if a == "LONG" and tp <= acuan:
            masalah.append("tp_di_sisi_salah")
        if a == "SHORT" and tp >= acuan:
            masalah.append("tp_di_sisi_salah")

    return masalah


def pasang_proteksi_aman(klien, simbol, arah, tp_harga, sl_harga, log=None,
                         spek=None, pengirim=None, data=None, tidur=None,
                         ember=None):
    """Pasang proteksi lewat lapisan aman. Selalu mengembalikan dict, tidak
    pernah melempar: pemanggil di jalur live tidak boleh gagal karena ini.
    """
    from .inti import DataPasar, GagalProteksi, PengirimOrder, Proteksi, SpekSimbol

    log = log if log is not None else []
    hasil = {"mode": MODE_AMAN, "log": log, "gagal": None, "arah": arah}
    proteksi = None
    try:
        spek = spek or SpekSimbol.dari_exchange_info(
            klien.exchange_info(simbol), simbol)
        data = data or DataPasar(klien)
        pengirim = pengirim or PengirimOrder(klien, log=log, tidur=tidur)
        proteksi = Proteksi(klien, pengirim, spek, simbol, data=data, log=log,
                            tidur=tidur)

        acuan = 0.0
        try:
            acuan = float(klien.harga_sekarang(simbol))
        except Exception:  # noqa: BLE001
            acuan = 0.0
        if acuan > 0:
            masalah = periksa_kewajaran(arah, acuan, tp_harga, sl_harga)
        else:
            # Gagal baca harga adalah gangguan sesaat, bukan bukti harga salah.
            # Jaring pengaman tambahan tidak boleh jadi sumber kegagalan baru.
            masalah = []
            hasil["kewajaran_dilewati"] = "harga_acuan_tak_terbaca"
        hasil["harga_acuan"] = acuan

        if masalah:
            hasil["kewajaran"] = masalah
            hasil["gagal"] = "harga proteksi tidak wajar: " + ", ".join(masalah)
            hasil["proteksi"] = proteksi
            try:
                failsafe = proteksi.tutup_posisi(
                    "harga_proteksi_tidak_wajar", ember)
                hasil["failsafe"] = failsafe
                hasil["posisi_ditutup"] = bool(failsafe.get("bersih"))
            except Exception as exc2:  # noqa: BLE001
                hasil["failsafe_gagal"] = str(exc2)
                hasil["posisi_ditutup"] = False
            return hasil

        hasil.update(proteksi.pasang(tp_harga, sl_harga, ember))
        hasil["proteksi"] = proteksi
        return hasil
    except GagalProteksi as exc:
        hasil["gagal"] = str(exc)
        hasil["posisi_ditutup"] = True
        hasil["proteksi"] = proteksi
        return hasil
    except Exception as exc:  # noqa: BLE001
        hasil["gagal"] = type(exc).__name__ + ": " + str(exc)
        hasil["proteksi"] = proteksi
        if proteksi is not None:
            try:
                failsafe = proteksi.tutup_posisi("galat_tak_terduga", ember)
                hasil["failsafe"] = failsafe
                hasil["posisi_ditutup"] = bool(failsafe.get("bersih"))
            except Exception as exc2:  # noqa: BLE001
                hasil["failsafe_gagal"] = str(exc2)
        return hasil
