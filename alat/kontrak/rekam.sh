#!/usr/bin/env bash
set -u
LABEL="${1:-hasil}"
git config user.name "kontrak-bot"
git config user.email "kontrak-bot@users.noreply.github.com"
git add -A -f bukti
if git diff --cached --quiet; then
  echo "tidak ada perubahan untuk direkam"
  exit 0
fi
git commit -m "[kontrak] ${LABEL} ${GITHUB_SHA} [skip ci]"
for i in 1 2 3 4 5; do
  if git pull --rebase --autostash origin main && git push origin HEAD:main; then
    echo "rekam OK percobaan $i"
    exit 0
  fi
  sleep 5
done
echo "rekam GAGAL"
exit 1
