"""Graf impor statis: impor rusak, nama hilang, modul yatim, dependensi luar."""
import ast
import importlib.util
import json
import os
import sys

AKAR = os.path.abspath(os.getcwd())
KELUARAN = os.environ.get("GRAF_KELUARAN", "bukti/ci/GRAF.json")
PAKET = "lux_modul"
DASAR = [d for d in (PAKET, "scripts", "tests", "alat") if os.path.isdir(d)]
STD = set(getattr(sys, "stdlib_module_names", ()))
BUKAN_LUAR = {"scripts", "tests", "alat", PAKET}


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


def nama_puncak(pohon):
    nama = set()
    bintang = False
    for n in datar(pohon.body):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nama.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    nama.add(t.id)
                elif isinstance(t, (ast.Tuple, ast.List)):
                    for e in t.elts:
                        if isinstance(e, ast.Name):
                            nama.add(e.id)
        elif isinstance(n, ast.AnnAssign):
            if isinstance(n.target, ast.Name):
                nama.add(n.target.id)
        elif isinstance(n, ast.Import):
            for a in n.names:
                nama.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                if a.name == "*":
                    bintang = True
                else:
                    nama.add(a.asname or a.name)
    return nama, bintang


def selesaikan(nama, himpunan):
    bagian = nama.split(".")
    while bagian:
        calon = ".".join(bagian)
        if calon in himpunan:
            return calon
        bagian.pop()
    return None


def milik(nama, prefiks):
    return nama == prefiks or nama.startswith(prefiks + ".")


def naik(basis, tingkat):
    for _ in range(tingkat):
        if "." in basis:
            basis = basis.rsplit(".", 1)[0]
        else:
            basis = ""
    return basis


