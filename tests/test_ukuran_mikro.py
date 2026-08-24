"""Stress test lapis 3: sizing modal mikro, base 0,20 USDT per setup.

Setiap angka di sini dihitung tangan dari aturan bursa, bukan disalin dari
keluaran program. Dua kasus memakai konstanta BTCUSDT testnet yang sudah kita
baca sendiri dari exchangeInfo (tickSize 0,10, stepSize/minQty 0,0001,
MIN_NOTIONAL 50), supaya uji ini bukan hanya aritmatika mainan.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from lux_modul.eksekusi.ukuran_mikro import (
    BASE_PER_SETUP_BAWAAN,
    BATAS_MODAL_KECIL_BAWAAN,
    TolakUkuranMikro,
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
    # minQty x harga (64,5364) mengalahkan MIN_NOTIONAL (1,0). Mengabaikan
    # salah satu batas menghasilkan order yang ditolak bursa.
    s = SpekSimbol(0.10, 0.001, 0.001, 120.0, 1.0, 2, 3)
    assert notional_minimum_efektif(64_536.4, s) == pytest.approx(64.5364)
    # Sebaliknya untuk BTCUSDT asli: MIN_NOTIONAL 50 yang mengikat.
    assert notional_minimum_efektif(64_536.4, btc()) == pytest.approx(50.0)


def test_sumber_minimum_dilaporkan_terpisah():
    h = rencana_mikro(10.0, 64_536.4, btc())
    assert h["notional_minimum_efektif"] == pytest.approx(50.0)
    assert h["sumber_minimum"]["min_notional"] == pytest.approx(50.0)
    assert h["sumber_minimum"]["min_qty_x_harga"] == pytest.approx(6.45364)


# --------------------------- pembulatan ke ATAS -------------------------- #


def test_naik_qty_tidak_menambah_step_saat_sudah_pas():
    # Tanpa toleransi epsilon, 0,05 / 0,001 = 50,000000000000004 akan dibulatkan
    # ke 51 step dan menaikkan notional tanpa alasan.
    assert naik_qty(spek(), 0.05) == pytest.approx(0.05)
    assert naik_qty(spek(), 0.0501) == pytest.approx(0.051)


def test_pembulatan_naik_mencapai_minimum_notional():
    # step 0,03 pada harga 100: 5/100 = 0,05 bukan kelipatan step.
    # Ke bawah -> 0,03 -> notional 3 -> ditolak -4164. Ke atas -> 0,06 -> 6.
    s = spek(step=0.03, min_qty=0.03, presisi_qty=2)
    h = rencana_mikro(10.0, 100.0, s)
    assert h["qty"] == pytest.approx(0.06)
    assert h["notional"] >= s.min_notional


def test_arah_pembulatan_sengaja_dibalik_dari_sizing_risiko():
    # Bukti bahwa dua arah pembulatan itu memang berbeda pada spek yang sama.
    s = spek(step=0.03, min_qty=0.03, presisi_qty=2)
    assert s.turun_qty(0.05) == pytest.approx(0.03)
    assert naik_qty(s, 0.05) == pytest.approx(0.06)


# ------------------------------ base 0,20 ------------------------------- #


def test_base_020_tercapai_saat_min_notional_5():
    # notional 5, leverage 25 -> margin tepat 0,20 USDT.
    h = rencana_mikro(10.0, 100.0, spek(), sl_harga=99.0, arah="LONG")
    assert h["qty"] == pytest.approx(0.05)
    assert h["notional"] == pytest.approx(5.0)
    assert h["leverage_dibutuhkan_untuk_base"] == 25
    assert h["leverage_dipakai"] == 25
    assert h["margin_nyata"] == pytest.approx(0.20)
    assert h["base_tercapai"] is True
    assert h["risiko_pct_dari_saldo"] == pytest.approx(0.5)
    assert h["jarak_likuidasi_pct"] == pytest.approx(4.0)
    assert h["layak"] is True


def test_base_020_tidak_mungkin_dilaporkan_jujur():
    # minNotional 100 butuh leverage 500, di atas batas bursa 125. Yang termurah
    # 100/125 = 0,80 USDT. Modul melaporkan itu, tidak memaksakan 0,20.
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0),
                      sl_harga=99.6, arah="LONG")
    assert h["leverage_dibutuhkan_untuk_base"] == 500
    assert h["leverage_dipakai"] == 125
    assert h["base_tercapai"] is False
    assert h["margin_nyata"] == pytest.approx(0.8)
    assert h["margin_minimum_mungkin"] == pytest.approx(0.8)
    assert "tidak tercapai" in h["catatan_base"]
    assert h["layak"] is True


# --------------------- penolakan yang WAJIB terjadi --------------------- #


def test_maks_qty_membuat_simbol_tidak_bisa_dipesan():
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0, maks_qty=0.5))
    assert h["layak"] is False
    assert "maxQty" in h["alasan"]


def test_risiko_di_atas_batas_ditolak_bukan_dipaksakan():
    # Margin memang cuma 0,80 USDT, tetapi rugi di SL 1,0 USDT = 10% saldo.
    # Inilah bahaya utama base 0,20: ia mengatur MARGIN, bukan RISIKO.
    h = rencana_mikro(10.0, 100.0, spek(min_notional=100.0),
                      sl_harga=99.0, arah="LONG")
    assert h["margin_nyata"] == pytest.approx(0.8)
    assert h["rugi_pada_sl_usdt"] == pytest.approx(1.0)
    assert h["risiko_pct_dari_saldo"] == pytest.approx(10.0)
    assert h["layak"] is False
    assert "melebihi batas" in h["alasan"]


def test_likuidasi_lebih_dekat_daripada_sl_ditolak():
    # leverage 125 -> jarak likuidasi 0,8%. SL 0,9% berarti posisi terlikuidasi
    # sebelum SL bekerja, jadi SL itu bukan proteksi.
    h = rencana_mikro(19.0, 100.0, spek(min_notional=100.0),
                      sl_harga=99.1, arah="LONG")
    assert h["jarak_likuidasi_pct"] == pytest.approx(0.8)
    assert h["likuidasi_lebih_jauh_dari_sl"] is False
    assert h["layak"] is False
    assert "likuidasi" in h["alasan"]


def test_input_tidak_valid_ditolak_tanpa_melempar():
    assert rencana_mikro(10.0, 0.0, spek())["alasan"] == "harga tidak valid"
    assert rencana_mikro(0.0, 100.0, spek())["alasan"] == "saldo tidak valid"


def test_tanpa_sl_risiko_TIDAK_diperiksa():
    # Batasan yang harus disadari pemanggil: tanpa sl_harga+arah, blok risiko
    # dilewati sepenuhnya dan layak=True hanya berarti sah menurut bursa.
    h = rencana_mikro(10.0, 100.0, spek())
    assert h["layak"] is True
    assert "risiko_pct_dari_saldo" not in h


# ----------------------- BTCUSDT testnet sebenarnya --------------------- #


def test_btcusdt_nyata_modal_10_sl_1_persen_ditolak():
    # Temuan nyata: minNotional 50 memaksa qty 0,0008 BTC. Dengan SL 1%,
    # ruginya 0,516 USDT = 5,16% dari saldo 10 - di atas batas 5%. Mesin
    # MENOLAK, bukan diam-diam meloloskan risiko berlebih.
    s = btc()
    harga = 64_536.4
    h = rencana_mikro(10.0, harga, s, sl_harga=harga * 0.99, arah="LONG")
    assert h["qty"] == pytest.approx(0.0008)
    assert h["notional"] == pytest.approx(51.62912)
    assert h["base_tercapai"] is False
    assert h["margin_nyata"] == pytest.approx(0.41303296)
    assert h["risiko_pct_dari_saldo"] == pytest.approx(5.1629, rel=1e-3)
    assert h["layak"] is False


def test_btcusdt_nyata_modal_19_ditolak_karena_likuidasi():
    # Saldo 19 membuat risiko lolos (0,516 <= 0,95), tetapi leverage 125
    # menaruh likuidasi di 0,8% sementara SL di 1,0%.
    s = btc()
    harga = 64_536.4
    h = rencana_mikro(19.0, harga, s, sl_harga=harga * 0.99, arah="LONG")
    assert h["jarak_sl_pct"] == pytest.approx(1.0)
    assert h["jarak_likuidasi_pct"] == pytest.approx(0.8)
    assert h["likuidasi_lebih_jauh_dari_sl"] is False
    assert h["layak"] is False


# ------------------------------ pilih_ukuran ---------------------------- #


def test_pilih_ukuran_mengembalikan_qty_dan_leverage():
    qty, lev, rincian = pilih_ukuran(10.0, 100.0, spek(), sl_harga=99.0,
                                     arah="LONG")
    assert qty == pytest.approx(0.05)
    assert lev == 25
    assert rincian["margin_nyata"] == pytest.approx(0.20)


def test_pilih_ukuran_melempar_saat_tidak_layak():
    with pytest.raises(TolakUkuranMikro):
        pilih_ukuran(10.0, 100.0, spek(min_notional=100.0), sl_harga=99.0,
                     arah="LONG")
