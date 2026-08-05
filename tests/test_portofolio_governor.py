"""Uji governor portofolio: batas 4 posisi, minimum free margin, antrean global.

Semua kasus di sini adalah reproduksi langsung dari galat -2019 pada log testnet
operator (4 Agu 2026): banyak runner mengirim order seolah masing-masing punya
seluruh saldo.
"""
from __future__ import annotations

from lux_modul.governor import (
    GovernorPortofolio,
    KandidatEntry,
    KebijakanPortofolio,
    PosisiTerbuka,
    SnapshotAkun,
    TOLAK_ARAH_BERLAWANAN,
    TOLAK_BUKAN_AUTO_ENTRY,
    TOLAK_DUPLIKAT_SIMBOL,
    TOLAK_FREE_MARGIN,
    TOLAK_KUOTA_POSISI,
    margin_dibutuhkan,
    snapshot_dari_akun,
)


def _kandidat(simbol, skor, margin=10.0, tf="15m", horizon="intraday", arah="LONG", **kw):
    return KandidatEntry(
        simbol=simbol,
        arah=arah,
        entry_tf=tf,
        horizon=horizon,
        skor=skor,
        margin_dibutuhkan=margin,
        **kw,
    )


def _gov(snapshot, kebijakan=None):
    g = GovernorPortofolio(kebijakan)
    g.mulai_siklus(snapshot)
    return g


def test_kuota_maksimum_empat_posisi():
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    g.antre_banyak([_kandidat(f"P{i}USDT", skor=90 - i) for i in range(10)])
    hasil = g.putuskan()
    diterima = [h for h in hasil if h.diterima]
    assert len(diterima) == 4
    assert all(h.alasan == TOLAK_KUOTA_POSISI for h in hasil if not h.diterima)


def test_posisi_yang_sudah_terbuka_mengurangi_kuota():
    snap = SnapshotAkun(
        equity=1000.0,
        margin_tersedia=900.0,
        posisi=(PosisiTerbuka("BTCUSDT", "LONG"), PosisiTerbuka("XRPUSDT", "SHORT")),
    )
    g = _gov(snap)
    g.antre_banyak([_kandidat(f"P{i}USDT", skor=90 - i) for i in range(5)])
    assert len([h for h in g.putuskan() if h.diterima]) == 2


def test_urutan_kuota_mengikuti_skor_bukan_urutan_kedatangan():
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    g.antre(_kandidat("SAMPAHUSDT", skor=61))
    g.antre(_kandidat("BTCUSDT", skor=95))
    g.antre(_kandidat("ETHUSDT", skor=88))
    diterima = [h.kandidat.simbol for h in g.putuskan() if h.diterima]
    assert diterima[0] == "BTCUSDT"
    assert diterima[1] == "ETHUSDT"


def test_skor_sama_dipisah_likuiditas_lalu_deterministik():
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0),
             KebijakanPortofolio(maks_posisi=1))
    g.antre(_kandidat("AUSDT", skor=80, skor_likuiditas=0.2))
    g.antre(_kandidat("BUSDT", skor=80, skor_likuiditas=0.9))
    assert [h.kandidat.simbol for h in g.putuskan() if h.diterima] == ["BUSDT"]


def test_hasil_deterministik_tanpa_bergantung_urutan_runner():
    kandidat = [_kandidat(f"P{i}USDT", skor=70.0) for i in range(8)]
    a = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    a.antre_banyak(kandidat)
    b = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    b.antre_banyak(list(reversed(kandidat)))
    assert [h.kandidat.kunci() for h in a.putuskan() if h.diterima] == [
        h.kandidat.kunci() for h in b.putuskan() if h.diterima
    ]


def test_minimum_free_margin_dipertahankan():
    """Inti galat -2019: margin dipakai sampai habis lalu order ditolak bursa."""
    keb = KebijakanPortofolio(min_free_margin_pct=0.30)
    g = _gov(SnapshotAkun(equity=100.0, margin_tersedia=100.0), keb)
    g.antre(_kandidat("AUSDT", skor=95, margin=40.0))
    g.antre(_kandidat("BUSDT", skor=90, margin=40.0))
    hasil = g.putuskan()
    assert hasil[0].diterima and hasil[0].free_margin_setelah == 60.0
    assert not hasil[1].diterima and hasil[1].alasan == TOLAK_FREE_MARGIN


