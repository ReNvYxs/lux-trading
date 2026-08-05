"""Konfigurasi terpusat LUX modul trading.

Semua nilai dibaca dari variabel lingkungan (file .env atau environment OS).
Tidak ada nilai yang dikodekan keras di sini; semua ada di .env.contoh.

Prinsip:
- .env adalah KONFIGURASI, bukan batasan. Operator bisa mengubah semua parameter
  dari file ini tanpa menyentuh kode.
- Token dan secret TIDAK PERNAH dicetak utuh; gunakan samarkan().
- Kegagalan memuat konfigurasi menghasilkan KonfigurasiError yang jelas, bukan
  AttributeError/ImportError diam-diam.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

BERKAS_ENV_DEFAULT = ".env"
BERKAS_ENV_CONTOH = ".env.contoh"


class KonfigurasiError(Exception):
    """Dilempar bila .env/lingkungan tidak sah. Pesannya wajib jelas untuk operator."""


ENV_SIMBOL = "LUX_SIMBOL"
ENV_TF_ENTRY = "LUX_TF_ENTRY"
ENV_TF_KONTEKS = "LUX_TF_KONTEKS"
ENV_HORIZON = "LUX_HORIZON"
ENV_LEVERAGE_MAKS = "LUX_LEVERAGE_MAKS"
ENV_MARGIN_KONFLIK = "LUX_MARGIN_KONFLIK"
ENV_INTERVAL_POLL = "LUX_INTERVAL_POLL"
ENV_BALANCE = "LUX_BALANCE"
ENV_MAKS_SIKLUS = "LUX_MAKS_SIKLUS"
ENV_DATA_DIR = "LUX_DATA_DIR"
ENV_TG_TOKEN = "LUX_TELEGRAM_BOT_TOKEN"
ENV_TG_CHAT_ID = "LUX_TELEGRAM_CHAT_ID"
ENV_TG_AKTIF = "LUX_TELEGRAM_AKTIF"
ENV_RR_BERSIH_MIN = "LUX_RR_BERSIH_MIN"
ENV_PORSI_MARGIN_MAKS = "LUX_PORSI_MARGIN_MAKS"

ENV_PINDAI_QUOTE = "LUX_PINDAI_QUOTE"
ENV_PINDAI_MAKS_PAIR = "LUX_PINDAI_MAKS_PAIR"
ENV_PINDAI_MIN_PAIR = "LUX_PINDAI_MIN_PAIR"
ENV_PINDAI_MIN_VOLUME = "LUX_PINDAI_MIN_VOLUME"
ENV_PINDAI_MIN_TRADE = "LUX_PINDAI_MIN_TRADE"
ENV_PINDAI_MAKS_SPREAD = "LUX_PINDAI_MAKS_SPREAD"
ENV_PINDAI_MIN_KEDALAMAN = "LUX_PINDAI_MIN_KEDALAMAN"
ENV_PINDAI_TTL = "LUX_PINDAI_TTL"
ENV_PINDAI_PERIKSA_BUKU = "LUX_PINDAI_PERIKSA_BUKU"
ENV_MAKS_RUNNER = "LUX_MAKS_RUNNER"

ENV_MAKS_POSISI = "LUX_MAKS_POSISI"
ENV_MIN_FREE_MARGIN_PCT = "LUX_MIN_FREE_MARGIN_PCT"

HORIZON_PILIHAN = ("scalping", "intraday")

_LEVERAGE_DEFAULT = 20.0
_MARGIN_KONFLIK_DEFAULT = 5.0
_INTERVAL_POLL_DEFAULT = 15.0
_RR_BERSIH_MIN_DEFAULT = 0.0
_PORSI_MARGIN_MAKS_DEFAULT = 0.5
_MAKS_RUNNER_DEFAULT = 120
_MAKS_POSISI_DEFAULT = 4
_MIN_FREE_MARGIN_PCT_DEFAULT = 0.30


def _teks(kunci: str, default: str = "") -> str:
    return os.environ.get(kunci, default).strip()


def _boolean(kunci: str, default: bool) -> bool:
    raw = os.environ.get(kunci, "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def _angka(kunci: str, default: float) -> float:
    raw = os.environ.get(kunci, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise KonfigurasiError(f"{kunci} bukan angka yang sah: {raw!r}") from exc


def _bulat(kunci: str, default: int) -> int:
    return int(_angka(kunci, float(default)))


def _angka_opsional(kunci: str) -> Optional[float]:
    raw = os.environ.get(kunci, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise KonfigurasiError(f"{kunci} bukan angka yang sah: {raw!r}") from exc


def _bulat_opsional(kunci: str) -> Optional[int]:
    v = _angka_opsional(kunci)
    return None if v is None else int(v)


def samarkan(nilai: str, tampil_awal: int = 4, tampil_akhir: int = 2) -> str:
    if not nilai:
        return "(kosong)"
    if len(nilai) <= tampil_awal + tampil_akhir:
        return "***"
    return nilai[:tampil_awal] + "..." + nilai[-tampil_akhir:]


def urai_env_teks(teks: str) -> Dict[str, str]:
    hasil: Dict[str, str] = {}
    for baris_mentah in teks.splitlines():
        baris = baris_mentah.strip()
        if not baris or baris.startswith("#"):
            continue
        if baris.startswith("export "):
            baris = baris[len("export "):].strip()
        if "=" not in baris:
            continue
        kunci, _, nilai = baris.partition("=")
        kunci = kunci.strip()
        nilai = nilai.strip()
        if not kunci:
            continue
        if len(nilai) >= 2 and nilai[0] == nilai[-1] and nilai[0] in ("'", '"'):
            nilai = nilai[1:-1]
        elif nilai.startswith("#"):
            nilai = ""
        elif " #" in nilai:
            nilai = nilai.split(" #", 1)[0].rstrip()
        hasil[kunci] = nilai
    return hasil


def muat_berkas_env(path: str) -> Dict[str, str]:
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        teks = fh.read()
    diterapkan: Dict[str, str] = {}
    for k, v in urai_env_teks(teks).items():
        if k in os.environ:
            continue
        os.environ[k] = v
        diterapkan[k] = v
    return diterapkan


@dataclass
class Konfigurasi:
    simbol: str
    tf_entry: str
    tf_konteks: str
    horizon: str
    leverage_maks: float
    margin_konflik: float
    interval_poll: float
    balance: Optional[float]
    maks_siklus: Optional[int]
    data_dir: str
    rr_bersih_min: float
    porsi_margin_maks: float
    maks_runner: int

    maks_posisi: int
    min_free_margin_pct: float

    pindai_quote: str
    pindai_maks_pair: int
    pindai_min_pair: int
    pindai_min_volume: float
    pindai_min_trade: int
    pindai_maks_spread: float
    pindai_min_kedalaman: float
    pindai_ttl: int
    pindai_periksa_buku: bool

    telegram_bot_token: str
    telegram_chat_id: str
    telegram_aktif: bool

    telegram_siap: bool

    def telegram_lengkap(self) -> bool:
        return bool(self.telegram_aktif and self.telegram_bot_token and self.telegram_chat_id)

    def mode_multi_pair(self) -> bool:
        return not bool(self.simbol)

    def daftar_entry_tf(self) -> Tuple[str, ...]:
        from .rencana_tf import uraikan_daftar_tf
        return uraikan_daftar_tf(self.tf_entry)

    def daftar_tf_konteks(self) -> Tuple[str, ...]:
        from .rencana_tf import uraikan_daftar_tf
        return uraikan_daftar_tf(self.tf_konteks)

    def daftar_simbol(self) -> Tuple[str, ...]:
        if not self.simbol:
            return ()
        return tuple(s.strip().upper() for s in self.simbol.split(",") if s.strip())

    def kriteria_pindai(self):
        from .pemindai import KriteriaLikuiditas
        return KriteriaLikuiditas(
            quote_aset=self.pindai_quote or "USDT",
            min_pair=self.pindai_min_pair,
            maks_pair=self.pindai_maks_pair,
            min_quote_volume_24j=self.pindai_min_volume,
            min_jumlah_trade_24j=self.pindai_min_trade,
            maks_spread_bps=self.pindai_maks_spread,
            min_kedalaman_usd=self.pindai_min_kedalaman,
            periksa_buku=self.pindai_periksa_buku,
            ttl_detik=float(self.pindai_ttl),
        )

    def ringkas(self) -> dict:
        return {
            "simbol": self.simbol or "(pindai pasar dinamis)",
            "horizon": self.horizon,
            "tf_entry": self.tf_entry or "(dari strategi)",
            "tf_konteks": self.tf_konteks or "(dari strategi)",
            "leverage_maks": self.leverage_maks,
            "margin_konflik": self.margin_konflik,
            "interval_poll": self.interval_poll,
            "balance": self.balance if self.balance is not None else "(tarik dari akun)",
            "maks_siklus": self.maks_siklus if self.maks_siklus else "tak terbatas",
            "porsi_margin_maks": self.porsi_margin_maks,
            "maks_runner": self.maks_runner,
            "maks_posisi": self.maks_posisi,
            "min_free_margin_pct": self.min_free_margin_pct,
            "telegram": {
                "aktif": self.telegram_aktif,
                "token": samarkan(self.telegram_bot_token),
                "chat_id": self.telegram_chat_id or "(kosong)",
            },
        }


def muat_konfigurasi(muat_env: bool = True) -> Konfigurasi:
    if muat_env:
        env_path = os.environ.get("LUX_ENV_PATH", BERKAS_ENV_DEFAULT)
        muat_berkas_env(env_path)

    horizon = _teks(ENV_HORIZON, "intraday").lower()
    if horizon not in HORIZON_PILIHAN:
        raise KonfigurasiError(
            f"{ENV_HORIZON} harus salah satu dari {HORIZON_PILIHAN}, dapat {horizon!r}. "
            "Horizon 'swing' tidak bisa dikonfigurasi di sini karena selamanya "
            "signal-only (tidak pernah auto-entry) - lihat governor.py."
        )

    cfg = Konfigurasi(
        simbol=_teks(ENV_SIMBOL).upper(),
        tf_entry=_teks(ENV_TF_ENTRY),
        tf_konteks=_teks(ENV_TF_KONTEKS),
        horizon=horizon,
        leverage_maks=_angka(ENV_LEVERAGE_MAKS, _LEVERAGE_DEFAULT),
        margin_konflik=_angka(ENV_MARGIN_KONFLIK, _MARGIN_KONFLIK_DEFAULT),
        interval_poll=_angka(ENV_INTERVAL_POLL, _INTERVAL_POLL_DEFAULT),
        balance=_angka_opsional(ENV_BALANCE),
        maks_siklus=_bulat_opsional(ENV_MAKS_SIKLUS),
        data_dir=_teks(ENV_DATA_DIR, "dataset_masuk/ekstrak/data_upload"),
        rr_bersih_min=_angka(ENV_RR_BERSIH_MIN, _RR_BERSIH_MIN_DEFAULT),
        porsi_margin_maks=_angka(ENV_PORSI_MARGIN_MAKS, _PORSI_MARGIN_MAKS_DEFAULT),
        maks_runner=_bulat(ENV_MAKS_RUNNER, _MAKS_RUNNER_DEFAULT),
        maks_posisi=_bulat(ENV_MAKS_POSISI, _MAKS_POSISI_DEFAULT),
        min_free_margin_pct=_angka(ENV_MIN_FREE_MARGIN_PCT, _MIN_FREE_MARGIN_PCT_DEFAULT),
        pindai_quote=_teks(ENV_PINDAI_QUOTE, "USDT"),
        pindai_maks_pair=_bulat(ENV_PINDAI_MAKS_PAIR, 50),
        pindai_min_pair=_bulat(ENV_PINDAI_MIN_PAIR, 25),
        pindai_min_volume=_angka(ENV_PINDAI_MIN_VOLUME, 50_000_000.0),
        pindai_min_trade=_bulat(ENV_PINDAI_MIN_TRADE, 50_000),
        pindai_maks_spread=_angka(ENV_PINDAI_MAKS_SPREAD, 6.0),
        pindai_min_kedalaman=_angka(ENV_PINDAI_MIN_KEDALAMAN, 25_000.0),
        pindai_ttl=_bulat(ENV_PINDAI_TTL, 1800),
        pindai_periksa_buku=_boolean(ENV_PINDAI_PERIKSA_BUKU, True),
        telegram_bot_token=_teks(ENV_TG_TOKEN),
        telegram_chat_id=_teks(ENV_TG_CHAT_ID),
        telegram_aktif=_boolean(ENV_TG_AKTIF, True),
        telegram_siap=False,
    )
    cfg = Konfigurasi(
        **{k: v for k, v in vars(cfg).items() if k != "telegram_siap"},
        telegram_siap=cfg.telegram_lengkap(),
    )
    return cfg


@dataclass(frozen=True)
class StatusKredensial:
    testnet_siap: bool
    live_siap: bool
    live_gerbang_env_siap: bool
    telegram_siap: bool
    detail: Dict[str, str]
    peringatan: Tuple[str, ...] = ()


def status_kredensial(cfg: Konfigurasi) -> StatusKredensial:
    from .eksekusi.kredensial import (
        ENV_LIVE_KEY,
        ENV_LIVE_KONFIRMASI,
        ENV_LIVE_SECRET,
        ENV_TESTNET_KEY,
        ENV_TESTNET_SECRET,
        FRASA_KONFIRMASI_LIVE,
    )

    testnet_key = _teks(ENV_TESTNET_KEY)
    testnet_secret = _teks(ENV_TESTNET_SECRET)
    live_key = _teks(ENV_LIVE_KEY)
    live_secret = _teks(ENV_LIVE_SECRET)
    live_konfirmasi_env = _teks(ENV_LIVE_KONFIRMASI)

    peringatan: List[str] = []
    if testnet_key and live_key and testnet_key == live_key:
        peringatan.append(
            "BAHAYA: kunci API testnet dan live IDENTIK - kemungkinan besar salah "
            "salin-tempel. Kredensial testnet dan live wajib berbeda akun."
        )
    if testnet_secret and live_secret and testnet_secret == live_secret:
        peringatan.append(
            "BAHAYA: secret API testnet dan live IDENTIK - kemungkinan besar salah "
            "salin-tempel. Kredensial testnet dan live wajib berbeda akun."
        )
    gerbang_env_siap = live_konfirmasi_env == FRASA_KONFIRMASI_LIVE
    if gerbang_env_siap:
        peringatan.append(
            "CATATAN: LUX_LIVE_KONFIRMASI sudah diisi frasa yang benar. Order live "
            "TETAP butuh gerbang kedua (--konfirmasi-live) sebelum benar-benar "
            "mengirim order dengan dana asli."
        )

    detail = {
        "testnet_key": samarkan(testnet_key),
        "live_key": samarkan(live_key),
        ENV_TG_TOKEN: samarkan(cfg.telegram_bot_token),
        ENV_TG_CHAT_ID: cfg.telegram_chat_id or "(kosong)",
    }

    return StatusKredensial(
        testnet_siap=bool(testnet_key and testnet_secret),
        live_siap=bool(live_key and live_secret),
        live_gerbang_env_siap=gerbang_env_siap,
        telegram_siap=cfg.telegram_siap,
        detail=detail,
        peringatan=tuple(peringatan),
    )
