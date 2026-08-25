"""Stress test lapis 3b: base 0,20 USDT per setup DI DALAM siklus eksekusi.

Lapis 3 sebelumnya menguji perhitungannya. Berkas ini menguji bahwa perhitungan
itu benar-benar DIPAKAI jalur hidup, karena modul yang sudah diuji tetapi tidak
tersambung sama saja dengan tidak ada.

Tiga hal yang dikunci:
1. Saldo di bawah 20 USDT memakai jalur mikro dan mencapai margin 0,20.
2. Ketidaklayakan berhenti SEBELUM satu order pun dikirim.
3. Saldo 20 USDT atau lebih tetap memakai sizing risiko - tanpa regresi.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.binance_client import BinanceAPIError
from lux_modul.eksekusi_aman.inti import (
    ARAH_LONG,
    KebijakanRisiko,
    SpekSimbol,
    jalankan_siklus,
)


def spek(min_notional=5.0):
    return SpekSimbol(0.01, 0.001, 0.001, 1000.0, min_notional, 2, 3)


class Klien:
    def __init__(self, posisi_amt=0.05, entry=100.0, tp_terlihat=True,
                 leverage_galat=None):
        self.posisi_amt = posisi_amt
        self.entry = entry
        self.tp_terlihat = tp_terlihat
        self.leverage_galat = leverage_galat
        self.leverage_diatur = []
        self.terkirim = []
        self._ot = []

    def atur_leverage(self, simbol, lev):
        if self.leverage_galat is not None:
            raise self.leverage_galat
        self.leverage_diatur.append((simbol, int(lev)))
        return {"leverage": int(lev)}

    def posisi(self, simbol=None):
        if abs(self.posisi_amt) <= 0:
            return []
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.posisi_amt),
                 "entryPrice": str(self.entry)}]

    def order_terbuka(self, simbol=None):
        return self._ot

    def batalkan_semua_order(self, simbol=None):
        return {"code": 200, "msg": "done"}

    def bid_ask_terbaik(self, simbol=None):
        return {"bid": 99.9, "ask": 100.1}

    def harga_sekarang(self, simbol=None):
        return 100.0

    def kirim_order(self, payload):
        self.terkirim.append(payload)
        oid = 700 + len(self.terkirim)
        gtc = payload.get("timeInForce") == "GTC"
        if payload.get("reduceOnly") and gtc and self.tp_terlihat:
            self._ot = list(self._ot) + [
                {"orderId": oid, "reduceOnly": True, "type": "LIMIT",
                 "side": payload["side"],
                 "origQty": str(payload.get("quantity")),
                 "price": str(payload.get("price"))}]
        elif payload.get("reduceOnly") and not gtc:
            self.posisi_amt = 0.0
        return {"orderId": oid, "clientOrderId": None,
                "symbol": payload["symbol"], "side": payload["side"],
                "status": "FILLED", "type": payload.get("type", "LIMIT"),
                "origQty": str(payload.get("quantity", 0)),
                "executedQty": str(payload.get("quantity", 0)),
                "price": str(payload.get("price", 0)), "avgPrice": "100"}

    def _permintaan(self, metode, jalur, params=None, signed=False):
        return {}

    def status_order(self, simbol, order_id=None, **lain):
        return {"orderId": order_id or 1, "clientOrderId": None,
                "symbol": "BTCUSDT", "side": "BUY", "status": "FILLED",
                "type": "LIMIT", "origQty": "0.05", "executedQty": "0.05",
                "price": "100", "avgPrice": "100"}

    def sinkron_waktu(self):
        return 0


class DataStub:
    def mark(self, simbol):
        return 100.0

    def bid_ask(self, simbol):
        return {"bid": 99.9, "ask": 100.1}


def siklus(k, saldo, min_notional=5.0):
    return jalankan_siklus(k, "BTCUSDT", ARAH_LONG, 99.0, 101.0,
                           KebijakanRisiko(), spek=spek(min_notional),
                           data=DataStub(), tidur=lambda _d: None, saldo=saldo)


def test_saldo_mikro_memakai_jalur_mikro_dan_mencapai_base_020():
    # notional 5 (minimum bursa) x leverage 25 -> margin tepat 0,20 USDT.
    k = Klien()
    h = siklus(k, 10.0)
    assert h["jalur_ukuran"] == "mikro"
    assert h["ukuran"]["qty"] == pytest.approx(0.05)
    assert h["ukuran"]["notional"] == pytest.approx(5.0)
    assert h["ukuran"]["margin_nyata"] == pytest.approx(0.20)
    assert h["ukuran"]["base_tercapai"] is True
    assert h["leverage_dipasang"] == 25
    assert k.leverage_diatur == [("BTCUSDT", 25)]
    assert h["kesimpulan"] == "terlindungi"
    assert h["rekonsiliasi"]["masalah"] is None


def test_saldo_mikro_tidak_layak_tidak_mengirim_order_apa_pun():
    # minNotional 100 pada saldo 10 dengan SL 1% = rugi 1 USDT = 10% modal.
    # Setup HARUS dilewati, bukan dipaksakan.
    k = Klien()
    h = siklus(k, 10.0, min_notional=100.0)
    assert h["jalur_ukuran"] == "mikro"
    assert h["kesimpulan"] == "ukuran_tidak_layak"
    assert "melebihi batas" in h["alasan_tidak_layak"]
    assert h["dampak"] == "tidak ada order dikirim; setup dilewati"
    assert k.terkirim == []
    assert k.leverage_diatur == []


def test_leverage_gagal_dipasang_membatalkan_setup_sebelum_ada_order():
    # Seluruh angka margin dan jarak likuidasi jalur mikro dihitung dari
    # leverage tertentu. Kalau leverage gagal dipasang, angka itu tidak
    # berlaku, jadi meneruskan eksekusi berarti memakai asumsi risiko salah.
    k = Klien(leverage_galat=BinanceAPIError(400, -4028,
                                            "Leverage is not valid."))
    h = siklus(k, 10.0)
    assert h["kesimpulan"] == "leverage_gagal_dipasang"
    assert "-4028" in h["galat_leverage"] or "not valid" in h["galat_leverage"]
    assert h["dampak"] == "tidak ada order dikirim; posisi tidak dibuka"
    assert h["perlu_diperbaiki"] == "BinanceFuturesClient.atur_leverage"
    assert k.terkirim == []


def test_saldo_normal_tetap_memakai_sizing_risiko_tanpa_regresi():
    k = Klien()
    h = siklus(k, 5000.0)
    assert h["jalur_ukuran"] == "risiko"
    assert k.leverage_diatur == []
    assert h["ukuran"]["qty"] == pytest.approx(50.0)
    assert h["ukuran"]["leverage"] == 10


def test_ambang_20_usdt_persis_memakai_jalur_risiko():
    # modal_mikro memakai perbandingan ketat: 20,0 BUKAN modal mikro.
    assert siklus(Klien(), 20.0)["jalur_ukuran"] == "risiko"
    assert siklus(Klien(), 19.99)["jalur_ukuran"] == "mikro"
