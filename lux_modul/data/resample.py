"""L0 - resample TF dasar ke TF turunan.

Aturan: TF tujuan wajib kelipatan bulat dari TF sumber. Lilin turunan yang
BELUM lengkap dibuang (parameter `buang_parsial=True`), supaya tidak ada lilin
setengah jadi yang bocor sebagai konteks.
"""
from __future__ import annotations

import numpy as np

from ..kontrak import Bars, tf_ms


def resample(bars: Bars, tf_tujuan: str, buang_parsial: bool = True) -> Bars:
    src = bars.durasi_ms
    dst = tf_ms(tf_tujuan)
    if dst < src:
        raise ValueError(f"tidak bisa resample turun: {bars.tf} -> {tf_tujuan}")
    if dst % src != 0:
        raise ValueError(f"{tf_tujuan} bukan kelipatan bulat dari {bars.tf}")
    if dst == src:
        return bars

    ts = np.asarray(bars.ts, dtype=np.int64)
    ember = (ts // dst) * dst
    batas = np.flatnonzero(np.diff(ember)) + 1
    mulai = np.concatenate(([0], batas))
    akhir = np.concatenate((batas, [ts.size]))  # eksklusif

    o = np.asarray(bars.open, dtype=np.float64)
    h = np.asarray(bars.high, dtype=np.float64)
    l = np.asarray(bars.low, dtype=np.float64)
    c = np.asarray(bars.close, dtype=np.float64)
    v = np.asarray(bars.volume, dtype=np.float64)

    n_harus = dst // src
    baris_ts, ro, rh, rl, rc, rv = [], [], [], [], [], []
    for s, e in zip(mulai, akhir):
        if buang_parsial and (e - s) != n_harus:
            continue
        baris_ts.append(int(ember[s]))
        ro.append(float(o[s]))
        rh.append(float(h[s:e].max()))
        rl.append(float(l[s:e].min()))
        rc.append(float(c[e - 1]))
        rv.append(float(v[s:e].sum()))

    return Bars(
        tf=tf_tujuan,
        ts=np.array(baris_ts, dtype=np.int64),
        open=np.array(ro, dtype=np.float64),
        high=np.array(rh, dtype=np.float64),
        low=np.array(rl, dtype=np.float64),
        close=np.array(rc, dtype=np.float64),
        volume=np.array(rv, dtype=np.float64),
        simbol=bars.simbol,
    )
