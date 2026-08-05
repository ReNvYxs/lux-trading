"""Jalankan SATU konfigurasi backtest BTC dan simpan hasilnya ke reports/bt_<label>.json.

Dipakai agar tiap konfigurasi selesai dalam satu panggilan terminal (proses latar
belakang di sandbox bisa dihentikan antar-perintah).

Pemakaian: python3 scripts/bt_satu.py <label>
Label: multi_5m_ctx15m | single_5m | single_15m | multi_15m_ctx1h

Variabel lingkungan:
  LUX_DATA_DIR      folder CSV (default dataset_masuk/ekstrak/data_upload)
  LUX_SUFIKS        sufiks nama berkas laporan (mis. _potong)
  LUX_SARING_BIAYA  "0" untuk mematikan gerbang biaya (diagnostik saja)
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.backtest import Backtester
from lux_modul.data.loader import muat_csv
from lux_modul.data.plane import DataPlane
from lux_modul.kontrak import HORIZON_INTRADAY, TFPlan
from lux_modul.strategi import registry_bawaan

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get(
    "LUX_DATA_DIR", os.path.join(AKAR, "dataset_masuk", "ekstrak", "data_upload")
)
# Sufiks opsional untuk nama berkas laporan (mis. potongan data).
SUFIKS = os.environ.get("LUX_SUFIKS", "")

KONFIG = {
    "multi_5m_ctx15m": ("5m", ("15m",)),
    "single_5m": ("5m", ()),
    "single_15m": ("15m", ()),
    "multi_15m_ctx1h": ("15m", ("1h",)),
}


def muat_plane(simbol, tfs):
    peta = {}
    for tf in tfs:
        peta[tf] = muat_csv(os.path.join(DATA_DIR, f"{simbol}_{tf}.csv"), tf, simbol)
    return DataPlane(peta)


def per_strategi(trades):
    agg = defaultdict(
        lambda: {"trade": 0, "menang": 0, "pnl": 0.0, "pnl_kotor": 0.0, "biaya": 0.0}
    )
    for t in trades:
        a = agg[t.strategy_id]
        a["trade"] += 1
        a["menang"] += 1 if t.pnl_bersih > 0 else 0
        a["pnl"] += t.pnl_bersih
        a["pnl_kotor"] += t.pnl_kotor
        a["biaya"] += t.biaya
    out = {}
    for k, v in sorted(agg.items(), key=lambda kv: -kv[1]["trade"]):
        out[k] = {
            "trade": v["trade"],
            "menang": v["menang"],
            "win_rate": round(v["menang"] / v["trade"], 4) if v["trade"] else 0.0,
            "pnl": round(v["pnl"], 4),
            "pnl_kotor": round(v["pnl_kotor"], 4),
            "biaya": round(v["biaya"], 4),
            "edge_kotor_per_trade": round(v["pnl_kotor"] / v["trade"], 4) if v["trade"] else 0.0,
        }
    return out


def main():
    label = sys.argv[1]
    entry_tf, ctx = KONFIG[label]
    tfs = (entry_tf,) + tuple(ctx)
    t0 = time.time()
    plane = muat_plane("BTC", tfs)
    bt = Backtester(
        plane,
        TFPlan(entry_tf=entry_tf, context_tfs=tuple(ctx)),
        horizon=HORIZON_INTRADAY,
        registry=registry_bawaan(),
        balance_awal=1000.0,
        saring_biaya=os.environ.get("LUX_SARING_BIAYA", "1") != "0",
    )
    hasil = bt.jalankan()
    ringkas = hasil.ringkas()
    ringkas["label"] = label
    ringkas["entry_tf"] = entry_tf
    ringkas["context_tfs"] = list(ctx)
    ringkas["bar_total_entry_tf"] = len(plane.bars(entry_tf))
    ringkas["detik"] = round(time.time() - t0, 1)
    trades = hasil.trades
    ringkas["expectancy_per_trade"] = round(
        sum(t.pnl_bersih for t in trades) / len(trades), 6
    ) if trades else 0.0
    ringkas["total_pnl_kotor"] = round(sum(t.pnl_kotor for t in trades), 4)
    ringkas["saring_biaya"] = bt.saring_biaya
    ringkas["per_strategi"] = per_strategi(trades)
    ringkas["data_dir"] = DATA_DIR
    out = os.path.join(AKAR, "reports", f"bt_{label}{SUFIKS}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(ringkas, fh, indent=2, ensure_ascii=False)
    print(json.dumps(ringkas, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
