"""Backtest BTC nyata (dataset kecil) - entry=5m/context=15m (multi-TF) dan
entry=5m single-TF (pembanding), horizon intraday. Tidak mengubah pipeline/arbiter/
strategi apa pun; hanya memuat data nyata dan memanggil lux_modul.backtest.Backtester.

Dilarang mengoptimalkan/mengubah parameter strategi hanya supaya dataset kecil ini
profit (perintah eksplisit operator) - skrip ini murni observasi/pelaporan.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.backtest import Backtester
from lux_modul.data.loader import muat_csv
from lux_modul.data.plane import DataPlane
from lux_modul.kontrak import HORIZON_INTRADAY, TFPlan
from lux_modul.strategi import registry_bawaan

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dataset_masuk", "ekstrak", "data_upload")


def muat_plane(simbol: str, tfs) -> DataPlane:
    peta = {}
    for tf in tfs:
        path = os.path.join(DATA_DIR, f"{simbol}_{tf}.csv")
        peta[tf] = muat_csv(path, tf, simbol)
    return DataPlane(peta)


def per_strategi(trades):
    agg = defaultdict(lambda: {"trade": 0, "menang": 0, "pnl": 0.0})
    for t in trades:
        a = agg[t.strategy_id]
        a["trade"] += 1
        a["menang"] += 1 if t.pnl_bersih > 0 else 0
        a["pnl"] += t.pnl_bersih
    out = {}
    for k, v in sorted(agg.items()):
        out[k] = {
            "trade": v["trade"],
            "menang": v["menang"],
            "win_rate": round(v["menang"] / v["trade"], 4) if v["trade"] else 0.0,
            "pnl": round(v["pnl"], 4),
        }
    return out


def expectancy(trades):
    if not trades:
        return 0.0
    return sum(t.pnl_bersih for t in trades) / len(trades)


def jalankan(label: str, plane: DataPlane, tfplan: TFPlan, balance_awal: float = 1000.0):
    reg = registry_bawaan()
    bt = Backtester(plane, tfplan, horizon=HORIZON_INTRADAY, registry=reg, balance_awal=balance_awal)
    hasil = bt.jalankan()
    ringkas = hasil.ringkas()
    ringkas["label"] = label
    ringkas["expectancy_per_trade"] = round(expectancy(hasil.trades), 6)
    ringkas["per_strategi"] = per_strategi(hasil.trades)
    return ringkas, hasil


def main():
    simbol = "BTC"
    hasil_semua = {}

    # 1) Multi-TF: entry 5m, context 15m
    plane_multi = muat_plane(simbol, ("5m", "15m"))
    tfplan_multi = TFPlan(entry_tf="5m", context_tfs=("15m",))
    ringkas_multi, _ = jalankan("multi_5m_ctx15m", plane_multi, tfplan_multi)
    hasil_semua["multi_5m_ctx15m"] = ringkas_multi

    # 2) Single-TF pembanding: entry 5m saja
    plane_single = muat_plane(simbol, ("5m",))
    tfplan_single = TFPlan(entry_tf="5m")
    ringkas_single, _ = jalankan("single_5m", plane_single, tfplan_single)
    hasil_semua["single_5m"] = ringkas_single

    # 3) Single-TF pembanding kedua: entry 15m saja
    plane_single15 = muat_plane(simbol, ("15m",))
    tfplan_single15 = TFPlan(entry_tf="15m")
    ringkas_single15, _ = jalankan("single_15m", plane_single15, tfplan_single15)
    hasil_semua["single_15m"] = ringkas_single15

    # 4) Multi-TF lebih tinggi: entry 15m, context 1h
    plane_multi2 = muat_plane(simbol, ("15m", "1h"))
    tfplan_multi2 = TFPlan(entry_tf="15m", context_tfs=("1h",))
    ringkas_multi2, _ = jalankan("multi_15m_ctx1h", plane_multi2, tfplan_multi2)
    hasil_semua["multi_15m_ctx1h"] = ringkas_multi2

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports", "backtest_btc_kecil.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(hasil_semua, fh, indent=2, ensure_ascii=False)

    for label, r in hasil_semua.items():
        print(f"=== {label} ===")
        print(json.dumps(r, indent=2, ensure_ascii=False))
        print()


if __name__ == "__main__":
    main()
