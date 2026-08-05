#!/usr/bin/env bash
set -u
LABEL="${1:-hasil}"
git config user.name "teori-bot"
git config user.email "teori-bot@users.noreply.github.com"
git add -A -f bukti
if git diff --cached --quiet; then
  echo "tidak ada perubahan untuk direkam"
  exit 0
fi
git commit -m "[teori3] $LABEL $GITHUB_SHA [skip ci]"
for n in 1 2 3 4 5; do
  if git pull --rebase origin "$GITHUB_REF_NAME" && git push origin "HEAD:$GITHUB_REF_NAME"; then
    echo "terekam pada percobaan $n"
    exit 0
  fi
  sleep 3
done
echo "gagal merekam"
exit 1
