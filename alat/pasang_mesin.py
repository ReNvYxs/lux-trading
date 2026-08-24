"""Penambal berjangkar untuk lapisan REST (binance_client.py).

Sasaran, semuanya temuan audit 25 Agu 2026 yang dibuktikan dari sumber:

1. _permintaan TIDAK punya satu baris log pun. Ia adalah satu-satunya pintu
   keluar ke Binance, jadi instrumentasi di sini otomatis menutup SELURUH
   panggilan - termasuk yang memanggil _permintaan langsung seperti
   Proteksi.order_terbuka dan DataPasar.klines.

2. resp.read() yang kehabisan waktu melempar TimeoutError MENTAH. Blok except
   hanya menangkap HTTPError dan URLError, sehingga timeout baca lolos sebagai
   TimeoutError dan luput dari semua penanganan BinanceAPIError di lapisan atas.

3. Badan jawaban kosong dikembalikan sebagai {} tanpa catatan apa pun. Pada
   jalur order, {} berarti kita tidak tahu apa yang terjadi - dan {} itu sempat
   mengalir jauh sebagai 'sukses'.

4. TIDAK ADA jalur modify sama sekali. Satu-satunya cara mengubah order adalah
   batal lalu kirim baru, yang membuka jendela tanpa proteksi di antaranya.

5. TIDAK ADA pembaca openOrders bertipe di klien, padahal Proteksi memakainya
   lewat _permintaan mentah.

Aturan penambal: jangkar harus muncul PERSIS sejumlah yang dinyatakan, seluruh
jumlah dilaporkan lebih dulu, berkas dikompilasi sebelum ditulis, dan idempoten
lewat sentinel 'tanda'.
"""
import json
import os
import sys

KLIEN = "lux_modul/eksekusi/binance_client.py"

CARI_IMPOR = "from .kredensial import KredensialBinance\n"
GANTI_IMPOR = ("from .jejak import perekam\n"
               "from .kredensial import KredensialBinance\n")

CARI_JALUR = '_PATH_ALL_OPEN_ORDERS = "/fapi/v1/allOpenOrders"\n'
GANTI_JALUR = ('_PATH_ALL_OPEN_ORDERS = "/fapi/v1/allOpenOrders"\n'
               '_PATH_OPEN_ORDERS = "/fapi/v1/openOrders"\n')

CARI_MULAI = """        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
"""
GANTI_MULAI = """        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # Satu korelasi dipakai baris permintaan, jawaban, dan galat, supaya
        # satu order bermasalah bisa ditarik utuh dengan satu grep.
        _jj = perekam()
        _kor = _jj.catat_permintaan(method, path, params, signed,
                                   bobot=bobot_permintaan(path, params))
        _t0 = time.monotonic()
        try:
"""

CARI_HTTP = """            self._catat_pembatasan(status, payload)
            raise BinanceAPIError(
                status=status,
"""
GANTI_HTTP = """            self._catat_pembatasan(status, payload)
            _jj.catat_galat(_kor, method, path, status=status,
                            kode=payload.get("code"),
                            pesan=payload.get("msg", str(exc)), jawaban=payload,
                            ms=(time.monotonic() - _t0) * 1000.0,
                            parameter=params)
            raise BinanceAPIError(
                status=status,
"""

CARI_URL = """        except urllib.error.URLError as exc:
            raise BinanceAPIError(status=None, kode=None, pesan=f"jaringan gagal: {exc}") from exc
"""
GANTI_URL = """        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # TimeoutError dan OSError sengaja ikut ditangkap. resp.read() yang
            # kehabisan waktu melempar TimeoutError MENTAH, bukan URLError,
            # sehingga dulu ia lolos dari seluruh penanganan BinanceAPIError.
            # HTTPError sudah ditangani di blok sebelumnya, jadi tidak tertelan.
            _jj.catat_galat(_kor, method, path, status=None, kode=None,
                            pesan="jaringan gagal: " + str(exc),
                            ms=(time.monotonic() - _t0) * 1000.0,
                            parameter=params)
            raise BinanceAPIError(status=None, kode=None, pesan=f"jaringan gagal: {exc}") from exc
"""

