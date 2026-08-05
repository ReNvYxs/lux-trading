# Audit Leverage, Presisi, RR Bersih & Final Validation

Tanggal: 4 Agustus 2026. Menjawab permintaan operator poin 1-5.
Semua angka di dokumen ini adalah keluaran nyata dari kode di repo ini
(`scripts/asap_multi_e2e.py`, `tests/test_spesifikasi.py`), bukan ilustrasi.

---

## 1. Leverage otomatis (Risk -> Notional -> Margin -> Leverage)

Modul: `lux_modul/eksekusi/spesifikasi.py` -> `rencana_posisi(...)`.

Urutan perhitungan yang dipakai engine (tidak boleh dibalik):

1. **Risk**: `risiko_usd(balance)` dari `eksekusi/risiko.py` (rumus modal kecil
   `<$20` eksponensial, `>=$20` tiered + taper). Leverage TIDAK ikut menentukan
   angka ini.
2. **Position size**: `qty = risk_usd / |entry - sl|`, lalu dibulatkan **ke bawah**
   ke `stepSize`. `notional = qty * entry`.
3. **Validasi kontrak**: `minQty`, `MIN_NOTIONAL`, `maks_notional`, `tickSize`,
   `pricePrecision`, `quantityPrecision` dari `exchange_info` Binance.
4. **Required margin**: `margin = notional / lev`, dibatasi
   `porsi_margin_maks` (default 0.5 = maksimum setengah saldo per posisi).
5. **Optimal leverage**: `lev = max(1, ceil(notional / (balance * porsi_margin_maks)))`
   lalu dipotong oleh `min(leverage_maks_simbol dari /fapi/v1/leverageBracket,
   batas operator)`. Bila kebutuhan leverage melampaui batas simbol -> setup
   **ditolak** (`butuh_leverage_di_atas_batas_simbol`), bukan dipaksakan.

Leverage yang terpilih dikirim ke bursa per setup lewat
`client.atur_leverage(simbol, leverage)` di `live_runner.siklus_sekali()`
sebelum order entry dikirim.

### Bukti leverage berbeda-beda per setup/pair (bukan statis)

Keluaran `scripts/asap_multi_e2e.py` bagian 2:

| saldo | pair | arah | notional | margin | **leverage** | rr kotor | **rr bersih** | BEP |
|---|---|---|---|---|---|---|---|---|
| 15 | P000 (harga 60.000) | LONG | 45.00 | 7.50 | **x6** | 3.0 | 2.7156 | 60.024,0 |
| 15 | P000 | SHORT | 45.00 | 7.50 | **x6** | 3.0 | 2.7156 | 59.976,0 |
| 15 | P001 (harga 0,32) | LONG | 15.00 | 7.50 | **x2** | 4.0 | 3.8706 | 0,320128 |
| 1000 | P000 | LONG | 2000.00 | 500.00 | **x4** | 3.0 | 2.7156 | 60.024,0 |
| 1000 | P001 | LONG | 666.67 | 333.33 | **x2** | 4.0 | 3.8706 | 0,320128 |

Pada loop multi-pair 120 siklus x 30 runner, leverage yang benar-benar dipasang
ke bursa berbeda tiap setup, contoh nyata: `P001USDT: [8, 7, 6]`,
`P004USDT: [9, 6, 3, 7]`, `P005USDT: [10, 8, 6, 7]`, `P012USDT: [9, 5, 6, 9, 8]`.
Tidak ada x5/x10 statis.

`LUX_LEVERAGE_MAKS` / `--leverage-maks` kini **hanya batas atas**, bukan leverage
kerja. Ditegaskan di `.env.contoh`, `main.py --help`, dan `scripts/live_run.py --help`.

---

## 2. Presisi entry, TP, SL, RR, dan toleransi eksekusi

| Besaran | Pembulatan | Alasan |
|---|---|---|
| Entry | ke tick **terdekat** | harga sinyal harus valid di `PRICE_FILTER` |
| Stop loss | **menjauh** dari entry | SL tidak jadi lebih ketat dari niat strategi |
| Take profit | **ke dalam** (konservatif) | TP tetap realistis tercapai |
| Qty | step **ke bawah** | tidak pernah melebihi risiko yang diizinkan |

Gerbang penolakan (bukan pemaksaan) dengan kode eksplisit:
`notional_di_bawah_minimum_exchange`, `qty_nol_setelah_pembulatan_step`,
`margin_melebihi_saldo_tersedia`, `butuh_leverage_di_atas_batas_simbol`,
`jarak_sl_nol_setelah_pembulatan_tick`, `rr_bersih_tidak_layak`.

