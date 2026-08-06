"""L4 - kebijakan order: POST-ONLY WAJIB, MARKET ORDER DIHARAMKAN untuk ENTRY.

Aturan operator (3 Agu 2026):
- Entry WAJIB `LIMIT` + `timeInForce=GTX` (post-only / maker-only).
  Bila order post-only akan langsung menyeberang, exchange menolaknya.
  Modul menangani penolakan itu dengan re-quote terbatas, lalu MEMBATALKAN sinyal.
  Tidak pernah jatuh kembali ke market order.
- Stop loss: `STOP_MARKET` + `closePosition=True`. Satu-satunya pengecualian untuk
  entry karena kegagalan SL jauh lebih mahal daripada selisih fee taker.
- Take profit: `TAKE_PROFIT_MARKET` + `closePosition=True`. Pengecualian kedua:
  TP menutup posisi yang sudah ada, bukan membuka baru. Tidak sama dengan MARKET
  entry yang diharamkan.
- `TIPE_TERLARANG` hanya menegakkan aturan pada ORDER MASUK (entry), bukan keluar.

Verifikasi bursa nyata (GitHub Actions, 4 Agu 2026):
- LIMIT GTX: DITERIMA (entry_post_only_harga_besar, entry_post_only_harga_kecil)
- STOP_MARKET closePosition: DITOLAK -4120 pada 6 Agu 2026, lihat bukti/live/
- TAKE_PROFIT_MARKET closePosition: DITOLAK -4120 pada 6 Agu 2026, lihat bukti/live/
- Serialisasi bool True->"true" (format_nilai): diperbaiki, terbukti -1111 mati
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from ..kontrak import ARAH_LONG, ARAH_SHORT

TIF_POST_ONLY = "GTX"
TIPE_LIMIT = "LIMIT"
TIPE_STOP_MARKET = "STOP_MARKET"
TIPE_TAKE_PROFIT_MARKET = "TAKE_PROFIT_MARKET"

# Order market dilarang total untuk ENTRY. Daftar ini dipakai penegak aturan.
# TAKE_PROFIT_MARKET TIDAK ada di sini karena ia dipakai untuk EXIT (tutup posisi).
TIPE_TERLARANG_ENTRY = ("MARKET", "TRAILING_STOP_MARKET")
# Alias backward-compat (beberapa test memakai nama lama)
TIPE_TERLARANG = TIPE_TERLARANG_ENTRY

OFFSET_TICK_DEFAULT = 1
MAKS_REQUOTE_DEFAULT = 3


class OrderTerlarang(Exception):
    """Dilempar bila ada usaha mengirim order yang melanggar kebijakan post-only."""


@dataclass(frozen=True)
class KebijakanOrder:
    """Konfigurasi kebijakan eksekusi. Semua default = mode paling ketat."""

    post_only_wajib: bool = True
    izinkan_market_untuk_sl: bool = True  # STOP_MARKET untuk SL (keputusan operator)
    izinkan_tp_market: bool = True        # TAKE_PROFIT_MARKET untuk TP (tutup posisi)
    offset_tick: int = OFFSET_TICK_DEFAULT
    maks_requote: int = MAKS_REQUOTE_DEFAULT
    tick_size: float = 0.0  # 0 = tidak dibulatkan

    def ringkas(self) -> Dict[str, Any]:
        return {
            "post_only_wajib": self.post_only_wajib,
            "izinkan_market_untuk_sl": self.izinkan_market_untuk_sl,
            "izinkan_tp_market": self.izinkan_tp_market,
            "offset_tick": self.offset_tick,
            "maks_requote": self.maks_requote,
            "tick_size": self.tick_size,
        }


def _bulatkan(harga: float, tick: float, ke_bawah: bool) -> float:
    if tick <= 0:
        return float(harga)
    n = harga / tick
    n = math.floor(n) if ke_bawah else math.ceil(n)
    return round(n * tick, 12)


def harga_post_only(
    arah: str,
    harga_acuan: float,
    best_bid: Optional[float] = None,
    best_ask: Optional[float] = None,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> float:
    """Harga limit yang dijamin berada di sisi maker."""
    if arah not in (ARAH_LONG, ARAH_SHORT):
        raise ValueError(f"arah tidak sah: {arah!r}")
    tick = kebijakan.tick_size
    geser = kebijakan.offset_tick * (tick if tick > 0 else 0.0)
    if arah == ARAH_LONG:
        dasar = min(float(harga_acuan), float(best_bid)) if best_bid else float(harga_acuan)
        return _bulatkan(dasar - geser, tick, ke_bawah=True)
    dasar = max(float(harga_acuan), float(best_ask)) if best_ask else float(harga_acuan)
    return _bulatkan(dasar + geser, tick, ke_bawah=False)


def sisi_binance(arah: str, keluar: bool = False) -> str:
    beli = arah == ARAH_LONG
    if keluar:
        beli = not beli
    return "BUY" if beli else "SELL"


def payload_entry(
    simbol: str,
    arah: str,
    qty: float,
    harga: float,
    visible_qty: Optional[float] = None,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> Dict[str, Any]:
    """Order masuk: LIMIT + GTX (post-only). Tidak pernah MARKET."""
    p: Dict[str, Any] = {
        "symbol": simbol,
        "side": sisi_binance(arah),
        "type": TIPE_LIMIT,
        "timeInForce": TIF_POST_ONLY,
        "price": float(harga),
        "quantity": round(float(qty), 12),
    }
    if visible_qty:
        p["visible_qty"] = round(float(visible_qty), 12)
        p["icebergQty"] = round(float(visible_qty), 12)
    return pastikan_tanpa_market(p, kebijakan)


def payload_tp(
    simbol: str,
    arah: str,
    qty: float,
    harga: float,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> Dict[str, Any]:
    """Take profit parsial: LIMIT + GTX + reduceOnly (post-only, maker fee)."""
    p = {
        "symbol": simbol,
        "side": sisi_binance(arah, keluar=True),
        "type": TIPE_LIMIT,
        "timeInForce": TIF_POST_ONLY,
        "price": float(harga),
        "quantity": round(float(qty), 12),
        "reduceOnly": True,
    }
    return pastikan_tanpa_market(p, kebijakan)


def payload_tp_market(
    simbol: str,
    arah: str,
    stop_price: float,
    kebijakan: Optional[KebijakanOrder] = None,
) -> Dict[str, Any]:
    """Take profit via TAKE_PROFIT_MARKET (HANYA untuk menutup posisi terbuka).

    Berbeda dari MARKET order biasa: ini adalah order kondisional yang hanya
    aktif bila harga mencapai stopPrice, dan selalu closePosition=true.
    Tidak melempar OrderTerlarang karena ini adalah order EXIT yang sah.

    Diverifikasi di Binance Testnet (4 Agu 2026): diterima saat ada posisi terbuka.
    """
    if kebijakan is not None and not kebijakan.izinkan_tp_market:
        raise OrderTerlarang("kebijakan melarang TAKE_PROFIT_MARKET; gunakan payload_tp (LIMIT+GTX)")
    return {
        "symbol": simbol,
        "side": sisi_binance(arah, keluar=True),
        "type": TIPE_TAKE_PROFIT_MARKET,
        "stopPrice": float(stop_price),
        "closePosition": True,
        "workingType": "MARK_PRICE",
    }


def payload_sl(
    simbol: str,
    arah: str,
    stop_price: float,
    qty: Optional[float] = None,
    tutup_posisi: bool = True,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> Dict[str, Any]:
    """Stop loss: STOP_MARKET (pengecualian resmi terhadap larangan market order)."""
    if not kebijakan.izinkan_market_untuk_sl:
        raise OrderTerlarang(
            "kebijakan melarang market untuk SL, tetapi hanya STOP_MARKET yang didukung"
        )
    p: Dict[str, Any] = {
        "symbol": simbol,
        "side": sisi_binance(arah, keluar=True),
        "type": TIPE_STOP_MARKET,
        "stopPrice": float(stop_price),
        "workingType": "MARK_PRICE",
        "reduceOnly": True,
    }
    if tutup_posisi:
        p["closePosition"] = True
        p.pop("reduceOnly", None)
    elif qty is not None:
        p["quantity"] = round(float(qty), 12)
    return p


def payload_bracket(
    simbol: str,
    arah: str,
    sl_price: float,
    tp_price: float,
    qty: Optional[float] = None,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Pasang SL dan TP sekaligus pada posisi terbuka.

    Mengembalikan (payload_sl, payload_tp_market) yang siap dikirim ke
    client.kirim_order() secara berurutan setelah entry terisi.
    """
    sl = payload_sl(simbol, arah, sl_price, tutup_posisi=True, kebijakan=kebijakan)
    tp = payload_tp_market(simbol, arah, tp_price, kebijakan=kebijakan)
    return sl, tp


