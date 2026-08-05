# Calon Strategi (Pengembangan Berikutnya)

Dokumen ini mendaftar strategi/indikator yang **sengaja belum dibuat** karena
dataset yang tersedia saat ini hanya OHLCV (`ts, open, high, low, close, volume`)
dan TIDAK memuat data yang dibutuhkan untuk menghitungnya secara valid.

Prinsip operator yang mendasari daftar ini (wajib dipatuhi):

> Gunakan kemampuan dataset sebagai batasan validasi, bukan sebagai alasan
> untuk memaksakan implementasi strategi yang datanya tidak tersedia. Jangan
> melakukan asumsi atau membat data sintetis seolah-olah data tersebut
> tersedia.

Jadi butir-butir di bawah ini BUKAN bagian dari modul yang diuji sekarang.
Baru boleh diimplementasikan kalau dataset dengan kolom yang relevan benar-benar
tersedia dan sudah divalidasi (bukan direkonstruksi/dikira-kira dari OHLCV).

## 1. CVD asli (Cumulative Volume Delta)

- **Butuh**: klasifikasi agresor per transaksi (buy-initiated vs sell-initiated),
  biasanya dari data tick/trade atau order book (bid/ask di setiap match).
- **Kenapa tidak dibuat**: dataset OHLCV tidak tahu sisi mana yang agresif pada
  tiap transaksi. Sebuah "proksi" dari OHLCV (mis. memakai posisi close dalam
  rentang bar) BUKAN CVD yang valid -- itu hanya indikator momentum/tekanan
  yang menyamar sebagai order flow, dan berpotensi menyesatkan keputusan
  trading kalau dilabeli seolah representasi order flow asli.
- **Kalau datanya tersedia nanti**: hitung delta = volume_buy - volume_sell per
  transaksi/candle dari data trade asli, lalu kumulatifkan. Bisa dipakai untuk
  strategi divergensi CVD vs harga (harga higher-high, CVD lower-high, dst).

## 2. Order flow / tick-level order flow (footprint, imbalance, absorpsi)

- **Butuh**: data tick-by-tick atau order book depth (Level 2), termasuk ukuran
  dan sisi tiap order/trade.
- **Kenapa tidak dibuat**: dataset OHLCV tidak punya granularitas ini sama
  sekali; tidak ada cara valid merekonstruksinya dari candle biasa.

## 3. Open Interest (OI)

- **Butuh**: kolom open interest per timeframe dari exchange (mis. endpoint
  futures OI Binance).
- **Kenapa tidak dibuat**: kolom ini tidak ada di dataset OHLCV yang dipakai
  sekarang.
- **Kalau datanya tersedia nanti**: strategi seperti "OI naik + harga naik =
  tren didukung leverage baru" vs "OI turun + harga naik = short covering" bisa
  dibangun sebagai pola/strategi baru lewat `@daftar_pola` tanpa mengubah core
  engine.

## 4. Funding Rate

- **Butuh**: data funding rate periodik dari exchange futures perpetual.
- **Kenapa tidak dibuat**: kolom ini tidak ada di dataset OHLCV yang dipakai
  sekarang.
- **Kalau datanya tersedia nanti**: strategi funding rate ekstrem (kontrarian
  saat funding sangat positif/negatif) bisa jadi kandidat kuat.

## 5. Liquidation heatmap / peta likuidasi

- **Butuh**: data liquidation feed (per exchange) atau estimasi leverage
  agregat, bukan sekadar OHLCV.
- **Kenapa tidak dibuat**: tidak ada sumber data ini di dataset yang dipakai
  sekarang; mengarang estimasi liquidation dari OHLCV saja tidak valid.

## Yang SUDAH dibangun dari OHLCV (bukan bagian daftar tunda ini)

Untuk kejelasan, hal-hal berikut TERLIHAT mirip "order flow" tapi sebenarnya
valid dihitung murni dari OHLCV dan SUDAH ada di modul (lihat `ARSITEKTUR.md` /
`REFERENSI.md` untuk daftar lengkap strategi terdaftar):

- **VWAP sesi + pita deviasi** (`vwap_sesi`, `vwap_pita`) -- murni harga x volume
  per bar, bukan klaim order flow.
- **Volume Profile** (POC/VAH/VAL) -- agregasi volume per level harga dari
  rentang high-low tiap bar (mode Range/Uniform), bukan rekonstruksi trade
  individual.
- **Money Flow Volume** (`delta_volume` di `fitur/lanjutan.py`) -- rumus
  Chaikin/Accumulation-Distribution standar, indikator OHLCV yang sah, secara
  eksplisit didokumentasikan BUKAN CVD dan tidak dipakai untuk klaim order flow.

Ketiganya berbeda dari CVD/order-flow asli karena tidak berpura-pura tahu sisi
agresor transaksi -- hanya memakai volume total per bar yang memang tersedia.
