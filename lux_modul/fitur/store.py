"""L1 - FeatureStore: cache fitur per (tf, nama, parameter).

Cache bersifat LOKAL per objek dan hanya berumur satu evaluasi. Ini BUKAN state
global dan tidak dibagikan antar strategi selain sebagai hasil perhitungan murni
atas data yang sama.
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from ..kontrak import Bars
from . import dasar, struktur


class FeatureStore:
    """Penghitung fitur ber-cache. Dibuat ulang tiap evaluasi bar."""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[Any, ...], Any] = {}

    def _kunci(self, bars: Bars, nama: str, *args: Any) -> Tuple[Any, ...]:
        return (id(bars.close), bars.tf, len(bars), nama) + args

    def _ambil(self, kunci, buat):
        if kunci not in self._cache:
            self._cache[kunci] = buat()
        return self._cache[kunci]

    # ---------------- indikator pluggable ---------------- #

    def hitung(self, nama: str, bars: Bars, *args: Any) -> Any:
        """Panggil indikator apa pun dari KATALOG_INDIKATOR, ber-cache otomatis.

        Inilah pintu perluasan lapis fitur: indikator baru cukup didaftarkan lewat
        @daftar_indikator, tanpa menambah satu pun method di kelas ini.
        """
        from ..plugin import KATALOG_INDIKATOR

        if nama not in KATALOG_INDIKATOR:
            raise KeyError(
                f"indikator {nama!r} belum terdaftar. "
                f"Tersedia: {sorted(KATALOG_INDIKATOR)}"
            )
        fn = KATALOG_INDIKATOR[nama]
        return self._ambil(self._kunci(bars, nama, *args), lambda: fn(bars, *args))

    # ---------------- indikator ---------------- #

    def ema(self, bars: Bars, n: int) -> np.ndarray:
        return self._ambil(self._kunci(bars, "ema", n), lambda: dasar.ema(bars.close, n))

    def sma(self, bars: Bars, n: int) -> np.ndarray:
        return self._ambil(self._kunci(bars, "sma", n), lambda: dasar.sma(bars.close, n))

    def rsi(self, bars: Bars, n: int = 14) -> np.ndarray:
        return self._ambil(self._kunci(bars, "rsi", n), lambda: dasar.rsi(bars.close, n))

    def macd(self, bars: Bars, cepat: int = 12, lambat: int = 26, sinyal: int = 9):
        return self._ambil(
            self._kunci(bars, "macd", cepat, lambat, sinyal),
            lambda: dasar.macd(bars.close, cepat, lambat, sinyal),
        )

    def atr(self, bars: Bars, n: int = 14) -> np.ndarray:
        return self._ambil(
            self._kunci(bars, "atr", n),
            lambda: dasar.atr(bars.high, bars.low, bars.close, n),
        )

    def rasio_volume(self, bars: Bars, n: int = 20) -> np.ndarray:
        return self._ambil(
            self._kunci(bars, "volrasio", n), lambda: dasar.rasio_volume(bars.volume, n)
        )

    def bollinger(self, bars: Bars, n: int = 20, k: float = 2.0):
        return self._ambil(
            self._kunci(bars, "bb", n, k), lambda: dasar.bollinger(bars.close, n, k)
        )

    # ---------------- struktur ---------------- #

    def pivots(self, bars: Bars, kiri: int = 2, kanan: int = 2):
        return self._ambil(
            self._kunci(bars, "pivots", kiri, kanan),
            lambda: struktur.pivots(bars.high, bars.low, kiri, kanan),
        )

    def tren(self, bars: Bars, kiri: int = 2, kanan: int = 2) -> str:
        return self._ambil(
            self._kunci(bars, "tren", kiri, kanan),
            lambda: struktur.struktur_tren(self.pivots(bars, kiri, kanan)),
        )

    def peristiwa_struktur(self, bars: Bars, kiri: int = 2, kanan: int = 2):
        return self._ambil(
            self._kunci(bars, "peristiwa", kiri, kanan),
            lambda: struktur.peristiwa_struktur(
                bars.high, bars.low, bars.close, self.pivots(bars, kiri, kanan)
            ),
        )

    def fvg(self, bars: Bars, min_ukuran: float = 0.0):
        return self._ambil(
            self._kunci(bars, "fvg", min_ukuran),
            lambda: struktur.fair_value_gaps(bars.high, bars.low, min_ukuran),
        )
