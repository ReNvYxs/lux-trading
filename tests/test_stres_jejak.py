"""Uji stres lapisan jejak audit.

Mengunci perbaikan yang lahir dari bukti uji hidup 25 Agu 2026: jawaban jalur
dana yang panjang dulu tercatat sebagai repr Python karena teks JSON dipotong
lebih dulu lalu dicoba di-parse. Tiga endpoint yang paling penting saat API
berubah - balance, positionRisk, openOrders - adalah justru yang paling sering
panjang, jadi kegagalan ini menyerang tepat di titik terburuk.

Uji di bawah ini memaksa jalur panjang itu terjadi dan menuntut hasilnya tetap
TERSTRUKTUR.
"""
import json
import os

import pytest

from lux_modul.eksekusi.jejak import (
    BATAS_TEKS,
    PerekamJejak,
    perekam_senyap,
    redaksi,
    ringkas_jawaban,
)

JALUR_DANA_UJI = "/fapi/v2/balance"
JALUR_ORDER = "/fapi/v1/order"
JALUR_DATA = "/fapi/v1/klines"


def saldo_panjang(n=12):
    """Tiruan /fapi/v2/balance yang panjangnya melewati BATAS_TEKS."""
    keluar = []
    for i in range(n):
        keluar.append({
            "accountAlias": "XqXqXqSguXAuoC",
            "asset": "USDT" if i == 0 else "AST" + str(i),
            "balance": "4179.81481529",
            "crossWalletBalance": "4179.81481529",
            "crossUnPnl": "0.00000000",
            "availableBalance": "4179.81481529",
            "maxWithdrawAmount": "4179.81481529",
            "marginAvailable": True,
            "updateTime": 1771708805218,
        })
    return keluar


def test_jawaban_dana_panjang_tetap_terstruktur():
    jawaban = saldo_panjang()
    assert len(json.dumps(jawaban)) > BATAS_TEKS
    hasil = ringkas_jawaban(JALUR_DANA_UJI, jawaban)
    assert hasil.get("dipangkas") is True
    assert hasil.get("tipe") == "list"
    assert hasil.get("panjang") == 12
    assert "tak_terserialisasi" not in hasil


def test_jawaban_dana_panjang_menyimpan_field_penting():
    hasil = ringkas_jawaban(JALUR_DANA_UJI, saldo_panjang())
    entri = hasil.get("entri")
    assert isinstance(entri, list) and len(entri) == 8
    assert entri[0].get("asset") == "USDT"
    assert entri[0].get("balance") == "4179.81481529"
    assert entri[0].get("availableBalance") == "4179.81481529"


def test_jawaban_dana_panjang_bukan_repr_python():
    """REGRESI: dulu hasilnya repr Python, bukan data."""
    teks = json.dumps(ringkas_jawaban(JALUR_DANA_UJI, saldo_panjang()))
    assert "tak_terserialisasi" not in teks
    # Penanda repr Python: kutip tunggal dan True kapital gaya Python.
    assert "'asset':" not in teks
    assert "'marginAvailable': True" not in teks


def test_jawaban_dana_pendek_disimpan_utuh():
    jawaban = {"orderId": 28554851344, "status": "NEW", "symbol": "BTCUSDT",
               "price": "74145.40", "origQty": "0.0017"}
    assert ringkas_jawaban(JALUR_ORDER, jawaban) == jawaban


def test_dict_dana_panjang_menyimpan_order_id_dan_status():
    jawaban = {"orderId": 999, "status": "PARTIALLY_FILLED",
               "executedQty": "0.5"}
    for i in range(120):
        jawaban["padding_" + str(i)] = "nilai yang cukup panjang untuk mengisi"
    assert len(json.dumps(jawaban)) > BATAS_TEKS
    hasil = ringkas_jawaban(JALUR_ORDER, jawaban)
    assert hasil.get("dipangkas") is True
    assert hasil.get("orderId") == 999
    assert hasil.get("status") == "PARTIALLY_FILLED"
    assert hasil.get("executedQty") == "0.5"
    assert isinstance(hasil.get("kunci"), list)


