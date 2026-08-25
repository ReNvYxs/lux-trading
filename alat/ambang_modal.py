"""Ambang modal: dari 1 USDT sampai batas terkecil yang masih bisa dipakai mesin.

PERTANYAANNYA. Mulai modal berapa mesin ini benar-benar bisa mengirim satu
setup yang sah dan aman? Jawabannya tidak bisa dikarang, karena yang mengikat
adalah tiga hal sekaligus: minimum notional bursa per simbol, batas leverage
per simbol, dan batas risiko kita sendiri terhadap saldo.

KENAPA SALDO DISUNTIK, BUKAN DIKURAS. Saldo testnet tidak bisa disetel ke angka
sembarang; menghabiskannya lewat trading justru merusak akun uji. Yang penting:
seluruh perhitungan ukuran di mesin menerima saldo sebagai PARAMETER
(rencana_mikro(saldo, ...) dan hitung_ukuran(saldo, ...)). Jadi menyuntikkan
saldo 1,00 menguji jalur kode yang sama persis dengan akun bersaldo 1 USDT.
Bukti bahwa order hasil hitungan itu benar-benar diterima bursa diambil
terpisah oleh uji hidup.

DUA ARTI "ICE BREAKER". Di modul ini IceBreakerExecutor adalah pemecah order
BESAR (AMBANG_NOTIONAL_ICEBREAKER = 5000 USDT, dipotong per 2500). Itu ujung
yang berlawanan dengan modal minimum. Keduanya dicetak supaya tidak tertukar.

Biaya rate-limit: 3 permintaan untuk seluruh bursa (exchangeInfo bobot 1,
ticker/price tanpa simbol bobot 2, leverageBracket tanpa simbol bobot 1).
"""
import base64
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())

KUNCI_B64 = "WXVwdU1EWjI3Z0tqY1NlSjd5UHBwU25rUmFJSk9ZWVNoUlFjYVdLSThBOVdKblJVb0RZSm5JZmxyaHlUUHdwZQ=="
RAHASIA_B64 = "TVJld29CSEV4Yno1NG1FWEhteW1GZzdtalNQbGZxTG9ZVWFHZHl2enliYTh3SmJQU1Y1cWRmOUExaWF0N0NHUQ=="

KELUARAN = os.environ.get("AMBANG_KELUARAN", "bukti/mikro/AMBANG_MODAL.json")
TANGGA = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
          12.0, 15.0, 19.0, 19.99, 20.0, 25.0]
GRID_SL = [float(x) for x in
           (os.environ.get("LUX_SL_GRID") or "0.5,1.0,1.5,2.0,3.0,5.0").split(",")
           if str(x).strip()]
BASE = 0.20
_EPS = 1e-9


def kelipatan(nilai, satuan):
    """True bila nilai adalah kelipatan satuan, dengan toleransi relatif."""
    s = float(satuan or 0.0)
    if s <= 0:
        return True
    r = float(nilai) / s
    return abs(r - round(r)) <= 1e-6 * max(1.0, abs(r))


