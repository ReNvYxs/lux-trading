"""Demo end-to-end di atas data sintetis (tanpa dataset asli, tanpa jaringan).

Membuktikan empat hal yang jadi kriteria selesai fase implementasi:
1. Pipeline jalan dari data mentah -> verdict lengkap (entry/SL/TP).
2. Satu strategi single-TF dan satu strategi multi-TF sama-sama bisa menang.
3. Pembobotan + ambang + aturan konflik arah berfungsi.
4. Risk management + ice-breaker terpasang di jalur eksekusi.

Jalankan:  python scripts/demo_sintetis.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)

from lux_modul import sintetis  # noqa: E402
from lux_modul.arbiter import Arbiter  # noqa: E402
from lux_modul.data import DataPlane  # noqa: E402
from lux_modul.eksekusi import (  # noqa: E402
    IceBreakerExecutor,
    plan_execution,
    ringkas_kurva,
    ukuran_posisi,
)
from lux_modul.kontrak import (  # noqa: E402
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SWING,
    KELOMPOK_POLA,
    StrategyVerdict,
    TargetTP,
    TFPlan,
)
from lux_modul.pipeline import Pipeline  # noqa: E402
from lux_modul.strategi import Registry, registry_bawaan, registry_dari  # noqa: E402
from lux_modul.strategi.basis import Strategi  # noqa: E402


def judul(t: str) -> None:
    print("\n" + "=" * 78)
    print(t)
    print("=" * 78)


def bagian_1_single_tf() -> None:
    judul("1. SINGLE-TF end-to-end: double_top di 5m (context = 0)")
    bars = sintetis.bars_double_top()
    plane = DataPlane({bars.tf: bars})
    pipe = Pipeline(plane, TFPlan("5m"), HORIZON_INTRADAY, registry_dari(["double_top"]), balance=500.0)
    hasil, stat = pipe.jalankan_rentang()
    print(f"bar dievaluasi: {stat.bar_dievaluasi}, entry: {stat.entry}")
    h = hasil[0]
    v = h.verdict
    print(json.dumps(v.ringkas(), indent=2, ensure_ascii=False))
    print("sizing :", h.sizing)
    print("rencana:", json.dumps(h.rencana.ringkas(), ensure_ascii=False))


def bagian_2_multi_tf() -> None:
    judul("2. MULTI-TF end-to-end: smc_ob_fvg 5m + konteks 15m (context = 1)")
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(1200, seed=9), ("15m", "1h"))
    pipe = Pipeline(
        plane,
        TFPlan("5m", ("15m",)),
        HORIZON_INTRADAY,
        registry_dari(["smc_ob_fvg", "macd_rsi_trendbreak"]),
        balance=2_000.0,
    )
    hasil, stat = pipe.jalankan_rentang()
    print(f"bar dievaluasi: {stat.bar_dievaluasi}, entry: {stat.entry}")
    print("menang per strategi:", stat.menang_per_strategi)
    v = hasil[0].verdict
    print(json.dumps(v.ringkas(), indent=2, ensure_ascii=False))
    print("TF yang dipakai:", v.tfs_used)


def bagian_3_distribusi() -> None:
    judul("3. Tidak ada strategi yang mendominasi (registry penuh, 12 strategi)")
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(1500, seed=21), ("15m", "1h"))
    pipe = Pipeline(plane, TFPlan("5m", ("15m", "1h")), HORIZON_INTRADAY, balance=1_000.0)
    _, stat = pipe.jalankan_rentang()
    print("kandidat per strategi (berapa kali MUNCUL, bukan menang):")
    for k, n in sorted(stat.kandidat_per_strategi.items(), key=lambda kv: -kv[1]):
        print(f"   {k:<24} {n}")
    print("menang per strategi:")
    for k, n in sorted(stat.menang_per_strategi.items(), key=lambda kv: -kv[1]):
        print(f"   {k:<24} {n}")
    print(f"bar konflik arah (no entry): {stat.konflik}")
    print(f"total entry: {stat.entry}")


class _Sintetik(Strategi):
    """Strategi tiruan untuk mendemonstrasikan aturan arbiter secara deterministik."""

    kelompok = KELOMPOK_POLA
    warmup = 1

    def __init__(self, sid: str, arah: str, skor: float, ambang: float = 60.0):
        self.id = sid
        self.ambang = ambang
        self._arah = arah
        self._skor = skor
        super().__init__()

    def evaluasi(self, ctx):
        sl = 98.0 if self._arah == ARAH_LONG else 102.0
        tp = 106.0 if self._arah == ARAH_LONG else 94.0
        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=self._arah,
            skor=self._skor,
            ambang=self.ambang,
            entry=100.0,
            sl=sl,
            tps=(TargetTP(tp, 1.0),),
            level=100.0,
            invalidation=sl,
            tfs_used=("5m",),
        )


def bagian_4_arbiter() -> None:
    judul("4. Aturan pembobotan / ambang / konflik arah")
    plane = DataPlane.dari_dasar(sintetis.bars_acak(80), ())
    ctx = plane.konteks_pada(60, TFPlan("5m"), HORIZON_INTRADAY)

    kasus = {
        "skor tertinggi menang": [
            _Sintetik("a", ARAH_LONG, 72),
            _Sintetik("b", ARAH_LONG, 88),
            _Sintetik("c", ARAH_LONG, 61),
        ],
        "semua di bawah ambang -> no entry": [
            _Sintetik("a", ARAH_LONG, 59.9),
            _Sintetik("b", ARAH_SHORT, 40),
        ],
        "konflik arah selisih 3.5 -> saling meniadakan": [
            _Sintetik("long", ARAH_LONG, 80),
            _Sintetik("short", ARAH_SHORT, 76.5),
        ],
        "konflik arah selisih 15 -> tetap entry": [
            _Sintetik("long", ARAH_LONG, 85),
            _Sintetik("short", ARAH_SHORT, 70),
        ],
    }
    for nama, strategi in kasus.items():
        k = Arbiter(Registry(strategi)).putuskan(ctx)
        pilih = k.verdict.strategy_id if k.verdict else "TIDAK ADA ENTRY"
        print(f"   {nama:<48} -> {pilih:<16} ({k.alasan})")


def bagian_5_swing() -> None:
    judul("5. Swing = signal_only (tidak ada order, tidak ada sizing)")
    bars = sintetis.bars_double_top()
    plane = DataPlane({bars.tf: bars})
    pipe = Pipeline(plane, TFPlan("5m"), HORIZON_SWING, registry_dari(["double_top"]), balance=500.0)
    hasil, stat = pipe.jalankan_rentang()
    h = hasil[0]
    print(f"mode: {h.mode}, sinyal: {'ada' if h.sinyal else 'tidak'}, "
          f"rencana order: {h.rencana}, sizing: {h.sizing}")
    print(f"entry otomatis: {stat.entry}, sinyal saja: {stat.sinyal_saja}")


def bagian_6_risiko() -> None:
    judul("6. Risk management: kurva risk% / risk$")
    for r in ringkas_kurva():
        print(f"   balance ${r['balance']:>12,.2f}  risk% {r['risk_pct']*100:>6.3f}%  risk$ ${r['risk_usd']:.4f}")
    print("\n   catatan: $0.20 adalah LANTAI, bukan nilai flat -> risk$ naik seiring saldo")


def bagian_7_icebreaker() -> None:
    judul("7. Ice-breaker: slice TWAP+iceberg, visible_qty terkirim, non-blocking")
    kecil = plan_execution("BTCUSDT", ARAH_LONG, qty=0.005, harga=60_000.0)
    print(f"   order kecil  (notional ${kecil.notional:,.0f}): icebreaker={kecil.memakai_icebreaker}, "
          f"slice={kecil.jumlah_slice}  <- baseline tidak berubah")

    besar = plan_execution("BTCUSDT", ARAH_LONG, qty=1.5, harga=60_000.0, sl=58_800.0)
    print(f"   order besar  (notional ${besar.notional:,.0f}): icebreaker={besar.memakai_icebreaker}, "
          f"slice={besar.jumlah_slice}")

    keadaan = {"harga": 60_000.0, "n": 0}
    terkirim = []

    async def kirim(payload):
        keadaan["n"] += 1
        terkirim.append(payload)
        if keadaan["n"] == 3:
            keadaan["harga"] = 58_700.0  # harga tembus SL di tengah eksekusi
        return {"status": "NEW"}

    async def tidur_cepat(_d):
        return None

    ex = IceBreakerExecutor(kirim, harga_kini=lambda: keadaan["harga"], tidur=tidur_cepat)
    hasil = asyncio.run(ex.jalankan(besar))
    print(f"   payload slice pertama: {terkirim[0]}")
    print(f"   slice terkirim: {len(hasil.terkirim)}, dibatalkan: {len(hasil.dibatalkan)}, "
          f"alasan: {hasil.alasan_batal}")

    s = ukuran_posisi(balance=10.0, entry=60_000.0, sl=59_400.0, leverage_maks=20)
    print(f"   sizing modal kecil ($10): risk% {s.risk_pct*100:.3f}% risk$ ${s.risk_usd:.4f} "
          f"qty {s.qty:.8f} notional ${s.notional:.4f}")


def main() -> int:
    reg = registry_bawaan()
    judul("LUX - DEMO MODUL TRADING MULTI-STRATEGI (data sintetis)")
    print(f"strategi terdaftar : {len(reg)}")
    print(f"kelompok teknik    : {', '.join(reg.kelompok_terwakili())}")
    for s in reg.semua():
        jenis = f"multi-TF (context={s.konteks_dibutuhkan})" if s.multi_tf else "single-TF"
        print(f"   {s.id:<24} {s.kelompok:<20} {jenis:<24} ambang={s.ambang}")
    bagian_1_single_tf()
    bagian_2_multi_tf()
    bagian_3_distribusi()
    bagian_4_arbiter()
    bagian_5_swing()
    bagian_6_risiko()
    bagian_7_icebreaker()
    judul("SELESAI - seluruh kriteria fase implementasi didemonstrasikan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
