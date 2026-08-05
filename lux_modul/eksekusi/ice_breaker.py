"""L4 - Ice-breaker: pemecah order notional besar menjadi slice TWAP + iceberg.

Diporting dari modul lama DENGAN dua perbaikan wajib:
1. `visible_qty` benar-benar DIKIRIM ke exchange (masuk payload order), bukan sekadar
   dihitung lalu dibuang.
2. Eksekusi slice NON-BLOCKING: memakai asyncio, penundaan antar slice tidak memblokir
   event loop, dan pembatalan bisa terjadi kapan saja.

`entry_invalidated()` ikut diporting: bila harga sudah menembus SL sebelum seluruh
slice terkirim, sisa slice dibatalkan.

Order kecil (notional di bawah ambang) TIDAK diubah: satu slice, tanpa iceberg.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from ..kontrak import ARAH_LONG, ARAH_SHORT
from .order import (
    TIF_POST_ONLY,
    TIPE_LIMIT,
    KebijakanOrder,
    OrderTerlarang,
    harga_post_only,
    pastikan_tanpa_market,
)

AMBANG_NOTIONAL_ICEBREAKER = 5_000.0
SLICE_MAKS = 12
NOTIONAL_PER_SLICE = 2_500.0
RASIO_VISIBLE = 0.25
JEDA_DETIK = 1.5


@dataclass(frozen=True)
class Slice:
    urutan: int
    qty: float
    visible_qty: float
    jeda_detik: float

    def payload(self, simbol: str, sisi: str, harga: Optional[float]) -> Dict[str, Any]:
        """Payload order Binance Futures.

        KEBIJAKAN 3 Agu 2026: MARKET ORDER DIHARAMKAN. Setiap slice wajib LIMIT
        post-only (`timeInForce=GTX`), sehingga `harga` tidak boleh None.
        `visible_qty` benar-benar dikirim -> parameter iceberg `icebergQty`.
        """
        if harga is None:
            raise OrderTerlarang(
                "slice tanpa harga akan menjadi MARKET order; kebijakan post-only "
                "mewajibkan harga limit"
            )
        p: Dict[str, Any] = {
            "symbol": simbol,
            "side": sisi,
            "type": TIPE_LIMIT,
            "timeInForce": TIF_POST_ONLY,
            "price": float(harga),
            "quantity": round(self.qty, 12),
            # PERBAIKAN BUG 1: visible_qty ikut dikirim, bukan hanya dihitung.
            "visible_qty": round(self.visible_qty, 12),
            "icebergQty": round(self.visible_qty, 12),
        }
        return pastikan_tanpa_market(p)


@dataclass(frozen=True)
class RencanaEksekusi:
    simbol: str
    arah: str
    qty_total: float
    harga_acuan: float
    notional: float
    slices: Sequence[Slice]
    memakai_icebreaker: bool
    sl: Optional[float] = None

    @property
    def jumlah_slice(self) -> int:
        return len(self.slices)

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "arah": self.arah,
            "qty_total": self.qty_total,
            "notional": self.notional,
            "icebreaker": self.memakai_icebreaker,
            "slice": [
                {"urutan": s.urutan, "qty": s.qty, "visible_qty": s.visible_qty, "jeda": s.jeda_detik}
                for s in self.slices
            ],
        }


def plan_execution(
    simbol: str,
    arah: str,
    qty: float,
    harga: float,
    sl: Optional[float] = None,
    ambang_notional: float = AMBANG_NOTIONAL_ICEBREAKER,
    notional_per_slice: float = NOTIONAL_PER_SLICE,
    slice_maks: int = SLICE_MAKS,
    rasio_visible: float = RASIO_VISIBLE,
    jeda_detik: float = JEDA_DETIK,
) -> RencanaEksekusi:
    """Susun rencana eksekusi. Order kecil tetap satu slice penuh (baseline tak berubah)."""
    if arah not in (ARAH_LONG, ARAH_SHORT):
        raise ValueError(f"arah tidak sah: {arah!r}")
    if qty <= 0 or harga <= 0:
        raise ValueError("qty dan harga wajib positif")
    if not (0 < rasio_visible <= 1):
        raise ValueError("rasio_visible wajib di (0, 1]")
    notional = qty * harga

    if notional < ambang_notional:
        return RencanaEksekusi(
            simbol=simbol,
            arah=arah,
            qty_total=float(qty),
            harga_acuan=float(harga),
            notional=float(notional),
            slices=(Slice(0, float(qty), float(qty), 0.0),),
            memakai_icebreaker=False,
            sl=sl,
        )

    n = int(min(slice_maks, max(2, round(notional / max(notional_per_slice, 1e-9)))))
    dasar = qty / n
    slices: List[Slice] = []
    sisa = qty
    for k in range(n):
        q = dasar if k < n - 1 else sisa
        sisa -= q
        slices.append(
            Slice(
                urutan=k,
                qty=float(q),
                visible_qty=float(max(q * rasio_visible, min(q, 1e-12))),
                jeda_detik=0.0 if k == 0 else float(jeda_detik),
            )
        )
    return RencanaEksekusi(
        simbol=simbol,
        arah=arah,
        qty_total=float(qty),
        harga_acuan=float(harga),
        notional=float(notional),
        slices=tuple(slices),
        memakai_icebreaker=True,
        sl=sl,
    )


def entry_invalidated(arah: str, harga_kini: float, sl: Optional[float]) -> bool:
    """True bila harga sudah menembus SL sehingga sisa slice tidak boleh dikirim."""
    if sl is None:
        return False
    if arah == ARAH_LONG:
        return float(harga_kini) <= float(sl)
    return float(harga_kini) >= float(sl)


@dataclass
class HasilEksekusi:
    terkirim: List[Dict[str, Any]] = field(default_factory=list)
    dibatalkan: List[int] = field(default_factory=list)
    qty_terisi: float = 0.0
    alasan_batal: Optional[str] = None

    @property
    def selesai_penuh(self) -> bool:
        return not self.dibatalkan


class IceBreakerExecutor:
    """Eksekutor non-blocking.

    Dependensi disuntikkan agar bisa diuji tanpa jaringan dan tanpa menunggu waktu nyata:
      kirim_order : async (payload) -> respons exchange
      harga_kini  : callable () -> float (dipakai untuk cek entry_invalidated)
      tidur       : async (detik) -> None (default asyncio.sleep)
    """

    def __init__(
        self,
        kirim_order: Callable[[Dict[str, Any]], Awaitable[Any]],
        harga_kini: Optional[Callable[[], float]] = None,
        tidur: Optional[Callable[[float], Awaitable[None]]] = None,
        kebijakan: Optional[KebijakanOrder] = None,
    ):
        self._kirim = kirim_order
        self._harga = harga_kini
        self._tidur = tidur or asyncio.sleep
        self.kebijakan = kebijakan or KebijakanOrder()

    async def jalankan(self, rencana: RencanaEksekusi) -> HasilEksekusi:
        hasil = HasilEksekusi()
        sisi = "BUY" if rencana.arah == ARAH_LONG else "SELL"
        batal = False
        for s in rencana.slices:
            if batal:
                hasil.dibatalkan.append(s.urutan)
                continue
            if s.jeda_detik > 0:
                # NON-BLOCKING: await, bukan time.sleep
                await self._tidur(s.jeda_detik)
            if self._harga is not None and entry_invalidated(
                rencana.arah, self._harga(), rencana.sl
            ):
                hasil.alasan_batal = "entry_invalidated"
                hasil.dibatalkan.append(s.urutan)
                batal = True
                continue
            harga_limit = harga_post_only(
                rencana.arah,
                self._harga() if self._harga is not None else rencana.harga_acuan,
                kebijakan=self.kebijakan,
            )
            payload = s.payload(rencana.simbol, sisi, harga_limit)
            resp = await self._kirim(payload)
            hasil.terkirim.append({"payload": payload, "respons": resp})
            hasil.qty_terisi += s.qty
        return hasil

    def jalankan_sinkron(self, rencana: RencanaEksekusi) -> HasilEksekusi:
        """Pembungkus untuk pemakaian di skrip/uji sinkron."""
        return asyncio.run(self.jalankan(rencana))
