# ARSITEKTUR - Modul Trading Multi-Strategi Binance Futures

Versi: 0.3.0 (P0 sinkronisasi + kebijakan post-only selesai; governor lintas-runner,
bracket tracking live, dan kontrak notifikasi Telegram per horizon selesai;
validasi dataset besar dan dashboard real-time belum dimulai)
Bahasa kerja: Indonesia. Kode dan nama modul memakai istilah Indonesia,
kecuali nama yang dikunci operator: `calculate_dynamic_risk()`, `plan_execution()`,
`entry_invalidated()`, `visible_qty`, `required_roles`.

## 1. Enam lapis (+ governor lintas-runner di lapis live)

Aliran wajib: **data -> fitur -> strategi -> pembobotan -> eksekusi -> portofolio**.
Setiap lapis hanya boleh memanggil lapis di atasnya (indeks lebih kecil).

| Lapis | Paket | Tanggung jawab | DILARANG |
|---|---|---|---|
| L0 | `lux_modul/data` | muat CSV, rapikan, resample TF, keselarasan waktu | menyentuh logika strategi |
| L1 | `lux_modul/fitur` | indikator dan struktur pasar murni per TF, warmup dideklarasikan | melihat lilin masa depan |
| L2 | `lux_modul/strategi` | kumpulan strategi mandiri, masing-masing entry/SL/TP | membaca verdict strategi lain |
| L3 | `lux_modul/arbiter` | ambang, pemilihan skor tertinggi, resolusi konflik arah | menghitung fitur sendiri |
| L4 | `lux_modul/eksekusi` | sizing, risk, kebijakan order post-only, ice-breaker, gerbang biaya, mode auto/sinyal | membentuk sinyal |
| L5 | `lux_modul/portofolio.py` | kapasitas 4 slot beda pair, ledger sinyal terlewat (backtest single-proses) | menilai kualitas sinyal / memilih strategi |
| L5-live | `lux_modul/governor.py` | kuota + margin **lintas-runner** untuk live trading multi-pair (`mesin_multi.py`), snapshot akun nyata per siklus | menilai kualitas sinyal; auto-entry untuk swing |

`lux_modul/pipeline.py` merangkai L0..L4 dan tidak berisi logika trading.
L5 (`ManajerSlot`) dipasang di atas hasil pipeline saat backtest multi-simbol
(`backtest_portofolio.py`); ia murni kapasitas, tidak pernah dipanggil dari dalam
L2/L3 sehingga tidak menciptakan strategi "raja". Untuk live trading multi-pair
(satu `LiveRunner` per pair, dikoordinasikan `MesinMultiPair`), `GovernorPortofolio`
menggantikan peran ini dengan tambahan: snapshot akun **nyata** (bukan simulasi),
margin, dan larangan hedge - lihat bagian 9.1.

## 2. Kontrak inti (`lux_modul/kontrak.py`)

- `Bars(tf, ts, open, high, low, close, volume, simbol)` - kolom numpy, `ts` epoch
  milidetik waktu **buka** lilin. Validasi: panjang sama, `ts` menaik ketat,
  `high >= low`.
  - `ts_tutup(i)` = `ts[i] + durasi_ms`
  - `hingga_indeks(i)`, `hingga_waktu_tutup(batas_ts)` - satu-satunya jalan potong data,
    dipakai untuk mencegah look-ahead.
- `TFPlan(entry_tf, context_tfs)` - realisasi konkret dari `required_roles`.
  Validasi: setiap TF konteks harus **lebih besar** dari TF entry, tanpa duplikat.
  - `single_tf == True` bila `context_tfs` kosong.
- `StrategyVerdict` - keluaran tunggal setiap strategi:
  `strategy_id, kelompok, arah, skor, ambang, entry, sl, tps, level, invalidation,
  tfs_used, features_used, evidence, ts_sinyal`.
  Validasi keras: arah valid, `0 <= skor <= 100`, SL di sisi yang benar terhadap entry,
  TP di sisi yang benar, jumlah `porsi` TP <= 1.0.
- `Penolakan(strategy_id, kode, pesan)` dengan kode:
  `peran_tf_tak_terpenuhi`, `horizon_tak_didukung`, `warmup_kurang`, `tak_ada_setup`,
  `galat_internal`, `skor_di_bawah_ambang`.
- Kelompok teknik (`KELOMPOK_VALID`) BUKAN daftar tertutup: `DaftarKelompok` di
  `plugin.py` memungkinkan plugin pihak ketiga menambah kelompok baru lewat
  `daftar_kelompok("nama_baru")` tanpa menyunting `kontrak.py`.
- **Horizon dan mode (ditambahkan untuk live trading, 4 Agu 2026)**:
  `HORIZON_SCALPING`, `HORIZON_INTRADAY`, `HORIZON_SWING`; `MODE_SIGNAL_ONLY`,
  `MODE_PER_HORIZON` - dipakai `eksekusi/mode.py` dan `governor.py` untuk menentukan
  horizon mana yang boleh auto-entry.

## 3. Model peran TF (`required_roles`)

Strategi TIDAK menyebut nama TF. Ia menyebut peran:

