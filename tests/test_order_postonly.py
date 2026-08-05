"""Uji kebijakan order: MARKET diharamkan, post-only (GTX) wajib, SL = STOP_MARKET."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.ice_breaker import IceBreakerExecutor, Slice, plan_execution
from lux_modul.eksekusi.order import (
    TIF_POST_ONLY,
    TIPE_LIMIT,
    TIPE_STOP_MARKET,
    KebijakanOrder,
    OrderTerlarang,
    harga_post_only,
    pastikan_tanpa_market,
    payload_entry,
    payload_sl,
    payload_tp,
    rencana_requote,
)
from lux_modul.kontrak import ARAH_LONG, ARAH_SHORT


def test_payload_entry_selalu_limit_postonly():
    p = payload_entry("BTCUSDT", ARAH_LONG, qty=0.01, harga=50_000.0)
    assert p["type"] == TIPE_LIMIT
    assert p["timeInForce"] == TIF_POST_ONLY
    assert p["side"] == "BUY"


def test_payload_tp_reduce_only_dan_postonly():
    p = payload_tp("BTCUSDT", ARAH_LONG, qty=0.01, harga=51_000.0)
    assert p["type"] == TIPE_LIMIT
    assert p["timeInForce"] == TIF_POST_ONLY
    assert p["reduceOnly"] is True
    assert p["side"] == "SELL"


def test_payload_sl_stop_market():
    p = payload_sl("BTCUSDT", ARAH_LONG, stop_price=49_000.0)
    assert p["type"] == TIPE_STOP_MARKET
    assert p["closePosition"] is True
    assert p["side"] == "SELL"
    assert p["workingType"] == "MARK_PRICE"


def test_market_order_ditolak():
    with pytest.raises(OrderTerlarang):
        pastikan_tanpa_market({"symbol": "BTCUSDT", "side": "BUY", "type": "MARKET"})
    with pytest.raises(OrderTerlarang):
        pastikan_tanpa_market(
            {"symbol": "BTCUSDT", "side": "SELL", "type": "TAKE_PROFIT_MARKET"}
        )


def test_limit_tanpa_gtx_ditolak():
    with pytest.raises(OrderTerlarang):
        pastikan_tanpa_market(
            {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "timeInForce": "GTC"}
        )


def test_stop_market_bisa_dilarang_oleh_kebijakan():
    k = KebijakanOrder(izinkan_market_untuk_sl=False)
    with pytest.raises(OrderTerlarang):
        payload_sl("BTCUSDT", ARAH_LONG, stop_price=49_000.0, kebijakan=k)


def test_harga_post_only_di_sisi_maker():
    k = KebijakanOrder(tick_size=0.1, offset_tick=1)
    long_h = harga_post_only(ARAH_LONG, 100.0, best_bid=99.9, kebijakan=k)
    short_h = harga_post_only(ARAH_SHORT, 100.0, best_ask=100.1, kebijakan=k)
    assert long_h < 100.0
    assert short_h > 100.0


def test_requote_makin_menjauh_dari_pasar():
    k = KebijakanOrder(tick_size=0.5, offset_tick=1, maks_requote=3)
    harga = rencana_requote(ARAH_LONG, 100.0, k)
    assert len(harga) == 3
    assert harga[0] > harga[1] > harga[2]


def test_slice_tanpa_harga_ditolak():
    s = Slice(urutan=0, qty=1.0, visible_qty=0.25, jeda_detik=0.0)
    with pytest.raises(OrderTerlarang):
        s.payload("BTCUSDT", "BUY", None)


def test_slice_payload_postonly_dan_iceberg():
    s = Slice(urutan=0, qty=1.0, visible_qty=0.25, jeda_detik=0.0)
    p = s.payload("BTCUSDT", "BUY", 100.0)
    assert p["type"] == TIPE_LIMIT
    assert p["timeInForce"] == TIF_POST_ONLY
    assert p["icebergQty"] == 0.25
    assert p["visible_qty"] == 0.25


def test_eksekutor_icebreaker_mengirim_semua_postonly():
    rencana = plan_execution("BTCUSDT", ARAH_LONG, qty=1.0, harga=20_000.0, sl=19_000.0)
    assert rencana.memakai_icebreaker
    terkirim = []

    async def kirim(p):
        terkirim.append(p)
        return {"orderId": len(terkirim)}

    async def tidur(_d):
        return None

    hasil = IceBreakerExecutor(kirim, harga_kini=lambda: 20_000.0, tidur=tidur).jalankan_sinkron(
        rencana
    )
    assert hasil.selesai_penuh
    assert terkirim
    assert all(p["type"] == TIPE_LIMIT for p in terkirim)
    assert all(p["timeInForce"] == TIF_POST_ONLY for p in terkirim)
