"""Tambalan tests/test_inti.py.

Tiga uji ice-breaker memakai jawaban bursa palsu {"status": "NEW"} tanpa
orderId. Bursa nyata tidak pernah menjawab begitu, dan sejak konfirmasi order
diwajibkan, jawaban seperti itu MEMANG harus gagal konfirmasi. Satu uji lagi
menuntut visible_qty dan icebergQty dikirim ke bursa, padahal p01 membuktikan
icebergQty diabaikan Binance Futures dan visible_qty bukan parameter Binance.

Jadi palsuannya yang diperbaiki, bukan konfirmasinya.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pasang_tes import UJI_INTI, blok, terapkan_uji  # noqa: E402

TAMBALAN = [
    {
        "nama": "nama_uji_jujur",
        "berkas": UJI_INTI,
        "tanda": "def test_parameter_hantu_tidak_dikirim_dan_qty_dari_konfirmasi",
        "jumlah": 1,
        "lama": blok('def test_visible_qty_benar_benar_dikirim():'),
        "baru": blok('def test_parameter_hantu_tidak_dikirim_dan_qty_dari_konfirmasi():'),
    },
    {
        "nama": "docstring_klaim_palsu",
        "berkas": UJI_INTI,
        "tanda": "# Klaim lama BUG LAMA 1",
        "jumlah": 1,
        "lama": blok(
            '    """BUG LAMA 1: visible_qty hanya dihitung, tidak dikirim. Sekarang wajib ada di payload."""',
        ),
        "baru": blok(
            '    # Klaim lama BUG LAMA 1 (visible_qty wajib dikirim) terbukti salah.',
            '    # p01: icebergQty diabaikan Binance Futures, dan visible_qty sama',
            '    # sekali bukan parameter Binance. Yang benar diuji di sini: parameter',
            '    # hantu TIDAK dikirim, cid deterministik ADA, dan qty_terisi hanya',
            '    # boleh berasal dari executedQty jawaban bursa.',
        ),
    },
    {
        "nama": "jawaban_filled_realistis",
        "berkas": UJI_INTI,
        "tanda": '"orderId": 900 + len(terkirim)',
        "jumlah": 1,
        "lama": blok(
            '    async def kirim(payload):',
            '        terkirim.append(payload)',
            '        return {"status": "NEW"}',
            '',
            '    async def tidur_cepat(_d):',
            '        return None',
            '',
            '    hasil = asyncio.run(',
            '        IceBreakerExecutor(kirim, tidur=tidur_cepat).jalankan(r)',
            '    )',
            '    assert len(terkirim) == r.jumlah_slice',
            '    for p, s in zip(terkirim, r.slices):',
            '        assert "visible_qty" in p and p["visible_qty"] == pytest.approx(s.visible_qty)',
            '        assert p["icebergQty"] == pytest.approx(s.visible_qty)',
            '        assert 0 < p["visible_qty"] <= p["quantity"]',
            '    assert hasil.qty_terisi == pytest.approx(2.0)',
            '    assert hasil.selesai_penuh',
        ),
        "baru": blok(
            '    async def kirim(payload):',
            '        terkirim.append(payload)',
            '        return {"orderId": 900 + len(terkirim), "symbol": payload["symbol"],',
            '                "side": payload["side"], "status": "FILLED",',
            '                "clientOrderId": payload.get("newClientOrderId"),',
            '                "origQty": str(payload["quantity"]),',
            '                "executedQty": str(payload["quantity"]),',
            '                "avgPrice": str(payload["price"])}',
            '',
            '    async def tidur_cepat(_d):',
            '        return None',
            '',
            '    hasil = asyncio.run(',
            '        IceBreakerExecutor(kirim, tidur=tidur_cepat).jalankan(r)',
            '    )',
            '    assert len(terkirim) == r.jumlah_slice',
            '    for p, s in zip(terkirim, r.slices):',
            '        assert "visible_qty" not in p',
            '        assert "icebergQty" not in p',
            '        assert p["newClientOrderId"].startswith("lxs")',
            '        assert 0 < p["quantity"] <= r.qty_total',
            '    assert len(set(p["newClientOrderId"] for p in terkirim)) == r.jumlah_slice',
            '    assert hasil.qty_terisi == pytest.approx(2.0)',
            '    assert hasil.selesai_penuh',
            '    assert hasil.aman',
        ),
    },
    {
        "nama": "jawaban_new_belum_terisi",
        "berkas": UJI_INTI,
        "tanda": '"orderId": 800',
        "jumlah": 1,
        "lama": blok(
            '    async def kirim(payload):',
            '        await asyncio.sleep(0)',
            '        return {"status": "NEW"}',
        ),
        "baru": blok(
            '    async def kirim(payload):',
            '        await asyncio.sleep(0)',
            '        # NEW = order limit post-only sudah diterima bursa tetapi belum',
            '        # terisi. executedQty 0 memang harus terbaca 0, bukan qty penuh.',
            '        return {"orderId": 800, "symbol": payload["symbol"],',
            '                "side": payload["side"], "status": "NEW",',
            '                "clientOrderId": payload.get("newClientOrderId"),',
            '                "origQty": str(payload["quantity"]), "executedQty": "0"}',
        ),
    },
    {
        "nama": "jawaban_new_saat_entry_invalid",
        "berkas": UJI_INTI,
        "tanda": '"orderId": 700 + keadaan',
        "jumlah": 1,
        "lama": blok(
            '    async def kirim(payload):',
            '        keadaan["n"] += 1',
            '        if keadaan["n"] == 2:',
            '            keadaan["harga"] = 48_900.0  # harga tembus SL di tengah eksekusi',
            '        return {"status": "NEW"}',
        ),
        "baru": blok(
            '    async def kirim(payload):',
            '        keadaan["n"] += 1',
            '        if keadaan["n"] == 2:',
            '            keadaan["harga"] = 48_900.0  # harga tembus SL di tengah eksekusi',
            '        return {"orderId": 700 + keadaan["n"], "symbol": payload["symbol"],',
            '                "side": payload["side"], "status": "NEW",',
            '                "clientOrderId": payload.get("newClientOrderId"),',
            '                "origQty": str(payload["quantity"]), "executedQty": "0"}',
        ),
    },
]


if __name__ == "__main__":
    raise SystemExit(terapkan_uji(TAMBALAN, "TES_INTI"))
