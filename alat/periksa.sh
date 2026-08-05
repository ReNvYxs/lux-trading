#!/usr/bin/env bash
# Bukti kesehatan hasil rakitan. Semua non-fatal: kegagalan direkam, bukan
# menghilang di balik job merah tanpa artefak.
# Nama berkas sengaja TIDAK berawalan log_ karena .gitignore repo sumber
# memuat pola log_*.txt yang pernah menelan artefak tanpa pesan galat.
set +e
mkdir -p bukti

{
  echo "=== impor paket inti ==="
  python3 -c "import lux_modul; print('lux_modul OK')"
  echo "rc_lux_modul=$?"
  echo
  echo "=== impor lapisan eksekusi aman ==="
  python3 -c "import lux_modul.eksekusi_aman.inti as I; ns=[n for n in dir(I) if not n.startswith('_')]; print('inti OK, simbol publik=', len(ns)); print(sorted(ns))"
  echo "rc_inti=$?"
  echo
  python3 -c "import lux_modul.eksekusi_aman.proteksi as P; ns=[n for n in dir(P) if not n.startswith('_')]; print('proteksi OK, simbol publik=', len(ns)); print(sorted(ns))"
  echo "rc_proteksi=$?"
  echo
  echo "=== registry strategi (introspeksi) ==="
  python3 alat/temu_registry.py
  echo "rc_registry=$?"
  echo
  echo "=== konfigurasi bawaan ==="
  python3 -c "from lux_modul.konfigurasi import muat_konfigurasi; k=muat_konfigurasi(muat_env=False); print(k.ringkas())"
  echo "rc_konfigurasi=$?"
} > bukti/jejak_impor.txt 2>&1
cat bukti/jejak_impor.txt

echo "=== pytest baseline ===" > bukti/jejak_pytest.txt
python3 -m pytest -q tests 2>&1 | tee -a bukti/jejak_pytest.txt
echo "rc_pytest=${PIPESTATUS[0]}" | tee -a bukti/jejak_pytest.txt
tail -n 30 bukti/jejak_pytest.txt > bukti/ringkas_pytest.txt

python3 alat/ringkas_rakit.py > bukti/jejak_ringkas.txt 2>&1
tail -n 5 bukti/jejak_ringkas.txt
exit 0
