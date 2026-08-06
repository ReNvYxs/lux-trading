"""Saklar .env pemilih lapisan eksekusi. Default TETAP lapisan lama.

  LUX_EKSEKUSI=lama   (default) -> perilaku tidak berubah sama sekali
  LUX_EKSEKUSI=aman             -> lapisan tervalidasi testnet:
                                   TP = LIMIT reduceOnly di bursa,
                                   SL = dipantau perangkat lunak,
                                   gagal pasang proteksi = posisi DITUTUP.

Nilai yang tidak dikenal jatuh ke 'lama'. Saklar tidak boleh jadi sumber
kejutan baru.

BATAS YANG DIAKUI JUJUR: bila kegagalan terjadi SEBELUM objek Proteksi sempat
dibuat (misal exchange_info gagal), fungsi ini tidak punya pegangan untuk
menutup posisi. Kasus itu dilaporkan lewat kunci 'gagal' tanpa klaim bahwa
posisi sudah aman.
"""
import os

MODE_LAMA = "lama"
MODE_AMAN = "aman"
ENV_NAMA = "LUX_EKSEKUSI"


def mode_eksekusi(env=None):
    sumber = os.environ if env is None else env
    nilai = str(sumber.get(ENV_NAMA, MODE_LAMA) or MODE_LAMA).strip().lower()
    return MODE_AMAN if nilai == MODE_AMAN else MODE_LAMA


def aman_aktif(env=None):
    return mode_eksekusi(env) == MODE_AMAN


def pasang_proteksi_aman(klien, simbol, arah, tp_harga, sl_harga, log=None,
                         spek=None, pengirim=None, data=None, tidur=None,
                         ember=None):
    """Pasang proteksi lewat lapisan aman. Selalu mengembalikan dict, tidak
    pernah melempar: pemanggil di jalur live tidak boleh gagal karena ini.
    """
    from .inti import DataPasar, GagalProteksi, PengirimOrder, Proteksi, SpekSimbol

    log = log if log is not None else []
    hasil = {"mode": MODE_AMAN, "log": log, "gagal": None, "arah": arah}
    proteksi = None
    try:
        spek = spek or SpekSimbol.dari_exchange_info(
            klien.exchange_info(simbol), simbol)
        data = data or DataPasar(klien)
        pengirim = pengirim or PengirimOrder(klien, log=log, tidur=tidur)
        proteksi = Proteksi(klien, pengirim, spek, simbol, data=data, log=log,
                            tidur=tidur)
        hasil.update(proteksi.pasang(tp_harga, sl_harga, ember))
        hasil["proteksi"] = proteksi
        return hasil
    except GagalProteksi as exc:
        hasil["gagal"] = str(exc)
        hasil["posisi_ditutup"] = True
        hasil["proteksi"] = proteksi
        return hasil
    except Exception as exc:  # noqa: BLE001
        hasil["gagal"] = type(exc).__name__ + ": " + str(exc)
        hasil["proteksi"] = proteksi
        if proteksi is not None:
            try:
                failsafe = proteksi.tutup_posisi("galat_tak_terduga", ember)
                hasil["failsafe"] = failsafe
                hasil["posisi_ditutup"] = bool(failsafe.get("bersih"))
            except Exception as exc2:  # noqa: BLE001
                hasil["failsafe_gagal"] = str(exc2)
        return hasil
