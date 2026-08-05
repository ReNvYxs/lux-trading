# TELEGRAM.md - rencana adapter notifikasi/kontrol (BELUM DIIMPLEMENTASIKAN)

Status: **rencana saja**. Tidak ada satu baris kode Telegram di modul ini. Berkas ini
memetakan apa yang ada di bot v8 lama (`bot v8/telegram_bot.py`, dikirim operator
3 Agu 2026, 721 baris) sebagai REFERENSI GARIS BESAR, bukan sesuatu yang akan disalin
langsung. Operator secara eksplisit meminta: "jangan dibuat terlalu mirip, cukup pahami
garis besar fungsinya" - bot v8 disebut punya banyak tambal-sulam.

Perbedaan penting yang wajib diperhatikan bila adapter ini dibangun: modul kami memakai
konsep berbeda dari bot v8 (arbiter skor+ambang bukan setup tunggal, `ManajerSlot` 4 slot
beda pair bukan `max_long_positions`/`max_short_positions`, kebijakan order post-only
wajib di `eksekusi/order.py`, gerbang biaya asimetris di `eksekusi/biaya.py`). Adapter
harus memakai istilah dan struktur data modul kami (`StrategyVerdict`, `SinyalTerlewat`,
`HasilBar`, `HasilPortofolio`), bukan istilah bot v8 (`TradeState`, `journal`, dst).

## 1. Command yang ada di bot v8 (18, dipetakan dari `build_app()` baris 620-649)

| Command | Baris | Fungsi di bot v8 | Relevansi untuk adapter kami |
|---|---|---|---|
| `/start` | 121 | Sapaan + ringkasan strategi/TF/RR/max posisi | Setara: sapaan + ringkasan konfigurasi (`horizon`, `TFPlan`, `ManajerSlot.maks_posisi`) |
| `/help` | 134 | Daftar seluruh command | Setara |
| `/status` | 162 | Ringkasan state + balance + loss/trade harian | Setara: `ManajerSlot.ringkas()` + status halt |
| `/balance` | 192 | Balance + risk/trade + daily limit | Setara: `risiko.py` (risk_usd saat ini) |
| `/positions` | 209 | Posisi terbuka + uPnL + info trailing SL | Setara: `ManajerSlot.simbol_terbuka()` + `PosisiTerbuka` |
| `/journal` | 255 | N trade terakhir (default 10, arg opsional) | Setara: butuh ledger trade tersendiri (belum ada di modul kami) |
| `/stats` | 288 | Win rate, net PnL, fee, avg win/loss (`today` opsional) | Setara: agregasi dari ledger trade |
| `/growth` | 312 | Kurva balance 10 snapshot terakhir | Setara: `kurva_ekuitas` dari `HasilPortofolio` |
| `/risk` | 342 | Tabel risk/trade live per tier saldo | Setara langsung: tabel `risiko.py` bagian 8.2 ARSITEKTUR.md |
| `/limits` | 379 | Ringkasan seluruh limit (loss harian, trade harian, posisi, spread) | Setara: gabungan `ManajerSlot` + limit baru yang BELUM ada di modul kami (lihat bagian 4) |
| `/export` | 408 | Export CSV seluruh trade | Setara: export `SinyalTerlewat`/ledger trade ke CSV |
| `/pause` | 426 | Berhenti buka trade baru, posisi aktif tetap dikelola | Setara langsung |
| `/resume` | 434 | Lanjutkan scanning | Setara langsung |
| `/setdailyloss` | 442 | Override limit loss harian runtime (0 = reset otomatis) | Fitur baru untuk modul kami - lihat bagian 4 |
| `/setmaxspread` | 471 | Ubah ambang spread maksimum runtime | Tidak relevan untuk kami sekarang (belum ada gerbang spread) |
| `/takecontrol` | 490 | Ambil alih posisi yang dibuka manual di exchange (inline button per pair) | TIDAK relevan: modul kami tidak mendeteksi posisi manual di luar `ManajerSlot` |
| `/resetsummary` | 564 | Hapus semua histori trade (konfirmasi inline button) | Setara, tetap butuh konfirmasi dua langkah |
| `/stop` | 592 | Tutup SEMUA posisi (market close) + matikan bot (konfirmasi inline button) | **Konflik kebijakan**: bot v8 menutup pakai market order; modul kami mengharamkan market order (8.5). Kill-switch versi kami wajib tetap post-only atau eksplisit memakai jalur pengecualian SL (`STOP_MARKET`) - perlu keputusan operator sebelum implementasi. |

Otorisasi (`_is_authorized`, baris 75-104): urutan cek `tg_allowed_ids` (whitelist
eksplisit) -> multi-account `tg_user_id` -> `tg_chat_id` (legacy) -> **fail-closed**
(tolak semua command bila tidak ada auth dikonfigurasi sama sekali). Prinsip fail-closed
ini WAJIB dipertahankan di adapter kami: command destruktif (`/stop`, `/resetsummary`)
tidak boleh open-access.

## 2. Kategori notifikasi (dari ~32 titik `self._notify(...)` di `engine.py`, digilir lewat `notify()` baris 665)

Bukan daftar lengkap baris-per-baris; dikelompokkan per jenis kejadian supaya bisa
dipetakan ke `EventBus` kami:

