"""Uji regresi untuk tiga cacat nyata yang lolos dari 213 uji sebelumnya.

1. BUG P0 - order Take Profit tidak pernah dikirim ke bursa.
   Uji lama menyuntik `tp_price` langsung ke dataclass `_BracketAktif`, jadi
   jalur `verdict -> tp_price` tidak pernah teruji sama sekali. Di sini yang
   diuji adalah jalur itu, memakai `StrategyVerdict` sungguhan.

2. Ban IP 418/-1003 (log testnet 4 Agu 2026, 29 pair).
   Akarnya: tidak ada pengatur laju, data identik ditarik berulang per runner,
   dan saat sudah kena ban engine tetap menembak sehingga ban diperpanjang.

3. Penjadwalan runner: runner 15m tidak boleh menembak bursa 240x/jam.
"""
from __future__ import annotations

import io
import json
import os
import sys
import types
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lux_modul.eksekusi.binance_client import (
    BinanceAPIError,
    BinanceFuturesClient,
    PengaturLaju,
    _PATH_DEPTH,
    _PATH_KLINES,
    _PATH_TICKER_24J,
    bobot_permintaan,
    ms_ban_dari_pesan,
)
from lux_modul.eksekusi.kredensial import MODE_TESTNET, KredensialBinance
from lux_modul.kontrak import ARAH_LONG, KELOMPOK_INDIKATOR, StrategyVerdict, TargetTP
from lux_modul.live_runner import strategi_verdict, tp_pertama
from lux_modul.mesin_multi import JEDA_SETELAH_BAR_MS, MesinMultiPair


# --------------------------------------------------------------------------- #
# perkakas uji
# --------------------------------------------------------------------------- #


def _kredensial() -> KredensialBinance:
    return KredensialBinance(
        mode=MODE_TESTNET,
        api_key="kunci-uji",
        api_secret="rahasia-uji",
        base_url="https://contoh.invalid",
    )


class _Respons:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")
        self.status = 200

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _pembuka(payload, hitung):
    def buka(req, timeout=None):
        hitung.append(req.full_url)
        return _Respons(payload)

    return buka


def _pembuka_418(pesan, hitung):
    def buka(req, timeout=None):
        hitung.append(req.full_url)
        badan = json.dumps({"code": -1003, "msg": pesan}).encode("utf-8")
        raise urllib.error.HTTPError(
            req.full_url, 418, "Too Many Requests", {}, io.BytesIO(badan)
        )

    return buka


def _verdict(tps) -> StrategyVerdict:
    return StrategyVerdict(
        strategy_id="uji_strategi",
        kelompok=KELOMPOK_INDIKATOR,
        arah=ARAH_LONG,
        skor=70.0,
        ambang=60.0,
        entry=100.0,
        sl=95.0,
        tps=tps,
        level=100.0,
        invalidation=94.0,
        tfs_used=("15m",),
    )


# --------------------------------------------------------------------------- #
# 1. BUG P0: Take Profit
# --------------------------------------------------------------------------- #


def test_tp_pertama_membaca_tps_dari_verdict_sungguhan():
    v = _verdict((TargetTP(harga=110.0, porsi=0.5), TargetTP(harga=120.0, porsi=0.5)))
    assert tp_pertama(v) == 110.0


def test_tp_pertama_memakai_target_terdekat_lebih_dulu():
    v = _verdict((TargetTP(harga=105.0, porsi=0.5), TargetTP(harga=130.0, porsi=0.5)))
    assert tp_pertama(v) == 105.0


def test_verdict_tidak_punya_atribut_tp_sama_sekali():
    """Inilah akar bug lama: atribut `tp` memang tidak pernah ada."""
    v = _verdict((TargetTP(harga=110.0, porsi=1.0),))
    assert not hasattr(v, "tp")
    assert getattr(v, "tp", 0) == 0  # cara lama -> 0 -> TP tidak pernah dikirim
    assert tp_pertama(v) > 0  # cara baru -> harga TP sungguhan


