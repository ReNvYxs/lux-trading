# Laporan Backtest 95 Pair (Tahap 1)

Sumber angka: `reports/besar95/RINGKASAN.json` (dibuat 2026-08-03T12:59:32Z) dan
berkas rinci `reports/besar95/bt95m_*.json`. Dataset: 95 pair Binance USDT-M,
CSV OHLCV `5m/15m/1h/4h/1d`, `LUX_MAKS_BAR=6000` per simbol per TF, modal awal
$1.000 per konfigurasi, dieksekusi di GitHub Actions (matrix 5 konfigurasi).

> **STATUS RUN INI: BASELINE NON-PARITAS.**
> Run ini memakai jalur sizing lama (`ukuran_posisi`) dan belum memakai
> `rencana_posisi()` (leverage otomatis, pembulatan tick/step, gerbang RR
> bersih) yang baru dikunci pada audit 4 Agu 2026. Angka di bawah sah sebagai
> **peringkat relatif dan uji robustness**, tetapi belum sah sebagai proyeksi
> PnL live. Versi paritas dijalankan terpisah lewat `scripts/bt_paritas.py`.

---

## 1. Ringkasan lima konfigurasi

| konfigurasi | trade | win rate | PF bersih | PF kotor | expectancy R | PnL bersih | biaya | max DD | breadth pair profit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `single_5m` | 8.825 | 42,10% | **0,9003** | 0,9987 | −0,0587 | −10.552,84 | 10.420,86 | 11.543,62 | 41,05% (39/95) |
| `single_15m` | 11.192 | 42,07% | 0,9394 | 1,0241 | −0,0347 | −8.420,24 | 11.576,72 | 10.810,60 | 38,95% (37/95) |
| `multi_15m_ctx1h` | 7.375 | 38,54% | 0,9684 | 1,0417 | −0,0193 | −3.176,46 | 7.163,47 | 5.538,52 | **50,53%** (48/95) |
| `multi_1h_ctx4h` | 5.213 | 38,37% | 0,9556 | 0,9991 | −0,0263 | −3.096,40 | 3.033,46 | 6.638,07 | 43,48% (40/92) |
| `single_1h` | 8.958 | 42,48% | **0,9790** | 1,0358 | **−0,0118** | −2.377,39 | 6.269,82 | 7.885,99 | 45,65% (42/92) |

**Temuan utama: kelima konfigurasi rugi bersih.** Namun tiga dari lima punya
**profit factor kotor > 1** (`single_15m` 1,0241; `multi_15m_ctx1h` 1,0417;
`single_1h` 1,0358). Artinya sinyalnya punya edge tipis, dan **biaya transaksi
yang menghabiskannya**, bukan arah prediksi yang salah total.

Edge kotor per trade vs biaya per trade:

| konfigurasi | edge kotor/trade | biaya/trade | selisih |
|---|---:|---:|---:|
| `multi_15m_ctx1h` | +0,5406 | 0,9713 | −0,43 |
| `single_1h` | +0,4345 | 0,6999 | −0,27 |
| `single_15m` | +0,2820 | 1,0344 | −0,75 |
| `multi_1h_ctx4h` | −0,0121 | 0,5819 | −0,59 |
| `single_5m` | −0,0150 | 1,1808 | −1,20 |

Kesimpulan biaya: semakin rendah TF, semakin besar biaya per trade relatif
terhadap edge. `single_5m` adalah yang terburuk di dua sisi sekaligus.

---

## 2. Risk/reward dan struktur kemenangan

| konfigurasi | R rata menang | R rata kalah | payoff ratio R | SL : TP |
|---|---:|---:|---:|---:|
| `multi_15m_ctx1h` | 1,5938 | −1,0306 | 1,5465 | 5.337 : 1.947 (2,74:1) |
| `multi_1h_ctx4h` | 1,5513 | −1,0083 | 1,5385 | 3.818 : 1.309 (2,92:1) |
| `single_1h` | 1,3422 | −1,0115 | 1,3269 | 6.370 : 2.519 (2,53:1) |
| `single_15m` | 1,3184 | −1,0172 | 1,2961 | 7.812 : 3.308 (2,36:1) |
| `single_5m` | 1,2408 | −1,0035 | 1,2365 | 6.074 : 2.691 (2,26:1) |

Profil ini konsisten: **win rate rendah + payoff > 1**. Konfigurasi multi-TF
punya payoff paling tinggi (≈1,55R) walau win rate paling rendah (≈38,5%) -
filter konteks memang membuang sinyal lemah, bukan menambah akurasi.
Secara matematis, dengan payoff 1,546 titik impas win rate ≈ 39,3%; `multi_15m_ctx1h`
ada di 38,54%, yaitu **tepat sedikit di bawah impas** bahkan sebelum biaya.

