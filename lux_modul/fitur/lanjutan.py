"""L1 lanjutan - indikator aliran volume, level harga, dan volatilitas.

Seluruh fungsi di sini MURNI: hanya bergantung pada bar yang sudah tutup, tanpa
state, tanpa mengintip bar masa depan. Semuanya juga terdaftar di KATALOG_INDIKATOR
sehingga bisa dipanggil lewat FeatureStore.hitung("nama", bars, ...).

BATAS KEJUJURAN DATA (revisi operator, wajib dipatuhi)
-------------------------------------------------------
Dataset yang dipakai hanya OHLCV. Tidak ada tick data, tidak ada agresor bid/ask,
tidak ada open interest, tidak ada funding rate. Aturan operator: kalau suatu
indikator/strategi TIDAK BISA dihitung secara valid dari data yang benar-benar
tersedia, jangan dipaksakan masuk modul -- cukup didokumentasikan sebagai calon
pengembangan berikutnya (lihat CALON_STRATEGI.md di root repo).

- CVD (Cumulative Volume Delta) SENGAJA TIDAK dibuat di sini. CVD asli butuh
  klasifikasi agresor per trade (data tick/order-flow) yang tidak ada di dataset
  OHLCV ini. Versi "proksi" dari OHLCV bukan CVD yang valid dan berpotensi
  menyesatkan, jadi dihapus, bukan sekadar diberi label proksi.
- Open Interest dan Funding Rate juga SENGAJA belum dibuat karena kolomnya tidak
  ada di dataset; membuatnya sekarang berarti mengarang data.
- `delta_volume` di bawah BUKAN CVD. Ini adalah Money Flow Volume (rumus
  Chaikin/Accumulation-Distribution), indikator OHLCV standar yang mengukur
  posisi close di dalam rentang bar per-bar (bukan kumulatif order-flow), dan
  tidak dipakai untuk klaim apa pun soal aliran order sungguhan. Saat ini belum
  dipakai strategi mana pun; disediakan sebagai bahan baku indikator turunan
  yang sah dari OHLCV (mis. Chaikin Money Flow) di masa depan.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from ..kontrak import Bars
from ..plugin import daftar_indikator
from . import dasar


def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def _bagi_aman_larik(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pembagian elemen-per-elemen yang aman untuk larik (bukan skalar).

    `dasar.aman_bagi` sengaja hanya untuk skalar (dipakai di util.py/adaptor.py).
    ADX di sini butuh versi larik karena +DI/-DI/DX dihitung untuk seluruh bar
    sekaligus, bukan satu nilai. Elemen dengan penyebut nol/tak-hingga -> 0.0.
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    keluaran = np.zeros_like(a)
    sah = np.isfinite(b) & (b != 0)
    keluaran[sah] = a[sah] / b[sah]
    return keluaran


# --------------------------------------------------------------------------- #
# Aliran volume
# --------------------------------------------------------------------------- #


@daftar_indikator("delta_volume")
def delta_volume(bars: Bars) -> np.ndarray:
    """Perkiraan delta volume per bar dari posisi close dalam rentang bar.

    mult = ((close - low) - (high - close)) / (high - low), rentang -1..+1.
    Bar yang menutup di puncak rentang dianggap didominasi pembeli agresif.
    """
    h, l, c, v = _arr(bars.high), _arr(bars.low), _arr(bars.close), _arr(bars.volume)
    rentang = h - l
    mult = np.zeros_like(c)
    sah = rentang > 0
    mult[sah] = ((c[sah] - l[sah]) - (h[sah] - c[sah])) / rentang[sah]
    return mult * v


@daftar_indikator("vwap_sesi")
def vwap_sesi(bars: Bars, periode_ms: int = 86_400_000) -> np.ndarray:
    """VWAP yang reset tiap sesi (default harian UTC).

    Memakai harga tipikal (H+L+C)/3 tertimbang volume. Reset dideteksi dari
    pergantian bucket `ts // periode_ms`, jadi tidak perlu kalender eksternal.
    """
    ts = np.asarray(bars.ts, dtype=np.int64)
    h, l, c, v = _arr(bars.high), _arr(bars.low), _arr(bars.close), _arr(bars.volume)
    tipikal = (h + l + c) / 3.0
    bucket = ts // int(periode_ms)
    hasil = np.empty_like(tipikal)
    kum_pv = 0.0
    kum_v = 0.0
    bucket_kini = None
    for i in range(tipikal.size):
        if bucket[i] != bucket_kini:
            bucket_kini = bucket[i]
            kum_pv = 0.0
            kum_v = 0.0
        kum_pv += tipikal[i] * v[i]
        kum_v += v[i]
        hasil[i] = kum_pv / kum_v if kum_v > 0 else tipikal[i]
    return hasil


@daftar_indikator("vwap_pita")
def vwap_pita(
    bars: Bars, periode_ms: int = 86_400_000, k: float = 1.0
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """VWAP + pita deviasi standar tertimbang volume (atas, vwap, bawah)."""
    ts = np.asarray(bars.ts, dtype=np.int64)
    h, l, c, v = _arr(bars.high), _arr(bars.low), _arr(bars.close), _arr(bars.volume)
    tipikal = (h + l + c) / 3.0
    bucket = ts // int(periode_ms)
    vwap = np.empty_like(tipikal)
    dev = np.zeros_like(tipikal)
    kum_pv = kum_v = kum_p2v = 0.0
    bucket_kini = None
    for i in range(tipikal.size):
        if bucket[i] != bucket_kini:
            bucket_kini = bucket[i]
            kum_pv = kum_v = kum_p2v = 0.0
        kum_pv += tipikal[i] * v[i]
        kum_p2v += (tipikal[i] ** 2) * v[i]
        kum_v += v[i]
        if kum_v > 0:
            vwap[i] = kum_pv / kum_v
            varian = max(kum_p2v / kum_v - vwap[i] ** 2, 0.0)
            dev[i] = varian**0.5
        else:
            vwap[i] = tipikal[i]
            dev[i] = 0.0
    return vwap + k * dev, vwap, vwap - k * dev


class ProfilVolume:
    """Hasil volume profile atas satu jendela bar."""

    __slots__ = ("poc", "vah", "val", "bin_harga", "bin_volume", "total")

    def __init__(self, poc, vah, val, bin_harga, bin_volume, total):
        self.poc = poc
        self.vah = vah
        self.val = val
        self.bin_harga = bin_harga
        self.bin_volume = bin_volume
        self.total = total

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProfilVolume poc={self.poc:.6g} vah={self.vah:.6g} val={self.val:.6g}>"


@daftar_indikator("volume_profile")
def volume_profile(
    bars: Bars, jendela: int = 240, bin_jumlah: int = 48, porsi_area: float = 0.70
) -> Optional[ProfilVolume]:
    """Volume profile sederhana: POC, VAH, VAL atas `jendela` bar terakhir.

    Volume tiap bar disebar merata ke seluruh bin yang disentuh rentang low-high
    bar tersebut (mode Range/Uniform). Ini pendekatan jujur untuk data OHLCV:
    tanpa data intrabar kita tidak tahu di harga mana persisnya volume terjadi,
    jadi menaruh semuanya di harga close justru akan memalsukan bentuk profil.
    """
    h, l, v = _arr(bars.high), _arr(bars.low), _arr(bars.volume)
    n = min(int(jendela), h.size)
    if n < 10:
        return None
    h, l, v = h[-n:], l[-n:], v[-n:]
    lo, hi = float(l.min()), float(h.max())
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None

    tepi = np.linspace(lo, hi, int(bin_jumlah) + 1)
    tengah = (tepi[:-1] + tepi[1:]) / 2.0
    ember = np.zeros(int(bin_jumlah))
    lebar_bin = (hi - lo) / bin_jumlah

    for i in range(n):
        if v[i] <= 0:
            continue
        a = int((l[i] - lo) / lebar_bin) if lebar_bin > 0 else 0
        b = int((h[i] - lo) / lebar_bin) if lebar_bin > 0 else 0
        a = max(0, min(bin_jumlah - 1, a))
        b = max(0, min(bin_jumlah - 1, b))
        if b < a:
            a, b = b, a
        ember[a : b + 1] += v[i] / (b - a + 1)

    total = float(ember.sum())
    if total <= 0:
        return None

    idx_poc = int(np.argmax(ember))
    # Perluas dari POC ke sisi bervolume lebih besar sampai porsi_area tercapai.
    bawah = atas = idx_poc
    terkumpul = ember[idx_poc]
    target = total * float(porsi_area)
    while terkumpul < target and (bawah > 0 or atas < bin_jumlah - 1):
        kiri = ember[bawah - 1] if bawah > 0 else -1.0
        kanan = ember[atas + 1] if atas < bin_jumlah - 1 else -1.0
        if kanan >= kiri:
            atas += 1
            terkumpul += ember[atas]
        else:
            bawah -= 1
            terkumpul += ember[bawah]
    return ProfilVolume(
        poc=float(tengah[idx_poc]),
        vah=float(tepi[atas + 1]),
        val=float(tepi[bawah]),
        bin_harga=tengah,
        bin_volume=ember,
        total=total,
    )


# --------------------------------------------------------------------------- #
# Volatilitas & rezim
# --------------------------------------------------------------------------- #


@daftar_indikator("keltner")
def keltner(
    bars: Bars, n: int = 20, k: float = 1.5
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Keltner Channel: EMA(n) +/- k * ATR(n). Kembalikan (atas, tengah, bawah)."""
    tengah = dasar.ema(bars.close, n)
    a = dasar.atr(bars.high, bars.low, bars.close, n)
    return tengah + k * a, tengah, tengah - k * a


