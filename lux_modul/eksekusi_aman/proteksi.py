"""Penjaga proteksi posisi - dirancang dari BUKTI, bukan dari dokumentasi.

Bukti yang membentuk desain ini (lihat hasil/p02 dan hasil/p03):
  - Semua tipe kondisional (STOP, STOP_MARKET, TAKE_PROFIT, TAKE_PROFIT_MARKET,
    TRAILING_STOP_MARKET) ditolak -4120 di POST /fapi/v1/order untuk akun ini,
    bahkan lewat endpoint validasi /order/test. Jadi TIDAK BISA mengandalkan
    stop order sisi-bursa di lingkungan ini.
  - LIMIT + reduceOnly DITERIMA, tetapi HANYA jika posisi sudah terbuka
    (tanpa posisi -> -2022). Jadi urutan wajib: fill dikonfirmasi -> pasang.
  - qty_terisi milik modul menghitung fill palsu (naik saat terkirim, bukan
    terisi). Jadi ukuran proteksi HARUS diambil dari positionRisk/executedQty.

Konsekuensi desain:
  TP  = LIMIT reduceOnly sisi-bursa (bertahan saat proses mati).
  SL  = stop yang dipantau perangkat lunak, karena bursa menolak stop order.
        Ini kelemahan yang jujur: kalau proses mati, SL tidak dijaga siapa pun.
        Karena itu wajib ada rekonsiliasi saat start dan aturan fail-safe.
  Fail-safe: gagal memasang proteksi => TUTUP posisi, jangan lanjut.
"""
import time


class GagalProteksi(Exception):
    pass


