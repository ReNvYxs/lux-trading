"""Stress test lapis 2a: injeksi kegagalan pada pengiriman order.

Yang diuji di sini bukan jalur bahagia, tetapi justru jalur yang dulu membuat
mesin BERBOHONG: timeout dianggap gagal, badan jawaban kosong dianggap sukses,
dan galat ambigu diulang buta sehingga order bisa berganda.

Aturan yang dikunci uji ini:
1. Satu perintah tulis ke bursa dikirim SEKALI. Tidak pernah diulang buta
   setelah timeout atau jawaban tak jelas.
2. Jawaban apa pun tanpa orderId/clientOrderId atau tanpa status yang dikenal
   BUKAN konfirmasi.
3. Dibatasi laju tidak boleh diulang - mengulang memperpanjang pembatasan dan
   bisa memicu ban IP.
4. Pembacaan status order harus tahan galat sementara, karena status paling
   dibutuhkan justru saat jaringan sedang buruk.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.binance_client import BinanceAPIError
from lux_modul.eksekusi.klasifikasi import KELAS_LAJU, KELAS_TAK_DIKETAHUI
from lux_modul.eksekusi_aman.inti import PengirimOrder

PAYLOAD = {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT",
           "timeInForce": "IOC", "price": 64_000.0, "quantity": 0.001}


def jawaban(status="NEW", simbol="BTCUSDT", sisi="BUY", terisi="0"):
    """Bentuk jawaban order Binance USD-M yang sebenarnya."""
    return {"orderId": 111, "clientOrderId": None, "symbol": simbol,
            "side": sisi, "status": status, "type": "LIMIT",
            "origQty": "0.001", "executedQty": terisi, "price": "64000",
            "avgPrice": "0"}


class KlienPalsu:
    def __init__(self, kirim=None, cari=None, status=None):
        self._kirim = kirim
        self._cari = {} if cari is None else cari
        self._status = status
        self.jumlah_kirim = 0
        self.jumlah_cari = 0
        self.jumlah_status = 0
        self.jumlah_sinkron = 0

    @staticmethod
    def _pilih(nilai, n):
        if isinstance(nilai, list):
            return nilai[min(n - 1, len(nilai) - 1)]
        return nilai

    def kirim_order(self, payload):
        self.jumlah_kirim += 1
        h = self._pilih(self._kirim, self.jumlah_kirim)
        if isinstance(h, Exception):
            raise h
        return h

    def _permintaan(self, metode, jalur, params=None, signed=False):
        self.jumlah_cari += 1
        if isinstance(self._cari, Exception):
            raise self._cari
        return self._cari

    def status_order(self, simbol, order_id=None, **lain):
        self.jumlah_status += 1
        s = self._pilih(self._status, self.jumlah_status)
        if isinstance(s, Exception):
            raise s
        return s

    def sinkron_waktu(self):
        self.jumlah_sinkron += 1
        return 0


def pengirim(klien, coba_maks=3):
    return PengirimOrder(klien, tidur=lambda _d: None, coba_maks=coba_maks,
                         jeda_awal=0.0)


# ----------------------- 1. keadaan TIDAK DIKETAHUI ---------------------- #


def test_timeout_pada_post_order_tidak_pernah_disebut_gagal():
    # Order mungkin SUDAH sampai matching engine. Menyebutnya gagal adalah
    # kebohongan; mengulangnya bisa menggandakan posisi.
    k = KlienPalsu(kirim=TimeoutError("the read operation timed out"))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e1")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert r["kelas"] == KELAS_TAK_DIKETAHUI
    assert r["wajib_rekonsiliasi"] is True
    assert k.jumlah_kirim == 1


def test_timeout_tetapi_order_ternyata_sampai_dipulihkan_lewat_cid():
    k = KlienPalsu(kirim=TimeoutError("timeout"), cari=jawaban())
    r = pengirim(k).kirim(PAYLOAD, "entry", "e2")
    assert r["hasil"] == "PULIH_LEWAT_CID"
    assert k.jumlah_kirim == 1


def test_http_503_diperlakukan_tak_diketahui_dan_wajib_rekonsiliasi():
    k = KlienPalsu(kirim=BinanceAPIError(
        503, None, "Unknown error, please check your request or try again later."))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e3")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert r["kelas"] == KELAS_TAK_DIKETAHUI
    assert r["wajib_rekonsiliasi"] is True
    assert k.jumlah_kirim == 1


# --------------------- 2. jawaban tidak lengkap ------------------------- #


def test_badan_jawaban_kosong_bukan_sukses():
    k = KlienPalsu(kirim={})
    r = pengirim(k).kirim(PAYLOAD, "entry", "e4")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert "kosong" in r["pesan"]


def test_jawaban_tanpa_status_bukan_sukses_tetapi_bisa_dipulihkan():
    k = KlienPalsu(kirim={"orderId": 1}, cari=jawaban())
    r = pengirim(k).kirim(PAYLOAD, "entry", "e5")
    assert r["hasil"] == "PULIH_LEWAT_CID"
    assert r["ringkas"]["status"] == "NEW"


def test_status_tidak_dikenal_membuat_mesin_berhenti_bukan_menebak():
    k = KlienPalsu(kirim={"orderId": 1, "status": "STATUS_BARU_BINANCE"})
    r = pengirim(k).kirim(PAYLOAD, "entry", "e6")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert "tidak dikenal" in r["pesan"]


def test_jawaban_untuk_simbol_lain_ditolak():
    k = KlienPalsu(kirim=jawaban(simbol="ETHUSDT"))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e7")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert "tidak cocok" in r["pesan"]


def test_jawaban_sisi_salah_ditolak():
    k = KlienPalsu(kirim=jawaban(sisi="SELL"))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e8")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert "tidak cocok" in r["pesan"]


def test_jawaban_sah_disebut_ok_dan_qty_terisi_dibaca_dari_bursa():
    k = KlienPalsu(kirim=jawaban(status="FILLED", terisi="0.001"))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e9")
    assert r["hasil"] == "OK"
    assert r["ringkas"]["qty_terisi"] == pytest.approx(0.001)
    assert r["ringkas"]["terisi_penuh"] is True
    assert k.jumlah_kirim == 1


# ------------------------ 3. penolakan bursa ---------------------------- #


def test_permintaan_duplikat_4116_berarti_yang_pertama_sudah_sampai():
    k = KlienPalsu(kirim=BinanceAPIError(400, -4116, "duplicate cid"),
                   cari=jawaban())
    r = pengirim(k).kirim(PAYLOAD, "entry", "e10")
    assert r["hasil"] == "SUDAH_ADA"
    assert r["order"]["orderId"] == 111
    assert k.jumlah_kirim == 1


def test_margin_tidak_cukup_2019_permanen_tanpa_retry():
    # -2019 TIDAK ada di daftar permanen lama yang hanya 9 kode, sehingga dulu
    # diulang 3x dengan backoff tepat saat fail-safe harus cepat.
    k = KlienPalsu(kirim=BinanceAPIError(400, -2019, "Margin is insufficient."))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e11")
    assert r["hasil"] == "DITOLAK_PERMANEN"
    assert r["kode"] == -2019
    assert k.jumlah_kirim == 1


def test_notional_di_bawah_minimum_4164_permanen():
    k = KlienPalsu(kirim=BinanceAPIError(400, -4164, "Order's notional must be "
                                                    "no smaller than 5"))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e12")
    assert r["hasil"] == "DITOLAK_PERMANEN"
    assert k.jumlah_kirim == 1


def test_tipe_order_tidak_didukung_4120_permanen():
    k = KlienPalsu(kirim=BinanceAPIError(
        400, -4120, "Order type not supported for this endpoint. Please use "
                    "the Algo Order API endpoints instead."))
    r = pengirim(k).kirim(PAYLOAD, "sl", "e13")
    assert r["hasil"] == "DITOLAK_PERMANEN"
    assert r["kode"] == -4120


def test_dibatasi_laju_tidak_diulang_supaya_tidak_kena_ban_ip():
    k = KlienPalsu(kirim=BinanceAPIError(429, -1003, "Too many requests."))
    r = pengirim(k).kirim(PAYLOAD, "entry", "e14")
    assert r["hasil"] == "TIDAK_TERKONFIRMASI"
    assert r["kelas"] == KELAS_LAJU
    assert k.jumlah_kirim == 1


def test_timestamp_1021_disinkronkan_dulu_baru_diulang():
    k = KlienPalsu(kirim=BinanceAPIError(400, -1021, "Timestamp for this "
                                                    "request is outside of "
                                                    "the recvWindow."))
    r = pengirim(k, coba_maks=2).kirim(PAYLOAD, "entry", "e15")
    assert k.jumlah_sinkron == 2
    assert k.jumlah_kirim == 2
    assert r["hasil"] == "GAGAL"


# --------------------- 4. pembacaan status order ------------------------ #


def test_baca_status_menoleransi_2013_lalu_berhasil():
    # p10: -2013 muncul saat query terlalu dini, dan galat itu SEMPAT membuat
    # posisi terisi tertinggal tanpa proteksi.
    k = KlienPalsu(status=[BinanceAPIError(400, -2013, "Order does not exist."),
                           jawaban(status="FILLED", terisi="0.001")])
    st = pengirim(k).baca_status("BTCUSDT", order_id=1, coba=4, jeda=0.0)
    assert st is not None
    assert st["status"] == "FILLED"
    assert k.jumlah_status == 2


def test_baca_status_tetap_mencoba_saat_galat_sementara():
    # Versi lama BERHENTI pada galat non -2013 apa pun, sehingga satu timeout
    # sesaat membatalkan seluruh pembacaan status.
    k = KlienPalsu(status=[TimeoutError("timeout"), TimeoutError("timeout"),
                           jawaban(status="FILLED", terisi="0.001")])
    st = pengirim(k).baca_status("BTCUSDT", order_id=1, coba=4, jeda=0.0)
    assert st is not None
    assert k.jumlah_status == 3


def test_baca_status_berhenti_cepat_pada_galat_permanen():
    k = KlienPalsu(status=BinanceAPIError(400, -1121, "Invalid symbol."))
    p = pengirim(k)
    st = p.baca_status("BTCUSDT", order_id=1, coba=4, jeda=0.0)
    assert st is None
    assert k.jumlah_status == 1
    assert any(e["peristiwa"] == "status_tidak_terbaca" for e in p.log)


# ------------------------- 5. jejak yang bisa ditelusuri ---------------- #


def test_setiap_kegagalan_meninggalkan_jejak_dengan_konteks():
    k = KlienPalsu(kirim=BinanceAPIError(400, -2019, "Margin is insufficient."))
    p = pengirim(k)
    p.kirim(PAYLOAD, "entry", "e16")
    jejak = [e for e in p.log if e["peristiwa"] == "ditolak_permanen"]
    assert len(jejak) == 1
    # Konteks minimum yang wajib ada untuk menelusuri masalah di kemudian hari.
    assert jejak[0]["niat"] == "entry"
    assert jejak[0]["kode"] == -2019
    assert jejak[0]["cid"].startswith("lx")


def test_cid_deterministik_sama_untuk_ember_sama():
    k1 = KlienPalsu(kirim=jawaban())
    k2 = KlienPalsu(kirim=jawaban())
    a = pengirim(k1).kirim(PAYLOAD, "entry", "ember-tetap")
    b = pengirim(k2).kirim(PAYLOAD, "entry", "ember-tetap")
    assert a["cid"] == b["cid"]
    c = pengirim(KlienPalsu(kirim=jawaban())).kirim(PAYLOAD, "entry", "lain")
    assert c["cid"] != a["cid"]
