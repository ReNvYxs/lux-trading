"""Deteksi klaim STATUS berangka yang basi di dokumen markdown akar repo.

Jalankan: python tools/cek_dokumen.py

Kenapa ini ada: kriteria kesiapan mencakup "dokumen tidak boleh tidak sinkron
dengan implementasi". Klaim seperti "168 uji, semuanya lulus" mudah basi setiap
kali uji ditambah, dan tidak ada satu pun uji yang menjaganya. Daripada
MENGASUMSIKAN dokumen sudah benar, angka nyata dihitung dari kode lalu
dibandingkan dengan angka yang tertulis.

Riwayat cacat gerbang ini (ditulis supaya tidak terulang):

1. Versi pertama menghasilkan 22 dugaan yang sebagian besar POSITIF PALSU: judul
   "## 6. Lapis strategi", "95 pair", batas 121 karakter pesan Telegram, ambang
   skor 58. Heuristik terlalu longgar bukan kewaspadaan - ia melatih orang
   mengabaikan peringatan.
2. Versi kedua menuduh baris "21 uji di `tests/test_konfigurasi.py`" basi,
   padahal angkanya BENAR. Cacatnya: setiap klaim dibandingkan ke total repo,
   padahal klaim itu per-berkas. Perbaikannya bukan mengecualikan barisnya,
   melainkan membandingkan ke angka yang tepat: bila baris menyebut berkas uji
   tertentu, angka pembandingnya adalah jumlah uji DI BERKAS ITU.

JURNAL DIKECUALIKAN: STATE.md dan RESUME_PROMPT.md adalah catatan kemajuan
berisi angka HISTORIS yang memang benar untuk saat itu. Mereka tidak boleh
dipaksa sama dengan angka hari ini.

Keluar dengan kode 1 bila masih ada klaim status yang basi.
"""
import ast
import pathlib
import re
import sys

AKAR = pathlib.Path(__file__).resolve().parent.parent
if str(AKAR) not in sys.path:
    sys.path.insert(0, str(AKAR))

# Jurnal kemajuan + laporan yang dihasilkan CI: bukan klaim status kini.
DIKECUALIKAN = {
    "STATE.md",
    "RESUME_PROMPT.md",
    "LAPORAN_PERBAIKAN.md",
    "LAPORAN_KESIAPAN.md",
    "LAPORAN_BACKTEST_95.md",
    "CALON_STRATEGI.md",
}


