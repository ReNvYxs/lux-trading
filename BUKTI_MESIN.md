# Buku Bukti Mesin Eksekusi

Analisisnya ada di [`AUDIT_MESIN.md`](AUDIT_MESIN.md). Berkas ini hanya berisi
**hasil pengukuran yang dapat diverifikasi**: commit, angka, dan berkas bukti.
Semua dijalankan di GitHub Actions terhadap Binance Futures Testnet sungguhan,
bukan di sandbox.

---

## 1. Uji hidup Cancel dan Modify - LULUS

Commit bukti: `mesin-hidup-bot 557d6613` - berkas
`bukti/live/jejak_mesin_hidup.txt` dan `bukti/live/MESIN_HIDUP.json`.
Dijalankan `alat/uji_hidup_mesin.py` lewat workflow `mesin_hidup.yml`.

Sengaja TIDAK membuka posisi: order uji adalah LIMIT BUY pasif 5% di bawah pasar,
sehingga yang diuji murni siklus hidup order, bukan strategi.

| yang diuji | hasil nyata |
|---|---|
| harga pasar saat uji | BTCUSDT `78878.1`, saldo `4179.81481529` USDT |
| Limit entry | `orderId 28554851344`, cid `lxujimesin87616962`, status `NEW`, qty `0.0016` @ `74934.2` |
| terkonfirmasi bursa | ya - lewat `konfirmasi_order`, bukan sekadar respons diterima |
| terlihat di openOrders | ya - `order_terbuka` mengembalikan `[28554851344]` |
| **Modify (PUT)** | harga `74934.2` -> `74145.4`, qty `0.0016` -> `0.0017` |
| Modify diverifikasi ulang | ya - `status_order` membalas `price 74145.40`, `origQty 0.0017` |
| orderId setelah amend | **TIDAK berubah** (`28554851344`) - fakta yang sebelumnya tidak diketahui |
| Cancel | respons `status CANCELED`, lolos `konfirmasi_batal` |
| Cancel diverifikasi hilang | ya - `openOrders` menjadi `[]` |
| Cancel ulang (jalur gagal) | `-2011 Unknown order sent.` -> kelas `tidak_ada`, `boleh_ulang false`, `wajib_rekonsiliasi true` |
| Modify setelah batal (jalur gagal) | `-2013 Order does not exist.` -> kelas `tidak_ada`, `boleh_ulang false` |
| jejak JSONL | `bukti/jejak/jejak-20260825.jsonl`, 26 baris, 12619 byte, `gagal_tulis 0` |
| hitungan jejak | permintaan 13, jawaban 11, galat 2 |
| posisi tersisa di akhir | `0.0` (`bersih_akhir true`) |

**Ini menutup satu-satunya jalur eksekusi yang sebelumnya belum pernah diadu
dengan bursa.** `ubah_order` ditulis dari dokumentasi dan sampai run ini belum
pernah dijalankan sekali pun.

Catatan penting: nilai `price` dan `origQty` diambil dari `status_order`, BUKAN
dari respons PUT-nya sendiri. Kalau nanti Binance mengubah bentuk respons PUT,
uji ini tetap valid karena kebenarannya diukur dari keadaan order di bursa.

---

## 2. Peta kelayakan base 0,20 USDT - seluruh bursa

Commit bukti: `mikro-bot 30c10488` - berkas `bukti/mikro/jejak_mikro.txt` dan
`bukti/mikro/PETA_MIKRO.json`. Dijalankan `alat/peta_mikro.py`.

Diukur pada saldo uji **19 USDT** dengan SL **1,0%**, memakai `exchangeInfo` dan
`leverageBracket` asli. Biaya hanya 3 permintaan REST untuk 527 pair (tidak ada
panggilan per simbol), jadi pengukuran ini tidak menambah risiko rate-limit.

| ukuran | nilai |
|---|---|
| simbol di exchangeInfo | 733 |
| dievaluasi (USDT PERPETUAL TRADING) | **527** |
| dilewati | 133 bukan TRADING, 42 bukan USDT, 31 bukan PERPETUAL |
| galat spek / galat rencana | **0 / 0** |
| base 0,20 benar-benar tercapai | **382** |
| layak penuh (lolos risiko + likuidasi) | **525 / 527** |
| layak DAN base tercapai | **382** |
| tidak layak | **2**, keduanya karena likuidasi lebih dekat daripada SL |

Simbol termurah (identik karena semuanya dibatasi minNotional 5,0):

