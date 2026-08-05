"""Teori v3 - mengukur asumsi struktural yang dipakai 26 strategi.

Tidak ada satu baris strategi pun yang diubah. Seluruh angka di berkas ini adalah
HASIL UKUR atas kode yang sedang berjalan, bukan penilaian dari membaca kode.

Yang diukur:
  A. Kontrak skor: bobot komponen tiap pola, pangsa bobot konteks TF yang
     disuntikkan adaptor, dan skor-sendiri minimum agar lolos ambang.
  B. Sensus penolakan per strategi (termasuk TOLAK_GALAT yang senyap).
  C. Pivot fraktal: aturan unik-ketat vs aturan longgar (seri diizinkan).
  D. Garis tren: regresi kuadrat terkecil vs garis dua titik sentuh.
  E. SL Donchian: kanal berlawanan vs stop 2N ala Turtle, mana yang mengikat.
  F. Pivot klasik: jendela bergulir 'periode sebelumnya' vs hari kalender.
  G. EMA200: sentuhan ketat vs pita toleransi.
  H. Dua puncak: toleransi kesamaan 1.2 persen vs rentang literatur.
  I. Parameter vs sumber: aritmetika kalender dan ambang rezim.
"""
import csv
import json
import os
import statistics
import sys

sys.path.insert(0, os.getcwd())

import numpy as np

from lux_modul.data.plane import DataPlane
from lux_modul.fitur import dasar
from lux_modul.fitur import struktur as st
from lux_modul.fitur.store import FeatureStore
from lux_modul.kontrak import (
    ARAH_LONG,
    ARAH_SHORT,
    Bars,
    HORIZON_INTRADAY,
    TFPlan,
    tf_ms,
)
from lux_modul.plugin import KATALOG_POLA
from lux_modul.strategi import registry_bawaan
from lux_modul.strategi.util import bias_konteks

AKAR = os.getcwd()
KELUAR = os.path.join(AKAR, "bukti", "teori3")
DATA = os.path.join(AKAR, "dataset_masuk", "btc")
GALAT = []


def aman(nama, fn, bawaan=None):
    try:
        return fn()
    except Exception as exc:
        GALAT.append(nama + ": " + type(exc).__name__ + ": " + str(exc))
        return bawaan


def muat(nama, tf):
    p = os.path.join(DATA, nama)
    ts = []
    o = []
    h = []
    l = []
    c = []
    v = []
    with open(p, newline="") as f:
        for row in csv.DictReader(f):
            ts.append(int(float(row["ts"])))
            o.append(float(row["open"]))
            h.append(float(row["high"]))
            l.append(float(row["low"]))
            c.append(float(row["close"]))
            v.append(float(row["volume"]))
    return Bars(tf=tf, ts=ts, open=o, high=h, low=l, close=c, volume=v, simbol="BTCUSDT")


def daftar_spek():
    kp = KATALOG_POLA
    if isinstance(kp, dict):
        return list(kp.values())
    return list(kp)


def atribut(obj, nama_calon, indeks_tuple):
    for nama in nama_calon:
        if hasattr(obj, nama):
            return getattr(obj, nama)
    try:
        import dataclasses

        return dataclasses.astuple(obj)[indeks_tuple]
    except Exception:
        return "?"


def ringkas_angka(xs):
    xs = [float(x) for x in xs if x is not None and np.isfinite(x)]
    if not xs:
        return {"n": 0}
    xs_urut = sorted(xs)
    n = len(xs_urut)
    return {
        "n": n,
        "min": round(xs_urut[0], 6),
        "p50": round(statistics.median(xs_urut), 6),
        "p90": round(xs_urut[min(n - 1, int(0.9 * n))], 6),
        "maks": round(xs_urut[-1], 6),
        "rata": round(sum(xs_urut) / n, 6),
    }


# --------------------------------------------------------------------------- #
# A + B: jalankan registry, kumpulkan bobot komponen dan sensus penolakan
# --------------------------------------------------------------------------- #