def test_tp_pertama_aman_untuk_masukan_rusak():
    assert tp_pertama(None) == 0.0
    assert tp_pertama(types.SimpleNamespace(tps=())) == 0.0
    assert tp_pertama(types.SimpleNamespace(tps=None)) == 0.0
    assert tp_pertama(types.SimpleNamespace(tps=(types.SimpleNamespace(harga=0),))) == 0.0
    assert tp_pertama(types.SimpleNamespace(tps=(types.SimpleNamespace(harga="x"),))) == 0.0
    assert tp_pertama(types.SimpleNamespace()) == 0.0


def test_strategi_verdict_memakai_strategy_id():
    v = _verdict((TargetTP(harga=110.0, porsi=1.0),))
    assert strategi_verdict(v) == "uji_strategi"
    assert not hasattr(v, "strategi")  # nama field lama memang tidak ada
    assert strategi_verdict(None) == ""


# --------------------------------------------------------------------------- #
# 2. bobot rate-limit & pengatur laju
# --------------------------------------------------------------------------- #


def test_bobot_klines_mengikuti_limit():
    assert bobot_permintaan(_PATH_KLINES, {"limit": 5}) == 1
    assert bobot_permintaan(_PATH_KLINES, {"limit": 200}) == 2
    assert bobot_permintaan(_PATH_KLINES, {"limit": 1000}) == 5


def test_bobot_ticker_24jam_tanpa_simbol_mahal():
    assert bobot_permintaan(_PATH_TICKER_24J, {}) == 40
    assert bobot_permintaan(_PATH_TICKER_24J, {"symbol": "BTCUSDT"}) == 1


def test_bobot_depth_mengikuti_limit():
    assert bobot_permintaan(_PATH_DEPTH, {"limit": 20}) == 2
    assert bobot_permintaan(_PATH_DEPTH, {"limit": 100}) == 5


def test_ms_ban_dari_pesan_membaca_epoch():
    pesan = (
        "Way too many requests; IP(130.176.187.110) banned until 1785848930502. "
        "Please use the websocket for live updates to avoid bans."
    )
    assert ms_ban_dari_pesan(pesan) == 1785848930502
    assert ms_ban_dari_pesan("tanpa angka") is None
    assert ms_ban_dari_pesan("") is None


def test_pengatur_laju_menahan_saat_budget_habis():
    jam = [0.0]
    tidur_tercatat = []

    def tidur(detik):
        tidur_tercatat.append(detik)
        jam[0] += detik

    laju = PengaturLaju(budget_per_menit=10, jam=lambda: jam[0], tidur=tidur)
    assert laju.ambil(6) == 0.0  # muat, tidak menahan
    tertahan = laju.ambil(6)  # tidak muat -> wajib menahan
    assert tertahan > 0.0
    assert tidur_tercatat


def test_pengatur_laju_menolak_budget_tidak_sah():
    for nilai in (0, -1):
        try:
            PengaturLaju(budget_per_menit=nilai)
        except ValueError:
            continue
        raise AssertionError(f"budget {nilai} seharusnya ditolak")


# --------------------------------------------------------------------------- #
# 3. client: ban, cache, dedupe
# --------------------------------------------------------------------------- #


def test_ban_418_menahan_permintaan_berikutnya_tanpa_ke_jaringan():
    hitung = []
    client = BinanceFuturesClient(
        _kredensial(),
        jam_ms=lambda: 1_785_848_000_000,
        pembuka_url=_pembuka_418(
            "Way too many requests; IP(130.176.187.110) banned until 1785848930502. "
            "Please use the websocket for live updates to avoid bans.",
            hitung,
        ),
    )
    try:
        client.waktu_server()
    except BinanceAPIError as exc:
        assert exc.status == 418
    else:
        raise AssertionError("418 seharusnya dilempar")

    assert len(hitung) == 1
    assert client.banned_sampai_ms == 1785848930502
    assert client.sisa_ban_ms() == 930_502

    # permintaan kedua HARUS ditahan lokal: menembak lagi memperpanjang ban
    try:
        client.harga_sekarang("BTCUSDT")
    except BinanceAPIError as exc:
        assert exc.kode == -1003
    else:
        raise AssertionError("permintaan saat ban seharusnya ditahan")
    assert len(hitung) == 1, "tidak boleh ada permintaan jaringan selama ban"