@daftar_indikator("squeeze_bb_kc")
def squeeze_bb_kc(bars: Bars, n: int = 20, k_bb: float = 2.0, k_kc: float = 1.5) -> np.ndarray:
    """Penanda squeeze TTM: 1.0 bila Bollinger berada DI DALAM Keltner."""
    bb_atas, _, bb_bawah = dasar.bollinger(bars.close, n, k_bb)
    kc_atas, _, kc_bawah = keltner(bars, n, k_kc)
    dalam = (bb_atas < kc_atas) & (bb_bawah > kc_bawah)
    keluaran = np.where(dalam, 1.0, 0.0)
    keluaran[~np.isfinite(bb_atas) | ~np.isfinite(kc_atas)] = float("nan")
    return keluaran


@daftar_indikator("donchian")
def donchian(bars: Bars, n: int = 20) -> Tuple[np.ndarray, np.ndarray]:
    """Donchian Channel dari n bar SEBELUM bar berjalan.

    Sengaja digeser satu bar. Kalau bar berjalan ikut dihitung, harga tidak akan
    pernah bisa menembus channel-nya sendiri dan sinyalnya jadi bocor (look-ahead
    terselubung yang lazim terjadi pada implementasi Donchian yang ceroboh).
    """
    h, l = _arr(bars.high), _arr(bars.low)
    atas = np.full(h.size, np.nan)
    bawah = np.full(h.size, np.nan)
    for i in range(n, h.size):
        atas[i] = h[i - n : i].max()
        bawah[i] = l[i - n : i].min()
    return atas, bawah


