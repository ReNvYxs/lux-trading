"""Kunci jahitan saklar LUX_EKSEKUSI di LiveRunner.

Dibuktikan dua arah:
  - default -> tetap memakai payload lama, jadi tidak ada perubahan perilaku.
  - mode aman -> memakai lapisan tervalidasi, jalur lama tidak boleh tersentuh,
    dan objek proteksi disimpan supaya SL perangkat lunak benar-benar dipantau
    tiap siklus (SL mode aman tidak ada di bursa, jadi tanpa pemantau ini
    posisi akan berjalan tanpa stop).
"""
import lux_modul.live_runner as lr
from lux_modul.kontrak import TFPlan


class KlienKosong:
    def kirim_order(self, payload):
        return {"orderId": 1, "status": "NEW"}

    def harga_sekarang(self, simbol):
        return 100.0


class VerdictPalsu:
    arah = "LONG"
    skor = 70.0
    strategy_id = "uji"
    sl = 90.0
    tps = ()


def buat_runner():
    return lr.LiveRunner(client=KlienKosong(), simbol="BTCUSDT",
                         tfplan=TFPlan("4h", ()))


def test_default_memakai_payload_lama(monkeypatch):
    dipanggil = {"sl": 0, "tp": 0, "aman": 0}

    def sl_palsu(*a, **k):
        dipanggil["sl"] += 1
        return {"type": "STOP_MARKET"}

    def tp_palsu(*a, **k):
        dipanggil["tp"] += 1
        return {"type": "TAKE_PROFIT_MARKET"}

    def aman_palsu(**k):
        dipanggil["aman"] += 1
        return {}

    monkeypatch.setattr(lr, "aman_aktif", lambda env=None: False)
    monkeypatch.setattr(lr, "payload_sl", sl_palsu)
    monkeypatch.setattr(lr, "payload_tp_market", tp_palsu)
    monkeypatch.setattr(lr, "pasang_proteksi_aman", aman_palsu)

    r = buat_runner()
    siklus = lr.SiklusHasil()
    sl_id, tp_id = r._pasang_proteksi(VerdictPalsu(), 90.0, 110.0, siklus)

    assert dipanggil == {"sl": 1, "tp": 1, "aman": 0}
    assert sl_id == 1
    assert tp_id == 1


def test_mode_aman_memakai_lapisan_aman(monkeypatch):
    class ProteksiPalsu:
        def periksa_sl(self):
            return {"aksi": "aman"}

    prot = ProteksiPalsu()

    def aman_palsu(**k):
        return {"tp": {"orderId": 77}, "sl_harga": 90.0, "gagal": None,
                "proteksi": prot}

    def jangan_dipanggil(*a, **k):
        raise AssertionError("jalur lama tidak boleh dipakai di mode aman")

    monkeypatch.setattr(lr, "aman_aktif", lambda env=None: True)
    monkeypatch.setattr(lr, "pasang_proteksi_aman", aman_palsu)
    monkeypatch.setattr(lr, "payload_sl", jangan_dipanggil)
    monkeypatch.setattr(lr, "payload_tp_market", jangan_dipanggil)

    r = buat_runner()
    siklus = lr.SiklusHasil()
    sl_id, tp_id = r._pasang_proteksi(VerdictPalsu(), 90.0, 110.0, siklus)

    assert sl_id is None
    assert tp_id == 77
    assert siklus.order_sl["mode"] == "sl_dipantau_perangkat_lunak"
    assert siklus.order_sl["sl_harga"] == 90.0
    assert r._proteksi_aman["BTCUSDT"] is prot


def test_mode_aman_gagal_dicatat_sebagai_galat(monkeypatch):
    def aman_palsu(**k):
        return {"tp": None, "sl_harga": None, "gagal": "TP ditolak -4120",
                "posisi_ditutup": True, "proteksi": None}

    monkeypatch.setattr(lr, "aman_aktif", lambda env=None: True)
    monkeypatch.setattr(lr, "pasang_proteksi_aman", aman_palsu)

    r = buat_runner()
    siklus = lr.SiklusHasil()
    sl_id, tp_id = r._pasang_proteksi(VerdictPalsu(), 90.0, 110.0, siklus)

    assert sl_id is None
    assert tp_id is None
    assert "proteksi_aman" in (siklus.galat or "")
    assert "-4120" in (siklus.galat or "")


def test_periksa_sl_aman_membersihkan_setelah_dieksekusi():
    class ProteksiPalsu:
        def __init__(self, aksi):
            self.aksi = aksi

        def periksa_sl(self):
            return {"aksi": self.aksi}

    r = buat_runner()
    r._proteksi_aman["AAA"] = ProteksiPalsu("aman")
    r._proteksi_aman["BBB"] = ProteksiPalsu("sl_dieksekusi")

    galat = r._periksa_sl_aman()

    assert galat == []
    assert "AAA" in r._proteksi_aman
    assert "BBB" not in r._proteksi_aman


def test_periksa_sl_aman_menangkap_galat():
    class ProteksiMeledak:
        def periksa_sl(self):
            raise RuntimeError("koneksi putus")

    r = buat_runner()
    r._proteksi_aman["AAA"] = ProteksiMeledak()

    galat = r._periksa_sl_aman()

    assert len(galat) == 1
    assert "periksa_sl_AAA" in galat[0]
    assert "AAA" in r._proteksi_aman
