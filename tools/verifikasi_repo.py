"""Verifikasi kesehatan repo secara menyeluruh. Jalankan: python tools/verifikasi_repo.py

Dibuat sebagai skrip (bukan heredoc di dalam YAML) setelah pelajaran nyata:
heredoc yang menjorok di dalam blok `run: |` membuat penanda penutupnya tidak
pernah cocok, sehingga langkah verifikasi gagal tanpa keluaran apa pun dan
seluruh gerbang uji ikut terlewat. Skrip di repo bisa dijalankan sama persis di
runner CI maupun di mesin lokal.

CATATAN PENTING: skrip ini berada di tools/, jadi Python menaruh tools/ sebagai
sys.path[0] - bukan akar repo. Tanpa penyisipan akar repo di bawah, `import
lux_modul` gagal dengan ModuleNotFoundError meskipun repo sehat (ini benar-benar
terjadi di run pertama). pytest tidak terkena karena ia menyisipkan rootdir
sendiri.

Keluar dengan kode 1 bila ada pemeriksaan WAJIB yang gagal.
"""
import ast
import importlib
import pathlib
import pkgutil
import re
import sys

AKAR = pathlib.Path(__file__).resolve().parent.parent
if str(AKAR) not in sys.path:
    sys.path.insert(0, str(AKAR))

GAGAL = []
CATATAN = []


def bagian(judul: str) -> None:
    print(f"\n===== {judul} =====")


print("AKAR_REPO=", AKAR)

# --------------------------------------------------------------------------- #
bagian("1. seluruh modul bisa diimpor")
import lux_modul  # noqa: E402

print("VERSI", getattr(lux_modul, "__version__", "?"))
gagal_impor = []
for m in pkgutil.walk_packages(lux_modul.__path__, "lux_modul."):
    try:
        importlib.import_module(m.name)
    except Exception as exc:  # noqa: BLE001 - kita ingin SEMUA kegagalan, bukan yang pertama
        gagal_impor.append(f"{m.name}: {type(exc).__name__}: {exc}")
print("JUMLAH_GAGAL_IMPOR=", len(gagal_impor))
for g in gagal_impor:
    print("  ", g)
if gagal_impor:
    GAGAL.append(f"{len(gagal_impor)} modul gagal diimpor")

# --------------------------------------------------------------------------- #
bagian("2. tidak ada sisa nama field yang salah")
# Akar bug P0: StrategyVerdict tidak punya atribut `tp` maupun `strategi`.
POLA_SALAH = (r'getattr\(v, "tp", 0\)', r'getattr\(v, "strategi", ""\)')
temuan = []
for p in sorted((AKAR / "lux_modul").rglob("*.py")):
    isi = p.read_text(encoding="utf-8")
    for pola in POLA_SALAH:
        for m in re.finditer(pola, isi):
            baris = isi[: m.start()].count("\n") + 1
            temuan.append(f"{p.relative_to(AKAR)}:{baris}: {m.group(0)}")
if temuan:
    for t in temuan:
        print("  ", t)
    GAGAL.append(f"{len(temuan)} pemakaian nama field yang salah masih ada")
else:
    print("POLA_SALAH_BERSIH")

# --------------------------------------------------------------------------- #
bagian("3. jalur verdict -> TP benar-benar hidup")
try:
    from lux_modul.kontrak import (
        ARAH_LONG,
        KELOMPOK_INDIKATOR,
        StrategyVerdict,
        TargetTP,
    )
    from lux_modul.live_runner import strategi_verdict, tp_pertama

    v = StrategyVerdict(
        strategy_id="verifikasi",
        kelompok=KELOMPOK_INDIKATOR,
        arah=ARAH_LONG,
        skor=70.0,
        ambang=60.0,
        entry=100.0,
        sl=95.0,
        tps=(TargetTP(harga=110.0, porsi=1.0),),
        level=100.0,
        invalidation=94.0,
        tfs_used=("15m",),
    )
    assert not hasattr(v, "tp"), "atribut tp seharusnya memang tidak ada"
    assert tp_pertama(v) == 110.0, f"tp_pertama salah: {tp_pertama(v)}"
    assert strategi_verdict(v) == "verifikasi"
    print("TP_DARI_VERDICT_OK harga=", tp_pertama(v))
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"jalur verdict->TP: {exc}")

