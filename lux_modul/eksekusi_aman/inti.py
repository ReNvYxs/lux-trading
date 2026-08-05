"""MODUL BERSIH - gabungan lux-modul-trading-main + final (1).

Setiap keputusan punya bukti dari probe p00-p11 dan nomor buktinya ditulis di
komentar. Tidak ada bagian yang dimasukkan karena 'terlihat benar'.

Bukti pembentuk rancangan:
- p01/p04: ice_breaker.py mensyaratkan `await kirim(payload)` dan `harga()` TANPA
  argumen. main melanggar -> TypeError -> 0 order. Kontrak dibuat eksplisit dan
  diuji (KontrakEksekutor).
- p02/p03/p08: SEMUA tipe order kondisional (STOP, STOP_MARKET, TAKE_PROFIT,
  TAKE_PROFIT_MARKET, TRAILING_STOP_MARKET) ditolak -4120 di /fapi/v1/order,
  /fapi/v1/order/test DAN /fapi/v1/batchOrders, juga pada isolated margin dan
  hedge mode. TP/SL tidak boleh memakai tipe kondisional.
- p09: Algo API yang disarankan pesan -4120 TIDAK ADA di host testnet (rute palsu
  memberi respons identik dengan rute Algo). Saran itu tidak bisa diikuti.
- p08: LIMIT reduceOnly DI BAWAH pasar untuk LONG langsung FILLED sebagai taker
  (avgPrice = bid, posisi jadi 0); GTX post-only ditolak -5022. Jadi SL TIDAK
  BISA berupa order pasif di bursa. Yang bisa pasif hanya TP (di atas pasar).
- p09: LIMIT IOC dengan batas terlalu ketat EXPIRED dan posisi TIDAK tertutup.
  Eksekusi SL WAJIB punya fallback MARKET.
- p07: tanpa newClientOrderId, dua order identik dua-duanya diterima; dengan cid
  sama -> -4116. Retry hanya aman bila cid deterministik.
- p07: Binance otomatis membatalkan reduceOnly saat posisi habis.
- p07: order reduceOnly yang melebihi posisi di-clamp Binance.
- p05: notional = saldo x risiko% / jarakSL%. Leverage TIDAK mengubah notional,
  hanya initial margin dan jarak likuidasi (~100/leverage %).
- p09: jendela posisi telanjang terukur 538-625 ms; tidak bisa dihilangkan lewat
  REST, hanya diperkecil dan dijaga fail-safe.
- p10: galat -2013 saat MEMBACA STATUS order membuat posisi terisi tertinggal
  tanpa proteksi. Karena itu pembacaan status wajib tahan galat, dan setiap
  galat tak terduga setelah fill wajib memicu fail-safe (lihat jalankan_siklus).
"""
import hashlib
import math
import time

ARAH_LONG = "LONG"
ARAH_SHORT = "SHORT"

# Galat permanen: mengulang hanya menghasilkan galat yang sama. Semua terbukti
# nyata di p01-p10.
KODE_PERMANEN = {-1102, -1111, -4003, -4014, -4120, -2022, -5022, -1116, -1121}
KODE_CID_DUPLIKAT = -4116
KODE_ORDER_TIDAK_ADA = -2013  # p10: muncul saat query status terlalu dini


class GagalProteksi(Exception):
    """Proteksi gagal dipasang DAN posisi sudah ditutup sebagai fail-safe."""


class TolakUkuran(Exception):
    """Ukuran posisi melanggar aturan Binance atau kebijakan risiko."""


