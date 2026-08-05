"""Uji integritas sinyal + A/B varian terkendali pada dataset 95 pair.

SEMANGAT SKRIP INI: mengukur dan membuktikan, bukan menyetel. Tidak ada satu
pun parameter strategi yang diubah secara permanen. "Varian" di bawah hanya
diterapkan di dalam proses backtest sebagai pembanding terkendali (satu
variabel berubah), lalu dibuang saat proses selesai. Tidak pernah di-commit
ke modul.

Latar belakang varian `final_bar_per_hari`:
  Pohon `main` memakai helper `_bar_per_hari(tf)` di `_pivot_reversal`
  (4h -> 6, 1d -> 1), sedangkan pohon `final` memakai konstanta
  `288 if tf == "5m" else 96 if tf == "15m" else 24` (4h -> 24, 1d -> 24).
  Untuk 5m/15m/1h kedua rumus MENGHASILKAN ANGKA SAMA, jadi perbedaan hanya
  muncul pada TF entry 4h dan 1d. Itu sebabnya backtest 95 pair sebelumnya
  (5m/15m/1h saja) secara struktural tidak mungkin mendeteksi perbedaan ini.

Subperintah:
  inventaris  -> integritas dataset (celah, duplikat ts, ts menurun, NaN, OHLC)
  integritas  -> determinisme, anti-look-ahead, sanitasi verdict
  backtest    -> backtest penuh + metrik per strategi/kelompok/arah/simbol

Env: LUX_AKAR, LUX_DATA_DIR, LUX_KONFIG, LUX_VARIAN, LUX_MAKS_BAR,
     LUX_MAKS_SIMBOL, LUX_BATAS_DETIK, LUX_SARING_BIAYA, LUX_KELUARAN,
     LUX_SIMBOL, LUX_SAMPEL
"""
from __future__ import annotations

import inspect
import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict


def _env(nama, bawaan=""):
    return os.environ.get(nama, bawaan)


def _env_int(nama, bawaan=0):
    try:
        return int(_env(nama, str(bawaan)) or bawaan)
    except ValueError:
        return bawaan


AKAR = os.path.abspath(_env("LUX_AKAR", os.getcwd()))
if not os.path.isdir(os.path.join(AKAR, "lux_modul")):
    print(f"GAGAL: LUX_AKAR tidak punya lux_modul/: {AKAR}")
    raise SystemExit(2)
sys.path.insert(0, AKAR)

from lux_modul.backtest import Backtester  # noqa: E402
from lux_modul.data.loader import muat_csv  # noqa: E402
from lux_modul.data.plane import DataPlane  # noqa: E402
from lux_modul.kontrak import Bars, HORIZON_INTRADAY, TFPlan  # noqa: E402
from lux_modul.pipeline import Pipeline  # noqa: E402
from lux_modul.strategi import registry_bawaan  # noqa: E402

KONFIG = {
    "single_5m": ("5m", ()),
    "single_15m": ("15m", ()),
    "multi_15m_ctx1h": ("15m", ("1h",)),
    "single_1h": ("1h", ()),
    "multi_1h_ctx4h": ("1h", ("4h",)),
    "single_4h": ("4h", ()),
    "multi_4h_ctx1d": ("4h", ("1d",)),
}

MODAL_AWAL = 1000.0
DATA_DIR = _env("LUX_DATA_DIR") or os.path.join(AKAR, "dataset_masuk", "ekstrak")


