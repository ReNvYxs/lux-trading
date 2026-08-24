"""Stress test lapis 1: klasifikasi galat, konfirmasi order, jejak audit.

Lapis ini murni unit, tanpa jaringan dan tanpa klien tiruan, supaya kegagalan
di sini selalu berarti aturannya sendiri yang salah - bukan tiruannya.
"""
import json

import pytest

from lux_modul.eksekusi.binance_client import BinanceAPIError
from lux_modul.eksekusi import jejak as J
from lux_modul.eksekusi import klasifikasi as K

ORDER = "/fapi/v1/order"
KLINES = "/fapi/v1/klines"


def galat(status=None, kode=None, pesan="uji", payload=None):
    return BinanceAPIError(status=status, kode=kode, pesan=pesan, payload=payload)


# ------------------------------------------------------------------ #
# Tabel kode
# ------------------------------------------------------------------ #
def test_kode_permanen_memuat_temuan_yang_dulu_terlewat():
    # Daftar lama hanya punya 9 kode. Ini yang dulu diulang 3x sia-sia.
    for kode in (-2019, -4164, -1104, -2027, -2018, -2025):
        assert kode in K.KODE_PERMANEN, kode
    # Yang lama tetap ada supaya tidak ada regresi.
    for kode in (-4120, -5022, -1111, -1121, -2022):
        assert kode in K.KODE_PERMANEN, kode


def test_rate_limit_bukan_permanen_dan_bukan_sementara():
    # Kalau -1003 masuk permanen, fail-safe jadi terlalu cepat menyerah;
    # kalau masuk sementara, retry-nya memperpanjang ban.
    assert -1003 not in K.KODE_PERMANEN
    assert -1003 not in K.KODE_SEMENTARA
    assert -1003 in K.KODE_LAJU


# ------------------------------------------------------------------ #
# Keadaan ketiga: TIDAK DIKETAHUI
# ------------------------------------------------------------------ #
def test_tanpa_jawaban_pada_jalur_tulis_dana_adalah_tak_diketahui():
    k = K.klasifikasikan(galat(), jalur=ORDER, metode="POST")
    assert k.kelas == K.KELAS_TAK_DIKETAHUI
    assert k.boleh_ulang is False
    assert k.wajib_rekonsiliasi is True


def test_tanpa_jawaban_pada_jalur_baca_boleh_diulang():
    k = K.klasifikasikan(galat(), jalur=KLINES, metode="GET")
    assert k.kelas == K.KELAS_SEMENTARA
    assert k.boleh_ulang is True
    assert k.wajib_rekonsiliasi is False


def test_http_503_adalah_tak_diketahui_bukan_gagal():
    # Dokumentasi Binance: permintaan diterima tanpa jawaban sebelum timeout,
    # eksekusi MUNGKIN BERHASIL.
    k = K.klasifikasikan(galat(status=503), jalur=ORDER, metode="POST")
    assert k.kelas == K.KELAS_TAK_DIKETAHUI
    assert k.wajib_rekonsiliasi is True


@pytest.mark.parametrize("kode", [-1000, -1006, -1007])
def test_kode_status_tak_diketahui(kode):
    k = K.klasifikasikan(galat(kode=kode), jalur=ORDER, metode="POST")
    assert k.kelas == K.KELAS_TAK_DIKETAHUI
    assert k.boleh_ulang is False


def test_kode_belum_dikenal_pada_jalur_tulis_ditahan_ke_sisi_aman():
    # Sifat paling penting dari tabel ini: ia PASTI akan ketinggalan zaman.
    k = K.klasifikasikan(galat(status=400, kode=-9999), jalur=ORDER,
                         metode="POST")
    assert k.kelas == K.KELAS_TAK_DIKETAHUI
    assert k.boleh_ulang is False
    assert k.wajib_rekonsiliasi is True


