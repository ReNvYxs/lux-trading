"""Uji regresi serialisasi payload order ke Binance.

Dua galat NYATA dari log testnet operator (4 Agu 2026) direproduksi di sini:

- kode -4120 "Order type not supported for this endpoint" pada order SL.
  Sebabnya `closePosition=True` (bool Python) di-urlencode menjadi "True",
  sedangkan Binance hanya menerima "true". Karena flag itu tidak terbaca,
  STOP_MARKET dianggap tanpa quantity -> ditolak.
- kode -1111 "Precision is over the maximum defined for this asset".
  Sebabnya `str(float)` memakai notasi ilmiah untuk harga koin murah
  (0.00001234 -> "1.234e-05") dan menyisakan derau biner float
  (39.400000000000006).

Uji ini memeriksa QUERY STRING yang benar-benar dikirim, bukan dict payload,
karena bug-nya ada di tahap serialisasi - bukan di tahap perhitungan.
"""
from __future__ import annotations

import urllib.parse

from lux_modul.eksekusi.binance_client import _urutkan_query, format_nilai
from lux_modul.eksekusi.order import payload_entry, payload_sl
from lux_modul.kontrak import ARAH_LONG, ARAH_SHORT


def _urai(query: str) -> dict:
    return dict(urllib.parse.parse_qsl(query, keep_blank_values=True))


def test_boolean_diserialisasi_huruf_kecil():
    assert format_nilai(True) == "true"
    assert format_nilai(False) == "false"


def test_float_tidak_pernah_notasi_ilmiah():
    assert format_nilai(0.00001234) == "0.00001234"
    assert format_nilai(1e-08) == "0.00000001"
    assert "e" not in format_nilai(0.000000015).lower()


def test_float_tidak_membawa_derau_biner():
    assert format_nilai(39.400000000000006) == "39.4"
    assert format_nilai(0.1 + 0.2) == "0.3"


def test_float_bulat_tidak_berekor_titik_nol():
    assert format_nilai(3.0) == "3"
    assert format_nilai(20.0) == "20"


def test_nilai_lain_dibiarkan_apa_adanya():
    assert format_nilai("LIMIT") == "LIMIT"
    assert format_nilai(5) == 5


def test_query_sl_membawa_closeposition_huruf_kecil():
    """Regresi galat -4120."""
    p = payload_sl(simbol="AIOUSDT", arah=ARAH_LONG, stop_price=0.1234, tutup_posisi=True)
    q = _urai(_urutkan_query(p))
    assert q["closePosition"] == "true"
    assert "True" not in _urutkan_query(p)
    assert q["type"] == "STOP_MARKET"
    assert q["side"] == "SELL"
    assert q["workingType"] == "MARK_PRICE"


def test_query_sl_short_arah_terbalik():
    p = payload_sl(simbol="AIOUSDT", arah=ARAH_SHORT, stop_price=0.1234, tutup_posisi=True)
    q = _urai(_urutkan_query(p))
    assert q["side"] == "BUY"


def test_query_sl_parsial_memakai_reduceonly_huruf_kecil():
    p = payload_sl(
        simbol="AIOUSDT", arah=ARAH_LONG, stop_price=0.1234, qty=12.0, tutup_posisi=False
    )
    q = _urai(_urutkan_query(p))
    assert q["reduceOnly"] == "true"
    assert q["quantity"] == "12"


def test_query_entry_harga_kecil_tidak_ditolak_precision():
    """Regresi galat -1111 pada koin murah seperti 1000PEPEUSDT."""
    p = payload_entry(simbol="1000PEPEUSDT", arah=ARAH_LONG, qty=39.400000000000006, harga=0.00001234)
    teks = _urutkan_query(p)
    q = _urai(teks)
    assert q["price"] == "0.00001234"
    assert q["quantity"] == "39.4"
    assert "e-" not in teks


def test_query_entry_iceberg_ikut_diformat():
    p = payload_entry(
        simbol="BTCUSDT",
        arah=ARAH_SHORT,
        qty=0.30000000000000004,
        harga=60000.0,
        visible_qty=0.07500000000000001,
    )
    q = _urai(_urutkan_query(p))
    assert q["quantity"] == "0.3"
    assert q["price"] == "60000"
    assert q["icebergQty"] == "0.075"


def test_urutan_kunci_stabil_untuk_tanda_tangan():
    p = {"symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "price": 1.5}
    assert _urutkan_query(p) == _urutkan_query(dict(reversed(list(p.items()))))


def test_nilai_none_dibuang():
    assert "kosong" not in _urutkan_query({"symbol": "BTCUSDT", "kosong": None})
