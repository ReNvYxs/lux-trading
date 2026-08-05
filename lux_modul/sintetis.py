"""Pembangkit data sintetis deterministik untuk uji & demo.

BUKAN bagian dari jalur produksi. Dipakai hanya untuk membuktikan mekanisme
(pembobotan, ambang, konflik arah, pipeline end-to-end) tanpa dataset asli.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

from .data.loader import dari_baris
from .kontrak import Bars, tf_ms

# disejajarkan ke batas hari agar resample ke TF besar tidak menyisakan lilin parsial
TS0 = (1_700_000_000_000 // 86_400_000) * 86_400_000


def bangun_bars(
    closes: Sequence[float],
    tf: str = "5m",
    ts0: int = TS0,
    simbol: str = "SYNTH",
    volume: Optional[Sequence[float]] = None,
    seed: int = 7,
    noise: float = 0.0015,
) -> Bars:
    """Ubah deret harga penutupan menjadi OHLCV yang konsisten (high>=max, low<=min)."""
    rng = np.random.default_rng(seed)
    c = np.asarray(closes, dtype=float)
    n = c.size
    o = np.concatenate(([c[0]], c[:-1]))
    amp = np.abs(c) * noise
    h = np.maximum(o, c) + rng.random(n) * amp
    l = np.minimum(o, c) - rng.random(n) * amp
    v = (
        np.asarray(volume, dtype=float)
        if volume is not None
        else 1000.0 + rng.random(n) * 100.0
    )
    d = tf_ms(tf)
    ts = ts0 + np.arange(n, dtype=np.int64) * d
    baris = np.column_stack([ts, o, h, l, c, v])
    return dari_baris(tf, baris, simbol)


def _lerp(a: float, b: float, n: int) -> List[float]:
    return list(np.linspace(a, b, n, endpoint=False))


def deret_acak(n: int, awal: float = 100.0, sigma: float = 0.002, seed: int = 3) -> List[float]:
    rng = np.random.default_rng(seed)
    langkah = rng.normal(0.0, sigma, n)
    return list(awal * np.exp(np.cumsum(langkah)))


def deret_double_top(
    pra: int = 220, awal: float = 100.0, tinggi: float = 8.0, lembah: float = 4.0
) -> List[float]:
    """Uptrend -> puncak A -> lembah -> puncak B (setara) -> tembus neckline ke bawah."""
    puncak = awal + tinggi
    neck = puncak - lembah
    d: List[float] = []
    d += _lerp(awal - 6.0, awal, pra)
    d += _lerp(awal, puncak, 12)
    d += _lerp(puncak, neck, 10)
    d += _lerp(neck, puncak * 0.999, 10)
    d += _lerp(puncak * 0.999, neck * 0.995, 8)
    d += [neck * 0.985, neck * 0.975]
    return d


def deret_double_bottom(
    pra: int = 220, awal: float = 100.0, dalam: float = 8.0, puncak: float = 4.0
) -> List[float]:
    dasar = awal - dalam
    neck = dasar + puncak
    d: List[float] = []
    d += _lerp(awal + 6.0, awal, pra)
    d += _lerp(awal, dasar, 12)
    d += _lerp(dasar, neck, 10)
    d += _lerp(neck, dasar * 1.001, 10)
    d += _lerp(dasar * 1.001, neck * 1.005, 8)
    d += [neck * 1.015, neck * 1.025]
    return d


def deret_range_breakout(
    pra: int = 220, awal: float = 100.0, lebar: float = 1.2, naik: bool = True
) -> List[float]:
    """Konsolidasi sempit lalu breakout tegas (dipakai menguji breakout_volume)."""
    d: List[float] = list(np.linspace(awal - 3, awal, pra, endpoint=False))
    for k in range(24):
        d.append(awal + (lebar / 2.0) * (1 if k % 2 == 0 else -1) * 0.8)
    arah = 1.0 if naik else -1.0
    d.append(awal + arah * lebar * 1.6)
    d.append(awal + arah * lebar * 2.0)
    return d


def volume_breakout_akhir(n: int, lonjakan: float = 3.0, dasar: float = 1000.0) -> List[float]:
    v = [dasar] * n
    v[-1] = dasar * lonjakan
    v[-2] = dasar * (1.0 + (lonjakan - 1.0) * 0.4)
    return v


def bars_double_top(tf: str = "5m", **kw) -> Bars:
    d = deret_double_top(**kw)
    return bangun_bars(d, tf=tf, volume=volume_breakout_akhir(len(d)), noise=0.0008)


def bars_double_bottom(tf: str = "5m", **kw) -> Bars:
    d = deret_double_bottom(**kw)
    return bangun_bars(d, tf=tf, volume=volume_breakout_akhir(len(d)), noise=0.0008)


def bars_range_breakout(tf: str = "5m", **kw) -> Bars:
    d = deret_range_breakout(**kw)
    return bangun_bars(d, tf=tf, volume=volume_breakout_akhir(len(d), 3.5), noise=0.0005)


def bars_acak(n: int = 600, tf: str = "5m", seed: int = 3) -> Bars:
    return bangun_bars(deret_acak(n, seed=seed), tf=tf, seed=seed)


def bars_tren_naik(n: int = 900, tf: str = "5m", seed: int = 11, sigma: float = 0.0015) -> Bars:
    """Tren naik berombak: menyediakan pullback ke EMA200 dan struktur HH/HL."""
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    dasar = 100.0 * np.exp(0.0009 * t)
    ombak = 1.0 + 0.012 * np.sin(t / 9.0) + 0.006 * np.sin(t / 3.1)
    derau = np.exp(np.cumsum(rng.normal(0.0, sigma, n)) * 0.35)
    return bangun_bars(list(dasar * ombak * derau), tf=tf, seed=seed, noise=0.0009)
