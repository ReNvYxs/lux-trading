"""Kelompok 'volatilitas_rezim' - squeeze, breakout channel, dan pembalikan tren ATR.

Semua didaftarkan lewat @daftar_pola. Core engine tidak berubah sedikit pun.
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
    KELOMPOK_VOLATILITAS,
)
from ..plugin import Deteksi, daftar_pola
from .util import atr_kini, volume_breakout

_SUMBER_SQUEEZE = (
    "https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze",
    "https://trendspider.com/learning-center/bb-kc-squeeze-a-powerful-indicator-for-trading-range-breakouts/",
)
_SUMBER_DONCHIAN = (
    "https://crosstrade.io/learn/technical-indicators/donchian-channels",
    "https://www.altrady.com/blog/crypto-trading-strategies/donchian-channel-strategy",
)
_SUMBER_SUPERTREND = (
    "https://www.investopedia.com/supertrend-indicator-7976167",
)
_SUMBER_KELTNER = (
    "https://www.quantifiedstrategies.com/keltner-bands-trading-strategies/",
)


def _skala(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (x - lo) / (hi - lo))))


@daftar_pola(
    "squeeze_breakout",
    kelompok=KELOMPOK_VOLATILITAS,
    ambang=62.0,
    warmup=140,
    konteks=1,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=1.2,
    rr=(1.5, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="Bollinger terkurung di dalam Keltner lalu harga menutup keluar pita, dengan volume.",
    sumber=_SUMBER_SQUEEZE,
)
def _squeeze_breakout(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 120:
        return None
    sq = ctx.fitur.hitung("squeeze_bb_kc", b, 20, 2.0, 1.5)
    bb_atas, bb_tengah, bb_bawah = ctx.fitur.bollinger(b, 20, 2.0)
    c = np.asarray(b.close, dtype=float)
    if not np.isfinite(sq[-1]) or not np.isfinite(bb_atas[-1]):
        return None

    # Squeeze harus BARU SAJA lepas: bar ini tidak lagi squeeze, tapi baru saja iya.
    if sq[-1] != 0.0:
        return None
    lihat = sq[-13:-1]
    lihat = lihat[np.isfinite(lihat)]
    if lihat.size < 6:
        return None
    durasi = float(lihat.sum())
    if durasi < 4:
        return None

    atr = atr_kini(ctx)
    if c[-1] > bb_atas[-1]:
        arah = ARAH_LONG
        invalid = float(bb_tengah[-1]) - 0.2 * atr
        level = float(bb_atas[-1])
    elif c[-1] < bb_bawah[-1]:
        arah = ARAH_SHORT
        invalid = float(bb_tengah[-1]) + 0.2 * atr
        level = float(bb_bawah[-1])
    else:
        return None

    vol = volume_breakout(ctx, 20)
    dorongan = abs(c[-1] - float(bb_tengah[-1])) / max(atr, 1e-12)

    komponen = {
        "durasi_squeeze": (_skala(durasi, 4.0, 12.0), 1.0),
        "konfirmasi_volume": (_skala(vol, 1.0, 2.0), 1.1),
        "kekuatan_dorongan": (_skala(dorongan, 0.8, 3.0), 0.9),
    }
    return Deteksi(
        arah=arah,
        level=level,
        invalidation=invalid,
        komponen=komponen,
        bukti={"bar_squeeze": int(durasi), "rasio_volume": round(vol, 4)},
        fitur=("squeeze_bb_kc", "bollinger", "rasio_volume"),
    )


@daftar_pola(
    "donchian_breakout",
    kelompok=KELOMPOK_VOLATILITAS,
    ambang=60.0,
    warmup=120,
    konteks=1,
    horizon=(HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=2.0,
    rr=(1.5, 3.5),
    porsi=(0.5, 0.5),
    deskripsi="Tembus Donchian 20 bar (turtle) dengan stop 2 ATR; channel digeser 1 bar.",
    sumber=_SUMBER_DONCHIAN,
)
def _donchian_breakout(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 100:
        return None
    atas, bawah = ctx.fitur.hitung("donchian", b, 20)
    if not np.isfinite(atas[-1]) or not np.isfinite(atas[-2]):
        return None
    c = np.asarray(b.close, dtype=float)
    atr = atr_kini(ctx)

    # Wajib tembusan BARU: bar sebelumnya masih di dalam channel.
    if c[-1] > atas[-1] and c[-2] <= atas[-2]:
        arah = ARAH_LONG
        invalid = float(bawah[-1])
        level = float(atas[-1])
    elif c[-1] < bawah[-1] and c[-2] >= bawah[-2]:
        arah = ARAH_SHORT
        invalid = float(atas[-1])
        level = float(bawah[-1])
    else:
        return None

    lebar = float(atas[-1] - bawah[-1]) / max(atr, 1e-12)
    tembus = abs(c[-1] - level) / max(atr, 1e-12)
    vol = volume_breakout(ctx, 20)

    komponen = {
        "ketegasan_tembusan": (_skala(tembus, 0.1, 1.2), 1.0),
        "konfirmasi_volume": (_skala(vol, 0.9, 1.8), 1.0),
        "channel_tidak_terlalu_lebar": (1.0 - _skala(lebar, 4.0, 20.0), 0.6),
    }
    return Deteksi(
        arah=arah,
        level=level,
        invalidation=invalid,
        komponen=komponen,
        bukti={
            "donchian_atas": round(float(atas[-1]), 10),
            "donchian_bawah": round(float(bawah[-1]), 10),
            "lebar_atr": round(lebar, 3),
        },
        fitur=("donchian", "rasio_volume"),
    )


@daftar_pola(
    "keltner_reversi",
    kelompok=KELOMPOK_VOLATILITAS,
    ambang=61.0,
    warmup=120,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=1.1,
    rr=(1.0, 2.0),
    porsi=(0.6, 0.4),
    deskripsi="Penutupan kembali ke dalam Keltner setelah menembus keluar saat rezim lemah.",
    sumber=_SUMBER_KELTNER,
)
def _keltner_reversi(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 100:
        return None
    atas, tengah, bawah = ctx.fitur.hitung("keltner", b, 20, 2.0)
    if not np.isfinite(atas[-1]) or not np.isfinite(atas[-2]):
        return None
    adx_nilai, _, _ = ctx.fitur.hitung("adx", b, 14)
    if not np.isfinite(adx_nilai[-1]) or adx_nilai[-1] > 22.0:
        return None

    c = np.asarray(b.close, dtype=float)
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    atr = atr_kini(ctx)

    if c[-2] > atas[-2] and c[-1] < atas[-1]:
        arah = ARAH_SHORT
        invalid = float(max(h[-2], h[-1])) + 0.3 * atr
        level = float(atas[-1])
        regang = (float(c[-2]) - float(tengah[-2])) / max(float(atas[-2] - tengah[-2]), 1e-12)
    elif c[-2] < bawah[-2] and c[-1] > bawah[-1]:
        arah = ARAH_LONG
        invalid = float(min(l[-2], l[-1])) - 0.3 * atr
        level = float(bawah[-1])
        regang = (float(tengah[-2]) - float(c[-2])) / max(float(tengah[-2] - bawah[-2]), 1e-12)
    else:
        return None

    komponen = {
        "peregangan_sebelumnya": (_skala(float(regang), 1.0, 2.0), 1.0),
        "rezim_menyamping": (1.0 - _skala(float(adx_nilai[-1]), 8.0, 22.0), 1.0),
        "penutupan_balik": (_skala(abs(c[-1] - level) / max(atr, 1e-12), 0.05, 0.8), 0.7),
    }
    return Deteksi(
        arah=arah,
        level=level,
        invalidation=invalid,
        komponen=komponen,
        bukti={"adx": round(float(adx_nilai[-1]), 3), "keltner_tengah": round(float(tengah[-1]), 10)},
        fitur=("keltner", "adx"),
    )


@daftar_pola(
    "supertrend_flip",
    kelompok=KELOMPOK_VOLATILITAS,
    ambang=60.0,
    warmup=130,
    konteks=1,
    horizon=(HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=1.0,
    rr=(1.5, 3.0),
    porsi=(0.5, 0.5),
    deskripsi="Supertrend berbalik arah dan didukung kemiringan EMA50.",
    sumber=_SUMBER_SUPERTREND,
)
def _supertrend_flip(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 110:
        return None
    garis, arah_st = ctx.fitur.hitung("supertrend", b, 10, 3.0)
    if not np.isfinite(garis[-1]) or not np.isfinite(garis[-2]):
        return None
    if arah_st[-1] == arah_st[-2] or arah_st[-1] == 0:
        return None

    c = np.asarray(b.close, dtype=float)
    atr = atr_kini(ctx)
    ema50 = ctx.fitur.ema(b, 50)
    if not np.isfinite(ema50[-1]) or not np.isfinite(ema50[-6]):
        return None
    kemiringan = (float(ema50[-1]) - float(ema50[-6])) / max(atr, 1e-12)

    if arah_st[-1] > 0:
        arah = ARAH_LONG
        dukungan = _skala(kemiringan, -0.2, 1.0)
    else:
        arah = ARAH_SHORT
        dukungan = _skala(-kemiringan, -0.2, 1.0)

    invalid = float(garis[-1])
    adx_nilai, _, _ = ctx.fitur.hitung("adx", b, 14)
    kekuatan = float(adx_nilai[-1]) if np.isfinite(adx_nilai[-1]) else 15.0

    komponen = {
        "dukungan_kemiringan_ema": (dukungan, 1.0),
        "kekuatan_tren": (_skala(kekuatan, 15.0, 35.0), 0.9),
        "jarak_ke_garis": (1.0 - _skala(abs(c[-1] - invalid) / max(atr, 1e-12), 0.5, 3.0), 0.6),
    }
    return Deteksi(
        arah=arah,
        level=float(garis[-1]),
        invalidation=invalid,
        komponen=komponen,
        bukti={"supertrend": round(float(garis[-1]), 10), "adx": round(kekuatan, 3)},
        fitur=("supertrend", "ema50", "adx"),
    )
