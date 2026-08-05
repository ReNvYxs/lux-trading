"""Verifikasi implementasi indikator/strategi modul terhadap teori kanonik.

Skrip ini TIDAK mengubah apa pun di lux_modul. Ia hanya membandingkan keluaran
implementasi modul dengan implementasi rujukan independen (alat/teori/referensi.py)
di atas data OHLCV nyata, lalu menuliskan bukti angka ke bukti/teori/.

Keluaran:
- bukti/teori/PARAMETER_26.json  : metadata + sumber teori yang dideklarasikan modul
- bukti/teori/TEORI.json         : seluruh hasil pembandingan
- bukti/teori/RINGKAS_TEORI.json : ringkasan pendek untuk dibaca cepat
"""
from __future__ import annotations

import csv
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())

import numpy as np

import referensi as ref

from lux_modul.kontrak import Bars
from lux_modul.fitur import dasar as ds
from lux_modul.fitur import lanjutan as lj

KELUARAN = os.path.join("bukti", "teori")


def banding(nama, a, b, catatan=""):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    n = int(min(a.size, b.size))
    a = a[:n]
    b = b[:n]
    sah = np.isfinite(a) & np.isfinite(b)
    hanya_a = int(np.sum(np.isfinite(a) & ~np.isfinite(b)))
    hanya_b = int(np.sum(np.isfinite(b) & ~np.isfinite(a)))
    if not sah.any():
        return {
            "nama": nama,
            "status": "TIDAK_ADA_TUMPANG_TINDIH",
            "hanya_modul": hanya_a,
            "hanya_rujukan": hanya_b,
            "catatan": catatan,
        }
    d = np.abs(a[sah] - b[sah])
    skala = np.maximum(np.abs(b[sah]), 1e-12)
    rel = d / skala
    return {
        "nama": nama,
        "n_dibanding": int(sah.sum()),
        "maks_selisih_abs": float(d.max()),
        "maks_selisih_rel": float(rel.max()),
        "rerata_selisih_rel": float(rel.mean()),
        "identik": bool(rel.max() <= 1e-9),
        "hanya_modul": hanya_a,
        "hanya_rujukan": hanya_b,
        "catatan": catatan,
    }


def muat_csv(jalur):
    with open(jalur, "r", encoding="utf-8", errors="replace") as fh:
        baris = list(csv.reader(fh))
    if len(baris) < 2:
        raise ValueError("csv terlalu pendek: " + jalur)
    kepala = [str(x).strip().lower() for x in baris[0]]
    alias = {
        "ts": ("ts", "time", "timestamp", "open_time", "opentime", "date"),
        "open": ("open", "o"),
        "high": ("high", "h"),
        "low": ("low", "l"),
        "close": ("close", "c"),
        "volume": ("volume", "v", "vol"),
    }
    idx = {}
    for kunci in alias:
        pos = -1
        for nm in alias[kunci]:
            if nm in kepala:
                pos = kepala.index(nm)
                break
        if pos < 0:
            raise ValueError("kolom hilang: " + kunci + " pada " + jalur + " kepala=" + ",".join(kepala))
        idx[kunci] = pos
    maks = max(idx.values())
    kolom = {}
    for kunci in alias:
        kolom[kunci] = []
    for r in baris[1:]:
        if len(r) <= maks:
            continue
        try:
            nilai = {}
            for kunci in alias:
                nilai[kunci] = float(r[idx[kunci]])
        except ValueError:
            continue
        for kunci in alias:
            kolom[kunci].append(nilai[kunci])
    return kolom


def buat_bars(kolom, tf, simbol):
    ts_semua = np.asarray(kolom["ts"], dtype=np.int64)
    urut = np.argsort(ts_semua, kind="stable")
    ts_urut = ts_semua[urut]
    if ts_urut.size == 0:
        raise ValueError("tidak ada baris data")
    unik = np.concatenate(([True], np.diff(ts_urut) > 0))
    pilih = urut[unik]
    return Bars(
        tf=tf,
        ts=ts_semua[pilih],
        open=np.asarray(kolom["open"], dtype=float)[pilih],
        high=np.asarray(kolom["high"], dtype=float)[pilih],
        low=np.asarray(kolom["low"], dtype=float)[pilih],
        close=np.asarray(kolom["close"], dtype=float)[pilih],
        volume=np.asarray(kolom["volume"], dtype=float)[pilih],
        simbol=simbol,
    )


