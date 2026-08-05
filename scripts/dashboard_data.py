"""Kumpulkan seluruh data dashboard menjadi satu berkas dashboard/data.json.

Sumber data (semuanya nyata, tidak ada angka karangan):
  reports/btp_*.json         hasil backtest PORTOFOLIO (termasuk sinyal terlewat)
  reports/bt_*.json          hasil backtest satu simbol
  reports/audit_dataset.json audit dataset
  reports/ci_terakhir.json   status uji
  registry_bawaan()          daftar strategi + ambang + horizon
  eksekusi/*                 kebijakan order, model biaya, aturan risiko

Pemakaian: python3 scripts/dashboard_data.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi import biaya as mbiaya
from lux_modul.eksekusi import risiko as mrisiko
from lux_modul.eksekusi.ice_breaker import (
    AMBANG_NOTIONAL_ICEBREAKER,
    JEDA_DETIK,
    NOTIONAL_PER_SLICE,
    RASIO_VISIBLE,
    SLICE_MAKS,
)
from lux_modul.eksekusi.order import KebijakanOrder
from lux_modul.portofolio import MAKS_POSISI_BERSAMAAN
from lux_modul.strategi import registry_bawaan

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORTS = os.path.join(AKAR, "reports")
KELUARAN = os.path.join(AKAR, "dashboard", "data.json")


def muat(nama):
    p = os.path.join(REPORTS, nama)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def daftar_strategi():
    reg = registry_bawaan()
    out = []
    for s in reg.semua():
        out.append(
            {
                "id": s.id,
                "kelompok": s.kelompok,
                "ambang": s.ambang,
                "horizon": list(getattr(s, "horizon_didukung", ()) or []),
                "warmup": getattr(s, "warmup", None),
                "butuh_konteks": bool(getattr(s, "multi_tf", False))
                or bool(getattr(s, "konteks_dibutuhkan", ())),
                "sumber": getattr(s, "sumber", ""),
            }
        )
    return sorted(out, key=lambda d: (d["kelompok"], d["id"]))


def kumpulkan_portofolio():
    hasil = {}
    for path in sorted(glob.glob(os.path.join(REPORTS, "btp_*.json"))):
        label = os.path.basename(path)[4:-5]
        with open(path, encoding="utf-8") as fh:
            hasil[label] = json.load(fh)
    return hasil


def main():
    k = KebijakanOrder()
    data = {
        "_dibuat": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kebijakan_order": {
            **k.ringkas(),
            "entry": "LIMIT + timeInForce=GTX (post-only)",
            "tp": "LIMIT + GTX + reduceOnly",
            "sl": "STOP_MARKET + closePosition (satu-satunya pengecualian market)",
            "market_order": "DIHARAMKAN",
        },
        "model_biaya": {
            "fee_bps_maker": mbiaya.FEE_BPS_MAKER,
            "fee_bps_taker": mbiaya.FEE_BPS_TAKER,
            "slippage_bps_maker": mbiaya.SLIPPAGE_MAKER_BPS,
            "slippage_bps_sl": mbiaya.SLIPPAGE_BPS,
            "rasio_biaya_maks": mbiaya.RASIO_BIAYA_MAKS,
            "kelipatan_tp1_min": mbiaya.KELIPATAN_TP1_MIN,
            "fill_keluar_maks": mbiaya.FILL_KELUAR_MAKS,
        },
        "risiko": {
            "risk_lantai_usd": mrisiko.RISK_LANTAI_USD,
            "risk_pct_min": mrisiko.RISK_PCT_MIN,
            "risk_pct_maks": mrisiko.RISK_PCT_MAKS,
            "ambang_modal_kecil": mrisiko.AMBANG_MODAL_KECIL,
            "eksponen_kecil": mrisiko.EKSPONEN_KECIL,
            "tier": [list(t) for t in mrisiko.TIER],
            "taper_mulai": mrisiko.TAPER_MULAI,
            "taper_lantai": mrisiko.TAPER_LANTAI,
        },
        "ice_breaker": {
            "ambang_notional": AMBANG_NOTIONAL_ICEBREAKER,
            "slice_maks": SLICE_MAKS,
            "notional_per_slice": NOTIONAL_PER_SLICE,
            "rasio_visible": RASIO_VISIBLE,
            "jeda_detik": JEDA_DETIK,
        },
        "portofolio": {"maks_posisi_bersamaan": MAKS_POSISI_BERSAMAAN},
        "strategi": daftar_strategi(),
        "backtest_portofolio": kumpulkan_portofolio(),
        "backtest_satu_simbol": muat("backtest_btc_kecil_v2.json"),
        "audit_dataset": muat("audit_dataset.json"),
        "ci": muat("ci_terakhir.json"),
    }
    os.makedirs(os.path.dirname(KELUARAN), exist_ok=True)
    with open(KELUARAN, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    print(f"ditulis {KELUARAN} ({os.path.getsize(KELUARAN)} bytes)")
    print(f"strategi: {len(data['strategi'])}, konfigurasi portofolio: {list(data['backtest_portofolio'])}")


if __name__ == "__main__":
    main()
