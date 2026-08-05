#!/usr/bin/env python3
"""Isolasi penyebab galat -4120 pada order kondisional (SL/TP) di Binance Testnet.

Hipotesis awal saya - bool Python diserialisasi jadi "True" huruf besar - TERBUKTI
SALAH: setelah serialisasi diperbaiki, STOP_MARKET tetap ditolak -4120, sementara
entry LIMIT post-only (termasuk pada 1000PEPEUSDT dengan tick 1e-07) LULUS.

Skrip ini mencoba matriks varian payload untuk menemukan bentuk mana yang
diterima bursa, tanpa menebak-nebak dari dokumentasi:

  A. STOP_MARKET + closePosition=true
  B. STOP_MARKET + quantity + reduceOnly=true
  C. STOP_MARKET + quantity (tanpa flag apa pun)
  D. STOP (stop-limit) + quantity + price + reduceOnly
  E. TAKE_PROFIT_MARKET + closePosition=true
  F. TAKE_PROFIT + quantity + price + reduceOnly
  G. STOP_MARKET + closePosition=true + workingType=CONTRACT_PRICE
  H. STOP_MARKET tanpa workingType sama sekali
  I. STOP_MARKET + priceProtect=true
  J. TRAILING_STOP_MARKET + callbackRate

Semua stopPrice ditempatkan 25% dari harga pasar sehingga tidak akan tertrigger,
dan seluruh order dibatalkan lagi di akhir.
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
from lux_modul.eksekusi.spesifikasi import SpesifikasiKontrak  # noqa: E402

KELUARAN = AKAR / "reports" / "testnet" / "hasil_kondisional.json"
JAUH = 0.25


def _spek(client, simbol):
    info = client.exchange_info(simbol)
    for s in info.get("symbols", []):
        if s.get("symbol") == simbol:
            return SpesifikasiKontrak.dari_exchange_info(s)
    raise RuntimeError(f"simbol tidak ada: {simbol}")


def main() -> int:
    simbol = os.environ.get("LUX_UJI_SIMBOL", "BTCUSDT")
    hasil = {"waktu_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "varian": []}

    kred = muat_kredensial(MODE_TESTNET)
    client = BinanceFuturesClient(kred)
    client.sinkron_waktu()

    spek = _spek(client, simbol)
    pasar = client.harga_sekarang(simbol)
    stop_bawah = spek.bulat_harga(pasar * (1.0 - JAUH), "bawah")
    stop_atas = spek.bulat_harga(pasar * (1.0 + JAUH), "atas")
    qty = spek.bulat_qty(max(spek.min_qty, spek.min_notional / pasar) * 1.5, "atas")
    hasil["konteks"] = {
        "simbol": simbol,
        "harga_pasar": pasar,
        "stop_bawah": stop_bawah,
        "stop_atas": stop_atas,
        "qty": qty,
    }

    # posisi terbuka? beberapa varian hanya sah bila ada posisi
    try:
        pos = [p for p in client.posisi(simbol) if float(p.get("positionAmt", 0) or 0) != 0]
        hasil["posisi_terbuka_simbol_ini"] = len(pos)
    except Exception as e:  # noqa: BLE001
        hasil["posisi_terbuka_simbol_ini"] = f"gagal: {e!r}"

    varian = [
        ("A_stop_market_closeposition", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "closePosition": True, "workingType": "MARK_PRICE"}),
        ("B_stop_market_qty_reduceonly", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "quantity": qty, "reduceOnly": True}),
        ("C_stop_market_qty_polos", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "quantity": qty}),
        ("D_stop_limit_qty_reduceonly", {
            "symbol": simbol, "side": "SELL", "type": "STOP",
            "stopPrice": stop_bawah, "price": stop_bawah, "quantity": qty,
            "timeInForce": "GTC", "reduceOnly": True}),
        ("E_take_profit_market_closeposition", {
            "symbol": simbol, "side": "SELL", "type": "TAKE_PROFIT_MARKET",
            "stopPrice": stop_atas, "closePosition": True, "workingType": "MARK_PRICE"}),
        ("F_take_profit_limit_qty_reduceonly", {
            "symbol": simbol, "side": "SELL", "type": "TAKE_PROFIT",
            "stopPrice": stop_atas, "price": stop_atas, "quantity": qty,
            "timeInForce": "GTC", "reduceOnly": True}),
        ("G_stop_market_contract_price", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "closePosition": True,
            "workingType": "CONTRACT_PRICE"}),
        ("H_stop_market_tanpa_workingtype", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "closePosition": True}),
        ("I_stop_market_priceprotect", {
            "symbol": simbol, "side": "SELL", "type": "STOP_MARKET",
            "stopPrice": stop_bawah, "closePosition": True,
            "workingType": "MARK_PRICE", "priceProtect": True}),
        ("J_trailing_stop_market", {
            "symbol": simbol, "side": "SELL", "type": "TRAILING_STOP_MARKET",
            "quantity": qty, "callbackRate": 1.0, "reduceOnly": True}),
    ]

    for nama, payload in varian:
        catatan = {"varian": nama, "payload": dict(payload)}
        try:
            resp = client.kirim_order(payload)
            catatan.update(
                diterima=True,
                orderId=resp.get("orderId"),
                status=resp.get("status"),
                tipe=resp.get("type"),
            )
            print(f"[DITERIMA] {nama} -> orderId={resp.get('orderId')}")
        except BinanceAPIError as e:
            catatan.update(diterima=False, kode=e.kode, pesan=str(e))
            print(f"[DITOLAK ] {nama} -> kode={e.kode} {e}")
        except Exception as e:  # noqa: BLE001
            catatan.update(diterima=False, kode=None, pesan=repr(e))
            print(f"[GALAT   ] {nama} -> {e!r}")
        hasil["varian"].append(catatan)

    try:
        client.batalkan_semua_order(simbol)
        hasil["pembersihan"] = "ok"
    except Exception as e:  # noqa: BLE001
        hasil["pembersihan"] = repr(e)

    diterima = [v["varian"] for v in hasil["varian"] if v.get("diterima")]
    hasil["ringkas"] = {
        "diterima": diterima,
        "jumlah_diterima": len(diterima),
        "jumlah_ditolak": len(hasil["varian"]) - len(diterima),
    }

    KELUARAN.parent.mkdir(parents=True, exist_ok=True)
    KELUARAN.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"VARIAN DITERIMA: {diterima or 'TIDAK ADA'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
