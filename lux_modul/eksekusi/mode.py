"""L4 - gerbang mode eksekusi berdasarkan horizon.

Aturan operator:
- scalping & intraday  -> auto_entry (boleh eksekusi otomatis)
- swing                -> signal_only (HANYA sinyal, tidak boleh auto-entry)

Gerbang ini berada di lapis eksekusi, bukan di strategi, supaya strategi yang sama
bisa dipakai untuk sinyal swing maupun auto-entry intraday tanpa perubahan logika.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..kontrak import (
    HORIZON_SWING,
    HORIZON_VALID,
    MODE_AUTO_ENTRY,
    MODE_PER_HORIZON,
    MODE_SIGNAL_ONLY,
    StrategyVerdict,
)


class ModeTerlarang(Exception):
    """Dilempar bila ada usaha auto-entry pada horizon yang hanya boleh sinyal."""


def mode_untuk(horizon: str) -> str:
    if horizon not in HORIZON_VALID:
        raise ValueError(f"horizon tidak sah: {horizon!r}")
    return MODE_PER_HORIZON[horizon]


def boleh_auto_entry(horizon: str) -> bool:
    return mode_untuk(horizon) == MODE_AUTO_ENTRY


def pastikan_boleh_eksekusi(horizon: str) -> None:
    if not boleh_auto_entry(horizon):
        raise ModeTerlarang(
            f"horizon {horizon!r} berada pada mode {mode_untuk(horizon)!r}: "
            "eksekusi otomatis tidak diizinkan, hanya penerbitan sinyal"
        )


@dataclass(frozen=True)
class Sinyal:
    """Keluaran untuk horizon signal_only (swing): tanpa order, hanya notifikasi."""

    simbol: str
    horizon: str
    verdict: StrategyVerdict

    @property
    def mode(self) -> str:
        return MODE_SIGNAL_ONLY

    def ringkas(self) -> dict:
        d = self.verdict.ringkas()
        d.update({"simbol": self.simbol, "horizon": self.horizon, "mode": self.mode})
        return d


def sinyal_swing(simbol: str, verdict: StrategyVerdict) -> Optional[Sinyal]:
    return Sinyal(simbol, HORIZON_SWING, verdict)
