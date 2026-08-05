#!/usr/bin/env bash
set -u

LABEL="${1:-tanpa-label}"

git config user.name "teori-bot"
git config user.email "teori-bot@users.noreply.github.com"

git add -A -f bukti || true

if git diff --cached --quiet; then
  echo "tidak ada perubahan untuk label $LABEL"
  exit 0
fi

git commit -m "[teori] $LABEL $GITHUB_SHA [skip ci]" || exit 0

i=1
while [ "$i" -le 5 ]; do
  if git pull --rebase origin "$GITHUB_REF_NAME" && git push origin "HEAD:$GITHUB_REF_NAME"; then
    echo "push berhasil pada percobaan $i"
    exit 0
  fi
  echo "percobaan $i gagal, ulangi"
  i=$((i + 1))
  sleep 3
done

echo "push gagal setelah 5 percobaan"
exit 0