def test_jalur_data_hanya_bentuk_bukan_isi():
    """Jawaban data pasar tidak boleh menenggelamkan jejak jalur dana."""
    hasil = ringkas_jawaban(JALUR_DATA, [[1, 2, 3]] * 500)
    assert hasil.get("tipe") == "list"
    assert hasil.get("panjang") == 500
    assert "dipangkas" not in hasil


def test_redaksi_membuang_nilai_tetapi_menyimpan_nama():
    hasil = redaksi({"symbol": "BTCUSDT", "signature": "rahasia",
                     "apiKey": "kunci", "quantity": 0.0017})
    assert hasil["signature"] == "[disunting]"
    assert hasil["apiKey"] == "[disunting]"
    assert hasil["symbol"] == "BTCUSDT"
    assert hasil["quantity"] == 0.0017


def test_korelasi_menyatukan_permintaan_jawaban_galat():
    p = perekam_senyap()
    kor = p.catat_permintaan("POST", JALUR_ORDER,
                             {"symbol": "BTCUSDT", "signature": "x"},
                             signed=True, bobot=1)
    p.catat_jawaban(kor, "POST", JALUR_ORDER, status=200,
                    jawaban={"orderId": 1, "status": "NEW"}, ms=12.5)
    p.catat_galat(kor, "POST", JALUR_ORDER, kelas="permanen", status=400,
                  kode=-2010, pesan="Order would immediately trigger.",
                  parameter={"symbol": "BTCUSDT", "signature": "x"})
    baris = p.cari_korelasi(kor)
    assert len(baris) == 3
    permintaan = [b for b in baris if b["peristiwa"] == "permintaan"][0]
    assert permintaan["dana"] is True
    assert permintaan["parameter"]["signature"] == "[disunting]"
    assert permintaan["parameter"]["symbol"] == "BTCUSDT"


def test_galat_menyimpan_parameter_dan_kode():
    """Enam fakta wajib: tanpa parameter, -1111 tidak bisa didiagnosis."""
    p = perekam_senyap()
    p.catat_galat("kor1", "POST", JALUR_ORDER, kelas="permanen", status=400,
                  kode=-1111, pesan="Precision is over the maximum",
                  parameter={"quantity": 0.00012345})
    galat = p.terakhir(1, peristiwa="galat")[0]
    assert galat["kode"] == -1111
    assert galat["parameter"]["quantity"] == 0.00012345
    assert galat["dana"] is True


def test_gagal_menulis_tidak_menjatuhkan_pemanggil(tmp_path):
    """Gagal mencatat tidak boleh menjadi gagal bertransaksi."""
    berkas = tmp_path / "bukan_direktori.txt"
    berkas.write_text("halangan", encoding="utf-8")
    p = PerekamJejak(direktori=os.path.join(str(berkas), "sub"), env={})
    p.catat_permintaan("POST", JALUR_ORDER, {"symbol": "BTCUSDT"})
    assert p.gagal_tulis >= 1
    assert p.ringkas()["gagal_tulis"] >= 1
    assert len(p.ingatan) == 1


def test_berkas_jsonl_benar_benar_tertulis(tmp_path):
    p = PerekamJejak(direktori=str(tmp_path), nama_berkas="uji.jsonl", env={})
    kor = p.catat_permintaan("DELETE", JALUR_ORDER, {"orderId": 5})
    p.catat_jawaban(kor, "DELETE", JALUR_ORDER, status=200,
                    jawaban={"orderId": 5, "status": "CANCELED"})
    isi = (tmp_path / "uji.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(isi) == 2
    kedua = json.loads(isi[1])
    assert kedua["jawaban"]["status"] == "CANCELED"
    assert kedua["dana"] is True
    assert p.gagal_tulis == 0


def test_batas_ingatan_dihormati():
    p = PerekamJejak(direktori="", batas_ingatan=5, env={})
    for i in range(20):
        p.catat("permintaan", urutan=i)
    assert len(p.ingatan) == 5
    assert p.ingatan[-1]["urutan"] == 19
    assert p.jumlah["permintaan"] == 20
