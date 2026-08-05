"""L3 - Arbiter: pembobotan, ambang, resolusi konflik arah, pemilihan akhir.

Aturan yang WAJIB dipegang (tercantum di ARSITEKTUR.md):
1. SETIAP strategi dievaluasi tiap candle. Tidak ada short-circuit, tidak ada urutan
   prioritas. Urutan pendaftaran strategi TIDAK memengaruhi hasil.
2. Lolos ambang = skor > ambang strategi itu sendiri (ketat, bukan >=).
3. Dari yang lolos, dieksekusi yang skornya TERTINGGI.
4. Bila dua strategi lolos dengan arah berlawanan dan selisih skor < MARGIN_KONFLIK
   (5.0 poin), keduanya dianggap saling meniadakan -> TIDAK ADA ENTRY.
5. Arbiter tidak menghitung fitur sendiri dan tidak mengubah verdict strategi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from ..data.plane import KonteksEvaluasi
from ..kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    Penolakan,
    StrategyVerdict,
    TOLAK_AMBANG,
    arah_lawan,
)
from ..strategi.basis import HasilEvaluasi, Registry

MARGIN_KONFLIK = 5.0

ALASAN_TIDAK_ADA_KANDIDAT = "tak_ada_kandidat"
ALASAN_SEMUA_DI_BAWAH_AMBANG = "semua_di_bawah_ambang"
ALASAN_KONFLIK_ARAH = "konflik_arah_saling_meniadakan"
ALASAN_TERPILIH = "skor_tertinggi_di_atas_ambang"


@dataclass(frozen=True)
class Keputusan:
    """Hasil akhir satu candle."""

    verdict: Optional[StrategyVerdict]
    alasan: str
    lolos: Tuple[StrategyVerdict, ...] = ()
    kandidat: Tuple[StrategyVerdict, ...] = ()
    ditolak: Tuple[Penolakan, ...] = ()
    jumlah_dievaluasi: int = 0
    catatan: Dict[str, object] = field(default_factory=dict)

    @property
    def ada_entry(self) -> bool:
        return self.verdict is not None

    def ringkas(self) -> Dict[str, object]:
        return {
            "alasan": self.alasan,
            "dievaluasi": self.jumlah_dievaluasi,
            "kandidat": [v.strategy_id for v in self.kandidat],
            "lolos": [(v.strategy_id, round(v.skor, 2), v.arah) for v in self.lolos],
            "terpilih": self.verdict.ringkas() if self.verdict else None,
            "catatan": self.catatan,
        }


class Arbiter:
    def __init__(self, registry: Registry, margin_konflik: float = MARGIN_KONFLIK):
        if margin_konflik < 0:
            raise ValueError("margin_konflik tidak boleh negatif")
        self.registry = registry
        self.margin_konflik = float(margin_konflik)

    # -------------------------------------------------------------- #

    def putuskan(self, ctx: KonteksEvaluasi) -> Keputusan:
        hasil: HasilEvaluasi = self.registry.evaluasi_semua(ctx)
        return self.putuskan_dari(hasil)

    def putuskan_dari(self, hasil: HasilEvaluasi) -> Keputusan:
        """Pemilihan murni dari kumpulan verdict. Dipisah agar mudah diuji."""
        kandidat = hasil.verdicts
        ditolak: List[Penolakan] = list(hasil.penolakan)

        if not kandidat:
            return Keputusan(
                None,
                ALASAN_TIDAK_ADA_KANDIDAT,
                (),
                (),
                tuple(ditolak),
                hasil.jumlah_dievaluasi,
            )

        lolos: List[StrategyVerdict] = []
        for v in kandidat:
            if v.lolos_ambang:
                lolos.append(v)
            else:
                ditolak.append(
                    Penolakan(
                        v.strategy_id,
                        TOLAK_AMBANG,
                        f"skor {v.skor:.2f} <= ambang {v.ambang:.2f}",
                    )
                )
        if not lolos:
            return Keputusan(
                None,
                ALASAN_SEMUA_DI_BAWAH_AMBANG,
                (),
                kandidat,
                tuple(ditolak),
                hasil.jumlah_dievaluasi,
                {"skor_tertinggi": max(v.skor for v in kandidat)},
            )

        # urut deterministik: skor desc, lalu id asc (tie-break stabil, bukan urutan daftar)
        urut = sorted(lolos, key=lambda v: (-v.skor, v.strategy_id))
        teratas = urut[0]

        lawan = [v for v in urut if v.arah == arah_lawan(teratas.arah)]
        if lawan:
            penantang = lawan[0]
            selisih = teratas.skor - penantang.skor
            if selisih < self.margin_konflik:
                return Keputusan(
                    None,
                    ALASAN_KONFLIK_ARAH,
                    tuple(urut),
                    kandidat,
                    tuple(ditolak),
                    hasil.jumlah_dievaluasi,
                    {
                        "pihak_a": teratas.ringkas(),
                        "pihak_b": penantang.ringkas(),
                        "selisih_skor": round(selisih, 4),
                        "margin_konflik": self.margin_konflik,
                    },
                )

        return Keputusan(
            teratas,
            ALASAN_TERPILIH,
            tuple(urut),
            kandidat,
            tuple(ditolak),
            hasil.jumlah_dievaluasi,
            {
                "jumlah_lolos": len(urut),
                "runner_up": urut[1].ringkas() if len(urut) > 1 else None,
            },
        )
