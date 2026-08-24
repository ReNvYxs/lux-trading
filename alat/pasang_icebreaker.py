"""Penambal berjangkar untuk eksekusi/ice_breaker.py - jalur entry LIVE.

Ini temuan paling berat dari audit 25 Agu 2026, dan ia ada di jalur yang BENAR
BENAR dipakai live_runner untuk entry.

D12. hasil.qty_terisi += s.qty. Yang ditambahkan adalah qty yang DIMINTA, dan
     jawaban bursa TIDAK PERNAH dilihat. Tidak ada pemeriksaan orderId, status,
     maupun executedQty. Order yang ditolak, jawaban kosong, bahkan dict galat,
     semuanya dihitung terisi PENUH. Inilah bentuk paling murni dari kondisi
     yang dilarang: mesin melaporkan order berhasil padahal bursa belum
     mengonfirmasi apa pun.

D13. payload mengirim visible_qty, yang BUKAN parameter Binance Futures sama
     sekali, plus icebergQty yang sudah dibuktikan diabaikan Futures di p01.
     Keduanya tetap ikut ditandatangani dan dikirim. Komentar lama menyebut ini
     PERBAIKAN BUG 1; klaim itu tidak benar dan justru membuka risiko -1104
     Not all sent parameters were read bila Binance mengeraskan validasi.

D14. Tidak ada penghentian saat satu slice gagal. Loop terus mengirim slice
     berikutnya, jadi kegagalan yang belum dipahami dibalas dengan MENAMBAH
     eksposur.

D16. Tidak ada newClientOrderId, jadi tidak ada idempotensi sama sekali di
     jalur entry: timeout berarti kita tidak punya cara menanyakan kembali
     apakah order itu masuk atau tidak.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pasang_inti import terapkan  # noqa: E402

IB = "lux_modul/eksekusi/ice_breaker.py"

CARI_IMPOR = """import asyncio
import time
from dataclasses import dataclass, field
"""
GANTI_IMPOR = """import asyncio
import hashlib
import time
from dataclasses import dataclass, field
"""

CARI_IMPOR2 = """from .order import (
    TIF_POST_ONLY,
    TIPE_LIMIT,
    KebijakanOrder,
    OrderTerlarang,
    harga_post_only,
    pastikan_tanpa_market,
)
"""
GANTI_IMPOR2 = """from .klasifikasi import GagalKonfirmasi, konfirmasi_order
from .order import (
    TIF_POST_ONLY,
    TIPE_LIMIT,
    KebijakanOrder,
    OrderTerlarang,
    harga_post_only,
    pastikan_tanpa_market,
)
"""

CARI_TANDA_TANGAN = """    def payload(self, simbol: str, sisi: str, harga: Optional[float]) -> Dict[str, Any]:
"""
GANTI_TANDA_TANGAN = """    def payload(self, simbol: str, sisi: str, harga: Optional[float],
                cid: Optional[str] = None) -> Dict[str, Any]:
"""

CARI_PAYLOAD = """            # PERBAIKAN BUG 1: visible_qty ikut dikirim, bukan hanya dihitung.
            "visible_qty": round(self.visible_qty, 12),
            "icebergQty": round(self.visible_qty, 12),
        }
        return pastikan_tanpa_market(p)
"""
GANTI_PAYLOAD = """            # DIHAPUS 25 Agu 2026. visible_qty BUKAN parameter Binance Futures
            # sama sekali, dan icebergQty sudah dibuktikan diabaikan Futures di
            # p01. Keduanya tetap ikut ditandatangani dan dikirim, sehingga
            # membuka risiko -1104 Not all sent parameters were read bila
            # Binance mengeraskan validasi parameter. Komentar lama menyebut
            # pengirimannya sebagai PERBAIKAN BUG 1; klaim itu tidak benar.
            # visible_qty tetap dihitung di objek Slice untuk keperluan laporan,
            # tetapi TIDAK dikirim ke bursa.
        }
        if cid:
            # Idempotensi. Tanpa ini, timeout pada entry tidak bisa
            # direkonsiliasi: kita tidak punya nama untuk ditanyakan kembali.
            p["newClientOrderId"] = cid
        return pastikan_tanpa_market(p)
"""

CARI_HASIL = """@dataclass
class HasilEksekusi:
    terkirim: List[Dict[str, Any]] = field(default_factory=list)
    dibatalkan: List[int] = field(default_factory=list)
    qty_terisi: float = 0.0
    alasan_batal: Optional[str] = None

    @property
    def selesai_penuh(self) -> bool:
        return not self.dibatalkan
"""
GANTI_HASIL = """@dataclass
class HasilEksekusi:
    terkirim: List[Dict[str, Any]] = field(default_factory=list)
    dibatalkan: List[int] = field(default_factory=list)
    qty_terisi: float = 0.0
    alasan_batal: Optional[str] = None
    # qty_diminta dipisah dari qty_terisi supaya partial fill terlihat sebagai
    # partial fill, bukan menyatu jadi satu angka yang menyesatkan.
    qty_diminta: float = 0.0
    galat: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def selesai_penuh(self) -> bool:
        return not self.dibatalkan

    @property
    def aman(self) -> bool:
        # Aman berarti tidak ada slice yang gagal DAN tidak ada slice yang
        # jawabannya tak terkonfirmasi. Dipakai pemanggil untuk memutuskan
        # apakah boleh melanjutkan ke pemasangan proteksi.
        return not self.galat and not self.dibatalkan

    @property
    def parsial(self) -> bool:
        return 0.0 < self.qty_terisi < self.qty_diminta

    def ringkas(self) -> Dict[str, Any]:
        return {"qty_diminta": self.qty_diminta, "qty_terisi": self.qty_terisi,
                "slice_terkirim": len(self.terkirim),
                "slice_dibatalkan": list(self.dibatalkan),
                "jumlah_galat": len(self.galat),
                "alasan_batal": self.alasan_batal,
                "aman": self.aman, "parsial": self.parsial}