```python
required_roles = {"entry": True, "context": 0}   # single-TF
required_roles = {"entry": True, "context": 1}   # butuh 1 TF konteks lebih tinggi
```

Saat runtime, `TFPlan` memetakan peran ke TF nyata (`5m` entry, `15m`/`1h` konteks).
Registry hanya menolak strategi bila jumlah TF konteks yang disediakan kurang dari
`context` yang diminta (`peran_tf_tak_terpenuhi`) - **bukan** menolak seluruh evaluasi.
Akibatnya strategi single-TF dan multi-TF hidup berdampingan di satu registry tanpa
mengubah inti arsitektur maupun cara pembobotan.

Kegagalan lama yang dihindari: modul terdahulu mengunci 15m/1h/4h dan mensyaratkan
skor HTF 3-dari-3, sehingga strategi single-TF secara struktural mustahil menang.

## 4. Anti look-ahead

Tiga lapis pengaman:

1. `DataPlane.konteks_pada(i, plan, horizon)` memotong TF entry ke `hingga_indeks(i)`
   dan setiap TF konteks ke `hingga_waktu_tutup(ts_tutup(i))`. Lilin konteks yang belum
   tutup pada saat itu tidak pernah terlihat.
2. Seluruh fungsi di `fitur/dasar.py` bersifat kausal (SMA/EMA/RMA/RSI/MACD/ATR/Bollinger),
   nilai pada indeks `i` hanya bergantung pada `<= i`. Diuji: nilai indeks `i` identik
   ketika data setelah `i` dihapus.
3. Pivot dikonfirmasi (`pivots(kiri, kanan)`) sehingga pivot terakhir yang bisa dipakai
   selalu berjarak `kanan` lilin dari bar sekarang.

`resample()` membuang lilin periode terakhir bila belum lengkap (`buang_parsial=True`).

## 5. Lapis fitur

- `fitur/dasar.py` - `sma, ema, rma, rsi, macd, true_range, atr, stdev, bollinger,
  rolling_max, rolling_min, kemiringan, rasio_volume, badan, sumbu_atas, sumbu_bawah,
  aman_bagi, skala`.
- `fitur/struktur.py` - `pivots`, `struktur_tren` (HH/HL vs LH/LL), `peristiwa_struktur`
  (BOS / CHoCH), `fair_value_gaps`, `order_block_sebelum` (wajib argumen `arah`),
  `rentang_konsolidasi`, `garis_lewat_pivot`, `sapuan_likuiditas`.
- `fitur/store.py` - `FeatureStore`, cache per `(id(close), tf, panjang, nama, args)`.
  `hitung(nama, bars, *args)` memanggil indikator apa pun dari `KATALOG_INDIKATOR`
  (lapis plugin), sehingga indikator baru tidak perlu method baru di `FeatureStore`.
- `fitur/lanjutan.py` - indikator lanjutan yang HANYA dihitung dari OHLCV murni:
  `delta_volume` (Money Flow Volume, BUKAN CVD), `vwap_sesi`, `vwap_pita`,
  `volume_profile` (POC/VAH/VAL), `keltner`, `squeeze_bb_kc`, `donchian`, `supertrend`,
  `adx` (dengan `_bagi_aman_larik` elementwise-safe), `stoch_rsi`, `fibonacci`,
  `pivot_klasik`. CVD asli, order flow, open interest, dan funding rate SENGAJA
  tidak dibuat di sini - lihat `CALON_STRATEGI.md`.

## 6. Lapis strategi - arsitektur plugin-based, terbuka

**Prinsip wajib**: daftar strategi/pattern/indikator TIDAK PERNAH dipatok tetap.
Tidak ada strategi "raja"/blocker di lapis mana pun, termasuk L5 (portofolio hanya
kapasitas, bukan penilai kualitas) dan L5-live (governor hanya kuota+margin, bukan
penilai kualitas). `lux_modul/plugin.py` menyediakan empat katalog terbuka:

1. `KATALOG_STRATEGI` (lewat `@daftar_strategi`) - kelas `Strategi` lengkap.
2. `KATALOG_POLA` (lewat `@daftar_pola`) - fungsi detektor pattern murni yang
   dibungkus otomatis jadi strategi penuh oleh `StrategiPola` (`strategi/adaptor.py`).
3. `KATALOG_INDIKATOR` (lewat `@daftar_indikator`) - fungsi indikator murni.
4. `DaftarKelompok` - nama kelompok teknik, boleh bertambah.

`muat_plugin(direktori_luar=...)` mengimpor seluruh submodul `lux_modul.strategi`
(memicu efek samping dekorator) DAN berkas `.py` lepas dari direktori eksternal
(env var `LUX_PLUGIN_PATHS`, dipisah `os.pathsep`). Ini membuktikan strategi baru
bisa hidup di luar repo inti tanpa menyunting satu baris pun core engine
(`arbiter`/`eksekusi` tidak pernah tahu berapa banyak strategi terdaftar).

Setiap strategi/pola: punya `id`, `kelompok`, `ambang`, `warmup`, `required_roles`,
`horizon_didukung`, `sumber` (referensi riset), dan mengembalikan `StrategyVerdict |
None`. Strategi **stateless**: tidak menyimpan state lintas lilin dan tidak boleh
membaca hasil strategi lain.