CARI_EKOR = """        if not mentah:
            return {}
        try:
            hasil = json.loads(mentah.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BinanceAPIError(status, None, f"respons bukan JSON sah: {exc}") from exc
        if isinstance(hasil, dict) and "code" in hasil and "msg" in hasil and status >= 400:
            self._catat_pembatasan(status, hasil)
            raise BinanceAPIError(status, hasil.get("code"), hasil.get("msg", ""), hasil)
        return hasil
"""
GANTI_EKOR = """        _ms = (time.monotonic() - _t0) * 1000.0
        if not mentah:
            # Badan jawaban kosong. Pada jalur dana ini BUKAN sukses: kita tidak
            # tahu apa yang terjadi pada order. Ditandai eksplisit supaya
            # lapisan atas merekonsiliasi, bukan meneruskannya sebagai hasil.
            _jj.catat_jawaban(_kor, method, path, status=status, jawaban={},
                              ms=_ms, konteks={"badan_kosong": True})
            return {}
        try:
            hasil = json.loads(mentah.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # Cuplikan mentah dicatat: tanpa itu, jawaban rusak dari proxy atau
            # halaman galat HTML tidak bisa dibedakan dari galat Binance.
            _jj.catat_galat(_kor, method, path, status=status, kode=None,
                            pesan="respons bukan JSON sah: " + str(exc),
                            ms=_ms, parameter=params,
                            konteks={"mentah": mentah[:400].decode("utf-8", "replace")})
            raise BinanceAPIError(status, None, f"respons bukan JSON sah: {exc}") from exc
        if isinstance(hasil, dict) and "code" in hasil and "msg" in hasil and status >= 400:
            self._catat_pembatasan(status, hasil)
            _jj.catat_galat(_kor, method, path, status=status,
                            kode=hasil.get("code"), pesan=hasil.get("msg", ""),
                            jawaban=hasil, ms=_ms, parameter=params)
            raise BinanceAPIError(status, hasil.get("code"), hasil.get("msg", ""), hasil)
        _jj.catat_jawaban(_kor, method, path, status=status, jawaban=hasil, ms=_ms)
        return hasil
"""

CARI_METODE = """    def batalkan_semua_order(self, simbol: str) -> Dict[str, Any]:
        return self._permintaan("DELETE", _PATH_ALL_OPEN_ORDERS, {"symbol": simbol}, signed=True)
"""
GANTI_METODE = """    def batalkan_semua_order(self, simbol: str) -> Dict[str, Any]:
        return self._permintaan("DELETE", _PATH_ALL_OPEN_ORDERS, {"symbol": simbol}, signed=True)

    def order_terbuka(self, simbol: Optional[str] = None) -> List[Dict[str, Any]]:
        # Pembaca openOrders bertipe. Sebelum ini Proteksi memanggil
        # _permintaan mentah, sehingga tidak ada satu tempat pun yang bisa
        # diuji atau dibatasi. Catatan bobot: 1 dengan simbol, 40 tanpa simbol,
        # jadi JANGAN dipanggil tanpa simbol di dalam loop per pair.
        params = {"symbol": simbol} if simbol else {}
        hasil = self._permintaan("GET", _PATH_OPEN_ORDERS, params, signed=True)
        if isinstance(hasil, list):
            return hasil
        return [hasil] if hasil else []

    def ubah_order(
        self,
        simbol: str,
        sisi: str,
        quantity: Any,
        price: Any,
        order_id: Optional[int] = None,
        orig_client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        # Amend order LIMIT lewat PUT /fapi/v1/order.
        #
        # Sebelum ini TIDAK ADA jalur modify di seluruh modul: satu-satunya
        # cara mengubah order adalah batal lalu kirim baru, dan itu membuka
        # jendela tanpa proteksi di antara keduanya.
        #
        # Menurut dokumentasi Binance USD-M, symbol, side, quantity, dan price
        # semuanya wajib, ditambah salah satu dari orderId atau
        # origClientOrderId. Keempatnya diwajibkan di sini dan TIDAK ditebak;
        # perilaku nyatanya diverifikasi di uji hidup testnet.
        if order_id is None and not orig_client_order_id:
            raise ValueError("ubah_order butuh order_id atau orig_client_order_id")
        if quantity is None or price is None:
            raise ValueError("ubah_order butuh quantity DAN price (keduanya wajib)")
        params: Dict[str, Any] = {
            "symbol": simbol,
            "side": str(sisi).upper(),
            "quantity": quantity,
            "price": price,
        }
        if order_id is not None:
            params["orderId"] = int(order_id)
        if orig_client_order_id:
            params["origClientOrderId"] = orig_client_order_id
        return self._permintaan("PUT", _PATH_ORDER, params, signed=True)
"""

