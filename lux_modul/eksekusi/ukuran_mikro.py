"""Sizing untuk modal mikro: base 0,20 USDT per setup saat saldo di bawah 20.

APA YANG DIMAKSUD "BASE 0,20 PER SETUP". Yang bisa dikendalikan sampai 0,20
USDT adalah INITIAL MARGIN, yaitu uang yang benar-benar dikunci per setup.
NOTIONAL tidak bisa, karena Binance memasang minimum notional per simbol
(5 USDT untuk sebagian besar pair, jauh lebih tinggi untuk beberapa) dan juga
minQty. Jadi target modul ini: biaya satu setup = 0,20 USDT margin, dengan
notional dinaikkan ke minimum bursa dan leverage dipakai untuk menutup jaraknya.

    notional = margin x leverage  ->  leverage = notional_minimum / 0,20

CONTOH NYATA. Pair dengan minNotional 5 USDT: notional 5, margin 0,20 berarti
leverage 25. Itu di dalam batas bursa, jadi layak. Pair dengan minNotional 100
USDT: butuh leverage 500, di atas batas 125, jadi TIDAK layak pada 0,20 - yang
termurah adalah 100/125 = 0,80 USDT. Modul ini melaporkan angka itu apa adanya,
tidak memaksakan angka yang tidak mungkin.

PEMBULATAN DIBALIK, DAN INI PENTING. Sizing berbasis risiko di inti.py
membulatkan qty ke BAWAH, supaya notional tidak melewati batas risiko. Di sini
kebalikannya: qty dibulatkan ke ATAS, karena tujuannya justru MENCAPAI minimum
bursa. Membulatkan ke bawah di sini akan menghasilkan order yang pasti ditolak
-4164. Dua arah pembulatan ini sengaja dipisah ke dua fungsi berbeda supaya
tidak pernah tertukar.

BAHAYA YANG WAJIB DILAPORKAN. "Base 0,20" mengatur MARGIN, bukan RISIKO. Pada
saldo kecil, minimum notional bursa bisa membuat kerugian di SL jadi besar
secara persentase. Notional 100 dengan SL 2% berarti rugi 2 USDT; pada saldo 10
USDT itu 20% modal dalam satu trade. Margin memang tetap 0,80, tetapi risikonya
tidak kecil sama sekali. Karena itu fungsi ini SELALU menghitung risiko nyata
dan menolak bila melewati batas, bukan diam-diam meloloskannya.
"""
import math

BATAS_MODAL_KECIL_BAWAAN = 20.0
BASE_PER_SETUP_BAWAAN = 0.20
LEVERAGE_MAKS_BAWAAN = 125
# Margin satu setup tidak boleh menelan sebagian besar modal mikro, walaupun
# angka absolutnya kecil.
PORSI_MARGIN_MAKS_BAWAAN = 0.35
# Risiko satu setup terhadap saldo. Pada modal mikro batas ini yang mengikat,
# bukan margin.
RISIKO_MAKS_BAWAAN = 0.05
_EPS = 1e-9


class TolakUkuranMikro(Exception):
    """Setup ini tidak bisa dijalankan pada modal ini dengan aman."""


def naik_qty(spek, x):
    """Bulatkan qty ke ATAS mengikuti stepSize. Lihat catatan modul."""
    step = float(spek.step)
    if step <= 0:
        return float(x)
    n = math.ceil(float(x) / step - _EPS)
    return round(n * step, int(spek.presisi_qty))


def notional_minimum_efektif(harga, spek):
    """Notional terkecil yang benar-benar bisa dikirim untuk simbol ini.

    Dua batas bekerja sekaligus dan yang menentukan adalah yang lebih besar:
    MIN_NOTIONAL langsung, dan minQty x harga yang membuat notional punya dasar
    tersendiri. Mengabaikan salah satunya menghasilkan order yang ditolak.
    """
    dari_notional = float(spek.min_notional or 0.0)
    dari_qty = float(spek.min_qty or 0.0) * float(harga)
    dari_step = float(spek.step or 0.0) * float(harga)
    return max(dari_notional, dari_qty, dari_step)