Toleransi biaya/eksekusi memakai angka bursa yang wajar, tidak dilebih-lebihkan
sampai mengubah karakter strategi (`eksekusi/biaya.py`): maker 2,0 bps, taker
5,0 bps, slippage maker 0,0 bps, slippage keluar darurat 2,0 bps, SL market 5,0
bps. Order entry **wajib post-only (GTX)**; `MARKET` diharamkan
(`TIPE_TERLARANG`); SL memakai `STOP_MARKET` `closePosition`. Selisih harga
sinyal vs eksekusi ditangani `harga_post_only` dengan `offset_tick` 1 tick +
maksimum 3 requote.

Funding fee tersedia sebagai parameter (`funding_bps` pada `ekonomi_trade`) dan
dipakai bila operator mengisinya; default 0 karena holding intraday/scalping
sering tidak melewati jam funding.

---

## 3. RR bersih & BEP sadar arah

```
risiko_bersih  = |entry - sl| + biaya_masuk + biaya_keluar_sl
imbalan_bersih = |tp - entry| - biaya_masuk - biaya_keluar_tp
rr_bersih      = imbalan_bersih / risiko_bersih
```

BEP sadar arah: `harga_break_even()` menghasilkan BEP **di atas** entry untuk
LONG dan **di bawah** entry untuk SHORT. Bukti: entry 100 -> BEP long 100,04 /
BEP short 99,96; entry 60.000 -> BEP long 60.024,0 dan BEP short 59.976,0. RR
kotor 3,0 selalu turun jadi 2,7156 setelah biaya; tidak pernah ada kasus
`rr_bersih >= rr_kotor` (ditegakkan sebagai invariant uji).

Gerbang opsional `LUX_RR_BERSIH_MIN` menolak setup yang RR bersihnya di bawah
ambang operator.

---

## 4. Sinkronisasi repository

- `lux_modul/eksekusi/spesifikasi.py` (baru) - spesifikasi kontrak, sizing,
  leverage otomatis, BEP, RR bersih.
- `lux_modul/pipeline.py`, `lux_modul/live_runner.py`, `lux_modul/backtest.py` -
  semuanya memakai `rencana_posisi` yang sama (**paritas backtest vs live**).
- `lux_modul/pemindai/likuiditas.py`, `lux_modul/rencana_tf.py`,
  `lux_modul/mesin_multi.py` - pemindaian pasar dinamis 25-50 pair + rencana
  STF/MTF dari kontrak strategi.
- `lux_modul/konfigurasi.py` - default `LUX_SIMBOL`/`LUX_TF_ENTRY` **kosong**
  (tidak lagi BTC/15m), plus ENV pemindai, `LUX_MAKS_RUNNER`,
  `LUX_RR_BERSIH_MIN`, `LUX_PORSI_MARGIN_MAKS`.
- `main.py`, `scripts/live_run.py` - jalur multi-pair jadi default; jalur satu
  pair hanya untuk uji terarah.
- `.env.contoh`, `README.md`, dokumen ini - diselaraskan dengan implementasi.
- `tests/` - 242 uji, semuanya lulus (`python scripts/jalankan_uji.py`).

Bug nyata yang ditemukan lewat validasi E2E dan sudah diperbaiki:
`live_runner` dulu memanggil `client.atur_leverage` tanpa cek dukungan klien,
sehingga klien yang tidak punya endpoint leverage membuat SELURUH entry gagal.
Kini dicek dengan `getattr` dan dicatat di `SiklusHasil.catatan`.

Sisa penyebutan `BTCUSDT`/`15m` hanya ada di baris **contoh pemakaian** pada
dokumentasi/`--help`, bukan di jalur kode default.

---

## 5. Final validation end-to-end

`python scripts/asap_multi_e2e.py` menjalankan bursa palsu 40 simbol (tanpa
jaringan, tanpa uang) dan membuktikan rantai penuh:

```
1. pemindai pasar: 30 pair aktif dari 40 kandidat
   cakupan strategi lengkap: True
3. loop multi-pair: 120 siklus x 30 runner, 812 sinyal, 153 entry, 0 galat runner
   order terkirim : {'LIMIT': 153, 'STOP_MARKET': 153}
   leverage dipasang otomatis pada 30 simbol
HASIL: LULUS
```

Invariant yang ditegakkan: tidak ada satu pun order `MARKET`; setiap `LIMIT`
ber-`timeInForce=GTX`; setiap `STOP_MARKET` `closePosition/reduceOnly`; setiap
entry punya SL (153 entry = 153 SL); jumlah pair aktif 25-50; leverage bervariasi
antar setup.

### Yang JUJUR belum bisa divalidasi di sandbox ini

Sandbox tidak punya akses internet, jadi konektor Binance hanya teruji terhadap
klien tiruan yang meniru bentuk respons REST Binance. Uji terhadap endpoint
Testnet sungguhan harus dijalankan operator di mesin sendiri
(`python main.py --mode testnet`).
