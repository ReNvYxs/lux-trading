"""L4 - Klien REST Binance USD-M Futures (testnet & live berbagi kode ini).

SATU implementasi dipakai untuk kedua mode: base_url dan kredensial datang dari
`KredensialBinance` (lihat kredensial.py), sehingga tidak ada cabang kode
"if testnet ... else ..." yang bisa salah ketik dan tidak sengaja memanggil
endpoint yang salah. Perbedaan testnet vs live HANYA pada base_url + kredensial,
tidak pernah pada logika request.

PERINGATAN JUJUR (wajib dibaca sebelum dipakai sungguhan):
    Sandbox tempat kode ini ditulis TIDAK memiliki akses jaringan keluar, sehingga
    modul ini TIDAK PERNAH diuji terhadap server Binance sungguhan (testnet maupun
    live) dari dalam sandbox. Pengujian di sini hanya unit test berbasis mock
    (lihat tests/test_binance_client.py). Sebelum dipakai untuk order sungguhan,
    operator WAJIB menguji sendiri terhadap Binance Futures Testnet di lingkungan
    yang punya akses internet, dan memverifikasi setiap endpoint (waktu server,
    exchangeInfo, order, posisi, leverage) merespons sebagaimana mestinya.

Kebijakan order (order.py) tetap berlaku di sini: klien ini hanya mengirim
payload yang sudah lolos `pastikan_tanpa_market()`; ia tidak menegakkan ulang
aturan itu (tanggung jawab pemanggil), tapi juga tidak menambah jalan pintas
untuk melewatinya.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Optional, Tuple

from .jejak import perekam
from .kredensial import KredensialBinance

RECV_WINDOW_DEFAULT = 5000
MAKS_DESIMAL = 8  # batas presisi Binance USD-M Futures
_KUANTUM_MAKS = Decimal(1).scaleb(-MAKS_DESIMAL)
TIMEOUT_DETIK_DEFAULT = 10

# --------------------------------------------------------------------------- #
# anggaran rate-limit
# --------------------------------------------------------------------------- #
# Anggaran resmi Binance USD-M Futures: 2400 bobot/menit per IP.
BOBOT_BATAS_PER_MENIT = 2400
# Kita hanya memakai sebagian; sisanya cadangan untuk order, pembatalan, dan
# proses lain yang berbagi IP sama. Menghabiskan 100% anggaran adalah cara
# tercepat kembali kena ban.
RASIO_BUDGET_DEFAULT = 0.5
BOBOT_BUDGET_DEFAULT = int(BOBOT_BATAS_PER_MENIT * RASIO_BUDGET_DEFAULT)

# TTL cache dipilih dari SIFAT datanya, bukan dikira-kira: spesifikasi kontrak
# dan bracket leverage nyaris tak pernah berubah dalam satu sesi.
TTL_EXCHANGE_INFO_DETIK = 3600.0
TTL_BRACKET_DETIK = 3600.0
# Waktu server hanya dipakai untuk offset tanda tangan; di antara panggilan kita
# ekstrapolasi dengan jam monotonik.
TTL_WAKTU_SERVER_DETIK = 30.0
# Lilin: beberapa runner berbagi TF konteks yang sama (mis. 15m). TTL pendek ini
# menghapus tarikan ganda dalam satu siklus tanpa membuat data jadi basi.
TTL_KLINES_DETIK = 3.0
MAKS_ENTRI_CACHE_KLINES = 512

# Bila Binance mengubah teks pesannya sehingga tenggat ban tak terbaca, kita
# TETAP wajib menahan diri. Ini pagar aman, bukan tebakan.
JEDA_BAN_TAK_DIKETAHUI_MS = 60_000

_PATH_WAKTU = "/fapi/v1/time"
_PATH_EXCHANGE_INFO = "/fapi/v1/exchangeInfo"
_PATH_KLINES = "/fapi/v1/klines"
_PATH_HARGA = "/fapi/v1/ticker/price"
_PATH_TICKER_24J = "/fapi/v1/ticker/24hr"
_PATH_DEPTH = "/fapi/v1/depth"
_PATH_SALDO = "/fapi/v2/balance"
_PATH_POSISI = "/fapi/v2/positionRisk"
_PATH_LEVERAGE = "/fapi/v1/leverage"
_PATH_BRACKET_LEVERAGE = "/fapi/v1/leverageBracket"
_PATH_ORDER = "/fapi/v1/order"
_PATH_ALL_OPEN_ORDERS = "/fapi/v1/allOpenOrders"
_PATH_OPEN_ORDERS = "/fapi/v1/openOrders"

_POLA_BAN = re.compile(r"banned until (\d{10,})")


class BinanceAPIError(Exception):
    """Dilempar saat Binance membalas dengan status non-2xx atau kode error."""

    def __init__(
        self,
        status: Optional[int],
        kode: Optional[int],
        pesan: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.status = status
        self.kode = kode
        self.pesan = pesan
        self.payload = payload or {}
        super().__init__(f"BinanceAPIError(status={status}, kode={kode}): {pesan}")


def ms_ban_dari_pesan(pesan: str) -> Optional[int]:
    """Ambil tenggat ban (epoch-ms) dari pesan -1003 Binance.

    Contoh nyata dari log testnet:
        "Way too many requests; IP(130.176.187.110) banned until 1785848930502."

    Mengembalikan None bila tidak ada epoch yang meyakinkan - pemanggil WAJIB
    tetap memasang jeda aman pada kasus itu.
    """
    if not pesan:
        return None
    cocok = _POLA_BAN.search(str(pesan))
    if not cocok:
        return None
    try:
        return int(cocok.group(1))
    except (TypeError, ValueError):
        return None


def bobot_permintaan(path: str, params: Optional[Dict[str, Any]] = None) -> int:
    """Bobot rate-limit satu permintaan menurut tabel resmi Binance USD-M.

    Angka ini menentukan: `ticker/24hr` TANPA symbol berbobot 40 (bukan 1), dan
    `klines` limit 1000 berbobot 5 (bukan 1). Pemindai likuiditas memakai
    keduanya, jadi salah hitung di sini akan mengulang insiden ban.
    """
    p = params or {}
    if path == _PATH_KLINES:
        limit = int(p.get("limit", 500) or 500)
        if limit < 100:
            return 1
        if limit < 500:
            return 2
        if limit <= 1000:
            return 5
        return 10
    if path == _PATH_DEPTH:
        limit = int(p.get("limit", 500) or 500)
        if limit <= 50:
            return 2
        if limit <= 100:
            return 5
        if limit <= 500:
            return 10
        return 20
    if path == _PATH_TICKER_24J:
        return 1 if p.get("symbol") else 40
    if path == _PATH_HARGA:
        return 1 if p.get("symbol") else 2
    if path in (_PATH_SALDO, _PATH_POSISI):
        return 5
    return 1


class PengaturLaju:
    """Jendela geser 60 detik untuk anggaran bobot per IP.

    Poin desain yang menentukan: penahanan terjadi SEBELUM permintaan dikirim.
    Pola "coba dulu, mundur kalau ditolak" secara struktural tidak bisa
    menyembuhkan masalah ini, karena permintaan yang ditolak Binance TETAP
    dihitung dan justru memperpanjang ban.

    `jam` dan `tidur` disuntikkan supaya penahanan bisa diuji tanpa menunggu.
    """

    def __init__(
        self,
        budget_per_menit: Optional[int] = None,
        jam: Optional[Any] = None,
        tidur: Optional[Any] = None,
    ) -> None:
        budget = BOBOT_BUDGET_DEFAULT if budget_per_menit is None else int(budget_per_menit)
        if budget <= 0:
            raise ValueError("budget_per_menit harus > 0")
        self.budget = budget
        self._jam = jam or time.monotonic
        self._tidur = tidur or time.sleep
        self._jejak: List[Tuple[float, int]] = []
        self.total_tertahan_detik = 0.0

    def _bersihkan(self, sekarang: float) -> None:
        batas = sekarang - 60.0
        while self._jejak and self._jejak[0][0] <= batas:
            self._jejak.pop(0)

    def terpakai(self) -> int:
        sekarang = float(self._jam())
        self._bersihkan(sekarang)
        return sum(b for _, b in self._jejak)

    def ambil(self, bobot: int) -> float:
        """Tahan sampai `bobot` muat dalam anggaran, lalu catat pemakaiannya.

        Mengembalikan total detik tertahan (0.0 bila langsung muat).
        """
        bobot = max(1, int(bobot))
        tertahan = 0.0
        for _ in range(240):  # pagar: tidak boleh menahan tanpa batas
            sekarang = float(self._jam())
            self._bersihkan(sekarang)
            terpakai = sum(b for _, b in self._jejak)
            if terpakai + bobot <= self.budget:
                self._jejak.append((sekarang, bobot))
                self.total_tertahan_detik += tertahan
                return tertahan
            tunggu = max(0.05, (self._jejak[0][0] + 60.0) - sekarang) if self._jejak else 0.05
            self._tidur(tunggu)
            tertahan += tunggu
        sekarang = float(self._jam())
        self._jejak.append((sekarang, bobot))
        self.total_tertahan_detik += tertahan
        return tertahan


def format_nilai(nilai: Any) -> Any:
    """Ubah nilai Python jadi bentuk yang DIPAHAMI Binance.

    Dua bug nyata yang diperbaiki fungsi ini (terlihat di log testnet 4 Agu 2026):

    1. `True`/`False` Python di-urlencode jadi "True"/"False" (huruf besar).
       Binance hanya menerima "true"/"false". Akibatnya `closePosition=True`
       tidak terbaca, STOP_MARKET dianggap tanpa quantity, dan endpoint
       membalas -4120 "Order type not supported for this endpoint".
    2. `str(float)` memakai notasi ilmiah untuk harga kecil
       (0.00001234 -> "1.234e-05") dan menyisakan derau biner
       (39.400000000000006). Keduanya ditolak dengan -1111
       "Precision is over the maximum defined for this asset".

    Solusi: boolean -> "true"/"false"; float -> desimal tetap tanpa eksponen,
    nol di belakang dibuang, memakai Decimal(repr(x)) supaya tidak menambah
    digit palsu.
    """
    if isinstance(nilai, bool):
        return "true" if nilai else "false"
    if isinstance(nilai, float):
        d = Decimal(repr(nilai))
        # Binance USD-M Futures tidak pernah menerima lebih dari 8 desimal.
        # Sisa derau biner (39.400000000000006) dipotong di sini sebagai pagar
        # terakhir; pembulatan ke tick/step tetap dilakukan di spesifikasi.py.
        if -d.as_tuple().exponent > MAKS_DESIMAL:
            d = d.quantize(_KUANTUM_MAKS, rounding=ROUND_HALF_UP)
        d = d.normalize()
        if d == d.to_integral_value():
            d = d.quantize(Decimal(1))
        teks = format(d, "f")
        if "." in teks:
            teks = teks.rstrip("0").rstrip(".")
        return teks or "0"
    return nilai


def _urutkan_query(params: Dict[str, Any]) -> str:
    """urlencode dengan urutan kunci stabil - wajib supaya tanda tangan konsisten."""
    bersih = {k: format_nilai(v) for k, v in params.items() if v is not None}
    return urllib.parse.urlencode(sorted(bersih.items()), doseq=True)


class BinanceFuturesClient:
    """Klien REST tipis untuk Binance USD-M Futures (testnet & live).

    `jam_ms` disuntikkan (default `time.time`-based) supaya bisa diuji tanpa
    bergantung pada jam sistem nyata, dan supaya offset waktu server bisa
    dipakai ulang tanpa panggilan jaringan berulang.
    """

    def __init__(
        self,
        kredensial: KredensialBinance,
        recv_window: int = RECV_WINDOW_DEFAULT,
        timeout: float = TIMEOUT_DETIK_DEFAULT,
        jam_ms: Optional[callable] = None,
        pembuka_url: Optional[callable] = None,
        pengatur_laju: Optional["PengaturLaju"] = None,
        tidur: Optional[callable] = None,
        jam_mono: Optional[callable] = None,
    ) -> None:
        self.kredensial = kredensial
        self.recv_window = int(recv_window)
        self.timeout = float(timeout)
        self._jam_ms = jam_ms or (lambda: int(time.time() * 1000))
        # `pembuka_url` disuntikkan untuk pengujian (mock) tanpa jaringan nyata.
        # Default: urllib.request.urlopen sungguhan.
        self._buka_url = pembuka_url or urllib.request.urlopen
        self._offset_waktu_ms = 0
        self._tidur = tidur or time.sleep
        self._jam_mono = jam_mono or time.monotonic
        # Anggaran rate-limit melekat pada IP, BUKAN pada objek klien. Karena itu
        # pengatur laju sengaja bisa dibagikan antar klien dalam satu proses.
        self.pengatur_laju = (
            pengatur_laju
            if pengatur_laju is not None
            else PengaturLaju(jam=self._jam_mono, tidur=self._tidur)
        )
        # 0 = tidak sedang dibatasi. Diisi dari pesan -1003/418.
        self.banned_sampai_ms = 0
        self._cache_exchange_info: Dict[str, Tuple[float, Any]] = {}
        self._cache_bracket: Dict[str, Tuple[float, Any]] = {}
        self._cache_klines: Dict[Tuple[str, str, int], Tuple[float, Any]] = {}
        self._cache_waktu_server: Optional[Tuple[float, int]] = None

    # ------------------------------------------------------------------ #
    # pagar rate-limit & ban
    # ------------------------------------------------------------------ #

    def sisa_ban_ms(self) -> int:
        """Sisa masa ban IP dalam ms (0 = bebas)."""
        if not self.banned_sampai_ms:
            return 0
        sisa = int(self.banned_sampai_ms) - int(self._jam_ms())
        if sisa <= 0:
            self.banned_sampai_ms = 0
            return 0
        return sisa

    def _sebelum_permintaan(self, path: str, params: Dict[str, Any]) -> None:
        sisa = self.sisa_ban_ms()
        if sisa > 0:
            # Ditahan LOKAL. Menembak lagi selama ban hanya memperpanjang ban.
            raise BinanceAPIError(
                status=418,
                kode=-1003,
                pesan=(
                    f"permintaan ditahan lokal: IP masih dibatasi Binance "
                    f"{sisa // 1000}s lagi; menembak lagi hanya memperpanjang ban"
                ),
                payload={"banned_sampai_ms": self.banned_sampai_ms},
            )
        self.pengatur_laju.ambil(bobot_permintaan(path, params))

    def _catat_pembatasan(self, status: Optional[int], payload: Dict[str, Any]) -> None:
        """Catat ban dari respons 418/429 supaya permintaan berikutnya ditahan."""
        if status not in (418, 429):
            return
        tenggat = ms_ban_dari_pesan(str(payload.get("msg", "")))
        if tenggat is None:
            tenggat = int(self._jam_ms()) + JEDA_BAN_TAK_DIKETAHUI_MS
        self.banned_sampai_ms = max(int(self.banned_sampai_ms or 0), int(tenggat))

    # ------------------------------------------------------------------ #
    # inti permintaan bertanda tangan
    # ------------------------------------------------------------------ #

    def _tandatangan(self, query: str) -> str:
        return hmac.new(
            self.kredensial.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _bangun_query(self, params: Dict[str, Any], signed: bool) -> str:
        p = dict(params)
        if signed:
            p.setdefault("recvWindow", self.recv_window)
            p["timestamp"] = self._jam_ms() + self._offset_waktu_ms
        q = _urutkan_query(p)
        if signed:
            q = f"{q}&signature={self._tandatangan(q)}" if q else f"signature={self._tandatangan('')}"
        return q

    def _permintaan(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        signed: bool = False,
    ) -> Any:
        params = params or {}
        # Gerbang ban + anggaran bobot dijalankan SEBELUM query dibangun, supaya
        # timestamp tanda tangan dihitung setelah selesai menahan (kalau tidak,
        # permintaan bisa kedaluwarsa oleh recvWindow).
        self._sebelum_permintaan(path, params)
        query = self._bangun_query(params, signed)
        url = f"{self.kredensial.base_url}{path}"
        headers = {"X-MBX-APIKEY": self.kredensial.api_key}
        data = None
        if method in ("POST", "DELETE", "PUT"):
            data = query.encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        # Satu korelasi dipakai baris permintaan, jawaban, dan galat, supaya
        # satu order bermasalah bisa ditarik utuh dengan satu grep.
        _jj = perekam()
        _kor = _jj.catat_permintaan(method, path, params, signed,
                                   bobot=bobot_permintaan(path, params))
        _t0 = time.monotonic()
        try:
            with self._buka_url(req, timeout=self.timeout) as resp:
                mentah = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            mentah = exc.read()
            status = exc.code
            try:
                payload = json.loads(mentah.decode("utf-8")) if mentah else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {}
            self._catat_pembatasan(status, payload)
            _jj.catat_galat(_kor, method, path, status=status,
                            kode=payload.get("code"),
                            pesan=payload.get("msg", str(exc)), jawaban=payload,
                            ms=(time.monotonic() - _t0) * 1000.0,
                            parameter=params)
            raise BinanceAPIError(
                status=status,
                kode=payload.get("code"),
                pesan=payload.get("msg", str(exc)),
                payload=payload,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # TimeoutError dan OSError sengaja ikut ditangkap. resp.read() yang
            # kehabisan waktu melempar TimeoutError MENTAH, bukan URLError,
            # sehingga dulu ia lolos dari seluruh penanganan BinanceAPIError.
            # HTTPError sudah ditangani di blok sebelumnya, jadi tidak tertelan.
            _jj.catat_galat(_kor, method, path, status=None, kode=None,
                            pesan="jaringan gagal: " + str(exc),
                            ms=(time.monotonic() - _t0) * 1000.0,
                            parameter=params)
            raise BinanceAPIError(status=None, kode=None, pesan=f"jaringan gagal: {exc}") from exc

        _ms = (time.monotonic() - _t0) * 1000.0
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

    # ------------------------------------------------------------------ #
    # publik: pasar (tidak perlu tanda tangan)
    # ------------------------------------------------------------------ #

    def waktu_server(self, paksa: bool = False) -> int:
        """Waktu server (ms), di-cache lalu diekstrapolasi dengan jam monotonik.

        Dulu ini dipanggil sekali per runner per siklus: 87 permintaan/siklus
        hanya untuk membaca jam. Sekarang satu permintaan per 30 detik.
        """
        if not paksa and self._cache_waktu_server is not None:
            mono_lama, server_lama = self._cache_waktu_server
            lewat = float(self._jam_mono()) - mono_lama
            if 0.0 <= lewat <= TTL_WAKTU_SERVER_DETIK:
                return int(server_lama + lewat * 1000.0)
        hasil = self._permintaan("GET", _PATH_WAKTU)
        server = int(hasil["serverTime"])
        self._cache_waktu_server = (float(self._jam_mono()), server)
        return server

    def sinkron_waktu(self) -> int:
        """Hitung & simpan offset (server - lokal) supaya timestamp signed valid.

        Selalu memaksa panggilan nyata: offset tanda tangan tidak boleh dihitung
        dari waktu hasil ekstrapolasi.
        """
        lokal_sebelum = self._jam_ms()
        server = self.waktu_server(paksa=True)
        lokal_sesudah = self._jam_ms()
        lokal_tengah = (lokal_sebelum + lokal_sesudah) // 2
        self._offset_waktu_ms = server - lokal_tengah
        return self._offset_waktu_ms

    def exchange_info(
        self, simbol: Optional[str] = None, ttl_detik: float = TTL_EXCHANGE_INFO_DETIK
    ) -> Dict[str, Any]:
        """Spesifikasi kontrak, di-cache: 87 runner tidak boleh = 87 permintaan."""
        kunci = simbol or "__semua__"
        if ttl_detik > 0:
            entri = self._cache_exchange_info.get(kunci)
            if entri is not None and (float(self._jam_mono()) - entri[0]) <= ttl_detik:
                return entri[1]
        params = {"symbol": simbol} if simbol else {}
        hasil = self._permintaan("GET", _PATH_EXCHANGE_INFO, params)
        self._cache_exchange_info[kunci] = (float(self._jam_mono()), hasil)
        return hasil

    def klines(
        self,
        simbol: str,
        interval: str,
        limit: int = 500,
        start_time: Optional[int] = None,
        ttl_detik: float = TTL_KLINES_DETIK,
    ) -> List[list]:
        """Lilin. Cache TTL-pendek meredam tarikan ganda dalam satu siklus.

        Permintaan dengan `start_time` TIDAK pernah di-cache: itu jalur muat
        riwayat historis, di mana data basi berbahaya dan pengulangannya jarang.
        """
        params: Dict[str, Any] = {"symbol": simbol, "interval": interval, "limit": int(limit)}
        if start_time is not None:
            params["startTime"] = int(start_time)
            return self._permintaan("GET", _PATH_KLINES, params)

        kunci = (simbol, interval, int(limit))
        if ttl_detik > 0:
            entri = self._cache_klines.get(kunci)
            if entri is not None and (float(self._jam_mono()) - entri[0]) <= ttl_detik:
                return entri[1]
        hasil = self._permintaan("GET", _PATH_KLINES, params)
        if ttl_detik > 0:
            if len(self._cache_klines) >= MAKS_ENTRI_CACHE_KLINES:
                tertua = min(self._cache_klines.items(), key=lambda kv: kv[1][0])[0]
                self._cache_klines.pop(tertua, None)
            self._cache_klines[kunci] = (float(self._jam_mono()), hasil)
        return hasil

    def harga_sekarang(self, simbol: str) -> float:
        hasil = self._permintaan("GET", _PATH_HARGA, {"symbol": simbol})
        return float(hasil["price"])

    def ticker_24jam(self, simbol: Optional[str] = None) -> Any:
        """Statistik 24 jam. Tanpa `simbol` -> daftar SELURUH simbol futures.

        Dipakai pemindai likuiditas untuk mengukur quoteVolume dan jumlah trade
        sehingga daftar pair TIDAK PERNAH di-hardcode. Catatan bobot: tanpa
        `simbol` permintaan ini berbobot 40, jadi jangan dipanggil per pair.
        """
        params = {"symbol": simbol} if simbol else {}
        return self._permintaan("GET", _PATH_TICKER_24J, params)

    def buku_order(self, simbol: str, limit: int = 5) -> Dict[str, Any]:
        return self._permintaan("GET", _PATH_DEPTH, {"symbol": simbol, "limit": int(limit)})

    def bid_ask_terbaik(self, simbol: str) -> Dict[str, float]:
        buku = self.buku_order(simbol, limit=5)
        bids = buku.get("bids") or []
        asks = buku.get("asks") or []
        return {
            "bid": float(bids[0][0]) if bids else float("nan"),
            "ask": float(asks[0][0]) if asks else float("nan"),
        }

    # ------------------------------------------------------------------ #
    # akun (butuh tanda tangan)
    # ------------------------------------------------------------------ #

    def saldo(self) -> List[Dict[str, Any]]:
        return self._permintaan("GET", _PATH_SALDO, signed=True)

    def saldo_usdt(self) -> float:
        for baris in self.saldo():
            if baris.get("asset") == "USDT":
                return float(baris.get("availableBalance", baris.get("balance", 0.0)))
        return 0.0

    def posisi(self, simbol: Optional[str] = None) -> List[Dict[str, Any]]:
        params = {"symbol": simbol} if simbol else {}
        return self._permintaan("GET", _PATH_POSISI, params, signed=True)

    def bracket_leverage(
        self, simbol: Optional[str] = None, ttl_detik: float = TTL_BRACKET_DETIK
    ) -> List[Dict[str, Any]]:
        """Leverage bracket per simbol (batas leverage menurut tingkat notional).

        Dipakai `spesifikasi.SpesifikasiKontrak` supaya leverage optimal yang
        dihitung engine tidak pernah melebihi batas Binance untuk notional itu.
        """
        kunci = simbol or "__semua__"
        if ttl_detik > 0:
            entri = self._cache_bracket.get(kunci)
            if entri is not None and (float(self._jam_mono()) - entri[0]) <= ttl_detik:
                return entri[1]
        params = {"symbol": simbol} if simbol else {}
        hasil = self._permintaan("GET", _PATH_BRACKET_LEVERAGE, params, signed=True)
        if isinstance(hasil, dict):
            hasil = [hasil]
        if ttl_detik > 0:
            self._cache_bracket[kunci] = (float(self._jam_mono()), hasil)
        return hasil

    def atur_leverage(self, simbol: str, leverage: int) -> Dict[str, Any]:
        return self._permintaan(
            "POST", _PATH_LEVERAGE, {"symbol": simbol, "leverage": int(leverage)}, signed=True
        )

    # ------------------------------------------------------------------ #
    # order - klien ini TIDAK menegakkan kebijakan post-only; itu tugas
    # order.py (pastikan_tanpa_market) sebelum payload sampai ke sini.
    # ------------------------------------------------------------------ #

    def kirim_order(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._permintaan("POST", _PATH_ORDER, payload, signed=True)

    def batalkan_order(self, simbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": simbol}
        if order_id is not None:
            params["orderId"] = int(order_id)
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return self._permintaan("DELETE", _PATH_ORDER, params, signed=True)

    def status_order(self, simbol: str, order_id: Optional[int] = None, orig_client_order_id: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"symbol": simbol}
        if order_id is not None:
            params["orderId"] = int(order_id)
        if orig_client_order_id is not None:
            params["origClientOrderId"] = orig_client_order_id
        return self._permintaan("GET", _PATH_ORDER, params, signed=True)

    def batalkan_semua_order(self, simbol: str) -> Dict[str, Any]:
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


async def kirim_order_async(client: BinanceFuturesClient, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Adaptor async tipis di atas `kirim_order` sinkron, untuk IceBreakerExecutor.

    Binance REST via urllib bersifat blocking; dijalankan lewat run_in_executor
    supaya tidak memblokir loop TWAP/iceberg saat mengirim banyak slice.
    """
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, client.kirim_order, payload)
