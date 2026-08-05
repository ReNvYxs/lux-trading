"""Adaptor pattern -> strategi lengkap.

Mengapa berkas ini ada: operator meminta pattern bisa ditambah TANPA mengubah
arsitektur inti. Detektor pattern hanya perlu melapor "pattern terbentuk, arah X,
level Y, invalidasi Z, komponen bukti begini". Semua sisanya (SL berbasis ATR +
invalidasi struktur, TP berbasis R, penggabungan skor, ambang, penegakan kontrak
verdict) diurus di sini secara seragam.

Hasilnya: satu fungsi + satu dekorator = satu strategi penuh yang punya entry, TP,
SL, skor, dan ambangnya sendiri, dan langsung ikut dievaluasi Registry bersama
strategi lain tanpa hak istimewa apa pun.
"""
from __future__ import annotations

from typing import Optional, Tuple

from ..data.plane import KonteksEvaluasi
from ..kontrak import (
    ARAH_LONG,
    HORIZON_VALID,
    StrategyVerdict,
    TargetTP,
)
from ..plugin import Deteksi, SpesifikasiPola
from .basis import Strategi
from .util import atr_kini, kekuatan_konteks, sl_valid


class StrategiPola(Strategi):
    """Pembungkus generik: mengubah satu detektor pattern menjadi strategi penuh."""

    def __init__(self, spek: SpesifikasiPola) -> None:
        self.spek = spek
        self.id = spek.nama
        self.kelompok = spek.kelompok
        self.ambang = spek.ambang
        self.warmup = spek.warmup
        self.horizon_didukung = spek.horizon or HORIZON_VALID
        self.required_roles = {"entry": True, "context": spek.konteks}
        self.deskripsi = spek.deskripsi
        self.sumber = spek.sumber
        super().__init__()

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        d = self.spek.detektor(ctx)
        if d is None:
            return None
        if not isinstance(d, Deteksi):
            raise TypeError(f"{self.id}: detektor wajib mengembalikan Deteksi atau None")

        harga = ctx.harga
        atr = atr_kini(ctx)

        # Komponen konteks TF lebih tinggi hanya ditambahkan bila strategi memang
        # mendeklarasikan butuh konteks. Strategi single-TF tidak terpengaruh.
        komponen = dict(d.komponen)
        if self.multi_tf:
            komponen["konteks_tf"] = (kekuatan_konteks(ctx, d.arah), 1.0)

        skor, rincian = self._skor(komponen)

        # SL: sisi terjauh antara invalidasi struktural pattern dan buffer ATR.
        buffer = self.spek.sl_atr * atr
        if d.arah == ARAH_LONG:
            sl_mentah = min(float(d.invalidation), harga - buffer)
        else:
            sl_mentah = max(float(d.invalidation), harga + buffer)
        sl = sl_valid(d.arah, harga, sl_mentah, minimum=0.15 * atr)

        r = abs(harga - sl)
        if r <= 0:
            return None

        tps: Tuple[TargetTP, ...] = tuple(
            TargetTP(
                harga + k * r if d.arah == ARAH_LONG else harga - k * r,
                p,
                f"tp{n + 1}_{k}R",
            )
            for n, (k, p) in enumerate(zip(self.spek.rr, self.spek.porsi))
            if (harga + k * r if d.arah == ARAH_LONG else harga - k * r) > 0
        )
        if not tps:
            return None

        bukti = dict(d.bukti)
        bukti["komponen_skor"] = rincian
        bukti["atr"] = round(atr, 10)
        bukti["sumber_pola"] = self.spek.nama

        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=d.arah,
            skor=skor,
            ambang=self.ambang,
            entry=harga,
            sl=sl,
            tps=tps,
            level=float(d.level),
            invalidation=float(d.invalidation),
            tfs_used=ctx.tfplan.semua_tf(),
            features_used=d.fitur,
            evidence=bukti,
            ts_sinyal=ctx.ts_sekarang,
        )