# =================================================================== #
# 1. SPESIFIKASI SIMBOL
# =================================================================== #
class SpekSimbol:
    def __init__(self, tick, step, min_qty, maks_qty, min_notional,
                 presisi_harga, presisi_qty):
        self.tick = tick
        self.step = step
        self.min_qty = min_qty
        self.maks_qty = maks_qty
        self.min_notional = min_notional
        self.presisi_harga = presisi_harga
        self.presisi_qty = presisi_qty

    @classmethod
    def dari_exchange_info(cls, info, simbol):
        for s in info.get("symbols", []):
            if s.get("symbol") != simbol:
                continue
            tick = step = min_qty = min_not = None
            maks_qty = float("inf")
            for f in s.get("filters", []):
                t = f.get("filterType")
                if t == "PRICE_FILTER":
                    tick = float(f["tickSize"])
                elif t == "LOT_SIZE":
                    step = float(f["stepSize"])
                    min_qty = float(f["minQty"])
                    maks_qty = min(maks_qty, float(f["maxQty"]))
                elif t == "MARKET_LOT_SIZE":
                    maks_qty = min(maks_qty, float(f["maxQty"]))
                elif t == "MIN_NOTIONAL":
                    min_not = float(f["notional"])
            if tick is None or step is None:
                raise TolakUkuran(f"filter tidak lengkap untuk {simbol}")
            return cls(tick, step, min_qty or step, maks_qty, min_not or 0.0,
                       int(s.get("pricePrecision", 2)),
                       int(s.get("quantityPrecision", 3)))
        raise TolakUkuran(f"simbol {simbol} tidak ada di exchangeInfo")

    # p07: lupa membulatkan ke tick -> -4014 / -1111.
    def bulat_harga(self, x):
        return round(round(float(x) / self.tick) * self.tick, self.presisi_harga)

    def turun_harga(self, x):
        return round(math.floor(float(x) / self.tick) * self.tick, self.presisi_harga)

    def naik_harga(self, x):
        return round(math.ceil(float(x) / self.tick) * self.tick, self.presisi_harga)

    # qty SELALU dibulatkan ke bawah supaya notional tidak melewati batas risiko.
    def turun_qty(self, x):
        return round(math.floor(float(x) / self.step) * self.step, self.presisi_qty)


# =================================================================== #
# 2. UKURAN POSISI
# =================================================================== #
class KebijakanRisiko:
    """porsi_notional_maks : notional maksimum sebagai kelipatan saldo (p05:
         tanpa batas ini, SL rapat membuat notional berkali-kali saldo).
       porsi_margin_maks   : initial margin maksimum sebagai fraksi saldo.
       faktor_aman_likuidasi: jarak likuidasi minimal = faktor x jarak SL (p05:
         jarak likuidasi ~ 100/leverage %, jadi leverage tinggi bisa membuat
         likuidasi lebih dekat daripada SL).
    """

    def __init__(self, risiko_per_trade=0.01, porsi_notional_maks=1.0,
                 porsi_margin_maks=0.10, min_margin_bebas=0.30,
                 faktor_aman_likuidasi=3.0, leverage_maks_bursa=125):
        self.risiko_per_trade = risiko_per_trade
        self.porsi_notional_maks = porsi_notional_maks
        self.porsi_margin_maks = porsi_margin_maks
        self.min_margin_bebas = min_margin_bebas
        self.faktor_aman_likuidasi = faktor_aman_likuidasi
        self.leverage_maks_bursa = leverage_maks_bursa


