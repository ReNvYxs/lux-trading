"""Pelari uji minimal untuk sandbox TANPA jaringan (pytest tidak bisa dipasang).

Di GitHub Actions, pytest asli yang dipakai. Skrip ini hanya jaring pengaman lokal:
ia menyediakan shim `pytest.raises` / `pytest.approx`, lalu menjalankan seluruh
fungsi `test_*` di berkas `tests/test_*.py`.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import traceback
import types

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)


def _pasang_shim_pytest() -> None:
    try:
        import pytest  # noqa: F401

        return
    except ImportError:
        pass

    mod = types.ModuleType("pytest")

    class _Raises:
        def __init__(self, exc):
            self.exc = exc
            self.value = None

        def __enter__(self):
            return self

        def __exit__(self, t, v, tb):
            if t is None:
                raise AssertionError(f"tidak melempar {self.exc}")
            if not issubclass(t, self.exc):
                return False
            self.value = v
            return True

    class _Approx:
        def __init__(self, nilai, rel=1e-6, abs=1e-12):
            self.nilai = nilai
            self.rel = rel
            self.abs = abs

        def __eq__(self, lain):
            try:
                a, b = float(lain), float(self.nilai)
            except (TypeError, ValueError):
                return False
            return abs(a - b) <= max(self.abs, self.rel * max(abs(a), abs(b)))

        def __repr__(self):
            return f"approx({self.nilai})"

    def raises(exc, *a, **kw):
        return _Raises(exc)

    def approx(nilai, rel=1e-6, abs=1e-12):
        return _Approx(nilai, rel, abs)

    mod.raises = raises
    mod.approx = approx
    mod.fixture = lambda *a, **kw: (lambda f: f)
    sys.modules["pytest"] = mod


def main() -> int:
    _pasang_shim_pytest()
    dir_uji = os.path.join(AKAR, "tests")
    berkas = sorted(f for f in os.listdir(dir_uji) if f.startswith("test_") and f.endswith(".py"))
    lulus = gagal = 0
    kegagalan = []
    for nama in berkas:
        spec = importlib.util.spec_from_file_location(nama[:-3], os.path.join(dir_uji, nama))
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        for fn_nama in sorted(dir(modul)):
            if not fn_nama.startswith("test_"):
                continue
            fn = getattr(modul, fn_nama)
            if not callable(fn):
                continue
            try:
                fn()
                lulus += 1
                print(f".  {nama}::{fn_nama}")
            except Exception:
                gagal += 1
                kegagalan.append((nama, fn_nama, traceback.format_exc()))
                print(f"X  {nama}::{fn_nama}")
    print("\n" + "=" * 70)
    for nama, fn_nama, tb in kegagalan:
        print(f"\nGAGAL {nama}::{fn_nama}\n{tb}")
    print(f"RINGKASAN: {lulus} lulus, {gagal} gagal, total {lulus + gagal}")
    return 1 if gagal else 0


if __name__ == "__main__":
    raise SystemExit(main())
