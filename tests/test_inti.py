"""Uji kontrak, fitur, risiko, ice-breaker, dan mode eksekusi."""
from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from lux_modul import sintetis
from lux_modul.data import DataPlane, resample
from lux_modul.eksekusi import (
    IceBreakerExecutor,
    ModeTerlarang,
    boleh_auto_entry,
    calculate_dynamic_risk,
    entry_invalidated,
    pastikan_boleh_eksekusi,
    plan_execution,
    risiko_usd,
    ukuran_posisi,
)
from lux_modul.fitur import dasar
from lux_modul.kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    HORIZON_INTRADAY,
    HORIZON_SCALPING,
    HORIZON_SWING,
    Bars,
    StrategyVerdict,
    TargetTP,
    TFPlan,
)


# ------------------------------- kontrak ------------------------------- #


def test_bars_menolak_ts_tidak_menaik():
    with pytest.raises(ValueError):
        Bars("5m", np.array([2, 1]), *[np.array([1.0, 1.0])] * 5)


def test_tfplan_konteks_wajib_lebih_besar():
    TFPlan("5m", ("1h",))
    with pytest.raises(ValueError):
        TFPlan("1h", ("5m",))
    with pytest.raises(ValueError):
        TFPlan("5m", ("1h", "1h"))


def test_tfplan_single_tf():
    assert TFPlan("5m").single_tf
    assert not TFPlan("5m", ("1h",)).single_tf


def test_verdict_menolak_sl_di_sisi_salah():
    with pytest.raises(ValueError):
        StrategyVerdict(
            strategy_id="x",
            kelompok="pola_klasik",
            arah=ARAH_LONG,
            skor=70,
            ambang=60,
            entry=100,
            sl=101,  # SL di atas entry untuk LONG -> salah
            tps=(TargetTP(110, 1.0),),
            level=100,
            invalidation=101,
            tfs_used=("5m",),
        )


def test_verdict_rr_dan_lolos_ambang():
    v = StrategyVerdict(
        strategy_id="x",
        kelompok="pola_klasik",
        arah=ARAH_LONG,
        skor=70,
        ambang=60,
        entry=100,
        sl=95,
        tps=(TargetTP(110, 0.5), TargetTP(115, 0.5)),
        level=100,
        invalidation=95,
        tfs_used=("5m",),
    )
    assert v.lolos_ambang
    assert v.rr_tp1 == pytest.approx(2.0)
    assert v.rr_utama == pytest.approx(3.0)


# -------------------------------- data --------------------------------- #


def test_resample_5m_ke_15m_konsisten():
    b = sintetis.bars_acak(300, tf="5m")
    r = resample(b, "15m")
    assert len(r) == len(b) // 3
    assert r.high[0] == pytest.approx(max(b.high[:3]))
    assert r.low[0] == pytest.approx(min(b.low[:3]))
    assert r.close[0] == pytest.approx(b.close[2])
    assert r.volume[0] == pytest.approx(sum(b.volume[:3]))


def test_resample_membuang_lilin_parsial():
    b = sintetis.bars_acak(301, tf="5m")
    r = resample(b, "15m")
    assert len(r) == 100  # sisa 1 bar dibuang


def test_konteks_tidak_bocor_ke_masa_depan():
    dasar_bars = sintetis.bars_acak(600, tf="5m")
    plane = DataPlane.dari_dasar(dasar_bars, ("15m", "1h"))
    plan = TFPlan("5m", ("15m", "1h"))
    for i in (100, 233, 599):
        ctx = plane.konteks_pada(i, plan, HORIZON_INTRADAY)
        assert len(ctx.entry) == i + 1
        for tf, kb in ctx.konteks.items():
            if len(kb):
                # setiap lilin konteks WAJIB sudah tutup pada ts_tutup bar entry
                assert kb.ts_tutup(len(kb) - 1) <= ctx.ts_sekarang


# -------------------------------- fitur -------------------------------- #


def test_ema_dan_sma_warmup_nan():
    x = np.arange(1, 51, dtype=float)
    assert np.isnan(dasar.sma(x, 10)[:9]).all()
    assert not math.isnan(dasar.sma(x, 10)[9])
    assert np.isnan(dasar.ema(x, 10)[:9]).all()


def test_rsi_rentang_dan_ekstrem():
    naik = np.arange(1, 100, dtype=float)
    r = dasar.rsi(naik, 14)
    sah = r[~np.isnan(r)]
    assert sah.min() >= 0 and sah.max() <= 100
    assert sah[-1] == pytest.approx(100.0)


def test_atr_positif():
    b = sintetis.bars_acak(200)
    a = dasar.atr(b.high, b.low, b.close, 14)
    assert np.nanmin(a) > 0