def terapkan_varian():
    """Terapkan varian pembanding terkendali. Hanya di memori proses ini."""
    varian = _env("LUX_VARIAN", "asli") or "asli"
    if varian == "asli":
        return {"varian": "asli", "diterapkan": False}
    if varian != "final_bar_per_hari":
        return {"varian": varian, "diterapkan": False, "alasan": "varian tidak dikenal"}

    import lux_modul.strategi.level_harga as lh

    if not hasattr(lh, "_bar_per_hari"):
        return {
            "varian": varian,
            "diterapkan": False,
            "alasan": "pohon ini tidak punya _bar_per_hari (kemungkinan sudah gaya final)",
        }
    asli = lh._bar_per_hari

    def tiruan(tf, cadangan=24):
        # Rumus persis milik pohon `final`.
        return 288 if tf == "5m" else 96 if tf == "15m" else 24

    lh._bar_per_hari = tiruan
    bukti = {}
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        try:
            bukti[tf] = {"asli": asli(tf), "varian": tiruan(tf)}
        except Exception as exc:  # noqa: BLE001
            bukti[tf] = {"galat": f"{type(exc).__name__}: {exc}"}
    return {"varian": varian, "diterapkan": True, "nilai_bar_per_hari": bukti}


def _saring_kwargs(fungsi, kandidat):
    """Kirim hanya kwargs yang ada di tanda tangan; jangan menebak."""
    try:
        sig = inspect.signature(fungsi)
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in kandidat.items() if k in sig.parameters}


def muat_bars(simbol, tf):
    jalur = os.path.join(DATA_DIR, f"{simbol}_{tf}.csv")
    try:
        return muat_csv(jalur, tf, simbol)
    except TypeError:
        return muat_csv(jalur, tf)


def iris(bars, a, b):
    return Bars(
        tf=bars.tf,
        simbol=bars.simbol,
        ts=bars.ts[a:b],
        open=bars.open[a:b],
        high=bars.high[a:b],
        low=bars.low[a:b],
        close=bars.close[a:b],
        volume=bars.volume[a:b],
    )


def potong_akhir(bars, maks_bar):
    if maks_bar <= 0 or len(bars.ts) <= maks_bar:
        return bars
    return iris(bars, len(bars.ts) - maks_bar, len(bars.ts))


def muat_plane(simbol, tfs, maks_bar):
    peta = {}
    for tf in tfs:
        b = muat_bars(simbol, tf)
        peta[tf] = potong_akhir(b, maks_bar) if tf == tfs[0] else b
    return DataPlane(peta)


def daftar_simbol(tfs):
    manual = [s.strip() for s in _env("LUX_SIMBOL").split(",") if s.strip()]
    if manual:
        kandidat = manual
    else:
        kandidat = sorted(
            {
                n.rsplit("_", 1)[0]
                for n in os.listdir(DATA_DIR)
                if n.endswith(".csv") and "_" in n
            }
        )
    lengkap = [
        s
        for s in kandidat
        if all(os.path.exists(os.path.join(DATA_DIR, f"{s}_{tf}.csv")) for tf in tfs)
    ]
    maks = _env_int("LUX_MAKS_SIMBOL", 0)
    return lengkap[:maks] if maks > 0 else lengkap


def buat_pipeline(plane, tfplan, saring):
    kw = _saring_kwargs(
        Pipeline.__init__,
        {
            "horizon": HORIZON_INTRADAY,
            "registry": registry_bawaan(),
            "balance": MODAL_AWAL,
            "saring_biaya": saring,
        },
    )
    return Pipeline(plane, tfplan, **kw)


def buat_backtester(plane, tfplan, saring):
    kw = _saring_kwargs(
        Backtester.__init__,
        {
            "horizon": HORIZON_INTRADAY,
            "registry": registry_bawaan(),
            "balance_awal": MODAL_AWAL,
            "saring_biaya": saring,
        },
    )
    return Backtester(plane, tfplan, **kw)


def _bulat(x, n=4):
    if x is None:
        return None
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return "inf" if math.isinf(x) else "nan"
    return round(x, n)


def _pf(menang, kalah):
    if kalah <= 0:
        return None if menang <= 0 else float("inf")
    return menang / kalah