def modal_mikro(saldo, batas=None):
    """True bila saldo berada di rezim modal mikro."""
    ambang = BATAS_MODAL_KECIL_BAWAAN if batas is None else float(batas)
    return float(saldo) < ambang


def rencana_mikro(saldo, harga, spek, sl_harga=None, arah=None,
                  base_per_setup=None, batas_modal=None,
                  leverage_maks_bursa=None, porsi_margin_maks=None,
                  risiko_maks=None):
    """Susun ukuran order terkecil yang sah untuk modal mikro.

    Semua angka perantara dikembalikan supaya bisa diaudit tanpa menjalankan
    ulang. Fungsi ini TIDAK melempar galat untuk ketidaklayakan biasa: ia
    mengembalikan layak=False beserta alasannya, karena pemanggil perlu
    mencatat dan melewati setup itu, bukan jatuh.
    """
    base = BASE_PER_SETUP_BAWAAN if base_per_setup is None else float(base_per_setup)
    ambang = BATAS_MODAL_KECIL_BAWAAN if batas_modal is None else float(batas_modal)
    lev_maks = int(LEVERAGE_MAKS_BAWAAN if leverage_maks_bursa is None
                   else leverage_maks_bursa)
    porsi_margin = (PORSI_MARGIN_MAKS_BAWAAN if porsi_margin_maks is None
                    else float(porsi_margin_maks))
    risiko_batas = RISIKO_MAKS_BAWAAN if risiko_maks is None else float(risiko_maks)

    h = {"saldo": float(saldo), "harga": float(harga),
         "base_per_setup": base, "batas_modal_mikro": ambang,
         "leverage_maks_bursa": lev_maks,
         "spek": {"tick": spek.tick, "step": spek.step,
                  "min_qty": spek.min_qty, "maks_qty": spek.maks_qty,
                  "min_notional": spek.min_notional,
                  "presisi_harga": spek.presisi_harga,
                  "presisi_qty": spek.presisi_qty}}

    if float(harga) <= 0:
        h["layak"] = False
        h["alasan"] = "harga tidak valid"
        return h
    if float(saldo) <= 0:
        h["layak"] = False
        h["alasan"] = "saldo tidak valid"
        return h

    h["mikro_aktif"] = modal_mikro(saldo, ambang)
    if not h["mikro_aktif"]:
        h["layak"] = False
        h["alasan"] = ("saldo " + str(round(float(saldo), 4)) + " >= ambang " +
                       str(ambang) + "; pakai sizing risiko biasa di inti.py")
        return h

    # 1) Notional terkecil yang sah menurut bursa.
    notional_min = notional_minimum_efektif(harga, spek)
    h["notional_minimum_efektif"] = round(notional_min, 8)
    h["sumber_minimum"] = {
        "min_notional": float(spek.min_notional or 0.0),
        "min_qty_x_harga": round(float(spek.min_qty or 0.0) * float(harga), 8),
        "step_x_harga": round(float(spek.step or 0.0) * float(harga), 8)}

    # 2) qty dibulatkan ke ATAS, lalu diverifikasi ulang terhadap SEMUA batas.
    qty = naik_qty(spek, notional_min / float(harga))
    if qty < float(spek.min_qty or 0.0):
        qty = naik_qty(spek, float(spek.min_qty))
    notional = qty * float(harga)
    # Pembulatan ke atas bisa masih kurang bila minNotional bukan kelipatan step.
    penjaga = 0
    while notional < notional_min - _EPS and penjaga < 64:
        qty = round(qty + float(spek.step), int(spek.presisi_qty))
        notional = qty * float(harga)
        penjaga += 1
    h["qty"] = qty
    h["notional"] = round(notional, 8)
    h["iterasi_penambahan_step"] = penjaga

    if float(spek.maks_qty) and qty > float(spek.maks_qty):
        h["layak"] = False
        h["alasan"] = ("qty minimum " + str(qty) + " melebihi maxQty " +
                       str(spek.maks_qty) + " - simbol ini tidak bisa dipesan")
        return h

    # 3) Leverage yang dibutuhkan supaya margin = base.
    lev_butuh = int(math.ceil(notional / base - _EPS)) if base > 0 else lev_maks
    h["leverage_dibutuhkan_untuk_base"] = lev_butuh
    lev_pakai = min(max(1, lev_butuh), lev_maks)
    h["leverage_dipakai"] = lev_pakai
    margin = notional / float(lev_pakai)
    h["margin_nyata"] = round(margin, 8)
    h["base_tercapai"] = margin <= base + 1e-6
    h["margin_minimum_mungkin"] = round(notional / float(lev_maks), 8)
    h["margin_pct_dari_saldo"] = round(margin / float(saldo) * 100.0, 4)

    if not h["base_tercapai"]:
        h["catatan_base"] = (
            "base " + str(base) + " USDT tidak tercapai: butuh leverage " +
            str(lev_butuh) + " tetapi batas bursa " + str(lev_maks) +
            "; margin termurah untuk simbol ini " +
            str(h["margin_minimum_mungkin"]) + " USDT")

    # 4) Margin tidak boleh menelan modal mikro.
    if margin > float(saldo) * porsi_margin:
        h["layak"] = False
        h["alasan"] = ("margin " + str(round(margin, 6)) + " melebihi " +
                       str(round(porsi_margin * 100, 1)) + "% saldo " +
                       str(round(float(saldo), 4)))
        return h

    # 5) RISIKO NYATA. Ini yang biasanya mengikat pada modal mikro, bukan margin.
    if sl_harga is not None and arah is not None:
        jarak_abs = abs(float(harga) - float(sl_harga))
        h["jarak_sl_abs"] = round(jarak_abs, 10)
        h["jarak_sl_pct"] = round(jarak_abs / float(harga) * 100.0, 6)
        rugi = qty * jarak_abs
        h["rugi_pada_sl_usdt"] = round(rugi, 8)
        h["risiko_pct_dari_saldo"] = round(rugi / float(saldo) * 100.0, 4)
        h["rasio_risiko_terhadap_margin"] = (
            round(rugi / margin, 4) if margin > 0 else None)
        if rugi > float(saldo) * risiko_batas:
            h["layak"] = False
            h["alasan"] = (
                "risiko " + str(round(rugi, 6)) + " USDT = " +
                str(h["risiko_pct_dari_saldo"]) + "% saldo, melebihi batas " +
                str(round(risiko_batas * 100, 1)) + "%. Ukuran ini dipaksa oleh "
                "minimum notional bursa, bukan oleh kebijakan risiko kita, "
                "jadi setup ini harus dilewati - bukan dipaksakan")
            return h
        # Jarak likuidasi kira-kira 100/leverage persen. Kalau likuidasi lebih
        # dekat daripada SL, SL tidak pernah kepakai dan itu bukan proteksi.
        h["jarak_likuidasi_pct"] = round(100.0 / float(lev_pakai), 4)
        h["likuidasi_lebih_jauh_dari_sl"] = (
            h["jarak_likuidasi_pct"] > h["jarak_sl_pct"])
        if not h["likuidasi_lebih_jauh_dari_sl"]:
            h["layak"] = False
            h["alasan"] = (
                "leverage " + str(lev_pakai) + " membuat jarak likuidasi " +
                str(h["jarak_likuidasi_pct"]) + "% lebih dekat daripada SL " +
                str(h["jarak_sl_pct"]) + "% - posisi akan terlikuidasi sebelum "
                "SL bekerja")
            return h

    h["layak"] = True
    h["alasan"] = None
    return h


def pilih_ukuran(saldo, harga, spek, sl_harga=None, arah=None, **opsi):
    """Pembungkus tegas: kembalikan (qty, leverage, rincian) atau lempar.

    Dipakai di jalur eksekusi, di mana melanjutkan dengan ukuran tidak layak
    berarti mengirim order yang pasti ditolak atau berisiko berlebihan.
    """
    h = rencana_mikro(saldo, harga, spek, sl_harga=sl_harga, arah=arah, **opsi)
    if not h.get("layak"):
        raise TolakUkuranMikro(str(h.get("alasan") or "tidak layak"))
    return h["qty"], h["leverage_dipakai"], h
