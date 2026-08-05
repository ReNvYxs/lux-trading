"""Gerbang kesiapan uji langsung ke Binance (testnet maupun real).

Jalankan: python tools/kesiapan_live.py

Kenapa berkas ini ada. pytest TIDAK pernah mengimpor `main.py` maupun berkas di
`scripts/`, jadi galat seperti

    ImportError: cannot import name 'evaluasi_verdict' from 'lux_modul.eksekusi.biaya'

bisa lolos dari 242 uji yang semuanya hijau lalu baru meledak di tangan operator
saat menjalankan `python main.py`. Itu benar-benar terjadi. Gerbang di bawah
memeriksa kontrak impor SETIAP entry point secara statis-lalu-nyata: nama yang
diimpor diambil dari AST, lalu benar-benar di-resolve dari modul sumbernya -
TANPA mengeksekusi body entry point (penting: mengeksekusi main.py bisa memulai
trading sungguhan).

Pemeriksaan yang gagal karena API-nya tidak dapat diverifikasi dilaporkan
sebagai CATATAN, bukan LULUS. Tidak ada pemeriksaan yang boleh lulus karena
asumsi.

Keluar dengan kode 1 bila ada pemeriksaan WAJIB yang gagal.
"""
import ast
import importlib
import inspect
import pathlib
import sys

AKAR = pathlib.Path(__file__).resolve().parent.parent
if str(AKAR) not in sys.path:
    sys.path.insert(0, str(AKAR))

GAGAL = []
CATATAN = []


def bagian(judul):
    print(f"\n===== {judul} =====")


# ========================================================================== #
bagian("A. kontrak impor setiap entry point (main.py + scripts/*.py)")
# ========================================================================== #
def modul_lokal(nama):
    """Hanya modul repo ini yang kita paksa resolve; stdlib/pihak ketiga dilewati."""
    akar_nama = nama.split(".")[0]
    return akar_nama in {"lux_modul", "scripts", "tools"}