def dump_metadata():
    from lux_modul import plugin as pl

    pl.muat_plugin()
    pola = []
    for nama in sorted(pl.KATALOG_POLA):
        s = pl.KATALOG_POLA[nama]
        pola.append(
            {
                "id": s.nama,
                "kelompok": s.kelompok,
                "ambang": s.ambang,
                "warmup": s.warmup,
                "konteks": s.konteks,
                "horizon": list(s.horizon),
                "sl_atr": s.sl_atr,
                "rr": list(s.rr),
                "porsi": list(s.porsi),
                "deskripsi": s.deskripsi,
                "sumber": list(s.sumber),
                "modul_detektor": getattr(s.detektor, "__module__", "?"),
            }
        )
    kelas = []
    for nama in sorted(pl.KATALOG_STRATEGI):
        k = pl.KATALOG_STRATEGI[nama]
        kelas.append(
            {
                "id": nama,
                "kelas": getattr(k, "__name__", "?"),
                "modul": getattr(k, "__module__", "?"),
            }
        )
    return {
        "jumlah_pola": len(pola),
        "jumlah_kelas_strategi": len(kelas),
        "jumlah_indikator": len(pl.KATALOG_INDIKATOR),
        "daftar_indikator": sorted(pl.KATALOG_INDIKATOR),
        "jumlah_multi_tf": int(sum(1 for p in pola if p["konteks"] >= 1)),
        "jumlah_single_tf": int(sum(1 for p in pola if p["konteks"] == 0)),
        "tanpa_sumber": [p["id"] for p in pola if not p["sumber"]],
        "per_kelompok": _hitung_kelompok(pola),
        "pola": pola,
        "kelas_strategi": kelas,
    }


def _hitung_kelompok(pola):
    hasil = {}
    for p in pola:
        k = p["kelompok"]
        hasil[k] = int(hasil.get(k, 0)) + 1
    return hasil