def hitung_ukuran(saldo, harga, sl_harga, arah, spek, kebijakan):
    """jarak SL -> notional risiko -> batas notional -> qty (bulat bawah) ->
    leverage dari kebutuhan margin, dibatasi jarak likuidasi. Semua angka
    perantara dikembalikan supaya bisa diaudit.
    """
    h = {"saldo": saldo, "harga": harga, "sl_harga": sl_harga, "arah": arah}
    if harga <= 0:
        raise TolakUkuran("harga tidak valid")
    if arah == ARAH_LONG and sl_harga >= harga:
        raise TolakUkuran("SL long harus di bawah harga")
    if arah == ARAH_SHORT and sl_harga <= harga:
        raise TolakUkuran("SL short harus di atas harga")
    jarak = abs(harga - sl_harga) / harga
    h["jarak_sl_pct"] = round(jarak * 100, 6)
    if jarak < 1e-6:
        raise TolakUkuran("jarak SL terlalu kecil")

    rugi_maks = saldo * kebijakan.risiko_per_trade
    notional_risiko = rugi_maks / jarak
    notional_batas = saldo * kebijakan.porsi_notional_maks
    notional = min(notional_risiko, notional_batas)
    h["rugi_maks_usdt"] = round(rugi_maks, 6)
    h["notional_dari_risiko"] = round(notional_risiko, 4)
    h["notional_batas_kebijakan"] = round(notional_batas, 4)
    h["notional_dibatasi"] = notional_risiko > notional_batas

    qty = spek.turun_qty(notional / harga)
    if qty > spek.maks_qty:
        qty = spek.turun_qty(spek.maks_qty)
        h["qty_dibatasi_maks"] = True
    if qty < spek.min_qty:
        raise TolakUkuran(f"qty {qty} < minQty {spek.min_qty}")
    notional = qty * harga
    if notional < spek.min_notional:
        raise TolakUkuran(
            f"notional {notional:.2f} < minNotional {spek.min_notional} - "
            f"saldo terlalu kecil untuk risiko {kebijakan.risiko_per_trade:.2%} "
            f"pada jarak SL {jarak*100:.2f}%")
    h["qty"] = qty
    h["notional"] = round(notional, 4)
    h["rugi_pada_sl_usdt"] = round(qty * abs(harga - sl_harga), 6)
    h["risiko_nyata_pct"] = round(h["rugi_pada_sl_usdt"] / saldo * 100, 6)
    # p10: saat notional dibatasi, risiko NYATA jadi LEBIH KECIL dari target.
    # Ini konsekuensi yang harus disadari, bukan bug - dilaporkan eksplisit.
    h["risiko_lebih_kecil_dari_target"] = (
        h["risiko_nyata_pct"] < kebijakan.risiko_per_trade * 100 * 0.95)

    margin_maks = saldo * kebijakan.porsi_margin_maks
    lev_min = max(1, math.ceil(notional / margin_maks)) if margin_maks > 0 else 1
    lev_maks_aman = min(math.floor(1.0 / (jarak * kebijakan.faktor_aman_likuidasi)),
                        kebijakan.leverage_maks_bursa)
    h["leverage_min_dari_margin"] = lev_min
    h["leverage_maks_dari_likuidasi"] = lev_maks_aman
    if lev_maks_aman < 1:
        raise TolakUkuran(
            f"jarak SL {jarak*100:.2f}% terlalu lebar untuk faktor aman "
            f"{kebijakan.faktor_aman_likuidasi}x")
    if lev_min > lev_maks_aman:
        notional_baru = margin_maks * lev_maks_aman
        qty = spek.turun_qty(notional_baru / harga)
        if qty < spek.min_qty or qty * harga < spek.min_notional:
            raise TolakUkuran(
                "tidak ada kombinasi aman: batas margin dan jarak likuidasi "
                "bertabrakan pada ukuran minimum bursa")
        notional = qty * harga
        h["konflik_leverage_diselesaikan_dengan_menurunkan_notional"] = True
        h["qty"] = qty
        h["notional"] = round(notional, 4)
        h["rugi_pada_sl_usdt"] = round(qty * abs(harga - sl_harga), 6)
        h["risiko_nyata_pct"] = round(h["rugi_pada_sl_usdt"] / saldo * 100, 6)
        leverage = lev_maks_aman
    else:
        leverage = lev_min
    h["leverage"] = leverage
    h["initial_margin"] = round(notional / leverage, 6)
    h["margin_pct_dari_saldo"] = round(notional / leverage / saldo * 100, 4)
    h["margin_bebas_pct"] = round(100 - h["margin_pct_dari_saldo"], 4)
    h["jarak_likuidasi_pct"] = round(100.0 / leverage, 4)
    h["rasio_likuidasi_terhadap_sl"] = round(
        h["jarak_likuidasi_pct"] / h["jarak_sl_pct"], 4)
    h["margin_bebas_memenuhi_kebijakan"] = (
        h["margin_bebas_pct"] >= kebijakan.min_margin_bebas * 100)
    h["likuidasi_lebih_jauh_dari_sl"] = h["jarak_likuidasi_pct"] > h["jarak_sl_pct"]
    return h


# =================================================================== #
# 3. PENGIRIM ORDER
# =================================================================== #
def buat_cid(niat, simbol, sisi, ember):
    """p07: TANPA cid deterministik, retry menggandakan posisi. DENGAN cid,
    percobaan kedua ditolak -4116 sehingga kita tahu yang pertama sudah sampai.
    """
    return "lx" + hashlib.sha1(
        f"{niat}|{simbol}|{sisi}|{ember}".encode()).hexdigest()[:20]