def test_fitur_tidak_melihat_masa_depan():
    """Nilai indikator pada indeks i tidak berubah bila data setelah i dihapus."""
    b = sintetis.bars_acak(400)
    i = 300
    penuh = {
        "ema": dasar.ema(b.close, 50)[i],
        "rsi": dasar.rsi(b.close, 14)[i],
        "atr": dasar.atr(b.high, b.low, b.close, 14)[i],
        "macd": dasar.macd(b.close)[0][i],
    }
    p = b.hingga_indeks(i)
    potong = {
        "ema": dasar.ema(p.close, 50)[-1],
        "rsi": dasar.rsi(p.close, 14)[-1],
        "atr": dasar.atr(p.high, p.low, p.close, 14)[-1],
        "macd": dasar.macd(p.close)[0][-1],
    }
    for k in penuh:
        assert penuh[k] == pytest.approx(potong[k], rel=1e-12, abs=1e-12)


def test_rolling_max_min():
    x = np.array([1.0, 5.0, 3.0, 2.0, 9.0])
    assert dasar.rolling_max(x, 3)[-1] == 9.0
    assert dasar.rolling_min(x, 3)[-1] == 2.0


# -------------------------------- risiko ------------------------------- #


def test_rumus_modal_kecil_persis():
    for b in (1.0, 5.0, 10.0, 19.99):
        harap = min(0.03, max(0.005, 0.03 * (20.0 / b) ** 0.55))
        assert calculate_dynamic_risk(b) == pytest.approx(harap)


def test_clamp_atas_tiga_persen():
    assert calculate_dynamic_risk(0.5) == pytest.approx(0.03)
    assert calculate_dynamic_risk(19.0) <= 0.03


def test_lantai_20_sen_bukan_nilai_flat():
    """$0.20 hanya lantai: saldo lebih besar menghasilkan risk$ lebih besar."""
    assert risiko_usd(1.0) == pytest.approx(0.20)
    a, b = risiko_usd(10.0), risiko_usd(19.0)
    assert a > 0.20 and b > a


def test_tiered_dan_taper():
    assert calculate_dynamic_risk(50.0) == pytest.approx(0.03)
    assert calculate_dynamic_risk(500.0) == pytest.approx(0.025)
    assert calculate_dynamic_risk(5_000.0) == pytest.approx(0.02)
    assert calculate_dynamic_risk(20_000.0) == pytest.approx(0.015)
    assert calculate_dynamic_risk(80_000.0) == pytest.approx(0.01)
    assert calculate_dynamic_risk(1_000_000.0) < 0.01
    assert calculate_dynamic_risk(10_000_000_000.0) == pytest.approx(0.0025)
    # monotonik tidak naik di atas $20
    titik = [20, 100, 1_000, 10_000, 100_000, 1_000_000]
    nilai = [calculate_dynamic_risk(t) for t in titik]
    assert all(nilai[i] >= nilai[i + 1] for i in range(len(nilai) - 1))


def test_ukuran_posisi_sesuai_jarak_sl():
    s = ukuran_posisi(balance=500.0, entry=100.0, sl=98.0, leverage_maks=20)
    assert s.risk_pct == pytest.approx(0.025)  # tier 100-1000
    assert s.risk_usd == pytest.approx(12.5)  # 2.5% dari 500
    assert s.qty == pytest.approx(6.25)  # 12.5 / 2
    assert s.notional == pytest.approx(625.0)


def test_ukuran_posisi_dibatasi_leverage():
    s = ukuran_posisi(balance=10.0, entry=100.0, sl=99.99, leverage_maks=5)
    assert s.terpotong_oleh == "leverage_maks"
    assert s.notional == pytest.approx(50.0)


def test_ukuran_posisi_menolak_sl_nol():
    with pytest.raises(ValueError):
        ukuran_posisi(balance=100.0, entry=100.0, sl=100.0)


# ------------------------------ ice-breaker ---------------------------- #


def test_order_kecil_tidak_dipecah():
    r = plan_execution("BTCUSDT", ARAH_LONG, qty=0.01, harga=100_000 * 0.001)
    assert not r.memakai_icebreaker
    assert r.jumlah_slice == 1


def test_order_besar_dipecah_dan_qty_terjaga():
    r = plan_execution("BTCUSDT", ARAH_LONG, qty=2.0, harga=50_000.0)
    assert r.memakai_icebreaker
    assert r.jumlah_slice > 1
    assert sum(s.qty for s in r.slices) == pytest.approx(2.0)


