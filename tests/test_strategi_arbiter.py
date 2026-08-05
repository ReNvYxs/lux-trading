"""Uji registry strategi, aturan pembobotan/ambang/konflik arah, dan pipeline end-to-end."""
from __future__ import annotations

from typing import Optional

import pytest

from lux_modul import sintetis
from lux_modul.arbiter import (
    ALASAN_KONFLIK_ARAH,
    ALASAN_SEMUA_DI_BAWAH_AMBANG,
    ALASAN_TERPILIH,
    Arbiter,
)
from lux_modul.data import DataPlane
from lux_modul.fitur.store import FeatureStore
from lux_modul.kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SWING,
    KELOMPOK_POLA,
    MODE_SIGNAL_ONLY,
    StrategyVerdict,
    TargetTP,
    TFPlan,
)
from lux_modul.pipeline import Pipeline
from lux_modul.strategi import KELAS_BAWAAN, Registry, registry_bawaan, registry_dari
from lux_modul.strategi.basis import Strategi


# --------------------------- cakupan registry --------------------------- #


def test_cakupan_minimum_strategi():
    reg = registry_bawaan()
    assert len(reg) >= 8
    assert len(reg.kelompok_terwakili()) >= 3


def test_ada_single_tf_dan_multi_tf():
    reg = registry_bawaan()
    single = [s for s in reg.semua() if not s.multi_tf]
    multi = [s for s in reg.semua() if s.multi_tf]
    assert single and multi


def test_setiap_strategi_punya_ambang_dan_sumber():
    for kelas in KELAS_BAWAAN:
        s = kelas()
        assert 0 < s.ambang <= 100
        assert s.required_roles["entry"] is True
        assert len(s.sumber) >= 2, f"{s.id} kurang referensi"


# ----------------------- strategi palsu untuk arbiter -------------------- #


class _Palsu(Strategi):
    kelompok = KELOMPOK_POLA
    warmup = 1

    def __init__(self, sid: str, arah: str, skor: float, ambang: float = 60.0, meledak: bool = False):
        self.id = sid
        self.ambang = ambang
        self._arah = arah
        self._skor = skor
        self._meledak = meledak
        self.dipanggil = 0
        super().__init__()

    def evaluasi(self, ctx) -> Optional[StrategyVerdict]:
        self.dipanggil += 1
        if self._meledak:
            raise RuntimeError("strategi ini sengaja gagal")
        entry = 100.0
        sl = 98.0 if self._arah == ARAH_LONG else 102.0
        tp = 106.0 if self._arah == ARAH_LONG else 94.0
        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=self._arah,
            skor=self._skor,
            ambang=self.ambang,
            entry=entry,
            sl=sl,
            tps=(TargetTP(tp, 1.0),),
            level=entry,
            invalidation=sl,
            tfs_used=("5m",),
        )


def _ctx():
    plane = DataPlane.dari_dasar(sintetis.bars_acak(80), ())
    return plane.konteks_pada(60, TFPlan("5m"), HORIZON_INTRADAY, FeatureStore())


def test_semua_strategi_dievaluasi_tanpa_short_circuit():
    a = _Palsu("a_menang_duluan", ARAH_LONG, 95.0)
    b = _Palsu("b_biasanya_tertutup", ARAH_LONG, 70.0)
    c = _Palsu("c_paling_akhir", ARAH_LONG, 65.0)
    reg = Registry([a, b, c])
    hasil = reg.evaluasi_semua(_ctx())
    assert a.dipanggil == b.dipanggil == c.dipanggil == 1
    assert len(hasil.verdicts) == 3


def test_urutan_pendaftaran_tidak_memengaruhi_pemenang():
    v1 = [_Palsu("z", ARAH_LONG, 90.0), _Palsu("a", ARAH_LONG, 70.0)]
    v2 = [_Palsu("a", ARAH_LONG, 70.0), _Palsu("z", ARAH_LONG, 90.0)]
    k1 = Arbiter(Registry(v1)).putuskan(_ctx())
    k2 = Arbiter(Registry(v2)).putuskan(_ctx())
    assert k1.verdict.strategy_id == k2.verdict.strategy_id == "z"


def test_galat_satu_strategi_tidak_menjatuhkan_yang_lain():
    reg = Registry([_Palsu("rusak", ARAH_LONG, 90.0, meledak=True), _Palsu("sehat", ARAH_LONG, 70.0)])
    k = Arbiter(reg).putuskan(_ctx())
    assert k.verdict.strategy_id == "sehat"
    assert any(p.kode == "galat_internal" for p in k.ditolak)