class PengirimOrder:
    def __init__(self, klien, log=None, jeda_awal=0.5, coba_maks=3, tidur=None):
        self.klien = klien
        self.log = log if log is not None else []
        self.jeda_awal = jeda_awal
        self.coba_maks = coba_maks
        self._tidur = tidur or time.sleep
        self.jumlah_permintaan = 0
        self.jumlah_retry = 0

    def _catat(self, peristiwa, **rinci):
        self.log.append({"t": time.time(), "peristiwa": peristiwa, **rinci})

    def cari_lewat_cid(self, simbol, cid):
        try:
            return self.klien._permintaan(
                "GET", "/fapi/v1/order",
                {"symbol": simbol, "origClientOrderId": cid}, signed=True)
        except Exception:
            return None

    def baca_status(self, simbol, order_id=None, cid=None, coba=4, jeda=0.35):
        """p10: query status terlalu dini bisa -2013 'Order does not exist' dan
        galat itu SEMPAT membuat posisi terisi tertinggal tanpa proteksi.
        Di sini -2013 diperlakukan sebagai 'belum terlihat', bukan fatal.
        """
        terakhir = None
        for i in range(coba):
            try:
                if order_id is not None:
                    return self.klien.status_order(simbol, order_id=order_id)
                if cid:
                    r = self.cari_lewat_cid(simbol, cid)
                    if r:
                        return r
                    raise RuntimeError("cid belum terlihat")
            except Exception as exc:
                terakhir = exc
                kode = getattr(exc, "kode", None)
                if kode is not None and kode != KODE_ORDER_TIDAK_ADA:
                    break
                if cid and order_id is not None:
                    r = self.cari_lewat_cid(simbol, cid)
                    if r:
                        return r
                self._tidur(jeda)
        self._catat("status_tidak_terbaca", order_id=order_id, cid=cid,
                    pesan=str(terakhir)[:140])
        return None

    def kirim(self, payload, niat, ember):
        payload = dict(payload)
        cid = buat_cid(niat, payload["symbol"], payload["side"], ember)
        payload["newClientOrderId"] = cid
        jeda = self.jeda_awal
        galat = None
        for percobaan in range(1, self.coba_maks + 1):
            try:
                self.jumlah_permintaan += 1
                order = self.klien.kirim_order(payload)
                self._catat("order_terkirim", niat=niat, cid=cid,
                            percobaan=percobaan, orderId=order.get("orderId"))
                return {"hasil": "OK", "order": order, "cid": cid,
                        "percobaan": percobaan}
            except Exception as exc:
                kode = getattr(exc, "kode", None)
                if kode == KODE_CID_DUPLIKAT:
                    ada = self.cari_lewat_cid(payload["symbol"], cid)
                    self._catat("idempoten_sudah_ada", niat=niat, cid=cid)
                    return {"hasil": "SUDAH_ADA", "order": ada, "cid": cid,
                            "percobaan": percobaan}
                if kode in KODE_PERMANEN:
                    self._catat("ditolak_permanen", niat=niat, cid=cid, kode=kode,
                                pesan=getattr(exc, "pesan", str(exc)))
                    return {"hasil": "DITOLAK_PERMANEN", "kode": kode,
                            "pesan": getattr(exc, "pesan", str(exc)), "cid": cid}
                # Galat ambigu: JANGAN kirim ulang buta, cek dulu lewat cid.
                ada = self.cari_lewat_cid(payload["symbol"], cid)
                if ada:
                    self._catat("pulih_lewat_cid", niat=niat, cid=cid)
                    return {"hasil": "PULIH_LEWAT_CID", "order": ada, "cid": cid,
                            "percobaan": percobaan}
                galat = exc
                if percobaan < self.coba_maks:
                    self.jumlah_retry += 1
                    self._catat("backoff", niat=niat, cid=cid, jeda=jeda,
                                kode=kode, pesan=str(exc)[:120])
                    self._tidur(jeda)
                    jeda *= 2  # eksponensial 0.5 -> 1 -> 2 detik
        self._catat("gagal_total", niat=niat, cid=cid, pesan=str(galat)[:160])
        return {"hasil": "GAGAL", "galat": str(galat), "cid": cid}


# =================================================================== #
# 4. DATA PASAR - cache di ATAS _permintaan, jadi cache hit = 0 permintaan
# =================================================================== #
class DataPasar:
    def __init__(self, klien, ttl_klines=3.0, ttl_harga=1.0):
        self.klien = klien
        self.ttl_klines = ttl_klines
        self.ttl_harga = ttl_harga
        self._cache = {}
        self.hit = 0
        self.miss = 0

    def _ambil(self, kunci, ttl, pengambil):
        sekarang = time.time()
        entri = self._cache.get(kunci)
        if entri and sekarang - entri[0] < ttl:
            self.hit += 1
            return entri[1]
        self.miss += 1
        nilai = pengambil()
        self._cache[kunci] = (sekarang, nilai)
        return nilai

    def klines(self, simbol, interval, limit=500):
        return self._ambil(
            ("kl", simbol, interval, limit), self.ttl_klines,
            lambda: self.klien._permintaan(
                "GET", "/fapi/v1/klines",
                {"symbol": simbol, "interval": interval, "limit": limit},
                signed=False))

    def mark(self, simbol):
        return self._ambil(("mk", simbol), self.ttl_harga,
                           lambda: float(self.klien._permintaan(
                               "GET", "/fapi/v1/premiumIndex", {"symbol": simbol},
                               signed=False).get("markPrice")))

    def bid_ask(self, simbol):
        return self._ambil(("ba", simbol), self.ttl_harga,
                           lambda: self.klien.bid_ask_terbaik(simbol))


