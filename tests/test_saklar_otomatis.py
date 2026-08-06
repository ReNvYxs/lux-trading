"""Tes mode 'otomatis': bursa ditanya sekali, lalu jalur dipilih.

Latar bukti. 6 Agu 2026 di Binance Futures Testnet, STOP_MARKET dan
TAKE_PROFIT_MARKET dua-duanya dijawab -4120. Perilaku mainnet belum pernah
diverifikasi. Menebak salah satu arah sama-sama berbahaya:
  - menebak 'lama' di bursa yang menolak -> posisi berjalan telanjang;
  - menebak 'aman' di bursa yang menerima -> SL sisi bursa yang tahan mati
    proses dibuang tanpa alasan.
Karena itu keputusan diambil dari jawaban bursa, dan berkas ini mengunci
aturan penafsiran jawaban itu.
"""
import pytest

from lux_modul.eksekusi_aman import saklar as sk


class GalatBursa(Exception):
    def __init__(self, kode, pesan="ditolak"):
        super().__init__(pesan)
        self.kode = kode


class KlienProbe:
    """Klien minimal yang cukup untuk probe: info bursa, harga, permintaan."""

    def __init__(self, galat=None, harga=100.0):
        self.galat = galat
        self.harga = harga
        self.permintaan = []

    def exchange_info(self, simbol=None, ttl_detik=3600.0):
        return {"symbols": [{
            "symbol": "BTCUSDT", "pricePrecision": 2, "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ]}]}

    def harga_sekarang(self, simbol):
        return self.harga

    def _permintaan(self, method, path, params=None, signed=False):
        self.permintaan.append((method, path, dict(params or {})))
        if self.galat is not None:
            raise self.galat
        return {}


class KlienHaram:
    """Kalau probe dipanggil padahal tidak boleh, tes harus gagal keras."""

    def exchange_info(self, simbol=None, ttl_detik=3600.0):
        raise AssertionError("probe tidak boleh jalan di mode eksplisit")

    def harga_sekarang(self, simbol):
        raise AssertionError("probe tidak boleh jalan di mode eksplisit")

    def _permintaan(self, method, path, params=None, signed=False):
        raise AssertionError("probe tidak boleh jalan di mode eksplisit")


@pytest.fixture(autouse=True)
def cache_bersih():
    sk.bersihkan_cache_probe()
    yield
    sk.bersihkan_cache_probe()


def test_probe_diterima_pilih_lama():
    k = KlienProbe()
    h = sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert h["didukung"] is True
    assert sk.mode_efektif(k, "BTCUSDT", {}) == sk.MODE_LAMA
    assert sk.aman_aktif_untuk(k, "BTCUSDT", {}) is False


def test_probe_4120_pilih_aman():
    k = KlienProbe(galat=GalatBursa(-4120, "Order type not supported"))
    h = sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert h["didukung"] is False
    assert h["kode"] == -4120
    assert sk.mode_efektif(k, "BTCUSDT", {}) == sk.MODE_AMAN


def test_probe_kode_bursa_lain_berarti_tipe_dikenal():
    # -2022 ReduceOnly rejected: bursa MENJAWAB, dan yang ditolak bukan
    # tipenya. Artinya STOP_MARKET dikenal endpoint ini.
    k = KlienProbe(galat=GalatBursa(-2022, "ReduceOnly Order is rejected"))
    h = sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert h["didukung"] is True
    assert sk.mode_efektif(k, "BTCUSDT", {}) == sk.MODE_LAMA


def test_probe_galat_bukan_bursa_fail_closed():
    k = KlienProbe(galat=OSError("koneksi putus"))
    h = sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert h["didukung"] is None
    assert h["kode"] is None
    # Tidak bisa disimpulkan -> jalur yang tidak pernah meninggalkan posisi
    # telanjang.
    assert sk.mode_efektif(k, "BTCUSDT", {}) == sk.MODE_AMAN


def test_hasil_pasti_dicache_probe_tidak_diulang():
    k = KlienProbe()
    sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert len(k.permintaan) == 1
    for _ in range(5):
        sk.mode_efektif(k, "BTCUSDT", {})
    assert len(k.permintaan) == 1
    assert sk.deteksi_dukungan_stop(k, "BTCUSDT")["sumber"] == "cache"


def test_hasil_tak_pasti_tidak_dicache_tetapi_dijeda():
    k = KlienProbe(galat=OSError("koneksi putus"))
    sk.deteksi_dukungan_stop(k, "BTCUSDT")
    assert len(k.permintaan) == 1
    kedua = sk.deteksi_dukungan_stop(k, "BTCUSDT")
    # Dijeda supaya kegagalan jaringan tidak berubah jadi badai request.
    assert kedua["sumber"] == "jeda"
    assert len(k.permintaan) == 1


def test_mode_eksplisit_tidak_memanggil_probe():
    k = KlienHaram()
    assert sk.mode_efektif(k, "BTCUSDT", {"LUX_EKSEKUSI": "lama"}) == sk.MODE_LAMA
    assert sk.mode_efektif(k, "BTCUSDT", {"LUX_EKSEKUSI": "aman"}) == sk.MODE_AMAN


def test_payload_probe_aman_dan_tanpa_order_nyata():
    k = KlienProbe(harga=64536.4)
    sk.deteksi_dukungan_stop(k, "BTCUSDT")
    metode, jalur, params = k.permintaan[0]
    assert metode == "POST"
    assert jalur.endswith("/order/test")
    assert params["type"] == "STOP_MARKET"
    assert params["side"] == "SELL"
    assert params["closePosition"] == "true"
    assert "quantity" not in params
    # Stop SELL harus JAUH DI BAWAH pasar, kalau tidak bursa menjawab -2021
    # 'would immediately trigger' dan jawaban itu mengaburkan pertanyaan.
    assert 0 < params["stopPrice"] < k.harga * 0.9
