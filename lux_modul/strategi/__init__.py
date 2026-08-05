"""L2 - registry strategi, dirakit dari katalog terbuka (plugin-based).

Tidak ada daftar strategi yang dipatok di berkas ini. Ada dua sumber:

1. KATALOG_STRATEGI - kelas Strategi utuh, didaftarkan lewat @daftar_strategi.
   12 strategi lama (pola.py / indikator.py / struktur_modern.py) ditulis
   sebelum arsitektur plugin ada, jadi didaftarkan terprogram di bawah. Ini
   BUKAN daftar istimewa -- hanya satu titik masuk ke katalog yang sama.
   Strategi baru cukup memakai @daftar_strategi langsung di modulnya sendiri.
2. KATALOG_POLA - detektor pattern murni, didaftarkan lewat @daftar_pola dan
   dibungkus otomatis jadi Strategi penuh oleh StrategiPola (lihat adaptor.py).

registry_bawaan() merakit Registry dari GABUNGAN kedua katalog itu. Menambah
strategi atau pola baru TIDAK PERNAH mengubah satu baris pun di berkas ini.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from ..plugin import (
    KATALOG_POLA,
    KATALOG_STRATEGI,
    daftar_strategi,
    muat_plugin,
    ringkas_katalog,
)
from .adaptor import StrategiPola
from .basis import HasilEvaluasi, Registry, Strategi
from .indikator import EmaBounce200, MacdRsiTrendBreak, RsiDivergence
from .pola import (
    CupAndHandle,
    DoubleBottom,
    DoubleTop,
    HeadShoulders,
    TriangleBreakout,
    WedgeBreakout,
)
from .struktur_modern import BreakoutVolume, IctLiquiditySweep, SmcOrderBlockFvg

# Impor untuk EFEK SAMPING dekorator @daftar_pola (mendaftarkan pattern baru ke
# KATALOG_POLA saat modulnya dieksekusi). Tidak ada simbol dari sini yang dipakai
# langsung -- itulah yang membuktikan arsitekturnya plugin-based.
from . import aliran_volume as _aliran_volume  # noqa: F401
from . import level_harga as _level_harga  # noqa: F401
from . import struktur_plus as _struktur_plus  # noqa: F401
from . import volatilitas as _volatilitas  # noqa: F401

# 12 strategi warisan fase-1, ditulis sebelum ada dekorator @daftar_strategi.
KELAS_BAWAAN: Tuple[type, ...] = (
    DoubleTop,
    DoubleBottom,
    HeadShoulders,
    TriangleBreakout,
    WedgeBreakout,
    CupAndHandle,
    EmaBounce200,
    RsiDivergence,
    MacdRsiTrendBreak,
    SmcOrderBlockFvg,
    IctLiquiditySweep,
    BreakoutVolume,
)


def _registrasi_bawaan() -> None:
    """Daftarkan KELAS_BAWAAN ke KATALOG_STRATEGI kalau belum ada.

    Dibuat idempotent (cek dulu, baru daftar) supaya aman dipanggil ulang
    setelah `bersihkan_katalog()` dipakai tes, tanpa memicu error id ganda.
    """
    for k in KELAS_BAWAAN:
        if getattr(k, "id", None) not in KATALOG_STRATEGI:
            daftar_strategi(k)


_registrasi_bawaan()


def semua_strategi(direktori_luar: Sequence[str] = ()) -> List[Strategi]:
    """Instansiasi satu strategi penuh untuk tiap entri katalog yang terdaftar."""
    if direktori_luar:
        muat_plugin(direktori_luar=direktori_luar)
    _registrasi_bawaan()
    instansi: List[Strategi] = [k() for k in KATALOG_STRATEGI.values()]
    instansi.extend(StrategiPola(spek) for spek in KATALOG_POLA.values())
    return instansi


def registry_bawaan(direktori_luar: Sequence[str] = ()) -> Registry:
    """Registry lengkap: seluruh strategi + pola terdaftar di katalog."""
    return Registry(semua_strategi(direktori_luar))


def registry_dari(nama: Sequence[str]) -> Registry:
    """Registry berisi sebagian strategi/pola saja (dipakai untuk uji terisolasi)."""
    _registrasi_bawaan()
    instansi: List[Strategi] = []
    hilang: List[str] = []
    for n in nama:
        if n in KATALOG_STRATEGI:
            instansi.append(KATALOG_STRATEGI[n]())
        elif n in KATALOG_POLA:
            instansi.append(StrategiPola(KATALOG_POLA[n]))
        else:
            hilang.append(n)
    if hilang:
        raise KeyError(f"strategi/pola tidak dikenal: {hilang}")
    return Registry(instansi)


def registry_kelompok(kelompok: str) -> Registry:
    """Registry hanya berisi strategi/pola dari satu kelompok teknik."""
    _registrasi_bawaan()
    instansi: List[Strategi] = [
        k() for k in KATALOG_STRATEGI.values() if getattr(k, "kelompok", None) == kelompok
    ]
    instansi.extend(StrategiPola(spek) for spek in KATALOG_POLA.values() if spek.kelompok == kelompok)
    return Registry(instansi)


def ringkas_registry(direktori_luar: Sequence[str] = ()) -> Dict[str, object]:
    """Ringkasan katalog + jumlah strategi yang benar-benar bisa dirakit."""
    if direktori_luar:
        muat_plugin(direktori_luar=direktori_luar)
    _registrasi_bawaan()
    ringkas = ringkas_katalog()
    ringkas["total_dirakit"] = len(KATALOG_STRATEGI) + len(KATALOG_POLA)
    kelompok = set()
    for k in KATALOG_STRATEGI.values():
        kelompok.add(getattr(k, "kelompok", None))
    for spek in KATALOG_POLA.values():
        kelompok.add(spek.kelompok)
    ringkas["kelompok_terwakili"] = sorted(k for k in kelompok if k)
    return ringkas


__all__ = [
    "Strategi",
    "Registry",
    "HasilEvaluasi",
    "StrategiPola",
    "KELAS_BAWAAN",
    "semua_strategi",
    "registry_bawaan",
    "registry_dari",
    "registry_kelompok",
    "ringkas_registry",
    "DoubleTop",
    "DoubleBottom",
    "HeadShoulders",
    "TriangleBreakout",
    "WedgeBreakout",
    "CupAndHandle",
    "EmaBounce200",
    "RsiDivergence",
    "MacdRsiTrendBreak",
    "SmcOrderBlockFvg",
    "IctLiquiditySweep",
    "BreakoutVolume",
]
