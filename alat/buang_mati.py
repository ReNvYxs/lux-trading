"""Buang berkas yang terbukti mati, diverifikasi ulang tepat sebelum dihapus.

Menghapus kode tidak bisa diambil kembali, jadi alat ini tidak percaya pada
catatan lama. Ia memindai ulang SELURUH pohon saat itu juga: impor tingkat
atas, impor bersarang, impor relatif, dan sebutan berbasis string (gerbang
memakai __import__ dengan nama string, dan alat/periksa.sh memakai python3 -c,
sehingga pemindai berbasis AST saja akan buta). Kalau ada satu saja penyebut,
berkas dibiarkan dan rc bukan 0.

Penjaga ini sudah membuktikan dirinya: percobaan pertama DITAHAN karena
menemukan dua penyebut nyata yang tidak tercatat di analisis impor, yaitu
alat/periksa.sh dan alat/kontrak/bedah_kontrak.py.

ABAIKAN_BERKAS hanya berisi berkas yang memang harus menyebut nama sasaran
untuk bisa bekerja: alat ini sendiri (daftar polanya) dan penambal berjangkar
(teks jangkarnya). Keduanya bukan pemakaian runtime.
"""
import json
import os
import sys

SASARAN = [
    {
        "berkas": "lux_modul/eksekusi_aman/proteksi.py",
        "pola": [
            "PenjagaProteksi",
            "eksekusi_aman.proteksi",
            "eksekusi_aman import proteksi",
            "from .proteksi import",
            "from . import proteksi",
        ],
    },
]

ABAIKAN_BERKAS = {"alat/buang_mati.py", "alat/pasang_v2.py"}
LEWATI_DIR = {".git", "__pycache__", "bukti", "dataset_masuk", ".github",
              "node_modules", ".pytest_cache"}
EKSTENSI = (".py", ".yml", ".yaml", ".sh", ".cfg", ".toml", ".ini", ".txt")


def berkas_teks():
    keluar = []
    for akar, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in LEWATI_DIR]
        for f in sorted(files):
            if not f.endswith(EKSTENSI):
                continue
            penuh = os.path.join(akar, f)
            rel = os.path.relpath(penuh, ".").replace(os.sep, "/")
            keluar.append(rel)
    return sorted(keluar)


def main():
    semua = berkas_teks()
    print("berkas_dipindai=" + str(len(semua)))
    print("berkas_diabaikan=" + json.dumps(sorted(ABAIKAN_BERKAS)))
    kode = 0
    laporan = []
    for s in SASARAN:
        target = s["berkas"]
        if not os.path.isfile(target):
            laporan.append({"berkas": target, "status": "sudah_tidak_ada"})
            continue
        penyebut = {}
        for jalur in semua:
            if jalur == target or jalur in ABAIKAN_BERKAS:
                continue
            try:
                fh = open(jalur, "r", encoding="utf-8", errors="replace")
                isi = fh.read()
                fh.close()
            except OSError:
                continue
            cocok = [p for p in s["pola"] if p in isi]
            if cocok:
                penyebut[jalur] = cocok
        if penyebut:
            laporan.append({"berkas": target, "status": "MASIH_DIPAKAI",
                            "penyebut": penyebut})
            kode = 1
            continue
        ukuran = os.path.getsize(target)
        os.remove(target)
        laporan.append({"berkas": target, "status": "DIHAPUS",
                        "ukuran": ukuran})

    for r in laporan:
        print("sasaran=" + json.dumps(r, ensure_ascii=False, sort_keys=True))
    print("BUANG=" + ("SELESAI" if kode == 0 else "DITAHAN"))
    return kode


if __name__ == "__main__":
    sys.exit(main())
