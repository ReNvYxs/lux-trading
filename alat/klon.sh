#!/usr/bin/env bash
# Klon anonim ter-pin SHA ke LUAR worktree.
#
# Dua jebakan yang sudah terbukti dan dicegah di sini:
#
# 1) Klon di DALAM worktree membuat .git/ bersarang, sehingga `git add -A`
#    mendaftarkannya sebagai gitlink submodule: isinya tidak ikut, tapi entri
#    submodule rusak tertinggal di pohon.
#
# 2) Menulis skema dan host bersebelahan sebagai literal di dalam berkas bisa
#    berubah jadi placeholder saat berkas dikirim ke GitHub. Itu benar-benar
#    terjadi dan menghasilkan:
#      fatal: protocol '{{https' is not supported
#    Karena itu URL dirakit dari potongan, dan ada tripwire di bawah supaya
#    kegagalan serupa berteriak, bukan lolos diam-diam.
set -uo pipefail
export GIT_TERMINAL_PROMPT=0
SKEMA="https"
HOST="github.com"
mkdir -p bukti

klon () {
  repo="$1"; ref="$2"; dir="$3"
  asal="${SKEMA}://${HOST}/${repo}.git"
  case "$asal" in
    *"{"*|*"}"*)
      echo "GAGAL: URL asal tercemar placeholder -> ${asal}"
      return 9
      ;;
  esac
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
  echo "skema=${SKEMA} host=${HOST}"
  echo "tujuan_base=${SUMBER_BASE}"
  echo "tujuan_fix=${SUMBER_FIX}"
  klon "$BASE_REPO" "$BASE_REF" "$SUMBER_BASE"
  klon "$FIX_REPO" "$FIX_REF" "$SUMBER_FIX"
} 2>&1 | tee bukti/jejak_klon.txt

if [ ! -d "${SUMBER_BASE}/lux_modul" ]; then
  echo "GAGAL: sumber base tanpa lux_modul/" | tee -a bukti/jejak_klon.txt
  exit 3
fi
if [ ! -d "${SUMBER_FIX}/modul/main/lux_modul" ]; then
  echo "CATATAN: sumber fix tanpa modul/main/lux_modul/" | tee -a bukti/jejak_klon.txt
fi

{
  echo "--- akar sumber base ---"
  ls -1 "$SUMBER_BASE"
  echo "--- sumber fix/modul ---"
  ls -1 "${SUMBER_FIX}/modul" 2>/dev/null
} 2>&1 | tee -a bukti/jejak_klon.txt