def hitung_uji_per_berkas():
    """{'test_inti.py': 12, ...} dihitung via AST, bukan dihafal."""
    hasil = {}
    for p in sorted((AKAR / "tests").glob("test_*.py")):
        pohon = ast.parse(p.read_text(encoding="utf-8"))
        hasil[p.name] = sum(
            1
            for node in pohon.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return hasil


def hitung_strategi():
    try:
        from lux_modul.strategi import registry_bawaan

        reg = registry_bawaan()
        for atribut in ("nama", "semua", "daftar", "keys"):
            fn = getattr(reg, atribut, None)
            if callable(fn):
                try:
                    return len(list(fn()))
                except Exception:  # noqa: BLE001
                    continue
    except Exception as exc:  # noqa: BLE001
        print("  tidak dapat menghitung strategi:", exc)
    return -1


PER_BERKAS = hitung_uji_per_berkas()
UJI_NYATA = sum(PER_BERKAS.values())
STRATEGI_NYATA = hitung_strategi()
print("UJI_NYATA=", UJI_NYATA)
print("BERKAS_UJI=", len(PER_BERKAS))
print("STRATEGI_NYATA=", STRATEGI_NYATA)

# Klaim jumlah uji: angka HARUS berdampingan dengan kata uji/lulus.
POLA_UJI = re.compile(r"\b(\d{2,5})\s+(?:uji|tes|test)\b", re.IGNORECASE)
POLA_UJI_LULUS = re.compile(r"\b(\d{2,5})\s+lulus\b", re.IGNORECASE)
# Berkas uji yang disebut pada baris yang sama, mis. `tests/test_konfigurasi.py`.
POLA_BERKAS_UJI = re.compile(r"(test_[a-z0-9_]+\.py)", re.IGNORECASE)
# Klaim jumlah strategi TERDAFTAR: butuh kata penanda total/terdaftar/registry,
# supaya subhimpunan yang sah (mis. "12 strategi tunggal fase-1") tidak dituduh.
POLA_STRATEGI_TOTAL = re.compile(
    r"\b(\d{1,4})\s+strategi\s+(?:terdaftar|total)\b|"
    r"\b(?:total|terdaftar)[^\n]{0,20}?\b(\d{1,4})\s+strategi\b",
    re.IGNORECASE,
)

# Baris yang secara jelas bukan klaim jumlah uji/strategi.
ABAIKAN_BARIS = re.compile(
    r"bobot|weight|epoch|ban(ned)? until|leverage|bps|http|"
    r"\bpair\b|\bsimbol\b|backtest95|\btrade\b|karakter|char",
    re.IGNORECASE,
)
ABAIKAN_JUDUL = re.compile(r"^#{1,6}\s")
ABAIKAN_DAFTAR_NOMOR = re.compile(r"^\s*\d+\.\s")
ABAIKAN_BARIS_PERINTAH = re.compile(r"^\|\s*`/")

mismatch = 0
diperiksa = 0
for p in sorted(AKAR.glob("*.md")):
    if p.name in DIKECUALIKAN:
        print(f"  dikecualikan (jurnal/laporan): {p.name}")
        continue
    laporan = []
    for i, baris in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if (
            ABAIKAN_BARIS.search(baris)
            or ABAIKAN_JUDUL.match(baris)
            or ABAIKAN_DAFTAR_NOMOR.match(baris)
            or ABAIKAN_BARIS_PERINTAH.match(baris)
        ):
            continue

        # Bila baris menyebut berkas uji tertentu, pembandingnya adalah jumlah
        # uji di berkas itu - bukan total repo.
        harapan = UJI_NYATA
        konteks = "total repo"
        berkas_disebut = [
            m.group(1) for m in POLA_BERKAS_UJI.finditer(baris) if m.group(1) in PER_BERKAS
        ]
        if len(berkas_disebut) == 1:
            harapan = PER_BERKAS[berkas_disebut[0]]
            konteks = berkas_disebut[0]
        elif len(berkas_disebut) > 1:
            harapan = sum(PER_BERKAS[n] for n in berkas_disebut)
            konteks = "+".join(berkas_disebut)

        angka = set()
        for m in POLA_UJI.finditer(baris):
            angka.add(int(m.group(1)))
        for m in POLA_UJI_LULUS.finditer(baris):
            angka.add(int(m.group(1)))
        for n in sorted(angka):
            diperiksa += 1
            if n != harapan:
                laporan.append(
                    f"    MISMATCH_DOKUMEN {p.name}:{i}: klaim {n} uji, nyata"
                    f" {harapan} ({konteks}) | {baris.strip()[:110]}"
                )
                mismatch += 1

        for m in POLA_STRATEGI_TOTAL.finditer(baris):
            n = int(m.group(1) or m.group(2))
            if STRATEGI_NYATA <= 0:
                continue
            diperiksa += 1
            if n != STRATEGI_NYATA:
                laporan.append(
                    f"    MISMATCH_DOKUMEN {p.name}:{i}: klaim {n} strategi terdaftar,"
                    f" nyata {STRATEGI_NYATA} | {baris.strip()[:110]}"
                )
                mismatch += 1
    if laporan:
        print(f"  {p.name}:")
        for b in laporan:
            print(b)

print("KLAIM_ANGKA_DIPERIKSA=", diperiksa)
print("JUMLAH_MISMATCH_DOKUMEN=", mismatch)
if mismatch:
    print("STATUS_DOKUMEN= BASI")
    sys.exit(1)
print("STATUS_DOKUMEN= BERSIH")
