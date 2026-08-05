"""Kelompok 1 - POLA KLASIK.

Strategi: Double Top, Double Bottom, Head & Shoulders (+inverse), Triangle Breakout,
Wedge (rising/falling), Cup and Handle.

Aturan entry/SL/TP mengikuti rumusan baku pola (lihat REFERENSI.md). Seluruh angka
parameter di sini adalah TITIK AWAL dari riset, BUKAN kebenaran teruji.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from ..data.plane import KonteksEvaluasi
from ..fitur import struktur as st
from ..kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    KELOMPOK_POLA,
    StrategyVerdict,
    TargetTP,
)
from .basis import Strategi
from .util import (
    atr_kini,
    beda_relatif,
    kekuatan_konteks,
    sl_valid,
    tps_terukur,
    volume_breakout,
)


def _saring_tps(arah: str, entry: float, tps: Tuple[TargetTP, ...]) -> Tuple[TargetTP, ...]:
    """Buang TP yang berada di sisi salah; kembalikan tuple kosong bila habis."""
    ok: List[TargetTP] = []
    for t in tps:
        if arah == ARAH_LONG and t.harga > entry:
            ok.append(t)
        elif arah == ARAH_SHORT and t.harga < entry:
            ok.append(t)
    if not ok:
        return ()
    total = sum(t.porsi for t in ok)
    if total > 1.0:
        ok = [TargetTP(t.harga, t.porsi / total, t.label) for t in ok]
    return tuple(ok)


def _skala(nilai: float, rendah: float, tinggi: float) -> float:
    if not np.isfinite(nilai) or tinggi == rendah:
        return 0.0
    return float(min(1.0, max(0.0, (nilai - rendah) / (tinggi - rendah))))


# --------------------------------------------------------------------------- #
# 1 & 2. Double Top / Double Bottom
# --------------------------------------------------------------------------- #


class _DuaEkstrem(Strategi):
    """Basis Double Top / Double Bottom.

    Entry : penutupan menembus neckline (lembah antar puncak / puncak antar lembah).
    SL    : di luar ekstrem tertinggi/terendah pola + buffer ATR.
    TP    : measured move dari neckline sebesar tinggi pola (parsial 0.618 lalu 1.0).
    """

    kelompok = KELOMPOK_POLA
    warmup = 80
    ambang = 62.0
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}  # single-TF

    arah_pola: str = ARAH_SHORT
    toleransi_puncak: float = 0.012
    jarak_min: int = 5
    jarak_maks: int = 70
    buffer_sl_atr: float = 0.30

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        if i < 2:
            return None
        tipe = "high" if self.arah_pola == ARAH_SHORT else "low"
        ps = st.pivot_terakhir(ctx.fitur.pivots(b, 2, 2), tipe, 2)
        if len(ps) < 2:
            return None
        p1, p2 = ps[-2], ps[-1]
        jarak = p2.idx - p1.idx
        if not (self.jarak_min <= jarak <= self.jarak_maks):
            return None
        kesamaan = beda_relatif(p1.harga, p2.harga)
        if kesamaan > self.toleransi_puncak:
            return None

        seg = slice(p1.idx, p2.idx + 1)
        atr = atr_kini(ctx, b)
        if self.arah_pola == ARAH_SHORT:
            neckline = float(np.min(np.asarray(b.low)[seg]))
            puncak = max(p1.harga, p2.harga)
            tinggi = puncak - neckline
        else:
            neckline = float(np.max(np.asarray(b.high)[seg]))
            puncak = min(p1.harga, p2.harga)
            tinggi = neckline - puncak
        if tinggi <= 0.8 * atr:
            return None

        c = np.asarray(b.close, dtype=float)
        if self.arah_pola == ARAH_SHORT:
            tembus = c[i] < neckline and c[i - 1] >= neckline
        else:
            tembus = c[i] > neckline and c[i - 1] <= neckline
        if not tembus:
            return None

        # tren pendahulu wajib searah pembalikan (Double Top butuh uptrend sebelumnya)
        awal = max(0, p1.idx - 20)
        tren_ok = (
            c[p1.idx] > c[awal] if self.arah_pola == ARAH_SHORT else c[p1.idx] < c[awal]
        )
        if not tren_ok:
            return None

        arah = self.arah_pola
        entry = float(c[i])
        if arah == ARAH_SHORT:
            sl = puncak + self.buffer_sl_atr * atr
        else:
            sl = puncak - self.buffer_sl_atr * atr
        sl = sl_valid(arah, entry, sl, 0.15 * atr)

        dasar_tp = neckline
        tps = tps_terukur(arah, dasar_tp, tinggi)
        tps = _saring_tps(arah, entry, tps)
        if not tps:
            return None

        vol = volume_breakout(ctx)
        ketegasan = abs(entry - neckline) / atr
        skor, rincian = self._skor(
            {
                "kesamaan_puncak": (1.0 - _skala(kesamaan, 0.0, self.toleransi_puncak), 0.25),
                "kedalaman_pola": (_skala(tinggi / atr, 0.8, 3.5), 0.25),
                "volume_breakout": (_skala(vol, 0.9, 2.0), 0.20),
                "ketegasan_break": (_skala(ketegasan, 0.02, 0.60), 0.15),
                "simetri_jarak": (_skala(jarak, self.jarak_min, 30), 0.15),
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
            level=float(neckline),
            invalidation=float(puncak),
            tfs_used=(b.tf,),
            features_used=("pivots", "atr", "rasio_volume"),
            evidence={
                "pola": self.id,
                "p1_idx": p1.idx,
                "p2_idx": p2.idx,
                "p1": p1.harga,
                "p2": p2.harga,
                "neckline": neckline,
                "tinggi": tinggi,
                "atr": atr,
                "volume_rasio": vol,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )


class DoubleTop(_DuaEkstrem):
    id = "double_top"
    arah_pola = ARAH_SHORT
    deskripsi = "Dua puncak sejajar, entry saat penutupan menembus neckline ke bawah."
    sumber = (
        "investopedia.com/terms/d/doubletop.asp",
        "trendspider.com/learning-center/chart-patterns-double-bottoms-and-tops/",
        "tastyfx.com - double top: SL di atas puncak kedua, TP = neckline - tinggi pola",
    )


class DoubleBottom(_DuaEkstrem):
    id = "double_bottom"
    arah_pola = ARAH_LONG
    deskripsi = "Dua lembah sejajar, entry saat penutupan menembus neckline ke atas."
    sumber = (
        "trendspider.com/learning-center/chart-patterns-double-bottoms-and-tops/",
        "oanda.com - double bottom: konfirmasi wajib break neckline",
        "tradezero.com/blog/how-to-trade-double-top-and-double-bottom-chart-patterns",
    )


# --------------------------------------------------------------------------- #
# 3. Head & Shoulders (+ inverse)
# --------------------------------------------------------------------------- #


class HeadShoulders(Strategi):
    """Head & Shoulders dan Inverse Head & Shoulders dalam satu strategi.

    Entry : penutupan menembus neckline (garis lewat dua lembah/puncak antar bahu).
    SL    : di luar bahu kanan + buffer ATR.
    TP    : jarak kepala-neckline diproyeksikan dari titik breakout.
    """

    id = "head_shoulders"
    kelompok = KELOMPOK_POLA
    ambang = 64.0
    warmup = 120
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}
    deskripsi = "Tiga puncak dengan kepala tertinggi; entry saat neckline tertembus."
    sumber = (
        "investopedia.com/articles/technical/121201.asp",
        "oanda.com - H&S: SL tepat di atas bahu kanan",
        "schwab.com - target = jarak kepala ke neckline dari titik breakout",
    )

    toleransi_bahu = 0.05
    buffer_sl_atr = 0.30

    def _coba(self, ctx: KonteksEvaluasi, arah: str) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        piv = ctx.fitur.pivots(b, 2, 2)
        tipe_utama = "high" if arah == ARAH_SHORT else "low"
        tipe_neck = "low" if arah == ARAH_SHORT else "high"
        tiga = st.pivot_terakhir(piv, tipe_utama, 3)
        if len(tiga) < 3:
            return None
        ls, kepala, rs = tiga
        if arah == ARAH_SHORT:
            if not (kepala.harga > ls.harga and kepala.harga > rs.harga):
                return None
        else:
            if not (kepala.harga < ls.harga and kepala.harga < rs.harga):
                return None
        if beda_relatif(ls.harga, rs.harga) > self.toleransi_bahu:
            return None

        lembah = [p for p in piv if p.tipe == tipe_neck and ls.idx < p.idx < rs.idx]
        if len(lembah) < 2:
            return None
        n1, n2 = lembah[0], lembah[-1]
        garis = st.garis_lewat_pivot([n1, n2])
        if garis is None:
            return None
        neck_i = st.nilai_garis(garis, i)
        neck_kepala = st.nilai_garis(garis, kepala.idx)
        tinggi = abs(kepala.harga - neck_kepala)
        atr = atr_kini(ctx, b)
        if tinggi <= 1.0 * atr:
            return None

        c = np.asarray(b.close, dtype=float)
        neck_prev = st.nilai_garis(garis, i - 1)
        if arah == ARAH_SHORT:
            tembus = c[i] < neck_i and c[i - 1] >= neck_prev
        else:
            tembus = c[i] > neck_i and c[i - 1] <= neck_prev
        if not tembus:
            return None

        entry = float(c[i])
        sl = rs.harga + self.buffer_sl_atr * atr if arah == ARAH_SHORT else rs.harga - self.buffer_sl_atr * atr
        sl = sl_valid(arah, entry, sl, 0.15 * atr)
        tps = _saring_tps(arah, entry, tps_terukur(arah, neck_i, tinggi))
        if not tps:
            return None

        vol = volume_breakout(ctx)
        simetri = 1.0 - min(1.0, beda_relatif(kepala.idx - ls.idx, rs.idx - kepala.idx))
        dominasi = abs(kepala.harga - (ls.harga + rs.harga) / 2.0) / atr
        skor, rincian = self._skor(
            {
                "simetri_bahu": (1.0 - _skala(beda_relatif(ls.harga, rs.harga), 0.0, self.toleransi_bahu), 0.25),
                "dominasi_kepala": (_skala(dominasi, 0.5, 3.0), 0.25),
                "simetri_waktu": (simetri, 0.15),
                "volume_breakout": (_skala(vol, 0.9, 2.0), 0.20),
                "tinggi_relatif": (_skala(tinggi / atr, 1.0, 4.0), 0.15),
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
            level=float(neck_i),
            invalidation=float(rs.harga),
            tfs_used=(b.tf,),
            features_used=("pivots", "atr", "rasio_volume"),
            evidence={
                "varian": "H&S" if arah == ARAH_SHORT else "inverse H&S",
                "bahu_kiri": ls.harga,
                "kepala": kepala.harga,
                "bahu_kanan": rs.harga,
                "neckline_di_i": neck_i,
                "tinggi": tinggi,
                "volume_rasio": vol,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        # Kedua varian dicoba; yang skornya lebih tinggi dipakai. Ini TIDAK membaca
        # strategi lain - hanya dua varian internal dari pola yang sama.
        kandidat = [v for v in (self._coba(ctx, ARAH_SHORT), self._coba(ctx, ARAH_LONG)) if v]
        if not kandidat:
            return None
        return max(kandidat, key=lambda v: v.skor)


# --------------------------------------------------------------------------- #
# 4. Triangle breakout
# --------------------------------------------------------------------------- #


class TriangleBreakout(Strategi):
    """Segitiga (ascending/descending/symmetrical) yang menyempit lalu ditembus.

    Entry : penutupan menembus garis tren yang relevan.
    SL    : sisi berlawanan segitiga pada bar breakout + buffer ATR.
    TP    : measured move sebesar lebar terlebar segitiga.
    """

    id = "triangle_breakout"
    kelompok = KELOMPOK_POLA
    ambang = 60.0
    warmup = 90
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}
    deskripsi = "Konvergensi dua garis tren, entry pada penembusan penutupan."
    sumber = (
        "investopedia.com/articles/trading/08/trading-breakouts.asp",
        "quantvps.com/blog/trading-the-wedge-pattern (entry breakout vs retest)",
        "naga.com/academy - target = tinggi pola pada titik terlebar",
    )

    buffer_sl_atr = 0.35
    rasio_konvergensi_min = 1.35

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        piv = ctx.fitur.pivots(b, 2, 2)
        hi = st.pivot_terakhir(piv, "high", 3)
        lo = st.pivot_terakhir(piv, "low", 3)
        if len(hi) < 2 or len(lo) < 2:
            return None
        g_atas = st.garis_lewat_pivot(hi)
        g_bawah = st.garis_lewat_pivot(lo)
        if g_atas is None or g_bawah is None:
            return None

        mulai = min(hi[0].idx, lo[0].idx)
        lebar_awal = st.nilai_garis(g_atas, mulai) - st.nilai_garis(g_bawah, mulai)
        lebar_kini = st.nilai_garis(g_atas, i) - st.nilai_garis(g_bawah, i)
        if lebar_kini <= 0 or lebar_awal <= 0:
            return None
        if lebar_awal / lebar_kini < self.rasio_konvergensi_min:
            return None  # tidak cukup menyempit -> bukan segitiga

        # segitiga wajib konvergen: minimal satu garis mengarah ke garis lainnya
        if not (g_atas[0] < 0 or g_bawah[0] > 0):
            return None

        c = np.asarray(b.close, dtype=float)
        atas_i, bawah_i = st.nilai_garis(g_atas, i), st.nilai_garis(g_bawah, i)
        atas_p, bawah_p = st.nilai_garis(g_atas, i - 1), st.nilai_garis(g_bawah, i - 1)
        atr = atr_kini(ctx, b)
        if c[i] > atas_i and bawah_p <= c[i - 1] <= atas_p:
            arah, level, sisi_lawan = ARAH_LONG, atas_i, bawah_i
        elif c[i] < bawah_i and bawah_p <= c[i - 1] <= atas_p:
            arah, level, sisi_lawan = ARAH_SHORT, bawah_i, atas_i
        else:
            return None

        entry = float(c[i])
        sl = sisi_lawan - self.buffer_sl_atr * atr if arah == ARAH_LONG else sisi_lawan + self.buffer_sl_atr * atr
        # SL segitiga bisa sangat lebar; batasi ke 1.5x lebar kini
        maks = 1.5 * lebar_kini + self.buffer_sl_atr * atr
        if arah == ARAH_LONG:
            sl = max(sl, entry - maks)
        else:
            sl = min(sl, entry + maks)
        sl = sl_valid(arah, entry, sl, 0.2 * atr)

        tps = _saring_tps(arah, entry, tps_terukur(arah, level, lebar_awal))
        if not tps:
            return None

        vol = volume_breakout(ctx)
        sentuhan = len(hi) + len(lo)
        skor, rincian = self._skor(
            {
                "konvergensi": (_skala(lebar_awal / lebar_kini, 1.35, 4.0), 0.25),
                "jumlah_sentuhan": (_skala(sentuhan, 4, 6), 0.15),
                "volume_breakout": (_skala(vol, 1.0, 2.2), 0.25),
                "ketegasan_break": (_skala(abs(entry - level) / atr, 0.02, 0.6), 0.20),
                "lebar_relatif": (_skala(lebar_awal / atr, 1.5, 6.0), 0.15),
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
            invalidation=float(sisi_lawan),
            tfs_used=(b.tf,),
            features_used=("pivots", "garis_tren", "atr", "rasio_volume"),
            evidence={
                "kemiringan_atas": g_atas[0],
                "kemiringan_bawah": g_bawah[0],
                "lebar_awal": lebar_awal,
                "lebar_kini": lebar_kini,
                "volume_rasio": vol,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )


# --------------------------------------------------------------------------- #
# 5. Wedge (rising / falling)
# --------------------------------------------------------------------------- #


class WedgeBreakout(Strategi):
    """Rising wedge (bearish) dan falling wedge (bullish).

    Ciri pembeda dari segitiga: KEDUA garis miring ke arah yang sama, namun menyempit.
    Entry : break garis sinyal (bawah untuk rising, atas untuk falling).
    SL    : di luar ekstrem wedge + buffer ATR.
    TP    : tinggi wedge pada titik terlebar diproyeksikan dari titik breakout.
    """

    id = "wedge_breakout"
    kelompok = KELOMPOK_POLA
    ambang = 61.0
    warmup = 90
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}
    deskripsi = "Wedge menyempit searah; break garis sinyal jadi pemicu entry."
    sumber = (
        "trendspider.com/learning-center/what-is-a-wedge-and-what-are-the-rising-and-falling-wedge-patterns/",
        "tradingsim.com/blog/how-to-trade-rising-and-falling-wedges (SL di luar garis)",
        "chartmill.com - target awal = selisih terlebar antar garis",
    )

    buffer_sl_atr = 0.35
    rasio_konvergensi_min = 1.25

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        piv = ctx.fitur.pivots(b, 2, 2)
        hi = st.pivot_terakhir(piv, "high", 3)
        lo = st.pivot_terakhir(piv, "low", 3)
        if len(hi) < 2 or len(lo) < 2:
            return None
        g_atas = st.garis_lewat_pivot(hi)
        g_bawah = st.garis_lewat_pivot(lo)
        if g_atas is None or g_bawah is None:
            return None
        sa, sb = g_atas[0], g_bawah[0]
        if sa * sb <= 0:
            return None  # arah berbeda -> segitiga, bukan wedge

        mulai = min(hi[0].idx, lo[0].idx)
        lebar_awal = st.nilai_garis(g_atas, mulai) - st.nilai_garis(g_bawah, mulai)
        lebar_kini = st.nilai_garis(g_atas, i) - st.nilai_garis(g_bawah, i)
        if lebar_kini <= 0 or lebar_awal <= 0:
            return None
        if lebar_awal / lebar_kini < self.rasio_konvergensi_min:
            return None

        c = np.asarray(b.close, dtype=float)
        atr = atr_kini(ctx, b)
        atas_i, bawah_i = st.nilai_garis(g_atas, i), st.nilai_garis(g_bawah, i)
        atas_p, bawah_p = st.nilai_garis(g_atas, i - 1), st.nilai_garis(g_bawah, i - 1)

        if sa > 0 and sb > 0:  # rising wedge -> bias bearish, sinyal = garis bawah
            if not (c[i] < bawah_i and c[i - 1] >= bawah_p):
                return None
            arah, level = ARAH_SHORT, bawah_i
            ekstrem = float(np.max(np.asarray(b.high)[mulai : i + 1]))
            sl = ekstrem + self.buffer_sl_atr * atr
            varian = "rising_wedge"
        else:  # falling wedge -> bias bullish, sinyal = garis atas
            if not (c[i] > atas_i and c[i - 1] <= atas_p):
                return None
            arah, level = ARAH_LONG, atas_i
            ekstrem = float(np.min(np.asarray(b.low)[mulai : i + 1]))
            sl = ekstrem - self.buffer_sl_atr * atr
            varian = "falling_wedge"

        entry = float(c[i])
        maks = 1.5 * lebar_awal
        sl = max(sl, entry - maks) if arah == ARAH_LONG else min(sl, entry + maks)
        sl = sl_valid(arah, entry, sl, 0.2 * atr)
        tps = _saring_tps(arah, entry, tps_terukur(arah, level, lebar_awal))
        if not tps:
            return None

        vol = volume_breakout(ctx)
        skor, rincian = self._skor(
            {
                "konvergensi": (_skala(lebar_awal / lebar_kini, 1.25, 3.5), 0.30),
                "kemiringan_searah": (_skala(min(abs(sa), abs(sb)) / max(abs(sa), abs(sb), 1e-12), 0.15, 1.0), 0.15),
                "volume_breakout": (_skala(vol, 1.0, 2.2), 0.25),
                "ketegasan_break": (_skala(abs(entry - level) / atr, 0.02, 0.6), 0.15),
                "lebar_relatif": (_skala(lebar_awal / atr, 1.5, 6.0), 0.15),
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
            invalidation=float(ekstrem),
            tfs_used=(b.tf,),
            features_used=("pivots", "garis_tren", "atr", "rasio_volume"),
            evidence={
                "varian": varian,
                "kemiringan_atas": sa,
                "kemiringan_bawah": sb,
                "lebar_awal": lebar_awal,
                "lebar_kini": lebar_kini,
                "volume_rasio": vol,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )


# --------------------------------------------------------------------------- #
# 6. Cup and Handle
# --------------------------------------------------------------------------- #


class CupAndHandle(Strategi):
    """Cup and Handle (hanya LONG - varian terbalik sengaja tidak diaktifkan).

    Entry : penutupan menembus resistensi handle.
    SL    : di bawah low handle (setara aturan 'below the handle low').
    TP    : kedalaman cup diproyeksikan dari titik breakout (0.618 lalu 1.0).
    """

    id = "cup_and_handle"
    kelompok = KELOMPOK_POLA
    ambang = 63.0
    warmup = 140
    horizon_didukung = (HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}
    deskripsi = "Cup membulat lalu handle dangkal; entry saat resistensi handle tembus."
    sumber = (
        "investopedia.com/terms/c/cupandhandle.asp",
        "fidelity.com - handle maksimal retrace 1/3 kedalaman cup",
        "luxalgo.com - SL di bawah low handle, target 0.618/1.0/1.618 kedalaman cup",
    )

    jendela = 120
    handle_maks = 30
    handle_min = 3
    toleransi_bibir = 0.06
    retrace_handle_maks = 0.40

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        n = len(b)
        if n < self.jendela + 5:
            return None
        h = np.asarray(b.high, dtype=float)
        l = np.asarray(b.low, dtype=float)
        c = np.asarray(b.close, dtype=float)
        atr = atr_kini(ctx, b)

        awal = i - self.jendela + 1
        # handle = segmen terakhir; cup = sisanya
        for panjang_handle in range(self.handle_min, self.handle_maks + 1):
            h_awal = i - panjang_handle + 1
            if h_awal - awal < 20:
                break
            cup = slice(awal, h_awal)
            bibir_kanan = float(h[h_awal - 1])
            dasar_idx = int(np.argmin(l[cup])) + awal
            dasar = float(l[dasar_idx])
            bibir_kiri = float(h[awal : dasar_idx + 1].max()) if dasar_idx > awal else float(h[awal])
            if beda_relatif(bibir_kiri, bibir_kanan) > self.toleransi_bibir:
                continue
            kedalaman = min(bibir_kiri, bibir_kanan) - dasar
            if kedalaman <= 1.5 * atr:
                continue
            # dasar harus berada di bagian tengah cup (bentuk membulat, bukan V di tepi)
            posisi = (dasar_idx - awal) / max(1, (h_awal - 1 - awal))
            if not (0.25 <= posisi <= 0.75):
                continue
            handle_low = float(l[h_awal : i + 1].min())
            handle_high = float(h[h_awal : i].max()) if i > h_awal else bibir_kanan
            resistensi = max(handle_high, bibir_kanan)
            retrace = (bibir_kanan - handle_low) / max(kedalaman, 1e-12)
            if retrace > self.retrace_handle_maks or retrace <= 0:
                continue
            if not (c[i] > resistensi and c[i - 1] <= resistensi):
                continue

            arah = ARAH_LONG
            entry = float(c[i])
            sl = sl_valid(arah, entry, handle_low - 0.25 * atr, 0.2 * atr)
            tps = _saring_tps(arah, entry, tps_terukur(arah, resistensi, kedalaman))
            if not tps:
                continue
            vol = volume_breakout(ctx)
            # kemulusan cup: makin kecil deviasi low terhadap parabola, makin baik
            xs = np.arange(cup.start, cup.stop, dtype=float)
            try:
                koef = np.polyfit(xs, l[cup], 2)
                sisa = float(np.mean(np.abs(np.polyval(koef, xs) - l[cup])))
                kemulusan = 1.0 - _skala(sisa / atr, 0.1, 1.5)
                membulat = 1.0 if koef[0] > 0 else 0.0
            except Exception:
                kemulusan, membulat = 0.5, 0.5

            skor, rincian = self._skor(
                {
                    "kesamaan_bibir": (1.0 - _skala(beda_relatif(bibir_kiri, bibir_kanan), 0.0, self.toleransi_bibir), 0.20),
                    "kedalaman_cup": (_skala(kedalaman / atr, 1.5, 6.0), 0.20),
                    "handle_dangkal": (1.0 - _skala(retrace, 0.05, self.retrace_handle_maks), 0.20),
                    "kemulusan_cup": (kemulusan * membulat, 0.20),
                    "volume_breakout": (_skala(vol, 1.1, 2.5), 0.20),
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
                level=float(resistensi),
                invalidation=float(handle_low),
                tfs_used=(b.tf,),
                features_used=("atr", "rasio_volume"),
                evidence={
                    "bibir_kiri": bibir_kiri,
                    "bibir_kanan": bibir_kanan,
                    "dasar_cup": dasar,
                    "kedalaman": kedalaman,
                    "panjang_handle": panjang_handle,
                    "retrace_handle": retrace,
                    "volume_rasio": vol,
                    "komponen_skor": rincian,
                },
                ts_sinyal=int(b.ts_tutup(i)),
            )
        return None