# =================================================================== #
# 5. PROTEKSI - TP pasif di bursa, SL dieksekusi perangkat lunak
# =================================================================== #
class Proteksi:
    def __init__(self, klien, pengirim, spek, simbol, data=None, log=None,
                 toleransi_ioc=0.001, tidur=None):
        self.klien = klien
        self.pengirim = pengirim
        self.spek = spek
        self.simbol = simbol
        self.data = data
        self.log = log if log is not None else []
        self.toleransi_ioc = toleransi_ioc
        self._tidur = tidur or time.sleep
        self.order_tp = None
        self.sl_harga = None
        self.qty_dilindungi = 0.0

    def _catat(self, peristiwa, **rinci):
        self.log.append({"t": time.time(), "peristiwa": peristiwa, **rinci})

    # Kondisi NYATA dari Binance, bukan state lokal.
    def posisi_nyata(self):
        for p in self.klien.posisi(self.simbol):
            amt = float(p.get("positionAmt", 0) or 0)
            if abs(amt) > 0:
                return {"amt": amt, "arah": ARAH_LONG if amt > 0 else ARAH_SHORT,
                        "entry": float(p.get("entryPrice", 0) or 0)}
        return None

    def order_terbuka(self):
        return self.klien._permintaan("GET", "/fapi/v1/openOrders",
                                      {"symbol": self.simbol}, signed=True)

    def tutup_posisi(self, alasan, ember=None):
        """LIMIT IOC (batasi slippage) -> VERIFIKASI -> MARKET (jaminan).
        p09 membuktikan verifikasi + fallback ini wajib: IOC terlalu ketat
        EXPIRED dan posisi tetap terbuka.
        """
        pos = self.posisi_nyata()
        if not pos:
            return {"aksi": "tidak_ada_posisi", "bersih": True}
        ember = ember or f"tutup{int(time.time()*1000)}"
        sisi = "SELL" if pos["amt"] > 0 else "BUY"
        jejak = []
        try:
            ba = (self.data.bid_ask(self.simbol) if self.data
                  else self.klien.bid_ask_terbaik(self.simbol))
            acuan = ba["bid"] if sisi == "SELL" else ba["ask"]
            batas = (self.spek.turun_harga(acuan * (1 - self.toleransi_ioc))
                     if sisi == "SELL"
                     else self.spek.naik_harga(acuan * (1 + self.toleransi_ioc)))
            r = self.pengirim.kirim(
                {"symbol": self.simbol, "side": sisi, "type": "LIMIT",
                 "timeInForce": "IOC", "price": batas,
                 "quantity": abs(pos["amt"]), "reduceOnly": True},
                "tutupioc", ember)
            jejak.append({"langkah": "limit_ioc", "batas": batas,
                          "hasil": r.get("hasil"), "kode": r.get("kode")})
        except Exception as exc:
            jejak.append({"langkah": "limit_ioc", "galat": str(exc)[:140]})
        self._tidur(0.8)
        try:
            pos = self.posisi_nyata()
        except Exception:
            pos = None
            jejak.append({"langkah": "cek_posisi", "galat": "gagal_dibaca"})
        if pos:
            r = self.pengirim.kirim(
                {"symbol": self.simbol, "side": sisi, "type": "MARKET",
                 "quantity": abs(pos["amt"]), "reduceOnly": True},
                "tutupmkt", ember)
            jejak.append({"langkah": "fallback_market", "hasil": r.get("hasil"),
                          "kode": r.get("kode")})
            self._tidur(0.8)
        akhir = self.posisi_nyata()
        self._catat("posisi_ditutup", alasan=alasan, jejak=jejak,
                    bersih=akhir is None)
        return {"aksi": "ditutup", "alasan": alasan, "jejak": jejak,
                "posisi_setelah": akhir, "bersih": akhir is None}

    def batalkan_proteksi(self):
        try:
            self.klien.batalkan_semua_order(self.simbol)
        except Exception as exc:
            self._catat("gagal_batalkan", pesan=str(exc)[:140])
        self.order_tp = None

    def pasang(self, tp_harga, sl_harga, ember=None):
        """TP dipasang di bursa; SL dicatat untuk dipantau. Kalau TP tidak bisa
        dipasang atau tidak terlihat di bursa, posisi DITUTUP (fail-safe).
        Terbukti bekerja di p07 blok B.
        """
        pos = self.posisi_nyata()
        if not pos:
            raise GagalProteksi("tidak ada posisi untuk dilindungi")
        ember = ember or f"prot{int(time.time()*1000)}"
        qty = abs(pos["amt"])
        sisi = "SELL" if pos["amt"] > 0 else "BUY"
        # p08: TP di sisi yang salah tidak menunggu, tapi langsung tereksekusi.
        if pos["arah"] == ARAH_LONG and tp_harga <= pos["entry"]:
            raise GagalProteksi("TP long harus di atas entry")
        if pos["arah"] == ARAH_SHORT and tp_harga >= pos["entry"]:
            raise GagalProteksi("TP short harus di bawah entry")
        harga_tp = self.spek.bulat_harga(tp_harga)
        r = self.pengirim.kirim(
            {"symbol": self.simbol, "side": sisi, "type": "LIMIT",
             "timeInForce": "GTC", "price": harga_tp, "quantity": qty,
             "reduceOnly": True}, "tp", ember)
        if r["hasil"] not in ("OK", "SUDAH_ADA", "PULIH_LEWAT_CID"):
            t = self.tutup_posisi("tp_gagal_dipasang", ember)
            raise GagalProteksi(
                f"TP gagal ({r.get('kode')} {r.get('pesan') or r.get('galat')}), "
                f"posisi ditutup: bersih={t.get('bersih')}")
        self.order_tp = r.get("order") or {}
        self.sl_harga = self.spek.bulat_harga(sl_harga)
        self.qty_dilindungi = qty
        # Verifikasi TP benar-benar TERCATAT, bukan hanya respons OK.
        terlihat = any(
            str(o.get("orderId")) == str(self.order_tp.get("orderId"))
            for o in self.order_terbuka())
        self._catat("proteksi_terpasang", tp=harga_tp, sl=self.sl_harga, qty=qty,
                    terlihat_di_bursa=terlihat)
        if not terlihat:
            t = self.tutup_posisi("tp_tidak_terlihat_di_bursa", ember)
            raise GagalProteksi(
                f"TP tidak terlihat di openOrders, posisi ditutup: "
                f"bersih={t.get('bersih')}")
        return {"tp": self.order_tp, "tp_harga": harga_tp,
                "sl_harga": self.sl_harga, "qty": qty,
                "terlihat_di_bursa": terlihat}

    def periksa_sl(self, mark_harga=None):
        pos = self.posisi_nyata()
        if not pos or self.sl_harga is None:
            return {"aksi": "tidak_ada"}
        m = mark_harga if mark_harga is not None else (
            self.data.mark(self.simbol) if self.data
            else float(self.klien.harga_sekarang(self.simbol)))
        tersentuh = (m <= self.sl_harga if pos["arah"] == ARAH_LONG
                     else m >= self.sl_harga)
        if not tersentuh:
            return {"aksi": "aman", "mark": m, "sl": self.sl_harga}
        self._catat("sl_tersentuh", mark=m, sl=self.sl_harga)
        self.batalkan_proteksi()
        return {"aksi": "sl_dieksekusi", "mark": m, "sl": self.sl_harga,
                "penutupan": self.tutup_posisi("sl_tersentuh")}

    def rekonsiliasi(self):
        """p07: Binance otomatis membatalkan reduceOnly saat posisi habis, dan
        meng-clamp proteksi yang melebihi posisi -> perbandingan ukuran memakai
        toleransi setengah step.
        """
        pos = self.posisi_nyata()
        proteksi = [o for o in self.order_terbuka() if o.get("reduceOnly")]
        qty_prot = sum(float(o.get("origQty", 0) or 0) for o in proteksi)
        h = {"ada_posisi": pos is not None,
             "qty_posisi": abs(pos["amt"]) if pos else 0.0,
             "jumlah_proteksi": len(proteksi), "qty_proteksi": qty_prot,
             "sl_dipantau": self.sl_harga}
        if pos is None and proteksi:
            h["masalah"] = "orphan_proteksi"
        elif pos is not None and not proteksi:
            h["masalah"] = "posisi_tanpa_proteksi"
        elif pos is not None and abs(qty_prot - abs(pos["amt"])) > self.spek.step / 2:
            h["masalah"] = "ukuran_proteksi_tidak_cocok"
        elif pos is not None and self.sl_harga is None:
            h["masalah"] = "sl_tidak_dipantau"
        else:
            h["masalah"] = None
        return h

    def pulihkan_dari_bursa(self, sl_harga=None):
        """Setelah restart: state dibangun dari Binance, bukan dari disk."""
        pos = self.posisi_nyata()
        proteksi = [o for o in self.order_terbuka() if o.get("reduceOnly")]
        self.order_tp = proteksi[0] if proteksi else None
        self.qty_dilindungi = abs(pos["amt"]) if pos else 0.0
        if sl_harga is not None:
            self.sl_harga = self.spek.bulat_harga(sl_harga)
        self._catat("pulih_dari_bursa", ada_posisi=pos is not None,
                    jumlah_proteksi=len(proteksi))
        return {"posisi": pos, "proteksi": len(proteksi),
                "sl_dipantau": self.sl_harga}


