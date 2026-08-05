"""L4 - gerbang biaya (fee + slippage) yang berlaku UNIVERSAL untuk semua strategi.

Latar belakang (temuan backtest BTC putaran 1, lihat reports/CATATAN_BACKTEST_1.md):
PnL kotor seluruh konfigurasi berada di sekitar nol, tetapi fee taker + slippage
menelan hampir seluruh modal. Penyebab strukturalnya bukan strategi tertentu,
melainkan hubungan matematis antara jarak SL dan notional:

    qty      = risk_usd / jarak_sl
    notional = qty * entry = risk_usd / jarak_sl_frac        (jarak_sl_frac = jarak_sl / entry)
    biaya    = notional * pp_total                            (pp_total = total bps semua fill)
    biaya / risk_usd = pp_total / jarak_sl_frac               <- TIDAK bergantung saldo

Jadi semakin rapat SL, semakin besar biaya RELATIF terhadap risiko yang diambil.

PUTARAN 3 (kebijakan post-only, 3 Agu 2026)
-------------------------------------------
Operator mengharamkan market order. Entry dan TP kini WAJIB limit post-only (GTX)
sehingga membayar fee MAKER dan praktis tanpa slippage. Satu-satunya kaki yang
masih taker adalah stop loss (`STOP_MARKET`, lihat eksekusi/order.py).

Model biaya karena itu menjadi ASIMETRIS dan lebih murah:

    masuk        : maker  (2 bps, slippage 0)
    keluar TP    : maker  (2 bps, slippage 0) per target
    keluar SL    : taker  (5 bps + 2 bps slippage)

Untuk gerbang, jalur keluar terakhir SELALU dihitung sebagai keluar darurat (SL,
taker) supaya estimasi tetap konservatif: biaya_pp = masuk + (n_tp-1) maker + 1 SL.

Aturan di berkas ini:
1. Bersifat universal (berlaku sama untuk setiap strategi), sehingga tidak menciptakan
   strategi "raja": ini bukan penilaian kualitas sinyal, melainkan syarat kelayakan
   eksekusi seperti halnya pemeriksaan entry/SL/TP yang valid.
2. Tidak ada parameter yang disetel ke dataset tertentu. Ambangnya diturunkan dari
   aritmetika biaya dan dari daftar fee resmi, bukan dari hasil optimasi.
3. Rumus di lux_modul/eksekusi/risiko.py TIDAK diubah.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

# Fee Binance USDT-M futures (tier dasar).
FEE_BPS_MAKER = 2.0
FEE_BPS_TAKER = 5.0

# Slippage. Post-only tidak menyeberang spread -> 0. STOP_MARKET menyeberang -> 2 bps.
SLIPPAGE_MAKER_BPS = 0.0
SLIPPAGE_BPS = 2.0

# Biaya round-trip maksimum yang boleh ditanggung, dinyatakan sebagai fraksi dari
# RISIKO NOMINAL trade (1R). 0.20 berarti: biaya tidak boleh memakan lebih dari 20% 1R.
RASIO_BIAYA_MAKS = 0.20

# TP terdekat harus setidaknya sekian kali biaya round-trip, supaya TP pertama
# benar-benar menghasilkan uang setelah ongkos, bukan sekadar impas.
KELIPATAN_TP1_MIN = 3.0

# Batas jumlah fill keluar yang diperhitungkan. Tiap TP parsial adalah satu fill
# berbiaya; memakai lebih dari 3 TP membuat ongkos naik tanpa menambah edge.
FILL_KELUAR_MAKS = 3

KODE_BIAYA_VS_RISIKO = "biaya_melebihi_batas_risiko"
KODE_TP1_TERLALU_DEKAT = "tp1_terlalu_dekat_terhadap_biaya"


def bps_per_fill(
    fee_bps: float = FEE_BPS_MAKER, slippage_bps: float = SLIPPAGE_MAKER_BPS
) -> float:
    """Ongkos satu fill maker (post-only) dalam basis point terhadap notional."""
    return float(fee_bps) + float(slippage_bps)


def bps_keluar_darurat(
    fee_taker_bps: float = FEE_BPS_TAKER, slippage_bps: float = SLIPPAGE_BPS
) -> float:
    """Ongkos satu fill keluar lewat STOP_MARKET (taker + slippage)."""
    return float(fee_taker_bps) + float(slippage_bps)


def jumlah_fill(n_tp: int) -> int:
    """1 fill masuk + n fill keluar (dibatasi FILL_KELUAR_MAKS, minimum 1 keluar)."""
    keluar = min(max(int(n_tp), 1), FILL_KELUAR_MAKS)
    return 1 + keluar


def biaya_pp_round_trip(
    n_tp: int,
    fee_bps: float = FEE_BPS_MAKER,
    slippage_bps: float = SLIPPAGE_MAKER_BPS,
    fee_sl_bps: float = FEE_BPS_TAKER,
    slippage_sl_bps: float = SLIPPAGE_BPS,
) -> float:
    """Total ongkos round-trip sebagai FRAKSI notional (bukan bps).

    Struktur: 1 fill masuk maker + (k-1) fill TP maker + 1 fill keluar darurat taker,
    dengan k = jumlah fill keluar efektif (dibatasi FILL_KELUAR_MAKS).
    """
    keluar = min(max(int(n_tp), 1), FILL_KELUAR_MAKS)
    maker = bps_per_fill(fee_bps, slippage_bps)
    darurat = bps_keluar_darurat(fee_sl_bps, slippage_sl_bps)
    total_bps = maker + (keluar - 1) * maker + darurat
    return total_bps / 10_000.0


@dataclass(frozen=True)
class MetrikBiaya:
    jarak_sl_frac: float
    jarak_tp1_frac: float
    biaya_pp: float
    rasio_biaya_risiko: float  # biaya / 1R, bebas dari besar saldo
    kelipatan_tp1: float
    lolos: bool
    kode: Optional[str] = None

    def ringkas(self) -> dict:
        return {
            "jarak_sl_frac": round(self.jarak_sl_frac, 8),
            "jarak_tp1_frac": round(self.jarak_tp1_frac, 8),
            "biaya_pp": round(self.biaya_pp, 8),
            "rasio_biaya_risiko": round(self.rasio_biaya_risiko, 6),
            "kelipatan_tp1": round(self.kelipatan_tp1, 4),
            "lolos": self.lolos,
            "kode": self.kode,
        }


def evaluasi_biaya(
    entry: float,
    sl: float,
    harga_tp: Sequence[float],
    fee_bps: float = FEE_BPS_MAKER,
    slippage_bps: float = SLIPPAGE_MAKER_BPS,
    rasio_maks: float = RASIO_BIAYA_MAKS,
    kelipatan_tp1_min: float = KELIPATAN_TP1_MIN,
    fee_sl_bps: float = FEE_BPS_TAKER,
    slippage_sl_bps: float = SLIPPAGE_BPS,
) -> MetrikBiaya:
    """Uji kelayakan biaya sebuah rencana trade. Tidak melihat identitas strategi."""
    entry = float(entry)
    if entry <= 0:
        raise ValueError("entry harus > 0")
    jarak_sl_frac = abs(entry - float(sl)) / entry
    tps = [float(h) for h in harga_tp]
    jarak_tp1_frac = (
        min(abs(h - entry) for h in tps) / entry if tps else 0.0
    )
    biaya_pp = biaya_pp_round_trip(
        len(tps), fee_bps, slippage_bps, fee_sl_bps, slippage_sl_bps
    )

    if jarak_sl_frac <= 0:
        return MetrikBiaya(0.0, jarak_tp1_frac, biaya_pp, float("inf"), 0.0, False, KODE_BIAYA_VS_RISIKO)

    rasio = biaya_pp / jarak_sl_frac
    kelipatan_tp1 = (jarak_tp1_frac / biaya_pp) if biaya_pp > 0 else float("inf")

    if rasio > rasio_maks:
        return MetrikBiaya(
            jarak_sl_frac, jarak_tp1_frac, biaya_pp, rasio, kelipatan_tp1, False, KODE_BIAYA_VS_RISIKO
        )
    if kelipatan_tp1 < kelipatan_tp1_min:
        return MetrikBiaya(
            jarak_sl_frac, jarak_tp1_frac, biaya_pp, rasio, kelipatan_tp1, False, KODE_TP1_TERLALU_DEKAT
        )
    return MetrikBiaya(jarak_sl_frac, jarak_tp1_frac, biaya_pp, rasio, kelipatan_tp1, True, None)


def evaluasi_verdict(
    verdict,
    fee_bps: float = FEE_BPS_MAKER,
    slippage_bps: float = SLIPPAGE_MAKER_BPS,
    rasio_maks: float = RASIO_BIAYA_MAKS,
    kelipatan_tp1_min: float = KELIPATAN_TP1_MIN,
    fee_sl_bps: float = FEE_BPS_TAKER,
    slippage_sl_bps: float = SLIPPAGE_BPS,
) -> MetrikBiaya:
    """Bungkus evaluasi_biaya untuk sebuah StrategyVerdict."""
    return evaluasi_biaya(
        entry=verdict.entry,
        sl=verdict.sl,
        harga_tp=[tp.harga for tp in verdict.tps],
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        rasio_maks=rasio_maks,
        kelipatan_tp1_min=kelipatan_tp1_min,
        fee_sl_bps=fee_sl_bps,
        slippage_sl_bps=slippage_sl_bps,
    )


def batas_tp_efektif(tps: Sequence, maks: int = FILL_KELUAR_MAKS):
    """Pangkas daftar TP menjadi paling banyak `maks` target, porsi sisa digabung ke
    target terakhir yang dipertahankan, supaya total porsi tetap 1.0 dan jumlah fill
    (= ongkos) tidak membengkak.

    Mengembalikan daftar tuple (harga, porsi).
    """
    daftar = [(float(t.harga), float(t.porsi)) for t in tps]
    if len(daftar) <= maks:
        return daftar
    kepala = daftar[: maks - 1]
    ekor = daftar[maks - 1 :]
    porsi_ekor = sum(p for _, p in ekor)
    # Target gabungan memakai harga TP PERTAMA dari ekor (paling konservatif: target
    # terdekat, tidak mengarang target yang lebih menguntungkan). Daftar TP sudah
    # diurutkan dari yang terdekat ke entry oleh pemanggil.
    harga_gabung = ekor[0][0]
    return kepala + [(harga_gabung, porsi_ekor)]
