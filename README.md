# lux-trading

Modul trading LUX versi gabungan. **Seluruh isi repo ini dihasilkan oleh skrip**
(`alat/`) lewat GitHub Actions, bukan salin-tempel manual, supaya asal-usul tiap
berkas bisa ditelusuri dan dirakit ulang.

## Asal bahan

| Bagian | Sumber | Pin |
| --- | --- | --- |
| Pohon modul, tes, skrip, dokumen | `EnVyxS/lux-modul-trading` | `8401b2327736a4cc5c588d211eb6911dde0842da` |
| `lux_modul/eksekusi_aman/` | `EnVyxS/uji-trading` | `c1749202dc31be1f995485dfc5c549c077338ecf` |

Dikecualikan dari salinan: `.github/` (workflow repo sumber menunjuk repo dan
rahasia yang bukan milik repo ini) dan `reports/` (artefak lama, bukan modul).

## Kenapa pohon dasarnya `main`, bukan `final`

Karena `main` terbukti benar pada titik yang membedakan keduanya. Docstring
`strategi/level_harga.py` di `main` mencatat sendiri bahwa versi lama mematok
`_bar_per_hari` ke 24 untuk semua timeframe selain 5m dan 15m, sehingga jendela
pivot salah tanpa satu pun pesan galat. A/B 95 pair pada `single_4h` mengukur
dampaknya: PnL bersih `+539,0089` (perilaku `main`) versus `-905,8863`
(perilaku `final`) - selisih `1444,8952` USD dan berganti tanda, dan `95,2%`
dari selisih itu berasal dari `pivot_reversal`, satu-satunya pemanggil fungsi
tersebut. Jadi mempertahankan `main` bukan perubahan strategi, melainkan menolak
regresi yang sudah diukur.

## `lux_modul/eksekusi_aman/`

Lapisan eksekusi yang sudah divalidasi langsung di Binance Testnet (probe
p07/p10/p11): pengiriman order idempoten lewat `newClientOrderId` deterministik,
pemulihan lewat CID, penanganan `-2013`, dan penjaga proteksi yang menutup posisi
bila TP/SL gagal terpasang.

Lapisan ini **belum** menggantikan `lux_modul/eksekusi/`. Penggantian menunggu
bukti tes regresi, bukan asumsi.

## Status

Repo ini sedang dirakit bertahap. Lihat `bukti/` untuk log mentah tiap langkah:
manifest berkas, diff terhadap sumber, hasil impor, dan baseline `pytest`.
