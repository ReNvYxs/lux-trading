"""Asap E2E: buktikan rantai LENGKAP jalan tanpa jaringan & tanpa uang.

Alur yang diuji persis seperti mode testnet/live, hanya `client`-nya palsu:

  konfigurasi (.env) -> konektor (fake) -> market data (klines) -> DataPlane
  -> FeatureStore -> strategi -> arbiter/skor -> risk management (sizing)
  -> rencana eksekusi (post-only + ice-breaker) -> order entry -> order SL
  (STOP_MARKET) -> ringkasan siklus -> notifikasi (Telegram)

Klien palsu memakai KURSOR waktu: tiap panggilan `klines` menyingkap satu bar
baru, persis seperti pasar sungguhan yang menutup lilin satu per satu. Dengan
begitu loop polling LiveRunner benar-benar diputar berkali-kali, bukan sekali.

Gunanya: menangkap "terlihat terintegrasi tapi meledak saat dijalankan". Skrip
ini TIDAK menyentuh jaringan sama sekali dan tidak pernah memuat kredensial asli.

    python scripts/asap_e2e.py
"""
from __future__ import annotations

import json
import os
import sys

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, AKAR)

from lux_modul import sintetis
from lux_modul.eksekusi.order import KebijakanOrder
from lux_modul.konfigurasi import muat_konfigurasi
from lux_modul.kontrak import HORIZON_INTRADAY, TFPlan
from lux_modul.live_runner import LiveRunner
from lux_modul.notifikasi import buat_notifier
from lux_modul.strategi import registry_bawaan

TF_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}
BAR_AWAL = 500  # jumlah bar yang sudah "tersedia" saat runner start


class KlienPalsu:
    """Tiruan BinanceFuturesClient: protokol sama, tanpa jaringan sama sekali."""

    def __init__(self, bars_per_tf, simbol="BTCUSDT", kursor=BAR_AWAL):
        self.bars_per_tf = bars_per_tf
        self.simbol = simbol
        self.tf_dasar = min(bars_per_tf, key=lambda tf: TF_MS[tf])
        self.kursor = kursor
        self.order_terkirim = []

    # -- kursor waktu ---------------------------------------------------- #

    def maju(self, langkah: int = 1) -> None:
        batas = len(self.bars_per_tf[self.tf_dasar])
        self.kursor = min(batas, self.kursor + langkah)

    def _batas_ts(self) -> int:
        b = self.bars_per_tf[self.tf_dasar]
        i = min(self.kursor, len(b)) - 1
        return int(b.ts[i]) + TF_MS[self.tf_dasar]

    # -- protokol klien --------------------------------------------------- #

    def waktu_server(self):
        return self._batas_ts()

    def klines(self, simbol, tf, limit=500):
        b = self.bars_per_tf[tf]
        batas_ts = self._batas_ts()
        baris = []
        for i in range(len(b)):
            ts = int(b.ts[i])
            if ts + TF_MS[tf] > batas_ts:
                break  # bar ini belum tutup pada waktu server sekarang
            baris.append(
                [ts, f"{b.open[i]}", f"{b.high[i]}", f"{b.low[i]}", f"{b.close[i]}",
                 f"{b.volume[i]}", ts + TF_MS[tf] - 1]
            )
        return baris[-limit:]

    def harga_sekarang(self, simbol):
        b = self.bars_per_tf[self.tf_dasar]
        return float(b.close[min(self.kursor, len(b)) - 1])

    def kirim_order(self, payload):
        self.order_terkirim.append(payload)
        return {
            "orderId": len(self.order_terkirim),
            "status": "NEW",
            "type": payload.get("type"),
        }

    def saldo_usdt(self):
        return 100.0


async def _kirim_async(client, payload):
    return client.kirim_order(payload)


