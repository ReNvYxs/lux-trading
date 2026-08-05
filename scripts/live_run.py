"""Titik eksekusi mode testnet & live - dipanggil oleh main.py lewat subprocess.

Satu skrip untuk KEDUA mode. Perbedaan testnet vs live murni ditentukan oleh
`--mode` yang diteruskan ke `muat_kredensial()` (lux_modul/eksekusi/kredensial.py):
base_url, nama variabel lingkungan kredensial, dan gerbang konfirmasi mode live
seluruhnya diurus di sana.

DUA JALUR EKSEKUSI (KEBIJAKAN 4 Agu 2026 - sistem TIDAK BTC-centric):

1. MULTI-PAIR (default, tanpa --simbol)
   Binance Market -> PemindaiPasar (likuiditas) -> 25..50 pair -> RencanaTF
   dari kontrak strategi (STF & MTF) -> LiveRunner per (pair, rencana).
   Tidak ada daftar pair hardcode, tidak ada TF entry yang dipaksa.

2. SATU PAIR (bila operator sengaja memberi --simbol)
   Dipakai untuk uji terarah/smoke test; TETAP memakai Pipeline yang sama.

Pemakaian:
  python3 scripts/live_run.py --mode testnet
  python3 scripts/live_run.py --mode testnet --simbol BTCUSDT --tf-entry 15m
  python3 scripts/live_run.py --mode live --konfirmasi-live --maks-siklus 1

Variabel lingkungan wajib (lihat kredensial.py untuk nama persis):
  Testnet : LUX_BINANCE_TESTNET_API_KEY, LUX_BINANCE_TESTNET_API_SECRET
  Live    : LUX_BINANCE_LIVE_API_KEY, LUX_BINANCE_LIVE_API_SECRET,
            LUX_LIVE_KONFIRMASI=SAYA_PAHAM_INI_AKUN_LIVE_DANA_ASLI

PERINGATAN: skrip ini memanggil endpoint Binance sungguhan (testnet atau live).
Konektor belum pernah diadu dengan jaringan nyata dari sandbox pengembangan
(lihat disclaimer di lux_modul/eksekusi/binance_client.py). Uji di testnet dulu.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi.binance_client import BinanceFuturesClient
from lux_modul.eksekusi.kredensial import KredensialError, muat_kredensial
from lux_modul.eksekusi.order import KebijakanOrder
from lux_modul.konfigurasi import muat_konfigurasi
from lux_modul.kontrak import HORIZON_INTRADAY, HORIZON_SCALPING, TFPlan
from lux_modul.live_runner import LiveRunner
from lux_modul.mesin_multi import MesinError, MesinMultiPair
from lux_modul.notifikasi import buat_notifier
from lux_modul.pemindai import PemindaiError
from lux_modul.rencana_tf import uraikan_daftar_tf
from lux_modul.strategi import registry_bawaan

HORIZON_PILIHAN = {"scalping": HORIZON_SCALPING, "intraday": HORIZON_INTRADAY}


def _saldo(client, override):
    if override is not None:
        return float(override)
    return client.saldo_usdt()


def _jalur_satu_pair(args, cfg, client, notifier, horizon, balance) -> int:
    """Mode terarah: satu simbol, satu TFPlan (uji/smoke test)."""
    ctx_tfs = uraikan_daftar_tf(args.tf_konteks or cfg.tf_konteks)
    tf_entry = args.tf_entry or (cfg.daftar_entry_tf()[0] if cfg.daftar_entry_tf() else None)
    if not tf_entry:
        print(
            "--simbol diberikan tetapi TF entry tidak. Beri --tf-entry atau isi LUX_TF_ENTRY.",
            file=sys.stderr,
        )
        return 5
    tfplan = TFPlan(entry_tf=tf_entry, context_tfs=ctx_tfs)
    print(f"simbol={args.simbol} tfplan={tfplan} horizon={horizon} balance={balance}", flush=True)

    runner = LiveRunner(
        client=client,
        simbol=args.simbol,
        tfplan=tfplan,
        horizon=horizon,
        registry=registry_bawaan(),
        balance=balance,
        leverage_maks=args.leverage_maks,
        margin_konflik=args.margin_konflik,
        kebijakan_order=KebijakanOrder(),
        interval_poll_detik=args.interval_poll,
    )
    runner.muat_riwayat_awal()
    print("riwayat awal termuat, mulai polling...", flush=True)
    if getattr(notifier, "aktif", False):
        notifier.kirim(
            f"[LUX {args.mode}] memantau {args.simbol} tf_entry={tf_entry} "
            f"horizon={args.horizon} balance={balance}"
        )
    else:
        print("(Telegram nonaktif - notifikasi hanya ke layar)", flush=True)

    n = 0
    try:
        while args.maks_siklus is None or n < args.maks_siklus:
            hasil = runner.siklus_sekali()
            ringkas = hasil.ringkas()
            print(json.dumps(ringkas, indent=2, ensure_ascii=False), flush=True)
            notifier.lapor_siklus(ringkas, simbol=args.simbol, mode=args.mode)
            n += 1
            if args.maks_siklus is None or n < args.maks_siklus:
                import time as _time

                _time.sleep(args.interval_poll)
    except KeyboardInterrupt:
        print("dihentikan operator (Ctrl+C)", flush=True)
        if getattr(notifier, "aktif", False):
            notifier.kirim(f"[LUX {args.mode}] dihentikan operator (Ctrl+C).")
    return 0


def _jalur_multi_pair(args, cfg, client, notifier, horizon, balance) -> int:
    """Mode utama: pemindaian pasar dinamis + engine multi-pair multi-TF."""
    kriteria = cfg.kriteria_pindai()
    entry_tfs = uraikan_daftar_tf(args.tf_entry) or cfg.daftar_entry_tf()

    mesin = MesinMultiPair(
        client=client,
        kriteria=kriteria,
        horizon=horizon,
        registry=registry_bawaan(),
        entry_tfs=entry_tfs,
        balance=balance,
        leverage_maks=args.leverage_maks,
        margin_konflik=args.margin_konflik,
        kebijakan_order=KebijakanOrder(),
        interval_poll_detik=args.interval_poll,
        maks_runner=args.maks_runner or cfg.maks_runner,
        pencatat=lambda pesan: print(pesan, flush=True),
    )

    try:
        laporan = mesin.siapkan()
    except (MesinError, PemindaiError) as exc:
        print(f"GAGAL menyiapkan engine multi-pair: {exc}", file=sys.stderr)
        return 5

    print(json.dumps(laporan, indent=2, ensure_ascii=False, default=str), flush=True)
    pair = sorted({s for s, _ in mesin.runner})
    print(f"pair aktif ({len(pair)}): {', '.join(pair)}", flush=True)
    if getattr(notifier, "aktif", False):
        notifier.kirim(
            f"[LUX {args.mode}] engine multi-pair mulai: {len(pair)} pair, "
            f"{len(mesin.rencana)} rencana TF, horizon={args.horizon}, balance={balance}"
        )
    else:
        print("(Telegram nonaktif - notifikasi hanya ke layar)", flush=True)

    n = 0
    try:
        while args.maks_siklus is None or n < args.maks_siklus:
            ringkas = mesin.siklus().ringkas()
            print(json.dumps(ringkas, ensure_ascii=False, default=str), flush=True)
            notifier.lapor_siklus(ringkas, simbol=f"{len(ringkas.get('pair', []))} pair", mode=args.mode)
            n += 1
            if args.maks_siklus is None or n < args.maks_siklus:
                import time as _time

                _time.sleep(args.interval_poll)
    except KeyboardInterrupt:
        print("dihentikan operator (Ctrl+C)", flush=True)
        if getattr(notifier, "aktif", False):
            notifier.kirim(f"[LUX {args.mode}] dihentikan operator (Ctrl+C).")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="live_run.py",
        description="Jalankan modul trading LUX real-time di Binance Futures (testnet/live)",
    )
    p.add_argument("--mode", required=True, choices=["testnet", "live"])
    p.add_argument(
        "--simbol",
        default="",
        help="KOSONGKAN untuk memindai pasar (25-50 pair paling likuid). Isi hanya untuk uji satu pair.",
    )
    p.add_argument(
        "--tf-entry",
        default="",
        help="kosong = ikuti kontrak strategi/horizon; boleh daftar dipisah koma untuk multi-pair",
    )
    p.add_argument("--tf-konteks", default="", help="khusus mode satu pair; kosong = single-TF")
    p.add_argument("--horizon", default="intraday", choices=list(HORIZON_PILIHAN))
    p.add_argument("--balance", type=float, default=None, help="override saldo; default: tarik dari akun")
    p.add_argument(
        "--leverage-maks",
        type=float,
        default=None,
        help="BATAS ATAS saja, bukan leverage tetap. Leverage per setup dihitung otomatis "
        "(Risk -> Notional -> Margin -> Leverage) di eksekusi/spesifikasi.py.",
    )
    p.add_argument("--margin-konflik", type=float, default=None)
    p.add_argument("--interval-poll", type=float, default=None, help="detik antar polling")
    p.add_argument("--maks-runner", type=int, default=None, help="batas jumlah runner (pair x rencana TF)")
    p.add_argument("--maks-siklus", type=int, default=None, help="batas siklus (uji manual); default: tanpa batas")
    p.add_argument(
        "--konfirmasi-live",
        action="store_true",
        help="gerbang keamanan 1/2 untuk --mode live (wajib bersama LUX_LIVE_KONFIRMASI)",
    )
    args = p.parse_args(argv)

    # Muat .env lebih dulu supaya kredensial & setelan Telegram tersedia di
    # os.environ walau skrip ini dipanggil langsung (bukan lewat main.py).
    cfg = muat_konfigurasi()
    notifier = buat_notifier(cfg)

    # .env = KONFIGURASI, bukan batasan: argumen CLI menang, lalu .env, lalu default.
    if args.leverage_maks is None:
        args.leverage_maks = cfg.leverage_maks
    if args.margin_konflik is None:
        args.margin_konflik = cfg.margin_konflik
    if args.interval_poll is None:
        args.interval_poll = cfg.interval_poll
    if args.maks_siklus is None:
        args.maks_siklus = cfg.maks_siklus
    if not args.simbol and cfg.daftar_simbol():
        args.simbol = cfg.daftar_simbol()[0]
    args.simbol = (args.simbol or "").upper()

    try:
        kredensial = muat_kredensial(args.mode, konfirmasi_live_cli=args.konfirmasi_live)
    except KredensialError as exc:
        print(f"GAGAL memuat kredensial: {exc}", file=sys.stderr)
        return 2

    print(f"== mode {args.mode} == kredensial: {json.dumps(kredensial.ringkas())}", flush=True)

    client = BinanceFuturesClient(kredensial)
    try:
        client.sinkron_waktu()
    except Exception as exc:
        print(f"GAGAL sinkronisasi waktu server Binance: {exc}", file=sys.stderr)
        print("Periksa koneksi jaringan dan base_url. Tidak ada order yang dikirim.", file=sys.stderr)
        return 3

    horizon = HORIZON_PILIHAN[args.horizon]

    try:
        balance = _saldo(client, args.balance)
    except Exception as exc:
        print(f"GAGAL menarik saldo akun, pakai --balance eksplisit: {exc}", file=sys.stderr)
        return 4

    if args.simbol:
        print("MODE SATU PAIR (uji terarah) - kosongkan --simbol untuk engine multi-pair.", flush=True)
        return _jalur_satu_pair(args, cfg, client, notifier, horizon, balance)
    return _jalur_multi_pair(args, cfg, client, notifier, horizon, balance)


if __name__ == "__main__":
    raise SystemExit(main())
