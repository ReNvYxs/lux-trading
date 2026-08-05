"""L0 - DataPlane: kumpulan Bars multi-TF + penyusun KonteksEvaluasi.

Satu-satunya tempat penyelarasan waktu antar TF terjadi. Pagar anti look-ahead:
TF konteks hanya boleh melihat lilin yang SUDAH TUTUP pada waktu tutup lilin entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from ..fitur.store import FeatureStore
from ..kontrak import Bars, TFPlan, tf_ms


@dataclass(frozen=True)
class KonteksEvaluasi:
    """Satu-satunya masukan yang diterima strategi. Tidak berisi verdict siapa pun."""

    tfplan: TFPlan
    entry: Bars  # sudah dipotong sampai bar berjalan (inklusif)
    konteks: Mapping[str, Bars]  # TF -> Bars yang sudah tutup
    fitur: FeatureStore
    horizon: str
    ts_sekarang: int
    simbol: str = "?"

    @property
    def i(self) -> int:
        """Indeks bar berjalan pada TF entry."""
        return len(self.entry) - 1

    @property
    def harga(self) -> float:
        return float(self.entry.close[-1])

    def konteks_utama(self) -> Optional[Bars]:
        """TF konteks terkecil (paling dekat ke entry TF). None bila single-TF."""
        urut = self.tfplan.konteks_terurut()
        if not urut:
            return None
        return self.konteks.get(urut[0])

    def konteks_tertinggi(self) -> Optional[Bars]:
        urut = self.tfplan.konteks_terurut()
        if not urut:
            return None
        return self.konteks.get(urut[-1])


# Batas lookback yang diberikan ke strategi tiap evaluasi bar. Jauh lebih
# besar dari kebutuhan lookback internal strategi mana pun (indikator, pivot,
# pola harga), sehingga TIDAK mengubah sinyal apa pun. Ini membatasi biaya
# evaluasi per-bar agar tidak tumbuh tanpa batas seiring panjang riwayat
# (mencegah O(n^2) pada backtest panjang & perlambatan progresif saat live).
BATAS_LOOKBACK_BAR = 5000


class DataPlane:
    """Wadah Bars per TF untuk satu simbol."""

    def __init__(self, bars_per_tf: Mapping[str, Bars]):
        if not bars_per_tf:
            raise ValueError("DataPlane butuh minimal satu TF")
        simbol = {b.simbol for b in bars_per_tf.values()}
        if len(simbol) > 1:
            raise ValueError(f"DataPlane hanya untuk satu simbol, dapat {simbol}")
        for tf, b in bars_per_tf.items():
            if b.tf != tf:
                raise ValueError(f"kunci TF {tf!r} != bars.tf {b.tf!r}")
        self._bars: Dict[str, Bars] = dict(bars_per_tf)
        self.simbol = next(iter(simbol))

    @property
    def tfs(self) -> Tuple[str, ...]:
        return tuple(sorted(self._bars, key=tf_ms))

    def bars(self, tf: str) -> Bars:
        if tf not in self._bars:
            raise KeyError(f"TF {tf!r} tidak tersedia; ada {self.tfs}")
        return self._bars[tf]

    def punya(self, tf: str) -> bool:
        return tf in self._bars

    def dukung(self, tfplan: TFPlan) -> bool:
        return all(self.punya(t) for t in tfplan.semua_tf())

    def konteks_pada(
        self,
        i: int,
        tfplan: TFPlan,
        horizon: str,
        fitur: Optional[FeatureStore] = None,
    ) -> KonteksEvaluasi:
        """Bangun KonteksEvaluasi pada bar ke-i dari TF entry."""
        if not self.dukung(tfplan):
            hilang = [t for t in tfplan.semua_tf() if not self.punya(t)]
            raise KeyError(f"TF hilang untuk rencana ini: {hilang}")
        e = self.bars(tfplan.entry_tf)
        if not (0 <= i < len(e)):
            raise IndexError(f"indeks {i} di luar rentang TF entry ({len(e)})")
        ts_tutup = e.ts_tutup(i)
        konteks = {
            tf: self.bars(tf).hingga_waktu_tutup(ts_tutup, maks_lookback=BATAS_LOOKBACK_BAR)
            for tf in tfplan.context_tfs
        }
        return KonteksEvaluasi(
            tfplan=tfplan,
            entry=e.hingga_indeks(i, maks_lookback=BATAS_LOOKBACK_BAR),
            konteks=konteks,
            fitur=fitur if fitur is not None else FeatureStore(),
            horizon=horizon,
            ts_sekarang=ts_tutup,
            simbol=self.simbol,
        )

    @classmethod
    def dari_dasar(cls, dasar: Bars, tf_turunan: Tuple[str, ...] = ()) -> "DataPlane":
        """Bangun DataPlane dari satu TF dasar + turunan hasil resample."""
        from .resample import resample

        peta = {dasar.tf: dasar}
        for tf in tf_turunan:
            peta[tf] = resample(dasar, tf)
        return cls(peta)
