# Audit Mesin Eksekusi Order

**Ruang lingkup:** mesin trading, yaitu segala hal yang mengirim order dan
menggerakkan dana di pasar. **Bukan** strategi dan bukan logika sinyal.

**Metode:** hipotesis -> pengujian -> bukti -> akar masalah -> perbaikan -> uji
regresi -> validasi ulang. Tidak ada perbaikan yang dimasukkan karena "terlihat
benar". Setiap keputusan menyebut nomor buktinya (p01-p13 = probe testnet nyata,
dok = dokumentasi resmi Binance).

---

## 0. Ringkasan status

| bagian eksekusi | status |
|---|---|
| Limit entry | diperbaiki, diuji injeksi galat |
| Take Profit | LIMIT reduceOnly pasif di bursa, diverifikasi terlihat di openOrders |
| Stop Loss | SL perangkat lunak + fallback MARKET wajib; tipe stop bursa ditolak `-4120` |
| Cancel | pembatalan diverifikasi lewat openOrders, bukan lewat respons |
| Modify | `ubah_order` (PUT) ditambahkan; **belum diverifikasi hidup** |
| Logging | JSONL terstruktur di satu choke point REST |
| Fail-safe | tiga keadaan: berhasil / gagal / **TIDAK DIKETAHUI** |
| Base 0,20 per setup | tersambung ke siklus untuk saldo < 20 USDT |

---

## 1. Temuan audit dan perbaikannya

### 1.1 Klien REST - `lux_modul/eksekusi/binance_client.py`

| id | temuan | perbaikan |
|---|---|---|
| A1 | nol logging: tidak ada request/response yang tercatat | `jejak.py` dipasang di `_permintaan` |
| A2 | `kirim_order` mengembalikan respons mentah tanpa konfirmasi; `if not mentah: return {}` | `konfirmasi_order` wajib dilewati |
| A3 | tidak ada retry/backoff di dalam `_permintaan` | backoff eksponensial dikelola pemanggil sesuai klasifikasi |
| A4 | timeout pada `kirim_order` = keadaan TIDAK DIKETAHUI, tetapi diperlakukan gagal | dipetakan ke `TAK_DIKETAHUI` + wajib rekonsiliasi |
| A5 | timeout baca lolos sebagai `TimeoutError` mentah | `except (URLError, TimeoutError, OSError)` |
| A6 | tidak ada modify/amend order | `ubah_order()` ditambahkan |
| A7 | tidak ada metode `openOrders` | `order_terbuka()` ditambahkan |
| A8 | `-1021` tidak memicu sinkron waktu; `Retry-After` diabaikan | sinkron waktu dipanggil sebelum percobaan ulang |
| A9 | `format_nilai` sudah benar | dipertahankan apa adanya |

### 1.2 Pengirim order dan proteksi - `lux_modul/eksekusi_aman/inti.py`

| id | temuan | perbaikan |
|---|---|---|
| B1 | `kirim` tidak pernah memeriksa respons; dict kosong dianggap sukses | wajib `konfirmasi_order`, hasil baru `TIDAK_TERKONFIRMASI` |
| B2 | retry pada semua galat non-permanen, termasuk pembatasan laju | laju dan status tak diketahui **berhenti tanpa ulang** |
| B3 | `KODE_PERMANEN` hanya 9 kode; `-2019`, `-4164` ikut diulang sia-sia | satu sumber di `klasifikasi.py`, 25 kode |
| B4 | `baca_status` berhenti pada galat non `-2013` apa pun | hanya galat permanen/kredensial yang menghentikan |
| B5 | `batalkan_proteksi` menelan galat lalu mengosongkan state lokal | hasil dikembalikan, dikonfirmasi, lalu **diverifikasi ulang** |
| B6 | `hitung_ukuran` menolak saldo mikro (`TolakUkuran`) | jalur `ukuran_mikro` tersambung untuk saldo < 20 |
| B7 | `periksa_sl` diam-diam melewati siklus saat harga gagal dibaca | dihitung; 3x buta berturut-turut -> posisi ditutup |
| B8 | `rekonsiliasi` mendeteksi masalah tetapi tidak ada yang bertindak | `posisi_tanpa_proteksi` dan `orphan_proteksi` ditindak |
| B9 | `order_terbuka` tanpa jaminan bentuk -> `AttributeError` di jalur proteksi | bentuk dijamin daftar objek |

### 1.3 Eksekusi slice - `lux_modul/eksekusi/ice_breaker.py`

| id | temuan | perbaikan |
|---|---|---|
| C1 | `qty_terisi += s.qty` tanpa melihat respons sama sekali | qty hanya dari `executedQty` jawaban bursa |
| C2 | payload mengirim `visible_qty` + `icebergQty` (parameter hantu) | dihapus; keduanya ikut ditandatangani -> risiko `-1104` |
| C3 | tidak ada rollback saat satu slice gagal | sisa slice dibatalkan, alasan dicatat |
| C4 | entry memakai `GTX` yang terbukti ditolak `-5022` (p08) | tidak dipakai untuk entry |
| C5 | tanpa `newClientOrderId` | cid deterministik SHA1 per slice |