def test_parameter_hantu_tidak_dikirim_dan_qty_dari_konfirmasi():
    # Klaim lama BUG LAMA 1 (visible_qty wajib dikirim) terbukti salah.
    # p01: icebergQty diabaikan Binance Futures, dan visible_qty sama
    # sekali bukan parameter Binance. Yang benar diuji di sini: parameter
    # hantu TIDAK dikirim, cid deterministik ADA, dan qty_terisi hanya
    # boleh berasal dari executedQty jawaban bursa.
    r = plan_execution("BTCUSDT", ARAH_SHORT, qty=2.0, harga=50_000.0)
    terkirim = []

    async def kirim(payload):
        terkirim.append(payload)
        return {"orderId": 900 + len(terkirim), "symbol": payload["symbol"],
                "side": payload["side"], "status": "FILLED",
                "clientOrderId": payload.get("newClientOrderId"),
                "origQty": str(payload["quantity"]),
                "executedQty": str(payload["quantity"]),
                "avgPrice": str(payload["price"])}

    async def tidur_cepat(_d):
        return None

    hasil = asyncio.run(
        IceBreakerExecutor(kirim, tidur=tidur_cepat).jalankan(r)
    )
    assert len(terkirim) == r.jumlah_slice
    for p, s in zip(terkirim, r.slices):
        assert "visible_qty" not in p
        assert "icebergQty" not in p
        assert p["newClientOrderId"].startswith("lxs")
        assert 0 < p["quantity"] <= r.qty_total
    assert len(set(p["newClientOrderId"] for p in terkirim)) == r.jumlah_slice
    assert hasil.qty_terisi == pytest.approx(2.0)
    assert hasil.selesai_penuh
    assert hasil.aman


def test_eksekusi_non_blocking():
    """BUG LAMA 2: slice dieksekusi blocking. Sekarang penundaan memakai await."""
    r = plan_execution("BTCUSDT", ARAH_LONG, qty=2.0, harga=50_000.0)
    jejak = []

    async def kirim(payload):
        await asyncio.sleep(0)
        # NEW = order limit post-only sudah diterima bursa tetapi belum
        # terisi. executedQty 0 memang harus terbaca 0, bukan qty penuh.
        return {"orderId": 800, "symbol": payload["symbol"],
                "side": payload["side"], "status": "NEW",
                "clientOrderId": payload.get("newClientOrderId"),
                "origQty": str(payload["quantity"]), "executedQty": "0"}

    async def tidur_palsu(d):
        jejak.append(d)
        await asyncio.sleep(0)

    async def utama():
        ex = IceBreakerExecutor(kirim, tidur=tidur_palsu)
        tugas = asyncio.create_task(ex.jalankan(r))
        # event loop tetap responsif selama eksekusi berjalan
        lain = await asyncio.wait_for(asyncio.sleep(0, result="loop-hidup"), timeout=1)
        return await tugas, lain

    hasil, lain = asyncio.run(utama())
    assert lain == "loop-hidup"
    assert jejak and all(d > 0 for d in jejak)
    assert hasil.selesai_penuh


def test_entry_invalidated_membatalkan_sisa_slice():
    r = plan_execution("BTCUSDT", ARAH_LONG, qty=2.0, harga=50_000.0, sl=49_000.0)
    keadaan = {"harga": 50_000.0, "n": 0}

    async def kirim(payload):
        keadaan["n"] += 1
        if keadaan["n"] == 2:
            keadaan["harga"] = 48_900.0  # harga tembus SL di tengah eksekusi
        return {"orderId": 700 + keadaan["n"], "symbol": payload["symbol"],
                "side": payload["side"], "status": "NEW",
                "clientOrderId": payload.get("newClientOrderId"),
                "origQty": str(payload["quantity"]), "executedQty": "0"}

    async def tidur_cepat(_d):
        return None

    ex = IceBreakerExecutor(kirim, harga_kini=lambda: keadaan["harga"], tidur=tidur_cepat)
    hasil = asyncio.run(ex.jalankan(r))
    assert hasil.alasan_batal == "entry_invalidated"
    assert len(hasil.terkirim) == 2
    assert len(hasil.dibatalkan) == r.jumlah_slice - 2
    assert hasil.qty_terisi < r.qty_total


def test_entry_invalidated_fungsi_murni():
    assert entry_invalidated(ARAH_LONG, 99.0, 100.0)
    assert not entry_invalidated(ARAH_LONG, 101.0, 100.0)
    assert entry_invalidated(ARAH_SHORT, 101.0, 100.0)
    assert not entry_invalidated(ARAH_SHORT, 99.0, 100.0)
    assert not entry_invalidated(ARAH_LONG, 1.0, None)


# --------------------------------- mode -------------------------------- #


def test_mode_per_horizon():
    assert boleh_auto_entry(HORIZON_SCALPING)
    assert boleh_auto_entry(HORIZON_INTRADAY)
    assert not boleh_auto_entry(HORIZON_SWING)
    with pytest.raises(ModeTerlarang):
        pastikan_boleh_eksekusi(HORIZON_SWING)
