"""Backtest LINTAS BANYAK SIMBOL untuk satu konfigurasi TF.

Tujuan: mengumpulkan sampel yang cukup besar per strategi (target n >= 200 trade)
sehingga edge KOTOR (sebelum biaya) tiap strategi bisa diukur dengan bermakna.
Dipakai untuk dataset besar `95-pair-dataset` di GitHub Actions.

Pemakaian:
    python scripts/bt_banyak.py            # konfigurasi dari env LUX_KONFIG

Variabel lingkungan:
    LUX_KONFIG      label konfigurasi (default single_15m); lihat KONFIG di bawah
    LUX_DATA_DIR    folder CSV (default dataset_masuk/ekstrak/data_upload)
    LUX_SIMBOL      daftar simbol dipisah koma; kosong = semua simbol yang ada
    LUX_MAKS_SIMBOL batas jumlah simbol (0 = tanpa batas)
    LUX_MAKS_BAR    hanya pakai N bar TERAKHIR pada TF entry (0 = semua)
    LUX_BATAS_DETIK berhenti menerima simbol baru setelah N detik (0 = tanpa batas)
    LUX_SARING_BIAYA "0" untuk mematikan gerbang biaya (diagnostik saja)
    LUX_KELUARAN    nama berkas keluaran (default reports/bt_banyak_<konfig>.json)

Catatan: tiap simbol dijalankan sebagai akun TERPISAH dengan modal awal yang sama.
Ini bukan simulasi portofolio; tujuannya mengukur edge per strategi, bukan mengklaim
hasil gabungan sebagai kurva ekuitas nyata.
"""
from __future__ import annotations

import json
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


def _int_env(nama: str, bawaan: int = 0) -> int:
    try:
        return int(os.environ.get(nama, str(bawaan)) or bawaan)
    except ValueError:
        return bawaan


def daftar_simbol(tfs) -> list:
    """Simbol yang punya CSV lengkap untuk SEMUA tf yang dibutuhkan."""
    manual = [s.strip() for s in os.environ.get("LUX_SIMBOL", "").split(",") if s.strip()]
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
    maks = _int_env("LUX_MAKS_SIMBOL", 0)
    return lengkap[:maks] if maks > 0 else lengkap


def _potong(bars: Bars, maks_bar: int) -> Bars:
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


def muat_plane(simbol: str, tfs, maks_bar: int) -> DataPlane:
    peta = {}
    for tf in tfs:
        b = muat_csv(os.path.join(DATA_DIR, f"{simbol}_{tf}.csv"), tf, simbol)
        peta[tf] = _potong(b, maks_bar) if tf == tfs[0] else b
    return DataPlane(peta)


def main() -> int:
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
    agg = defaultdict(
        lambda: {
            "trade": 0,
            "menang": 0,
            "pnl": 0.0,
            "pnl_kotor": 0.0,
            "biaya": 0.0,
            "r_total": 0.0,
            "simbol": set(),
        }
    )
    per_simbol = {}
    gagal = {}
    tolak_kode = defaultdict(int)
    total = {
        "trade": 0,
        "menang": 0,
        "pnl": 0.0,
        "pnl_kotor": 0.0,
        "biaya": 0.0,
        "bar_dievaluasi": 0,
        "entry_ditolak_biaya": 0,
        "entry_batal_gap": 0,
    }
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
        except Exception as exc:  # simbol rusak tidak boleh menjatuhkan seluruh run
            gagal[simbol] = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            continue
        diproses += 1
        r = hasil.ringkas()
        per_simbol[simbol] = {
            "trade": r["jumlah_trade"],
            "win_rate": r["win_rate"],
            "pnl": r["total_pnl"],
            "pnl_kotor": round(sum(t.pnl_kotor for t in hasil.trades), 4),
            "biaya": r["total_biaya"],
            "balance_akhir": r["balance_akhir"],
            "max_drawdown": r["max_drawdown"],
            "bar": r["bar_dievaluasi"],
            "detik": round(time.time() - ts, 1),
        }
        total["bar_dievaluasi"] += r["bar_dievaluasi"]
        total["entry_ditolak_biaya"] += r["entry_ditolak_biaya"]
        total["entry_batal_gap"] += r["entry_batal_gap"]
        for k, v in r["tolak_biaya_per_kode"].items():
            tolak_kode[k] += v
        for t in hasil.trades:
            a = agg[t.strategy_id]
            a["trade"] += 1
            a["menang"] += 1 if t.pnl_bersih > 0 else 0
            a["pnl"] += t.pnl_bersih
            a["pnl_kotor"] += t.pnl_kotor
            a["biaya"] += t.biaya
            a["r_total"] += t.r_multiple
            a["simbol"].add(simbol)
            total["trade"] += 1
            total["menang"] += 1 if t.pnl_bersih > 0 else 0
            total["pnl"] += t.pnl_bersih
            total["pnl_kotor"] += t.pnl_kotor
            total["biaya"] += t.biaya
        print(
            f"[{diproses}/{len(simbol_list)}] {simbol} trade={r['jumlah_trade']} "
            f"pnl={r['total_pnl']} kotor={per_simbol[simbol]['pnl_kotor']} "
            f"({per_simbol[simbol]['detik']}s)",
            flush=True,
        )

    per_strategi = {}
    for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["trade"]):
        n = v["trade"]
        per_strategi[k] = {
            "trade": n,
            "simbol": len(v["simbol"]),
            "win_rate": round(v["menang"] / n, 4) if n else 0.0,
            "pnl": round(v["pnl"], 4),
            "pnl_kotor": round(v["pnl_kotor"], 4),
            "biaya": round(v["biaya"], 4),
            "edge_kotor_per_trade": round(v["pnl_kotor"] / n, 4) if n else 0.0,
            "edge_bersih_per_trade": round(v["pnl"] / n, 4) if n else 0.0,
            "r_rata": round(v["r_total"] / n, 4) if n else 0.0,
            "sampel_cukup": n >= 200,
        }

    out = {
        "konfig": label,
        "entry_tf": entry_tf,
        "context_tfs": list(ctx),
        "modal_awal_per_simbol": MODAL_AWAL,
        "saring_biaya": saring,
        "maks_bar": maks_bar,
        "simbol_tersedia": len(simbol_list),
        "simbol_diproses": diproses,
        "simbol_gagal": gagal,
        "detik": round(time.time() - t0, 1),
        "total": {
            "trade": total["trade"],
            "win_rate": round(total["menang"] / total["trade"], 4) if total["trade"] else 0.0,
            "pnl": round(total["pnl"], 4),
            "pnl_kotor": round(total["pnl_kotor"], 4),
            "biaya": round(total["biaya"], 4),
            "edge_kotor_per_trade": round(total["pnl_kotor"] / total["trade"], 4)
            if total["trade"]
            else 0.0,
            "bar_dievaluasi": total["bar_dievaluasi"],
            "entry_ditolak_biaya": total["entry_ditolak_biaya"],
            "entry_batal_gap": total["entry_batal_gap"],
            "tolak_biaya_per_kode": dict(sorted(tolak_kode.items())),
        },
        "per_strategi": per_strategi,
        "per_simbol": per_simbol,
    }
    nama = os.environ.get("LUX_KELUARAN", os.path.join("reports", f"bt_banyak_{label}.json"))
    jalur = nama if os.path.isabs(nama) else os.path.join(AKAR, nama)
    os.makedirs(os.path.dirname(jalur), exist_ok=True)
    with open(jalur, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    ringkas = dict(out)
    ringkas.pop("per_simbol", None)
    print(json.dumps(ringkas, indent=1, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
