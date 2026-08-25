# lux-modul-trading

Modul trading multi-strategi untuk **Binance USDT-M Futures**. Satu arsitektur yang
menampung strategi **single-timeframe** dan **multi-timeframe** sekaligus, dengan
pembobotan skor (bukan bloker berurutan), risk management dinamis, dan lapisan
eksekusi yang setiap kegagalannya wajib dikonfirmasi bursa.

Status: **modul lengkap & terintegrasi**. Tiga mode jalan dari satu titik masuk
(`main.py`): backtest historis, Binance Futures **Testnet**, dan **Live**. Uji
otomatis: **373 lulus / 373** (lantai gerbang CI `CI_MIN_PYTEST=373`). Backtest 95
pair sudah dijalankan lewat GitHub Actions.

Lapisan eksekusi sudah **diuji hidup** terhadap Binance Futures Testnet, bukan
hanya dengan mock. Bukti dan angkanya ada di
**[`BUKTI_MESIN.md`](BUKTI_MESIN.md)**; analisis temuannya di
**[`AUDIT_MESIN.md`](AUDIT_MESIN.md)**.

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

Semua kredensial diisi di **satu** tempat: berkas `.env`. Panduan lengkap ada di
**[`KONFIGURASI.md`](KONFIGURASI.md)** - baca itu lebih dulu sebelum menjalankan
mode testnet/live.

Pemakaian non-interaktif (cron/CI):

```powershell
python main.py --mode konfigurasi                  # periksa kesiapan kredensial
python main.py --mode uji
python main.py --mode backtest --label single_15m
python main.py --mode testnet                      # MULTI-PAIR: pindai 25-50 pair likuid
python main.py --mode live --konfirmasi-live       # DANA ASLI, multi-pair
```

### Sistem ini TIDAK BTC-centric dan TIDAK 15m-centric

Tanpa `--simbol-live`, engine memindai pasar Binance Futures secara langsung,
menyaring likuiditas (volume 24 jam, jumlah trade, spread, kedalaman buku), lalu
menjalankan **25-50 pair paling likuid** secara paralel. Tidak ada daftar pair
hardcode. TF entry mengikuti kontrak tiap strategi (STF & MTF), bukan 15m saja.

---

## Mesin eksekusi order

Bagian ini yang paling menentukan apakah modal Anda aman. Tiga aturan yang
dipegang tanpa pengecualian:

1. **Order tidak pernah disebut berhasil sebelum bursa mengonfirmasinya.** Setiap
   respons wajib lolos `konfirmasi_order` (orderId/clientOrderId ada, `status`
   ada dan dikenal, simbol dan sisi cocok). Badan jawaban kosong BUKAN sukses.
2. **Ada tiga keadaan, bukan dua**: berhasil, gagal, dan **TIDAK DIKETAHUI**.
   Timeout dan HTTP 503 masuk keadaan ketiga - tidak pernah dikirim ulang buta,
   melainkan diselesaikan lewat pencarian `clientOrderId` dan rekonsiliasi.
3. **Gagal proteksi berarti posisi ditutup.** Bila TP/SL tidak berhasil terpasang
   dan terlihat di bursa, posisi tidak dibiarkan terbuka.

Status jalur eksekusi (semua sudah diuji terhadap testnet sungguhan):

| jalur | status |
|---|---|
| Limit entry | terkonfirmasi bursa |
| Take Profit | LIMIT reduceOnly, diverifikasi terlihat di `openOrders` |
| Stop Loss | pemantau perangkat lunak + fallback MARKET; tipe stop bursa ditolak `-4120` |
| Cancel | dikonfirmasi lalu diverifikasi hilang dari `openOrders` |
| Modify | `PUT /fapi/v1/order`, diverifikasi ulang lewat `status_order` |
| Rekonsiliasi | posisi tanpa proteksi ditutup, proteksi yatim dibatalkan |

### Logging yang bisa ditelusuri

`lux_modul/eksekusi/jejak.py` menulis JSONL di satu choke point REST. Satu
`korelasi` menyatukan baris request, response, dan error untuk satu perintah,
sehingga satu order bermasalah bisa ditarik utuh dengan satu grep. Jalur dana
dicatat utuh; rahasia diredaksi tetapi **nama parameternya dipertahankan**, supaya
perubahan API di masa depan tetap terlihat tanpa membocorkan nilainya.

Atur lewat `.env`: `LUX_JEJAK_AKTIF`, `LUX_JEJAK_DIR`, `LUX_JEJAK_STDOUT`.

### Base 0,20 USDT per setup (modal < 20 USDT)

Yang dikendalikan sampai 0,20 USDT adalah **initial margin**, bukan notional -
karena minimum notional dan minQty ditetapkan bursa per simbol:

    notional = margin x leverage  ->  leverage = notional_minimum / 0,20

Diukur pada 527 pair USDT perpetual sungguhan (saldo uji 19 USDT, SL 1%):
**382 simbol benar-benar mencapai base 0,20**, dan **525 dari 527** layak
ditradingkan. Simbol termurah memakai leverage 26 dengan margin `0,1923` dan
risiko hanya 0,26% modal.

Pada simbol bernotional-minimum tinggi seperti **BTCUSDT (minNotional 50) base
0,20 tidak tercapai** - margin termurahnya `0,4417`. Mesin melaporkannya jujur
dan **melewati setup** bila risikonya melewati batas atau likuidasi lebih dekat
daripada SL. Angka lengkapnya di [`BUKTI_MESIN.md`](BUKTI_MESIN.md).

### Leverage dihitung otomatis per setup

Urutan yang dipakai engine: **Risk -> Position Size/Notional -> Required Margin
-> Optimal Leverage**. `LUX_LEVERAGE_MAKS` hanya BATAS ATAS, bukan leverage
kerja. RR yang dilaporkan adalah **RR bersih** setelah fee masuk, fee keluar, dan
slippage. Rinciannya di
**[`AUDIT_LEVERAGE_PRESISI.md`](AUDIT_LEVERAGE_PRESISI.md)**.

---

## Isi cepat

```
lux_modul/
  kontrak.py            Bars, TFPlan, StrategyVerdict, Penolakan, konstanta
  data/                 L0  loader CSV, resample, DataPlane (anti look-ahead)
  fitur/                L1  indikator dasar, struktur pasar, FeatureStore (cache)
  strategi/             L2  26 strategi terdaftar di 6 kelompok teknik
  arbiter/              L3  ambang, skor tertinggi, resolusi konflik arah
  eksekusi/             L4  risiko, ice-breaker, mode auto-entry / signal-only
  eksekusi/jejak.py         perekam JSONL request/response/error jalur dana
  eksekusi/klasifikasi.py   taksonomi galat + konfirmasi order/pembatalan
  eksekusi/ukuran_mikro.py  sizing base 0,20 untuk modal < 20 USDT
  eksekusi/binance_client.py konektor REST (urllib) + pengatur laju + modify
  eksekusi_aman/            pengirim order, proteksi, rekonsiliasi, saklar mode
  konfigurasi.py        L0  pemuat .env + status kredensial
  notifikasi/           L6  notifier Telegram (opsional)
  pemindai/             L0  pemindai likuiditas pasar (25-50 pair dinamis)
  mesin_multi.py        L5  engine multi-pair multi-TF
  live_runner.py        L5  loop real-time testnet/live memakai Pipeline sama
main.py                 titik masuk TUNGGAL (menu interaktif + CLI)
alat/                   penambal berbasis jangkar, gerbang, uji hidup, peta mikro
bukti/                  bukti mentah: gerbang CI, uji hidup, jejak JSONL
tests/                  373 uji
```

Workflow GitHub Actions: `ci` (gerbang regresi), `mesin` (penambal + pytest),
`mesin_hidup` (uji hidup cancel/modify di testnet), `mikro` (peta kelayakan base
0,20), `hidup`, `saklar`, `tambal`, `kontrak`, `rakit`.

Dokumen: [`KONFIGURASI.md`](KONFIGURASI.md) - kredensial & cara menjalankan.
[`ARSITEKTUR.md`](ARSITEKTUR.md) - desain lengkap.
[`AUDIT_MESIN.md`](AUDIT_MESIN.md) - audit mesin eksekusi.
[`BUKTI_MESIN.md`](BUKTI_MESIN.md) - bukti pengukuran mesin.
[`REFERENSI.md`](REFERENSI.md) - sumber aturan entry/SL/TP tiap strategi.
[`STATE.md`](STATE.md) - status pekerjaan dan langkah berikutnya.

## Aturan pemilihan (arbiter)

1. Seluruh strategi dievaluasi tiap lilin, **tanpa short-circuit**. Satu strategi
   galat tidak menjatuhkan yang lain.
2. Kandidat = `skor > ambang` (ketat lebih besar).
3. Tidak ada kandidat -> tidak ada entry sama sekali.
4. Ada kandidat -> **skor tertinggi** yang dieksekusi (tie-break deterministik
   oleh `strategy_id`, bukan urutan pendaftaran).
5. LONG dan SHORT sama-sama lolos ambang dengan selisih skor **< 5.0 poin**
   (`MARGIN_KONFLIK`) -> saling meniadakan, **tidak ada entry**.

## Risk management

- Saldo `< $20`: jalur mikro. Margin ditarget **0,20 USDT per setup**, qty
  dibulatkan **ke atas** ke minimum bursa, dan risiko nyatanya tetap diperiksa -
  setup ditolak bila rugi di SL melewati 5% modal atau bila jarak likuidasi lebih
  dekat daripada SL. **0,20 mengatur MARGIN, bukan RISIKO.**
- Saldo `>= $20`: sizing risiko biasa (tier 3% / 2.5% / 2% / 1.5% / 1%, taper di
  atas $100rb sampai lantai 0.25%), qty dibulatkan **ke bawah**.
- Order besar lewat `plan_execution()`: TWAP + iceberg, maks 12 slice. Setiap
  slice memakai `newClientOrderId` deterministik, dan `qty_terisi` hanya dihitung
  dari `executedQty` jawaban bursa - tidak pernah dari qty yang diminta.

> Catatan koreksi: versi lama README mengklaim `visible_qty` dan `icebergQty`
> ikut dikirim ke exchange. Itu **terbantah** oleh uji hidup - keduanya bukan
> parameter sah `/fapi/v1/order`, ikut ditandatangani, dan berisiko `-1104`.
> Keduanya sudah dihapus dari payload.

## Menjalankan uji dan demo

```bash
python main.py --mode uji      # cara yang disarankan (jalan di mana saja)
pytest -q                      # 373 uji (dipakai di CI)
python scripts/jalankan_uji.py # pelari minimal untuk lingkungan tanpa pytest
python scripts/demo_sintetis.py
```

## Tiga mode eksekusi

| mode | sumber data | order nyata | pengaman |
|---|---|---|---|
| `backtest` | CSV OHLCV lokal | tidak ada | - |
| `testnet` | REST klines testnet | ya, dana mainan | kredensial testnet terpisah total |
| `live` | REST klines live | ya, **DANA ASLI** | dua gerbang wajib (lihat `KONFIGURASI.md`) |

Ketiganya memanggil `Pipeline`/`Registry` strategi yang **sama persis**. Mode
`live` hanya berjalan bila **KEDUA** gerbang lolos: konfirmasi eksplisit
(`--konfirmasi-live` atau frasa di menu) **DAN** `LUX_LIVE_KONFIRMASI`. Base URL
ditentukan murni oleh mode dan tidak bisa diubah lewat konfigurasi, sehingga
kunci testnet mustahil terpakai di endpoint live.

## Ketergantungan

Inti hanya butuh `numpy`; `pytest` dipakai untuk uji. Keduanya dipin di
`requirements.txt`. `pandas`, `pyarrow`, dan `PyYAML` **terbukti tidak dipakai**
di seluruh kedalaman impor. Konektor Binance dan notifier Telegram memakai
`urllib` pustaka standar - tidak ada dependency HTTP pihak ketiga.

## Batasan jujur yang perlu Anda tahu

- **SL adalah pemantau perangkat lunak.** Binance testnet menolak `STOP_MARKET`
  dan `TAKE_PROFIT_MARKET` dengan `-4120` (wajib lewat Algo Order API, yang tidak
  ada di testnet). Konsekuensinya: bila proses mati, SL mati bersamanya sampai
  pemulihan berjalan. Jendela ini tidak bisa dihilangkan lewat REST.
- **Perilaku mainnet berpotensi berbeda.** Endpoint Algo mungkin ada di mainnet,
  sehingga stop di bursa mungkin bisa dipakai. Saklar `LUX_EKSEKUSI=otomatis`
  memutuskan dari jawaban bursa dan gagal ke sisi aman.
- **Rate limit belum dioptimalkan penuh.** WebSocket belum menggantikan polling.
- Hasil backtest 95 pair menunjukkan PnL bersih **negatif** di hampir seluruh
  konfigurasi TF setelah biaya, walau beberapa strategi punya edge kotor positif.
  Jangan menjalankan mode live dengan modal berarti sebelum seleksi strategi
  selesai.