| simbol | minNotional | qty | notional | leverage | margin | risiko% | jarak likuidasi% |
|---|---|---|---|---|---|---|---|
| 1000WHYUSDT | 5,0 | 2777778 | 5,0 | 26 | **0,192308** | 0,2632 | 3,8462 |
| DOGSUSDT | 5,0 | 125282 | 5,0 | 26 | 0,192308 | 0,2632 | 3,8462 |
| 1000SATSUSDT | 5,0 | 409837 | 5,0 | 26 | 0,192308 | 0,2632 | 3,8462 |
| OPUSDT | 5,0 | 46,6 | 5,0002 | 26 | 0,192315 | 0,2632 | 3,8462 |

Perhatikan leverage yang dipilih adalah **26**, bukan 125. Mesin memakai leverage
sekecil mungkin yang masih mencapai base, sehingga jarak likuidasi tetap lebar
(3,85%) dan risiko nyata hanya 0,26% dari modal.

### Temuan yang harus disampaikan apa adanya

**Pada BTCUSDT base 0,20 TIDAK tercapai, dan itu bukan bug.** minNotional 50
dibagi leverage maksimum 125 sudah memberi margin 0,40; setelah qty dibulatkan ke
atas menjadi `0,4417`. Pada harga `78878.1` mesin **menolak** setup BTCUSDT:

| saldo | qty | notional | leverage | margin | risiko | vonis |
|---|---|---|---|---|---|---|
| 10 USDT | 0,0007 | 55,21467 | 125 | 0,4417 | **5,5215%** | DITOLAK - di atas batas 5% |
| 19 USDT | 0,0007 | 55,21467 | 125 | 0,4417 | 2,906% | DITOLAK - likuidasi 0,8% lebih dekat dari SL 1,0% |

Jadi janji base 0,20 berlaku pada 382 simbol, tetapi **tidak** pada simbol
bernotional-minimum tinggi seperti BTCUSDT. Mesin melaporkannya jujur dan
melewati setup, bukan memaksakan ukuran yang melanggar batas risiko.

---

## 3. Riwayat gerbang regresi

| gerbang | commit | pytest |
|---|---|---|
| sebelum pengerasan | `2ec26e93` | 310 lulus / 0 gagal |
| + stress lapis 3 dan 2a | `b1f52369` | 349 / 0 |
| + stress lapis 2b | `ec7fbad4` | 368 / 0 |
| + stress lapis 3b (jalur mikro tersambung) | `18c20ec9` | **373 / 0** |
| lantai gerbang dinaikkan ke 373 | `33cb896d` | 373 / 0, `GERBANG=LULUS` |

`CI_MIN_PYTEST` kini `373`, jadi uji yang hilang atau dilewati akan menjatuhkan
gerbang - bukan lewat diam-diam.

Penambal mesin (`mesin-bot 8d977d6e`) hijau seluruhnya dan **idempoten**:
`rc_mesin`, `rc_inti`, `rc_proteksi`, `rc_ib`, `rc_mikro`, `rc_tes_order`,
`rc_tes_inti`, `rc_kompilasi`, `rc_pytest` semuanya `0`.

---

## 4. Masalah mesin yang masih terbuka

1. **Cacat logging yang baru ditemukan di run ini.** Jawaban REST bertipe
   **daftar** - `/fapi/v2/balance`, `/fapi/v2/positionRisk`, `/fapi/v1/openOrders`
   - tercatat di jejak sebagai `tak_terserialisasi` berisi `repr` Python
   (`'marginAvailable': True`, kutip tunggal), bukan ringkasan terstruktur.
   Isinya tetap terbaca dan terpotong aman, tetapi justru tiga endpoint itulah
   yang paling perlu terbaca rapi ketika API berubah. **Belum diperbaiki.**
2. **Jendela mati proses.** SL perangkat lunak hidup di dalam proses; bila proses
   mati, SL mati bersamanya sampai pemulihan berjalan. Tidak bisa dihilangkan
   lewat REST. Wajib masuk runbook mainnet.
3. **Divergensi mainnet.** `/sapi/v1/algo/futures/*` terbukti tidak ada di
   testnet, padahal `-4120` menyuruh memakainya. Perilaku mainnet belum diukur.
4. **Rate limit.** WebSocket belum menggantikan polling; cache `klines` dengan
   `start_time` masih dilewati dengan sengaja.
5. **Jahitan entry.** Entry hidup masih lewat `IceBreakerExecutor`; lapisan
   `eksekusi_aman.Entry` sudah teruji tetapi belum menjadi jalur bawaan.
