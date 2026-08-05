"""Patch 1 untuk lux_modul/eksekusi/binance_client.py - akar ban IP 418/-1003.

Jalankan dari akar repo:  python tools/patch1_binance_client.py

Akar masalah (log testnet 4 Agu 2026, 29 pair, dua tenggat ban berbeda):

1. Tidak ada akuntansi bobot sama sekali. Anggaran Binance USD-M adalah
   2400 bobot/menit per IP; kode lama menembak urllib tanpa tahu sudah memakai
   berapa.
2. Data identik ditarik berulang-ulang. 29 pair x 3 rencana TF = 87 runner,
   sehingga saat start ada 87x exchangeInfo + 87x leverageBracket (isinya sama)
   dan 87x2 klines(limit=1000) @bobot 5. Tiap siklus: 87x waktu_server() hanya
   untuk membaca jam.
3. Setelah kena ban, siklus berikutnya TETAP menembak. Permintaan yang ditolak
   pun tetap dihitung Binance, sehingga ban MEMANJANG - itulah sebabnya di log
   muncul dua tenggat ban yang berbeda.

Skrip ini ber-assert ketat dan menulis hanya di akhir: bila satu jangkar saja
tidak cocok, file tidak berubah sama sekali. Aman dijalankan dua kali.
"""
import pathlib
import sys

P = pathlib.Path("lux_modul/eksekusi/binance_client.py")
if not P.exists():
    sys.exit("jalankan skrip ini dari akar repo (folder yang berisi lux_modul/)")

src = P.read_text(encoding="utf-8")
awal = len(src)

if "class PengaturLaju" in src:
    print("patch 1 sudah terpasang - tidak ada yang perlu dikerjakan")
    sys.exit(0)


def ganti(lama, baru, label, jumlah=1):
    global src
    n = src.count(lama)
    assert n == jumlah, f"{label}: ditemukan {n} kali (harus {jumlah})"
    src = src.replace(lama, baru)
    print(f"OK {label} (x{n})")


# ------------------------------------------------------------------ 1. import
ganti(
    "import json\nimport time\n",
    "import json\nimport re\nimport time\n",
    "import re",
)
ganti(
    "from dataclasses import dataclass\nfrom decimal import ROUND_HALF_UP, Decimal\n"
    "from typing import Any, Dict, List, Optional\n",
    "from decimal import ROUND_HALF_UP, Decimal\n"
    "from typing import Any, Dict, List, Optional, Tuple\n",
    "buang import mati dataclass, ambil Tuple",
)

# --------------------------------------------------------------- 2. konstanta
ganti(
    "TIMEOUT_DETIK_DEFAULT = 10\n",
    '''TIMEOUT_DETIK_DEFAULT = 10

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
''',
    "konstanta anggaran & TTL",
)

ganti(
    '_PATH_ALL_OPEN_ORDERS = "/fapi/v1/allOpenOrders"\n',
    '_PATH_ALL_OPEN_ORDERS = "/fapi/v1/allOpenOrders"\n\n'
    '_POLA_BAN = re.compile(r"banned until (\\d{10,})")\n',
    "pola pengurai ban",
)

# ------------------------------------------------- 3. helper bobot & pengatur laju
ganti(
    "def format_nilai(nilai: Any) -> Any:",
    '''def ms_ban_dari_pesan(pesan: str) -> Optional[int]:
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


def format_nilai(nilai: Any) -> Any:''',
    "helper bobot + PengaturLaju",
)

# ---------------------------------------------------------- 4. konstruktor klien
ganti(
    """        jam_ms: Optional[callable] = None,
        pembuka_url: Optional[callable] = None,
    ) -> None:""",
    """        jam_ms: Optional[callable] = None,
        pembuka_url: Optional[callable] = None,
        pengatur_laju: Optional["PengaturLaju"] = None,
        tidur: Optional[callable] = None,
        jam_mono: Optional[callable] = None,
    ) -> None:""",
    "parameter konstruktor baru",
)
ganti(
    "        self._offset_waktu_ms = 0\n",
    """        self._offset_waktu_ms = 0
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
""",
    "field pengatur laju + cache",
)

# --------------------------------------------------------- 5. gerbang ban & laju
ganti(
    """    # ------------------------------------------------------------------ #
    # inti permintaan bertanda tangan
    # ------------------------------------------------------------------ #""",
    '''    # ------------------------------------------------------------------ #
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
    # ------------------------------------------------------------------ #''',
    "metode gerbang ban",
)

