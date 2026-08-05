"""Patch 4: kebersihan repo yang tersisa. Jalankan: python tools/patch4_hygiene.py

Tiga hal, masing-masing berdiri sendiri (satu gagal tidak membatalkan yang lain,
tapi semuanya dilaporkan apa adanya di akhir):

1. IMPORT MATI - dihapus hanya setelah DIBUKTIKAN tak terpakai.
   Ini penting: pada `from dataclasses import dataclass, field`, nama `field`
   sering dipakai sebagai `field(default_factory=...)` di file lain. Karena itu
   skrip TIDAK memakai daftar hafalan; ia menghitung kemunculan nama di seluruh
   isi file setelah baris impor dikeluarkan. Nol kemunculan = baru dihapus.
   Dilewati dengan sengaja: `__init__.py` (impor di sana adalah re-export),
   `from __future__ import ...`, nama di dalam `__all__`, dan alias berawalan
   garis bawah (pola impor demi efek samping di strategi/__init__.py).

2. TF SEMI-HARDCODE di strategi/level_harga.py.
   `n = 288 if b.tf == "5m" else 96 if b.tf == "15m" else 24` berarti SETIAP TF
   lain (1m, 30m, 1h, 4h...) diam-diam memakai 24 bar. Untuk 1m, 24 bar = 24
   menit, padahal maksudnya "satu hari". Bukan crash, tapi cacat logika yang
   menghasilkan level pivot salah tanpa satu pun pesan galat. Diganti hitungan
   dari tf_ms sehingga benar untuk semua TF.

3. README yang tidak lagi cocok dengan implementasi (jumlah uji, aritmetika
   jumlah strategi yang menyesatkan).
"""
import ast
import pathlib
import re
import sys

if not pathlib.Path("lux_modul").is_dir():
    sys.exit("jalankan skrip ini dari akar repo (folder yang berisi lux_modul/)")

laporan = []

# --------------------------------------------------------------------------- #
# 1. import mati
# --------------------------------------------------------------------------- #


def nama_terikat(alias: ast.alias) -> str:
    """Nama yang benar-benar terikat di namespace modul."""
    if alias.asname:
        return alias.asname
    return alias.name.split(".")[0]


def sapu_import_mati(path: pathlib.Path) -> list:
    src = path.read_text(encoding="utf-8")
    try:
        pohon = ast.parse(src)
    except SyntaxError as exc:
        return [f"LEWAT {path}: tidak bisa diparse ({exc})"]

    baris = src.splitlines(keepends=True)
    catatan = []
    # (nomor_baris_0, nama) yang aman dihapus
    hapus = {}

    for node in pohon.body:  # hanya impor tingkat modul
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        # impor multi-baris (dalam tanda kurung) tidak disentuh: penulisan
        # ulangnya berisiko, dan tidak sebanding dengan manfaatnya.
        if getattr(node, "end_lineno", node.lineno) != node.lineno:
            continue
        for alias in node.names:
            nama = nama_terikat(alias)
            if nama.startswith("_"):
                continue  # pola impor demi efek samping
            if nama == "*":
                continue
            # hitung pemakaian di SELURUH file, minus baris impornya sendiri
            tanpa_impor = "".join(
                b for i, b in enumerate(baris) if i != node.lineno - 1
            )
            if re.search(r"\b" + re.escape(nama) + r"\b", tanpa_impor):
                continue  # TERPAKAI - jangan diapa-apakan
            hapus.setdefault(node.lineno - 1, []).append(nama)

    if not hapus:
        return catatan

    for idx, nama_mati in sorted(hapus.items()):
        teks = baris[idx]
        node_baris = ast.parse(teks.strip()).body[0]
        semua = [nama_terikat(a) for a in node_baris.names]
        sisa = [n for n in semua if n not in nama_mati]
        if not sisa:
            baris[idx] = ""  # seluruh baris impor mati
            catatan.append(f"  - {path}:{idx + 1} hapus baris: {teks.strip()}")
            continue
        if isinstance(node_baris, ast.ImportFrom):
            titik = "." * (node_baris.level or 0)
            modul = node_baris.module or ""
            simpan = [
                a for a in node_baris.names if nama_terikat(a) not in nama_mati
            ]
            bagian = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in simpan
            )
            baris[idx] = f"from {titik}{modul} import {bagian}\n"
            catatan.append(
                f"  - {path}:{idx + 1} buang {', '.join(nama_mati)} -> {baris[idx].strip()}"
            )
        else:
            simpan = [
                a for a in node_baris.names if nama_terikat(a) not in nama_mati
            ]
            bagian = ", ".join(
                a.name + (f" as {a.asname}" if a.asname else "") for a in simpan
            )
            baris[idx] = f"import {bagian}\n"
            catatan.append(f"  - {path}:{idx + 1} buang {', '.join(nama_mati)}")

    baru = "".join(baris)
    # PAGAR: hasil suntingan wajib tetap sah secara sintaks.
    try:
        ast.parse(baru)
    except SyntaxError as exc:
        return [f"BATAL {path}: suntingan menghasilkan sintaks tidak sah ({exc})"]
    path.write_text(baru, encoding="utf-8")
    return catatan


