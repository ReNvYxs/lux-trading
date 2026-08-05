"""Uji BinanceFuturesClient dengan mock (SANDBOX TANPA JARINGAN - lihat disclaimer
di lux_modul/eksekusi/binance_client.py). Tidak ada panggilan jaringan sungguhan
di sini; `pembuka_url` disuntikkan sebagai fake HTTP opener.
"""
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.binance_client import BinanceAPIError, BinanceFuturesClient
from lux_modul.eksekusi.kredensial import BASE_URL_TESTNET, KredensialBinance


def _kredensial_uji():
    return KredensialBinance("testnet", "kunci-uji", "rahasia-uji", BASE_URL_TESTNET)


class _RespPalsu:
    def __init__(self, payload, status=200):
        self._raw = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _pembuka(payload, status=200, tangkap=None):
    def _buka(req, timeout=None):
        if tangkap is not None:
            tangkap.append(req)
        return _RespPalsu(payload, status)

    return _buka


def _pembuka_error(status, kode, pesan):
    def _buka(req, timeout=None):
        body = json.dumps({"code": kode, "msg": pesan}).encode("utf-8")
        raise urllib.error.HTTPError(req.full_url, status, pesan, {}, io.BytesIO(body))

    return _buka


def test_waktu_server():
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka({"serverTime": 123456789}))
    assert client.waktu_server() == 123456789


def test_sinkron_waktu_menyimpan_offset():
    jam = [1_000_000]
    client = BinanceFuturesClient(
        _kredensial_uji(),
        jam_ms=lambda: jam[0],
        pembuka_url=_pembuka({"serverTime": 1_000_500}),
    )
    offset = client.sinkron_waktu()
    assert offset == 500


def test_request_signed_menyertakan_signature_dan_timestamp():
    tangkap = []
    client = BinanceFuturesClient(
        _kredensial_uji(), jam_ms=lambda: 5_000_000, pembuka_url=_pembuka([], tangkap=tangkap)
    )
    client.saldo()
    assert len(tangkap) == 1
    url = tangkap[0].full_url
    assert "signature=" in url
    assert "timestamp=" in url
    assert "recvWindow=" in url


def test_request_unsigned_tidak_menyertakan_signature():
    tangkap = []
    client = BinanceFuturesClient(
        _kredensial_uji(), pembuka_url=_pembuka({"serverTime": 1}, tangkap=tangkap)
    )
    client.waktu_server()
    assert len(tangkap) == 1
    assert "signature=" not in tangkap[0].full_url


def test_klines_meneruskan_parameter():
    tangkap = []
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka([], tangkap=tangkap))
    client.klines("BTCUSDT", "15m", limit=250)
    assert "symbol=BTCUSDT" in tangkap[0].full_url
    assert "interval=15m" in tangkap[0].full_url
    assert "limit=250" in tangkap[0].full_url


def test_harga_sekarang():
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka({"price": "65000.5"}))
    assert client.harga_sekarang("BTCUSDT") == 65000.5


def test_bid_ask_terbaik():
    payload = {"bids": [["64999.0", "1.0"]], "asks": [["65001.0", "1.0"]]}
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka(payload))
    ba = client.bid_ask_terbaik("BTCUSDT")
    assert ba["bid"] == 64999.0
    assert ba["ask"] == 65001.0


def test_saldo_usdt_ambil_asset_usdt():
    payload = [
        {"asset": "BNB", "availableBalance": "1.0"},
        {"asset": "USDT", "availableBalance": "250.5"},
    ]
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka(payload))
    assert client.saldo_usdt() == 250.5


def test_kirim_order_post_signed():
    tangkap = []
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka({"orderId": 1}, tangkap=tangkap))
    resp = client.kirim_order({"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT"})
    assert resp == {"orderId": 1}
    assert tangkap[0].get_method() == "POST"
    body = tangkap[0].data.decode("utf-8")
    assert "signature=" in body


def test_http_error_dilempar_sebagai_binance_api_error():
    client = BinanceFuturesClient(
        _kredensial_uji(), pembuka_url=_pembuka_error(400, -2010, "insufficient balance")
    )
    with pytest.raises(BinanceAPIError) as exc:
        client.kirim_order({"symbol": "BTCUSDT"})
    assert exc.value.kode == -2010
    assert exc.value.status == 400


def test_batalkan_order_delete_signed():
    tangkap = []
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka({}, tangkap=tangkap))
    client.batalkan_order("BTCUSDT", order_id=42)
    assert tangkap[0].get_method() == "DELETE"


def test_urutan_query_stabil_untuk_tandatangan():
    client = BinanceFuturesClient(_kredensial_uji())
    q1 = client._bangun_query({"b": 1, "a": 2}, signed=False)
    q2 = client._bangun_query({"a": 2, "b": 1}, signed=False)
    assert q1 == q2 == "a=2&b=1"


import asyncio

from lux_modul.eksekusi.binance_client import kirim_order_async


def test_kirim_order_async_membungkus_sinkron():
    client = BinanceFuturesClient(_kredensial_uji(), pembuka_url=_pembuka({"orderId": 7}))

    async def _jalan():
        return await kirim_order_async(client, {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT"})

    hasil = asyncio.run(_jalan())
    assert hasil == {"orderId": 7}