def test_tidak_ada_entry_bila_semua_di_bawah_ambang():
    reg = Registry([_Palsu("x", ARAH_LONG, 59.9, ambang=60.0), _Palsu("y", ARAH_SHORT, 40.0, ambang=60.0)])
    k = Arbiter(reg).putuskan(_ctx())
    assert k.verdict is None
    assert k.alasan == ALASAN_SEMUA_DI_BAWAH_AMBANG


def test_ambang_bersifat_ketat_lebih_besar():
    reg = Registry([_Palsu("tepat_di_ambang", ARAH_LONG, 60.0, ambang=60.0)])
    assert Arbiter(reg).putuskan(_ctx()).verdict is None
    reg2 = Registry([_Palsu("sedikit_di_atas", ARAH_LONG, 60.01, ambang=60.0)])
    assert Arbiter(reg2).putuskan(_ctx()).verdict is not None


def test_skor_tertinggi_yang_dieksekusi():
    reg = Registry([_Palsu("a", ARAH_LONG, 72.0), _Palsu("b", ARAH_LONG, 88.0), _Palsu("c", ARAH_LONG, 61.0)])
    k = Arbiter(reg).putuskan(_ctx())
    assert k.alasan == ALASAN_TERPILIH
    assert k.verdict.strategy_id == "b"


def test_konflik_arah_selisih_kecil_membatalkan_entry():
    reg = Registry([_Palsu("long", ARAH_LONG, 80.0), _Palsu("short", ARAH_SHORT, 76.5)])
    k = Arbiter(reg).putuskan(_ctx())
    assert k.verdict is None
    assert k.alasan == ALASAN_KONFLIK_ARAH
    assert k.catatan["selisih_skor"] == pytest.approx(3.5)


def test_konflik_arah_selisih_besar_tetap_entry():
    reg = Registry([_Palsu("long", ARAH_LONG, 85.0), _Palsu("short", ARAH_SHORT, 70.0)])
    k = Arbiter(reg).putuskan(_ctx())
    assert k.verdict is not None and k.verdict.arah == ARAH_LONG


def test_konflik_hanya_dihitung_antar_yang_lolos_ambang():
    reg = Registry(
        [_Palsu("long", ARAH_LONG, 80.0), _Palsu("short_gagal", ARAH_SHORT, 55.0, ambang=60.0)]
    )
    k = Arbiter(reg).putuskan(_ctx())
    assert k.verdict is not None and k.verdict.strategy_id == "long"


def test_strategi_multi_tf_ditolak_bila_rencana_single_tf():
    reg = registry_dari(["macd_rsi_trendbreak", "smc_ob_fvg"])
    hasil = reg.evaluasi_semua(_ctx())
    assert {p.kode for p in hasil.penolakan} == {"peran_tf_tak_terpenuhi"}


# ---------------------- strategi nyata atas data sintetis ---------------- #


def _cari_verdict(strategi_id: str, bars, tfplan: TFPlan, plane=None):
    plane = plane or DataPlane(({bars.tf: bars}))
    reg = registry_dari([strategi_id])
    s = reg.ambil(strategi_id)
    for i in range(max(s.warmup, 2), len(plane.bars(tfplan.entry_tf))):
        ctx = plane.konteks_pada(i, tfplan, HORIZON_INTRADAY, FeatureStore())
        hasil = reg.evaluasi_semua(ctx)
        if hasil.verdicts:
            return hasil.verdicts[0], i
    return None, None


def test_double_top_terdeteksi_pada_pola_sintetis():
    bars = sintetis.bars_double_top()
    v, _ = _cari_verdict("double_top", bars, TFPlan("5m"))
    assert v is not None, "double_top tidak terdeteksi pada pola sintetisnya sendiri"
    assert v.arah == ARAH_SHORT
    assert v.sl > v.entry
    assert all(t.harga < v.entry for t in v.tps)
    assert v.rr_tp1 > 0


def test_double_bottom_terdeteksi_pada_pola_sintetis():
    bars = sintetis.bars_double_bottom()
    v, _ = _cari_verdict("double_bottom", bars, TFPlan("5m"))
    assert v is not None
    assert v.arah == ARAH_LONG
    assert v.sl < v.entry
    assert all(t.harga > v.entry for t in v.tps)


