"""Uji lux_modul/backtest.py: no-look-ahead, fill di bar berikutnya, pesimisme SL,
multi-TP parsial, fee/slippage, dan penutupan paksa di akhir data."""
from __future__ import annotations

import pytest

from lux_modul import sintetis
from lux_modul.backtest import Backtester
from lux_modul.data import DataPlane, dari_baris
from lux_modul.eksekusi import ukuran_posisi
from lux_modul.kontrak import (
    ARAH_LONG,
    HORIZON_INTRADAY,
    KELOMPOK_POLA,
    StrategyVerdict,
    TargetTP,
    TFPlan,
    tf_ms,
)
from lux_modul.strategi import Registry, Strategi, registry_bawaan

_TS0 = 1_700_000_000_000


def _bars(ohlc, tf: str = "5m", simbol: str = "UJI"):
    d = tf_ms(tf)
    baris = [[_TS0 + i * d, o, h, l, c, 1000.0] for i, (o, h, l, c) in enumerate(ohlc)]
    return dari_baris(tf, baris, simbol)


class _StrategiUji(Strategi):
    """Strategi deterministik: hanya melempar verdict pada indeks bar tertentu.

    Dipakai KHUSUS untuk uji Backtester supaya isi/keluar posisi bisa dihitung
    ulang secara eksak dengan angka bulat, tanpa bergantung pada deteksi pola.
    """

    kelompok = KELOMPOK_POLA
    warmup = 1

    def __init__(self, sid, arah, sl, tps, pada_i, ambang=50.0):
        self.id = sid
        self.ambang = ambang
        self._arah = arah
        self._sl = sl
        self._tps = tps
        self._pada_i = pada_i
        super().__init__()

    def evaluasi(self, ctx):
        if ctx.i != self._pada_i:
            return None
        entry = ctx.harga
        return StrategyVerdict(
            strategy_id=self.id,
            kelompok=self.kelompok,
            arah=self._arah,
            skor=90.0,
            ambang=self.ambang,
            entry=entry,
            sl=self._sl,
            tps=self._tps,
            level=entry,
            invalidation=self._sl,
            tfs_used=("5m",),
        )


def _plane_tunggal(bars):
    return DataPlane({"5m": bars}), TFPlan("5m")


# ---------------------------------------------------------------- test 1 ---


def test_fill_di_open_bar_berikutnya_bukan_harga_sinyal():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 101.5, 100.8, 101.2),
        (101.2, 103.0, 101.0, 102.5),
        (102.5, 111.0, 101.0, 105.0),
    ]
    bars = _bars(ohlc)
    plane, tfplan = _plane_tunggal(bars)
    strat = _StrategiUji("uji_fill", ARAH_LONG, 95.0, (TargetTP(110.0, 1.0),), pada_i=2)
    bt = Backtester(
        plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
        balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
    )
    hasil = bt.jalankan(mulai=0)
    assert len(hasil.trades) == 1
    t = hasil.trades[0]
    assert t.entry_rencana == pytest.approx(100.0)
    assert t.entry_isi == pytest.approx(101.0)  # harga BUKA bar 3, bukan harga sinyal 100.0
    assert t.ts_entry == int(bars.ts[3])
    assert t.alasan_keluar == "tp"
    assert t.keluar_terakhir == pytest.approx(110.0)
    sizing = ukuran_posisi(balance=1000.0, entry=101.0, sl=95.0, leverage_maks=20.0)
    assert t.qty_awal == pytest.approx(sizing.qty)
    pnl_diharapkan = (110.0 - 101.0) * sizing.qty
    assert t.pnl_bersih == pytest.approx(pnl_diharapkan)
    assert hasil.balance_akhir == pytest.approx(1000.0 + pnl_diharapkan)


# ---------------------------------------------------------------- test 2 ---


def test_sl_didahulukan_saat_ambigu_dalam_satu_bar():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 115.0, 90.0, 105.0),  # fill di 101, bar sama menyentuh SL(95) & TP(110)
        (105.0, 106.0, 104.0, 105.5),
    ]
    bars = _bars(ohlc)
    plane, tfplan = _plane_tunggal(bars)
    strat = _StrategiUji("uji_sl_dulu", ARAH_LONG, 95.0, (TargetTP(110.0, 1.0),), pada_i=2)
    bt = Backtester(
        plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
        balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
    )
    hasil = bt.jalankan(mulai=0)
    assert len(hasil.trades) == 1
    t = hasil.trades[0]
    assert t.alasan_keluar == "sl"
    assert t.keluar_terakhir == pytest.approx(95.0)
    assert t.pnl_bersih < 0


# ---------------------------------------------------------------- test 3 ---


def test_gap_melewati_sl_membatalkan_entry():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (90.0, 91.0, 88.0, 89.0),  # open sudah <= sl(95): gap invalidation
        (89.0, 92.0, 87.0, 90.0),
    ]
    bars = _bars(ohlc)
    plane, tfplan = _plane_tunggal(bars)
    strat = _StrategiUji("uji_gap", ARAH_LONG, 95.0, (TargetTP(110.0, 1.0),), pada_i=2)
    bt = Backtester(
        plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
        balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
    )
    hasil = bt.jalankan(mulai=0)
    assert hasil.trades == ()
    assert hasil.entry_batal_gap == 1
    assert hasil.balance_akhir == pytest.approx(1000.0)


# ---------------------------------------------------------------- test 4 ---