def main() -> int:
    print("== ASAP E2E (tanpa jaringan, tanpa uang) ==\n")

    # 1. konfigurasi -------------------------------------------------------
    cfg = muat_konfigurasi()
    print("1. konfigurasi termuat:", json.dumps(cfg.ringkas(), ensure_ascii=False))
    notifier = buat_notifier(cfg)
    print(f"   notifier Telegram aktif: {getattr(notifier, 'aktif', False)}")

    # 2. market data (sintetis, berperan sebagai jawaban REST klines) ------
    b15 = sintetis.bars_tren_naik(n=1200, tf="15m", seed=7)
    b1h = sintetis.bars_tren_naik(n=1200, tf="1h", seed=8)
    client = KlienPalsu({"15m": b15, "1h": b1h})
    print(f"2. konektor palsu siap: 15m={len(b15)} bar, 1h={len(b1h)} bar, kursor={client.kursor}")

    # 3. rakit LiveRunner PERSIS seperti scripts/live_run.py ---------------
    runner = LiveRunner(
        client=client,
        simbol="BTCUSDT",
        tfplan=TFPlan(entry_tf="15m", context_tfs=("1h",)),
        horizon=HORIZON_INTRADAY,
        registry=registry_bawaan(),
        balance=100.0,
        leverage_maks=cfg.leverage_maks,
        margin_konflik=cfg.margin_konflik,
        kebijakan_order=KebijakanOrder(),
        kirim_order_async=_kirim_async,
        sekarang_ms=client.waktu_server,
        tidur=lambda d: None,
        interval_poll_detik=0.0,
    )
    runner.muat_riwayat_awal(limit=1000)
    print("3. riwayat awal termuat, pipeline terpasang")

    # 4. putar loop polling sungguhan: tiap iterasi satu lilin baru tutup --
    n_siklus = n_bar = n_sinyal = n_entry = n_sl = n_galat = 0
    galat_contoh = []
    for _ in range(600):
        client.maju(1)
        hasil = runner.siklus_sekali()
        n_siklus += 1
        if hasil.galat:
            n_galat += 1
            if len(galat_contoh) < 5:
                galat_contoh.append(hasil.galat)
        if hasil.bar_baru:
            n_bar += 1
        if hasil.hasil_bar is not None and hasil.hasil_bar.verdict is not None:
            n_sinyal += 1
        if hasil.eksekusi_entry is not None:
            n_entry += 1
            notifier.lapor_siklus(hasil.ringkas(), simbol="BTCUSDT", mode="asap")
        if hasil.order_sl is not None:
            n_sl += 1

    print(
        f"4. loop selesai: {n_siklus} siklus, {n_bar} bar baru diproses, "
        f"{n_sinyal} verdict, {n_entry} eksekusi entry, {n_sl} order SL, {n_galat} galat"
    )
    for g in galat_contoh:
        print("   galat:", g)

    tipe_order = {}
    for o in client.order_terkirim:
        t = o.get("type", "?")
        tipe_order[t] = tipe_order.get(t, 0) + 1
    print(f"5. order yang benar-benar dikirim ke konektor: {tipe_order or '(tidak ada)'}")

    # 6. pemeriksaan invariant yang WAJIB benar ---------------------------
    galat = []
    for o in client.order_terkirim:
        tipe = o.get("type")
        if tipe == "LIMIT" and o.get("timeInForce") != "GTX":
            galat.append(f"order LIMIT bukan post-only (GTX): {o}")
        if tipe == "MARKET":
            galat.append(f"order MARKET terkirim padahal diharamkan: {o}")
        if tipe == "STOP_MARKET" and not o.get("closePosition") and not o.get("reduceOnly"):
            galat.append(f"SL tidak reduceOnly/closePosition: {o}")
    if n_galat:
        galat.append(f"ada {n_galat} siklus bergalat (lihat contoh di atas)")
    if n_bar < 100:
        galat.append(f"hanya {n_bar} bar diproses - loop polling tidak benar-benar berputar")
    if n_entry and not n_sl:
        galat.append("ada entry terisi tetapi TIDAK ada order SL yang dikirim")

    if galat:
        print("\nHASIL: GAGAL")
        for g in galat:
            print(" -", g)
        return 1

    print("\nHASIL: LULUS - rantai main.py -> konfigurasi -> konektor -> data -> strategi")
    print("       -> risiko -> eksekusi -> SL -> pelaporan berjalan utuh tanpa galat.")
    if n_entry == 0:
        print("       Catatan: tidak ada entry pada data sintetis ini (arbiter memang ketat);")
        print("       jalur order tetap diuji terpisah di tests/test_order_postonly.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