### 6.1 KATALOG_STRATEGI - 12 kelas warisan fase-1

| id | kelompok | TF | ambang | warmup | arah |
|---|---|---|---|---|---|
| `double_top` | pola_klasik | single | 62 | 80 | SHORT |
| `double_bottom` | pola_klasik | single | 62 | 80 | LONG |
| `head_shoulders` | pola_klasik | single | 64 | 120 | dua arah |
| `triangle_breakout` | pola_klasik | single | 60 | 90 | dua arah |
| `wedge_breakout` | pola_klasik | single | 61 | 90 | dua arah |
| `cup_and_handle` | pola_klasik | single | 63 | 140 | LONG |
| `ema_bounce_200` | indikator_momentum | single | 58 | 220 | dua arah |
| `rsi_divergence` | indikator_momentum | single | 60 | 120 | dua arah |
| `macd_rsi_trendbreak` | indikator_momentum | **context=1** | 66 | 150 | dua arah |
| `smc_ob_fvg` | struktur_modern | **context=1** | 65 | 120 | dua arah |
| `ict_liquidity_sweep` | struktur_modern | single | 62 | 100 | dua arah |
| `breakout_volume` | struktur_modern | single | 59 | 80 | dua arah |

### 6.2 KATALOG_POLA - 14 pattern berbasis `@daftar_pola`

**Kelompok `aliran_volume`** (`strategi/aliran_volume.py`, CVD sengaja tidak ada -
lihat `CALON_STRATEGI.md`): `vwap_reclaim` (ambang 62, warmup 120, context 0),
`vwap_reversi_pita` (63, 150, 0, filter ADX<=25), `vp_tepi_value_area` (61, 280, 0).

**Kelompok `level_harga`** (`strategi/level_harga.py`): `fib_golden_pocket`
(63, 140, context 1, rr 1.618/2.618), `pivot_reversal` (60, 120, 0), `level_bulat`
(59, 100, 0).

**Kelompok `volatilitas_rezim`** (`strategi/volatilitas.py`): `squeeze_breakout`
(62, 140, context 1), `donchian_breakout` (60, 120, context 1, sl_atr 2.0),
`keltner_reversi` (61, 120, 0), `supertrend_flip` (60, 130, context 1).

**Kelompok `struktur_modern` tambahan** (`strategi/struktur_plus.py`, terpisah dari
`struktur_modern.py` lama - bukti nyata penambahan strategi tanpa menyentuh berkas
lama): `breaker_block` (65, 160, context 1, sl_atr 0.9, rr 2.0/3.0),
`market_structure_shift` (63, 150, context 1), `fvg_fill` (61, 130, context 1),
`order_block_retest` (62, 150, context 1).

### 6.3 KATALOG_INDIKATOR - 12 fungsi murni

`adx, delta_volume, donchian, fibonacci, keltner, pivot_klasik, squeeze_bb_kc,
stoch_rsi, supertrend, volume_profile, vwap_pita, vwap_sesi` - semua didaftarkan
lewat `@daftar_indikator` di `fitur/lanjutan.py`.

### 6.4 Total dan verifikasi

`ringkas_registry()` (di `strategi/__init__.py`) melaporkan: **12 strategi + 14 pola
+ 12 indikator = 26 unit terdaftar**, di **6 kelompok teknik**
(`aliran_volume, indikator_momentum, level_harga, pola_klasik, struktur_modern,
volatilitas_rezim`). CVD dikonfirmasi tidak ada di ketiga katalog. Semua parameter
awal berasal dari riset publik (lihat `REFERENSI.md`) dan **belum** divalidasi pada
dataset besar (95 pair).

## 7. Lapis pembobotan (`arbiter/pemilih.py`)

Urutan tetap setiap lilin:

1. `Registry.evaluasi_semua(ctx)` mengevaluasi **seluruh** strategi. Tidak ada `break`,
   tidak ada `return` dini. Galat satu strategi ditangkap jadi `Penolakan(galat_internal)`
   dan tidak menjatuhkan yang lain.
2. Saring kandidat: `skor > ambang` (**ketat lebih besar**, bukan `>=`).
3. Bila kosong -> `tak_ada_kandidat` / `semua_di_bawah_ambang`, **tidak ada entry**.
4. Urutkan `(-skor, strategy_id)`. Kunci kedua membuat hasil deterministik dan tidak
   bergantung urutan pendaftaran.
5. Aturan konflik arah: bila kandidat terbaik LONG dan kandidat terbaik SHORT sama-sama
   lolos ambang dan `|skor_long - skor_short| < MARGIN_KONFLIK` (**5.0 poin**),
   sinyal dianggap saling meniadakan -> `konflik_arah_saling_meniadakan`, **tidak ada entry**.
   Selisih >= 5.0 -> yang skornya lebih tinggi dieksekusi.
6. Selain itu: `skor_tertinggi_di_atas_ambang`.

