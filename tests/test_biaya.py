"""Uji gerbang biaya universal (lux_modul/eksekusi/biaya.py).

Fokus: aturan harus universal, bebas dari besar saldo, dan tidak memihak strategi mana pun.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi.biaya import (
    FILL_KELUAR_MAKS,
    KODE_BIAYA_VS_RISIKO,
    KODE_TP1_TERLALU_DEKAT,
    batas_tp_efektif,
    biaya_pp_round_trip,
    evaluasi_biaya,
    jumlah_fill,
)
from lux_modul.eksekusi.risiko import ukuran_posisi
from lux_modul.kontrak import TargetTP


def test_jumlah_fill_dibatasi():
    assert jumlah_fill(1) == 2
    assert jumlah_fill(3) == 1 + 3
    assert jumlah_fill(10) == 1 + FILL_KELUAR_MAKS


def test_biaya_pp_naik_dengan_jumlah_tp_tapi_ada_plafon():
    b1 = biaya_pp_round_trip(1)
    b3 = biaya_pp_round_trip(3)
    b9 = biaya_pp_round_trip(9)
    assert b1 < b3
    assert b9 == b3  # plafon FILL_KELUAR_MAKS


def test_sl_terlalu_rapat_ditolak():
    # SL 0,05% dari entry: biaya round-trip pasti melebihi 20% dari 1R
    m = evaluasi_biaya(entry=100.0, sl=99.95, harga_tp=[100.5, 101.0])
    assert not m.lolos
    assert m.kode == KODE_BIAYA_VS_RISIKO
    assert m.rasio_biaya_risiko > 0.2


def test_sl_lebar_dengan_tp_jauh_lolos():
    # SL 3% dan TP 3%: biaya 21 bps vs 1R 3% -> rasio 0,07
    m = evaluasi_biaya(entry=100.0, sl=97.0, harga_tp=[103.0])
    assert m.lolos
    assert m.kode is None
    assert m.rasio_biaya_risiko < 0.2


def test_tp1_terlalu_dekat_ditolak_walau_sl_lebar():
    # SL lebar (lolos syarat pertama) tapi TP1 hanya 0,05% -> tidak menutup ongkos
    m = evaluasi_biaya(entry=100.0, sl=95.0, harga_tp=[100.05])
    assert not m.lolos
    assert m.kode == KODE_TP1_TERLALU_DEKAT


def test_rasio_biaya_tidak_bergantung_saldo():
    """Rasio biaya/risiko harus identik untuk saldo berapa pun (sifat matematis)."""
    entry, sl = 100.0, 98.0
    m = evaluasi_biaya(entry=entry, sl=sl, harga_tp=[104.0])
    for balance in (10.0, 1_000.0, 250_000.0):
        s = ukuran_posisi(balance=balance, entry=entry, sl=sl, leverage_maks=1e9)
        biaya = s.notional * m.biaya_pp
        assert abs(biaya / s.risk_usd - m.rasio_biaya_risiko) < 1e-9


def test_batas_tp_efektif_mempertahankan_total_porsi():
    tps = [
        TargetTP(harga=101.0, porsi=0.25),
        TargetTP(harga=102.0, porsi=0.25),
        TargetTP(harga=103.0, porsi=0.25),
        TargetTP(harga=104.0, porsi=0.25),
    ]
    hasil = batas_tp_efektif(tps, maks=3)
    assert len(hasil) == 3
    assert abs(sum(p for _, p in hasil) - 1.0) < 1e-12
    # target gabungan memakai harga TP terdekat dari ekor (konservatif)
    assert hasil[-1][0] == 103.0


def test_batas_tp_efektif_tidak_mengubah_bila_sudah_sedikit():
    tps = [TargetTP(harga=101.0, porsi=0.5), TargetTP(harga=102.0, porsi=0.5)]
    hasil = batas_tp_efektif(tps, maks=3)
    assert hasil == [(101.0, 0.5), (102.0, 0.5)]


def test_gerbang_tidak_melihat_identitas_strategi():
    """Dua rencana identik secara harga harus mendapat putusan sama, apa pun asalnya."""
    a = evaluasi_biaya(entry=50_000.0, sl=49_000.0, harga_tp=[52_000.0])
    b = evaluasi_biaya(entry=50_000.0, sl=49_000.0, harga_tp=[52_000.0])
    assert a.ringkas() == b.ringkas()