# --------------------------------------------------------------------------- #
bagian("4. kontrak auto-entry: scalp DAN intraday, swing dilarang")
try:
    from lux_modul.governor import HORIZON_AUTO_ENTRY
    from lux_modul.kontrak import HORIZON_INTRADAY, HORIZON_SCALPING

    print("HORIZON_AUTO_ENTRY=", HORIZON_AUTO_ENTRY)
    assert HORIZON_SCALPING in HORIZON_AUTO_ENTRY, "scalp WAJIB boleh auto-entry"
    assert HORIZON_INTRADAY in HORIZON_AUTO_ENTRY, "intraday WAJIB boleh auto-entry"
    assert len(HORIZON_AUTO_ENTRY) == 2, "tepat dua mode, tidak lebih"
    assert not any(
        "swing" in str(h).lower() for h in HORIZON_AUTO_ENTRY
    ), "swing DILARANG auto-entry"
    print("KONTRAK_AUTO_ENTRY_OK")
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"kontrak auto-entry: {exc}")

# --------------------------------------------------------------------------- #
bagian("5. pengatur laju & gerbang ban terpasang")
try:
    from lux_modul.eksekusi.binance_client import (
        BOBOT_BATAS_PER_MENIT,
        PengaturLaju,
        _PATH_TICKER_24J,
        bobot_permintaan,
        ms_ban_dari_pesan,
    )

    assert bobot_permintaan(_PATH_TICKER_24J, {}) == 40, "ticker 24h tanpa simbol = bobot 40"
    pesan = "Way too many requests; IP(130.176.187.110) banned until 1785848930502."
    assert ms_ban_dari_pesan(pesan) == 1785848930502
    jam = [0.0]
    laju = PengaturLaju(
        budget_per_menit=10,
        jam=lambda: jam[0],
        tidur=lambda d: jam.__setitem__(0, jam[0] + d),
    )
    assert laju.ambil(6) == 0.0
    assert laju.ambil(6) > 0.0, "anggaran habis WAJIB menahan"
    print("RATE_LIMIT_OK batas_resmi=", BOBOT_BATAS_PER_MENIT)
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"pengatur laju: {exc}")

# --------------------------------------------------------------------------- #
bagian("6. TF pivot tidak lagi semi-hardcode")
try:
    isi = (AKAR / "lux_modul/strategi/level_harga.py").read_text(encoding="utf-8")
    if '288 if b.tf == "5m"' in isi:
        GAGAL.append("level_harga.py masih memakai peta TF hardcode")
        print("  GAGAL: pola hardcode masih ada")
    else:
        from lux_modul.strategi.level_harga import _bar_per_hari

        assert _bar_per_hari("5m") == 288, _bar_per_hari("5m")
        assert _bar_per_hari("15m") == 96, _bar_per_hari("15m")
        assert _bar_per_hari("1m") == 1440, _bar_per_hari("1m")
        assert _bar_per_hari("tf-ngawur") == 24, "TF tak dikenal wajib pakai cadangan"
        print("TF_DINAMIS_OK 1m=", _bar_per_hari("1m"), "5m=", _bar_per_hari("5m"))
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"TF pivot: {exc}")

# --------------------------------------------------------------------------- #
bagian("7. registry strategi")
try:
    from lux_modul.strategi import registry_bawaan

    reg = registry_bawaan()
    nama = None
    for atribut in ("nama", "semua", "daftar", "keys"):
        fn = getattr(reg, atribut, None)
        if callable(fn):
            try:
                nama = sorted(str(x) for x in fn())
                break
            except Exception:  # noqa: BLE001
                continue
    jumlah = len(nama) if nama is not None else -1
    print("STRATEGI_TERDAFTAR=", jumlah)
    if nama:
        print("  ", ", ".join(nama))
    if jumlah == 0:
        GAGAL.append("registry strategi kosong")
except Exception as exc:  # noqa: BLE001
    print("  GAGAL:", type(exc).__name__, exc)
    GAGAL.append(f"registry: {exc}")

# --------------------------------------------------------------------------- #
bagian("8. jumlah fungsi uji (dihitung, bukan dihafal)")
total_uji = 0
for p in sorted((AKAR / "tests").glob("test_*.py")):
    pohon = ast.parse(p.read_text(encoding="utf-8"))
    n = sum(
        1
        for node in pohon.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )
    total_uji += n
    print(f"  {p.name}: {n}")
print("TOTAL_FUNGSI_UJI=", total_uji)
CATATAN.append(f"total fungsi uji = {total_uji}")

# --------------------------------------------------------------------------- #
bagian("RINGKASAN VERIFIKASI")
for c in CATATAN:
    print("  info:", c)
if GAGAL:
    print("STATUS_VERIFIKASI= GAGAL")
    for g in GAGAL:
        print("  -", g)
    sys.exit(1)
print("STATUS_VERIFIKASI= LULUS")