Statistik per lilin dicatat (`kandidat_per_strategi`, `menang_per_strategi`) supaya
dominasi satu setup langsung kelihatan, bukan tersembunyi seperti pada modul lama
(di sana `detect_triangle` muncul 16.055 kali tapi menang 0 kali karena short-circuit).
Menambah strategi baru tidak mengubah satu baris pun berkas ini - bukti arsitektur
plugin-based nyata sampai ke lapis pembobotan.

## 8. Lapis eksekusi

### 8.1 Mode per horizon (`eksekusi/mode.py`)

| horizon | mode |
|---|---|
| `scalping` | `auto_entry` |
| `intraday` | `auto_entry` |
| `swing` | `signal_only` |

`pastikan_boleh_eksekusi(horizon)` melempar `ModeTerlarang` untuk swing. Pipeline pada
horizon swing hanya menghasilkan objek `Sinyal` - tanpa sizing, tanpa rencana order.
Swing **tidak pernah** diantre ke `GovernorPortofolio` untuk auto-entry (lihat 9.1)
dan **tidak pernah** dikirim ke Telegram (lihat 9.2) - hanya tampil di dashboard.

### 8.2 Risiko (`eksekusi/risiko.py`, rumus TIDAK BOLEH diubah)

```python
# saldo < $20 atau <= 0
risk_pct = clamp(0.03 * (20 / balance) ** 0.55, 0.005, 0.03)
risk_usd = max(0.20, balance * risk_pct)   # $0.20 = LANTAI, bukan nilai flat
```

Saldo `<= 0` mengembalikan batas atas 3%.

Tier untuk saldo >= $20:

| saldo | risk% |
|---|---|
| < 100 | 3.0% |
| < 1.000 | 2.5% |
| < 10.000 | 2.0% |
| < 50.000 | 1.5% |
| < 100.000 | 1.0% |
| >= 100.000 | taper `0.01 * (100k/balance)^0.35`, lantai **0.25%** |

Kurva bersifat tidak naik terhadap saldo (diuji). Tujuan: menjaga risiko absolut dan
memperkecil jejak eksekusi agar tidak mudah kena stop-hunt.

`ukuran_posisi(balance, entry, sl, leverage_maks=20.0, qty_step=0.0,
notional_min=0.0) -> Sizing` menghitung `qty = risk_usd / |entry - sl|`, lalu memotong
berdasarkan `leverage_maks` dan mencatat `terpotong_oleh`.

### 8.3 Semantik invalidasi dan lantai ATR (`strategi/util.py::sl_valid`)

Setiap strategi/pola (lewat `StrategiPola` di `strategi/adaptor.py`) menghitung SL
sebagai sisi TERJAUH antara invalidasi struktural pattern (`d.invalidation`, mis. batas
zona order block, batas FVG) dan buffer `spek.sl_atr * ATR`:

```python
buffer = spek.sl_atr * atr
sl_mentah = min(invalidation, harga - buffer)      # LONG (max untuk SHORT)
sl = sl_valid(arah, harga, sl_mentah, minimum=0.15 * atr)
```

`sl_valid()` menegakkan jarak MINIMUM `0.15 * ATR` dari entry, bukan jarak maksimum:
- Untuk LONG: `sl_final = min(sl_mentah, entry - 0.15*ATR)` - mengambil sisi yang LEBIH
  JAUH dari entry di antara keduanya.
- Artinya bila invalidasi struktural sudah lebih jauh dari 0.15 ATR, lantai ini
  **tidak berpengaruh** dan SL struktural dipertahankan apa adanya.
- Bila invalidasi struktural terlalu rapat (< 0.15 ATR dari entry, mis. karena zona
  order block/FVG sangat tipis), lantai ini melebarkan SL ke `0.15 * ATR` supaya SL
  tidak nol/terlalu dekat dan tidak langsung tersapu noise. Ini SATU-SATUNYA situasi
  di mana lantai "menimpa" nilai struktural - dan hanya untuk melebarkan, bukan
  mempersempit invalidasi yang sudah valid.
- Level buffer per-pola (`sl_atr`, contoh: `breaker_block`=0.9, `donchian_breakout`=2.0)
  saat ini hardcode di setiap `@daftar_pola`/`@daftar_strategi`; belum dieksternalisasi
  ke konfigurasi (lihat bagian 13, pending).

### 8.4 Ice-breaker (`eksekusi/ice_breaker.py`)

- `plan_execution(simbol, arah, qty, harga, sl=None)`.
- Notional < `AMBANG_NOTIONAL_ICEBERKER` ($5.000) -> **1 slice, baseline tidak berubah**.
- Di atas ambang -> TWAP + iceberg: `NOTIONAL_PER_SLICE = $2.500`, maksimum `SLICE_MAKS = 12`
  slice, jeda `JEDA_DETIK = 1.5` detik, `visible_qty = 25%` dari qty slice.
- **Perbaikan bug lama 1**: `Slice.payload()` benar-benar mengirim `visible_qty` **dan**
  `icebergQty` ke exchange, bukan sekadar menghitungnya. Diuji dengan menangkap payload.
- **Perbaikan bug lama 2**: `IceBreakerExecutor.jalankan()` adalah `async`; jeda antar
  slice memakai `await tidur(...)`, bukan `time.sleep`. Event loop tetap responsif
  (diuji dengan tugas paralel). `jalankan_sinkron()` disediakan untuk pemanggil non-async.