ganti(
    "        params = params or {}\n        query = self._bangun_query(params, signed)",
    "        params = params or {}\n"
    "        # Gerbang ban + anggaran bobot dijalankan SEBELUM query dibangun, supaya\n"
    "        # timestamp tanda tangan dihitung setelah selesai menahan (kalau tidak,\n"
    "        # permintaan bisa kedaluwarsa oleh recvWindow).\n"
    "        self._sebelum_permintaan(path, params)\n"
    "        query = self._bangun_query(params, signed)",
    "panggil gerbang di _permintaan",
)

ganti(
    """                payload = {}
            raise BinanceAPIError(
                status=status,""",
    """                payload = {}
            self._catat_pembatasan(status, payload)
            raise BinanceAPIError(
                status=status,""",
    "catat ban pada jalur HTTPError",
)

ganti(
    '        if isinstance(hasil, dict) and "code" in hasil and "msg" in hasil and status >= 400:\n'
    '            raise BinanceAPIError(status, hasil.get("code")',
    '        if isinstance(hasil, dict) and "code" in hasil and "msg" in hasil and status >= 400:\n'
    "            self._catat_pembatasan(status, hasil)\n"
    '            raise BinanceAPIError(status, hasil.get("code")',
    "catat ban pada jalur badan JSON",
)

# ------------------------------------------------------------ 6. cache endpoint
ganti(
    '''    def waktu_server(self) -> int:
        hasil = self._permintaan("GET", _PATH_WAKTU)
        return int(hasil["serverTime"])

    def sinkron_waktu(self) -> int:
        """Hitung & simpan offset (server - lokal) supaya timestamp signed valid."""
        lokal_sebelum = self._jam_ms()
        server = self.waktu_server()''',
    '''    def waktu_server(self, paksa: bool = False) -> int:
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
        server = self.waktu_server(paksa=True)''',
    "cache waktu server",
)

ganti(
    '''    def exchange_info(self, simbol: Optional[str] = None) -> Dict[str, Any]:
        params = {"symbol": simbol} if simbol else {}
        return self._permintaan("GET", _PATH_EXCHANGE_INFO, params)''',
    '''    def exchange_info(
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
        return hasil''',
    "cache exchange_info",
)

ganti(
    '''    def klines(
        self, simbol: str, interval: str, limit: int = 500, start_time: Optional[int] = None
    ) -> List[list]:
        params: Dict[str, Any] = {"symbol": simbol, "interval": interval, "limit": int(limit)}
        if start_time is not None:
            params["startTime"] = int(start_time)
        return self._permintaan("GET", _PATH_KLINES, params)''',
    '''    def klines(
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
        return hasil''',
    "cache klines",
)

ganti(
    """    def bracket_leverage(self, simbol: Optional[str] = None) -> List[Dict[str, Any]]:""",
    """    def bracket_leverage(
        self, simbol: Optional[str] = None, ttl_detik: float = TTL_BRACKET_DETIK
    ) -> List[Dict[str, Any]]:""",
    "tanda tangan bracket_leverage",
)
ganti(
    """        params = {"symbol": simbol} if simbol else {}
        hasil = self._permintaan("GET", _PATH_BRACKET_LEVERAGE, params, signed=True)
        if isinstance(hasil, dict):
            return [hasil]
        return hasil""",
    """        kunci = simbol or "__semua__"
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
        return hasil""",
    "cache bracket_leverage",
)

ganti(
    '        """Statistik 24 jam. Tanpa `simbol` -> daftar SELURUH simbol futures.\n\n'
    "        Dipakai pemindai likuiditas untuk mengukur quoteVolume dan jumlah trade\n"
    '        sehingga daftar pair TIDAK PERNAH di-hardcode.\n        """',
    '        """Statistik 24 jam. Tanpa `simbol` -> daftar SELURUH simbol futures.\n\n'
    "        Dipakai pemindai likuiditas untuk mengukur quoteVolume dan jumlah trade\n"
    "        sehingga daftar pair TIDAK PERNAH di-hardcode. Catatan bobot: tanpa\n"
    "        `simbol` permintaan ini berbobot 40, jadi jangan dipanggil per pair.\n"
    '        """',
    "catatan bobot ticker 24 jam",
)

P.write_text(src, encoding="utf-8")
print(f"SELESAI {awal} -> {len(src)} byte")