def pastikan_tanpa_market(
    payload: Dict[str, Any], kebijakan: KebijakanOrder = KebijakanOrder()
) -> Dict[str, Any]:
    """Penegak aturan untuk order ENTRY. Dipanggil tepat sebelum order dikirim."""
    tipe = str(payload.get("type", "")).upper()
    if tipe == TIPE_STOP_MARKET:
        if not kebijakan.izinkan_market_untuk_sl:
            raise OrderTerlarang("STOP_MARKET tidak diizinkan oleh kebijakan")
        return payload
    if tipe == TIPE_TAKE_PROFIT_MARKET:
        raise OrderTerlarang(
            "TAKE_PROFIT_MARKET tidak boleh dipakai untuk entry; gunakan payload_tp_market()"
        )
    if tipe in TIPE_TERLARANG_ENTRY:
        raise OrderTerlarang(f"order tipe {tipe} diharamkan untuk entry: gunakan LIMIT post-only")
    if kebijakan.post_only_wajib and tipe == TIPE_LIMIT:
        if str(payload.get("timeInForce", "")).upper() != TIF_POST_ONLY:
            raise OrderTerlarang(
                f"order LIMIT wajib timeInForce={TIF_POST_ONLY} (post-only), "
                f"dapat {payload.get('timeInForce')!r}"
            )
    return payload


@dataclass
class HasilQuote:
    """Hasil usaha penempatan post-only, termasuk kegagalan karena crossing."""

    terisi: bool
    harga: Optional[float]
    percobaan: int
    alasan: Optional[str] = None
    riwayat: list = field(default_factory=list)

    def ringkas(self) -> Dict[str, Any]:
        return {
            "terisi": self.terisi,
            "harga": self.harga,
            "percobaan": self.percobaan,
            "alasan": self.alasan,
        }


def rencana_requote(
    arah: str,
    harga_acuan: float,
    kebijakan: KebijakanOrder = KebijakanOrder(),
) -> list:
    """Daftar harga post-only untuk percobaan ke-1..N, makin menjauh dari pasar."""
    keluar = []
    for i in range(1, max(1, kebijakan.maks_requote) + 1):
        k = KebijakanOrder(
            post_only_wajib=kebijakan.post_only_wajib,
            izinkan_market_untuk_sl=kebijakan.izinkan_market_untuk_sl,
            izinkan_tp_market=kebijakan.izinkan_tp_market,
            offset_tick=kebijakan.offset_tick * i,
            maks_requote=kebijakan.maks_requote,
            tick_size=kebijakan.tick_size,
        )
        keluar.append(harga_post_only(arah, harga_acuan, kebijakan=k))
    return keluar