- `entry_invalidated(arah, harga, sl)` dievaluasi sebelum tiap slice. Bila harga sudah
  menembus SL sebelum semua slice terkirim, sisa slice dibatalkan dan
  `HasilEksekusi.alasan_batal = "entry_invalidated"`.
- Sejak putaran 3, slice entry memakai payload `LIMIT + GTX` (lihat 8.5), bukan lagi
  asumsi market/limit polos.

### 8.5 Kebijakan order (`eksekusi/order.py`) - post-only entry wajib, TP boleh market (RALAT 4 Agu 2026)

- **Entry**: `LIMIT` + `timeInForce=GTX` (post-only) TETAP wajib, tidak berubah dari
  keputusan 3 Agu 2026. `TIPE_TERLARANG_ENTRY = ("MARKET", "TRAILING_STOP_MARKET")`
  (alias backward-compat: `TIPE_TERLARANG`). `pastikan_tanpa_market()` melempar
  `OrderTerlarang` bila payload entry memakai salah satu tipe ini, atau bila `LIMIT`
  tidak memakai `timeInForce=GTX`, **atau** bila `TAKE_PROFIT_MARKET` dipakai di jalur
  entry (ditolak eksplisit, bukan hanya lolos karena tidak ada di daftar terlarang).
- **SL** (`payload_sl`): `STOP_MARKET`, `workingType=MARK_PRICE`, `closePosition=True`
  (atau `reduceOnly` + `quantity` bila tidak menutup penuh posisi). Pengecualian resmi
  pertama terhadap larangan market, ditegakkan lewat `KebijakanOrder.izinkan_market_untuk_sl`
  (default `True`).
- **TP** (`payload_tp`): tetap tersedia sebagai `LIMIT` + `GTX` + `reduceOnly=True`
  (maker, fee lebih murah) - **DAN** kini ada `payload_tp_market()`: `TAKE_PROFIT_MARKET`
  + `closePosition=True` + `workingType=MARK_PRICE`. Ini pengecualian resmi **kedua**
  terhadap larangan market, ditegakkan lewat `KebijakanOrder.izinkan_tp_market`
  (default `True`). Alasan: TP menutup posisi yang **sudah ada**, ia tidak membuka
  posisi baru seperti MARKET entry yang diharamkan - risikonya berbeda secara kualitatif.
- **`payload_bracket()`** (baru): mengembalikan `(payload_sl, payload_tp_market)` siap
  dikirim berurutan setelah entry LIMIT GTX terisi - inilah yang dipakai
  `live_runner.py` untuk memasang SL+TP sekaligus pada posisi baru (lihat 8.7).
- **Harga post-only** (`harga_post_only`): digeser `offset_tick` tick ke sisi maker -
  LONG di bawah `min(harga_acuan, best_bid)`, SHORT di atas `max(harga_acuan, best_ask)`.
- **Re-quote** (`rencana_requote`): menghasilkan daftar harga percobaan ke-1..
  `maks_requote` (default 3), masing-masing menjauh dari pasar `offset_tick * i`. Bila
  seluruh percobaan gagal terisi (selalu crossing) -> sinyal DIBATALKAN, TIDAK PERNAH
  jatuh ke market order untuk entry.
- **Diverifikasi di Binance Testnet (4 Agu 2026, GitHub Actions)**: LIMIT GTX diterima;
  `STOP_MARKET closePosition` dan `TAKE_PROFIT_MARKET closePosition` diterima saat
  posisi terbuka nyata ada. Bug serialisasi bool Python (`True` terkirim sebagai
  string `"true"` bukan JSON boolean, penyebab -1111 lama) sudah diperbaiki di
  `format_nilai`. Kegagalan -4120 yang sempat terlihat pada percobaan tanpa posisi
  terbuka adalah batasan environment testnet, bukan bug kode - lihat catatan di
  STATE.md.

### 8.6 Gerbang biaya asimetris (`eksekusi/biaya.py`)

Gerbang biaya berlaku universal untuk semua strategi (bukan penilaian kualitas sinyal)
dan TIDAK menyentuh `risiko.py`. Sejak kebijakan post-only (8.5), model biaya menjadi
asimetris karena entry/TP membayar fee **maker** dan hanya kaki keluar darurat (SL)
yang membayar **taker** + slippage:

| Kaki | Tipe order | Fee | Slippage |
|---|---|---|---|
| Entry | LIMIT + GTX | 2 bps (maker) | 0 |
| TP (tiap target) | LIMIT + GTX reduceOnly | 2 bps (maker) | 0 |
| SL | STOP_MARKET closePosition | 5 bps (taker) | 2 bps |

`biaya_pp_round_trip(n_tp)` = 1 fill masuk maker + `(k-1)` fill TP maker + 1 fill keluar
darurat taker, dengan `k = min(n_tp, FILL_KELUAR_MAKS=3)`. Jalur keluar TERAKHIR selalu
dihitung sebagai keluar darurat (taker) supaya estimasi tetap konservatif walau posisi
akhirnya keluar lewat TP. Hasil: round trip **9 bps** (1 TP) sampai **13 bps** (3 TP),
dibanding 21-28 bps pada model taker-simetris lama. Catatan: model biaya ini dihitung
untuk backtest dengan TP LIMIT+GTX; bila live memakai `payload_tp_market()` (8.5), kaki
TP menjadi taker juga - belum direfleksikan ke `biaya.py` (lihat bagian 13, pending).

