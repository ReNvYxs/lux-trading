"""L6 - Notifikasi/monitoring keluar (Telegram).

Lapisan ini SENGAJA dibuat pasif: kegagalan mengirim notifikasi TIDAK BOLEH
menjatuhkan proses trading. Semua pengirim mengembalikan bool/None, tidak
melempar ke pemanggil (lihat NotifierTelegram.kirim).
"""
from .telegram import NotifierNonaktif, NotifierTelegram, buat_notifier

__all__ = ["NotifierTelegram", "NotifierNonaktif", "buat_notifier"]
