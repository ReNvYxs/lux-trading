"""Alat bantu bersama antar strategi. Murni fungsional, tanpa state.

Berkas ini TIDAK menyimpan hasil strategi apa pun. Ia hanya menyediakan perhitungan
berulang (ATR, toleransi, penyusun TP, cek bias TF konteks) agar tiap strategi tetap
ringkas namun tetap berdiri sendiri.
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import numpy as np

from ..data.plane import KonteksEvaluasi
from ..fitur import struktur as st
from ..kontrak import ARAH_LONG, ARAH_SHORT, Bars, TargetTP


def atr_kini(ctx: KonteksEvaluasi, bars: Optional[Bars] = None, n: int = 14) -> float:
    b = bars if bars is not None else ctx.entry
    a = ctx.fitur.atr(b, n)
    v = float(a[-1]) if a.size and np.isfinite(a[-1]) else float("nan")
    if not np.isfinite(v) or v <= 0:
        h = np.asarray(b.high)[-n:]
        l = np.asarray(b.low)[-n:]
        v = float(np.mean(h - l)) if h.size else 0.0
    return max(v, 1e-12)


def tps_terukur(
    arah: str,
    entry: float,
    tinggi: float,
    porsi: Sequence[Tuple[float, float, str]] = (
        (0.618, 0.5, "tp1_0618_measured_move"),
        (1.0, 0.5, "tp2_full_measured_move"),
    ),
) -> Tuple[TargetTP, ...]:
    """TP dari measured move (tinggi pola). Aturan baku pola klasik."""
    tinggi = abs(float(tinggi))
    hasil: List[TargetTP] = []
    for f, p, label in porsi:
        harga = entry + f * tinggi if arah == ARAH_LONG else entry - f * tinggi
        if harga <= 0:
            continue
        hasil.append(TargetTP(float(harga), float(p), label))
    return tuple(hasil)


def tps_rr(
    arah: str,
    entry: float,
    sl: float,
    kelipatan: Sequence[Tuple[float, float, str]] = (
        (1.5, 0.5, "tp1_1R5"),
        (3.0, 0.5, "tp2_3R"),
    ),
) -> Tuple[TargetTP, ...]:
    """TP berbasis kelipatan risiko (R)."""
    r = abs(entry - sl)
    hasil: List[TargetTP] = []
    for k, p, label in kelipatan:
        harga = entry + k * r if arah == ARAH_LONG else entry - k * r
        if harga <= 0:
            continue
        hasil.append(TargetTP(float(harga), float(p), label))
    return tuple(hasil)


def sl_valid(arah: str, entry: float, sl: float, minimum: float) -> float:
    """Pastikan SL di sisi yang benar dan jaraknya tidak nol."""
    minimum = max(float(minimum), abs(entry) * 1e-6)
    if arah == ARAH_LONG:
        return min(float(sl), entry - minimum)
    return max(float(sl), entry + minimum)


def bias_konteks(ctx: KonteksEvaluasi) -> Optional[str]:
    """Bias arah dari TF konteks terkecil: struktur pivot + posisi terhadap EMA50."""
    kb = ctx.konteks_utama()
    if kb is None or len(kb) < 60:
        return None
    tren = ctx.fitur.tren(kb)
    e = ctx.fitur.ema(kb, 50)
    if not e.size or not np.isfinite(e[-1]):
        return None
    di_atas = float(kb.close[-1]) > float(e[-1])
    if tren == st.TREN_NAIK and di_atas:
        return ARAH_LONG
    if tren == st.TREN_TURUN and not di_atas:
        return ARAH_SHORT
    return None


def kekuatan_konteks(ctx: KonteksEvaluasi, arah: str) -> float:
    """0..1 seberapa kuat TF konteks mendukung arah. 0.5 bila netral atau tak ada."""
    b = bias_konteks(ctx)
    if b is None:
        return 0.5
    return 1.0 if b == arah else 0.0


def pivot_pasangan(
    ctx: KonteksEvaluasi, tipe: str, jumlah: int, kiri: int = 2, kanan: int = 2
) -> List[st.Pivot]:
    return st.pivot_terakhir(ctx.fitur.pivots(ctx.entry, kiri, kanan), tipe, jumlah)


def beda_relatif(a: float, b: float) -> float:
    d = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / d


def volume_breakout(ctx: KonteksEvaluasi, n: int = 20) -> float:
    r = ctx.fitur.rasio_volume(ctx.entry, n)
    if not r.size or not np.isfinite(r[-1]):
        return 1.0
    return float(r[-1])