1. **Siklus hidup posisi**: `OPEN {arah} {symbol}` (entry terisi), `CLOSE ... via {alasan}`
   (TP/SL/manual), `TP1 HIT`, `TP diperpanjang` (trailing TP), `SL+` (milestone atau
   structural - profit dikunci via trailing).
2. **Kegagalan order/eksekusi**: entry order gagal, SL gagal terpasang -> force close
   darurat, TP1 gagal terpasang (retry), force close gagal (butuh cek manual).
3. **Posisi tak terduga**: `ORPHAN POSITION` terdeteksi (posisi ada, SL tak ada -> force
   close atau pasang SL darurat), `NAKED_RECOVERY_CLOSE` (tak bisa diproteksi saat
   recovery), posisi manual terdeteksi/konflik dengan sinyal bot/manual ditutup.
4. **Gerbang risiko/circuit breaker**: limit drawdown harian tercapai, limit jumlah
   trade harian tercapai, free-margin guard aktif, circuit breaker (N loss beruntun),
   pair blacklist sementara (M loss beruntun di satu pair).
5. **Housekeeping**: pembersihan order menggantung/zombie saat startup, koreksi PnL
   jurnal (settle telat dari exchange).
6. **Siklus hidup bot**: pesan startup ("LUX aktif, /help untuk command"), kill switch
   diaktifkan lalu dikonfirmasi selesai.
7. **Ringkasan terjadwal**: `daily_summary_loop()` (baris 681) - laporan 24 jam pada jam
   UTC tertentu (win rate, net PnL, fee), TIDAK dipicu oleh event.

## 3. Rencana adapter untuk modul kami (belum ditulis)

Bukan port langsung. Rancangan yang konsisten dengan arsitektur 6 lapis kami:

1. **`EventBus`** (baru, lapis independen, dipanggil dari `Pipeline`/`backtest_portofolio.py`
   /calon konektor live) - method `emit(jenis_event, payload)` murni in-process, tanpa
   dependensi Telegram. Jenis event minimal setara kategori 1, 3, 4, 6 di atas, memakai
   struktur data kami sendiri (`StrategyVerdict`, `PosisiTerbuka`, `SinyalTerlewat`,
   bukan `TradeState`/`journal` milik bot v8).
2. **Adapter Telegram tipis** (baru, di luar `lux_modul` inti - mengikuti pola plugin,
   BUKAN dependency wajib) - subscriber `EventBus` yang memformat pesan dan memanggil
   `bot.send_message`. Auth memakai model fail-closed yang sama dengan bot v8
   (`TG_ALLOWED_IDS` wajib; tanpa itu semua command ditolak).
3. **Command yang relevan untuk versi awal**: `/start`, `/help`, `/status`, `/balance`
   (baca `risiko.py`), `/positions` (baca `ManajerSlot`), `/risk` (tabel bagian 8.2),
   `/pause` / `/resume` (mode auto_entry global), `/export` (CSV dari ledger trade -
   ledger ini sendiri BELUM ada dan harus dibangun dulu).
4. **Command yang butuh keputusan operator dulu** (jangan diimplementasikan diam-diam):
   - `/stop` - kebijakan kill-switch modul kami harus konsisten dengan larangan market
     order (8.5); menutup paksa lewat market order bertentangan dengan aturan operator
     3 Agu 2026 kecuali operator menyetujui pengecualian.
   - `/setdailyloss`, `/setmaxspread`, `/limits` - modul kami belum punya gerbang
     drawdown harian / spread maksimum di `eksekusi/`; ini fitur BARU, bukan yang sudah
     ada dan tinggal dihubungkan.
   - `/takecontrol` - konsep "posisi manual di exchange" tidak dipetakan ke arsitektur
     kami (`ManajerSlot` hanya tahu posisi yang dibuka modul sendiri); butuh desain baru
     atau didrop.
5. **Ledger trade** untuk `/journal`, `/stats`, `/growth`, `/export` belum ada di modul
   kami sama sekali - saat ini hanya `kurva_ekuitas` ringkas dan `SinyalTerlewat` yang
   tercatat. Ini pekerjaan tersendiri sebelum command tersebut bisa diimplementasikan
   secara jujur (bukan menampilkan data kosong/placeholder).
6. **Testing**: adapter harus stub-tested (mock `bot.send_message`) tanpa kredensial
   Telegram nyata sampai operator menyediakan token bot terpisah untuk modul ini.

## 4. Yang SENGAJA tidak diadopsi dari bot v8

- Struktur `main.py`/`config.py`/`exchange.py` bot v8 (45 KB, 184 KB `engine.py`,
  banyak modul `lux/` internal) - terlalu besar dan tercampur logika strategi milik bot
  v8 sendiri (SMC Order Block + Liquidity Sweep + iFVG, sizing 2L+2S) yang TIDAK sama
  dengan arsitektur plugin 26-unit kami. Mengadopsi strukturnya berarti mewarisi
  tambal-sulam yang disebut operator sendiri.
- Fitur "LUX paper" (paper trading sintetis yang mengikuti saldo asli) di
  `daily_summary_loop` - di luar cakupan modul ini untuk saat ini.
- Multi-account (`ACCOUNTS`, `tg_user_id` per akun) - modul kami belum punya konsep
  multi-akun; ditunda sampai ada kebutuhan nyata.
