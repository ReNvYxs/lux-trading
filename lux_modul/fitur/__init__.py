"""L1 - lapis fitur: indikator dasar + struktur pasar + cache.

`lanjutan` diimpor di sini (bukan hanya lewat muat_plugin) supaya seluruh
indikator lanjutannya (VWAP, volume profile, Keltner, squeeze, Donchian,
Supertrend, ADX, stoch RSI, fibonacci, pivot klasik) SELALU terdaftar ke
KATALOG_INDIKATOR begitu `lux_modul.fitur` diimpor -- termasuk saat dipanggil
lewat FeatureStore.hitung() dari strategi pola manapun, tanpa bergantung pada
urutan impor modul lain.
"""
from . import dasar, lanjutan, struktur
from .store import FeatureStore

__all__ = ["dasar", "struktur", "lanjutan", "FeatureStore"]
