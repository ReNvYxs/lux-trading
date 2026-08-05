"""Perekat lintas lapis: data -> fitur -> strategi -> pembobotan -> eksekusi.

Pipeline TIDAK menambahkan logika sinyal apa pun. Ia hanya merangkai lapis yang ada
sesuai urutan kontrak, lalu menerapkan gerbang mode (swing = signal_only).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .arbiter.pemilih import Arbiter, Keputusan
from .data.plane import DataPlane, KonteksEvaluasi
from .eksekusi.biaya import evaluasi_verdict
from .eksekusi.ice_breaker import RencanaEksekusi, plan_execution
from .eksekusi.mode import Sinyal, boleh_auto_entry, mode_untuk
from .eksekusi.risiko import Sizing, ukuran_posisi
from .eksekusi.spesifikasi import RencanaPosisi, SpesifikasiKontrak, rencana_posisi
from .fitur.store import FeatureStore
from .kontrak import HORIZON_INTRADAY, MODE_SIGNAL_ONLY, StrategyVerdict, TFPlan
from .strategi import Registry, registry_bawaan


@dataclass(frozen=True)
class HasilBar:
    """Keluaran lengkap satu candle."""

    ts: int
    indeks: int
    keputusan: Keputusan
    mode: str
    sinyal: Optional[Sinyal] = None
    sizing: Optional[Sizing] = None
    # Rencana posisi presisi: Risk -> Notional -> Margin -> Leverage optimal.
    posisi: Optional[RencanaPosisi] = None
    rencana: Optional[RencanaEksekusi] = None
    # Kode penolakan gerbang biaya (None bila lolos / tidak diuji).
    tolak_biaya: Optional[str] = None
    # Kode penolakan sizing/leverage (mis. notional < minimum exchange).
    tolak_sizing: Optional[str] = None

    @property
    def verdict(self) -> Optional[StrategyVerdict]:
        return self.keputusan.verdict

    def ringkas(self) -> Dict[str, object]:
        return {
            "ts": self.ts,
            "indeks": self.indeks,
            "mode": self.mode,
            "keputusan": self.keputusan.ringkas(),
            "sizing": None if self.sizing is None else self.sizing.__dict__,
            "posisi": None if self.posisi is None else self.posisi.ringkas(),
            "rencana": None if self.rencana is None else self.rencana.ringkas(),
            "tolak_biaya": self.tolak_biaya,
            "tolak_sizing": self.tolak_sizing,
        }


@dataclass
class StatistikJalan:
    bar_dievaluasi: int = 0
    bar_dengan_kandidat: int = 0
    entry: int = 0
    sinyal_saja: int = 0
    entry_ditolak_biaya: int = 0
    konflik: int = 0
    kandidat_per_strategi: Dict[str, int] = field(default_factory=dict)
    menang_per_strategi: Dict[str, int] = field(default_factory=dict)
    penolakan_per_kode: Dict[str, int] = field(default_factory=dict)

    def ringkas(self) -> Dict[str, object]:
        return {
            "bar_dievaluasi": self.bar_dievaluasi,
            "bar_dengan_kandidat": self.bar_dengan_kandidat,
            "entry": self.entry,
            "sinyal_saja": self.sinyal_saja,
            "entry_ditolak_biaya": self.entry_ditolak_biaya,
            "konflik_arah": self.konflik,
            "kandidat_per_strategi": dict(sorted(self.kandidat_per_strategi.items())),
            "menang_per_strategi": dict(sorted(self.menang_per_strategi.items())),
            "penolakan_per_kode": dict(sorted(self.penolakan_per_kode.items())),
        }


class Pipeline:
    def __init__(
        self,
        plane: DataPlane,
        tfplan: TFPlan,
        horizon: str = HORIZON_INTRADAY,
        registry: Optional[Registry] = None,
        balance: float = 100.0,
        leverage_maks: float = 20.0,
        margin_konflik: float = 5.0,
        saring_biaya: bool = True,
        spek: Optional[SpesifikasiKontrak] = None,
        rr_bersih_min: Optional[float] = None,
        porsi_margin_maks: float = 0.5,
    ):
        if not plane.dukung(tfplan):
            hilang = [t for t in tfplan.semua_tf() if not plane.punya(t)]
            raise KeyError(f"DataPlane tidak punya TF: {hilang}")
        self.plane = plane
        self.tfplan = tfplan
        self.horizon = horizon
        self.mode = mode_untuk(horizon)
        self.registry = registry if registry is not None else registry_bawaan()
        self.arbiter = Arbiter(self.registry, margin_konflik=margin_konflik)
        self.balance = float(balance)
        self.leverage_maks = float(leverage_maks)
        # Gerbang biaya universal: menolak rencana yang ongkosnya tidak masuk akal
        # dibanding risiko 1R. Berlaku sama untuk SEMUA strategi.
        self.saring_biaya = bool(saring_biaya)
        # Spesifikasi kontrak (tick/step/min notional/bracket leverage). Bila tidak
        # diberikan, dipakai spek generik: pembulatan mati, batas leverage operator.
        self.spek = spek or SpesifikasiKontrak(
            simbol=str(getattr(plane, "simbol", "") or ""),
            leverage_maks_simbol=float(leverage_maks),
        )
        self.rr_bersih_min = rr_bersih_min
        self.porsi_margin_maks = float(porsi_margin_maks)

    # ------------------------------------------------------------------ #

    def konteks(self, i: int, fitur: Optional[FeatureStore] = None) -> KonteksEvaluasi:
        return self.plane.konteks_pada(i, self.tfplan, self.horizon, fitur)

    def jalankan(self, i: int) -> HasilBar:
        """Proses satu bar TF entry (indeks absolut pada TF entry)."""
        ctx = self.konteks(i, FeatureStore())
        keputusan = self.arbiter.putuskan(ctx)
        hasil = HasilBar(
            ts=ctx.ts_sekarang, indeks=i, keputusan=keputusan, mode=self.mode
        )
        v = keputusan.verdict
        if v is None:
            return hasil

        if not boleh_auto_entry(self.horizon):
            # swing -> hanya sinyal, TIDAK ADA order dan TIDAK ADA sizing eksekusi
            return HasilBar(
                ts=hasil.ts,
                indeks=i,
                keputusan=keputusan,
                mode=MODE_SIGNAL_ONLY,
                sinyal=Sinyal(self.plane.simbol, self.horizon, v),
            )

        if self.saring_biaya:
            metrik = evaluasi_verdict(v)
            if not metrik.lolos:
                return HasilBar(
                    ts=hasil.ts,
                    indeks=i,
                    keputusan=keputusan,
                    mode=self.mode,
                    tolak_biaya=metrik.kode,
                )

        sizing = ukuran_posisi(
            balance=self.balance,
            entry=v.entry,
            sl=v.sl,
            leverage_maks=self.leverage_maks,
        )
        # Sizing presisi + leverage otomatis. Leverage adalah HASIL dari notional
        # dan margin, bukan input yang menentukan risiko.
        posisi = rencana_posisi(
            simbol=self.plane.simbol,
            arah=v.arah,
            balance=self.balance,
            entry=v.entry,
            sl=v.sl,
            tp_utama=v.tps[0].harga if v.tps else None,
            spek=self.spek,
            porsi_margin_maks=self.porsi_margin_maks,
            leverage_batas_operator=self.leverage_maks,
            rr_bersih_min=self.rr_bersih_min,
        )
        if not posisi.layak or posisi.qty <= 0:
            return HasilBar(
                ts=hasil.ts,
                indeks=i,
                keputusan=keputusan,
                mode=self.mode,
                sizing=sizing,
                posisi=posisi,
                tolak_sizing=posisi.kode,
            )
        rencana = plan_execution(
            simbol=self.plane.simbol,
            arah=v.arah,
            qty=posisi.qty,
            harga=posisi.entry,
            sl=posisi.sl,
        )
        return HasilBar(
            ts=hasil.ts,
            indeks=i,
            keputusan=keputusan,
            mode=self.mode,
            sizing=sizing,
            posisi=posisi,
            rencana=rencana,
        )

    def jalankan_rentang(
        self, mulai: Optional[int] = None, akhir: Optional[int] = None
    ) -> Tuple[List[HasilBar], StatistikJalan]:
        """Jalankan pipeline untuk rentang bar. Bukan backtest PnL - ini pemindaian sinyal."""
        e = self.plane.bars(self.tfplan.entry_tf)
        warmup = max([s.warmup for s in self.registry.semua()] or [50])
        a = warmup if mulai is None else max(mulai, 1)
        b = len(e) if akhir is None else min(akhir, len(e))
        hasil: List[HasilBar] = []
        stat = StatistikJalan()
        for i in range(a, b):
            h = self.jalankan(i)
            stat.bar_dievaluasi += 1
            k = h.keputusan
            if k.kandidat:
                stat.bar_dengan_kandidat += 1
            for v in k.kandidat:
                stat.kandidat_per_strategi[v.strategy_id] = (
                    stat.kandidat_per_strategi.get(v.strategy_id, 0) + 1
                )
            for p in k.ditolak:
                stat.penolakan_per_kode[p.kode] = stat.penolakan_per_kode.get(p.kode, 0) + 1
            if k.alasan == "konflik_arah_saling_meniadakan":
                stat.konflik += 1
            if k.verdict is not None:
                stat.menang_per_strategi[k.verdict.strategy_id] = (
                    stat.menang_per_strategi.get(k.verdict.strategy_id, 0) + 1
                )
                if h.mode == MODE_SIGNAL_ONLY:
                    stat.sinyal_saja += 1
                elif h.tolak_biaya is not None:
                    stat.entry_ditolak_biaya += 1
                    stat.penolakan_per_kode[h.tolak_biaya] = (
                        stat.penolakan_per_kode.get(h.tolak_biaya, 0) + 1
                    )
                else:
                    stat.entry += 1
                hasil.append(h)
        return hasil, stat
