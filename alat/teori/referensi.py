"""Implementasi RUJUKAN kanonik, ditulis ulang langsung dari rumus aslinya.

Sengaja naif dan lambat. Tujuannya BUKAN performa, melainkan menjadi pembanding
independen terhadap implementasi modul. Tidak satu pun fungsi di sini mengimpor
lux_modul, supaya pembandingnya benar-benar bebas.

Rujukan rumus ditulis sebagai teks (bukan tautan) dengan sengaja:
- Wilder, J. Welles (1978), New Concepts in Technical Trading Systems.
  RSI, ATR, DX/ADX, dan pemulusan Wilder (RMA).
- Bollinger, John (2001), Bollinger on Bollinger Bands.
  Pita = SMA(n) +/- k * deviasi standar POPULASI (pembagi n, bukan n-1).
- Appel, Gerald. MACD = EMA(12) - EMA(26); sinyal = EMA(9) atas garis MACD.
- Keltner, Chester W. (1960), How to Make Money in Commodities.
  Rumus ASLI: SMA harga tipikal (H+L+C)/3 +/- k * SMA rentang (H-L).
  Varian modern Linda Bradford Raschke (baku StockCharts 20, 2.0, 10):
  EMA(20) +/- 2 * ATR(10).
- Carter, John F., Mastering the Trade. TTM Squeeze = Bollinger(20, 2.0)
  berada DI DALAM Keltner(20, 1.5) memakai rumus Keltner ASLI 1960.
- Donchian, Richard; Faith, Curtis (Way of the Turtle). Channel n periode dari
  bar SEBELUM bar berjalan; stop 2N dengan N = ATR.
- Seban, Olivier. Supertrend: ATR(10), pengali 3, pita final yang meratchet.
- Steidlmayer / CBOT Market Profile. Value area = 70 persen volume di sekitar
  POC, diperluas BERPASANGAN (dua baris di atas lawan dua baris di bawah).
- Pivot lantai klasik: P = (H+L+C)/3, R1 = 2P-L, S1 = 2P-H, dan seterusnya.
"""
from __future__ import annotations

import numpy as np


def sma_ref(x, n):
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    for i in range(n - 1, x.size):
        out[i] = float(x[i - n + 1 : i + 1].mean())
    return out


def ema_ref(x, n):
    """EMA disemai SMA n pertama, rekursi PENUH dari awal deret (tanpa pemotongan)."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    a = 2.0 / (n + 1.0)
    out[n - 1] = float(x[:n].mean())
    for i in range(n, x.size):
        out[i] = a * x[i] + (1.0 - a) * out[i - 1]
    return out


def rma_ref(x, n):
    """Pemulusan Wilder, rekursi penuh."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    if n <= 0 or x.size < n:
        return out
    out[n - 1] = float(x[:n].mean())
    for i in range(n, x.size):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / float(n)
    return out


def rsi_ref(close, n=14):
    c = np.asarray(close, dtype=float)
    out = np.full(c.size, np.nan)
    if c.size < n + 1:
        return out
    d = np.diff(c)
    gain = np.where(d > 0.0, d, 0.0)
    loss = np.where(d < 0.0, -d, 0.0)
    ag = rma_ref(gain, n)
    al = rma_ref(loss, n)
    for i in range(d.size):
        if not np.isfinite(ag[i]):
            continue
        if al[i] <= 0.0:
            out[i + 1] = 100.0
        else:
            rs = ag[i] / al[i]
            out[i + 1] = 100.0 - 100.0 / (1.0 + rs)
    return out


def macd_ref(close, cepat=12, lambat=26, sinyal=9):
    c = np.asarray(close, dtype=float)
    garis = ema_ref(c, cepat) - ema_ref(c, lambat)
    sig = np.full(c.size, np.nan)
    sah = np.isfinite(garis)
    if sah.any():
        i0 = int(np.argmax(sah))
        sig[i0:] = ema_ref(garis[i0:], sinyal)
    return garis, sig, garis - sig


def tr_ref(high, low, close):
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    out = np.empty(h.size)
    for i in range(h.size):
        pc = c[i - 1] if i > 0 else c[0]
        out[i] = max(h[i] - l[i], abs(h[i] - pc), abs(l[i] - pc))
    return out


def atr_ref(high, low, close, n=14):
    return rma_ref(tr_ref(high, low, close), n)


def stdev_pop_ref(x, n):
    """Deviasi standar POPULASI, dua lintasan (eksak, tanpa cancellation)."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    for i in range(n - 1, x.size):
        w = x[i - n + 1 : i + 1]
        m = w.mean()
        out[i] = float(np.sqrt(((w - m) ** 2).sum() / float(n)))
    return out


def stdev_sampel_ref(x, n):
    """Deviasi standar SAMPEL (pembagi n-1). Pembanding NEGATIF: Bollinger
    kanonik TIDAK memakai ini."""
    x = np.asarray(x, dtype=float)
    out = np.full(x.size, np.nan)
    if n <= 1:
        return out
    for i in range(n - 1, x.size):
        w = x[i - n + 1 : i + 1]
        m = w.mean()
        out[i] = float(np.sqrt(((w - m) ** 2).sum() / float(n - 1)))
    return out


def bollinger_ref(close, n=20, k=2.0):
    m = sma_ref(close, n)
    s = stdev_pop_ref(close, n)
    return m + k * s, m, m - k * s


def donchian_ref(high, low, n=20):
    """Donchian BENAR: n bar sebelum bar berjalan (bar berjalan dikecualikan)."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    atas = np.full(h.size, np.nan)
    bawah = np.full(h.size, np.nan)
    for i in range(n, h.size):
        atas[i] = float(h[i - n : i].max())
        bawah[i] = float(l[i - n : i].min())
    return atas, bawah


