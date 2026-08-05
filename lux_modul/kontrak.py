"""Kontrak data lintas lapis (L0..L4) untuk modul LUX.

Aturan mengikat:
- Komunikasi antar lapis HANYA lewat struktur data di berkas ini.
- Tidak ada state global. Tidak ada panggilan balik dari lapis bawah ke lapis atas.
- Strategi (L2) TIDAK BOLEH membaca verdict strategi lain dan TIDAK BOLEH menyimpan
  state di luar dirinya. Ditegakkan lewat API: strategi hanya menerima KonteksEvaluasi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

ARAH_LONG = "LONG"
ARAH_SHORT = "SHORT"
ARAH_VALID = (ARAH_LONG, ARAH_SHORT)

HORIZON_SCALPING = "scalping"
HORIZON_INTRADAY = "intraday"
HORIZON_SWING = "swing"
HORIZON_VALID = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)

MODE_AUTO_ENTRY = "auto_entry"
MODE_SIGNAL_ONLY = "signal_only"

# Langkah 4 (mengikat): swing DILARANG auto-entry.
MODE_PER_HORIZON: Mapping[str, str] = {
    HORIZON_SCALPING: MODE_AUTO_ENTRY,
    HORIZON_INTRADAY: MODE_AUTO_ENTRY,
    HORIZON_SWING: MODE_SIGNAL_ONLY,
}

# Kelompok teknik BUKAN daftar tertutup. Tiga di bawah hanyalah bawaan; plugin
# boleh menambah kelompok baru lewat plugin.KELOMPOK.tambah("nama_kelompok").
from .plugin import DaftarKelompok  # noqa: E402

KELOMPOK_POLA = "pola_klasik"
KELOMPOK_INDIKATOR = "indikator_momentum"
KELOMPOK_STRUKTUR = "struktur_modern"
KELOMPOK_ALIRAN = "aliran_volume"
KELOMPOK_LEVEL = "level_harga"
KELOMPOK_VOLATILITAS = "volatilitas_rezim"

KELOMPOK_VALID = DaftarKelompok(
    (
        KELOMPOK_POLA,
        KELOMPOK_INDIKATOR,
        KELOMPOK_STRUKTUR,
        KELOMPOK_ALIRAN,
        KELOMPOK_LEVEL,
        KELOMPOK_VOLATILITAS,
    )
)


def daftar_kelompok(nama: str) -> str:
    """Daftarkan kelompok teknik baru. Dipakai plugin pihak ketiga."""
    return KELOMPOK_VALID.tambah(nama)

TF_MS: Mapping[str, int] = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def tf_ms(tf: str) -> int:
    try:
        return TF_MS[tf]
    except KeyError as exc:
        raise ValueError(f"timeframe tidak dikenal: {tf!r}") from exc


def arah_lawan(arah: str) -> str:
    return ARAH_SHORT if arah == ARAH_LONG else ARAH_LONG


@dataclass(frozen=True)
class Bars:
    """Deret OHLCV satu timeframe. `ts` = waktu BUKA lilin, epoch ms (konvensi Binance)."""

    tf: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    simbol: str = "?"

    def __post_init__(self) -> None:
        tf_ms(self.tf)
        n = len(self.ts)
        for nama in ("open", "high", "low", "close", "volume"):
            if len(getattr(self, nama)) != n:
                raise ValueError(f"panjang kolom {nama} != panjang ts")
        if n > 1 and not np.all(np.diff(np.asarray(self.ts)) > 0):
            raise ValueError("ts wajib menaik ketat (tidak boleh duplikat/mundur)")

    def __len__(self) -> int:
        return int(len(self.ts))

    @property
    def durasi_ms(self) -> int:
        return tf_ms(self.tf)

    def ts_tutup(self, i: int) -> int:
        return int(self.ts[i]) + self.durasi_ms

    def potong(self, mulai: int = 0, akhir: Optional[int] = None) -> "Bars":
        s = slice(mulai, akhir)
        return Bars(
            tf=self.tf,
            ts=self.ts[s],
            open=self.open[s],
            high=self.high[s],
            low=self.low[s],
            close=self.close[s],
            volume=self.volume[s],
            simbol=self.simbol,
        )

    def hingga_indeks(self, i: int, maks_lookback: Optional[int] = None) -> "Bars":
        """Potong dari awal hingga indeks i (inklusif).

        `maks_lookback` opsional membatasi seberapa jauh ke belakang bar yang
        disertakan (mis. 5000 bar). Ini murni optimasi kompleksitas: indikator
        dan pola teknikal yang dipakai strategi tidak pernah butuh lebih dari
        beberapa ratus bar ke belakang, sedangkan tanpa batas ini biaya
        evaluasi per-bar tumbuh terus seiring panjang riwayat (O(n^2) pada
        backtest panjang, dan makin lambat seiring waktu saat live trading).
        Batas ini TIDAK mengubah sinyal karena jauh lebih besar dari lookback
        internal strategi mana pun. Default None = tidak dibatasi (perilaku lama).
        """
        mulai = 0
        if maks_lookback is not None:
            mulai = max(0, i + 1 - maks_lookback)
        return self.potong(mulai, i + 1)

    def hingga_waktu_tutup(self, batas_ts: int, maks_lookback: Optional[int] = None) -> "Bars":
        """Hanya bar yang SUDAH TUTUP pada atau sebelum `batas_ts` (pagar anti look-ahead).

        Lihat `hingga_indeks` untuk penjelasan `maks_lookback`.
        """
        tutup = np.asarray(self.ts, dtype=np.int64) + self.durasi_ms
        n = int(np.searchsorted(tutup, np.int64(batas_ts), side="right"))
        mulai = 0
        if maks_lookback is not None:
            mulai = max(0, n - maks_lookback)
        return self.potong(mulai, n)


@dataclass(frozen=True)
class TFPlan:
    """context_tfs kosong -> SINGLE TF. Terisi -> MULTI TF (konteks wajib lebih besar)."""

    entry_tf: str
    context_tfs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        e = tf_ms(self.entry_tf)
        seen = set()
        for c in self.context_tfs:
            if tf_ms(c) <= e:
                raise ValueError(
                    f"context TF {c!r} harus lebih besar dari entry TF {self.entry_tf!r}"
                )
            if c in seen:
                raise ValueError(f"context TF duplikat: {c!r}")
            seen.add(c)

    @property
    def jumlah_konteks(self) -> int:
        return len(self.context_tfs)

    @property
    def single_tf(self) -> bool:
        return self.jumlah_konteks == 0

    def semua_tf(self) -> Tuple[str, ...]:
        return (self.entry_tf,) + tuple(self.context_tfs)

    def konteks_terurut(self) -> Tuple[str, ...]:
        return tuple(sorted(self.context_tfs, key=tf_ms))


@dataclass(frozen=True)
class TargetTP:
    harga: float
    porsi: float
    label: str = ""

    def __post_init__(self) -> None:
        if not (0.0 < self.porsi <= 1.0):
            raise ValueError(f"porsi TP harus di (0,1], dapat {self.porsi}")
        if not np.isfinite(self.harga) or self.harga <= 0:
            raise ValueError(f"harga TP tidak sah: {self.harga}")


@dataclass(frozen=True)
class StrategyVerdict:
    """Keluaran satu strategi tunggal. Sudah lengkap: entry + SL + TP."""

    strategy_id: str
    kelompok: str
    arah: str
    skor: float
    ambang: float
    entry: float
    sl: float
    tps: Tuple[TargetTP, ...]
    level: float
    invalidation: float
    tfs_used: Tuple[str, ...]
    features_used: Tuple[str, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)
    ts_sinyal: int = 0
    calibrated_p: Optional[float] = None  # HANYA Arbiter (L3) yang boleh mengisi

    def __post_init__(self) -> None:
        if self.arah not in ARAH_VALID:
            raise ValueError(f"arah tidak sah: {self.arah!r}")
        if self.kelompok not in KELOMPOK_VALID:
            raise ValueError(f"kelompok tidak sah: {self.kelompok!r}")
        if not (0.0 <= self.skor <= 100.0):
            raise ValueError(f"skor wajib 0..100, dapat {self.skor}")
        if not self.tps:
            raise ValueError("verdict wajib punya minimal satu TP")
        total = sum(t.porsi for t in self.tps)
        if total > 1.0 + 1e-9:
            raise ValueError(f"total porsi TP > 1.0 ({total})")
        if self.arah == ARAH_LONG:
            if not self.sl < self.entry:
                raise ValueError("LONG: SL wajib di bawah entry")
            if any(t.harga <= self.entry for t in self.tps):
                raise ValueError("LONG: seluruh TP wajib di atas entry")
        else:
            if not self.sl > self.entry:
                raise ValueError("SHORT: SL wajib di atas entry")
            if any(t.harga >= self.entry for t in self.tps):
                raise ValueError("SHORT: seluruh TP wajib di bawah entry")

    @property
    def risiko_harga(self) -> float:
        return abs(self.entry - self.sl)

    @property
    def rr_utama(self) -> float:
        if self.risiko_harga <= 0:
            return 0.0
        jauh = max(abs(t.harga - self.entry) for t in self.tps)
        return jauh / self.risiko_harga

    @property
    def rr_tp1(self) -> float:
        if self.risiko_harga <= 0:
            return 0.0
        return abs(self.tps[0].harga - self.entry) / self.risiko_harga

    @property
    def lolos_ambang(self) -> bool:
        # KETAT: aturan operator berbunyi "skor DI ATAS ambang", jadi bukan >=
        return self.skor > self.ambang

    def ringkas(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "kelompok": self.kelompok,
            "arah": self.arah,
            "skor": round(float(self.skor), 2),
            "ambang": float(self.ambang),
            "lolos": self.lolos_ambang,
            "entry": float(self.entry),
            "sl": float(self.sl),
            "tp": [round(float(t.harga), 8) for t in self.tps],
            "rr_tp1": round(self.rr_tp1, 3),
            "rr_utama": round(self.rr_utama, 3),
            "tfs_used": list(self.tfs_used),
            "ts_sinyal": int(self.ts_sinyal),
        }


@dataclass(frozen=True)
class Penolakan:
    strategy_id: str
    kode: str
    pesan: str = ""


TOLAK_PERAN_TF = "peran_tf_tak_terpenuhi"
TOLAK_HORIZON = "horizon_tak_didukung"
TOLAK_WARMUP = "warmup_kurang"
TOLAK_TAK_ADA_SETUP = "tak_ada_setup"
TOLAK_GALAT = "galat_internal"
TOLAK_AMBANG = "skor_di_bawah_ambang"
