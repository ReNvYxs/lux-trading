"""Tambahan kelompok 'struktur_modern' - breaker block, MSS, FVG fill, OB retest.

Berkas ini menambah strategi SMC/ICT lewat @daftar_pola tanpa menyentuh
struktur_modern.py yang lama. Ini bukti konkret bahwa penambahan strategi tidak
memerlukan perubahan pada berkas yang sudah ada.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..fitur import struktur as st
from ..kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    KELOMPOK_STRUKTUR,
)
from ..plugin import Deteksi, daftar_pola
from .util import atr_kini, volume_breakout

_SUMBER_BREAKER = (
    "https://innercircletrader.net/tutorials/ict-breaker-block-trading/",
    "https://fluxcharts.com/articles/breaker-blocks-bb-explained",
    "https://atas.net/blog/what-are-ict-order-blocks-and-breaker-blocks-in-trading/",
)
_SUMBER_MSS = (
    "https://www.tradingwyckoff.com/en/smart-money-concepts/",
    "https://innercircletrader.net/tutorials/ict-market-structure-shift/",
)
_SUMBER_FVG = (
    "https://fluxcharts.com/articles/fair-value-gap-fvg-explained",
    "https://innercircletrader.net/tutorials/ict-fair-value-gap/",
)


def _skala(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (x - lo) / (hi - lo))))


@daftar_pola(
    "breaker_block",
    kelompok=KELOMPOK_STRUKTUR,
    ambang=65.0,
    warmup=160,
    konteks=1,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=0.9,
    rr=(2.0, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="Order block yang ditembus lalu diuji ulang dari sisi berlawanan (ICT breaker).",
    sumber=_SUMBER_BREAKER,
)
def _breaker_block(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 140:
        return None
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    c = np.asarray(b.close, dtype=float)
    o = np.asarray(b.open, dtype=float)
    atr = atr_kini(ctx)
    n = len(b) - 1

    peristiwa = ctx.fitur.peristiwa_struktur(b)
    if not peristiwa:
        return None
    pecah = [p for p in peristiwa if n - p.idx <= 40]
    if not pecah:
        return None
    ev = pecah[-1]

    arah_ob_dicari = "turun" if ev.arah == st.TREN_NAIK else "naik"
    ob = st.order_block_sebelum(b.open, b.high, b.low, b.close, ev.idx, arah_ob_dicari)
    if ob is None:
        return None
    # Breaker sejati: OB yang arahnya BERLAWANAN dengan arah pecahnya struktur.
    if ob.arah == ev.arah:
        return None

    zona_atas, zona_bawah = float(ob.atas), float(ob.bawah)
    if zona_atas <= zona_bawah:
        return None

    # Harga harus kembali menguji zona breaker pada bar ini.
    menyentuh = l[-1] <= zona_atas + 0.2 * atr and h[-1] >= zona_bawah - 0.2 * atr
    if not menyentuh:
        return None

    if ev.arah == st.TREN_NAIK:
        arah = ARAH_LONG
        if c[-1] <= o[-1]:
            return None
        invalid = zona_bawah - 0.2 * atr
    else:
        arah = ARAH_SHORT
        if c[-1] >= o[-1]:
            return None
        invalid = zona_atas + 0.2 * atr

    tebal = (zona_atas - zona_bawah) / max(atr, 1e-12)
    usia = n - ev.idx
    komponen = {
        "jenis_peristiwa": (1.0 if ev.jenis == "CHoCH" else 0.6, 1.0),
        "kesegaran_breaker": (1.0 - _skala(usia, 3.0, 40.0), 0.9),
        "zona_tidak_terlalu_tebal": (1.0 - _skala(tebal, 0.5, 4.0), 0.7),
        "konfirmasi_volume": (_skala(volume_breakout(ctx, 20), 0.8, 1.6), 0.6),
    }
    return Deteksi(
        arah=arah,
        level=float((zona_atas + zona_bawah) / 2.0),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "peristiwa": ev.jenis,
            "peristiwa_arah": ev.arah,
            "zona_atas": round(zona_atas, 10),
            "zona_bawah": round(zona_bawah, 10),
            "usia_bar": int(usia),
        },
        fitur=("peristiwa_struktur", "order_block"),
    )


@daftar_pola(
    "market_structure_shift",
    kelompok=KELOMPOK_STRUKTUR,
    ambang=63.0,
    warmup=150,
    konteks=1,
    horizon=(HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=1.0,
    rr=(1.5, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="CHoCH setelah sapuan likuiditas: pergeseran struktur pasar yang sah.",
    sumber=_SUMBER_MSS,
)
def _mss(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 130:
        return None
    n = len(b) - 1
    peristiwa = ctx.fitur.peristiwa_struktur(b)
    choch = [p for p in peristiwa if p.jenis == "CHoCH" and n - p.idx <= 6]
    if not choch:
        return None
    ev = choch[-1]

    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    c = np.asarray(b.close, dtype=float)
    atr = atr_kini(ctx)

    if ev.arah == st.TREN_NAIK:
        arah = ARAH_LONG
        dasar_baru = float(l[max(0, ev.idx - 12) : n + 1].min())
        invalid = dasar_baru - 0.2 * atr
        # Sapuan: sebelum CHoCH, harga menembus di bawah low sebelumnya lalu balik.
        sapuan = dasar_baru < float(l[max(0, ev.idx - 40) : max(1, ev.idx - 12)].min())
    else:
        arah = ARAH_SHORT
        puncak_baru = float(h[max(0, ev.idx - 12) : n + 1].max())
        invalid = puncak_baru + 0.2 * atr
        sapuan = puncak_baru > float(h[max(0, ev.idx - 40) : max(1, ev.idx - 12)].max())

    dorongan = abs(float(c[-1]) - float(ev.level)) / max(atr, 1e-12)
    komponen = {
        "ada_sapuan_likuiditas": (1.0 if sapuan else 0.35, 1.2),
        "kebaruan_choch": (1.0 - _skala(n - ev.idx, 0.0, 6.0), 0.9),
        "belum_terlalu_jauh": (1.0 - _skala(dorongan, 0.5, 3.0), 0.8),
    }
    return Deteksi(
        arah=arah,
        level=float(ev.level),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={"choch_level": round(float(ev.level), 10), "sapuan": bool(sapuan)},
        fitur=("peristiwa_struktur", "sapuan_likuiditas"),
    )


@daftar_pola(
    "fvg_fill",
    kelompok=KELOMPOK_STRUKTUR,
    ambang=61.0,
    warmup=130,
    konteks=1,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=0.9,
    rr=(1.5, 2.5),
    porsi=(0.5, 0.5),
    deskripsi="Harga kembali mengisi Fair Value Gap yang masih segar lalu bereaksi.",
    sumber=_SUMBER_FVG,
)
def _fvg_fill(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 120:
        return None
    atr = atr_kini(ctx)
    gaps = ctx.fitur.fvg(b)
    if not gaps:
        return None
    n = len(b) - 1
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    c = np.asarray(b.close, dtype=float)
    o = np.asarray(b.open, dtype=float)

    kandidat = [g for g in gaps if 3 <= n - g.idx <= 30 and (g.atas - g.bawah) >= 0.25 * atr]
    if not kandidat:
        return None
    g = kandidat[-1]

    # Gap harus belum pernah terisi penuh sebelum bar ini.
    sesudah = slice(g.idx + 1, n)
    if g.arah == st.TREN_NAIK:
        if sesudah.stop > sesudah.start and float(l[sesudah].min()) <= g.bawah:
            return None
        if not (l[-1] <= g.atas and c[-1] > g.bawah and c[-1] > o[-1]):
            return None
        arah = ARAH_LONG
        invalid = float(g.bawah) - 0.2 * atr
    else:
        if sesudah.stop > sesudah.start and float(h[sesudah].max()) >= g.atas:
            return None
        if not (h[-1] >= g.bawah and c[-1] < g.atas and c[-1] < o[-1]):
            return None
        arah = ARAH_SHORT
        invalid = float(g.atas) + 0.2 * atr

    ukuran = (g.atas - g.bawah) / max(atr, 1e-12)
    usia = n - g.idx
    komponen = {
        "ukuran_gap": (_skala(ukuran, 0.25, 1.5), 1.0),
        "kesegaran_gap": (1.0 - _skala(usia, 3.0, 30.0), 0.9),
        "reaksi_candle": (
            _skala(abs(c[-1] - o[-1]) / max(h[-1] - l[-1], 1e-12), 0.25, 0.7),
            0.8,
        ),
    }
    return Deteksi(
        arah=arah,
        level=float((g.atas + g.bawah) / 2.0),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "fvg_atas": round(float(g.atas), 10),
            "fvg_bawah": round(float(g.bawah), 10),
            "usia_bar": int(usia),
        },
        fitur=("fair_value_gaps",),
    )


@daftar_pola(
    "order_block_retest",
    kelompok=KELOMPOK_STRUKTUR,
    ambang=62.0,
    warmup=150,
    konteks=1,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=0.9,
    rr=(1.8, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="Uji ulang order block searah BOS terakhir, tanpa syarat FVG tumpang tindih.",
    sumber=_SUMBER_BREAKER,
)
def _ob_retest(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 140:
        return None
    n = len(b) - 1
    peristiwa = ctx.fitur.peristiwa_struktur(b)
    bos = [p for p in peristiwa if p.jenis == "BOS" and n - p.idx <= 30]
    if not bos:
        return None
    ev = bos[-1]

    ob = st.order_block_sebelum(b.open, b.high, b.low, b.close, ev.idx, ev.arah)
    if ob is None or ob.arah != ev.arah:
        return None

    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    c = np.asarray(b.close, dtype=float)
    o = np.asarray(b.open, dtype=float)
    atr = atr_kini(ctx)

    if not (l[-1] <= float(ob.atas) + 0.15 * atr and h[-1] >= float(ob.bawah) - 0.15 * atr):
        return None

    if ev.arah == st.TREN_NAIK:
        arah = ARAH_LONG
        if c[-1] <= o[-1]:
            return None
        invalid = float(ob.bawah) - 0.2 * atr
    else:
        arah = ARAH_SHORT
        if c[-1] >= o[-1]:
            return None
        invalid = float(ob.atas) + 0.2 * atr

    usia = n - ev.idx
    tebal = (float(ob.atas) - float(ob.bawah)) / max(atr, 1e-12)
    komponen = {
        "kesegaran_ob": (1.0 - _skala(usia, 2.0, 30.0), 1.0),
        "zona_rapat": (1.0 - _skala(tebal, 0.4, 3.0), 0.8),
        "konfirmasi_volume": (_skala(volume_breakout(ctx, 20), 0.8, 1.6), 0.7),
    }
    return Deteksi(
        arah=arah,
        level=float((ob.atas + ob.bawah) / 2.0),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "ob_atas": round(float(ob.atas), 10),
            "ob_bawah": round(float(ob.bawah), 10),
            "bos_level": round(float(ev.level), 10),
        },
        fitur=("peristiwa_struktur", "order_block"),
    )