---

## 3. Asimetri arah - sinyal peringatan rezim

| konfigurasi | LONG PF bersih | LONG PnL | SHORT PF bersih | SHORT PnL |
|---|---:|---:|---:|---:|
| `single_15m` | 0,8824 | −8.973,46 | **1,0088** | +553,22 |
| `multi_15m_ctx1h` | 0,9343 | −3.396,79 | **1,0045** | +220,33 |
| `single_1h` | 0,9257 | −4.413,73 | **1,0380** | +2.036,34 |
| `multi_1h_ctx4h` | 0,9126 | −3.035,44 | 0,9983 | −60,96 |
| `single_5m` | 0,8816 | −6.861,97 | 0,9228 | −3.690,88 |

SHORT lebih baik daripada LONG di **kelima** konfigurasi tanpa kecuali. Ini
hampir pasti properti **periode dataset** (pasar turun), bukan keunggulan
struktural strategi. **Jangan** menonaktifkan LONG berdasarkan temuan ini -
itu persis bentuk overfitting rezim yang dilarang. Yang perlu dilakukan:
uji ulang pada periode dengan rezim berbeda (dataset `lux-ai-research`).

---

## 4. Konsistensi antar paruh waktu (uji stabilitas)

| konfigurasi | PnL paruh 1 | PnL paruh 2 | arah |
|---|---:|---:|---|
| `single_1h` | +723,99 | −3.101,38 | memburuk tajam |
| `single_15m` | −1.020,54 | −7.399,70 | memburuk tajam |
| `multi_1h_ctx4h` | −587,46 | −2.508,94 | memburuk |
| `multi_15m_ctx1h` | −1.638,23 | −1.538,24 | **stabil** |
| `single_5m` | −6.290,75 | −4.262,09 | sedikit membaik |

`multi_15m_ctx1h` adalah satu-satunya konfigurasi yang **stabil antar paruh**
(PF bersih 0,9682 vs 0,9687 - praktis identik). Dari sudut robustness, ini
kandidat terkuat meski PnL-nya belum positif, karena perilakunya tidak
bergantung pada satu jendela waktu.

---

## 5. Performa per kelompok teknik (di mana edge sebenarnya berada)

### Kelompok yang konsisten positif

| kelompok | `multi_15m_ctx1h` | `multi_1h_ctx4h` | `single_15m` | `single_1h` | `single_5m` |
|---|---|---|---|---|---|
| **volatilitas_rezim** | PF 1,162 / +1.484,74 (743 tr) | PF 1,424 / +2.374,06 (499 tr) | 1 trade | 3 trade | PF 0,980 / −2,82 (13 tr) |
| **indikator_momentum** | PF 1,893 / +626,84 (60 tr) | PF 1,517 / +206,49 (34 tr) | PF 1,356 / +963,16 (217 tr) | PF 1,240 / +307,68 (98 tr) | PF 1,180 / +416,51 (179 tr) |

- `volatilitas_rezim` (squeeze/donchian/keltner/supertrend) adalah **satu-satunya
  kelompok dengan PF bersih > 1,15 pada sampel memadai**, dan biaya per trade-nya
  paling murah (0,21-0,50 USD) karena SL-nya lebar relatif terhadap fee.
- `indikator_momentum` punya expectancy R tertinggi (0,12-0,45) tetapi sampelnya
  kecil (34-217 trade; `sampel_cukup: false` di tiga konfigurasi). **Belum boleh
  disimpulkan.**

### Kelompok yang konsisten merugi

| kelompok | pola |
|---|---|
| **level_harga** | PF bersih 0,82-0,945 di **semua** konfigurasi; edge kotor negatif di 4 dari 5 (`single_15m` −1,138/trade, `single_5m` −0,848/trade). Penyumbang kerugian terbesar. |
| **struktur_modern** | PF 0,86-0,95 di 15m/1h/5m; hanya nyaris impas kotor di `multi_15m_ctx1h` (1,0064) walau volumenya besar (3.990 trade). |
| **pola_klasik** | campur: positif di `multi_15m_ctx1h` (PF 1,046), negatif kuat di `single_5m` (PF 0,873) dan `multi_1h_ctx4h` (PF 0,806). |
| **aliran_volume** | campur: positif di `multi_15m_ctx1h` (PF 1,057) dan `single_15m` (PF 1,028), negatif di `multi_1h_ctx4h` (PF 0,923). |

### Strategi yang lolos gerbang kelayakan bawaan

