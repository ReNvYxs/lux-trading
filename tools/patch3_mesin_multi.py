"""Patch 3 untuk lux_modul/mesin_multi.py - hentikan sumber beban REST di engine.

Jalankan dari akar repo:  python tools/patch3_mesin_multi.py

Dua cacat logika yang diperbaiki (akar, bukan gejala):

1. Saat IP kena ban 418/-1003, engine TETAP memanggil siklus_sekali() untuk
   semua runner tiap 15 detik. Tiap permintaan yang ditolak tetap dihitung
   Binance dan MEMPERPANJANG ban - itulah sebabnya galat muncul serentak untuk
   hampir semua pair, dan mengapa di log ada dua tenggat ban yang berbeda.
   Sekarang siklus dilewati utuh selama masa ban, tanpa satu pun permintaan.

2. Semua runner disegarkan tiap siklus (15 detik) tanpa memandang TF-nya.
   Runner 15m tidak mungkin punya bar baru 240x/jam, tapi tetap menembak
   240x/jam. Penjadwalan sekarang mengikuti batas tutup bar per TF; runner yang
   masih punya entry pending / bracket aktif tetap dipoll tiap siklus karena
   SL/TP wajib dipantau.
"""
import pathlib
import sys

P = pathlib.Path("lux_modul/mesin_multi.py")
if not P.exists():
    sys.exit("jalankan skrip ini dari akar repo (folder yang berisi lux_modul/)")

src = P.read_text(encoding="utf-8")
awal = len(src)

if "_jatuh_tempo" in src:
    print("patch 3 sudah terpasang - tidak ada yang perlu dikerjakan")
    sys.exit(0)


def ganti(lama, baru, label, jumlah=1):
    global src
    n = src.count(lama)
    assert n == jumlah, f"{label}: ditemukan {n} kali (harus {jumlah})"
    src = src.replace(lama, baru)
    print(f"OK {label} (x{n})")


ganti(
    "from .kontrak import HORIZON_INTRADAY",
    "from .kontrak import HORIZON_INTRADAY, tf_ms",
    "import tf_ms",
)

ganti(
    "from .strategi import Registry, registry_bawaan\n",
    """from .strategi import Registry, registry_bawaan

# Jeda kecil setelah bar tutup sebelum menarik lilin: bursa butuh sesaat untuk
# memfinalkan bar, dan ini juga memecah ledakan permintaan serentak.
JEDA_SETELAH_BAR_MS = 2_000
""",
    "konstanta jeda bar",
)

ganti(
    """    sinyal_tertolak_governor: Tuple[Dict[str, Any], ...] = ()

    def ringkas(self) -> Dict[str, Any]:""",
    """    sinyal_tertolak_governor: Tuple[Dict[str, Any], ...] = ()
    # runner yang sengaja dilewati karena barnya belum tutup (hemat rate-limit)
    dilewati_jadwal: Tuple[str, ...] = ()
    # sisa masa ban IP saat siklus ini dijalankan (0 = tidak sedang dibatasi)
    ban_sisa_ms: int = 0

    def ringkas(self) -> Dict[str, Any]:""",
    "field RingkasanSiklus",
)

ganti(
    '            "ditolak_governor": list(self.sinyal_tertolak_governor),',
    """            "ditolak_governor": list(self.sinyal_tertolak_governor),
            "dilewati_jadwal": len(self.dilewati_jadwal),
            "ban_sisa_ms": self.ban_sisa_ms,""",
    "ringkas() field baru",
)

ganti(
    "        self._pair_dilepas: Dict[str, int] = {}\n",
    """        self._pair_dilepas: Dict[str, int] = {}
        # jadwal penyegaran per runner (epoch-ms). Kosong = jalankan sekarang.
        self._jatuh_tempo: Dict[Tuple[str, str], int] = {}
""",
    "field _jatuh_tempo",
)

ganti(
    """            del self.runner[kunci]
            dilepas.append(f"{simbol}@{tf}")""",
    """            del self.runner[kunci]
            self._jatuh_tempo.pop(kunci, None)
            dilepas.append(f"{simbol}@{tf}")""",
    "bersihkan jadwal saat runner dilepas",
)

