"""Perbaiki pencatatan jawaban jalur dana yang terlalu panjang.

AKAR MASALAH (ditemukan dari bukti, bukan dugaan). Uji hidup 25 Agu 2026
menghasilkan baris jejak seperti ini untuk /fapi/v2/balance:

    "jawaban": {"tak_terserialisasi": "[{'accountAlias': 'XqXqXqSguXAuoC',
     'asset': 'FDUSD', ... 'marginAvailable': True, ..."}

Itu repr Python (kutip tunggal, True kapital), bukan JSON. Penyebabnya bukan
soal daftar atau bukan daftar, melainkan urutan operasinya:

    json.loads(_potong(json.dumps(jawaban)))

Teks JSON dipotong LEBIH DULU, lalu dicoba di-parse. JSON yang dipotong di
tengah SELALU tidak sah, jadi except-nya SELALU kena, dan hasilnya selalu repr.
Artinya setiap jawaban jalur dana yang lebih panjang dari BATAS_TEKS kehilangan
strukturnya - termasuk /fapi/v2/balance, /fapi/v2/positionRisk, dan
/fapi/v1/openOrders, yaitu tiga jalur yang justru paling perlu terbaca rapi
ketika Binance mengubah API.

PERBAIKAN. Jangan pernah memotong teks JSON lalu memparsenya. Serialisasi dulu
untuk mengukur panjang; kalau muat, parse utuh; kalau tidak muat, ringkas secara
TERSTRUKTUR dengan mempertahankan field-field yang menentukan.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pasang_tes import blok, terapkan_uji  # noqa: E402

JEJAK = "lux_modul/eksekusi/jejak.py"

TAMBALAN = [
    {
        "nama": "ringkas_jawaban_tidak_memotong_json",
        "berkas": JEJAK,
        "tanda": "_ringkas_besar",
        "jumlah": 1,
        "lama": blok(
            'def ringkas_jawaban(path, jawaban):',
            '    """Jalur dana dicatat utuh; jalur lain hanya bentuknya."""',
            '    if jalur_dana(path):',
            '        try:',
            '            return json.loads(_potong(json.dumps(jawaban, default=str)))',
            '        except Exception:',
            '            return {"tak_terserialisasi": _potong(repr(jawaban))}',
        ),
        "baru": blok(
            '# Field yang menentukan saat membedah order atau posisi. Dipakai ketika',
            '# jawaban terlalu panjang untuk disimpan utuh.',
            '_KUNCI_PENTING = (',
            '    "orderId", "clientOrderId", "origClientOrderId", "status", "symbol",',
            '    "side", "type", "origType", "timeInForce", "price", "stopPrice",',
            '    "origQty", "executedQty", "cumQuote", "avgPrice", "reduceOnly",',
            '    "closePosition", "positionAmt", "entryPrice", "liquidationPrice",',
            '    "leverage", "asset", "balance", "availableBalance", "code", "msg",',
            '    "updateTime",',
            ')',
            '',
            '',
            'def _ringkas_besar(jawaban, teks):',
            '    """Ringkasan TERSTRUKTUR untuk jawaban jalur dana yang terlalu panjang.',
            '',
            '    Versi lama memotong teks JSON lalu memanggil json.loads. JSON yang',
            '    dipotong di tengah tidak pernah sah, jadi jalur except SELALU kena dan',
            '    hasilnya selalu repr Python. Akibatnya balance, positionRisk, dan',
            '    openOrders tercatat sebagai teks repr, bukan data - padahal justru itu',
            '    yang perlu dibaca saat endpoint atau parameter Binance berubah.',
            '    """',
            '    ringkas = {"dipangkas": True, "panjang_json": len(teks),',
            '               "tipe": type(jawaban).__name__}',
            '    try:',
            '        if isinstance(jawaban, dict):',
            '            ringkas["kunci"] = sorted(str(k) for k in jawaban)',
            '            for k in _KUNCI_PENTING:',
            '                if k in jawaban:',
            '                    ringkas[k] = jawaban[k]',
            '        elif isinstance(jawaban, (list, tuple)):',
            '            ringkas["panjang"] = len(jawaban)',
            '            entri = []',
            '            for x in list(jawaban)[:8]:',
            '                if isinstance(x, dict):',
            '                    inti = {}',
            '                    for k in _KUNCI_PENTING:',
            '                        if k in x:',
            '                            inti[k] = x[k]',
            '                    entri.append(inti or {"kunci": sorted(str(k) for k in x)})',
            '                else:',
            '                    entri.append(_potong(repr(x), 120))',
            '            ringkas["entri"] = entri',
            '        else:',
            '            ringkas["nilai"] = _potong(repr(jawaban), 400)',
            '    except Exception:',
            '        ringkas["nilai"] = "[tak terbaca]"',
            '    return ringkas',
            '',
            '',
            'def ringkas_jawaban(path, jawaban):',
            '    """Jalur dana dicatat utuh; jalur lain hanya bentuknya."""',
            '    if jalur_dana(path):',
            '        try:',
            '            teks = json.dumps(jawaban, default=str)',
            '        except Exception:',
            '            return {"tak_terserialisasi": _potong(repr(jawaban))}',
            '        if len(teks) <= BATAS_TEKS:',
            '            try:',
            '                return json.loads(teks)',
            '            except Exception:',
            '                return {"tak_terserialisasi": _potong(teks)}',
            '        return _ringkas_besar(jawaban, teks)',
        ),
    },
]


if __name__ == "__main__":
    raise SystemExit(terapkan_uji(TAMBALAN, "JEJAK"))
