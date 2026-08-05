#!/usr/bin/env bash
# Klon anonim ter-pin SHA. Tidak memakai PAT: kedua repo sumber publik.
# Host dirakit dari variabel supaya tidak ada URL literal di dalam berkas.
set -uo pipefail
export GIT_TERMINAL_PROMPT=0
HOST="github.com"
mkdir -p bukti

klon () {
  repo="$1"; ref="$2"; dir="$3"
  asal="https://${HOST}/${repo}.git"
  rm -rf "$dir"
  mkdir -p "$dir"
  (
    cd "$dir" || exit 3
    git init -q
    git remote add origin "$asal"
    if git fetch -q --depth 1 origin "$ref"; then
      git checkout -q FETCH_HEAD
      echo "OK ${repo}@${ref} -> ${dir}"
    else
      echo "fetch dangkal gagal, coba klon penuh: ${repo}"
      cd ..
      rm -rf "$dir"
      git clone -q "$asal" "$dir" || exit 3
      cd "$dir" || exit 3
      git checkout -q "$ref" || exit 4
      echo "OK-penuh ${repo}@${ref} -> ${dir}"
    fi
  )
}

{
  echo "utc=$(date -u +%FT%TZ)"
  klon "$BASE_REPO" "$BASE_REF" sumber_base
  klon "$FIX_REPO" "$FIX_REF" sumber_fix
} 2>&1 | tee bukti/log_klon.txt

if [ ! -d sumber_base/lux_modul ]; then
  echo "GAGAL: sumber_base tanpa lux_modul/" | tee -a bukti/log_klon.txt
  exit 3
fi
if [ ! -d sumber_fix/modul/main/lux_modul ]; then
  echo "PERINGATAN: sumber_fix tanpa modul/main/lux_modul/" | tee -a bukti/log_klon.txt
fi

{
  echo "--- akar sumber_base ---"
  ls -1 sumber_base
  echo "--- sumber_fix/modul ---"
  ls -1 sumber_fix/modul 2>/dev/null
  echo "--- sumber_fix/modul/bersih ---"
  ls -1 sumber_fix/modul/bersih 2>/dev/null
} 2>&1 | tee -a bukti/log_klon.txt
