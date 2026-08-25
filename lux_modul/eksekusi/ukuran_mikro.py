"""Sizing modal mikro: risiko FLAT 0,20 USDT per setup saat saldo di bawah 20.

ATURAN YANG BERLAKU (keputusan pemilik modul, 25 Agu 2026). Di bawah saldo 20
USDT money management persentase TIDAK dipakai. Berapa pun saldonya, termasuk 1
USDT, nominal yang dipertaruhkan per trade tetap 0,20 USDT:

    notional_target = 0,20 / jarak_SL        (risiko = notional x jarak_SL)

Plafon 0,20 boleh dilampaui SEDIKIT, karena minimum notional dan stepSize bursa
tidak selalu bisa dibagi rata. Toleransinya eksplisit (plafon = flat x 1,25),
bukan diam-diam. Konsekuensi yang tidak disembunyikan: pada saldo 1 USDT, 0,20
USDT adalah 20% modal per trade. Itu memang yang diminta, dan setiap hasil
memuat risiko_pct_dari_saldo supaya angka itu selalu terlihat.

BASE MARGIN 0,20 SEKARANG SEKUNDER. Dulu "base 0,20" berarti MARGIN. Sekarang
yang dikunci adalah RISIKO, dan margin jadi akibat: leverage dipilih sekecil
mungkin yang masih menekan margin ke base, TETAPI dibatasi jarak likuidasi.
Kalau base tak tercapai, base_tercapai=False dan catatan_base menyebut sebabnya.

LIKUIDASI MEMAKAI MAINTENANCE MARGIN - INI KOREKSI PENTING. Rumus lama
100/leverage adalah jarak ke ekuitas NOL, padahal likuidasi terjadi lebih awal,
yaitu saat ekuitas menyentuh maintenance margin. Rumus lama MELEBIHKAN rasa
aman. Dengan mmr 0,004 (tier terkecil Binance USD-M, dibaca sendiri dari
leverageBracket):

    jarak_likuidasi = 1/leverage - mmr

Pada leverage 99 rumus lama mengaku 1,01% padahal nyatanya 0,61% - lebih dekat
daripada SL 1%, jadi SL tidak akan pernah kepakai. Karena aturan flat mendorong
leverage naik, kesalahan itu berubah dari sepele menjadi menentukan. Karena itu
leverage sekarang DIBATASI agar likuidasi selalu lebih jauh daripada SL.

PEMBULATAN DUA ARAH. qty ke ATAS untuk mencapai minimum bursa; ke BAWAH saat
mengejar target risiko, supaya tidak melewati plafon. Sengaja dipisah.
"""
import math

BATAS_MODAL_KECIL_BAWAAN = 20.0
BASE_PER_SETUP_BAWAAN = 0.20
LEVERAGE_MAKS_BAWAAN = 125
PORSI_MARGIN_MAKS_BAWAAN = 0.35
# Nominal yang dipertaruhkan per setup: ABSOLUT dalam USDT, bukan persentase.
RISIKO_FLAT_BAWAAN = 0.20
# "boleh sedikit dilampaui" -> plafon = flat x (1 + toleransi).
TOLERANSI_RISIKO_BAWAAN = 0.25
# Maintenance margin rate tier terkecil Binance USD-M (bracket 125x).
MMR_BAWAAN = 0.004
# Warisan. TIDAK dipakai lagi di rezim mikro; disimpan agar alat lama tetap jalan.
RISIKO_MAKS_BAWAAN = 0.05
_EPS = 1e-9


class TolakUkuranMikro(Exception):
    """Setup ini tidak bisa dijalankan pada modal ini dengan aman."""


def naik_qty(spek, x):
    """Bulatkan qty ke ATAS mengikuti stepSize."""
    step = float(spek.step)
    if step <= 0:
        return float(x)
    n = math.ceil(float(x) / step - _EPS)
    return round(n * step, int(spek.presisi_qty))


def notional_minimum_efektif(harga, spek):
    """Notional terkecil yang benar-benar bisa dikirim untuk simbol ini."""
    dari_notional = float(spek.min_notional or 0.0)
    dari_qty = float(spek.min_qty or 0.0) * float(harga)
    dari_step = float(spek.step or 0.0) * float(harga)
    return max(dari_notional, dari_qty, dari_step)


def modal_mikro(saldo, batas=None):
    """True bila saldo berada di rezim modal mikro."""
    ambang = BATAS_MODAL_KECIL_BAWAAN if batas is None else float(batas)
    return float(saldo) < ambang