def jalankan_registry(plane, tfplan, mulai):
    reg = registry_bawaan()
    spek_semua = daftar_spek()
    stat = {}
    bobot = {}
    bias = {"long": 0, "short": 0, "netral": 0}
    b = plane.bars(tfplan.entry_tf)
    n_bar = 0
    for i in range(mulai, len(b)):
        ctx = plane.konteks_pada(i, tfplan, HORIZON_INTRADAY)
        n_bar += 1
        if tfplan.context_tfs:
            bb = bias_konteks(ctx)
            if bb == ARAH_LONG:
                bias["long"] += 1
            elif bb == ARAH_SHORT:
                bias["short"] += 1
            else:
                bias["netral"] += 1
        he = reg.evaluasi_semua(ctx)
        for v in he.verdicts:
            s = stat.setdefault(
                v.strategy_id,
                {"verdict": 0, "lolos_ambang": 0, "skor": [], "tolak": {}},
            )
            s["verdict"] += 1
            s["skor"].append(float(v.skor))
            if bool(v.lolos_ambang):
                s["lolos_ambang"] += 1
        for p in he.penolakan:
            sid = str(atribut(p, ("strategy_id", "sid", "id"), 0))
            kode = str(atribut(p, ("kode", "code"), 1))
            s = stat.setdefault(
                sid, {"verdict": 0, "lolos_ambang": 0, "skor": [], "tolak": {}}
            )
            s["tolak"][kode] = s["tolak"].get(kode, 0) + 1
        for spek in spek_semua:
            nama = str(getattr(spek, "nama", "?"))
            rec = bobot.setdefault(
                nama, {"terpicu": 0, "galat": 0, "bobot_komponen": {}}
            )
            try:
                d = spek.detektor(ctx)
            except Exception:
                rec["galat"] += 1
                continue
            if d is None:
                continue
            rec["terpicu"] += 1
            for k, pasangan in dict(d.komponen).items():
                rec["bobot_komponen"][str(k)] = round(float(pasangan[1]), 6)
    for sid in stat:
        stat[sid]["skor_ringkas"] = ringkas_angka(stat[sid]["skor"])
        del stat[sid]["skor"]
    return {"bar_dievaluasi": n_bar, "per_strategi": stat, "bias_konteks": bias}, bobot


def kontrak_skor(bobot):
    """Pangsa bobot konteks TF dan skor-sendiri minimum agar lolos ambang.

    adaptor.StrategiPola menyuntikkan komponen 'konteks_tf' dengan BOBOT 1.0 untuk
    setiap pola multi-TF. kekuatan_konteks hanya bernilai 0.0, 0.5, atau 1.0.
    lolos_ambang memakai perbandingan KETAT (skor > ambang).
    """
    out = {}
    for spek in daftar_spek():
        nama = str(getattr(spek, "nama", "?"))
        rec = bobot.get(nama, {})
        komponen = rec.get("bobot_komponen", {})
        w = sum(float(x) for x in komponen.values())
        konteks = int(getattr(spek, "konteks", 0))
        ambang = float(getattr(spek, "ambang", 60.0))
        baris = {
            "ambang": ambang,
            "konteks_dibutuhkan": konteks,
            "terpicu": int(rec.get("terpicu", 0)),
            "galat_detektor": int(rec.get("galat", 0)),
            "bobot_komponen": komponen,
            "jumlah_bobot_sendiri": round(w, 6),
        }
        if konteks > 0 and w > 0:
            total = w + 1.0
            baris["bobot_konteks_disuntik"] = 1.0
            baris["pangsa_bobot_konteks"] = round(1.0 / total, 6)
            butuh = {}
            capai = {}
            for kk in (0.0, 0.5, 1.0):
                perlu = (ambang / 100.0 * total - kk) / w
                butuh[str(kk)] = round(float(perlu), 6)
                capai[str(kk)] = round(float((w + kk) / total * 100.0), 4)
            baris["skor_sendiri_minimum"] = butuh
            baris["skor_maksimum_tercapai"] = capai
            baris["terkunci_bila_konteks_menolak"] = bool(capai["0.0"] <= ambang)
        else:
            baris["bobot_konteks_disuntik"] = 0.0
            baris["pangsa_bobot_konteks"] = 0.0
        out[nama] = baris
    return out


# --------------------------------------------------------------------------- #
# C: pivot fraktal ketat vs longgar
# --------------------------------------------------------------------------- #


