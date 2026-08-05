"""L5 - manajer slot posisi portofolio.

Aturan operator (3 Agu 2026):
- Maksimum 4 posisi terbuka SECARA BERSAMAAN, dan wajib pada pair yang BERBEDA
  (satu simbol tidak boleh punya dua posisi sekaligus).
- Sinyal yang lolos seluruh gerbang tetapi tidak bisa masuk karena slot penuh
  TIDAK boleh hilang diam-diam: dicatat sebagai `SinyalTerlewat` supaya bisa
  ditampilkan di dashboard ("sinyal scalp lain yang tidak di-entry").

Manajer ini TIDAK menilai kualitas sinyal dan tidak boleh dipakai untuk memilih
strategi. Ia hanya kapasitas: siapa yang datang lebih dulu saat ada slot kosong.
Dengan begitu ia tidak menciptakan strategi "raja".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

MAKS_POSISI_BERSAMAAN = 4

ALASAN_SLOT_PENUH = "slot_penuh"
ALASAN_SIMBOL_SUDAH_ADA = "simbol_sudah_punya_posisi"


@dataclass(frozen=True)
class PosisiTerbuka:
    simbol: str
    arah: str
    strategy_id: str
    kelompok: str
    ts_masuk: int
    entry: float
    sl: float
    qty: float
    horizon: str = ""

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "arah": self.arah,
            "strategy_id": self.strategy_id,
            "kelompok": self.kelompok,
            "ts_masuk": self.ts_masuk,
            "entry": self.entry,
            "sl": self.sl,
            "qty": self.qty,
            "horizon": self.horizon,
        }


@dataclass(frozen=True)
class SinyalTerlewat:
    """Sinyal valid yang tidak dieksekusi karena kapasitas, bukan karena kualitas."""

    ts: int
    simbol: str
    arah: str
    strategy_id: str
    kelompok: str
    skor: float
    ambang: float
    entry: float
    sl: float
    tp1: Optional[float]
    r_teoretis: Optional[float]
    alasan: str
    simbol_pemegang_slot: List[str] = field(default_factory=list)

    def ringkas(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "simbol": self.simbol,
            "arah": self.arah,
            "strategy_id": self.strategy_id,
            "kelompok": self.kelompok,
            "skor": round(self.skor, 3),
            "ambang": self.ambang,
            "entry": self.entry,
            "sl": self.sl,
            "tp1": self.tp1,
            "r_teoretis": None if self.r_teoretis is None else round(self.r_teoretis, 4),
            "alasan": self.alasan,
            "slot_dipegang": list(self.simbol_pemegang_slot),
        }


class ManajerSlot:
    """Kapasitas posisi bersamaan + buku sinyal terlewat."""

    def __init__(self, maks_posisi: int = MAKS_POSISI_BERSAMAAN) -> None:
        if int(maks_posisi) < 1:
            raise ValueError("maks_posisi minimal 1")
        self.maks_posisi = int(maks_posisi)
        self._posisi: Dict[str, PosisiTerbuka] = {}
        self.terlewat: List[SinyalTerlewat] = []

    # -- keadaan ---------------------------------------------------------
    @property
    def jumlah_terbuka(self) -> int:
        return len(self._posisi)

    @property
    def slot_tersisa(self) -> int:
        return self.maks_posisi - len(self._posisi)

    def simbol_terbuka(self) -> List[str]:
        return sorted(self._posisi)

    def posisi(self, simbol: str) -> Optional[PosisiTerbuka]:
        return self._posisi.get(simbol)

    def punya_posisi(self, simbol: str) -> bool:
        return simbol in self._posisi

    # -- keputusan kapasitas --------------------------------------------
    def alasan_tolak(self, simbol: str) -> Optional[str]:
        if simbol in self._posisi:
            return ALASAN_SIMBOL_SUDAH_ADA
        if self.slot_tersisa <= 0:
            return ALASAN_SLOT_PENUH
        return None

    def boleh_masuk(self, simbol: str) -> bool:
        return self.alasan_tolak(simbol) is None

    # -- mutasi ----------------------------------------------------------
    def buka(self, posisi: PosisiTerbuka) -> None:
        alasan = self.alasan_tolak(posisi.simbol)
        if alasan is not None:
            raise RuntimeError(f"tidak boleh membuka posisi {posisi.simbol}: {alasan}")
        self._posisi[posisi.simbol] = posisi

    def tutup(self, simbol: str) -> Optional[PosisiTerbuka]:
        return self._posisi.pop(simbol, None)

    def catat_terlewat(
        self,
        ts: int,
        simbol: str,
        verdict,
        alasan: str,
        horizon: str = "",
    ) -> SinyalTerlewat:
        """Simpan sinyal yang tidak dieksekusi karena kapasitas."""
        tps = list(getattr(verdict, "tps", ()) or ())
        tp1 = float(tps[0].harga) if tps else None
        jarak_sl = abs(float(verdict.entry) - float(verdict.sl))
        r = None
        if tp1 is not None and jarak_sl > 0:
            r = abs(tp1 - float(verdict.entry)) / jarak_sl
        s = SinyalTerlewat(
            ts=int(ts),
            simbol=simbol,
            arah=verdict.arah,
            strategy_id=verdict.strategy_id,
            kelompok=getattr(verdict, "kelompok", ""),
            skor=float(verdict.skor),
            ambang=float(verdict.ambang),
            entry=float(verdict.entry),
            sl=float(verdict.sl),
            tp1=tp1,
            r_teoretis=r,
            alasan=alasan,
            simbol_pemegang_slot=self.simbol_terbuka(),
        )
        self.terlewat.append(s)
        return s

    # -- laporan ---------------------------------------------------------
    def ringkas_terlewat(self) -> Dict[str, Any]:
        per_alasan: Dict[str, int] = {}
        per_strategi: Dict[str, int] = {}
        per_simbol: Dict[str, int] = {}
        for s in self.terlewat:
            per_alasan[s.alasan] = per_alasan.get(s.alasan, 0) + 1
            per_strategi[s.strategy_id] = per_strategi.get(s.strategy_id, 0) + 1
            per_simbol[s.simbol] = per_simbol.get(s.simbol, 0) + 1
        return {
            "jumlah": len(self.terlewat),
            "per_alasan": per_alasan,
            "per_strategi": dict(sorted(per_strategi.items(), key=lambda kv: -kv[1])),
            "per_simbol": dict(sorted(per_simbol.items(), key=lambda kv: -kv[1])),
        }

    def ringkas(self) -> Dict[str, Any]:
        return {
            "maks_posisi": self.maks_posisi,
            "terbuka": [p.ringkas() for p in self._posisi.values()],
            "slot_tersisa": self.slot_tersisa,
            "terlewat": self.ringkas_terlewat(),
        }
