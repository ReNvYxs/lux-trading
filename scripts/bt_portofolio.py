"""Backtest PORTOFOLIO dataset kecil: banyak simbol, satu saldo, maks 4 posisi bersamaan.

Menyimpan hasil ke reports/btp_<label>.json, termasuk daftar SINYAL TERLEWAT
(sinyal valid yang tidak dieksekusi karena slot penuh) untuk dashboard.

Pemakaian: python3 scripts/bt_portofolio.py <label> [simbol,dipisah,koma]
Label: single_5m | multi_5m_ctx15m | single_15m | multi_15m_ctx1h

Variabel lingkungan:
  LUX_DATA_DIR   folder CSV (default dataset_masuk/ekstrak/data_upload)
  LUX_MAKS_BAR   batas bar entry-TF per simbol (default 0 = semua)
  LUX_MAKS_POS   kapasitas posisi bersamaan (default 4)
  LUX_SUFIKS     sufiks nama berkas laporan
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.backtest_portofolio import BacktesterPortofolio
from lux_modul.data.loader import muat_csv
from lux_modul.data.plane import DataPlane
from lux_modul.kontrak import HORIZON_INTRADAY, TFPlan
from lux_modul.strategi import registry_bawaan

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get(
    "LUX_DATA_DIR", os.path.join(AKAR, "dataset_masuk", "ekstrak", "data_upload")
)
SUFIKS = os.environ.get("LUX_SUFIKS", "")
MAKS_BAR = int(os.environ.get("LUX_MAKS_BAR", "0"))
MAKS_POS = int(os.environ.get("LUX_MAKS_POS", "4"))

KONFIG = {
    "multi_5m_ctx15m": ("5m", ("15m",)),
    "single_5m": ("5m", ()),
    "single_15m": ("15m", ()),
    "multi_15m_ctx1h": ("15m", ("1h",)),
}

# Dataset kecil: 6 simbol paling likuid dari audit dataset.
SIMBOL_DEFAULT = ("BTC", "ETH", "SOL", "XRP", "ADA", "DOGE")


def muat_plane(simbol, tfs):
    peta = {}
    for tf in tfs:
        peta[tf] = muat_csv(os.path.join(DATA_DIR, f"{simbol}_{tf}.csv"), tf, simbol)
    return DataPlane(peta)


def main():
    label = sys.argv[1]
    simbol = tuple(sys.argv[2].split(",")) if len(sys.argv) > 2 else SIMBOL_DEFAULT
    entry_tf, ctx = KONFIG[label]
    tfs = (entry_tf,) + tuple(ctx)

    t0 = time.time()
    planes = {}
    for s in simbol:
        try:
            planes[s] = muat_plane(s, tfs)
        except Exception as exc:  # data tidak lengkap -> lewati, catat
            print(f"lewati {s}: {exc}", flush=True)
    if not planes:
        raise SystemExit("tidak ada simbol yang bisa dimuat")

    bt = BacktesterPortofolio(
        planes,
        TFPlan(entry_tf=entry_tf, context_tfs=tuple(ctx)),
        horizon=HORIZON_INTRADAY,
        registry=registry_bawaan(),
        balance_awal=1000.0,
        maks_posisi=MAKS_POS,
    )
    hasil = bt.jalankan(maks_bar=MAKS_BAR or None)
    ringkas = hasil.ringkas()
    ringkas["label"] = label
    ringkas["entry_tf"] = entry_tf
    ringkas["context_tfs"] = list(ctx)
    ringkas["maks_bar"] = MAKS_BAR
    ringkas["detik"] = round(time.time() - t0, 1)
    ringkas["data_dir"] = DATA_DIR
    ringkas["model_biaya"] = {
        "entry": "maker post-only (GTX)",
        "tp": "maker post-only (GTX)",
        "sl": "taker STOP_MARKET + slippage",
    }
    # Simpan maksimum 300 contoh sinyal terlewat agar berkas tetap ringan.
    ringkas["contoh_sinyal_terlewat"] = list(hasil.terlewat[:300])

    out = os.path.join(AKAR, "reports", f"btp_{label}{SUFIKS}.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(ringkas, fh, indent=2, ensure_ascii=False)
    ringkas.pop("contoh_sinyal_terlewat", None)
    print(json.dumps(ringkas, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