def donchian_tanpa_geser(high, low, n=20):
    """Varian CEROBOH yang ikut menghitung bar berjalan. Dipakai HANYA sebagai
    pembanding negatif untuk membuktikan modul tidak memakainya."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    atas = np.full(h.size, np.nan)
    bawah = np.full(h.size, np.nan)
    for i in range(n - 1, h.size):
        atas[i] = float(h[i - n + 1 : i + 1].max())
        bawah[i] = float(l[i - n + 1 : i + 1].min())
    return atas, bawah


def supertrend_ref(high, low, close, n=10, k=3.0):
    """Supertrend kanonik: pita dasar (H+L)/2 +/- k*ATR(n), pita final meratchet."""
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    a = atr_ref(h, l, c, n)
    hl2 = (h + l) / 2.0
    ub = hl2 + k * a
    lb = hl2 - k * a
    fub = np.full(c.size, np.nan)
    flb = np.full(c.size, np.nan)
    arah = np.zeros(c.size)
    garis = np.full(c.size, np.nan)
    mulai = -1
    for i in range(c.size):
        if np.isfinite(a[i]):
            mulai = i
            break
    if mulai < 0:
        return garis, arah
    for i in range(mulai, c.size):
        if i == mulai:
            fub[i] = ub[i]
            flb[i] = lb[i]
            arah[i] = 1.0 if c[i] >= hl2[i] else -1.0
        else:
            fub[i] = ub[i] if (ub[i] < fub[i - 1] or c[i - 1] > fub[i - 1]) else fub[i - 1]
            flb[i] = lb[i] if (lb[i] > flb[i - 1] or c[i - 1] < flb[i - 1]) else flb[i - 1]
            if arah[i - 1] > 0:
                arah[i] = -1.0 if c[i] < flb[i] else 1.0
            else:
                arah[i] = 1.0 if c[i] > fub[i] else -1.0
        garis[i] = flb[i] if arah[i] > 0 else fub[i]
    return garis, arah


def adx_ref(high, low, close, n=14):
    """ADX Wilder BERSIH.

    Perbedaan penting dengan implementasi ceroboh: bar warmup menghasilkan NaN,
    bukan nol. Dengan begitu penyemaian ADX (rata-rata n nilai DX pertama) tidak
    tercemar deretan nol palsu dari masa warmup.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    ukuran = h.size
    plus_dm = np.zeros(ukuran)
    minus_dm = np.zeros(ukuran)
    for i in range(1, ukuran):
        naik = h[i] - h[i - 1]
        turun = l[i - 1] - l[i]
        plus_dm[i] = naik if (naik > turun and naik > 0.0) else 0.0
        minus_dm[i] = turun if (turun > naik and turun > 0.0) else 0.0
    tr = tr_ref(h, l, c)
    atr_w = rma_ref(tr[1:], n)
    pdm_w = rma_ref(plus_dm[1:], n)
    mdm_w = rma_ref(minus_dm[1:], n)
    pdi = np.full(ukuran, np.nan)
    mdi = np.full(ukuran, np.nan)
    dx = np.full(ukuran, np.nan)
    for j in range(atr_w.size):
        i = j + 1
        if not np.isfinite(atr_w[j]) or atr_w[j] <= 0.0:
            continue
        p = 100.0 * pdm_w[j] / atr_w[j]
        m = 100.0 * mdm_w[j] / atr_w[j]
        pdi[i] = p
        mdi[i] = m
        if (p + m) > 0.0:
            dx[i] = 100.0 * abs(p - m) / (p + m)
    adx = np.full(ukuran, np.nan)
    idx = np.flatnonzero(np.isfinite(dx))
    if idx.size >= n:
        mulai = int(idx[n - 1])
        adx[mulai] = float(np.mean(dx[idx[:n]]))
        for i in range(mulai + 1, ukuran):
            if np.isfinite(dx[i]) and np.isfinite(adx[i - 1]):
                adx[i] = (adx[i - 1] * (n - 1) + dx[i]) / float(n)
    return adx, pdi, mdi


def keltner_raschke_ref(high, low, close, n_ema=20, k=2.0, n_atr=10):
    """Keltner modern (Raschke). Baku StockCharts: 20, 2.0, ATR 10."""
    tengah = ema_ref(close, n_ema)
    a = atr_ref(high, low, close, n_atr)
    return tengah + k * a, tengah, tengah - k * a


