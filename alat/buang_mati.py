"""Buang berkas yang terbukti mati, diverifikasi ulang tepat sebelum dihapus.

Menghapus kode tidak bisa diambil kembali, jadi alat ini tidak percaya pada
catatan lama. Ia memindai ulang SELURUH pohon saat itu juga: impor tingkat
atas, impor bersarang, impor relatif, dan sebutan berbasis string (gerbang
memakai __import__ dengan nama string, sehingga pemindai berbasis AST saja
akan buta). Kalau ada satu saja penyebut, berkas dibiarkan dan rc bukan 0.

Kenapa proteksi.py dibuang. alat/impor_dalam.py melaporkan
  sorot=lux_modul.eksekusi_aman.proteksi {tingkat_atas: [], bersarang: [],
                                          dipakai: false}
satu-satunya yang menghidupkannya adalah daftar MODUL_WAJIB di gerbang, dan
itu bukan pemakaian melainkan pemeriksaan impor belaka. Dua implementasi
proteksi yang bersaing di satu repo siap-mainnet adalah jebakan, bukan
cadangan: yang satu diuji di bursa sungguhan, yang satu tidak pernah.
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

LEWATI_DIR = {".git", "__pycache__", "bukti", "dataset_masuk", ".github",
              "node_modules", ".pytest_cache"}


def berkas_teks():
    keluar = []
    for akar, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in LEWATI_DIR]
        for f in sorted(files):
            if f.endswith((".py", ".yml", ".yaml", ".sh", ".cfg", ".toml",
                           ".ini", ".txt", ".md")):
                keluar.append(os.path.join(akar, f).replace(os.sep, "/")
                              .lstrip("./"))
    return keluar


def main():
    semua = berkas_teks()
    print("berkas_dipindai=" + str(len(semua)))
    kode = 0
    laporan = []
    for s in SASARAN:
        target = s["berkas"]
        if not os.path.isfile(target):
            laporan.append({"berkas": target, "status": "sudah_tidak_ada"})
            continue
        penyebut = {}
        for jalur in semua:
            if jalur == target:
                continue
            # Dokumentasi boleh menyebut sejarahnya; yang dilarang adalah kode
            # yang benar-benar mengimpor atau memakai kelasnya.
            if jalur.endswith(".md"):
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
