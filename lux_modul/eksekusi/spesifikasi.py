"""L4 - spesifikasi kontrak + pembulatan presisi + LEVERAGE OTOMATIS.

Arah perhitungan yang ditegakkan modul ini (perintah operator 4 Agu 2026):

    Risk -> Position Size / Notional -> Required Margin -> Optimal Leverage

BUKAN `Leverage -> Risk`. Leverage adalah HASIL, bukan input. Tidak ada angka
statis x5/x10 di mana pun; nilainya dihitung per setup dan bisa berbeda antar
pair karena jarak SL, harga, step size, dan bracket leverage tiap simbol berbeda.

Yang diperhitungkan:
- saldo/equity dan risk per trade (dari eksekusi/risiko.py - rumusnya TIDAK diubah)
- entry & stop loss (jarak SL menentukan qty)
- tick size, step size, price/quantity precision
- minimum & maksimum notional dari exchangeInfo
- batas leverage per simbol (leverage bracket Binance)
- biaya round-trip (fee maker/taker + slippage) untuk RR BERSIH dan BEP

Semua fungsi di sini murni (tanpa jaringan) sehingga bisa diuji tanpa Binance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..kontrak import ARAH_LONG, ARAH_SHORT
from .biaya import (
    FEE_BPS_MAKER,
    FEE_BPS_TAKER,
    SLIPPAGE_BPS,
    SLIPPAGE_MAKER_BPS,
)
from .risiko import calculate_dynamic_risk, risiko_usd

# kode alasan rencana posisi ditolak
TOLAK_NOTIONAL_MIN = "notional_di_bawah_minimum_exchange"
TOLAK_QTY_NOL = "qty_nol_setelah_pembulatan_step"
TOLAK_MARGIN = "margin_melebihi_saldo_tersedia"
TOLAK_LEVERAGE_MAKS = "butuh_leverage_di_atas_batas_simbol"
TOLAK_SL_NOL = "jarak_sl_nol_setelah_pembulatan_tick"
TOLAK_RR_BERSIH = "rr_bersih_tidak_layak"


# --------------------------------------------------------------------------- #
# pembulatan presisi
# --------------------------------------------------------------------------- #


def _desimal_dari_step(step: float) -> int:
    if step <= 0:
        return 8
    s = f"{step:.12f}".rstrip("0")
    if "." not in s:
        return 0
    return len(s.split(".")[1])


def bulatkan_ke_kelipatan(nilai: float, kelipatan: float, arah: str = "terdekat") -> float:
    """Bulatkan `nilai` ke kelipatan `kelipatan` (tick/step).

    arah: 'bawah' | 'atas' | 'terdekat'. Hasil dibulatkan ulang ke jumlah desimal
    kelipatan supaya tidak muncul galat floating point seperti 0.30000000000000004.
    """
    if kelipatan is None or kelipatan <= 0:
        return float(nilai)
    n = float(nilai) / float(kelipatan)
    if arah == "bawah":
        n = math.floor(n + 1e-9)
    elif arah == "atas":
        n = math.ceil(n - 1e-9)
    else:
        n = math.floor(n + 0.5)
    return round(n * float(kelipatan), _desimal_dari_step(float(kelipatan)))


@dataclass(frozen=True)
class SpesifikasiKontrak:
    """Spesifikasi satu simbol futures, apa adanya dari exchangeInfo."""

    simbol: str
    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    maks_notional: float = 0.0  # 0 = tanpa batas yang diketahui
    presisi_harga: Optional[int] = None
    presisi_qty: Optional[int] = None
    leverage_maks_simbol: float = 20.0
    bracket: Tuple[Tuple[float, float], ...] = ()  # ((batas_notional, leverage_maks), ...)

    # --------------------------- pembulatan --------------------------- #

    def bulat_harga(self, harga: float, arah: str = "terdekat") -> float:
        h = bulatkan_ke_kelipatan(harga, self.tick_size, arah)
        if self.presisi_harga is not None:
            h = round(h, int(self.presisi_harga))
        return h

    def bulat_qty(self, qty: float, arah: str = "bawah") -> float:
        q = bulatkan_ke_kelipatan(qty, self.step_size, arah)
        if self.presisi_qty is not None:
            q = round(q, int(self.presisi_qty))
        return max(0.0, q)

    def leverage_untuk_notional(self, notional: float) -> float:
        """Leverage maksimum yang diizinkan Binance untuk notional sebesar itu."""
        if not self.bracket:
            return float(self.leverage_maks_simbol)
        for batas, lev in sorted(self.bracket, key=lambda x: x[0]):
            if notional <= batas:
                return float(lev)
        return float(sorted(self.bracket, key=lambda x: x[0])[-1][1])

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "tick_size": self.tick_size,
            "step_size": self.step_size,
            "min_qty": self.min_qty,
            "min_notional": self.min_notional,
            "maks_notional": self.maks_notional,
            "presisi_harga": self.presisi_harga,
            "presisi_qty": self.presisi_qty,
            "leverage_maks_simbol": self.leverage_maks_simbol,
            "jumlah_bracket": len(self.bracket),
        }

    # --------------------------- pabrik --------------------------- #

    @staticmethod
    def dari_exchange_info(
        info_simbol: Mapping[str, Any],
        bracket: Sequence[Mapping[str, Any]] = (),
    ) -> "SpesifikasiKontrak":
        tick = step = min_qty = min_notional = maks_notional = 0.0
        for f in info_simbol.get("filters", []) or []:
            jenis = f.get("filterType")
            if jenis == "PRICE_FILTER":
                tick = float(f.get("tickSize", 0) or 0)
            elif jenis == "LOT_SIZE":
                step = float(f.get("stepSize", 0) or 0)
                min_qty = float(f.get("minQty", 0) or 0)
                maks_qty = float(f.get("maxQty", 0) or 0)
                if maks_qty:
                    maks_notional = 0.0  # dikonversi belakangan bila perlu
            elif jenis == "MIN_NOTIONAL":
                nilai = f.get("notional", f.get("minNotional"))
                min_notional = float(nilai) if nilai is not None else 0.0
        pasangan: List[Tuple[float, float]] = []
        for b in bracket or ():
            try:
                pasangan.append(
                    (float(b.get("notionalCap", 0) or 0), float(b.get("initialLeverage", 0) or 0))
                )
            except (TypeError, ValueError):
                continue
        lev_maks = max((l for _, l in pasangan), default=0.0)
        return SpesifikasiKontrak(
            simbol=str(info_simbol.get("symbol", "")).upper(),
            tick_size=tick,
            step_size=step,
            min_qty=min_qty,
            min_notional=min_notional,
            maks_notional=maks_notional,
            presisi_harga=info_simbol.get("pricePrecision"),
            presisi_qty=info_simbol.get("quantityPrecision"),
            leverage_maks_simbol=lev_maks or 20.0,
            bracket=tuple(pasangan),
        )


SPEK_UMUM = SpesifikasiKontrak(simbol="(generik)", leverage_maks_simbol=20.0)


# --------------------------------------------------------------------------- #
# ekonomi break-even & RR bersih
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EkonomiTrade:
    """BEP dan RR BERSIH (sesudah fee + slippage), sadar arah long/short."""

    arah: str
    entry: float
    sl: float
    tp_utama: float
    bep: float
    biaya_masuk_frac: float
    biaya_keluar_tp_frac: float
    biaya_keluar_sl_frac: float
    risiko_harga: float
    risiko_bersih_frac: float
    imbalan_bersih_frac: float
    rr_kotor: float
    rr_bersih: float

    def ringkas(self) -> Dict[str, Any]:
        return {
            "arah": self.arah,
            "entry": self.entry,
            "sl": self.sl,
            "tp_utama": self.tp_utama,
            "bep": round(self.bep, 10),
            "rr_kotor": round(self.rr_kotor, 4),
            "rr_bersih": round(self.rr_bersih, 4),
            "risiko_bersih_frac": round(self.risiko_bersih_frac, 8),
            "imbalan_bersih_frac": round(self.imbalan_bersih_frac, 8),
        }


def harga_break_even(
    arah: str,
    entry: float,
    fee_masuk_bps: float = FEE_BPS_MAKER,
    fee_keluar_bps: float = FEE_BPS_MAKER,
    slippage_masuk_bps: float = SLIPPAGE_MAKER_BPS,
    slippage_keluar_bps: float = SLIPPAGE_MAKER_BPS,
) -> float:
    """Harga impas SETELAH biaya, konsisten dengan arah posisi.

    LONG  : harus keluar DI ATAS entry  -> entry * (1 + total)
    SHORT : harus keluar DI BAWAH entry -> entry * (1 - total)
    """
    if arah not in (ARAH_LONG, ARAH_SHORT):
        raise ValueError(f"arah tidak sah: {arah!r}")
    total = (
        float(fee_masuk_bps)
        + float(fee_keluar_bps)
        + float(slippage_masuk_bps)
        + float(slippage_keluar_bps)
    ) / 10_000.0
    e = float(entry)
    return e * (1.0 + total) if arah == ARAH_LONG else e * (1.0 - total)


def ekonomi_trade(
    arah: str,
    entry: float,
    sl: float,
    tp_utama: float,
    fee_masuk_bps: float = FEE_BPS_MAKER,
    slippage_masuk_bps: float = SLIPPAGE_MAKER_BPS,
    fee_tp_bps: float = FEE_BPS_MAKER,
    slippage_tp_bps: float = SLIPPAGE_MAKER_BPS,
    fee_sl_bps: float = FEE_BPS_TAKER,
    slippage_sl_bps: float = SLIPPAGE_BPS,
    funding_bps: float = 0.0,
) -> EkonomiTrade:
    """Hitung BEP dan RR BERSIH.

    RR bersih = (jarak TP - biaya jalur TP) / (jarak SL + biaya jalur SL),
    keduanya dalam fraksi harga terhadap entry. Ini yang dilaporkan ke operator,
    bukan RR teoritis `TP/SL` yang mengabaikan ongkos.

    `funding_bps` dibebankan ke KEDUA jalur (biaya menahan posisi tidak peduli
    trade berakhir di TP atau SL). Default 0 karena horizon scalping/intraday
    umumnya tidak melewati jadwal funding 8 jam; isi bila memang relevan.
    """
    if arah not in (ARAH_LONG, ARAH_SHORT):
        raise ValueError(f"arah tidak sah: {arah!r}")
    e = float(entry)
    if e <= 0:
        raise ValueError("entry harus > 0")

    masuk = (float(fee_masuk_bps) + float(slippage_masuk_bps)) / 10_000.0
    keluar_tp = (float(fee_tp_bps) + float(slippage_tp_bps)) / 10_000.0
    keluar_sl = (float(fee_sl_bps) + float(slippage_sl_bps)) / 10_000.0
    fund = float(funding_bps) / 10_000.0

    jarak_sl = abs(e - float(sl)) / e
    jarak_tp = abs(float(tp_utama) - e) / e

    # biaya dibayar atas notional; untuk fraksi harga, biaya keluar dihitung pada
    # harga keluar, tapi selisihnya orde bps*bps -> diabaikan secara sadar.
    risiko_bersih = jarak_sl + masuk + keluar_sl + fund
    imbalan_bersih = jarak_tp - masuk - keluar_tp - fund

    rr_kotor = (jarak_tp / jarak_sl) if jarak_sl > 0 else 0.0
    rr_bersih = (imbalan_bersih / risiko_bersih) if risiko_bersih > 0 else 0.0

    return EkonomiTrade(
        arah=arah,
        entry=e,
        sl=float(sl),
        tp_utama=float(tp_utama),
        bep=harga_break_even(arah, e, fee_masuk_bps, fee_tp_bps, slippage_masuk_bps, slippage_tp_bps),
        biaya_masuk_frac=masuk,
        biaya_keluar_tp_frac=keluar_tp,
        biaya_keluar_sl_frac=keluar_sl,
        risiko_harga=abs(e - float(sl)),
        risiko_bersih_frac=risiko_bersih,
        imbalan_bersih_frac=imbalan_bersih,
        rr_kotor=rr_kotor,
        rr_bersih=rr_bersih,
    )


# --------------------------------------------------------------------------- #
# rencana posisi: Risk -> Notional -> Margin -> Leverage
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RencanaPosisi:
    """Hasil sizing lengkap, siap dipakai order layer."""

    simbol: str
    arah: str
    entry: float
    sl: float
    qty: float
    notional: float
    risk_usd: float
    risk_pct: float
    risiko_nyata_usd: float  # risiko setelah pembulatan qty & termasuk biaya keluar SL
    margin_dibutuhkan: float
    leverage_optimal: float
    leverage_maks_simbol: float
    jarak_sl: float
    ekonomi: Optional[EkonomiTrade] = None
    layak: bool = True
    kode: Optional[str] = None
    catatan: Tuple[str, ...] = ()

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "arah": self.arah,
            "entry": self.entry,
            "sl": self.sl,
            "qty": self.qty,
            "notional": round(self.notional, 8),
            "risk_usd": round(self.risk_usd, 6),
            "risk_pct": round(self.risk_pct, 6),
            "risiko_nyata_usd": round(self.risiko_nyata_usd, 6),
            "margin_dibutuhkan": round(self.margin_dibutuhkan, 6),
            "leverage_optimal": self.leverage_optimal,
            "leverage_maks_simbol": self.leverage_maks_simbol,
            "rr_bersih": None if self.ekonomi is None else round(self.ekonomi.rr_bersih, 4),
            "rr_kotor": None if self.ekonomi is None else round(self.ekonomi.rr_kotor, 4),
            "bep": None if self.ekonomi is None else round(self.ekonomi.bep, 10),
            "layak": self.layak,
            "kode": self.kode,
            "catatan": list(self.catatan),
        }


def rencana_posisi(
    simbol: str,
    arah: str,
    balance: float,
    entry: float,
    sl: float,
    tp_utama: Optional[float] = None,
    spek: Optional[SpesifikasiKontrak] = None,
    porsi_margin_maks: float = 0.5,
    leverage_batas_operator: Optional[float] = None,
    fee_masuk_bps: float = FEE_BPS_MAKER,
    fee_sl_bps: float = FEE_BPS_TAKER,
    slippage_sl_bps: float = SLIPPAGE_BPS,
    rr_bersih_min: Optional[float] = None,
) -> RencanaPosisi:
    """Hitung posisi lengkap dengan urutan Risk -> Notional -> Margin -> Leverage.

    - `qty` lahir dari risiko nominal dibagi jarak SL, LALU dibulatkan ke step size.
    - `notional` = qty * entry (setelah pembulatan tick/step, bukan sebelum).
    - `margin_dibutuhkan` dibatasi `porsi_margin_maks` dari saldo agar satu setup
      tidak mengunci seluruh equity.
    - `leverage_optimal` = ceil(notional / margin_yang_direlakan), dibatasi bracket
      simbol. Ia HASIL, bukan input, dan berbeda-beda per setup.
    - Risiko nominal TIDAK PERNAH dinaikkan oleh leverage: bila leverage yang
      dibutuhkan melebihi batas simbol/operator, rencana ditolak - bukan risikonya
      yang dibesarkan.
    """
    spek = spek or SpesifikasiKontrak(simbol=simbol)
    if arah not in (ARAH_LONG, ARAH_SHORT):
        raise ValueError(f"arah tidak sah: {arah!r}")

    catatan: List[str] = []
    e = spek.bulat_harga(entry, "terdekat")
    # SL dibulatkan MENJAUH dari entry supaya jarak risiko tidak menyusut diam-diam
    s = spek.bulat_harga(sl, "bawah" if arah == ARAH_LONG else "atas")
    if e <= 0:
        raise ValueError("entry harus > 0")

    jarak = abs(e - s)
    risk_pct = calculate_dynamic_risk(balance)
    r_usd = risiko_usd(balance)

    def gagal(kode: str, qty: float = 0.0, notional: float = 0.0, lev: float = 0.0) -> RencanaPosisi:
        return RencanaPosisi(
            simbol=simbol,
            arah=arah,
            entry=e,
            sl=s,
            qty=qty,
            notional=notional,
            risk_usd=r_usd,
            risk_pct=risk_pct,
            risiko_nyata_usd=qty * jarak,
            margin_dibutuhkan=(notional / lev) if lev > 0 else 0.0,
            leverage_optimal=lev,
            leverage_maks_simbol=spek.leverage_untuk_notional(notional),
            jarak_sl=jarak,
            ekonomi=eko,
            layak=False,
            kode=kode,
            catatan=tuple(catatan),
        )

    eko: Optional[EkonomiTrade] = None
    if tp_utama is not None:
        tp = spek.bulat_harga(
            tp_utama, "bawah" if arah == ARAH_LONG else "atas"
        )  # TP dibulatkan KE DALAM agar realistis terisi
        if jarak > 0:
            eko = ekonomi_trade(
                arah,
                e,
                s,
                tp,
                fee_masuk_bps=fee_masuk_bps,
                fee_sl_bps=fee_sl_bps,
                slippage_sl_bps=slippage_sl_bps,
            )

    if jarak <= 0:
        return gagal(TOLAK_SL_NOL)

    qty_ideal = r_usd / jarak
    qty = spek.bulat_qty(qty_ideal, "bawah")
    if qty <= 0 or (spek.min_qty and qty < spek.min_qty):
        catatan.append(
            f"qty ideal {qty_ideal:.10f} lebih kecil dari step/min qty simbol - "
            "saldo terlalu kecil untuk pair ini, cari pair dengan harga satuan lebih rendah"
        )
        return gagal(TOLAK_QTY_NOL, qty=qty)

    notional = qty * e
    if spek.min_notional and notional < spek.min_notional:
        catatan.append(
            f"notional {notional:.4f} < min_notional {spek.min_notional} - menaikkan qty "
            "akan melanggar batas risiko, jadi setup ini dilewati (bukan dipaksakan)"
        )
        return gagal(TOLAK_NOTIONAL_MIN, qty=qty, notional=notional)

    # ---- margin & leverage: HASIL dari notional, bukan penentu risiko ---- #
    saldo = max(0.0, float(balance))
    margin_direlakan = saldo * float(porsi_margin_maks)
    if margin_direlakan <= 0:
        return gagal(TOLAK_MARGIN, qty=qty, notional=notional)

    lev_perlu = notional / margin_direlakan
    lev_optimal = max(1.0, math.ceil(lev_perlu - 1e-9))
    lev_maks_simbol = spek.leverage_untuk_notional(notional)
    if leverage_batas_operator:
        lev_maks = min(lev_maks_simbol, float(leverage_batas_operator))
    else:
        lev_maks = lev_maks_simbol

    if lev_optimal > lev_maks:
        catatan.append(
            f"butuh leverage x{lev_optimal:.0f} untuk notional {notional:.2f} dengan margin "
            f"{margin_direlakan:.2f}, sementara batas {lev_maks:.0f} - setup ditolak, "
            "risiko TIDAK dinaikkan untuk memaksakan entry"
        )
        return gagal(TOLAK_LEVERAGE_MAKS, qty=qty, notional=notional, lev=lev_optimal)

    margin = notional / lev_optimal
    if margin > saldo:
        return gagal(TOLAK_MARGIN, qty=qty, notional=notional, lev=lev_optimal)

    # risiko nyata: jarak SL setelah pembulatan + ongkos keluar darurat
    biaya_keluar = notional * (float(fee_sl_bps) + float(slippage_sl_bps)) / 10_000.0
    biaya_masuk = notional * float(fee_masuk_bps) / 10_000.0
    risiko_nyata = qty * jarak + biaya_masuk + biaya_keluar

    kode: Optional[str] = None
    layak = True
    if rr_bersih_min is not None and eko is not None and eko.rr_bersih < float(rr_bersih_min):
        layak = False
        kode = TOLAK_RR_BERSIH
        catatan.append(
            f"RR bersih {eko.rr_bersih:.3f} < minimum {float(rr_bersih_min):.3f} "
            "(RR kotor tidak dipakai sebagai dasar keputusan)"
        )

    return RencanaPosisi(
        simbol=simbol,
        arah=arah,
        entry=e,
        sl=s,
        qty=qty,
        notional=notional,
        risk_usd=r_usd,
        risk_pct=risk_pct,
        risiko_nyata_usd=risiko_nyata,
        margin_dibutuhkan=margin,
        leverage_optimal=float(lev_optimal),
        leverage_maks_simbol=float(lev_maks_simbol),
        jarak_sl=jarak,
        ekonomi=eko,
        layak=layak,
        kode=kode,
        catatan=tuple(catatan),
    )