class PenjagaProteksi:
    def __init__(self, klien, simbol, tick, step, log=None):
        self.klien = klien
        self.simbol = simbol
        self.tick = tick
        self.step = step
        self.log = log if log is not None else []
        self.order_tp = None
        self.sl_harga = None
        self.qty_dilindungi = 0.0

    # ------------------------------------------------------------------ #
    def _catat(self, peristiwa, **rinci):
        self.log.append(dict(peristiwa=peristiwa, ts=time.time(), **rinci))

    def _bulat_tick(self, x):
        return round(round(x / self.tick) * self.tick, 8)

    def _bulat_step(self, q):
        return round(round(q / self.step) * self.step, 8)

    # ------------------------------------------------------------------ #
    def posisi_nyata(self):
        """SUMBER KEBENARAN: posisi menurut Binance, bukan state lokal."""
        for p in self.klien.posisi(self.simbol):
            amt = float(p.get("positionAmt", 0) or 0)
            if abs(amt) > 0:
                return {"qty": abs(amt), "arah": "LONG" if amt > 0 else "SHORT",
                        "entry": float(p.get("entryPrice") or 0),
                        "mark": float(p.get("markPrice") or 0)}
        return None

    def order_terbuka(self):
        return self.klien._permintaan(
            "GET", "/fapi/v1/openOrders", {"symbol": self.simbol}, signed=True)

    def tutup_posisi(self, alasan):
        """Penutupan darurat. MARKET reduceOnly = satu-satunya yang pasti jalan."""
        pos = self.posisi_nyata()
        if not pos:
            self._catat("tutup_dilewati_tidak_ada_posisi", alasan=alasan)
            return None
        sisi = "SELL" if pos["arah"] == "LONG" else "BUY"
        resp = self.klien.kirim_order({
            "symbol": self.simbol, "side": sisi, "type": "MARKET",
            "quantity": self._bulat_step(pos["qty"]), "reduceOnly": True})
        self._catat("posisi_ditutup", alasan=alasan, qty=pos["qty"],
                    order_id=resp.get("orderId"), status=resp.get("status"))
        return resp

    def batalkan_proteksi(self):
        try:
            self.klien.batalkan_semua_order(self.simbol)
            self._catat("proteksi_dibatalkan")
        except Exception as exc:
            self._catat("gagal_batalkan_proteksi", galat=str(exc))
        self.order_tp = None

    # ------------------------------------------------------------------ #
    def pasang(self, tp_harga, sl_harga, coba_maks=3):
        """Pasang proteksi SETELAH fill dikonfirmasi. Fail-safe kalau gagal.

        Retry memakai exponential backoff terkontrol (0.5s, 1s, 2s) - ini yang
        absen di kedua modul asli.
        """
        pos = self.posisi_nyata()
        if not pos:
            raise GagalProteksi("tidak ada posisi terbuka; proteksi tidak sah dipasang")

        self.qty_dilindungi = self._bulat_step(pos["qty"])
        self.sl_harga = self._bulat_tick(sl_harga)
        sisi_keluar = "SELL" if pos["arah"] == "LONG" else "BUY"
        payload = {"symbol": self.simbol, "side": sisi_keluar, "type": "LIMIT",
                   "timeInForce": "GTC", "price": self._bulat_tick(tp_harga),
                   "quantity": self.qty_dilindungi, "reduceOnly": True}

        galat_terakhir = None
        for percobaan in range(coba_maks):
            try:
                resp = self.klien.kirim_order(payload)
                self.order_tp = resp.get("orderId")
                self._catat("tp_terpasang", order_id=self.order_tp,
                            harga=payload["price"], qty=self.qty_dilindungi,
                            percobaan=percobaan + 1)
                return {"tp_order_id": self.order_tp, "sl_dipantau": self.sl_harga}
            except Exception as exc:
                galat_terakhir = exc
                jeda = 0.5 * (2 ** percobaan)
                self._catat("tp_gagal_backoff", percobaan=percobaan + 1,
                            jeda_detik=jeda, galat=str(exc))
                time.sleep(jeda)

        # FAIL-SAFE: proteksi tidak terpasang => posisi TIDAK BOLEH dibiarkan.
        self._catat("fail_safe_aktif", alasan="tp_gagal_setelah_retry",
                    galat=str(galat_terakhir))
        self.tutup_posisi("proteksi gagal terpasang")
        raise GagalProteksi(f"TP gagal terpasang, posisi ditutup: {galat_terakhir}")

    # ------------------------------------------------------------------ #
    def periksa_sl(self):
        """Pemantau SL perangkat lunak. Dipanggil tiap siklus."""
        pos = self.posisi_nyata()
        if not pos:
            return {"aksi": "tidak_ada_posisi"}
        if self.sl_harga is None:
            return {"aksi": "sl_tidak_diset"}
        mark = pos["mark"] or self.klien.harga_sekarang(self.simbol)
        tersentuh = (mark <= self.sl_harga) if pos["arah"] == "LONG" else (mark >= self.sl_harga)
        if not tersentuh:
            return {"aksi": "aman", "mark": mark, "sl": self.sl_harga}
        self._catat("sl_tersentuh", mark=mark, sl=self.sl_harga, arah=pos["arah"])
        # batalkan TP dulu supaya tidak jadi orphan setelah posisi tertutup
        self.batalkan_proteksi()
        self.tutup_posisi("SL tersentuh")
        return {"aksi": "sl_dieksekusi", "mark": mark, "sl": self.sl_harga}

    # ------------------------------------------------------------------ #
    def rekonsiliasi(self):
        """Dijalankan saat start/restart/reconnect. Menyamakan kenyataan Binance
        dengan state lokal, dan menutup celah orphan di kedua arah."""
        pos = self.posisi_nyata()
        order = self.order_terbuka()
        reduce_only = [o for o in order if o.get("reduceOnly")]
        laporan = {
            "posisi": pos,
            "jumlah_order_terbuka": len(order),
            "jumlah_proteksi_reduce_only": len(reduce_only),
        }
        if pos is None and reduce_only:
            # orphan TP/SL: proteksi menggantung tanpa posisi
            laporan["masalah"] = "orphan_proteksi"
            self.batalkan_proteksi()
            laporan["tindakan"] = "proteksi menggantung dibatalkan"
        elif pos is not None and not reduce_only:
            # posisi tanpa proteksi: kondisi paling berbahaya
            laporan["masalah"] = "posisi_tanpa_proteksi"
            laporan["tindakan"] = "perlu pasang ulang proteksi atau tutup posisi"
        elif pos is not None and reduce_only:
            qty_proteksi = sum(float(o.get("origQty", 0) or 0) for o in reduce_only)
            laporan["qty_posisi"] = pos["qty"]
            laporan["qty_proteksi"] = qty_proteksi
            if abs(qty_proteksi - pos["qty"]) > self.step / 2:
                laporan["masalah"] = "ukuran_proteksi_tidak_cocok"
                laporan["tindakan"] = "proteksi harus dipasang ulang sesuai qty nyata"
            else:
                laporan["masalah"] = None
        else:
            laporan["masalah"] = None
        self._catat("rekonsiliasi", **{k: v for k, v in laporan.items() if k != "posisi"})
        return laporan