def keltner_asli_ref(high, low, close, n=20, k=1.5):
    """Keltner ASLI Chester Keltner 1960: SMA harga tipikal +/- k * SMA rentang.

    Inilah rumus yang dipakai Carter untuk TTM Squeeze menurut StockCharts.
    """
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    tipikal = (h + l + c) / 3.0
    tengah = sma_ref(tipikal, n)
    rentang = sma_ref(h - l, n)
    return tengah + k * rentang, tengah, tengah - k * rentang


def squeeze_ref(bb_atas, bb_bawah, kc_atas, kc_bawah):
    bb_atas = np.asarray(bb_atas, dtype=float)
    bb_bawah = np.asarray(bb_bawah, dtype=float)
    kc_atas = np.asarray(kc_atas, dtype=float)
    kc_bawah = np.asarray(kc_bawah, dtype=float)
    dalam = (bb_atas < kc_atas) & (bb_bawah > kc_bawah)
    out = np.where(dalam, 1.0, 0.0)
    buruk = ~np.isfinite(bb_atas) | ~np.isfinite(kc_atas)
    out[buruk] = np.nan
    return out


def stoch_rsi_ref(close, n_rsi=14, n_stoch=14, halus=3):
    r = rsi_ref(close, n_rsi)
    k_mentah = np.full(r.size, np.nan)
    for i in range(n_stoch, r.size):
        w = r[i - n_stoch + 1 : i + 1]
        if not np.all(np.isfinite(w)):
            continue
        lo = float(w.min())
        hi = float(w.max())
        k_mentah[i] = 50.0 if hi <= lo else 100.0 * (r[i] - lo) / (hi - lo)
    k = sma_ref(k_mentah, halus)
    d = sma_ref(k, halus)
    return k, d


def vwap_sesi_ref(ts, high, low, close, volume, periode_ms=86400000):
    """VWAP sesi dihitung ulang dari nol untuk tiap bar (lambat tapi jelas benar)."""
    ts = np.asarray(ts, dtype=np.int64)
    h = np.asarray(high, dtype=float)
    l = np.asarray(low, dtype=float)
    c = np.asarray(close, dtype=float)
    v = np.asarray(volume, dtype=float)
    tipikal = (h + l + c) / 3.0
    out = np.empty(tipikal.size)
    for i in range(tipikal.size):
        ember = ts[i] // int(periode_ms)
        j = i
        pv = 0.0
        vv = 0.0
        while j >= 0 and (ts[j] // int(periode_ms)) == ember:
            pv += tipikal[j] * v[j]
            vv += v[j]
            j -= 1
        out[i] = pv / vv if vv > 0 else tipikal[i]
    return out


def pivot_ref(tinggi, rendah, tutup):
    p = (tinggi + rendah + tutup) / 3.0
    return {
        "P": p,
        "R1": 2.0 * p - rendah,
        "S1": 2.0 * p - tinggi,
        "R2": p + (tinggi - rendah),
        "S2": p - (tinggi - rendah),
        "R3": tinggi + 2.0 * (p - rendah),
        "S3": rendah - 2.0 * (tinggi - p),
    }


def fib_ref(awal, akhir):
    """Retracement diukur dari ayunan awal->akhir; ekstensi dari titik awal."""
    r = akhir - awal
    return {
        "0.382": akhir - 0.382 * r,
        "0.5": akhir - 0.5 * r,
        "0.618": akhir - 0.618 * r,
        "0.65": akhir - 0.65 * r,
        "0.786": akhir - 0.786 * r,
        "ext_1.272": awal + 1.272 * r,
        "ext_1.618": awal + 1.618 * r,
    }


def value_area_pasangan_ref(tepi, ember, porsi=0.70):
    """Perluasan value area cara klasik CBOT: bandingkan DUA baris di atas
    melawan DUA baris di bawah, ambil sisi bervolume lebih besar."""
    ember = np.asarray(ember, dtype=float)
    tepi = np.asarray(tepi, dtype=float)
    n = ember.size
    total = float(ember.sum())
    if total <= 0.0 or n == 0:
        return None
    poc = int(np.argmax(ember))
    bawah = poc
    atas = poc
    terkumpul = float(ember[poc])
    target = total * float(porsi)
    while terkumpul < target and (bawah > 0 or atas < n - 1):
        vol_atas = 0.0
        langkah_atas = 0
        for t in (1, 2):
            if atas + t <= n - 1:
                vol_atas += float(ember[atas + t])
                langkah_atas = t
        vol_bawah = 0.0
        langkah_bawah = 0
        for t in (1, 2):
            if bawah - t >= 0:
                vol_bawah += float(ember[bawah - t])
                langkah_bawah = t
        if langkah_atas == 0 and langkah_bawah == 0:
            break
        if langkah_atas > 0 and (vol_atas >= vol_bawah or langkah_bawah == 0):
            atas += langkah_atas
            terkumpul += vol_atas
        else:
            bawah -= langkah_bawah
            terkumpul += vol_bawah
    return float(tepi[bawah]), float(tepi[atas + 1]), terkumpul / total