@daftar_indikator("supertrend")
def supertrend(bars: Bars, n: int = 10, k: float = 3.0) -> Tuple[np.ndarray, np.ndarray]:
    """Supertrend. Kembalikan (garis, arah) dengan arah +1 naik / -1 turun."""
    h, l, c = _arr(bars.high), _arr(bars.low), _arr(bars.close)
    a = dasar.atr(h, l, c, n)
    tengah = (h + l) / 2.0
    atas_dasar = tengah + k * a
    bawah_dasar = tengah - k * a

    garis = np.full(c.size, np.nan)
    arah = np.zeros(c.size)
    atas_final = np.full(c.size, np.nan)
    bawah_final = np.full(c.size, np.nan)

    mulai = int(np.argmax(np.isfinite(a))) if np.any(np.isfinite(a)) else c.size
    for i in range(mulai, c.size):
        if not np.isfinite(atas_dasar[i]):
            continue
        if i == mulai or not np.isfinite(atas_final[i - 1]):
            atas_final[i] = atas_dasar[i]
            bawah_final[i] = bawah_dasar[i]
            arah[i] = 1.0 if c[i] >= tengah[i] else -1.0
        else:
            atas_final[i] = (
                atas_dasar[i]
                if (atas_dasar[i] < atas_final[i - 1] or c[i - 1] > atas_final[i - 1])
                else atas_final[i - 1]
            )
            bawah_final[i] = (
                bawah_dasar[i]
                if (bawah_dasar[i] > bawah_final[i - 1] or c[i - 1] < bawah_final[i - 1])
                else bawah_final[i - 1]
            )
            if arah[i - 1] > 0:
                arah[i] = -1.0 if c[i] < bawah_final[i] else 1.0
            else:
                arah[i] = 1.0 if c[i] > atas_final[i] else -1.0
        garis[i] = bawah_final[i] if arah[i] > 0 else atas_final[i]
    return garis, arah


