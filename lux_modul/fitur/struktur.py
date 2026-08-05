"""L1 - fitur STRUKTUR pasar: pivot, tren, BOS/CHoCH, FVG, order block, range, garis tren.

Semua fungsi murni. Pivot hanya dianggap SAH bila sudah terkonfirmasi (butuh `kanan`
bar setelahnya), sehingga tidak ada kebocoran informasi masa depan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from .dasar import _f


@dataclass(frozen=True)
class Pivot:
    idx: int
    harga: float
    tipe: str  # "high" | "low"


def pivots(high, low, kiri: int = 2, kanan: int = 2) -> List[Pivot]:
    """Fractal pivot terkonfirmasi. Pivot pada idx i hanya sah bila i + kanan <= n-1."""
    h, l = _f(high), _f(low)
    n = h.size
    hasil: List[Pivot] = []
    for i in range(kiri, n - kanan):
        jd_h = h[i - kiri : i + kanan + 1]
        if h[i] == jd_h.max() and np.count_nonzero(jd_h == h[i]) == 1:
            hasil.append(Pivot(i, float(h[i]), "high"))
        jd_l = l[i - kiri : i + kanan + 1]
        if l[i] == jd_l.min() and np.count_nonzero(jd_l == l[i]) == 1:
            hasil.append(Pivot(i, float(l[i]), "low"))
    hasil.sort(key=lambda p: p.idx)
    return hasil


def pivot_tipe(ps: Sequence[Pivot], tipe: str) -> List[Pivot]:
    return [p for p in ps if p.tipe == tipe]


def pivot_terakhir(ps: Sequence[Pivot], tipe: str, n: int = 1) -> List[Pivot]:
    """n pivot terakhir bertipe `tipe`, urut lama -> baru."""
    sel = [p for p in ps if p.tipe == tipe]
    return sel[-n:] if n <= len(sel) else sel


TREN_NAIK = "naik"
TREN_TURUN = "turun"
TREN_SIDEWAYS = "sideways"


def struktur_tren(ps: Sequence[Pivot]) -> str:
    """HH+HL -> naik, LH+LL -> turun, sisanya sideways."""
    hi = pivot_terakhir(ps, "high", 2)
    lo = pivot_terakhir(ps, "low", 2)
    if len(hi) < 2 or len(lo) < 2:
        return TREN_SIDEWAYS
    hh = hi[-1].harga > hi[-2].harga
    hl = lo[-1].harga > lo[-2].harga
    lh = hi[-1].harga < hi[-2].harga
    ll = lo[-1].harga < lo[-2].harga
    if hh and hl:
        return TREN_NAIK
    if lh and ll:
        return TREN_TURUN
    return TREN_SIDEWAYS


@dataclass(frozen=True)
class PeristiwaStruktur:
    idx: int
    jenis: str  # "BOS" | "CHoCH"
    arah: str  # "naik" | "turun"
    level: float


def peristiwa_struktur(
    high, low, close, ps: Sequence[Pivot]
) -> List[PeristiwaStruktur]:
    """Deteksi BOS (lanjutan) & CHoCH (pembalikan) berdasar penutupan menembus pivot.

    BOS naik  : close menembus pivot high terakhir saat tren sedang naik.
    CHoCH naik: close menembus pivot high terakhir saat tren sedang turun.
    """
    c = _f(close)
    out: List[PeristiwaStruktur] = []
    if not ps:
        return out
    tren = TREN_SIDEWAYS
    hi_ref: Optional[Pivot] = None
    lo_ref: Optional[Pivot] = None
    idx_pivot = 0
    terpakai_hi: Optional[int] = None
    terpakai_lo: Optional[int] = None
    for i in range(c.size):
        while idx_pivot < len(ps) and ps[idx_pivot].idx <= i:
            p = ps[idx_pivot]
            if p.tipe == "high":
                hi_ref = p
            else:
                lo_ref = p
            tren = struktur_tren([q for q in ps[: idx_pivot + 1]])
            idx_pivot += 1
        if hi_ref is not None and c[i] > hi_ref.harga and terpakai_hi != hi_ref.idx:
            jenis = "CHoCH" if tren == TREN_TURUN else "BOS"
            out.append(PeristiwaStruktur(i, jenis, "naik", hi_ref.harga))
            terpakai_hi = hi_ref.idx
        if lo_ref is not None and c[i] < lo_ref.harga and terpakai_lo != lo_ref.idx:
            jenis = "CHoCH" if tren == TREN_NAIK else "BOS"
            out.append(PeristiwaStruktur(i, jenis, "turun", lo_ref.harga))
            terpakai_lo = lo_ref.idx
    return out


@dataclass(frozen=True)
class FVG:
    idx: int  # indeks lilin ke-3 pembentuk gap
    atas: float
    bawah: float
    arah: str  # "naik" (bullish gap) | "turun"

    @property
    def ukuran(self) -> float:
        return self.atas - self.bawah

    @property
    def tengah(self) -> float:
        return 0.5 * (self.atas + self.bawah)


def fair_value_gaps(high, low, min_ukuran: float = 0.0) -> List[FVG]:
    """FVG 3-lilin klasik: gap antara high[i-2] dan low[i] (bullish) atau sebaliknya."""
    h, l = _f(high), _f(low)
    out: List[FVG] = []
    for i in range(2, h.size):
        if l[i] > h[i - 2] and (l[i] - h[i - 2]) > min_ukuran:
            out.append(FVG(i, float(l[i]), float(h[i - 2]), "naik"))
        elif h[i] < l[i - 2] and (l[i - 2] - h[i]) > min_ukuran:
            out.append(FVG(i, float(l[i - 2]), float(h[i]), "turun"))
    return out


@dataclass(frozen=True)
class OrderBlock:
    idx: int
    atas: float
    bawah: float
    arah: str  # "naik" = demand OB, "turun" = supply OB

    @property
    def tengah(self) -> float:
        return 0.5 * (self.atas + self.bawah)


def order_block_sebelum(
    open_, high, low, close, idx_impuls: int, arah: str, maks_mundur: int = 12
) -> Optional[OrderBlock]:
    """Lilin berlawanan terakhir sebelum impuls yang memicu BOS.

    arah "naik"  -> cari lilin bearish terakhir sebelum idx_impuls (demand OB).
    arah "turun" -> cari lilin bullish terakhir sebelum idx_impuls (supply OB).
    """
    o, h, l, c = _f(open_), _f(high), _f(low), _f(close)
    awal = max(0, idx_impuls - maks_mundur)
    for j in range(idx_impuls - 1, awal - 1, -1):
        bearish = c[j] < o[j]
        if (arah == "naik" and bearish) or (arah == "turun" and not bearish):
            return OrderBlock(j, float(h[j]), float(l[j]), arah)
    return None


@dataclass(frozen=True)
class Rentang:
    atas: float
    bawah: float
    mulai: int
    akhir: int

    @property
    def tinggi(self) -> float:
        return self.atas - self.bawah

    @property
    def tengah(self) -> float:
        return 0.5 * (self.atas + self.bawah)


def rentang_konsolidasi(high, low, idx: int, panjang: int = 20) -> Optional[Rentang]:
    h, l = _f(high), _f(low)
    awal = idx - panjang + 1
    if awal < 0:
        return None
    return Rentang(float(h[awal : idx + 1].max()), float(l[awal : idx + 1].min()), awal, idx)


def garis_lewat_pivot(ps: Sequence[Pivot]) -> Optional[Tuple[float, float]]:
    """Regresi linier lewat titik-titik pivot -> (kemiringan, intersep) pada sumbu indeks."""
    if len(ps) < 2:
        return None
    x = np.array([p.idx for p in ps], dtype=np.float64)
    y = np.array([p.harga for p in ps], dtype=np.float64)
    if np.ptp(x) == 0:
        return None
    a, b = np.polyfit(x, y, 1)
    return float(a), float(b)


def nilai_garis(garis: Tuple[float, float], idx: int) -> float:
    a, b = garis
    return float(a * idx + b)


def sapuan_likuiditas(
    high, low, close, idx: int, level: float, arah: str
) -> bool:
    """Sweep: sumbu menembus level tetapi penutupan kembali ke sisi semula.

    arah "naik"  = sweep sell-side (low ditembus, close balik ke atas) -> bias LONG.
    arah "turun" = sweep buy-side (high ditembus, close balik ke bawah) -> bias SHORT.
    """
    h, l, c = _f(high), _f(low), _f(close)
    if arah == "naik":
        return bool(l[idx] < level and c[idx] > level)
    return bool(h[idx] > level and c[idx] < level)
