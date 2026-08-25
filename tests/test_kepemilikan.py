"""Uji lapisan kepemilikan posisi.

Yang dikunci di sini adalah janji paling berbahaya kalau dilanggar: mesin tidak
boleh menyentuh posisi manual user, dan identitas posisi harus tetap konsisten
walau user memodifikasi SL/TP, menutup sebagian, atau menutup penuh.
"""
import json
import os

import pytest

from lux_modul.eksekusi.jejak import perekam_senyap
from lux_modul.eksekusi.kepemilikan import (
    ARAH_BERUBAH_USER,
    BUKU_HILANG,
    DIKURANGI_USER,
    DITAMBAH_USER,
    DITUTUP_USER,
    ENV_AWALAN,
    MILIK_CAMPUR,
    MILIK_KOSONG,
    MILIK_MESIN,
    MILIK_USER,
    PROTEKSI_HILANG_USER,
    UTUH,
    BukuPosisi,
    PenjagaKepemilikan,
    PosisiBukanMilikMesin,
    awalan_mesin,
    cid_mesin,
    klasifikasi_posisi,
    pemilik_order,
    pisahkan_order,
)


def posisi(qty, harga=100.0):
    return {"symbol": "BTCUSDT", "positionAmt": str(qty), "entryPrice": str(harga)}


def order(cid, oid=1, tipe="LIMIT"):
    return {"orderId": oid, "clientOrderId": cid, "symbol": "BTCUSDT",
            "type": tipe, "status": "NEW"}


def buku_baru(tmp_path, nama="buku.json"):
    return BukuPosisi(jalur=os.path.join(str(tmp_path), nama), env={})


# ---------------------------------------------------------------- cid ---- #
def test_cid_mesin_mengenali_awalan_bawaan():
    assert cid_mesin("lxe8355e81e94d3b916205")
    assert cid_mesin("lxsfe7c6525e65ec4e03")
    assert not cid_mesin("web_1a2b3c")
    assert not cid_mesin("android_99")
    assert not cid_mesin("")
    assert not cid_mesin(None)


def test_awalan_bisa_ditambah_lewat_env(monkeypatch):
    monkeypatch.setenv(ENV_AWALAN, "bot_ , zz")
    assert awalan_mesin() == ("bot_", "zz")
    assert cid_mesin("bot_7", awalan_mesin())
    assert not cid_mesin("lx7", awalan_mesin())


def test_pemilik_order_dari_client_order_id():
    assert pemilik_order(order("lx123")) == MILIK_MESIN
    assert pemilik_order(order("web_123")) == MILIK_USER
    assert pemilik_order({"origClientOrderId": "lxabc"}) == MILIK_MESIN
    assert pemilik_order({"orderId": 5}) == MILIK_USER


def test_pisahkan_order_memisahkan_mesin_dan_user():
    pecah = pisahkan_order([order("lx1", 1), order("web_2", 2), order("lxs3", 3)])
    assert pecah["jumlah_mesin"] == 2
    assert pecah["jumlah_user"] == 1
    assert [o["orderId"] for o in pecah["user"]] == [2]


# --------------------------------------------------------------- buku ---- #
def test_buku_posisi_tahan_restart(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 0.5, harga=70000.0, cid="lxaaa",
                      order_id=111)
    lagi = BukuPosisi(jalur=b.jalur, env={})
    e = lagi.ambil("BTCUSDT")
    assert e["arah"] == "LONG"
    assert e["qty"] == 0.5
    assert e["cid_entry"] == "lxaaa"
    assert lagi.milik_mesin("BTCUSDT")


def test_buku_posisi_tulis_atomik_tanpa_sisa_tmp(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("ETHUSDT", "SHORT", 2.0)
    assert not os.path.exists(b.jalur + ".tmp")
    isi = json.load(open(b.jalur, encoding="utf-8"))
    assert isi["versi"] == 1
    assert "ETHUSDT" in isi["entri"]


def test_buku_gagal_tulis_tidak_melempar(tmp_path):
    penghalang = os.path.join(str(tmp_path), "bukan_direktori")
    open(penghalang, "w").write("x")
    b = BukuPosisi(jalur=os.path.join(penghalang, "buku.json"), env={})
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0)
    assert b.gagal_tulis >= 1
    assert b.ambil("BTCUSDT")["qty"] == 1.0


def test_selaraskan_qty_tidak_mengubah_pemilik(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0, cid="lxaaa")
    b.selaraskan_qty("BTCUSDT", 0.4, alasan="partial_close_user")
    e = b.ambil("BTCUSDT")
    assert e["qty"] == 0.4
    assert e["qty_awal"] == 1.0
    assert e["cid_entry"] == "lxaaa"
    assert klasifikasi_posisi("BTCUSDT", posisi(0.4), e)["pemilik"] == MILIK_MESIN


