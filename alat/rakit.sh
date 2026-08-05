#!/usr/bin/env bash
# Rakit isi repo secara reproducible dari sumber yang sudah diklon ter-pin SHA.
set -uo pipefail
mkdir -p bukti

if [ ! -d "${SUMBER_BASE}/lux_modul" ]; then
  echo "GAGAL: sumber base belum ada; jalankan alat/klon.sh dulu"
  exit 3
fi

# 1) Salin pohon modul terbaru apa adanya.
#    .github dikecualikan supaya workflow repo sumber tidak ikut aktif di sini
#    (mereka menunjuk repo dan rahasia yang bukan milik repo ini).
#    reports/ dikecualikan karena artefak lama, bukan bagian modul.
(
  cd "$SUMBER_BASE" && tar cf - \
    --exclude=./.git \
    --exclude=./.github \
    --exclude=./reports \
    --exclude=__pycache__ \
    .
) | tar xf - -C .
echo "salin pohon dasar selesai" | tee bukti/jejak_rakit.txt

# 2) Salinan itu MENIMPA .gitignore repo ini. Aturan milik repo rakitan harus
#    dipasang ulang tiap run - kalau tidak, artefak klon dan cache pytest ikut
#    ter-commit. Ini sudah pernah terjadi, jadi ditangani eksplisit.
{
  echo ""
  echo "# --- tambahan repo rakitan, dipasang ulang oleh alat/rakit.sh ---"
  echo ".pytest_cache/"
  echo "sumber_base/"
  echo "sumber_fix/"
} >> .gitignore

# 3) Lapisan eksekusi yang SUDAH terbukti di testnet (p07/p10/p11), sebagai
#    paket terpisah. Sengaja TIDAK menimpa lux_modul/eksekusi/: penggantian
#    harus dibuktikan tes lebih dulu.
mkdir -p lux_modul/eksekusi_aman
for pasangan in "modul/bersih/inti.py:inti.py" "modul/proteksi.py:proteksi.py"; do
  asal="${SUMBER_FIX}/${pasangan%%:*}"
  tujuan="lux_modul/eksekusi_aman/${pasangan##*:}"
  if [ -f "$asal" ]; then
    cp "$asal" "$tujuan"
    echo "salin ${tujuan} OK" | tee -a bukti/jejak_rakit.txt
  else
    echo "PERINGATAN: ${asal} tidak ada" | tee -a bukti/jejak_rakit.txt
  fi
done
printf '%s\n' \
  '"""Lapisan eksekusi yang sudah divalidasi di Binance Testnet (p07/p10/p11).' \
  '' \
  'Belum dipasang menggantikan lux_modul/eksekusi/. Penggantian menunggu bukti tes.' \
  '"""' > lux_modul/eksekusi_aman/__init__.py

# 4) Catat jebakan .gitignore milik repo sumber.
{
  echo "utc=$(date -u +%FT%TZ)"
  echo "pola .gitignore bawaan repo sumber yang pernah menelan artefak:"
  grep -nE 'log_|dataset_masuk|reports/|\*\.zip' .gitignore 2>/dev/null
  echo
  echo "penanganan: aturan repo rakitan dipasang ulang di atas, dan langkah"
  echo "rekam memakai git add -A -f pada bukti/ dan dataset_masuk/"
} > bukti/CATATAN_GITIGNORE.txt 2>&1

# 5) Manifest supaya isi repo bisa diaudit tanpa membuka satu per satu.
{
  echo "utc=$(date -u +%FT%TZ)"
  echo "base_ref=${BASE_REF}"
  echo "fix_ref=${FIX_REF}"
  echo "--- jumlah berkas ---"
  echo "py_lux_modul=$(find lux_modul -name '*.py' | wc -l)"
  echo "py_tests=$(find tests -name '*.py' 2>/dev/null | wc -l)"
  echo "py_scripts=$(find scripts -name '*.py' 2>/dev/null | wc -l)"
  echo "py_tools=$(find tools -name '*.py' 2>/dev/null | wc -l)"
  echo "berkas_dataset_masuk=$(find dataset_masuk -type f 2>/dev/null | wc -l)"
  echo "--- akar ---"
  ls -1
  echo "--- md5 seluruh .py ---"
  find . -name '*.py' -not -path './.pytest_cache/*' -print0 | sort -z | xargs -0 md5sum
} > bukti/manifest_rakit.txt 2>&1
echo "manifest baris=$(wc -l < bukti/manifest_rakit.txt)" | tee -a bukti/jejak_rakit.txt
