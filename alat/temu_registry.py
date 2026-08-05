#!/usr/bin/env python3
"""Temukan registry strategi lewat introspeksi, bukan tebakan.

Dua kesalahan probe yang sudah terbukti dan diperbaiki di sini:

1) Probe pertama mengasumsikan `from lux_modul.plugin import registry_bawaan`
   dan gagal dengan ImportError. Itu kesalahan probe, bukan cacat modul.

2) Probe kedua gagal dengan `ModuleNotFoundError: No module named 'lux_modul'`
   padahal `python3 -c "import lux_modul"` sukses di langkah yang sama. Sebabnya
   Python menaruh direktori SKRIP di sys.path[0] untuk `python3 alat/x.py`,
   sedangkan untuk `python3 -c` yang masuk adalah direktori kerja. Karena itu
   direktori kerja disisipkan eksplisit di bawah.
"""
import importlib
import json
import os
import sys

sys.path.insert(0, os.getcwd())

KANDIDAT = [
    "lux_modul.plugin",
    "lux_modul.strategi",
    "lux_modul",
    "lux_modul.pipeline",
    "lux_modul.arbiter",
    "lux_modul.arbiter.pemilih",
]
PETUNJUK = ("regist", "bawaan", "daftar", "plugin", "strategi")

temuan = {}
for nama in KANDIDAT:
    try:
        modul = importlib.import_module(nama)
    except Exception as galat:
        temuan[nama] = "GAGAL IMPOR: " + type(galat).__name__ + ": " + str(galat)
        continue
    temuan[nama] = sorted(
        n
        for n in dir(modul)
        if not n.startswith("_") and any(p in n.lower() for p in PETUNJUK)
    )

print("--- kandidat lokasi registry ---")
print(json.dumps(temuan, indent=1, ensure_ascii=False))


def tarik_ids(obj):
    for cara in ("ids", "daftar", "semua", "keys"):
        fn = getattr(obj, cara, None)
        if callable(fn):
            try:
                return sorted(str(x) for x in fn())
            except Exception:
                continue
    try:
        return sorted(str(x) for x in obj)
    except Exception:
        return None


ids = None
asal = None
for nama, daftar in temuan.items():
    if isinstance(daftar, str):
        continue
    for atribut in daftar:
        if "bawaan" not in atribut.lower() and "regist" not in atribut.lower():
            continue
        try:
            objek = getattr(importlib.import_module(nama), atribut)
            hasil = objek() if callable(objek) else objek
        except Exception as galat:
            print("gagal panggil " + nama + "." + atribut + ": " + str(galat))
            continue
        kandidat_ids = tarik_ids(hasil)
        if kandidat_ids:
            ids = kandidat_ids
            asal = nama + "." + atribut
            break
    if ids:
        break

print("--- hasil ---")
if ids:
    print("registry ditemukan di: " + str(asal))
    print("jumlah strategi: " + str(len(ids)))
    print(json.dumps(ids, ensure_ascii=False))
else:
    print("registry TIDAK ditemukan lewat introspeksi")

with open("bukti/registry.json", "w", encoding="utf-8") as fh:
    json.dump(
        {"kandidat": temuan, "asal": asal, "jumlah": len(ids or []), "ids": ids},
        fh,
        indent=1,
        ensure_ascii=False,
    )

raise SystemExit(0 if ids else 1)
