"""Peta permukaan API lapisan eksekusi lama vs lapisan aman, prasyarat rancang saklar .env."""
import ast
import importlib
import inspect
import json
import os
import pkgutil
import sys

sys.path.insert(0, os.getcwd())

AKAR = os.path.abspath(os.getcwd())
LAMA = "lux_modul.eksekusi"
AMAN = "lux_modul.eksekusi_aman"
KELUARAN = os.environ.get("PERMUKAAN_KELUARAN", "bukti/ci/PERMUKAAN.json")
DASAR = [d for d in ("lux_modul", "scripts", "tests") if os.path.isdir(d)]


def berkas_py(dasar):
    keluar = []
    for akar, dirs, files in os.walk(dasar):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                keluar.append(os.path.join(akar, f))
    return keluar


def nama_modul(jalur):
    rel = os.path.relpath(jalur, AKAR).replace(os.sep, "/")
    if rel.endswith("/__init__.py"):
        rel = rel[:-12]
    elif rel.endswith(".py"):
        rel = rel[:-3]
    return rel.replace("/", ".")


def datar(body):
    keluar = []
    for n in body:
        keluar.append(n)
        if isinstance(n, ast.If):
            keluar.extend(datar(n.body))
            keluar.extend(datar(n.orelse))
        elif isinstance(n, ast.Try):
            keluar.extend(datar(n.body))
            keluar.extend(datar(n.orelse))
            keluar.extend(datar(n.finalbody))
            for h in n.handlers:
                keluar.extend(datar(h.body))
    return keluar


def naik(basis, tingkat):
    for _ in range(tingkat):
        if "." in basis:
            basis = basis.rsplit(".", 1)[0]
        else:
            basis = ""
    return basis


def milik(nama, prefiks):
    return nama == prefiks or nama.startswith(prefiks + ".")


def ringkas_nilai(obj):
    try:
        teks = repr(obj)
    except Exception:
        teks = "?"
    if len(teks) > 160:
        teks = teks[:160] + "..."
    return teks


def deskripsi(obj):
    if inspect.isclass(obj):
        try:
            sig = str(inspect.signature(obj))
        except Exception:
            sig = "?"
        metode = []
        for n in dir(obj):
            if n.startswith("_"):
                continue
            try:
                a = getattr(obj, n)
            except Exception:
                continue
            if callable(a):
                metode.append(n)
        return {"jenis": "kelas", "tanda_tangan": sig, "metode": sorted(metode)}
    if inspect.isfunction(obj) or inspect.isbuiltin(obj):
        try:
            sig = str(inspect.signature(obj))
        except Exception:
            sig = "?"
        return {"jenis": "fungsi", "tanda_tangan": sig}
    return {"jenis": type(obj).__name__, "nilai": ringkas_nilai(obj)}


def permukaan(paket):
    keluar = {}
    galat = {}
    try:
        akar_mod = importlib.import_module(paket)
    except Exception as exc:
        return {}, {paket: repr(exc)}
    daftar = [paket]
    jalur = getattr(akar_mod, "__path__", None)
    if jalur:
        for info in pkgutil.iter_modules(list(jalur)):
            daftar.append(paket + "." + info.name)
    for nama in sorted(set(daftar)):
        try:
            mod = importlib.import_module(nama)
        except Exception as exc:
            galat[nama] = repr(exc)
            continue
        isi = {}
        for n in sorted(dir(mod)):
            if n.startswith("_"):
                continue
            try:
                obj = getattr(mod, n)
            except Exception:
                continue
            if inspect.ismodule(obj):
                continue
            asal = getattr(obj, "__module__", None)
            if asal is not None and not str(asal).startswith("lux_modul"):
                continue
            isi[n] = deskripsi(obj)
        keluar[nama] = isi
    return keluar, galat


def main():
    pakai = {}
    for d in DASAR:
        for jalur in berkas_py(d):
            m = nama_modul(jalur)
            if milik(m, LAMA) or milik(m, AMAN):
                continue
            try:
                fh = open(jalur, "r", encoding="utf-8")
                isi = fh.read()
                fh.close()
                pohon = ast.parse(isi, filename=jalur)
            except Exception:
                continue
            pkg = m if os.path.basename(jalur) == "__init__.py" else naik(m, 1)
            catat = {}
            for n in datar(pohon.body):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if milik(a.name, LAMA):
                            catat.setdefault(a.name, set()).add("*modul*")
                elif isinstance(n, ast.ImportFrom):
                    if n.level:
                        basis = naik(pkg, n.level - 1)
                        if n.module:
                            basis = (basis + "." + n.module) if basis else n.module
                    else:
                        basis = n.module or ""
                    if not milik(basis, LAMA):
                        continue
                    for a in n.names:
                        catat.setdefault(basis, set()).add(a.name)
            if catat:
                pakai[m] = dict((k, sorted(v)) for k, v in sorted(catat.items()))

    p_lama, g_lama = permukaan(LAMA)
    p_aman, g_aman = permukaan(AMAN)

    nama_dipakai = set()
    for m in pakai:
        for basis in pakai[m]:
            for x in pakai[m][basis]:
                if x != "*modul*":
                    nama_dipakai.add(x)

    tersedia_aman = {}
    for mod_nama in p_aman:
        for n in p_aman[mod_nama]:
            tersedia_aman.setdefault(n, []).append(mod_nama)

    padanan = {}
    tanpa_padanan = []
    for x in sorted(nama_dipakai):
        if x in tersedia_aman:
            padanan[x] = sorted(tersedia_aman[x])
        else:
            tanpa_padanan.append(x)

    hasil = {
        "dipakai_dari_lama": pakai,
        "konsumen_jumlah": len(pakai),
        "nama_lama_dipakai": sorted(nama_dipakai),
        "permukaan_lama": p_lama,
        "permukaan_aman": p_aman,
        "galat_impor_lama": g_lama,
        "galat_impor_aman": g_aman,
        "padanan_nama_di_aman": padanan,
        "tanpa_padanan_di_aman": tanpa_padanan,
        "aman_nama_publik": sorted(tersedia_aman),
    }

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump(hasil, fh, indent=1, sort_keys=True, default=str)
    fh.close()

    print("PERMUKAAN=OK")
    print("konsumen=" + str(len(pakai)))
    print("nama_lama_dipakai_jumlah=" + str(len(nama_dipakai)))
    print("padanan_jumlah=" + str(len(padanan)))
    print("tanpa_padanan_jumlah=" + str(len(tanpa_padanan)))
    print("tanpa_padanan=" + json.dumps(tanpa_padanan))
    print("padanan=" + json.dumps(sorted(padanan)))
    print("aman_modul=" + json.dumps(sorted(p_aman)))
    print("aman_nama_publik=" + json.dumps(sorted(tersedia_aman)))
    print("galat_impor_lama=" + json.dumps(g_lama))
    print("galat_impor_aman=" + json.dumps(g_aman))
    kunci = "lux_modul.live_runner"
    if kunci in pakai:
        print("live_runner_pakai=" + json.dumps(pakai[kunci]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