**Catatan penting soal C2.** Uji lama justru MENUNTUT kedua parameter hantu itu
dikirim (`test_visible_qty_benar_benar_dikirim`, docstring `BUG LAMA 1`). Setelah
perbaikan, 5 uji lama menjadi merah. Diperiksa satu per satu: itu bukan regresi,
melainkan uji yang mengunci bug. Buktinya tegas - 310 uji LULUS pada kode belum
ditambal, dan 310 uji yang sama memberi 305 lulus / 5 gagal pada kode sudah
ditambal. Yang diperbaiki adalah asersi dan jawaban bursa palsunya, **bukan**
konfirmasinya. Melemahkan `konfirmasi_order` agar uji hijau akan mengembalikan
cacat C1.

---

## 2. Logging yang bisa ditelusuri

`lux_modul/eksekusi/jejak.py` menulis JSONL di satu choke point REST. Satu
`korelasi` menyatukan baris request, response, dan error untuk satu perintah.

- Jalur dana (`/fapi/v1/order`, `batchOrders`, `leverage`, `positionRisk`, ...)
  dicatat **utuh**; jalur data pasar hanya diringkas bentuknya.
- Rahasia diredaksi, tetapi **nama kuncinya dipertahankan** - supaya perubahan
  parameter API tetap terlihat tanpa membocorkan nilainya.
- `-2010` adalah keranjang serbaguna yang alasan sebenarnya ada di `msg`, jadi
  `msg` dicatat penuh. Tanpa itu `-2010` tidak bisa didiagnosis (dok).
- Perekam **tidak pernah melempar galat**; kegagalan tulis hanya dihitung di
  `gagal_tulis`. Logging tidak boleh menjatuhkan mesin.

Enam informasi yang diminta selalu tersedia saat eksekusi gagal:

| yang diminta | tempatnya |
|---|---|
| 1. proses apa yang gagal | `niat` (`entry`, `tp`, `tutupioc`, `tutupmkt`) + `peristiwa` |
| 2. penyebab / error | `Keputusan.kelas` + `kode` + `alasan` |
| 3. request/parameter | baris `permintaan` (jalur dana dicatat utuh) |
| 4. response API | baris `jawaban` / `galat` |
| 5. dampak ke posisi/order | `dampak`, `masalah`, `order_yatim`, `bersih` |
| 6. bagian yang perlu diperbaiki | `perlu_diperbaiki` |

---

## 3. Fail-safe: tiga keadaan, bukan dua

Kode lama hanya mengenal berhasil dan gagal, sehingga timeout dipetakan ke gagal
- padahal itu keadaan paling berbahaya. Dokumentasi Binance sendiri menyatakan
HTTP 503 varian A berarti permintaan diterima tanpa jawaban dan **eksekusi
mungkin BERHASIL** (dok). `nautilus_trader` memakai kebijakan yang sama: kirim
sekali, jangan pernah ulang buta, selesaikan keraguan lewat rekonsiliasi, dan
jangan pernah memancarkan penolakan palsu.

| keadaan | boleh ulang | wajib rekonsiliasi |
|---|---|---|
| permanen (`-2019`, `-4164`, `-4120`, `-5022`, ...) | tidak | tidak |
| sementara (`-1001`, `-1008`, `-1016`) | hanya jalur baca | ya bila jalur tulis dana |
| laju (`-1003`, `-1015`, HTTP 418/429) | **tidak** | ya |
| waktu (`-1021`) | ya, setelah sinkron waktu | ya |
| tak diketahui (`-1000`, `-1006`, `-1007`, HTTP 503, tanpa jawaban) | **tidak** | ya |
| duplikat (`-4116`) | tidak - artinya yang pertama SUDAH sampai | ya |

**Aturan bawaan yang menentukan:** kode yang tidak ada di tabel mana pun, pada
jalur TULIS ke endpoint dana, diklasifikasikan **TAK_DIKETAHUI**. Tabel ini pasti
akan ketinggalan zaman; yang tidak boleh ketinggalan zaman adalah sikap amannya.

---

## 4. Base 0,20 USDT per setup (saldo < 20 USDT)

Yang bisa dikendalikan sampai 0,20 USDT adalah **initial margin**, bukan
notional - karena Binance memasang minimum notional dan minQty per simbol.

    notional = margin x leverage  ->  leverage = notional_minimum / 0,20

| kasus | hasil |
|---|---|
| minNotional 5 | leverage 25, margin **tepat 0,20** - layak |
| minNotional 100 | butuh leverage 500 > batas 125; termurah **0,80** - dilaporkan jujur |
| BTCUSDT nyata (minNotional 50, harga 64.536,4) | qty 0,0008, margin 0,413 |

**Pembulatan sengaja dibalik.** Sizing risiko membulatkan qty ke BAWAH agar tidak
melewati batas risiko; jalur mikro membulatkan ke ATAS agar mencapai minimum
bursa. Membulatkan ke bawah di sini menghasilkan order yang pasti ditolak
`-4164`. Dua arah itu dipisah ke dua fungsi berbeda supaya tidak pernah tertukar.