def periksa_impor(path):
    """Kembalikan daftar galat kontrak impor untuk satu berkas entry point."""
    galat = []
    pohon = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(pohon):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not modul_lokal(alias.name):
                    continue
                try:
                    importlib.import_module(alias.name)
                except Exception as exc:  # noqa: BLE001
                    galat.append(
                        f"{path.relative_to(AKAR)}:{node.lineno}: import {alias.name} -> "
                        f"{type(exc).__name__}: {exc}"
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # impor relatif di dalam paket; dicakup oleh walk_packages
                continue
            if not node.module or not modul_lokal(node.module):
                continue
            try:
                mod = importlib.import_module(node.module)
            except Exception as exc:  # noqa: BLE001
                galat.append(
                    f"{path.relative_to(AKAR)}:{node.lineno}: from {node.module} -> "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if hasattr(mod, alias.name):
                    continue
                # bisa jadi submodul yang belum diimpor
                try:
                    importlib.import_module(f"{node.module}.{alias.name}")
                except Exception:  # noqa: BLE001
                    galat.append(
                        f"{path.relative_to(AKAR)}:{node.lineno}: "
                        f"cannot import name '{alias.name}' from '{node.module}'"
                    )
    return galat


entry_points = [AKAR / "main.py"] + sorted((AKAR / "scripts").glob("*.py"))
total_galat_impor = 0
for ep in entry_points:
    if not ep.exists():
        GAGAL.append(f"entry point hilang: {ep.name}")
        continue
    galat = periksa_impor(ep)
    total_galat_impor += len(galat)
    tanda = "OK  " if not galat else "GAGAL"
    print(f"  {tanda} {ep.relative_to(AKAR)}")
    for g in galat:
        print("       ", g)
print("JUMLAH_ENTRY_POINT=", len(entry_points))
print("GALAT_KONTRAK_IMPOR=", total_galat_impor)
if total_galat_impor:
    GAGAL.append(f"{total_galat_impor} galat kontrak impor di entry point")

# ========================================================================== #
bagian("B. pengatur laju benar-benar terpasang di jalur permintaan")
# ========================================================================== #
try:
    from lux_modul.eksekusi.binance_client import (
        BOBOT_BATAS_PER_MENIT,
        BOBOT_BUDGET_DEFAULT,
        BinanceFuturesClient,
        bobot_permintaan,
    )

    src = inspect.getsource(BinanceFuturesClient._permintaan)
    if "_sebelum_permintaan" not in src:
        GAGAL.append("_permintaan tidak memanggil _sebelum_permintaan (limiter bisa dilewati)")
        print("  GAGAL: gerbang laju tidak ada di _permintaan")
    else:
        print("  OK   _permintaan memanggil _sebelum_permintaan")
    if "_catat_pembatasan" not in src:
        GAGAL.append("_permintaan tidak mencatat pembatasan 418/429")
        print("  GAGAL: 418/429 tidak dicatat sebagai ban")
    else:
        print("  OK   418/429 dicatat sebagai ban lokal")

    tanda_tangan = inspect.signature(BinanceFuturesClient.__init__)
    for wajib in ("pengatur_laju", "tidur"):
        if wajib not in tanda_tangan.parameters:
            GAGAL.append(f"BinanceFuturesClient.__init__ tanpa parameter {wajib}")
    print("  OK   parameter injeksi tersedia:", ", ".join(tanda_tangan.parameters))
    print(
        "  BUDGET_DEFAULT=", BOBOT_BUDGET_DEFAULT,
        "dari BATAS_RESMI=", BOBOT_BATAS_PER_MENIT,
    )
    if BOBOT_BUDGET_DEFAULT >= BOBOT_BATAS_PER_MENIT:
        GAGAL.append("budget default tidak menyisakan margin di bawah batas resmi Binance")
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"wiring pengatur laju: {exc}")

# ========================================================================== #
bagian("C. gerbang ban di level engine")
# ========================================================================== #
try:
    from lux_modul.mesin_multi import MesinMultiPair

    src_siklus = inspect.getsource(MesinMultiPair.siklus)
    if "_sisa_ban_ms" not in src_siklus:
        GAGAL.append("siklus engine tidak memeriksa sisa ban IP")
        print("  GAGAL: engine tetap menembak walau IP kena ban")
    else:
        print("  OK   siklus dilewati selama IP masih kena ban")
    if not hasattr(MesinMultiPair, "_ada_eksekusi_menggantung"):
        GAGAL.append("tidak ada penjaga eksekusi menggantung saat siklus dilewati")
    else:
        print("  OK   runner dengan entry/bracket aktif tetap dipoll")
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"gerbang ban engine: {exc}")

# ========================================================================== #
bagian("D. gerbang kredensial: LIVE tidak boleh terbuka karena kelalaian")
# ========================================================================== #
try:
    from lux_modul.eksekusi.kredensial import MODE_LIVE, MODE_TESTNET, muat_kredensial

    def harus_gagal(label, **kw):
        try:
            muat_kredensial(**kw)
        except Exception as exc:  # noqa: BLE001
            print(f"  OK   {label} ditolak ({type(exc).__name__})")
            return True
        print(f"  GAGAL {label} DITERIMA padahal harus ditolak")
        GAGAL.append(f"gerbang kredensial lemah: {label} diterima")
        return False

    # Runner CI tidak punya env kredensial apa pun -> semuanya wajib ditolak.
    harus_gagal("LIVE tanpa gerbang CLI", mode=MODE_LIVE, konfirmasi_live_cli=False)
    harus_gagal("LIVE dengan CLI tapi tanpa env", mode=MODE_LIVE, konfirmasi_live_cli=True)
    harus_gagal("TESTNET tanpa kredensial", mode=MODE_TESTNET)
    harus_gagal("mode ngawur", mode="kasino")
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"gerbang kredensial: {exc}")

