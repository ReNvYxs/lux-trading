"""Patch 2 untuk lux_modul/live_runner.py

Jalankan dari akar repo:  python tools/patch2_live_runner.py

Memperbaiki:
1. BUG P0 - order Take Profit TIDAK PERNAH dikirim ke bursa.
2. BUG - id strategi selalu kosong di Telegram/dashboard.
3. Beban REST - penyegaran menarik 200 bar/TF/runner/siklus (penyumbang ban 418).
4. Import mati: `field`, `ARAH_LONG`.

Skrip ini ber-assert ketat: bila teks sumber tidak sesuai harapan, ia berhenti
TANPA menulis apa pun, sehingga file tidak mungkin rusak setengah jalan.

Urutan sengaja: penggantian pola salah dilakukan SEBELUM helper disisipkan,
supaya docstring helper (yang mengutip pola lama sebagai dokumentasi) tidak
ikut terhitung maupun tergantikan.
"""
import pathlib
import sys

P = pathlib.Path("lux_modul/live_runner.py")
if not P.exists():
    sys.exit("jalankan skrip ini dari akar repo (folder yang berisi lux_modul/)")

src = P.read_text(encoding="utf-8")
awal = len(src)
SALAH_TP = 'getattr(v, "tp"'
SALAH_STRATEGI = 'getattr(v, "strategi"'

if "def tp_pertama" in src:
    print("patch 2 sudah terpasang - tidak ada yang perlu dikerjakan")
    sys.exit(0)


def ganti(lama, baru, label, jumlah=1):
    global src
    n = src.count(lama)
    assert n == jumlah, f"{label}: ditemukan {n} kali (harus {jumlah})"
    src = src.replace(lama, baru)
    print(f"OK {label} (x{n})")


# --------------------------------------------------------- 1. import bersih
ganti(
    "from dataclasses import dataclass, field, replace",
    "from dataclasses import dataclass, replace",
    "buang import mati: field",
)
ganti(
    "from .kontrak import ARAH_LONG, Bars, HORIZON_INTRADAY, MODE_SIGNAL_ONLY, TFPlan",
    "from .kontrak import Bars, HORIZON_INTRADAY, MODE_SIGNAL_ONLY, TFPlan, tf_ms",
    "buang ARAH_LONG, ambil tf_ms",
)

# ------------------------------------------------------------ 2. konstanta
ganti(
    "KLINES_LIMIT_AWAL = 1000\n",
    """KLINES_LIMIT_AWAL = 1000
# Penyegaran hanya butuh bar yang benar-benar baru. Sebelumnya dipatok 200 bar
# per TF per runner per siklus - pemborosan bobot rate-limit yang menjadi salah
# satu penyebab ban IP 418/-1003 saat menjalankan 29 pair.
KLINES_LIMIT_SEGAR_MIN = 3
KLINES_LIMIT_SEGAR_MAKS = 500
BAR_CADANGAN_SEGAR = 2
""",
    "konstanta limit segar",
)

# ------------------------- 3. ganti SEMUA pemakaian nama field yang salah
ganti(
    'float(getattr(v, "tp", 0) or 0) if v else 0',
    "tp_pertama(v)",
    "TP jalur entry pending",
)
ganti(
    'float(getattr(v, "tp", 0) or 0)',
    "tp_pertama(v)",
    "TP jalur entry terisi",
)
ganti(
    'getattr(v, "strategi", "") if v else ""',
    "strategi_verdict(v)",
    "strategi jalur pending",
)
sisa = src.count(SALAH_STRATEGI)
assert sisa >= 1, "pola strategi salah tidak ditemukan"
src = src.replace('getattr(v, "strategi", "")', "strategi_verdict(v)")
print(f"OK strategi sisa (x{sisa})")

assert SALAH_TP not in src, "masih ada pemakaian atribut tp yang salah"
assert SALAH_STRATEGI not in src, "masih ada pemakaian atribut strategi yang salah"
print("OK verifikasi: tidak ada sisa pola nama field yang salah")

