"""Uji konfigurasi terpusat (.env) + notifier Telegram.

Semua uji di sini TIDAK menyentuh jaringan: notifier diuji lewat fungsi murni
`format_siklus` dan lewat penggantian metode `_panggil` dengan fake.
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi.kredensial import (
    ENV_LIVE_KEY,
    ENV_LIVE_KONFIRMASI,
    ENV_LIVE_SECRET,
    ENV_TESTNET_KEY,
    ENV_TESTNET_SECRET,
    FRASA_KONFIRMASI_LIVE,
)
from lux_modul.konfigurasi import (
    ENV_HORIZON,
    ENV_LEVERAGE_MAKS,
    ENV_SIMBOL,
    ENV_TF_KONTEKS,
    ENV_TG_AKTIF,
    ENV_TG_CHAT_ID,
    ENV_TG_TOKEN,
    KonfigurasiError,
    muat_berkas_env,
    muat_konfigurasi,
    samarkan,
    status_kredensial,
    urai_env_teks,
)
from lux_modul.notifikasi.telegram import (
    NotifierNonaktif,
    NotifierTelegram,
    buat_notifier,
    format_siklus,
)

SEMUA_ENV_UJI = (
    ENV_TESTNET_KEY,
    ENV_TESTNET_SECRET,
    ENV_LIVE_KEY,
    ENV_LIVE_SECRET,
    ENV_LIVE_KONFIRMASI,
    ENV_TG_TOKEN,
    ENV_TG_CHAT_ID,
    ENV_TG_AKTIF,
    ENV_SIMBOL,
    ENV_TF_KONTEKS,
    ENV_HORIZON,
    ENV_LEVERAGE_MAKS,
)


def _bersihkan_env():
    for nama in SEMUA_ENV_UJI:
        os.environ.pop(nama, None)


# ---------------------------------------------------------------- parser .env


def test_urai_env_menangani_format_umum():
    teks = (
        "# komentar\n"
        "\n"
        "KOSONG=\n"
        "SEDERHANA=nilai\n"
        "  SPASI  =  ada spasi  \n"
        'KUTIP_GANDA="abc def"\n'
        "KUTIP_TUNGGAL='xyz'\n"
        "export DIEKSPOR=1\n"
        "KOMENTAR_BELAKANG=nilai  # ini catatan\n"
        "TANPA_SAMA_DENGAN\n"
    )
    hasil = urai_env_teks(teks)
    assert hasil["SEDERHANA"] == "nilai"
    assert hasil["SPASI"] == "ada spasi"
    assert hasil["KUTIP_GANDA"] == "abc def"
    assert hasil["KUTIP_TUNGGAL"] == "xyz"
    assert hasil["DIEKSPOR"] == "1"
    assert hasil["KOMENTAR_BELAKANG"] == "nilai"
    assert hasil["KOSONG"] == ""
    assert "TANPA_SAMA_DENGAN" not in hasil


def test_env_shell_menang_atas_berkas_env():
    """Variabel yang sudah diset di shell TIDAK boleh ditimpa berkas .env."""
    _bersihkan_env()
    os.environ[ENV_SIMBOL] = "ETHUSDT"
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8") as f:
        f.write(f"{ENV_SIMBOL}=BTCUSDT\n{ENV_TF_KONTEKS}=1h\n")
        path = f.name
    try:
        diterapkan = muat_berkas_env(path)
        assert ENV_SIMBOL not in diterapkan  # tidak ditimpa
        assert os.environ[ENV_SIMBOL] == "ETHUSDT"
        assert os.environ[ENV_TF_KONTEKS] == "1h"  # yang kosong tetap diisi
    finally:
        os.unlink(path)
        _bersihkan_env()


def test_muat_berkas_env_tidak_galat_bila_berkas_tidak_ada():
    assert muat_berkas_env("/tmp/berkas-env-yang-pasti-tidak-ada-12345") == {}


# ------------------------------------------------------------- Konfigurasi


def test_konfigurasi_default_aman():
    _bersihkan_env()
    cfg = muat_konfigurasi(muat_env=False)
    # KEBIJAKAN 4 Agu 2026: tanpa default BTCUSDT/15m -> engine memindai pasar
    # dan mengikuti kontrak strategi.
    assert cfg.simbol == ""
    assert cfg.tf_entry == ""
    assert cfg.daftar_simbol() == ()
    assert cfg.daftar_entry_tf() == ()
    assert cfg.mode_multi_pair() is True
    assert cfg.kriteria_pindai().min_pair >= 25
    assert cfg.daftar_tf_konteks() == ()  # single-TF
    assert cfg.horizon == "intraday"
    assert cfg.balance is None  # tarik dari akun
    assert cfg.telegram_lengkap() is False  # tanpa token = nonaktif


def test_konfigurasi_membaca_env_dan_multi_tf():
    _bersihkan_env()
    os.environ[ENV_SIMBOL] = "ethusdt"
    os.environ[ENV_TF_KONTEKS] = "1h, 4h"
    os.environ[ENV_LEVERAGE_MAKS] = "10"
    try:
        cfg = muat_konfigurasi(muat_env=False)
        assert cfg.simbol == "ETHUSDT"  # dinormalkan huruf besar
        assert cfg.daftar_tf_konteks() == ("1h", "4h")
        assert cfg.leverage_maks == 10.0
    finally:
        _bersihkan_env()


def test_horizon_swing_ditolak_karena_tidak_boleh_auto_entry():
    _bersihkan_env()
    os.environ[ENV_HORIZON] = "swing"
    try:
        with pytest.raises(KonfigurasiError):
            muat_konfigurasi(muat_env=False)
    finally:
        _bersihkan_env()


def test_nilai_angka_tidak_sah_ditolak():
    _bersihkan_env()
    os.environ[ENV_LEVERAGE_MAKS] = "bukan-angka"
    try:
        with pytest.raises(KonfigurasiError):
            muat_konfigurasi(muat_env=False)
    finally:
        _bersihkan_env()


def test_ringkas_tidak_membocorkan_token():
    _bersihkan_env()
    os.environ[ENV_TG_TOKEN] = "123456789:RAHASIA-SEKALI-JANGAN-BOCOR"
    os.environ[ENV_TG_CHAT_ID] = "999"
    try:
        cfg = muat_konfigurasi(muat_env=False)
        teks = str(cfg.ringkas())
        assert "RAHASIA-SEKALI" not in teks
        assert "..." in teks
    finally:
        _bersihkan_env()


def test_samarkan():
    assert samarkan("") == "(kosong)"
    assert samarkan("pendek") == "***"
    assert samarkan("abcdefghijkl") == "abcd...kl"


# ------------------------------------------------------- status kredensial


def test_status_kredensial_melaporkan_kesiapan_terpisah():
    _bersihkan_env()
    os.environ[ENV_TESTNET_KEY] = "kunci-testnet-panjang"
    os.environ[ENV_TESTNET_SECRET] = "rahasia-testnet-panjang"
    try:
        st = status_kredensial(muat_konfigurasi(muat_env=False))
        assert st.testnet_siap is True
        assert st.live_siap is False  # terpisah total
        assert st.live_gerbang_env_siap is False
        assert "kunci-testnet-panjang" not in str(st.detail)  # disamarkan
    finally:
        _bersihkan_env()


def test_status_kredensial_memperingatkan_kunci_testnet_sama_dengan_live():
    _bersihkan_env()
    sama = "KUNCI-YANG-SAMA-PERSIS"
    os.environ[ENV_TESTNET_KEY] = sama
    os.environ[ENV_TESTNET_SECRET] = "secret-a"
    os.environ[ENV_LIVE_KEY] = sama
    os.environ[ENV_LIVE_SECRET] = "secret-b"
    try:
        st = status_kredensial(muat_konfigurasi(muat_env=False))
        assert any("BAHAYA" in w for w in st.peringatan)
    finally:
        _bersihkan_env()


def test_status_kredensial_menandai_gerbang_live_terbuka():
    _bersihkan_env()
    os.environ[ENV_LIVE_KONFIRMASI] = FRASA_KONFIRMASI_LIVE
    try:
        st = status_kredensial(muat_konfigurasi(muat_env=False))
        assert st.live_gerbang_env_siap is True
        assert any("CATATAN" in w for w in st.peringatan)
    finally:
        _bersihkan_env()


# ------------------------------------------------------------ notifikasi TG


def test_buat_notifier_tanpa_token_mengembalikan_nonaktif():
    _bersihkan_env()
    cfg = muat_konfigurasi(muat_env=False)
    notifier = buat_notifier(cfg)
    assert isinstance(notifier, NotifierNonaktif)
    assert notifier.aktif is False
    assert notifier.kirim("apa pun") is False  # no-op, tidak melempar


def test_buat_notifier_lengkap_mengembalikan_telegram():
    _bersihkan_env()
    os.environ[ENV_TG_TOKEN] = "123:abc"
    os.environ[ENV_TG_CHAT_ID] = "42"
    try:
        notifier = buat_notifier(muat_konfigurasi(muat_env=False))
        assert isinstance(notifier, NotifierTelegram)
        assert notifier.chat_id == "42"
    finally:
        _bersihkan_env()


def test_saklar_telegram_aktif_nol_membisukan():
    _bersihkan_env()
    os.environ[ENV_TG_TOKEN] = "123:abc"
    os.environ[ENV_TG_CHAT_ID] = "42"
    os.environ[ENV_TG_AKTIF] = "0"
    try:
        assert isinstance(buat_notifier(muat_konfigurasi(muat_env=False)), NotifierNonaktif)
    finally:
        _bersihkan_env()


def test_notifier_butuh_token_dan_chat_id():
    with pytest.raises(ValueError):
        NotifierTelegram("", "42")
    with pytest.raises(ValueError):
        NotifierTelegram("123:abc", "")


def test_kirim_menelan_galat_jaringan_dan_tidak_menjatuhkan_proses():
    notifier = NotifierTelegram("123:abc", "42")

    def _meledak(metode, data):
        raise OSError("jaringan mati")

    notifier._panggil = _meledak
    assert notifier.kirim("halo") is False  # tidak melempar keluar


def test_kirim_memotong_pesan_sangat_panjang():
    notifier = NotifierTelegram("123:abc", "42")
    tercatat = {}

    def _rekam(metode, data):
        tercatat["teks"] = data["text"]
        return {"ok": True}

    notifier._panggil = _rekam
    assert notifier.kirim("x" * 9000) is True
    assert len(tercatat["teks"]) <= 4000


def test_format_siklus_sepi_tidak_mengirim_apa_apa():
    assert format_siklus({"ts_server": 1, "bar_baru": False, "hasil_bar": None}) == ""


def test_format_siklus_melaporkan_eksekusi_dan_sl():
    teks = format_siklus(
        {
            "ts_server": 1,
            "bar_baru": True,
            "hasil_bar": {"pemenang": "vwap_reclaim", "skor": 72, "mode": "auto_entry"},
            "eksekusi_entry": {"qty_terisi": 0.5, "terkirim": 3, "dibatalkan": 0, "alasan_batal": None},
            "order_sl": {"type": "STOP_MARKET", "stopPrice": 100.0},
        },
        simbol="BTCUSDT",
        mode="testnet",
    )
    assert "BTCUSDT" in teks
    assert "vwap_reclaim" in teks
    assert "qty_terisi=0.5" in teks
    assert "STOP_MARKET" in teks


def test_format_siklus_melaporkan_galat():
    teks = format_siklus({"ts_server": 1, "bar_baru": True, "galat": "koneksi putus"}, mode="live")
    assert "GALAT: koneksi putus" in teks
