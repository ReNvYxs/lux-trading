"""Peta kelayakan base 0,20 USDT per setup, diukur dari bursa SUNGGUHAN.

Uji hidup 25 Agu 2026 menemukan bahwa pada BTCUSDT base 0,20 TIDAK tercapai:
minNotional 50 dibagi leverage maksimum 125 sudah memberi margin 0,40, dan
setelah qty dibulatkan ke atas menjadi 0,4417. Itu batas bursa, bukan pilihan
kita. Pertanyaan yang harus dijawab dengan angka, bukan dugaan: pada simbol mana
base 0,20 benar-benar mungkin?

Berkas ini menjawabnya untuk SELURUH pair USDT perpetual sekaligus, memakai
exchangeInfo dan leverageBracket asli, lalu menghitung rencana mikro yang sama
yang dipakai mesin. Tidak ada angka yang diketik tangan.

Biaya rate-limit sengaja dijaga: exchangeInfo (bobot 1), ticker/price tanpa
simbol (bobot 2), leverageBracket tanpa simbol (bobot 1). Tidak ada panggilan
per simbol, sehingga 500+ pair diukur dengan 3 permintaan.
"""
import base64
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())

KUNCI_B64 = "WXVwdU1EWjI3Z0tqY1NlSjd5UHBwU25rUmFJSk9ZWVNoUlFjYVdLSThBOVdKblJVb0RZSm5JZmxyaHlUUHdwZQ=="
RAHASIA_B64 = "TVJld29CSEV4Yno1NG1FWEhteW1GZzdtalNQbGZxTG9ZVWFHZHl2enliYTh3SmJQU1Y1cWRmOUExaWF0N0NHUQ=="

KELUARAN = os.environ.get("MIKRO_KELUARAN", "bukti/mikro/PETA_MIKRO.json")
SALDO = float(os.environ.get("LUX_SALDO_MIKRO", "19"))
SL_PCT = float(os.environ.get("LUX_SL_PCT", "1.0"))
BASE = 0.20


