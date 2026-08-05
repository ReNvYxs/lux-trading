"""Titik masuk TUNGGAL modul trading LUX.

Cara termudah (Windows PowerShell / bash), tanpa argumen apa pun:

    python main.py

Tanpa argumen, main.py membuka MENU INTERAKTIF: ia memuat `.env`, menampilkan
status kredensial (disamarkan), lalu meminta Anda memilih mode. Tidak ada berkas
lain yang perlu dijalankan manual.

Masih tersedia pemakaian non-interaktif (untuk cron/CI/skrip):

    python main.py --mode uji
    python main.py --mode backtest --label single_15m
    python main.py --mode backtest --label single_15m --portofolio --simbol BTC,ETH,SOL
    python main.py --mode dashboard
    python main.py --mode konfigurasi
    python main.py --mode testnet                      (multi-pair: pindai pasar sendiri)
    python main.py --mode testnet --simbol-live BTCUSDT --tf-entry 15m   (uji satu pair)
    python main.py --mode live --konfirmasi-live       (multi-pair, DANA ASLI)

Tiga mode trading (lihat ARSITEKTUR.md bagian LiveRunner):
  1. backtest  - data historis CSV, TANPA order nyata.
  2. testnet   - real-time di Binance Futures TESTNET (dana mainan).
  3. live      - real-time di Binance Futures LIVE (DANA ASLI). Wajib DUA
                 gerbang keamanan sekaligus: konfirmasi eksplisit (argumen
                 --konfirmasi-live atau ketik ulang frasa di menu) DAN variabel
                 lingkungan LUX_LIVE_KONFIRMASI. Lihat lux_modul/eksekusi/kredensial.py.

Ketiga mode memanggil Pipeline/Registry strategi yang SAMA PERSIS
(lux_modul/pipeline.py, lux_modul/strategi/). Yang berbeda hanya sumber data
(CSV vs REST klines) dan apakah rencana eksekusi dikirim ke exchange.

Semua kredensial dibaca dari variabel lingkungan / berkas `.env` lewat
lux_modul/konfigurasi.py - TIDAK ADA rahasia yang di-hardcode di source code.

Catatan jujur: konektor Binance (lux_modul/eksekusi/binance_client.py) diuji
dengan unit test bermock di sandbox TANPA akses jaringan keluar - ia belum pernah
diadu dengan server Binance sungguhan. Jalankan `--mode testnet` dulu.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

AKAR = os.path.dirname(os.path.abspath(__file__))
if AKAR not in sys.path:
    sys.path.insert(0, AKAR)

PYTHON = sys.executable or "python3"

from lux_modul.eksekusi.kredensial import FRASA_KONFIRMASI_LIVE  # noqa: E402
from lux_modul.konfigurasi import (  # noqa: E402
    BERKAS_ENV_CONTOH,
    BERKAS_ENV_DEFAULT,
    KonfigurasiError,
    muat_konfigurasi,
    status_kredensial,
)

LABEL_VALID = ("single_5m", "multi_5m_ctx15m", "single_15m", "multi_15m_ctx1h")


def _jalankan(perintah, env_tambahan=None):
    """Jalankan sub-proses dengan working dir akar repo, kembalikan return code."""
    env = os.environ.copy()
    if env_tambahan:
        for k, v in env_tambahan.items():
            if v is not None:
                env[k] = str(v)
    proses = subprocess.run(perintah, cwd=AKAR, env=env)
    return proses.returncode


# ====================================================================== #
# mode non-interaktif
# ====================================================================== #


def mode_uji(args):
    print("== mode uji: menjalankan seluruh tests/test_*.py ==", flush=True)
    return _jalankan([PYTHON, os.path.join("scripts", "jalankan_uji.py")])


def mode_backtest(args):
    if args.label not in LABEL_VALID:
        print(
            f"label tidak dikenal: {args.label!r}. Pilihan: {', '.join(LABEL_VALID)}",
            file=sys.stderr,
        )
        return 2

    if args.portofolio:
        print(f"== mode backtest (portofolio, banyak simbol) label={args.label} ==", flush=True)
        env = {
            "LUX_DATA_DIR": args.data_dir,
            "LUX_MAKS_BAR": args.maks_bar,
            "LUX_MAKS_POS": args.maks_posisi,
            "LUX_SUFIKS": args.sufiks,
        }
        perintah = [PYTHON, os.path.join("scripts", "bt_portofolio.py"), args.label]
        if args.simbol:
            perintah.append(args.simbol)
    else:
        print(f"== mode backtest (satu simbol BTC) label={args.label} ==", flush=True)
        env = {
            "LUX_DATA_DIR": args.data_dir,
            "LUX_SUFIKS": args.sufiks,
        }
        perintah = [PYTHON, os.path.join("scripts", "bt_satu.py"), args.label]

    return _jalankan(perintah, env)


def mode_dashboard(args):
    print("== mode dashboard: membangkitkan ulang dashboard/data.json dari reports/ ==", flush=True)
    return _jalankan([PYTHON, os.path.join("scripts", "dashboard_data.py")])


def mode_konfigurasi(args):
    """Tampilkan status konfigurasi & kredensial (nilai rahasia disamarkan)."""
    return 0 if _cetak_status() else 0


def _perintah_live_run(args, mode):
    perintah = [
        PYTHON,
        os.path.join("scripts", "live_run.py"),
        "--mode", mode,
        "--horizon", args.horizon,
        "--leverage-maks", str(args.leverage_maks),
        "--margin-konflik", str(args.margin_konflik),
        "--interval-poll", str(args.interval_poll),
    ]
    if args.simbol_live:
        perintah += ["--simbol", args.simbol_live]
    if args.tf_entry:
        perintah += ["--tf-entry", args.tf_entry]
    if args.tf_konteks:
        perintah += ["--tf-konteks", args.tf_konteks]
    if getattr(args, "maks_runner", None):
        perintah += ["--maks-runner", str(args.maks_runner)]
    if args.balance_live is not None:
        perintah += ["--balance", str(args.balance_live)]
    if args.maks_siklus is not None:
        perintah += ["--maks-siklus", str(args.maks_siklus)]
    if mode == "live" and args.konfirmasi_live:
        perintah.append("--konfirmasi-live")
    return perintah


def mode_testnet(args):
    print(
        f"== mode testnet: {args.simbol_live or '(multi-pair: pindai pasar)'} "
        f"tf_entry={args.tf_entry or '(ikuti kontrak strategi)'} "
        f"horizon={args.horizon} ==",
        flush=True,
    )
    return _jalankan(_perintah_live_run(args, "testnet"))


def mode_live(args):
    if not args.konfirmasi_live:
        print(
            "Mode 'live' wajib argumen --konfirmasi-live SEKALIGUS variabel\n"
            f"lingkungan LUX_LIVE_KONFIRMASI={FRASA_KONFIRMASI_LIVE}\n"
            "(lihat lux_modul/eksekusi/kredensial.py). Tanpa --konfirmasi-live pada\n"
            "perintah ini, tidak ada order live yang akan dikirim. Gunakan\n"
            "--mode testnet untuk mencoba dulu tanpa dana asli.",
            file=sys.stderr,
        )
        return 1
    print(
        f"== mode LIVE (DANA ASLI): {args.simbol_live or '(multi-pair: pindai pasar)'} "
        f"tf_entry={args.tf_entry or '(ikuti kontrak strategi)'} "
        f"horizon={args.horizon} ==",
        flush=True,
    )
    return _jalankan(_perintah_live_run(args, "live"))


# ====================================================================== #
# menu interaktif (dipakai saat `python main.py` tanpa argumen)
# ====================================================================== #


def _cetak_status():
    """Cetak ringkasan konfigurasi + kesiapan kredensial. Kembalikan (cfg, status)."""
    ada_env = os.path.isfile(BERKAS_ENV_DEFAULT)
    try:
        cfg = muat_konfigurasi()
    except KonfigurasiError as exc:
        print(f"\nKONFIGURASI TIDAK SAH: {exc}\nPerbaiki berkas .env Anda.", file=sys.stderr)
        return None
    st = status_kredensial(cfg)

    print("\n" + "=" * 66)
    print(" LUX - Modul Trading Multi-Strategi Binance Futures")
    print("=" * 66)
    print(f" berkas .env       : {BERKAS_ENV_DEFAULT if ada_env else '(BELUM ADA)'}")
    if not ada_env:
        print(f"   -> salin dulu   : copy {os.path.basename(BERKAS_ENV_CONTOH)} .env")
    print(" parameter aktif   : " + json.dumps(cfg.ringkas(), ensure_ascii=False))
    print("-" * 66)
    print(" kesiapan kredensial (nilai sengaja disamarkan):")
    print(f"   Binance TESTNET : {'SIAP' if st.testnet_siap else 'BELUM diisi'}")
    print(f"   Binance LIVE    : {'SIAP' if st.live_siap else 'BELUM diisi'}")
    print(
        f"   gerbang live 2/2: {'TERBUKA' if st.live_gerbang_env_siap else 'tertutup (aman)'}"
    )
    print(f"   Telegram        : {'SIAP' if st.telegram_siap else 'BELUM diisi / nonaktif'}")
    for k, v in st.detail.items():
        print(f"     {k:32s} = {v}")
    for w in st.peringatan:
        print(f"   ! {w}")
    print("=" * 66)
    return cfg, st


def _tanya(prompt, default=""):
    try:
        jawab = input(f"{prompt} [{default or 'kosong'}]: ").strip()
    except EOFError:
        return default
    return jawab or default


def _uji_telegram(cfg):
    from lux_modul.notifikasi import buat_notifier

    notifier = buat_notifier(cfg)
    if not getattr(notifier, "aktif", False):
        print(
            "Telegram belum dikonfigurasi. Isi LUX_TELEGRAM_BOT_TOKEN dan "
            "LUX_TELEGRAM_CHAT_ID di .env lebih dulu."
        )
        return 1
    hasil = notifier.uji_koneksi()
    print(json.dumps(hasil, ensure_ascii=False, indent=2))
    return 0 if hasil.get("ok") else 1


def _args_dari_cfg(cfg, konfirmasi_live=False):
    """Bangun objek argumen setara CLI dari Konfigurasi (untuk jalur interaktif)."""
    return argparse.Namespace(
        simbol_live=cfg.simbol,
        tf_entry=cfg.tf_entry,
        tf_konteks=cfg.tf_konteks,
        horizon=cfg.horizon,
        leverage_maks=cfg.leverage_maks,
        margin_konflik=cfg.margin_konflik,
        interval_poll=cfg.interval_poll,
        balance_live=cfg.balance,
        maks_siklus=cfg.maks_siklus,
        konfirmasi_live=konfirmasi_live,
        label="single_15m",
        portofolio=False,
        simbol=None,
        maks_bar="0",
        maks_posisi="4",
        data_dir=cfg.data_dir,
        sufiks="",
        maks_runner=cfg.maks_runner,
    )


def menu_interaktif():
    """Menu utama saat `python main.py` dijalankan tanpa argumen."""
    ringkasan = _cetak_status()
    if ringkasan is None:
        return 2
    cfg, st = ringkasan

    print(
        "\nPilih mode:\n"
        "  1) Uji modul (jalankan seluruh unit test)          - aman, tanpa jaringan\n"
        "  2) Backtest data historis (CSV lokal)              - aman, tanpa order\n"
        "  3) TESTNET  Binance Futures (dana mainan)          - order sungguhan di testnet\n"
        "  4) LIVE     Binance Futures (DANA ASLI)            - berisiko finansial nyata\n"
        "  5) Uji koneksi Telegram\n"
        "  6) Bangkitkan ulang data dashboard\n"
        "  0) Keluar"
    )
    pilih = _tanya("Nomor mode", "1")

    if pilih == "0" or not pilih:
        print("keluar.")
        return 0

    if pilih == "1":
        return mode_uji(_args_dari_cfg(cfg))

    if pilih == "2":
        label = _tanya(f"Label TF ({', '.join(LABEL_VALID)})", "single_15m")
        portofolio = _tanya("Backtest portofolio banyak simbol? (y/t)", "t").lower().startswith("y")
        args = _args_dari_cfg(cfg)
        args.label = label
        args.portofolio = portofolio
        if portofolio:
            args.simbol = _tanya("Simbol dipisah koma (kosong = semua di data_dir)", "") or None
            args.maks_bar = _tanya("Batas bar per simbol (0 = semua)", "0")
            args.maks_posisi = _tanya("Kapasitas posisi bersamaan", "4")
        return mode_backtest(args)

    if pilih == "3":
        if not st.testnet_siap:
            print(
                "\nKredensial TESTNET belum lengkap. Isi di .env:\n"
                "  LUX_BINANCE_TESTNET_API_KEY=...\n"
                "  LUX_BINANCE_TESTNET_API_SECRET=...\n"
                "Buat kuncinya gratis di https://testnet.binancefuture.com",
                file=sys.stderr,
            )
            return 2
        args = _args_dari_cfg(cfg)
        args.simbol_live = _tanya("Simbol", cfg.simbol).upper()
        args.tf_entry = _tanya("TF entry", cfg.tf_entry)
        args.tf_konteks = _tanya("TF konteks (kosong = single-TF)", cfg.tf_konteks)
        args.horizon = _tanya("Horizon (scalping/intraday)", cfg.horizon)
        siklus = _tanya("Batas siklus polling (kosong = tanpa batas)", "")
        args.maks_siklus = int(siklus) if siklus else cfg.maks_siklus
        return mode_testnet(args)

    if pilih == "4":
        return _alur_live(cfg, st)

    if pilih == "5":
        return _uji_telegram(cfg)

    if pilih == "6":
        return mode_dashboard(_args_dari_cfg(cfg))

    print(f"pilihan tidak dikenal: {pilih!r}", file=sys.stderr)
    return 2


def _alur_live(cfg, st):
    """Alur mode live dengan dua gerbang keamanan + konfirmasi ketik ulang."""
    print("\n" + "!" * 66)
    print("! MODE LIVE - UANG ASLI. Order yang dikirim TIDAK BISA dibatalkan")
    print("! oleh siapa pun setelah terisi di exchange. Pastikan Anda sudah")
    print("! menguji mode TESTNET lebih dulu dan memahami risikonya.")
    print("!" * 66)

    if not st.live_siap:
        print(
            "\nKredensial LIVE belum lengkap. Isi LUX_BINANCE_LIVE_API_KEY dan "
            "LUX_BINANCE_LIVE_API_SECRET di .env.",
            file=sys.stderr,
        )
        return 2
    if not st.live_gerbang_env_siap:
        print(
            "\nGerbang keamanan 2/2 masih tertutup (ini disengaja).\n"
            f"Set di .env: LUX_LIVE_KONFIRMASI={FRASA_KONFIRMASI_LIVE}\n"
            "lalu jalankan ulang. Selama baris itu kosong, TIDAK ADA order dana "
            "asli yang bisa terkirim - termasuk secara tidak sengaja.",
            file=sys.stderr,
        )
        return 3

    ketik = _tanya(f"Ketik ulang persis '{FRASA_KONFIRMASI_LIVE}' untuk lanjut", "")
    if ketik != FRASA_KONFIRMASI_LIVE:
        print("Frasa tidak cocok. Dibatalkan - tidak ada order yang dikirim.", file=sys.stderr)
        return 4

    args = _args_dari_cfg(cfg, konfirmasi_live=True)
    args.simbol_live = _tanya("Simbol", cfg.simbol).upper()
    args.tf_entry = _tanya("TF entry", cfg.tf_entry)
    args.tf_konteks = _tanya("TF konteks (kosong = single-TF)", cfg.tf_konteks)
    args.horizon = _tanya("Horizon (scalping/intraday)", cfg.horizon)
    siklus = _tanya("Batas siklus polling (kosong = tanpa batas)", "")
    args.maks_siklus = int(siklus) if siklus else cfg.maks_siklus
    return mode_live(args)


# ====================================================================== #


def bangun_parser(cfg=None):
    """Bangun ArgumentParser. Default diambil dari .env bila `cfg` diberikan."""
    # KEBIJAKAN 4 Agu 2026: TIDAK ADA default BTCUSDT/15m. Kosong = engine
    # memindai pasar sendiri (25-50 pair likuid) dan TF mengikuti kontrak strategi.
    d_simbol = cfg.simbol if cfg else ""
    d_tf = cfg.tf_entry if cfg else ""
    d_ctx = cfg.tf_konteks if cfg else ""
    d_horizon = cfg.horizon if cfg else "intraday"
    d_lev = cfg.leverage_maks if cfg else 20.0
    d_margin = cfg.margin_konflik if cfg else 5.0
    d_poll = cfg.interval_poll if cfg else 15.0
    d_balance = cfg.balance if cfg else None
    d_siklus = cfg.maks_siklus if cfg else None
    d_data = cfg.data_dir if cfg else os.path.join(AKAR, "dataset_masuk", "ekstrak", "data_upload")

    p = argparse.ArgumentParser(
        prog="main.py",
        description=(
            "Titik masuk modul trading LUX. Jalankan TANPA argumen untuk menu interaktif."
        ),
    )
    p.add_argument(
        "--mode",
        default=None,
        choices=["uji", "backtest", "dashboard", "konfigurasi", "testnet", "live"],
        help="kosongkan untuk membuka menu interaktif",
    )
    p.add_argument("--label", default="single_15m", choices=LABEL_VALID)
    p.add_argument("--portofolio", action="store_true")
    p.add_argument("--simbol", default=None, help="daftar simbol backtest portofolio, mis. BTC,ETH")
    p.add_argument("--maks-bar", default="0")
    p.add_argument("--maks-posisi", default="4")
    p.add_argument("--data-dir", default=d_data)
    p.add_argument("--sufiks", default="")
    p.add_argument(
        "--simbol-live",
        default=d_simbol,
        help="KOSONGKAN untuk engine multi-pair (pemindaian pasar dinamis). "
        "Isi hanya untuk uji terarah satu pair.",
    )
    p.add_argument("--maks-runner", type=int, default=(cfg.maks_runner if cfg else 120))
    p.add_argument("--tf-entry", default=d_tf)
    p.add_argument("--tf-konteks", default=d_ctx)
    p.add_argument("--horizon", default=d_horizon, choices=["scalping", "intraday"])
    p.add_argument("--balance-live", type=float, default=d_balance)
    p.add_argument(
        "--leverage-maks",
        type=float,
        default=d_lev,
        help="BATAS ATAS saja, bukan leverage tetap. Leverage tiap setup dihitung "
        "otomatis: Risk -> Notional -> Margin -> Leverage.",
    )
    p.add_argument("--margin-konflik", type=float, default=d_margin)
    p.add_argument("--interval-poll", type=float, default=d_poll)
    p.add_argument("--maks-siklus", type=int, default=d_siklus)
    p.add_argument(
        "--konfirmasi-live",
        action="store_true",
        help="gerbang keamanan 1/2 untuk --mode live (wajib bersama env LUX_LIVE_KONFIRMASI)",
    )
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)

    # .env dimuat lebih dulu supaya nilai default argumen pun mengikutinya.
    try:
        cfg = muat_konfigurasi()
    except KonfigurasiError as exc:
        print(f"KONFIGURASI TIDAK SAH: {exc}", file=sys.stderr)
        return 2

    if not argv:
        return menu_interaktif()

    args = bangun_parser(cfg).parse_args(argv)
    if args.mode is None:
        return menu_interaktif()

    dispatcher = {
        "uji": mode_uji,
        "backtest": mode_backtest,
        "dashboard": mode_dashboard,
        "konfigurasi": mode_konfigurasi,
        "testnet": mode_testnet,
        "live": mode_live,
    }
    return dispatcher[args.mode](args)


if __name__ == "__main__":
    raise SystemExit(main())
