"""L0 - pemuat data mentah.

Skema CSV yang dipakai (sama dengan dataset lux-trading-strategy / Binance USDT-M):
    ts,open,high,low,close,volume
dengan `ts` epoch MILIDETIK waktu buka lilin.
"""
from __future__ import annotations

import csv
import os
from typing import Dict, Iterable, Optional, Sequence

import numpy as np

from ..kontrak import Bars, TF_MS

KOLOM_WAJIB = ("ts", "open", "high", "low", "close", "volume")


class GalatData(Exception):
    pass


def muat_csv(path: str, tf: str, simbol: Optional[str] = None) -> Bars:
    """Muat satu berkas CSV menjadi Bars. Toleran terhadap CRLF dan kolom ekstra."""
    if tf not in TF_MS:
        raise GalatData(f"timeframe tidak dikenal: {tf!r}")
    with open(path, "r", newline="", encoding="utf-8-sig") as fh:
        pembaca = csv.DictReader(fh)
        if pembaca.fieldnames is None:
            raise GalatData(f"{path}: berkas kosong")
        kolom = [c.strip().lower() for c in pembaca.fieldnames]
        hilang = [k for k in KOLOM_WAJIB if k not in kolom]
        if hilang:
            raise GalatData(f"{path}: kolom hilang {hilang}; ditemukan {kolom}")
        baris = []
        for r in pembaca:
            rr = {k.strip().lower(): v for k, v in r.items() if k is not None}
            baris.append(rr)
    if not baris:
        raise GalatData(f"{path}: tidak ada baris data")
    ts = np.array([int(float(b["ts"])) for b in baris], dtype=np.int64)
    kol = {}
    for nama in ("open", "high", "low", "close", "volume"):
        kol[nama] = np.array([float(b[nama]) for b in baris], dtype=np.float64)
    return rapikan(
        Bars(
            tf=tf,
            ts=ts,
            open=kol["open"],
            high=kol["high"],
            low=kol["low"],
            close=kol["close"],
            volume=kol["volume"],
            simbol=simbol or os.path.basename(path).split(".")[0],
        )
    )


def rapikan(bars: Bars) -> Bars:
    """Urutkan menaik, buang duplikat ts (ambil yang terakhir), buang baris NaN."""
    ts = np.asarray(bars.ts, dtype=np.int64)
    urut = np.argsort(ts, kind="stable")
    ts = ts[urut]
    o, h, l, c, v = (
        np.asarray(bars.open)[urut],
        np.asarray(bars.high)[urut],
        np.asarray(bars.low)[urut],
        np.asarray(bars.close)[urut],
        np.asarray(bars.volume)[urut],
    )
    # duplikat: simpan kemunculan terakhir
    unik = np.ones(ts.size, dtype=bool)
    if ts.size > 1:
        unik[:-1] = ts[1:] != ts[:-1]
    ts, o, h, l, c, v = ts[unik], o[unik], h[unik], l[unik], c[unik], v[unik]
    sah = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    sah &= (h >= l) & (h >= o) & (h >= c) & (l <= o) & (l <= c)
    ts, o, h, l, c, v = ts[sah], o[sah], h[sah], l[sah], c[sah], v[sah]
    v = np.nan_to_num(v, nan=0.0)
    return Bars(bars.tf, ts, o, h, l, c, v, bars.simbol)


def dari_baris(
    tf: str, baris: Sequence[Sequence[float]], simbol: str = "?"
) -> Bars:
    """Bangun Bars dari list [ts, o, h, l, c, v]. Berguna untuk uji & data sintetis."""
    a = np.asarray(baris, dtype=np.float64)
    if a.ndim != 2 or a.shape[1] < 6:
        raise GalatData("baris wajib berbentuk (n, 6): ts,o,h,l,c,v")
    return rapikan(
        Bars(
            tf=tf,
            ts=a[:, 0].astype(np.int64),
            open=a[:, 1],
            high=a[:, 2],
            low=a[:, 3],
            close=a[:, 4],
            volume=a[:, 5],
            simbol=simbol,
        )
    )


def muat_simbol(
    direktori: str, simbol: str, tfs: Iterable[str], pola: str = "{simbol}_{tf}.csv"
) -> Dict[str, Bars]:
    """Muat beberapa TF satu simbol. Nama berkas dapat diatur lewat `pola`."""
    hasil: Dict[str, Bars] = {}
    for tf in tfs:
        p = os.path.join(direktori, pola.format(simbol=simbol, tf=tf))
        if not os.path.exists(p):
            raise GalatData(f"berkas tidak ditemukan: {p}")
        hasil[tf] = muat_csv(p, tf, simbol)
    return hasil


def laporan_integritas(bars: Bars) -> Dict[str, object]:
    """Cek lubang (gap) jadwal lilin. Dilaporkan, bukan diperbaiki diam-diam."""
    ts = np.asarray(bars.ts, dtype=np.int64)
    d = bars.durasi_ms
    if ts.size < 2:
        return {"baris": int(ts.size), "lubang": 0, "keterisian": 1.0}
    beda = np.diff(ts)
    lubang = int(np.count_nonzero(beda != d))
    diharapkan = int((ts[-1] - ts[0]) // d) + 1
    return {
        "simbol": bars.simbol,
        "tf": bars.tf,
        "baris": int(ts.size),
        "baris_diharapkan": diharapkan,
        "lubang": lubang,
        "keterisian": round(float(ts.size) / diharapkan, 6),
        "ts0": int(ts[0]),
        "ts1": int(ts[-1]),
    }
