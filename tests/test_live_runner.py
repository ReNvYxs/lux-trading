"""Uji LiveRunner: bracket tracking (SL+TP setelah entry LIMIT terisi, OCO sederhana).

Fokus pada dua metode inti yang baru (4 Agu 2026): `_periksa_entry_pending()` dan
`_periksa_bracket_aktif()`. Kedua metode diuji terisolasi dari plane/pipeline karena
keduanya hanya bergantung pada `client` (Binance) + `notifier`, bukan pada data
historis/strategi - `LiveRunner` dibuat lewat `__new__` (tanpa `__init__` penuh) supaya
tidak perlu memuat riwayat klines.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi.order import KebijakanOrder
from lux_modul.kontrak import ARAH_LONG
from lux_modul.live_runner import (
    BRACKET_POLL_TIMEOUT_MS,
    MONITOR_TIMEOUT_MS,
    LiveRunner,
    _BracketAktif,
    _EntryPending,
)


class _ClientTiruan:
    """Client Binance tiruan: status_order/kirim_order/batalkan_order dikontrol test."""

    def __init__(self):
        self.status: dict = {}
        self.dibatalkan: list = []
        self.dikirim: list = []
        self._next_order_id = 100

    def status_order(self, simbol, order_id):
        return self.status[order_id]

    def batalkan_order(self, simbol, order_id):
        self.dibatalkan.append((simbol, order_id))

    def kirim_order(self, payload):
        self.dikirim.append(payload)
        self._next_order_id += 1
        return {"orderId": self._next_order_id}


class _NotifierTiruan:
    def __init__(self):
        self.entry_terisi: list = []
        self.sl_tertrigger: list = []
        self.tp_tertrigger: list = []

    def lapor_entry_terisi(self, **kw):
        self.entry_terisi.append(kw)

    def lapor_entry_dikirim(self, **kw):
        pass

    def lapor_sl_tertrigger(self, **kw):
        self.sl_tertrigger.append(kw)

    def lapor_tp_tertrigger(self, **kw):
        self.tp_tertrigger.append(kw)


def _runner_kosong(client=None, notifier=None, sekarang_ms=None):
    """LiveRunner minimal tanpa __init__ penuh (tidak butuh plane/pipeline)."""
    r = LiveRunner.__new__(LiveRunner)
    r.client = client or _ClientTiruan()
    r.simbol = "BTCUSDT"
    r.notifier = notifier
    r.kebijakan_order = KebijakanOrder()
    r._sekarang_ms = sekarang_ms or (lambda: 1_000_000)
    r._pending_entry = {}
    r._bracket_aktif = {}
    return r


def _entry_pending(order_id=1, sl=49_000.0, tp=51_000.0, dibuat_ms=0, arah=ARAH_LONG):
    return _EntryPending(
        order_id=order_id,
        simbol="BTCUSDT",
        arah=arah,
        sl_price=sl,
        tp_price=tp,
        qty=0.01,
        entry_price=50_000.0,
        dibuat_ms=dibuat_ms,
    )


def _bracket(sl_id=1, tp_id=2, arah=ARAH_LONG, dipasang_ms=0):
    return _BracketAktif(
        simbol="BTCUSDT",
        arah=arah,
        sl_order_id=sl_id,
        tp_order_id=tp_id,
        entry_price=50_000.0,
        sl_price=49_000.0,
        tp_price=51_000.0,
        qty=0.01,
        dipasang_ms=dipasang_ms,
    )


# ---------------------------------------------------------------------------- #
# _periksa_entry_pending
# ---------------------------------------------------------------------------- #


def test_entry_terisi_memasang_sl_dan_tp_lalu_lapor_notifier():
    client = _ClientTiruan()
    client.status[1] = {"status": "FILLED", "avgPrice": "50000.0", "executedQty": "0.01"}
    notifier = _NotifierTiruan()
    r = _runner_kosong(client=client, notifier=notifier, sekarang_ms=lambda: 10_000)
    r._pending_entry[1] = _entry_pending(order_id=1, dibuat_ms=0)

    galat = r._periksa_entry_pending()

    assert galat == []
    assert 1 not in r._pending_entry
    assert "BTCUSDT" in r._bracket_aktif
    br = r._bracket_aktif["BTCUSDT"]
    assert br.sl_price == 49_000.0 and br.tp_price == 51_000.0
    assert len(client.dikirim) == 2  # SL lalu TP
    assert client.dikirim[0]["type"] == "STOP_MARKET"
    assert client.dikirim[1]["type"] == "TAKE_PROFIT_MARKET"
    assert len(notifier.entry_terisi) == 1


def test_entry_tanpa_tp_hanya_kirim_sl():
    client = _ClientTiruan()
    client.status[1] = {"status": "FILLED", "avgPrice": "50000.0", "executedQty": "0.01"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: 10_000)
    r._pending_entry[1] = _entry_pending(order_id=1, tp=0.0, dibuat_ms=0)

    r._periksa_entry_pending()

    assert len(client.dikirim) == 1
    assert client.dikirim[0]["type"] == "STOP_MARKET"
    assert r._bracket_aktif["BTCUSDT"].tp_order_id is None


def test_entry_pending_dibatalkan_kalau_timeout():
    client = _ClientTiruan()
    client.status[1] = {"status": "NEW"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: BRACKET_POLL_TIMEOUT_MS + 1)
    r._pending_entry[1] = _entry_pending(order_id=1, dibuat_ms=0)

    r._periksa_entry_pending()

    assert 1 not in r._pending_entry
    assert ("BTCUSDT", 1) in client.dibatalkan
    assert "BTCUSDT" not in r._bracket_aktif


def test_entry_pending_belum_terisi_tetap_menunggu():
    client = _ClientTiruan()
    client.status[1] = {"status": "NEW"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: 1_000)
    r._pending_entry[1] = _entry_pending(order_id=1, dibuat_ms=0)

    galat = r._periksa_entry_pending()

    assert galat == []
    assert 1 in r._pending_entry
    assert client.dikirim == []


def test_entry_pending_canceled_dibuang_tanpa_bracket():
    client = _ClientTiruan()
    client.status[1] = {"status": "CANCELED"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: 1_000)
    r._pending_entry[1] = _entry_pending(order_id=1, dibuat_ms=0)

    r._periksa_entry_pending()

    assert 1 not in r._pending_entry
    assert "BTCUSDT" not in r._bracket_aktif


def test_status_order_galat_tidak_menghentikan_siklus():
    """Galat jaringan saat poll tidak boleh membuang entry dari pengawasan."""

    class _ClientGalat(_ClientTiruan):
        def status_order(self, simbol, order_id):
            raise RuntimeError("boom")

    r = _runner_kosong(client=_ClientGalat(), sekarang_ms=lambda: 1_000)
    r._pending_entry[1] = _entry_pending(order_id=1, dibuat_ms=0)

    galat = r._periksa_entry_pending()

    assert len(galat) == 1
    assert "status_order_1" in galat[0]
    assert 1 in r._pending_entry


def test_tanpa_pending_mengembalikan_kosong_cepat():
    r = _runner_kosong()
    assert r._periksa_entry_pending() == []


# ---------------------------------------------------------------------------- #
# _periksa_bracket_aktif
# ---------------------------------------------------------------------------- #


def test_sl_tertrigger_membatalkan_tp_dan_lapor_notifier():
    client = _ClientTiruan()
    client.status[1] = {"status": "FILLED"}
    client.status[2] = {"status": "NEW"}
    notifier = _NotifierTiruan()
    r = _runner_kosong(client=client, notifier=notifier, sekarang_ms=lambda: 1_000)
    r._bracket_aktif["BTCUSDT"] = _bracket()

    galat = r._periksa_bracket_aktif()

    assert galat == []
    assert "BTCUSDT" not in r._bracket_aktif
    assert ("BTCUSDT", 2) in client.dibatalkan
    assert len(notifier.sl_tertrigger) == 1
    assert notifier.tp_tertrigger == []


def test_tp_tertrigger_membatalkan_sl_dan_lapor_notifier():
    client = _ClientTiruan()
    client.status[1] = {"status": "NEW"}
    client.status[2] = {"status": "FILLED"}
    notifier = _NotifierTiruan()
    r = _runner_kosong(client=client, notifier=notifier, sekarang_ms=lambda: 1_000)
    r._bracket_aktif["BTCUSDT"] = _bracket()

    r._periksa_bracket_aktif()

    assert "BTCUSDT" not in r._bracket_aktif
    assert ("BTCUSDT", 1) in client.dibatalkan
    assert len(notifier.tp_tertrigger) == 1
    assert notifier.sl_tertrigger == []


def test_bracket_tanpa_tp_order_id_sl_tertrigger_tidak_error():
    client = _ClientTiruan()
    client.status[1] = {"status": "FILLED"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: 1_000)
    r._bracket_aktif["BTCUSDT"] = _bracket(tp_id=None)

    galat = r._periksa_bracket_aktif()

    assert galat == []
    assert "BTCUSDT" not in r._bracket_aktif
    assert client.dibatalkan == []


def test_bracket_belum_tertrigger_tetap_dipantau():
    client = _ClientTiruan()
    client.status[1] = {"status": "NEW"}
    client.status[2] = {"status": "NEW"}
    r = _runner_kosong(client=client, sekarang_ms=lambda: 1_000)
    r._bracket_aktif["BTCUSDT"] = _bracket()

    r._periksa_bracket_aktif()

    assert "BTCUSDT" in r._bracket_aktif
    assert client.dibatalkan == []


def test_bracket_timeout_dibersihkan_tanpa_notifikasi():
    client = _ClientTiruan()
    notifier = _NotifierTiruan()
    r = _runner_kosong(
        client=client, notifier=notifier, sekarang_ms=lambda: MONITOR_TIMEOUT_MS + 1
    )
    r._bracket_aktif["BTCUSDT"] = _bracket(dipasang_ms=0)

    r._periksa_bracket_aktif()

    assert "BTCUSDT" not in r._bracket_aktif
    assert notifier.sl_tertrigger == [] and notifier.tp_tertrigger == []


def test_tanpa_bracket_mengembalikan_kosong_cepat():
    r = _runner_kosong()
    assert r._periksa_bracket_aktif() == []