| konfigurasi | `strategi_layak` |
|---|---|
| `multi_15m_ctx1h` | `donchian_breakout`, `squeeze_breakout`, `vwap_reclaim` |
| `multi_1h_ctx4h` | `donchian_breakout` |
| `single_15m` | `vwap_reclaim` |
| `single_1h` | `cup_and_handle` |
| `single_5m` | (tidak ada) |

Yang muncul di lebih dari satu konfigurasi: **`donchian_breakout`**,
**`vwap_reclaim`**. Keduanya juga masuk daftar `strategi_edge_kotor_positif`
di 4-5 konfigurasi bersama `ema_bounce_200`, `cup_and_handle`, dan
`triangle_breakout`.

---

## 6. Performa per pair (breadth)

| konfigurasi | pair profit / pair bertrade | breadth |
|---|---|---:|
| `multi_15m_ctx1h` | 48 / 95 | 50,53% |
| `single_1h` | 42 / 92 | 45,65% |
| `multi_1h_ctx4h` | 40 / 92 | 43,48% |
| `single_5m` | 39 / 95 | 41,05% |
| `single_15m` | 37 / 95 | 38,95% |

Tidak ada konsentrasi edge pada segelintir pair, dan **tidak ada pair yang
mendominasi hasil** - konsisten dengan kebijakan tidak BTC-centric. Sisi
buruknya: tidak ada pair yang bisa dipakai sebagai "jangkar" profit.

---

## 7. Gerbang biaya bekerja, tapi belum cukup

| konfigurasi | entry ditolak biaya | dari alasan |
|---|---:|---|
| `single_5m` | 11.294 | 10.422 biaya > batas risiko; 872 TP1 terlalu dekat |
| `single_15m` | 4.229 | 3.890 / 339 |
| `multi_15m_ctx1h` | 2.321 | 2.234 / 87 |
| `single_1h` | 494 | 435 / 59 |
| `multi_1h_ctx4h` | 181 | 150 / 31 |

Gerbang biaya menolak lebih banyak entry daripada yang diterima di `single_5m`
(11.294 ditolak vs 8.825 dieksekusi) dan hasilnya **tetap** paling merugi. Ini
bukti kuat bahwa **scalping 5m tidak ekonomis** dengan asumsi fee/slippage saat
ini, bukan sekadar masalah ambang.

`entry_batal_gap` hampir nol (0-1) di semua konfigurasi - artinya asumsi eksekusi
backtest tidak terlalu bergantung pada gap harga.

---

## 8. Kesimpulan

1. **Tidak ada konfigurasi yang layak live saat ini.** PF bersih tertinggi 0,979.
2. **Edge ada tetapi tipis** dan berada di kelompok tertentu, bukan merata:
   `volatilitas_rezim` (kuat, sampel memadai) dan `indikator_momentum` (kuat,
   sampel belum cukup).
3. **Kerugian terkonsentrasi** di `level_harga` dan `struktur_modern`.
4. **`single_5m` sebaiknya dihentikan** sebagai kandidat auto-entry: edge kotor
   negatif + biaya per trade tertinggi.
5. **`multi_15m_ctx1h` adalah kandidat paling robust** (satu-satunya yang stabil
   antar paruh, breadth tertinggi, payoff R tertinggi), meski belum profit.
6. Asimetri LONG/SHORT yang ekstrem menandakan **periode dataset ini bias rezim**;
   kesimpulan apa pun wajib diuji ulang pada periode berbeda.

## 9. Langkah berikutnya (tanpa optimasi kosmetik)

1. Jalankan ulang versi **paritas engine** (`rencana_posisi`, leverage otomatis,
   pembulatan tick/step, gerbang RR bersih) agar angka dapat dibandingkan dengan
   Testnet/Live.
2. Uji subset kelompok positif (`volatilitas_rezim` + `donchian_breakout` +
   `vwap_reclaim`) **tanpa mengubah parameter internal strategi**, semata untuk
   mengukur apakah membuang kelompok merugi cukup membalikkan PF.
3. Aktifkan `LUX_RR_BERSIH_MIN` dan ukur trade-off jumlah trade vs expectancy.
4. Validasi out-of-sample pada dataset lebih besar dari `lux-ai-research` /
   `lux-trading-strategy` (periode dan rezim berbeda) sebelum kesimpulan apa pun
   dianggap final.
5. Bandingkan dengan hasil Testnet/Live operator: slippage, spread, latency,
   funding fee, dan likuiditas nyata.

**Prinsip yang dipegang:** tidak ada parameter yang disetel ulang hanya agar
angka backtest terlihat bagus. Semua angka di atas dilaporkan apa adanya,
termasuk yang buruk.
