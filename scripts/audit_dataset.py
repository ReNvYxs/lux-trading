"""Audit kualitas dataset mentah SEBELUM dipakai menguji strategi.

Tidak menyentuh strategi sama sekali. Hanya memeriksa:
struktur, kolom, timeframe, timestamp, simbol, missing, duplikat, gap, anomali.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import defaultdict

DIR = "/data/lux/dataset_masuk/ekstrak/data_upload"
TF_MS = {"5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
KOLOM = ["ts", "open", "high", "low", "close", "volume"]


def baca(path):
    with open(path, "r", newline="", encoding="utf-8-sig") as f:
        r = csv.reader(f)
        head = next(r)
        head = [h.strip() for h in head]
        rows = []
        rusak = 0
        for baris in r:
            if len(baris) != len(head):
                rusak += 1
                continue
            try:
                rows.append(
                    (
                        int(float(baris[0])),
                        float(baris[1]),
                        float(baris[2]),
                        float(baris[3]),
                        float(baris[4]),
                        float(baris[5]),
                    )
                )
            except ValueError:
                rusak += 1
    return head, rows, rusak


def periksa(path, tf):
    head, rows, rusak = baca(path)
    d = TF_MS[tf]
    lap = {
        "header_cocok": head == KOLOM,
        "header": head,
        "baris": len(rows),
        "baris_rusak": rusak,
    }
    if not rows:
        lap["kosong"] = True
        return lap

    ts = [r[0] for r in rows]
    lap["ts_awal"] = ts[0]
    lap["ts_akhir"] = ts[-1]
    lap["menaik"] = all(ts[i] < ts[i + 1] for i in range(len(ts) - 1))
    lap["duplikat_ts"] = len(ts) - len(set(ts))
    lap["selaras_grid"] = sum(1 for t in ts if t % d != 0)

    # gap: selisih ts yang bukan tepat satu periode
    gap = 0
    lilin_hilang = 0
    selisih_aneh = defaultdict(int)
    for i in range(len(ts) - 1):
        delta = ts[i + 1] - ts[i]
        if delta != d:
            gap += 1
            selisih_aneh[delta] += 1
            if delta > d and delta % d == 0:
                lilin_hilang += delta // d - 1
    lap["gap"] = gap
    lap["lilin_hilang"] = lilin_hilang
    lap["selisih_aneh_teratas"] = sorted(selisih_aneh.items(), key=lambda kv: -kv[1])[:3]

    # anomali OHLC
    ohlc_salah = 0
    non_positif = 0
    vol_nol = 0
    vol_negatif = 0
    lompatan_ekstrem = 0
    for i, (t, o, h, l, c, v) in enumerate(rows):
        if not (h >= max(o, c) and l <= min(o, c) and h >= l):
            ohlc_salah += 1
        if min(o, h, l, c) <= 0:
            non_positif += 1
        if v == 0:
            vol_nol += 1
        if v < 0:
            vol_negatif += 1
        if i and rows[i - 1][4] > 0:
            perub = abs(c - rows[i - 1][4]) / rows[i - 1][4]
            if perub > 0.35:
                lompatan_ekstrem += 1
    lap["ohlc_tidak_konsisten"] = ohlc_salah
    lap["harga_non_positif"] = non_positif
    lap["volume_nol"] = vol_nol
    lap["volume_negatif"] = vol_negatif
    lap["lompatan_harga_gt35pct"] = lompatan_ekstrem
    lap["volume_total"] = sum(r[5] for r in rows)
    lap["quote_volume_perkiraan"] = sum(r[5] * r[4] for r in rows)
    return lap


def main():
    berkas = sorted(f for f in os.listdir(DIR) if f.endswith(".csv") and f != "manifest.csv")
    per_simbol = defaultdict(dict)
    for f in berkas:
        nama = f[:-4]
        for tf in TF_MS:
            if nama.endswith("_" + tf):
                per_simbol[nama[: -(len(tf) + 1)]][tf] = f
                break

    print(f"berkas CSV (tanpa manifest): {len(berkas)}")
    print(f"simbol unik                : {len(per_simbol)}")
    tf_hitung = defaultdict(int)
    for s, m in per_simbol.items():
        for tf in m:
            tf_hitung[tf] += 1
    print(f"berkas per timeframe       : {dict(sorted(tf_hitung.items()))}")
    tidak_lengkap = [s for s, m in per_simbol.items() if len(m) != 5]
    print(f"simbol tanpa 5 TF lengkap  : {tidak_lengkap if tidak_lengkap else 'tidak ada'}")

    # manifest
    likuid = []
    with open(os.path.join(DIR, "manifest.csv"), newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            try:
                likuid.append((row["base"].strip(), row["symbol"].strip(), float(row["quoteVolume"])))
            except (KeyError, ValueError):
                pass
    likuid.sort(key=lambda x: -x[2])
    print("\n10 aset paling likuid menurut manifest (quoteVolume 24j):")
    for b, s, q in likuid[:10]:
        ada = "ADA di dataset" if b in per_simbol else "TIDAK ADA berkasnya"
        print(f"   {b:<10} {s:<20} {q:>18,.0f}   {ada}")

    # audit penuh untuk kandidat teratas
    kandidat = [b for b, _, _ in likuid[:5] if b in per_simbol]
    hasil = {}
    print("\n=== AUDIT KUALITAS PER TF UNTUK KANDIDAT TERATAS ===")
    for b in kandidat:
        hasil[b] = {}
        print(f"\n--- {b} ---")
        for tf in ("5m", "15m", "1h", "4h", "1d"):
            if tf not in per_simbol[b]:
                continue
            lap = periksa(os.path.join(DIR, per_simbol[b][tf]), tf)
            hasil[b][tf] = lap
            print(
                f"   {tf:<4} baris={lap['baris']:<7} rusak={lap['baris_rusak']:<3} "
                f"dup={lap['duplikat_ts']:<3} gap={lap['gap']:<4} hilang={lap['lilin_hilang']:<5} "
                f"offgrid={lap['selaras_grid']:<4} ohlc_salah={lap['ohlc_tidak_konsisten']:<3} "
                f"vol0={lap['volume_nol']:<4} lompat={lap['lompatan_harga_gt35pct']:<3} "
                f"menaik={lap['menaik']}"
            )
            if lap["selisih_aneh_teratas"]:
                print(f"        selisih ts tak normal teratas: {lap['selisih_aneh_teratas']}")

    # sapuan cepat seluruh berkas 5m untuk cari masalah sistemik
    print("\n=== SAPUAN CEPAT SELURUH BERKAS 5m ===")
    total_dup = total_gap = total_ohlc = total_rusak = 0
    header_beda = []
    baris_per_simbol = {}
    for s, m in per_simbol.items():
        if "5m" not in m:
            continue
        lap = periksa(os.path.join(DIR, m["5m"]), "5m")
        baris_per_simbol[s] = lap["baris"]
        total_dup += lap["duplikat_ts"]
        total_gap += lap.get("gap", 0)
        total_ohlc += lap.get("ohlc_tidak_konsisten", 0)
        total_rusak += lap["baris_rusak"]
        if not lap["header_cocok"]:
            header_beda.append((s, lap["header"]))
    print(f"total duplikat ts        : {total_dup}")
    print(f"total gap                : {total_gap}")
    print(f"total OHLC tak konsisten : {total_ohlc}")
    print(f"total baris rusak        : {total_rusak}")
    print(f"header menyimpang        : {header_beda if header_beda else 'tidak ada'}")
    n = sorted(baris_per_simbol.values())
    print(f"baris 5m: min={n[0]} median={n[len(n)//2]} maks={n[-1]}")
    pendek = sorted((v, k) for k, v in baris_per_simbol.items())[:8]
    print(f"8 simbol dengan riwayat 5m terpendek: {[(k, v) for v, k in pendek]}")

    os.makedirs("/data/lux/reports", exist_ok=True)
    with open("/data/lux/reports/audit_dataset.json", "w") as f:
        json.dump(
            {
                "jumlah_berkas": len(berkas),
                "jumlah_simbol": len(per_simbol),
                "per_tf": dict(tf_hitung),
                "likuiditas_teratas": likuid[:10],
                "audit_kandidat": hasil,
                "sapuan_5m": {
                    "duplikat": total_dup,
                    "gap": total_gap,
                    "ohlc_salah": total_ohlc,
                    "rusak": total_rusak,
                },
            },
            f,
            indent=2,
            default=str,
        )
    print("\nlaporan ditulis ke /data/lux/reports/audit_dataset.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
