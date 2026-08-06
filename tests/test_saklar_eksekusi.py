"""Tes saklar LUX_EKSEKUSI dan jalur proteksi aman.

Yang dibuktikan di sini adalah syarat penyelesaian dari pengguna:
  - TP benar-benar dikirim sebagai order yang DITERIMA Binance (LIMIT
    reduceOnly), bukan tipe kondisional yang terbukti ditolak -4120.
  - Tidak ada kondisi posisi terbuka tanpa proteksi: kalau TP ditolak
    permanen, posisi ditutup.
  - Harga TP/SL yang tidak wajar TIDAK dikirim, karena bursa terbukti tidak
    menolaknya sendiri.
"""
from lux_modul.eksekusi_aman.saklar import (
    MODE_AMAN,
    MODE_LAMA,
    MODE_OTOMATIS,
    aman_aktif,
    batas_jarak,
    mode_eksekusi,
    pasang_proteksi_aman,
    periksa_kewajaran,
)


class GalatPalsu(Exception):
    def __init__(self, kode, pesan="ditolak"):
        super().__init__(pesan)
        self.kode = kode
        self.pesan = pesan


class KlienPalsu:
    def __init__(self, tolak_tp_kode=None, harga=100.0):
        self.tolak_tp_kode = tolak_tp_kode
        self.harga = harga
        self.terkirim = []
        self.qty = 0.01
        self.order_terbuka_ = []
        self._id = 1000

    def exchange_info(self, simbol=None, ttl_detik=3600.0):
        return {"symbols": [{
            "symbol": "BTCUSDT", "pricePrecision": 2, "quantityPrecision": 3,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001",
                 "minQty": "0.001", "maxQty": "1000"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ]}]}

    def posisi(self, simbol=None):
        if self.qty <= 0:
            return []
        return [{"symbol": "BTCUSDT", "positionAmt": str(self.qty),
                 "entryPrice": "100.0", "markPrice": "100.0"}]

    def kirim_order(self, payload):
        self.terkirim.append(dict(payload))
        tipe = payload.get("type")
        tif = payload.get("timeInForce")
        if tipe == "LIMIT" and tif == "GTC" and self.tolak_tp_kode:
            raise GalatPalsu(self.tolak_tp_kode)
        self._id += 1
        oid = self._id
        if tipe == "MARKET":
            self.qty = 0.0
        if tipe == "LIMIT" and tif == "GTC" and payload.get("reduceOnly"):
            self.order_terbuka_.append({
                "orderId": oid, "reduceOnly": True,
                "origQty": payload["quantity"]})
        return {"orderId": oid, "status": "NEW", "executedQty": "0"}

    def _permintaan(self, method, path, params=None, signed=False):
        if path.endswith("openOrders"):
            return list(self.order_terbuka_)
        return {}

    def batalkan_semua_order(self, simbol):
        self.order_terbuka_ = []
        return {}

    def bid_ask_terbaik(self, simbol):
        return {"bid": self.harga - 0.1, "ask": self.harga + 0.1}

    def harga_sekarang(self, simbol):
        return self.harga

    def status_order(self, simbol, order_id=None, orig_client_order_id=None):
        return {"orderId": order_id, "status": "NEW"}

    def saldo_usdt(self):
        return 1000.0


def diam(_detik):
    return None


def test_default_otomatis():
    assert mode_eksekusi({}) == MODE_OTOMATIS


def test_env_lama():
    assert mode_eksekusi({"LUX_EKSEKUSI": "lama"}) == MODE_LAMA
    assert aman_aktif({"LUX_EKSEKUSI": "LAMA"}) is False


def test_env_aman():
    assert mode_eksekusi({"LUX_EKSEKUSI": "aman"}) == MODE_AMAN
    assert aman_aktif({"LUX_EKSEKUSI": "AMAN"}) is True


def test_nilai_asing_jatuh_ke_otomatis():
    assert mode_eksekusi({"LUX_EKSEKUSI": "ngawur"}) == MODE_OTOMATIS
    assert mode_eksekusi({"LUX_EKSEKUSI": ""}) == MODE_OTOMATIS


def test_otomatis_tanpa_klien_fail_closed():
    # Tanpa klien, mode otomatis tidak bisa membuktikan apa pun. Satu-satunya
    # jalur yang tidak pernah meninggalkan posisi telanjang adalah 'aman'.
    assert aman_aktif({}) is True


def test_tp_dipasang_sebagai_limit_reduce_only():
    k = KlienPalsu()
    h = pasang_proteksi_aman(k, "BTCUSDT", "LONG", 110.0, 90.0, tidur=diam)
    assert h["gagal"] is None
    tp = [p for p in k.terkirim
          if p.get("type") == "LIMIT" and p.get("timeInForce") == "GTC"]
    assert len(tp) == 1
    assert tp[0]["reduceOnly"] is True
    assert tp[0]["side"] == "SELL"
    assert h["terlihat_di_bursa"] is True
    assert h["sl_harga"] == 90.0


def test_tidak_pernah_memakai_tipe_kondisional():
    k = KlienPalsu()
    pasang_proteksi_aman(k, "BTCUSDT", "LONG", 110.0, 90.0, tidur=diam)
    terlarang = [p for p in k.terkirim
                 if "STOP" in str(p.get("type"))
                 or "TAKE_PROFIT" in str(p.get("type"))]
    assert terlarang == []


def test_tp_ditolak_permanen_menutup_posisi():
    k = KlienPalsu(tolak_tp_kode=-4120)
    h = pasang_proteksi_aman(k, "BTCUSDT", "LONG", 110.0, 90.0, tidur=diam)
    assert h["gagal"]
    assert h.get("posisi_ditutup") is True
    assert k.qty == 0.0
    market = [p for p in k.terkirim
              if p.get("type") == "MARKET" and p.get("reduceOnly")]
    assert market


def test_kewajaran_menerima_harga_wajar():
    assert periksa_kewajaran("LONG", 100.0, 110.0, 90.0) == []
    assert periksa_kewajaran("SHORT", 100.0, 90.0, 110.0) == []


def test_kewajaran_menolak_sisi_salah():
    masalah = periksa_kewajaran("LONG", 100.0, 95.0, 105.0)
    assert "tp_di_sisi_salah" in masalah
    assert "sl_di_sisi_salah" in masalah


def test_kewajaran_menolak_terlalu_jauh():
    # TP 10x harga pasar: bursa TERBUKTI menerimanya (maxPrice BTCUSDT
    # 809484.0, sekitar 12.5x). Jaring pengaman harus ada di sisi kita.
    masalah = periksa_kewajaran("LONG", 100.0, 1000.0, 90.0)
    assert masalah == ["tp_terlalu_jauh"]


def test_batas_jarak_dari_env():
    assert batas_jarak({}) == 0.5
    assert batas_jarak({"LUX_BATAS_JARAK_PROTEKSI": "0.2"}) == 0.2
    assert batas_jarak({"LUX_BATAS_JARAK_PROTEKSI": "ngawur"}) == 0.5
    assert batas_jarak({"LUX_BATAS_JARAK_PROTEKSI": "-1"}) == 0.5


def test_harga_tidak_wajar_menutup_posisi():
    k = KlienPalsu()
    h = pasang_proteksi_aman(k, "BTCUSDT", "LONG", 1000.0, 90.0, tidur=diam)
    assert h["gagal"]
    assert "tp_terlalu_jauh" in h["kewajaran"]
    assert k.qty == 0.0
    tp = [p for p in k.terkirim
          if p.get("type") == "LIMIT" and p.get("timeInForce") == "GTC"]
    assert tp == []
