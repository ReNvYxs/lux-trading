"""L3 - GOVERNOR PORTOFOLIO: batas posisi, free margin, dan antrean sinyal global.

Masalah nyata yang diselesaikan modul ini (log testnet operator, 4 Agu 2026):
sekitar 20 runner gagal dengan kode -2019 "Margin is insufficient".

Penyebabnya BUKAN sizing per-setup, melainkan tidak adanya state portofolio
bersama. 120 runner (40 pair x 3 entry TF) masing-masing menghitung margin dari
SALDO TOTAL dengan porsi_margin_maks=0.5, seolah dirinya satu-satunya yang akan
mengirim order. Runner pertama memakai margin, sisanya tetap memakai angka saldo
lama, lalu ditolak bursa satu per satu.

Aturan operator yang ditegakkan di sini:
1. Maksimum 4 posisi terbuka bersamaan (scalp + intraday DIGABUNG).
2. Ada minimum free margin yang WAJIB tersisa (pagar likuidasi).
3. Swing TIDAK PERNAH auto-entry - hanya sinyal untuk dashboard.
4. Sinyal yang tidak dieksekusi karena kuota penuh TIDAK dibuang, tetapi
   dikembalikan sebagai keputusan ditolak + alasan, supaya dashboard tetap
   menampilkannya.

Karena satu siklus bisa memunculkan puluhan sinyal sedangkan kuota hanya 4,
urutan "siapa cepat dia dapat" tidak dapat diterima - kuota akan diisi pair
sampah yang kebetulan diproses lebih dulu. Semua kandidat satu siklus diantre
dulu, diperingkat (skor strategi, likuiditas, RR bersih, nama), baru kuota
dibagikan. Deterministik, jadi bisa direproduksi di backtest.

Modul ini murni (tanpa jaringan) sehingga bisa diuji penuh tanpa Binance.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .kontrak import HORIZON_INTRADAY, HORIZON_SCALPING

# horizon yang boleh auto-entry (perintah operator: swing hanya sinyal)
HORIZON_AUTO_ENTRY = (HORIZON_SCALPING, HORIZON_INTRADAY)

# kode alasan penolakan - dipakai dashboard & Telegram supaya pesan seragam
TOLAK_KUOTA_POSISI = "kuota_posisi_penuh"
TOLAK_FREE_MARGIN = "melanggar_minimum_free_margin"
TOLAK_DUPLIKAT_SIMBOL = "sudah_ada_posisi_pada_simbol_ini"
TOLAK_ARAH_BERLAWANAN = "bentrok_arah_dengan_posisi_terbuka"
TOLAK_MARGIN_KURANG = "margin_tersedia_tidak_cukup"
TOLAK_BUKAN_AUTO_ENTRY = "horizon_tidak_boleh_auto_entry"
TOLAK_MARGIN_TIDAK_SAH = "margin_dibutuhkan_tidak_sah"

MAKS_POSISI_DEFAULT = 4
MIN_FREE_MARGIN_PCT_DEFAULT = 0.30


@dataclass(frozen=True)
class KebijakanPortofolio:
    """Pagar risiko tingkat AKUN (bukan tingkat setup)."""

    maks_posisi: int = MAKS_POSISI_DEFAULT
    min_free_margin_pct: float = MIN_FREE_MARGIN_PCT_DEFAULT
    maks_posisi_per_simbol: int = 1
    izinkan_hedge: bool = False

    def validasi(self) -> None:
        if self.maks_posisi < 1:
            raise ValueError("maks_posisi minimal 1")
        if not 0.0 <= self.min_free_margin_pct < 1.0:
            raise ValueError("min_free_margin_pct harus di [0, 1)")
        if self.maks_posisi_per_simbol < 1:
            raise ValueError("maks_posisi_per_simbol minimal 1")

    def ringkas(self) -> Dict[str, object]:
        return {
            "maks_posisi": self.maks_posisi,
            "min_free_margin_pct": self.min_free_margin_pct,
            "maks_posisi_per_simbol": self.maks_posisi_per_simbol,
            "izinkan_hedge": self.izinkan_hedge,
        }


@dataclass(frozen=True)
class PosisiTerbuka:
    """Cuplikan posisi nyata dari akun (bukan tebakan internal)."""

    simbol: str
    arah: str
    qty: float = 0.0
    notional: float = 0.0
    margin: float = 0.0


@dataclass(frozen=True)
class KandidatEntry:
    """Satu sinyal yang MINTA kuota posisi."""

    simbol: str
    arah: str
    entry_tf: str
    horizon: str
    skor: float
    margin_dibutuhkan: float
    notional: float = 0.0
    leverage: float = 0.0
    rr_bersih: float = 0.0
    skor_likuiditas: float = 0.0
    strategi: str = ""

    def kunci(self) -> str:
        return f"{self.simbol}@{self.entry_tf}"


@dataclass(frozen=True)
class KeputusanEntry:
    """Hasil keputusan governor untuk satu kandidat."""

    kandidat: KandidatEntry
    diterima: bool
    alasan: str = ""
    peringkat: int = 0
    margin_setelah: float = 0.0
    free_margin_setelah: float = 0.0

    def ringkas(self) -> Dict[str, object]:
        return {
            "simbol": self.kandidat.simbol,
            "entry_tf": self.kandidat.entry_tf,
            "arah": self.kandidat.arah,
            "horizon": self.kandidat.horizon,
            "strategi": self.kandidat.strategi,
            "skor": round(self.kandidat.skor, 4),
            "diterima": self.diterima,
            "alasan": self.alasan,
            "peringkat": self.peringkat,
            "margin_dibutuhkan": round(self.kandidat.margin_dibutuhkan, 6),
            "free_margin_setelah": round(self.free_margin_setelah, 6),
        }


@dataclass
class SnapshotAkun:
    """Kondisi akun saat siklus dimulai - selalu dari bursa, tidak diasumsikan."""

    equity: float
    margin_tersedia: float
    posisi: Tuple[PosisiTerbuka, ...] = ()

    @property
    def jumlah_posisi(self) -> int:
        return len(self.posisi)


class GovernorPortofolio:
    """Pembagi kuota posisi & margin untuk SELURUH runner dalam satu siklus."""

    def __init__(self, kebijakan: Optional[KebijakanPortofolio] = None) -> None:
        self.kebijakan = kebijakan or KebijakanPortofolio()
        self.kebijakan.validasi()
        self.snapshot: Optional[SnapshotAkun] = None
        self._antrean: List[KandidatEntry] = []

    def mulai_siklus(self, snapshot: SnapshotAkun) -> None:
        self.snapshot = snapshot
        self._antrean = []

    def antre(self, kandidat: KandidatEntry) -> None:
        self._antrean.append(kandidat)

    def antre_banyak(self, kandidat: Sequence[KandidatEntry]) -> None:
        self._antrean.extend(kandidat)

    @staticmethod
    def _kunci_urut(k: KandidatEntry) -> Tuple[float, float, float, str]:
        """Urutan: skor strategi -> likuiditas -> RR bersih -> nama (stabil)."""
        return (-float(k.skor), -float(k.skor_likuiditas), -float(k.rr_bersih), k.kunci())

    def peringkat(self) -> List[KandidatEntry]:
        return sorted(self._antrean, key=self._kunci_urut)

    def putuskan(self) -> List[KeputusanEntry]:
        if self.snapshot is None:
            raise RuntimeError("panggil mulai_siklus(snapshot) sebelum putuskan()")
        snap = self.snapshot
        keb = self.kebijakan

        equity = max(0.0, float(snap.equity))
        lantai_free = equity * keb.min_free_margin_pct
        free_margin = float(snap.margin_tersedia)

        hitung_simbol: Dict[str, int] = {}
        arah_simbol: Dict[str, str] = {}
        for p in snap.posisi:
            hitung_simbol[p.simbol] = hitung_simbol.get(p.simbol, 0) + 1
            arah_simbol.setdefault(p.simbol, p.arah)
        slot = keb.maks_posisi - snap.jumlah_posisi

        hasil: List[KeputusanEntry] = []
        for i, k in enumerate(self.peringkat(), start=1):
            alasan = self._alasan_tolak(
                k, slot, free_margin, lantai_free, hitung_simbol, arah_simbol
            )
            if alasan:
                hasil.append(
                    KeputusanEntry(
                        kandidat=k,
                        diterima=False,
                        alasan=alasan,
                        peringkat=i,
                        free_margin_setelah=free_margin,
                    )
                )
                continue
            free_margin -= float(k.margin_dibutuhkan)
            slot -= 1
            hitung_simbol[k.simbol] = hitung_simbol.get(k.simbol, 0) + 1
            arah_simbol.setdefault(k.simbol, k.arah)
            hasil.append(
                KeputusanEntry(
                    kandidat=k,
                    diterima=True,
                    peringkat=i,
                    margin_setelah=equity - free_margin,
                    free_margin_setelah=free_margin,
                )
            )
        return hasil

    def _alasan_tolak(
        self,
        k: KandidatEntry,
        slot: int,
        free_margin: float,
        lantai_free: float,
        hitung_simbol: Dict[str, int],
        arah_simbol: Dict[str, str],
    ) -> str:
        keb = self.kebijakan
        if k.horizon not in HORIZON_AUTO_ENTRY:
            return TOLAK_BUKAN_AUTO_ENTRY
        margin = float(k.margin_dibutuhkan)
        if margin <= 0.0:
            return TOLAK_MARGIN_TIDAK_SAH
        if slot <= 0:
            return TOLAK_KUOTA_POSISI
        if hitung_simbol.get(k.simbol, 0) >= keb.maks_posisi_per_simbol:
            return TOLAK_DUPLIKAT_SIMBOL
        arah_lama = arah_simbol.get(k.simbol)
        if arah_lama is not None and arah_lama != k.arah and not keb.izinkan_hedge:
            return TOLAK_ARAH_BERLAWANAN
        if margin > free_margin:
            return TOLAK_MARGIN_KURANG
        if free_margin - margin < lantai_free:
            return TOLAK_FREE_MARGIN
        return ""

    @staticmethod
    def ringkas_keputusan(keputusan: Sequence[KeputusanEntry]) -> Dict[str, object]:
        diterima = [k for k in keputusan if k.diterima]
        ditolak = [k for k in keputusan if not k.diterima]
        per_alasan: Dict[str, int] = {}
        for k in ditolak:
            per_alasan[k.alasan] = per_alasan.get(k.alasan, 0) + 1
        return {
            "kandidat": len(keputusan),
            "diterima": len(diterima),
            "ditolak": len(ditolak),
            "ditolak_per_alasan": per_alasan,
            "dieksekusi": [k.kandidat.kunci() for k in diterima],
        }


def margin_dibutuhkan(notional: float, leverage: float) -> float:
    """Margin awal = notional / leverage. Leverage <= 0 dianggap 1x (paling aman)."""
    lev = float(leverage) if leverage and leverage > 0 else 1.0
    return float(notional) / lev


def snapshot_dari_akun(
    saldo: Sequence[Dict[str, object]],
    posisi: Sequence[Dict[str, object]],
    aset: str = "USDT",
) -> SnapshotAkun:
    """Bangun SnapshotAkun dari respons mentah /fapi/v2/balance & positionRisk.

    Hanya posisi dengan positionAmt != 0 yang dihitung; Binance mengembalikan
    SELURUH simbol termasuk yang qty-nya nol, dan menghitungnya sebagai posisi
    terbuka akan langsung memblokir seluruh entry.
    """
    equity = 0.0
    tersedia = 0.0
    for baris in saldo:
        if baris.get("asset") != aset:
            continue
        equity = float(baris.get("balance", 0.0) or 0.0)
        tersedia = float(baris.get("availableBalance", equity) or 0.0)
        break

    terbuka: List[PosisiTerbuka] = []
    for p in posisi:
        try:
            qty = float(p.get("positionAmt", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if qty == 0.0:
            continue
        harga = float(p.get("entryPrice", 0.0) or 0.0)
        lev = float(p.get("leverage", 1.0) or 1.0)
        notional = abs(qty) * harga
        terbuka.append(
            PosisiTerbuka(
                simbol=str(p.get("symbol", "")),
                arah="LONG" if qty > 0 else "SHORT",
                qty=abs(qty),
                notional=notional,
                margin=margin_dibutuhkan(notional, lev),
            )
        )
    return SnapshotAkun(equity=equity, margin_tersedia=tersedia, posisi=tuple(terbuka))
