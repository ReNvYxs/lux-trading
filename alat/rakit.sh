#!/usr/bin/env bash
# Rakit isi repo secara reproducible dari sumber yang sudah diklon ter-pin SHA.
# Tidak ada salin-tempel manual: apa pun yang ada di repo ini dihasilkan skrip.
set -uo pipefail
mkdir -p bukti

if [ ! -d sumber_base/lux_modul ]; then
  echo "GAGAL: sumber_base belum ada; jalankan alat/klon.sh dulu"
  exit 3
fi

# 1) Salin pohon modul terbaru apa adanya.
#    .github SENGAJA dikecualikan supaya workflow milik repo sumber tidak ikut
#    aktif di sini (mereka menunjuk repo dan rahasia yang bukan milik kita).
#    reports/ dikecualikan karena itu artefak lama, bukan bagian modul.
(
  cd sumber_base && tar cf - \
    --exclude=./.git \
    --exclude=./.github \
    --exclude=./reports \
    --exclude=__pycache__ \
    .
) | tar xf - -C .
echo "salin pohon dasar rc=$?" | tee bukti/log_rakit.txt

# 2) Tambahkan lapisan eksekusi yang SUDAH terbukti di testnet (p07/p10/p11)
#    sebagai paket terpisah. Sengaja TIDAK menimpa lux_modul/eksekusi/:
#    penggantian harus dibuktikan tes lebih dulu, bukan diasumsikan.
mkdir -p lux_modul/eksekusi_aman
if [ -f sumber_fix/modul/bersih/inti.py ]; then
  cp sumber_fix/modul/bersih/inti.py lux_modul/eksekusi_aman/inti.py
  echo "salin inti.py OK" | tee -a bukti/log_rakit.txt
else
  echo "PERINGATAN: inti.py tidak ditemukan" | tee -a bukti/log_rakit.txt
fi
if [ -f sumber_fix/modul/proteksi.py ]; then
  cp sumber_fix/modul/proteksi.py lux_modul/eksekusi_aman/proteksi.py
  echo "salin proteksi.py OK" | tee -a bukti/log_rakit.txt
else
  echo "PERINGATAN: proteksi.py tidak ditemukan" | tee -a bukti/log_rakit.txt
fi
printf '%s\n' '"""Lapisan eksekusi yang sudah divalidasi di Binance Testnet (p07/p10/p11).' '' 'Belum dipasang menggantikan lux_modul/eksekusi/. Penggantian menunggu bukti tes.' '"""' > lux_modul/eksekusi_aman/__init__.py

# 3) Manifest supaya isi repo bisa diaudit tanpa membuka satu per satu.
{
  echo "utc=$(date -u +%FT%TZ)"
  echo "base_ref=${BASE_REF}"
  echo "fix_ref=${FIX_REF}"
  echo "--- jumlah berkas ---"
  echo "py_lux_modul=$(find lux_modul -name '*.py' | wc -l)"
  echo "py_tests=$(find tests -name '*.py' 2>/dev/null | wc -l)"
  echo "py_scripts=$(find scripts -name '*.py' 2>/dev/null | wc -l)"
  echo "py_tools=$(find tools -name '*.py' 2>/dev/null | wc -l)"
  echo "--- akar ---"
  ls -1
  echo "--- md5 seluruh .py ---"
  find . -name '*.py' -not -path './sumber_base/*' -not -path './sumber_fix/*' -print0 \
    | sort -z | xargs -0 md5sum
} > bukti/manifest_rakit.txt 2>&1
echo "manifest baris=$(wc -l < bukti/manifest_rakit.txt)" | tee -a bukti/log_rakit.txt
