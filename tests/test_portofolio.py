"""Uji manajer slot portofolio: maks 4 posisi bersamaan, beda pair, sinyal terlewat dicatat."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.kontrak import ARAH_LONG, StrategyVerdict, TargetTP
from lux_modul.portofolio import (
    ALASAN_SIMBOL_SUDAH_ADA,
    ALASAN_SLOT_PENUH,
    MAKS_POSISI_BERSAMAAN,
    ManajerSlot,
    PosisiTerbuka,
)


def _posisi(simbol: str) -> PosisiTerbuka:
    return PosisiTerbuka(
        simbol=simbol,
        arah=ARAH_LONG,
        strategy_id="uji",
        kelompok="uji",
        ts_masuk=1,
        entry=100.0,
        sl=99.0,
        qty=1.0,
    )


def _verdict() -> StrategyVerdict:
    return StrategyVerdict(
        strategy_id="uji",
        kelompok="level_harga",
        arah=ARAH_LONG,
        skor=80.0,
        ambang=60.0,
        entry=100.0,
        sl=99.0,
        tps=(TargetTP(harga=103.0, porsi=1.0),),
        level=100.0,
        invalidation=99.0,
        tfs_used=("15m",),
    )


def test_default_empat_posisi():
    assert MAKS_POSISI_BERSAMAAN == 4
    assert ManajerSlot().maks_posisi == 4


def test_slot_penuh_menolak_simbol_kelima():
    m = ManajerSlot()
    for s in ("BTC", "ETH", "SOL", "XRP"):
        m.buka(_posisi(s))
    assert m.jumlah_terbuka == 4
    assert m.slot_tersisa == 0
    assert m.alasan_tolak("DOGE") == ALASAN_SLOT_PENUH
    with pytest.raises(RuntimeError):
        m.buka(_posisi("DOGE"))


def test_satu_simbol_tidak_boleh_dua_posisi():
    m = ManajerSlot()
    m.buka(_posisi("BTC"))
    assert m.alasan_tolak("BTC") == ALASAN_SIMBOL_SUDAH_ADA


def test_slot_bebas_setelah_tutup():
    m = ManajerSlot()
    for s in ("BTC", "ETH", "SOL", "XRP"):
        m.buka(_posisi(s))
    m.tutup("ETH")
    assert m.boleh_masuk("DOGE")
    m.buka(_posisi("DOGE"))
    assert m.jumlah_terbuka == 4


def test_sinyal_terlewat_dicatat_lengkap():
    m = ManajerSlot()
    for s in ("BTC", "ETH", "SOL", "XRP"):
        m.buka(_posisi(s))
    s = m.catat_terlewat(ts=1234, simbol="DOGE", verdict=_verdict(), alasan=ALASAN_SLOT_PENUH)
    assert s.simbol == "DOGE"
    assert s.alasan == ALASAN_SLOT_PENUH
    assert s.tp1 == 103.0
    assert abs(s.r_teoretis - 3.0) < 1e-9
    assert s.simbol_pemegang_slot == ["BTC", "ETH", "SOL", "XRP"]
    r = m.ringkas_terlewat()
    assert r["jumlah"] == 1
    assert r["per_alasan"][ALASAN_SLOT_PENUH] == 1
    assert r["per_strategi"]["uji"] == 1


def test_manajer_tidak_memilih_berdasarkan_kualitas():
    """Kapasitas tidak boleh melihat skor: dua sinyal berbeda skor diperlakukan sama."""
    m = ManajerSlot(maks_posisi=1)
    m.buka(_posisi("BTC"))
    assert m.alasan_tolak("ETH") == ALASAN_SLOT_PENUH
    assert m.alasan_tolak("SOL") == ALASAN_SLOT_PENUH