**Bahaya yang wajib disebut.** Base 0,20 mengatur MARGIN, bukan RISIKO. Pada
BTCUSDT nyata dengan saldo 10 USDT dan SL 1%, ruginya 0,516 USDT = **5,16% modal**
- di atas batas 5%. Mesin **menolak** setup itu, bukan meloloskannya diam-diam.
Demikian pula bila jarak likuidasi (~100/leverage %) lebih dekat daripada SL.

Jalur ini juga **wajib memasang leverage**. Bila `atur_leverage` gagal, seluruh
angka margin dan likuidasi tidak berlaku, jadi setup dibatalkan **sebelum satu
order pun dikirim**.

---

## 5. Hasil stress test

Semua dijalankan di GitHub Actions, bukan sandbox. Bukti: `bukti/ci/` dan
`bukti/mesin/`.

| gerbang | commit ci-bot | hasil |
|---|---|---|
| sebelum pengerasan | `2ec26e93` | 310 lulus / 0 gagal |
| + lapis 3 dan 2a | `b1f52369` | 349 lulus / 0 gagal |
| + lapis 2b | `ec7fbad4` | 368 lulus / 0 gagal |

Skenario yang diinjeksikan:

- **Keadaan tak diketahui:** timeout POST order, timeout tetapi order ternyata
  sampai (pulih lewat cid), HTTP 503.
- **Jawaban tidak lengkap:** badan kosong `{}`, tanpa `status`, status tidak
  dikenal, simbol/sisi tidak cocok.
- **Penolakan bursa:** `-4116` duplikat, `-2019` margin, `-4164` notional,
  `-4120` tipe order, `429/-1003` laju, `-1021` timestamp.
- **Pembacaan status:** `-2013` ditoleransi, galat sementara tetap dicoba,
  galat permanen berhenti cepat.
- **Proteksi:** pembatalan gagal `-2011` melaporkan order yatim, bentuk jawaban
  pembatalan salah ditolak, `openOrders` berbentuk objek tidak lagi menjatuhkan
  jalur proteksi.
- **SL perangkat lunak:** harga buta 3x berturut-turut memicu penutupan,
  penghitung direset saat harga terbaca, SL tersentuh dengan penutupan terbukti,
  dan SL tersentuh dengan penutupan GAGAL dilaporkan keras (`sl_gagal_menutup`,
  fallback MARKET tercatat di jejak).
- **Rekonsiliasi:** `posisi_tanpa_proteksi`, `orphan_proteksi`,
  `ukuran_proteksi_tidak_cocok`, `sl_tidak_dipantau`.
- **Siklus penuh:** TP ditolak -> posisi ditutup; TP OK tetapi tidak terlihat di
  bursa -> posisi ditutup; galat tak terduga setelah fill -> posisi tetap
  ditutup (jaring pengaman p10).
- **Base 0,20:** tercapai, tidak mungkin (dilaporkan jujur), ditolak karena
  risiko, ditolak karena likuidasi, `maxQty`, ambang 20 USDT persis.

---

## 6. Masalah yang MASIH terbuka

Sesuai permintaan, ini dilaporkan apa adanya dan **belum** dinyatakan selesai.

1. **`Modify` belum diverifikasi hidup.** `ubah_order` (PUT) sudah ada dan
   terkompilasi, tetapi belum pernah diadu dengan bursa sungguhan.
2. **Jendela mati proses.** SL perangkat lunak hidup di dalam proses. Bila proses
   mati, SL mati bersamanya sampai `_pulihkan_proteksi_aman()` jalan lagi.
   Jendela ini tidak bisa dihilangkan lewat REST dan wajib masuk runbook mainnet.
3. **Divergensi mainnet vs testnet.** `/sapi/v1/algo/futures/*` terbukti TIDAK
   ADA di testnet (p09), padahal `-4120` menyuruh memakainya. Di mainnet endpoint
   itu mungkin ada, sehingga stop di bursa mungkin bisa dipakai. Saklar
   `otomatis` memutuskan dari jawaban bursa dan gagal ke sisi aman.
4. **Rate limit belum dikerjakan.** WebSocket kline/markPrice dan user-data
   stream belum menggantikan polling; cache `klines(start_time=...)` masih
   terlewat.

---

## 7. Cara mereproduksi

```
.github/workflows/mesin.yml   penambal + kompilasi + pytest -> bukti/mesin/
.github/workflows/ci.yml      gerbang regresi          -> bukti/ci/
.github/workflows/hidup.yml   uji hidup di testnet     -> bukti/live/
```

Setiap penambal berbasis jangkar: jumlah jangkar dideklarasikan dan diperiksa,
hasilnya dikompilasi sebelum ditulis, dan idempoten lewat penanda. Bila satu
jangkar tidak cocok, seluruh penambalan berhenti dengan rc bukan nol.
