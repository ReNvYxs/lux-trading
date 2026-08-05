#!/usr/bin/env python3
"""Uji STOP_MARKET dan TAKE_PROFIT_MARKET pada posisi yang benar-benar ada.

Screenshot user membuktikan TP/SL bisa dipasang lewat UI testnet.
Diagnosa sebelumnya mengirim order kondisional saat TIDAK ADA posisi
BTCUSDT (posisi_terbuka_simbol_ini: 0), sehingga -4120 muncul karena
begitulah Binance menolak closePosition/reduceOnly tanpa posisi.

Skrip ini:
1. Membaca semua posisi terbuka di akun.
2. Memilih satu posisi (pilih BTCUSDT bila ada, atau yang pertama).
3. Mengirim STOP_MARKET dan TAKE_PROFIT_MARKET di sisi berlawanan,
   25% jauh dari harga pasar sehingga tidak akan tertrigger.
4. Mencatat hasilnya dan membatalkan order uji.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR))

from lux_modul.eksekusi.binance_client import (
    BinanceAPIError,
    BinanceFuturesClient,
)
from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
from lux_modul.eksekusi.spesifikasi import SpesifikasiKontrak

KELUARAN = AKAR / "reports" / "testnet" / "hasil_sl_tp_posisi.json"
JAUH = 0.25


def _spek(client, simbol):
    info = client.exchange_info(simbol)
    for s in info.get("symbols", []):
        if s.get("symbol") == simbol:
            return SpesifikasiKontrak.dari_exchange_info(s)
    raise RuntimeError(f"simbol tidak ada: {simbol}")


def _coba(hasil, nama, fungsi):
    try:
        r = fungsi()
        hasil[nama] = {"ok": True, "data": r}
        print(f"[OK   ] {nama}")
    except BinanceAPIError as e:
        hasil[nama] = {"ok": False, "kode": e.kode, "pesan": str(e)}
        print(f"[GAGAL] {nama} kode={e.kode} {e}")
    except Exception as e:  # noqa: BLE001
        hasil[nama] = {"ok": False, "kode": None, "pesan": repr(e)}
        print(f"[GALAT] {nama} {e!r}")


def main() -> int:
    hasil = {"waktu_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "langkah": []}

    kred = muat_kredensial(MODE_TESTNET)
    client = BinanceFuturesClient(kred)
    client.sinkron_waktu()

    # baca semua posisi terbuka
    semua_pos = []
    try:
        raw = client._permintaan("GET", "/fapi/v2/positionRisk", {}, signed=True)
        semua_pos = [
            p for p in raw
            if abs(float(p.get("positionAmt", 0) or 0)) > 0
        ]
    except Exception as e:  # noqa: BLE001
        hasil["galat_baca_posisi"] = repr(e)

    hasil["posisi_terbuka"] = [
        {"symbol": p["symbol"], "positionAmt": p["positionAmt"], "entryPrice": p["entryPrice"]}
        for p in semua_pos
    ]
    print(f"Posisi terbuka: {len(semua_pos)}")
    for p in semua_pos:
        print(f"  {p['symbol']} amt={p['positionAmt']} entry={p.get('entryPrice')}")

    if not semua_pos:
        hasil["kesimpulan"] = "tidak ada posisi terbuka, tidak bisa uji closePosition=true"
        KELUARAN.parent.mkdir(parents=True, exist_ok=True)
        KELUARAN.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Tidak ada posisi terbuka.")
        return 0

    # pilih BTCUSDT bila ada, atau posisi pertama
    pos = next((p for p in semua_pos if p["symbol"] == "BTCUSDT"), semua_pos[0])
    simbol = pos["symbol"]
    qty_pos = abs(float(pos.get("positionAmt", 0)))
    arah_pos = "LONG" if float(pos.get("positionAmt", 0)) > 0 else "SHORT"
    sisi_keluar = "SELL" if arah_pos == "LONG" else "BUY"

    hasil["posisi_dipilih"] = {"simbol": simbol, "arah": arah_pos, "qty": qty_pos}
    print(f"Posisi dipilih: {simbol} {arah_pos} qty={qty_pos}")

    spek = _spek(client, simbol)
    pasar = client.harga_sekarang(simbol)

    if arah_pos == "LONG":
        stop_sl = spek.bulat_harga(pasar * (1.0 - JAUH), "bawah")
        stop_tp = spek.bulat_harga(pasar * (1.0 + JAUH), "atas")
    else:
        stop_sl = spek.bulat_harga(pasar * (1.0 + JAUH), "atas")
        stop_tp = spek.bulat_harga(pasar * (1.0 - JAUH), "bawah")

    hasil["konteks"] = {
        "simbol": simbol,
        "pasar": pasar,
        "arah_pos": arah_pos,
        "sisi_keluar": sisi_keluar,
        "stop_sl": stop_sl,
        "stop_tp": stop_tp,
        "qty_pos": qty_pos,
    }
    print(f"  harga pasar: {pasar}  stop_sl: {stop_sl}  stop_tp: {stop_tp}")

    # Varian A: STOP_MARKET closePosition=true MARK_PRICE
    def _sl_closeposition():
        r = client.kirim_order({
            "symbol": simbol, "side": sisi_keluar, "type": "STOP_MARKET",
            "stopPrice": stop_sl, "closePosition": True, "workingType": "MARK_PRICE",
        })
        return {"orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type")}

    _coba(hasil, "SL_A_closePosition_markprice", _sl_closeposition)

    # Varian B: STOP_MARKET qty reduceOnly MARK_PRICE
    def _sl_reduceonly():
        qty = spek.bulat_qty(qty_pos, "bawah")
        r = client.kirim_order({
            "symbol": simbol, "side": sisi_keluar, "type": "STOP_MARKET",
            "stopPrice": stop_sl, "quantity": qty, "reduceOnly": True,
            "workingType": "MARK_PRICE",
        })
        return {"orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type")}

    _coba(hasil, "SL_B_qty_reduceonly_markprice", _sl_reduceonly)

    # Varian C: STOP_MARKET closePosition CONTRACT_PRICE
    def _sl_contract():
        r = client.kirim_order({
            "symbol": simbol, "side": sisi_keluar, "type": "STOP_MARKET",
            "stopPrice": stop_sl, "closePosition": True, "workingType": "CONTRACT_PRICE",
        })
        return {"orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type")}

    _coba(hasil, "SL_C_closePosition_contractprice", _sl_contract)

    # Varian D: TAKE_PROFIT_MARKET closePosition MARK_PRICE
    def _tp_closeposition():
        r = client.kirim_order({
            "symbol": simbol, "side": sisi_keluar, "type": "TAKE_PROFIT_MARKET",
            "stopPrice": stop_tp, "closePosition": True, "workingType": "MARK_PRICE",
        })
        return {"orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type")}

    _coba(hasil, "TP_D_closePosition_markprice", _tp_closeposition)

    # Varian E: TAKE_PROFIT limit qty reduceOnly
    def _tp_limit():
        qty = spek.bulat_qty(qty_pos, "bawah")
        r = client.kirim_order({
            "symbol": simbol, "side": sisi_keluar, "type": "TAKE_PROFIT",
            "stopPrice": stop_tp, "price": stop_tp, "quantity": qty,
            "timeInForce": "GTC", "reduceOnly": True,
        })
        return {"orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type")}

    _coba(hasil, "TP_E_limit_qty_reduceonly", _tp_limit)

    # bersihkan semua order uji
    try:
        client.batalkan_semua_order(simbol)
        hasil["pembersihan"] = "ok"
        print("Order dibersihkan.")
    except Exception as e:  # noqa: BLE001
        hasil["pembersihan"] = repr(e)
        print(f"Pembersihan gagal: {e!r}")

    diterima = [k for k, v in hasil.items() if isinstance(v, dict) and v.get("ok")]
    hasil["ringkas"] = {
        "diterima": diterima,
        "jumlah_diterima": len(diterima),
    }
    print(f"\nDITERIMA: {diterima or 'TIDAK ADA'}")

    KELUARAN.parent.mkdir(parents=True, exist_ok=True)
    KELUARAN.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
