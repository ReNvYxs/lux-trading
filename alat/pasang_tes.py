"""Mesin penambal berkas uji + tambalan tests/test_order_postonly.py.

Setelah lapisan eksekusi dikeraskan, 5 uji lama menjadi merah. Diperiksa satu
per satu: ini BUKAN regresi kode. Uji-uji itu mengunci perilaku yang sudah
dibuktikan salah.

1. Dua uji MENUNTUT visible_qty dan icebergQty dikirim ke bursa. p01
   membuktikan icebergQty diabaikan Binance Futures, dan visible_qty sama
   sekali bukan parameter Binance. Keduanya ikut ditandatangani, jadi
   menuntutnya dikirim sama dengan menuntut risiko -1104.
2. Tiga uji memakai jawaban bursa palsu tanpa orderId atau tanpa status. Bursa
   nyata tidak pernah menjawab begitu; jawaban seperti itu MEMANG harus gagal
   konfirmasi.

Yang diperbaiki adalah palsuannya, bukan konfirmasinya. Melemahkan
konfirmasi_order agar uji hijau akan mengembalikan cacat D12: order ditolak
dihitung terisi penuh.
"""
from __future__ import annotations

import json
import os

AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UJI_ORDER = "tests/test_order_postonly.py"
UJI_INTI = "tests/test_inti.py"


def blok(*baris):
    return "\n".join(baris) + "\n"


def terapkan_uji(tambalan, label):
    isi = {}
    diterapkan = []
    rc = 0
    for t in tambalan:
        jalur = os.path.join(AKAR, t["berkas"])
        if not os.path.isfile(jalur):
            print("HILANG=" + t["berkas"])
            return 2
        if t["berkas"] not in isi:
            with open(jalur, "r", encoding="utf-8") as f:
                isi[t["berkas"]] = f.read()
        teks = isi[t["berkas"]]
        sudah = t["tanda"] in teks
        n = teks.count(t["lama"])
        print("jangkar=" + json.dumps({"nama": t["nama"], "berkas": t["berkas"],
                                       "jumlah": n, "diharap": t["jumlah"],
                                       "sudah": sudah}))
        if sudah:
            continue
        if n != t["jumlah"]:
            rc = 3
            continue
        isi[t["berkas"]] = teks.replace(t["lama"], t["baru"])
        diterapkan.append(t["nama"])
    if rc:
        print(label + "=GAGAL")
        return rc
    for berkas, teks in isi.items():
        try:
            compile(teks, berkas, "exec")
        except SyntaxError as exc:
            print("SINTAKS_GAGAL=" + berkas + " " + str(exc))
            return 4
        with open(os.path.join(AKAR, berkas), "w", encoding="utf-8") as f:
            f.write(teks)
    gabung = "".join(isi.values())
    print(label + "=SELESAI")
    print("diterapkan=" + json.dumps(diterapkan))
    print("sisa_iceberg_dituntut=" + str(gabung.count('p["icebergQty"]')))
    print("sisa_visible_dituntut=" + str(gabung.count('"visible_qty" in p')))
    print("sisa_jawab_tanpa_status=" + str(gabung.count('return {"status": "NEW"}')))
    print("jumlah_executedqty=" + str(gabung.count("executedQty")))
    return 0


TAMBALAN = [
    {
        "nama": "payload_tanpa_parameter_hantu",
        "berkas": UJI_ORDER,
        "tanda": "def test_slice_payload_postonly_tanpa_parameter_hantu",
        "jumlah": 1,
        "lama": blok(
            'def test_slice_payload_postonly_dan_iceberg():',
            '    s = Slice(urutan=0, qty=1.0, visible_qty=0.25, jeda_detik=0.0)',
            '    p = s.payload("BTCUSDT", "BUY", 100.0)',
            '    assert p["type"] == TIPE_LIMIT',
            '    assert p["timeInForce"] == TIF_POST_ONLY',
            '    assert p["icebergQty"] == 0.25',
            '    assert p["visible_qty"] == 0.25',
        ),
        "baru": blok(
            'def test_slice_payload_postonly_tanpa_parameter_hantu():',
            '    s = Slice(urutan=0, qty=1.0, visible_qty=0.25, jeda_detik=0.0)',
            '    p = s.payload("BTCUSDT", "BUY", 100.0)',
            '    assert p["type"] == TIPE_LIMIT',
            '    assert p["timeInForce"] == TIF_POST_ONLY',
            '    # p01: icebergQty diabaikan Futures, visible_qty bukan parameter',
            '    # Binance. Keduanya ditandatangani, jadi mengirimnya = risiko -1104.',
            '    assert "icebergQty" not in p',
            '    assert "visible_qty" not in p',
            '    assert s.visible_qty == 0.25',
            '    p2 = s.payload("BTCUSDT", "BUY", 100.0, cid="lxsujicid")',
            '    assert p2["newClientOrderId"] == "lxsujicid"',
        ),
    },
    {
        "nama": "jawaban_bursa_realistis",
        "berkas": UJI_ORDER,
        "tanda": '"status": "FILLED"',
        "jumlah": 1,
        "lama": blok(
            '    async def kirim(p):',
            '        terkirim.append(p)',
            '        return {"orderId": len(terkirim)}',
        ),
        "baru": blok(
            '    async def kirim(p):',
            '        terkirim.append(p)',
            '        # Bentuk jawaban Binance USD-M sebenarnya: ada orderId DAN status,',
            '        # angka berupa string. Tanpa keduanya konfirmasi wajib gagal.',
            '        return {"orderId": 1000 + len(terkirim), "symbol": p["symbol"],',
            '                "side": p["side"], "status": "FILLED", "type": p["type"],',
            '                "clientOrderId": p.get("newClientOrderId"),',
            '                "origQty": str(p["quantity"]),',
            '                "executedQty": str(p["quantity"]),',
            '                "avgPrice": str(p["price"])}',
        ),
    },
]


if __name__ == "__main__":
    raise SystemExit(terapkan_uji(TAMBALAN, "TES_ORDER"))
