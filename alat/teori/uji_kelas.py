"""Verifikasi teori lanjutan.

Tiga hal yang belum tercakup uji_teori.py:
1. 12 strategi berbasis KELAS (uji_teori.py hanya memetakan 14 pola berdekorator).
2. Akar penyebab stoch_rsi yang keluarannya seluruhnya NaN pada data nyata.
3. Peta pemakaian tiap indikator, untuk tahu mana yang benar-benar dipakai strategi.

Skrip ini murni membaca dan mengukur. Tidak ada satu baris pun lux_modul yang diubah.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())

import numpy as np

from lux_modul.kontrak import Bars
from lux_modul.fitur import dasar as ds
from lux_modul.fitur import lanjutan as lj

KELUARAN = os.path.join("bukti", "teori")

_SEDERHANA = (bool, int, float, str, type(None))
_TIDAK_ADA = object()


def _nilai_sederhana(v):
    if isinstance(v, _SEDERHANA):
        return v
    if isinstance(v, (tuple, list)):
        semua = True
        for x in v:
            if not isinstance(x, _SEDERHANA):
                semua = False
                break
        if semua:
            return list(v)
    return _TIDAK_ADA


def dump_kelas():
    from lux_modul import plugin as pl

    pl.muat_plugin()
    hasil = []
    for nama in sorted(pl.KATALOG_STRATEGI):
        kelas = pl.KATALOG_STRATEGI[nama]
        atribut = {}
        metode = []
        for k in sorted(dir(kelas)):
            if k.startswith("_"):
                continue
            try:
                v = getattr(kelas, k)
            except Exception:
                continue
            if callable(v):
                metode.append(k)
                continue
            s = _nilai_sederhana(v)
            if s is not _TIDAK_ADA:
                atribut[k] = s
        doc = inspect.getdoc(kelas) or ""
        sumber_kode = ""
        try:
            sumber_kode = inspect.getsource(kelas)
        except Exception:
            sumber_kode = ""
        hasil.append(
            {
                "id": nama,
                "kelas": getattr(kelas, "__name__", "?"),
                "modul": getattr(kelas, "__module__", "?"),
                "atribut": atribut,
                "metode": metode,
                "docstring": doc[:1500],
                "baris_kode": int(len(sumber_kode.splitlines())),
            }
        )
    return hasil


def uji_nan_propagasi():
    """Hipotesis: dasar.sma dan dasar.stdev memakai cumsum, sehingga satu NaN di
    awal deret mencemari SELURUH keluaran sesudahnya. Diuji langsung."""
    out = []
    x = np.array(
        [np.nan, np.nan, np.nan, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    )
    n = 3
    harusnya = 0
    for i in range(n - 1, x.size):
        if bool(np.all(np.isfinite(x[i - n + 1 : i + 1]))):
            harusnya += 1

    s = ds.sma(x, n)
    finit_sma = int(np.sum(np.isfinite(s)))
    out.append(
        {
            "nama": "sma_menyebarkan_nan",
            "n_masukan": int(x.size),
            "jendela_bebas_nan": harusnya,
            "keluaran_finit": finit_sma,
            "menyebarkan_nan": bool(finit_sma == 0 and harusnya > 0),
            "catatan": "dasar.sma memakai cumsum; satu NaN mencemari seluruh keluaran sesudahnya",
        }
    )

    st = ds.stdev(x, n)
    finit_st = int(np.sum(np.isfinite(st)))
    out.append(
        {
            "nama": "stdev_menyebarkan_nan",
            "jendela_bebas_nan": harusnya,
            "keluaran_finit": finit_st,
            "menyebarkan_nan": bool(finit_st == 0 and harusnya > 0),
        }
    )

    rmx = ds.rolling_max(x, n)
    out.append(
        {
            "nama": "rolling_max_pembanding",
            "jendela_bebas_nan": harusnya,
            "keluaran_finit": int(np.sum(np.isfinite(rmx))),
            "catatan": "memakai sliding window per-jendela, jadi NaN TIDAK menular; pembanding positif",
        }
    )

    e = ds.ema(x, n)
    out.append(
        {
            "nama": "ema_dengan_nan_awal",
            "keluaran_finit": int(np.sum(np.isfinite(e))),
            "catatan": "EMA rekursif juga menular; macd sengaja memotong prefiks NaN sebelum memanggil ema",
        }
    )
    return out


def uji_stoch_rsi(n=400):
    """Membuktikan stoch_rsi menghasilkan NaN total walau RSI-nya sehat."""
    acak = np.random.default_rng(11)
    harga = 100.0 + np.cumsum(acak.normal(0.0, 1.0, n))
    harga = np.maximum(harga, 5.0)
    ts = np.arange(n, dtype=np.int64) * 3600000
    b = Bars(
        tf="1h",
        ts=ts,
        open=harga,
        high=harga + 0.5,
        low=harga - 0.5,
        close=harga,
        volume=np.full(n, 100.0),
        simbol="UJI",
    )
    k, d = lj.stoch_rsi(b, 14, 14, 3)
    r = ds.rsi(harga, 14)

    k_mentah = np.full(r.size, np.nan)
    for i in range(14, r.size):
        jendela = r[i - 14 + 1 : i + 1]
        if not np.all(np.isfinite(jendela)):
            continue
        lo = float(jendela.min())
        hi = float(jendela.max())
        k_mentah[i] = 50.0 if hi <= lo else 100.0 * (r[i] - lo) / (hi - lo)

    halus_manual = np.full(k_mentah.size, np.nan)
    for i in range(2, k_mentah.size):
        jendela = k_mentah[i - 2 : i + 1]
        if np.all(np.isfinite(jendela)):
            halus_manual[i] = float(jendela.mean())

    return {
        "n_bar": int(n),
        "rsi_finit": int(np.sum(np.isfinite(r))),
        "k_mentah_finit": int(np.sum(np.isfinite(k_mentah))),
        "stoch_k_finit_modul": int(np.sum(np.isfinite(k))),
        "stoch_d_finit_modul": int(np.sum(np.isfinite(d))),
        "k_halus_finit_bila_sma_aman_nan": int(np.sum(np.isfinite(halus_manual))),
        "seluruhnya_nan": bool(int(np.sum(np.isfinite(k))) == 0),
        "catatan": "RSI sehat dan k_mentah sehat, tetapi keluaran modul nol finit -> akar masalah ada pada penghalusan dasar.sma",
    }


def peta_pemakaian():
    from lux_modul import plugin as pl

    pl.muat_plugin()
    berkas = []
    for akar, _dirs, files in os.walk("lux_modul"):
        if "__pycache__" in akar:
            continue
        for f in files:
            if f.endswith(".py"):
                berkas.append(os.path.join(akar, f))
    definisi = (
        os.path.join("lux_modul", "fitur", "lanjutan.py"),
        os.path.join("lux_modul", "fitur", "dasar.py"),
    )
    peta = {}
    for nm in sorted(pl.KATALOG_INDIKATOR):
        pemakai = []
        a = '"' + nm + '"'
        c = "'" + nm + "'"
        for jalur in berkas:
            if jalur in definisi:
                continue
            try:
                with open(jalur, "r", encoding="utf-8", errors="replace") as fh:
                    isi = fh.read()
            except Exception:
                continue
            if a in isi or c in isi:
                pemakai.append(jalur)
        peta[nm] = pemakai
    tanpa = []
    for k in sorted(peta):
        if not peta[k]:
            tanpa.append(k)
    return {
        "berkas_dipindai": int(len(berkas)),
        "pemakaian": peta,
        "indikator_tanpa_pemakai": tanpa,
    }


def utama():
    os.makedirs(KELUARAN, exist_ok=True)
    hasil = {"versi": 2}
    for nama, fn in (
        ("kelas_strategi", dump_kelas),
        ("nan_propagasi", uji_nan_propagasi),
        ("stoch_rsi", uji_stoch_rsi),
        ("peta_pemakaian", peta_pemakaian),
    ):
        try:
            hasil[nama] = fn()
        except Exception:
            hasil[nama + "_galat"] = traceback.format_exc()[-2000:]

    with open(os.path.join(KELUARAN, "KELAS_STRATEGI.json"), "w", encoding="utf-8") as fh:
        json.dump(hasil.get("kelas_strategi", []), fh, indent=1, ensure_ascii=False, default=str)

    ringkas = {
        "jumlah_kelas": len(hasil.get("kelas_strategi", [])),
        "id_kelas": [k.get("id") for k in hasil.get("kelas_strategi", [])],
        "nan_propagasi": hasil.get("nan_propagasi"),
        "stoch_rsi": hasil.get("stoch_rsi"),
        "indikator_tanpa_pemakai": hasil.get("peta_pemakaian", {}).get("indikator_tanpa_pemakai"),
        "berkas_dipindai": hasil.get("peta_pemakaian", {}).get("berkas_dipindai"),
        "galat": [k for k in hasil if str(k).endswith("galat")],
    }
    with open(os.path.join(KELUARAN, "RINGKAS_TEORI2.json"), "w", encoding="utf-8") as fh:
        json.dump(ringkas, fh, indent=1, ensure_ascii=False, default=str)
    with open(os.path.join(KELUARAN, "TEORI2.json"), "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, indent=1, ensure_ascii=False, default=str)

    print(json.dumps(ringkas, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    utama()
