"""Validasi HIDUP jalur LUX_EKSEKUSI=aman lewat jahitan LiveRunner.

Yang dibuktikan di bursa sungguhan (Binance Futures Testnet):
1. Apakah STOP_MARKET / TAKE_PROFIT_MARKET masih ditolak hari ini (uji ulang
   sezaman terhadap klaim docstring lux_modul/eksekusi/order.py).
2. Apakah _pasang_proteksi() mode aman benar-benar menaruh TP LIMIT reduceOnly
   yang TERLIHAT di openOrders.
3. Apakah sl_order_id memang None dan SL hidup sebagai pemantau perangkat lunak.
4. Apakah _periksa_sl_aman() jalan terhadap data pasar sungguhan.
5. Apakah kegagalan proteksi benar-benar MENUTUP posisi (fail-safe).

Catatan v2. Uji negatif v1 memakai TP 10x harga dan TERNYATA DITERIMA bursa,
sehingga kegagalan tidak pernah terpicu dan fail-safe tidak teruji. v2 memakai
dua jalur: (a) harga di atas maxPrice PRICE_FILTER untuk melihat penolakan
nyata bursa, dan (b) injeksi -4120 khusus pada order TP (LIMIT reduceOnly GTC)
lewat pembungkus klien, sementara penutupan posisi tetap menembak bursa asli.
Jalur (b) membuktikan fail-safe menutup POSISI SUNGGUHAN.

Kredensial testnet diizinkan eksplisit oleh pemilik akun untuk dipakai dan
terbuka; kunci akan dirotasi setelah audit. Base URL TIDAK ditulis di sini -
ia datang dari lux_modul/eksekusi/kredensial.py yang mengunci URL per mode.
"""
import base64
import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.getcwd())

KUNCI_B64 = "WXVwdU1EWjI3Z0tqY1NlSjd5UHBwU25rUmFJSk9ZWVNoUlFjYVdLSThBOVdKblJVb0RZSm5JZmxyaHlUUHdwZQ=="
RAHASIA_B64 = "TVJld29CSEV4Yno1NG1FWEhteW1GZzdtalNQbGZxTG9ZVWFHZHl2enliYTh3SmJQU1Y1cWRmOUExaWF0N0NHUQ=="

SIMBOL = os.environ.get("LUX_SIMBOL_UJI", "BTCUSDT")
KELUARAN = os.environ.get("HIDUP_KELUARAN", "bukti/live/SAKLAR_HIDUP.json")
NOTIONAL_UJI = float(os.environ.get("LUX_NOTIONAL_UJI", "120"))

JEJAK = []
VONIS = {}