def sensus_pivot(b, kiri=2, kanan=2):
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    n = h.size
    ketat_h = 0
    longgar_h = 0
    ketat_l = 0
    longgar_l = 0
    for i in range(kiri, n - kanan):
        jh = h[i - kiri : i + kanan + 1]
        if h[i] == jh.max():
            longgar_h += 1
            if np.count_nonzero(jh == h[i]) == 1:
                ketat_h += 1
        jl = l[i - kiri : i + kanan + 1]
        if l[i] == jl.min():
            longgar_l += 1
            if np.count_nonzero(jl == l[i]) == 1:
                ketat_l += 1
    modul = st.pivots(b.high, b.low, kiri, kanan)
    return {
        "bar": int(n),
        "pivot_modul_total": len(modul),
        "high_aturan_ketat": ketat_h,
        "high_aturan_longgar": longgar_h,
        "high_hilang_karena_seri": longgar_h - ketat_h,
        "low_aturan_ketat": ketat_l,
        "low_aturan_longgar": longgar_l,
        "low_hilang_karena_seri": longgar_l - ketat_l,
        "cocok_dengan_modul": bool(len(modul) == ketat_h + ketat_l),
    }


# --------------------------------------------------------------------------- #
# D: garis tren regresi vs garis dua titik
# --------------------------------------------------------------------------- #


def sensus_garis(b, mulai):
    piv = st.pivots(b.high, b.low, 2, 2)
    atr = dasar.atr(b.high, b.low, b.close, 14)
    hi_semua = [p for p in piv if p.tipe == "high"]
    lo_semua = [p for p in piv if p.tipe == "low"]
    kasus = 0
    langgar_atas = 0
    langgar_bawah = 0
    beda = []
    sisa_atas = []
    for i in range(mulai, len(b)):
        a = float(atr[i]) if np.isfinite(atr[i]) else 0.0
        if a <= 0:
            continue
        hi = [p for p in hi_semua if p.idx + 2 <= i][-3:]
        lo = [p for p in lo_semua if p.idx + 2 <= i][-3:]
        if len(hi) < 3 or len(lo) < 3:
            continue
        kasus += 1
        ga = st.garis_lewat_pivot(hi)
        gb = st.garis_lewat_pivot(lo)
        if ga is not None:
            sisa = [p.harga - st.nilai_garis(ga, p.idx) for p in hi]
            sisa_atas.append(max(abs(x) for x in sisa) / a)
            if max(sisa) > 1e-9:
                langgar_atas += 1
            dua = st.garis_lewat_pivot([hi[0], hi[-1]])
            if dua is not None:
                beda.append(
                    abs(st.nilai_garis(ga, i) - st.nilai_garis(dua, i)) / a
                )
        if gb is not None:
            sisa = [st.nilai_garis(gb, p.idx) - p.harga for p in lo]
            if max(sisa) > 1e-9:
                langgar_bawah += 1
    return {
        "kasus_tiga_pivot": kasus,
        "garis_atas_dilanggar_pivotnya_sendiri": langgar_atas,
        "garis_bawah_dilanggar_pivotnya_sendiri": langgar_bawah,
        "fraksi_atas_dilanggar": round(langgar_atas / kasus, 6) if kasus else None,
        "fraksi_bawah_dilanggar": round(langgar_bawah / kasus, 6) if kasus else None,
        "sisa_maks_atas_dalam_atr": ringkas_angka(sisa_atas),
        "selisih_regresi_vs_dua_titik_dalam_atr": ringkas_angka(beda),
    }


# --------------------------------------------------------------------------- #
# E: SL Donchian - kanal berlawanan vs 2N Turtle
# --------------------------------------------------------------------------- #


