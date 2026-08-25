"""Sambungkan jalur sizing modal mikro ke siklus eksekusi.

MASALAH YANG DIPERBAIKI. ukuran_mikro.py sudah ada dan sudah diuji, tetapi
BELUM dipakai siapa pun di jalur hidup. Akibatnya saldo di bawah 20 USDT tetap
masuk ke hitung_ukuran, dan di sana notional dari risiko jatuh di bawah
minNotional bursa sehingga setup ditolak TolakUkuran. Jadi janji base 0,20 USDT
per setup belum benar-benar berlaku.

DUA KEPUTUSAN PENTING DI TAMBALAN INI.

1. Jalur mikro TIDAK melempar galat untuk ketidaklayakan biasa. Ia mengembalikan
   kesimpulan ukuran_tidak_layak beserta alasannya dan berhenti SEBELUM satu
   order pun dikirim. Melewati setup adalah hasil yang benar, bukan kecelakaan.

2. Leverage WAJIB terpasang. Seluruh angka margin dan jarak likuidasi jalur
   mikro dihitung dari leverage tertentu; kalau leverage gagal dipasang, angka
   itu tidak berlaku dan meneruskan eksekusi berarti bertransaksi dengan asumsi
   risiko yang salah. Karena itu kegagalan atur_leverage membatalkan setup
   sebelum ada order, dan dilaporkan lengkap dengan bagian yang perlu
   diperbaiki.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pasang_tes import blok, terapkan_uji  # noqa: E402

INTI = "lux_modul/eksekusi_aman/inti.py"

TAMBALAN = [
    {
        "nama": "inti_impor_ukuran_mikro",
        "berkas": INTI,
        "tanda": "from ..eksekusi.ukuran_mikro import",
        "jumlah": 1,
        "lama": blok(
            'from ..eksekusi.klasifikasi import KODE_PERMANEN as _KODE_PERMANEN_RUJUKAN',
        ),
        "baru": blok(
            'from ..eksekusi.klasifikasi import KODE_PERMANEN as _KODE_PERMANEN_RUJUKAN',
            'from ..eksekusi.ukuran_mikro import modal_mikro, rencana_mikro',
        ),
    },
    {
        "nama": "siklus_pakai_jalur_mikro",
        "berkas": INTI,
        "tanda": 'h["jalur_ukuran"]',
        "jumlah": 1,
        "lama": blok(
            '    h["ukuran"] = hitung_ukuran(saldo, harga, sl_harga, arah, spek, kebijakan)',
        ),
        "baru": blok(
            '    # Modal mikro (< 20 USDT): hitung_ukuran menolak dengan TolakUkuran',
            '    # karena notional dari risiko jatuh di bawah minNotional bursa. Jalur',
            '    # mikro menaikkan qty ke minimum bursa lalu memakai leverage untuk',
            '    # menekan margin ke base 0,20 USDT per setup - dan TETAP memeriksa',
            '    # risiko nyatanya, karena base 0,20 mengatur MARGIN, bukan RISIKO.',
            '    if modal_mikro(saldo):',
            '        mikro = rencana_mikro(saldo, harga, spek, sl_harga=sl_harga,',
            '                              arah=arah,',
            '                              leverage_maks_bursa=kebijakan.leverage_maks_bursa)',
            '        h["ukuran"] = mikro',
            '        h["jalur_ukuran"] = "mikro"',
            '        if not mikro.get("layak"):',
            '            h["kesimpulan"] = "ukuran_tidak_layak"',
            '            h["alasan_tidak_layak"] = mikro.get("alasan")',
            '            h["dampak"] = "tidak ada order dikirim; setup dilewati"',
            '            return h',
            '        # Tanpa leverage yang benar, margin dan jarak likuidasi hasil jalur',
            '        # mikro TIDAK berlaku. Gagal memasangnya berarti asumsi risiko kita',
            '        # salah, jadi setup dibatalkan SEBELUM satu order pun dikirim.',
            '        lev = int(mikro.get("leverage_dipakai") or 1)',
            '        try:',
            '            klien.atur_leverage(simbol, lev)',
            '            h["leverage_dipasang"] = lev',
            '        except Exception as exc:',
            '            h["kesimpulan"] = "leverage_gagal_dipasang"',
            '            h["galat_leverage"] = str(exc)[:200]',
            '            h["dampak"] = "tidak ada order dikirim; posisi tidak dibuka"',
            '            h["perlu_diperbaiki"] = "BinanceFuturesClient.atur_leverage"',
            '            return h',
            '    else:',
            '        h["ukuran"] = hitung_ukuran(saldo, harga, sl_harga, arah, spek,',
            '                                    kebijakan)',
            '        h["jalur_ukuran"] = "risiko"',
        ),
    },
]


if __name__ == "__main__":
    raise SystemExit(terapkan_uji(TAMBALAN, "MIKRO"))