def test_ban_kedaluwarsa_membuka_kembali_permintaan():
    jam = [1_785_848_000_000]
    hitung = []
    client = BinanceFuturesClient(
        _kredensial(),
        jam_ms=lambda: jam[0],
        pembuka_url=_pembuka_418("banned until 1785848930502.", hitung),
    )
    try:
        client.waktu_server()
    except BinanceAPIError:
        pass
    assert client.sisa_ban_ms() > 0
    jam[0] = 1785848930503  # ban sudah lewat
    assert client.sisa_ban_ms() == 0
    assert client.banned_sampai_ms == 0


def test_ban_tanpa_epoch_terbaca_tetap_memicu_jeda_aman():
    """Jika Binance mengubah teks pesannya, jangan sampai kita menembak lagi.

    Ini menjawab "apa yang terjadi jika API mengembalikan data yang tidak
    sesuai": pengurai gagal, tapi sistem HARUS tetap menahan diri.
    """
    hitung = []
    client = BinanceFuturesClient(
        _kredensial(),
        jam_ms=lambda: 1_785_848_000_000,
        pembuka_url=_pembuka_418("Way too many requests. Slow down.", hitung),
    )
    try:
        client.waktu_server()
    except BinanceAPIError:
        pass
    assert client.sisa_ban_ms() > 0, "pesan tak terbaca tetap harus menahan permintaan"
    try:
        client.harga_sekarang("BTCUSDT")
    except BinanceAPIError:
        pass
    assert len(hitung) == 1, "tidak boleh ada permintaan tambahan"


def test_exchange_info_di_cache_tidak_menembak_berulang():
    hitung = []
    client = BinanceFuturesClient(
        _kredensial(), pembuka_url=_pembuka({"symbols": [{"symbol": "BTCUSDT"}]}, hitung)
    )
    a = client.exchange_info("BTCUSDT")
    b = client.exchange_info("BTCUSDT")
    assert a == b
    assert len(hitung) == 1, "87 runner tidak boleh jadi 87 panggilan exchangeInfo"


def test_klines_dedupe_dalam_ttl_pendek():
    hitung = []
    client = BinanceFuturesClient(_kredensial(), pembuka_url=_pembuka([[1, 2]], hitung))
    client.klines("BTCUSDT", "15m", limit=5)
    client.klines("BTCUSDT", "15m", limit=5)
    assert len(hitung) == 1, "dua runner berbagi TF konteks tidak boleh menarik dua kali"
    client.klines("BTCUSDT", "5m", limit=5)
    assert len(hitung) == 2, "TF berbeda tetap harus ditarik"


def test_klines_ttl_nol_selalu_menembak():
    hitung = []
    client = BinanceFuturesClient(_kredensial(), pembuka_url=_pembuka([[1, 2]], hitung))
    client.klines("BTCUSDT", "15m", limit=5, ttl_detik=0)
    client.klines("BTCUSDT", "15m", limit=5, ttl_detik=0)
    assert len(hitung) == 2


def test_waktu_server_di_cache_lalu_diekstrapolasi():
    hitung = []
    mono = [100.0]
    client = BinanceFuturesClient(
        _kredensial(),
        pembuka_url=_pembuka({"serverTime": 1_700_000_000_000}, hitung),
        jam_mono=lambda: mono[0],
    )
    assert client.waktu_server() == 1_700_000_000_000
    mono[0] = 102.0  # 2 detik berlalu
    assert client.waktu_server() == 1_700_000_002_000
    assert len(hitung) == 1