def sensus_donchian(b, mulai, n_don=20):
    fs = FeatureStore()
    keluaran = fs.hitung("donchian", b, n_don)
    bagian = list(keluaran) if isinstance(keluaran, (tuple, list)) else [keluaran]
    atas = np.asarray(bagian[0], dtype=float)
    bawah = np.asarray(bagian[-1], dtype=float)
    c = np.asarray(b.close, dtype=float)
    atr = dasar.atr(b.high, b.low, b.close, 14)
    pecah = 0
    kanal_mengikat = 0
    dua_atr_mengikat = 0
    jarak = []
    for i in range(max(mulai, 1), len(c)):
        if not (
            np.isfinite(atas[i - 1])
            and np.isfinite(bawah[i])
            and np.isfinite(atr[i])
            and atr[i] > 0
        ):
            continue
        if not (c[i] > atas[i - 1]):
            continue
        pecah += 1
        d = (c[i] - bawah[i]) / atr[i]
        jarak.append(d)
        if d > 2.0:
            kanal_mengikat += 1
        else:
            dua_atr_mengikat += 1
    return {
        "bar_breakout_long": pecah,
        "kanal_berlawanan_mengikat": kanal_mengikat,
        "stop_2atr_mengikat": dua_atr_mengikat,
        "fraksi_stop_lebih_lebar_dari_2N": (
            round(kanal_mengikat / pecah, 6) if pecah else None
        ),
        "jarak_ke_kanal_bawah_dalam_atr": ringkas_angka(jarak),
        "catatan": "sl = min(kanal_bawah, harga - 2*atr); nilai lebih rendah = stop lebih lebar",
    }


# --------------------------------------------------------------------------- #
# F: pivot klasik bergulir vs kalender harian
# --------------------------------------------------------------------------- #