# ------------------------------- 4. sisipkan helper (setelah verifikasi bersih)
ganti(
    "class LiveRunnerError(Exception):",
    '''def tp_pertama(verdict: Any) -> float:
    """Harga Take Profit pertama dari sebuah StrategyVerdict.

    AKAR MASALAH YANG DIPERBAIKI (bukan gejala): kode lama membaca atribut
    bernama 'tp' lewat getattr dengan default 0. StrategyVerdict TIDAK punya
    atribut itu - yang ada adalah `tps: Tuple[TargetTP, ...]` (lihat
    kontrak.py). Akibatnya tp_price selalu 0.0, gerbang `if tp_price > 0`
    selalu False, dan **order Take Profit tidak pernah sekali pun dikirim ke
    bursa**; posisi hanya bisa tutup lewat SL atau timeout 7 hari. Backtest
    memakai v.tps[0].harga yang benar, jadi paritas backtest<->live pun rusak.
    Uji lama tidak menangkapnya karena menyuntik tp_price langsung ke
    dataclass, melewati verdict sepenuhnya.

    Aman terhadap tps kosong, elemen tanpa harga, dan harga <= 0.
    """
    if verdict is None:
        return 0.0
    tps = getattr(verdict, "tps", ()) or ()
    for t in tps:
        try:
            harga = float(getattr(t, "harga", 0) or 0)
        except (TypeError, ValueError):
            continue
        if harga > 0:
            return harga
    return 0.0


def strategi_verdict(verdict: Any) -> str:
    """Id strategi dari verdict.

    Kode lama membaca atribut bernama 'strategi'; nama field sebenarnya adalah
    `strategy_id`, sehingga nilainya selalu kosong di notifikasi Telegram dan
    dashboard (pesan selalu menampilkan "Strategi : -").
    """
    if verdict is None:
        return ""
    return str(getattr(verdict, "strategy_id", "") or "")


class LiveRunnerError(Exception):''',
    "sisipkan helper tp_pertama + strategi_verdict",
)

# --------------------------------------------- 5. _segarkan_plane adaptif
ganti(
    '''    def _segarkan_plane(self, limit: int = 200) -> int:
        if self.plane is None:
            raise LiveRunnerError("panggil muat_riwayat_awal() sebelum polling")
        waktu_server = self.client.waktu_server()
        peta_baru: Dict[str, Bars] = {}
        for tf in self.tfplan.semua_tf():
            lama = self.plane.bars(tf)
            mentah = self.client.klines(self.simbol, tf, limit=limit)''',
    '''    def _limit_segar(self, lama: Bars, tf: str, waktu_server: int) -> int:
        """Berapa bar yang perlu ditarik ulang untuk TF ini.

        Dihitung dari selisih waktu, BUKAN angka tetap. Kalau runner sempat
        tertidur atau terkena ban lama, limit ikut melebar supaya `_gabung_bars`
        tidak menyambung dengan LUBANG di tengah - `_gabung_bars` memotong pakai
        searchsorted dan tidak akan mengeluh bila ada gap.
        """
        if len(lama) == 0:
            return KLINES_LIMIT_AWAL
        satuan = tf_ms(tf)
        if satuan <= 0:
            return KLINES_LIMIT_SEGAR_MAKS
        tertinggal = (int(waktu_server) - int(lama.ts[-1])) // satuan
        if tertinggal < 0:
            tertinggal = 0
        butuh = int(tertinggal) + BAR_CADANGAN_SEGAR
        return max(KLINES_LIMIT_SEGAR_MIN, min(KLINES_LIMIT_SEGAR_MAKS, butuh))

    def _segarkan_plane(self, limit: Optional[int] = None) -> int:
        if self.plane is None:
            raise LiveRunnerError("panggil muat_riwayat_awal() sebelum polling")
        waktu_server = self.client.waktu_server()
        peta_baru: Dict[str, Bars] = {}
        for tf in self.tfplan.semua_tf():
            lama = self.plane.bars(tf)
            limit_tf = limit if limit is not None else self._limit_segar(lama, tf, waktu_server)
            mentah = self.client.klines(self.simbol, tf, limit=limit_tf)''',
    "_segarkan_plane adaptif + sadar gap",
)

P.write_text(src, encoding="utf-8")
print(f"SELESAI {awal} -> {len(src)} byte")
