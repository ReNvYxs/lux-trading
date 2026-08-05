"""Kelompok 2 - INDIKATOR / MOMENTUM.

Strategi: EMA Bounce 200, RSI Divergence + pola lilin, MACD Divergence + RSI Divergence
+ Trend Breakout (multi-TF).

Angka parameter adalah titik awal dari riset publik, bukan kebenaran teruji.
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
    KELOMPOK_INDIKATOR,
    StrategyVerdict,
    TargetTP,
)
from .basis import Strategi
from .pola import _saring_tps, _skala
from .util import atr_kini, kekuatan_konteks, sl_valid, tps_rr, volume_breakout


# --------------------------------------------------------------------------- #
# 7. EMA Bounce 200
# --------------------------------------------------------------------------- #


class EmaBounce200(Strategi):
    """Pullback ke EMA200 lalu ditolak, searah tren EMA200.

    Entry : penutupan lilin penolakan (close kembali ke sisi tren setelah menyentuh EMA200).
    SL    : di sisi seberang EMA200 / low-high pullback + buffer ATR (SL ketat).
    TP    : swing terakhir; bila tak ada, kelipatan R (1.5R dan 3R).
    """

    id = "ema_bounce_200"
    kelompok = KELOMPOK_INDIKATOR
    ambang = 58.0
    warmup = 220
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}  # single-TF
    deskripsi = "Bounce pada EMA200 searah kemiringan EMA200."
    sumber = (
        "beatmarket.com/blog/200-ema-strategy/",
        "investopedia.com - moving average sebagai support/resistance dinamis",
        "snappchart.app - SL di sisi seberang EMA200, target swing terdekat",
    )

    toleransi_sentuh_atr = 0.75
    buffer_sl_atr = 0.50

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        e = ctx.fitur.ema(b, 200)
        if e.size < 210 or not np.isfinite(e[i]) or not np.isfinite(e[i - 5]):
            return None
        c = np.asarray(b.close, dtype=float)
        h = np.asarray(b.high, dtype=float)
        l = np.asarray(b.low, dtype=float)
        atr = atr_kini(ctx, b)
        ema_kini = float(e[i])
        kemiringan = (ema_kini - float(e[i - 20])) / atr if i >= 20 else 0.0

        if c[i] > ema_kini and kemiringan > 0.05:
            arah = ARAH_LONG
            sentuh = (l[i] - ema_kini) <= self.toleransi_sentuh_atr * atr and l[i] >= ema_kini - 1.0 * atr
            penolakan = c[i] > (l[i] + h[i]) / 2.0
        elif c[i] < ema_kini and kemiringan < -0.05:
            arah = ARAH_SHORT
            sentuh = (ema_kini - h[i]) <= self.toleransi_sentuh_atr * atr and h[i] <= ema_kini + 1.0 * atr
            penolakan = c[i] < (l[i] + h[i]) / 2.0
        else:
            return None
        if not (sentuh and penolakan):
            return None

        entry = float(c[i])
        if arah == ARAH_LONG:
            sl = min(float(l[i]), ema_kini) - self.buffer_sl_atr * atr
        else:
            sl = max(float(h[i]), ema_kini) + self.buffer_sl_atr * atr
        sl = sl_valid(arah, entry, sl, 0.2 * atr)

        piv = ctx.fitur.pivots(b, 2, 2)
        swing = st.pivot_terakhir(piv, "high" if arah == ARAH_LONG else "low", 1)
        tps: Tuple[TargetTP, ...] = tps_rr(arah, entry, sl)
        if swing:
            target = swing[0].harga
            ok = target > entry if arah == ARAH_LONG else target < entry
            if ok:
                tps = (
                    TargetTP(float(target), 0.5, "tp1_swing_terakhir"),
                    tps_rr(arah, entry, sl, ((3.0, 0.5, "tp2_3R"),))[0],
                )
        tps = _saring_tps(arah, entry, tps)
        if not tps:
            return None

        jarak = abs(entry - ema_kini) / atr
        skor, rincian = self._skor(
            {
                "kemiringan_ema": (_skala(abs(kemiringan), 0.05, 1.2), 0.30),
                "kedekatan_sentuh": (1.0 - _skala(jarak, 0.05, 1.0), 0.25),
                "kekuatan_penolakan": (
                    _skala(abs(entry - (l[i] if arah == ARAH_LONG else h[i])) / max(h[i] - l[i], 1e-12), 0.4, 0.9),
                    0.25,
                ),
                "volume": (_skala(volume_breakout(ctx), 0.8, 1.8), 0.20),
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
            level=ema_kini,
            invalidation=float(sl),
            tfs_used=(b.tf,),
            features_used=("ema200", "atr", "pivots"),
            evidence={
                "ema200": ema_kini,
                "kemiringan_atr": kemiringan,
                "jarak_atr": jarak,
                "komponen_skor": rincian,
            },
            ts_sinyal=int(b.ts_tutup(i)),
        )


# --------------------------------------------------------------------------- #
# util divergensi
# --------------------------------------------------------------------------- #


def _divergensi(
    piv: List[st.Pivot], seri: np.ndarray, arah: str, maks_jarak: int = 60
) -> Optional[Tuple[st.Pivot, st.Pivot, float]]:
    """Divergensi reguler antara harga (pivot) dan seri osilator.

    arah LONG  (bullish): harga Lower Low, osilator Higher Low.
    arah SHORT (bearish): harga Higher High, osilator Lower High.
    Mengembalikan (pivot_lama, pivot_baru, besar_divergensi) atau None.
    """
    tipe = "low" if arah == ARAH_LONG else "high"
    ps = st.pivot_terakhir(piv, tipe, 2)
    if len(ps) < 2:
        return None
    a, z = ps[-2], ps[-1]
    if z.idx - a.idx > maks_jarak or z.idx - a.idx < 3:
        return None
    if not (np.isfinite(seri[a.idx]) and np.isfinite(seri[z.idx])):
        return None
    if arah == ARAH_LONG:
        ok = z.harga < a.harga and seri[z.idx] > seri[a.idx]
    else:
        ok = z.harga > a.harga and seri[z.idx] < seri[a.idx]
    if not ok:
        return None
    return a, z, float(abs(seri[z.idx] - seri[a.idx]))


# --------------------------------------------------------------------------- #
# 8. RSI Divergence + konfirmasi struktur
# --------------------------------------------------------------------------- #


class RsiDivergence(Strategi):
    """Divergensi RSI reguler + konfirmasi penembusan swing perantara.

    Entry : penutupan menembus swing perantara searah divergensi (konfirmasi).
    SL    : di luar ekstrem divergensi + buffer ATR.
    TP    : 1.5R lalu 3R (rentang yang lazim disarankan untuk divergensi).
    """

    id = "rsi_divergence"
    kelompok = KELOMPOK_INDIKATOR
    ambang = 60.0
    warmup = 120
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 0}
    deskripsi = "Divergensi RSI 14 dengan konfirmasi break swing perantara."
    sumber = (
        "altfins.com - divergence: konfirmasi wajib, jangan entry di pivot",
        "tradeciety.com - divergensi lebih andal di area S/R dan TF besar",
        "tradingview.com - RSI regular divergence definition",
    )

    rsi_n = 14
    buffer_sl_atr = 0.35

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        r = ctx.fitur.rsi(b, self.rsi_n)
        piv = ctx.fitur.pivots(b, 2, 2)
        c = np.asarray(b.close, dtype=float)
        atr = atr_kini(ctx, b)

        for arah in (ARAH_LONG, ARAH_SHORT):
            hasil = _divergensi(piv, r, arah)
            if hasil is None:
                continue
            a, z, besar = hasil
            # konfirmasi: tembus swing perantara berlawanan yang terbentuk antara a dan z
            tipe_konf = "high" if arah == ARAH_LONG else "low"
            antara = [p for p in piv if p.tipe == tipe_konf and a.idx < p.idx <= z.idx]
            if not antara:
                continue
            level = max(p.harga for p in antara) if arah == ARAH_LONG else min(p.harga for p in antara)
            if arah == ARAH_LONG:
                if not (c[i] > level and c[i - 1] <= level):
                    continue
                sl = z.harga - self.buffer_sl_atr * atr
            else:
                if not (c[i] < level and c[i - 1] >= level):
                    continue
                sl = z.harga + self.buffer_sl_atr * atr

            entry = float(c[i])
            sl = sl_valid(arah, entry, sl, 0.2 * atr)
            tps = _saring_tps(arah, entry, tps_rr(arah, entry, sl))
            if not tps:
                continue
            ekstrem_rsi = float(r[z.idx])
            zona = (
                _skala(35.0 - ekstrem_rsi, 0.0, 15.0)
                if arah == ARAH_LONG
                else _skala(ekstrem_rsi - 65.0, 0.0, 15.0)
            )
            skor, rincian = self._skor(
                {
                    "besar_divergensi": (_skala(besar, 2.0, 15.0), 0.30),
                    "zona_ekstrem_rsi": (zona, 0.25),
                    "ketegasan_konfirmasi": (_skala(abs(entry - level) / atr, 0.02, 0.6), 0.25),
                    "volume": (_skala(volume_breakout(ctx), 0.9, 2.0), 0.20),
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
                invalidation=float(z.harga),
                tfs_used=(b.tf,),
                features_used=("rsi", "pivots", "atr"),
                evidence={
                    "pivot_lama": {"idx": a.idx, "harga": a.harga, "rsi": float(r[a.idx])},
                    "pivot_baru": {"idx": z.idx, "harga": z.harga, "rsi": float(r[z.idx])},
                    "level_konfirmasi": level,
                    "komponen_skor": rincian,
                },
                ts_sinyal=int(b.ts_tutup(i)),
            )
        return None


# --------------------------------------------------------------------------- #
# 9. MACD Divergence + RSI Divergence + Trend Breakout (MULTI-TF)
# --------------------------------------------------------------------------- #


class MacdRsiTrendBreak(Strategi):
    """Konfluensi: divergensi MACD + divergensi RSI + penembusan garis tren.

    Multi-TF: butuh 1 TF konteks. Arah wajib disetujui bias TF konteks.
    Entry : penutupan menembus garis tren pivot searah divergensi.
    SL    : di luar ekstrem divergensi + buffer ATR.
    TP    : 1.5R lalu 3R.
    """

    id = "macd_rsi_trendbreak"
    kelompok = KELOMPOK_INDIKATOR
    ambang = 66.0
    warmup = 150
    horizon_didukung = (HORIZON_SCALPING, HORIZON_INTRADAY, HORIZON_SWING)
    required_roles = {"entry": True, "context": 1}  # MULTI-TF
    deskripsi = "Divergensi ganda MACD+RSI dengan konfirmasi break garis tren dan bias TF atas."
    sumber = (
        "investopedia.com/terms/m/macd.asp - divergensi MACD",
        "altfins.com - konfluensi divergensi + break trendline",
        "tradeciety.com - filter tren TF lebih tinggi mengurangi sinyal palsu",
    )

    buffer_sl_atr = 0.40

    def evaluasi(self, ctx: KonteksEvaluasi) -> Optional[StrategyVerdict]:
        b = ctx.entry
        i = ctx.i
        kb = ctx.konteks_utama()
        if kb is None or len(kb) < 60:
            return None
        piv = ctx.fitur.pivots(b, 2, 2)
        r = ctx.fitur.rsi(b, 14)
        garis_macd, _, _ = ctx.fitur.macd(b)
        c = np.asarray(b.close, dtype=float)
        atr = atr_kini(ctx, b)

        for arah in (ARAH_LONG, ARAH_SHORT):
            d_rsi = _divergensi(piv, r, arah)
            d_macd = _divergensi(piv, garis_macd, arah)
            if d_rsi is None or d_macd is None:
                continue
            dukungan = kekuatan_konteks(ctx, arah)
            if dukungan < 0.5:
                continue  # bias TF konteks menolak arah ini
            tipe_garis = "high" if arah == ARAH_LONG else "low"
            titik = st.pivot_terakhir(piv, tipe_garis, 3)
            if len(titik) < 2:
                continue
            garis = st.garis_lewat_pivot(titik)
            if garis is None:
                continue
            lv, lv_prev = st.nilai_garis(garis, i), st.nilai_garis(garis, i - 1)
            if arah == ARAH_LONG:
                if not (c[i] > lv and c[i - 1] <= lv_prev):
                    continue
                sl = d_rsi[1].harga - self.buffer_sl_atr * atr
            else:
                if not (c[i] < lv and c[i - 1] >= lv_prev):
                    continue
                sl = d_rsi[1].harga + self.buffer_sl_atr * atr

            entry = float(c[i])
            sl = sl_valid(arah, entry, sl, 0.2 * atr)
            tps = _saring_tps(arah, entry, tps_rr(arah, entry, sl))
            if not tps:
                continue
            skor, rincian = self._skor(
                {
                    "divergensi_rsi": (_skala(d_rsi[2], 2.0, 15.0), 0.25),
                    "divergensi_macd": (_skala(d_macd[2] / atr, 0.05, 1.0), 0.25),
                    "break_garis_tren": (_skala(abs(entry - lv) / atr, 0.02, 0.6), 0.20),
                    "dukungan_konteks": (dukungan, 0.20),
                    "volume": (_skala(volume_breakout(ctx), 0.9, 2.0), 0.10),
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
                level=float(lv),
                invalidation=float(d_rsi[1].harga),
                tfs_used=(b.tf, kb.tf),
                features_used=("rsi", "macd", "pivots", "garis_tren", "ema50_konteks"),
                evidence={
                    "tf_konteks": kb.tf,
                    "dukungan_konteks": dukungan,
                    "divergensi_rsi": d_rsi[2],
                    "divergensi_macd": d_macd[2],
                    "garis_tren_di_i": lv,
                    "komponen_skor": rincian,
                },
                ts_sinyal=int(b.ts_tutup(i)),
            )
        return None