def test_kode_belum_dikenal_pada_jalur_baca_cukup_diulang():
    k = K.klasifikasikan(galat(status=400, kode=-9999), jalur=KLINES,
                         metode="GET")
    assert k.kelas == K.KELAS_SEMENTARA
    assert k.boleh_ulang is True


@pytest.mark.parametrize("status", [418, 429])
def test_pembatasan_laju_tidak_boleh_diulang(status):
    k = K.klasifikasikan(galat(status=status), jalur=ORDER, metode="POST")
    assert k.kelas == K.KELAS_LAJU
    assert k.boleh_ulang is False
    assert k.jeda_ms > 0


def test_1021_wajib_sinkron_waktu_bukan_sekadar_ulang():
    k = K.klasifikasikan(galat(status=400, kode=-1021), jalur=ORDER,
                         metode="POST")
    assert k.kelas == K.KELAS_WAKTU
    assert k.wajib_sinkron_waktu is True


def test_4116_menandakan_percobaan_sebelumnya_sudah_sampai():
    k = K.klasifikasikan(galat(status=400, kode=-4116), jalur=ORDER,
                         metode="POST")
    assert k.kelas == K.KELAS_DUPLIKAT
    assert k.wajib_rekonsiliasi is True


@pytest.mark.parametrize("kode", [-2013, -2011])
def test_order_tidak_ada_harus_direkonsiliasi(kode):
    k = K.klasifikasikan(galat(status=400, kode=kode), jalur=ORDER,
                         metode="DELETE")
    assert k.kelas == K.KELAS_TIDAK_ADA
    assert k.wajib_rekonsiliasi is True


def test_permanen_tidak_perlu_rekonsiliasi():
    k = K.klasifikasikan(galat(status=400, kode=-4120), jalur=ORDER,
                         metode="POST")
    assert k.kelas == K.KELAS_PERMANEN
    assert k.boleh_ulang is False
    assert k.wajib_rekonsiliasi is False


# ------------------------------------------------------------------ #
# Konfirmasi order
# ------------------------------------------------------------------ #
@pytest.mark.parametrize("jawaban", [
    None, {}, [], "OK", 200,
    {"orderId": 1},
    {"status": "NEW"},
    {"orderId": 1, "status": "SESUATU_BARU"},
    {"orderId": None, "clientOrderId": "", "status": "NEW"},
])
def test_konfirmasi_menolak_jawaban_yang_bukan_konfirmasi(jawaban):
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_order(jawaban)


def test_konfirmasi_menolak_simbol_dan_sisi_yang_tidak_cocok():
    j = {"orderId": 9, "status": "NEW", "symbol": "ETHUSDT", "side": "BUY"}
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_order(j, simbol="BTCUSDT")
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_order(j, sisi="SELL")


def test_konfirmasi_menolak_cid_milik_order_lain():
    j = {"orderId": 9, "clientOrderId": "lxLAIN", "status": "NEW"}
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_order(j, cid="lxKITA")


def test_konfirmasi_menerima_order_baru_dan_menyebutnya_belum_terisi():
    r = K.konfirmasi_order({"orderId": 5, "status": "NEW", "symbol": "BTCUSDT",
                            "side": "BUY", "origQty": "0.010",
                            "executedQty": "0"}, simbol="BTCUSDT", sisi="BUY")
    assert r["hidup"] is True
    assert r["selesai"] is False
    assert r["qty_terisi"] == 0.0
    assert r["terisi_penuh"] is False
    assert r["parsial"] is False


def test_konfirmasi_mengenali_partial_fill():
    r = K.konfirmasi_order({"orderId": 5, "status": "PARTIALLY_FILLED",
                            "origQty": "1.0", "executedQty": "0.4"})
    assert r["parsial"] is True
    assert r["terisi_penuh"] is False
    assert r["qty_terisi"] == 0.4


