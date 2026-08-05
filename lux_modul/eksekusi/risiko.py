"""L4 - manajemen risiko.

Rumus di berkas ini TIDAK BOLEH diubah tanpa uji ulang (perintah eksplisit operator).

Modal sangat kecil (< $20, termasuk saldo <= 0 yang diperlakukan sebagai kasus batas):
    risk_pct = 3% * (20 / balance) ** 0.55
    clamp ke [0.5%, 3%]
    risk_usd = max($0.20, balance * risk_pct)
$0.20 adalah LANTAI MINIMUM, bukan nilai flat untuk semua saldo di bawah $20.

Modal >= $20: tiered 1-3%, lalu taper menuju 0.25% di atas $100.000.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

RISK_LANTAI_USD = 0.20
RISK_PCT_MIN = 0.005
RISK_PCT_MAKS = 0.03
AMBANG_MODAL_KECIL = 20.0
EKSPONEN_KECIL = 0.55

# Tier untuk saldo >= $20 (batas_atas_eksklusif, risk_pct)
TIER = (
    (100.0, 0.03),
    (1_000.0, 0.025),
    (10_000.0, 0.02),
    (50_000.0, 0.015),
    (100_000.0, 0.01),
)
TAPER_MULAI = 100_000.0
TAPER_PCT_DASAR = 0.01
TAPER_EKSPONEN = 0.35
TAPER_LANTAI = 0.0025


def calculate_dynamic_risk(balance: float) -> float:
    """Persentase risiko per trade (desimal, mis. 0.03 = 3%).

    Saldo <= 0 dikembalikan sebagai RISK_PCT_MAKS karena rumus pangkat tidak terdefinisi;
    ukuran posisi tetap nol karena risk_usd dihitung dari saldo.
    """
    b = float(balance)
    if b < AMBANG_MODAL_KECIL:
        if b <= 0:
            return RISK_PCT_MAKS
        pct = RISK_PCT_MAKS * (AMBANG_MODAL_KECIL / b) ** EKSPONEN_KECIL
        return min(RISK_PCT_MAKS, max(RISK_PCT_MIN, pct))
    for batas, pct in TIER:
        if b < batas:
            return pct
    # taper di atas $100rb: risiko persen mengecil supaya risiko absolut terkendali
    pct = TAPER_PCT_DASAR * (TAPER_MULAI / b) ** TAPER_EKSPONEN
    return max(TAPER_LANTAI, min(TAPER_PCT_DASAR, pct))


def risiko_usd(balance: float) -> float:
    """Nominal risiko per trade dalam USD.

    Lantai $0.20 hanya berlaku pada rezim modal kecil (< $20); di atas itu nominal
    sudah jauh melewati lantai sehingga max() tetap aman diterapkan seragam.
    """
    b = max(0.0, float(balance))
    return max(RISK_LANTAI_USD, b * calculate_dynamic_risk(b))


@dataclass(frozen=True)
class Sizing:
    qty: float
    notional: float
    risk_usd: float
    risk_pct: float
    jarak_sl: float
    leverage_efektif: float
    terpotong_oleh: Optional[str] = None


def ukuran_posisi(
    balance: float,
    entry: float,
    sl: float,
    leverage_maks: float = 20.0,
    qty_step: float = 0.0,
    notional_min: float = 0.0,
) -> Sizing:
    """Hitung qty dari jarak SL. Risiko nominal, bukan persen posisi."""
    entry = float(entry)
    sl = float(sl)
    jarak = abs(entry - sl)
    if entry <= 0 or jarak <= 0:
        raise ValueError("entry harus > 0 dan jarak SL tidak boleh nol")
    pct = calculate_dynamic_risk(balance)
    r_usd = risiko_usd(balance)
    qty = r_usd / jarak
    notional = qty * entry
    batas_notional = max(0.0, float(balance)) * float(leverage_maks)
    terpotong = None
    if batas_notional > 0 and notional > batas_notional:
        qty = batas_notional / entry
        notional = qty * entry
        terpotong = "leverage_maks"
    if qty_step and qty_step > 0:
        qty = (int(qty / qty_step)) * qty_step
        notional = qty * entry
    if notional_min and notional < notional_min:
        terpotong = "di_bawah_notional_min"
    lev = notional / max(float(balance), 1e-12)
    return Sizing(
        qty=float(qty),
        notional=float(notional),
        risk_usd=float(r_usd),
        risk_pct=float(pct),
        jarak_sl=float(jarak),
        leverage_efektif=float(lev),
        terpotong_oleh=terpotong,
    )


def ringkas_kurva(saldo: Tuple[float, ...] = (1, 5, 10, 19.99, 20, 100, 1_000, 10_000, 100_000, 1_000_000)):
    """Tabel diagnostik risk% dan risk$ pada beberapa titik saldo."""
    return [
        {
            "balance": s,
            "risk_pct": round(calculate_dynamic_risk(s), 6),
            "risk_usd": round(risiko_usd(s), 6),
        }
        for s in saldo
    ]