# =================================================================== #
# 6. KONTRAK EKSEKUTOR - regression test untuk root cause #1
# =================================================================== #
class KontrakEksekutor:
    @staticmethod
    def verifikasi(kirim_fn, harga_fn):
        import inspect
        masalah = []
        if not inspect.iscoroutinefunction(kirim_fn):
            masalah.append("kirim harus coroutine (dipanggil dengan await)")
        try:
            n = len([p for p in inspect.signature(harga_fn).parameters.values()
                     if p.default is inspect.Parameter.empty
                     and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)])
            if n != 0:
                masalah.append(
                    f"harga harus dapat dipanggil tanpa argumen, butuh {n}")
        except (TypeError, ValueError):
            masalah.append("tanda tangan harga tidak dapat diperiksa")
        return masalah


# =================================================================== #
# 7. ENTRY
# =================================================================== #
class Entry:
    """p01: icebergQty/visible_qty DIABAIKAN Binance Futures, jadi slicing hanya
    menambah beban /ticker/price tanpa menyembunyikan apa pun -> slicing dihapus.
    """

    def __init__(self, klien, pengirim, spek, simbol, data=None, tidur=None):
        self.klien = klien
        self.pengirim = pengirim
        self.spek = spek
        self.simbol = simbol
        self.data = data
        self._tidur = tidur or time.sleep

    def qty_posisi(self):
        try:
            for p in self.klien.posisi(self.simbol):
                a = float(p.get("positionAmt", 0) or 0)
                if abs(a) > 0:
                    return abs(a)
        except Exception:
            pass
        return 0.0

    def kirim_entry(self, arah, qty, ember, agresivitas=0.003, tunggu=2.0):
        sisi = "BUY" if arah == ARAH_LONG else "SELL"
        ba = (self.data.bid_ask(self.simbol) if self.data
              else self.klien.bid_ask_terbaik(self.simbol))
        harga = (self.spek.naik_harga(ba["ask"] * (1 + agresivitas)) if sisi == "BUY"
                 else self.spek.turun_harga(ba["bid"] * (1 - agresivitas)))
        qty_minta = self.spek.turun_qty(qty)
        r = self.pengirim.kirim(
            {"symbol": self.simbol, "side": sisi, "type": "LIMIT",
             "timeInForce": "IOC", "price": harga, "quantity": qty_minta},
            "entry", ember)
        if r["hasil"] not in ("OK", "SUDAH_ADA", "PULIH_LEWAT_CID"):
            return {"terisi": 0.0, "hasil": r, "qty_minta": qty_minta}
        order = r.get("order") or {}
        oid = order.get("orderId")
        st = order
        batas = time.time() + tunggu
        while time.time() < batas:
            # p10: pembacaan status TIDAK boleh melempar galat ke pemanggil,
            # karena posisi mungkin sudah terisi dan butuh proteksi.
            baru = self.pengirim.baca_status(self.simbol, order_id=oid,
                                             cid=r.get("cid"), coba=2)
            if baru:
                st = baru
                if st.get("status") in ("FILLED", "EXPIRED", "CANCELED",
                                        "REJECTED"):
                    break
            self._tidur(0.25)
        # p01: qty_terisi TIDAK boleh diasumsikan sama dengan qty diminta.
        terisi = float(st.get("executedQty", 0) or 0)
        sumber = "executedQty"
        if terisi <= 0:
            # Fallback terakhir: baca posisi nyata. Lebih baik tahu ada posisi
            # daripada menganggap tidak terisi lalu meninggalkannya telanjang.
            dari_posisi = self.qty_posisi()
            if dari_posisi > 0:
                terisi, sumber = dari_posisi, "positionRisk"
        return {"terisi": terisi, "sumber_qty": sumber,
                "status": st.get("status"), "avgPrice": st.get("avgPrice"),
                "orderId": oid, "cid": r.get("cid"), "hasil": r["hasil"],
                "qty_minta": qty_minta,
                "parsial": 0 < terisi < qty_minta}


