# lux-modul-trading

Modul trading multi-strategi untuk **Binance USDT-M Futures**. Satu arsitektur yang
menampung strategi **single-timeframe** dan **multi-timeframe** sekaligus, dengan
pembobotan skor (bukan bloker berurutan), risk management dinamis, dan eksekusi
ice-breaker TWAP+iceberg.

Status: **modul lengkap & terintegrasi**. Tiga mode jalan dari satu titik masuk
(`main.py`): backtest historis, Binance Futures **Testnet**, dan **Live**. Uji
otomatis: **242 lulus / 242**. Backtest 95 pair sudah pernah dijalankan lewat
GitHub Actions (hasil di `reports/besar/` dan `reports/besar95/`).

---

## Mulai cepat (Windows PowerShell)

```powershell
pip install -r requirements.txt
copy .env.contoh .env      # isi kredensial Anda di berkas .env
python main.py             # menu interaktif - tidak perlu argumen apa pun
```

`python main.py` tanpa argumen membuka menu:

```
1) Uji modul (unit test)                - aman, tanpa jaringan
2) Backtest data historis (CSV lokal)   - aman, tanpa order
3) TESTNET Binance Futures              - order sungguhan, dana mainan
4) LIVE    Binance Futures              - DANA ASLI, dua gerbang keamanan
5) Uji koneksi Telegram
6) Bangkitkan ulang data dashboard
```

Semua kredensial (Telegram, Binance Testnet, Binance Live) diisi di **satu**
tempat: berkas `.env`. Panduan lengkap ada di **[`KONFIGURASI.md`](KONFIGURASI.md)** -
baca itu lebih dulu sebelum menjalankan mode testnet/live.

Pemakaian non-interaktif (cron/CI) tetap tersedia:

```powershell
python main.py --mode konfigurasi                  # periksa kesiapan kredensial
python main.py --mode uji
python main.py --mode backtest --label single_15m
python main.py --mode testnet                      # MULTI-PAIR: pindai 25-50 pair likuid
python main.py --mode live --konfirmasi-live       # DANA ASLI, multi-pair

# uji terarah satu pair saja (opsional, bukan mode default):
python main.py --mode testnet --simbol-live BTCUSDT --tf-entry 15m
```

### Sistem ini TIDAK BTC-centric dan TIDAK 15m-centric

Tanpa `--simbol-live`, engine memindai pasar Binance Futures secara langsung,
menyaring likuiditas (volume 24 jam, jumlah trade, spread, kedalaman buku), lalu
menjalankan **25-50 pair paling likuid** secara paralel. Tidak ada daftar pair
hardcode. TF entry mengikuti kontrak tiap strategi (STF & MTF), bukan 15m saja.

### Leverage dihitung otomatis per setup

Urutan yang dipakai engine: **Risk -> Position Size/Notional -> Required Margin
-> Optimal Leverage**. `LUX_LEVERAGE_MAKS` hanya BATAS ATAS, bukan leverage
kerja; leverage nyata berbeda-beda tiap pair/setup dan tidak pernah statis x5/x10.
RR yang dilaporkan adalah **RR bersih** setelah fee masuk, fee keluar, dan
slippage; BEP dihitung sesuai arah posisi (long di atas entry, short di bawah).
Rinciannya beserta bukti angka ada di
**[`AUDIT_LEVERAGE_PRESISI.md`](AUDIT_LEVERAGE_PRESISI.md)**.

---

## Isi cepat