def uji_indikator(b):
    c = np.asarray(b.close, dtype=float)
    h = np.asarray(b.high, dtype=float)
    l = np.asarray(b.low, dtype=float)
    v = np.asarray(b.volume, dtype=float)
    out = []

    out.append(banding("sma_20", ds.sma(c, 20), ref.sma_ref(c, 20), "rata-rata sederhana"))
    out.append(
        banding(
            "ema_20_vs_rekursi_penuh",
            ds.ema(c, 20),
            ref.ema_ref(c, 20),
            "menguji klaim modul bahwa pemotongan jendela rekursi tidak mengubah nilai",
        )
    )
    out.append(banding("ema_200_vs_rekursi_penuh", ds.ema(c, 200), ref.ema_ref(c, 200), "EMA panjang"))
    out.append(banding("rma_14_wilder", ds.rma(c, 14), ref.rma_ref(c, 14), "pemulusan Wilder 1978"))
    out.append(banding("rsi_14_wilder", ds.rsi(c, 14), ref.rsi_ref(c, 14), "RSI Wilder 1978"))

    gm, sm, hm = ds.macd(c, 12, 26, 9)
    gr, sr, hr = ref.macd_ref(c, 12, 26, 9)
    out.append(banding("macd_garis_12_26", gm, gr, "Appel: EMA12 - EMA26"))
    out.append(banding("macd_sinyal_9", sm, sr, "EMA9 atas garis MACD"))

    out.append(banding("true_range", ds.true_range(h, l, c), ref.tr_ref(h, l, c), "Wilder TR"))
    out.append(banding("atr_14_wilder", ds.atr(h, l, c, 14), ref.atr_ref(h, l, c, 14), "ATR Wilder"))

    st = ds.stdev(c, 20)
    out.append(
        banding("stdev_20_vs_populasi", st, ref.stdev_pop_ref(c, 20), "Bollinger kanonik: pembagi n")
    )
    out.append(
        banding(
            "stdev_20_vs_sampel_pembanding_negatif",
            st,
            ref.stdev_sampel_ref(c, 20),
            "HARUS berbeda; kalau identik berarti modul salah pakai pembagi n-1",
        )
    )

    ba, bm, bb = ds.bollinger(c, 20, 2.0)
    ra, rm, rb = ref.bollinger_ref(c, 20, 2.0)
    out.append(banding("bollinger_atas_20_2", ba, ra, "SMA20 + 2 * stdev populasi"))
    out.append(banding("bollinger_bawah_20_2", bb, rb, ""))

    da, db = lj.donchian(b, 20)
    ra2, rb2 = ref.donchian_ref(h, l, 20)
    out.append(banding("donchian_atas_tergeser", da, ra2, "channel dari 20 bar SEBELUM bar berjalan"))
    na, nb = ref.donchian_tanpa_geser(h, l, 20)
    out.append(
        banding(
            "donchian_atas_vs_varian_ceroboh",
            da,
            na,
            "HARUS berbeda; kalau identik berarti bar berjalan ikut dihitung (look-ahead)",
        )
    )
    pelanggaran = 0
    for i in range(20, h.size):
        if np.isfinite(da[i]) and abs(da[i] - float(h[i - 20 : i].max())) > 1e-9:
            pelanggaran += 1
    tembus_atas = int(np.sum(np.isfinite(da) & (c > da)))
    tembus_bawah = int(np.sum(np.isfinite(db) & (c < db)))
    out.append(
        {
            "nama": "donchian_struktur",
            "pelanggaran_definisi": pelanggaran,
            "bar_close_di_atas_channel": tembus_atas,
            "bar_close_di_bawah_channel": tembus_bawah,
            "catatan": "jumlah tembusan harus > 0; kalau 0 berarti channel memuat bar berjalan sehingga mustahil ditembus",
        }
    )

    gs, ar = lj.supertrend(b, 10, 3.0)
    rg, rar = ref.supertrend_ref(h, l, c, 10, 3.0)
    out.append(banding("supertrend_garis_10_3", gs, rg, "Seban: ATR10, pengali 3"))
    beda_arah = int(np.sum(np.isfinite(gs) & np.isfinite(rg) & (ar != rar)))
    ratchet = 0
    for i in range(1, gs.size):
        if not (np.isfinite(gs[i]) and np.isfinite(gs[i - 1])):
            continue
        if ar[i] > 0 and ar[i - 1] > 0 and gs[i] < gs[i - 1] - 1e-9:
            ratchet += 1
        if ar[i] < 0 and ar[i - 1] < 0 and gs[i] > gs[i - 1] + 1e-9:
            ratchet += 1
    out.append(
        {
            "nama": "supertrend_sifat",
            "bar_arah_berbeda": beda_arah,
            "pelanggaran_ratchet": ratchet,
            "jumlah_flip": int(np.sum(np.abs(np.diff(ar)) > 0)),
            "catatan": "dalam satu leg tren, garis supertrend tidak boleh mundur (sifat trailing stop)",
        }
    )

    ax, pdi, mdi = lj.adx(b, 14)
    rax, rpdi, rmdi = ref.adx_ref(h, l, c, 14)
    out.append(
        banding(
            "adx_14_vs_wilder_bersih",
            ax,
            rax,
            "selisih menandakan pencemaran nol pada penyemaian ADX saat warmup",
        )
    )
    for batas in (30, 60, 100, 150, 200):
        if ax.size > batas:
            a1 = ax[batas:]
            a2 = rax[batas:]
            sah = np.isfinite(a1) & np.isfinite(a2)
            if sah.any():
                d = np.abs(a1[sah] - a2[sah])
                out.append(
                    {
                        "nama": "adx_selisih_sesudah_bar_" + str(batas),
                        "maks_selisih_abs": float(d.max()),
                        "rerata_selisih_abs": float(d.mean()),
                        "n": int(sah.sum()),
                    }
                )

    ka, km, kb = lj.keltner(b, 20, 2.0)
    ema20 = ref.ema_ref(c, 20)
    atr20 = ref.atr_ref(h, l, c, 20)
    out.append(
        banding(
            "keltner_modul_vs_ema20_atr20",
            ka,
            ema20 + 2.0 * atr20,
            "membuktikan periode ATR modul mengikuti periode EMA",
        )
    )
    kra, krm, krb = ref.keltner_raschke_ref(h, l, c, 20, 2.0, 10)
    out.append(
        banding(
            "keltner_modul_vs_baku_stockcharts_20_2_atr10",
            ka,
            kra,
            "baku StockCharts/Raschke memakai ATR(10); selisih = penyimpangan parameter",
        )
    )
    lm = np.asarray(ka - kb, dtype=float)
    lb_ = np.asarray(kra - krb, dtype=float)
    sah = np.isfinite(lm) & np.isfinite(lb_) & (lb_ > 0)
    out.append(
        {
            "nama": "keltner_rasio_lebar_pita",
            "rerata_lebar_modul_dibagi_baku": float(np.mean(lm[sah] / lb_[sah])) if sah.any() else None,
            "n": int(sah.sum()),
            "catatan": "rasio 1.0 berarti setara; menjauh dari 1.0 berarti pita modul lebih lebar/sempit",
        }
    )

    sq = lj.squeeze_bb_kc(b, 20, 2.0, 1.5)
    aa, am, ab = ref.keltner_asli_ref(h, l, c, 20, 1.5)
    sq_carter = ref.squeeze_ref(ba, bb, aa, ab)
    sah = np.isfinite(sq) & np.isfinite(sq_carter)
    beda = int(np.sum(sah & (sq != sq_carter)))
    out.append(
        {
            "nama": "squeeze_modul_vs_carter_keltner_asli",
            "bar_dibanding": int(sah.sum()),
            "bar_berbeda": beda,
            "porsi_berbeda": float(beda) / float(max(int(sah.sum()), 1)),
            "squeeze_aktif_modul": int(np.nansum(sq)),
            "squeeze_aktif_carter": int(np.nansum(sq_carter)),
            "catatan": "Carter/StockCharts memakai rumus Keltner ASLI 1960 untuk TTM Squeeze",
        }
    )

    km_, dm_ = lj.stoch_rsi(b, 14, 14, 3)
    kr_, dr_ = ref.stoch_rsi_ref(c, 14, 14, 3)
    out.append(banding("stoch_rsi_k", km_, kr_, "Chande dan Kroll"))

    vw = lj.vwap_sesi(b, 86400000)
    vwr = ref.vwap_sesi_ref(b.ts, h, l, c, v, 86400000)
    out.append(banding("vwap_sesi_harian", vw, vwr, "harga tipikal tertimbang volume, reset harian UTC"))

    out.append(banding("rasio_volume_20", ds.rasio_volume(v, 20), v / ref.sma_ref(v, 20), "volume / SMA volume"))

    vp = lj.volume_profile(b, 240, 48, 0.70)
    if vp is not None:
        di_dalam = float(
            np.sum(vp.bin_volume[(vp.bin_harga >= vp.val) & (vp.bin_harga <= vp.vah)])
        )
        lebar_bin = float(vp.bin_harga[1] - vp.bin_harga[0]) if vp.bin_harga.size > 1 else 0.0
        tepi = np.concatenate((vp.bin_harga - lebar_bin / 2.0, [vp.bin_harga[-1] + lebar_bin / 2.0]))
        pas = ref.value_area_pasangan_ref(tepi, vp.bin_volume, 0.70)
        out.append(
            {
                "nama": "volume_profile_value_area",
                "porsi_volume_di_dalam_va_modul": round(di_dalam / vp.total, 6),
                "poc": float(vp.poc),
                "val_modul": float(vp.val),
                "vah_modul": float(vp.vah),
                "val_cbot_berpasangan": pas[0] if pas else None,
                "vah_cbot_berpasangan": pas[1] if pas else None,
                "porsi_cbot_berpasangan": round(pas[2], 6) if pas else None,
                "catatan": "Market Profile klasik memperluas value area dua baris sekaligus, modul satu bin",
            }
        )
    return out


