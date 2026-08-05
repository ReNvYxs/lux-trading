"""L5b - mesin MULTI-PAIR yang digerakkan pemindaian pasar + kontrak strategi.

Alur yang ditegakkan modul ini:

    Binance Market -> Scan Liquid Pairs (25..50) -> Rencana TF dari STRATEGI
    (STF & MTF) -> Signal -> Risk Management -> Entry

BUKAN `BTC -> 15m -> Entry`.

Catatan penting:
- Daftar pair tidak pernah ditulis di source code. Ia datang dari
  `pemindai.PemindaiPasar` yang membaca kondisi pasar saat itu dan disegarkan
  berkala (TTL).
- Entry TF tidak dipaksa 15m. Ia lahir dari `rencana_tf.rencana_dari_registry`
  yang membaca `required_roles` dan `horizon_didukung` tiap strategi.
- Satu pair bisa punya beberapa rencana TF sekaligus (mis. 15m+1h dan 1h+4h).
  Setiap kombinasi (pair, rencana) dijalankan oleh satu LiveRunner.
- Pair yang keluar dari daftar likuid TIDAK langsung dibuang bila runner-nya
  masih memegang eksekusi terbuka pada siklus terakhir; ia ditandai "dilepas
  bertahap" agar tidak meninggalkan posisi tanpa pengawasan.

Governor portofolio (4 Agu 2026):
- Akar masalah -2019 "Margin is insufficient" di log testnet operator: setiap
  runner menghitung margin dari SALDO TOTAL seolah dirinya satu-satunya yang
  akan mengirim order. Dengan puluhan runner berjalan bersamaan, semua memakai
  angka saldo yang sama sehingga runner-runner belakangan ditolak bursa.
- Solusi: `GovernorPortofolio` opsional. Bila diberikan, MesinMultiPair menarik
  SATU snapshot akun nyata (saldo + posisi) di awal setiap `siklus()`, dan
  setiap runner WAJIB minta izin governor sebelum mengeksekusi entry lewat
  callback `pemeriksa_entry_fn`. Governor menegakkan: maksimum posisi, minimum
  free margin, tidak dobel simbol, tidak bentrok arah, dan swing tidak pernah
  auto-entry.
- Bila pengambilan snapshot gagal (jaringan/API), governor tetap dijalankan
  dengan snapshot "tanpa kapasitas" (equity 0) supaya SELALU menolak entry
  pada siklus itu -- gagal aman, bukan gagal terbuka.
- Sinyal yang ditolak governor tetap dilaporkan (untuk dashboard), tidak
  dibuang diam-diam.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .eksekusi.order import KebijakanOrder
from .governor import (
    GovernorPortofolio,
    KandidatEntry,
    KebijakanPortofolio,
    SnapshotAkun,
    snapshot_dari_akun,
)
from .kontrak import HORIZON_INTRADAY, tf_ms
from .live_runner import LiveRunner
from .pemindai import HasilPindai, KriteriaLikuiditas, PemindaiPasar
from .rencana_tf import RencanaTF, cakupan_strategi, rencana_dari_registry
from .strategi import Registry, registry_bawaan

# Jeda kecil setelah bar tutup sebelum menarik lilin: bursa butuh sesaat untuk
# memfinalkan bar, dan ini juga memecah ledakan permintaan serentak.
JEDA_SETELAH_BAR_MS = 2_000


class MesinError(Exception):
    pass


@dataclass
class HasilSiklusPair:
    simbol: str
    entry_tf: str
    context_tfs: Tuple[str, ...]
    bar_baru: bool = False
    ada_sinyal: bool = False
    ada_entry: bool = False
    galat: Optional[str] = None

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "entry_tf": self.entry_tf,
            "context_tfs": list(self.context_tfs),
            "bar_baru": self.bar_baru,
            "ada_sinyal": self.ada_sinyal,
            "ada_entry": self.ada_entry,
            "galat": self.galat,
        }


@dataclass
class RingkasanSiklus:
    waktu_ms: int
    jumlah_runner: int
    pair: Tuple[str, ...]
    hasil: Tuple[HasilSiklusPair, ...] = ()
    dipindai_ulang: bool = False
    galat: Tuple[str, ...] = ()
    sinyal_tertolak_governor: Tuple[Dict[str, Any], ...] = ()
    # runner yang sengaja dilewati karena barnya belum tutup (hemat rate-limit)
    dilewati_jadwal: Tuple[str, ...] = ()
    # sisa masa ban IP saat siklus ini dijalankan (0 = tidak sedang dibatasi)
    ban_sisa_ms: int = 0

    def ringkas(self) -> Dict[str, Any]:
        return {
            "waktu_ms": self.waktu_ms,
            "jumlah_runner": self.jumlah_runner,
            "jumlah_pair": len(self.pair),
            "pair": list(self.pair),
            "dipindai_ulang": self.dipindai_ulang,
            "bar_baru": sum(1 for h in self.hasil if h.bar_baru),
            "sinyal": sum(1 for h in self.hasil if h.ada_sinyal),
            "entry": sum(1 for h in self.hasil if h.ada_entry),
            "galat": list(self.galat),
            "detail_sinyal": [h.ringkas() for h in self.hasil if h.ada_sinyal],
            "ditolak_governor": list(self.sinyal_tertolak_governor),
            "dilewati_jadwal": len(self.dilewati_jadwal),
            "ban_sisa_ms": self.ban_sisa_ms,
        }


class MesinMultiPair:
    """Orkestrator multi-pair untuk mode testnet/live."""

    def __init__(
        self,
        client: Any,
        kriteria: Optional[KriteriaLikuiditas] = None,
        horizon: str = HORIZON_INTRADAY,
        registry: Optional[Registry] = None,
        entry_tfs: Sequence[str] = (),
        maks_konteks: Optional[int] = None,
        balance: float = 100.0,
        leverage_maks: float = 20.0,
        margin_konflik: float = 5.0,
        kebijakan_order: Optional[KebijakanOrder] = None,
        interval_poll_detik: float = 15.0,
        maks_runner: int = 120,
        pemindai: Optional[PemindaiPasar] = None,
        buat_runner: Optional[Callable[..., Any]] = None,
        jam: Optional[Callable[[], int]] = None,
        tidur: Optional[Callable[[float], None]] = None,
        pencatat: Optional[Callable[[str], None]] = None,
        governor: Optional[GovernorPortofolio] = None,
        ambil_snapshot_akun: Optional[Callable[[], SnapshotAkun]] = None,
        notifier: Optional[Any] = None,
    ) -> None:
        self.client = client
        self.kriteria = kriteria or KriteriaLikuiditas()
        self.horizon = horizon
        self.registry = registry if registry is not None else registry_bawaan()
        self.entry_tfs = tuple(entry_tfs)
        self.maks_konteks = maks_konteks
        self.balance = float(balance)
        self.leverage_maks = float(leverage_maks)
        self.margin_konflik = float(margin_konflik)
        self.kebijakan_order = kebijakan_order or KebijakanOrder()
        self.interval_poll_detik = float(interval_poll_detik)
        self.maks_runner = int(maks_runner)
        self.pemindai = pemindai or PemindaiPasar(client, self.kriteria)
        self._buat_runner = buat_runner or self._buat_runner_bawaan
        self._jam = jam or (lambda: int(time.time() * 1000))
        self._tidur = tidur or time.sleep
        self._catat = pencatat or (lambda pesan: None)

        # governor portofolio (opsional; None = tanpa batasan lintas-runner,
        # perilaku lama dipertahankan untuk kompatibilitas mundur)
        self.governor = governor
        self.ambil_snapshot_akun = ambil_snapshot_akun
        self.notifier = notifier
        self._tertolak_siklus: List[Dict[str, Any]] = []

        self.rencana: Tuple[RencanaTF, ...] = ()
        self.runner: Dict[Tuple[str, str], Any] = {}
        self.pindai_terakhir: Optional[HasilPindai] = None
        self._pair_dilepas: Dict[str, int] = {}
        # jadwal penyegaran per runner (epoch-ms). Kosong = jalankan sekarang.
        self._jatuh_tempo: Dict[Tuple[str, str], int] = {}

    # ------------------------------------------------------------------ #
    # penyiapan
    # ------------------------------------------------------------------ #

    def _buat_pemeriksa_entry(
        self, simbol: str, entry_tf: str
    ) -> Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]]:
        """Bungkus GovernorPortofolio jadi callback yang dipanggil LiveRunner.

        Setiap kandidat diantre ke governor, keputusan dihitung ulang untuk
        SELURUH antrean siklus ini (peringkat skor -> likuiditas -> RR), lalu
        keputusan milik kandidat ini dicari dari hasil tersebut. Keputusan yang
        sudah diberikan tidak pernah ditarik kembali pada runner lain di siklus
        yang sama; hanya kandidat yang BELUM dieksekusi yang bisa berubah oleh
        kandidat baru dengan skor lebih tinggi.
        """

        def _periksa(info: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
            gov = self.governor
            if gov is None:
                return True, None
            kandidat = KandidatEntry(
                simbol=str(info.get("simbol") or simbol),
                arah=str(info.get("arah") or ""),
                entry_tf=entry_tf,
                horizon=str(info.get("horizon") or self.horizon),
                skor=float(info.get("skor") or 0.0),
                margin_dibutuhkan=float(info.get("margin_dibutuhkan") or 0.0),
                notional=float(info.get("notional") or 0.0),
                leverage=float(info.get("leverage") or 0.0),
                rr_bersih=float(info.get("rr_bersih") or 0.0),
                skor_likuiditas=float(info.get("skor_likuiditas") or 0.0),
                strategi=str(info.get("strategi") or ""),
            )
            gov.antre(kandidat)
            for k in gov.putuskan():
                if k.kandidat.kunci() == kandidat.kunci():
                    if not k.diterima:
                        self._tertolak_siklus.append(k.ringkas())
                    return k.diterima, (k.alasan or None)
            # tidak seharusnya terjadi (kandidat baru saja diantre) - gagal aman
            self._tertolak_siklus.append(
                {"simbol": kandidat.simbol, "entry_tf": entry_tf, "alasan": "governor_tidak_menjawab"}
            )
            return False, "governor_tidak_menjawab"

        return _periksa

    def _buat_runner_bawaan(self, simbol: str, rencana: RencanaTF) -> LiveRunner:
        return LiveRunner(
            client=self.client,
            simbol=simbol,
            tfplan=rencana.tfplan,
            horizon=self.horizon,
            registry=self.registry,
            balance=self.balance,
            leverage_maks=self.leverage_maks,
            margin_konflik=self.margin_konflik,
            kebijakan_order=self.kebijakan_order,
            interval_poll_detik=self.interval_poll_detik,
            notifier=self.notifier,
            pemeriksa_entry_fn=(
                self._buat_pemeriksa_entry(simbol, rencana.entry_tf)
                if self.governor is not None
                else None
            ),
        )

    def bangun_rencana(self) -> Tuple[RencanaTF, ...]:
        self.rencana = rencana_dari_registry(
            self.registry,
            self.horizon,
            entry_tfs=self.entry_tfs or None,
            maks_konteks=self.maks_konteks,
        )
        if not self.rencana:
            raise MesinError("tidak ada rencana TF yang bisa dibangun dari registry")
        return self.rencana

    def siapkan(self) -> Dict[str, Any]:
        """Pindai pasar, bangun rencana TF, lalu siapkan runner."""
        self.bangun_rencana()
        laporan_pindai = self.segarkan_pair(paksa=True)
        cakupan = cakupan_strategi(self.registry, self.rencana, self.horizon)
        return {
            "horizon": self.horizon,
            "rencana_tf": [r.ringkas() for r in self.rencana],
            "cakupan_strategi": cakupan,
            "pindai": laporan_pindai,
            "jumlah_runner": len(self.runner),
            "governor_aktif": self.governor is not None,
        }

    # ------------------------------------------------------------------ #
    # manajemen pair
    # ------------------------------------------------------------------ #

    def _pair_aktif(self, simbol_terpilih: Sequence[str]) -> List[str]:
        """Batasi jumlah pair agar total runner tidak melebihi maks_runner."""
        n_rencana = max(1, len(self.rencana))
        batas_pair = max(2, self.maks_runner // n_rencana)
        return list(simbol_terpilih[:batas_pair])

    def segarkan_pair(self, paksa: bool = False) -> Dict[str, Any]:
        if not self.rencana:
            self.bangun_rencana()
        hasil = self.pemindai.pindai(paksa=paksa)
        self.pindai_terakhir = hasil

        terpilih = self._pair_aktif(hasil.simbol)
        if len(terpilih) < 2:
            raise MesinError(
                "pemindaian menghasilkan <2 pair; engine multi-pair menolak jalan "
                "sebagai single-pair (BTC-only)"
            )

        diinginkan = {
            (s, r.entry_tf) for s in terpilih for r in self.rencana
        }
        peta_rencana = {r.entry_tf: r for r in self.rencana}

        ditambah: List[str] = []
        for kunci in sorted(diinginkan):
            if kunci in self.runner:
                continue
            simbol, tf = kunci
            self.runner[kunci] = self._buat_runner(simbol, peta_rencana[tf])
            ditambah.append(f"{simbol}@{tf}")

        dilepas: List[str] = []
        for kunci in list(self.runner):
            if kunci in diinginkan:
                self._pair_dilepas.pop(kunci[0], None)
                continue
            simbol, tf = kunci
            if self._punya_eksekusi_terbuka(self.runner[kunci]):
                self._pair_dilepas[simbol] = self._pair_dilepas.get(simbol, 0) + 1
                self._catat(
                    f"pair {simbol} keluar dari daftar likuid tapi masih ada eksekusi "
                    "terbuka - runner dipertahankan sampai bersih"
                )
                continue
            del self.runner[kunci]
            self._jatuh_tempo.pop(kunci, None)
            dilepas.append(f"{simbol}@{tf}")

        return {
            "waktu_ms": hasil.waktu_ms,
            "jumlah_pair_terpilih": len(terpilih),
            "pair": terpilih,
            "runner_ditambah": ditambah,
            "runner_dilepas": dilepas,
            "runner_total": len(self.runner),
            "ditolak": dict(hasil.ditolak),
            "total_kandidat": hasil.total_kandidat,
            "catatan": list(hasil.catatan),
        }

    @staticmethod
    def _punya_eksekusi_terbuka(runner: Any) -> bool:
        riwayat = getattr(runner, "riwayat_siklus", None) or []
        for s in reversed(riwayat[-20:]):
            eks = getattr(s, "eksekusi_entry", None)
            if eks is not None and getattr(eks, "qty_terisi", 0) > 0:
                return True
        return False

    # ------------------------------------------------------------------ #
    # governor: snapshot akun
    # ------------------------------------------------------------------ #

    def _ambil_snapshot(self) -> SnapshotAkun:
        """Tarik SATU snapshot akun nyata untuk seluruh siklus ini.

        Bila `ambil_snapshot_akun` tidak disuntikkan, gunakan client langsung
        (`saldo()` + `posisi()`), yang harus tersedia pada BinanceFuturesClient.
        """
        if self.ambil_snapshot_akun is not None:
            return self.ambil_snapshot_akun()
        saldo = self.client.saldo()
        posisi = self.client.posisi()
        return snapshot_dari_akun(saldo, posisi)

    # ------------------------------------------------------------------ #
    # siklus
    # ------------------------------------------------------------------ #

    def _sisa_ban_ms(self) -> int:
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

    def siklus(self) -> RingkasanSiklus:
        if not self.runner:
            self.siapkan()

        self._tertolak_siklus = []
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

        if self.pemindai.perlu_segarkan():
            try:
                self.segarkan_pair()
                dipindai_ulang = True
            except Exception as exc:  # pemindaian gagal tidak boleh mematikan engine
                galat.append(f"segarkan_pair: {type(exc).__name__}: {exc}")

        if self.governor is not None:
            try:
                snapshot = self._ambil_snapshot()
            except Exception as exc:
                galat.append(f"snapshot_akun: {type(exc).__name__}: {exc}")
                # gagal aman: snapshot tanpa kapasitas -> semua entry ditolak
                # governor pada siklus ini, bukan diloloskan tanpa pengawasan.
                snapshot = SnapshotAkun(equity=0.0, margin_tersedia=0.0, posisi=())
            self.governor.mulai_siklus(snapshot)

        hasil: List[HasilSiklusPair] = []
        dilewati: List[str] = []
        sekarang_ms = int(self._jam())
        for (simbol, tf), runner in sorted(self.runner.items()):
            tfplan_runner = getattr(runner, "tfplan", None)
            ctx_tfs = tuple(getattr(tfplan_runner, "context_tfs", ()) or ())
            baris = HasilSiklusPair(simbol=simbol, entry_tf=tf, context_tfs=ctx_tfs)
            if not self._perlu_jalan((simbol, tf), runner, sekarang_ms):
                dilewati.append(f"{simbol}@{tf}")
                hasil.append(baris)
                continue
            self._jatuh_tempo[(simbol, tf)] = self._tempo_berikut(tf, sekarang_ms)
            try:
                s = runner.siklus_sekali()
            except Exception as exc:
                baris.galat = f"{type(exc).__name__}: {exc}"
                hasil.append(baris)
                galat.append(f"{simbol}@{tf}: {baris.galat}")
                continue
            baris.bar_baru = bool(getattr(s, "bar_baru", False))
            hb = getattr(s, "hasil_bar", None)
            if hb is not None and getattr(hb, "verdict", None) is not None:
                baris.ada_sinyal = True
            eks = getattr(s, "eksekusi_entry", None)
            if eks is not None and getattr(eks, "qty_terisi", 0) > 0:
                baris.ada_entry = True
            if getattr(s, "galat", None):
                baris.galat = str(s.galat)
                galat.append(f"{simbol}@{tf}: {s.galat}")
            hasil.append(baris)

        return RingkasanSiklus(
            waktu_ms=int(self._jam()),
            jumlah_runner=len(self.runner),
            pair=tuple(sorted({k[0] for k in self.runner})),
            hasil=tuple(hasil),
            dipindai_ulang=dipindai_ulang,
            galat=tuple(galat),
            sinyal_tertolak_governor=tuple(self._tertolak_siklus),
            dilewati_jadwal=tuple(dilewati),
            ban_sisa_ms=0,
        )

    def jalankan_selamanya(self, maks_putaran: Optional[int] = None) -> None:
        n = 0
        while maks_putaran is None or n < maks_putaran:
            ringkas = self.siklus()
            self._catat(str(ringkas.ringkas()))
            n += 1
            if maks_putaran is None or n < maks_putaran:
                self._tidur(self.interval_poll_detik)