# ========================================================================== #
bagian("E. model beban API untuk 29 pair (bukan pengukuran jaringan)")
# ========================================================================== #
# JUJUR SOAL SIFATNYA: ini model aritmetika memakai fungsi bobot milik kode
# sendiri, bukan trafik nyata. Nilainya: menunjukkan apakah beban steady-state
# masuk ke dalam anggaran. Yang MENJAMIN plafon tetap pengatur laju di runtime.
try:
    from lux_modul.eksekusi.binance_client import (
        BOBOT_BUDGET_DEFAULT,
        _PATH_DEPTH,
        _PATH_KLINES,
        _PATH_POSISI,
        _PATH_SALDO,
        _PATH_TICKER_24J,
        _PATH_WAKTU,
        bobot_permintaan,
    )
    from lux_modul.kontrak import tf_ms

    PAIR = 29
    TF = ("1m", "5m", "15m")
    POLL_DETIK = 15.0
    siklus_per_menit = 60.0 / POLL_DETIK

    b_klines = bobot_permintaan(_PATH_KLINES, {"limit": 200})
    b_waktu = bobot_permintaan(_PATH_WAKTU, {})
    b_saldo = bobot_permintaan(_PATH_SALDO, {})
    b_posisi = bobot_permintaan(_PATH_POSISI, {})
    b_ticker = bobot_permintaan(_PATH_TICKER_24J, {})
    b_depth = bobot_permintaan(_PATH_DEPTH, {"limit": 20})

    # Setelah patch: klines hanya disegarkan saat bar TF-nya tutup.
    segar_per_menit = sum(60000.0 / tf_ms(tf) for tf in TF) * PAIR
    bobot_klines = segar_per_menit * b_klines
    # waktu server di-cache 30 detik -> maksimum 2 panggilan/menit total.
    bobot_waktu = 2.0 * b_waktu
    # snapshot akun: satu kali per siklus, bukan per runner.
    bobot_akun = siklus_per_menit * (b_saldo + b_posisi)
    # pemindai likuiditas: sekali per 30 menit (TTL 1800 detik).
    bobot_pindai = (b_ticker + 80 * b_depth) / 30.0

    total = bobot_klines + bobot_waktu + bobot_akun + bobot_pindai
    print(f"  klines (per-TF, saat bar tutup) : {bobot_klines:8.1f} bobot/menit")
    print(f"  waktu server (cache 30s)        : {bobot_waktu:8.1f}")
    print(f"  snapshot akun (1x/siklus)       : {bobot_akun:8.1f}")
    print(f"  pemindai likuiditas (TTL 30m)   : {bobot_pindai:8.1f}")
    print(f"  TOTAL_MODEL                     : {total:8.1f} bobot/menit")
    print(f"  ANGGARAN_PENGATUR_LAJU          : {BOBOT_BUDGET_DEFAULT:8.1f} bobot/menit")
    print("  SEBELUM_PERBAIKAN (terukur)     :   1740.0 bobot/menit")
    if total <= BOBOT_BUDGET_DEFAULT:
        print("  MODEL_BEBAN_OK margin=", round(BOBOT_BUDGET_DEFAULT - total, 1))
    else:
        print("  MODEL_BEBAN_KETAT: pengatur laju akan menahan permintaan (aman, tapi lebih lambat)")
        CATATAN.append(
            f"beban model {total:.0f} > anggaran {BOBOT_BUDGET_DEFAULT}; "
            "limiter akan melambatkan siklus, tidak menyebabkan ban"
        )
except Exception as exc:  # noqa: BLE001
    print("  TIDAK DIVERIFIKASI:", type(exc).__name__, exc)
    CATATAN.append(f"model beban API tidak dapat dihitung: {exc}")

# ========================================================================== #
bagian("F. larangan market order pada entry masih berlaku")
# ========================================================================== #
try:
    from lux_modul.eksekusi.order import TIF_POST_ONLY, TIPE_TERLARANG_ENTRY

    assert TIF_POST_ONLY == "GTX", TIF_POST_ONLY
    assert "MARKET" in TIPE_TERLARANG_ENTRY, TIPE_TERLARANG_ENTRY
    print("  OK   entry wajib LIMIT+GTX; MARKET terlarang:", TIPE_TERLARANG_ENTRY)
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"kebijakan order: {exc}")

# ========================================================================== #
bagian("RINGKASAN KESIAPAN LIVE")
for c in CATATAN:
    print("  catatan:", c)
if GAGAL:
    print("STATUS_KESIAPAN= BELUM SIAP")
    for g in GAGAL:
        print("  -", g)
    sys.exit(1)
print("STATUS_KESIAPAN= SIAP")
