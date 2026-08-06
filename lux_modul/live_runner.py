"""L5 - LiveRunner dengan bracket tracking lengkap.

Perubahan utama (4 Agu 2026):
1. Bracket tracking: entry LIMIT GTX ditempatkan -> orderId disimpan di
   `_pending_entry`. Siklus berikutnya: poll status order. Bila FILLED ->
   kirim SL (STOP_MARKET) DAN TP (TAKE_PROFIT_MARKET), simpan ke
   `_bracket_aktif`.
2. Monitor bracket aktif: poll status SL/TP. Bila salah satu tertrigger ->
   batalkan sisi lainnya (one-cancels-other sederhana) + notifikasi Telegram.
3. Telegram event-driven: hanya untuk scalp/intraday yang benar-benar di-entry.
   Event: setup entry terpasang, entry terisi, TP tertrigger, SL tertrigger.
4. `pemeriksa_entry_fn`: callback opsional dari GovernorPortofolio di
   MesinMultiPair untuk batasan posisi global. GAGAL AMAN: bila callback ini
   melempar exception (governor tidak terhubung dsb), entry DITOLAK pada
   siklus itu -- tidak pernah diloloskan tanpa pengawasan.

Arsitektur:
  siklus_sekali()
    |-> _periksa_entry_pending()   [cek fill entry, kirim bracket]
    |-> _periksa_bracket_aktif()   [cek fill SL/TP, notif, OCO]
    |-> pipeline.jalankan(i)       [sinyal baru]
    |-> governor? pemeriksa_entry_fn
    |-> IceBreakerExecutor          [order entry]
    '-> _pending_entry[orderId]     [simpan untuk poll berikutnya]
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from .data.loader import GalatData
from .data.plane import DataPlane
from .eksekusi.ice_breaker import HasilEksekusi, IceBreakerExecutor
from .eksekusi.mode import boleh_auto_entry
from .eksekusi.order import (
    KebijakanOrder,
    payload_bracket,
    payload_sl,
    payload_tp_market,
)
from .eksekusi.spesifikasi import SpesifikasiKontrak
from .eksekusi_aman.saklar import aman_aktif, pasang_proteksi_aman
from .kontrak import Bars, HORIZON_INTRADAY, MODE_SIGNAL_ONLY, TFPlan, tf_ms
from .pipeline import HasilBar, Pipeline
from .strategi import Registry

KLINES_LIMIT_AWAL = 1000
# Penyegaran hanya butuh bar yang benar-benar baru. Sebelumnya dipatok 200 bar
# per TF per runner per siklus - pemborosan bobot rate-limit yang menjadi salah
# satu penyebab ban IP 418/-1003 saat menjalankan 29 pair.
KLINES_LIMIT_SEGAR_MIN = 3
KLINES_LIMIT_SEGAR_MAKS = 500
BAR_CADANGAN_SEGAR = 2
BRACKET_POLL_TIMEOUT_MS = 4 * 3600 * 1000   # entry max 4 jam menunggu fill
MONITOR_TIMEOUT_MS = 7 * 24 * 3600 * 1000   # SL/TP dipantau max 7 hari


def tp_pertama(verdict: Any) -> float:
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


class LiveRunnerError(Exception):
    pass


@dataclass
class _EntryPending:
    """Entry LIMIT yang sudah dikirim ke bursa, menunggu fill."""
    order_id: int
    simbol: str
    arah: str
    sl_price: float
    tp_price: float       # 0 = tidak ada TP dari sinyal ini
    qty: float
    entry_price: float
    dibuat_ms: int
    skor: float = 0.0
    strategi: str = ""
    setup_teks: str = ""  # untuk Telegram


@dataclass
class _BracketAktif:
    """SL+TP sudah dipasang di bursa, pantau untuk notifikasi + OCO."""
    simbol: str
    arah: str
    sl_order_id: Optional[int]
    tp_order_id: Optional[int]
    entry_price: float
    sl_price: float
    tp_price: float
    qty: float
    dipasang_ms: int
    skor: float = 0.0
    strategi: str = ""


@dataclass
class SiklusHasil:
    ts_server: int = 0
    bar_baru: bool = False
    hasil_bar: Optional[HasilBar] = None
    eksekusi_entry: Optional[HasilEksekusi] = None
    order_sl: Optional[Dict[str, Any]] = None
    order_tp: Optional[Dict[str, Any]] = None
    galat: Optional[str] = None
    catatan: Optional[str] = None
    alasan_ditolak_governor: Optional[str] = None

    def ringkas(self) -> Dict[str, Any]:
        return {
            "ts_server": self.ts_server,
            "bar_baru": self.bar_baru,
            "galat": self.galat,
            "catatan": self.catatan,
            "alasan_ditolak_governor": self.alasan_ditolak_governor,
            "eksekusi_entry": (
                {
                    "qty_terisi": getattr(self.eksekusi_entry, "qty_terisi", 0),
                    "terkirim": getattr(self.eksekusi_entry, "terkirim", 0),
                    "dibatalkan": getattr(self.eksekusi_entry, "dibatalkan", 0),
                    "alasan_batal": getattr(self.eksekusi_entry, "alasan_batal", None),
                }
                if self.eksekusi_entry is not None
                else None
            ),
            "hasil_bar": (
                {
                    "mode": getattr(self.hasil_bar, "mode", None),
                    "verdict": (
                        vars(self.hasil_bar.verdict) if getattr(self.hasil_bar, "verdict", None) else None
                    ),
                    "skor": getattr(getattr(self.hasil_bar, "verdict", None), "skor", None),
                }
                if self.hasil_bar is not None
                else None
            ),
        }


class LiveRunner:
    """Satu pair + satu TFPlan, dijalankan terus-menerus."""

    def __init__(
        self,
        client: Any,
        simbol: str,
        tfplan: TFPlan,
        horizon: str = HORIZON_INTRADAY,
        registry: Optional[Registry] = None,
        balance: float = 100.0,
        leverage_maks: float = 20.0,
        margin_konflik: float = 5.0,
        kebijakan_order: Optional[KebijakanOrder] = None,
        kirim_order_async: Optional[Callable] = None,
        sekarang_ms: Optional[Callable[[], int]] = None,
        tidur: Optional[Callable[[float], None]] = None,
        interval_poll_detik: float = 15.0,
        notifier: Optional[Any] = None,
        pemeriksa_entry_fn: Optional[Callable[[Dict[str, Any]], Tuple[bool, Optional[str]]]] = None,
    ) -> None:
        self.client = client
        self.simbol = simbol
        self.tfplan = tfplan
        self.horizon = horizon
        self.registry = registry
        self.balance = float(balance)
        self.leverage_maks = float(leverage_maks)
        self.margin_konflik = float(margin_konflik)
        self.kebijakan_order = kebijakan_order or KebijakanOrder()
        self._kirim_order_async = kirim_order_async
        self._sekarang_ms = sekarang_ms or (lambda: int(time.time() * 1000))
        self._tidur = tidur or time.sleep
        self.interval_poll_detik = float(interval_poll_detik)
        self.notifier = notifier
        self.pemeriksa_entry_fn = pemeriksa_entry_fn

        self.plane: Optional[DataPlane] = None
        self.pipeline: Optional[Pipeline] = None
        self.spek: Optional[SpesifikasiKontrak] = None
        self._indeks_terakhir_diproses: int = -1
        self._leverage_terpasang: int = 0
        self.riwayat_siklus: List[SiklusHasil] = []

        # bracket tracking
        self._pending_entry: Dict[int, _EntryPending] = {}
        self._bracket_aktif: Dict[str, _BracketAktif] = {}
        self._proteksi_aman: Dict[str, Any] = {}

    def _kirim(self, payload: Dict[str, Any]) -> Any:
        return self.client.kirim_order(payload)

    def _harga_kini(self, simbol: str) -> float:
        return float(self.client.harga_sekarang(simbol))

    def muat_spek(self) -> SpesifikasiKontrak:
        try:
            info = self.client.exchange_info(self.simbol)
            spek = None
            for s in info.get("symbols", []):
                if s.get("symbol") == self.simbol:
                    try:
                        bracket = self.client.bracket_leverage(self.simbol)
                    except Exception:  # noqa: BLE001
                        bracket = ()
                    spek = SpesifikasiKontrak.dari_exchange_info(s, bracket=bracket)
                    break
            if spek is None:
                raise LiveRunnerError(f"{self.simbol} tidak ada di exchangeInfo")
        except LiveRunnerError:
            raise
        except Exception:  # noqa: BLE001
            spek = SpesifikasiKontrak(
                simbol=self.simbol, leverage_maks_simbol=float(self.leverage_maks)
            )
        self.spek = spek
        if spek.tick_size > 0 and self.kebijakan_order.tick_size <= 0:
            self.kebijakan_order = replace(self.kebijakan_order, tick_size=spek.tick_size)
        return spek

    def muat_riwayat_awal(self, limit: int = KLINES_LIMIT_AWAL) -> None:
        if self.spek is None:
            self.muat_spek()
        waktu_server = self.client.waktu_server()
        peta: Dict[str, Bars] = {}
        for tf in self.tfplan.semua_tf():
            mentah = self.client.klines(self.simbol, tf, limit=limit)
            bars = _bars_dari_klines(mentah, tf, self.simbol)
            bars = _buang_bar_belum_tutup(bars, waktu_server)
            if len(bars) < 2:
                raise LiveRunnerError(f"riwayat awal {tf} terlalu pendek: {len(bars)} bar")
            peta[tf] = bars
        self.plane = DataPlane(peta)
        self.pipeline = Pipeline(
            plane=self.plane,
            tfplan=self.tfplan,
            horizon=self.horizon,
            registry=self.registry,
            balance=self.balance,
            leverage_maks=self.leverage_maks,
            margin_konflik=self.margin_konflik,
            spek=self.spek,
        )
        self._indeks_terakhir_diproses = len(self.plane.bars(self.tfplan.entry_tf)) - 2

    def _limit_segar(self, lama: Bars, tf: str, waktu_server: int) -> int:
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
            mentah = self.client.klines(self.simbol, tf, limit=limit_tf)
            segar = _bars_dari_klines(mentah, tf, self.simbol)
            segar = _buang_bar_belum_tutup(segar, waktu_server)
            gabung = _gabung_bars(lama, segar)
            peta_baru[tf] = gabung
        self.plane = DataPlane(peta_baru)
        assert self.pipeline is not None
        self.pipeline.plane = self.plane
        return waktu_server

    # ------------------------------------------------------------------ #
    # bracket tracking: poll entry pending
    # ------------------------------------------------------------------ #

    def _periksa_entry_pending(self) -> List[str]:
        """Poll status entry pending; kirim SL+TP bila sudah terisi."""
        if not self._pending_entry:
            return []
        galat: List[str] = []
        kini_ms = self._sekarang_ms()
        selesai: List[int] = []

        for oid, ep in list(self._pending_entry.items()):
            if kini_ms - ep.dibuat_ms > BRACKET_POLL_TIMEOUT_MS:
                selesai.append(oid)
                try:
                    self.client.batalkan_order(ep.simbol, oid)
                except Exception:  # noqa: BLE001
                    pass
                continue

            try:
                status = self.client.status_order(ep.simbol, oid)
            except Exception as exc:  # noqa: BLE001
                galat.append(f"status_order_{oid}: {exc}")
                continue

            state = str(status.get("status", ""))
            if state in ("CANCELED", "EXPIRED", "REJECTED"):
                selesai.append(oid)
                continue

            avg_price = float(status.get("avgPrice") or ep.entry_price or 0)
            qty_terisi = float(status.get("executedQty") or 0)

            if state not in ("FILLED", "PARTIALLY_FILLED") or qty_terisi <= 0:
                continue

            sl_order_id: Optional[int] = None
            tp_order_id: Optional[int] = None

            sl_order_id, tp_order_id = self._pasang_proteksi_pending(ep, oid, galat)

            self._bracket_aktif[ep.simbol] = _BracketAktif(
                simbol=ep.simbol, arah=ep.arah,
                sl_order_id=sl_order_id, tp_order_id=tp_order_id,
                entry_price=avg_price or ep.entry_price,
                sl_price=ep.sl_price, tp_price=ep.tp_price,
                qty=qty_terisi, dipasang_ms=kini_ms,
                skor=ep.skor, strategi=ep.strategi,
            )

            if self.notifier is not None:
                try:
                    self.notifier.lapor_entry_terisi(
                        simbol=ep.simbol, arah=ep.arah,
                        entry_price=avg_price or ep.entry_price,
                        sl_price=ep.sl_price, tp_price=ep.tp_price,
                        qty=qty_terisi, strategi=ep.strategi, skor=ep.skor,
                    )
                except Exception:  # noqa: BLE001
                    pass

            if state == "FILLED":
                selesai.append(oid)

        for oid in selesai:
            self._pending_entry.pop(oid, None)
        return galat

    # ------------------------------------------------------------------ #
    # bracket tracking: monitor SL/TP aktif
    # ------------------------------------------------------------------ #

    def _periksa_bracket_aktif(self) -> List[str]:
        """Poll status SL/TP; notifikasi + OCO bila salah satu tertrigger."""
        galat_sl_aman = self._periksa_sl_aman()
        if not self._bracket_aktif:
            return galat_sl_aman
        galat: List[str] = list(galat_sl_aman)
        kini_ms = self._sekarang_ms()
        selesai: List[str] = []

        for simbol, br in list(self._bracket_aktif.items()):
            if kini_ms - br.dipasang_ms > MONITOR_TIMEOUT_MS:
                selesai.append(simbol)
                continue

            sl_tertrigger = False
            tp_tertrigger = False

            if br.sl_order_id is not None:
                try:
                    s = self.client.status_order(simbol, br.sl_order_id)
                    if str(s.get("status", "")) == "FILLED":
                        sl_tertrigger = True
                except Exception as exc:  # noqa: BLE001
                    galat.append(f"status_sl_{br.sl_order_id}: {exc}")

            if br.tp_order_id is not None and not sl_tertrigger:
                try:
                    s = self.client.status_order(simbol, br.tp_order_id)
                    if str(s.get("status", "")) == "FILLED":
                        tp_tertrigger = True
                except Exception as exc:  # noqa: BLE001
                    galat.append(f"status_tp_{br.tp_order_id}: {exc}")

            if sl_tertrigger:
                if br.tp_order_id is not None:
                    try:
                        self.client.batalkan_order(simbol, br.tp_order_id)
                    except Exception:  # noqa: BLE001
                        pass
                if self.notifier is not None:
                    try:
                        self.notifier.lapor_sl_tertrigger(
                            simbol=simbol, arah=br.arah,
                            sl_price=br.sl_price, qty=br.qty, strategi=br.strategi,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                selesai.append(simbol)

            elif tp_tertrigger:
                if br.sl_order_id is not None:
                    try:
                        self.client.batalkan_order(simbol, br.sl_order_id)
                    except Exception:  # noqa: BLE001
                        pass
                if self.notifier is not None:
                    try:
                        self.notifier.lapor_tp_tertrigger(
                            simbol=simbol, arah=br.arah,
                            tp_price=br.tp_price, qty=br.qty, strategi=br.strategi,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                selesai.append(simbol)

        for s in selesai:
            self._bracket_aktif.pop(s, None)
        return galat

    # ------------------------------------------------------------------ #
    # satu siklus
    # ------------------------------------------------------------------ #

    def siklus_sekali(self) -> SiklusHasil:
        if self.plane is None or self.pipeline is None:
            self.muat_riwayat_awal()
        assert self.plane is not None and self.pipeline is not None

        galat_bracket: List[str] = []
        galat_bracket += self._periksa_entry_pending()
        galat_bracket += self._periksa_bracket_aktif()

        try:
            ts_server = self._segarkan_plane()
        except Exception as exc:
            return SiklusHasil(
                ts_server=self._sekarang_ms(), bar_baru=False,
                galat=f"segarkan_plane: {exc}",
            )

        entry = self.plane.bars(self.tfplan.entry_tf)
        i = len(entry) - 1
        if i <= self._indeks_terakhir_diproses:
            galat_str = "; ".join(galat_bracket) if galat_bracket else None
            return SiklusHasil(ts_server=ts_server, bar_baru=False, galat=galat_str)

        self._indeks_terakhir_diproses = i
        try:
            hasil_bar = self.pipeline.jalankan(i)
        except Exception as exc:
            return SiklusHasil(ts_server=ts_server, bar_baru=True, galat=f"pipeline.jalankan: {exc}")

        siklus = SiklusHasil(ts_server=ts_server, bar_baru=True, hasil_bar=hasil_bar)
        if galat_bracket:
            siklus.galat = "; ".join(galat_bracket)

        if hasil_bar.mode == MODE_SIGNAL_ONLY or hasil_bar.rencana is None:
            return siklus
        if not boleh_auto_entry(self.horizon):
            return siklus  # swing = signal-only, tidak pernah auto-entry

        # governor check - GAGAL AMAN: bila governor tidak bisa dihubungi,
        # entry DITOLAK pada siklus ini, bukan diloloskan tanpa pengawasan.
        if self.pemeriksa_entry_fn is not None:
            v = getattr(hasil_bar, "verdict", None)
            kandidat = {
                "simbol": self.simbol,
                "horizon": self.horizon,
                "skor": getattr(v, "skor", 0),
                "arah": getattr(v, "arah", ""),
                "margin_dibutuhkan": (
                    getattr(hasil_bar.posisi, "margin_dibutuhkan", 0)
                    if hasil_bar.posisi is not None else 0
                ),
            }
            try:
                diizinkan, alasan = self.pemeriksa_entry_fn(kandidat)
            except Exception as exc:  # noqa: BLE001
                siklus.catatan = f"governor_error: {exc}"
                siklus.alasan_ditolak_governor = "governor_error"
                return siklus
            if not diizinkan:
                siklus.alasan_ditolak_governor = alasan
                return siklus

        # leverage
        posisi = hasil_bar.posisi
        if posisi is not None and posisi.leverage_optimal > 0:
            lev = int(posisi.leverage_optimal)
            pasang = getattr(self.client, "atur_leverage", None)
            if pasang is None:
                siklus.catatan = f"atur_leverage tidak tersedia; optimal x{lev}"
            elif lev != self._leverage_terpasang:
                try:
                    pasang(self.simbol, lev)
                    self._leverage_terpasang = lev
                except Exception as exc:
                    siklus.galat = f"atur_leverage: {exc}"
                    return siklus

        # eksekusi
        eksekutor = IceBreakerExecutor(
            kirim_order=self._kirim,
            harga_kini=self._harga_kini,
            kebijakan=self.kebijakan_order,
        )
        try:
            eksekusi = eksekutor.jalankan_sinkron(hasil_bar.rencana)
            siklus.eksekusi_entry = eksekusi
        except Exception as exc:
            siklus.galat = f"eksekusi_entry: {exc}"
            return siklus

        v = hasil_bar.verdict

        if eksekusi.qty_terisi <= 0:
            # entry LIMIT pending, simpan untuk dipoll
            for sl_item in reversed(getattr(eksekusi, "slices", []) or []):
                oid = getattr(sl_item, "order_id", None)
                if oid is not None and oid > 0:
                    tp_price = tp_pertama(v)
                    self._pending_entry[oid] = _EntryPending(
                        order_id=oid,
                        simbol=self.simbol,
                        arah=v.arah if v else "",
                        sl_price=posisi.sl if posisi else getattr(v, "sl", 0),
                        tp_price=tp_price,
                        qty=getattr(sl_item, "qty", 0),
                        entry_price=getattr(sl_item, "harga", 0),
                        dibuat_ms=self._sekarang_ms(),
                        skor=getattr(v, "skor", 0.0) if v else 0.0,
                        strategi=strategi_verdict(v),
                    )
                    break
            return siklus

        # entry langsung terisi
        assert v is not None
        sl_price = posisi.sl if posisi is not None else v.sl
        tp_price = tp_pertama(v)

        sl_order_id, tp_order_id = self._pasang_proteksi(v, sl_price, tp_price, siklus)

        self._bracket_aktif[self.simbol] = _BracketAktif(
            simbol=self.simbol, arah=v.arah,
            sl_order_id=sl_order_id, tp_order_id=tp_order_id,
            entry_price=float(eksekusi.harga_rata or 0),
            sl_price=sl_price, tp_price=tp_price,
            qty=eksekusi.qty_terisi, dipasang_ms=self._sekarang_ms(),
            skor=getattr(v, "skor", 0.0),
            strategi=strategi_verdict(v),
        )

        if self.notifier is not None:
            try:
                self.notifier.lapor_entry_dikirim(
                    simbol=self.simbol, arah=v.arah,
                    entry_price=float(eksekusi.harga_rata or 0),
                    sl_price=sl_price, tp_price=tp_price,
                    qty=eksekusi.qty_terisi,
                    strategi=strategi_verdict(v),
                    skor=getattr(v, "skor", 0.0),
                    horizon=self.horizon,
                )
            except Exception:  # noqa: BLE001
                pass

        return siklus

    # Saklar proteksi. Default jalur lama; LUX_EKSEKUSI=aman memakai lapisan
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
        n = 0
        while maks_siklus is None or n < maks_siklus:
            hasil = self.siklus_sekali()
            self.riwayat_siklus.append(hasil)
            if len(self.riwayat_siklus) > 500:
                self.riwayat_siklus = self.riwayat_siklus[-500:]
            n += 1
            if maks_siklus is None or n < maks_siklus:
                self._tidur(self.interval_poll_detik)


# ------------------------------------------------------------------ #
# utilitas bar
# ------------------------------------------------------------------ #

def _bars_dari_klines(klines, tf: str, simbol: str) -> Bars:
    if not klines:
        raise GalatData(f"klines kosong untuk {simbol} {tf}")
    ts = np.array([int(k[0]) for k in klines], dtype=np.int64)
    o = np.array([float(k[1]) for k in klines], dtype=np.float64)
    h = np.array([float(k[2]) for k in klines], dtype=np.float64)
    l = np.array([float(k[3]) for k in klines], dtype=np.float64)
    c = np.array([float(k[4]) for k in klines], dtype=np.float64)
    v = np.array([float(k[5]) for k in klines], dtype=np.float64)
    return Bars(tf=tf, ts=ts, open=o, high=h, low=l, close=c, volume=v, simbol=simbol)


def _buang_bar_belum_tutup(bars: Bars, waktu_server_ms: int) -> Bars:
    if len(bars) == 0:
        return bars
    if bars.ts_tutup(len(bars) - 1) > waktu_server_ms:
        return bars.potong(0, len(bars) - 1)
    return bars


def _gabung_bars(lama: Bars, segar: Bars) -> Bars:
    if len(segar) == 0:
        return lama
    ts_segar_awal = int(segar.ts[0])
    potong_di = int(np.searchsorted(np.asarray(lama.ts, dtype=np.int64), ts_segar_awal, side="left"))
    sisa_lama = lama.potong(0, potong_di)
    if len(sisa_lama) == 0:
        return segar
    ts = np.concatenate([sisa_lama.ts, segar.ts])
    o = np.concatenate([sisa_lama.open, segar.open])
    h = np.concatenate([sisa_lama.high, segar.high])
    l = np.concatenate([sisa_lama.low, segar.low])
    c = np.concatenate([sisa_lama.close, segar.close])
    v = np.concatenate([sisa_lama.volume, segar.volume])
    return Bars(tf=lama.tf, ts=ts, open=o, high=h, low=l, close=c, volume=v, simbol=lama.simbol)
