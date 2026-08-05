"""L5 - backtest PORTOFOLIO: banyak simbol, satu saldo, kapasitas 4 posisi bersamaan.

Berbeda dengan `backtest.Backtester` (satu simbol, satu posisi), modul ini:
1. Menjalankan banyak simbol pada SATU garis waktu gabungan (urut timestamp), sehingga
   persaingan slot antar simbol tersimulasi apa adanya.
2. Memakai satu saldo bersama, sehingga sizing tiap entry memakai balance berjalan yang
   sudah memperhitungkan posisi lain.
3. Membatasi posisi terbuka lewat `portofolio.ManajerSlot` (default 4, wajib beda pair).
4. MENCATAT setiap sinyal valid yang tidak dieksekusi karena slot penuh. Inilah data
   "sinyal scalp lain yang tidak di-entry" untuk dashboard.

Manajer slot TIDAK menilai kualitas sinyal: siapa yang datang lebih dulu saat ada slot
kosong, dia yang masuk. Jadi tidak ada strategi "raja".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .backtest import (
    FEE_BPS_DEFAULT,
    FEE_SL_BPS_DEFAULT,
    SLIPPAGE_BPS_DEFAULT,
    SLIPPAGE_SL_BPS_DEFAULT,
    Backtester,
    HasilBacktest,
    PosisiTerbuka,
    TradeTutup,
)
from .eksekusi.mode import boleh_auto_entry
from .kontrak import HORIZON_INTRADAY, TFPlan
from .portofolio import (
    ALASAN_SIMBOL_SUDAH_ADA,
    ALASAN_SLOT_PENUH,
    MAKS_POSISI_BERSAMAAN,
    ManajerSlot,
    PosisiTerbuka as SlotPosisi,
)
from .strategi import Registry


def _ringkas_kurva(
    kurva: Sequence[Tuple[int, float]], maks_titik: int = 500
) -> List[List[float]]:
    """Turunkan resolusi kurva ekuitas agar ringan dikirim ke dashboard.

    Titik pertama dan terakhir selalu dipertahankan supaya balance awal dan akhir
    tidak berubah. Tidak ada perataan nilai: ini murni pengambilan sampel.
    """
    n = len(kurva)
    if n == 0:
        return []
    if n <= maks_titik:
        return [[int(ts), round(float(bal), 4)] for ts, bal in kurva]
    langkah = n / float(maks_titik)
    indeks = sorted({int(k * langkah) for k in range(maks_titik)} | {0, n - 1})
    return [[int(kurva[i][0]), round(float(kurva[i][1]), 4)] for i in indeks]


@dataclass
class HasilPortofolio:
    trades: Tuple[TradeTutup, ...]
    kurva_ekuitas: Tuple[Tuple[int, float], ...]
    balance_awal: float
    balance_akhir: float
    bar_dievaluasi: int
    entry_batal_gap: int
    entry_ditolak_biaya: int
    tolak_biaya_per_kode: Dict[str, int]
    simbol: Tuple[str, ...]
    maks_posisi: int
    terlewat: Tuple[Dict[str, Any], ...] = ()
    ringkas_terlewat: Dict[str, Any] = field(default_factory=dict)
    simbol_trade: Dict[str, int] = field(default_factory=dict)
    puncak_posisi_bersamaan: int = 0

    @property
    def total_trade(self) -> int:
        return len(self.trades)

    @property
    def total_biaya(self) -> float:
        return sum(t.biaya for t in self.trades)

    @property
    def pnl_bersih(self) -> float:
        return self.balance_akhir - self.balance_awal

    @property
    def pnl_kotor(self) -> float:
        return self.pnl_bersih + self.total_biaya

    @property
    def menang(self) -> int:
        return sum(1 for t in self.trades if t.pnl_bersih > 0)

    @property
    def win_rate(self) -> float:
        return (self.menang / self.total_trade) if self.total_trade else 0.0

    @property
    def profit_factor(self) -> float:
        untung = sum(t.pnl_bersih for t in self.trades if t.pnl_bersih > 0)
        rugi = -sum(t.pnl_bersih for t in self.trades if t.pnl_bersih < 0)
        if rugi <= 0:
            return float("inf") if untung > 0 else 0.0
        return untung / rugi

    @property
    def max_drawdown(self) -> float:
        puncak = self.balance_awal
        mdd = 0.0
        for _, bal in self.kurva_ekuitas:
            puncak = max(puncak, bal)
            if puncak > 0:
                mdd = max(mdd, (puncak - bal) / puncak)
        return mdd

    def per_strategi(self) -> Dict[str, Dict[str, Any]]:
        keluar: Dict[str, Dict[str, Any]] = {}
        for t in self.trades:
            d = keluar.setdefault(
                t.strategy_id,
                {"trade": 0, "menang": 0, "pnl_bersih": 0.0, "pnl_kotor": 0.0, "biaya": 0.0},
            )
            d["trade"] += 1
            d["menang"] += 1 if t.pnl_bersih > 0 else 0
            d["pnl_bersih"] += t.pnl_bersih
            d["pnl_kotor"] += t.pnl_kotor
            d["biaya"] += t.biaya
        for d in keluar.values():
            d["pnl_bersih"] = round(d["pnl_bersih"], 4)
            d["pnl_kotor"] = round(d["pnl_kotor"], 4)
            d["biaya"] = round(d["biaya"], 4)
            d["edge_kotor_per_trade"] = round(d["pnl_kotor"] / d["trade"], 6)
            d["edge_bersih_per_trade"] = round(d["pnl_bersih"] / d["trade"], 6)
        return dict(sorted(keluar.items(), key=lambda kv: -kv[1]["trade"]))

    def ringkas(self) -> Dict[str, Any]:
        pf = self.profit_factor
        return {
            "simbol": list(self.simbol),
            "maks_posisi_bersamaan": self.maks_posisi,
            "puncak_posisi_bersamaan": self.puncak_posisi_bersamaan,
            "balance_awal": round(self.balance_awal, 4),
            "balance_akhir": round(self.balance_akhir, 4),
            "total_trade": self.total_trade,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": (None if pf == float("inf") else round(pf, 4)),
            "pnl_bersih": round(self.pnl_bersih, 4),
            "pnl_kotor": round(self.pnl_kotor, 4),
            "total_biaya": round(self.total_biaya, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "bar_dievaluasi": self.bar_dievaluasi,
            "entry_batal_gap": self.entry_batal_gap,
            "entry_ditolak_biaya": self.entry_ditolak_biaya,
            "tolak_biaya_per_kode": dict(sorted(self.tolak_biaya_per_kode.items())),
            "sinyal_terlewat": self.ringkas_terlewat,
            "trade_per_simbol": dict(sorted(self.simbol_trade.items(), key=lambda kv: -kv[1])),
            "per_strategi": self.per_strategi(),
            "kurva_ekuitas": _ringkas_kurva(self.kurva_ekuitas),
        }


class BacktesterPortofolio:
    def __init__(
        self,
        planes: Dict[str, Any],
        tfplan: TFPlan,
        horizon: str = HORIZON_INTRADAY,
        registry: Optional[Registry] = None,
        balance_awal: float = 1_000.0,
        leverage_maks: float = 20.0,
        margin_konflik: float = 5.0,
        fee_bps: float = FEE_BPS_DEFAULT,
        slippage_bps: float = SLIPPAGE_BPS_DEFAULT,
        fee_sl_bps: float = FEE_SL_BPS_DEFAULT,
        slippage_sl_bps: float = SLIPPAGE_SL_BPS_DEFAULT,
        saring_biaya: bool = True,
        maks_posisi: int = MAKS_POSISI_BERSAMAAN,
        simpan_terlewat_maks: int = 5_000,
    ) -> None:
        if not planes:
            raise ValueError("planes tidak boleh kosong")
        self.balance_awal = float(balance_awal)
        self.maks_posisi = int(maks_posisi)
        self.simpan_terlewat_maks = int(simpan_terlewat_maks)
        self.horizon = horizon
        self.mesin: Dict[str, Backtester] = {
            simbol: Backtester(
                plane,
                tfplan,
                horizon,
                registry,
                balance_awal=balance_awal,
                leverage_maks=leverage_maks,
                margin_konflik=margin_konflik,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
                saring_biaya=saring_biaya,
                fee_sl_bps=fee_sl_bps,
                slippage_sl_bps=slippage_sl_bps,
            )
            for simbol, plane in planes.items()
        }

    def jalankan(self, maks_bar: Optional[int] = None) -> HasilPortofolio:
        # 1. Susun garis waktu gabungan (ts, simbol, indeks bar).
        acara: List[Tuple[int, str, int]] = []
        for simbol, bt in self.mesin.items():
            pipe = bt.pipeline
            e = pipe.plane.bars(pipe.tfplan.entry_tf)
            warmup = max([s.warmup for s in pipe.registry.semua()] or [50])
            batas = len(e) if maks_bar is None else min(len(e), warmup + int(maks_bar))
            for i in range(warmup, batas):
                acara.append((int(e.ts[i]), simbol, i))
        acara.sort(key=lambda x: (x[0], x[1]))

        slot = ManajerSlot(self.maks_posisi)
        posisi_bt: Dict[str, PosisiTerbuka] = {}
        balance = self.balance_awal
        trades: List[TradeTutup] = []
        kurva: List[Tuple[int, float]] = []
        bar_dievaluasi = 0
        entry_batal_gap = 0
        simbol_trade: Dict[str, int] = {}
        puncak = 0
        boleh_entry = boleh_auto_entry(self.horizon)

        for ts, simbol, i in acara:
            bt = self.mesin[simbol]
            pipe = bt.pipeline
            e = pipe.plane.bars(pipe.tfplan.entry_tf)
            n = len(e)

            pos = posisi_bt.get(simbol)
            if pos is not None:
                pos_baru, trade, balance = bt._proses_bar_posisi(pos, e, i, balance)
                if trade is not None:
                    trades.append(trade)
                    simbol_trade[simbol] = simbol_trade.get(simbol, 0) + 1
                    slot.tutup(simbol)
                if pos_baru is None:
                    posisi_bt.pop(simbol, None)
                else:
                    posisi_bt[simbol] = pos_baru
                kurva.append((ts, balance))
                continue

            bar_dievaluasi += 1
            if not boleh_entry or i + 1 >= n:
                kurva.append((ts, balance))
                continue

            ctx = pipe.konteks(i)
            keputusan = pipe.arbiter.putuskan(ctx)
            v = keputusan.verdict
            if v is None:
                kurva.append((ts, balance))
                continue

            alasan = slot.alasan_tolak(simbol)
            if alasan is not None:
                # Sinyal valid tetapi tidak ada kapasitas -> catat, jangan hilangkan.
                if len(slot.terlewat) < self.simpan_terlewat_maks:
                    slot.catat_terlewat(ts, simbol, v, alasan, horizon=self.horizon)
                kurva.append((ts, balance))
                continue

            posisi_baru, batal = bt._buka_posisi(v, e, i, balance)
            if batal:
                entry_batal_gap += 1
            elif posisi_baru is not None:
                posisi_bt[simbol] = posisi_baru
                slot.buka(
                    SlotPosisi(
                        simbol=simbol,
                        arah=v.arah,
                        strategy_id=v.strategy_id,
                        kelompok=getattr(v, "kelompok", ""),
                        ts_masuk=ts,
                        entry=posisi_baru.entry_isi,
                        sl=posisi_baru.sl,
                        qty=posisi_baru.qty_awal,
                        horizon=self.horizon,
                    )
                )
                puncak = max(puncak, slot.jumlah_terbuka)
            kurva.append((ts, balance))

        # Tutup sisa posisi pada bar terakhir masing-masing simbol.
        for simbol, pos in list(posisi_bt.items()):
            bt = self.mesin[simbol]
            e = bt.pipeline.plane.bars(bt.pipeline.tfplan.entry_tf)
            ts_akhir = int(e.ts[len(e) - 1])
            trade, balance = bt._tutup_penuh(
                pos, ts_akhir, float(e.close[len(e) - 1]), "akhir_data", balance
            )
            trades.append(trade)
            simbol_trade[simbol] = simbol_trade.get(simbol, 0) + 1
            slot.tutup(simbol)
            posisi_bt.pop(simbol, None)
        if kurva:
            kurva[-1] = (kurva[-1][0], balance)

        ditolak = sum(bt.ditolak_biaya for bt in self.mesin.values())
        per_kode: Dict[str, int] = {}
        for bt in self.mesin.values():
            for k, jml in bt.tolak_biaya_per_kode.items():
                per_kode[k] = per_kode.get(k, 0) + jml

        trades.sort(key=lambda t: t.ts_keluar)
        return HasilPortofolio(
            trades=tuple(trades),
            kurva_ekuitas=tuple(kurva),
            balance_awal=self.balance_awal,
            balance_akhir=balance,
            bar_dievaluasi=bar_dievaluasi,
            entry_batal_gap=entry_batal_gap,
            entry_ditolak_biaya=ditolak,
            tolak_biaya_per_kode=per_kode,
            simbol=tuple(sorted(self.mesin)),
            maks_posisi=self.maks_posisi,
            terlewat=tuple(s.ringkas() for s in slot.terlewat),
            ringkas_terlewat=slot.ringkas_terlewat(),
            simbol_trade=simbol_trade,
            puncak_posisi_bersamaan=puncak,
        )
