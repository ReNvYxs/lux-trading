"""Notifier Telegram - event-driven, stdlib murni (urllib).

Event yang dikirim (hanya scalp/intraday yang benar-benar di-entry):
  lapor_entry_dikirim   - saat entry LIMIT GTX terisi langsung atau bracket aktif
  lapor_entry_terisi    - saat entry pending terkonfirmasi FILLED di poll berikutnya
  lapor_sl_tertrigger   - saat SL (STOP_MARKET) tertrigger di bursa
  lapor_tp_tertrigger   - saat TP (TAKE_PROFIT_MARKET) tertrigger di bursa
  lapor_sinyal_swing    - NO-OP: swing signal-only, hanya ke dashboard
  lapor_sinyal_tertolak - NO-OP: ditolak governor, hanya ke dashboard

Aturan operator (Message 41, 4 Agu 2026):
- Telegram = hanya scalp/intraday yang benar-benar di-entry
- Swing dan sinyal tertolak = dashboard saja, TIDAK ke Telegram
- Kegagalan notifikasi tidak pernah menjatuhkan proses trading
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

API_BASIS = "https://api.telegram.org"
TIMEOUT_DETIK = 10.0
BATAS_KARAKTER = 4000


class NotifierNonaktif:
    """Objek null: dipakai bila Telegram tidak dikonfigurasi. Selalu no-op."""
    aktif = False

    def kirim(self, teks: str) -> bool:
        return False

    def lapor_siklus(self, ringkas: Dict[str, Any], simbol: str = "", mode: str = "") -> bool:
        return False

    def lapor_entry_dikirim(self, **kwargs: Any) -> bool:
        return False

    def lapor_entry_terisi(self, **kwargs: Any) -> bool:
        return False

    def lapor_sl_tertrigger(self, **kwargs: Any) -> bool:
        return False

    def lapor_tp_tertrigger(self, **kwargs: Any) -> bool:
        return False

    def lapor_sinyal_swing(self, **kwargs: Any) -> bool:
        return False

    def lapor_sinyal_tertolak(self, **kwargs: Any) -> bool:
        return False

    def uji_koneksi(self) -> Dict[str, Any]:
        return {"ok": False, "alasan": "Telegram tidak dikonfigurasi (token/chat_id kosong)"}


class NotifierTelegram:
    """Pengirim pesan Telegram lewat Bot API sendMessage."""
    aktif = True

    def __init__(self, token: str, chat_id: str, timeout: float = TIMEOUT_DETIK) -> None:
        if not token or not chat_id:
            raise ValueError("NotifierTelegram butuh token DAN chat_id yang tidak kosong")
        self._token = token
        self.chat_id = str(chat_id)
        self.timeout = float(timeout)

    def _url(self, metode: str) -> str:
        return f"{API_BASIS}/bot{self._token}/{metode}"

    def _panggil(self, metode: str, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        req = urllib.request.Request(
            self._url(metode), data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def kirim(self, teks: str) -> bool:
        """Kirim satu pesan. Mengembalikan True bila Telegram menjawab ok."""
        if not teks:
            return False
        potong = teks if len(teks) <= BATAS_KARAKTER else teks[:BATAS_KARAKTER - 3] + "..."
        try:
            jawab = self._panggil(
                "sendMessage",
                {"chat_id": self.chat_id, "text": potong, "disable_web_page_preview": "true"},
            )
            if not jawab.get("ok"):
                print(f"[telegram] ditolak API: {jawab.get('description')}", file=sys.stderr)
                return False
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
            print(f"[telegram] gagal kirim (diabaikan, trading lanjut): {exc}", file=sys.stderr)
            return False

    # ---------------------------------------------------------------- #
    # event-driven methods
    # ---------------------------------------------------------------- #

    def lapor_entry_dikirim(
        self,
        simbol: str,
        arah: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        qty: float,
        strategi: str = "",
        skor: float = 0.0,
        horizon: str = "",
        **_: Any,
    ) -> bool:
        """Entry scalp/intraday ter-trigger dan order dikirim ke bursa."""
        rr = _hitung_rr(arah, entry_price, sl_price, tp_price)
        icon = "\U0001f7e2" if arah == "LONG" else "\U0001f534"
        baris = [
            f"{icon} ENTRY {'LONG' if arah == 'LONG' else 'SHORT'} | {simbol}",
            f"Strategi  : {strategi or '-'} (skor {skor:.1f})",
            f"Horizon   : {horizon or '-'}",
            f"Entry     : {entry_price:,.4f}",
            f"Stop Loss : {sl_price:,.4f}",
        ]
        if tp_price:
            baris.append(f"Take Profit: {tp_price:,.4f}")
        baris += [
            f"Qty       : {qty}",
            f"R:R       : {rr}" if rr else "",
        ]
        return self.kirim("\n".join(b for b in baris if b))

    def lapor_entry_terisi(
        self,
        simbol: str,
        arah: str,
        entry_price: float,
        sl_price: float,
        tp_price: float,
        qty: float,
        strategi: str = "",
        skor: float = 0.0,
        **_: Any,
    ) -> bool:
        """Entry pending terkonfirmasi FILLED (poll berikutnya)."""
        rr = _hitung_rr(arah, entry_price, sl_price, tp_price)
        baris = [
            f"\u2705 ENTRY TERISI | {simbol}",
            f"Strategi  : {strategi or '-'}",
            f"Avg Fill  : {entry_price:,.4f}",
            f"SL Aktif  : {sl_price:,.4f}",
        ]
        if tp_price:
            baris.append(f"TP Aktif  : {tp_price:,.4f}")
        baris += [
            f"Qty       : {qty}",
            f"R:R       : {rr}" if rr else "",
        ]
        return self.kirim("\n".join(b for b in baris if b))

    def lapor_sl_tertrigger(
        self,
        simbol: str,
        arah: str,
        sl_price: float,
        qty: float,
        strategi: str = "",
        **_: Any,
    ) -> bool:
        """Stop loss tertrigger di bursa."""
        baris = [
            f"\U0001f534 SL TER-TRIGGER | {simbol}",
            f"Arah      : {arah}",
            f"Stop Loss : {sl_price:,.4f}",
            f"Qty       : {qty}",
            f"Strategi  : {strategi or '-'}",
        ]
        return self.kirim("\n".join(baris))

    def lapor_tp_tertrigger(
        self,
        simbol: str,
        arah: str,
        tp_price: float,
        qty: float,
        strategi: str = "",
        **_: Any,
    ) -> bool:
        """Take profit tertrigger di bursa."""
        baris = [
            f"\U0001f7e2 TP TER-TRIGGER \U0001f3af | {simbol}",
            f"Arah      : {arah}",
            f"Take Profit: {tp_price:,.4f}",
            f"Qty       : {qty}",
            f"Strategi  : {strategi or '-'}",
        ]
        return self.kirim("\n".join(baris))

    def lapor_sinyal_swing(self, **_: Any) -> bool:
        """Sinyal swing - NO-OP. Hanya ke dashboard, tidak ke Telegram."""
        return False

    def lapor_sinyal_tertolak(self, **_: Any) -> bool:
        """Sinyal tertolak governor - NO-OP. Hanya ke dashboard."""
        return False

    # ---------------------------------------------------------------- #
    # backward-compat
    # ---------------------------------------------------------------- #

    def lapor_siklus(
        self, ringkas: Dict[str, Any], simbol: str = "", mode: str = ""
    ) -> bool:
        teks = format_siklus(ringkas, simbol=simbol, mode=mode)
        if not teks:
            return False
        return self.kirim(teks)

    def uji_koneksi(self) -> Dict[str, Any]:
        try:
            jawab = self._panggil("getMe", {})
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "alasan": f"tidak bisa menghubungi Telegram: {exc}"}
        if not jawab.get("ok"):
            return {"ok": False, "alasan": f"token ditolak: {jawab.get('description')}"}
        nama_bot = (jawab.get("result") or {}).get("username", "?")
        terkirim = self.kirim(
            "\U0001f916 LUX modul trading: uji koneksi BERHASIL.\n"
            "Notifikasi real-time Entry/TP/SL akan dikirim ke chat ini."
        )
        return {
            "ok": bool(terkirim),
            "bot": nama_bot,
            "alasan": "" if terkirim else "getMe ok, tapi sendMessage gagal - periksa chat_id",
        }


# ---------------------------------------------------------------- #
# helpers
# ---------------------------------------------------------------- #

def _hitung_rr(arah: str, entry: float, sl: float, tp: float) -> str:
    try:
        if not (entry and sl and tp):
            return ""
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0:
            return ""
        return f"1:{reward / risk:.2f}"
    except Exception:  # noqa: BLE001
        return ""


def format_siklus(ringkas: Dict[str, Any], simbol: str = "", mode: str = "") -> str:
    """Ubah SiklusHasil.ringkas() jadi teks. Kembalikan '' bila tidak perlu dikirim."""
    galat = ringkas.get("galat")
    hasil_bar = ringkas.get("hasil_bar") or {}
    eksekusi = ringkas.get("eksekusi_entry")
    order_sl = ringkas.get("order_sl")

    if not galat and not eksekusi and not hasil_bar:
        return ""

    kepala = f"[LUX {mode or '?'}] {simbol or '?'}"
    baris = [kepala]

    if galat:
        baris.append(f"GALAT: {galat}")
    if hasil_bar:
        pemenang = hasil_bar.get("pemenang") or hasil_bar.get("strategi")
        skor = hasil_bar.get("skor")
        mode_bar = hasil_bar.get("mode")
        alasan = hasil_bar.get("alasan") or hasil_bar.get("alasan_tolak")
        if pemenang:
            baris.append(f"sinyal: {pemenang} (skor {skor}, mode {mode_bar})")
        elif alasan:
            baris.append(f"tidak ada entry: {alasan}")
        arah = hasil_bar.get("arah")
        entry = hasil_bar.get("entry")
        sl = hasil_bar.get("sl")
        if arah is not None and entry is not None:
            baris.append(f"arah={arah} entry={entry} sl={sl}")
    if eksekusi:
        baris.append(
            "eksekusi: qty_terisi={qty} slice_terkirim={n} {alasan}".format(
                qty=eksekusi.get("qty_terisi"),
                n=eksekusi.get("terkirim"),
                alasan=eksekusi.get("alasan_batal") or "",
            ).strip()
        )
    if order_sl:
        baris.append(f"SL: {json.dumps(order_sl, ensure_ascii=False)[:200]}")

    return "\n".join(baris)


def buat_notifier(cfg: Optional[Any] = None) -> Any:
    """Pabrik: kembalikan NotifierTelegram bila lengkap, selain itu NotifierNonaktif."""
    if cfg is None:
        from ..konfigurasi import muat_konfigurasi
        cfg = muat_konfigurasi()
    if not getattr(cfg, "telegram_lengkap", lambda: False)():
        return NotifierNonaktif()
    return NotifierTelegram(cfg.telegram_bot_token, cfg.telegram_chat_id)
