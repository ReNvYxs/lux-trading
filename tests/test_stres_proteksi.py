"""Stress test lapis 2b: proteksi, pembatalan, dan jaring pengaman siklus.

Aturan yang dikunci di sini: sebuah proses yang menyentuh dana TIDAK boleh
disebut berhasil sebelum keadaan di bursa membuktikannya. Pembatalan diverifikasi
lewat openOrders, penutupan diverifikasi lewat positionRisk, dan setiap kegagalan
melaporkan dampaknya beserta bagian mana yang perlu diperbaiki.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.binance_client import BinanceAPIError
from lux_modul.eksekusi_aman.inti import (
    ARAH_LONG,
    BATAS_GAGAL_HARGA,
    GagalProteksi,
    KebijakanRisiko,
    PengirimOrder,
    Proteksi,
    SpekSimbol,
    jalankan_siklus,
)


def spek():
    return SpekSimbol(0.10, 0.0001, 0.0001, 120.0, 50.0, 2, 4)


class KlienProteksi:
    def __init__(self, posisi_amt=0.001, entry=64_000.0, order_terbuka_hasil=None,
                 batal=None, harga=None, tutup_membersihkan=True,
                 tolak_gtc=False, tp_terlihat=False, order_terbuka_galat=None,
                 status_akhir=("FILLED", "0.05")):
        self.posisi_amt = posisi_amt
        self.entry = entry
        self._ot = [] if order_terbuka_hasil is None else order_terbuka_hasil
        self._batal = {"code": 200, "msg": "done"} if batal is None else batal
        self._harga = harga
        self.tutup_membersihkan = tutup_membersihkan
        self.tolak_gtc = tolak_gtc
        self.tp_terlihat = tp_terlihat
        self.order_terbuka_galat = order_terbuka_galat
        self.status_akhir = status_akhir
        self.terkirim = []
        self.jumlah_batal = 0

    def posisi(self, simbol=None):
        if abs(self.posisi_amt) <= 0:
            return []
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.posisi_amt),
                 "entryPrice": str(self.entry)}]

    def order_terbuka(self, simbol=None):
        if self.order_terbuka_galat is not None:
            raise self.order_terbuka_galat
        return self._ot

    def batalkan_semua_order(self, simbol=None):
        self.jumlah_batal += 1
        if isinstance(self._batal, Exception):
            raise self._batal
        return self._batal

    def bid_ask_terbaik(self, simbol=None):
        return {"bid": 64_000.0, "ask": 64_001.0}

    def harga_sekarang(self, simbol=None):
        if isinstance(self._harga, Exception):
            raise self._harga
        return self._harga

    def kirim_order(self, payload):
        self.terkirim.append(payload)
        oid = 900 + len(self.terkirim)
        gtc = payload.get("timeInForce") == "GTC"
        if self.tolak_gtc and gtc:
            raise BinanceAPIError(400, -2019, "Margin is insufficient.")
        if payload.get("reduceOnly") and gtc:
            if self.tp_terlihat:
                self._ot = list(self._ot) + [
                    {"orderId": oid, "reduceOnly": True, "type": "LIMIT",
                     "side": payload["side"],
                     "origQty": str(payload.get("quantity")),
                     "price": str(payload.get("price"))}]
        elif payload.get("reduceOnly") and self.tutup_membersihkan:
            self.posisi_amt = 0.0
        return {"orderId": oid, "clientOrderId": None,
                "symbol": payload["symbol"], "side": payload["side"],
                "status": "FILLED", "type": payload.get("type", "LIMIT"),
                "origQty": str(payload.get("quantity", 0)),
                "executedQty": str(payload.get("quantity", 0)),
                "price": str(payload.get("price", 0)), "avgPrice": "64000"}

    def _permintaan(self, metode, jalur, params=None, signed=False):
        return {}

    def status_order(self, simbol, order_id=None, **lain):
        st, terisi = self.status_akhir
        return {"orderId": order_id or 1, "clientOrderId": None,
                "symbol": "BTCUSDT", "side": "BUY", "status": st,
                "type": "LIMIT", "origQty": "0.05", "executedQty": terisi,
                "price": "64000", "avgPrice": "64000"}

    def sinkron_waktu(self):
        return 0


class DataStub:
    def __init__(self, harga=64_000.0):
        self.harga = harga

    def mark(self, simbol):
        return self.harga

    def bid_ask(self, simbol):
        return {"bid": 64_000.0, "ask": 64_001.0}


def proteksi(klien):
    p = PengirimOrder(klien, tidur=lambda _d: None, coba_maks=1, jeda_awal=0.0)
    return Proteksi(klien, p, spek(), "BTCUSDT", tidur=lambda _d: None)


# --------------------------- pembatalan order --------------------------- #


def test_pembatalan_terkonfirmasi_dan_terverifikasi_bersih():
    h = proteksi(KlienProteksi()).batalkan_proteksi()
    assert h["terkonfirmasi"] is True
    assert h["konfirmasi"]["bentuk"] == "semua_order"
    assert h["sisa_order"] == 0
    assert h["bersih"] is True
    assert "masalah" not in h


def test_pembatalan_gagal_2011_dilaporkan_beserta_order_yatim():
    # Versi lama menelan galat lalu mengosongkan state lokal seolah berhasil.
    sisa = [{"orderId": 5, "reduceOnly": True, "type": "LIMIT",
             "side": "SELL", "origQty": "0.001", "price": "70000"}]
    k = KlienProteksi(order_terbuka_hasil=sisa,
                      batal=BinanceAPIError(400, -2011, "Unknown order sent."))
    h = proteksi(k).batalkan_proteksi()
    assert h["terkonfirmasi"] is False
    assert "Unknown order" in h["galat"]
    assert h["kelas"]["kelas"] == "tidak_ada"
    assert h["sisa_order"] == 1
    assert h["bersih"] is False
    assert h["masalah"] == "orphan_proteksi_masih_hidup"
    assert h["order_yatim"][0]["orderId"] == 5


def test_jawaban_pembatalan_bentuk_salah_tidak_diterima():
    h = proteksi(KlienProteksi(batal={"status": "NEW"})).batalkan_proteksi()
    assert h["terkonfirmasi"] is False
    assert "tidak dikonfirmasi" in h["galat"]


def test_order_terbuka_selalu_berbentuk_daftar_objek():
    # Jawaban berbentuk objek dulu membuat iterasi menghasilkan string lalu
    # pemanggil jatuh AttributeError persis di jalur proteksi.
    p = proteksi(KlienProteksi(order_terbuka_hasil={"orderId": 7,
                                                   "reduceOnly": True}))
    assert p.order_terbuka() == [{"orderId": 7, "reduceOnly": True}]
    p2 = proteksi(KlienProteksi(order_terbuka_hasil={"code": 200,
                                                    "msg": "done"}))
    assert p2.order_terbuka() == []
    assert proteksi(KlienProteksi()).order_terbuka() == []


# ------------------------- SL perangkat lunak --------------------------- #


def test_harga_buta_berulang_berakhir_pada_failsafe():
    # SL perangkat lunak tanpa harga BUKAN proteksi.
    k = KlienProteksi(harga=TimeoutError("the read operation timed out"))
    p = proteksi(k)
    p.sl_harga = 63_000.0
    a = p.periksa_sl()
    assert a["aksi"] == "harga_tidak_terbaca" and a["berturut"] == 1
    assert p.periksa_sl()["berturut"] == 2
    c = p.periksa_sl()
    assert c["aksi"] == "failsafe_harga_buta"
    assert c["berturut"] == BATAS_GAGAL_HARGA
    assert c["penutupan"]["bersih"] is True
    assert k.posisi_amt == 0.0


def test_harga_terbaca_kembali_mereset_hitungan():
    k = KlienProteksi(harga=TimeoutError("timeout"))
    p = proteksi(k)
    p.sl_harga = 63_000.0
    p.periksa_sl()
    k._harga = 64_000.0
    assert p.periksa_sl()["aksi"] == "aman"
    assert p._gagal_harga == 0


def test_sl_tersentuh_dan_posisi_terbukti_tertutup():
    k = KlienProteksi()
    p = proteksi(k)
    p.sl_harga = 63_000.0
    h = p.periksa_sl(mark_harga=62_000.0)
    assert h["aksi"] == "sl_dieksekusi"
    assert h["penutupan"]["bersih"] is True
    assert "dampak" not in h


def test_sl_tersentuh_tetapi_posisi_TIDAK_tertutup_dilaporkan_keras():
    # p09: LIMIT IOC bisa EXPIRED tanpa menutup posisi, jadi fallback MARKET
    # wajib dipakai, dan bila tetap gagal, itu HARUS dilaporkan.
    k = KlienProteksi(tutup_membersihkan=False)
    p = proteksi(k)
    p.sl_harga = 63_000.0
    h = p.periksa_sl(mark_harga=62_000.0)
    assert h["aksi"] == "sl_gagal_menutup"
    assert "risiko masih berjalan" in h["dampak"]
    assert h["perlu_diperbaiki"] == "Proteksi.tutup_posisi"
    langkah = [j.get("langkah") for j in h["penutupan"]["jejak"]]
    assert "limit_ioc" in langkah
    assert "fallback_market" in langkah


# --------------------------- rekonsiliasi ------------------------------- #


def test_rekonsiliasi_posisi_tanpa_proteksi():
    h = proteksi(KlienProteksi()).rekonsiliasi()
    assert h["ada_posisi"] is True
    assert h["masalah"] == "posisi_tanpa_proteksi"


def test_rekonsiliasi_orphan_proteksi():
    k = KlienProteksi(posisi_amt=0.0, order_terbuka_hasil=[
        {"orderId": 5, "reduceOnly": True, "origQty": "0.001"}])
    h = proteksi(k).rekonsiliasi()
    assert h["ada_posisi"] is False
    assert h["masalah"] == "orphan_proteksi"


def test_rekonsiliasi_ukuran_proteksi_tidak_cocok():
    k = KlienProteksi(order_terbuka_hasil=[
        {"orderId": 5, "reduceOnly": True, "origQty": "0.005"}])
    assert proteksi(k).rekonsiliasi()["masalah"] == "ukuran_proteksi_tidak_cocok"


def test_rekonsiliasi_sl_tidak_dipantau():
    k = KlienProteksi(order_terbuka_hasil=[
        {"orderId": 5, "reduceOnly": True, "origQty": "0.001"}])
    assert proteksi(k).rekonsiliasi()["masalah"] == "sl_tidak_dipantau"


# ------------------------- pemasangan proteksi -------------------------- #


def test_tp_ditolak_membuat_posisi_ditutup():
    k = KlienProteksi(tolak_gtc=True)
    with pytest.raises(GagalProteksi) as e:
        proteksi(k).pasang(66_000.0, 63_000.0, "ember1")
    assert "bersih=True" in str(e.value)
    assert k.posisi_amt == 0.0


def test_tp_ok_tetapi_tidak_terlihat_di_bursa_membuat_posisi_ditutup():
    # Respons OK saja TIDAK cukup: TP harus terlihat di openOrders.
    k = KlienProteksi()
    with pytest.raises(GagalProteksi) as e:
        proteksi(k).pasang(66_000.0, 63_000.0, "ember2")
    assert "tidak terlihat" in str(e.value)
    assert k.posisi_amt == 0.0


def test_tp_terpasang_dan_terlihat_maka_posisi_dipertahankan():
    k = KlienProteksi(tp_terlihat=True)
    h = proteksi(k).pasang(66_000.0, 63_000.0, "ember3")
    assert h["terlihat_di_bursa"] is True
    assert h["tp_harga"] == pytest.approx(66_000.0)
    assert h["sl_harga"] == pytest.approx(63_000.0)
    assert h["qty"] == pytest.approx(0.001)
    assert k.posisi_amt == pytest.approx(0.001)


def test_tp_di_sisi_salah_ditolak_sebelum_dikirim():
    k = KlienProteksi()
    with pytest.raises(GagalProteksi):
        proteksi(k).pasang(63_500.0, 63_000.0, "ember4")
    assert k.terkirim == []


# ------------------------- siklus penuh -------------------------------- #


def siklus(k, **opsi):
    return jalankan_siklus(k, "BTCUSDT", ARAH_LONG, 63_000.0, 66_000.0,
                           KebijakanRisiko(), spek=spek(), data=DataStub(),
                           tidur=lambda _d: None, saldo=5000.0, **opsi)


def test_siklus_entry_tidak_terisi_berhenti_bersih():
    k = KlienProteksi(posisi_amt=0.0, status_akhir=("EXPIRED", "0"))
    h = siklus(k)
    assert h["entry"]["terisi"] == 0.0
    assert h["kesimpulan"] == "tidak_terisi"
    assert h["rekonsiliasi"]["masalah"] is None


def test_siklus_tp_gagal_menutup_posisi_dan_melapor():
    k = KlienProteksi(posisi_amt=0.05, tolak_gtc=True)
    h = siklus(k)
    assert h["entry"]["terisi"] == pytest.approx(0.05)
    assert h["kesimpulan"] == "gagal_dilindungi_posisi_ditutup"
    assert "bersih=True" in h["proteksi_gagal"]
    assert h["rekonsiliasi"]["ada_posisi"] is False


def test_siklus_galat_tak_terduga_setelah_fill_tetap_menutup_posisi():
    # Inilah perbaikan dari kegagalan p10: galat -2013 saat membaca status
    # sempat meninggalkan posisi 0,0261 BTC tanpa proteksi.
    k = KlienProteksi(posisi_amt=0.05,
                      order_terbuka_galat=ValueError("bentuk jawaban aneh"))
    h = siklus(k)
    assert "ValueError" in h["galat_tak_terduga"]
    assert h["kesimpulan"] == "galat_tak_terduga_posisi_ditutup"
    assert h["failsafe"]["bersih"] is True
    assert k.posisi_amt == 0.0
