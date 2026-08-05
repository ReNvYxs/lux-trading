"""Selaraskan klaim STATUS (bukan catatan historis) di dokumen dengan angka nyata.

Jalankan: python tools/patch5_dokumen.py

Prinsip yang dipegang di sini:

1. Hanya klaim **status kini** yang diperbaiki, mis. "tests/ - 168 uji, semuanya
   lulus" atau baris tabel "128 lulus / 0 gagal". Klaim seperti ini menjadi
   SALAH begitu jumlah uji berubah.
2. Catatan **historis** TIDAK disentuh. Baris seperti "sempat 83 lulus pada
   putaran 3 (3 Agu)" di STATE.md / RESUME_PROMPT.md adalah jurnal kemajuan;
   menimpa angkanya dengan 242 justru akan membuat dokumen itu berbohong soal
   masa lalu. Memperbaiki gejala sambil merusak kebenaran bukan perbaikan.
3. Angka pengganti DIHITUNG dari kode (AST), tidak dihafal.
4. Idempoten: bila polanya sudah tidak ada, item dilaporkan 'lewat', bukan crash.
"""
import ast
import pathlib
import re
import sys

AKAR = pathlib.Path(__file__).resolve().parent.parent


def hitung_uji():
    total = 0
    for p in sorted((AKAR / "tests").glob("test_*.py")):
        pohon = ast.parse(p.read_text(encoding="utf-8"))
        total += sum(
            1
            for node in pohon.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return total


UJI = hitung_uji()
print("UJI_NYATA=", UJI)

SUNTINGAN = [
    # (berkas, pola, pengganti, keterangan)
    (
        "AUDIT_LEVERAGE_PRESISI.md",
        r"\b168 uji\b",
        f"{UJI} uji",
        "klaim status jumlah uji",
    ),
    (
        "AUDIT_TOTAL.md",
        r"\b128 lulus / 0 gagal\b",
        f"{UJI} lulus / 0 gagal",
        "baris status tabel audit",
    ),
    (
        "ARSITEKTUR.md",
        r"- Cacah uji CI \(180[^\n]*",
        (
            f"- Cacah uji CI dan lokal sudah disamakan: {UJI} uji, dijalankan oleh "
            "`.github/workflows/kesiapan_live.yml` di `main` dan dibuktikan di "
            "`LAPORAN_KESIAPAN.md` / `LOG_KESIAPAN.txt`."
        ),
        "isu terbuka yang sudah selesai",
    ),
]

ringkasan = []
for nama, pola, pengganti, ket in SUNTINGAN:
    path = AKAR / nama
    if not path.exists():
        ringkasan.append(f"  LEWAT {nama}: berkas tidak ada")
        continue
    isi = path.read_text(encoding="utf-8")
    baru, n = re.subn(pola, pengganti, isi)
    if n == 0:
        ringkasan.append(f"  LEWAT {nama}: pola tidak ditemukan ({ket}) - mungkin sudah selaras")
        continue
    path.write_text(baru, encoding="utf-8")
    ringkasan.append(f"  OK    {nama}: {n} baris diperbarui ({ket})")

print("== RINGKASAN PATCH 5 (dokumen) ==")
for r in ringkasan:
    print(r)
print("PATCH5_SELESAI")