def test_free_margin_tidak_pernah_turun_di_bawah_lantai():
    keb = KebijakanPortofolio(min_free_margin_pct=0.25)
    g = _gov(SnapshotAkun(equity=200.0, margin_tersedia=200.0), keb)
    g.antre_banyak([_kandidat(f"P{i}USDT", skor=90 - i, margin=60.0) for i in range(4)])
    for h in g.putuskan():
        assert h.free_margin_setelah >= 200.0 * 0.25


def test_satu_simbol_tidak_menumpuk_dari_beberapa_tf():
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    g.antre(_kandidat("BTCUSDT", skor=95, tf="15m"))
    g.antre(_kandidat("BTCUSDT", skor=93, tf="1h"))
    g.antre(_kandidat("BTCUSDT", skor=91, tf="4h"))
    hasil = g.putuskan()
    assert len([h for h in hasil if h.diterima]) == 1
    assert hasil[1].alasan == TOLAK_DUPLIKAT_SIMBOL


def test_arah_berlawanan_pada_simbol_yang_sama_ditolak():
    snap = SnapshotAkun(
        equity=1000.0, margin_tersedia=1000.0, posisi=(PosisiTerbuka("BTCUSDT", "LONG"),)
    )
    g = _gov(snap, KebijakanPortofolio(maks_posisi_per_simbol=2))
    g.antre(_kandidat("BTCUSDT", skor=95, arah="SHORT"))
    assert g.putuskan()[0].alasan == TOLAK_ARAH_BERLAWANAN


def test_swing_tidak_pernah_auto_entry():
    """Perintah operator: swing hanya sinyal dashboard."""
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    g.antre(_kandidat("BTCUSDT", skor=99, horizon="swing", tf="4h"))
    hasil = g.putuskan()
    assert not hasil[0].diterima
    assert hasil[0].alasan == TOLAK_BUKAN_AUTO_ENTRY


def test_sinyal_ditolak_tetap_dikembalikan_untuk_dashboard():
    g = _gov(SnapshotAkun(equity=1000.0, margin_tersedia=1000.0))
    g.antre_banyak([_kandidat(f"P{i}USDT", skor=90 - i) for i in range(9)])
    hasil = g.putuskan()
    assert len(hasil) == 9  # tidak ada sinyal yang hilang diam-diam
    ringkas = GovernorPortofolio.ringkas_keputusan(hasil)
    assert ringkas["diterima"] == 4 and ringkas["ditolak"] == 5
    assert ringkas["ditolak_per_alasan"][TOLAK_KUOTA_POSISI] == 5


def test_margin_dibutuhkan_dari_notional_dan_leverage():
    assert margin_dibutuhkan(1000.0, 10) == 100.0
    assert margin_dibutuhkan(1000.0, 0) == 1000.0  # leverage tak sah -> paling aman


def test_snapshot_mengabaikan_posisi_qty_nol():
    saldo = [{"asset": "USDT", "balance": "500.0", "availableBalance": "420.0"}]
    posisi = [
        {"symbol": "BTCUSDT", "positionAmt": "0.000", "entryPrice": "0", "leverage": "10"},
        {"symbol": "XRPUSDT", "positionAmt": "-100", "entryPrice": "0.5", "leverage": "5"},
    ]
    snap = snapshot_dari_akun(saldo, posisi)
    assert snap.equity == 500.0 and snap.margin_tersedia == 420.0
    assert snap.jumlah_posisi == 1
    assert snap.posisi[0].simbol == "XRPUSDT" and snap.posisi[0].arah == "SHORT"
    assert abs(snap.posisi[0].margin - 10.0) < 1e-9


def test_kebijakan_tidak_sah_ditolak():
    for keb in (
        KebijakanPortofolio(maks_posisi=0),
        KebijakanPortofolio(min_free_margin_pct=1.0),
        KebijakanPortofolio(maks_posisi_per_simbol=0),
    ):
        try:
            GovernorPortofolio(keb)
        except ValueError:
            continue
        raise AssertionError(f"kebijakan tidak sah lolos: {keb}")
