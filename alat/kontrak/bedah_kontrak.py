#!/usr/bin/env python3
"""Bedah API kontrak eksekutor. Temukan dulu, uji kemudian.

Alasan: tes kontrak yang dulu menemukan pelanggaran hanya ada di sandbox dan
sudah hilang. Menulis ulang tes dari ingatan sama saja dengan menebak, dan
probe saya sudah dua kali salah karena menebak API. Jadi langkah ini TIDAK
menguji apa pun; ia hanya merekam tanda tangan dan sumber fungsi yang relevan
supaya tes berikutnya ditulis di atas fakta.
"""
import inspect
import json
import os
import sys

sys.path.insert(0, os.getcwd())

BATAS = 9000
out = {}


def publik(obj):
    return sorted(n for n in dir(obj) if not n.startswith("_"))


def aman(kunci, fn):
    try:
        nilai = fn()
    except Exception as galat:
        out[kunci] = "GAGAL: " + type(galat).__name__ + ": " + str(galat)
        return None
    if isinstance(nilai, str) and len(nilai) > BATAS:
        nilai = nilai[:BATAS] + "\n... [dipotong]"
    out[kunci] = nilai
    return nilai


def bedah_modul(label, jalur, target):
    """target: dict nama_atribut -> daftar anggota yang mau dibedah."""
    try:
        mod = __import__(jalur, fromlist=["*"])
    except Exception as galat:
        out[label + "_galat_impor"] = type(galat).__name__ + ": " + str(galat)
        return
    out[label + "_publik"] = publik(mod)
    for nama, anggota in target.items():
        obj = getattr(mod, nama, None)
        if obj is None:
            out[label + "_" + nama] = "TIDAK ADA"
            continue
        out[label + "_" + nama + "_api"] = publik(obj)
        aman(label + "_" + nama + "_sig", lambda o=obj: str(inspect.signature(o)))
        for m in anggota:
            fn = getattr(obj, m, None)
            if fn is None:
                out[label + "_" + nama + "_" + m] = "TIDAK ADA"
                continue
            aman(label + "_" + nama + "_" + m + "_sig",
                 lambda f=fn: str(inspect.signature(f)))
            aman(label + "_" + nama + "_" + m + "_src",
                 lambda f=fn: inspect.getsource(f))


# 1) Lapisan aman yang sudah terbukti di testnet (p07/p10/p11).
bedah_modul("aman", "lux_modul.eksekusi_aman.inti", {
    "KontrakEksekutor": ["verifikasi"],
    "PengirimOrder": ["kirim"],
    "KebijakanRisiko": [],
    "SpekSimbol": [],
})
bedah_modul("aman_proteksi", "lux_modul.eksekusi_aman.proteksi", {
    "PenjagaProteksi": ["pasang", "rekonsiliasi", "periksa_sl"],
})

# 2) Lapisan eksekusi bawaan yang BELUM diganti. Inilah yang harus diuji.
bedah_modul("dasar_ice", "lux_modul.eksekusi.ice_breaker", {
    "IceBreakerExecutor": ["jalankan"],
    "Slice": ["payload"],
    "HasilEksekusi": [],
})
bedah_modul("dasar_order", "lux_modul.eksekusi.order", {
    "KebijakanOrder": [],
})
for fn_nama in ("payload_tp", "payload_sl", "payload_bracket", "plan_execution"):
    for jalur in ("lux_modul.eksekusi.order", "lux_modul.eksekusi.ice_breaker"):
        try:
            mod = __import__(jalur, fromlist=["*"])
        except Exception:
            continue
        fn = getattr(mod, fn_nama, None)
        if fn is None:
            continue
        aman("fungsi_" + fn_nama + "_sig", lambda f=fn: str(inspect.signature(f)))
        aman("fungsi_" + fn_nama + "_src", lambda f=fn: inspect.getsource(f))

os.makedirs("bukti", exist_ok=True)
with open("bukti/kontrak_api.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=True)

kunci_gagal = sorted(k for k, v in out.items()
                     if isinstance(v, str) and v.startswith(("GAGAL", "TIDAK ADA")))
ringkas = {
    "jumlah_kunci": len(out),
    "kunci_bermasalah": kunci_gagal,
    "punya_KontrakEksekutor": "aman_KontrakEksekutor_api" in out,
    "punya_Slice_payload_src": "dasar_ice_Slice_payload_src" in out,
}
with open("bukti/RINGKAS_KONTRAK.json", "w", encoding="utf-8") as fh:
    json.dump(ringkas, fh, indent=1, ensure_ascii=False, sort_keys=True)

print(json.dumps(ringkas, indent=1, ensure_ascii=False, sort_keys=True))
