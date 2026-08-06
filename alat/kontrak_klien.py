"""Kontrak klien: metode apa yang dibutuhkan lapisan aman, apakah klien lama menyediakannya.

Diekstrak dari kode, bukan dari dokumentasi: setiap akses atribut pada variabel
`klien` / `self.klien` di lux_modul/eksekusi_aman dikumpulkan lewat AST, lalu
dicocokkan dengan kelas klien nyata di lux_modul/eksekusi/binance_client.py.
"""
import ast
import importlib
import inspect
import json
import os
import sys

sys.path.insert(0, os.getcwd())

AMAN_DIR = "lux_modul/eksekusi_aman"
KLIEN_MODUL = "lux_modul.eksekusi.binance_client"
KELUARAN = os.environ.get("KONTRAK_KELUARAN", "bukti/ci/KONTRAK_KLIEN.json")
VAR = ("klien", "pengirim", "spek", "data")


def berkas_py(dasar):
    keluar = []
    for akar, dirs, files in os.walk(dasar):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                keluar.append(os.path.join(akar, f))
    return keluar


def akses_pada(pohon, nama_var):
    hasil = {}
    for n in ast.walk(pohon):
        if not isinstance(n, ast.Attribute):
            continue
        v = n.value
        cocok = False
        if isinstance(v, ast.Name) and v.id == nama_var:
            cocok = True
        elif (isinstance(v, ast.Attribute) and v.attr == nama_var
              and isinstance(v.value, ast.Name) and v.value.id == "self"):
            cocok = True
        if cocok:
            hasil[n.attr] = hasil.get(n.attr, 0) + 1
    return hasil


def gabung(a, b):
    for k in b:
        a[k] = a.get(k, 0) + b[k]
    return a


def tanda_tangan(obj):
    try:
        return str(inspect.signature(obj))
    except Exception:
        return "?"


def main():
    butuh = {}
    per_berkas = {}
    for jalur in berkas_py(AMAN_DIR):
        try:
            fh = open(jalur, "r", encoding="utf-8")
            isi = fh.read()
            fh.close()
            pohon = ast.parse(isi, filename=jalur)
        except Exception as exc:
            per_berkas[jalur] = {"galat": repr(exc)}
            continue
        catat = {}
        for v in VAR:
            a = akses_pada(pohon, v)
            if a:
                catat[v] = dict(sorted(a.items()))
        per_berkas[jalur] = catat
        if "klien" in catat:
            gabung(butuh, catat["klien"])

    butuh_nama = sorted(butuh)

    galat_impor = None
    kelas_nama = None
    ada = []
    hilang = []
    rinci = {}
    kelas_lain = []
    exc_info = {}
    try:
        mod = importlib.import_module(KLIEN_MODUL)
    except Exception as exc:
        galat_impor = repr(exc)
        mod = None

    if mod is not None:
        kandidat = []
        for n in sorted(dir(mod)):
            o = getattr(mod, n, None)
            if inspect.isclass(o) and getattr(o, "__module__", "") == mod.__name__:
                kandidat.append(n)
        kelas_lain = kandidat
        pilih = None
        for n in kandidat:
            if n == "BinanceFuturesClient":
                pilih = getattr(mod, n)
                kelas_nama = n
                break
        if pilih is None:
            for n in kandidat:
                o = getattr(mod, n)
                if hasattr(o, "kirim_order"):
                    pilih = o
                    kelas_nama = n
                    break
        if pilih is not None:
            for nama in butuh_nama:
                if hasattr(pilih, nama):
                    ada.append(nama)
                    atr = getattr(pilih, nama)
                    rinci[nama] = {
                        "jenis": "metode" if callable(atr) else type(atr).__name__,
                        "tanda_tangan": tanda_tangan(atr) if callable(atr) else "",
                    }
                else:
                    hilang.append(nama)
        galat_kelas = getattr(mod, "BinanceAPIError", None)
        if galat_kelas is not None:
            exc_info = {
                "tanda_tangan": tanda_tangan(galat_kelas),
                "atribut": sorted([x for x in dir(galat_kelas) if not x.startswith("_")]),
            }

    lulus = (galat_impor is None) and (kelas_nama is not None) and (not hilang)

    hasil = {
        "lulus": lulus,
        "butuh_dari_klien": dict(sorted(butuh.items())),
        "butuh_nama": butuh_nama,
        "per_berkas": per_berkas,
        "kelas_klien": kelas_nama,
        "kelas_di_modul": kelas_lain,
        "ada": ada,
        "hilang": hilang,
        "rinci_metode": rinci,
        "galat_impor": galat_impor,
        "BinanceAPIError": exc_info,
    }

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump(hasil, fh, indent=1, sort_keys=True, default=str)
    fh.close()

    print("KONTRAK_KLIEN=" + ("LULUS" if lulus else "GAGAL"))
    print("kelas_klien=" + str(kelas_nama))
    print("kelas_di_modul=" + json.dumps(kelas_lain))
    print("butuh_jumlah=" + str(len(butuh_nama)))
    print("butuh=" + json.dumps(butuh_nama))
    print("ada=" + json.dumps(ada))
    print("hilang=" + json.dumps(hilang))
    print("galat_impor=" + json.dumps(galat_impor))
    print("BinanceAPIError_tanda_tangan=" + json.dumps(exc_info.get("tanda_tangan", "")))
    for nama in ada:
        print("metode=" + nama + rinci[nama]["tanda_tangan"])
    return 0 if lulus else 1


if __name__ == "__main__":
    sys.exit(main())