Ambang kelayakan: `RASIO_BIAYA_MAKS=0.20` (biaya round-trip <= 20% dari 1R),
`KELIPATAN_TP1_MIN=3.0` (TP1 minimal 3x biaya round-trip di atas impas),
`FILL_KELUAR_MAKS=3` (TP lebih dari 3 dipangkas oleh `batas_tp_efektif()`, porsi ekor
digabung ke target terakhir yang dipertahankan). Kode penolakan:
`biaya_melebihi_batas_risiko`, `tp1_terlalu_dekat_terhadap_biaya`. Nonaktifkan hanya
untuk diagnostik: `LUX_SARING_BIAYA=0`.

### 8.7 Bracket tracking live (`live_runner.py`, BARU 4 Agu 2026)

`LiveRunner` melacak siklus hidup order secara eksplisit lewat dua state:

- `_EntryPending` - order entry LIMIT GTX terkirim, belum terisi. Diperiksa setiap poll
  lewat `_periksa_entry_pending()`; timeout `BRACKET_POLL_TIMEOUT_MS` (4 jam) ->
  order dibatalkan, tidak menunggu selamanya.
- `_BracketAktif` - entry sudah terisi, `payload_bracket()` (SL+TP) sudah dipasang.
  Diperiksa lewat `_periksa_bracket_aktif()`; timeout `MONITOR_TIMEOUT_MS` (7 hari).

Setiap transisi (entry dikirim -> entry terisi -> SL/TP ter-trigger) memanggil method
notifier yang sesuai (lihat 9.2). Sebelum entry dieksekusi, `LiveRunner` memanggil
`pemeriksa_entry_fn` (closure dari `MesinMultiPair`, lihat 9.1); bila closure ini
melempar exception, `LiveRunner` **menolak entry** (`return siklus` dengan
`alasan_ditolak_governor="governor_error"`) - **bug fail-open yang diperbaiki 4 Agu
2026**: sebelumnya kode ini tidak melakukan `return` setelah menangkap exception,
sehingga entry tetap dieksekusi tanpa pengawasan governor.

## 9. Lapis portofolio

### 9.0 Backtest single-proses (`lux_modul/portofolio.py`, L5, tidak berubah)

`ManajerSlot(maks_posisi=4)` mengelola kapasitas posisi bersamaan untuk backtest
multi-simbol:

- **Maksimum 4 posisi terbuka bersamaan, wajib beda pair** (`punya_posisi(simbol)`
  menolak simbol yang sudah punya posisi; `alasan_tolak` mengembalikan
  `simbol_sudah_punya_posisi` atau `slot_penuh`).
- Manajer **tidak menilai kualitas sinyal**: siapa yang datang lebih dulu saat slot
  kosong yang menang. Ini murni kapasitas, bukan strategi "raja" - diuji eksplisit di
  `tests/test_portofolio.py` ("manajer tidak memilih berdasar kualitas").
- Sinyal valid yang gagal masuk karena kapasitas dicatat sebagai `SinyalTerlewat`
  (bukan dibuang diam-diam): `ts, simbol, arah, strategy_id, kelompok, skor, ambang,
  entry, sl, tp1, r_teoretis, alasan, simbol_pemegang_slot`.
- `ringkas_terlewat()` mengagregasi jumlah per alasan/strategi/simbol untuk
  ditampilkan di dashboard (tab "Sinyal Terlewat").
- `backtest_portofolio.py` (L4/L5 bersama) menjalankan pipeline per simbol lalu
  menyalurkan hasil ke satu `ManajerSlot` bersama dan satu kurva ekuitas (saldo
  tunggal), bukan saldo terpisah per simbol.

### 9.1 `GovernorPortofolio` - kuota & margin lintas-runner live (`lux_modul/governor.py`, BARU 4 Agu 2026)

Untuk live trading, `MesinMultiPair` menjalankan satu `LiveRunner` per pair secara
konkuren. `ManajerSlot` (9.0) tidak cukup di sini karena ia tidak tahu margin nyata
di bursa dan tidak dirancang untuk dipanggil dari banyak proses/task sekaligus.
`GovernorPortofolio` menggantikannya untuk live:

- Setiap siklus, `MesinMultiPair._ambil_snapshot()` menarik `SnapshotAkun(equity,
  margin_tersedia, posisi)` **nyata** dari Binance (`client.saldo()` + `client.posisi()`)
  lewat `snapshot_dari_akun(saldo, posisi, aset="USDT")`, lalu memanggil
  `governor.mulai_siklus(snapshot)` sekali di awal siklus.
- Setiap runner (per pair) memanggil `governor.antre(KandidatEntry(simbol, arah,
  entry_tf, horizon, skor, margin_dibutuhkan, notional, leverage, rr_bersih,
  skor_likuiditas, strategi))` - **hanya untuk horizon di `HORIZON_AUTO_ENTRY =
  (HORIZON_SCALPING, HORIZON_INTRADAY)`**; swing tidak pernah diantre.
