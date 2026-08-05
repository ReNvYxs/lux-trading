"""Uji presisi kontrak, LEVERAGE OTOMATIS, BEP, dan RR BERSIH.

Prinsip yang diuji (perintah operator 4 Agu 2026):
    Risk -> Position Size/Notional -> Required Margin -> Optimal Leverage
BUKAN sebaliknya. Tidak boleh ada leverage statis, dan risiko nominal tidak
boleh naik hanya karena leverage tersedia lebih besar.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.spesifikasi import (
    TOLAK_LEVERAGE_MAKS,
    TOLAK_NOTIONAL_MIN,
    TOLAK_QTY_NOL,
    TOLAK_RR_BERSIH,
    SpesifikasiKontrak,
    bulatkan_ke_kelipatan,
    ekonomi_trade,
    harga_break_even,
    rencana_posisi,
)
from lux_modul.eksekusi.risiko import risiko_usd
from lux_modul.kontrak import ARAH_LONG, ARAH_SHORT

SPEK_BTC = SpesifikasiKontrak(
    simbol="BTCUSDT",
    tick_size=0.1,
    step_size=0.001,
    min_qty=0.001,
    min_notional=5.0,
    presisi_harga=1,
    presisi_qty=3,
    leverage_maks_simbol=125.0,
    bracket=((50_000.0, 125.0), (250_000.0, 100.0), (1_000_000.0, 50.0)),
)

SPEK_ALT = SpesifikasiKontrak(
    simbol="DOGEUSDT",
    tick_size=0.00001,
    step_size=1.0,
    min_qty=1.0,
    min_notional=5.0,
    presisi_harga=5,
    presisi_qty=0,
    leverage_maks_simbol=75.0,
    bracket=((5_000.0, 75.0), (25_000.0, 50.0)),
)


# --------------------------------------------------------------------- #
# pembulatan presisi
# --------------------------------------------------------------------- #


def test_pembulatan_kelipatan_tidak_meninggalkan_galat_float():
    assert bulatkan_ke_kelipatan(0.1 + 0.2, 0.1) == 0.3
    assert bulatkan_ke_kelipatan(60000.07, 0.1, "bawah") == 60000.0
    assert bulatkan_ke_kelipatan(60000.07, 0.1, "atas") == 60000.1
    # kelipatan 0 = tidak dibulatkan (spek generik)
    assert bulatkan_ke_kelipatan(1.23456789, 0.0) == 1.23456789


def test_qty_dibulatkan_ke_bawah_agar_risiko_tidak_membengkak():
    q = SPEK_BTC.bulat_qty(0.0019999)
    assert q == 0.001


def test_sl_dibulatkan_menjauh_dan_tp_mendekat():
    # LONG: SL turun (menjauh), TP turun (mendekat) -> keduanya konservatif
    r = rencana_posisi("BTCUSDT", ARAH_LONG, 1000.0, 60000.04, 59700.07, 60900.09, spek=SPEK_BTC)
    assert r.entry == 60000.0
    assert r.sl == 59700.0  # dibulatkan ke bawah = jarak risiko sedikit lebih besar
    assert r.ekonomi is not None and r.ekonomi.tp_utama == 60900.0
    # SHORT: SL naik, TP naik
    r2 = rencana_posisi("BTCUSDT", ARAH_SHORT, 1000.0, 60000.04, 60300.02, 59100.02, spek=SPEK_BTC)
    assert r2.sl == 60300.1
    assert r2.ekonomi is not None and r2.ekonomi.tp_utama == 59100.1


def test_batas_leverage_mengikuti_bracket_notional():
    assert SPEK_BTC.leverage_untuk_notional(1_000.0) == 125.0
    assert SPEK_BTC.leverage_untuk_notional(100_000.0) == 100.0
    assert SPEK_BTC.leverage_untuk_notional(900_000.0) == 50.0
    assert SPEK_BTC.leverage_untuk_notional(9_000_000.0) == 50.0  # di atas bracket terakhir


def test_spek_dibangun_dari_exchange_info():
    spek = SpesifikasiKontrak.dari_exchange_info(
        {
            "symbol": "ETHUSDT",
            "pricePrecision": 2,
            "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        },
        bracket=[{"notionalCap": 50000, "initialLeverage": 75}, {"notionalCap": 250000, "initialLeverage": 50}],
    )
    assert spek.tick_size == 0.01
    assert spek.step_size == 0.001
    assert spek.min_notional == 5.0
    assert spek.leverage_maks_simbol == 75.0
    assert spek.leverage_untuk_notional(100_000.0) == 50.0


# --------------------------------------------------------------------- #
# leverage otomatis
# --------------------------------------------------------------------- #


def test_leverage_adalah_hasil_bukan_input():
    r = rencana_posisi("BTCUSDT", ARAH_LONG, 1000.0, 60000.0, 59700.0, 60900.0, spek=SPEK_BTC)
    assert r.layak
    # notional = qty * entry, margin = notional / leverage
    assert r.notional == pytest.approx(r.qty * r.entry)
    assert r.margin_dibutuhkan == pytest.approx(r.notional / r.leverage_optimal)
    # leverage bilangan bulat >= 1, cukup untuk menutup notional dengan margin
    assert r.leverage_optimal >= 1
    assert r.leverage_optimal * (1000.0 * 0.5) >= r.notional - 1e-6


def test_leverage_berbeda_antar_setup_tidak_statis():
    hasil = set()
    for sl in (59_700.0, 59_400.0, 58_800.0, 57_600.0):
        r = rencana_posisi("BTCUSDT", ARAH_LONG, 1000.0, 60_000.0, sl, 61_000.0, spek=SPEK_BTC)
        hasil.add(r.leverage_optimal)
    # jarak SL berbeda -> notional berbeda -> leverage optimal berbeda
    assert len(hasil) > 1, f"leverage tampak statis: {hasil}"


def test_leverage_tidak_menaikkan_risiko_nominal():
    """Batas leverage operator yang lebih longgar TIDAK boleh membesarkan risiko."""
    a = rencana_posisi(
        "BTCUSDT", ARAH_LONG, 1000.0, 60_000.0, 59_700.0, 60_900.0, spek=SPEK_BTC,
        leverage_batas_operator=5.0,
    )
    b = rencana_posisi(
        "BTCUSDT", ARAH_LONG, 1000.0, 60_000.0, 59_700.0, 60_900.0, spek=SPEK_BTC,
        leverage_batas_operator=125.0,
    )
    assert a.qty == b.qty
    assert a.notional == b.notional
    assert a.risk_usd == b.risk_usd == risiko_usd(1000.0)


def test_risiko_qty_konsisten_dengan_jarak_sl():
    saldo = 500.0
    r = rencana_posisi("BTCUSDT", ARAH_LONG, saldo, 60_000.0, 59_400.0, 61_200.0, spek=SPEK_BTC)
    r_usd = risiko_usd(saldo)
    # qty hasil pembulatan ke bawah -> risiko harga <= anggaran risiko
    assert r.qty * r.jarak_sl <= r_usd + 1e-9
    assert r.qty * r.jarak_sl > r_usd * 0.5  # tidak boleh jauh menyusut


def test_setup_ditolak_bila_butuh_leverage_di_atas_batas():
    spek = SpesifikasiKontrak(
        simbol="XUSDT", tick_size=0.01, step_size=0.001, min_qty=0.001,
        leverage_maks_simbol=3.0, bracket=((1_000_000.0, 3.0),),
    )
    # SL sangat rapat -> qty besar -> notional besar -> butuh leverage tinggi
    r = rencana_posisi("XUSDT", ARAH_LONG, 1000.0, 100.0, 99.99, 100.5, spek=spek)
    assert not r.layak
    assert r.kode == TOLAK_LEVERAGE_MAKS
    assert r.catatan  # ada penjelasan, bukan diam-diam menaikkan risiko


def test_setup_ditolak_bila_di_bawah_min_notional():
    r = rencana_posisi("DOGEUSDT", ARAH_LONG, 12.0, 0.1, 0.05, 0.2, spek=SPEK_ALT)
    assert not r.layak
    assert r.kode in (TOLAK_NOTIONAL_MIN, TOLAK_QTY_NOL)


def test_saldo_terlalu_kecil_untuk_step_size_ditolak_bukan_dipaksakan():
    # saldo $5 + SL lebar $1.000 -> qty ideal 0,0002 BTC, di bawah step 0,001.
    # Sistem harus MENOLAK, bukan membulatkan ke atas (itu akan melipatgandakan risiko).
    r = rencana_posisi("BTCUSDT", ARAH_LONG, 5.0, 60_000.0, 59_000.0, 63_000.0, spek=SPEK_BTC)
    assert not r.layak
    assert r.kode == TOLAK_QTY_NOL
    assert r.catatan


def test_saldo_kecil_dengan_sl_rapat_tetap_layak_dan_risikonya_tetap_kecil():
    r = rencana_posisi("BTCUSDT", ARAH_LONG, 5.0, 60_000.0, 59_940.0, 60_180.0, spek=SPEK_BTC)
    assert r.layak
    # meski leverage tinggi, risiko harga tetap <= anggaran risiko akun
    assert r.qty * r.jarak_sl <= risiko_usd(5.0) + 1e-9
    assert r.margin_dibutuhkan <= 5.0


# --------------------------------------------------------------------- #
# BEP dan RR bersih
# --------------------------------------------------------------------- #


def test_bep_sadar_arah_posisi():
    assert harga_break_even(ARAH_LONG, 100.0) > 100.0
    assert harga_break_even(ARAH_SHORT, 100.0) < 100.0
    with pytest.raises(ValueError):
        harga_break_even("naik", 100.0)


def test_rr_bersih_selalu_lebih_kecil_dari_rr_kotor():
    for arah, sl, tp in ((ARAH_LONG, 99.0, 103.0), (ARAH_SHORT, 101.0, 97.0)):
        e = ekonomi_trade(arah, 100.0, sl, tp)
        assert e.rr_kotor == pytest.approx(3.0)
        assert e.rr_bersih < e.rr_kotor
        assert e.rr_bersih > 0


def test_rr_bersih_simetris_untuk_long_dan_short():
    a = ekonomi_trade(ARAH_LONG, 100.0, 99.0, 103.0)
    b = ekonomi_trade(ARAH_SHORT, 100.0, 101.0, 97.0)
    assert a.rr_bersih == pytest.approx(b.rr_bersih)


def test_rr_bersih_negatif_bila_tp_di_dalam_bep():
    e = ekonomi_trade(ARAH_LONG, 100.0, 99.0, 100.01)  # TP di bawah BEP
    assert e.imbalan_bersih_frac < 0
    assert e.rr_bersih < 0


def test_funding_membebani_kedua_jalur():
    tanpa = ekonomi_trade(ARAH_LONG, 100.0, 99.0, 103.0, funding_bps=0.0)
    dengan = ekonomi_trade(ARAH_LONG, 100.0, 99.0, 103.0, funding_bps=3.0)
    assert dengan.rr_bersih < tanpa.rr_bersih
    assert dengan.risiko_bersih_frac > tanpa.risiko_bersih_frac


def test_gerbang_rr_bersih_minimum_menolak_setup():
    r = rencana_posisi(
        "BTCUSDT", ARAH_LONG, 1000.0, 60_000.0, 59_700.0, 60_150.0, spek=SPEK_BTC,
        rr_bersih_min=2.0,
    )
    assert not r.layak
    assert r.kode == TOLAK_RR_BERSIH


def test_arah_tidak_sah_ditolak():
    with pytest.raises(ValueError):
        rencana_posisi("BTCUSDT", "long", 1000.0, 60_000.0, 59_700.0, spek=SPEK_BTC)
