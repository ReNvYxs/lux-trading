"""Ambang modal di bawah aturan risiko FLAT 0,20 USDT per trade.

PERTANYAANNYA. Setelah money management persentase dibuang untuk saldo di bawah
20 USDT, mulai modal berapa mesin masih bisa mengirim satu setup yang sah DAN
aman, dan berapa banyak simbol yang benar-benar bisa mempertaruhkan tepat 0,20
USDT? Ini diukur, bukan dikarang.

YANG DIUKUR, PER (saldo x jarak SL), untuk SELURUH simbol USDT perpetual:
  layak        - lolos semua penjaga, jadi boleh dikirim
  flat         - risikonya benar-benar mencapai 0,20 USDT
  susut        - qty disusutkan karena batas porsi margin, jadi flat tak penuh

INVARIAN YANG WAJIB NOL pada setiap rencana yang dinyatakan layak, di seluruh
kombinasi: risiko di atas plafon, likuidasi lebih dekat daripada SL, margin di
atas porsi maksimum, qty bukan kelipatan step, qty di bawah minQty, notional di
bawah minNotional, qty di atas maxQty. Satu saja bukan nol berarti mesin bisa
mengirim order yang salah, jadi rc dibuat bukan nol.

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

KELUARAN = os.environ.get("FLAT_KELUARAN", "bukti/mikro/AMBANG_FLAT.json")
TANGGA = [1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0,
          12.0, 15.0, 19.0, 19.99, 20.0]
GRID_SL = [float(x) for x in
           (os.environ.get("LUX_SL_GRID") or "0.5,1.0,1.5,2.0,3.0,5.0").split(",")
           if str(x).strip()]
_EPS = 1e-9


def kelipatan(nilai, satuan):
    s = float(satuan or 0.0)
    if s <= 0:
        return True
    r = float(nilai) / s
    return abs(r - round(r)) <= 1e-6 * max(1.0, abs(r))


def main():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()

    from lux_modul.eksekusi.binance_client import BinanceFuturesClient
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.ukuran_mikro import (BATAS_MODAL_KECIL_BAWAAN,
                                                 MMR_BAWAAN,
                                                 PORSI_MARGIN_MAKS_BAWAAN,
                                                 RISIKO_FLAT_BAWAAN,
                                                 TOLERANSI_RISIKO_BAWAAN,
                                                 rencana_mikro)
    from lux_modul.eksekusi_aman.inti import SpekSimbol

    plafon = RISIKO_FLAT_BAWAAN * (1.0 + TOLERANSI_RISIKO_BAWAAN)
    print("risiko_flat_usdt=" + str(RISIKO_FLAT_BAWAAN))
    print("toleransi=" + str(TOLERANSI_RISIKO_BAWAAN))
    print("plafon_risiko_usdt=" + str(round(plafon, 8)))
    print("mmr=" + str(MMR_BAWAAN))
    print("porsi_margin_maks=" + str(PORSI_MARGIN_MAKS_BAWAAN))
    print("batas_modal_mikro=" + str(BATAS_MODAL_KECIL_BAWAAN))

    klien = BinanceFuturesClient(muat_kredensial(MODE_TESTNET))
    info = klien.exchange_info()
    harga_map = {}
    for h in klien._permintaan("GET", "/fapi/v1/ticker/price", {}, False) or []:
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

    def rencanakan(saldo, sl_pct, harga, spek, lev):
        return rencana_mikro(saldo, harga, spek,
                            sl_harga=harga * (1.0 - sl_pct / 100.0),
                            arah="LONG", leverage_maks_bursa=lev)

    pelanggaran = {"risiko_di_atas_plafon": 0, "likuidasi_lebih_dekat_dari_sl": 0,
                   "margin_di_atas_porsi": 0, "bukan_kelipatan_step": 0,
                   "di_bawah_min_qty": 0, "di_bawah_min_notional": 0,
                   "di_atas_maks_qty": 0}
    contoh = []

    def periksa(saldo, sl_pct, sim, spek, r):
        cacat = []
        rugi = float(r.get("rugi_pada_sl_usdt") or 0.0)
        if rugi > plafon + 1e-6:
            cacat.append("risiko_di_atas_plafon")
        liq = r.get("jarak_likuidasi_pct")
        sl_p = r.get("jarak_sl_pct")
        if liq is not None and sl_p is not None and float(liq) <= float(sl_p):
            cacat.append("likuidasi_lebih_dekat_dari_sl")
        if float(r.get("margin_nyata") or 0.0) > saldo * PORSI_MARGIN_MAKS_BAWAAN + 1e-6:
            cacat.append("margin_di_atas_porsi")
        qty = float(r.get("qty") or 0.0)
        if not kelipatan(qty, spek.step):
            cacat.append("bukan_kelipatan_step")
        if qty < float(spek.min_qty or 0.0) - _EPS:
            cacat.append("di_bawah_min_qty")
        if float(r.get("notional") or 0.0) < float(spek.min_notional or 0.0) - 1e-6:
            cacat.append("di_bawah_min_notional")
        if float(spek.maks_qty or 0.0) and qty > float(spek.maks_qty) + _EPS:
            cacat.append("di_atas_maks_qty")
        for c in cacat:
            pelanggaran[c] += 1
        if cacat and len(contoh) < 8:
            contoh.append({"simbol": sim, "saldo": saldo, "sl_pct": sl_pct,
                           "cacat": cacat, "qty": qty,
                           "notional": r.get("notional"),
                           "lev": r.get("leverage_dipakai"),
                           "margin": r.get("margin_nyata"),
                           "rugi": rugi, "liq": liq, "sl": sl_p})

    def sapu(saldo, sl_pct):
        layak = flat = susut = 0
        risiko = []
        for (sim, harga, spek, lev) in semesta:
            try:
                r = rencanakan(saldo, sl_pct, harga, spek, lev)
            except Exception:  # noqa: BLE001
                continue
            if not r.get("layak"):
                continue
            layak += 1
            periksa(saldo, sl_pct, sim, spek, r)
            if r.get("risiko_flat_tercapai"):
                flat += 1
            if r.get("disusutkan_karena_margin"):
                susut += 1
            risiko.append(float(r.get("rugi_pada_sl_usdt") or 0.0))
        risiko.sort()
        return {"layak": layak, "flat": flat, "susut": susut,
                "risiko_min": round(risiko[0], 6) if risiko else None,
                "risiko_p50": round(risiko[len(risiko) // 2], 6) if risiko else None,
                "risiko_maks": round(risiko[-1], 6) if risiko else None}

    matriks = {}
    print("--- layak / flat-tercapai / disusutkan, per saldo x jarak SL ---")
    print("saldo|" + "|".join("sl" + str(x) + "%" for x in GRID_SL))
    for saldo in TANGGA:
        kolom = []
        for sl in GRID_SL:
            h = sapu(saldo, sl)
            matriks[str(saldo) + "|" + str(sl)] = h
            kolom.append(str(h["layak"]) + "/" + str(h["flat"]) + "/" +
                         str(h["susut"]))
        print(str(saldo) + "|" + "|".join(kolom))
    print("catatan=saldo 20,0 keluar dari rezim mikro sehingga wajar 0/0/0")

    print("--- risiko nyata (USDT) pada rencana layak: min|p50|maks ---")
    print("saldo|" + "|".join("sl" + str(x) + "%" for x in GRID_SL))
    for saldo in TANGGA:
        kolom = []
        for sl in GRID_SL:
            h = matriks[str(saldo) + "|" + str(sl)]
            kolom.append(str(h["risiko_min"]) + "|" + str(h["risiko_p50"]) +
                         "|" + str(h["risiko_maks"]))
        print(str(saldo) + "|" + "|".join(kolom))

    def ada_layak(saldo, sl_pct):
        for (sim, harga, spek, lev) in semesta:
            try:
                if rencanakan(saldo, sl_pct, harga, spek, lev).get("layak"):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    ambang = {}
    for sl in GRID_SL:
        atas = BATAS_MODAL_KECIL_BAWAAN - 0.01
        if not ada_layak(atas, sl):
            ambang[str(sl)] = None
            continue
        lo, hi = 0.01, atas
        if ada_layak(lo, sl):
            ambang[str(sl)] = lo
            continue
        for _ in range(28):
            tengah = (lo + hi) / 2.0
            if ada_layak(tengah, sl):
                hi = tengah
            else:
                lo = tengah
        ambang[str(sl)] = round(hi, 4)
    print("AMBANG_PER_SL=" + json.dumps(ambang))
    terkecil = [v for v in ambang.values() if v is not None]
    print("AMBANG_MESIN_USDT=" + str(min(terkecil) if terkecil else None))

    # ---- rincian pada saldo tepat 1,00 USDT, SL 1% ----
    baris = []
    for (sim, harga, spek, lev) in semesta:
        try:
            r = rencanakan(1.0, 1.0, harga, spek, lev)
        except Exception:  # noqa: BLE001
            continue
        if r.get("layak"):
            baris.append((sim, float(r.get("margin_nyata") or 9e9), r))
    baris.sort(key=lambda x: (x[1], x[0]))
    print("layak_pada_saldo_1_sl_1pct=" + str(len(baris)))
    flat_penuh = sum(1 for (_s, _m, r) in baris if r.get("risiko_flat_tercapai"))
    print("flat_tercapai_pada_saldo_1=" + str(flat_penuh))
    print("--- 10 setup termurah margin pada saldo 1,00 USDT, SL 1% ---")
    print("simbol|harga|qty|notional|lev|margin|margin%|rugi|risiko%|liq%")
    for (sim, m, r) in baris[:10]:
        print("|".join([sim, str(r["harga"]), str(r["qty"]),
                        str(round(float(r["notional"]), 6)),
                        str(r["leverage_dipakai"]), str(round(m, 6)),
                        str(r.get("margin_pct_dari_saldo")),
                        str(r.get("rugi_pada_sl_usdt")),
                        str(r.get("risiko_pct_dari_saldo")),
                        str(r.get("jarak_likuidasi_pct"))]))
    if baris:
        print("RENCANA_TERMURAH_SALDO_1=" +
              json.dumps(baris[0][2], default=str)[:1500])

    print("PELANGGARAN=" + json.dumps(pelanggaran))
    if contoh:
        print("CONTOH_PELANGGARAN=" + json.dumps(contoh, default=str)[:2000])
    total = sum(pelanggaran.values())
    print("TOTAL_PELANGGARAN=" + str(total))

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump({"risiko_flat": RISIKO_FLAT_BAWAAN,
               "toleransi": TOLERANSI_RISIKO_BAWAAN,
               "plafon": round(plafon, 8), "mmr": MMR_BAWAAN,
               "porsi_margin_maks": PORSI_MARGIN_MAKS_BAWAAN,
               "tangga": TANGGA, "grid_sl": GRID_SL, "matriks": matriks,
               "ambang_per_sl": ambang, "simbol_dievaluasi": len(semesta),
               "layak_saldo_1_sl_1pct": len(baris),
               "flat_tercapai_saldo_1": flat_penuh,
               "pelanggaran": pelanggaran, "contoh": contoh,
               "termurah_saldo_1": [{"simbol": s, "margin": m}
                                    for (s, m, _r) in baris[:60]]},
              fh, indent=1, default=str)
    fh.close()
    print("berkas=" + KELUARAN)
    print("AMBANG_FLAT=SELESAI")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        print(traceback.format_exc()[-2000:])
        print("AMBANG_FLAT=GAGAL")
        sys.exit(1)