def catat(tahap, **kv):
    baris = {"tahap": tahap, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    baris.update(kv)
    JEJAK.append(baris)
    ringkas = json.dumps(kv, default=str)
    if len(ringkas) > 900:
        ringkas = ringkas[:900] + "...POTONG"
    print("tahap=" + tahap + " " + ringkas)
    sys.stdout.flush()


def galat_dict(exc):
    d = {"jenis": type(exc).__name__, "pesan": str(exc)}
    for atribut in ("status", "kode", "pesan"):
        if hasattr(exc, atribut):
            d["api_" + atribut] = getattr(exc, atribut)
    return d


def maks_harga_filter(info, simbol):
    daftar = info.get("symbols") if isinstance(info, dict) else None
    sim = None
    if isinstance(daftar, list):
        for s in daftar:
            if s.get("symbol") == simbol:
                sim = s
                break
    elif isinstance(info, dict) and info.get("symbol") == simbol:
        sim = info
    if not sim:
        return None
    for f in sim.get("filters", []) or []:
        if f.get("filterType") == "PRICE_FILTER":
            try:
                return float(f.get("maxPrice"))
            except Exception:  # noqa: BLE001
                return None
    return None


def main():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()
    os.environ.pop("LUX_BINANCE_LIVE_API_KEY", None)
    os.environ.pop("LUX_BINANCE_LIVE_API_SECRET", None)

    from lux_modul.eksekusi.binance_client import BinanceAPIError, BinanceFuturesClient
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.order import KebijakanOrder, payload_sl, payload_tp_market
    from lux_modul.kontrak import ARAH_LONG
    from lux_modul.eksekusi_aman.inti import DataPasar, Entry, PengirimOrder, SpekSimbol
    from lux_modul.eksekusi_aman.saklar import aman_aktif, pasang_proteksi_aman
    import lux_modul.live_runner as lr

    kred = muat_kredensial(MODE_TESTNET)
    catat("kredensial", ringkas=kred.ringkas())

    klien = BinanceFuturesClient(kred)
    saldo = klien.saldo_usdt()
    harga = klien.harga_sekarang(SIMBOL)
    catat("koneksi", saldo_usdt=saldo, harga=harga, simbol=SIMBOL)

    # ---------------------------------------------------------------- #
    # 1. Uji ulang sezaman: apakah stop order masih ditolak?
    # ---------------------------------------------------------------- #
    uji_tipe = {}
    kandidat = {
        "STOP_MARKET": payload_sl(SIMBOL, ARAH_LONG, harga * 0.90),
        "TAKE_PROFIT_MARKET": payload_tp_market(SIMBOL, ARAH_LONG, harga * 1.10),
    }
    for nama in sorted(kandidat):
        try:
            resp = klien._permintaan("POST", "/fapi/v1/order/test", kandidat[nama], True)
            uji_tipe[nama] = {"diterima": True, "respons": resp}
        except Exception as exc:  # noqa: BLE001
            uji_tipe[nama] = {"diterima": False, "galat": galat_dict(exc)}
        catat("uji_tipe_order", tipe=nama, hasil=uji_tipe[nama])
    VONIS["stop_order_ditolak"] = not any(uji_tipe[n].get("diterima") for n in uji_tipe)
    VONIS["uji_tipe_order"] = uji_tipe

    # ---------------------------------------------------------------- #
    # 2. Spesifikasi simbol + ukuran uji terkecil yang sah
    # ---------------------------------------------------------------- #
    info = klien.exchange_info(SIMBOL)
    spek = SpekSimbol.dari_exchange_info(info, SIMBOL)
    maks_harga = maks_harga_filter(info, SIMBOL)
    qty = spek.turun_qty(NOTIONAL_UJI / harga)
    penjaga = 0
    while qty * harga < spek.min_notional and penjaga < 500:
        qty = spek.turun_qty(qty + spek.step)
        penjaga += 1
    if qty < spek.min_qty:
        qty = spek.min_qty
    catat(
        "spek",
        tick=spek.tick,
        step=spek.step,
        min_qty=spek.min_qty,
        min_notional=spek.min_notional,
        maks_harga_filter=maks_harga,
        qty_uji=qty,
        notional_uji=qty * harga,
    )

    pengirim = PengirimOrder(klien)
    data = DataPasar(klien)
    entry = Entry(klien, pengirim, spek, SIMBOL, data=data)

    def qty_posisi():
        try:
            return float(entry.qty_posisi())
        except Exception as exc:  # noqa: BLE001
            catat("qty_posisi_galat", galat=galat_dict(exc))
            return 0.0

    def bersihkan(alasan):
        try:
            klien.batalkan_semua_order(SIMBOL)
        except Exception as exc:  # noqa: BLE001
            catat("bersih_batal_galat", galat=galat_dict(exc))
        sisa = qty_posisi()
        if abs(sisa) > 0:
            try:
                klien.kirim_order(
                    {
                        "symbol": SIMBOL,
                        "side": "SELL" if sisa > 0 else "BUY",
                        "type": "MARKET",
                        "quantity": abs(sisa),
                        "reduceOnly": True,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                catat("bersih_tutup_galat", galat=galat_dict(exc))
        akhir = qty_posisi()
        catat("bersihkan", alasan=alasan, sisa_awal=sisa, sisa_akhir=akhir)
        return akhir

    def buka_posisi(label):
        ember = int(time.time() * 1000) % 100000000
        try:
            h = entry.kirim_entry(ARAH_LONG, qty, ember)
            catat("entry", label=label, hasil=h)
        except Exception as exc:  # noqa: BLE001
            catat("entry_galat", label=label, galat=galat_dict(exc))
        q = qty_posisi()
        if abs(q) <= 0:
            try:
                h2 = entry.kirim_entry(ARAH_LONG, qty, ember + 1, agresivitas=0.01)
                catat("entry_ulang", label=label, hasil=h2)
            except Exception as exc:  # noqa: BLE001
                catat("entry_ulang_galat", label=label, galat=galat_dict(exc))
            q = qty_posisi()
        catat("posisi_setelah_entry", label=label, qty=q)
        return q

    bersihkan("pra_uji")

    # ---------------------------------------------------------------- #
    # 3. Buka posisi memakai lapisan aman (Entry)
    # ---------------------------------------------------------------- #
    terisi = buka_posisi("utama")
    VONIS["posisi_terbuka"] = abs(terisi) > 0
    VONIS["qty_terisi"] = terisi
    if abs(terisi) <= 0:
        VONIS["vonis"] = "GAGAL_ENTRY"
        return 1

    # ---------------------------------------------------------------- #
    # 4. Rakit LiveRunner minimal (pola tests/test_live_runner.py)
    # ---------------------------------------------------------------- #
    r = lr.LiveRunner.__new__(lr.LiveRunner)
    r.client = klien
    r.simbol = SIMBOL
    r.notifier = None
    r.kebijakan_order = KebijakanOrder()
    r._sekarang_ms = lambda: int(time.time() * 1000)
    r._tidur = time.sleep
    r._pending_entry = {}
    r._bracket_aktif = {}
    r._proteksi_aman = {}

    os.environ["LUX_EKSEKUSI"] = "aman"
    VONIS["aman_aktif"] = bool(aman_aktif())
    catat("mode", aman_aktif=VONIS["aman_aktif"], env=os.environ.get("LUX_EKSEKUSI"))

    class Verdict(object):
        arah = ARAH_LONG
        skor = 99.0
        strategy_id = "uji_hidup"

    v = Verdict()
    sl_harga = spek.bulat_harga(harga * 0.97)
    tp_harga = spek.bulat_harga(harga * 1.03)

    try:
        siklus = lr.SiklusHasil()
        bentuk_siklus = "SiklusHasil()"
    except Exception:  # noqa: BLE001
        class SiklusStub(object):
            def __init__(self):
                self.order_tp = None
                self.order_sl = None
                self.galat = None

        siklus = SiklusStub()
        bentuk_siklus = "stub"
    catat("siklus", bentuk=bentuk_siklus)

    # ---------------------------------------------------------------- #
    # 5. Jahitan yang diuji: _pasang_proteksi mode aman
    # ---------------------------------------------------------------- #
    try:
        sl_id, tp_id = r._pasang_proteksi(v, sl_harga, tp_harga, siklus)
        catat(
            "pasang_proteksi",
            sl_order_id=sl_id,
            tp_order_id=tp_id,
            sl_harga=sl_harga,
            tp_harga=tp_harga,
            order_sl=getattr(siklus, "order_sl", None),
            galat=getattr(siklus, "galat", None),
        )
        VONIS["sl_order_id_none"] = sl_id is None
        VONIS["tp_order_id"] = tp_id
        VONIS["siklus_order_sl"] = getattr(siklus, "order_sl", None)
        VONIS["siklus_galat"] = getattr(siklus, "galat", None)
    except Exception as exc:  # noqa: BLE001
        catat("pasang_proteksi_galat", galat=galat_dict(exc), jejak=traceback.format_exc()[-1200:])
        VONIS["vonis"] = "GAGAL_PASANG"
        bersihkan("gagal_pasang")
        return 1

    # ---------------------------------------------------------------- #
    # 6. Bukti independen: TP terlihat di openOrders bursa
    # ---------------------------------------------------------------- #
    def baca_open_orders():
        try:
            terbuka = klien._permintaan("GET", "/fapi/v1/openOrders", {"symbol": SIMBOL}, True)
        except Exception as exc:  # noqa: BLE001
            catat("open_orders_galat", galat=galat_dict(exc))
            return []
        keluar = []
        for o in terbuka or []:
            keluar.append(
                {
                    "orderId": o.get("orderId"),
                    "type": o.get("type"),
                    "side": o.get("side"),
                    "price": o.get("price"),
                    "stopPrice": o.get("stopPrice"),
                    "origQty": o.get("origQty"),
                    "reduceOnly": o.get("reduceOnly"),
                    "closePosition": o.get("closePosition"),
                    "timeInForce": o.get("timeInForce"),
                    "status": o.get("status"),
                }
            )
        return keluar

    ringkas_order = baca_open_orders()
    catat("open_orders", jumlah=len(ringkas_order), order=ringkas_order)
    VONIS["open_orders"] = ringkas_order
    VONIS["tp_terlihat_limit_reduceonly"] = any(
        str(o.get("type")) == "LIMIT"
        and str(o.get("side")) == "SELL"
        and bool(o.get("reduceOnly"))
        for o in ringkas_order
    )
    VONIS["ada_tipe_stop_di_bursa"] = any(
        "STOP" in str(o.get("type")) or "TAKE_PROFIT" in str(o.get("type"))
        for o in ringkas_order
    )

    # ---------------------------------------------------------------- #
    # 7. Pemantau SL perangkat lunak berjalan terhadap pasar nyata
    # ---------------------------------------------------------------- #
    try:
        galat_sl = r._periksa_sl_aman()
        catat("periksa_sl_aman", galat=galat_sl, masih_dipantau=list(r._proteksi_aman.keys()))
        VONIS["periksa_sl_galat"] = galat_sl
        VONIS["masih_dipantau"] = list(r._proteksi_aman.keys())
    except Exception as exc:  # noqa: BLE001
        catat("periksa_sl_galat_fatal", galat=galat_dict(exc))
        VONIS["periksa_sl_galat"] = [str(exc)]

    # ---------------------------------------------------------------- #
    # 8a. Apakah bursa menolak harga di luar PRICE_FILTER? (pengamatan)
    # ---------------------------------------------------------------- #
    try:
        klien.batalkan_semua_order(SIMBOL)
    except Exception as exc:  # noqa: BLE001
        catat("batal_sebelum_8a_galat", galat=galat_dict(exc))
    harga_liar = (maks_harga * 10.0) if maks_harga else (harga * 1000.0)
    coba = {
        "symbol": SIMBOL,
        "side": "SELL",
        "type": "LIMIT",
        "timeInForce": "GTC",
        "price": spek.bulat_harga(harga_liar),
        "quantity": abs(qty_posisi()) or qty,
        "reduceOnly": True,
    }
    try:
        resp_liar = klien._permintaan("POST", "/fapi/v1/order/test", coba, True)
        filter_menolak = False
        detail_liar = {"diterima": True, "respons": resp_liar}
    except Exception as exc:  # noqa: BLE001
        filter_menolak = True
        detail_liar = {"diterima": False, "galat": galat_dict(exc)}
    catat("harga_di_luar_filter", harga=coba["price"], hasil=detail_liar)
    VONIS["filter_harga_menolak"] = filter_menolak
    VONIS["harga_di_luar_filter"] = detail_liar

    # ---------------------------------------------------------------- #
    # 8b. Fail-safe sungguhan: TP ditolak -4120, posisi WAJIB ditutup
    # ---------------------------------------------------------------- #
    class KlienTolakTP(object):
        """Bursa asli, kecuali order TP (LIMIT reduceOnly GTC) yang ditolak -4120.

        Penutupan posisi tetap menembak bursa sungguhan, sehingga yang diuji
        adalah apakah fail-safe benar-benar menutup POSISI NYATA.
        """

        def __init__(self, asli, kelas_galat):
            self._asli = asli
            self._kelas_galat = kelas_galat
            self.ditolak = []
            self.diteruskan = []

        def __getattr__(self, nama):
            return getattr(self._asli, nama)

        def kirim_order(self, payload):
            tipe = str(payload.get("type", "")).upper()
            tif = str(payload.get("timeInForce", "")).upper()
            if tipe == "LIMIT" and bool(payload.get("reduceOnly")) and tif == "GTC":
                self.ditolak.append(payload)
                raise self._kelas_galat(
                    400,
                    -4120,
                    "Order type not supported for this endpoint. "
                    "Please use the Algo Order API endpoints instead.",
                )
            self.diteruskan.append(payload)
            return self._asli.kirim_order(payload)

    qty_sebelum = qty_posisi()
    if abs(qty_sebelum) <= 0:
        qty_sebelum = buka_posisi("failsafe")
    VONIS["failsafe_qty_sebelum"] = qty_sebelum

    if abs(qty_sebelum) <= 0:
        VONIS["failsafe_gagal_terdeteksi"] = None
        VONIS["failsafe_posisi_ditutup"] = None
        catat("failsafe_dilewati", alasan="tidak ada posisi untuk diuji")
    else:
        klien_tolak = KlienTolakTP(klien, BinanceAPIError)
        hasil_gagal = pasang_proteksi_aman(
            klien=klien_tolak,
            simbol=SIMBOL,
            arah=ARAH_LONG,
            tp_harga=tp_harga,
            sl_harga=sl_harga,
            spek=spek,
            tidur=time.sleep,
        )
        qty_sesudah = qty_posisi()
        catat(
            "failsafe",
            qty_sebelum=qty_sebelum,
            qty_sesudah=qty_sesudah,
            tp_ditolak_kali=len(klien_tolak.ditolak),
            order_diteruskan=[
                {"type": p.get("type"), "side": p.get("side"),
                 "timeInForce": p.get("timeInForce"),
                 "reduceOnly": p.get("reduceOnly")}
                for p in klien_tolak.diteruskan
            ],
            gagal=hasil_gagal.get("gagal"),
            posisi_ditutup=hasil_gagal.get("posisi_ditutup"),
            failsafe=hasil_gagal.get("failsafe"),
        )
        VONIS["failsafe_gagal_terdeteksi"] = hasil_gagal.get("gagal") is not None
        VONIS["failsafe_posisi_ditutup"] = abs(qty_sesudah) <= 0
        VONIS["failsafe_tp_ditolak_kali"] = len(klien_tolak.ditolak)
        VONIS["failsafe_order_penutup"] = [
            {"type": p.get("type"), "side": p.get("side"),
             "timeInForce": p.get("timeInForce"),
             "reduceOnly": p.get("reduceOnly")}
            for p in klien_tolak.diteruskan
        ]
        VONIS["failsafe_detail"] = {
            k: hasil_gagal.get(k)
            for k in ("mode", "gagal", "posisi_ditutup", "failsafe", "failsafe_gagal")
        }

    VONIS["open_orders_pasca_failsafe"] = baca_open_orders()
    sisa_akhir = bersihkan("pasca_uji")
    VONIS["bersih_akhir"] = abs(sisa_akhir) <= 0

    lulus = (
        VONIS.get("stop_order_ditolak")
        and VONIS.get("posisi_terbuka")
        and VONIS.get("aman_aktif")
        and VONIS.get("sl_order_id_none")
        and VONIS.get("tp_terlihat_limit_reduceonly")
        and not VONIS.get("ada_tipe_stop_di_bursa")
        and VONIS.get("failsafe_gagal_terdeteksi")
        and VONIS.get("failsafe_posisi_ditutup")
        and VONIS.get("bersih_akhir")
    )
    VONIS["vonis"] = "LULUS" if lulus else "GAGAL"
    return 0 if lulus else 1


if __name__ == "__main__":
    kode = 1
    try:
        kode = main()
    except Exception as exc:  # noqa: BLE001
        catat("fatal", galat=galat_dict(exc), jejak=traceback.format_exc()[-2000:])
        VONIS["vonis"] = "GALAT_FATAL"
    direktori = os.path.dirname(KELUARAN)
    if direktori:
        os.makedirs(direktori, exist_ok=True)
    fh = open(KELUARAN, "w", encoding="utf-8")
    json.dump({"vonis": VONIS, "jejak": JEJAK}, fh, indent=1, default=str)
    fh.close()
    print("SAKLAR_HIDUP=" + str(VONIS.get("vonis")))
    for kunci in (
        "stop_order_ditolak",
        "posisi_terbuka",
        "qty_terisi",
        "aman_aktif",
        "sl_order_id_none",
        "tp_order_id",
        "tp_terlihat_limit_reduceonly",
        "ada_tipe_stop_di_bursa",
        "periksa_sl_galat",
        "masih_dipantau",
        "filter_harga_menolak",
        "failsafe_qty_sebelum",
        "failsafe_tp_ditolak_kali",
        "failsafe_gagal_terdeteksi",
        "failsafe_posisi_ditutup",
        "bersih_akhir",
    ):
        print(str(kunci) + "=" + json.dumps(VONIS.get(kunci), default=str))
    print("siklus_order_sl=" + json.dumps(VONIS.get("siklus_order_sl"), default=str))
    print("failsafe_detail=" + json.dumps(VONIS.get("failsafe_detail"), default=str))
    print("failsafe_order_penutup=" + json.dumps(VONIS.get("failsafe_order_penutup"), default=str))
    print("harga_di_luar_filter=" + json.dumps(VONIS.get("harga_di_luar_filter"), default=str))
    print("open_orders=" + json.dumps(VONIS.get("open_orders"), default=str))
    print("open_orders_pasca_failsafe=" + json.dumps(VONIS.get("open_orders_pasca_failsafe"), default=str))
    print("uji_tipe_order=" + json.dumps(VONIS.get("uji_tipe_order"), default=str))
    sys.exit(kode)
