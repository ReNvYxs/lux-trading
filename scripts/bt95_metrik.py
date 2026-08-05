"""Backtest 95 pair dengan METRIK LENGKAP (bukan sekadar profit/loss).

Mengumpulkan seluruh trade level lalu menghitung: jumlah trade, win rate,
profit factor (kotor & bersih), expectancy USD dan R, rata-rata R menang/kalah,
payoff ratio, max drawdown, konsistensi (paruh & kuartil waktu, breadth pair
profit), performa per pair, per strategi, per kelompok, per arah, dan distribusi
alasan keluar. Semua angka bersih sudah termasuk fee + slippage.

Skrip ini MENGUKUR saja; tidak ada parameter strategi yang disetel di sini.

Pemakaian:
    LUX_KONFIG=single_15m LUX_MAKS_BAR=6000 python scripts/bt95_metrik.py

Env: LUX_KONFIG, LUX_DATA_DIR, LUX_SIMBOL, LUX_MAKS_SIMBOL, LUX_MAKS_BAR,
     LUX_BATAS_DETIK, LUX_SARING_BIAYA, LUX_KELUARAN

Metodologi: tiap simbol = akun terpisah dengan modal awal sama. Angka gabungan
adalah agregat statistik lintas simbol untuk mengukur edge, BUKAN kurva ekuitas
satu akun yang menradingkan 95 pair sekaligus.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.backtest import Backtester
from lux_modul.data.loader import muat_csv
from lux_modul.data.plane import DataPlane
from lux_modul.kontrak import Bars, HORIZON_INTRADAY, TFPlan
from lux_modul.strategi import registry_bawaan

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get(
    "LUX_DATA_DIR", os.path.join(AKAR, "dataset_masuk", "ekstrak", "data_upload")
)

KONFIG = {
    "multi_5m_ctx15m": ("5m", ("15m",)),
    "single_5m": ("5m", ()),
    "single_15m": ("15m", ()),
    "multi_15m_ctx1h": ("15m", ("1h",)),
    "single_1h": ("1h", ()),
    "multi_1h_ctx4h": ("1h", ("4h",)),
}

MODAL_AWAL = 1000.0


def _int_env(nama, bawaan=0):
    try:
        return int(os.environ.get(nama, str(bawaan)) or bawaan)
    except ValueError:
        return bawaan


def daftar_simbol(tfs):
    manual = [s.strip() for s in os.environ.get("LUX_SIMBOL", "").split(",") if s.strip()]
    if manual:
        kandidat = manual
    else:
        kandidat = sorted(
            {n.rsplit("_", 1)[0] for n in os.listdir(DATA_DIR) if n.endswith(".csv") and "_" in n}
        )
    lengkap = [
        s
        for s in kandidat
        if all(os.path.exists(os.path.join(DATA_DIR, f"{s}_{tf}.csv")) for tf in tfs)
    ]
    maks = _int_env("LUX_MAKS_SIMBOL", 0)
    return lengkap[:maks] if maks > 0 else lengkap


def _potong(bars, maks_bar):
    if maks_bar <= 0 or len(bars) <= maks_bar:
        return bars
    i = len(bars) - maks_bar
    return Bars(
        tf=bars.tf,
        simbol=bars.simbol,
        ts=bars.ts[i:],
        open=bars.open[i:],
        high=bars.high[i:],
        low=bars.low[i:],
        close=bars.close[i:],
        volume=bars.volume[i:],
    )


def muat_plane(simbol, tfs, maks_bar):
    peta = {}
    for tf in tfs:
        b = muat_csv(os.path.join(DATA_DIR, f"{simbol}_{tf}.csv"), tf, simbol)
        peta[tf] = _potong(b, maks_bar) if tf == tfs[0] else b
    return DataPlane(peta)


def _pf(menang_total, kalah_total):
    if kalah_total <= 0:
        return None if menang_total <= 0 else float("inf")
    return menang_total / kalah_total


def _bulat(x, n=4):
    if x is None:
        return None
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    return round(x, n)


def metrik(trades):
    n = len(trades)
    if n == 0:
        return {"trade": 0}
    urut = sorted(trades, key=lambda t: t["ts_entry"])
    pnl = [t["pnl"] for t in urut]
    r = [t["r"] for t in urut]
    menang = [p for p in pnl if p > 0]
    kalah = [p for p in pnl if p <= 0]
    r_menang = [x for x, p in zip(r, pnl) if p > 0]
    r_kalah = [x for x, p in zip(r, pnl) if p <= 0]
    total_menang = sum(menang)
    total_kalah = abs(sum(kalah))
    kotor_menang = sum(t["pnl_kotor"] for t in urut if t["pnl_kotor"] > 0)
    kotor_kalah = abs(sum(t["pnl_kotor"] for t in urut if t["pnl_kotor"] <= 0))
    ekuitas = 0.0
    puncak = 0.0
    dd_maks = 0.0
    for p in pnl:
        ekuitas += p
        puncak = max(puncak, ekuitas)
        dd_maks = max(dd_maks, puncak - ekuitas)
    rata_menang = (sum(r_menang) / len(r_menang)) if r_menang else 0.0
    rata_kalah = (sum(r_kalah) / len(r_kalah)) if r_kalah else 0.0
    return {
        "trade": n,
        "menang": len(menang),
        "kalah": len(kalah),
        "win_rate": _bulat(len(menang) / n),
        "pnl_bersih": _bulat(sum(pnl)),
        "pnl_kotor": _bulat(sum(t["pnl_kotor"] for t in urut)),
        "biaya": _bulat(sum(t["biaya"] for t in urut)),
        "profit_factor_bersih": _bulat(_pf(total_menang, total_kalah)),
        "profit_factor_kotor": _bulat(_pf(kotor_menang, kotor_kalah)),
        "expectancy_usd": _bulat(sum(pnl) / n),
        "expectancy_r": _bulat(sum(r) / n),
        "r_rata_menang": _bulat(rata_menang),
        "r_rata_kalah": _bulat(rata_kalah),
        "payoff_ratio_r": _bulat(abs(rata_menang / rata_kalah) if rata_kalah else None),
        "max_drawdown_usd": _bulat(dd_maks),
        "edge_kotor_per_trade": _bulat(sum(t["pnl_kotor"] for t in urut) / n),
        "biaya_per_trade": _bulat(sum(t["biaya"] for t in urut) / n),
        "sampel_cukup": n >= 200,
    }


def belah_waktu(trades, bagian=2):
    urut = sorted(trades, key=lambda t: t["ts_entry"])
    n = len(urut)
    if n < bagian:
        return []
    ukuran = n // bagian
    hasil = []
    for i in range(bagian):
        awal = i * ukuran
        akhir = n if i == bagian - 1 else (i + 1) * ukuran
        potong = urut[awal:akhir]
        m = metrik(potong)
        m["ts_awal"] = potong[0]["ts_entry"]
        m["ts_akhir"] = potong[-1]["ts_entry"]
        hasil.append(m)
    return hasil


def main():
    label = os.environ.get("LUX_KONFIG", "single_15m")
    if label not in KONFIG:
        print(f"konfigurasi tidak dikenal: {label}")
        return 2
    entry_tf, ctx = KONFIG[label]
    tfs = (entry_tf,) + tuple(ctx)
    maks_bar = _int_env("LUX_MAKS_BAR", 0)
    batas_detik = _int_env("LUX_BATAS_DETIK", 0)
    saring = os.environ.get("LUX_SARING_BIAYA", "1") != "0"

    simbol_list = daftar_simbol(tfs)
    print(f"konfig={label} entry_tf={entry_tf} ctx={ctx} simbol={len(simbol_list)}", flush=True)

    t0 = time.time()
    semua_trade = []
    per_simbol = {}
    gagal = {}
    tolak_kode = defaultdict(int)
    bar_total = 0
    tolak_biaya_total = 0
    batal_gap_total = 0
    diproses = 0

    for simbol in simbol_list:
        if batas_detik and (time.time() - t0) > batas_detik:
            print(f"batas waktu {batas_detik}s tercapai, berhenti di {diproses} simbol", flush=True)
            break
        ts = time.time()
        try:
            plane = muat_plane(simbol, tfs, maks_bar)
            bt = Backtester(
                plane,
                TFPlan(entry_tf=entry_tf, context_tfs=tuple(ctx)),
                horizon=HORIZON_INTRADAY,
                registry=registry_bawaan(),
                balance_awal=MODAL_AWAL,
                saring_biaya=saring,
            )
            hasil = bt.jalankan()
        except Exception as exc:
            gagal[simbol] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            continue
        diproses += 1
        r = hasil.ringkas()
        bar_total += r["bar_dievaluasi"]
        tolak_biaya_total += r["entry_ditolak_biaya"]
        batal_gap_total += r["entry_batal_gap"]
        for k, v in r["tolak_biaya_per_kode"].items():
            tolak_kode[k] += v
        trades_simbol = []
        for t in hasil.trades:
            rec = {
                "simbol": simbol,
                "strategy_id": t.strategy_id,
                "kelompok": t.kelompok,
                "arah": t.arah,
                "ts_entry": int(t.ts_entry),
                "ts_keluar": int(t.ts_keluar),
                "alasan_keluar": t.alasan_keluar,
                "pnl": float(t.pnl_bersih),
                "pnl_kotor": float(t.pnl_kotor),
                "biaya": float(t.biaya),
                "r": float(t.r_multiple),
            }
            trades_simbol.append(rec)
            semua_trade.append(rec)
        m = metrik(trades_simbol)
        m["balance_akhir"] = r["balance_akhir"]
        m["max_drawdown_frac_akun"] = r["max_drawdown"]
        m["bar"] = r["bar_dievaluasi"]
        m["detik"] = round(time.time() - ts, 1)
        per_simbol[simbol] = m
        print(
            f"[{diproses}/{len(simbol_list)}] {simbol} trade={m['trade']} "
            f"pnl={m.get('pnl_bersih')} pf={m.get('profit_factor_bersih')} ({m['detik']}s)",
            flush=True,
        )

    per_strategi = {}
    grup_strategi = defaultdict(list)
    for t in semua_trade:
        grup_strategi[t["strategy_id"]].append(t)
    for sid, lst in sorted(grup_strategi.items(), key=lambda kv: -len(kv[1])):
        m = metrik(lst)
        m["simbol_terlibat"] = len({t["simbol"] for t in lst})
        m["kelompok"] = lst[0]["kelompok"]
        m["paruh"] = belah_waktu(lst, 2)
        per_strategi[sid] = m

    per_kelompok = {}
    grup_kel = defaultdict(list)
    for t in semua_trade:
        grup_kel[t["kelompok"]].append(t)
    for kel, lst in sorted(grup_kel.items(), key=lambda kv: -len(kv[1])):
        per_kelompok[kel] = metrik(lst)

    per_arah = {}
    for arah in sorted({t["arah"] for t in semua_trade}):
        per_arah[str(arah)] = metrik([t for t in semua_trade if t["arah"] == arah])

    alasan = defaultdict(int)
    for t in semua_trade:
        alasan[t["alasan_keluar"]] += 1

    pair_profit = [s for s, m in per_simbol.items() if (m.get("pnl_bersih") or 0) > 0]
    pair_ada_trade = [s for s, m in per_simbol.items() if m.get("trade", 0) > 0]

    total = metrik(semua_trade)
    total["bar_dievaluasi"] = bar_total
    total["entry_ditolak_biaya"] = tolak_biaya_total
    total["entry_batal_gap"] = batal_gap_total
    total["tolak_biaya_per_kode"] = dict(sorted(tolak_kode.items()))

    konsistensi = {
        "paruh": belah_waktu(semua_trade, 2),
        "kuartil": belah_waktu(semua_trade, 4),
        "pair_dengan_trade": len(pair_ada_trade),
        "pair_profit": len(pair_profit),
        "breadth_pair_profit": _bulat(
            len(pair_profit) / len(pair_ada_trade) if pair_ada_trade else None
        ),
        "strategi_expectancy_r_positif": sorted(
            [
                s
                for s, m in per_strategi.items()
                if (m.get("expectancy_r") or 0) > 0 and m.get("trade", 0) >= 100
            ]
        ),
    }

    out = {
        "konfig": label,
        "entry_tf": entry_tf,
        "context_tfs": list(ctx),
        "modal_awal_per_simbol": MODAL_AWAL,
        "metodologi": (
            "tiap simbol = akun terpisah modal sama; angka gabungan adalah agregat "
            "statistik lintas simbol untuk mengukur edge, bukan kurva ekuitas satu akun"
        ),
        "saring_biaya": saring,
        "maks_bar": maks_bar,
        "simbol_tersedia": len(simbol_list),
        "simbol_diproses": diproses,
        "simbol_gagal": gagal,
        "detik": round(time.time() - t0, 1),
        "total": total,
        "konsistensi": konsistensi,
        "alasan_keluar": dict(sorted(alasan.items())),
        "per_arah": per_arah,
        "per_kelompok": per_kelompok,
        "per_strategi": per_strategi,
        "per_simbol": per_simbol,
    }

    nama = os.environ.get("LUX_KELUARAN", os.path.join("reports", f"bt95m_{label}.json"))
    jalur = nama if os.path.isabs(nama) else os.path.join(AKAR, nama)
    os.makedirs(os.path.dirname(jalur), exist_ok=True)
    with open(jalur, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    ringkas = {k: v for k, v in out.items() if k not in ("per_simbol", "per_strategi")}
    print(json.dumps(ringkas, indent=1, ensure_ascii=False), flush=True)
    print(f"keluaran: {jalur}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
