#!/usr/bin/env python3
"""Bedah gabung: apa PERSISNYA beda antara modul dasar dan pohon yang sudah
saya perbaiki dan validasi di uji-trading.

Berkas ini TIDAK menggabungkan apa pun. Tugasnya menghasilkan bukti yang bisa
dibaca sebelum satu baris pun digabung, supaya perakitan nanti dideklarasikan
dari daftar berkas yang terbukti berbeda - bukan dari ingatan.

sumber_base = pohon 'main' asli pada BASE_REF
sumber_fix  = pohon main yang dipakai probe testnet p01-p11, plus lapisan
              eksekusi bersih hasil p10/p11
"""
import hashlib
import json
import os
import subprocess

BASE = "sumber_base"
FIX = "sumber_fix"
BASE_MODUL = os.path.join(BASE, "lux_modul")
FIX_MODUL = os.path.join(FIX, "modul", "main", "lux_modul")
OUT = "bukti"
DIFFDIR = os.path.join(OUT, "diff")
MAKS_BARIS_DIFF = 4000

os.makedirs(DIFFDIR, exist_ok=True)


def md5(p):
    h = hashlib.md5()
    with open(p, "rb") as fh:
        for blok in iter(lambda: fh.read(65536), b""):
            h.update(blok)
    return h.hexdigest()


def daftar_py(akar):
    hasil = {}
    if not os.path.isdir(akar):
        return hasil
    for dp, dn, fn in os.walk(akar):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                full = os.path.join(dp, f)
                hasil[os.path.relpath(full, akar).replace(os.sep, "/")] = full
    return hasil


def inventaris(akar, maks=400):
    hasil = []
    if not os.path.isdir(akar):
        return hasil
    for dp, dn, fn in os.walk(akar):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
        for f in sorted(fn):
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, akar).replace(os.sep, "/")
            try:
                hasil.append([rel, os.path.getsize(full)])
            except OSError:
                pass
            if len(hasil) >= maks:
                return hasil
    return hasil


def diff_file(a, b, rel):
    aman = rel.replace("/", "__") + ".diff"
    tujuan = os.path.join(DIFFDIR, aman)
    proc = subprocess.run(
        ["diff", "-u", "--label", "base/" + rel, "--label", "fix/" + rel, a, b],
        capture_output=True,
        text=True,
    )
    baris = proc.stdout.splitlines()
    tambah = sum(1 for x in baris if x.startswith("+") and not x.startswith("+++"))
    hapus = sum(1 for x in baris if x.startswith("-") and not x.startswith("---"))
    potong = len(baris) > MAKS_BARIS_DIFF
    isi = "\n".join(baris[:MAKS_BARIS_DIFF])
    if potong:
        isi += "\n... DIPOTONG pada " + str(MAKS_BARIS_DIFF) + " baris ..."
    with open(tujuan, "w", encoding="utf-8") as fh:
        fh.write(isi + "\n")
    return {"berkas_diff": aman, "tambah": tambah, "hapus": hapus, "dipotong": potong}


base_py = daftar_py(BASE_MODUL)
fix_py = daftar_py(FIX_MODUL)

sama, beda, hanya_base, hanya_fix = [], [], [], []
for rel in sorted(set(base_py) | set(fix_py)):
    a = base_py.get(rel)
    b = fix_py.get(rel)
    if a and not b:
        hanya_base.append(rel)
        continue
    if b and not a:
        hanya_fix.append([rel, os.path.getsize(b)])
        continue
    ma, mb = md5(a), md5(b)
    if ma == mb:
        sama.append(rel)
    else:
        rec = {"path": rel, "md5_base": ma[:8], "md5_fix": mb[:8]}
        rec.update(diff_file(a, b, rel))
        beda.append(rec)

bersih = []
for kandidat in (
    os.path.join(FIX, "modul", "bersih", "inti.py"),
    os.path.join(FIX, "modul", "bersih", "__init__.py"),
    os.path.join(FIX, "modul", "proteksi.py"),
):
    if os.path.isfile(kandidat):
        with open(kandidat, encoding="utf-8", errors="replace") as fh:
            n = sum(1 for _ in fh)
        bersih.append(
            {
                "path": kandidat,
                "byte": os.path.getsize(kandidat),
                "md5": md5(kandidat)[:8],
                "baris": n,
            }
        )

req = os.path.join(BASE, "requirements.txt")
isi_req = None
if os.path.isfile(req):
    with open(req, encoding="utf-8") as fh:
        isi_req = fh.read()[:2000]

out = {
    "base_repo": os.environ.get("BASE_REPO"),
    "base_ref": os.environ.get("BASE_REF"),
    "fix_repo": os.environ.get("FIX_REPO"),
    "fix_ref": os.environ.get("FIX_REF"),
    "jumlah": {
        "py_base": len(base_py),
        "py_fix": len(fix_py),
        "sama": len(sama),
        "beda": len(beda),
        "hanya_base": len(hanya_base),
        "hanya_fix": len(hanya_fix),
    },
    "beda": sorted(beda, key=lambda r: -(r["tambah"] + r["hapus"])),
    "hanya_base": hanya_base,
    "hanya_fix": hanya_fix,
    "sama": sama,
    "lapisan_bersih": bersih,
    "requirements_base": isi_req,
    "inventaris_akar_base": inventaris(BASE),
    "catatan": (
        "pohon fix adalah salinan main yang dipakai probe testnet p01-p11. "
        "Perbedaan di sini adalah KANDIDAT perbaikan, bukan otomatis perbaikan "
        "sah. Tiap berkas beda harus dinilai satu per satu sebelum dirakit."
    ),
}

with open(os.path.join(OUT, "RINGKAS_GABUNG.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=True)

cetak = dict(out)
cetak.pop("sama", None)
cetak.pop("inventaris_akar_base", None)
cetak.pop("requirements_base", None)
print(json.dumps(cetak, indent=1, ensure_ascii=False)[:7000])
print("berkas diff: " + str(len(os.listdir(DIFFDIR))))