def test_tutup_menghapus_dari_buku(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0)
    e = b.tutup("BTCUSDT", alasan="tp_kena")
    assert e["ditutup"] is True
    assert b.ambil("BTCUSDT") is None
    assert not BukuPosisi(jalur=b.jalur, env={}).milik_mesin("BTCUSDT")


# -------------------------------------------------------- klasifikasi ---- #
def test_posisi_tanpa_catatan_dianggap_milik_user():
    h = klasifikasi_posisi("BTCUSDT", posisi(1.0), None, [order("web_9", 9)])
    assert h["pemilik"] == MILIK_USER
    assert h["boleh_dikelola_mesin"] is False
    assert h["buku_hilang"] is False
    assert "manual" in h["alasan"]


def test_posisi_tanpa_catatan_tapi_ada_cid_mesin_jadi_buku_hilang():
    h = klasifikasi_posisi("BTCUSDT", posisi(1.0), None, [order("lx9", 9)])
    assert h["pemilik"] == MILIK_CAMPUR
    assert h["boleh_dikelola_mesin"] is False
    assert h["buku_hilang"] is True
    assert h["perubahan_user"] == BUKU_HILANG
    assert h["perlu_tindakan"] == "rekonsiliasi_manual"


def test_posisi_cocok_buku_milik_mesin():
    catatan = {"arah": "LONG", "qty": 1.0}
    h = klasifikasi_posisi("BTCUSDT", posisi(1.0), catatan, [])
    assert h["pemilik"] == MILIK_MESIN
    assert h["boleh_dikelola_mesin"] is True
    assert h["perubahan_user"] == UTUH
    assert h["selisih_qty"] == 0.0


def test_partial_close_user_tetap_milik_mesin():
    catatan = {"arah": "LONG", "qty": 1.0}
    h = klasifikasi_posisi("BTCUSDT", posisi(0.4), catatan, [])
    assert h["pemilik"] == MILIK_MESIN
    assert h["boleh_dikelola_mesin"] is True
    assert h["perubahan_user"] == DIKURANGI_USER
    assert h["perlu_tindakan"] == "selaraskan_qty_dan_perbarui_proteksi"
    assert h["selisih_qty"] < 0


def test_user_menambah_posisi_jadi_campuran_dan_dilarang():
    catatan = {"arah": "LONG", "qty": 1.0}
    h = klasifikasi_posisi("BTCUSDT", posisi(1.5), catatan, [])
    assert h["pemilik"] == MILIK_CAMPUR
    assert h["boleh_dikelola_mesin"] is False
    assert h["perubahan_user"] == DITAMBAH_USER
    assert "satu arah" in h["alasan"]


def test_arah_dibalik_user_jadi_campuran():
    catatan = {"arah": "LONG", "qty": 1.0}
    h = klasifikasi_posisi("BTCUSDT", posisi(-1.0), catatan, [])
    assert h["pemilik"] == MILIK_CAMPUR
    assert h["boleh_dikelola_mesin"] is False
    assert h["perubahan_user"] == ARAH_BERUBAH_USER
    assert h["arah_bursa"] == "SHORT"


def test_posisi_habis_terdeteksi_ditutup_user():
    catatan = {"arah": "LONG", "qty": 1.0, "order_sl": 5}
    h = klasifikasi_posisi("BTCUSDT", posisi(0.0), catatan, [])
    assert h["pemilik"] == MILIK_KOSONG
    assert h["perubahan_user"] == DITUTUP_USER
    assert h["perlu_tindakan"] == "tutup_buku_dan_batalkan_proteksi_mesin"


def test_tanpa_posisi_dan_tanpa_buku_bukan_masalah():
    h = klasifikasi_posisi("BTCUSDT", posisi(0.0), None, [])
    assert h["pemilik"] == MILIK_KOSONG
    assert h["perubahan_user"] == UTUH
    assert h["boleh_dikelola_mesin"] is True


def test_proteksi_dibatalkan_user_terdeteksi():
    catatan = {"arah": "LONG", "qty": 1.0, "order_sl": 77, "order_tp": 88}
    h = klasifikasi_posisi("BTCUSDT", posisi(1.0), catatan, [order("lx88", 88)])
    assert h["pemilik"] == MILIK_MESIN
    assert h["proteksi_hilang"] is True
    assert h["perubahan_user"] == PROTEKSI_HILANG_USER
    assert h["perlu_tindakan"] == "pasang_ulang_proteksi"


