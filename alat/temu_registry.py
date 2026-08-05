#!/usr/bin/env python3
"""Buktikan registry strategi pada pohon rakitan.

Riwayat kesalahan probe (bukan cacat modul) yang sudah diperbaiki di sini:

1) Mengasumsikan `from lux_modul.plugin import registry_bawaan` -> ImportError.
2) `python3 alat/x.py` menaruh direktori SKRIP di sys.path[0], bukan direktori
   kerja, sehingga `lux_modul` tak terlihat -> ModuleNotFoundError.
3) Introspeksi memilih atribut pertama yang cocok menurut urutan sortir, yaitu
   KELAS_BAWAAN (12 kelas), lalu berhenti. Angka 12 itu jumlah kelas bawaan,
   BUKAN jumlah strategi terdaftar. Sekarang fungsi registry_bawaan() dipanggil
   secara eksplisit dan hasilnya dibandingkan dengan daftar acuan 26 id.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())

# 26 id yang tercatat pada audit sebelumnya. Dipakai sebagai penjaga regresi:
# selisih apa pun harus muncul di artefak, bukan lewat begitu saja.
ACUAN = [
    "breaker_block",
    "breakout_volume",
    "cup_and_handle",
    "donchian_breakout",
    "double_bottom",
    "double_top",
    "ema_bounce_200",
    "fib_golden_pocket",
    "fvg_fill",
    "head_shoulders",
    "ict_liquidity_sweep",
    "keltner_reversi",
    "level_bulat",
    "macd_rsi_trendbreak",
    "market_structure_shift",
    "order_block_retest",
    "pivot_reversal",
    "rsi_divergence",
    "smc_ob_fvg",
    "squeeze_breakout",
    "supertrend_flip",
    "triangle_breakout",
    "vp_tepi_value_area",
    "vwap_reclaim",
    "vwap_reversi_pita",
    "wedge_breakout",
]

out = {"acuan_jumlah": len(ACUAN)}

try:
    from lux_modul.strategi import registry_bawaan
except Exception as galat:
    out["galat_impor"] = type(galat).__name__ + ": " + str(galat)
    with open("bukti/registry.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    raise SystemExit(1)

reg = registry_bawaan()
out["tipe_registry"] = type(reg).__name__
out["api_registry"] = sorted(n for n in dir(reg) if not n.startswith("_"))


def coba_ids(objek):
    """Kumpulkan id lewat beberapa jalan, catat mana yang berhasil."""
    jalan = {}
    for cara in ("ids", "semua", "daftar", "keys", "nama"):
        fn = getattr(objek, cara, None)
        if fn is None:
            continue
        try:
            nilai = fn() if callable(fn) else fn
            jalan[cara] = sorted(str(x) for x in nilai)
        except Exception as galat:
            jalan[cara] = "GAGAL: " + str(galat)
    try:
        jalan["iterasi"] = sorted(str(x) for x in objek)
    except Exception as galat:
        jalan["iterasi"] = "GAGAL: " + str(galat)
    for atribut in ("_strategi", "_daftar", "_peta", "items"):
        obj = getattr(objek, atribut, None)
        if obj is None:
            continue
        try:
            nilai = obj() if callable(obj) else obj
            if hasattr(nilai, "keys"):
                jalan[atribut] = sorted(str(x) for x in nilai.keys())
            else:
                jalan[atribut] = sorted(str(x) for x in nilai)
        except Exception as galat:
            jalan[atribut] = "GAGAL: " + str(galat)
    return jalan


jalan = coba_ids(reg)
out["jalan_pengambilan_id"] = {
    k: (v if isinstance(v, str) else {"jumlah": len(v), "contoh": v[:5]})
    for k, v in jalan.items()
}

# Pilih jalan yang menghasilkan id berupa string pendek (bukan repr kelas).
terpilih = None
ids = None
for nama, nilai in jalan.items():
    if isinstance(nilai, str) or not nilai:
        continue
    if any(x.startswith("<class ") for x in nilai):
        continue
    if terpilih is None or len(nilai) > len(ids):
        terpilih = nama
        ids = nilai

out["jalan_terpilih"] = terpilih
out["jumlah"] = len(ids or [])
out["ids"] = ids

if ids:
    set_ids = set(ids)
    set_acuan = set(ACUAN)
    out["cocok_dengan_acuan"] = set_ids == set_acuan
    out["hilang_dari_rakitan"] = sorted(set_acuan - set_ids)
    out["tambahan_di_rakitan"] = sorted(set_ids - set_acuan)

with open("bukti/registry.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=True)

print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if ids else 1)
