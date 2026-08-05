# REFERENSI - Sumber aturan entry / SL / TP per strategi

Catatan penting: seluruh angka di bawah ini hanyalah **titik awal parameter** dari
literatur publik. **Kebenaran akhir ditentukan hasil uji data**, bukan sumbernya.
Setiap kali parameter diubah, wajib diuji ulang.

## Kelompok 1 - Pola klasik

### `double_top` / `double_bottom`
- Entry: penembusan neckline (lembah di antara dua puncak / puncak di antara dua lembah).
- SL: di atas puncak kedua (top) atau di bawah lembah kedua (bottom).
- TP: measured move = tinggi pola diproyeksikan dari titik breakout.
- Sumber: investopedia.com/terms/d/doubletop.asp,
  trendspider.com/learning-center/chart-patterns-double-bottoms-and-tops/,
  tastyfx.com, oanda.com, tradezero.com
- Implementasi: toleransi kesamaan puncak dan kedalaman lembah dinilai jadi komponen skor,
  bukan filter keras.

### `head_shoulders` (termasuk inverse)
- Entry: penembusan neckline setelah bahu kanan terbentuk.
- SL: di luar bahu kanan.
- TP: |head - neckline| diproyeksikan dari titik breakout.
- Sumber: investopedia.com/articles/technical/121201.asp, oanda.com, schwab.com, ig.com

### `triangle_breakout`
- Entry: penembusan garis tren pembatas segitiga (ascending / descending / symmetrical).
- SL: di sisi berlawanan segitiga.
- TP: tinggi terlebar segitiga dari titik breakout.
- Sumber: investopedia, chartmill.com, trendspider.com

### `wedge_breakout`
- Falling wedge: long saat menembus garis atas. Rising wedge: short saat menembus garis bawah.
- SL: di luar garis tren yang berlawanan.
- TP: tinggi terlebar wedge.
- Sumber: tradingsim.com, chartmill.com, trendspider.com, fxopen.com, naga.com, quantvps.com

### `cup_and_handle`
- Entry: penembusan resistance handle, idealnya volume >= +40-50% terhadap rata-rata 20 periode.
- SL: di bawah low handle atau 2-3x ATR.
- TP bertingkat: 62% / 100% / 161.8% dari kedalaman cup.
- Hanya LONG. Sumber: investopedia.com/terms/c/cupandhandle.asp, luxalgo.com, fidelity.com,
  tradingsim.com

## Kelompok 2 - Indikator / momentum

### `ema_bounce_200`
- Harga di atas EMA200 -> hanya long, di bawah -> hanya short.
- Entry: pullback menyentuh EMA200 lalu ditolak (candle penolakan tutup ke arah tren).
- SL: di bawah EMA200 atau low pullback.
- TP: swing high sebelumnya atau RRR 1:2 - 1:3.
- Sumber: beatmarket.com/blog/200-ema-strategy/, snappchart.app, investopedia
- **Peringatan hasil publik**: satu backtest mekanis melaporkan net -$2.739, win rate 18%,
  profit factor 0.53 atas 22 trade. Karena itu ambangnya paling rendah (58) dan strategi ini
  wajib diperiksa serius pada tahap validasi data - kandidat kuat untuk dibuang bila merugi.

### `rsi_divergence`
- Bullish: harga lower low + RSI higher low. Bearish: harga higher high + RSI lower high.
- Entry: setelah konfirmasi penembusan struktur kecil, bukan pada saat divergensi terbentuk.
- SL: di luar ekstrem divergensi.
- TP: 1.5R - 3R.
- Sumber: altfins.com, tradeciety.com, tradingview.com

### `macd_rsi_trendbreak` (multi-TF, context = 1)
- Gabungan tiga syarat: divergensi MACD, divergensi RSI searah, dan penembusan garis tren.
- Konteks TF lebih tinggi harus searah, kalau tidak skor dipangkas.
- SL: di luar ekstrem divergensi. TP: RR bertingkat 1.5R / 3R.
- Sumber: investopedia MACD divergence, tradeciety.com, altfins.com

## Kelompok 3 - Struktur modern

### `smc_ob_fvg` (multi-TF, context = 1)
- BOS -> harga retrace ke order block atau fair value gap -> entry pada mitigasi.
- SL: di luar order block.
- TP: likuiditas berlawanan (swing high/low sebelumnya).
- Sumber: tradingwyckoff.com/en/smart-money-concepts/, fluxcharts.com, innercircletrader.net

### `ict_liquidity_sweep`
- Sweep likuiditas (menembus swing lalu tutup kembali di dalam) -> CHoCH -> entry.
- SL: di luar ekstrem sweep.
- TP: pool likuiditas sisi berlawanan.
- Sumber: innercircletrader.net/tutorials/ict-liquidity-sweep-vs-liquidity-run/,
  dailypriceaction.com/blog/liquidity-sweep-reversals/, atas.net, phidiaspropfirm.com

### `breakout_volume`
- Entry: penembusan rentang konsolidasi dengan volume >= 1.5x rata-rata.
- SL: kembali ke dalam rentang atau 2x ATR.
- TP: tinggi rentang diproyeksikan.
- Sumber: investopedia.com/articles/trading/08/trading-breakouts.asp, tradingsim.com

## Kelompok tambahan (plugin, pasca-revisi CVD)

### `aliran_volume`: `vwap_reclaim`, `vwap_reversi_pita`, `vp_tepi_value_area`
- VWAP sesi + pita deviasi + reclaim/reversi/tepi value-area, semua murni dari OHLCV.
- Sumber: investopedia.com VWAP, trademomentum.org, scanz.com, crosstrade.io,
  thevwap.com, quantvps.com, trendspider.com, tastylive.com.
- CVD sengaja tidak ada di kelompok ini - lihat `CALON_STRATEGI.md`.

### `level_harga`: `fib_golden_pocket`, `pivot_reversal`, `level_bulat`
- Sumber: investopedia.com fibonacci, quantum-algo.com, thinkmarkets.com,
  investopedia.com pivot point, babypips.com, investopedia.com round numbers.

### `volatilitas_rezim`: `squeeze_breakout`, `donchian_breakout`, `keltner_reversi`,
`supertrend_flip`
- Sumber: stockcharts.com BB/KC squeeze, trendspider.com, crosstrade.io Donchian,
  altrady.com, investopedia.com Supertrend, quantifiedstrategies.com Keltner.

### `struktur_modern` tambahan: `breaker_block`, `market_structure_shift`, `fvg_fill`,
`order_block_retest`
- Sumber: innercircletrader.net breaker block/MSS/FVG, fluxcharts.com, atas.net,
  tradingwyckoff.com.

## Ringkasan konvensi bersama

1. Semua SL punya cadangan ATR (`buffer`) agar tidak persis di level struktur.
2. Semua TP disaring supaya RR TP pertama minimal masuk akal; setup dengan RR terlalu
   rendah diturunkan skornya, bukan dipaksa lolos.
3. Tidak ada strategi yang boleh memakai lilin yang belum tutup.
4. Strategi yang membutuhkan data di luar OHLCV (order flow, CVD asli, open interest,
   funding rate) TIDAK dipaksakan masuk - didokumentasikan sebagai calon pengembangan
   di `CALON_STRATEGI.md`.
