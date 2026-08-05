"""Regresi untuk bug 4 Agu 2026: scripts/live_run.py memanggil
cfg.daftar_entry_tf(), cfg.daftar_simbol(), dan cfg.kriteria_pindai() pada objek
Konfigurasi, tetapi ketiga metode itu sebelumnya TIDAK didefinisikan sama sekali
di lux_modul/konfigurasi.py. Akibatnya live_run.py pasti crash AttributeError
begitu dijalankan (testnet maupun live, jalur satu-pair maupun multi-pair).

Ditemukan lewat audit pembacaan source code (bukan lewat menjalankan skrip -
sandbox tidak punya akses jaringan ke Binance).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.konfigurasi import Konfigurasi
from lux_modul.pemindai import KriteriaLikuiditas


def _cfg(**override):
    dasar = dict(
        simbol="",
        tf_entry="",
        tf_konteks="",
        horizon="intraday",
        leverage_maks=20.0,
        margin_konflik=5.0,
        interval_poll=15.0,
        balance=100.0,
        maks_siklus=0,
        data_dir="dataset_masuk/ekstrak/data_upload",
        rr_bersih_min=0.0,
        porsi_margin_maks=0.5,
        maks_runner=120,
        maks_posisi=4,
        min_free_margin_pct=0.30,
        pindai_quote="USDT",
        pindai_maks_pair=50,
        pindai_min_pair=25,
        pindai_min_volume=50_000_000.0,
        pindai_min_trade=50_000,
        pindai_maks_spread=6.0,
        pindai_min_kedalaman=25_000.0,
        pindai_ttl=1800,
        pindai_periksa_buku=True,
        telegram_bot_token="",
        telegram_chat_id="",
        telegram_aktif=True,
        telegram_siap=False,
    )
    dasar.update(override)
    return Konfigurasi(**dasar)


def test_daftar_entry_tf_kosong_mengembalikan_tuple_kosong():
    assert _cfg(tf_entry="").daftar_entry_tf() == ()


def test_daftar_entry_tf_dipisah_koma_dan_dibersihkan():
    assert _cfg(tf_entry="15m, 1h ,4h").daftar_entry_tf() == ("15m", "1h", "4h")


def test_daftar_simbol_kosong_mengembalikan_tuple_kosong():
    assert _cfg(simbol="").daftar_simbol() == ()


def test_daftar_simbol_dipisah_koma_dan_huruf_besar():
    assert _cfg(simbol="btcusdt, ethusdt").daftar_simbol() == ("BTCUSDT", "ETHUSDT")


def test_kriteria_pindai_mengembalikan_kriterialikuiditas_dari_ambang_env():
    cfg = _cfg(
        pindai_quote="USDT",
        pindai_min_pair=25,
        pindai_maks_pair=50,
        pindai_min_volume=50_000_000.0,
        pindai_min_trade=50_000,
        pindai_maks_spread=6.0,
        pindai_min_kedalaman=25_000.0,
        pindai_ttl=1800,
        pindai_periksa_buku=True,
    )
    k = cfg.kriteria_pindai()
    assert isinstance(k, KriteriaLikuiditas)
    assert k.quote_aset == "USDT"
    assert k.min_pair == 25
    assert k.maks_pair == 50
    assert k.min_quote_volume_24j == 50_000_000.0
    assert k.min_jumlah_trade_24j == 50_000
    assert k.maks_spread_bps == 6.0
    assert k.min_kedalaman_usd == 25_000.0
    assert k.periksa_buku is True
    assert k.ttl_detik == 1800.0


def test_kriteria_pindai_quote_kosong_default_usdt():
    cfg = _cfg(pindai_quote="")
    assert cfg.kriteria_pindai().quote_aset == "USDT"