def main():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()

    from lux_modul.eksekusi import AMBANG_NOTIONAL_ICEBREAKER
    from lux_modul.eksekusi.binance_client import BinanceFuturesClient
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.ukuran_mikro import (BATAS_MODAL_KECIL_BAWAAN,
                                                 RISIKO_MAKS_BAWAAN,
                                                 modal_mikro, rencana_mikro)
    from lux_modul.eksekusi_aman.inti import SpekSimbol

    print("ambang_notional_icebreaker=" + str(AMBANG_NOTIONAL_ICEBREAKER))
    print("batas_modal_mikro=" + str(BATAS_MODAL_KECIL_BAWAAN))
    print("risiko_maks_bawaan=" + str(RISIKO_MAKS_BAWAAN))

    klien = BinanceFuturesClient(muat_kredensial(MODE_TESTNET))
    info = klien.exchange_info()
    daftar_harga = klien._permintaan("GET", "/fapi/v1/ticker/price", {}, False)
    harga_map = {}
    for h in daftar_harga or []:
        try:
            harga_map[h.get("symbol")] = float(h.get("price"))
        except (TypeError, ValueError):
            pass
    lev_map = {}
    for b in klien.bracket_leverage() or []:
        lev = 0
        for x in b.get("brackets") or []:
            try:
                lev = max(lev, int(x.get("initialLeverage") or 0))
            except (TypeError, ValueError):
                pass
        if b.get("symbol"):
            lev_map[b["symbol"]] = lev or 125

    semesta = []
    for s in info.get("symbols") or []:
        sim = s.get("symbol")
        if (s.get("status") != "TRADING" or s.get("quoteAsset") != "USDT"
                or s.get("contractType") != "PERPETUAL"):
            continue
        harga = harga_map.get(sim)
        if not harga or harga <= 0:
            continue
        try:
            spek = SpekSimbol.dari_exchange_info(info, sim)
        except Exception:  # noqa: BLE001
            continue
        semesta.append((sim, harga, spek, lev_map.get(sim, 125)))
    print("simbol_dievaluasi=" + str(len(semesta)))

    def rencanakan(saldo, sl_pct, sim, harga, spek, lev):
        return rencana_mikro(saldo, harga, spek,
                             sl_harga=harga * (1.0 - sl_pct / 100.0),
                             arah="LONG", leverage_maks_bursa=lev)

    def sapu(saldo, sl_pct):
        layak, base_ok, termurah = 0, 0, None
        for (sim, harga, spek, lev) in semesta:
            try:
                r = rencanakan(saldo, sl_pct, sim, harga, spek, lev)
            except Exception:  # noqa: BLE001
                continue
            if not r.get("layak"):
                continue
            layak += 1
            if r.get("base_tercapai"):
                base_ok += 1
            m = float(r.get("margin_nyata") or 9e9)
            if termurah is None or m < termurah[1]:
                termurah = (sim, m, r)
        return {"layak": layak, "base_tercapai": base_ok,
                "termurah_simbol": None if termurah is None else termurah[0],
                "termurah_margin": None if termurah is None else round(termurah[1], 8),
                "rencana": None if termurah is None else termurah[2]}

    matriks = {}
    print("--- jumlah simbol LAYAK per (saldo x jarak SL) ---")
    print("saldo|" + "|".join("sl" + str(x) + "%" for x in GRID_SL))
    for saldo in TANGGA:
        kolom = []
        for sl in GRID_SL:
            h = sapu(saldo, sl)
            matriks[str(saldo) + "|" + str(sl)] = {
                k: h[k] for k in ("layak", "base_tercapai", "termurah_simbol",
                                  "termurah_margin")}
            kolom.append(str(h["layak"]))
        print(str(saldo) + "|" + "|".join(kolom))
    print("catatan_tangga=saldo >= " + str(BATAS_MODAL_KECIL_BAWAAN) +
          " keluar dari rezim mikro; sizing beralih ke risiko biasa di inti.py"
          " sehingga kolom mikro wajar bernilai 0")

    # Ambang tepat per jarak SL, dicari dengan bagi dua di dalam rezim mikro.
    def ada_yang_layak(saldo, sl_pct):
        for (sim, harga, spek, lev) in semesta:
            try:
                if rencanakan(saldo, sl_pct, sim, harga, spek, lev).get("layak"):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    ambang = {}
    for sl in GRID_SL:
        atas = BATAS_MODAL_KECIL_BAWAAN - 0.01
        if not ada_yang_layak(atas, sl):
            ambang[str(sl)] = None
            continue
        lo, hi = 0.01, atas
        if ada_yang_layak(lo, sl):
            ambang[str(sl)] = lo
            continue
        for _ in range(28):
            tengah = (lo + hi) / 2.0
            if ada_yang_layak(tengah, sl):
                hi = tengah
            else:
                lo = tengah
        ambang[str(sl)] = round(hi, 4)
    print("AMBANG_PER_SL=" + json.dumps(ambang))

    terkecil = [v for v in ambang.values() if v is not None]
    ambang_mesin = min(terkecil) if terkecil else None
    print("AMBANG_MESIN_USDT=" + str(ambang_mesin))

    # ---- audit invarian pada saldo tepat 1,00 USDT ----
    pelanggaran = {"bukan_kelipatan_step": 0, "di_bawah_min_qty": 0,
                   "di_bawah_min_notional": 0, "di_atas_maks_qty": 0,
                   "sl_tidak_kelipatan_tick": 0, "tp_tidak_kelipatan_tick": 0,
                   "harga_sl_tidak_positif": 0, "margin_di_atas_saldo": 0}
    contoh_pelanggaran = []
    diperiksa = 0
    layak_satu = []
    for (sim, harga, spek, lev) in semesta:
        try:
            r = rencanakan(1.0, 1.0, sim, harga, spek, lev)
        except Exception:  # noqa: BLE001
            continue
        qty = r.get("qty")
        if qty is None:
            continue
        diperiksa += 1
        notional = float(r.get("notional") or 0.0)
        tick = float(spek.tick or 0.0)
        sl = harga * 0.99
        tp = harga * 1.02
        sl_b = round(round(sl / tick) * tick, int(spek.presisi_harga)) if tick > 0 else sl
        tp_b = round(round(tp / tick) * tick, int(spek.presisi_harga)) if tick > 0 else tp
        cacat = []
        if not kelipatan(qty, spek.step):
            cacat.append("bukan_kelipatan_step")
        if float(qty) < float(spek.min_qty or 0.0) - _EPS:
            cacat.append("di_bawah_min_qty")
        if notional < float(spek.min_notional or 0.0) - 1e-6:
            cacat.append("di_bawah_min_notional")
        if float(spek.maks_qty or 0.0) and float(qty) > float(spek.maks_qty) + _EPS:
            cacat.append("di_atas_maks_qty")
        if not kelipatan(sl_b, tick):
            cacat.append("sl_tidak_kelipatan_tick")
        if not kelipatan(tp_b, tick):
            cacat.append("tp_tidak_kelipatan_tick")
        if sl_b <= 0:
            cacat.append("harga_sl_tidak_positif")
        if r.get("layak") and float(r.get("margin_nyata") or 0.0) > 1.0:
            cacat.append("margin_di_atas_saldo")
        for c in cacat:
            pelanggaran[c] += 1
        if cacat and len(contoh_pelanggaran) < 8:
            contoh_pelanggaran.append({"simbol": sim, "cacat": cacat,
                                       "qty": qty, "notional": notional,
                                       "step": spek.step, "tick": tick,
                                       "min_qty": spek.min_qty,
                                       "min_notional": spek.min_notional})
        if r.get("layak"):
            layak_satu.append((sim, float(r.get("margin_nyata") or 9e9), r))

    print("VALIDASI_SALDO_1=" + json.dumps({"diperiksa": diperiksa,
                                            "pelanggaran": pelanggaran}))
    if contoh_pelanggaran:
        print("CONTOH_PELANGGARAN=" + json.dumps(contoh_pelanggaran)[:2000])

    layak_satu.sort(key=lambda x: (x[1], x[0]))
    print("layak_pada_saldo_1=" + str(len(layak_satu)))
    print("--- 10 setup termurah pada saldo 1,00 USDT, SL 1% ---")
    print("simbol|minNotional|harga|qty|notional|lev|margin|risiko%|liq%|base")
    for (sim, m, r) in layak_satu[:10]:
        print("|".join([sim, str(r["spek"]["min_notional"]), str(r["harga"]),
                        str(r["qty"]), str(round(float(r["notional"]), 6)),
                        str(r["leverage_dipakai"]), str(round(m, 6)),
                        str(r.get("risiko_pct_dari_saldo")),
                        str(r.get("jarak_likuidasi_pct")),
                        "ok" if r.get("base_tercapai") else "tidak"]))
    if layak_satu:
        print("RENCANA_TERMURAH_SALDO_1=" + json.dumps(layak_satu[0][2],
                                                       default=str)[:1800])

    total_cacat = sum(pelanggaran.values())
    print("TOTAL_PELANGGARAN=" + str(total_cacat))

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump({"tangga": TANGGA, "grid_sl": GRID_SL, "matriks": matriks,
               "ambang_per_sl": ambang, "ambang_mesin_usdt": ambang_mesin,
               "validasi_saldo_1": {"diperiksa": diperiksa,
                                    "pelanggaran": pelanggaran,
                                    "contoh": contoh_pelanggaran},
               "layak_pada_saldo_1": [{"simbol": s, "margin": m}
                                      for (s, m, _r) in layak_satu[:60]],
               "simbol_dievaluasi": len(semesta),
               "ambang_notional_icebreaker": AMBANG_NOTIONAL_ICEBREAKER,
               "mikro_aktif_pada_1": modal_mikro(1.0)},
              fh, indent=1, default=str)
    fh.close()
    print("berkas=" + KELUARAN)
    print("AMBANG_MODAL=SELESAI")
    return 0 if total_cacat == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        print(traceback.format_exc()[-2000:])
        print("AMBANG_MODAL=GAGAL")
        sys.exit(1)