```
lux_modul/
  kontrak.py            Bars, TFPlan, StrategyVerdict, Penolakan, konstanta
  data/                 L0  loader CSV, resample, DataPlane (anti look-ahead)
  fitur/                L1  indikator dasar, struktur pasar, FeatureStore (cache)
  strategi/             L2  12 strategi tunggal di 3 kelompok teknik
  arbiter/              L3  ambang, skor tertinggi, resolusi konflik arah
  eksekusi/             L4  risiko, ice-breaker, mode auto-entry / signal-only
  eksekusi/spesifikasi.py   presisi tick/step, RR bersih, BEP, leverage otomatis
  eksekusi/kredensial.py    pemisahan ketat kredensial testnet vs live
  eksekusi/binance_client.py konektor REST Binance Futures (urllib, stdlib)
  konfigurasi.py        L0  pemuat .env + status kredensial (satu sumber setelan)
  notifikasi/           L6  notifier Telegram (opsional, kegagalan tidak fatal)
  pemindai/             L0  pemindai likuiditas pasar (25-50 pair dinamis)
  rencana_tf.py             rencana TF entry/konteks dari kontrak strategi
  mesin_multi.py        L5  engine multi-pair multi-TF (banyak LiveRunner)
  live_runner.py        L5  loop real-time testnet/live memakai Pipeline yang sama
  pipeline.py               perangkai L0..L4
  sintetis.py               generator data uji tanpa jaringan
main.py                 titik masuk TUNGGAL (menu interaktif + CLI)
.env.contoh             template kredensial (salin jadi .env)
tests/                  242 uji
scripts/                demo end-to-end + pelari uji minimal untuk sandbox
.github/workflows/      ci.yml (unit test) + backtest95_metrik.yml (uji 95 pair)
```

Dokumen: [`KONFIGURASI.md`](KONFIGURASI.md) - kredensial & cara menjalankan.
[`ARSITEKTUR.md`](ARSITEKTUR.md) - desain lengkap.
[`REFERENSI.md`](REFERENSI.md) - sumber aturan entry/SL/TP tiap strategi.
[`STATE.md`](STATE.md) - status pekerjaan dan langkah berikutnya.

## Pemakaian singkat

```python
from lux_modul.data import DataPlane, muat_csv
from lux_modul.kontrak import HORIZON_INTRADAY, TFPlan
from lux_modul.pipeline import Pipeline

bars5m = muat_csv("data/BTCUSDT_5m.csv", tf="5m", simbol="BTCUSDT")
plane = DataPlane.dari_dasar(bars5m, ("15m", "1h"))     # resample otomatis

pipe = Pipeline(plane, TFPlan("5m", ("15m",)), HORIZON_INTRADAY, balance=50.0)
hasil, stat = pipe.jalankan_rentang()

for h in hasil:
    print(h.verdict.ringkas(), h.sizing, h.rencana.ringkas())
print(stat.ringkas())
```

Single-TF cukup ganti rencananya: `TFPlan("5m")` (tanpa TF konteks).
Swing: `HORIZON_SWING` - keluarannya `Sinyal`, tanpa order dan tanpa sizing.

## 12 strategi tunggal, 3 kelompok

| kelompok | strategi |
|---|---|
| pola klasik | `double_top`, `double_bottom`, `head_shoulders`, `triangle_breakout`, `wedge_breakout`, `cup_and_handle` |
| indikator / momentum | `ema_bounce_200`, `rsi_divergence`, `macd_rsi_trendbreak` (multi-TF) |
| struktur modern | `smc_ob_fvg` (multi-TF), `ict_liquidity_sweep`, `breakout_volume` |

Setiap strategi punya logika **entry, SL, dan TP sendiri**, skor 0-100, ambang sendiri,
dan mendeklarasikan kebutuhan TF sebagai peran:
`required_roles = {"entry": True, "context": 0..N}`.

Catatan: sejak revisi CVD, arsitektur juga bersifat **plugin-based/extensible** lewat
`lux_modul/plugin.py` (`KATALOG_STRATEGI`, `KATALOG_POLA`, `KATALOG_INDIKATOR`) -
tabel di atas hanya 12 strategi kelas lama fase-1. Total unit yang benar-benar
terdaftar sekarang 26 strategi terdaftar (lintas kelompok: struktur, pola, indikator, volatilitas, aliran volume) di 6 kelompok teknik.
Lihat `ARSITEKTUR.md` untuk daftar lengkap dan `CALON_STRATEGI.md` untuk strategi
yang sengaja belum dibuat karena keterbatasan data OHLCV.

## Aturan pemilihan (arbiter)

1. Seluruh strategi dievaluasi tiap lilin, **tanpa short-circuit**. Satu strategi galat
   tidak menjatuhkan yang lain.
2. Kandidat = `skor > ambang` (ketat lebih besar).
3. Tidak ada kandidat -> tidak ada entry sama sekali.
4. Ada kandidat -> **skor tertinggi** yang dieksekusi (tie-break deterministik oleh
   `strategy_id`, bukan urutan pendaftaran).
