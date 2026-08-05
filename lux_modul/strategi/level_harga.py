"""Kelompok 'level_harga' - Fibonacci, pivot point, dan level psikologis.

Semua strategi di sini didaftarkan lewat @daftar_pola. Menambah level baru cukup
menambah satu fungsi detektor di bawah; core engine tidak berubah.
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
    KELOMPOK_LEVEL,
)
from ..plugin import Deteksi, daftar_pola
from .util import atr_kini, volume_breakout

_SUMBER_FIB = (
    "https://www.investopedia.com/terms/f/fibonacciretracement.asp",
    "https://quantum-algo.com/blog/fibonacci-golden-pocket-trading/",
    "https://www.thinkmarkets.com/en/trading-academy/technical-analysis/fibonacci-trading-strategy-top-fibonacci-retracement-setups/",
)
_SUMBER_PIVOT = (
    "https://www.investopedia.com/terms/p/pivotpoint.asp",
    "https://www.babypips.com/learn/forex/pivot-points",
)
_SUMBER_ROUND = (
    "https://www.investopedia.com/articles/forex/08/round-numbers.asp",
)


def _skala(x: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return float(max(0.0, min(1.0, (x - lo) / (hi - lo))))


def _ayunan_terakhir(ctx, kiri: int = 3, kanan: int = 3):
    """Ambil ayunan impuls terakhir (pivot low->high atau high->low) yang sudah pasti.

    Pivot dengan konfirmasi `kanan` bar berarti pivot terbaru yang boleh dipakai
    berada minimal `kanan` bar di belakang. Ini disengaja: pivot yang belum
    terkonfirmasi = look-ahead.
    """
    piv = ctx.fitur.pivots(ctx.entry, kiri, kanan)
    if len(piv) < 2:
        return None
    a, b = piv[-2], piv[-1]
    if a.tipe == b.tipe:
        return None
    return a, b


@daftar_pola(
    "fib_golden_pocket",
    kelompok=KELOMPOK_LEVEL,
    ambang=63.0,
    warmup=140,
    konteks=1,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING),
    sl_atr=0.8,
    rr=(1.618, 2.618),
    porsi=(0.5, 0.5),
    deskripsi="Retracement ke zona 0.618-0.65 dari impuls terakhir, searah bias TF konteks.",
    sumber=_SUMBER_FIB,
)
def _fib_golden_pocket(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 120:
        return None
    ayun = _ayunan_terakhir(ctx)
    if ayun is None:
        return None
    a, z = ayun

    awal, akhir = float(a.harga), float(z.harga)
    if awal == akhir:
        return None
    rentang = akhir - awal
    gp_hi = akhir - 0.618 * rentang
    gp_lo = akhir - 0.65 * rentang
    zona_lo, zona_hi = min(gp_lo, gp_hi), max(gp_lo, gp_hi)

    c = np.asarray(b.close, dtype=float)
    o = np.asarray(b.open, dtype=float)
    atr = atr_kini(ctx)
    harga = float(c[-1])

    # Harga harus BERADA di golden pocket saat ini.
    if not (zona_lo - 0.15 * atr <= harga <= zona_hi + 0.15 * atr):
        return None

    # Impuls naik (pivot low -> pivot high) dicari retracement untuk LONG.
    if z.tipe == "high":
        arah = ARAH_LONG
        konfirmasi = c[-1] > o[-1]
    else:
        arah = ARAH_SHORT
        konfirmasi = c[-1] < o[-1]
    invalid = awal  # level Fib 1.0 = impuls dianggap batal

    if not konfirmasi:
        return None

    dalam = abs(harga - (zona_lo + zona_hi) / 2.0) / max(zona_hi - zona_lo, 1e-12)
    besar_impuls = abs(rentang) / max(atr, 1e-12)
    badan = abs(c[-1] - o[-1]) / max(float(b.high[-1]) - float(b.low[-1]), 1e-12)

    komponen = {
        "ketepatan_zona": (1.0 - _skala(dalam, 0.0, 1.5), 1.0),
        "kekuatan_impuls": (_skala(besar_impuls, 2.0, 10.0), 1.0),
        "candle_konfirmasi": (_skala(badan, 0.25, 0.7), 0.8),
    }
    return Deteksi(
        arah=arah,
        level=float((zona_lo + zona_hi) / 2.0),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={
            "impuls_awal": round(awal, 10),
            "impuls_akhir": round(akhir, 10),
            "gp_0618": round(float(gp_hi), 10),
            "gp_065": round(float(gp_lo), 10),
        },
        fitur=("pivots", "fibonacci"),
    )


@daftar_pola(
    "pivot_reversal",
    kelompok=KELOMPOK_LEVEL,
    ambang=60.0,
    warmup=120,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=0.9,
    rr=(1.3, 2.6),
    porsi=(0.5, 0.5),
    deskripsi="Penolakan di S1/R1 pivot klasik yang dihitung dari periode sebelumnya.",
    sumber=_SUMBER_PIVOT,
)
def _pivot_reversal(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    n = _bar_per_hari(b.tf)
    if len(b) < 2 * n + 5:
        return None

    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    c = np.asarray(b.close, dtype=float)

    # Periode SEBELUMNYA yang sudah selesai: [-2n : -n]. Periode berjalan tidak dipakai.
    lalu_h = float(h[-2 * n : -n].max())
    lalu_l = float(l[-2 * n : -n].min())
    lalu_c = float(c[-n - 1])
    p = (lalu_h + lalu_l + lalu_c) / 3.0
    r1 = 2 * p - lalu_l
    s1 = 2 * p - lalu_h

    atr = atr_kini(ctx)
    tol = 0.4 * atr
    harga = float(c[-1])

    if h[-1] >= r1 - tol and harga < r1:
        arah = ARAH_SHORT
        invalid = float(max(h[-1], r1)) + 0.3 * atr
        level = r1
        sumbu = (h[-1] - max(harga, float(b.open[-1]))) / max(h[-1] - l[-1], 1e-12)
    elif l[-1] <= s1 + tol and harga > s1:
        arah = ARAH_LONG
        invalid = float(min(l[-1], s1)) - 0.3 * atr
        level = s1
        sumbu = (min(harga, float(b.open[-1])) - l[-1]) / max(h[-1] - l[-1], 1e-12)
    else:
        return None

    komponen = {
        "penolakan_sumbu": (_skala(float(sumbu), 0.2, 0.7), 1.0),
        "jarak_ke_pivot": (1.0 - _skala(abs(harga - p) / max(atr, 1e-12), 0.0, 6.0), 0.6),
        "konfirmasi_volume": (_skala(volume_breakout(ctx, 20), 0.8, 1.6), 0.7),
    }
    return Deteksi(
        arah=arah,
        level=float(level),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={"P": round(p, 10), "R1": round(r1, 10), "S1": round(s1, 10), "bar_periode": n},
        fitur=("pivot_klasik",),
    )


@daftar_pola(
    "level_bulat",
    kelompok=KELOMPOK_LEVEL,
    ambang=59.0,
    warmup=100,
    konteks=0,
    horizon=(HORIZON_SCALPING, HORIZON_INTRADAY),
    sl_atr=0.8,
    rr=(1.2, 2.2),
    porsi=(0.6, 0.4),
    deskripsi="Reaksi di level angka bulat psikologis setelah pendekatan cepat.",
    sumber=_SUMBER_ROUND,
)
def _level_bulat(ctx) -> Optional[Deteksi]:
    b = ctx.entry
    if len(b) < 80:
        return None
    c = np.asarray(b.close, dtype=float)
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    harga = float(c[-1])
    atr = atr_kini(ctx)

    # Ukuran langkah bulat diturunkan dari besaran harga, bukan dihardcode.
    magnitudo = 10.0 ** np.floor(np.log10(max(harga, 1e-9)))
    langkah = float(magnitudo / 10.0)
    if langkah <= 0:
        return None
    bawah = np.floor(harga / langkah) * langkah
    atas = bawah + langkah
    dekat = bawah if abs(harga - bawah) < abs(harga - atas) else atas

    # Level bulat hanya menarik bila ATR jauh lebih kecil dari jarak antar level.
    if atr > 0.6 * langkah or atr <= 0:
        return None
    tol = 0.5 * atr

    laju = abs(harga - float(c[-6])) / max(atr, 1e-12) if len(b) > 6 else 0.0
    if laju < 0.8:
        return None

    if h[-1] >= dekat - tol and harga < dekat:
        arah = ARAH_SHORT
        invalid = float(max(h[-1], dekat)) + 0.3 * atr
    elif l[-1] <= dekat + tol and harga > dekat:
        arah = ARAH_LONG
        invalid = float(min(l[-1], dekat)) - 0.3 * atr
    else:
        return None

    komponen = {
        "kedekatan_level": (1.0 - _skala(abs(harga - dekat) / max(atr, 1e-12), 0.0, 1.0), 1.0),
        "laju_pendekatan": (_skala(laju, 0.8, 3.0), 0.9),
        "konfirmasi_volume": (_skala(volume_breakout(ctx, 20), 0.8, 1.6), 0.6),
    }
    return Deteksi(
        arah=arah,
        level=float(dekat),
        invalidation=float(invalid),
        komponen=komponen,
        bukti={"level_bulat": round(float(dekat), 10), "langkah": round(langkah, 10)},
        fitur=("harga",),
    )


_MS_HARI = 86_400_000


def _bar_per_hari(tf: str, cadangan: int = 24) -> int:
    """Jumlah bar dalam satu hari untuk TF apa pun.

    Sebelumnya nilainya dipatok: 288 untuk 5m, 96 untuk 15m, dan 24 untuk
    SEMUA TF lain. Akibatnya pada 1m jendelanya cuma 24 menit (bukan sehari)
    dan level pivot ikut salah - tanpa satu pun pesan galat. Sekarang dihitung
    dari durasi TF, jadi benar untuk 1m, 30m, 1h, 4h, dan seterusnya.

    `cadangan` dipakai bila TF tidak dikenal: lebih baik konservatif daripada
    melempar galat di tengah evaluasi strategi.
    """
    from ..kontrak import tf_ms  # impor lokal: blok impor modul tidak diubah

    try:
        satuan = int(tf_ms(tf))
    except Exception:  # noqa: BLE001 - TF tidak dikenal
        return cadangan
    if satuan <= 0:
        return cadangan
    return max(1, int(_MS_HARI // satuan))
