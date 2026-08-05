#!/usr/bin/env python3
"""Uji bracket order lengkap: buka posisi MARKET -> pasang SL -> pasang TP -> bersihkan.

Ini membuktikan bahwa -4120 terjadi HANYA saat tidak ada posisi, bukan bug
modul atau serialisasi. Setelah posisi ada, STOP_MARKET dan TAKE_PROFIT_MARKET
harus diterima bursa.

ALUR:
  1. Baca harga pasar BTCUSDT.
  2. Buka posisi LONG kecil via MARKET (qty minimum).
  3. Tunggu 3 detik supaya posisi terdaftar di sistem.
  4. Pasang STOP_MARKET SL (25% di bawah entry).
  5. Pasang TAKE_PROFIT_MARKET TP (25% di atas entry).
  6. Verifikasi kedua order diterima.
  7. Batalkan semua order, tutup posisi via MARKET SELL.

CATATAN: MARKET ORDER dipakai di sini HANYA untuk keperluan tes, bukan produksi.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

AKAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AKAR))

from lux_modul.eksekusi.binance_client import BinanceAPIError, BinanceFuturesClient
from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
from lux_modul.eksekusi.spesifikasi import SpesifikasiKontrak

KELUARAN = AKAR / "reports" / "testnet" / "hasil_bracket_penuh.json"
SIMBOL = "BTCUSDT"
JAUH = 0.25


def _spek(client):
    info = client.exchange_info(SIMBOL)
    for s in info.get("symbols", []):
        if s.get("symbol") == SIMBOL:
            return SpesifikasiKontrak.dari_exchange_info(s)
    raise RuntimeError("BTCUSDT tidak ada")


def main() -> int:
    hasil = {
        "waktu_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "langkah": [],
    }

    kred = muat_kredensial(MODE_TESTNET)
    client = BinanceFuturesClient(kred)
    client.sinkron_waktu()
    spek = _spek(client)

    posisi_dibuka = False

    try:
        # -- LANGKAH 1: buka posisi LONG minimum via MARKET --
        pasar = client.harga_sekarang(SIMBOL)
        qty = spek.bulat_qty(max(spek.min_qty, spek.min_notional / pasar) * 1.1, "atas")
        print(f"[1] Buka LONG MARKET qty={qty} harga_pasar={pasar}")
        try:
            resp_entry = client.kirim_order({
                "symbol": SIMBOL,
                "side": "BUY",
                "type": "MARKET",
                "quantity": qty,
            })
            posisi_dibuka = True
            hasil["langkah"].append({
                "nama": "entry_market",
                "ok": True,
                "orderId": resp_entry.get("orderId"),
                "status": resp_entry.get("status"),
                "avgPrice": resp_entry.get("avgPrice"),
            })
            print(f"   Entry OK orderId={resp_entry.get('orderId')} avgPrice={resp_entry.get('avgPrice')}")
        except BinanceAPIError as e:
            hasil["langkah"].append({"nama": "entry_market", "ok": False, "kode": e.kode, "pesan": str(e)})
            print(f"   Entry GAGAL kode={e.kode} {e}")
            raise

        # tunggu posisi terdaftar di sistem Binance
        time.sleep(3)

        # verifikasi posisi
        raw_pos = client._permintaan("GET", "/fapi/v2/positionRisk", {"symbol": SIMBOL}, signed=True)
        pos_aktif = [p for p in raw_pos if abs(float(p.get("positionAmt", 0) or 0)) > 0]
        hasil["posisi_setelah_entry"] = [
            {"symbol": p["symbol"], "positionAmt": p["positionAmt"], "entryPrice": p.get("entryPrice")}
            for p in pos_aktif
        ]
        print(f"[2] Posisi terdeteksi: {len(pos_aktif)}")

        entry_price = float(resp_entry.get("avgPrice") or pasar)
        stop_sl = spek.bulat_harga(entry_price * (1.0 - JAUH), "bawah")
        stop_tp = spek.bulat_harga(entry_price * (1.0 + JAUH), "atas")
        hasil["harga"] = {"entry": entry_price, "sl": stop_sl, "tp": stop_tp}
        print(f"   entry={entry_price}  SL={stop_sl}  TP={stop_tp}")

        # -- LANGKAH 3: STOP_MARKET SL ----------------------------------------
        print("[3] Pasang STOP_MARKET SL closePosition=true MARK_PRICE")
        try:
            r = client.kirim_order({
                "symbol": SIMBOL, "side": "SELL", "type": "STOP_MARKET",
                "stopPrice": stop_sl, "closePosition": True, "workingType": "MARK_PRICE",
            })
            hasil["langkah"].append({
                "nama": "SL_stop_market", "ok": True,
                "orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type"),
            })
            print(f"   SL OK orderId={r.get('orderId')}")
        except BinanceAPIError as e:
            hasil["langkah"].append({"nama": "SL_stop_market", "ok": False, "kode": e.kode, "pesan": str(e)})
            print(f"   SL GAGAL kode={e.kode} {e}")

        # -- LANGKAH 4: TAKE_PROFIT_MARKET TP ----------------------------------
        print("[4] Pasang TAKE_PROFIT_MARKET TP closePosition=true MARK_PRICE")
        try:
            r = client.kirim_order({
                "symbol": SIMBOL, "side": "SELL", "type": "TAKE_PROFIT_MARKET",
                "stopPrice": stop_tp, "closePosition": True, "workingType": "MARK_PRICE",
            })
            hasil["langkah"].append({
                "nama": "TP_take_profit_market", "ok": True,
                "orderId": r.get("orderId"), "status": r.get("status"), "type": r.get("type"),
            })
            print(f"   TP OK orderId={r.get('orderId')}")
        except BinanceAPIError as e:
            hasil["langkah"].append({"nama": "TP_take_profit_market", "ok": False, "kode": e.kode, "pesan": str(e)})
            print(f"   TP GAGAL kode={e.kode} {e}")

    finally:
        # -- BERSIHKAN: batalkan order, tutup posisi --------------------------
        print("[5] Bersihkan...")
        try:
            client.batalkan_semua_order(SIMBOL)
            print("   Order dibatalkan.")
        except Exception as e:  # noqa: BLE001
            print(f"   Gagal batalkan order: {e!r}")

        if posisi_dibuka:
            try:
                raw_pos = client._permintaan("GET", "/fapi/v2/positionRisk", {"symbol": SIMBOL}, signed=True)
                pos_sisa = [p for p in raw_pos if abs(float(p.get("positionAmt", 0) or 0)) > 0]
                if pos_sisa:
                    qty_sisa = abs(float(pos_sisa[0]["positionAmt"]))
                    qty_tutup = spek.bulat_qty(qty_sisa, "bawah")
                    tutup = client.kirim_order({
                        "symbol": SIMBOL, "side": "SELL", "type": "MARKET",
                        "quantity": qty_tutup, "reduceOnly": True,
                    })
                    hasil["tutup_posisi"] = {"ok": True, "orderId": tutup.get("orderId")}
                    print(f"   Posisi ditutup orderId={tutup.get('orderId')}")
                else:
                    hasil["tutup_posisi"] = {"ok": True, "catatan": "posisi sudah tidak ada"}
                    print("   Posisi sudah tidak ada.")
            except Exception as e:  # noqa: BLE001
                hasil["tutup_posisi"] = {"ok": False, "galat": repr(e)}
                print(f"   Gagal tutup posisi: {e!r}")

    diterima = [l["nama"] for l in hasil.get("langkah", []) if l.get("ok")]
    gagal = [l["nama"] for l in hasil.get("langkah", []) if not l.get("ok")]
    hasil["ringkas"] = {"diterima": diterima, "gagal": gagal}
    print(f"\nRINGKAS: DITERIMA={diterima} GAGAL={gagal}")

    KELUARAN.parent.mkdir(parents=True, exist_ok=True)
    KELUARAN.write_text(json.dumps(hasil, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if not gagal else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