def test_identitas_konsisten_setelah_sl_tp_diganti(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0, cid="lxaaa", order_id=1)
    b.catat_proteksi("BTCUSDT", cid_sl="lxsl1", order_sl=77, order_tp=88)
    b.catat_proteksi("BTCUSDT", cid_sl="lxsl2", order_sl=99)
    e = b.ambil("BTCUSDT")
    assert e["order_sl"] == 99 and e["order_tp"] == 88 and e["revisi"] == 2
    h = klasifikasi_posisi("BTCUSDT", posisi(1.0), e,
                           [order("lxsl2", 99), order("lxtp", 88)])
    assert h["pemilik"] == MILIK_MESIN
    assert h["proteksi_hilang"] is False


# ------------------------------------------------------------ penjaga ---- #
def test_penjaga_menolak_posisi_manual_dengan_enam_fakta(tmp_path):
    p = PenjagaKepemilikan(buku=buku_baru(tmp_path), rekam=perekam_senyap())
    with pytest.raises(PosisiBukanMilikMesin) as galat:
        p.pastikan_boleh_kelola("BTCUSDT", posisi(1.0), [order("web_1", 1)],
                                tindakan="tutup_posisi")
    lap = galat.value.laporan
    for kunci in ("proses", "penyebab", "parameter", "jawaban_api", "dampak",
                  "perlu_diperbaiki"):
        assert lap.get(kunci)
    assert lap["proses"] == "tutup_posisi"
    assert lap["pemilik"] == MILIK_USER
    assert "tidak disentuh" in lap["dampak"]


def test_penjaga_mengizinkan_posisi_mesin(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0, cid="lxaaa")
    p = PenjagaKepemilikan(buku=b, rekam=perekam_senyap())
    h = p.pastikan_boleh_kelola("BTCUSDT", posisi(1.0), [], tindakan="pasang_sl")
    assert h["pemilik"] == MILIK_MESIN


def test_penjaga_hanya_boleh_batalkan_order_mesin(tmp_path):
    p = PenjagaKepemilikan(buku=buku_baru(tmp_path), rekam=perekam_senyap())
    assert p.boleh_batalkan_order(order("lx1", 1))
    assert not p.boleh_batalkan_order(order("web_2", 2))
    assert [o["orderId"] for o in p.order_mesin([order("lx1", 1),
                                                 order("web_2", 2)])] == [1]


def test_batal_semua_ditolak_bila_ada_order_user(tmp_path):
    rekam = perekam_senyap()
    p = PenjagaKepemilikan(buku=buku_baru(tmp_path), rekam=rekam)
    assert p.boleh_batal_semua("BTCUSDT", [order("lx1", 1), order("web_2", 2)]) is False
    assert p.boleh_batal_semua("BTCUSDT", [order("lx1", 1)]) is True
    baris = rekam.terakhir(n=10, peristiwa="keputusan")
    assert any(r.get("keputusan") == "tolak_batal_semua" for r in baris)


def test_jejak_kepemilikan_tercatat(tmp_path):
    rekam = perekam_senyap()
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0, cid="lxaaa")
    p = PenjagaKepemilikan(buku=b, rekam=rekam)
    p.periksa("BTCUSDT", posisi(0.4), [])
    baris = [r for r in rekam.terakhir(n=10, peristiwa="keputusan")
             if r.get("keputusan") == "kepemilikan"]
    assert baris
    assert baris[-1]["pemilik"] == MILIK_MESIN
    assert baris[-1]["perubahan_user"] == DIKURANGI_USER
    assert baris[-1]["qty_bursa"] == 0.4


def test_failsafe_tercatat_saat_menolak(tmp_path):
    rekam = perekam_senyap()
    p = PenjagaKepemilikan(buku=buku_baru(tmp_path), rekam=rekam)
    with pytest.raises(PosisiBukanMilikMesin):
        p.pastikan_boleh_kelola("BTCUSDT", posisi(2.0), [], tindakan="ubah_sl")
    baris = rekam.terakhir(n=10, peristiwa="failsafe")
    assert baris and baris[-1]["pemicu"] == "kepemilikan_bukan_mesin"
    assert baris[-1]["tindakan"] == "tolak_ubah_sl"
    assert baris[-1]["berhasil"] is False


def test_buku_terhapus_mesin_tidak_menutup_posisi(tmp_path):
    b = buku_baru(tmp_path)
    b.catat_pembukaan("BTCUSDT", "LONG", 1.0, cid="lxaaa")
    os.remove(b.jalur)
    lagi = BukuPosisi(jalur=b.jalur, env={})
    p = PenjagaKepemilikan(buku=lagi, rekam=perekam_senyap())
    with pytest.raises(PosisiBukanMilikMesin) as galat:
        p.pastikan_boleh_kelola("BTCUSDT", posisi(1.0), [order("lxaaa", 1)],
                                tindakan="tutup_posisi")
    assert galat.value.laporan["pemilik"] == MILIK_CAMPUR
    assert "rekonsiliasi_manual" in galat.value.laporan["perlu_diperbaiki"]
