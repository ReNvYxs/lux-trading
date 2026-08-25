"""Stress test lapis 3: sizing modal mikro dengan risiko FLAT 0,20 USDT.

Setiap angka di sini dihitung tangan dari aturan bursa, bukan disalin dari
keluaran program. Dua kasus memakai konstanta BTCUSDT testnet yang sudah kita
baca sendiri dari exchangeInfo (tickSize 0,10, stepSize/minQty 0,0001,
MIN_NOTIONAL 50), supaya uji ini bukan hanya aritmatika mainan.

ATURAN YANG DIKUNCI DI SINI: di bawah saldo 20 USDT tidak ada money management
persentase. Berapa pun saldo, yang dipertaruhkan per trade tetap 0,20 USDT,
boleh dilampaui sedikit (plafon 0,25). Leverage dibatasi supaya likuidasi selalu
lebih jauh daripada SL, memakai maintenance margin - bukan rumus 100/leverage.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.ukuran_mikro import (
    BASE_PER_SETUP_BAWAAN,
    BATAS_MODAL_KECIL_BAWAAN,
    MMR_BAWAAN,
    RISIKO_FLAT_BAWAAN,
    TOLERANSI_RISIKO_BAWAAN,
    TolakUkuranMikro,
    leverage_liq_maks,
    modal_mikro,
    naik_qty,
    notional_minimum_efektif,
    pilih_ukuran,
    rencana_mikro,
)
from lux_modul.eksekusi_aman.inti import SpekSimbol


def spek(step=0.001, min_qty=0.001, maks_qty=1000.0, min_notional=5.0,
         tick=0.01, presisi_harga=2, presisi_qty=3):
    return SpekSimbol(tick, step, min_qty, maks_qty, min_notional,
                      presisi_harga, presisi_qty)


def btc():
    # Konstanta nyata BTCUSDT di testnet Binance USD-M.
    return SpekSimbol(0.10, 0.0001, 0.0001, 120.0, 50.0, 2, 4)


# --------------------------- konstanta & ambang -------------------------- #


def test_konstanta_sesuai_permintaan():
    assert BASE_PER_SETUP_BAWAAN == 0.20
    assert BATAS_MODAL_KECIL_BAWAAN == 20.0
    assert RISIKO_FLAT_BAWAAN == 0.20
    assert TOLERANSI_RISIKO_BAWAAN == 0.25
    assert MMR_BAWAAN == 0.004


def test_ambang_modal_mikro_ketat_di_bawah_20():
    assert modal_mikro(19.99)
    assert not modal_mikro(20.0)
    assert not modal_mikro(25.0)
    assert modal_mikro(2.0, 3.0)
    assert not modal_mikro(5.0, 3.0)


def test_saldo_di_atas_ambang_diserahkan_ke_sizing_risiko():
    h = rencana_mikro(25.0, 100.0, spek())
    assert h["mikro_aktif"] is False
    assert h["layak"] is False
    assert "sizing risiko biasa" in h["alasan"]


# ------------------------- minimum efektif bursa ------------------------- #


def test_minimum_efektif_ambil_yang_terbesar():
    s = SpekSimbol(0.10, 0.001, 0.001, 120.0, 1.0, 2, 3)
    assert notional_minimum_efektif(64_536.4, s) == pytest.approx(64.5364)
    assert notional_minimum_efektif(64_536.4, btc()) == pytest.approx(50.0)


def test_sumber_minimum_dilaporkan_terpisah():
    h = rencana_mikro(10.0, 64_536.4, btc())
    assert h["notional_minimum_efektif"] == pytest.approx(50.0)
    assert h["sumber_minimum"]["min_notional"] == pytest.approx(50.0)
    assert h["sumber_minimum"]["min_qty_x_harga"] == pytest.approx(6.45364)


# --------------------------- pembulatan dua arah ------------------------- #


def test_naik_qty_tidak_menambah_step_saat_sudah_pas():
    assert naik_qty(spek(), 0.05) == pytest.approx(0.05)
    assert naik_qty(spek(), 0.0501) == pytest.approx(0.051)


def test_pembulatan_naik_mencapai_minimum_notional():
    s = spek(step=0.03, min_qty=0.03, presisi_qty=2)
    h = rencana_mikro(10.0, 100.0, s)
    assert h["qty"] == pytest.approx(0.06)
    assert h["notional"] >= s.min_notional


def test_arah_pembulatan_sengaja_dibalik_dari_sizing_risiko():
    s = spek(step=0.03, min_qty=0.03, presisi_qty=2)
    assert s.turun_qty(0.05) == pytest.approx(0.03)
    assert naik_qty(s, 0.05) == pytest.approx(0.06)


# --------------------- batas leverage dari likuidasi -------------------- #


def test_batas_leverage_memakai_maintenance_margin():
    # 1/lev - 0,004 harus MASIH lebih besar daripada jarak SL.
    assert leverage_liq_maks(0.01) == 71
    assert leverage_liq_maks(0.005) == 111
    assert leverage_liq_maks(0.02) == 41
    assert leverage_liq_maks(0.05) == 18
    assert leverage_liq_maks(0.004) == 124
    # Batas bursa tetap menang bila lebih rendah.
    assert leverage_liq_maks(0.01, lev_maks=20) == 20
    # Tanpa SL tidak ada batas likuidasi yang bisa dihitung.
    assert leverage_liq_maks(None) == 125


def test_rumus_lama_100_per_leverage_melebihkan_rasa_aman():
    # Inti koreksinya: pada leverage 99 rumus lama mengaku 1,0101% padahal
    # likuidasi nyata 0,6101% - LEBIH DEKAT daripada SL 1%.
    lama = 100.0 / 99.0
    nyata = (1.0 / 99.0 - MMR_BAWAAN) * 100.0
    assert round(lama, 4) == 1.0101
    assert round(nyata, 4) == 0.6101
    assert nyata < 1.0 < lama
    assert leverage_liq_maks(0.01) < 99


# ------------------------ risiko flat 0,20 USDT ------------------------- #


def test_risiko_flat_020_dicapai_pada_saldo_10():
    # notional_target = 0,20 / 1% = 20 USDT -> qty 0,2 pada harga 100.
    h = rencana_mikro(10.0, 100.0, spek(), sl_harga=99.0, arah="LONG")
    assert h["notional_target_risiko"] == pytest.approx(20.0)
    assert h["qty_lantai_bursa"] == pytest.approx(0.05)
    assert h["qty"] == pytest.approx(0.2)
    assert h["notional"] == pytest.approx(20.0)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.20)
    assert h["risiko_flat_tercapai"] is True
    assert h["risiko_pct_dari_saldo"] == pytest.approx(2.0)
    # Leverage dibatasi likuidasi, bukan oleh base.
    assert h["leverage_dibutuhkan_untuk_base"] == 100
    assert h["leverage_batas_likuidasi"] == 71
    assert h["leverage_dipakai"] == 71
    assert h["margin_nyata"] == pytest.approx(0.28169014)
    assert h["base_tercapai"] is False
    assert "tidak tercapai" in h["catatan_base"]
    assert h["jarak_likuidasi_pct"] == pytest.approx(1.0085)
    assert h["likuidasi_lebih_jauh_dari_sl"] is True
    assert h["layak"] is True


def test_risiko_flat_020_TETAP_berlaku_pada_saldo_1():
    # Inti permintaan: saldo 1 USDT pun mempertaruhkan 0,20 USDT - 20% modal.
    # Angka itu tidak disembunyikan, dilaporkan apa adanya.
    h = rencana_mikro(1.0, 100.0, spek(), sl_harga=99.0, arah="LONG")
    assert h["qty"] == pytest.approx(0.2)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.20)
    assert h["risiko_flat_tercapai"] is True
    assert h["risiko_pct_dari_saldo"] == pytest.approx(20.0)
    assert h["margin_nyata"] == pytest.approx(0.28169014)
    assert h["margin_pct_dari_saldo"] == pytest.approx(28.169)
    assert h["layak"] is True


def test_saldo_1_risiko_sama_dengan_saldo_10_karena_flat():
    # Bukti langsung bahwa aturannya FLAT, bukan persentase: qty dan risiko
    # identik walau saldonya beda 10 kali.
    a = rencana_mikro(1.0, 100.0, spek(), sl_harga=99.0, arah="LONG")
    b = rencana_mikro(10.0, 100.0, spek(), sl_harga=99.0, arah="LONG")
    assert a["qty"] == pytest.approx(b["qty"])
    assert a["rugi_pada_sl_usdt"] == pytest.approx(b["rugi_pada_sl_usdt"])
    assert a["risiko_pct_dari_saldo"] != b["risiko_pct_dari_saldo"]


def test_batas_margin_menyusutkan_qty_bukan_menolak_setup():
    # Saldo 1, SL 0,5% -> target notional 40. Leverage maks aman 111 memberi
    # margin 0,36 > 35% saldo, jadi qty disusutkan sampai margin pas 0,3495.
    # Risiko turun ke 0,194: hampir flat, dan kekurangannya dilaporkan.
    h = rencana_mikro(1.0, 100.0, spek(), sl_harga=99.5, arah="LONG")
    assert h["notional_target_risiko"] == pytest.approx(40.0)
    assert h["disusutkan_karena_margin"] is True
    assert h["qty"] == pytest.approx(0.388)
    assert h["leverage_dipakai"] == 111
    assert h["margin_nyata"] == pytest.approx(0.34954955)
    assert h["margin_pct_dari_saldo"] == pytest.approx(34.955, rel=1e-3)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.194)
    assert h["risiko_flat_tercapai"] is False
    assert h["jarak_likuidasi_pct"] == pytest.approx(0.5009)
    assert h["layak"] is True


def test_toleransi_melampaui_020_sedikit_diizinkan():
    # Lantai bursa memaksa notional 5 dengan SL 5% -> rugi 0,25 = plafon pas.
    # Ini kasus "boleh sedikit dilampaui" yang diminta pemilik modul.
    h = rencana_mikro(1.0, 100.0, spek(), sl_harga=95.0, arah="LONG")
    assert h["qty"] == pytest.approx(0.05)
    assert h["notional"] == pytest.approx(5.0)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.25)
    assert h["plafon_risiko"] == pytest.approx(0.25)
    assert h["layak"] is True


def test_persentase_lama_tidak_bisa_menyelinap_masuk():
    # Kalau pemanggil masih mengirim risiko_maks persen, ia TIDAK diterapkan,
    # tetapi dicatat supaya kelihatan saat audit.
    h = rencana_mikro(10.0, 100.0, spek(), sl_harga=99.0, arah="LONG",
                      risiko_maks=0.01)
    assert h["risiko_maks_diabaikan"] == pytest.approx(0.01)
    assert "tidak diterapkan" in h["catatan_risiko"]
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.20)
    assert h["layak"] is True


# --------------------- penolakan yang WAJIB terjadi --------------------- #


def test_maks_qty_membuat_simbol_tidak_bisa_dipesan():
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0, maks_qty=0.5))
    assert h["layak"] is False
    assert "maxQty" in h["alasan"]


def test_lantai_bursa_yang_melewati_plafon_ditolak_bukan_dipaksakan():
    # minNotional 100 pada SL 1% = rugi 1,0 USDT, lima kali plafon 0,25.
    # Ukuran ini dipaksa bursa, bukan oleh kebijakan kita, jadi dilewati.
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0),
                      sl_harga=99.0, arah="LONG")
    assert h["qty"] == pytest.approx(1.0)
    assert h["margin_nyata"] == pytest.approx(1.4084507)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(1.0)
    assert h["risiko_pct_dari_saldo"] == pytest.approx(10.0)
    assert h["layak"] is False
    assert "melebihi batas flat" in h["alasan"]


def test_base_020_tidak_mungkin_dilaporkan_jujur_lalu_ditolak_risiko():
    # minNotional 100 butuh leverage 500 untuk base 0,20; batas likuidasi 124.
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0),
                      sl_harga=99.6, arah="LONG")
    assert h["leverage_dibutuhkan_untuk_base"] == 500
    assert h["leverage_batas_likuidasi"] == 124
    assert h["leverage_dipakai"] == 124
    assert h["base_tercapai"] is False
    assert h["margin_nyata"] == pytest.approx(0.80645161)
    assert h["margin_minimum_mungkin"] == pytest.approx(0.8)
    assert "tidak tercapai" in h["catatan_base"]
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.4)
    assert h["layak"] is False


def test_input_tidak_valid_ditolak_tanpa_melempar():
    assert rencana_mikro(10.0, 0.0, spek())["alasan"] == "harga tidak valid"
    assert rencana_mikro(0.0, 100.0, spek())["alasan"] == "saldo tidak valid"


def test_tanpa_sl_risiko_TIDAK_diperiksa_dan_base_020_tercapai():
    # Tanpa SL tidak ada target risiko, jadi ukuran tetap di lantai bursa dan
    # base margin 0,20 kembali tercapai. layak=True di sini hanya berarti sah
    # menurut bursa - bukan sudah teruji risikonya.
    h = rencana_mikro(10.0, 100.0, spek())
    assert h["qty"] == pytest.approx(0.05)
    assert h["notional"] == pytest.approx(5.0)
    assert h["leverage_dipakai"] == 25
    assert h["margin_nyata"] == pytest.approx(0.20)
    assert h["base_tercapai"] is True
    assert h["layak"] is True
    assert "risiko_pct_dari_saldo" not in h


# ----------------------- BTCUSDT testnet sebenarnya --------------------- #


def test_btcusdt_nyata_modal_10_sl_1_persen_ditolak_plafon():
    # minNotional 50 memaksa qty 0,0008 BTC. Dengan SL 1% ruginya 0,516 USDT,
    # dua kali plafon 0,25 - jadi BTCUSDT tidak bisa dipakai pada modal mikro.
    s = btc()
    harga = 64_536.4
    h = rencana_mikro(10.0, harga, s, sl_harga=harga * 0.99, arah="LONG")
    assert h["qty"] == pytest.approx(0.0008)
    assert h["notional"] == pytest.approx(51.62912)
    assert h["leverage_dipakai"] == 71
    assert h["margin_nyata"] == pytest.approx(0.7271707)
    assert h["base_tercapai"] is False
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.5162912)
    assert h["risiko_pct_dari_saldo"] == pytest.approx(5.1629, rel=1e-3)
    assert h["layak"] is False
    assert "melebihi batas flat" in h["alasan"]


def test_btcusdt_nyata_modal_19_juga_ditolak_karena_flat_bukan_persen():
    # Dulu saldo 19 lolos batas persen lalu ditolak likuidasi. Sekarang saldo
    # tidak lagi menentukan: plafon 0,25 absolut yang menolaknya.
    s = btc()
    harga = 64_536.4
    h = rencana_mikro(19.0, harga, s, sl_harga=harga * 0.99, arah="LONG")
    assert h["jarak_sl_pct"] == pytest.approx(1.0)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(0.5162912)
    assert h["layak"] is False
    assert "melebihi batas flat" in h["alasan"]


# ------------------------------ pilih_ukuran ---------------------------- #


def test_pilih_ukuran_mengembalikan_qty_dan_leverage():
    qty, lev, rincian = pilih_ukuran(10.0, 100.0, spek(), sl_harga=99.0,
                                     arah="LONG")
    assert qty == pytest.approx(0.2)
    assert lev == 71
    assert rincian["rugi_pada_sl_usdt"] == pytest.approx(0.20)


def test_pilih_ukuran_melempar_saat_tidak_layak():
    with pytest.raises(TolakUkuranMikro):
        pilih_ukuran(10.0, 100.0, spek(min_notional=100.0), sl_harga=99.0,
                     arah="LONG")