TAMBALAN = [
    {"nama": "klien_impor_jejak", "berkas": KLIEN, "cari": CARI_IMPOR,
     "ganti": GANTI_IMPOR, "jumlah": 1, "tanda": "from .jejak import perekam"},
    {"nama": "klien_jalur_open_orders", "berkas": KLIEN, "cari": CARI_JALUR,
     "ganti": GANTI_JALUR, "jumlah": 1, "tanda": "_PATH_OPEN_ORDERS = "},
    {"nama": "permintaan_mulai", "berkas": KLIEN, "cari": CARI_MULAI,
     "ganti": GANTI_MULAI, "jumlah": 1,
     "tanda": "_kor = _jj.catat_permintaan("},
    {"nama": "permintaan_galat_http", "berkas": KLIEN, "cari": CARI_HTTP,
     "ganti": GANTI_HTTP, "jumlah": 1,
     "tanda": "_jj.catat_galat(_kor, method, path, status=status,\n                            kode=payload.get"},
    {"nama": "permintaan_galat_jaringan", "berkas": KLIEN, "cari": CARI_URL,
     "ganti": GANTI_URL, "jumlah": 1,
     "tanda": "except (urllib.error.URLError, TimeoutError, OSError) as exc:"},
    {"nama": "permintaan_ekor", "berkas": KLIEN, "cari": CARI_EKOR,
     "ganti": GANTI_EKOR, "jumlah": 1,
     "tanda": "_jj.catat_jawaban(_kor, method, path, status=status, jawaban=hasil"},
    {"nama": "klien_modify_dan_open_orders", "berkas": KLIEN,
     "cari": CARI_METODE, "ganti": GANTI_METODE, "jumlah": 1,
     "tanda": "def ubah_order("},
]


def main():
    isi = {}
    hilang = []
    for t in TAMBALAN:
        b = t["berkas"]
        if b in isi:
            continue
        if not os.path.isfile(b):
            hilang.append(b)
            continue
        fh = open(b, "r", encoding="utf-8")
        isi[b] = fh.read()
        fh.close()
    if hilang:
        print("MESIN=GAGAL")
        print("berkas_hilang=" + json.dumps(sorted(set(hilang))))
        return 2

    laporan = []
    bermasalah = []
    for t in TAMBALAN:
        teks = isi[t["berkas"]]
        sudah = t["tanda"] in teks
        n = teks.count(t["cari"])
        laporan.append({"nama": t["nama"], "jumlah": n,
                        "diharap": t["jumlah"], "sudah": sudah})
        if not sudah and n != t["jumlah"]:
            bermasalah.append(t["nama"])
    for r in laporan:
        print("jangkar=" + json.dumps(r, ensure_ascii=False))
    if bermasalah:
        print("MESIN=GAGAL")
        print("jangkar_bermasalah=" + json.dumps(bermasalah))
        return 3

    diterapkan = []
    for t in TAMBALAN:
        teks = isi[t["berkas"]]
        if t["tanda"] in teks:
            continue
        isi[t["berkas"]] = teks.replace(t["cari"], t["ganti"], t["jumlah"])
        diterapkan.append(t["nama"])

    for b in sorted(isi):
        try:
            compile(isi[b], b, "exec")
        except SyntaxError as exc:
            print("MESIN=GAGAL")
            print("sintaks_rusak=" + b + " " + repr(exc))
            return 4
    for b in sorted(isi):
        fh = open(b, "w", encoding="utf-8")
        fh.write(isi[b])
        fh.close()

    teks = isi[KLIEN]
    print("MESIN=SELESAI")
    print("diterapkan=" + json.dumps(diterapkan))
    print("panjang_klien=" + str(len(teks)))
    print("punya_ubah_order=" + str("def ubah_order(" in teks))
    print("punya_order_terbuka=" + str("def order_terbuka(" in teks))
    print("jumlah_catat_permintaan=" + str(teks.count("catat_permintaan(")))
    print("jumlah_catat_jawaban=" + str(teks.count("catat_jawaban(")))
    print("jumlah_catat_galat=" + str(teks.count("catat_galat(")))
    print("tangkap_timeout=" + str("TimeoutError, OSError" in teks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
