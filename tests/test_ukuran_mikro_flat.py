"""Stress test lapis 3c: arah pembulatan qty pada aturan risiko flat 0,20.

KENAPA BERKAS INI ADA. Versi pertama aturan flat hanya membulatkan qty ke BAWAH
supaya risiko tidak pernah melewati 0,20. Terlihat aman, tetapi sweep 527 simbol
di testnet membuktikan itu MERUSAK aturannya: hanya 9 dari 504 simbol yang
benar-benar mempertaruhkan 0,20 USDT, sisanya jatuh jauh di bawah target karena
stepSize kasar. Bukti paling jelas ada di BNBUSDT: step 0,01 pada harga 712,91
berarti satu langkah qty bernilai 7,13 USDT notional, jadi membulatkan ke bawah
membuang sepertiga risiko yang seharusnya dipakai.

Angka di berkas ini memakai konstanta BNBUSDT testnet yang dibaca sendiri dari
exchangeInfo lewat sweep (harga 712,91, step/minQty 0,01, minNotional 5).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.ukuran_mikro import (
    RISIKO_FLAT_BAWAAN,
    TOLERANSI_RISIKO_BAWAAN,
    rencana_mikro,
)
from lux_modul.eksekusi_aman.inti import SpekSimbol

PLAFON = RISIKO_FLAT_BAWAAN * (1.0 + TOLERANSI_RISIKO_BAWAAN)


def bnb():
    # BNBUSDT testnet: step kasar relatif terhadap harga.
    return SpekSimbol(0.01, 0.01, 0.01, 10_000.0, 5.0, 3, 2)


def test_pembulatan_ke_atas_dipakai_bila_masih_di_dalam_plafon():
    harga = 712.91
    h = rencana_mikro(1.0, harga, bnb(), sl_harga=harga * 0.99, arah="LONG",
                      leverage_maks_bursa=75)
    assert h["notional_target_risiko"] == pytest.approx(20.0)
    assert h["qty_target_bawah"] == pytest.approx(0.02)
    assert h["qty_target_atas"] == pytest.approx(0.03)
    assert h["arah_pembulatan_target"] == "atas"
    assert h["qty"] == pytest.approx(0.03)
    assert h["notional"] == pytest.approx(21.3873)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.213873)
    assert h["rugi_pada_sl_usdt"] <= PLAFON
    assert h["risiko_flat_tercapai"] is True
    assert h["risiko_pct_dari_saldo"] == pytest.approx(21.3873)
    assert h["leverage_dipakai"] == 71
    assert h["margin_nyata"] == pytest.approx(0.30122958)
    assert h["jarak_likuidasi_pct"] == pytest.approx(1.0085)
    assert h["layak"] is True


def test_regresi_pembulatan_bawah_saja_akan_membuang_sepertiga_risiko():
    # Angka pembanding dari sweep sebelum perbaikan: qty 0,02 -> rugi 0,142582,
    # cuma 71% dari 0,20. Uji ini menjaga supaya perilaku itu tidak kembali.
    harga = 712.91
    jarak = harga - harga * 0.99
    assert 0.02 * jarak == pytest.approx(0.142582)
    assert 0.02 * jarak < RISIKO_FLAT_BAWAAN * 0.75
    h = rencana_mikro(1.0, harga, bnb(), sl_harga=harga * 0.99, arah="LONG",
                      leverage_maks_bursa=75)
    assert h["qty"] != pytest.approx(0.02)


def test_pembulatan_turun_ke_bawah_bila_ke_atas_melewati_plafon():
    # harga 900, SL 1% -> satu step qty bernilai 9 USDT notional. Target 20
    # jatuh di antara 0,02 (rugi 0,18) dan 0,03 (rugi 0,27 - lewat plafon).
    harga = 900.0
    h = rencana_mikro(1.0, harga, bnb(), sl_harga=harga * 0.99, arah="LONG",
                      leverage_maks_bursa=75)
    assert h["qty_target_bawah"] == pytest.approx(0.02)
    assert h["qty_target_atas"] == pytest.approx(0.03)
    assert 0.03 * 9.0 > PLAFON
    assert h["arah_pembulatan_target"] == "bawah"
    assert h["qty"] == pytest.approx(0.02)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.18)
    assert h["risiko_flat_tercapai"] is False
    assert h["margin_nyata"] == pytest.approx(0.25352113)
    assert h["layak"] is True


def test_plafon_tetap_dihormati_di_kedua_arah_pembulatan():
    # Sapuan kecil: apa pun harganya, risiko rencana yang layak tidak boleh
    # melewati plafon, dan likuidasi harus selalu lebih jauh daripada SL.
    for harga in (12.34, 99.5, 250.0, 712.91, 900.0, 4631.72):
        h = rencana_mikro(1.0, harga, bnb(), sl_harga=harga * 0.99,
                          arah="LONG", leverage_maks_bursa=75)
        if not h.get("layak"):
            continue
        assert h["rugi_pada_sl_usdt"] <= PLAFON + 1e-9
        assert h["jarak_likuidasi_pct"] > h["jarak_sl_pct"]
        assert h["margin_nyata"] <= 0.35 + 1e-9
