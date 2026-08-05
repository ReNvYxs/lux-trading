#!/usr/bin/env bash
# Bukti kesehatan hasil rakitan. Semua non-fatal: kegagalan direkam, bukan
# menyembunyikan diri di balik job merah tanpa artefak.
set +e
mkdir -p bukti

{
  echo "=== impor paket inti ==="
  python3 -c "import lux_modul; print('lux_modul OK')"
  echo "rc_lux_modul=$?"
  echo
  echo "=== impor lapisan eksekusi aman ==="
  python3 -c "import lux_modul.eksekusi_aman.inti as I; ns=[n for n in dir(I) if not n.startswith('_')]; print('inti OK, simbol publik=', len(ns)); print(sorted(ns)[:60])"
  echo "rc_inti=$?"
  echo
  python3 -c "import lux_modul.eksekusi_aman.proteksi as P; ns=[n for n in dir(P) if not n.startswith('_')]; print('proteksi OK, simbol publik=', len(ns)); print(sorted(ns)[:60])"
  echo "rc_proteksi=$?"
  echo
  echo "=== registry strategi ==="
  python3 -c "from lux_modul.plugin import registry_bawaan; r=registry_bawaan(); ids=sorted(getattr(r,'ids',lambda: [])() or []); print('jumlah strategi=', len(ids)); print(ids)"
  echo "rc_registry=$?"
} > bukti/log_impor.txt 2>&1
cat bukti/log_impor.txt

echo "=== pytest baseline ===" | tee bukti/log_pytest.txt
python3 -m pytest -q tests 2>&1 | tee -a bukti/log_pytest.txt
echo "rc_pytest=${PIPESTATUS[0]}" | tee -a bukti/log_pytest.txt
tail -n 30 bukti/log_pytest.txt > bukti/ringkas_pytest.txt
exit 0