def test_multi_tp_menutup_porsi_bertahap():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 102.0, 100.5, 101.5),
        (101.5, 106.0, 101.0, 105.5),
        (105.5, 112.0, 104.0, 108.0),
    ]
    bars = _bars(ohlc)
    plane, tfplan = _plane_tunggal(bars)
    tps = (TargetTP(105.0, 0.5), TargetTP(110.0, 0.5))
    strat = _StrategiUji("uji_multi_tp", ARAH_LONG, 95.0, tps, pada_i=2)
    bt = Backtester(
        plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
        balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
    )
    hasil = bt.jalankan(mulai=0)
    assert len(hasil.trades) == 1
    t = hasil.trades[0]
    assert t.alasan_keluar == "tp"
    assert len(t.isi_tp) == 2
    sizing = ukuran_posisi(balance=1000.0, entry=101.0, sl=95.0, leverage_maks=20.0)
    pnl_diharapkan = 0.5 * sizing.qty * (105.0 - 101.0) + 0.5 * sizing.qty * (110.0 - 101.0)
    assert t.pnl_bersih == pytest.approx(pnl_diharapkan)


# ---------------------------------------------------------------- test 5 ---


def test_fee_dan_slippage_mengurangi_pnl():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 101.5, 100.8, 101.2),
        (101.2, 103.0, 101.0, 102.5),
        (102.5, 111.0, 101.0, 105.0),
    ]
    bars = _bars(ohlc)

    def _jalankan(fee_bps, slippage_bps):
        plane, tfplan = _plane_tunggal(bars)
        strat = _StrategiUji("uji_biaya", ARAH_LONG, 95.0, (TargetTP(110.0, 1.0),), pada_i=2)
        bt = Backtester(
            plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
            balance_awal=1000.0, fee_bps=fee_bps, slippage_bps=slippage_bps,
        )
        return bt.jalankan(mulai=0)

    tanpa_biaya = _jalankan(0.0, 0.0)
    dengan_biaya = _jalankan(5.0, 2.0)
    t0 = tanpa_biaya.trades[0]
    t1 = dengan_biaya.trades[0]
    assert t1.biaya > 0.0
    assert t0.biaya == pytest.approx(0.0)
    assert t1.pnl_bersih < t0.pnl_bersih
    assert t1.pnl_kotor - t1.biaya == pytest.approx(t1.pnl_bersih)
    assert dengan_biaya.balance_akhir < tanpa_biaya.balance_akhir


# ---------------------------------------------------------------- test 6 ---


def test_akhir_data_menutup_posisi_paksa():
    ohlc = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 102.0, 100.5, 101.5),
        (101.5, 103.0, 101.0, 102.0),
        (102.0, 104.0, 101.5, 103.0),
    ]
    bars = _bars(ohlc)
    plane, tfplan = _plane_tunggal(bars)
    # SL dan TP jauh sekali sehingga tak pernah kena sampai data habis
    strat = _StrategiUji("uji_akhir_data", ARAH_LONG, 50.0, (TargetTP(500.0, 1.0),), pada_i=2)
    bt = Backtester(
        plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
        balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
    )
    hasil = bt.jalankan(mulai=0)
    assert len(hasil.trades) == 1
    t = hasil.trades[0]
    assert t.alasan_keluar == "akhir_data"
    assert t.keluar_terakhir == pytest.approx(103.0)
    assert t.ts_keluar == int(bars.ts[-1])


# ---------------------------------------------------------------- test 7 ---


def test_backtest_end_to_end_dengan_registry_bawaan_multi_tf():
    base = sintetis.bars_tren_naik(n=400, tf="5m", seed=11)
    plane = DataPlane.dari_dasar(base, ("15m",))
    tfplan = TFPlan("5m", ("15m",))
    bt = Backtester(plane, tfplan, HORIZON_INTRADAY, registry_bawaan(), balance_awal=500.0)
    hasil = bt.jalankan()
    ringkas = hasil.ringkas()
    assert hasil.bar_dievaluasi > 0
    assert isinstance(ringkas, dict)
    assert hasil.balance_akhir > 0.0


# ---------------------------------------------------------------- test 8 ---


def test_backtest_tidak_bocor_masa_depan():
    dasar = [
        (100, 100.5, 99.5, 100),
        (100, 100.5, 99.5, 100.2),
        (99.8, 100.3, 99.7, 100.0),
        (101.0, 101.5, 100.8, 101.2),
        (101.2, 103.0, 101.0, 102.5),
        (102.5, 111.0, 101.0, 105.0),
    ]
    ekor_liar = [
        (105.0, 500.0, 1.0, 250.0),
        (250.0, 900.0, 10.0, 400.0),
    ]

    def _jalankan(ohlc):
        bars = _bars(ohlc)
        plane, tfplan = _plane_tunggal(bars)
        strat = _StrategiUji(
            "uji_no_lookahead", ARAH_LONG, 95.0, (TargetTP(110.0, 1.0),), pada_i=2
        )
        bt = Backtester(
            plane, tfplan, HORIZON_INTRADAY, Registry([strat]),
            balance_awal=1000.0, fee_bps=0.0, slippage_bps=0.0,
        )
        return bt.jalankan(mulai=0)

    hasil_pendek = _jalankan(dasar)
    hasil_panjang = _jalankan(dasar + ekor_liar)
    assert len(hasil_pendek.trades) == 1
    assert len(hasil_panjang.trades) == 1
    assert hasil_pendek.trades[0] == hasil_panjang.trades[0]
