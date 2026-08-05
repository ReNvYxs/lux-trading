# RESUME_PROMPT (v8)

Cukup katakan: **"Lanjutkan riset di repo `lux-modul-trading`."**
Berkas ini adalah titik masuk tunggal untuk melanjutkan pekerjaan di sesi/model AI mana pun.
Urutan baca: **RESUME_PROMPT.md** -> **STATE.md** (kondisi terakhir) -> **README.md** (ikhtisar teknis)
-> **ARSITEKTUR.md** (desain rinci) -> `TELEGRAM.md` (rencana adapter) -> `reports/CATATAN_BACKTEST_*.md`.

## 0. Aturan kerja operator (wajib dipatuhi)

- Bahasa kerja: **Indonesia**.
- Repo `EnVyxS/lux-modul-trading` (privat) adalah **satu-satunya penyimpanan persisten**.
  Sandbox bisa hilang sewaktu-waktu; apa pun yang penting harus di-push.
- Repo referensi `EnVyxS/lux-ai-research` dan `EnVyxS/lux-trading-strategy` hanya untuk konteks.
  **Jangan porting strategi dari sana.**
- Kata "lanjut" / "lanjutkan" / "continue" dari operator = **setuju dengan rekomendasi terakhir**;
  langsung kerjakan tanpa bertanya lagi.
- **Dilarang** menyetel strategi hanya supaya dataset terlihat profit.
- **Dilarang** ada strategi "raja" atau blocker di lapis mana pun (termasuk L5 portofolio DAN
  L5-live governor). Semua strategi dievaluasi tiap candle secara independen, tanpa short-circuit.
- Arsitektur harus tetap **plugin-based / extensible** (jumlah strategi tidak dibatasi).
- **Swing = sinyal saja, tidak pernah auto-entry, tidak pernah ke Telegram.** Scalping dan
  intraday boleh auto-entry DAN wajib lapor ke Telegram tiap event penting (entry
  dikirim/terisi, SL/TP ter-trigger). Sinyal scalp/intraday yang ditolak governor karena
  kuota/margin tampil di dashboard saja, tidak ke Telegram. Lihat tabel kontrak di STATE.md.
- Rumus di `lux_modul/eksekusi/risiko.py` **tidak boleh diubah**; perbaikan struktural di lapis lain.
- **Market order DIHARAMKAN untuk ENTRY.** Entry wajib `LIMIT` + `timeInForce=GTX` (post-only).
  SL wajib `STOP_MARKET`. TP boleh `LIMIT+GTX` (maker) ATAU `TAKE_PROFIT_MARKET` (exit,
  bukan entry) - lihat `lux_modul/eksekusi/order.py` dan ARSITEKTUR.md bagian 8.5.
- **Maksimum 4 posisi terbuka bersamaan, wajib beda pair.** Untuk backtest single-proses:
  `lux_modul/portofolio.py` (`ManajerSlot`). Untuk live multi-pair: `lux_modul/governor.py`
  (`GovernorPortofolio`), yang memakai snapshot akun **nyata** (bukan simulasi) dan menolak
  entry secara fail-safe bila snapshot atau governor gagal dihubungi (jangan pernah fail-open).
  Sinyal yang gagal masuk wajib tercatat (`SinyalTerlewat` / `sinyal_tertolak_governor`).
- Dataset backtest hanya **OHLCV**. Strategi yang butuh Order Flow / OI / Funding / CVD
  didaftarkan di `CALON_STRATEGI.md`; **dilarang membuat data sintetis** untuk menutupinya.
- **Figma dibatalkan** (3 Agu 2026) - jangan gunakan tool Figma lagi; dashboard adalah HTML/JS
  statis langsung di repo (rencana selanjutnya: server real-time, lihat bagian 7).
- Jangan pernah menghubungkan akun Binance **live** tanpa konfirmasi eksplisit operator.
  Kredensial testnet sudah diizinkan operator untuk verifikasi otomatis lewat GitHub Actions.
  Mode live di `main.py` sudah punya gerbang ganda (`--konfirmasi-live` + env
  `LUX_LIVE_KONFIRMASI` + konfirmasi ketik ulang frasa via `lux_modul/eksekusi/kredensial.py`).