def metrik(trades):
    n = len(trades)
    if n == 0:
        return {"trade": 0}
    urut = sorted(trades, key=lambda t: t["ts_entry"])
    pnl = [t["pnl"] for t in urut]
    r = [t["r"] for t in urut]
    menang = [p for p in pnl if p > 0]
    kalah = [p for p in pnl if p <= 0]
    kotor = [t["pnl_kotor"] for t in urut]
    ek = puncak = dd = 0.0
    for p in pnl:
        ek += p
        puncak = max(puncak, ek)
        dd = max(dd, puncak - ek)
    return {
        "trade": n,
        "menang": len(menang),
        "win_rate": _bulat(len(menang) / n),
        "pnl_bersih": _bulat(sum(pnl)),
        "pnl_kotor": _bulat(sum(kotor)),
        "biaya": _bulat(sum(t["biaya"] for t in urut)),
        "profit_factor_bersih": _bulat(_pf(sum(menang), abs(sum(kalah)))),
        "profit_factor_kotor": _bulat(
            _pf(sum(x for x in kotor if x > 0), abs(sum(x for x in kotor if x <= 0)))
        ),
        "expectancy_r": _bulat(sum(r) / n),
        "edge_kotor_per_trade": _bulat(sum(kotor) / n),
        "biaya_per_trade": _bulat(sum(t["biaya"] for t in urut) / n),
        "max_drawdown_usd": _bulat(dd),
        "sampel_cukup": n >= 200,
    }


# ------------------------------------------------------------- inventaris