ganti(
    "    def siklus(self) -> RingkasanSiklus:",
    '''    def _sisa_ban_ms(self) -> int:
        """Sisa masa ban IP menurut client (0 bila client tidak mendukung)."""
        fn = getattr(self.client, "sisa_ban_ms", None)
        if not callable(fn):
            return 0
        try:
            return max(0, int(fn()))
        except Exception:  # noqa: BLE001 - client cacat tidak boleh mematikan engine
            return 0

    @staticmethod
    def _ada_eksekusi_menggantung(runner: Any) -> bool:
        """True bila runner masih punya entry pending atau bracket aktif.

        Runner seperti ini WAJIB dipoll tiap siklus: SL/TP-nya sedang hidup di
        bursa dan fill-nya harus terdeteksi secepat mungkin. Penghematan
        rate-limit tidak boleh mengorbankan pemantauan posisi terbuka.
        """
        if getattr(runner, "_pending_entry", None):
            return True
        if getattr(runner, "_bracket_aktif", None):
            return True
        return False

    def _tempo_berikut(self, tf: str, sekarang_ms: int) -> int:
        """Kapan runner TF ini layak disegarkan lagi: sesaat setelah bar tutup."""
        try:
            satuan = int(tf_ms(tf))
        except Exception:  # noqa: BLE001 - TF tidak dikenal
            satuan = 0
        if satuan <= 0:
            return int(sekarang_ms + self.interval_poll_detik * 1000)
        batas = ((int(sekarang_ms) // satuan) + 1) * satuan
        return int(batas + JEDA_SETELAH_BAR_MS)

    def _perlu_jalan(self, kunci: Tuple[str, str], runner: Any, sekarang_ms: int) -> bool:
        if self._ada_eksekusi_menggantung(runner):
            return True
        tempo = self._jatuh_tempo.get(kunci)
        if tempo is None:
            return True
        return int(sekarang_ms) >= int(tempo)

    def siklus(self) -> RingkasanSiklus:''',
    "helper penjadwalan + sisa ban",
)

ganti(
    """        self._tertolak_siklus = []
        dipindai_ulang = False
        galat: List[str] = []

        if self.pemindai.perlu_segarkan():""",
    '''        self._tertolak_siklus = []
        dipindai_ulang = False
        galat: List[str] = []

        # GERBANG BAN: selama IP masih dibatasi, satu-satunya tindakan yang benar
        # adalah TIDAK menembak bursa sama sekali. Menembak lagi hanya
        # memperpanjang ban dan membanjiri laporan dengan galat identik.
        sisa_ban = self._sisa_ban_ms()
        if sisa_ban > 0:
            self._catat(
                f"ban IP Binance masih {sisa_ban / 1000:.0f}s - siklus dilewati "
                "tanpa satu pun permintaan"
            )
            return RingkasanSiklus(
                waktu_ms=int(self._jam()),
                jumlah_runner=len(self.runner),
                pair=tuple(sorted({k[0] for k in self.runner})),
                galat=(
                    f"ban_ip: menunggu {sisa_ban / 1000:.0f}s sebelum menghubungi "
                    "bursa lagi (tidak ada permintaan dikirim)",
                ),
                ban_sisa_ms=sisa_ban,
            )

        if self.pemindai.perlu_segarkan():''',
    "gerbang ban di siklus()",
)

ganti(
    """        hasil: List[HasilSiklusPair] = []
        for (simbol, tf), runner in sorted(self.runner.items()):""",
    """        hasil: List[HasilSiklusPair] = []
        dilewati: List[str] = []
        sekarang_ms = int(self._jam())
        for (simbol, tf), runner in sorted(self.runner.items()):""",
    "siapkan penjadwalan",
)

ganti(
    """            baris = HasilSiklusPair(simbol=simbol, entry_tf=tf, context_tfs=ctx_tfs)
            try:
                s = runner.siklus_sekali()""",
    """            baris = HasilSiklusPair(simbol=simbol, entry_tf=tf, context_tfs=ctx_tfs)
            if not self._perlu_jalan((simbol, tf), runner, sekarang_ms):
                dilewati.append(f"{simbol}@{tf}")
                hasil.append(baris)
                continue
            self._jatuh_tempo[(simbol, tf)] = self._tempo_berikut(tf, sekarang_ms)
            try:
                s = runner.siklus_sekali()""",
    "gerbang jadwal per runner",
)

ganti(
    "            sinyal_tertolak_governor=tuple(self._tertolak_siklus),\n        )",
    """            sinyal_tertolak_governor=tuple(self._tertolak_siklus),
            dilewati_jadwal=tuple(dilewati),
            ban_sisa_ms=0,
        )""",
    "kembalikan dilewati_jadwal",
)

P.write_text(src, encoding="utf-8")
print(f"SELESAI {awal} -> {len(src)} byte")