def test_sinkron_waktu_selalu_memaksa_panggilan_nyata():
    """Tanda tangan tidak boleh memakai waktu hasil ekstrapolasi."""
    hitung = []
    client = BinanceFuturesClient(
        _kredensial(),
        jam_ms=lambda: 1_699_999_999_000,
        pembuka_url=_pembuka({"serverTime": 1_700_000_000_000}, hitung),
    )
    client.waktu_server()
    client.sinkron_waktu()
    assert len(hitung) == 2


# --------------------------------------------------------------------------- #
# 4. penjadwalan runner di mesin multi-pair
# --------------------------------------------------------------------------- #


def _mesin_palsu(interval=15.0):
    """Stub seringan mungkin: hanya atribut yang benar-benar dipakai metode uji.

    Metode diuji sebagai fungsi tak-terikat agar tidak perlu membangun engine
    penuh (yang butuh client + pemindai sungguhan).
    """
    return types.SimpleNamespace(
        interval_poll_detik=interval,
        _jatuh_tempo={},
        _ada_eksekusi_menggantung=MesinMultiPair._ada_eksekusi_menggantung,
    )


def test_tempo_berikut_mengikuti_batas_tutup_bar():
    mesin = _mesin_palsu()
    satu_menit = 60_000
    sekarang = 10 * satu_menit + 5_000
    tempo = MesinMultiPair._tempo_berikut(mesin, "1m", sekarang)
    assert tempo == 11 * satu_menit + JEDA_SETELAH_BAR_MS

    tempo15 = MesinMultiPair._tempo_berikut(mesin, "15m", sekarang)
    assert tempo15 == 15 * satu_menit + JEDA_SETELAH_BAR_MS
    assert tempo15 > tempo, "runner 15m harus lebih jarang daripada 1m"


def test_tempo_berikut_tf_tidak_dikenal_pakai_interval_poll():
    mesin = _mesin_palsu(interval=20.0)
    tempo = MesinMultiPair._tempo_berikut(mesin, "tf-ngawur", 1_000)
    assert tempo == 1_000 + 20_000


def test_runner_dilewati_sebelum_barnya_tutup():
    mesin = _mesin_palsu()
    runner = types.SimpleNamespace(_pending_entry={}, _bracket_aktif={})
    kunci = ("BTCUSDT", "15m")
    assert MesinMultiPair._perlu_jalan(mesin, kunci, runner, 1_000) is True  # pertama kali
    mesin._jatuh_tempo[kunci] = 900_000
    assert MesinMultiPair._perlu_jalan(mesin, kunci, runner, 100_000) is False
    assert MesinMultiPair._perlu_jalan(mesin, kunci, runner, 900_000) is True


def test_runner_dengan_posisi_terbuka_selalu_dipoll():
    """Penghematan rate-limit tidak boleh mengorbankan pemantauan SL/TP."""
    mesin = _mesin_palsu()
    kunci = ("BTCUSDT", "15m")
    mesin._jatuh_tempo[kunci] = 10**12  # jadwal masih jauh

    pending = types.SimpleNamespace(_pending_entry={1: object()}, _bracket_aktif={})
    assert MesinMultiPair._perlu_jalan(mesin, kunci, pending, 1_000) is True

    bracket = types.SimpleNamespace(_pending_entry={}, _bracket_aktif={"BTCUSDT": object()})
    assert MesinMultiPair._perlu_jalan(mesin, kunci, bracket, 1_000) is True


def test_sisa_ban_ms_tahan_client_tanpa_dukungan():
    mesin = types.SimpleNamespace(client=types.SimpleNamespace())
    assert MesinMultiPair._sisa_ban_ms(mesin) == 0

    def meledak():
        raise RuntimeError("client cacat")

    mesin2 = types.SimpleNamespace(client=types.SimpleNamespace(sisa_ban_ms=meledak))
    assert MesinMultiPair._sisa_ban_ms(mesin2) == 0

    mesin3 = types.SimpleNamespace(client=types.SimpleNamespace(sisa_ban_ms=lambda: 5_000))
    assert MesinMultiPair._sisa_ban_ms(mesin3) == 5_000
