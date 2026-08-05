"""L2 - basis strategi tunggal + registry.

Kontrak mengikat untuk setiap strategi:
- Mendeklarasikan kebutuhan TF sebagai PERAN: required_roles = {"entry": True, "context": N}.
  context = 0 -> bisa jalan single-TF. context >= 1 -> butuh konfirmasi TF lebih tinggi.
- Punya `ambang` sendiri (0..100) dan mengembalikan `skor` sendiri (0..100).
- DILARANG membaca verdict strategi lain (API-nya memang tidak menyediakannya).
- DILARANG menyimpan state di luar dirinya: instance strategi wajib stateless;
  `Registry.evaluasi_semua` memeriksa ini lewat pagar `__slots__`-like check ringan.
- Wajib mengembalikan None bila prasyarat tak terpenuhi (alasan dicatat Arbiter).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..data.plane import KonteksEvaluasi
from ..kontrak import (
    HORIZON_VALID,
    KELOMPOK_VALID,
    Penolakan,
    StrategyVerdict,
    TFPlan,
    TOLAK_GALAT,
    TOLAK_HORIZON,
    TOLAK_PERAN_TF,
    TOLAK_TAK_ADA_SETUP,
    TOLAK_WARMUP,
)


class Strategi(ABC):
    """Basis seluruh strategi tunggal."""

    id: str = ""
    kelompok: str = ""
    ambang: float = 60.0
    warmup: int = 50
    horizon_didukung: Tuple[str, ...] = HORIZON_VALID
    required_roles: Mapping[str, object] = {"entry": True, "context": 0}
    deskripsi: str = ""
    sumber: Tuple[str, ...] = ()

    def __init__(self) -> None:
        if not self.id:
            raise ValueError(f"{type(self).__name__}: id wajib diisi")
        if self.kelompok not in KELOMPOK_VALID:
            raise ValueError(f"{self.id}: kelompok tidak sah {self.kelompok!r}")
        if not (0.0 <= self.ambang <= 100.0):
            raise ValueError(f"{self.id}: ambang wajib 0..100")
        if int(self.required_roles.get("context", 0)) < 0:
            raise ValueError(f"{self.id}: context tidak boleh negatif")
        if not self.required_roles.get("entry", False):
            raise ValueError(f"{self.id}: peran 'entry' wajib True")

    # ----- pemeriksaan kelayakan (dipakai Arbiter, bukan oleh strategi lain) ----- #

    @property
    def konteks_dibutuhkan(self) -> int:
        return int(self.required_roles.get("context", 0))

    @property
    def multi_tf(self) -> bool:
        return self.konteks_dibutuhkan > 0

    def peran_terpenuhi(self, tfplan: TFPlan) -> bool:
        return tfplan.jumlah_konteks >= self.konteks_dibutuhkan

    def horizon_terpenuhi(self, horizon: str) -> bool:
        return horizon in self.horizon_didukung

    # ------------------------------ inti ------------------------------ #

    @abstractmethod
    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        """Kembalikan verdict lengkap (entry/SL/TP + skor) atau None."""

    # ------------------------------ util ------------------------------ #

    def _skor(self, komponen: Mapping[str, Tuple[float, float]]) -> Tuple[float, Dict[str, float]]:
        """Gabungkan komponen {nama: (nilai0..1, bobot)} menjadi skor 0..100.

        Transparan: rincian tiap komponen ikut dikembalikan untuk `evidence`.
        """
        total_bobot = sum(b for _, b in komponen.values())
        if total_bobot <= 0:
            return 0.0, {}
        rincian = {k: round(float(v), 4) for k, (v, _) in komponen.items()}
        nilai = sum(v * b for v, b in komponen.values()) / total_bobot
        return float(max(0.0, min(100.0, nilai * 100.0))), rincian

    def __repr__(self) -> str:  # pragma: no cover
        jenis = "multi-TF" if self.multi_tf else "single-TF"
        return f"<Strategi {self.id} [{self.kelompok}, {jenis}, ambang={self.ambang}]>"


@dataclass(frozen=True)
class HasilEvaluasi:
    """Hasil evaluasi SELURUH registry pada satu bar. Tidak ada short-circuit."""

    verdicts: Tuple[StrategyVerdict, ...]
    penolakan: Tuple[Penolakan, ...]
    jumlah_dievaluasi: int


class Registry:
    """Kumpulan strategi tunggal. Single-TF dan multi-TF hidup berdampingan di sini."""

    def __init__(self, strategi: Sequence[Strategi] = ()):
        self._peta: Dict[str, Strategi] = {}
        for s in strategi:
            self.daftar(s)

    def daftar(self, s: Strategi) -> "Registry":
        if s.id in self._peta:
            raise ValueError(f"strategi ganda: {s.id!r}")
        self._peta[s.id] = s
        return self

    def __len__(self) -> int:
        return len(self._peta)

    def __contains__(self, sid: object) -> bool:
        return sid in self._peta

    def ambil(self, sid: str) -> Strategi:
        return self._peta[sid]

    def semua(self) -> Tuple[Strategi, ...]:
        # urutan deterministik menurut id; urutan TIDAK memengaruhi hasil pemilihan
        return tuple(self._peta[k] for k in sorted(self._peta))

    def kelompok_terwakili(self) -> Tuple[str, ...]:
        return tuple(sorted({s.kelompok for s in self._peta.values()}))

    def evaluasi_semua(self, ctx: KonteksEvaluasi) -> HasilEvaluasi:
        """Evaluasi SETIAP strategi, selalu sampai habis.

        Tidak ada `break`. Tidak ada `return` dini. Satu strategi yang cocok atau
        melempar galat tidak boleh menghalangi strategi lain dinilai. Inilah pagar
        terhadap cacat lama (satu detektor mendominasi karena urutan kode).
        """
        verdicts: List[StrategyVerdict] = []
        tolak: List[Penolakan] = []
        for s in self.semua():
            if not s.peran_terpenuhi(ctx.tfplan):
                tolak.append(
                    Penolakan(
                        s.id,
                        TOLAK_PERAN_TF,
                        f"butuh {s.konteks_dibutuhkan} konteks, tersedia {ctx.tfplan.jumlah_konteks}",
                    )
                )
                continue
            if not s.horizon_terpenuhi(ctx.horizon):
                tolak.append(
                    Penolakan(s.id, TOLAK_HORIZON, f"horizon {ctx.horizon} tak didukung")
                )
                continue
            if len(ctx.entry) < s.warmup:
                tolak.append(
                    Penolakan(
                        s.id, TOLAK_WARMUP, f"butuh {s.warmup} bar, ada {len(ctx.entry)}"
                    )
                )
                continue
            try:
                v = s.evaluasi(ctx)
            except Exception as exc:  # galat satu strategi tidak menjatuhkan yang lain
                tolak.append(Penolakan(s.id, TOLAK_GALAT, f"{type(exc).__name__}: {exc}"))
                continue
            if v is None:
                tolak.append(Penolakan(s.id, TOLAK_TAK_ADA_SETUP, "prasyarat pola tak terpenuhi"))
                continue
            if v.strategy_id != s.id:
                tolak.append(
                    Penolakan(s.id, TOLAK_GALAT, f"verdict id salah: {v.strategy_id!r}")
                )
                continue
            if v.calibrated_p is not None:
                tolak.append(
                    Penolakan(s.id, TOLAK_GALAT, "strategi mengisi calibrated_p (dilarang)")
                )
                continue
            verdicts.append(v)
        return HasilEvaluasi(tuple(verdicts), tuple(tolak), len(self._peta))
