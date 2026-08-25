"""Uji HIDUP: kepemilikan posisi (mesin vs manual user) + sizing modal 1 USDT.

Dua tuntutan diuji di bursa sungguhan, bukan di simulasi.

A. MODAL 1 USDT. Saldo akun testnet tidak bisa disetel ke angka sembarang dan
   mengurasnya lewat trading justru merusak akun uji. Yang penting: seluruh
   perhitungan ukuran menerima saldo sebagai PARAMETER, jadi menyuntikkan
   saldo 1,00 menjalankan jalur kode yang identik dengan akun bersaldo 1 USDT.
   Yang dibuktikan di sini: order hasil hitungan itu DITERIMA bursa.

B. KEPEMILIKAN. Binance mode satu arah tidak menyimpan siapa pembuka posisi.
   Mesin memakai buku posisi lokal + awalan clientOrderId. Skenario di bawah
   memainkan peran USER sungguhan: user membatalkan proteksi mesin, menutup
   separuh posisi mesin, menutup penuh, lalu membuka posisinya sendiri.

MENGAPA DUA SIMBOL. Uji 25 Agu 2026 membuktikan simbol termurah di testnet
(1000WHYUSDT) MENOLAK order MARKET dengan -4131 PERCENT_PRICE karena tidak ada
lawan di buku. Jadi simbol termurah dipakai untuk membuktikan sizing 1 USDT
diterima bursa, sementara fase posisi memakai simbol likuid. Logika kepemilikan
sendiri tidak bergantung simbol.
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from milik_bantu import (JEJAK, baris_posisi, bersih_total, buka_posisi,  # noqa: E402
                         catat, cid, galat_dict, kurangi_posisi, order_terbuka,
                         pasang_kredensial, posisi_qty, semesta_mikro,
                         spek_dan_harga)

KELUARAN = os.environ.get("MILIK_KELUARAN", "bukti/live/MESIN_MILIK.json")
BUKU = os.environ.get("LUX_BUKU_POSISI", "bukti/live/buku_posisi.json")
SALDO_UJI = float(os.environ.get("LUX_SALDO_UJI", "1.0"))
SL_PCT = float(os.environ.get("LUX_SL_PCT_UJI", "0.5"))
SIMBOL_POSISI = os.environ.get("LUX_SIMBOL_POSISI", "BTCUSDT")
VONIS = {"temuan_market_simbol_tipis": (
    "MARKET pada 1000WHYUSDT ditolak -4131 PERCENT_PRICE (bukti/live/"
    "jejak_milik.txt commit caa32703). Penutupan fail-safe mesin memakai "
    "MARKET reduceOnly, jadi pada simbol tipis penutupan darurat bisa GAGAL.")}


def qty_untuk(spek, harga_order, minimal):
    """qty terkecil yang sah pada harga order ini. Dinaikkan, bukan diturunkan."""
    batas = max(float(minimal), float(spek.min_qty) * float(harga_order))
    q = spek.turun_qty(batas / float(harga_order))
    n = 0
    while q * float(harga_order) < batas - 1e-9 and n < 500:
        q = spek.turun_qty(q + spek.step)
        n += 1
    if q < spek.min_qty:
        q = spek.min_qty
    return q


def main():
    pasang_kredensial()
    from lux_modul.eksekusi.binance_client import BinanceFuturesClient
    from lux_modul.eksekusi.jejak import perekam
    from lux_modul.eksekusi.kepemilikan import (BukuPosisi, PenjagaKepemilikan,
                                                PosisiBukanMilikMesin)
    from lux_modul.eksekusi.klasifikasi import klasifikasikan, konfirmasi_order
    from lux_modul.eksekusi.kredensial import MODE_TESTNET, muat_kredensial
    from lux_modul.eksekusi.ukuran_mikro import rencana_mikro
    from lux_modul.eksekusi_aman.inti import SpekSimbol

    if os.path.exists(BUKU):
        os.remove(BUKU)
    klien = BinanceFuturesClient(muat_kredensial(MODE_TESTNET))
    catat("koneksi", saldo_nyata_usdt=klien.saldo_usdt(), saldo_uji=SALDO_UJI,
          simbol_posisi=SIMBOL_POSISI,
          catatan=("saldo uji disuntik sebagai parameter sizing; saldo akun "
                   "testnet TIDAK diubah karena itu akan merusak akun uji"))

    _info, calon = semesta_mikro(klien, SpekSimbol, rencana_mikro, SALDO_UJI,
                                SL_PCT)
    VONIS["kandidat_layak"] = len(calon)
    catat("kandidat", jumlah=len(calon),
          teratas=[{"simbol": c["simbol"], "margin": c["margin"],
                    "qty": c["rencana"].get("qty")} for c in calon[:5]])
    if not calon:
        VONIS["vonis"] = "GAGAL_TANPA_KANDIDAT"
        return 1

    # ============ A. sizing modal 1 USDT, benar-benar dikirim ============ #
    simbol_mikro = None
    for c in calon[:4]:
        sim, harga_m, spek_m = c["simbol"], c["harga"], c["spek"]
        bersih_total(klien, sim)
        try:
            klien.atur_leverage(sim, int(c["rencana"]["leverage_dipakai"]))
        except Exception as exc:  # noqa: BLE001
            catat("leverage_galat", simbol=sim, galat=galat_dict(exc))
            continue
        harga_pasif = spek_m.bulat_harga(harga_m * 0.90)
        r = rencana_mikro(SALDO_UJI, harga_pasif, spek_m,
                          sl_harga=harga_pasif * (1.0 - SL_PCT / 100.0),
                          arah="LONG", leverage_maks_bursa=c["lev"])
        payload = {"symbol": sim, "side": "BUY", "type": "LIMIT",
                   "timeInForce": "GTC", "price": harga_pasif,
                   "quantity": r["qty"], "newClientOrderId": cid("lx")}
        catat("sizing1_permintaan", simbol=sim, saldo_uji=SALDO_UJI,
              rencana={k: r.get(k) for k in
                       ("qty", "notional", "leverage_dipakai", "margin_nyata",
                        "base_tercapai", "risiko_pct_dari_saldo",
                        "jarak_likuidasi_pct", "layak")}, payload=payload)
        try:
            ringkas = konfirmasi_order(klien.kirim_order(payload), simbol=sim,
                                       sisi="BUY",
                                       cid=payload["newClientOrderId"])
            VONIS["sizing1_diterima_bursa"] = True
            VONIS["sizing1_order"] = ringkas
            VONIS["sizing1_rencana"] = r
            catat("sizing1_jawaban", ringkas=ringkas)
            simbol_mikro = sim
            break
        except Exception as exc:  # noqa: BLE001
            kelas = klasifikasikan(exc, jalur="/fapi/v1/order", metode="POST",
                                  dana=True).ringkas()
            catat("sizing1_galat", simbol=sim, galat=galat_dict(exc),
                  kelas=kelas, payload=payload)
    if simbol_mikro is None:
        VONIS["sizing1_diterima_bursa"] = False
        VONIS["vonis"] = "GAGAL_SIZING_1"
        return 1

    # ============ B. fase posisi pada simbol likuid ====================== #
    simbol = SIMBOL_POSISI
    spek, harga = spek_dan_harga(klien, SpekSimbol, simbol)
    VONIS["simbol_mikro"] = simbol_mikro
    VONIS["simbol_posisi"] = simbol
    bersih_total(klien, simbol)
    try:
        klien.atur_leverage(simbol, 25)
    except Exception as exc:  # noqa: BLE001
        catat("leverage_posisi_galat", simbol=simbol, galat=galat_dict(exc))
    buku = BukuPosisi(jalur=BUKU, env={})
    penjaga = PenjagaKepemilikan(buku=buku, rekam=perekam())

    def periksa(tahap):
        h = penjaga.periksa(simbol, baris_posisi(klien, simbol),
                            order_terbuka(klien, simbol))
        catat("kepemilikan_" + tahap, pemilik=h["pemilik"],
              boleh=h["boleh_dikelola_mesin"], perubahan=h["perubahan_user"],
              qty_bursa=h["qty_bursa"], qty_buku=h["qty_tercatat"],
              proteksi_hilang=h["proteksi_hilang"],
              perlu_tindakan=h["perlu_tindakan"], alasan=h["alasan"])
        VONIS["periksa_" + tahap] = {k: h.get(k) for k in
                                     ("pemilik", "boleh_dikelola_mesin",
                                      "perubahan_user", "qty_bursa",
                                      "qty_tercatat", "proteksi_hilang",
                                      "perlu_tindakan")}
        return h

    notional_uji = 3.0 * max(float(spek.min_notional),
                             float(spek.min_qty) * harga)
    qty_pos = qty_untuk(spek, harga, notional_uji)
    cid_entry = cid("lx")
    catat("entry_mesin_rencana", simbol=simbol, qty=qty_pos,
          notional=qty_pos * harga, harga=harga)
    resp, dipakai_payload, percobaan = buka_posisi(klien, simbol, "BUY",
                                                   qty_pos, cid_entry, spek,
                                                   harga)
    VONIS["entry_cara"] = percobaan
    if resp is None:
        VONIS["entry_mesin"] = False
        bersih_total(klien, simbol)
        bersih_total(klien, simbol_mikro)
        VONIS["vonis"] = "GAGAL_ENTRY_MESIN"
        return 1
    qty_nyata = posisi_qty(klien, simbol)
    VONIS["entry_mesin"] = abs(qty_nyata) > 0
    baris = baris_posisi(klien, simbol)
    buku.catat_pembukaan(simbol, "LONG", qty_nyata,
                         harga=baris.get("entryPrice"),
                         cid=dipakai_payload.get("newClientOrderId"),
                         order_id=resp.get("orderId"))
    h = periksa("posisi_mesin")
    VONIS["posisi_mesin_dikenali"] = (h["pemilik"] == "mesin"
                                      and h["boleh_dikelola_mesin"] is True)

    # proteksi milik mesin: LIMIT reduceOnly pasif di atas pasar
    tp = {"symbol": simbol, "side": "SELL", "type": "LIMIT",
          "timeInForce": "GTC", "price": spek.bulat_harga(harga * 1.05),
          "quantity": abs(qty_nyata), "reduceOnly": True,
          "newClientOrderId": cid("lx")}
    catat("proteksi_permintaan", payload=tp)
    tp_id = None
    try:
        tp_id = konfirmasi_order(klien.kirim_order(tp), simbol=simbol,
                                 sisi="SELL", cid=tp["newClientOrderId"])["orderId"]
        buku.catat_proteksi(simbol, cid_tp=tp["newClientOrderId"], order_tp=tp_id)
        VONIS["proteksi_terpasang"] = True
        catat("proteksi_jawaban", order_id=tp_id)
    except Exception as exc:  # noqa: BLE001
        VONIS["proteksi_terpasang"] = False
        catat("proteksi_galat", galat=galat_dict(exc), payload=tp)
    h = periksa("proteksi_terpasang")
    VONIS["proteksi_tercatat_utuh"] = h["proteksi_hilang"] is False

    # --- USER membatalkan proteksi mesin (seperti lewat aplikasi) --------- #
    if tp_id is not None:
        try:
            klien.batalkan_order(simbol, order_id=tp_id)
            catat("user_batalkan_proteksi", order_id=tp_id)
        except Exception as exc:  # noqa: BLE001
            catat("user_batalkan_proteksi_galat", galat=galat_dict(exc))
    h = periksa("proteksi_dibatalkan_user")
    VONIS["deteksi_proteksi_dihapus_user"] = (
        h["proteksi_hilang"] is True and h["pemilik"] == "mesin"
        and h["perubahan_user"] == "proteksi_dihapus_user")

    # --- order USER dan order MESIN hidup bersama di satu simbol ---------- #
    harga_user = spek.bulat_harga(harga * 0.85)
    pesan_user = {"symbol": simbol, "side": "BUY", "type": "LIMIT",
                  "timeInForce": "GTC", "price": harga_user,
                  "quantity": qty_untuk(spek, harga_user, spek.min_notional),
                  "newClientOrderId": cid("manual")}
    id_user = None
    try:
        id_user = klien.kirim_order(pesan_user).get("orderId")
        catat("order_user_dibuat", order_id=id_user, payload=pesan_user)
    except Exception as exc:  # noqa: BLE001
        catat("order_user_galat", galat=galat_dict(exc), payload=pesan_user)
    pesan_mesin = {"symbol": simbol, "side": "BUY", "type": "LIMIT",
                   "timeInForce": "GTC", "price": spek.bulat_harga(harga * 0.88),
                   "quantity": qty_untuk(spek, spek.bulat_harga(harga * 0.88),
                                         spek.min_notional),
                   "newClientOrderId": cid("lx")}
    try:
        catat("order_mesin_dibuat",
              order_id=klien.kirim_order(pesan_mesin).get("orderId"),
              payload=pesan_mesin)
    except Exception as exc:  # noqa: BLE001
        catat("order_mesin_galat", galat=galat_dict(exc), payload=pesan_mesin)

    terbuka = order_terbuka(klien, simbol)
    VONIS["batal_semua_ditolak"] = penjaga.boleh_batal_semua(simbol, terbuka) is False
    milik_mesin = penjaga.order_mesin(terbuka)
    catat("pisah_order", total=len(terbuka), milik_mesin=len(milik_mesin),
          id_mesin=[o.get("orderId") for o in milik_mesin], id_user=id_user)
    for o in milik_mesin:
        try:
            klien.batalkan_order(simbol, order_id=o.get("orderId"))
        except Exception as exc:  # noqa: BLE001
            catat("batal_mesin_galat", order_id=o.get("orderId"),
                  galat=galat_dict(exc))
    sisa = [o.get("orderId") for o in order_terbuka(klien, simbol)]
    VONIS["order_user_tetap_utuh"] = (id_user in sisa) if id_user else None
    catat("verifikasi_order_user", sisa_ids=sisa, id_user=id_user,
          utuh=VONIS["order_user_tetap_utuh"])

    # --- USER menutup SEPARUH posisi mesin -------------------------------- #
    q_separuh = spek.turun_qty(abs(qty_nyata) / 2.0)
    if q_separuh * harga >= spek.min_notional and q_separuh >= spek.min_qty:
        kurangi_posisi(klien, simbol, "SELL", q_separuh, cid("manual"), spek,
                       harga, label="user_separuh")
    else:
        catat("user_tutup_separuh_dilewati", qty=q_separuh,
              alasan="separuh posisi di bawah minimum notional bursa")
    h = periksa("partial_close_user")
    VONIS["deteksi_partial_close_user"] = (
        h["pemilik"] == "mesin" and h["boleh_dikelola_mesin"] is True
        and h["perubahan_user"] == "dikurangi_user")
    buku.selaraskan_qty(simbol, posisi_qty(klien, simbol),
                        alasan="partial_close_user")

    # --- kepemilikan harus selamat dari RESTART proses -------------------- #
    penjaga2 = PenjagaKepemilikan(buku=BukuPosisi(jalur=BUKU, env={}),
                                  rekam=perekam())
    h2 = penjaga2.periksa(simbol, baris_posisi(klien, simbol),
                          order_terbuka(klien, simbol))
    VONIS["kepemilikan_selamat_restart"] = (h2["pemilik"] == "mesin")
    catat("kepemilikan_setelah_restart", pemilik=h2["pemilik"],
          qty_bursa=h2["qty_bursa"], qty_buku=h2["qty_tercatat"],
          perubahan=h2["perubahan_user"])

    # --- USER menutup PENUH posisi mesin ---------------------------------- #
    sisa_qty = posisi_qty(klien, simbol)
    if abs(sisa_qty) > 0:
        kurangi_posisi(klien, simbol, "SELL" if sisa_qty > 0 else "BUY",
                       abs(sisa_qty), cid("manual"), spek, harga,
                       label="user_penuh")
    h = periksa("close_penuh_user")
    VONIS["deteksi_close_penuh_user"] = (
        h["pemilik"] == "kosong" and h["perubahan_user"] == "ditutup_user"
        and h["perlu_tindakan"] == "tutup_buku_dan_batalkan_proteksi_mesin")
    buku.tutup(simbol, alasan="ditutup_user")

    # --- posisi MANUAL user: mesin WAJIB menolak menyentuhnya ------------- #
    buka_posisi(klien, simbol, "BUY", qty_pos, cid("manual"), spek, harga)
    h = periksa("posisi_manual_user")
    VONIS["posisi_manual_dikenali_user"] = (h["pemilik"] == "user"
                                            and h["boleh_dikelola_mesin"] is False)
    try:
        penjaga.pastikan_boleh_kelola(simbol, baris_posisi(klien, simbol),
                                     order_terbuka(klien, simbol),
                                     tindakan="tutup_posisi")
        VONIS["posisi_manual_ditolak"] = False
        catat("BAHAYA_mesin_mengizinkan_posisi_manual")
    except PosisiBukanMilikMesin as exc:
        VONIS["posisi_manual_ditolak"] = True
        VONIS["laporan_enam_fakta"] = exc.laporan
        catat("mesin_menolak_posisi_manual", laporan=exc.laporan)

    sisa_akhir = bersih_total(klien, simbol)
    bersih_total(klien, simbol_mikro)
    VONIS["user_tetap_bisa_menutup"] = abs(sisa_akhir) <= 0
    VONIS["bersih_akhir"] = abs(sisa_akhir) <= 0

    p = perekam()
    berkas = getattr(p, "berkas_terpakai", None)
    baris_jejak = 0
    if berkas and os.path.exists(berkas):
        fh = open(berkas, "r", encoding="utf-8")
        baris_jejak = sum(1 for _ in fh)
        fh.close()
    VONIS["jejak_berkas"] = berkas
    VONIS["jejak_baris"] = baris_jejak
    VONIS["jejak_ringkas"] = p.ringkas() if hasattr(p, "ringkas") else {}
    catat("jejak", berkas=berkas, baris=baris_jejak, ringkas=VONIS["jejak_ringkas"])

    lulus = all([
        VONIS.get("sizing1_diterima_bursa"), VONIS.get("entry_mesin"),
        VONIS.get("posisi_mesin_dikenali"), VONIS.get("proteksi_tercatat_utuh"),
        VONIS.get("deteksi_proteksi_dihapus_user"),
        VONIS.get("batal_semua_ditolak"), VONIS.get("order_user_tetap_utuh"),
        VONIS.get("deteksi_partial_close_user"),
        VONIS.get("kepemilikan_selamat_restart"),
        VONIS.get("deteksi_close_penuh_user"),
        VONIS.get("posisi_manual_dikenali_user"),
        VONIS.get("posisi_manual_ditolak"), VONIS.get("bersih_akhir"),
        baris_jejak > 0,
    ])
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
    print("MESIN_MILIK=" + str(VONIS.get("vonis")))
    for kunci in ("simbol_mikro", "simbol_posisi", "kandidat_layak",
                  "sizing1_diterima_bursa", "entry_mesin",
                  "posisi_mesin_dikenali", "proteksi_terpasang",
                  "proteksi_tercatat_utuh", "deteksi_proteksi_dihapus_user",
                  "batal_semua_ditolak", "order_user_tetap_utuh",
                  "deteksi_partial_close_user", "kepemilikan_selamat_restart",
                  "deteksi_close_penuh_user", "posisi_manual_dikenali_user",
                  "posisi_manual_ditolak", "user_tetap_bisa_menutup",
                  "bersih_akhir", "jejak_berkas", "jejak_baris"):
        print(str(kunci) + "=" + json.dumps(VONIS.get(kunci), default=str))
    print("entry_cara=" + json.dumps(VONIS.get("entry_cara"), default=str))
    print("sizing1_rencana=" + json.dumps(VONIS.get("sizing1_rencana"), default=str))
    print("sizing1_order=" + json.dumps(VONIS.get("sizing1_order"), default=str))
    print("laporan_enam_fakta=" + json.dumps(VONIS.get("laporan_enam_fakta"), default=str))
    print("jejak_ringkas=" + json.dumps(VONIS.get("jejak_ringkas"), default=str))
    for tahap in ("posisi_mesin", "proteksi_terpasang", "proteksi_dibatalkan_user",
                  "partial_close_user", "close_penuh_user", "posisi_manual_user"):
        print("periksa_" + tahap + "=" + json.dumps(VONIS.get("periksa_" + tahap),
                                                    default=str))
    sys.exit(kode)