def sensus_pivot_harian(b4, b1d, mulai):
    n = max(1, int(86400000 // int(tf_ms(b4.tf))))
    h = np.asarray(b4.high, dtype=float)
    l = np.asarray(b4.low, dtype=float)
    c = np.asarray(b4.close, dtype=float)
    atr = dasar.atr(b4.high, b4.low, b4.close, 14)
    ts1 = [int(x) for x in b1d.ts]
    h1 = np.asarray(b1d.high, dtype=float)
    l1 = np.asarray(b1d.low, dtype=float)
    c1 = np.asarray(b1d.close, dtype=float)
    dur1 = int(b1d.durasi_ms)
    total = 0
    identik = 0
    dr = []
    ds = []
    hanya_modul_short = 0
    hanya_kal_short = 0
    keduanya_short = 0
    hanya_modul_long = 0
    hanya_kal_long = 0
    keduanya_long = 0
    for i in range(max(mulai, 2 * n + 5), len(c)):
        a = float(atr[i]) if np.isfinite(atr[i]) else 0.0
        if a <= 0:
            continue
        lalu_h = float(h[i - 2 * n + 1 : i - n + 1].max())
        lalu_l = float(l[i - 2 * n + 1 : i - n + 1].min())
        lalu_c = float(c[i - n])
        p_mod = (lalu_h + lalu_l + lalu_c) / 3.0
        r1_mod = 2.0 * p_mod - lalu_l
        s1_mod = 2.0 * p_mod - lalu_h
        tt = int(b4.ts_tutup(i))
        j = -1
        for k in range(len(ts1)):
            if ts1[k] + dur1 <= tt:
                j = k
            else:
                break
        if j < 0:
            continue
        p_kal = (float(h1[j]) + float(l1[j]) + float(c1[j])) / 3.0
        r1_kal = 2.0 * p_kal - float(l1[j])
        s1_kal = 2.0 * p_kal - float(h1[j])
        total += 1
        e_r = abs(r1_mod - r1_kal) / a
        e_s = abs(s1_mod - s1_kal) / a
        dr.append(e_r)
        ds.append(e_s)
        if e_r < 1e-9 and e_s < 1e-9:
            identik += 1
        tol = 0.4 * a
        m_short = bool(h[i] >= r1_mod - tol and c[i] < r1_mod)
        k_short = bool(h[i] >= r1_kal - tol and c[i] < r1_kal)
        if m_short and k_short:
            keduanya_short += 1
        elif m_short:
            hanya_modul_short += 1
        elif k_short:
            hanya_kal_short += 1
        m_long = bool(l[i] <= s1_mod + tol and c[i] > s1_mod)
        k_long = bool(l[i] <= s1_kal + tol and c[i] > s1_kal)
        if m_long and k_long:
            keduanya_long += 1
        elif m_long:
            hanya_modul_long += 1
        elif k_long:
            hanya_kal_long += 1
    return {
        "bar_per_hari_dipakai_modul": n,
        "bar_dibandingkan": total,
        "level_identik": identik,
        "fraksi_identik": round(identik / total, 6) if total else None,
        "selisih_R1_dalam_atr": ringkas_angka(dr),
        "selisih_S1_dalam_atr": ringkas_angka(ds),
        "pemicu_short": {
            "keduanya": keduanya_short,
            "hanya_modul": hanya_modul_short,
            "hanya_kalender": hanya_kal_short,
        },
        "pemicu_long": {
            "keduanya": keduanya_long,
            "hanya_modul": hanya_modul_long,
            "hanya_kalender": hanya_kal_long,
        },
        "catatan": "modul memakai blok bergulir bar i-2n+1..i-n; kalender memakai lilin 1d terakhir yang sudah tutup",
    }


# --------------------------------------------------------------------------- #
# G: EMA200 sentuhan ketat vs pita
# --------------------------------------------------------------------------- #


def sensus_ema200(b, mulai):
    e = dasar.ema(b.close, 200)
    atr = dasar.atr(b.high, b.low, b.close, 14)
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    n = 0
    ketat = 0
    pita_long = 0
    for i in range(mulai, len(h)):
        if not (np.isfinite(e[i]) and np.isfinite(atr[i]) and atr[i] > 0):
            continue
        n += 1
        if l[i] <= e[i] <= h[i]:
            ketat += 1
        if (l[i] - e[i]) <= 0.75 * atr[i] and l[i] >= e[i] - 1.0 * atr[i]:
            pita_long += 1
    return {
        "bar_diperiksa": n,
        "sentuhan_ketat_low_le_ema_le_high": ketat,
        "pita_modul_long": pita_long,
        "rasio_pita_terhadap_sentuhan": (
            round(pita_long / ketat, 4) if ketat else None
        ),
        "kondisi_modul_long": "(low - ema) <= 0.75*atr DAN low >= ema - 1.0*atr",
    }


# --------------------------------------------------------------------------- #
# H: toleransi kesamaan dua puncak
# --------------------------------------------------------------------------- #


def sensus_dua_puncak(b, mulai, jmin=5, jmaks=70):
    piv = st.pivots(b.high, b.low, 2, 2)
    hi = [p for p in piv if p.tipe == "high"]
    ember = {"le_0.012": 0, "0.012_0.03": 0, "0.03_0.05": 0, "gt_0.05": 0}
    total = 0
    for i in range(mulai, len(b)):
        sel = [p for p in hi if p.idx + 2 <= i][-2:]
        if len(sel) < 2:
            continue
        p1, p2 = sel
        jarak = p2.idx - p1.idx
        if not (jmin <= jarak <= jmaks):
            continue
        total += 1
        d = abs(p1.harga - p2.harga) / max(abs(p1.harga), abs(p2.harga), 1e-12)
        if d <= 0.012:
            ember["le_0.012"] += 1
        elif d <= 0.03:
            ember["0.012_0.03"] += 1
        elif d <= 0.05:
            ember["0.03_0.05"] += 1
        else:
            ember["gt_0.05"] += 1
    return {
        "pasangan_lolos_jarak": total,
        "sebaran_kesamaan": ember,
        "diterima_modul": ember["le_0.012"],
        "ditolak_padahal_dalam_5_persen": ember["0.012_0.03"] + ember["0.03_0.05"],
        "toleransi_modul": 0.012,
    }


# --------------------------------------------------------------------------- #
# I: parameter vs sumber
# --------------------------------------------------------------------------- #


def peta_parameter():
    tfs = ["5m", "15m", "1h", "4h", "1d"]

    def jam(bar, tf):
        return round(bar * int(tf_ms(tf)) / 3600000.0, 3)

    return {
        "cup_and_handle_retrace_handle_maks": {
            "modul": 0.40,
            "sumber_sepertiga_kedalaman_cup": round(1.0 / 3.0, 6),
            "selisih_relatif": round((0.40 - 1.0 / 3.0) / (1.0 / 3.0), 6),
        },
        "gerbang_rezim_adx": {
            "keltner_reversi_tolak_di_atas": 22.0,
            "vwap_reversi_pita_tolak_di_atas": 25.0,
            "ambang_tren_wilder": 25.0,
        },
        "jendela_volume_profile_240_bar_dalam_jam": {t: jam(240, t) for t in tfs},
        "double_top_jarak_maks_70_bar_dalam_jam": {t: jam(70, t) for t in tfs},
        "bar_per_hari": {t: int(86400000 // int(tf_ms(t))) for t in tfs},
        "tp_pola_klasik": {
            "modul": [0.618, 1.0],
            "measured_move_baku": [1.0],
            "catatan": "tp1 0.618 adalah tambahan parsial, bukan aturan measured move baku",
        },
    }


# --------------------------------------------------------------------------- #


def main():
    os.makedirs(KELUAR, exist_ok=True)
    registry_bawaan()
    b4 = muat("BTC_4h.csv", "4h")
    b1d = muat("BTC_1d.csv", "1d")
    plane = DataPlane({"4h": b4, "1d": b1d})
    mulai = 300

    hasil = {
        "bar_4h": len(b4),
        "bar_1d": len(b1d),
        "mulai_indeks": mulai,
    }

    single = aman(
        "registry_single_4h",
        lambda: jalankan_registry(plane, TFPlan("4h", ()), mulai),
        ({}, {}),
    )
    hasil["registry_single_4h"] = single[0]
    hasil["kontrak_skor_single"] = aman(
        "kontrak_skor_single", lambda: kontrak_skor(single[1]), {}
    )

    multi = aman(
        "registry_multi_4h_ctx1d",
        lambda: jalankan_registry(plane, TFPlan("4h", ("1d",)), mulai),
        ({}, {}),
    )
    hasil["registry_multi_4h_ctx1d"] = multi[0]
    hasil["kontrak_skor_multi"] = aman(
        "kontrak_skor_multi", lambda: kontrak_skor(multi[1]), {}
    )

    hasil["pivot_ketat_vs_longgar_4h"] = aman(
        "pivot_4h", lambda: sensus_pivot(b4), {}
    )
    hasil["pivot_ketat_vs_longgar_1d"] = aman(
        "pivot_1d", lambda: sensus_pivot(b1d), {}
    )
    hasil["garis_tren_4h"] = aman("garis_4h", lambda: sensus_garis(b4, mulai), {})
    hasil["sl_donchian_4h"] = aman(
        "donchian_4h", lambda: sensus_donchian(b4, mulai), {}
    )
    hasil["pivot_harian_4h"] = aman(
        "pivot_harian_4h", lambda: sensus_pivot_harian(b4, b1d, mulai), {}
    )
    hasil["ema200_4h"] = aman("ema200_4h", lambda: sensus_ema200(b4, mulai), {})
    hasil["dua_puncak_4h"] = aman(
        "dua_puncak_4h", lambda: sensus_dua_puncak(b4, mulai), {}
    )
    hasil["parameter_vs_sumber"] = aman("parameter", peta_parameter, {})
    hasil["galat"] = GALAT

    with open(os.path.join(KELUAR, "TEORI3.json"), "w") as f:
        json.dump(hasil, f, indent=1, sort_keys=True, default=str)

    ringkas = {
        "bar_4h": hasil["bar_4h"],
        "bar_1d": hasil["bar_1d"],
        "galat": GALAT,
        "bias_konteks_multi": hasil.get("registry_multi_4h_ctx1d", {}).get(
            "bias_konteks"
        ),
        "pivot_4h": hasil["pivot_ketat_vs_longgar_4h"],
        "garis_tren_4h": hasil["garis_tren_4h"],
        "sl_donchian_4h": hasil["sl_donchian_4h"],
        "pivot_harian_4h": hasil["pivot_harian_4h"],
        "ema200_4h": hasil["ema200_4h"],
        "dua_puncak_4h": hasil["dua_puncak_4h"],
        "parameter_vs_sumber": hasil["parameter_vs_sumber"],
        "kontrak_skor_multi": hasil["kontrak_skor_multi"],
    }
    with open(os.path.join(KELUAR, "RINGKAS_TEORI3.json"), "w") as f:
        json.dump(ringkas, f, indent=1, sort_keys=True, default=str)

    print(json.dumps(ringkas, indent=1, sort_keys=True, default=str))
    print("galat=" + str(len(GALAT)))


if __name__ == "__main__":
    main()
