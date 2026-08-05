"""Uji pemindai likuiditas, rencana TF strategy-driven, dan mesin multi-pair.

Pagar arsitektural yang ditegakkan (perintah operator 3-4 Agu 2026):
- sistem TIDAK BOLEH BTC-centric: pemindaian wajib menghasilkan 25..50 pair
- timeframe entry mengikuti strategi (STF & MTF), bukan dipaksa 15m
- tidak ada daftar pair hardcode permanen

Semua uji memakai fake client deterministik - tanpa jaringan sama sekali.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.mesin_multi import MesinError, MesinMultiPair
from lux_modul.pemindai import (
    KriteriaLikuiditas,
    PemindaiError,
    PemindaiPasar,
    peringkat_dari_ticker,
)
from lux_modul.rencana_tf import (
    ENTRY_TF_HORIZON,
    RencanaTFError,
    cakupan_strategi,
    konteks_untuk,
    rencana_dari_registry,
    uraikan_daftar_tf,
)
from lux_modul.strategi import registry_bawaan

JUMLAH_SIMBOL = 70


def _nama(i: int) -> str:
    return f"C{i:03d}USDT"


class FakeClient:
    """Bursa palsu: 70 perpetual USDT + beberapa simbol yang harus ditolak."""

    def __init__(self, tipis: int = 0, spread_lebar: int = 0):
        self.tipis = tipis
        self.spread_lebar = spread_lebar
        self.panggil_exchange_info = 0
        self.panggil_ticker = 0
        self.panggil_buku = 0

    def exchange_info(self, simbol=None):
        self.panggil_exchange_info += 1
        simbols = []
        for i in range(JUMLAH_SIMBOL):
            simbols.append(
                {
                    "symbol": _nama(i),
                    "status": "TRADING",
                    "contractType": "PERPETUAL",
                    "quoteAsset": "USDT",
                    "pricePrecision": 2,
                    "quantityPrecision": 3,
                    "filters": [
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                        {"filterType": "MIN_NOTIONAL", "notional": "5"},
                    ],
                }
            )
        simbols += [
            {"symbol": "OLDUSDT", "status": "BREAK", "contractType": "PERPETUAL", "quoteAsset": "USDT", "filters": []},
            {"symbol": "XUSDT_250926", "status": "TRADING", "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT", "filters": []},
            {"symbol": "ETHBUSD", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "BUSD", "filters": []},
        ]
        return {"symbols": simbols}

    def ticker_24jam(self, simbol=None):
        self.panggil_ticker += 1
        baris = []
        for i in range(JUMLAH_SIMBOL):
            besar = i >= self.tipis
            baris.append(
                {
                    "symbol": _nama(i),
                    "quoteVolume": str(1_000_000_000.0 / (i + 1) if besar else 1_000_000.0),
                    "count": str(2_000_000 // (i + 1) if besar else 100),
                    "lastPrice": str(100.0 + i),
                }
            )
        baris.append({"symbol": "ETHBUSD", "quoteVolume": "9e12", "count": "9999999", "lastPrice": "1"})
        return baris

    def buku_order(self, simbol, limit=5):
        self.panggil_buku += 1
        i = int(simbol[1:4])
        harga = 100.0 + i
        lebar = 0.5 if i < self.spread_lebar else 0.001
        bid = harga - lebar / 2
        ask = harga + lebar / 2
        return {
            "bids": [[f"{bid:.4f}", "500"] for _ in range(limit)],
            "asks": [[f"{ask:.4f}", "500"] for _ in range(limit)],
        }

    def waktu_server(self):
        return 1_700_000_000_000

    def harga_sekarang(self, simbol):
        return 100.0

    def bracket_leverage(self, simbol=None):
        return [{"symbol": simbol or "C000USDT", "brackets": [{"notionalCap": 50000, "initialLeverage": 50}]}]


KRITERIA_UJI = KriteriaLikuiditas(
    min_pair=25,
    maks_pair=50,
    min_quote_volume_24j=5_000_000.0,
    min_jumlah_trade_24j=1_000,
    maks_spread_bps=10.0,
    min_kedalaman_usd=1_000.0,
    kandidat_buku=60,
    kedalaman_limit=5,
)


def test_kriteria_menolak_konfigurasi_single_pair():
    with pytest.raises(ValueError):
        KriteriaLikuiditas(min_pair=1, maks_pair=1)


def test_kriteria_menolak_maks_lebih_kecil_dari_min():
    with pytest.raises(ValueError):
        KriteriaLikuiditas(min_pair=30, maks_pair=10)


def test_pindai_memilih_25_sampai_50_pair():
    hasil = PemindaiPasar(FakeClient(), KRITERIA_UJI).pindai()
    assert 25 <= len(hasil.pair) <= 50
    assert len(set(hasil.simbol)) == len(hasil.simbol)


def test_pindai_menolak_simbol_tidak_layak():
    hasil = PemindaiPasar(FakeClient(), KRITERIA_UJI).pindai()
    nama = set(hasil.simbol)
    assert "OLDUSDT" not in nama
    assert "XUSDT_250926" not in nama
    assert "ETHBUSD" not in nama
    assert hasil.ditolak


def test_pindai_tidak_memakai_daftar_hardcode():
    a = PemindaiPasar(FakeClient(), KRITERIA_UJI).pindai().simbol
    b = PemindaiPasar(FakeClient(tipis=30), KRITERIA_UJI).pindai().simbol
    assert set(a) != set(b)


def test_pindai_gagal_bila_pair_layak_kurang_dari_dua():
    with pytest.raises(PemindaiError):
        PemindaiPasar(FakeClient(tipis=JUMLAH_SIMBOL - 1), KRITERIA_UJI).pindai()


def test_pair_dengan_spread_lebar_disingkirkan():
    hasil = PemindaiPasar(FakeClient(spread_lebar=20), KRITERIA_UJI).pindai()
    nama = set(hasil.simbol)
    assert not any(_nama(i) in nama for i in range(20))


def test_cache_ttl_menghindari_pemindaian_berulang():
    klien = FakeClient()
    detak = {"ms": 0}
    p = PemindaiPasar(klien, KRITERIA_UJI, jam=lambda: detak["ms"])
    p.pindai()
    n = klien.panggil_exchange_info
    p.pindai()
    assert klien.panggil_exchange_info == n
    detak["ms"] += int(KRITERIA_UJI.ttl_detik * 1000) + 1_000
    p.pindai()
    assert klien.panggil_exchange_info == n + 1


def test_peringkat_dari_ticker_deterministik_dan_terurut():
    baris = [
        {"symbol": "A", "quoteVolume": "1000000000", "count": "1000000"},
        {"symbol": "B", "quoteVolume": "10000000", "count": "10000"},
        {"symbol": "C", "quoteVolume": "100000", "count": "100"},
    ]
    hasil = peringkat_dari_ticker(baris, KRITERIA_UJI)
    assert [s for s, _ in hasil] == ["A", "B", "C"]
    assert hasil == peringkat_dari_ticker(baris, KRITERIA_UJI)


def test_konteks_untuk_naik_tangga_timeframe():
    assert konteks_untuk("5m", 1) == ("15m",)
    assert konteks_untuk("15m", 2) == ("1h", "4h")
    assert konteks_untuk("1h", 1) == ("4h",)
    assert konteks_untuk("15m", 0) == ()


def test_uraikan_daftar_tf():
    assert uraikan_daftar_tf("5m, 15m ,1h") == ("5m", "15m", "1h")
    assert uraikan_daftar_tf("") == ()


def test_rencana_mengikuti_horizon_bukan_dipaksa_15m():
    reg = registry_bawaan()
    scalp = rencana_dari_registry(reg, "scalping")
    intra = rencana_dari_registry(reg, "intraday")
    assert tuple(r.entry_tf for r in scalp) == ENTRY_TF_HORIZON["scalping"]
    assert tuple(r.entry_tf for r in intra) == ENTRY_TF_HORIZON["intraday"]
    assert any(r.entry_tf != "15m" for r in intra)


def test_rencana_mencakup_strategi_stf_dan_mtf():
    reg = registry_bawaan()
    rencana = rencana_dari_registry(reg, "intraday")
    cakupan = cakupan_strategi(reg, rencana, "intraday")
    assert cakupan["lengkap"] is True
    assert not cakupan.get("tidak_tercakup")
    assert any(r.tfplan.jumlah_konteks > 0 for r in rencana)


def test_entry_tf_kustom_dihormati():
    rencana = rencana_dari_registry(registry_bawaan(), "intraday", entry_tfs=("1h",))
    assert [r.entry_tf for r in rencana] == ["1h"]


def test_entry_tf_tidak_dikenal_ditolak():
    with pytest.raises(RencanaTFError):
        rencana_dari_registry(registry_bawaan(), "intraday", entry_tfs=("7m",))


class FakeRunner:
    def __init__(self, simbol, rencana):
        self.simbol = simbol
        self.rencana = rencana
        self.siklus_dijalankan = 0

    def siklus_sekali(self):
        self.siklus_dijalankan += 1
        return type(
            "S", (), {"bar_baru": False, "galat": None, "hasil_bar": None, "eksekusi_entry": None}
        )()


def _mesin(klien=None, **kw):
    return MesinMultiPair(
        client=klien or FakeClient(),
        kriteria=KRITERIA_UJI,
        horizon="intraday",
        buat_runner=lambda simbol, rencana: FakeRunner(simbol, rencana),
        **kw,
    )


def test_mesin_menyiapkan_banyak_pair_bukan_hanya_btc():
    m = _mesin(maks_runner=1000)
    laporan = m.siapkan()
    pair = {s for s, _ in m.runner}
    assert len(pair) >= 25
    assert laporan["jumlah_runner"] == len(m.runner)
    assert len(laporan["rencana_tf"]) >= 1


def test_mesin_membuat_runner_untuk_tiap_kombinasi_pair_dan_rencana():
    m = _mesin(maks_runner=1000)
    m.siapkan()
    pair = {s for s, _ in m.runner}
    tf = {t for _, t in m.runner}
    assert len(m.runner) == len(pair) * len(tf)
    assert len(tf) == len(m.rencana)


def test_mesin_membatasi_jumlah_runner():
    m = _mesin(maks_runner=12)
    m.siapkan()
    assert len(m.runner) <= 12 + len(m.rencana)


def test_mesin_menolak_pasar_yang_hanya_menyisakan_satu_pair():
    m = _mesin(klien=FakeClient(tipis=JUMLAH_SIMBOL - 1))
    with pytest.raises((MesinError, PemindaiError)):
        m.siapkan()


def test_siklus_menjalankan_semua_runner():
    m = _mesin(maks_runner=60)
    m.siapkan()
    ringkas = m.siklus()
    assert ringkas.jumlah_runner == len(m.runner)
    assert len(ringkas.hasil) == len(m.runner)
    assert all(r.siklus_dijalankan == 1 for r in m.runner.values())