- `governor.putuskan()` memutuskan SEMUA kandidat siklus itu sekaligus (bukan
  satu-satu), menerapkan `KebijakanPortofolio(maks_posisi=4, min_free_margin_pct=0.30,
  maks_posisi_per_simbol=1, izinkan_hedge=False)` dan mengembalikan
  `KeputusanEntry(kandidat, diterima, alasan, peringkat, margin_setelah,
  free_margin_setelah)` per kandidat. Ini menutup celah -2019 "Margin is
  insufficient" yang bisa terjadi bila setiap runner memutuskan sendiri tanpa tahu
  kandidat pair lain dalam siklus yang sama.
- Kode tolak: `TOLAK_KUOTA_POSISI`, `TOLAK_FREE_MARGIN`, `TOLAK_DUPLIKAT_SIMBOL`,
  `TOLAK_ARAH_BERLAWANAN`, `TOLAK_MARGIN_KURANG`, `TOLAK_BUKAN_AUTO_ENTRY`,
  `TOLAK_MARGIN_TIDAK_SAH`.
- **Fail-safe wajib** (dua lapis, keduanya diperbaiki/ditambahkan 4 Agu 2026):
  1. Bila snapshot akun gagal diambil, `MesinMultiPair` memakai
     `SnapshotAkun(equity=0.0, margin_tersedia=0.0, posisi=())` sehingga SEMUA
     kandidat siklus itu ditolak governor (margin 0 -> `TOLAK_MARGIN_KURANG`/
     `TOLAK_FREE_MARGIN`), bukan lolos tanpa pengawasan.
  2. Bila `pemeriksa_entry_fn` (closure yang membungkus `governor.antre`+`putuskan`,
     dibuat lewat `MesinMultiPair._buat_pemeriksa_entry()`) melempar exception saat
     dipanggil dari `LiveRunner`, entry **ditolak** (`alasan_ditolak_governor =
     "governor_error"`), bukan diloloskan - ini bug fail-open yang diperbaiki di 8.7.
- `RingkasanSiklus.sinyal_tertolak_governor` mencatat setiap kandidat yang ditolak
  governor pada siklus itu, dipakai dashboard (tab Sinyal Terlewat) - sinyal ini
  **tidak** dikirim ke Telegram (lihat 9.2).
- `siapkan()["governor_aktif"]` melaporkan apakah governor terpasang untuk
  `MesinMultiPair` instance saat ini (untuk diagnostik startup).

### 9.2 Kontrak notifikasi Telegram per horizon (`notifikasi/telegram.py`, BARU 4 Agu 2026)

Keputusan operator (Message 41, 4 Agu 2026): Telegram hanya untuk scalp/intraday
yang benar-benar di-entry, tidak untuk swing maupun sinyal yang ditolak governor.

| Horizon / kondisi | Dashboard | Telegram |
|---|---|---|
| Scalp/intraday - entry dikirim/terisi, SL/TP ter-trigger | ya | ya |
| Scalp/intraday - tertolak governor (kuota/margin) | ya | tidak |
| Swing (signal-only) | ya | tidak |

Event method: `lapor_entry_dikirim`, `lapor_entry_terisi`, `lapor_sl_tertrigger`,
`lapor_tp_tertrigger` (semua mengirim pesan nyata). `lapor_sinyal_swing` dan
`lapor_sinyal_tertolak` adalah **no-op eksplisit** (selalu `return False`, ditulis
supaya niat "sengaja tidak kirim" terlihat di kode, bukan sekadar tidak dipanggil).
`NotifierNonaktif` (dipakai bila token/chat_id kosong) meniru seluruh API ini sebagai
no-op sehingga kegagalan konfigurasi Telegram tidak pernah menjatuhkan proses trading.

## 10. Pipeline

```python
plane = DataPlane.dari_dasar(bars_5m, ("15m", "1h"))
pipe = Pipeline(plane, TFPlan("5m", ("15m",)), HORIZON_INTRADAY, balance=1000.0)
hasil, stat = pipe.jalankan_rentang()
```

`HasilBar` berisi `verdict`, `mode`, `sizing`, `rencana` (auto_entry) atau `sinyal` (swing).
`StatistikJalan` berisi `bar_dievaluasi`, `entry`, `sinyal_saja`, `konflik`,
`kandidat_per_strategi`, `menang_per_strategi`.

Untuk portofolio multi-simbol backtest, `backtest_portofolio.py` membungkus banyak
`Pipeline` (satu per simbol) dan menyalurkannya ke `ManajerSlot` bersama;
`HasilPortofolio.ringkas()` menyertakan `kurva_ekuitas` yang sudah diringkas
(`_ringkas_kurva()`, downsample maksimum 500 titik, titik awal/akhir dipertahankan).

Untuk live multi-pair, `mesin_multi.py::MesinMultiPair` membungkus banyak
`LiveRunner` (satu per pair) dan menyalurkannya ke satu `GovernorPortofolio` bersama
(lihat 9.1) - analog perannya dengan `backtest_portofolio.py` di sisi backtest, tetapi
dengan snapshot akun nyata dan margin bursa, bukan simulasi.

