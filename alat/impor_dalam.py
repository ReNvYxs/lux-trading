"""Impor bersarang: apa yang tidak terlihat oleh graf tingkat atas.

alat/graf_impor.py sengaja hanya membaca impor tingkat atas, sehingga modul
yang hanya diimpor DI DALAM fungsi tampak yatim padahal dipakai. Alat ini
membaca seluruh kedalaman lalu melaporkan selisihnya, supaya kesimpulan
'yatim' tidak menyesatkan dan supaya pertanyaan requirements.txt terjawab
dengan bukti.
"""
import ast
import json
import os
import sys

sys.path.insert(0, os.getcwd())

AKAR = ["lux_modul", "scripts", "tests", "alat"]
KELUARAN = os.environ.get("IMPOR_DALAM_KELUARAN", "bukti/ci/IMPOR_DALAM.json")
PANTAU = ["pandas", "pyarrow", "yaml", "numpy", "pytest", "requests",
          "websocket", "websockets", "aiohttp", "httpx", "scipy",
          "matplotlib", "sklearn"]
SOROT = ["lux_modul.eksekusi_aman.inti", "lux_modul.eksekusi_aman.saklar",
         "lux_modul.live_runner"]


def berkas_py(dasar):
    keluar = []
    if not os.path.isdir(dasar):
        return keluar
    for akar, dirs, files in os.walk(dasar):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in sorted(files):
            if f.endswith(".py"):
                keluar.append(os.path.join(akar, f))
    return keluar


def nama_modul(jalur):
    p = jalur.replace(os.sep, "/")
    if p.endswith("/__init__.py"):
        p = p[: -len("/__init__.py")]
    elif p.endswith(".py"):
        p = p[: -len(".py")]
    return p.replace("/", ".")


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


def induk(modul, jalur_adalah_paket):
    if jalur_adalah_paket:
        return modul
    if "." in modul:
        return modul.rsplit(".", 1)[0]
    return ""


def sasaran(node, modul, adalah_paket):
    keluar = []
    if isinstance(node, ast.Import):
        for a in node.names:
            keluar.append(a.name)
        return keluar
    if isinstance(node, ast.ImportFrom):
        level = int(node.level or 0)
        dasar = node.module or ""
        if level == 0:
            keluar.append(dasar)
            return keluar
        paket = induk(modul, adalah_paket)
        bagian = paket.split(".") if paket else []
        naik = level - 1
        if naik > 0:
            bagian = bagian[:-naik] if naik <= len(bagian) else []
        awal = ".".join(bagian)
        penuh = (awal + "." + dasar) if (awal and dasar) else (awal or dasar)
        keluar.append(penuh)
        return keluar
    return keluar


def main():
    semua_modul = {}
    for dasar in AKAR:
        for jalur in berkas_py(dasar):
            semua_modul[nama_modul(jalur)] = jalur

    atas = {}
    dalam = {}
    galat = {}
    for modul, jalur in sorted(semua_modul.items()):
        try:
            fh = open(jalur, "r", encoding="utf-8")
            isi = fh.read()
            fh.close()
            pohon = ast.parse(isi, filename=jalur)
        except Exception as exc:  # noqa: BLE001
            galat[modul] = repr(exc)
            continue
        adalah_paket = jalur.replace(os.sep, "/").endswith("/__init__.py")
        simpul_atas = [n for n in datar(pohon.body)
                       if isinstance(n, (ast.Import, ast.ImportFrom))]
        id_atas = set()
        for n in simpul_atas:
            id_atas.add(id(n))
        semua = [n for n in ast.walk(pohon)
                 if isinstance(n, (ast.Import, ast.ImportFrom))]
        a = set()
        d = set()
        for n in semua:
            for t in sasaran(n, modul, adalah_paket):
                if not t:
                    continue
                if id(n) in id_atas:
                    a.add(t)
                else:
                    d.add(t)
        atas[modul] = sorted(a)
        dalam[modul] = sorted(d)

    hanya_dalam = {}
    for modul in sorted(dalam):
        sisa = [t for t in dalam[modul] if t not in set(atas.get(modul, []))]
        if sisa:
            hanya_dalam[modul] = sisa

    def puncak(nama):
        return nama.split(".")[0]

    internal = set()
    for m in semua_modul:
        internal.add(puncak(m))

    luar_atas = set()
    luar_dalam = set()
    for modul in atas:
        for t in atas[modul]:
            if puncak(t) not in internal:
                luar_atas.add(puncak(t))
    for modul in dalam:
        for t in dalam[modul]:
            if puncak(t) not in internal:
                luar_dalam.add(puncak(t))

    pantau = {}
    for nama in PANTAU:
        pemakai_atas = []
        pemakai_dalam = []
        for modul in sorted(atas):
            if any(puncak(t) == nama for t in atas[modul]):
                pemakai_atas.append(modul)
        for modul in sorted(dalam):
            if any(puncak(t) == nama for t in dalam[modul]):
                pemakai_dalam.append(modul)
        if pemakai_atas or pemakai_dalam:
            pantau[nama] = {"tingkat_atas": pemakai_atas,
                            "bersarang": pemakai_dalam}

    sorot = {}
    for target in SOROT:
        pemakai_atas = []
        pemakai_dalam = []
        for modul in sorted(atas):
            if target in atas[modul] or any(
                    t.startswith(target + ".") for t in atas[modul]):
                pemakai_atas.append(modul)
        for modul in sorted(dalam):
            if target in dalam[modul] or any(
                    t.startswith(target + ".") for t in dalam[modul]):
                pemakai_dalam.append(modul)
        sorot[target] = {"tingkat_atas": pemakai_atas,
                         "bersarang": pemakai_dalam,
                         "dipakai": bool(pemakai_atas or pemakai_dalam)}

    hasil = {
        "modul_jumlah": len(semua_modul),
        "galat_parse": galat,
        "impor_atas": atas,
        "impor_dalam": dalam,
        "hanya_terlihat_saat_bersarang": hanya_dalam,
        "paket_luar_tingkat_atas": sorted(luar_atas),
        "paket_luar_bersarang": sorted(luar_dalam),
        "paket_luar_gabungan": sorted(luar_atas | luar_dalam),
        "pantau_dependensi": pantau,
        "sorot": sorot,
    }

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump(hasil, fh, indent=1, sort_keys=True, default=str)
    fh.close()

    print("IMPOR_DALAM=SELESAI")
    print("modul_jumlah=" + str(len(semua_modul)))
    print("galat_parse=" + str(len(galat)))
    print("paket_luar_tingkat_atas=" + json.dumps(sorted(luar_atas)))
    print("paket_luar_bersarang=" + json.dumps(sorted(luar_dalam)))
    print("paket_luar_gabungan=" + json.dumps(sorted(luar_atas | luar_dalam)))
    for nama in sorted(pantau):
        print("pantau=" + nama
              + " atas=" + json.dumps(pantau[nama]["tingkat_atas"])
              + " bersarang=" + json.dumps(pantau[nama]["bersarang"]))
    for nama in PANTAU:
        if nama not in pantau:
            print("pantau=" + nama + " TIDAK_DIPAKAI")
    for target in SOROT:
        print("sorot=" + target + " " + json.dumps(sorot[target]))
    print("hanya_bersarang_jumlah=" + str(len(hanya_dalam)))
    print("hanya_bersarang=" + json.dumps(hanya_dalam))
    return 0


if __name__ == "__main__":
    sys.exit(main())