## 1. Status singkat

- Modul **selesai secara fungsional** untuk backtest (arsitektur 6 lapis termasuk L5
  portofolio, 26 unit strategi di 6 kelompok, arbiter, risiko, kebijakan order post-only,
  ice-breaker, gerbang biaya asimetris, pipeline, backtester single-simbol dan
  multi-simbol/portofolio) DAN untuk live trading dasar (governor lintas-runner, bracket
  tracking entry->SL/TP, notifier Telegram event-driven per horizon, fix fail-open governor).
- **P0 sinkronisasi repo (3 Agu 2026) selesai 100%.**
- **P0 integrasi live (4 Agu 2026)**: `governor.py`, integrasi ke `mesin_multi.py` dan
  `live_runner.py`, kontrak Telegram per horizon, ralat kebijakan order (TP boleh market),
  fix bug fallback pemindai likuiditas, `main.py` (entry point tunggal `--mode
  uji|backtest|dashboard|konfigurasi|testnet|live`, gerbang ganda live via
  `lux_modul/eksekusi/kredensial.py`) - **semua sudah di-push ke `main`**.
- **Bug kritis ditemukan & diperbaiki (audit lanjutan, sesi ini)**: `scripts/live_run.py`
  memanggil `cfg.daftar_entry_tf()`, `cfg.daftar_simbol()`, `cfg.kriteria_pindai()` pada
  `Konfigurasi`, tapi ketiganya **tidak pernah didefinisikan** - `live_run.py` pasti crash
  `AttributeError` begitu dijalankan (testnet/live, satu-pair/multi-pair). Tidak pernah
  terdeteksi sebelumnya karena skrip ini belum pernah benar-benar dieksekusi (sandbox tanpa
  akses jaringan ke Binance). Sudah diperbaiki + diuji regresi
  (`tests/test_konfigurasi_tf_simbol.py`, 9 test) - lihat STATE.md bagian atas untuk detail.
