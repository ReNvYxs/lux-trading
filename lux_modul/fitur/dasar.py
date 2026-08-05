"""L1 - fitur numerik murni. Tanpa state, tanpa melihat bar masa depan.

Seluruh fungsi mengembalikan array sepanjang input, NaN pada periode warmup.
Nilai indeks i HANYA boleh bergantung pada data indeks <= i.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def _f(x) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)


def sma(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[n - 1 :] = (c[n:] - c[:-n]) / float(n)
    return out


# Batas jendela rekursi untuk EMA/RMA. Bobot titik data yang lebih tua dari
# jendela ini meluruh eksponensial hingga jauh di bawah presisi float64,
# sehingga memotong rekursi di sini TIDAK mengubah nilai hasil pada indeks
# mana pun yang berada di dalam jendela (termasuk nilai terbaru yang dipakai
# strategi). Ini murni optimasi kompleksitas (menghindari O(n^2) saat dipanggil
# ulang setiap bar pada backtest/live yang terus bertambah panjang datanya),
# BUKAN perubahan logika sinyal.
_JENDELA_REKURSI_MIN = 2000
_JENDELA_REKURSI_KELIPATAN = 40


def _jendela_rekursi(ukuran: int, n: int) -> int:
    return min(ukuran, max(n * _JENDELA_REKURSI_KELIPATAN, _JENDELA_REKURSI_MIN))


def ema(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    jendela = _jendela_rekursi(x.size, n)
    mulai = x.size - jendela
    xs = x[mulai:]
    a = 2.0 / (n + 1.0)
    outs = np.full(xs.size, np.nan)
    outs[n - 1] = float(np.mean(xs[:n]))
    for i in range(n, xs.size):
        outs[i] = a * xs[i] + (1.0 - a) * outs[i - 1]
    out[mulai:] = outs
    return out


def rma(x, n: int) -> np.ndarray:
    """Wilder smoothing (dipakai RSI & ATR)."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    jendela = _jendela_rekursi(x.size, n)
    mulai = x.size - jendela
    xs = x[mulai:]
    outs = np.full(xs.size, np.nan)
    outs[n - 1] = float(np.mean(xs[:n]))
    for i in range(n, xs.size):
        outs[i] = (outs[i - 1] * (n - 1) + xs[i]) / float(n)
    out[mulai:] = outs
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    c = _f(close)
    out = np.full(c.size, np.nan)
    if c.size < n + 1:
        return out
    d = np.diff(c)
    gain = np.where(d > 0, d, 0.0)
    loss = np.where(d < 0, -d, 0.0)
    ag = rma(gain, n)
    al = rma(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = np.divide(ag, al, out=np.full(ag.size, np.inf), where=al > 0)
    val = 100.0 - (100.0 / (1.0 + rs))
    val[np.isnan(ag)] = np.nan
    out[1:] = val
    return out


def macd(
    close, cepat: int = 12, lambat: int = 26, sinyal: int = 9
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    c = _f(close)
    garis = ema(c, cepat) - ema(c, lambat)
    sig = np.full(c.size, np.nan)
    valid = ~np.isnan(garis)
    if valid.any():
        i0 = int(np.argmax(valid))
        sig[i0:] = ema(garis[i0:], sinyal)
    return garis, sig, garis - sig


def true_range(high, low, close) -> np.ndarray:
    h, l, c = _f(high), _f(low), _f(close)
    if c.size == 0:
        return np.array([], dtype=np.float64)
    pc = np.concatenate(([c[0]], c[:-1]))
    return np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))


def atr(high, low, close, n: int = 14) -> np.ndarray:
    return rma(true_range(high, low, close), n)


def stdev(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 1 or x.size < n:
        return out
    c1 = np.cumsum(np.insert(x, 0, 0.0))
    c2 = np.cumsum(np.insert(x * x, 0, 0.0))
    s = c1[n:] - c1[:-n]
    q = c2[n:] - c2[:-n]
    var = np.maximum(q / n - (s / n) ** 2, 0.0)
    out[n - 1 :] = np.sqrt(var)
    return out


def bollinger(close, n: int = 20, k: float = 2.0):
    m = sma(close, n)
    s = stdev(close, n)
    return m + k * s, m, m - k * s


def _sliding(x: np.ndarray, n: int) -> np.ndarray:
    return np.lib.stride_tricks.sliding_window_view(x, n)


def rolling_max(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    out[n - 1 :] = _sliding(x, n).max(axis=1)
    return out


def rolling_min(x, n: int) -> np.ndarray:
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    out[n - 1 :] = _sliding(x, n).min(axis=1)
    return out


def kemiringan(x, n: int) -> np.ndarray:
    """Kemiringan regresi linier atas jendela n (satuan: harga per bar)."""
    x = _f(x)
    out = np.full(x.size, np.nan)
    if n <= 1 or x.size < n:
        return out
    t = np.arange(n, dtype=np.float64)
    t = t - t.mean()
    denom = float((t * t).sum())
    w = _sliding(x, n)
    out[n - 1 :] = (w - w.mean(axis=1, keepdims=True)) @ t / denom
    return out


def rasio_volume(volume, n: int = 20) -> np.ndarray:
    v = _f(volume)
    rata = sma(v, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.divide(v, rata, out=np.full(v.size, np.nan), where=(rata > 0))


def badan(open_, close) -> np.ndarray:
    return np.abs(_f(close) - _f(open_))


def sumbu_bawah(open_, high, low, close) -> np.ndarray:
    o, c, l = _f(open_), _f(close), _f(low)
    return np.minimum(o, c) - l


def sumbu_atas(open_, high, low, close) -> np.ndarray:
    o, c, h = _f(open_), _f(close), _f(high)
    return h - np.maximum(o, c)


def aman_bagi(a: float, b: float, bawaan: float = 0.0) -> float:
    if b == 0 or not np.isfinite(b):
        return bawaan
    return float(a) / float(b)


def skala(nilai: float, rendah: float, tinggi: float) -> float:
    """Petakan nilai ke 0..1 linier lalu klem. Blok pembangun skor strategi."""
    if nilai is None or not np.isfinite(nilai) or tinggi == rendah:
        return 0.0
    return float(min(1.0, max(0.0, (nilai - rendah) / (tinggi - rendah))))