def uji_stabilitas_numerik():
    """Menguji bentuk komputasi stdev modul (jumlah kuadrat kumulatif) terhadap
    rumus dua lintasan yang eksak, pada deret panjang berharga tinggi."""
    acak = np.random.default_rng(7)
    n = 60000
    harga = 100000.0 + np.cumsum(acak.normal(0.0, 30.0, n))
    harga = np.maximum(harga, 1000.0)
    st_modul = ds.stdev(harga, 20)
    st_ref = ref.stdev_pop_ref(harga, 20)
    sah = np.isfinite(st_modul) & np.isfinite(st_ref) & (st_ref > 0)
    d = np.abs(st_modul[sah] - st_ref[sah])
    rel = d / st_ref[sah]
    negatif = int(np.sum(np.isfinite(st_modul) & (st_modul < 0)))
    return {
        "n_bar": int(n),
        "harga_rerata": float(np.mean(harga)),
        "maks_selisih_abs": float(d.max()),
        "maks_selisih_rel": float(rel.max()),
        "rerata_selisih_rel": float(rel.mean()),
        "stdev_negatif": negatif,
        "catatan": "modul memakai q/n - (s/n)^2 dari cumsum; rentan cancellation pada deret panjang berharga besar",
    }


def uji_aljabar():
    out = []
    tinggi = 108.0
    rendah = 92.0
    tutup = 101.0
    p_mod = lj.pivot_klasik(tinggi, rendah, tutup)
    p_ref = ref.pivot_ref(tinggi, rendah, tutup)
    sel = {}
    for k in p_ref:
        sel[k] = abs(float(p_mod[k]) - float(p_ref[k]))
    out.append(
        {
            "nama": "pivot_klasik",
            "maks_selisih": float(max(sel.values())),
            "rinci": sel,
            "catatan": "pivot lantai klasik",
        }
    )
    awal = 100.0
    akhir = 150.0
    f_mod = lj.fibonacci(awal, akhir)
    f_ref = ref.fib_ref(awal, akhir)
    sel2 = {}
    for k in f_ref:
        if k in f_mod:
            sel2[k] = abs(float(f_mod[k]) - float(f_ref[k]))
    out.append(
        {
            "nama": "fibonacci",
            "maks_selisih": float(max(sel2.values())) if sel2 else None,
            "rinci": sel2,
            "punya_golden_pocket": bool("0.618" in f_mod and "0.65" in f_mod),
            "kunci": sorted(f_mod.keys()),
            "catatan": "golden pocket kanonik 0.618 sampai 0.65",
        }
    )
    return out