def main():
    modul = {}
    for d in DASAR:
        for jalur in berkas_py(d):
            m = nama_modul(jalur)
            modul[m] = {
                "jalur": os.path.relpath(jalur, AKAR).replace(os.sep, "/"),
                "paket": os.path.basename(jalur) == "__init__.py",
            }
    himpunan = set(modul)

    pohon = {}
    galat_parse = []
    puncak = {}
    bintang = {}
    for m in sorted(modul):
        try:
            fh = open(modul[m]["jalur"], "r", encoding="utf-8")
            isi = fh.read()
            fh.close()
            t = ast.parse(isi, filename=modul[m]["jalur"])
        except Exception as exc:
            galat_parse.append({"modul": m, "galat": repr(exc)})
            continue
        pohon[m] = t
        puncak[m], bintang[m] = nama_puncak(t)

    sisi = {}
    impor_rusak = []
    nama_hilang = []
    luar = {}

    for m in sorted(pohon):
        pkg = m if modul[m]["paket"] else naik(m, 1)
        tujuan = set()
        for n in datar(pohon[m].body):
            if isinstance(n, ast.Import):
                for a in n.names:
                    tujuan.add((a.name, ""))
            elif isinstance(n, ast.ImportFrom):
                if n.level:
                    basis = naik(pkg, n.level - 1)
                    if n.module:
                        basis = (basis + "." + n.module) if basis else n.module
                else:
                    basis = n.module or ""
                if not basis:
                    continue
                tujuan.add((basis, ""))
                for a in n.names:
                    if a.name != "*":
                        tujuan.add((basis, a.name))
        for basis, anak in sorted(tujuan):
            akar_nama = basis.split(".")[0]
            if akar_nama == PAKET:
                res = selesaikan(basis, himpunan)
                if res is None:
                    impor_rusak.append({"dari": m, "impor": basis})
                    continue
                sisi.setdefault(m, set()).add(res)
                if anak:
                    sub = basis + "." + anak
                    if sub in himpunan:
                        sisi[m].add(sub)
                    elif res == basis and basis in puncak and not bintang.get(basis, False):
                        if anak not in puncak[basis]:
                            nama_hilang.append({"dari": m, "modul": basis, "nama": anak})
            elif akar_nama not in STD and akar_nama not in BUKAN_LUAR:
                luar.setdefault(akar_nama, set()).add(m)

    masuk = {}
    for a, bs in sisi.items():
        for b in bs:
            masuk.setdefault(b, set()).add(a)

    sisi_r = {}
    for a, bs in sisi.items():
        sisi_r[a] = set(bs)
    for m in himpunan:
        if "." in m:
            induk = naik(m, 1)
            if induk in himpunan:
                sisi_r.setdefault(m, set()).add(induk)

    awal = [m for m in sorted(himpunan) if m.split(".")[0] in ("scripts", "tests")]
    if PAKET in himpunan:
        awal.append(PAKET)
    terjangkau = set()
    antre = list(awal)
    while antre:
        cur = antre.pop()
        if cur in terjangkau:
            continue
        terjangkau.add(cur)
        for nxt in sisi_r.get(cur, ()):
            if nxt not in terjangkau:
                antre.append(nxt)

    yatim = sorted([m for m in himpunan if m.split(".")[0] == PAKET and m not in terjangkau])

    def pengimpor(prefiks):
        keluar = {}
        for a, bs in sisi.items():
            if milik(a, prefiks):
                continue
            hit = sorted([b for b in bs if milik(b, prefiks)])
            if hit:
                keluar[a] = hit
        return keluar

    p_eks = pengimpor("lux_modul.eksekusi")
    p_aman = pengimpor("lux_modul.eksekusi_aman")

    dep_hilang = []
    for pkg_luar in sorted(luar):
        try:
            ada = importlib.util.find_spec(pkg_luar) is not None
        except Exception:
            ada = False
        if not ada:
            dep_hilang.append(pkg_luar)

    rusak_modul = [x for x in impor_rusak if x["dari"].split(".")[0] == PAKET]
    rusak_alat = [x for x in impor_rusak if x["dari"].split(".")[0] != PAKET]
    hilang_modul = [x for x in nama_hilang if x["dari"].split(".")[0] == PAKET]
    hilang_alat = [x for x in nama_hilang if x["dari"].split(".")[0] != PAKET]
    parse_modul = [x for x in galat_parse if x["modul"].split(".")[0] == PAKET]

    lulus = not (rusak_modul or hilang_modul or parse_modul)

    hasil = {
        "lulus": lulus,
        "modul_total": len(himpunan),
        "modul_lux": len([m for m in himpunan if m.split(".")[0] == PAKET]),
        "impor_rusak_modul": rusak_modul,
        "impor_rusak_alat": rusak_alat,
        "nama_hilang_modul": hilang_modul,
        "nama_hilang_alat": hilang_alat,
        "galat_parse": galat_parse,
        "yatim": yatim,
        "dependensi_luar": dict((k, sorted(v)) for k, v in sorted(luar.items())),
        "dependensi_hilang": dep_hilang,
        "eksekusi": {
            "berkas": sorted([m for m in himpunan if milik(m, "lux_modul.eksekusi")]),
            "pengimpor_luar": p_eks,
            "terjangkau": sorted([m for m in terjangkau if milik(m, "lux_modul.eksekusi")]),
        },
        "eksekusi_aman": {
            "berkas": sorted([m for m in himpunan if milik(m, "lux_modul.eksekusi_aman")]),
            "pengimpor_luar": p_aman,
            "terjangkau": sorted([m for m in terjangkau if milik(m, "lux_modul.eksekusi_aman")]),
        },
        "sisi": dict((a, sorted(bs)) for a, bs in sorted(sisi.items())),
        "masuk": dict((a, sorted(bs)) for a, bs in sorted(masuk.items())),
        "titik_awal": awal,
    }

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump(hasil, fh, indent=1, sort_keys=True, default=str)
    fh.close()

    print("GRAF=" + ("LULUS" if lulus else "GAGAL"))
    print("modul_total=" + str(len(himpunan)))
    print("modul_lux=" + str(hasil["modul_lux"]))
    print("impor_rusak_modul=" + str(len(rusak_modul)))
    print("nama_hilang_modul=" + str(len(hilang_modul)))
    print("galat_parse=" + str(len(galat_parse)))
    print("impor_rusak_alat=" + str(len(rusak_alat)))
    print("nama_hilang_alat=" + str(len(hilang_alat)))
    print("dependensi_luar=" + json.dumps(sorted(luar)))
    print("dependensi_hilang=" + json.dumps(dep_hilang))
    print("yatim_jumlah=" + str(len(yatim)))
    print("yatim=" + json.dumps(yatim))
    print("eksekusi_pengimpor_luar=" + json.dumps(sorted(p_eks)))
    print("eksekusi_aman_pengimpor_luar=" + json.dumps(sorted(p_aman)))
    print("eksekusi_aman_terjangkau=" + json.dumps(hasil["eksekusi_aman"]["terjangkau"]))
    for x in (rusak_modul + hilang_modul + rusak_alat + hilang_alat)[:25]:
        print("cacat=" + json.dumps(x))
    return 0 if lulus else 1


if __name__ == "__main__":
    sys.exit(main())