"""

CARI_LOOP = """            payload = s.payload(rencana.simbol, sisi, harga_limit)
            resp = await self._kirim(payload)
            hasil.terkirim.append({"payload": payload, "respons": resp})
            hasil.qty_terisi += s.qty
        return hasil
"""
GANTI_LOOP = """            # cid deterministik per rencana+slice: percobaan ulang atas rencana
            # yang sama memakai nama yang sama, sehingga bursa menolaknya -4116
            # alih-alih membuat order kedua.
            cid = "lxs" + hashlib.sha1("|".join([
                str(rencana.simbol), str(sisi), str(rencana.qty_total),
                str(rencana.harga_acuan), str(s.urutan),
            ]).encode()).hexdigest()[:17]
            payload = s.payload(rencana.simbol, sisi, harga_limit, cid=cid)
            hasil.qty_diminta += float(s.qty)
            try:
                resp = await self._kirim(payload)
            except Exception as exc:
                # Slice gagal terkirim. JANGAN hitung sebagai terisi, dan JANGAN
                # kirim slice berikutnya: menambah eksposur di atas kegagalan
                # yang belum dipahami justru memperbesar risiko.
                hasil.alasan_batal = "slice_gagal_terkirim"
                hasil.galat.append({
                    "urutan": s.urutan, "tahap": "kirim", "payload": payload,
                    "galat": str(exc)[:240], "tipe_galat": type(exc).__name__,
                    "dampak": "slice ini mungkin sudah sampai ke bursa; "
                              "rekonsiliasi lewat newClientOrderId " + cid,
                    "perlu_diperbaiki": "IceBreakerExecutor.jalankan"})
                hasil.dibatalkan.append(s.urutan)
                batal = True
                continue
            try:
                ringkas = konfirmasi_order(resp, simbol=rencana.simbol,
                                          sisi=sisi, cid=cid)
            except GagalKonfirmasi as gk:
                # Ada jawaban, tetapi bukan konfirmasi. Versi lama TIDAK pernah
                # melihat jawaban sama sekali dan menambah qty_terisi dari qty
                # yang DIMINTA, sehingga order ditolak pun dihitung terisi
                # penuh. Inilah D12.
                hasil.alasan_batal = "slice_tidak_terkonfirmasi"
                hasil.galat.append({
                    "urutan": s.urutan, "tahap": "konfirmasi",
                    "payload": payload, "respons": resp,
                    "galat": str(gk)[:240],
                    "dampak": "qty slice ini TIDAK dihitung terisi; posisi "
                              "nyata wajib dibaca dari positionRisk",
                    "perlu_diperbaiki": "IceBreakerExecutor.jalankan"})
                hasil.dibatalkan.append(s.urutan)
                batal = True
                continue
            hasil.terkirim.append({"payload": payload, "respons": resp,
                                   "ringkas": ringkas, "cid": cid})
            # Hanya qty yang BENAR-BENAR terisi menurut bursa yang dihitung.
            # Order LIMIT post-only yang berstatus NEW belum terisi apa pun,
            # dan itu memang harus terbaca 0, bukan qty penuh.
            hasil.qty_terisi += float(ringkas.get("qty_terisi") or 0.0)
        return hasil
"""

TAMBALAN = [
    {"nama": "ib_impor_hashlib", "berkas": IB, "cari": CARI_IMPOR,
     "ganti": GANTI_IMPOR, "jumlah": 1, "tanda": "import hashlib"},
    {"nama": "ib_impor_konfirmasi", "berkas": IB, "cari": CARI_IMPOR2,
     "ganti": GANTI_IMPOR2, "jumlah": 1,
     "tanda": "from .klasifikasi import GagalKonfirmasi, konfirmasi_order"},
    {"nama": "ib_payload_tanda_tangan", "berkas": IB, "cari": CARI_TANDA_TANGAN,
     "ganti": GANTI_TANDA_TANGAN, "jumlah": 1,
     "tanda": "cid: Optional[str] = None) -> Dict[str, Any]:"},
    {"nama": "ib_buang_parameter_hantu", "berkas": IB, "cari": CARI_PAYLOAD,
     "ganti": GANTI_PAYLOAD, "jumlah": 1,
     "tanda": "visible_qty BUKAN parameter Binance Futures"},
    {"nama": "ib_hasil_diperluas", "berkas": IB, "cari": CARI_HASIL,
     "ganti": GANTI_HASIL, "jumlah": 1, "tanda": "def aman(self) -> bool:"},
    {"nama": "ib_qty_dari_konfirmasi", "berkas": IB, "cari": CARI_LOOP,
     "ganti": GANTI_LOOP, "jumlah": 1,
     "tanda": "slice_tidak_terkonfirmasi"},
]


def main():
    rc, isi = terapkan(TAMBALAN, "ICEBREAKER")
    if rc != 0:
        return rc
    teks = isi.get(IB, "")
    print("panjang_ib=" + str(len(teks)))
    print("sisa_visible_qty_dikirim=" + str(teks.count('"visible_qty": round(')))
    print("sisa_iceberg_dikirim=" + str(teks.count('"icebergQty": round(')))
    print("sisa_qty_terisi_buta=" + str(teks.count("hasil.qty_terisi += s.qty")))
    print("punya_cid=" + str("newClientOrderId" in teks))
    print("punya_konfirmasi=" + str("konfirmasi_order(" in teks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