# =================================================================== #
# 8. SIKLUS LENGKAP - dengan jaminan tidak ada posisi telanjang
# =================================================================== #
def jalankan_siklus(klien, simbol, arah, sl_harga, tp_harga, kebijakan,
                    spek=None, data=None, log=None, tidur=None, saldo=None,
                    pengirim=None):
    """ukur -> entry -> verifikasi fill -> proteksi -> rekonsiliasi.

    Proteksi dipasang berdasarkan qty NYATA yang terisi, bukan qty diminta,
    sehingga partial fill tidak menghasilkan proteksi berukuran salah.

    JAMINAN (p10): setiap galat tak terduga SETELAH ada fill memicu penutupan
    fail-safe. Tanpa jaminan ini, galat -2013 pada pembacaan status sempat
    meninggalkan posisi 0.0261 BTC tanpa proteksi.
    """
    log = log if log is not None else []
    spek = spek or SpekSimbol.dari_exchange_info(klien.exchange_info(simbol), simbol)
    data = data or DataPasar(klien)
    pengirim = pengirim or PengirimOrder(klien, log=log, tidur=tidur)
    proteksi = Proteksi(klien, pengirim, spek, simbol, data=data, log=log,
                        tidur=tidur)
    h = {"simbol": simbol, "arah": arah, "log": log}
    saldo = saldo if saldo is not None else float(klien.saldo_usdt())
    harga = data.mark(simbol)
    h["ukuran"] = hitung_ukuran(saldo, harga, sl_harga, arah, spek, kebijakan)
    ember = f"{simbol}{arah}{int(time.time()*1000)}"
    h["ember"] = ember
    entry = Entry(klien, pengirim, spek, simbol, data=data, tidur=tidur)
    t0 = time.time()
    h["entry"] = entry.kirim_entry(arah, h["ukuran"]["qty"], ember)
    if h["entry"]["terisi"] <= 0:
        # Tetap periksa: mungkin fill datang terlambat.
        sisa = entry.qty_posisi()
        if sisa <= 0:
            h["kesimpulan"] = "tidak_terisi"
            h["rekonsiliasi"] = proteksi.rekonsiliasi()
            h["objek_proteksi"] = proteksi
            return h
        h["fill_terlambat_terdeteksi"] = sisa
    try:
        h["proteksi"] = proteksi.pasang(tp_harga, sl_harga, ember)
        h["ms_jendela_telanjang"] = round((time.time() - t0) * 1000, 1)
        h["kesimpulan"] = "terlindungi"
    except GagalProteksi as exc:
        h["proteksi_gagal"] = str(exc)
        h["kesimpulan"] = "gagal_dilindungi_posisi_ditutup"
    except Exception as exc:
        # JARING PENGAMAN TERAKHIR - inilah perbaikan dari kegagalan p10.
        h["galat_tak_terduga"] = f"{type(exc).__name__}: {exc}"
        try:
            h["failsafe"] = proteksi.tutup_posisi("galat_tak_terduga", ember)
            h["kesimpulan"] = "galat_tak_terduga_posisi_ditutup"
        except Exception as exc2:
            h["failsafe_gagal"] = f"{type(exc2).__name__}: {exc2}"
            h["kesimpulan"] = "BAHAYA_posisi_mungkin_telanjang"
    try:
        h["rekonsiliasi"] = proteksi.rekonsiliasi()
    except Exception as exc:
        h["rekonsiliasi"] = {"galat": str(exc)[:140]}
    h["objek_proteksi"] = proteksi
    return h
