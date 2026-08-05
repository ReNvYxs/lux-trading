"""Kelompok 'aliran_volume' - VWAP dan Volume Profile.

Seluruh isi berkas ini didaftarkan lewat @daftar_pola. Tidak ada satu baris pun di
L3 (arbiter) atau L4 (eksekusi) yang perlu disunting agar strategi di sini ikut
dinilai. Itulah bukti arsitekturnya benar-benar plugin-based.

Catatan kejujuran: strategi berbasis CVD sengaja TIDAK ada di sini karena dataset
hanya OHLCV, bukan data order-flow/tick. Lihat CALON_STRATEGI.md di root repo.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    KELOMPOK_ALIRAN,
)
from ..plugin import Deteksi, daftar_pola
from .util import atr_kini, volume_breakout

_SUMBER_VWAP = (
    "https://www.investopedia.com/ask/answers/031115/what-common-strategy-traders-implement-when-using-volume-weighted-average-price-vwap.asp",
    "https://www.trademomentum.org/blog/vwap-pullback-trading-strategy-for-day-traders",
    "https://scanz.com/vwap-trading-strategy/",
)
_SUMBER_VWAP_REVERSI = (
    "https://crosstrade.io/learn/trading-strategies/vwap-reversion",
    "https://thevwap.com/vwap/",
)
_SUMBER_VP = (
    "https://www.quantvps.com/blog/value-area-trading-strategy-guide",
    "https://trendspider.com/learning-center/volume-profile-strategies/",
    "https://www.tastylive.com/news-insights/what-volume-profile-how-to-trade-it",
)


def _skala(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (x - lo) / (hi - lo))))


# --------------------------------------------------------------------------- #
# VWAP reclaim (kelanjutan tren)
# --------------------------------------------------------------------------- #


@daftar_pola(
    "vwap_reclaim",
    kelompok=KELOMPOK_ALIRAN,
    ambang=62.0,
    warmup=120,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=1.0,
    rr=(1.5, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="Harga menembus balik VWAP sesi setelah flush singkat, searah tren EMA.",
    sumber=_SUMBER_VWAP,
)
def _vwap_reclaim(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 60:
        return None
    vwap = ctx.fitur.hitung("vwap_sesi", b)
    c = np.asarray(b.close, dtype=float)
    if not np.isfinite(vwap[-1]):
        return None

    ema50 = ctx.fitur.ema(b, 50)
    ema200 = ctx.fitur.ema(b, 200) if len(b) >= 200 else ema50
    if not np.isfinite(ema50[-1]):
        return None

    # Reclaim = beberapa bar terakhir sempat di sisi berlawanan VWAP, bar ini balik.
    lihat = 6
    di_bawah = c[-lihat - 1 : -1] < vwap[-lihat - 1 : -1]
    di_atas = c[-lihat - 1 : -1] > vwap[-lihat - 1 : -1]

    atr = atr_kini(ctx)
    jarak = abs(c[-1] - vwap[-1])
    # Entry harus DEKAT VWAP; kalau sudah jauh, itu mengejar, bukan reclaim.
    if jarak > 0.8 * atr:
        return None

    tren_naik = ema50[-1] > ema200[-1]
    tren_turun = ema50[-1] < ema200[-1]

    if c[-1] > vwap[-1] and di_bawah.any() and tren_naik:
        arah = ARAH_LONG
        flush = float(np.min(np.asarray(b.low, dtype=float)[-lihat:]))
        invalid = min(flush, vwap[-1]) - 0.2 * atr
        sisi = float(di_bawah.mean())
    elif c[-1] < vwap[-1] and di_atas.any() and tren_turun:
        arah = ARAH_SHORT
        flush = float(np.max(np.asarray(b.high, dtype=float)[-lihat:]))
        invalid = max(flush, vwap[-1]) + 0.2 * atr
        sisi = float(di_atas.mean())
    else:
        return None

    vol = volume_breakout(ctx, 20)
    pisah = abs(ema50[-1] - ema200[-1]) / max(atr, 1e-12)

    komponen = {
        "kedalaman_flush": (_skala(sisi, 0.15, 0.85), 1.0),
        "kerapatan_ke_vwap": (1.0 - _skala(jarak / max(atr, 1e-12), 0.0, 0.8), 1.0),
        "konfirmasi_volume": (_skala(vol, 0.9, 1.8), 1.0),
        "pemisahan_tren": (_skala(pisah, 0.1, 1.5), 0.8),
    }
    return Deteksi(
        arah=arah,
        level=float(vwap[-1]),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "vwap": round(float(vwap[-1]), 10),
            "jarak_atr": round(jarak / max(atr, 1e-12), 4),
            "rasio_volume": round(vol, 4),
            "bar_di_sisi_lawan": int(sisi * lihat),
        },
        fitur=("vwap_sesi", "ema50", "ema200", "rasio_volume"),
    )


# --------------------------------------------------------------------------- #
# VWAP mean reversion (fade pita deviasi)
# --------------------------------------------------------------------------- #


@daftar_pola(
    "vwap_reversi_pita",
    kelompok=KELOMPOK_ALIRAN,
    ambang=63.0,
    warmup=150,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=1.2,
    rr=(1.0, 2.0),
    porsi=(0.6, 0.4),
    deskripsi="Fade peregangan ekstrem dari VWAP saat rezim menyamping (ADX rendah).",
    sumber=_SUMBER_VWAP_REVERSI,
)
def _vwap_reversi(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 80:
        return None
    atas, vwap, bawah = ctx.fitur.hitung("vwap_pita", b, 86_400_000, 2.0)
    c = np.asarray(b.close, dtype=float)
    if not np.isfinite(atas[-1]) or atas[-1] <= bawah[-1]:
        return None

    # Filter rezim WAJIB: reversi ke VWAP gagal parah di hari tren kuat.
    adx_nilai, _, _ = ctx.fitur.hitung("adx", b, 14)
    if not np.isfinite(adx_nilai[-1]) or adx_nilai[-1] > 25.0:
        return None

    atr = atr_kini(ctx)
    lebar = float(atas[-1] - vwap[-1])
    if lebar <= 0:
        return None

    if c[-1] > atas[-1] and c[-2] > atas[-2]:
        arah = ARAH_SHORT
        rentang = float(np.max(np.asarray(b.high, dtype=float)[-5:]))
        invalid = rentang + 0.4 * atr
        regang = (c[-1] - vwap[-1]) / lebar
    elif c[-1] < bawah[-1] and c[-2] < bawah[-2]:
        arah = ARAH_LONG
        rentang = float(np.min(np.asarray(b.low, dtype=float)[-5:]))
        invalid = rentang - 0.4 * atr
        regang = (vwap[-1] - c[-1]) / lebar
    else:
        return None

    komponen = {
        "peregangan": (_skala(regang, 1.0, 2.2), 1.2),
        "rezim_menyamping": (1.0 - _skala(float(adx_nilai[-1]), 10.0, 25.0), 1.0),
        "lebar_pita_sehat": (_skala(lebar / max(atr, 1e-12), 0.5, 3.0), 0.6),
    }
    return Deteksi(
        arah=arah,
        level=float(vwap[-1]),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "vwap": round(float(vwap[-1]), 10),
            "pita_atas": round(float(atas[-1]), 10),
            "pita_bawah": round(float(bawah[-1]), 10),
            "adx": round(float(adx_nilai[-1]), 3),
            "peregangan_sigma": round(float(regang), 4),
        },
        fitur=("vwap_pita", "adx"),
    )


# --------------------------------------------------------------------------- #
# Volume Profile: penolakan di tepi value area
# --------------------------------------------------------------------------- #


@daftar_pola(
    "vp_tepi_value_area",
    kelompok=KELOMPOK_ALIRAN,
    ambang=61.0,
    warmup=280,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=1.0,
    rr=(1.2, 2.5),
    porsi=(0.5, 0.5),
    deskripsi="Harga ditolak di VAH/VAL lalu berputar kembali ke arah POC.",
    sumber=_SUMBER_VP,
)
def _vp_tepi(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 260:
        return None
    profil = ctx.fitur.hitung("volume_profile", b, 240, 48, 0.70)
    if profil is None:
        return None

    c = np.asarray(b.close, dtype=float)
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    atr = atr_kini(ctx)
    toleransi = 0.5 * atr

    # Penolakan di VAH: bar menyentuh VAH lalu menutup kembali di dalam value area.
    sentuh_atas = h[-1] >= profil.vah - toleransi and c[-1] < profil.vah
    sentuh_bawah = l[-1] <= profil.val + toleransi and c[-1] > profil.val

    # POC harus punya ruang gerak yang berarti dari harga sekarang.
    ruang = abs(profil.poc - c[-1]) / max(atr, 1e-12)
    if ruang < 0.8:
        return None

    if sentuh_atas and profil.poc < c[-1]:
        arah = ARAH_SHORT
        invalid = float(max(h[-1], profil.vah)) + 0.3 * atr
        level = profil.vah
        sumbu = (h[-1] - max(c[-1], b.open[-1])) / max(h[-1] - l[-1], 1e-12)
    elif sentuh_bawah and profil.poc > c[-1]:
        arah = ARAH_LONG
        invalid = float(min(l[-1], profil.val)) - 0.3 * atr
        level = profil.val
        sumbu = (min(c[-1], b.open[-1]) - l[-1]) / max(h[-1] - l[-1], 1e-12)
    else:
        return None

    lebar_va = (profil.vah - profil.val) / max(atr, 1e-12)
    komponen = {
        "penolakan_sumbu": (_skala(float(sumbu), 0.2, 0.7), 1.0),
        "ruang_ke_poc": (_skala(ruang, 0.8, 4.0), 1.0),
        "value_area_terbentuk": (_skala(lebar_va, 2.0, 12.0), 0.7),
    }
    return Deteksi(
        arah=arah,
        level=float(level),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "poc": round(profil.poc, 10),
            "vah": round(profil.vah, 10),
            "val": round(profil.val, 10),
            "ruang_ke_poc_atr": round(ruang, 3),
        },
        fitur=("volume_profile",),
    )
