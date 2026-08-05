"""L1b - pemindai likuiditas pasar Binance USD-M Futures.

Tujuan arsitektural (jangan dilanggar):
    Binance Market -> Scan Liquid Pairs -> Pilih 25..50 pair -> Strategi (STF/MTF)
    -> Signal -> Risk Management -> Entry

BUKAN: BTC -> 15m -> Entry.

Aturan:
- Daftar pair diambil langsung dari `/fapi/v1/exchangeInfo` (tidak ada whitelist
  permanen di source code).
- Likuiditas diukur dari data pasar nyata: quoteVolume 24 jam, jumlah trade 24
  jam, dan (opsional) spread + kedalaman buku order.
- Hasil pindai punya masa berlaku (TTL). Engine WAJIB memanggil ulang secara
  berkala agar mengikuti perubahan likuiditas.
- BTCUSDT tidak pernah diistimewakan. Ia hanya lolos bila memang memenuhi
  kriteria, dan tidak pernah menjadi satu-satunya pair kecuali seluruh pasar
  memang hanya menyisakan satu pair yang lolos (kondisi itu dianggap galat).

Fallback saat verifikasi buku order kurang dari min_pair (4 Agu 2026):
- SEBELUMNYA: bila pemeriksaan spread/kedalaman buku hanya meloloskan < min_pair
  pair, seluruh verifikasi buku DIBUANG dan pemindai kembali memeringkat SEMUA
  kandidat murni dari volume+aktivitas mentah (tanpa spread/kedalaman) - ini
  MELONGGARKAN kriteria tepat saat pasar sedang ketat, kebalikan dari yang
  diinginkan.
- SEKARANG: pair yang sudah lolos verifikasi buku dipakai APA ADANYA, walau
  jumlahnya di bawah min_pair (mis. 23 dari target 25). Kriteria tidak pernah
  dilonggarkan. Hanya bila pemindaian menyisakan <2 pair sama sekali, engine
  menolak jalan (PemindaiError) - itu sudah pagar arsitektural yang ada.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

# kode alasan penolakan (dipakai laporan & pengujian)
TOLAK_STATUS = "status_bukan_trading"
TOLAK_KONTRAK = "tipe_kontrak_tidak_sesuai"
TOLAK_QUOTE = "quote_aset_tidak_sesuai"
TOLAK_SIMBOL_KHUSUS = "pola_simbol_dikecualikan"
TOLAK_DAFTAR_HITAM = "daftar_hitam_operator"
TOLAK_TANPA_TICKER = "tanpa_data_ticker_24j"
TOLAK_VOLUME = "volume_24j_di_bawah_minimum"
TOLAK_JUMLAH_TRADE = "jumlah_trade_24j_di_bawah_minimum"
TOLAK_HARGA = "harga_tidak_valid"
TOLAK_SPREAD = "spread_terlalu_lebar"
TOLAK_KEDALAMAN = "kedalaman_buku_tipis"
TOLAK_LEVERAGE_TF = "filter_pasar_tidak_lengkap"


class PemindaiError(Exception):
    """Dilempar bila pemindaian tidak menghasilkan pair yang layak."""


@dataclass(frozen=True)
class KriteriaLikuiditas:
    """Semua ambang bisa diatur operator lewat .env - tidak ada nilai sakral."""

    quote_aset: str = "USDT"
    tipe_kontrak: str = "PERPETUAL"
    min_pair: int = 25
    maks_pair: int = 50
    min_quote_volume_24j: float = 50_000_000.0
    min_jumlah_trade_24j: int = 50_000
    maks_spread_bps: float = 6.0
    min_kedalaman_usd: float = 25_000.0
    periksa_buku: bool = True
    kandidat_buku: int = 80
    kedalaman_limit: int = 20
    ttl_detik: float = 1800.0
    daftar_hitam: Tuple[str, ...] = ()
    bobot_volume: float = 0.5
    bobot_trade: float = 0.3
    bobot_spread: float = 0.2

    def __post_init__(self) -> None:
        if self.min_pair < 1:
            raise ValueError("min_pair minimal 1")
        if self.maks_pair < self.min_pair:
            raise ValueError("maks_pair tidak boleh lebih kecil dari min_pair")
        if self.min_pair < 2:
            # pagar arsitektural: engine ini memang multi-pair
            raise ValueError(
                "min_pair < 2 berarti engine single-pair (mis. BTC-only) - dilarang"
            )

    def ringkas(self) -> Dict[str, Any]:
        return {
            "quote_aset": self.quote_aset,
            "tipe_kontrak": self.tipe_kontrak,
            "rentang_pair": [self.min_pair, self.maks_pair],
            "min_quote_volume_24j": self.min_quote_volume_24j,
            "min_jumlah_trade_24j": self.min_jumlah_trade_24j,
            "maks_spread_bps": self.maks_spread_bps,
            "min_kedalaman_usd": self.min_kedalaman_usd,
            "periksa_buku": self.periksa_buku,
            "ttl_detik": self.ttl_detik,
            "daftar_hitam": list(self.daftar_hitam),
        }


@dataclass(frozen=True)
class PairLikuid:
    """Satu pair yang lolos saringan, lengkap dengan filter pasarnya."""

    simbol: str
    quote_volume_24j: float
    jumlah_trade_24j: int
    harga_terakhir: float
    spread_bps: Optional[float] = None
    kedalaman_usd: Optional[float] = None
    skor_likuiditas: float = 0.0
    peringkat: int = 0
    tick_size: Optional[float] = None
    step_size: Optional[float] = None
    min_notional: Optional[float] = None
    presisi_harga: Optional[int] = None
    presisi_qty: Optional[int] = None

    def ringkas(self) -> Dict[str, Any]:
        return {
            "simbol": self.simbol,
            "peringkat": self.peringkat,
            "skor_likuiditas": round(self.skor_likuiditas, 4),
            "quote_volume_24j": round(self.quote_volume_24j, 2),
            "jumlah_trade_24j": self.jumlah_trade_24j,
            "harga_terakhir": self.harga_terakhir,
            "spread_bps": None if self.spread_bps is None else round(self.spread_bps, 4),
            "kedalaman_usd": None if self.kedalaman_usd is None else round(self.kedalaman_usd, 2),
            "tick_size": self.tick_size,
            "step_size": self.step_size,
            "min_notional": self.min_notional,
        }


@dataclass(frozen=True)
class HasilPindai:
    """Snapshot pemindaian pada satu waktu."""

    waktu_ms: int
    pair: Tuple[PairLikuid, ...]
    ditolak: Mapping[str, int] = field(default_factory=dict)
    total_kandidat: int = 0
    kriteria: Mapping[str, Any] = field(default_factory=dict)
    catatan: Tuple[str, ...] = ()

    @property
    def simbol(self) -> Tuple[str, ...]:
        return tuple(p.simbol for p in self.pair)

    def kadaluarsa(self, ttl_detik: float, sekarang_ms: Optional[int] = None) -> bool:
        kini = int(time.time() * 1000) if sekarang_ms is None else int(sekarang_ms)
        return (kini - self.waktu_ms) >= ttl_detik * 1000.0

    def ringkas(self) -> Dict[str, Any]:
        return {
            "waktu_ms": self.waktu_ms,
            "jumlah_pair": len(self.pair),
            "total_kandidat": self.total_kandidat,
            "simbol": list(self.simbol),
            "ditolak": dict(self.ditolak),
            "kriteria": dict(self.kriteria),
            "catatan": list(self.catatan),
            "lima_teratas": [p.ringkas() for p in self.pair[:5]],
        }


# --------------------------------------------------------------------------- #
# util murni (mudah diuji tanpa jaringan)
# --------------------------------------------------------------------------- #


def _peringkat_persentil(nilai: Sequence[float], lebih_besar_lebih_baik: bool = True) -> List[float]:
    """Ubah deret nilai menjadi persentil 0..1 (tahan outlier & beda skala)."""
    n = len(nilai)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    urut = sorted(range(n), key=lambda i: nilai[i], reverse=not lebih_besar_lebih_baik)
    skor = [0.0] * n
    for posisi, idx in enumerate(urut):
        skor[idx] = posisi / (n - 1)
    return skor


def peringkat_dari_ticker(
    baris: Sequence[Mapping[str, Any]],
    kriteria: KriteriaLikuiditas,
) -> List[Tuple[str, float]]:
    """Hitung skor likuiditas gabungan dari data ticker 24 jam.

    Fungsi murni: dipakai engine live DAN backtest agar pemeringkatan identik.
    """
    if not baris:
        return []
    vol = [math.log10(max(float(b.get("quoteVolume", 0.0)), 1.0)) for b in baris]
    trd = [math.log10(max(float(b.get("count", 0.0)), 1.0)) for b in baris]
    sv = _peringkat_persentil(vol)
    st = _peringkat_persentil(trd)
    ada_spread = any(b.get("spread_bps") is not None for b in baris)
    if ada_spread:
        sp = [float(b.get("spread_bps") or 1e9) for b in baris]
        ss = _peringkat_persentil(sp, lebih_besar_lebih_baik=False)
        bobot_total = kriteria.bobot_volume + kriteria.bobot_trade + kriteria.bobot_spread
        skor = [
            (kriteria.bobot_volume * sv[i] + kriteria.bobot_trade * st[i] + kriteria.bobot_spread * ss[i])
            / bobot_total
            for i in range(len(baris))
        ]
    else:
        bobot_total = kriteria.bobot_volume + kriteria.bobot_trade
        skor = [
            (kriteria.bobot_volume * sv[i] + kriteria.bobot_trade * st[i]) / bobot_total
            for i in range(len(baris))
        ]
    pasangan = [(str(baris[i].get("symbol")), float(skor[i])) for i in range(len(baris))]
    pasangan.sort(key=lambda x: x[1], reverse=True)
    return pasangan


def _filter_pasar(info_simbol: Mapping[str, Any]) -> Dict[str, Optional[float]]:
    out: Dict[str, Optional[float]] = {
        "tick_size": None,
        "step_size": None,
        "min_notional": None,
    }
    for f in info_simbol.get("filters", []) or []:
        jenis = f.get("filterType")
        if jenis == "PRICE_FILTER":
            out["tick_size"] = float(f.get("tickSize", 0) or 0) or None
        elif jenis in ("LOT_SIZE", "MARKET_LOT_SIZE") and out["step_size"] is None:
            out["step_size"] = float(f.get("stepSize", 0) or 0) or None
        elif jenis == "MIN_NOTIONAL":
            nilai = f.get("notional", f.get("minNotional"))
            out["min_notional"] = float(nilai) if nilai is not None else None
    return out


# --------------------------------------------------------------------------- #
# pemindai
# --------------------------------------------------------------------------- #


class PemindaiPasar:
    """Memilih 25..50 pair paling likuid, langsung dari kondisi pasar Binance.

    Dipakai oleh engine testnet/live. Objek ini menyimpan cache ber-TTL sehingga
    aman dipanggil setiap siklus; jaringan hanya disentuh saat cache kedaluwarsa
    atau saat `paksa=True`.
    """

    def __init__(
        self,
        client: Any,
        kriteria: Optional[KriteriaLikuiditas] = None,
        jam: Optional[Any] = None,
    ) -> None:
        self.client = client
        self.kriteria = kriteria or KriteriaLikuiditas()
        self._jam = jam or (lambda: int(time.time() * 1000))
        self._terakhir: Optional[HasilPindai] = None

    # ------------------------------ publik ------------------------------ #

    @property
    def terakhir(self) -> Optional[HasilPindai]:
        return self._terakhir

    def perlu_segarkan(self) -> bool:
        if self._terakhir is None:
            return True
        return self._terakhir.kadaluarsa(self.kriteria.ttl_detik, self._jam())

    def pindai(self, paksa: bool = False) -> HasilPindai:
        if not paksa and not self.perlu_segarkan() and self._terakhir is not None:
            return self._terakhir
        hasil = self._pindai_sekarang()
        self._terakhir = hasil
        return hasil

    def simbol_aktif(self, paksa: bool = False) -> Tuple[str, ...]:
        return self.pindai(paksa=paksa).simbol

    # ------------------------------ internal ------------------------------ #

    def _pindai_sekarang(self) -> HasilPindai:
        k = self.kriteria
        ditolak: Dict[str, int] = {}
        catatan: List[str] = []

        def tolak(kode: str) -> None:
            ditolak[kode] = ditolak.get(kode, 0) + 1

        info = self.client.exchange_info() or {}
        simbol_info = info.get("symbols", []) or []
        if not simbol_info:
            raise PemindaiError("exchangeInfo tidak mengembalikan simbol apa pun")

        layak: Dict[str, Mapping[str, Any]] = {}
        hitam = {s.upper() for s in k.daftar_hitam}
        for s in simbol_info:
            nama = str(s.get("symbol", "")).upper()
            if not nama:
                continue
            if str(s.get("status", "")).upper() != "TRADING":
                tolak(TOLAK_STATUS)
                continue
            if str(s.get("contractType", "")).upper() != k.tipe_kontrak.upper():
                tolak(TOLAK_KONTRAK)
                continue
            if str(s.get("quoteAsset", "")).upper() != k.quote_aset.upper():
                tolak(TOLAK_QUOTE)
                continue
            if "_" in nama:  # kontrak berjangka bertanggal, mis. BTCUSDT_240927
                tolak(TOLAK_SIMBOL_KHUSUS)
                continue
            if nama in hitam:
                tolak(TOLAK_DAFTAR_HITAM)
                continue
            layak[nama] = s

        total_kandidat = len(layak)
        if total_kandidat == 0:
            raise PemindaiError("tidak ada simbol yang lolos saringan exchangeInfo")

        tikers = self.client.ticker_24jam()
        if isinstance(tikers, dict):
            tikers = [tikers]
        peta_ticker = {str(t.get("symbol", "")).upper(): t for t in (tikers or [])}

        baris: List[Dict[str, Any]] = []
        for nama in layak:
            t = peta_ticker.get(nama)
            if t is None:
                tolak(TOLAK_TANPA_TICKER)
                continue
            qv = float(t.get("quoteVolume", 0.0) or 0.0)
            cnt = int(float(t.get("count", 0) or 0))
            harga = float(t.get("lastPrice", 0.0) or 0.0)
            if harga <= 0:
                tolak(TOLAK_HARGA)
                continue
            if qv < k.min_quote_volume_24j:
                tolak(TOLAK_VOLUME)
                continue
            if cnt < k.min_jumlah_trade_24j:
                tolak(TOLAK_JUMLAH_TRADE)
                continue
            baris.append(
                {"symbol": nama, "quoteVolume": qv, "count": cnt, "lastPrice": harga, "spread_bps": None}
            )

        if not baris:
            raise PemindaiError(
                "tidak ada pair yang memenuhi ambang volume/trade - turunkan "
                "LUX_PINDAI_MIN_QUOTE_VOLUME / LUX_PINDAI_MIN_TRADE di .env"
            )

        # peringkat awal (volume + aktivitas) untuk memilih kandidat pemeriksaan buku
        awal = peringkat_dari_ticker(baris, k)
        urutan_awal = [nama for nama, _ in awal]
        peta_baris = {b["symbol"]: b for b in baris}

        if k.periksa_buku:
            kandidat = urutan_awal[: max(k.kandidat_buku, k.maks_pair)]
            lolos_buku: List[str] = []
            for nama in kandidat:
                try:
                    buku = self.client.buku_order(nama, limit=k.kedalaman_limit)
                except Exception as exc:  # jaringan/limit - jangan matikan seluruh pindai
                    catatan.append(f"buku_order {nama} gagal: {type(exc).__name__}")
                    continue
                bid = buku.get("bids") or []
                ask = buku.get("asks") or []
                if not bid or not ask:
                    tolak(TOLAK_KEDALAMAN)
                    continue
                bid_harga, ask_harga = float(bid[0][0]), float(ask[0][0])
                if bid_harga <= 0 or ask_harga <= 0:
                    tolak(TOLAK_HARGA)
                    continue
                tengah = (bid_harga + ask_harga) / 2.0
                spread_bps = (ask_harga - bid_harga) / tengah * 10_000.0
                kedalaman = sum(float(p) * float(q) for p, q in bid[:5]) + sum(
                    float(p) * float(q) for p, q in ask[:5]
                )
                if spread_bps > k.maks_spread_bps:
                    tolak(TOLAK_SPREAD)
                    continue
                if kedalaman < k.min_kedalaman_usd:
                    tolak(TOLAK_KEDALAMAN)
                    continue
                peta_baris[nama]["spread_bps"] = spread_bps
                peta_baris[nama]["kedalaman_usd"] = kedalaman
                lolos_buku.append(nama)
                if len(lolos_buku) >= k.maks_pair:
                    break
            # GAGAL AMAN (4 Agu 2026): kriteria TIDAK PERNAH dilonggarkan.
            # Sebelumnya, jika lolos_buku < min_pair, kode ini membuang SELURUH
            # verifikasi spread/kedalaman dan memeringkat ulang semua kandidat
            # murni dari volume+aktivitas mentah - itu justru melonggarkan
            # kriteria persis saat pasar sedang ketat. Sekarang: pair yang
            # sudah lolos verifikasi buku dipakai apa adanya, walau di bawah
            # min_pair (mis. 23 dari target 25). Hanya <2 pair total yang
            # dianggap galat (pagar arsitektural di bawah, tidak berubah).
            if len(lolos_buku) < k.min_pair:
                catatan.append(
                    f"pemeriksaan buku hanya meloloskan {len(lolos_buku)} pair (< min_pair "
                    f"{k.min_pair}); kriteria TETAP ditegakkan - pair yang lolos verifikasi "
                    "spread/kedalaman dipakai apa adanya, TIDAK melonggarkan ke peringkat "
                    "volume+aktivitas mentah"
                )
            baris_final = [peta_baris[n] for n in lolos_buku]
        else:
            baris_final = [peta_baris[n] for n in urutan_awal]

        akhir = peringkat_dari_ticker(baris_final, k)[: k.maks_pair]
        if len(akhir) < k.min_pair:
            catatan.append(
                f"hanya {len(akhir)} pair lolos (< min_pair {k.min_pair}); pasar sedang "
                "sepi atau ambang .env terlalu ketat"
            )
        if len(akhir) < 2:
            raise PemindaiError(
                "pemindaian menyisakan <2 pair - engine ini multi-pair, menolak "
                "berjalan single-pair (mis. BTC-only)"
            )

        pair: List[PairLikuid] = []
        for i, (nama, skor) in enumerate(akhir, start=1):
            b = peta_baris[nama]
            f = _filter_pasar(layak[nama])
            pair.append(
                PairLikuid(
                    simbol=nama,
                    quote_volume_24j=float(b["quoteVolume"]),
                    jumlah_trade_24j=int(b["count"]),
                    harga_terakhir=float(b["lastPrice"]),
                    spread_bps=b.get("spread_bps"),
                    kedalaman_usd=b.get("kedalaman_usd"),
                    skor_likuiditas=float(skor),
                    peringkat=i,
                    tick_size=f["tick_size"],
                    step_size=f["step_size"],
                    min_notional=f["min_notional"],
                    presisi_harga=layak[nama].get("pricePrecision"),
                    presisi_qty=layak[nama].get("quantityPrecision"),
                )
            )

        return HasilPindai(
            waktu_ms=int(self._jam()),
            pair=tuple(pair),
            ditolak=ditolak,
            total_kandidat=total_kandidat,
            kriteria=k.ringkas(),
            catatan=tuple(catatan),
        )
