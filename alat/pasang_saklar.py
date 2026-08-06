"""Pasang saklar LUX_EKSEKUSI di live_runner.py lewat penggantian berjangkar.

Gagal keras bila jangkar tidak muncul PERSIS satu kali. Lebih baik tidak
mengubah apa pun daripada mengubah tempat yang salah.
Idempoten: kalau sudah terpasang, tidak melakukan apa-apa.
"""
import json
import os
import sys

BERKAS = "lux_modul/live_runner.py"

JANGKAR_IMPOR = "from .eksekusi.spesifikasi import SpesifikasiKontrak\n"

GANTI_IMPOR = (
    "from .eksekusi.spesifikasi import SpesifikasiKontrak\n"
    "from .eksekusi_aman.saklar import aman_aktif, pasang_proteksi_aman\n"
)

JANGKAR_INIT = "        self._bracket_aktif: Dict[str, _BracketAktif] = {}\n"

GANTI_INIT = (
    "        self._bracket_aktif: Dict[str, _BracketAktif] = {}\n"
    "        self._proteksi_aman: Dict[str, Any] = {}\n"
)

JANGKAR_A = """        sl_order_id: Optional[int] = None
        tp_order_id: Optional[int] = None

        try:
            sl_p = payload_sl(
                simbol=self.simbol, arah=v.arah, stop_price=sl_price,
                tutup_posisi=True, kebijakan=self.kebijakan_order,
            )
            resp_sl = self.client.kirim_order(sl_p)
            siklus.order_sl = resp_sl
            sl_order_id = resp_sl.get("orderId")
        except Exception as exc:
            siklus.galat = f"order_sl: {exc}"

        if tp_price > 0:
            try:
                tp_p = payload_tp_market(
                    simbol=self.simbol, arah=v.arah, stop_price=tp_price,
                    kebijakan=self.kebijakan_order,
                )
                resp_tp = self.client.kirim_order(tp_p)
                siklus.order_tp = resp_tp
                tp_order_id = resp_tp.get("orderId")
            except Exception as exc:
                err = f"order_tp: {exc}"
                siklus.galat = (siklus.galat + "; " + err) if siklus.galat else err
"""

GANTI_A = "        sl_order_id, tp_order_id = self._pasang_proteksi(v, sl_price, tp_price, siklus)\n"

JANGKAR_B = """            try:
                sl_p = payload_sl(
                    ep.simbol, ep.arah, ep.sl_price,
                    tutup_posisi=True, kebijakan=self.kebijakan_order,
                )
                resp_sl = self.client.kirim_order(sl_p)
                sl_order_id = resp_sl.get("orderId")
            except Exception as exc:  # noqa: BLE001
                galat.append(f"kirim_sl_{oid}: {exc}")

            if ep.tp_price > 0:
                try:
                    tp_p = payload_tp_market(
                        ep.simbol, ep.arah, ep.tp_price,
                        kebijakan=self.kebijakan_order,
                    )
                    resp_tp = self.client.kirim_order(tp_p)
                    tp_order_id = resp_tp.get("orderId")
                except Exception as exc:  # noqa: BLE001
                    galat.append(f"kirim_tp_{oid}: {exc}")
"""

GANTI_B = "            sl_order_id, tp_order_id = self._pasang_proteksi_pending(ep, oid, galat)\n"

JANGKAR_C = """        if not self._bracket_aktif:
            return []
        galat: List[str] = []
        kini_ms = self._sekarang_ms()
        selesai: List[str] = []
"""

GANTI_C = """        galat_sl_aman = self._periksa_sl_aman()
        if not self._bracket_aktif:
            return galat_sl_aman
        galat: List[str] = list(galat_sl_aman)
        kini_ms = self._sekarang_ms()
        selesai: List[str] = []
"""

JANGKAR_M = "    def jalankan_selamanya(self, maks_siklus: Optional[int] = None) -> None:\n"

