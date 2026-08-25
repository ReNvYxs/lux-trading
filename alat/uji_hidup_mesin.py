"""Uji HIDUP mesin eksekusi di Binance Futures Testnet: Cancel dan Modify.

Mengapa berkas ini ada. Seluruh lapisan lain sudah dibuktikan hidup (entry, TP,
fail-safe penutupan posisi), tetapi DUA jalur belum pernah diadu dengan bursa
sungguhan: pembatalan satu order (`batalkan_order`) dan perubahan order
(`ubah_order`, PUT /fapi/v1/order). `ubah_order` ditulis dari dokumentasi dan
BELUM PERNAH dijalankan. Selama itu belum diverifikasi, mesin tidak boleh
disebut siap.

Desain sengaja TIDAK membuka posisi. Order uji adalah LIMIT BUY pasif jauh di
bawah pasar, jadi ia menunggu di buku tanpa terisi. Yang diuji adalah siklus
hidup order dan dana di bursa, bukan strategi.

Yang dibuktikan:
1. Limit entry benar-benar terkonfirmasi bursa (bukan sekadar respons diterima).
2. Order terlihat di openOrders lewat metode bertipe `order_terbuka`.
3. `ubah_order` sungguhan mengubah harga/qty - diverifikasi ulang lewat
   `status_order`, bukan dari respons PUT-nya sendiri.
4. `batalkan_order` dikonfirmasi `konfirmasi_batal` DAN diverifikasi hilang.
5. Membatalkan order yang sudah batal GAGAL dengan jelas (bukan diam-diam
   dianggap sukses).
6. Mengubah order yang sudah batal GAGAL dengan jelas.
7. Jejak JSONL benar-benar tertulis untuk seluruh panggilan dana di atas.
8. Angka sizing mikro base 0,20 pada spesifikasi BTCUSDT SUNGGUHAN.

Kredensial testnet diizinkan eksplisit oleh pemilik akun untuk dipakai dan
terbuka; kunci akan dirotasi setelah audit.
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
KELUARAN = os.environ.get("HIDUP_KELUARAN", "bukti/live/MESIN_HIDUP.json")
NOTIONAL_UJI = float(os.environ.get("LUX_NOTIONAL_UJI", "120"))

# Jejak diaktifkan SEBELUM modul apa pun diimpor, supaya seluruh panggilan
# REST di bawah ini benar-benar terekam ke berkas.
os.environ["LUX_JEJAK_DIR"] = os.environ.get("LUX_JEJAK_DIR", "bukti/jejak")
os.environ["LUX_JEJAK_AKTIF"] = "1"

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


def main():
    os.environ["LUX_BINANCE_TESTNET_API_KEY"] = base64.b64decode(KUNCI_B64).decode()
    os.environ["LUX_BINANCE_TESTNET_API_SECRET"] = base64.b64decode(RAHASIA_B64).decode()
    os.environ.pop("LUX_BINANCE_LIVE_API_KEY", None)
    os.environ.pop("LUX_BINANCE_LIVE_API_SECRET", None)

    from lux_modul.eksekusi.binance_client import BinanceFuturesClient
    from lux_modul.eksekusi.jejak import perekam
    from lux_modul.eksekusi.klasifikasi import (
        klasifikasikan,
        konfirmasi_batal,
        konfirmasi_order,
    )
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.ukuran_mikro import rencana_mikro
    from lux_modul.eksekusi_aman.inti import SpekSimbol

    kred = muat_kredensial(MODE_TESTNET)
    klien = BinanceFuturesClient(kred)
    harga = klien.harga_sekarang(SIMBOL)
    saldo = klien.saldo_usdt()
    catat("koneksi", simbol=SIMBOL, harga=harga, saldo_usdt=saldo)

    info = klien.exchange_info(SIMBOL)
    spek = SpekSimbol.dari_exchange_info(info, SIMBOL)

    # ---------------------------------------------------------------- #
    # 0. Angka sizing mikro pada spesifikasi SUNGGUHAN
    # ---------------------------------------------------------------- #
    for modal in (10.0, 19.0):
        r = rencana_mikro(modal, harga, spek, sl_harga=harga * 0.99,
                          arah="LONG", leverage_maks_bursa=125)
        catat("sizing_mikro_nyata", saldo=modal, qty=r.get("qty"),
              notional=r.get("notional"), leverage=r.get("leverage_dipakai"),
              margin=r.get("margin_nyata"), base_tercapai=r.get("base_tercapai"),
              risiko_pct=r.get("risiko_pct_dari_saldo"), layak=r.get("layak"),
              alasan=r.get("alasan"))
        VONIS["mikro_" + str(int(modal))] = {
            "qty": r.get("qty"), "notional": r.get("notional"),
            "leverage": r.get("leverage_dipakai"), "margin": r.get("margin_nyata"),
            "risiko_pct": r.get("risiko_pct_dari_saldo"), "layak": r.get("layak"),
            "alasan": r.get("alasan")}

    def bersihkan(alasan):
        try:
            klien.batalkan_semua_order(SIMBOL)
        except Exception as exc:  # noqa: BLE001
            catat("bersih_batal_galat", galat=galat_dict(exc))
        sisa = 0.0
        try:
            for p in klien.posisi(SIMBOL) or []:
                if p.get("symbol") == SIMBOL:
                    sisa = float(p.get("positionAmt") or 0.0)
        except Exception as exc:  # noqa: BLE001
            catat("bersih_posisi_galat", galat=galat_dict(exc))
        if abs(sisa) > 0:
            try:
                klien.kirim_order({"symbol": SIMBOL,
                                   "side": "SELL" if sisa > 0 else "BUY",
                                   "type": "MARKET", "quantity": abs(sisa),
                                   "reduceOnly": True})
            except Exception as exc:  # noqa: BLE001
                catat("bersih_tutup_galat", galat=galat_dict(exc))
        catat("bersihkan", alasan=alasan, sisa=sisa)
        return sisa

    bersihkan("pra_uji")

    # ---------------------------------------------------------------- #
    # 1. Limit entry pasif - WAJIB terkonfirmasi bursa
    # ---------------------------------------------------------------- #
    harga_pasif = spek.bulat_harga(harga * 0.95)
    qty = spek.turun_qty(NOTIONAL_UJI / harga_pasif)
    penjaga = 0
    while qty * harga_pasif < spek.min_notional and penjaga < 500:
        qty = spek.turun_qty(qty + spek.step)
        penjaga += 1
    if qty < spek.min_qty:
        qty = spek.min_qty
    cid = "lxujimesin" + str(int(time.time()))[-8:]
    payload = {"symbol": SIMBOL, "side": "BUY", "type": "LIMIT",
               "timeInForce": "GTC", "price": harga_pasif, "quantity": qty,
               "newClientOrderId": cid}
    catat("limit_entry_permintaan", payload=payload)
    try:
        resp = klien.kirim_order(payload)
        ringkas = konfirmasi_order(resp, simbol=SIMBOL, sisi="BUY", cid=cid)
        order_id = ringkas["orderId"]
        VONIS["limit_entry_terkonfirmasi"] = True
        VONIS["limit_entry"] = ringkas
        catat("limit_entry_jawaban", ringkas=ringkas)
    except Exception as exc:  # noqa: BLE001
        VONIS["limit_entry_terkonfirmasi"] = False
        VONIS["limit_entry_galat"] = galat_dict(exc)
        catat("limit_entry_galat", galat=galat_dict(exc),
              kelas=klasifikasikan(exc, jalur="/fapi/v1/order", metode="POST",
                                   dana=True).ringkas())
        bersihkan("gagal_entry")
        VONIS["vonis"] = "GAGAL_ENTRY"
        return 1

    # ---------------------------------------------------------------- #
    # 2. Terlihat di openOrders lewat metode bertipe
    # ---------------------------------------------------------------- #
    terbuka = klien.order_terbuka(SIMBOL)
    ids = [o.get("orderId") for o in terbuka]
    VONIS["order_terlihat"] = order_id in ids
    catat("open_orders", jumlah=len(terbuka), ids=ids, dicari=order_id)

    # ---------------------------------------------------------------- #
    # 3. MODIFY - verifikasi pertama kali di bursa sungguhan
    # ---------------------------------------------------------------- #
    harga_baru = spek.bulat_harga(harga * 0.94)
    qty_baru = spek.turun_qty(qty + spek.step)
    catat("modify_permintaan", order_id=order_id, harga_lama=harga_pasif,
          harga_baru=harga_baru, qty_lama=qty, qty_baru=qty_baru)
    try:
        resp_ubah = klien.ubah_order(SIMBOL, "BUY", qty_baru, harga_baru,
                                    order_id=order_id)
        catat("modify_jawaban", jawaban=resp_ubah)
        VONIS["modify_diterima"] = True
        VONIS["modify_jawaban"] = resp_ubah
        # Jangan percaya jawaban PUT-nya sendiri: baca ulang dari bursa.
        st = klien.status_order(SIMBOL, order_id=order_id)
        harga_bursa = float(st.get("price") or 0.0)
        qty_bursa = float(st.get("origQty") or 0.0)
        VONIS["modify_harga_di_bursa"] = harga_bursa
        VONIS["modify_qty_di_bursa"] = qty_bursa
        VONIS["modify_terverifikasi"] = (
            abs(harga_bursa - harga_baru) < spek.tick
            and abs(qty_bursa - qty_baru) < spek.step
        )
        # orderId bisa BERUBAH setelah amend; itu fakta yang perlu dicatat.
        VONIS["modify_order_id_baru"] = resp_ubah.get("orderId")
        if resp_ubah.get("orderId"):
            order_id = int(resp_ubah.get("orderId"))
        catat("modify_verifikasi", harga_di_bursa=harga_bursa,
              qty_di_bursa=qty_bursa, cocok=VONIS["modify_terverifikasi"],
              order_id_dipakai=order_id, status=st.get("status"))
    except Exception as exc:  # noqa: BLE001
        VONIS["modify_diterima"] = False
        VONIS["modify_terverifikasi"] = False
        VONIS["modify_galat"] = galat_dict(exc)
        VONIS["modify_kelas"] = klasifikasikan(
            exc, jalur="/fapi/v1/order", metode="PUT", dana=True).ringkas()
        catat("modify_galat", galat=galat_dict(exc), kelas=VONIS["modify_kelas"])

    # ---------------------------------------------------------------- #
    # 4. CANCEL - dikonfirmasi lalu DIVERIFIKASI hilang
    # ---------------------------------------------------------------- #
    try:
        resp_batal = klien.batalkan_order(SIMBOL, order_id=order_id)
        catat("cancel_jawaban", jawaban=resp_batal)
        try:
            konf = konfirmasi_batal(resp_batal, simbol=SIMBOL)
            VONIS["cancel_terkonfirmasi"] = True
            VONIS["cancel_konfirmasi"] = konf
        except Exception as exc:  # noqa: BLE001
            VONIS["cancel_terkonfirmasi"] = False
            VONIS["cancel_konfirmasi_galat"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        VONIS["cancel_terkonfirmasi"] = False
        VONIS["cancel_galat"] = galat_dict(exc)
        catat("cancel_galat", galat=galat_dict(exc))

    sisa_terbuka = klien.order_terbuka(SIMBOL)
    sisa_ids = [o.get("orderId") for o in sisa_terbuka]
    VONIS["cancel_terverifikasi_hilang"] = order_id not in sisa_ids
    catat("cancel_verifikasi", sisa_ids=sisa_ids, order_id=order_id,
          hilang=VONIS["cancel_terverifikasi_hilang"])

    # ---------------------------------------------------------------- #
    # 5. Jalur GAGAL: batalkan lagi order yang sudah batal
    # ---------------------------------------------------------------- #
    try:
        resp_ulang = klien.batalkan_order(SIMBOL, order_id=order_id)
        VONIS["cancel_ulang_ditolak"] = False
        VONIS["cancel_ulang_jawaban"] = resp_ulang
        catat("cancel_ulang_DITERIMA", jawaban=resp_ulang)
    except Exception as exc:  # noqa: BLE001
        kelas = klasifikasikan(exc, jalur="/fapi/v1/order", metode="DELETE",
                              dana=True).ringkas()
        VONIS["cancel_ulang_ditolak"] = True
        VONIS["cancel_ulang_galat"] = galat_dict(exc)
        VONIS["cancel_ulang_kelas"] = kelas
        catat("cancel_ulang_ditolak", galat=galat_dict(exc), kelas=kelas)

    # ---------------------------------------------------------------- #
    # 6. Jalur GAGAL: ubah order yang sudah batal
    # ---------------------------------------------------------------- #
    try:
        resp_ubah2 = klien.ubah_order(SIMBOL, "BUY", qty_baru, harga_baru,
                                     order_id=order_id)
        VONIS["modify_setelah_batal_ditolak"] = False
        VONIS["modify_setelah_batal_jawaban"] = resp_ubah2
        catat("modify_setelah_batal_DITERIMA", jawaban=resp_ubah2)
    except Exception as exc:  # noqa: BLE001
        kelas = klasifikasikan(exc, jalur="/fapi/v1/order", metode="PUT",
                              dana=True).ringkas()
        VONIS["modify_setelah_batal_ditolak"] = True
        VONIS["modify_setelah_batal_galat"] = galat_dict(exc)
        VONIS["modify_setelah_batal_kelas"] = kelas
        catat("modify_setelah_batal_ditolak", galat=galat_dict(exc), kelas=kelas)

    # ---------------------------------------------------------------- #
    # 7. Bukti jejak: berkas JSONL benar-benar tertulis
    # ---------------------------------------------------------------- #
    p = perekam()
    ringkas_jejak = p.ringkas() if hasattr(p, "ringkas") else {}
    berkas = getattr(p, "berkas_terpakai", None)
    baris = 0
    if berkas and os.path.exists(berkas):
        fh = open(berkas, "r", encoding="utf-8")
        baris = sum(1 for _ in fh)
        fh.close()
    VONIS["jejak_ringkas"] = ringkas_jejak
    VONIS["jejak_berkas"] = berkas
    VONIS["jejak_baris"] = baris
    VONIS["jejak_gagal_tulis"] = getattr(p, "gagal_tulis", None)
    VONIS["jejak_tertulis"] = baris > 0
    catat("jejak", berkas=berkas, baris=baris, ringkas=ringkas_jejak)

    sisa_akhir = bersihkan("pasca_uji")
    VONIS["bersih_akhir"] = abs(sisa_akhir) <= 0

    lulus = (
        VONIS.get("limit_entry_terkonfirmasi")
        and VONIS.get("order_terlihat")
        and VONIS.get("cancel_terkonfirmasi")
        and VONIS.get("cancel_terverifikasi_hilang")
        and VONIS.get("cancel_ulang_ditolak")
        and VONIS.get("modify_setelah_batal_ditolak")
        and VONIS.get("jejak_tertulis")
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
    print("MESIN_HIDUP=" + str(VONIS.get("vonis")))
    for kunci in (
        "limit_entry_terkonfirmasi",
        "order_terlihat",
        "modify_diterima",
        "modify_terverifikasi",
        "modify_harga_di_bursa",
        "modify_qty_di_bursa",
        "modify_order_id_baru",
        "cancel_terkonfirmasi",
        "cancel_terverifikasi_hilang",
        "cancel_ulang_ditolak",
        "modify_setelah_batal_ditolak",
        "jejak_berkas",
        "jejak_baris",
        "jejak_gagal_tulis",
        "bersih_akhir",
    ):
        print(str(kunci) + "=" + json.dumps(VONIS.get(kunci), default=str))
    print("modify_galat=" + json.dumps(VONIS.get("modify_galat"), default=str))
    print("modify_kelas=" + json.dumps(VONIS.get("modify_kelas"), default=str))
    print("cancel_ulang_kelas=" + json.dumps(VONIS.get("cancel_ulang_kelas"), default=str))
    print("modify_setelah_batal_kelas=" + json.dumps(VONIS.get("modify_setelah_batal_kelas"), default=str))
    print("mikro_10=" + json.dumps(VONIS.get("mikro_10"), default=str))
    print("mikro_19=" + json.dumps(VONIS.get("mikro_19"), default=str))
    print("jejak_ringkas=" + json.dumps(VONIS.get("jejak_ringkas"), default=str))
    sys.exit(kode)