print("== 1. sapu import mati (terverifikasi tak terpakai) ==")
kandidat = sorted(
    [p for p in pathlib.Path("lux_modul").rglob("*.py") if p.name != "__init__.py"]
    + sorted(pathlib.Path("tests").rglob("*.py"))
    + sorted(pathlib.Path("scripts").rglob("*.py"))
)
total_impor = 0
for p in kandidat:
    isi = p.read_text(encoding="utf-8")
    if "__all__" in isi:
        print(f"  lewat {p} (punya __all__, impornya bisa re-export)")
        continue
    hasil = sapu_import_mati(p)
    for baris_hasil in hasil:
        print(baris_hasil)
        total_impor += 1
laporan.append(f"import mati dibersihkan: {total_impor} baris")

# --------------------------------------------------------------------------- #
# 2. TF dinamis di level_harga.py
# --------------------------------------------------------------------------- #
print("== 2. TF dinamis di strategi/level_harga.py ==")
LH = pathlib.Path("lux_modul/strategi/level_harga.py")
src = LH.read_text(encoding="utf-8")
if "_bar_per_hari" in src:
    print("  sudah terpasang")
    laporan.append("TF pivot_reversal: sudah dinamis")
else:
    pola = re.compile(
        r'^([ \t]*)n = 288 if b\.tf == "5m" else 96 if b\.tf == "15m" else 24[ \t]*$',
        re.M,
    )
    cocok = pola.findall(src)
    if len(cocok) != 1:
        print(f"  LEWAT: jangkar ditemukan {len(cocok)} kali (harus 1) - file tidak diubah")
        laporan.append(
            f"TF pivot_reversal: DILEWATI (jangkar {len(cocok)}x, bukan 1x)"
        )
    else:
        indent = cocok[0]
        src = pola.sub(f"{indent}n = _bar_per_hari(b.tf)", src)
        src += '''

_MS_HARI = 86_400_000


def _bar_per_hari(tf: str, cadangan: int = 24) -> int:
    """Jumlah bar dalam satu hari untuk TF apa pun.

    Sebelumnya nilainya dipatok: 288 untuk 5m, 96 untuk 15m, dan 24 untuk
    SEMUA TF lain. Akibatnya pada 1m jendelanya cuma 24 menit (bukan sehari)
    dan level pivot ikut salah - tanpa satu pun pesan galat. Sekarang dihitung
    dari durasi TF, jadi benar untuk 1m, 30m, 1h, 4h, dan seterusnya.

    `cadangan` dipakai bila TF tidak dikenal: lebih baik konservatif daripada
    melempar galat di tengah evaluasi strategi.
    """
    from ..kontrak import tf_ms  # impor lokal: blok impor modul tidak diubah

    try:
        satuan = int(tf_ms(tf))
    except Exception:  # noqa: BLE001 - TF tidak dikenal
        return cadangan
    if satuan <= 0:
        return cadangan
    return max(1, int(_MS_HARI // satuan))
'''
        ast.parse(src)
        LH.write_text(src, encoding="utf-8")
        print("  OK: n = _bar_per_hari(b.tf) + helper ditambahkan")
        laporan.append("TF pivot_reversal: jadi dinamis untuk semua TF")

# --------------------------------------------------------------------------- #
# 3. README selaras dengan implementasi
# --------------------------------------------------------------------------- #
print("== 3. README selaras ==")
R = pathlib.Path("README.md")
teks = R.read_text(encoding="utf-8")
asli = teks


def hitung_uji() -> int:
    """Hitung jumlah fungsi uji sungguhan, jangan tulis angka dari hafalan."""
    total = 0
    for p in sorted(pathlib.Path("tests").glob("test_*.py")):
        pohon = ast.parse(p.read_text(encoding="utf-8"))
        total += sum(
            1
            for n in pohon.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name.startswith("test_")
        )
    return total


jumlah = hitung_uji()
print(f"  jumlah fungsi uji terhitung: {jumlah}")

baris_baru = []
diubah_uji = 0
for b in teks.splitlines(keepends=True):
    if re.search(r"\b168\b", b) and re.search(r"uji|lulus", b, re.I):
        b = re.sub(r"\b168\b", str(jumlah), b)
        diubah_uji += 1
    baris_baru.append(b)
teks = "".join(baris_baru)
print(f"  baris jumlah uji diperbarui: {diubah_uji}")

salah_aritmetika = "26 (12 strategi + 14 pola + 12 indikator)"
if salah_aritmetika in teks:
    teks = teks.replace(
        salah_aritmetika,
        "26 strategi terdaftar (lintas kelompok: struktur, pola, indikator, "
        "volatilitas, aliran volume)",
    )
    print("  OK: aritmetika 12+14+12 yang menyesatkan diperbaiki")
    laporan.append("README: aritmetika jumlah strategi diperbaiki")
else:
    print("  lewat: teks aritmetika lama tidak ditemukan")

sisa_168 = len(re.findall(r"\b168\b", teks))
if teks != asli:
    R.write_text(teks, encoding="utf-8")
laporan.append(f"README: {diubah_uji} baris jumlah uji -> {jumlah}; sisa '168' = {sisa_168}")

print("\n== RINGKASAN PATCH 4 ==")
for b in laporan:
    print(f"  - {b}")