def main():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()

    from lux_modul.eksekusi.binance_client import BinanceFuturesClient
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.ukuran_mikro import rencana_mikro
    from lux_modul.eksekusi_aman.inti import SpekSimbol

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
    try:
        for b in klien.bracket_leverage() or []:
            lev = 0
            for x in b.get("brackets") or []:
                try:
                    lev = max(lev, int(x.get("initialLeverage") or 0))
                except (TypeError, ValueError):
                    pass
            if b.get("symbol"):
                lev_map[b["symbol"]] = lev or 125
    except Exception as exc:  # noqa: BLE001
        print("bracket_galat=" + str(exc)[:200])

    print("simbol_di_exchange_info=" + str(len(info.get("symbols") or [])))
    print("harga_terbaca=" + str(len(harga_map)))
    print("bracket_terbaca=" + str(len(lev_map)))

    baris = []
    dilewati = {"bukan_trading": 0, "bukan_usdt": 0, "bukan_perpetual": 0,
                "tanpa_harga": 0, "spek_galat": 0, "rencana_galat": 0}
    for s in info.get("symbols") or []:
        sim = s.get("symbol")
        if s.get("status") != "TRADING":
            dilewati["bukan_trading"] += 1
            continue
        if s.get("quoteAsset") != "USDT":
            dilewati["bukan_usdt"] += 1
            continue
        if s.get("contractType") != "PERPETUAL":
            dilewati["bukan_perpetual"] += 1
            continue
        harga = harga_map.get(sim)
        if not harga or harga <= 0:
            dilewati["tanpa_harga"] += 1
            continue
        try:
            spek = SpekSimbol.dari_exchange_info(info, sim)
        except Exception:  # noqa: BLE001
            dilewati["spek_galat"] += 1
            continue
        lev = lev_map.get(sim, 125)
        try:
            r = rencana_mikro(SALDO, harga, spek,
                              sl_harga=harga * (1.0 - SL_PCT / 100.0),
                              arah="LONG", leverage_maks_bursa=lev)
        except Exception as exc:  # noqa: BLE001
            dilewati["rencana_galat"] += 1
            print("rencana_galat " + str(sim) + " " + str(exc)[:120])
            continue
        baris.append({
            "simbol": sim,
            "harga": harga,
            "min_notional": spek.min_notional,
            "min_qty": spek.min_qty,
            "step": spek.step,
            "lev_maks_bursa": lev,
            "notional_min_efektif": r.get("notional_minimum_efektif"),
            "sumber_minimum": r.get("sumber_minimum"),
            "qty": r.get("qty"),
            "notional": r.get("notional"),
            "lev_butuh_base": r.get("leverage_dibutuhkan_untuk_base"),
            "lev_dipakai": r.get("leverage_dipakai"),
            "margin": r.get("margin_nyata"),
            "margin_min_mungkin": r.get("margin_minimum_mungkin"),
            "base_tercapai": bool(r.get("base_tercapai")),
            "risiko_pct": r.get("risiko_pct_dari_saldo"),
            "jarak_likuidasi_pct": r.get("jarak_likuidasi_pct"),
            "layak": bool(r.get("layak")),
            "alasan": r.get("alasan"),
        })

    base_mungkin = [b for b in baris if b["margin_min_mungkin"] is not None
                    and float(b["margin_min_mungkin"]) <= BASE + 1e-9]
    base_tercapai = [b for b in baris if b["base_tercapai"]]
    layak = [b for b in baris if b["layak"]]
    layak_dan_base = [b for b in layak if b["base_tercapai"]]

    ringkas = {
        "saldo_uji": SALDO,
        "sl_pct_uji": SL_PCT,
        "base_target": BASE,
        "simbol_dievaluasi": len(baris),
        "dilewati": dilewati,
        "base_secara_teori_mungkin": len(base_mungkin),
        "base_benar_benar_tercapai": len(base_tercapai),
        "layak_penuh": len(layak),
        "layak_dan_base_tercapai": len(layak_dan_base),
    }
    print("RINGKAS=" + json.dumps(ringkas))

    # Sebab penolakan dikelompokkan supaya terlihat APA yang mengikat.
    sebab = {}
    for b in baris:
        if b["layak"]:
            continue
        a = str(b.get("alasan") or "")
        if "melebihi batas" in a:
            k = "risiko_di_atas_batas"
        elif "likuidasi" in a:
            k = "likuidasi_lebih_dekat_dari_sl"
        elif "maxQty" in a or "maks" in a:
            k = "melebihi_maks_qty"
        elif "margin" in a:
            k = "porsi_margin_terlampaui"
        else:
            k = "lain"
        sebab[k] = sebab.get(k, 0) + 1
    print("SEBAB_TIDAK_LAYAK=" + json.dumps(sebab))

    urut = sorted(baris, key=lambda b: (float(b["margin"] or 9e9), b["simbol"]))
    print("--- 25 simbol dengan margin terkecil ---")
    print("simbol|minNotional|harga|qty|notional|lev|margin|risiko%|liq%|layak")
    for b in urut[:25]:
        print("|".join([
            str(b["simbol"]), str(b["min_notional"]), str(b["harga"]),
            str(b["qty"]), str(round(float(b["notional"] or 0), 4)),
            str(b["lev_dipakai"]), str(round(float(b["margin"] or 0), 6)),
            str(b["risiko_pct"]), str(b["jarak_likuidasi_pct"]),
            "ya" if b["layak"] else "tidak"]))

    print("--- 15 simbol LAYAK termurah ---")
    for b in sorted(layak, key=lambda x: float(x["margin"] or 9e9))[:15]:
        print("|".join([
            str(b["simbol"]), str(b["min_notional"]), str(b["qty"]),
            str(round(float(b["notional"] or 0), 4)), str(b["lev_dipakai"]),
            str(round(float(b["margin"] or 0), 6)), str(b["risiko_pct"]),
            "base_ok" if b["base_tercapai"] else "base_tidak"]))

    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump({"ringkas": ringkas, "sebab_tidak_layak": sebab, "baris": baris},
              fh, indent=1, default=str)
    fh.close()
    print("berkas=" + KELUARAN)
    print("PETA_MIKRO=SELESAI")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        print(traceback.format_exc()[-2000:])
        print("PETA_MIKRO=GAGAL")
        sys.exit(1)
