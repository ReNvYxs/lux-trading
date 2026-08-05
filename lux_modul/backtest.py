"""L5 - Backtest: simulasi bar-by-bar PnL di atas Pipeline (L0..L4), tanpa look-ahead.

Backtest BUKAN lapis sinyal: ia tidak menambah atau mengubah logika strategi/arbiter
sama sekali (Registry dan Arbiter dipakai apa adanya). Ia hanya mensimulasikan apa yang
terjadi bila verdict yang dihasilkan Arbiter benar-benar dieksekusi di pasar, dengan
asumsi konservatif berikut (wajib dipegang, jangan dilonggarkan tanpa uji ulang):

1. TANPA LOOK-AHEAD: verdict yang dihasilkan dari bar ke-i (bar yang BARU SAJA TUTUP,
   sama seperti KonteksEvaluasi di pipeline.py) hanya dipakai untuk membuka posisi pada
   *bar berikutnya* (i+1). Harga isi (fill) memakai harga BUKA bar i+1, bukan harga bar
   sinyal itu sendiri.
2. Bila harga buka bar i+1 sendiri sudah menembus SL verdict (gap terhadap level acuan),
   posisi TIDAK dibuka sama sekali - entry batal (selaras dengan entry_invalidated di
   eksekusi/ice_breaker.py), bukan dibuka lalu langsung dianggap rugi pada bar yang sama.
3. PESIMISME INTRABAR: data OHLC tidak memberi tahu urutan sentuhan harga dalam satu
   lilin. Bila SL dan TP sama-sama tersentuh pada bar yang sama, SL DIANGGAP TERSENTUH
   LEBIH DULU (worst-case), sehingga seluruh sisa posisi ditutup di harga SL.
4. MULTI-TP: setiap TargetTP menutup porsi tertentu dari qty AWAL. TP diurutkan dari yang
   PALING DEKAT ke entry menuju yang paling jauh (diurutkan ulang di sini, tidak
   mengandalkan urutan pemberian verdict), lalu diperiksa berurutan; TP yang lebih jauh
   tidak mungkin kena pada bar yang sama bila TP yang lebih dekat belum kena.
5. FEE (taker, bps) dan SLIPPAGE (bps) dikenakan pada SETIAP fill (masuk, tiap TP
   parsial, SL, maupun penutupan paksa di akhir data), selalu ke arah yang merugikan
   trader.
6. Hanya SATU posisi terbuka pada satu waktu untuk satu Backtester (selaras dengan satu
   TFPlan/Registry/horizon); sinyal baru diabaikan selama posisi masih terbuka - ini
   bukan mesin portofolio multi-posisi.
7. Bila akhir data tercapai dengan posisi masih terbuka, posisi dipaksa tutup di harga
   CLOSE bar terakhir (alasan "akhir_data") supaya setiap posisi selalu berakhir sebagai
   satu TradeTutup yang lengkap.
8. Swing (signal_only) tidak pernah menghasilkan trade di sini; Backtester hanya
   membuka posisi bila `boleh_auto_entry(horizon)` True, sama seperti Pipeline.
9. GERBANG BIAYA UNIVERSAL (eksekusi/biaya.py): verdict yang ongkos round-trip-nya tidak
   masuk akal dibanding risiko 1R ditolak sebelum sizing, dan jumlah TP dibatasi supaya
   ongkos tidak membengkak. Berlaku sama untuk semua strategi.

Berkas ini TIDAK mengubah lux_modul/pipeline.py. Pipeline tetap dipakai apa adanya untuk
jalur sinyal/eksekusi langsung; Backtester di sini dipakai KHUSUS untuk uji strategi
(backtest) di atas data historis (sintetis maupun nyata).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .data.plane import DataPlane
from .eksekusi.biaya import FILL_KELUAR_MAKS, batas_tp_efektif, evaluasi_verdict
from .eksekusi.mode import boleh_auto_entry
from .eksekusi.spesifikasi import SpesifikasiKontrak, rencana_posisi
from .kontrak import ARAH_LONG, Bars, HORIZON_INTRADAY, StrategyVerdict, TFPlan, TargetTP
from .pipeline import Pipeline
from .strategi import Registry

# KEBIJAKAN 3 Agu 2026: market order diharamkan. Entry dan TP = LIMIT post-only (GTX)
# -> fee MAKER, slippage 0. Hanya SL yang taker (STOP_MARKET) -> fee taker + slippage.
FEE_BPS_DEFAULT = 2.0        # 0.02% per fill maker (entry + TP)
SLIPPAGE_BPS_DEFAULT = 0.0   # post-only tidak menyeberang spread
FEE_SL_BPS_DEFAULT = 5.0     # 0.05% taker untuk STOP_MARKET
SLIPPAGE_SL_BPS_DEFAULT = 2.0  # slippage konservatif saat stop terpicu


def _harga_slip(harga: float, arah: str, sisi: str, bps: float) -> float:
    """Geser harga fill ke arah yang MERUGIKAN trader.

    sisi="masuk": LONG dibeli lebih mahal, SHORT dijual lebih murah.
    sisi="keluar": LONG dijual lebih murah, SHORT dibeli lebih mahal.
    """
    faktor = bps / 10_000.0
    rugi_naik = (arah == ARAH_LONG and sisi == "masuk") or (arah != ARAH_LONG and sisi == "keluar")
    if rugi_naik:
        return harga * (1.0 + faktor)
    return harga * (1.0 - faktor)


@dataclass
class _TPState:
    tp: TargetTP
    qty: float
    kena: bool = False


@dataclass
class PosisiTerbuka:
    strategy_id: str
    kelompok: str
    arah: str
    verdict_entry: float
    entry_isi: float
    sl: float
    ts_sinyal: int
    ts_entry: int
    qty_awal: float
    balance_sebelum: float
    tps: Tuple[_TPState, ...]
    qty_sisa: float
    biaya: float = 0.0
    isi_tp: List[Tuple[int, float, float]] = field(default_factory=list)  # (ts, harga, qty)


@dataclass(frozen=True)
class TradeTutup:
    """Satu posisi lengkap dari isi sampai tutup (berapa pun jumlah TP parsialnya)."""

    strategy_id: str
    kelompok: str
    arah: str
    ts_sinyal: int
    ts_entry: int
    ts_keluar: int
    entry_rencana: float
    entry_isi: float
    sl: float
    keluar_terakhir: float
    alasan_keluar: str  # "sl" | "tp" | "akhir_data"
    qty_awal: float
    isi_tp: Tuple[Tuple[int, float, float], ...]
    biaya: float
    pnl_kotor: float
    pnl_bersih: float
    balance_sebelum: float
    balance_sesudah: float

    @property
    def r_multiple(self) -> float:
        risiko = abs(self.entry_isi - self.sl) * self.qty_awal
        if risiko <= 0:
            return 0.0
        return self.pnl_bersih / risiko

    def ringkas(self) -> Dict[str, object]:
        return {
            "strategy_id": self.strategy_id,
            "arah": self.arah,
            "ts_entry": self.ts_entry,
            "ts_keluar": self.ts_keluar,
            "alasan_keluar": self.alasan_keluar,
            "entry_isi": round(self.entry_isi, 8),
            "pnl_bersih": round(self.pnl_bersih, 6),
            "r_multiple": round(self.r_multiple, 4),
        }


@dataclass
class HasilBacktest:
    trades: Tuple[TradeTutup, ...]
    kurva_ekuitas: Tuple[Tuple[int, float], ...]
    balance_awal: float
    balance_akhir: float
    bar_dievaluasi: int
    entry_batal_gap: int = 0  # sinyal dibatalkan karena gap melewati SL saat open fill
    entry_ditolak_biaya: int = 0  # verdict ditolak gerbang biaya universal
    tolak_biaya_per_kode: Dict[str, int] = field(default_factory=dict)
    entry_ditolak_sizing: int = 0  # verdict ditolak rencana_posisi (notional/step/leverage)
    tolak_sizing_per_kode: Dict[str, int] = field(default_factory=dict)

    @property
    def jumlah_trade(self) -> int:
        return len(self.trades)

    @property
    def menang(self) -> int:
        return sum(1 for t in self.trades if t.pnl_bersih > 0)

    @property
    def kalah(self) -> int:
        return sum(1 for t in self.trades if t.pnl_bersih <= 0)

    @property
    def win_rate(self) -> float:
        return (self.menang / self.jumlah_trade) if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        untung = sum(t.pnl_bersih for t in self.trades if t.pnl_bersih > 0)
        rugi = -sum(t.pnl_bersih for t in self.trades if t.pnl_bersih < 0)
        if rugi <= 0:
            return float("inf") if untung > 0 else 0.0
        return untung / rugi

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl_bersih for t in self.trades)

    @property
    def total_biaya(self) -> float:
        return sum(t.biaya for t in self.trades)

    @property
    def max_drawdown(self) -> float:
        """Drawdown maksimum dari kurva ekuitas, dalam fraksi puncak (0..1)."""
        if not self.kurva_ekuitas:
            return 0.0
        puncak = float("-inf")
        dd_maks = 0.0
        for _, bal in self.kurva_ekuitas:
            puncak = max(puncak, bal)
            if puncak > 0:
                dd_maks = max(dd_maks, (puncak - bal) / puncak)
        return dd_maks

    def ringkas(self) -> Dict[str, object]:
        pf = self.profit_factor
        return {
            "jumlah_trade": self.jumlah_trade,
            "menang": self.menang,
            "kalah": self.kalah,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": "inf" if pf == float("inf") else round(pf, 4),
            "total_pnl": round(self.total_pnl, 4),
            "total_biaya": round(self.total_biaya, 4),
            "balance_awal": self.balance_awal,
            "balance_akhir": round(self.balance_akhir, 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "bar_dievaluasi": self.bar_dievaluasi,
            "entry_batal_gap": self.entry_batal_gap,
            "entry_ditolak_biaya": self.entry_ditolak_biaya,
            "tolak_biaya_per_kode": dict(sorted(self.tolak_biaya_per_kode.items())),
            "entry_ditolak_sizing": self.entry_ditolak_sizing,
            "tolak_sizing_per_kode": dict(sorted(self.tolak_sizing_per_kode.items())),
        }


class Backtester:
    """Simulasi bar-by-bar di atas satu Pipeline (satu simbol, satu TFPlan, satu horizon).

    Tidak mengubah cara Arbiter memutuskan; hanya mensimulasikan hasil eksekusi verdict
    dengan balance yang BERJALAN (bukan balance tetap seperti pada Pipeline biasa).
    """

    def __init__(
        self,
        plane: DataPlane,
        tfplan: TFPlan,
        horizon: str = HORIZON_INTRADAY,
        registry: Optional[Registry] = None,
        balance_awal: float = 1_000.0,
        leverage_maks: float = 20.0,
        margin_konflik: float = 5.0,
        fee_bps: float = FEE_BPS_DEFAULT,
        slippage_bps: float = SLIPPAGE_BPS_DEFAULT,
        saring_biaya: bool = True,
        fee_sl_bps: Optional[float] = None,
        slippage_sl_bps: Optional[float] = None,
        spek: Optional[SpesifikasiKontrak] = None,
        porsi_margin_maks: float = 0.5,
    ):
        # Pipeline dipakai HANYA untuk membangun KonteksEvaluasi dan memanggil Arbiter;
        # sizing riil dihitung ulang di sini per bar dari balance yang berjalan.
        self.pipeline = Pipeline(
            plane, tfplan, horizon, registry, balance_awal, leverage_maks, margin_konflik
        )
        self.leverage_maks = float(leverage_maks)
        # PARITAS ENGINE: sizing backtest memakai jalur yang sama dengan live
        # (Risk -> Notional -> Margin -> Leverage), termasuk pembulatan tick/step
        # bila spesifikasi kontrak tersedia.
        self.spek = spek or SpesifikasiKontrak(
            simbol=str(getattr(plane, "simbol", "") or ""),
            leverage_maks_simbol=float(leverage_maks),
        )
        self.porsi_margin_maks = float(porsi_margin_maks)
        self.ditolak_sizing = 0
        self.tolak_sizing_per_kode: Dict[str, int] = {}
        self.fee_bps = float(fee_bps)
        self.slippage_bps = float(slippage_bps)
        # Bila tidak ditentukan: kaki SL memakai taker + slippage, KECUALI pemanggil
        # sengaja menjalankan mode tanpa biaya (fee/slippage 0) untuk diagnostik.
        self.fee_sl_bps = (
            float(fee_sl_bps)
            if fee_sl_bps is not None
            else (FEE_SL_BPS_DEFAULT if float(fee_bps) > 0 else 0.0)
        )
        self.slippage_sl_bps = (
            float(slippage_sl_bps)
            if slippage_sl_bps is not None
            else (SLIPPAGE_SL_BPS_DEFAULT if float(fee_bps) > 0 else 0.0)
        )
        self.balance_awal = float(balance_awal)
        # Gerbang biaya universal (lihat eksekusi/biaya.py). Bisa dimatikan HANYA untuk
        # keperluan diagnostik/pembanding, bukan untuk operasi nyata.
        self.saring_biaya = bool(saring_biaya)
        self.ditolak_biaya = 0
        self.tolak_biaya_per_kode: Dict[str, int] = {}

    # ------------------------------------------------------------------ #

    def _buka_posisi(
        self, v: StrategyVerdict, e: Bars, i: int, balance: float
    ) -> Tuple[Optional[PosisiTerbuka], bool]:
        """Coba buka posisi pada open bar i+1. Kembalikan (posisi_atau_None, batal_gap)."""
        n = len(e)
        if i + 1 >= n:
            return None, False
        open_berikut = float(e.open[i + 1])
        # gap melewati SL sebelum sempat isi -> entry batal (selaras entry_invalidated)
        if v.arah == ARAH_LONG and open_berikut <= v.sl:
            return None, True
        if v.arah != ARAH_LONG and open_berikut >= v.sl:
            return None, True
        if self.saring_biaya:
            metrik = evaluasi_verdict(
                v,
                fee_bps=self.fee_bps,
                slippage_bps=self.slippage_bps,
                fee_sl_bps=self.fee_sl_bps,
                slippage_sl_bps=self.slippage_sl_bps,
            )
            if not metrik.lolos:
                self.ditolak_biaya += 1
                kode = metrik.kode or "tidak_diketahui"
                self.tolak_biaya_per_kode[kode] = self.tolak_biaya_per_kode.get(kode, 0) + 1
                return None, False
        entry_isi = _harga_slip(open_berikut, v.arah, "masuk", self.slippage_bps)
        posisi_rencana = rencana_posisi(
            simbol=self.spek.simbol,
            arah=v.arah,
            balance=balance,
            entry=entry_isi,
            sl=v.sl,
            tp_utama=v.tps[0].harga if v.tps else None,
            spek=self.spek,
            porsi_margin_maks=self.porsi_margin_maks,
            leverage_batas_operator=self.leverage_maks,
            fee_masuk_bps=self.fee_bps,
            fee_sl_bps=self.fee_sl_bps,
            slippage_sl_bps=self.slippage_sl_bps,
        )
        qty = posisi_rencana.qty
        if not posisi_rencana.layak or qty <= 0:
            self.ditolak_sizing += 1
            kode = posisi_rencana.kode or "tidak_diketahui"
            self.tolak_sizing_per_kode[kode] = self.tolak_sizing_per_kode.get(kode, 0) + 1
            return None, False
        entry_isi = posisi_rencana.entry
        biaya_masuk = entry_isi * qty * (self.fee_bps / 10_000.0)
        # urutkan TP dari yang PALING DEKAT ke entry menuju yang paling jauh, tidak
        # mengandalkan urutan yang diberikan strategi.
        tps_terurut = sorted(v.tps, key=lambda tp: abs(tp.harga - entry_isi))
        if self.saring_biaya:
            # Batasi jumlah TP -> membatasi jumlah fill -> membatasi ongkos.
            pasangan = batas_tp_efektif(tps_terurut, FILL_KELUAR_MAKS)
            tps_terurut = tuple(
                TargetTP(harga=h, porsi=min(1.0, max(1e-9, p))) for h, p in pasangan
            )
        tps = tuple(_TPState(tp=tp, qty=qty * tp.porsi) for tp in tps_terurut)
        posisi = PosisiTerbuka(
            strategy_id=v.strategy_id,
            kelompok=v.kelompok,
            arah=v.arah,
            verdict_entry=float(v.entry),
            entry_isi=entry_isi,
            sl=float(v.sl),
            ts_sinyal=int(v.ts_sinyal or e.ts_tutup(i)),
            ts_entry=int(e.ts[i + 1]),
            qty_awal=qty,
            balance_sebelum=balance,
            tps=tps,
            qty_sisa=qty,
            biaya=biaya_masuk,
        )
        return posisi, False

    def _pnl_qty(self, posisi: PosisiTerbuka, harga_keluar: float, qty: float) -> float:
        if posisi.arah == ARAH_LONG:
            return (harga_keluar - posisi.entry_isi) * qty
        return (posisi.entry_isi - harga_keluar) * qty

    def _rangkai_trade(
        self,
        posisi: PosisiTerbuka,
        ts_keluar: int,
        harga_keluar_akhir: float,
        alasan: str,
        balance_baru: float,
    ) -> TradeTutup:
        """Rangkai satu TradeTutup dari akumulasi seluruh fill (TP parsial + penutupan akhir).

        pnl_bersih_total dihitung dari SELISIH balance sebelum posisi dibuka vs sesudah
        posisi tertutup penuh, supaya benar walau ada beberapa TP parsial sebelumnya.
        """
        pnl_bersih_total = balance_baru - posisi.balance_sebelum
        pnl_kotor_total = pnl_bersih_total + posisi.biaya
        return TradeTutup(
            strategy_id=posisi.strategy_id,
            kelompok=posisi.kelompok,
            arah=posisi.arah,
            ts_sinyal=posisi.ts_sinyal,
            ts_entry=posisi.ts_entry,
            ts_keluar=ts_keluar,
            entry_rencana=posisi.verdict_entry,
            entry_isi=posisi.entry_isi,
            sl=posisi.sl,
            keluar_terakhir=harga_keluar_akhir,
            alasan_keluar=alasan,
            qty_awal=posisi.qty_awal,
            isi_tp=tuple(posisi.isi_tp),
            biaya=posisi.biaya,
            pnl_kotor=pnl_kotor_total,
            pnl_bersih=pnl_bersih_total,
            balance_sebelum=posisi.balance_sebelum,
            balance_sesudah=balance_baru,
        )

    def _tutup_penuh(
        self, posisi: PosisiTerbuka, ts: int, harga_acuan: float, alasan: str, balance: float
    ) -> Tuple[TradeTutup, float]:
        """Tutup SELURUH qty_sisa pada harga acuan (SL atau close akhir data)."""
        # SL keluar lewat STOP_MARKET -> taker + slippage. Penutupan lain (akhir data)
        # diasumsikan limit post-only -> maker tanpa slippage.
        taker = alasan == "sl"
        slip = self.slippage_sl_bps if taker else self.slippage_bps
        fee = self.fee_sl_bps if taker else self.fee_bps
        harga_keluar = _harga_slip(harga_acuan, posisi.arah, "keluar", slip)
        qty = posisi.qty_sisa
        pnl_kotor = self._pnl_qty(posisi, harga_keluar, qty)
        biaya_keluar = harga_keluar * qty * (fee / 10_000.0)
        posisi.biaya += biaya_keluar
        balance_baru = balance + (pnl_kotor - biaya_keluar)
        trade = self._rangkai_trade(posisi, ts, harga_keluar, alasan, balance_baru)
        return trade, balance_baru

    def _proses_bar_posisi(
        self, posisi: PosisiTerbuka, e: Bars, i: int, balance: float
    ) -> Tuple[Optional[PosisiTerbuka], Optional[TradeTutup], float]:
        h, l = float(e.high[i]), float(e.low[i])
        ts = int(e.ts[i])
        arah = posisi.arah

        # PESIMISME INTRABAR: SL diperiksa lebih dulu dan memenangkan ambiguitas.
        kena_sl = (l <= posisi.sl) if arah == ARAH_LONG else (h >= posisi.sl)
        if kena_sl:
            trade, balance = self._tutup_penuh(posisi, ts, posisi.sl, "sl", balance)
            return None, trade, balance

        for st in posisi.tps:
            if st.kena:
                continue
            kena_tp = (h >= st.tp.harga) if arah == ARAH_LONG else (l <= st.tp.harga)
            if not kena_tp:
                break  # TP lebih jauh tak mungkin kena bila yang lebih dekat belum
            st.kena = True
            harga_keluar = _harga_slip(st.tp.harga, arah, "keluar", self.slippage_bps)
            qty_tp = min(st.qty, posisi.qty_sisa)
            if qty_tp <= 0:
                continue
            pnl_kotor = self._pnl_qty(posisi, harga_keluar, qty_tp)
            biaya_keluar = harga_keluar * qty_tp * (self.fee_bps / 10_000.0)
            posisi.biaya += biaya_keluar
            posisi.isi_tp.append((ts, harga_keluar, qty_tp))
            posisi.qty_sisa -= qty_tp
            balance += pnl_kotor - biaya_keluar

        if posisi.qty_sisa <= 1e-15:
            harga_akhir = posisi.isi_tp[-1][1] if posisi.isi_tp else posisi.entry_isi
            trade = self._rangkai_trade(posisi, ts, harga_akhir, "tp", balance)
            return None, trade, balance
        return posisi, None, balance

    # ------------------------------------------------------------------ #

    def jalankan(self, mulai: Optional[int] = None, akhir: Optional[int] = None) -> HasilBacktest:
        pipe = self.pipeline
        e = pipe.plane.bars(pipe.tfplan.entry_tf)
        warmup = max([s.warmup for s in pipe.registry.semua()] or [50])
        a = warmup if mulai is None else max(mulai, 0)
        b = len(e) if akhir is None else min(akhir, len(e))

        self.ditolak_biaya = 0
        self.tolak_biaya_per_kode = {}
        self.ditolak_sizing = 0
        self.tolak_sizing_per_kode = {}
        balance = self.balance_awal
        posisi: Optional[PosisiTerbuka] = None
        trades: List[TradeTutup] = []
        kurva: List[Tuple[int, float]] = []
        bar_dievaluasi = 0
        entry_batal_gap = 0
        boleh_entry = boleh_auto_entry(pipe.horizon)

        i = a
        while i < b:
            if posisi is not None:
                posisi, trade, balance = self._proses_bar_posisi(posisi, e, i, balance)
                if trade is not None:
                    trades.append(trade)
                kurva.append((int(e.ts[i]), balance))
                i += 1
                continue

            bar_dievaluasi += 1
            if boleh_entry and i + 1 < b:
                ctx = pipe.konteks(i)
                keputusan = pipe.arbiter.putuskan(ctx)
                v = keputusan.verdict
                if v is not None:
                    posisi_baru, batal = self._buka_posisi(v, e, i, balance)
                    if batal:
                        entry_batal_gap += 1
                    elif posisi_baru is not None:
                        posisi = posisi_baru
            kurva.append((int(e.ts[i]), balance))
            i += 1

        if posisi is not None:
            ts_akhir = int(e.ts[b - 1])
            trade, balance = self._tutup_penuh(
                posisi, ts_akhir, float(e.close[b - 1]), "akhir_data", balance
            )
            trades.append(trade)
            if kurva:
                kurva[-1] = (kurva[-1][0], balance)
            else:
                kurva.append((ts_akhir, balance))

        return HasilBacktest(
            trades=tuple(trades),
            kurva_ekuitas=tuple(kurva),
            balance_awal=self.balance_awal,
            balance_akhir=balance,
            bar_dievaluasi=bar_dievaluasi,
            entry_batal_gap=entry_batal_gap,
            entry_ditolak_biaya=self.ditolak_biaya,
            tolak_biaya_per_kode=dict(self.tolak_biaya_per_kode),
            entry_ditolak_sizing=self.ditolak_sizing,
            tolak_sizing_per_kode=dict(self.tolak_sizing_per_kode),
        )
