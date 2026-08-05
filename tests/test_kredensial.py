"""Uji pemisahan kredensial testnet/live dan gerbang keamanan mode live."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.kredensial import (
    BASE_URL_LIVE,
    BASE_URL_TESTNET,
    ENV_LIVE_KEY,
    ENV_LIVE_KONFIRMASI,
    ENV_LIVE_SECRET,
    ENV_TESTNET_KEY,
    ENV_TESTNET_SECRET,
    FRASA_KONFIRMASI_LIVE,
    KredensialError,
    MODE_LIVE,
    MODE_TESTNET,
    muat_kredensial,
)

_SEMUA_ENV = (ENV_TESTNET_KEY, ENV_TESTNET_SECRET, ENV_LIVE_KEY, ENV_LIVE_SECRET, ENV_LIVE_KONFIRMASI)


class _EnvBersih:
    """Context manager: simpan & bersihkan env kredensial sebelum/sesudah tes."""

    def __enter__(self):
        self._lama = {k: os.environ.get(k) for k in _SEMUA_ENV}
        for k in _SEMUA_ENV:
            os.environ.pop(k, None)
        return self

    def __exit__(self, *a):
        for k, v in self._lama.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_mode_tidak_dikenal_ditolak():
    with _EnvBersih():
        with pytest.raises(KredensialError):
            muat_kredensial("paper")


def test_testnet_tanpa_kredensial_ditolak():
    with _EnvBersih():
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_TESTNET)


def test_testnet_lengkap_lolos_dan_base_url_benar():
    with _EnvBersih():
        os.environ[ENV_TESTNET_KEY] = "tkey123456"
        os.environ[ENV_TESTNET_SECRET] = "tsecret123456"
        k = muat_kredensial(MODE_TESTNET)
        assert k.mode == MODE_TESTNET
        assert k.base_url == BASE_URL_TESTNET
        assert k.api_key == "tkey123456"
        ringkas = k.ringkas()
        assert "tsecret123456" not in str(ringkas)
        assert ringkas["api_key_terlihat"] != k.api_key


def test_live_tanpa_kredensial_ditolak():
    with _EnvBersih():
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_LIVE, konfirmasi_live_cli=True)


def test_live_tanpa_gerbang_cli_ditolak_walau_env_benar():
    with _EnvBersih():
        os.environ[ENV_LIVE_KEY] = "lkey123456"
        os.environ[ENV_LIVE_SECRET] = "lsecret123456"
        os.environ[ENV_LIVE_KONFIRMASI] = FRASA_KONFIRMASI_LIVE
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_LIVE, konfirmasi_live_cli=False)


def test_live_tanpa_gerbang_env_ditolak_walau_cli_true():
    with _EnvBersih():
        os.environ[ENV_LIVE_KEY] = "lkey123456"
        os.environ[ENV_LIVE_SECRET] = "lsecret123456"
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_LIVE, konfirmasi_live_cli=True)


def test_live_gerbang_env_salah_frasa_ditolak():
    with _EnvBersih():
        os.environ[ENV_LIVE_KEY] = "lkey123456"
        os.environ[ENV_LIVE_SECRET] = "lsecret123456"
        os.environ[ENV_LIVE_KONFIRMASI] = "SALAH_FRASA"
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_LIVE, konfirmasi_live_cli=True)


def test_live_dua_gerbang_lolos_sekaligus():
    with _EnvBersih():
        os.environ[ENV_LIVE_KEY] = "lkey123456"
        os.environ[ENV_LIVE_SECRET] = "lsecret123456"
        os.environ[ENV_LIVE_KONFIRMASI] = FRASA_KONFIRMASI_LIVE
        k = muat_kredensial(MODE_LIVE, konfirmasi_live_cli=True)
        assert k.mode == MODE_LIVE
        assert k.base_url == BASE_URL_LIVE


def test_kredensial_testnet_dan_live_identik_ditolak_walau_mode_testnet():
    with _EnvBersih():
        os.environ[ENV_TESTNET_KEY] = "samakey123"
        os.environ[ENV_TESTNET_SECRET] = "tsecret123456"
        os.environ[ENV_LIVE_KEY] = "samakey123"
        os.environ[ENV_LIVE_SECRET] = "lsecret123456"
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_TESTNET)


def test_kredensial_secret_identik_ditolak():
    with _EnvBersih():
        os.environ[ENV_TESTNET_KEY] = "tkey123456"
        os.environ[ENV_TESTNET_SECRET] = "samasecret123"
        os.environ[ENV_LIVE_KEY] = "lkey123456"
        os.environ[ENV_LIVE_SECRET] = "samasecret123"
        os.environ[ENV_LIVE_KONFIRMASI] = FRASA_KONFIRMASI_LIVE
        with pytest.raises(KredensialError):
            muat_kredensial(MODE_LIVE, konfirmasi_live_cli=True)


def test_base_url_testnet_dan_live_berbeda():
    assert BASE_URL_TESTNET != BASE_URL_LIVE
    assert "testnet" in BASE_URL_TESTNET