GANTI_M = """    # Saklar proteksi. Default jalur lama; LUX_EKSEKUSI=aman memakai lapisan
    # yang sudah divalidasi di testnet: TP LIMIT reduceOnly, SL dipantau
    # perangkat lunak, dan fail-safe menutup posisi bila proteksi gagal.
    def _pasang_proteksi(self, v, sl_price, tp_price, siklus):
        sl_order_id: Optional[int] = None
        tp_order_id: Optional[int] = None

        if aman_aktif():
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=self.simbol, arah=v.arah,
                tp_harga=tp_price, sl_harga=sl_price, tidur=self._tidur,
            )
            self._proteksi_aman[self.simbol] = hasil.get("proteksi")
            siklus.order_tp = hasil.get("tp")
            siklus.order_sl = {
                "mode": "sl_dipantau_perangkat_lunak",
                "sl_harga": hasil.get("sl_harga"),
            }
            tp_order_id = (hasil.get("tp") or {}).get("orderId")
            if hasil.get("gagal"):
                err = "proteksi_aman: " + str(hasil.get("gagal"))
                siklus.galat = (siklus.galat + "; " + err) if siklus.galat else err
            return sl_order_id, tp_order_id

        try:
            sl_p = payload_sl(
                simbol=self.simbol, arah=v.arah, stop_price=sl_price,
                tutup_posisi=True, kebijakan=self.kebijakan_order,
            )
            resp_sl = self.client.kirim_order(sl_p)
            siklus.order_sl = resp_sl
            sl_order_id = resp_sl.get("orderId")
        except Exception as exc:
            siklus.galat = f"order_sl: {exc}"

        if tp_price > 0:
            try:
                tp_p = payload_tp_market(
                    simbol=self.simbol, arah=v.arah, stop_price=tp_price,
                    kebijakan=self.kebijakan_order,
                )
                resp_tp = self.client.kirim_order(tp_p)
                siklus.order_tp = resp_tp
                tp_order_id = resp_tp.get("orderId")
            except Exception as exc:
                err = f"order_tp: {exc}"
                siklus.galat = (siklus.galat + "; " + err) if siklus.galat else err

        return sl_order_id, tp_order_id

    def _pasang_proteksi_pending(self, ep, oid, galat):
        sl_order_id: Optional[int] = None
        tp_order_id: Optional[int] = None

        if aman_aktif():
            hasil = pasang_proteksi_aman(
                klien=self.client, simbol=ep.simbol, arah=ep.arah,
                tp_harga=ep.tp_price, sl_harga=ep.sl_price, tidur=self._tidur,
            )
            self._proteksi_aman[ep.simbol] = hasil.get("proteksi")
            tp_order_id = (hasil.get("tp") or {}).get("orderId")
            if hasil.get("gagal"):
                galat.append("proteksi_aman_" + str(oid) + ": "
                             + str(hasil.get("gagal")))
            return sl_order_id, tp_order_id

        try:
            sl_p = payload_sl(
                ep.simbol, ep.arah, ep.sl_price,
                tutup_posisi=True, kebijakan=self.kebijakan_order,
            )
            resp_sl = self.client.kirim_order(sl_p)
            sl_order_id = resp_sl.get("orderId")
        except Exception as exc:  # noqa: BLE001
            galat.append(f"kirim_sl_{oid}: {exc}")

        if ep.tp_price > 0:
            try:
                tp_p = payload_tp_market(
                    ep.simbol, ep.arah, ep.tp_price,
                    kebijakan=self.kebijakan_order,
                )
                resp_tp = self.client.kirim_order(tp_p)
                tp_order_id = resp_tp.get("orderId")
            except Exception as exc:  # noqa: BLE001
                galat.append(f"kirim_tp_{oid}: {exc}")

        return sl_order_id, tp_order_id

    # SL pada jalur aman tidak ada di bursa, jadi harus dipantau tiap siklus.
    def _periksa_sl_aman(self) -> List[str]:
        galat: List[str] = []
        peta = getattr(self, "_proteksi_aman", None)
        if not peta:
            return galat
        for simbol, prot in list(peta.items()):
            if prot is None:
                peta.pop(simbol, None)
                continue
            try:
                h = prot.periksa_sl()
            except Exception as exc:  # noqa: BLE001
                galat.append("periksa_sl_" + str(simbol) + ": " + str(exc))
                continue
            if h.get("aksi") in ("sl_dieksekusi", "tidak_ada"):
                peta.pop(simbol, None)
                self._bracket_aktif.pop(simbol, None)
        return galat

    def jalankan_selamanya(self, maks_siklus: Optional[int] = None) -> None:
"""

PASANGAN = [
    ("impor", JANGKAR_IMPOR, GANTI_IMPOR),
    ("init", JANGKAR_INIT, GANTI_INIT),
    ("blok_a_entry_langsung", JANGKAR_A, GANTI_A),
    ("blok_b_entry_pending", JANGKAR_B, GANTI_B),
    ("blok_c_monitor", JANGKAR_C, GANTI_C),
    ("metode_baru", JANGKAR_M, GANTI_M),
]


def main():
    if not os.path.isfile(BERKAS):
        print("berkas_tidak_ada=" + BERKAS)
        return 2
    fh = open(BERKAS, "r", encoding="utf-8")
    isi = fh.read()
    fh.close()
    asli_panjang = len(isi)

    if "_pasang_proteksi" in isi:
        print("SAKLAR=SUDAH_TERPASANG")
        print("panjang=" + str(asli_panjang))
        return 0

    laporan = []
    for nama, jangkar, ganti in PASANGAN:
        n = isi.count(jangkar)
        laporan.append({"jangkar": nama, "jumlah": n})
        if n != 1:
            print("SAKLAR=GAGAL")
            print("jangkar_bermasalah=" + nama)
            print("jumlah=" + str(n))
            print("laporan=" + json.dumps(laporan))
            return 3

    for nama, jangkar, ganti in PASANGAN:
        isi = isi.replace(jangkar, ganti, 1)

    try:
        compile(isi, BERKAS, "exec")
    except SyntaxError as exc:
        print("SAKLAR=GAGAL")
        print("sintaks_rusak=" + repr(exc))
        return 4

    fh = open(BERKAS, "w", encoding="utf-8")
    fh.write(isi)
    fh.close()

    print("SAKLAR=TERPASANG")
    print("panjang_sebelum=" + str(asli_panjang))
    print("panjang_sesudah=" + str(len(isi)))
    print("laporan=" + json.dumps(laporan))
    print("punya_pasang_proteksi=" + str("_pasang_proteksi" in isi))
    print("punya_periksa_sl_aman=" + str("_periksa_sl_aman" in isi))
    return 0


if __name__ == "__main__":
    sys.exit(main())
