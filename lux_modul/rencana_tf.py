"""L2b - perencana timeframe yang DIGERAKKAN STRATEGI, bukan oleh .env.

Masalah lama: `.env` memaksa satu `tf_entry` (praktis selalu 15m), sehingga
strategi yang memang dirancang untuk TF lain tidak pernah punya kesempatan, dan
strategi multi-TF berjalan tanpa konteks lalu ditolak Arbiter dengan kode
`peran_tf`. Itu membuat `.env` berfungsi sebagai BATASAN, bukan konfigurasi.

Aturan modul ini:
- Kebutuhan TF dibaca dari kontrak strategi (`required_roles["context"]`) dan
  `horizon_didukung`, bukan dari tebakan.
- Untuk setiap entry TF yang relevan bagi horizon, dibuat SATU TFPlan yang
  membawa konteks sebanyak kebutuhan TERBESAR di antara strategi yang aktif.
  Strategi single-TF tetap jalan pada plan tersebut (kontraknya hanya menuntut
  `jumlah_konteks >= konteks_dibutuhkan`), sedangkan strategi multi-TF akhirnya
  mendapatkan konteks yang mereka butuhkan.
- `.env` boleh MEMPERSEMPIT (mis. operator hanya mau 5m) tapi tidak boleh
  diam-diam menjadi satu-satunya sumber kebenaran: bila operator tidak mengatur
  apa pun, rencana lahir dari strategi + horizon.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .kontrak import TFPlan, TF_MS, tf_ms

# tangga TF yang dipakai untuk menaikkan konteks (lompat ~4x agar informatif)
TANGGA_KONTEKS: Dict[str, Tuple[str, ...]] = {
    "1m": ("5m", "15m", "1h"),
    "3m": ("15m", "1h", "4h"),
    "5m": ("15m", "1h", "4h"),
    "15m": ("1h", "4h", "1d"),
    "30m": ("2h", "4h", "1d"),
    "1h": ("4h", "1d"),
    "2h": ("4h", "1d"),
    "4h": ("1d",),
}

# entry TF yang masuk akal per horizon (bukan daftar pair, ini murni horizon)
ENTRY_TF_HORIZON: Dict[str, Tuple[str, ...]] = {
    "scalping": ("1m", "5m", "15m"),
    "intraday": ("15m", "1h", "4h"),
}


class RencanaTFError(Exception):
    pass


@dataclass(frozen=True)
class RencanaTF:
    """Satu TFPlan + daftar strategi yang benar-benar bisa hidup di dalamnya."""

    tfplan: TFPlan
    strategi_stf: Tuple[str, ...]
    strategi_mtf: Tuple[str, ...]

    @property
    def entry_tf(self) -> str:
        return self.tfplan.entry_tf

    @property
    def context_tfs(self) -> Tuple[str, ...]:
        return tuple(self.tfplan.context_tfs)

    @property
    def jumlah_strategi(self) -> int:
        return len(self.strategi_stf) + len(self.strategi_mtf)

    def ringkas(self) -> Dict[str, Any]:
        return {
            "entry_tf": self.entry_tf,
            "context_tfs": list(self.context_tfs),
            "mode": "MTF" if self.context_tfs else "STF",
            "strategi_stf": list(self.strategi_stf),
            "strategi_mtf": list(self.strategi_mtf),
            "jumlah_strategi": self.jumlah_strategi,
        }


def konteks_untuk(entry_tf: str, jumlah: int) -> Tuple[str, ...]:
    """Ambil `jumlah` TF konteks di atas `entry_tf` dari tangga standar."""
    if jumlah <= 0:
        return ()
    tangga = TANGGA_KONTEKS.get(entry_tf)
    if tangga is None:
        tangga = tuple(tf for tf in TF_MS if tf_ms(tf) > tf_ms(entry_tf))
        tangga = tuple(sorted(tangga, key=tf_ms))
    if len(tangga) < jumlah:
        raise RencanaTFError(
            f"entry TF {entry_tf!r} tidak punya {jumlah} TF konteks di atasnya"
        )
    return tuple(tangga[:jumlah])


def rencana_dari_registry(
    registry: Any,
    horizon: str,
    entry_tfs: Optional[Sequence[str]] = None,
    maks_konteks: Optional[int] = None,
) -> Tuple[RencanaTF, ...]:
    """Bangun daftar RencanaTF dari kebutuhan strategi yang TERDAFTAR.

    entry_tfs=None -> pakai ENTRY_TF_HORIZON[horizon] (bukan 15m hardcode).
    """
    strategi = [s for s in registry.semua() if s.horizon_terpenuhi(horizon)]
    if not strategi:
        raise RencanaTFError(f"tidak ada strategi yang mendukung horizon {horizon!r}")

    butuh = max(int(s.konteks_dibutuhkan) for s in strategi)
    if maks_konteks is not None:
        butuh = min(butuh, int(maks_konteks))

    tfs = tuple(entry_tfs) if entry_tfs else ENTRY_TF_HORIZON.get(horizon)
    if not tfs:
        raise RencanaTFError(f"horizon {horizon!r} tidak punya daftar entry TF")

    out: List[RencanaTF] = []
    for tf in tfs:
        try:
            tf_ms(tf)  # validasi timeframe
        except ValueError as exc:
            raise RencanaTFError(f"entry TF tidak dikenal: {tf!r}") from exc
        try:
            ctx = konteks_untuk(tf, butuh)
        except RencanaTFError:
            ctx = konteks_untuk(tf, max(0, len(TANGGA_KONTEKS.get(tf, ()))))
        plan = TFPlan(entry_tf=tf, context_tfs=ctx)
        stf = tuple(sorted(s.id for s in strategi if not s.multi_tf))
        mtf = tuple(
            sorted(s.id for s in strategi if s.multi_tf and s.peran_terpenuhi(plan))
        )
        out.append(RencanaTF(tfplan=plan, strategi_stf=stf, strategi_mtf=mtf))
    return tuple(out)


def cakupan_strategi(
    registry: Any, rencana: Sequence[RencanaTF], horizon: str
) -> Dict[str, Any]:
    """Periksa apakah SETIAP strategi kebagian minimal satu rencana TF."""
    strategi = [s for s in registry.semua() if s.horizon_terpenuhi(horizon)]
    tercakup = set()
    for r in rencana:
        tercakup.update(r.strategi_stf)
        tercakup.update(r.strategi_mtf)
    semua = {s.id for s in strategi}
    tidak_didukung = {s.id for s in registry.semua() if not s.horizon_terpenuhi(horizon)}
    return {
        "horizon": horizon,
        "jumlah_rencana": len(rencana),
        "entry_tf": [r.entry_tf for r in rencana],
        "strategi_horizon_ini": len(semua),
        "tercakup": sorted(tercakup),
        "tidak_tercakup": sorted(semua - tercakup),
        "horizon_tidak_didukung": sorted(tidak_didukung),
        "lengkap": not (semua - tercakup),
    }


def uraikan_daftar_tf(teks: str) -> Tuple[str, ...]:
    """'5m, 15m , 1h' -> ('5m','15m','1h'). Kosong -> () (biar strategi yang bicara)."""
    if not teks:
        return ()
    keluar: List[str] = []
    for bagian in teks.split(","):
        b = bagian.strip()
        if not b:
            continue
        tf_ms(b)
        keluar.append(b)
    return tuple(keluar)
