#!/usr/bin/env python3
"""Diagnosa akar galat -4120: batasan akun, batasan simbol, atau batasan endpoint?

Matriks 10 varian payload (scripts/uji_kondisional.py) SEMUANYA ditolak -4120,
termasuk varian tanpa closePosition, tanpa reduceOnly, dan tanpa workingType.
Artinya penyebabnya bukan bentuk payload. Kandidat penyebab yang tersisa:

  1. `orderTypes` simbol pada exchangeInfo memang tidak memuat tipe kondisional.
  2. Akun berada pada mode Portfolio Margin -> order kondisional harus lewat
     endpoint conditional/algo, bukan /fapi/v1/order.
  3. Izin API key dibatasi.

Skrip ini hanya MEMBACA konfigurasi (kecuali satu percobaan POST ke endpoint
conditional) lalu menuliskan fakta apa adanya.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR))

from lux_modul.eksekusi.binance_client import (  # noqa: E402
    BinanceAPIError,
    BinanceFuturesClient,
)
from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial  # noqa: E402

KELUARAN = AKAR / "reports" / "testnet" / "diagnosa_kondisional.json"


def _coba(hasil, nama, fungsi):
    try:
        hasil[nama] = {"ok": True, "data": fungsi()}
        print(f"[OK   ] {nama}")
    except BinanceAPIError as e:
        hasil[nama] = {"ok": False, "kode": e.kode, "pesan": str(e)}
        print(f"[GAGAL] {nama} kode={e.kode} {e}")
    except Exception as e:  # noqa: BLE001
        hasil[nama] = {"ok": False, "kode": None, "pesan": repr(e)}
        print(f"[GALAT] {nama} {e!r}")


def main() -> int:
    simbol = os.environ.get("LUX_UJI_SIMBOL", "BTCUSDT")
    hasil = {
        "waktu_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "simbol": simbol,
    }

    kred = muat_kredensial(MODE_TESTNET)
    client = BinanceFuturesClient(kred)
    client.sinkron_waktu()
    hasil["base_url"] = kred.base_url

    # 1. tipe order yang diakui bursa untuk simbol ini
    def _tipe_order():
        info = client.exchange_info(simbol)
        for s in info.get("symbols", []):
            if s.get("symbol") == simbol:
                return {
                    "orderTypes": s.get("orderTypes"),
                    "timeInForce": s.get("timeInForce"),
                    "contractType": s.get("contractType"),
                    "status": s.get("status"),
                }
        return None

    _coba(hasil, "tipe_order_simbol", _tipe_order)

    # 2. konfigurasi akun
    def _akun():
        data = client._permintaan("GET", "/fapi/v2/account", {}, signed=True)
        return {
            k: data.get(k)
            for k in (
                "feeTier",
                "canTrade",
                "canDeposit",
                "canWithdraw",
                "multiAssetsMargin",
                "tradeGroupId",
                "totalWalletBalance",
                "availableBalance",
            )
        }

    _coba(hasil, "akun", _akun)

    _coba(
        hasil,
        "mode_posisi",
        lambda: client._permintaan("GET", "/fapi/v1/positionSide/dual", {}, signed=True),
    )
    _coba(
        hasil,
        "status_trading_api",
        lambda: client._permintaan("GET", "/fapi/v1/apiTradingStatus", {}, signed=True),
    )
    _coba(
        hasil,
        "mode_multi_aset",
        lambda: client._permintaan("GET", "/fapi/v1/multiAssetsMargin", {}, signed=True),
    )

    # 3. apakah endpoint conditional/algo tersedia di base_url ini?
    _coba(
        hasil,
        "daftar_conditional_terbuka",
        lambda: client._permintaan(
            "GET", "/fapi/v1/conditional/openOrders", {"symbol": simbol}, signed=True
        ),
    )
    _coba(
        hasil,
        "daftar_algo_terbuka",
        lambda: client._permintaan("GET", "/sapi/v1/algo/futures/openOrders", {}, signed=True),
    )

    # 4. percobaan POST ke endpoint conditional (stop jauh dari pasar, langsung dibatalkan)
    def _post_conditional():
        pasar = client.harga_sekarang(simbol)
        stop = round(pasar * 0.75, 1)
        payload = {
            "symbol": simbol,
            "side": "SELL",
            "strategyType": "STOP_MARKET",
            "stopPrice": stop,
            "closePosition": True,
            "workingType": "MARK_PRICE",
        }
        resp = client._permintaan("POST", "/fapi/v1/conditional/order", payload, signed=True)
        return resp

    _coba(hasil, "post_conditional_order", _post_conditional)

    try:
        client.batalkan_semua_order(simbol)
        hasil["pembersihan"] = "ok"
    except Exception as e:  # noqa: BLE001
        hasil["pembersihan"] = repr(e)

    KELUARAN.parent.mkdir(parents=True, exist_ok=True)
    KELUARAN.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(hasil.get("tipe_order_simbol", {}), indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