def test_konfirmasi_mengenali_expired_sebagai_selesai_tanpa_isi():
    # p09: LIMIT IOC terlalu ketat EXPIRED dan posisi TIDAK tertutup.
    r = K.konfirmasi_order({"orderId": 5, "status": "EXPIRED",
                            "origQty": "1.0", "executedQty": "0"})
    assert r["selesai"] is True
    assert r["hidup"] is False
    assert r["qty_terisi"] == 0.0


# ------------------------------------------------------------------ #
# Konfirmasi pembatalan
# ------------------------------------------------------------------ #
def test_konfirmasi_batal_menolak_status_bukan_canceled():
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_batal({"orderId": 1, "status": "NEW"})
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_batal({})
    with pytest.raises(K.GagalKonfirmasi):
        K.konfirmasi_batal(None)


def test_konfirmasi_batal_menerima_dua_bentuk_yang_berbeda():
    a = K.konfirmasi_batal({"code": 200, "msg": "selesai"})
    assert a["bentuk"] == "semua_order"
    b = K.konfirmasi_batal({"orderId": 7, "status": "CANCELED",
                            "symbol": "BTCUSDT"}, simbol="BTCUSDT")
    assert b["bentuk"] == "satu_order"


# ------------------------------------------------------------------ #
# Jejak audit
# ------------------------------------------------------------------ #
def test_jejak_menyunting_rahasia_tapi_menahan_nama_parameter():
    r = J.redaksi({"symbol": "BTCUSDT", "signature": "abc123",
                   "api_key": "rahasia", "quantity": 1})
    assert r["signature"] == "[disunting]"
    assert r["api_key"] == "[disunting]"
    # Nama parameter DIPERTAHANKAN: saat Binance menolak karena parameter,
    # yang perlu diketahui adalah parameter apa saja yang ikut terkirim.
    assert "signature" in r and r["symbol"] == "BTCUSDT"


def test_jejak_korelasi_menyatukan_permintaan_dan_galat():
    p = J.perekam_senyap()
    kor = p.catat_permintaan("POST", ORDER, {"symbol": "BTCUSDT"}, True)
    p.catat_galat(kor, "POST", ORDER, status=400, kode=-4120, pesan="tolak",
                  parameter={"symbol": "BTCUSDT"})
    baris = p.cari_korelasi(kor)
    assert len(baris) == 2
    assert {b["peristiwa"] for b in baris} == {J.PERISTIWA_PERMINTAAN,
                                              J.PERISTIWA_GALAT}


def test_jejak_jalur_dana_utuh_jalur_pasar_diringkas():
    assert J.jalur_dana(ORDER) is True
    assert J.jalur_dana(KLINES) is False
    utuh = J.ringkas_jawaban(ORDER, {"orderId": 1, "status": "NEW"})
    assert utuh["orderId"] == 1
    # Satu jawaban exchangeInfo bisa jutaan karakter dan menenggelamkan jejak
    # yang penting, jadi jalur pasar hanya dicatat bentuknya.
    ringkas = J.ringkas_jawaban(KLINES, [[1, 2, 3]] * 500)
    assert ringkas["panjang"] == 500
    assert "contoh_pertama" in ringkas


def test_jejak_tidak_pernah_melempar_walau_direktori_mustahil():
    # Gagal mencatat TIDAK BOLEH menjadi gagal bertransaksi.
    p = J.PerekamJejak(direktori="/proc/mustahil/jejak", env={})
    p.catat_permintaan("POST", ORDER, {"a": 1}, True)
    assert p.gagal_tulis >= 1
    assert p.ringkas()["di_ingatan"] == 1


def test_jejak_dapat_diserialisasi_sebagai_jsonl():
    p = J.perekam_senyap()
    p.catat_keputusan("berhenti_tanpa_ulang", alasan="laju", korelasi="x1")
    p.catat_failsafe("tp_gagal", "tutup_posisi", berhasil=True)
    for rekaman in p.ingatan:
        json.loads(json.dumps(rekaman, default=str))
