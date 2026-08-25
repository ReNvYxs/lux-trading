"""Perkakas bersama untuk uji hidup kepemilikan posisi di Binance Testnet.

Dipisah dari skenarionya supaya tiap berkas tetap kecil dan bisa dibaca ulang
tanpa memuat seluruh uji. Berkas ini TIDAK mengimpor lux_modul di tingkat modul,
supaya variabel lingkungan jejak bisa dipasang lebih dulu.
"""
import base64
import json
import os
import sys
import time

KUNCI_B64 = "WXVwdU1EWjI3Z0tqY1NlSjd5UHBwU25rUmFJSk9ZWVNoUlFjYVdLSThBOVdKblJVb0RZSm5JZmxyaHlUUHdwZQ=="
RAHASIA_B64 = "TVJld29CSEV4Yno1NG1FWEhteW1GZzdtalNQbGZxTG9ZVWFHZHl2enliYTh3SmJQU1Y1cWRmOUExaWF0N0NHUQ=="

# Jejak WAJIB aktif sebelum modul apa pun diimpor pemanggil.
os.environ["LUX_JEJAK_DIR"] = os.environ.get("LUX_JEJAK_DIR", "bukti/jejak")
os.environ["LUX_JEJAK_AKTIF"] = "1"

JEJAK = []
_URUT = [0]


def pasang_kredensial():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()
    os.environ.pop("LUX_BINANCE_LIVE_API_KEY", None)
    os.environ.pop("LUX_BINANCE_LIVE_API_SECRET", None)


def catat(tahap, **kv):
    baris = {"tahap": tahap,
             "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    baris.update(kv)
    JEJAK.append(baris)
    ringkas = json.dumps(kv, default=str)
    if len(ringkas) > 900:
        ringkas = ringkas[:900] + "...POTONG"
    print("tahap=" + tahap + " " + ringkas)
    sys.stdout.flush()
    return baris


def galat_dict(exc):
    d = {"jenis": type(exc).__name__, "pesan": str(exc)}
    for atribut in ("status", "kode"):
        if hasattr(exc, atribut):
            d["api_" + atribut] = getattr(exc, atribut)
    return d


def cid(awalan):
    """clientOrderId unik. Awalan menentukan kepemilikan: 'lx' = mesin."""
    _URUT[0] += 1
    return awalan + str(int(time.time()))[-7:] + str(_URUT[0])


def posisi_qty(klien, simbol):
    """positionAmt sekarang, dibaca ulang dari bursa. 0.0 bila tidak ada."""
    try:
        for p in klien.posisi(simbol) or []:
            if p.get("symbol") == simbol:
                return float(p.get("positionAmt") or 0.0)
    except Exception as exc:  # noqa: BLE001
        catat("baca_posisi_galat", simbol=simbol, galat=galat_dict(exc))
    return 0.0


def baris_posisi(klien, simbol):
    try:
        for p in klien.posisi(simbol) or []:
            if p.get("symbol") == simbol:
                return p
    except Exception as exc:  # noqa: BLE001
        catat("baca_posisi_galat", simbol=simbol, galat=galat_dict(exc))
    return {"symbol": simbol, "positionAmt": "0"}


def order_terbuka(klien, simbol):
    try:
        return list(klien.order_terbuka(simbol) or [])
    except Exception as exc:  # noqa: BLE001
        catat("baca_open_orders_galat", simbol=simbol, galat=galat_dict(exc))
        return []


def semesta_mikro(klien, SpekSimbol, rencana_mikro, saldo, sl_pct, batas=12):
    """Simbol yang LAYAK pada saldo tertentu, diurutkan dari margin termurah.

    Biaya: 3 permintaan untuk seluruh bursa, tanpa panggilan per simbol.
    """
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

    calon = []
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
        lev = lev_map.get(sim, 125)
        try:
            r = rencana_mikro(saldo, harga, spek,
                              sl_harga=harga * (1.0 - sl_pct / 100.0),
                              arah="LONG", leverage_maks_bursa=lev)
        except Exception:  # noqa: BLE001
            continue
        if not r.get("layak"):
            continue
        # Uji kepemilikan butuh posisi yang bisa ditutup SEPARUH dan separuhnya
        # masih di atas minimum notional, jadi butuh ruang 3x minimum.
        target = 3.0 * float(r.get("notional_minimum_efektif") or 0.0)
        if float(spek.maks_qty or 0.0) and target / harga > float(spek.maks_qty):
            continue
        calon.append({"simbol": sim, "harga": harga, "spek": spek, "lev": lev,
                      "rencana": r, "margin": float(r.get("margin_nyata") or 9e9),
                      "notional_uji": target})
    calon.sort(key=lambda c: (c["margin"], c["simbol"]))
    return info, calon[:batas]


def bersih_total(klien, simbol):
    """Bersihkan simbol: batalkan seluruh order lalu tutup posisi apa pun.

    Ini WEWENANG HARNESS, bukan mesin. Harness memang pemilik semua order pada
    uji ini, jadi ia boleh memakai jalur tanpa penjaga kepemilikan.
    """
    try:
        klien.batalkan_semua_order(simbol)
    except Exception as exc:  # noqa: BLE001
        catat("bersih_batal_galat", simbol=simbol, galat=galat_dict(exc))
    sisa = posisi_qty(klien, simbol)
    if abs(sisa) > 0:
        try:
            klien.kirim_order({"symbol": simbol,
                               "side": "SELL" if sisa > 0 else "BUY",
                               "type": "MARKET", "quantity": abs(sisa),
                               "reduceOnly": True,
                               "newClientOrderId": cid("bersih")})
        except Exception as exc:  # noqa: BLE001
            catat("bersih_tutup_galat", simbol=simbol, galat=galat_dict(exc))
        sisa = posisi_qty(klien, simbol)
    catat("bersihkan", simbol=simbol, sisa=sisa)
    return sisa
