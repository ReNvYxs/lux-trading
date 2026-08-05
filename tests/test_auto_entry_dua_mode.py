"""Kunci kontrak HORIZON_AUTO_ENTRY: WAJIB dua mode, Swing WAJIB dilarang.

Permintaan operator (5 Agu 2026): auto-entry harus bisa berjalan untuk Scalp
DAN Intraday sekaligus - bukan hanya salah satu - sementara Swing tetap tidak
boleh auto-entry sama sekali.

Isi `HORIZON_AUTO_ENTRY` memang sudah `(HORIZON_SCALPING, HORIZON_INTRADAY)`,
tapi sebelumnya tidak ada satu pun uji yang mengunci kontrak itu. Tanpa uji,
satu suntingan kecil (mis. menghapus salah satu elemen, atau menambahkan swing)
bisa lolos ke produksi tanpa terdeteksi. Berkas ini menutup celah tersebut.

Catatan desain: konstanta ini BUKAN mode ketiga dan bukan lapisan tambahan di
atas Scalp/Intraday. Ia adalah satu-satunya titik penegakan aturan "hanya Scalp
dan Intraday yang boleh auto-entry" di governor. Menghapusnya tidak
menyederhanakan apa pun - yang hilang justru penjaga yang mencegah Swing
ikut auto-entry.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.governor import (
    HORIZON_AUTO_ENTRY,
    TOLAK_BUKAN_AUTO_ENTRY,
    GovernorPortofolio,
    KandidatEntry,
    KebijakanPortofolio,
    SnapshotAkun,
)
from lux_modul.kontrak import HORIZON_INTRADAY, HORIZON_SCALPING


def _kandidat(horizon: str, simbol: str) -> KandidatEntry:
    return KandidatEntry(
        simbol=simbol,
        arah="LONG",
        entry_tf="5m",
        horizon=horizon,
        skor=80.0,
        margin_dibutuhkan=10.0,
        notional=100.0,
        leverage=10.0,
    )


def _governor() -> GovernorPortofolio:
    gov = GovernorPortofolio(KebijakanPortofolio(maks_posisi=4, min_free_margin_pct=0.0))
    gov.mulai_siklus(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0, posisi=()))
    return gov


def test_horizon_auto_entry_berisi_scalp_dan_intraday():
    """Dua-duanya, bukan salah satu."""
    assert HORIZON_SCALPING in HORIZON_AUTO_ENTRY
    assert HORIZON_INTRADAY in HORIZON_AUTO_ENTRY
    assert len(HORIZON_AUTO_ENTRY) == 2, (
        "HORIZON_AUTO_ENTRY harus tepat dua mode: scalp + intraday"
    )


def test_swing_tidak_pernah_masuk_auto_entry():
    """Horizon apa pun di luar dua mode itu wajib ditolak governor."""
    for horizon in ("swing", "SWING", "posisi", "", "apa_saja"):
        assert horizon not in HORIZON_AUTO_ENTRY


def test_governor_menerima_scalp_dan_intraday_bersamaan():
    """Bukti operasional: kedua mode bisa auto-entry dalam SATU siklus."""
    gov = _governor()
    gov.antre(_kandidat(HORIZON_SCALPING, "BTCUSDT"))
    gov.antre(_kandidat(HORIZON_INTRADAY, "ETHUSDT"))
    keputusan = gov.putuskan()
    assert len(keputusan) == 2
    assert all(k.diterima for k in keputusan), [k.alasan for k in keputusan]
    horizon_diterima = {k.kandidat.horizon for k in keputusan if k.diterima}
    assert horizon_diterima == {HORIZON_SCALPING, HORIZON_INTRADAY}


def test_governor_menolak_horizon_di_luar_auto_entry():
    gov = _governor()
    gov.antre(_kandidat("swing", "SOLUSDT"))
    keputusan = gov.putuskan()
    assert len(keputusan) == 1
    assert keputusan[0].diterima is False
    assert keputusan[0].alasan == TOLAK_BUKAN_AUTO_ENTRY


def test_swing_ditolak_tanpa_menghabiskan_kuota_scalp_intraday():
    """Penolakan swing tidak boleh memakan slot posisi milik dua mode lain."""
    gov = GovernorPortofolio(KebijakanPortofolio(maks_posisi=2, min_free_margin_pct=0.0))
    gov.mulai_siklus(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0, posisi=()))
    gov.antre(_kandidat("swing", "SOLUSDT"))
    gov.antre(_kandidat(HORIZON_SCALPING, "BTCUSDT"))
    gov.antre(_kandidat(HORIZON_INTRADAY, "ETHUSDT"))
    keputusan = gov.putuskan()
    diterima = {k.kandidat.simbol for k in keputusan if k.diterima}
    assert diterima == {"BTCUSDT", "ETHUSDT"}
    ditolak = [k for k in keputusan if not k.diterima]
    assert len(ditolak) == 1
    assert ditolak[0].kandidat.simbol == "SOLUSDT"
    assert ditolak[0].alasan == TOLAK_BUKAN_AUTO_ENTRY
