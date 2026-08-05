#!/usr/bin/env python3
"""Smoke test TESTNET NYATA - memverifikasi perbaikan galat -1111, -4120, -2019.

Dijalankan di GitHub Actions karena sandbox pengembangan tidak punya akses
internet keluar. Skrip ini TIDAK pernah dijalankan pada mode live: base URL
dikunci oleh kredensial.muat_kredensial("testnet").

Apa yang diuji (urut):
1. konektivitas + sinkron waktu server
2. exchange info -> spesifikasi kontrak nyata (tick/step/precision)
3. saldo & posisi -> snapshot governor dari data akun asli
4. order entry LIMIT post-only JAUH dari pasar pada pair harga besar (BTCUSDT)
5. order entry LIMIT post-only pada pair HARGA SANGAT KECIL -> pemicu -1111
6. STOP_MARKET closePosition=true -> pemicu -4120
7. TAKE_PROFIT_MARKET closePosition=true -> verifikasi order keluar TP
8. pembersihan: batalkan seluruh open order pada simbol yang dipakai

Semua order sengaja ditempatkan jauh dari harga pasar (>=20%) supaya TIDAK
terisi. Skrip membatalkannya kembali di akhir, apa pun hasilnya.
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
from lux_modul.eksekusi.order import (  # noqa: E402
    KebijakanOrder,
    payload_entry,
    payload_sl,
)
from lux_modul.eksekusi.spesifikasi import SpesifikasiKontrak  # noqa: E402
from lux_modul.governor import (  # noqa: E402
    GovernorPortofolio,
    KandidatEntry,
    KebijakanPortofolio,
    snapshot_dari_akun,
)

KELUARAN = AKAR / "reports" / "testnet" / "hasil_smoke.json"
JAUH_DARI_PASAR = 0.25  # 25% - dijamin tidak terisi, sekaligus lolos post-only


class Hasil:
    def __init__(self) -> None:
        self.langkah = []
        self.mulai = time.time()

    def catat(self, nama, lulus, detail=None, galat=None):
        self.langkah.append(
            {
                "langkah": nama,
                "lulus": bool(lulus),
                "detail": detail or {},
                "galat": galat,
            }
        )
        tanda = "LULUS" if lulus else "GAGAL"
        print(f"[{tanda}] {nama}" + (f" :: {galat}" if galat else ""))
        return lulus

    def ringkas(self):
        lulus = sum(1 for l in self.langkah if l["lulus"])
        return {
            "waktu_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "durasi_detik": round(time.time() - self.mulai, 2),
            "total": len(self.langkah),
            "lulus": lulus,
            "gagal": len(self.langkah) - lulus,
            "langkah": self.langkah,
        }


def _spek(client, simbol):
    info = client.exchange_info(simbol)
    for s in info.get("symbols", []):
        if s.get("symbol") == simbol:
            return SpesifikasiKontrak.dari_exchange_info(s)
    raise RuntimeError(f"simbol tidak ditemukan di exchangeInfo: {simbol}")


def _uji_order_entry(h, client, simbol, label):
    """Kirim LIMIT post-only jauh di bawah pasar. Pemicu klasik galat -1111."""
    try:
        spek = _spek(client, simbol)
        harga_pasar = client.harga_sekarang(simbol)
        harga = spek.bulat_harga(harga_pasar * (1.0 - JAUH_DARI_PASAR), "bawah")
        qty_min = max(spek.min_qty, spek.min_notional / max(harga, 1e-12))
        qty = spek.bulat_qty(qty_min * 1.2, "atas")
        keb = KebijakanOrder(tick_size=spek.tick_size)
        payload = payload_entry(simbol, "LONG", qty, harga, kebijakan=keb)
        resp = client.kirim_order(payload)
        return h.catat(
            f"entry_post_only_{label}",
            True,
            {
                "simbol": simbol,
                "harga_pasar": harga_pasar,
                "harga_order": harga,
                "qty": qty,
                "tick_size": spek.tick_size,
                "step_size": spek.step_size,
                "orderId": resp.get("orderId"),
                "status": resp.get("status"),
                "type": resp.get("type"),
                "timeInForce": resp.get("timeInForce"),
            },
        )
    except BinanceAPIError as e:
        return h.catat(
            f"entry_post_only_{label}", False, {"simbol": simbol, "kode": e.kode}, str(e)
        )
    except Exception as e:  # noqa: BLE001
        return h.catat(f"entry_post_only_{label}", False, {"simbol": simbol}, repr(e))


def _uji_stop_market(h, client, simbol):
    """STOP_MARKET + closePosition=true. Inilah yang dulu ditolak dengan -4120."""
    try:
        spek = _spek(client, simbol)
        harga_pasar = client.harga_sekarang(simbol)
        stop = spek.bulat_harga(harga_pasar * (1.0 - JAUH_DARI_PASAR), "bawah")
        keb = KebijakanOrder(tick_size=spek.tick_size)
        payload = payload_sl(simbol, "LONG", stop, tutup_posisi=True, kebijakan=keb)
        resp = client.kirim_order(payload)
        return h.catat(
            "stop_market_close_position",
            True,
            {
                "simbol": simbol,
                "stopPrice": stop,
                "orderId": resp.get("orderId"),
                "type": resp.get("type"),
                "closePosition": resp.get("closePosition"),
                "workingType": resp.get("workingType"),
            },
        )
    except BinanceAPIError as e:
        return h.catat("stop_market_close_position", False, {"kode": e.kode}, str(e))
    except Exception as e:  # noqa: BLE001
        return h.catat("stop_market_close_position", False, {}, repr(e))


def _uji_take_profit_market(h, client, simbol):
    """TAKE_PROFIT_MARKET + closePosition=true - kaki TP dari bracket.

    Payload dibangun manual di sini karena order.py masih melarang tipe ini
    (warisan aturan 'haram market order'). Uji ini membuktikan bursa menerimanya
    sebagai order KELUAR sebelum larangan itu dilonggarkan di modul.
    """
    try:
        spek = _spek(client, simbol)
        harga_pasar = client.harga_sekarang(simbol)
        tp = spek.bulat_harga(harga_pasar * (1.0 + JAUH_DARI_PASAR), "atas")
        payload = {
            "symbol": simbol,
            "side": "SELL",
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": tp,
            "closePosition": True,
            "workingType": "MARK_PRICE",
        }
        resp = client.kirim_order(payload)
        return h.catat(
            "take_profit_market_close_position",
            True,
            {
                "simbol": simbol,
                "stopPrice": tp,
                "orderId": resp.get("orderId"),
                "type": resp.get("type"),
                "closePosition": resp.get("closePosition"),
            },
        )
    except BinanceAPIError as e:
        return h.catat(
            "take_profit_market_close_position", False, {"kode": e.kode}, str(e)
        )
    except Exception as e:  # noqa: BLE001
        return h.catat("take_profit_market_close_position", False, {}, repr(e))


def main() -> int:
    h = Hasil()
    simbol_besar = os.environ.get("LUX_UJI_SIMBOL", "BTCUSDT")
    simbol_kecil = os.environ.get("LUX_UJI_SIMBOL_KECIL", "1000PEPEUSDT")
    dipakai = []

    try:
        kred = muat_kredensial(MODE_TESTNET)
    except Exception as e:  # noqa: BLE001
        h.catat("muat_kredensial", False, {}, repr(e))
        _tulis(h)
        return 1
    h.catat("muat_kredensial", True, kred.ringkas())

    client = BinanceFuturesClient(kred)

    try:
        offset = client.sinkron_waktu()
        h.catat("sinkron_waktu", True, {"offset_ms": offset})
    except Exception as e:  # noqa: BLE001
        h.catat("sinkron_waktu", False, {}, repr(e))
        _tulis(h)
        return 1

    # spesifikasi kontrak nyata
    for simbol in (simbol_besar, simbol_kecil):
        try:
            s = _spek(client, simbol)
            h.catat(f"spesifikasi_{simbol}", True, s.ringkas())
        except Exception as e:  # noqa: BLE001
            h.catat(f"spesifikasi_{simbol}", False, {}, repr(e))

    # snapshot akun -> governor
    try:
        saldo = client.saldo()
        posisi = client.posisi()
        snap = snapshot_dari_akun(saldo, posisi)
        gov = GovernorPortofolio(KebijakanPortofolio())
        gov.mulai_siklus(snap)
        for i, sim in enumerate(["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT"]):
            gov.antre(
                KandidatEntry(
                    simbol=sim,
                    arah="LONG",
                    entry_tf="15m",
                    horizon="intraday",
                    skor=90 - i,
                    margin_dibutuhkan=max(1.0, snap.equity * 0.05),
                )
            )
        keputusan = gov.putuskan()
        ringkas = GovernorPortofolio.ringkas_keputusan(keputusan)
        h.catat(
            "governor_dengan_saldo_nyata",
            ringkas["diterima"] <= 4,
            {
                "equity": snap.equity,
                "margin_tersedia": snap.margin_tersedia,
                "posisi_terbuka": snap.jumlah_posisi,
                **ringkas,
            },
        )
    except Exception as e:  # noqa: BLE001
        h.catat("governor_dengan_saldo_nyata", False, {}, repr(e))

    # order nyata
    if _uji_order_entry(h, client, simbol_besar, "harga_besar"):
        dipakai.append(simbol_besar)
    if _uji_order_entry(h, client, simbol_kecil, "harga_kecil"):
        dipakai.append(simbol_kecil)
    if _uji_stop_market(h, client, simbol_besar):
        dipakai.append(simbol_besar)
    if _uji_take_profit_market(h, client, simbol_besar):
        dipakai.append(simbol_besar)

    # pembersihan WAJIB - jangan tinggalkan order menggantung di akun operator
    for simbol in sorted(set(dipakai + [simbol_besar, simbol_kecil])):
        try:
            client.batalkan_semua_order(simbol)
            h.catat(f"pembersihan_{simbol}", True, {})
        except Exception as e:  # noqa: BLE001
            h.catat(f"pembersihan_{simbol}", False, {}, repr(e))

    _tulis(h)
    return 0 if all(l["lulus"] for l in h.langkah) else 2


def _tulis(h: Hasil) -> None:
    KELUARAN.parent.mkdir(parents=True, exist_ok=True)
    ringkas = h.ringkas()
    KELUARAN.write_text(json.dumps(ringkas, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 60)
    print(f"RINGKASAN SMOKE TESTNET: {ringkas['lulus']} lulus, {ringkas['gagal']} gagal")
    print(f"ditulis ke {KELUARAN.relative_to(AKAR)}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