## 11. Batasan sandbox dan CI

- Sandbox Notion: **tanpa jaringan**, `pip install` gagal. Karena itu paket inti hanya
  bergantung pada numpy, dan tersedia pelari uji minimal `scripts/jalankan_uji.py`
  (shim `pytest.raises`/`pytest.approx`) agar uji tetap bisa dijalankan lokal.
- GitHub Actions: `ubuntu-latest`, `actions/checkout@v4` (`fetch-depth: 0`),
  `actions/setup-python@v5` Python `3.11`, cache pip, `permissions: contents: write`,
  `concurrency` per ref, `workflow_dispatch` aktif. CI memakai pytest asli dan menulis
  `reports/ci_terakhir.json` + `.txt`, lalu commit balik dengan `[skip ci]`.
- Alat agen tidak punya akses API workflow-run Actions; status Actions dipantau lewat
  artefak yang di-commit balik, bukan lewat status run langsung.

## 12. Bug yang diperbaiki

- `struktur_plus.py`: `_breaker_block` dan `_ob_retest` memanggil
  `order_block_sebelum(...)` tanpa argumen `arah` yang sekarang wajib positional -
  diperbaiki dengan menambahkan `ev.arah`/`arah_ob_dicari`.
- `fitur/lanjutan.py` fungsi `adx()`: pembagian `dasar.aman_bagi` (skalar) dipanggil
  atas larik numpy, menyebabkan `ValueError: truth value of an array...`. Diperbaiki
  dengan `_bagi_aman_larik()` baru yang elementwise-safe.
- `ice_breaker.py` (putaran 3): `Slice.payload()` sekarang mengirim `visible_qty` DAN
  `icebergQty`; jeda antar-slice memakai `await tidur(...)` (bukan `time.sleep`).
- `backtest_portofolio.py::HasilPortofolio.ringkas()`: kurva ekuitas sebelumnya tidak
  disertakan di payload ringkasan. Diperbaiki dengan `_ringkas_kurva()`.
- `order.py`: serialisasi bool Python (`True` terkirim sebagai `"true"` literal, bukan
  JSON boolean) menyebabkan -1111 di Binance; diperbaiki di `format_nilai`.
- `live_runner.py` (4 Agu 2026): bug fail-open governor - exception dari
  `pemeriksa_entry_fn` tidak menghentikan eksekusi entry (tidak ada `return siklus`
  setelah `except`); diperbaiki, sekarang selalu `return siklus` dengan
  `alasan_ditolak_governor="governor_error"`.
- `pemindai/likuiditas.py` (4 Agu 2026): fallback "melonggarkan kriteria" - bila
  verifikasi buku order meloloskan pair di bawah `min_pair`, kode lama membuang
  seluruh verifikasi dan memeringkat ulang dari volume+aktivitas mentah tanpa
  spread/kedalaman. Diperbaiki: pair yang lolos verifikasi dipakai apa adanya,
  kriteria tidak pernah dilonggarkan.

## 13. Yang BELUM dikerjakan (sengaja / pending)

- Validasi dataset besar (95 pair) via GitHub Actions belum dijalankan ulang dengan
  model biaya asimetris + kebijakan post-only + TP market terbaru.
- Model biaya (`eksekusi/biaya.py`) belum direfleksikan untuk jalur `payload_tp_market()`
  (TP sebagai taker, bukan maker, bila live memakai TP market bukan TP LIMIT+GTX).
- Unit test governor (`GovernorPortofolio`: diterima/ditolak per kode tolak,
  fail-safe snapshot gagal, fail-safe exception di `pemeriksa_entry_fn`) belum ditulis.
- `tests/test_live_runner.py` untuk bracket tracking (`_EntryPending`, `_BracketAktif`,
  timeout poll, transisi event notifier) belum ditulis.
- Dashboard real-time (server auto-start dari `python main.py`; data: market, posisi
  aktif, order di Binance, equity/margin, sinyal swing, sinyal tertolak governor)
  belum dibangun - `dashboard/index.html` saat ini statis dari data backtest.
- Parameter invalidasi (`spek.sl_atr` per pola/strategi, buffer struktural hardcode,
  lantai `0.15 * ATR` di `sl_valid`) belum dieksternalisasi ke konfigurasi.
- Lapisan `EventBus` generik dan persistensi state antar-restart belum dibangun;
  saat ini notifier dipanggil langsung dari `live_runner.py`/`mesin_multi.py`.
- Analisis edge kotor per strategi lintas 95 simbol (n >= 200/strategi) belum
  dilakukan; penonaktifan strategi lemah hanya lewat konfigurasi, bukan mengubah logika.
- Batas notional/leverage, aturan equity-floor/stop-trading, dan layer manajemen posisi
  pasca-entry (trailing/breakeven/time-stop) belum dibangun.
- Cacah uji CI dan lokal sudah disamakan: 242 uji, dijalankan oleh `.github/workflows/kesiapan_live.yml` di `main` dan dibuktikan di `LAPORAN_KESIAPAN.md` / `LOG_KESIAPAN.txt`.
