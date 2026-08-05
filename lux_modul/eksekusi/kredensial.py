"""L4 - Kredensial: pemisahan ketat antara akun Testnet dan Live Binance Futures.

Aturan keamanan wajib (operator, 3 Agu 2026):
1. Testnet dan live memakai NAMA variabel lingkungan BERBEDA. Tidak ada fallback
   silang antara keduanya (kredensial testnet tidak pernah dipakai untuk live,
   maupun sebaliknya).
2. Base URL exchange TIDAK BISA diubah lewat variabel lingkungan atau argumen -
   ia ditentukan murni oleh `mode` yang diminta. Ini mencegah kredensial testnet
   "nyasar" ke endpoint live, atau sebaliknya.
3. Mode "live" wajib DUA gerbang konfirmasi independen yang harus lolos SEKALIGUS:
   a. Argumen CLI eksplisit (`--konfirmasi-live`, diteruskan sebagai
      `konfirmasi_live_cli=True`).
   b. Variabel lingkungan `LUX_LIVE_KONFIRMASI` yang HARUS sama persis dengan
      `FRASA_KONFIRMASI_LIVE`.
   Satu gerbang saja TIDAK CUKUP. Tujuannya: satu kesalahan tunggal (mis. lupa
   menghapus flag lama di skrip cron, atau variabel lingkungan yang ter-copy
   dari environment lain) tidak bisa sendirian memicu order live.
4. Bila API key/secret testnet dan live KEBETULAN identik (indikasi kuat salah
   salin-tempel), muat_kredensial() MENOLAK keduanya, apa pun mode yang diminta.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

MODE_TESTNET = "testnet"
MODE_LIVE = "live"
MODE_VALID = (MODE_TESTNET, MODE_LIVE)

# Base URL TETAP per mode - bukan konfigurasi, supaya tidak bisa disilangkan.
BASE_URL_TESTNET = "https://testnet.binancefuture.com"
BASE_URL_LIVE = "https://fapi.binance.com"

ENV_TESTNET_KEY = "LUX_BINANCE_TESTNET_API_KEY"
ENV_TESTNET_SECRET = "LUX_BINANCE_TESTNET_API_SECRET"
ENV_LIVE_KEY = "LUX_BINANCE_LIVE_API_KEY"
ENV_LIVE_SECRET = "LUX_BINANCE_LIVE_API_SECRET"
ENV_LIVE_KONFIRMASI = "LUX_LIVE_KONFIRMASI"

# Frasa wajib untuk gerbang kedua mode live. Sengaja panjang & spesifik supaya
# tidak bisa ke-set tidak sengaja oleh nilai default/placeholder.
FRASA_KONFIRMASI_LIVE = "SAYA_PAHAM_INI_AKUN_LIVE_DANA_ASLI"


class KredensialError(Exception):
    """Dilempar bila kredensial tidak lengkap, tidak sah, atau gerbang keamanan gagal."""


@dataclass(frozen=True)
class KredensialBinance:
    mode: str
    api_key: str
    api_secret: str
    base_url: str

    def ringkas(self) -> dict:
        """Ringkasan aman untuk log - tidak pernah membocorkan api_key/secret utuh."""
        terlihat = (
            self.api_key[:4] + "..." + self.api_key[-2:] if len(self.api_key) > 8 else "***"
        )
        return {"mode": self.mode, "base_url": self.base_url, "api_key_terlihat": terlihat}


def _ambil_env(nama: str) -> Optional[str]:
    v = os.environ.get(nama)
    if v is None:
        return None
    v = v.strip()
    return v or None


def muat_kredensial(mode: str, konfirmasi_live_cli: bool = False) -> KredensialBinance:
    """Muat kredensial untuk mode 'testnet' atau 'live'.

    Melempar KredensialError dengan pesan jelas bila:
    - mode tidak dikenal
    - kredensial yang relevan belum diset / kosong
    - kredensial testnet dan live identik (indikasi salah salin)
    - (khusus live) salah satu dari dua gerbang konfirmasi tidak lolos
    """
    if mode not in MODE_VALID:
        raise KredensialError(f"mode kredensial tidak dikenal: {mode!r}, pilihan: {MODE_VALID}")

    testnet_key = _ambil_env(ENV_TESTNET_KEY)
    testnet_secret = _ambil_env(ENV_TESTNET_SECRET)
    live_key = _ambil_env(ENV_LIVE_KEY)
    live_secret = _ambil_env(ENV_LIVE_SECRET)

    if testnet_key and live_key and testnet_key == live_key:
        raise KredensialError(
            f"{ENV_TESTNET_KEY} dan {ENV_LIVE_KEY} identik - ini kemungkinan besar "
            "kesalahan salin-tempel. Kredensial testnet dan live WAJIB berbeda akun."
        )
    if testnet_secret and live_secret and testnet_secret == live_secret:
        raise KredensialError(
            f"{ENV_TESTNET_SECRET} dan {ENV_LIVE_SECRET} identik - kemungkinan besar "
            "kesalahan salin-tempel. Kredensial testnet dan live WAJIB berbeda akun."
        )

    if mode == MODE_TESTNET:
        if not testnet_key or not testnet_secret:
            raise KredensialError(
                f"kredensial testnet belum diset. Set variabel lingkungan {ENV_TESTNET_KEY} "
                f"dan {ENV_TESTNET_SECRET} dari akun Binance Futures TESTNET "
                "(https://testnet.binancefuture.com), BUKAN akun live."
            )
        return KredensialBinance(MODE_TESTNET, testnet_key, testnet_secret, BASE_URL_TESTNET)

    # mode == MODE_LIVE
    if not live_key or not live_secret:
        raise KredensialError(
            f"kredensial live belum diset. Set variabel lingkungan {ENV_LIVE_KEY} dan "
            f"{ENV_LIVE_SECRET} dari akun Binance Futures LIVE."
        )
    if not konfirmasi_live_cli:
        raise KredensialError(
            "mode live wajib argumen CLI eksplisit '--konfirmasi-live'. Ini gerbang "
            "keamanan PERTAMA dari dua yang wajib lolos bersamaan. Tanpa ini, tidak "
            "ada order live yang akan dikirim."
        )
    konfirmasi_env = _ambil_env(ENV_LIVE_KONFIRMASI)
    if konfirmasi_env != FRASA_KONFIRMASI_LIVE:
        raise KredensialError(
            f"mode live wajib variabel lingkungan {ENV_LIVE_KONFIRMASI}='{FRASA_KONFIRMASI_LIVE}' "
            "(sama persis, peka huruf besar/kecil). Ini gerbang keamanan KEDUA dari dua "
            "yang wajib lolos bersamaan. Tanpa KEDUA gerbang lolos sekaligus, tidak ada "
            "order live yang akan dikirim ke exchange."
        )
    return KredensialBinance(MODE_LIVE, live_key, live_secret, BASE_URL_LIVE)