@daftar_indikator("adx")
def adx(bars: Bars, n: int = 14) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """ADX, +DI, -DI dengan pemulusan Wilder."""
    h, l, c = _arr(bars.high), _arr(bars.low), _arr(bars.close)
    naik = np.diff(h, prepend=h[0])
    turun = -np.diff(l, prepend=l[0])
    plus_dm = np.where((naik > turun) & (naik > 0), naik, 0.0)
    minus_dm = np.where((turun > naik) & (turun > 0), turun, 0.0)
    tr = dasar.true_range(h, l, c)
    atr_w = dasar.rma(tr, n)
    plus_di = 100.0 * _bagi_aman_larik(dasar.rma(plus_dm, n), atr_w)
    minus_di = 100.0 * _bagi_aman_larik(dasar.rma(minus_dm, n), atr_w)
    dx = 100.0 * _bagi_aman_larik(np.abs(plus_di - minus_di), plus_di + minus_di)
    return dasar.rma(dx, n), plus_di, minus_di


@daftar_indikator("stoch_rsi")
def stoch_rsi(bars: Bars, n_rsi: int = 14, n_stoch: int = 14, halus: int = 3):
    """Stochastic RSI (k, d)."""
    r = dasar.rsi(bars.close, n_rsi)
    k_mentah = np.full(r.size, np.nan)
    for i in range(n_stoch, r.size):
        jendela = r[i - n_stoch + 1 : i + 1]
        if not np.all(np.isfinite(jendela)):
            continue
        lo, hi = jendela.min(), jendela.max()
        k_mentah[i] = 50.0 if hi <= lo else 100.0 * (r[i] - lo) / (hi - lo)
    k = dasar.sma(k_mentah, halus)
    d = dasar.sma(k, halus)
    return k, d


# --------------------------------------------------------------------------- #
# Level harga
# --------------------------------------------------------------------------- #


@daftar_indikator("fibonacci")
def fibonacci(awal: float, akhir: float) -> Dict[str, float]:
    """Level retracement + ekstensi dari satu ayunan harga awal->akhir."""
    rentang = akhir - awal
    level = {
        "0.0": akhir,
        "0.236": akhir - 0.236 * rentang,
        "0.382": akhir - 0.382 * rentang,
        "0.5": akhir - 0.5 * rentang,
        "0.618": akhir - 0.618 * rentang,
        "0.65": akhir - 0.65 * rentang,
        "0.786": akhir - 0.786 * rentang,
        "1.0": awal,
        "ext_1.272": akhir + 0.272 * rentang,
        "ext_1.618": akhir + 0.618 * rentang,
    }
    return {k: float(v) for k, v in level.items()}


@daftar_indikator("pivot_klasik")
def pivot_klasik(tinggi: float, rendah: float, tutup: float) -> Dict[str, float]:
    """Pivot point klasik dari satu periode yang SUDAH selesai."""
    p = (tinggi + rendah + tutup) / 3.0
    return {
        "P": float(p),
        "R1": float(2 * p - rendah),
        "S1": float(2 * p - tinggi),
        "R2": float(p + (tinggi - rendah)),
        "S2": float(p - (tinggi - rendah)),
        "R3": float(tinggi + 2 * (p - rendah)),
        "S3": float(rendah - 2 * (tinggi - p)),
    }