def cmd_inventaris():
    """Periksa dataset itu sendiri sebelum menyimpulkan apa pun dari hasilnya."""
    try:
        from lux_modul.kontrak import tf_ms
    except ImportError:
        tf_ms = None

    t0 = time.time()
    batas = _env_int("LUX_BATAS_DETIK", 0)
    berkas = sorted(n for n in os.listdir(DATA_DIR) if n.endswith(".csv") and "_" in n)
    per_tf = defaultdict(
        lambda: {"berkas": 0, "bar": 0, "bar_min": None, "bar_maks": None, "celah": 0}
    )
    rinci = {}
    bermasalah = []
    simbol_set = set()
    terpotong = False

    for n in berkas:
        if batas and (time.time() - t0) > batas:
            terpotong = True
            break
        simbol, tf = n[:-4].rsplit("_", 1)
        simbol_set.add(simbol)
        try:
            b = muat_bars(simbol, tf)
        except Exception as exc:  # noqa: BLE001
            bermasalah.append({"berkas": n, "galat": f"{type(exc).__name__}: {exc}"})
            continue
        ts = list(b.ts)
        nb = len(ts)
        harap = None
        if tf_ms is not None:
            try:
                harap = tf_ms(tf)
            except Exception:  # noqa: BLE001
                harap = None
        dup = turun = celah = bar_hilang = 0
        for i in range(1, nb):
            d = ts[i] - ts[i - 1]
            if d == 0:
                dup += 1
            elif d < 0:
                turun += 1
            elif harap and d != harap:
                celah += 1
                bar_hilang += max(0, int(d // harap) - 1)
        tidak_hingga = 0
        ohlc_rusak = 0
        vol_nol = 0
        for i in range(nb):
            o, h, l, c = (
                float(b.open[i]),
                float(b.high[i]),
                float(b.low[i]),
                float(b.close[i]),
            )
            v = float(b.volume[i])
            if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                tidak_hingga += 1
                continue
            if not (l <= o <= h and l <= c <= h and l <= h):
                ohlc_rusak += 1
            if v == 0.0:
                vol_nol += 1
        d = {
            "bar": nb,
            "ts_awal": ts[0] if nb else None,
            "ts_akhir": ts[-1] if nb else None,
            "hari": _bulat((ts[-1] - ts[0]) / 86400000.0, 2) if nb > 1 else None,
            "duplikat_ts": dup,
            "ts_menurun": turun,
            "celah": celah,
            "bar_hilang": bar_hilang,
            "nilai_tidak_hingga": tidak_hingga,
            "ohlc_rusak": ohlc_rusak,
            "volume_nol": vol_nol,
        }
        rinci[n] = d
        s = per_tf[tf]
        s["berkas"] += 1
        s["bar"] += nb
        s["bar_min"] = nb if s["bar_min"] is None else min(s["bar_min"], nb)
        s["bar_maks"] = nb if s["bar_maks"] is None else max(s["bar_maks"], nb)
        s["celah"] += celah
        if dup or turun or tidak_hingga or ohlc_rusak:
            bermasalah.append({"berkas": n, **d})

    out = {
        "perintah": "inventaris",
        "data_dir": DATA_DIR,
        "jumlah_berkas_csv": len(berkas),
        "berkas_diperiksa": len(rinci),
        "terpotong_batas_waktu": terpotong,
        "jumlah_simbol": len(simbol_set),
        "simbol": sorted(simbol_set),
        "tf_tersedia": sorted(per_tf.keys()),
        "per_tf": {k: dict(v) for k, v in sorted(per_tf.items())},
        "jumlah_berkas_bermasalah": len(bermasalah),
        "berkas_bermasalah": bermasalah[:60],
        "lulus": not bermasalah and not terpotong,
        "detik": round(time.time() - t0, 1),
        "rinci": rinci,
    }
    tulis(out, "inventaris")
    return 0


# --------------------------------------------------------------- backtest


def cmd_backtest():
    varian_info = terapkan_varian()
    label = _env("LUX_KONFIG", "single_15m")
    if label not in KONFIG:
        print(f"konfigurasi tidak dikenal: {label}")
        return 2
    entry_tf, ctx = KONFIG[label]
    tfs = (entry_tf,) + tuple(ctx)
    maks_bar = _env_int("LUX_MAKS_BAR", 0)
    batas = _env_int("LUX_BATAS_DETIK", 0)
    saring = _env("LUX_SARING_BIAYA", "1") != "0"

    simbol_list = daftar_simbol(tfs)
    print(json.dumps({"varian": varian_info}, ensure_ascii=False), flush=True)
    print(
        f"konfig={label} entry_tf={entry_tf} ctx={ctx} simbol={len(simbol_list)} "
        f"maks_bar={maks_bar}",
        flush=True,
    )

    t0 = time.time()
    semua = []
    per_simbol = {}
    gagal = {}
    tolak_kode = defaultdict(int)
    kandidat_strategi = defaultdict(int)
    menang_strategi = defaultdict(int)
    bar_total = tolak_biaya = batal_gap = diproses = 0

    for simbol in simbol_list:
        if batas and (time.time() - t0) > batas:
            print(f"batas waktu {batas}s tercapai pada {diproses} simbol", flush=True)
            break
        ts = time.time()
        try:
            plane = muat_plane(simbol, tfs, maks_bar)
            bt = buat_backtester(
                plane, TFPlan(entry_tf=entry_tf, context_tfs=tuple(ctx)), saring
            )
            hasil = bt.jalankan()
        except Exception as exc:  # noqa: BLE001
            gagal[simbol] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            continue
        diproses += 1
        r = hasil.ringkas()
        bar_total += r.get("bar_dievaluasi", 0)
        tolak_biaya += r.get("entry_ditolak_biaya", 0)
        batal_gap += r.get("entry_batal_gap", 0)
        for k, v in (r.get("tolak_biaya_per_kode") or {}).items():
            tolak_kode[k] += v
        for k, v in (r.get("kandidat_per_strategi") or {}).items():
            kandidat_strategi[k] += v
        for k, v in (r.get("menang_per_strategi") or {}).items():
            menang_strategi[k] += v
        lokal = []
        for t in hasil.trades:
            rec = {
                "simbol": simbol,
                "strategy_id": t.strategy_id,
                "kelompok": t.kelompok,
                "arah": str(t.arah),
                "ts_entry": int(t.ts_entry),
                "alasan_keluar": t.alasan_keluar,
                "pnl": float(t.pnl_bersih),
                "pnl_kotor": float(t.pnl_kotor),
                "biaya": float(t.biaya),
                "r": float(t.r_multiple),
            }
            lokal.append(rec)
            semua.append(rec)
        m = metrik(lokal)
        m["bar"] = r.get("bar_dievaluasi")
        m["detik"] = round(time.time() - ts, 1)
        per_simbol[simbol] = m
        print(
            f"[{diproses}/{len(simbol_list)}] {simbol} trade={m['trade']} "
            f"pnl={m.get('pnl_bersih')} ({m['detik']}s)",
            flush=True,
        )

    def kelompokkan(kunci):
        grup = defaultdict(list)
        for t in semua:
            grup[t[kunci]].append(t)
        keluar = {}
        for k, lst in sorted(grup.items(), key=lambda kv: -len(kv[1])):
            m = metrik(lst)
            if kunci == "strategy_id":
                m["kelompok"] = lst[0]["kelompok"]
                m["kandidat"] = kandidat_strategi.get(k)
                m["menang_arbiter"] = menang_strategi.get(k)
            keluar[str(k)] = m
        return keluar

    alasan = defaultdict(int)
    for t in semua:
        alasan[t["alasan_keluar"]] += 1

    total = metrik(semua)
    total["bar_dievaluasi"] = bar_total
    total["entry_ditolak_biaya"] = tolak_biaya
    total["entry_batal_gap"] = batal_gap
    total["tolak_biaya_per_kode"] = dict(sorted(tolak_kode.items()))

    pair_profit = [s for s, m in per_simbol.items() if (m.get("pnl_bersih") or 0) > 0]
    pair_trade = [s for s, m in per_simbol.items() if m.get("trade", 0) > 0]

    out = {
        "perintah": "backtest",
        "varian": varian_info,
        "konfig": label,
        "entry_tf": entry_tf,
        "context_tfs": list(ctx),
        "maks_bar": maks_bar,
        "saring_biaya": saring,
        "modal_awal_per_simbol": MODAL_AWAL,
        "metodologi": (
            "tiap simbol = akun terpisah modal sama; angka gabungan adalah agregat "
            "statistik lintas simbol untuk mengukur edge, bukan kurva ekuitas satu akun"
        ),
        "simbol_tersedia": len(simbol_list),
        "simbol_diproses": diproses,
        "simbol_gagal": gagal,
        "detik": round(time.time() - t0, 1),
        "total": total,
        "kandidat_per_strategi": dict(sorted(kandidat_strategi.items())),
        "pair_dengan_trade": len(pair_trade),
        "pair_profit": len(pair_profit),
        "breadth_pair_profit": _bulat(
            len(pair_profit) / len(pair_trade) if pair_trade else None
        ),
        "alasan_keluar": dict(sorted(alasan.items())),
        "per_arah": kelompokkan("arah"),
        "per_kelompok": kelompokkan("kelompok"),
        "per_strategi": kelompokkan("strategy_id"),
        "per_simbol": per_simbol,
    }
    tulis(out, f"bt_{_env('LUX_VARIAN', 'asli')}_{label}")
    return 0


# ------------------------------------------------------------- integritas


def _ringkas_verdict(h):
    try:
        d = h.ringkas()
    except Exception as exc:  # noqa: BLE001
        return {"_galat_ringkas": f"{type(exc).__name__}: {exc}"}
    return json.loads(json.dumps(d, sort_keys=True, default=str))


def potong_plane(plane, tfs, i):
    """Plane yang HANYA berisi bar sampai indeks i pada TF entry.

    Bar konteks dipotong berdasarkan timestamp (bukan indeks) karena panjang
    tiap TF berbeda. Jika keputusan berubah dibanding plane penuh, berarti ada
    kebocoran data masa depan (look-ahead).
    """
    entry_tf = tfs[0]
    be = plane.bars(entry_tf)
    ts_batas = be.ts[i]
    peta = {entry_tf: iris(be, 0, i + 1)}
    for tf in tfs[1:]:
        b = plane.bars(tf)
        n = 0
        for k, t in enumerate(b.ts):
            if t <= ts_batas:
                n = k + 1
            else:
                break
        peta[tf] = iris(b, 0, max(n, 1))
    return DataPlane(peta)


def periksa_verdict(v, bars, i):
    """Aturan yang HARUS benar apa pun strateginya. Bukan penilaian kualitas."""
    masalah = []
    arah = str(getattr(v, "arah", ""))
    entry = getattr(v, "entry", None)
    sl = getattr(v, "sl", None)
    tps = list(getattr(v, "tps", []) or [])
    naik = arah.upper().endswith("LONG")

    for nama, x in (("entry", entry), ("sl", sl)):
        if x is None:
            masalah.append(f"{nama} kosong")
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            masalah.append(f"{nama} tidak bisa dibaca: {x!r}")
            continue
        if not math.isfinite(f):
            masalah.append(f"{nama} bukan angka hingga: {x}")
        elif f <= 0:
            masalah.append(f"{nama} <= 0: {x}")
    if masalah:
        return masalah

    entry = float(entry)
    sl = float(sl)
    if naik and sl >= entry:
        masalah.append(f"LONG tetapi sl {sl} >= entry {entry}")
    if (not naik) and sl <= entry:
        masalah.append(f"SHORT tetapi sl {sl} <= entry {entry}")

    if not tps:
        masalah.append("tidak ada target TP")
    total_porsi = 0.0
    for k, t in enumerate(tps):
        h = getattr(t, "harga", t)
        try:
            h = float(h)
        except (TypeError, ValueError):
            masalah.append(f"tp[{k}] harga tidak bisa dibaca: {t!r}")
            continue
        if not math.isfinite(h) or h <= 0:
            masalah.append(f"tp[{k}] harga tidak valid: {h}")
            continue
        if naik and h <= entry:
            masalah.append(f"LONG tetapi tp[{k}] {h} <= entry {entry}")
        if (not naik) and h >= entry:
            masalah.append(f"SHORT tetapi tp[{k}] {h} >= entry {entry}")
        total_porsi += float(getattr(t, "porsi", 0.0) or 0.0)
    if total_porsi > 1.0001:
        masalah.append(f"total porsi TP > 1: {total_porsi}")

    lo = float(bars.low[i])
    hi = float(bars.high[i])
    if lo > 0 and (entry < lo * 0.5 or entry > hi * 1.5):
        masalah.append(f"entry {entry} jauh di luar rentang bar [{lo}, {hi}]")
    return masalah


def cmd_integritas():
    varian_info = terapkan_varian()
    label = _env("LUX_KONFIG", "single_4h")
    if label not in KONFIG:
        print(f"konfigurasi tidak dikenal: {label}")
        return 2
    entry_tf, ctx = KONFIG[label]
    tfs = (entry_tf,) + tuple(ctx)
    maks_bar = _env_int("LUX_MAKS_BAR", 3000)
    saring = _env("LUX_SARING_BIAYA", "1") != "0"
    n_sampel = _env_int("LUX_SAMPEL", 40)

    simbol_list = daftar_simbol(tfs)
    print(
        f"konfig={label} simbol={len(simbol_list)} sampel={n_sampel} "
        f"varian={varian_info.get('varian')}",
        flush=True,
    )

    try:
        reg = registry_bawaan()
        jml_strategi = len(reg.semua()) if hasattr(reg, "semua") else len(list(reg))
    except Exception:  # noqa: BLE001
        jml_strategi = None

    uji = {
        "determinisme": {"diperiksa": 0, "beda": 0, "contoh": []},
        "anti_lookahead": {"diperiksa": 0, "beda": 0, "contoh": []},
        "sanitasi_verdict": {"diperiksa": 0, "pelanggaran": 0, "contoh": []},
    }
    per_simbol = {}
    gagal = {}
    t0 = time.time()

    for simbol in simbol_list:
        try:
            plane = muat_plane(simbol, tfs, maks_bar)
            tfplan = TFPlan(entry_tf=entry_tf, context_tfs=tuple(ctx))
            n_bar = len(plane.bars(entry_tf).ts)
            mulai = min(320, max(0, n_bar - 2))
            if n_bar - mulai < 5:
                gagal[simbol] = f"bar terlalu sedikit: {n_bar}"
                continue
            langkah = max(1, (n_bar - mulai) // max(1, n_sampel))
            indeks = list(range(mulai, n_bar - 1, langkah))[:n_sampel]

            p1 = buat_pipeline(plane, tfplan, saring)
            p2 = buat_pipeline(plane, tfplan, saring)
            entry_terlihat = 0
            for i in indeks:
                h1 = p1.jalankan(i)
                a = _ringkas_verdict(h1)
                b = _ringkas_verdict(p2.jalankan(i))
                uji["determinisme"]["diperiksa"] += 1
                if a != b:
                    uji["determinisme"]["beda"] += 1
                    if len(uji["determinisme"]["contoh"]) < 10:
                        uji["determinisme"]["contoh"].append(
                            {"simbol": simbol, "i": i, "a": a, "b": b}
                        )

                try:
                    pot = potong_plane(plane, tfs, i)
                    c = _ringkas_verdict(buat_pipeline(pot, tfplan, saring).jalankan(i))
                except Exception as exc:  # noqa: BLE001
                    c = {"_galat": f"{type(exc).__name__}: {exc}"}
                uji["anti_lookahead"]["diperiksa"] += 1
                if a != c:
                    uji["anti_lookahead"]["beda"] += 1
                    if len(uji["anti_lookahead"]["contoh"]) < 10:
                        uji["anti_lookahead"]["contoh"].append(
                            {"simbol": simbol, "i": i, "penuh": a, "terpotong": c}
                        )

                v = getattr(h1, "verdict", None)
                if v is None:
                    continue
                entry_terlihat += 1
                uji["sanitasi_verdict"]["diperiksa"] += 1
                for pesan in periksa_verdict(v, plane.bars(entry_tf), i):
                    uji["sanitasi_verdict"]["pelanggaran"] += 1
                    if len(uji["sanitasi_verdict"]["contoh"]) < 20:
                        uji["sanitasi_verdict"]["contoh"].append(
                            {"simbol": simbol, "i": i, "masalah": pesan}
                        )
            per_simbol[simbol] = {
                "bar": n_bar,
                "indeks_diuji": len(indeks),
                "verdict_entry": entry_terlihat,
            }
            print(
                f"{simbol}: bar={n_bar} indeks={len(indeks)} entry={entry_terlihat}",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            gagal[simbol] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()

    out = {
        "perintah": "integritas",
        "varian": varian_info,
        "konfig": label,
        "maks_bar": maks_bar,
        "jumlah_strategi_registry": jml_strategi,
        "detik": round(time.time() - t0, 1),
        "simbol_gagal": gagal,
        "per_simbol": per_simbol,
        "uji": uji,
        "lulus": (
            uji["determinisme"]["beda"] == 0
            and uji["anti_lookahead"]["beda"] == 0
            and uji["sanitasi_verdict"]["pelanggaran"] == 0
            and not gagal
        ),
    }
    tulis(out, f"integritas_{label}")
    return 0


# -------------------------------------------------------------- utilitas


def tulis(out, nama_bawaan):
    nama = _env("LUX_KELUARAN") or os.path.join("reports", "ab95", f"{nama_bawaan}.json")
    jalur = nama if os.path.isabs(nama) else os.path.join(os.getcwd(), nama)
    os.makedirs(os.path.dirname(jalur), exist_ok=True)
    with open(jalur, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    buang = ("per_simbol", "per_strategi", "rinci", "simbol")
    ringkas = {k: v for k, v in out.items() if k not in buang}
    print(json.dumps(ringkas, indent=1, ensure_ascii=False)[:6000], flush=True)
    print(f"keluaran: {jalur}", flush=True)


def main():
    perintah = sys.argv[1] if len(sys.argv) > 1 else "backtest"
    if perintah == "backtest":
        return cmd_backtest()
    if perintah == "integritas":
        return cmd_integritas()
    if perintah == "inventaris":
        return cmd_inventaris()
    print(f"perintah tidak dikenal: {perintah}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