5. LONG dan SHORT sama-sama lolos ambang dengan selisih skor **< 5.0 poin**
   (`MARGIN_KONFLIK`) -> saling meniadakan, **tidak ada entry**.

## Risk management

- Saldo `< $20` atau `<= 0`: `risk% = 3% * (20/balance)^0.55`, clamp `[0.5%, 3%]`,
  `risk$ = max($0.20, balance * risk%)`. **$0.20 adalah lantai**, bukan nilai flat.
- Saldo `>= $20`: tier 3% / 2.5% / 2% / 1.5% / 1%, lalu taper di atas $100rb sampai
  lantai **0.25%**.
- Order besar wajib lewat `plan_execution()`: TWAP + iceberg, maks 12 slice,
  `visible_qty` 25% dan **benar-benar dikirim** ke exchange (`visible_qty` + `icebergQty`).
  Order kecil (< $5.000 notional) tetap 1 order utuh.
- Eksekusi slice **non-blocking** (`async`), dan `entry_invalidated()` membatalkan sisa
  slice bila harga sudah menembus SL sebelum semua slice terkirim.

## Menjalankan uji dan demo

```bash
python main.py --mode uji      # cara yang disarankan (jalan di mana saja)
pytest -q                      # 242 uji (butuh pytest, dipakai di CI)
python scripts/jalankan_uji.py # pelari minimal untuk lingkungan tanpa pytest
python scripts/demo_sintetis.py
```

`demo_sintetis.py` mendemonstrasikan seluruh kriteria selesai fase implementasi:
verdict single-TF, verdict multi-TF, distribusi kandidat/menang per strategi,
aturan ambang dan konflik arah, mode swing signal-only, kurva risiko, dan ice-breaker.

## Alur validasi

1. **Operator mengirim dataset kecil.** Pengujian data tidak dimulai sebelum ini.
2. Uji tahap awal di sandbox dengan dataset kecil.
3. Lolos -> dataset lebih besar.
4. Uji skala besar lewat GitHub Actions.
5. Baru di tahap ini `lux-ai-research` / `lux-trading-strategy` dipakai sebagai konteks
   tambahan (struktur dataset, batasan format), bukan untuk mem-porting strategi lama.
6. Semua pekerjaan tetap di repo ini.

## Tiga mode eksekusi

| mode | sumber data | order nyata | pengaman |
|---|---|---|---|
| `backtest` | CSV OHLCV lokal | tidak ada | - |
| `testnet` | REST klines testnet | ya, dana mainan | kredensial testnet terpisah total |
| `live` | REST klines live | ya, **DANA ASLI** | dua gerbang wajib (lihat `KONFIGURASI.md`) |

Ketiganya memanggil `Pipeline`/`Registry` strategi yang **sama persis** - tidak ada
logika sinyal yang ditulis ulang per mode. Yang berbeda hanya sumber data dan
apakah rencana eksekusi benar-benar dikirim ke exchange.

Mode `live` hanya berjalan bila **KEDUA** gerbang lolos bersamaan: konfirmasi
eksplisit (`--konfirmasi-live` atau ketik ulang frasa di menu) **DAN** variabel
lingkungan `LUX_LIVE_KONFIRMASI`. Base URL exchange ditentukan murni oleh mode dan
tidak bisa diubah lewat konfigurasi, sehingga kunci testnet mustahil terpakai di
endpoint live.

## Ketergantungan

Inti hanya butuh `numpy`. `pandas` opsional untuk loader dataset besar. Konektor
Binance dan notifier Telegram memakai `urllib` dari pustaka standar - **tidak** ada
dependency HTTP pihak ketiga. Versi CI dipin di `requirements.txt`.

## Batasan jujur yang perlu Anda tahu

- Konektor Binance diuji dengan unit test bermock di lingkungan **tanpa akses
  jaringan keluar**; ia belum pernah diadu dengan server Binance sungguhan.
  Jalankan `--mode testnet` dengan `LUX_MAKS_SIKLUS` kecil lebih dulu.
- Hasil backtest 95 pair saat ini menunjukkan PnL bersih **negatif** di kelima
  konfigurasi TF setelah biaya, walau beberapa strategi punya edge kotor positif.
  Jangan menjalankan mode live dengan modal berarti sebelum tahap seleksi strategi
  selesai.
