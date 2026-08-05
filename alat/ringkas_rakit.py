#!/usr/bin/env python3
"""Ringkasan padat isi repo hasil rakitan, supaya audit tidak perlu membuka
satu per satu berkas dan tidak perlu menebak apa yang ikut ter-commit."""
import json
import os


def hitung(akar, ext=None):
    if not os.path.isdir(akar):
        return 0
    total = 0
    for dp, dn, fn in os.walk(akar):
        dn[:] = [d for d in dn if d not in ("__pycache__", ".git")]
        for f in fn:
            if ext is None or f.endswith(ext):
                total += 1
    return total


def ekor(path, n=6):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as fh:
        baris = fh.read().splitlines()
    return baris[-n:]


out = {
    "base_ref": os.environ.get("BASE_REF"),
    "fix_ref": os.environ.get("FIX_REF"),
    "berkas": {
        "py_lux_modul": hitung("lux_modul", ".py"),
        "py_tests": hitung("tests", ".py"),
        "py_scripts": hitung("scripts", ".py"),
        "py_tools": hitung("tools", ".py"),
        "dataset_masuk_total": hitung("dataset_masuk"),
    },
    "kebersihan": {
        "ada_eksekusi_aman": os.path.isdir("lux_modul/eksekusi_aman"),
        "sisa_sumber_base": os.path.exists("sumber_base"),
        "sisa_sumber_fix": os.path.exists("sumber_fix"),
        "ada_requirements": os.path.isfile("requirements.txt"),
        "ada_main_py": os.path.isfile("main.py"),
        "ada_env_contoh": os.path.isfile(".env.contoh"),
        "workflow_sumber_ikut": os.path.isdir(".github/workflows")
        and sorted(os.listdir(".github/workflows")),
    },
    "akar": sorted(x for x in os.listdir(".") if not x.startswith(".git")),
    "pytest_ekor": ekor("bukti/jejak_pytest.txt"),
}

with open("bukti/RINGKAS_RAKIT.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False, sort_keys=True)

print(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True))
