"""Kelompok 3 - STRUKTUR MODERN (SMC / ICT / Breakout+Volume).

Strategi: SMC Order Block + FVG (multi-TF), ICT Liquidity Sweep + CHoCH,
Range Breakout dengan ekspansi volume.
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from ..data.plane import KonteksEvaluasi
from ..fitur import struktur as st
from ..kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    KELOMPOK_STRUKTUR,
    StrategyVerdict,
    TargetTP,
)
from .basis import Strategi
from .pola import _saring_tps, _skala
from .util import atr_kini, kekuatan_konteks, sl_valid, tps_rr, volume_breakout


# --------------------------------------------------------------------------- #
# 10. SMC: BOS -> retrace ke Order Block / FVG (MULTI-TF)
# --------------------------------------------------------------------------- #


class SmcOrderBlockFvg(Strategi):
    """Smart Money Concepts: BOS lalu harga kembali ke Order Block / FVG.

    Multi-TF: butuh 1 TF konteks sebagai penentu bias (higher timeframe narrative).
    Entry : harga menyentuh zona OB/FVG searah BOS dan ditutup kembali ke dalam zona.
    SL    : di luar batas Order Block + buffer ATR.
    TP    : likuiditas berlawanan (pivot terakhir arah target), cadangan 2R.
    """

    id = "smc_ob_fvg"
    kelompok = KELOMPOK_STRUKTUR
    ambang = 65.0
    warmup = 120
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 1}  # MULTI-TF
    deskripsi = "BOS lalu mitigasi ke order block / fair value gap searah bias TF atas."
    sumber = (
        "tradingwyckoff.com/en/smart-money-concepts/",
        "fluxcharts.com - order block + FVG entry model",
        "innercircletrader.net - mitigasi OB setelah break of structure",
    )

    maks_umur_bos = 40
    buffer_sl_atr = 0.35

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        kb = ctx.konteks_utama()
        if kb is None or len(kb) < 60:
            return None
        peristiwa = ctx.fitur.peristiwa_struktur(b, 2, 2)
        if not peristiwa:
            return None
        terakhir = [p for p in peristiwa if 0 < i - p.idx <= self.maks_umur_bos]
        if not terakhir:
            return None
        ev = terakhir[-1]
        arah = ARAH_LONG if ev.arah == "naik" else ARAH_SHORT

        dukungan = kekuatan_konteks(ctx, arah)
        if dukungan < 0.5:
            return None  # bias TF konteks menolak

        ob = st.order_block_sebelum(b.open, b.high, b.low, b.close, ev.idx, ev.arah)
        if ob is None:
            return None
        atr = atr_kini(ctx, b)
        h = np.asarray(b.high, dtype=float)
        l = np.asarray(b.low, dtype=float)
        c = np.asarray(b.close, dtype=float)

        # mitigasi: bar berjalan menyentuh zona OB dan ditutup di sisi yang benar
        if arah == ARAH_LONG:
            sentuh = l[i] <= ob.atas and c[i] >= ob.bawah
            keluar_zona = c[i] > ob.bawah
        else:
            sentuh = h[i] >= ob.bawah and c[i] <= ob.atas
            keluar_zona = c[i] < ob.atas
        if not (sentuh and keluar_zona):
            return None

        # FVG searah yang belum terisi menambah kualitas (bukan syarat wajib)
        gaps = [
            g
            for g in ctx.fitur.fvg(b, 0.1 * atr)
            if g.arah == ev.arah and ob.idx <= g.idx <= ev.idx
        ]
        ada_fvg = 1.0 if gaps else 0.0

        entry = float(c[i])
        sl = ob.bawah - self.buffer_sl_atr * atr if arah == ARAH_LONG else ob.atas + self.buffer_sl_atr * atr
        sl = sl_valid(arah, entry, sl, 0.2 * atr)

        piv = ctx.fitur.pivots(b, 2, 2)
        likuiditas = st.pivot_terakhir(piv, "high" if arah == ARAH_LONG else "low", 1)
        tps = tps_rr(arah, entry, sl, ((2.0, 0.5, "tp1_2R"), (3.5, 0.5, "tp2_3R5")))
        if likuiditas:
            t = likuiditas[0].harga
            layak = t > entry if arah == ARAH_LONG else t < entry
            if layak:
                tps = (
                    TargetTP(float(t), 0.5, "tp1_likuiditas_berlawanan"),
                    tps_rr(arah, entry, sl, ((3.5, 0.5, "tp2_3R5"),))[0],
                )
        tps = _saring_tps(arah, entry, tps)
        if not tps:
            return None

        umur = i - ev.idx
        tinggi_ob = max(ob.atas - ob.bawah, 1e-12)
        skor, rincian = self._skor(
            {
                "jenis_peristiwa": (1.0 if ev.jenis == "CHoCH" else 0.75, 0.15),
                "kesegaran_bos": (1.0 - _skala(umur, 1, self.maks_umur_bos), 0.20),
                "dukungan_konteks": (dukungan, 0.25),
                "ada_fvg": (ada_fvg, 0.20),
                "presisi_zona": (1.0 - _skala(tinggi_ob / atr, 0.3, 2.5), 0.20),
            }
        )
        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=arah,
            skor=skor,
            ambang=self.ambang,
            entry=entry,
            sl=float(sl),
            tps=tps,
            level=float(ob.tengah),
            invalidation=float(ob.bawah if arah == ARAH_LONG else ob.atas),
            tfs_used=(b.tf, kb.tf),
            features_used=("peristiwa_struktur", "order_block", "fvg", "atr"),
            evidence={
                "peristiwa": ev.jenis,
                "peristiwa_idx": ev.idx,
                "ob_atas": ob.atas,
                "ob_bawah": ob.bawah,
                "jumlah_fvg": len(gaps),
                "tf_konteks": kb.tf,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )


# --------------------------------------------------------------------------- #
# 11. ICT Liquidity Sweep + CHoCH
# --------------------------------------------------------------------------- #


class IctLiquiditySweep(Strategi):
    """Sapuan likuiditas pada swing lama lalu penolakan cepat.

    Entry : bar yang menembus swing (stop hunt) namun ditutup kembali di sisi semula.
    SL    : di luar ekstrem sapuan + buffer ATR.
    TP    : kolam likuiditas berlawanan (swing berlawanan terakhir), cadangan 2R.
    """

    id = "ict_liquidity_sweep"
    kelompok = KELOMPOK_STRUKTUR
    ambang = 62.0
    warmup = 100
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}  # single-TF
    deskripsi = "Liquidity sweep pada swing lama dengan penutupan balik (rejection)."
    sumber = (
        "innercircletrader.net/tutorials/ict-liquidity-sweep-vs-liquidity-run/",
        "dailypriceaction.com/blog/liquidity-sweep-reversals/",
        "atas.net - sweep ditandai wick panjang menembus level lalu close balik",
    )

    umur_swing_min = 5
    umur_swing_maks = 80
    buffer_sl_atr = 0.25

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        piv = ctx.fitur.pivots(b, 2, 2)
        atr = atr_kini(ctx, b)
        h = np.asarray(b.high, dtype=float)
        l = np.asarray(b.low, dtype=float)
        c = np.asarray(b.close, dtype=float)
        rentang_bar = max(h[i] - l[i], 1e-12)

        for arah in (ARAH_LONG, ARAH_SHORT):
            tipe = "low" if arah == ARAH_LONG else "high"
            kandidat = [
                p
                for p in piv
                if p.tipe == tipe and self.umur_swing_min <= i - p.idx <= self.umur_swing_maks
            ]
            if not kandidat:
                continue
            p = min(kandidat, key=lambda q: q.harga) if arah == ARAH_LONG else max(kandidat, key=lambda q: q.harga)
            if not st.sapuan_likuiditas(h, l, c, i, p.harga, "naik" if arah == ARAH_LONG else "turun"):
                continue
            # penolakan wajib tegas: sumbu yang menembus minimal 40% badan bar
            if arah == ARAH_LONG:
                sumbu = min(c[i], b.open[i]) - l[i]
                ekstrem = float(l[i])
                sl = ekstrem - self.buffer_sl_atr * atr
            else:
                sumbu = h[i] - max(c[i], b.open[i])
                ekstrem = float(h[i])
                sl = ekstrem + self.buffer_sl_atr * atr
            rasio_sumbu = float(sumbu) / rentang_bar
            if rasio_sumbu < 0.40:
                continue

            entry = float(c[i])
            sl = sl_valid(arah, entry, sl, 0.15 * atr)
            lawan = st.pivot_terakhir(piv, "high" if arah == ARAH_LONG else "low", 1)
            tps = tps_rr(arah, entry, sl, ((2.0, 0.5, "tp1_2R"), (3.0, 0.5, "tp2_3R")))
            if lawan:
                t = lawan[0].harga
                layak = t > entry if arah == ARAH_LONG else t < entry
                if layak:
                    tps = (
                        TargetTP(float(t), 0.5, "tp1_kolam_likuiditas"),
                        tps_rr(arah, entry, sl, ((3.0, 0.5, "tp2_3R"),))[0],
                    )
            tps = _saring_tps(arah, entry, tps)
            if not tps:
                continue

            kedalaman_sweep = abs(p.harga - ekstrem) / atr
            skor, rincian = self._skor(
                {
                    "rasio_sumbu": (_skala(rasio_sumbu, 0.40, 0.85), 0.30),
                    "kedalaman_sweep": (1.0 - _skala(kedalaman_sweep, 0.05, 1.2), 0.20),
                    "umur_likuiditas": (_skala(i - p.idx, self.umur_swing_min, 40), 0.20),
                    "volume": (_skala(volume_breakout(ctx), 1.0, 2.5), 0.20),
                    "posisi_close": (
                        _skala(
                            (c[i] - l[i]) / rentang_bar if arah == ARAH_LONG else (h[i] - c[i]) / rentang_bar,
                            0.5,
                            0.95,
                        ),
                        0.10,
                    ),
                }
            )
            return StrategyVerdict(
                strategy_id=self.id,
                kelompok=self.kelompok,
                arah=arah,
                skor=skor,
                ambang=self.ambang,
                entry=entry,
                sl=float(sl),
                tps=tps,
                level=float(p.harga),
                invalidation=ekstrem,
                tfs_used=(b.tf,),
                features_used=("pivots", "atr", "rasio_volume"),
                evidence={
                    "level_likuiditas": p.harga,
                    "idx_likuiditas": p.idx,
                    "ekstrem_sweep": ekstrem,
                    "rasio_sumbu": rasio_sumbu,
                    "komponen_skor": rincian,
                },
                ts_sinyal=int(b.ts_tutup(i)),
            )
        return None


# --------------------------------------------------------------------------- #
# 12. Range Breakout + ekspansi volume
# --------------------------------------------------------------------------- #


class BreakoutVolume(Strategi):
    """Penembusan range konsolidasi dengan ekspansi volume.

    Entry : penutupan di luar range konsolidasi n-bar disertai volume >= 1.5x rata-rata.
    SL    : kembali ke dalam range (sisi seberang batas) atau 2x ATR, mana yang lebih dekat.
    TP    : tinggi range diproyeksikan dari titik breakout.
    """

    id = "breakout_volume"
    kelompok = KELOMPOK_STRUKTUR
    ambang = 59.0
    warmup = 80
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}  # single-TF
    deskripsi = "Breakout range sempit dengan konfirmasi ekspansi volume."
    sumber = (
        "investopedia.com/articles/trading/08/trading-breakouts.asp",
        "tradingsim.com - volume >= 1.5x rata-rata sebagai konfirmasi breakout",
        "chartmill.com - target awal = tinggi range",
    )

    panjang_range = 20
    rasio_volume_min = 1.5
    kesempitan_maks_atr = 3.5

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        if i < self.panjang_range + 1:
            return None
        rng = st.rentang_konsolidasi(b.high, b.low, i - 1, self.panjang_range)
        if rng is None or rng.tinggi <= 0:
            return None
        atr = atr_kini(ctx, b)
        if rng.tinggi > self.kesempitan_maks_atr * atr:
            return None  # bukan konsolidasi, sudah trending
        vol = volume_breakout(ctx)
        if vol < self.rasio_volume_min:
            return None

        c = np.asarray(b.close, dtype=float)
        if c[i] > rng.atas:
            arah, level, lawan = ARAH_LONG, rng.atas, rng.bawah
        elif c[i] < rng.bawah:
            arah, level, lawan = ARAH_SHORT, rng.bawah, rng.atas
        else:
            return None
        if rng.bawah <= c[i - 1] <= rng.atas:
            pass
        else:
            return None  # breakout wajib baru pada bar ini

        entry = float(c[i])
        if arah == ARAH_LONG:
            sl = max(rng.tengah, entry - 2.0 * atr)
        else:
            sl = min(rng.tengah, entry + 2.0 * atr)
        sl = sl_valid(arah, entry, sl, 0.25 * atr)

        from .util import tps_terukur

        tps = _saring_tps(arah, entry, tps_terukur(arah, level, rng.tinggi))
        if not tps:
            return None

        kesempitan = 1.0 - _skala(rng.tinggi / atr, 0.8, self.kesempitan_maks_atr)
        skor, rincian = self._skor(
            {
                "ekspansi_volume": (_skala(vol, self.rasio_volume_min, 3.5), 0.35),
                "kesempitan_range": (kesempitan, 0.25),
                "ketegasan_break": (_skala(abs(entry - level) / atr, 0.05, 0.8), 0.25),
                "tinggi_range": (_skala(rng.tinggi / atr, 0.8, 3.0), 0.15),
            }
        )
        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=arah,
            skor=skor,
            ambang=self.ambang,
            entry=entry,
            sl=float(sl),
            tps=tps,
            level=float(level),
            invalidation=float(lawan),
            tfs_used=(b.tf,),
            features_used=("rentang_konsolidasi", "rasio_volume", "atr"),
            evidence={
                "range_atas": rng.atas,
                "range_bawah": rng.bawah,
                "tinggi_range": rng.tinggi,
                "volume_rasio": vol,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )
