# STATE v10 - 4 Agustus 2026

Status modul: **belum layak real trading**. Layak dipakai untuk **paper / demo
(Binance Futures Testnet)** setelah konektor selesai. Jangan sambungkan akun live
tanpa konfirmasi eksplisit operator.
Titik masuk sesi baru: `RESUME_PROMPT.md`. Ikhtisar teknis: `README.md`.
Desain rinci: `ARSITEKTUR.md`. Rencana Telegram (belum diimplementasikan): `TELEGRAM.md`.

## Bug kritis ditemukan & diperbaiki (v10, audit lanjutan 4 Agu 2026)

Audit pembacaan source code (bukan menjalankan skrip - sandbox tidak punya akses
jaringan ke Binance) menemukan bahwa `scripts/live_run.py` memanggil tiga metode
pada objek `Konfigurasi` yang **tidak pernah didefinisikan** di
`lux_modul/konfigurasi.py`: `cfg.daftar_entry_tf()`, `cfg.daftar_simbol()`,
`cfg.kriteria_pindai()`. Akibatnya `live_run.py` pasti crash `AttributeError`
begitu dijalankan - baik `--mode testnet` maupun `--mode live`, baik jalur
satu-pair (`--simbol`) maupun jalur multi-pair (default, tanpa `--simbol`). Bug ini
tidak pernah terdeteksi sebelumnya karena skrip ini belum pernah benar-benar
dieksekusi (tidak ada akses jaringan di sandbox pengembangan).

**Diperbaiki di sesi ini** (`lux_modul/konfigurasi.py`, method baru pada `Konfigurasi`):
- `daftar_entry_tf()` - urai `LUX_TF_ENTRY` (dipisah koma) lewat
  `rencana_tf.uraikan_daftar_tf`; kosong -> `()` supaya entry TF ditentukan dari
  kontrak strategi + horizon (lewat `rencana_dari_registry`), bukan dipaksa dari `.env`.
- `daftar_simbol()` - urai `LUX_SIMBOL` (dipisah koma, huruf besar); kosong -> `()`
  supaya `live_run.py` memindai pasar (25..50 pair) alih-alih dipaksa satu simbol statis.
- `kriteria_pindai()` - bangun `KriteriaLikuiditas` (dari `pemindai/likuiditas.py`)
  dari seluruh ambang `LUX_PINDAI_*` yang sudah ada di `Konfigurasi`; dipakai
  `MesinMultiPair` di jalur multi-pair.
- Regresi ditambahkan: `tests/test_konfigurasi_tf_simbol.py` (9 test: tuple kosong
  saat `.env` kosong, parsing dipisah koma + normalisasi, `KriteriaLikuiditas`
  terisi benar dari ambang `.env`).

Semua berkas `lux_modul/eksekusi/*` (`kredensial.py`, `biaya.py`, `binance_client.py`,
`ice_breaker.py`, `risiko.py`, `spesifikasi.py`), `lux_modul/rencana_tf.py`,
`lux_modul/pemindai/likuiditas.py`, `lux_modul/mesin_multi.py`, `scripts/live_run.py`,
`scripts/dashboard_data.py`, dan `scripts/jalankan_uji.py` sudah dibaca lengkap di sesi
ini (sebelumnya belum diaudit). Catatan penting dari pembacaan itu:
- `scripts/jalankan_uji.py` adalah **shim lokal** (bukan pytest sungguhan) yang hanya
  dipakai di sandbox tanpa akses jaringan (pytest tidak bisa dipasang) - ia memasang
  modul `pytest` palsu (`raises`/`approx`/`fixture` minimal) lalu memanggil setiap
  fungsi `test_*` di `tests/test_*.py` secara langsung, TANPA mendukung fixture atau
  `@pytest.mark.parametrize` sungguhan. Ini kandidat kuat penyebab selisih cacah uji
  CI (180, pytest asli) vs lokal (194+) - **belum dikonfirmasi**, karena butuh
  membaca isi setiap `tests/test_*.py` untuk mendeteksi pemakaian fixture/parametrize.
- `lux_modul/eksekusi/binance_client.py` punya disclaimer eksplisit: modul ini belum
  pernah diuji terhadap server Binance sungguhan (testnet maupun live) dari sandbox;
  hanya diuji lewat mock (`tests/test_binance_client.py`). Dua bug nyata sudah
  diperbaiki sebelumnya di `format_nilai()`: boolean Python `True`/`False` yang
  ter-urlencode jadi `"True"/"False"` (menyebabkan -4120), dan notasi ilmiah/derau
  floating point pada harga kecil (menyebabkan -1111).
- `lux_modul/eksekusi/spesifikasi.py` menegakkan arah **Risk -> Notional -> Margin ->
  Leverage**: leverage adalah HASIL perhitungan per setup, bukan input statis: bila
  leverage yang dibutuhkan melebihi batas leverage bracket simbol/operator, rencana
  posisi DITOLAK (`TOLAK_LEVERAGE_MAKS`) - risiko nominal tidak pernah dinaikkan untuk
  memaksakan entry.
- `lux_modul/konfigurasi.py` (`muat_konfigurasi`) sudah mencakup seluruh ambang
  governor (`LUX_MAKS_POSISI` default 4, `LUX_MIN_FREE_MARGIN_PCT` default 0.30) dan
  pemindai (`LUX_PINDAI_*`), konsisten dengan `governor.py` dan `pemindai/likuiditas.py`.

## Koreksi dokumentasi (v9, audit ulang repo 4 Agu 2026)

Audit ulang menemukan bahwa `main.py` (entry point tunggal `--mode
uji|backtest|dashboard|konfigurasi|testnet|live`, gerbang live dua lapis lewat
`lux_modul/eksekusi/kredensial.py`) dan `tests/test_portofolio_governor.py` (unit test
governor lengkap: kuota 4 posisi, margin minimum, duplikat simbol, arah berlawanan, swing
tidak pernah auto-entry, kebijakan tidak sah, ringkasan sinyal tertolak untuk dashboard)
**SUDAH ADA** di `main` sebelum sesi ini - STATE v8 dan RESUME_PROMPT v6 salah menyebut
keduanya "belum dimulai"/"belum ditulis" atau tidak menyebutkannya sama sekali.
`tests/test_live_runner.py` (bracket tracking: `_EntryPending`/`_BracketAktif`, timeout
entry pending (4 jam) dan bracket aktif (7 hari), event notifier per transisi, OCO
sederhana SL/TP) memang belum ada sebelumnya dan **baru ditulis di sesi ini**.

## Keputusan operator yang mengikat (4 Agu 2026, menambah keputusan 3 Agu)

1. **Swing BUKAN auto-entry, tidak pernah.** Auto-entry hanya berlaku untuk Scalp
   dan Intraday. Swing hanya menghasilkan sinyal yang ditampilkan di Dashboard
   (signal-only), ditegakkan oleh `pastikan_boleh_eksekusi(horizon)`.
2. **Kontrak notifikasi Telegram per horizon**, ditegakkan oleh
   `lux_modul/notifikasi/telegram.py`:

   | Horizon | Auto-entry | Dashboard | Telegram |
   |---|---|---|---|
   | Scalp | ya | ya | ya - Entry dikirim/terisi, TP/SL ter-trigger |
   | Intraday | ya | ya | ya - Entry dikirim/terisi, TP/SL ter-trigger |
   | Scalp/intraday tertolak kuota (governor) | tidak | ya | tidak |
   | Swing | TIDAK PERNAH | ya (signal-only) | tidak |

3. **`GovernorPortofolio` menjadi gerbang wajib sebelum entry** untuk scalp dan
   intraday (lihat bagian governor di bawah). Bila governor gagal dihubungi
   (galat jaringan, snapshot akun tidak terbaca, dst), entry **DITOLAK**
   (fail-safe), bukan diloloskan tanpa pengawasan (fail-open).
4. Keputusan operator 3 Agu 2026 (market order, 4 slot, dsb.) tetap berlaku,
   dengan satu ralat: **TP boleh memakai `TAKE_PROFIT_MARKET`** (lihat bagian
   kebijakan order di bawah) - ini bukan pelonggaran larangan market order untuk
   ENTRY, hanya pengecualian resmi kedua untuk order EXIT (setelah `STOP_MARKET`
   untuk SL), karena TP menutup posisi yang sudah ada, tidak membuka posisi baru.

## Governor - kuota & margin lintas-runner

`lux_modul/governor.py`: `GovernorPortofolio` menerima satu `SnapshotAkun` nyata
(saldo + posisi Binance) di awal setiap siklus lewat `mulai_siklus(snapshot)`, lalu
setiap runner (satu per pair) mengantre kandidat entrinya lewat `antre(kandidat)`
sebelum `putuskan()` dipanggil sekali untuk memutuskan SEMUA kandidat siklus itu
sekaligus - ini menutup celah -2019 "Margin is insufficient" yang sebelumnya bisa
terjadi karena setiap runner memutuskan sendiri-sendiri tanpa tahu kandidat pair lain.
Diuji lengkap di `tests/test_portofolio_governor.py` (sudah ada di repo).

- `KebijakanPortofolio(maks_posisi=4, min_free_margin_pct=0.30,
  maks_posisi_per_simbol=1, izinkan_hedge=False)`.
- `HORIZON_AUTO_ENTRY = (HORIZON_SCALPING, HORIZON_INTRADAY)` - swing tidak pernah
  diantre ke governor untuk auto-entry.
- Kode tolak: `TOLAK_KUOTA_POSISI`, `TOLAK_FREE_MARGIN`, `TOLAK_DUPLIKAT_SIMBOL`,
  `TOLAK_ARAH_BERLAWANAN`, `TOLAK_MARGIN_KURANG`, `TOLAK_BUKAN_AUTO_ENTRY`,
  `TOLAK_MARGIN_TIDAK_SAH`.
- Integrasi ke `mesin_multi.py` (`MesinMultiPair`): parameter baru `governor`,
  `ambil_snapshot_akun`, `notifier` (semua default `None`, backward compatible).
  `_ambil_snapshot()` menarik saldo+posisi nyata dari `client.saldo()` +
  `client.posisi()` kecuali disuntik custom. Bila snapshot gagal diambil, siklus
  **fail-safe**: dipakai `SnapshotAkun(equity=0.0, margin_tersedia=0.0, posisi=())`
  sehingga SEMUA entry siklus itu ditolak governor, bukan diloloskan.
  `RingkasanSiklus.sinyal_tertolak_governor` mencatat setiap sinyal yang ditolak
  (untuk dashboard, tab Sinyal Terlewat).
- Integrasi ke `live_runner.py`: parameter `pemeriksa_entry_fn` (closure per-runner
  dari `mesin_multi.py`) dipanggil sebelum entry dieksekusi. **Bug fail-open
  diperbaiki (4 Agu 2026)**: sebelumnya bila `pemeriksa_entry_fn` melempar exception
  (governor tidak terjangkau), kode tidak melakukan `return siklus` sehingga entry
  tetap dieksekusi TANPA pengawasan governor - persis kebalikan dari tujuan
  governor. Sekarang exception dari governor selalu `return siklus` dengan
  `alasan_ditolak_governor = "governor_error"` - entry ditolak, tidak diloloskan.

## Bracket tracking di `live_runner.py`

`LiveRunner` kini melacak siklus hidup order secara eksplisit lewat `_EntryPending`
(order entry LIMIT GTX yang belum terisi) dan `_BracketAktif` (SL+TP terpasang
setelah entry terisi), dengan `_periksa_entry_pending()` dan
`_periksa_bracket_aktif()` dipanggil setiap poll. Timeout: `BRACKET_POLL_TIMEOUT_MS`
(4 jam) untuk entry pending, `MONITOR_TIMEOUT_MS` (7 hari) untuk bracket aktif.
Event dikirim ke notifier (Telegram, hanya scalp/intraday) pada setiap transisi:
entry dikirim -> entry terisi -> SL/TP ter-trigger. Diuji di `tests/test_live_runner.py`
(BARU sesi ini): entry terisi -> kirim SL+TP -> notifier, timeout entry pending,
SL/TP tertrigger -> OCO (batalkan sisi lain) + notifier, timeout bracket aktif, dan
galat status_order tidak menghentikan pengawasan (entry tetap dipantau, bukan hilang
diam-diam).

## Kebijakan order - ralat TP boleh market (4 Agu 2026)

`lux_modul/eksekusi/order.py` diralat dari versi 3 Agu 2026 ("market order
diharamkan total, tanpa kecuali selain SL"):

- `TIPE_TERLARANG_ENTRY = ("MARKET", "TRAILING_STOP_MARKET")` - `TAKE_PROFIT_MARKET`
  **tidak lagi** ada di daftar terlarang karena ia dipakai untuk EXIT (menutup
  posisi), bukan ENTRY. `TIPE_TERLARANG` adalah alias backward-compat.
- `payload_tp_market()` baru: `TAKE_PROFIT_MARKET` + `closePosition=True` +
  `workingType=MARK_PRICE`. Dilarang dipakai untuk entry (`pastikan_tanpa_market`
  tetap melempar `OrderTerlarang` bila `TAKE_PROFIT_MARKET` muncul di jalur entry).
- `payload_bracket()` baru: mengembalikan `(payload_sl, payload_tp_market)` siap
  dikirim berurutan setelah entry terisi - inilah yang dipakai bracket tracking di
  `live_runner.py`.
- `KebijakanOrder.izinkan_tp_market: bool = True` (default) - dasar kebijakan
  untuk `payload_tp_market()`/`payload_bracket()`.
- Entry TETAP wajib `LIMIT` + `timeInForce=GTX` (post-only), tidak berubah.
- **Diverifikasi di Binance Testnet (4 Agu 2026) via GitHub Actions**: LIMIT GTX
  diterima, `STOP_MARKET closePosition` diterima saat posisi terbuka,
  `TAKE_PROFIT_MARKET closePosition` diterima saat posisi terbuka. Bug serialisasi
  bool Python (`True` terkirim sebagai string `"true"`, bukan JSON boolean) yang
  sebelumnya menyebabkan -1111 sudah diperbaiki di `format_nilai`.

## Fix fallback pemindai - kriteria tidak pernah dilonggarkan (4 Agu 2026)

`lux_modul/pemindai/likuiditas.py`: sebelumnya, bila pemeriksaan spread/kedalaman
buku order hanya meloloskan pair di bawah `min_pair` (mis. 23 dari target 25),
kode membuang SELURUH verifikasi buku dan memeringkat ulang SEMUA kandidat murni
dari volume+aktivitas mentah (tanpa spread/kedalaman) - ini melonggarkan kriteria
persis saat pasar sedang ketat, kebalikan dari yang diinginkan. Diperbaiki: pair
yang sudah lolos verifikasi buku dipakai apa adanya, walau di bawah `min_pair`.
Pagar arsitektural `<2 pair -> PemindaiError` tidak berubah.

## Temuan penting - batasan Binance Futures Testnet (bukan bug kode)

Pada `testnet.binancefuture.com`, `STOP_MARKET`/`TAKE_PROFIT_MARKET` sempat
ditolak dengan kode -4120 walau posisi nyata sudah ada. Setelah investigasi
mendalam (bukan bug bool Python "True" jadi string, sudah diperbaiki di atas),
kesimpulan akhir: **ini batasan environment testnet**, bukan bug kode - dikonfirmasi
operator lewat screenshot UI `testnet.binancefuture.com` yang berhasil memasang
SL/TP untuk posisi BTCUSDT secara manual (mis. SL 63.000, TP 65.110). Live API
(`fapi.binance.com`) mendukung `STOP_MARKET`/`TAKE_PROFIT_MARKET` secara normal.
Spesifikasi testnet BTCUSDT yang terverifikasi: `minNotional=50.0`, `tickSize=0.1`,
`stepSize=0.0001`.

## P0 (integrasi live) - status saat ini

| Item | Status |
|---|---|
| `lux_modul/kontrak.py` (`HORIZON_*`, `MODE_SIGNAL_ONLY`, `MODE_PER_HORIZON`) | di repo |
| `lux_modul/governor.py` | di repo |
| `lux_modul/eksekusi/order.py` (TP market, bracket) | di repo |
| `lux_modul/notifikasi/telegram.py` (event per horizon) | di repo |
| `lux_modul/konfigurasi.py` (`HORIZON_PILIHAN`, `status_kredensial`) | di repo |
| `lux_modul/konfigurasi.py::daftar_entry_tf/daftar_simbol/kriteria_pindai` (dipakai `live_run.py`) | **bug kritis diperbaiki sesi ini** - sebelumnya tidak didefinisikan sama sekali, `live_run.py` pasti crash `AttributeError`; sekarang di repo + diuji (`tests/test_konfigurasi_tf_simbol.py`) |
| `lux_modul/eksekusi/kredensial.py` (gerbang live 2 lapis) | di repo, diaudit isinya sesi ini |
| `lux_modul/eksekusi/binance_client.py`, `ice_breaker.py`, `risiko.py`, `spesifikasi.py`, `biaya.py` | di repo, semua diaudit isinya sesi ini |
| `lux_modul/rencana_tf.py` | di repo, diaudit isinya sesi ini - TF entry digerakkan kontrak strategi, bukan `.env` |
| `lux_modul/live_runner.py` (bracket tracking + fix fail-open governor) | di repo |
| `lux_modul/mesin_multi.py` (integrasi governor + snapshot + notifier) | di repo, diaudit isinya sesi ini |
| `lux_modul/pemindai/likuiditas.py` (fix fallback tidak melonggarkan kriteria) | di repo, diaudit isinya sesi ini |
| `main.py` (entry point tunggal --mode uji\|backtest\|dashboard\|konfigurasi\|testnet\|live) | di repo |
| `scripts/live_run.py`, `scripts/dashboard_data.py`, `scripts/jalankan_uji.py` | di repo, diaudit isinya sesi ini |
| `scripts/demo_sintetis.py` | diverifikasi cocok dengan signature `ukuran_posisi` saat ini, tidak perlu diubah |
| Unit test skenario governor (diterima/ditolak, fail-safe snapshot gagal, fail-safe exception) | **sudah ada** - `tests/test_portofolio_governor.py` |
| `tests/test_live_runner.py` untuk bracket tracking | **sudah ditulis** (sesi ini) |
| Dashboard real-time (server auto-refresh, bukan generate-sekali) | **belum dimulai** - `main.py --mode dashboard` saat ini hanya generate `dashboard/data.json` statis sekali |
| Verifikasi ulang seluruh suite uji (194+1+9 lokal) pasca perubahan governor/bracket/konfigurasi | **belum dijalankan ulang setelah patch sesi ini** (sandbox tanpa akses jaringan) |
| `scripts/uji_bracket_penuh.py`, `scripts/uji_sl_tp_posisi.py`, `scripts/uji_testnet.py` | **belum diaudit isinya** |

## Bagian historis (P0 sinkronisasi repo putaran sebelumnya, backtest, biaya) tidak berubah

Lihat bagian di bawah untuk riwayat penuh sampai 3 Agustus 2026 (backtest putaran 1-3,
model biaya, Figma dibatalkan, dsb.) - semuanya masih berlaku, tidak ditimpa oleh
perubahan governor/bracket/kontrak Telegram di atas karena keduanya lapis berbeda
(backtest historis vs eksekusi live).

### P0 (sinkronisasi repo, 3 Agu 2026) - SELESAI 100%

Seluruh berkas yang sebelumnya "belum tersinkron" di STATE v6 sudah di-push ke
`main` dan diverifikasi konsisten dengan sandbox: `lux_modul/eksekusi/order.py`
(v6), `lux_modul/portofolio.py`, `dashboard/index.html`,
`reports/CATATAN_BACKTEST_3.md`, `lux_modul/backtest_portofolio.py`,
`lux_modul/eksekusi/biaya.py`, `lux_modul/eksekusi/ice_breaker.py`,
`lux_modul/backtest.py`, `scripts/bt_portofolio.py`, `scripts/dashboard_data.py`,
`tests/test_order_postonly.py`, `tests/test_portofolio.py`, `.gitignore`.

### Bug diperbaiki (3 Agu 2026)

`HasilPortofolio.ringkas()` di `backtest_portofolio.py` sebelumnya TIDAK menyertakan
`kurva_ekuitas` di payload, sehingga dashboard tidak punya data untuk grafik ekuitas.
Diperbaiki dengan fungsi `_ringkas_kurva()` baru (downsample maksimum 500 titik,
titik awal/akhir dipertahankan agar rentang waktu tetap akurat). Diuji lokal:
**83 lulus, 0 gagal** tetap konsisten setelah patch (jumlah uji bertambah pada
putaran berikutnya menjadi 194 - lihat `RESUME_PROMPT.md`).

### Model biaya (putaran 3, tidak berubah)

| Kaki | Tipe order | Fee | Slippage |
|---|---|---|---|
| Entry | LIMIT + GTX | 2 bps maker | 0 |
| TP | LIMIT + GTX reduceOnly | 2 bps maker | 0 |
| SL | STOP_MARKET closePosition | 5 bps taker | 2 bps |

Round trip: 9 bps (1 TP) sampai 13 bps (3 TP). Sebelumnya 21-28 bps (model taker simetris).

### Hasil backtest putaran 3 (dataset kecil, 6 simbol likuid, portofolio 4 slot)

| Konfigurasi | Trade | WR | PF | PnL kotor | PnL bersih | MaxDD | Sinyal terlewat |
|---|---|---|---|---|---|---|---|
| `single_15m` (6000 bar) | 446 | 41,3% | 1,12 | +508,31 | -81,28 | 44,1% | 1173 |
| `multi_15m_ctx1h` (2500 bar) | 135 | 43,0% | 1,71 | +745,07 | +577,71 | 31,0% | 1571 |
| `single_5m` (2500 bar) | 126 | 19,8% | 0,17 | -451,95 | -575,86 | 71,5% | 213 |
| `multi_5m_ctx15m` (2500 bar) | 59 | 44,1% | 8,20 | +3455,84 | +3369,93 | 25,8% | 1556 |

**Peringatan interpretasi (jangan dibaca sebagai bukti edge)**: PF 8,20 pada
`multi_5m_ctx15m` berasal dari hanya 59 trade - sampel jauh terlalu kecil;
`single_5m` PF 0,17/WR 19,8% mengindikasikan konfigurasi rusak untuk TF ini pada
dataset kecil ini; `single_15m` frekuensi tinggi (446 trade) tapi PnL bersih
negatif (-81,28) walau kotor positif; seluruh 4 konfigurasi punya sinyal terlewat
besar (213-1571), semuanya `slot_penuh`. Detail: `reports/CATATAN_BACKTEST_3.md`.

### Figma dibatalkan (3 Agu 2026)

Operator awalnya menyetujui Figma untuk merancang flow dashboard (3 diagram FigJam
di board `https://www.figma.com/board/yneP8GKRr7y2swbir3vMWW`), lalu membatalkannya
karena FigJam hanya menghasilkan flow/diagram, bukan desain UI final. Dashboard
dibangun langsung sebagai HTML/JS statis (`dashboard/index.html` + `data.json`).

## Pekerjaan berikutnya (urut, menggantikan daftar v9)

1. ~~Tulis unit test governor~~ - **sudah ada** sebagai `tests/test_portofolio_governor.py`.
2. ~~Tulis `tests/test_live_runner.py`~~ - **sudah ditulis** (sesi ini).
3. ~~Baca isi `rencana_tf.py`, `kredensial.py`, sisa `eksekusi/*`, `live_run.py`,
   `dashboard_data.py`, `jalankan_uji.py`~~ - **sudah dibaca semua** (sesi ini); bug
   kritis `konfigurasi.py` ditemukan dan diperbaiki (lihat bagian atas).
4. Jalankan ulang seluruh suite uji (`python -m pytest tests -q`) untuk memastikan
   tidak ada regresi dari integrasi governor + bracket tracking + fix pemindai +
   `test_live_runner.py` + `test_konfigurasi_tf_simbol.py` baru (sandbox tanpa akses
   jaringan - jalankan lewat CI atau replikasi source tree manual).
5. Samakan cacah uji CI vs lokal (perbedaan 180 vs 194+1+9). Kandidat penyebab baru
   ditemukan sesi ini: `scripts/jalankan_uji.py` adalah shim lokal tanpa dukungan
   fixture/parametrize pytest sungguhan - belum dikonfirmasi sebagai penyebab pasti.
6. Bangun **server** dashboard real-time (auto-refresh): `main.py --mode dashboard`
   sudah ada tapi HANYA generate `dashboard/data.json` statis sekali lewat
   `scripts/dashboard_data.py` - belum ada server/loop auto-refresh untuk market,
   posisi aktif, order di Binance, equity/margin, sinyal swing, sinyal tertolak
   governor (`RingkasanSiklus.sinyal_tertolak_governor` sudah tersedia sebagai
   sumber data).
7. Baca isi `scripts/uji_bracket_penuh.py` / `scripts/uji_sl_tp_posisi.py` /
   `scripts/uji_testnet.py` - satu-satunya skrip live/testnet yang belum diaudit
   sesi ini; pastikan konsisten dengan `main.py` dan fix `konfigurasi.py` terbaru.
8. Jalankan ulang `backtest95.yml` dengan model biaya + kebijakan eksekusi
   terbaru (TP market, bracket).
9. Layer `EventBus` + persistensi state.

## Jebakan operasional (jangan diulang)

- Sandbox bisa ter-reset kapan saja; berkas `/tmp` TIDAK PERSISTEN antar sesi
  terminal berbeda - jangan mengandalkan file dari tool call sebelumnya.
- Proses latar belakang dibunuh di antara panggilan terminal -> job panjang harus
  selesai dalam satu panggilan foreground, atau dipindah ke GitHub Actions.
- Push GitHub harus berurutan (paralel -> HTTP 409), atau satu commit lewat `push_files`.
- Dataset besar tidak bisa di-push sebagai berkas repo; gunakan release `95-pair-dataset`.
- Alat agen tidak punya akses API workflow-run Actions; status dipantau dari artefak commit.
- Sandbox komputer tidak punya akses jaringan (`git clone` gagal) - ambil berkas satu per
  satu lewat GitHub API bila perlu menjalankan sesuatu secara lokal.