def test_breakout_volume_terdeteksi():
    bars = sintetis.bars_range_breakout()
    v, _ = _cari_verdict("breakout_volume", bars, TFPlan("5m"))
    assert v is not None
    assert v.arah == ARAH_LONG
    assert v.evidence["volume_rasio"] >= 1.5


def test_semua_strategi_bisa_dijalankan_tanpa_galat():
    """Smoke test: seluruh strategi jalan atas data acak tanpa melempar galat."""
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(700), ("15m", "1h"))
    reg = registry_bawaan()
    plan = TFPlan("5m", ("15m", "1h"))
    galat = []
    for i in range(250, 700, 7):
        ctx = plane.konteks_pada(i, plan, HORIZON_INTRADAY, FeatureStore())
        hasil = reg.evaluasi_semua(ctx)
        galat += [p for p in hasil.penolakan if p.kode == "galat_internal"]
    assert not galat, galat[:3]


def test_setiap_verdict_punya_entry_sl_tp_valid():
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(900, seed=5), ("15m", "1h"))
    reg = registry_bawaan()
    plan = TFPlan("5m", ("15m", "1h"))
    jumlah = 0
    for i in range(250, 900, 3):
        ctx = plane.konteks_pada(i, plan, HORIZON_INTRADAY, FeatureStore())
        for v in reg.evaluasi_semua(ctx).verdicts:
            jumlah += 1
            assert v.entry > 0 and v.tps
            assert (v.sl < v.entry) if v.arah == ARAH_LONG else (v.sl > v.entry)
            assert 0 <= v.skor <= 100
            assert sum(t.porsi for t in v.tps) <= 1.0 + 1e-9
    assert jumlah > 0, "tidak ada satupun verdict pada data uji"


# ------------------------------- pipeline -------------------------------- #


def test_pipeline_end_to_end_single_tf():
    bars = sintetis.bars_double_top()
    plane = DataPlane({bars.tf: bars})
    pipe = Pipeline(plane, TFPlan("5m"), HORIZON_INTRADAY, registry_dari(["double_top"]), balance=500.0)
    hasil, stat = pipe.jalankan_rentang()
    assert stat.bar_dievaluasi > 0
    assert hasil, "pipeline single-TF tidak menghasilkan entry apa pun"
    h = hasil[0]
    assert h.verdict.strategy_id == "double_top"
    assert h.sizing is not None and h.sizing.qty > 0
    assert h.rencana is not None and h.rencana.jumlah_slice >= 1


def test_pipeline_end_to_end_multi_tf():
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(1200, seed=9), ("15m",))
    pipe = Pipeline(
        plane,
        TFPlan("5m", ("15m",)),
        HORIZON_INTRADAY,
        registry_dari(["smc_ob_fvg", "macd_rsi_trendbreak"]),
        balance=1000.0,
    )
    hasil, stat = pipe.jalankan_rentang()
    assert stat.bar_dievaluasi > 0
    assert hasil, "pipeline multi-TF tidak menghasilkan entry apa pun"
    v = hasil[0].verdict
    assert len(v.tfs_used) >= 2


def test_swing_hanya_sinyal_tanpa_order():
    bars = sintetis.bars_double_top()
    plane = DataPlane({bars.tf: bars})
    pipe = Pipeline(plane, TFPlan("5m"), HORIZON_SWING, registry_dari(["double_top"]), balance=500.0)
    hasil, stat = pipe.jalankan_rentang()
    assert hasil
    for h in hasil:
        assert h.mode == MODE_SIGNAL_ONLY
        assert h.sinyal is not None
        assert h.rencana is None and h.sizing is None
    assert stat.entry == 0 and stat.sinyal_saja == len(hasil)


def test_tidak_ada_dominasi_satu_strategi_pada_data_panjang():
    """Bukti anti-cacat lama: lebih dari satu strategi berhasil memunculkan kandidat."""
    plane = DataPlane.dari_dasar(sintetis.bars_tren_naik(1500, seed=21), ("15m", "1h"))
    pipe = Pipeline(plane, TFPlan("5m", ("15m", "1h")), HORIZON_INTRADAY, balance=1000.0)
    _, stat = pipe.jalankan_rentang()
    assert len(stat.kandidat_per_strategi) >= 3, stat.kandidat_per_strategi
