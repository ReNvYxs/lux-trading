"""Setelan bersama untuk seluruh suite uji.

Sejak 6 Agu 2026 bawaan LUX_EKSEKUSI adalah 'otomatis': jalur proteksi dipilih
dari jawaban bursa, dan kalau bursa tidak bisa menjawab, jatuh ke jalur 'aman'
(fail-closed). Klien tiruan di suite lama tidak bisa menjawab probe, sehingga
tanpa deklarasi ini suite lama akan diam-diam berpindah jalur dan mengukur hal
yang berbeda dari yang ia klaim ukur. Itu bukan kegagalan yang perlu ditambal
di kode; itu tes yang perlu menyebutkan asumsinya.

Kejadian nyatanya: dua tes di tests/test_live_runner.py mendadak gagal dengan
AttributeError _tidur setelah bawaan berubah, karena _runner_kosong() membangun
LiveRunner lewat __new__ dan jalur aman menyentuh atribut yang tidak pernah
dipasang. Gejalanya tampak seperti bug kode, penyebabnya asumsi tes.

Jadi suite memakai jalur 'lama' secara EKSPLISIT. Perilaku 'otomatis' dan
'aman' tetap teruji, justru lebih tajam, di:
  tests/test_saklar_otomatis.py     env dioper eksplisit ke fungsi
  tests/test_saklar_eksekusi.py     env dioper eksplisit ke fungsi
  tests/test_live_runner_saklar.py  aman_aktif_untuk di-monkeypatch

Efek samping yang disengaja: hasil uji tidak lagi bergantung pada berkas .env
atau variabel lingkungan mesin yang kebetulan menjalankannya.
"""
import pytest

from lux_modul.eksekusi_aman import saklar as _saklar


@pytest.fixture(autouse=True)
def lingkungan_eksekusi_uji(monkeypatch):
    monkeypatch.setenv("LUX_EKSEKUSI", "lama")
    monkeypatch.delenv("LUX_BATAS_JARAK_PROTEKSI", raising=False)
    _saklar.bersihkan_cache_probe()
    yield
    _saklar.bersihkan_cache_probe()
