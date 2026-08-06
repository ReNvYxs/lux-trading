#!/usr/bin/env python3
"""Gerbang regresi permanen untuk modul bersih.

Prinsip perancangan. Gerbang ini TIDAK menebak nama atribut konfigurasi, sebab
menebak adalah sumber galat yang sudah terbukti mahal di proyek ini. Yang
dipatok keras hanya invarian yang sudah dibuktikan berulang kali lewat
pengujian nyata, yaitu 26 id strategi dan suite pytest tanpa kegagalan. Sisanya
dikunci dengan cara snapshot: run pertama menulis BASELINE.json apa adanya,
run berikutnya membandingkan keadaan sekarang terhadap baseline itu dan
menolak setiap pergeseran yang tidak disengaja.

Keluaran: bukti/ci/GERBANG.json dan bukti/ci/BASELINE.json.
Kode keluar 0 bila lulus, 1 bila ada masalah.
"""
import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.getcwd())

KELUARAN = os.path.join("bukti", "ci")
BASELINE = os.path.join(KELUARAN, "BASELINE.json")
LAPORAN = os.path.join(KELUARAN, "GERBANG.json")
RINGKAS_PYTEST = os.path.join("bukti", "ringkas_pytest.txt")
MIN_PYTEST_LULUS = int(os.environ.get("CI_MIN_PYTEST", "242"))

DIKENAL = [
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

MODUL_WAJIB = [
    "lux_modul",
    "lux_modul.backtest",
    "lux_modul.konfigurasi",
    "lux_modul.kontrak",
    "lux_modul.plugin",
    "lux_modul.strategi",
    "lux_modul.eksekusi.binance_client",
    "lux_modul.eksekusi.kredensial",
    "lux_modul.eksekusi.order",
    "lux_modul.eksekusi_aman.inti",
    "lux_modul.eksekusi_aman.saklar",
    "lux_modul.live_runner",
]

masalah = []


def catat(pesan):
    masalah.append(pesan)


def tulis(jalur, obj):
    d = os.path.dirname(jalur)
    if d:
        os.makedirs(d, exist_ok=True)
    fh = open(jalur, "w", encoding="utf-8")
    json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=True, default=str)
    fh.close()


def baca(jalur):
    if not os.path.exists(jalur):
        return None
    try:
        fh = open(jalur, "r", encoding="utf-8")
        data = json.load(fh)
        fh.close()
        return data
    except Exception:
        catat("baseline tidak dapat dibaca, dianggap tidak ada")
        return None


def aman(nama, fn, bawaan):
    try:
        return fn()
    except Exception:
        catat(nama + " gagal: " + traceback.format_exc()[-300:])
        return bawaan


def impor_wajib():
    hasil = {}
    for nama in MODUL_WAJIB:
        try:
            __import__(nama)
            hasil[nama] = "OK"
        except Exception as e:
            hasil[nama] = type(e).__name__ + ": " + str(e)
            catat("impor gagal: " + nama + " -> " + hasil[nama])
    return hasil


def id_registry():
    from lux_modul.strategi import registry_bawaan

    reg = registry_bawaan()
    peta = getattr(reg, "_peta", None)
    if isinstance(peta, dict) and peta:
        return sorted(str(k) for k in peta.keys())
    nama = []
    for s in reg.semua():
        n = getattr(s, "nama", None) or getattr(s, "id", None)
        if n is None:
            sp = getattr(s, "spek", None)
            n = getattr(sp, "nama", None)
        if n:
            nama.append(str(n))
    return sorted(set(nama))


def ringkas_konfigurasi():
    from lux_modul.konfigurasi import muat_konfigurasi

    k = muat_konfigurasi(muat_env=False)
    r = k.ringkas()
    if isinstance(r, dict):
        keluar = {}
        for a in r:
            keluar[str(a)] = str(r[a])
        return keluar
    return {"repr": str(r)}


def hitung_pytest():
    if not os.path.exists(RINGKAS_PYTEST):
        catat("ringkas_pytest.txt tidak ada, alat/periksa.sh tidak menghasilkan bukti")
        return {"ada": False}
    fh = open(RINGKAS_PYTEST, "r", encoding="utf-8", errors="replace")
    teks = fh.read()
    fh.close()

    def ambil(pola):
        m = re.search(pola, teks)
        return int(m.group(1)) if m else 0

    return {
        "ada": True,
        "lulus": ambil(r"(\d+) passed"),
        "gagal": ambil(r"(\d+) failed"),
        "galat": ambil(r"(\d+) error"),
        "dilewati": ambil(r"(\d+) skipped"),
        "rc": ambil(r"rc_pytest=(\d+)"),
    }


def main():
    os.makedirs(KELUARAN, exist_ok=True)
    kini = {}
    kini["impor"] = impor_wajib()
    kini["registry_id"] = aman("registry", id_registry, [])
    kini["konfigurasi"] = aman("konfigurasi", ringkas_konfigurasi, {})
    kini["pytest"] = hitung_pytest()

    hilang = sorted(set(DIKENAL) - set(kini["registry_id"]))
    tambahan = sorted(set(kini["registry_id"]) - set(DIKENAL))
    if hilang:
        catat("strategi hilang dari registry: " + ", ".join(hilang))
    if tambahan:
        catat("strategi baru belum diakui gerbang: " + ", ".join(tambahan))

    p = kini["pytest"]
    if p.get("ada"):
        if p.get("gagal"):
            catat("pytest gagal: " + str(p.get("gagal")))
        if p.get("galat"):
            catat("pytest error: " + str(p.get("galat")))
        if (p.get("lulus") or 0) < MIN_PYTEST_LULUS:
            catat(
                "jumlah tes lulus turun: "
                + str(p.get("lulus"))
                + " kurang dari "
                + str(MIN_PYTEST_LULUS)
            )
        if p.get("rc"):
            catat("rc_pytest bukan nol: " + str(p.get("rc")))

    dasar = baca(BASELINE)
    laporan = {"kini": kini, "baseline_ada": bool(dasar)}
    if dasar is None:
        tulis(BASELINE, kini)
        laporan["baseline_dibuat"] = True
    else:
        geser = {}
        for kunci in ("registry_id", "konfigurasi"):
            a = dasar.get(kunci)
            b = kini.get(kunci)
            if a != b:
                geser[kunci] = {"baseline": a, "kini": b}
                catat("pergeseran terhadap baseline pada " + kunci)
        laporan["pergeseran"] = geser

    laporan["masalah"] = masalah
    laporan["vonis"] = "LULUS" if not masalah else "GAGAL"
    tulis(LAPORAN, laporan)

    print("GERBANG=" + laporan["vonis"])
    print("registry_jumlah=" + str(len(kini["registry_id"])))
    print("pytest=" + json.dumps(kini["pytest"], ensure_ascii=False))
    print("baseline_ada=" + str(bool(dasar)))
    for m in masalah:
        print("MASALAH: " + m[:500])
    return 0 if not masalah else 1


if __name__ == "__main__":
    sys.exit(main())