- Audit lengkap sesi ini juga mencakup seluruh `lux_modul/eksekusi/*.py`, `rencana_tf.py`,
  `pemindai/likuiditas.py`, `mesin_multi.py`, `scripts/live_run.py`, `scripts/dashboard_data.py`,
  dan `scripts/jalankan_uji.py` (shim pytest lokal, kandidat penyebab selisih cacah uji CI vs
  lokal - lihat bagian 7 langkah #4). Sisa yang belum diaudit: `scripts/uji_bracket_penuh.py`,
  `scripts/uji_sl_tp_posisi.py`, `scripts/uji_testnet.py`.
- **Ralat dokumentasi (audit ulang sebelumnya)**: `main.py` dan
  `tests/test_portofolio_governor.py` (unit test governor lengkap: kuota, margin, duplikat
  simbol, arah berlawanan, swing tidak auto-entry, kebijakan tidak sah, ringkasan sinyal
  tertolak) **sudah ada** di `main` sebelum sesi sebelumnya - versi v6 sebelumnya salah menyebut
  keduanya "belum ditulis"/tidak menyebutkannya sama sekali. `tests/test_live_runner.py`
  (bracket tracking: `_EntryPending`/`_BracketAktif`, timeout, event notifier, OCO
  sederhana) memang belum ada sebelumnya dan **baru ditulis sebelum sesi ini**.
- Uji otomatis: sempat **83 lulus / 0 gagal** pada putaran 3 (3 Agu); jumlah bertambah jadi
  **194** secara lokal pada putaran berikutnya, dan bertambah lagi dengan
  `tests/test_live_runner.py` dan `tests/test_konfigurasi_tf_simbol.py` baru (belum
  diverifikasi ulang setelah patch governor/bracket/pemindai/konfigurasi sesi 4 Agu - lihat
  bagian 7 langkah #1). CI melaporkan 180 - perbedaan cacah CI vs lokal belum diinvestigasi;
  kandidat penyebab baru: `scripts/jalankan_uji.py` adalah shim lokal tanpa dukungan
  fixture/parametrize pytest sungguhan (belum dikonfirmasi).
- Dataset kecil (BTC, 5 TF) sudah diaudit dan diuji lewat 3 putaran (lihat
  `reports/CATATAN_BACKTEST_*.md`); putaran 3 menunjukkan PnL kotor positif di 3 dari 4
  konfigurasi, sampel masih kecil - **belum bukti edge**.
- Dataset besar (95 simbol) tersedia di release `95-pair-dataset`; belum diuji ulang dengan
  model biaya + kebijakan eksekusi terbaru (termasuk TP market) lewat GitHub Actions.
- Kebijakan order dan bracket TP/SL **diverifikasi nyata di Binance Futures Testnet**
  (4 Agu 2026) via GitHub Actions dan dikonfirmasi operator lewat UI testnet: LIMIT GTX,
  STOP_MARKET, dan TAKE_PROFIT_MARKET semuanya diterima bursa saat posisi terbuka ada.
  Kegagalan -4120 yang sempat terlihat adalah batasan environment testnet (bukan bug kode).
- Dashboard lokal (`dashboard/index.html`, 8 tab termasuk "Sinyal Terlewat") sudah di repo
  dengan data backtest statis, dibangkitkan lewat `main.py --mode dashboard` ->
  `scripts/dashboard_data.py`; ini generate-sekali, BUKAN server. Server real-time (posisi
  live, sinyal governor tertolak, sinyal swing, auto-refresh) **belum dibangun**.
- Lapisan Telegram **event-driven sudah diimplementasikan** untuk scalp/intraday
  (`lux_modul/notifikasi/telegram.py`); adapter penuh (command dua arah, dst.) masih
  sesuai rencana di `TELEGRAM.md`.
- **BELUM layak** untuk real trading di Binance. Layak untuk paper/demo testnet setelah
  verifikasi suite uji penuh pasca-patch governor/bracket/konfigurasi.

## 2. Peta repo (audit eksekusi/*, rencana_tf.py, live_run.py, dashboard_data.py, jalankan_uji.py selesai sesi ini)

```
main.py                        entry point tunggal: --mode uji|backtest|dashboard|
                                konfigurasi|testnet|live (gerbang ganda utk live)
lux_modul/
  kontrak.py                Bars, TFPlan, StrategyVerdict, HORIZON_*, MODE_SIGNAL_ONLY/PER_HORIZON
  plugin.py                 registrasi plugin (KATALOG_*, env LUX_PLUGIN_PATHS)
  pipeline.py                 jalur sinyal -> keputusan -> sizing (+ gerbang biaya)
  backtest.py                  simulasi bar-by-bar satu simbol (fee maker entry/TP, taker+slip SL)
  backtest_portofolio.py       simulasi banyak simbol, satu saldo, ManajerSlot, ledger terlewat
  portofolio.py                 L5: ManajerSlot 4 slot beda pair + SinyalTerlewat (backtest)
  governor.py                   L5-live: GovernorPortofolio, kuota+margin lintas-runner
  mesin_multi.py                 MesinMultiPair: koordinator banyak LiveRunner + governor
  live_runner.py                 LiveRunner: bracket tracking entry->SL/TP, fix fail-open
  konfigurasi.py                  muat_konfigurasi(), HORIZON_PILIHAN, status_kredensial(),
                                 daftar_entry_tf()/daftar_simbol()/kriteria_pindai() (BUG
                                 KRITIS diperbaiki sesi ini - lihat STATE.md)
  rencana_tf.py                   TANGGA_KONTEKS, ENTRY_TF_HORIZON, uraikan_daftar_tf(),
                                 rencana_dari_registry() - TF plan digerakkan kontrak strategi,
                                 bukan .env hardcode (diaudit sesi ini)
  sintetis.py                   generator data uji
  data/                          loader.py, resample.py, plane.py
  fitur/                         dasar.py, lanjutan.py, struktur.py, store.py
  strategi/                      26 unit dalam 6 kelompok teknik + basis.py, adaptor.py, util.py
  arbiter/pemilih.py              skor 0-100, ambang per strategi, konflik arah
  pemindai/likuiditas.py           PemindaiPasar, KriteriaLikuiditas, fix fallback (diaudit sesi ini)
  notifikasi/telegram.py           NotifierTelegram event-driven per horizon
  eksekusi/
    risiko.py                    sizing (JANGAN ubah rumus) (diaudit sesi ini)
    order.py                      entry post-only wajib, SL STOP_MARKET, TP LIMIT/market
    ice_breaker.py                 plan_execution TWAP+iceberg (LIMIT+GTX), entry_invalidated
                                   (diaudit sesi ini)
    mode.py                       boleh_auto_entry(horizon)
    biaya.py                       gerbang biaya asimetris (maker entry/TP, taker+slip SL)
                                   (diaudit sesi ini)
    kredensial.py                  FRASA_KONFIRMASI_LIVE, gerbang konfirmasi live dua lapis
                                   (diaudit sesi ini)
    binance_client.py              klien REST testnet+live, belum pernah diuji terhadap
                                   server Binance sungguhan dari sandbox (diaudit sesi ini)
    spesifikasi.py                  Risk->Notional->Margin->Leverage, rencana_posisi(),
                                   ekonomi_trade() (diaudit sesi ini)
scripts/                         audit_dataset.py, bt_satu.py, bt_banyak.py, bt_portofolio.py,
                                 dashboard_data.py (diaudit sesi ini), backtest_btc.py,
                                 demo_sintetis.py, jalankan_uji.py (shim pytest lokal, diaudit
                                 sesi ini), live_run.py (diaudit sesi ini, sumber temuan bug
                                 konfigurasi.py), uji_testnet.py, uji_bracket_penuh.py,
                                 uji_sl_tp_posisi.py (masih belum diaudit), asap_e2e.py,
                                 asap_multi_e2e.py, bt95_metrik.py, diagnosa_kondisional.py,
                                 uji_kondisional.py (beberapa belum diaudit detail sesi ini)
tests/                           test_inti.py, test_strategi_arbiter.py, test_backtest.py,
                                 test_biaya.py, test_order_postonly.py, test_portofolio.py,
                                 test_portofolio_governor.py, test_binance_client.py,
                                 test_konfigurasi.py, test_kredensial.py,
                                 test_serialisasi_order.py, test_spesifikasi.py,
                                 test_pemindai.py, test_live_runner.py,
                                 test_konfigurasi_tf_simbol.py (BARU sesi ini, 9 test)
dashboard/                        index.html (8 tab, termasuk Sinyal Terlewat), data.json (statis)
reports/                          audit_dataset.json, ci_terakhir.json, CATATAN_BACKTEST_1/2/3.md,
                                 backtest_btc_kecil_v2.json, backtest_kecil_v3.json, putaran1/ (arsip)
.github/workflows/                ci.yml, backtest95.yml
TELEGRAM.md                        rencana adapter Telegram penuh (event-driven dasar sudah jalan)
CALON_STRATEGI.md                  strategi yang menunggu data non-OHLCV (CVD, OI, funding, dst)
AUDIT_LEVERAGE_PRESISI.md, AUDIT_TOTAL.md, KONFIGURASI.md, LAPORAN_BACKTEST_95.md, REFERENSI.md
                                 (dokumen tambahan di repo, belum diaudit isinya sesi ini)
STATE.md / ARSITEKTUR.md           v10 / 0.3.0 - governor, bracket tracking, kontrak Telegram,
                                 bug kritis konfigurasi.py diperbaiki
```

## 3. Dataset `95-pair-dataset` (permanen di GitHub Release, tidak berubah)

- Tag **`95-pair-dataset`**, aset **`95.pair.zip`** (91.701.505 byte).
  Unduh: `https://github.com/EnVyxS/lux-modul-trading/releases/download/95-pair-dataset/95.pair.zip`
- Isi: **476 CSV** `<SIMBOL>_<TF>.csv`, **95 simbol** x TF `{5m,15m,1h,4h,1d}`, kolom
  `timestamp(ms), open, high, low, close, volume`. BTC/ETH 5m = 51.840 baris, 0 baris rusak.
- Di runner Actions: `gh release download 95-pair-dataset -p '95.pair.zip' -R <repo>` lalu
  `unzip -q 95.pair.zip -d dataset_masuk/ekstrak`.
- Di sandbox tanpa jaringan: minta operator mengunggah ulang arsipnya, lalu verifikasi dengan
  `python scripts/audit_dataset.py` dibanding `reports/audit_dataset.json`.
- **CSV besar tidak bisa di-push sebagai berkas repo**. Release adalah jalur resmi.

## 4. Governor + bracket tracking (4 Agu 2026 - ringkas, detail di ARSITEKTUR.md 9.1/8.7)

- `governor.py::GovernorPortofolio` memutuskan SEMUA kandidat entry (scalp/intraday) satu
  siklus sekaligus, berdasarkan satu `SnapshotAkun` nyata (bukan simulasi per-runner) -
  menutup celah -2019 "Margin is insufficient" lintas-pair. Diuji lengkap di
  `tests/test_portofolio_governor.py`.
- Fail-safe wajib di dua titik: snapshot akun gagal diambil -> semua kandidat ditolak;
  `pemeriksa_entry_fn` melempar exception -> entry ditolak (bug fail-open lama sudah
  diperbaiki, `return siklus` selalu dipanggil setelah exception).
- `live_runner.py` melacak `_EntryPending` -> `_BracketAktif` (SL+TP via `payload_bracket()`)
  dengan timeout masing-masing 4 jam dan 7 hari, memicu event Telegram di setiap transisi.
  Diuji di `tests/test_live_runner.py`.
- Kebijakan order diralat: TP boleh `TAKE_PROFIT_MARKET` (exit, bukan entry) selain
  `LIMIT+GTX`; entry tetap wajib post-only.
- Fix fallback pemindai likuiditas: kriteria tidak pernah dilonggarkan saat verifikasi
  buku order meloloskan pair di bawah `min_pair`.
- **Bug kritis diperbaiki sesi ini**: `scripts/live_run.py` (jalur satu-pair dan multi-pair)
  memanggil `Konfigurasi.daftar_entry_tf()/daftar_simbol()/kriteria_pindai()` yang sebelumnya
  tidak ada - lihat STATE.md untuk detail lengkap dan kode fix.

## 5. Keputusan desain: gerbang biaya asimetris (`lux_modul/eksekusi/biaya.py`, tidak berubah)

Masalah putaran 1: akun habis dimakan fee+slippage taker simetris. Putaran 3 (kebijakan
post-only, 3 Agu 2026): entry dan TP wajib LIMIT+GTX (fee maker, slippage 0); hanya kaki SL
(STOP_MARKET) yang masih taker+slippage. Round trip turun dari 21-28 bps menjadi **9-13 bps**.
Detail: ARSITEKTUR.md bagian 8.6. **Catatan pending**: bila live memakai `payload_tp_market()`
(TAKE_PROFIT_MARKET, bukan TP LIMIT+GTX), kaki TP itu jadi taker - `biaya.py` belum
diperbarui untuk merefleksikan skenario ini pada backtest (lihat bagian 7, langkah #7).

## 6. Hasil uji sejauh ini (dataset kecil, tidak berubah sejak putaran 3)

Putaran 1 (tanpa gerbang biaya, arsip `reports/putaran1/`): biaya 757-1.129 USDT dari modal
1.000, akun praktis nol di semua konfigurasi.

Putaran 2 (gerbang biaya aktif, model taker simetris): biaya turun ~89%, tidak ada akun nol,
tetapi PnL kotor negatif di semua konfigurasi -> kendala mengikat adalah edge strategi.

Putaran 3 (kebijakan post-only + biaya asimetris + portofolio 4 slot, 6 simbol likuid,
`reports/backtest_kecil_v3.json`): PnL kotor positif di 3 dari 4 konfigurasi (lihat STATE.md
untuk tabel lengkap). **Peringatan**: sampel `multi_5m_ctx15m` hanya 59 trade dan `single_5m`
menunjukkan tanda rusak (WR 19,8%, PF 0,17) - keduanya butuh investigasi lebih lanjut, bukan
bukti edge final.

## 7. Langkah berikutnya (urut, menggantikan daftar v7)

1. **Verifikasi suite uji penuh** (`python -m pytest tests -q`) pasca-patch governor +
   bracket tracking + fix pemindai + fix `konfigurasi.py` + `tests/test_live_runner.py` +
   `tests/test_konfigurasi_tf_simbol.py` baru - belum dijalankan ulang setelah push sesi ini
   (sandbox tidak punya akses jaringan untuk `git clone`; jalankan via CI GitHub Actions atau
   replikasi source tree manual bila perlu di sandbox).
2. ~~Tulis `tests/test_governor.py`~~ - **sudah ada** sebagai `tests/test_portofolio_governor.py`.
3. ~~Tulis `tests/test_live_runner.py`~~ - **sudah ditulis**.
4. Samakan cacah uji CI (180) vs lokal (194 + `test_live_runner.py` +
   `test_konfigurasi_tf_simbol.py` baru) - investigasi penyebab selisih. Kandidat baru dari
   sesi ini: `scripts/jalankan_uji.py` adalah shim pytest lokal (dipasang karena sandbox tanpa
   jaringan tidak bisa memasang pytest sungguhan) yang memanggil setiap fungsi `test_*` secara
   langsung TANPA mendukung fixture/`@pytest.mark.parametrize` sungguhan seperti pytest asli
   di CI - **belum dikonfirmasi**, perlu membaca isi test yang mungkin memakai parametrize.
5. Bangun **server** dashboard real-time (auto-refresh, bukan generate-sekali): `main.py
   --mode dashboard` saat ini hanya menjalankan `scripts/dashboard_data.py` sekali untuk
   membangkitkan `dashboard/data.json` statis dari `reports/`. Perlu: market, posisi aktif,
   order Binance, equity/margin, sinyal swing, sinyal tertolak governor
   (`RingkasanSiklus.sinyal_tertolak_governor` sudah tersedia sebagai sumber data).
6. Baca isi `scripts/uji_bracket_penuh.py` / `scripts/uji_sl_tp_posisi.py` /
   `scripts/uji_testnet.py` (satu-satunya skrip live/testnet yang belum diaudit) untuk
   pastikan konsisten dengan `main.py`, governor/bracket, dan fix `konfigurasi.py` terbaru.
7. Eksternalisasi parameter invalidasi (`sl_atr`, buffer struktural hardcode, lantai
   `0.15*ATR`) ke konfigurasi.
8. Perbarui `biaya.py` agar merefleksikan `payload_tp_market()` (TP taker) sebagai opsi
   biaya, terpisah dari TP LIMIT+GTX (maker).
9. Jalankan ulang `backtest95.yml` dengan model biaya + kebijakan eksekusi terbaru; baca
   `reports/besar/RINGKASAN.json` dan `bt95_<konfig>.json`.
10. Identifikasi strategi dengan **edge kotor positif** dan sampel memadai (n >= 200 trade);
    terapkan aturan pensiun strategi sebagai konfigurasi, bukan mengedit logika strategi.
11. Plafon notional/leverage untuk scalping + aturan equity-floor/stop-trading; layer
    manajemen posisi pasca-entry (trailing/breakeven/time-stop).
12. Penilaian akhir kelayakan real/demo Binance (saat ini: **belum layak** - lihat STATE.md).

## 8. Jebakan operasional sandbox (hemat waktu, tidak berubah)

- Proses latar belakang **dibunuh di antara panggilan terminal**. Job panjang: potong dataset
  agar selesai dalam satu panggilan foreground, atau pindahkan ke GitHub Actions.
- Push GitHub **satu per satu** (paralel -> HTTP 409); atau satu commit lewat `push_files`.
- Berkas `/tmp` **TIDAK PERSISTEN** antar sesi terminal berbeda - jangan mengandalkan file
  dari tool call sebelumnya; tulis ulang penuh bila diperlukan.
- Sandbox komputer **tidak punya akses jaringan** (`git clone` gagal, host tidak resolve) -
  untuk membaca/menjalankan source tree secara lokal, ambil berkas satu per satu lewat GitHub
  API lalu tulis manual ke sandbox; tidak bisa clone langsung.
- Resep potong data: `head -1 SRC > potong/BTC_5m.csv; tail -n 7000 SRC >> potong/BTC_5m.csv`.
- Backtest 5m 20.000 bar \u2248 660 detik; 7.000 bar \u2248 164 detik; 15m penuh 17.280 bar \u2248 256 detik.