def buat_ringkas(hasil):
    meta = hasil.get("metadata", {})
    cocok = []
    tidak_cocok = []
    struktural = []
    for blok in hasil.get("data", []):
        tf = str(blok.get("tf"))
        for u in blok.get("uji", []) or []:
            nama = tf + ":" + str(u.get("nama"))
            if "identik" in u:
                if u["identik"]:
                    cocok.append(nama)
                else:
                    tidak_cocok.append(
                        {
                            "uji": nama,
                            "maks_selisih_rel": u.get("maks_selisih_rel"),
                            "maks_selisih_abs": u.get("maks_selisih_abs"),
                            "catatan": u.get("catatan"),
                        }
                    )
            else:
                salinan = dict(u)
                salinan["uji"] = nama
                struktural.append(salinan)
    return {
        "jumlah_pola": meta.get("jumlah_pola"),
        "jumlah_kelas_strategi": meta.get("jumlah_kelas_strategi"),
        "jumlah_indikator": meta.get("jumlah_indikator"),
        "jumlah_multi_tf": meta.get("jumlah_multi_tf"),
        "jumlah_single_tf": meta.get("jumlah_single_tf"),
        "per_kelompok": meta.get("per_kelompok"),
        "tanpa_sumber": meta.get("tanpa_sumber"),
        "cocok_persis": cocok,
        "tidak_cocok": tidak_cocok,
        "struktural": struktural,
        "stabilitas_numerik": hasil.get("stabilitas_numerik"),
        "aljabar": hasil.get("aljabar"),
        "galat": [k for k in hasil if str(k).endswith("galat")],
    }


def utama():
    os.makedirs(KELUARAN, exist_ok=True)
    hasil = {"versi": 1}
    try:
        hasil["metadata"] = dump_metadata()
    except Exception:
        hasil["metadata_galat"] = traceback.format_exc()[-2000:]

    berkas = [
        (os.path.join("dataset_masuk", "btc", "BTC_4h.csv"), "4h"),
        (os.path.join("dataset_masuk", "btc", "BTC_1d.csv"), "1d"),
    ]
    hasil["data"] = []
    for jalur, tf in berkas:
        blok = {"jalur": jalur, "tf": tf, "ada": os.path.exists(jalur)}
        if blok["ada"]:
            try:
                kolom = muat_csv(jalur)
                b = buat_bars(kolom, tf, "BTCUSDT")
                blok["jumlah_bar"] = int(len(b))
                blok["harga_awal"] = float(b.close[0])
                blok["harga_akhir"] = float(b.close[-1])
                blok["uji"] = uji_indikator(b)
            except Exception:
                blok["galat"] = traceback.format_exc()[-2000:]
        hasil["data"].append(blok)

    try:
        hasil["stabilitas_numerik"] = uji_stabilitas_numerik()
    except Exception:
        hasil["stabilitas_galat"] = traceback.format_exc()[-2000:]

    try:
        hasil["aljabar"] = uji_aljabar()
    except Exception:
        hasil["aljabar_galat"] = traceback.format_exc()[-2000:]

    if "metadata" in hasil:
        with open(os.path.join(KELUARAN, "PARAMETER_26.json"), "w", encoding="utf-8") as fh:
            json.dump(hasil["metadata"], fh, indent=1, ensure_ascii=False, default=str)

    with open(os.path.join(KELUARAN, "TEORI.json"), "w", encoding="utf-8") as fh:
        json.dump(hasil, fh, indent=1, ensure_ascii=False, default=str)

    ringkas = buat_ringkas(hasil)
    with open(os.path.join(KELUARAN, "RINGKAS_TEORI.json"), "w", encoding="utf-8") as fh:
        json.dump(ringkas, fh, indent=1, ensure_ascii=False, default=str)

    print(json.dumps(ringkas, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    utama()
