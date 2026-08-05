"""Lapis plugin - titik perluasan modul TANPA menyentuh core engine.

Masalah yang dipecahkan berkas ini: sebelumnya daftar strategi dipatok keras di
`strategi/__init__.py` (KELAS_BAWAAN). Menambah strategi berarti menyunting berkas
inti. Itu bertentangan dengan permintaan operator: daftar strategi/pattern/indikator
harus terbuka, bukan tetap.

Empat katalog terbuka:

1. KATALOG_STRATEGI  - kelas strategi lengkap (punya entry/TP/SL/skor/ambang sendiri)
2. KATALOG_POLA      - detektor pattern murni; dibungkus otomatis jadi strategi
3. KATALOG_INDIKATOR - fungsi indikator murni; dipanggil lewat FeatureStore.hitung()
4. KATALOG_KELOMPOK  - nama kelompok teknik; boleh bertambah, tidak dipatok tiga

Aturan yang TIDAK berubah walau katalog terbuka:
- Setiap strategi tetap wajib punya entry, TP, SL, skor 0..100, dan ambang sendiri.
- Strategi tetap dilarang membaca hasil strategi lain.
- Registry tetap mengevaluasi SEMUA strategi tiap bar tanpa short-circuit.
Jadi menambah 100 strategi pun tidak mengubah satu baris pun di L3 (arbiter) atau
L4 (eksekusi).

Penemuan otomatis (auto-discovery):
- `muat_plugin()` mengimpor seluruh submodul di dalam paket `lux_modul.strategi`
  sehingga dekorator di dalamnya ikut terpicu.
- Direktori tambahan bisa disuntik lewat variabel lingkungan LUX_PLUGIN_PATHS
  (dipisah titik dua) atau argumen `direktori_luar`. Berkas .py di sana diimpor
  sebagai plugin pihak ketiga. Ini membuat strategi baru bisa hidup DI LUAR repo
  inti sekalipun.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# --------------------------------------------------------------------------- #
# Katalog kelompok teknik (terbuka)
# --------------------------------------------------------------------------- #


class DaftarKelompok:
    """Himpunan nama kelompok teknik yang boleh bertambah saat runtime.

    Sengaja dibuat objek, bukan tuple beku, supaya penambahan kelompok baru
    (misal 'aliran_volume') tidak memaksa penyuntingan kontrak inti.
    """

    def __init__(self, awal: Iterable[str] = ()) -> None:
        self._isi: List[str] = []
        for n in awal:
            self.tambah(n)

    def tambah(self, nama: str) -> str:
        nama = str(nama).strip()
        if not nama:
            raise ValueError("nama kelompok tidak boleh kosong")
        if nama not in self._isi:
            self._isi.append(nama)
        return nama

    def __contains__(self, x: object) -> bool:
        return x in self._isi

    def __iter__(self):
        return iter(sorted(self._isi))

    def __len__(self) -> int:
        return len(self._isi)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list)):
            return sorted(self._isi) == sorted(other)
        if isinstance(other, DaftarKelompok):
            return sorted(self._isi) == sorted(other._isi)
        return NotImplemented

    def __hash__(self):  # pragma: no cover
        return hash(tuple(sorted(self._isi)))

    def __repr__(self) -> str:  # pragma: no cover
        return f"DaftarKelompok({sorted(self._isi)!r})"


# --------------------------------------------------------------------------- #
# Katalog strategi
# --------------------------------------------------------------------------- #

KATALOG_STRATEGI: Dict[str, type] = {}
_ASAL_STRATEGI: Dict[str, str] = {}


def daftar_strategi(kelas: Optional[type] = None, *, ganti: bool = False):
    """Dekorator pendaftar strategi.

        @daftar_strategi
        class StrategiBaruku(Strategi):
            id = "strategi_baruku"
            ...

    Tidak ada berkas inti yang perlu disunting. `ganti=True` dipakai bila plugin
    pihak ketiga sengaja menimpa strategi bawaan dengan id yang sama.
    """

    def _pasang(k: type) -> type:
        sid = getattr(k, "id", "")
        if not sid:
            raise ValueError(f"{k.__name__}: atribut `id` wajib diisi sebelum didaftarkan")
        if sid in KATALOG_STRATEGI and not ganti:
            asal = _ASAL_STRATEGI.get(sid, "?")
            raise ValueError(
                f"id strategi ganda: {sid!r} (sudah terdaftar dari {asal}). "
                "Pakai @daftar_strategi(ganti=True) bila memang ingin menimpa."
            )
        KATALOG_STRATEGI[sid] = k
        _ASAL_STRATEGI[sid] = getattr(k, "__module__", "?")
        return k

    if kelas is not None:
        return _pasang(kelas)
    return _pasang


# --------------------------------------------------------------------------- #
# Katalog indikator
# --------------------------------------------------------------------------- #

KATALOG_INDIKATOR: Dict[str, Callable[..., Any]] = {}


def daftar_indikator(nama: str, *, ganti: bool = False):
    """Dekorator pendaftar indikator murni.

    Fungsi menerima `Bars` sebagai argumen pertama lalu parameter bebas, dan wajib
    murni (tanpa state, tanpa efek samping). Sesudah terdaftar, indikator dipanggil
    lewat `FeatureStore.hitung("nama", bars, *args)` dan otomatis ikut di-cache.
    """

    def _pasang(fn: Callable[..., Any]) -> Callable[..., Any]:
        if nama in KATALOG_INDIKATOR and not ganti:
            raise ValueError(f"indikator ganda: {nama!r}")
        KATALOG_INDIKATOR[nama] = fn
        return fn

    return _pasang


# --------------------------------------------------------------------------- #
# Katalog pattern
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Deteksi:
    """Keluaran mentah sebuah detektor pattern.

    Detektor TIDAK menentukan TP/SL final dan TIDAK tahu apa pun soal strategi lain.
    Ia hanya melapor: pattern ini terbentuk, arahnya ke mana, seberapa kuat tiap
    komponen buktinya, dan di harga berapa titik invalidasinya secara struktur.

    - arah        : "LONG" / "SHORT"
    - level       : harga acuan pattern (neckline, band, garis tren, dsb)
    - invalidation: harga yang membatalkan pattern secara struktural
    - komponen    : {nama: (nilai 0..1, bobot)} bahan penyusun skor
    """

    arah: str
    level: float
    invalidation: float
    komponen: Mapping[str, Tuple[float, float]]
    bukti: Mapping[str, Any] = field(default_factory=dict)
    fitur: Tuple[str, ...] = ()


KATALOG_POLA: Dict[str, "SpesifikasiPola"] = {}


@dataclass(frozen=True)
class SpesifikasiPola:
    """Metadata + detektor sebuah pattern.

    Menambah pattern baru = mendaftarkan satu fungsi detektor. Pembungkusnya
    (`StrategiPola` di strategi/adaptor.py) yang mengurus TP/SL/skor/ambang,
    sehingga arsitektur inti tidak berubah sama sekali.
    """

    nama: str
    kelompok: str
    detektor: Callable[..., Optional[Deteksi]]
    ambang: float = 60.0
    warmup: int = 100
    konteks: int = 0
    horizon: Tuple[str, ...] = ()
    sl_atr: float = 1.0
    rr: Tuple[float, ...] = (1.5, 3.0)
    porsi: Tuple[float, ...] = (0.5, 0.5)
    deskripsi: str = ""
    sumber: Tuple[str, ...] = ()


def daftar_pola(
    nama: str,
    *,
    kelompok: str,
    ambang: float = 60.0,
    warmup: int = 100,
    konteks: int = 0,
    horizon: Sequence[str] = (),
    sl_atr: float = 1.0,
    rr: Sequence[float] = (1.5, 3.0),
    porsi: Sequence[float] = (0.5, 0.5),
    deskripsi: str = "",
    sumber: Sequence[str] = (),
    ganti: bool = False,
):
    """Dekorator pendaftar pattern.

        @daftar_pola("inside_bar_break", kelompok=KELOMPOK_POLA, ambang=58)
        def _inside_bar(ctx, f, bars, i) -> Optional[Deteksi]:
            ...

    Satu fungsi, nol perubahan pada core engine.
    """

    def _pasang(fn: Callable[..., Optional[Deteksi]]):
        if nama in KATALOG_POLA and not ganti:
            raise ValueError(f"pola ganda: {nama!r}")
        if len(rr) != len(porsi):
            raise ValueError(f"{nama}: jumlah rr dan porsi wajib sama")
        if sum(porsi) > 1.0 + 1e-9:
            raise ValueError(f"{nama}: total porsi TP > 1.0")
        KATALOG_POLA[nama] = SpesifikasiPola(
            nama=nama,
            kelompok=kelompok,
            detektor=fn,
            ambang=float(ambang),
            warmup=int(warmup),
            konteks=int(konteks),
            horizon=tuple(horizon),
            sl_atr=float(sl_atr),
            rr=tuple(float(x) for x in rr),
            porsi=tuple(float(x) for x in porsi),
            deskripsi=deskripsi,
            sumber=tuple(sumber),
        )
        return fn

    return _pasang


# --------------------------------------------------------------------------- #
# Penemuan otomatis
# --------------------------------------------------------------------------- #

_SUDAH_DIMUAT = False


def _impor_paket(nama_paket: str) -> List[str]:
    """Impor seluruh submodul sebuah paket agar dekoratornya terpicu."""
    termuat: List[str] = []
    try:
        paket = importlib.import_module(nama_paket)
    except ImportError:
        return termuat
    for info in pkgutil.iter_modules(getattr(paket, "__path__", [])):
        if info.name.startswith("_"):
            continue
        penuh = f"{nama_paket}.{info.name}"
        importlib.import_module(penuh)
        termuat.append(penuh)
    return termuat


def _impor_direktori(direktori: str) -> List[str]:
    """Impor berkas .py lepas dari direktori luar sebagai plugin pihak ketiga."""
    termuat: List[str] = []
    if not os.path.isdir(direktori):
        return termuat
    for berkas in sorted(os.listdir(direktori)):
        if not berkas.endswith(".py") or berkas.startswith("_"):
            continue
        jalur = os.path.join(direktori, berkas)
        nama = f"lux_plugin_luar_{berkas[:-3]}"
        if nama in sys.modules:
            termuat.append(nama)
            continue
        spec = importlib.util.spec_from_file_location(nama, jalur)
        if spec is None or spec.loader is None:
            continue
        modul = importlib.util.module_from_spec(spec)
        sys.modules[nama] = modul
        spec.loader.exec_module(modul)
        termuat.append(nama)
    return termuat


def muat_plugin(direktori_luar: Sequence[str] = (), paksa: bool = False) -> Dict[str, Any]:
    """Temukan dan muat seluruh plugin. Aman dipanggil berkali-kali."""
    global _SUDAH_DIMUAT
    if _SUDAH_DIMUAT and not paksa and not direktori_luar:
        return ringkas_katalog()

    modul = _impor_paket("lux_modul.strategi")

    dari_env = os.environ.get("LUX_PLUGIN_PATHS", "")
    dirs = [d for d in dari_env.split(os.pathsep) if d.strip()]
    dirs.extend(direktori_luar)
    for d in dirs:
        modul.extend(_impor_direktori(d))

    _SUDAH_DIMUAT = True
    hasil = ringkas_katalog()
    hasil["modul_dimuat"] = modul
    return hasil


def ringkas_katalog() -> Dict[str, Any]:
    return {
        "strategi": sorted(KATALOG_STRATEGI),
        "pola": sorted(KATALOG_POLA),
        "indikator": sorted(KATALOG_INDIKATOR),
        "jumlah_strategi": len(KATALOG_STRATEGI),
        "jumlah_pola": len(KATALOG_POLA),
        "jumlah_indikator": len(KATALOG_INDIKATOR),
    }


def bersihkan_katalog() -> None:
    """Hanya untuk pengujian terisolasi."""
    global _SUDAH_DIMUAT
    KATALOG_STRATEGI.clear()
    KATALOG_POLA.clear()
    KATALOG_INDIKATOR.clear()
    _ASAL_STRATEGI.clear()
    _SUDAH_DIMUAT = False