def leverage_liq_maks(jarak_frac, mmr=None, lev_maks=None):
    """Leverage terbesar yang masih menaruh likuidasi LEBIH JAUH daripada SL.

    Dicari dengan turun satu-satu dari tebakan awal, bukan dengan rumus
    terbalik, supaya perbandingan yang menentukan kelayakan persis sama dengan
    perbandingan yang dipakai saat memverifikasi hasil akhir.
    """
    batas_lev = int(LEVERAGE_MAKS_BAWAAN if lev_maks is None else lev_maks)
    m = MMR_BAWAAN if mmr is None else float(mmr)
    if jarak_frac is None or float(jarak_frac) <= 0:
        return max(1, batas_lev)
    batas = float(jarak_frac) + m
    if batas <= 0:
        return max(1, batas_lev)
    lev = int(math.floor(1.0 / batas))
    while lev > 1 and (1.0 / lev - m) <= float(jarak_frac):
        lev -= 1
    return max(1, min(batas_lev, lev))


def rencana_mikro(saldo, harga, spek, sl_harga=None, arah=None,
                  base_per_setup=None, batas_modal=None,
                  leverage_maks_bursa=None, porsi_margin_maks=None,
                  risiko_maks=None, risiko_flat=None, toleransi_risiko=None,
                  mmr=None):
    """Susun ukuran order untuk modal mikro dengan risiko flat.

    Tidak melempar galat untuk ketidaklayakan biasa: mengembalikan layak=False
    beserta alasannya, karena pemanggil perlu mencatat dan melewati setup itu.
    Argumen risiko_maks (persentase) diterima demi kompatibilitas tetapi TIDAK
    diterapkan; kalau dikirim, ia dicatat di risiko_maks_diabaikan agar terlihat.
    """
    base = BASE_PER_SETUP_BAWAAN if base_per_setup is None else float(base_per_setup)
    ambang = BATAS_MODAL_KECIL_BAWAAN if batas_modal is None else float(batas_modal)
    lev_maks = int(LEVERAGE_MAKS_BAWAAN if leverage_maks_bursa is None
                   else leverage_maks_bursa)
    porsi_margin = (PORSI_MARGIN_MAKS_BAWAAN if porsi_margin_maks is None
                    else float(porsi_margin_maks))
    flat = RISIKO_FLAT_BAWAAN if risiko_flat is None else float(risiko_flat)
    tol = (TOLERANSI_RISIKO_BAWAAN if toleransi_risiko is None
           else float(toleransi_risiko))
    m = MMR_BAWAAN if mmr is None else float(mmr)
    plafon = flat * (1.0 + tol)

    h = {"saldo": float(saldo), "harga": float(harga),
         "base_per_setup": base, "batas_modal_mikro": ambang,
         "leverage_maks_bursa": lev_maks, "risiko_flat": flat,
         "plafon_risiko": round(plafon, 8), "mmr": m,
         "spek": {"tick": spek.tick, "step": spek.step,
                  "min_qty": spek.min_qty, "maks_qty": spek.maks_qty,
                  "min_notional": spek.min_notional,
                  "presisi_harga": spek.presisi_harga,
                  "presisi_qty": spek.presisi_qty}}
    if risiko_maks is not None:
        h["risiko_maks_diabaikan"] = float(risiko_maks)
        h["catatan_risiko"] = (
            "batas risiko persentase tidak diterapkan di rezim modal mikro: "
            "aturan yang berlaku adalah risiko flat " + str(flat) + " USDT")

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

    # 1) Lantai bursa: notional terkecil yang sah, qty dibulatkan ke ATAS.
    notional_min = notional_minimum_efektif(harga, spek)
    h["notional_minimum_efektif"] = round(notional_min, 8)
    h["sumber_minimum"] = {
        "min_notional": float(spek.min_notional or 0.0),
        "min_qty_x_harga": round(float(spek.min_qty or 0.0) * float(harga), 8),
        "step_x_harga": round(float(spek.step or 0.0) * float(harga), 8)}
    qty = naik_qty(spek, notional_min / float(harga))
    if qty < float(spek.min_qty or 0.0):
        qty = naik_qty(spek, float(spek.min_qty))
    penjaga = 0
    while qty * float(harga) < notional_min - _EPS and penjaga < 64:
        qty = round(qty + float(spek.step), int(spek.presisi_qty))
        penjaga += 1
    h["iterasi_penambahan_step"] = penjaga
    qty_lantai = qty
    h["qty_lantai_bursa"] = qty_lantai
    h["qty"] = qty
    h["notional"] = round(qty * float(harga), 8)

    # 2) Target risiko flat. qty dibulatkan ke BAWAH supaya tidak lewat plafon.
    jarak_abs = None
    jarak_frac = None
    if sl_harga is not None and arah is not None:
        jarak_abs = abs(float(harga) - float(sl_harga))
        jarak_frac = jarak_abs / float(harga)
        h["jarak_sl_abs"] = round(jarak_abs, 10)
        h["jarak_sl_pct"] = round(jarak_frac * 100.0, 6)
        if jarak_abs > 0:
            notional_target = flat / jarak_frac
            h["notional_target_risiko"] = round(notional_target, 8)
            qty_target = spek.turun_qty(notional_target / float(harga))
            if qty_target > qty:
                qty = qty_target

    # 3) Batas maxQty bursa.
    if float(spek.maks_qty) and qty_lantai > float(spek.maks_qty):
        h["layak"] = False
        h["alasan"] = ("qty minimum " + str(qty_lantai) + " melebihi maxQty " +
                       str(spek.maks_qty) + " - simbol ini tidak bisa dipesan")
        return h
    if float(spek.maks_qty) and qty > float(spek.maks_qty):
        qty = spek.turun_qty(float(spek.maks_qty))
        h["dibatasi_maks_qty"] = True
    notional = qty * float(harga)

    # 4) Leverage: sekecil mungkin untuk base, TAPI tidak melewati batas likuidasi.
    lev_liq = leverage_liq_maks(jarak_frac, m, lev_maks)
    h["leverage_batas_likuidasi"] = lev_liq
    lev_butuh = int(math.ceil(notional / base - _EPS)) if base > 0 else lev_maks
    h["leverage_dibutuhkan_untuk_base"] = lev_butuh
    lev_pakai = min(max(1, lev_butuh), lev_maks, lev_liq)
    margin = notional / float(lev_pakai)

    # 5) Margin tidak boleh menelan modal. Susutkan qty dulu, jangan langsung tolak.
    margin_maks = float(saldo) * porsi_margin
    if margin > margin_maks + _EPS:
        qty_muat = spek.turun_qty(margin_maks * float(lev_pakai) / float(harga))
        if qty_muat >= qty_lantai - _EPS and qty_muat > 0:
            qty = qty_muat
            notional = qty * float(harga)
            margin = notional / float(lev_pakai)
            h["disusutkan_karena_margin"] = True
        else:
            h["qty"] = qty
            h["notional"] = round(notional, 8)
            h["leverage_dipakai"] = lev_pakai
            h["margin_nyata"] = round(margin, 8)
            h["layak"] = False
            h["alasan"] = ("margin " + str(round(margin, 6)) + " melebihi " +
                           str(round(porsi_margin * 100, 1)) + "% saldo " +
                           str(round(float(saldo), 4)) +
                           " walau qty sudah di lantai minimum bursa")
            return h

    h["qty"] = qty
    h["notional"] = round(notional, 8)
    h["leverage_dipakai"] = lev_pakai
    h["margin_nyata"] = round(margin, 8)
    h["base_tercapai"] = margin <= base + 1e-6
    h["margin_minimum_mungkin"] = round(notional / float(lev_maks), 8)
    h["margin_pct_dari_saldo"] = round(margin / float(saldo) * 100.0, 4)
    if not h["base_tercapai"]:
        h["catatan_base"] = (
            "base margin " + str(base) + " USDT tidak tercapai: base butuh "
            "leverage " + str(lev_butuh) + " tetapi leverage dipakai " +
            str(lev_pakai) + " (batas bursa " + str(lev_maks) +
            ", batas likuidasi " + str(lev_liq) + "); margin termurah untuk "
            "simbol ini " + str(h["margin_minimum_mungkin"]) + " USDT")

    # 6) RISIKO NYATA terhadap aturan flat.
    if jarak_abs is not None and jarak_abs > 0:
        rugi = qty * jarak_abs
        h["rugi_pada_sl_usdt"] = round(rugi, 8)
        h["risiko_pct_dari_saldo"] = round(rugi / float(saldo) * 100.0, 4)
        h["rasio_risiko_terhadap_margin"] = (
            round(rugi / margin, 4) if margin > 0 else None)
        h["risiko_flat_tercapai"] = rugi >= flat - 1e-6
        if rugi > plafon + _EPS:
            h["layak"] = False
            h["alasan"] = (
                "risiko " + str(round(rugi, 6)) + " USDT melebihi batas flat " +
                str(flat) + " USDT (plafon " + str(round(plafon, 6)) +
                " dengan toleransi " + str(round(tol * 100, 1)) + "%). Ukuran "
                "ini dipaksa oleh minimum notional bursa, bukan oleh kebijakan "
                "kita, jadi setup ini harus dilewati - bukan dipaksakan")
            return h
        h["jarak_likuidasi_pct"] = round((1.0 / float(lev_pakai) - m) * 100.0, 4)
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
    """Pembungkus tegas: kembalikan (qty, leverage, rincian) atau lempar."""
    h = rencana_mikro(saldo, harga, spek, sl_harga=sl_harga, arah=arah, **opsi)
    if not h.get("layak"):
        raise TolakUkuranMikro(str(h.get("alasan") or "tidak layak"))
    return h["qty"], h["leverage_dipakai"], h
