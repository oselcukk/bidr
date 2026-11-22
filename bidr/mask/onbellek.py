"""Maskeleme önbelleği: içerik adresli SQLite (`<çalışma alanı>/.cache/maske.sqlite`).

Anahtar her zaman içeriğin sha256'sı + işi etkileyen her şey (araç sürümü, dil, DPI/görüntü boyutu,
kural sürümü, ayarlar); dosya adı ya da zaman anahtara girmez. Katmanlar:

- `donusum`: eski biçim dönüşümü (kaynak dosya sha256 + yöntem + sürüm → çevrilmiş dosya baytları);
- `ocr`: OCR kelimeleri (sayfa görüntüsü PNG sha256 + tesseract sürümü + dil + psm → TSV);
- `aday`: dosya düzeyinde maskeleme sonucu (kaynak sha256 + kural sürümü + kural parmak izi + motor +
  o dosyaya ait insan kararları + model metni → kayıt + maskeli kopya baytları).

Kural değişince yalnız `aday` katmanı ıskalar: sayfa görüntüleri aynı kaldığı için OCR yeniden
çalışmaz. Değişmeyen dosya yeniden işlenmez (`aday` isabeti). Önbellek yalnız hızlandırır: silinirse
sonuç değişmez. Değerler (kişisel veri dahil OCR metni) çalışma alanında kalır; çalışma alanı zaten
kanıtların kendisini tutar.

Çok süreçli kullanım: her süreç kendi bağlantısını açar (WAL, meşgul bekleme). Etkin önbellek ortam
değişkeniyle (`BIDR_MASKE_ONBELLEK`) alt süreçlere geçer.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path

ENV = "BIDR_MASKE_ONBELLEK"
DOSYA = ".cache/maske.sqlite"
SEMA = 1

_LOCK = threading.Lock()
_ACIK: dict[str, "Onbellek"] = {}
SAYAC: Counter = Counter()               # süreç içi isabet/ıska ("ocr:isabet" …): testler ve rapor için


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def anahtar(*parts) -> str:
    """Parçalardan kararlı anahtar (JSON → sha256)."""
    return sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))


class Onbellek:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = None
        self._pid = None

    def _c(self) -> sqlite3.Connection:
        if self._con is None or self._pid != os.getpid():
            con = sqlite3.connect(str(self.path), timeout=60, isolation_level=None, check_same_thread=False)
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            con.execute("PRAGMA synchronous=NORMAL")
            con.execute("CREATE TABLE IF NOT EXISTS k (katman TEXT, anahtar TEXT, deger BLOB, zaman REAL, "
                        "PRIMARY KEY (katman, anahtar))")
            con.execute("CREATE TABLE IF NOT EXISTS meta (ad TEXT PRIMARY KEY, deger TEXT)")
            con.execute("INSERT OR IGNORE INTO meta VALUES ('sema', ?)", (str(SEMA),))
            self._con, self._pid = con, os.getpid()
        return self._con

    def get(self, katman: str, key: str) -> bytes | None:
        try:
            with _LOCK:
                row = self._c().execute("SELECT deger FROM k WHERE katman=? AND anahtar=?", (katman, key)).fetchone()
        except sqlite3.Error:
            row = None
        SAYAC[f"{katman}:{'isabet' if row else 'iska'}"] += 1
        return bytes(row[0]) if row else None

    def put(self, katman: str, key: str, value: bytes) -> None:
        for _ in range(3):
            try:
                with _LOCK:
                    self._c().execute("INSERT OR REPLACE INTO k VALUES (?, ?, ?, ?)",
                                      (katman, key, sqlite3.Binary(value), time.time()))
                return
            except sqlite3.OperationalError:          # kilit: kısa bekle, yeniden dene
                time.sleep(0.2)
            except sqlite3.Error:
                return

    def get_json(self, katman: str, key: str):
        b = self.get(katman, key)
        if b is None:
            return None
        try:
            return json.loads(b.decode("utf-8"))
        except ValueError:
            return None

    def put_json(self, katman: str, key: str, value) -> None:
        self.put(katman, key, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def close(self) -> None:
        if self._con is not None:
            try:
                self._con.close()
            except sqlite3.Error:
                pass
            self._con = None


def ac(ws: Path | None) -> Onbellek | None:
    """Çalışma alanının önbelleğini etkinleştirir (alt süreçler ortamdan devralır). `ws` None: kapat."""
    if ws is None:
        os.environ.pop(ENV, None)
        return None
    os.environ["BIDR_MASKE_WS"] = str(Path(ws).resolve())    # m3 form şablon belleği (raster._sablonlar)
    p = (Path(ws) / DOSYA).resolve()
    os.environ[ENV] = str(p)
    return aktif()


def aktif() -> Onbellek | None:
    p = os.environ.get(ENV)
    if not p:
        return None
    ob = _ACIK.get(p)
    if ob is None:
        try:
            ob = _ACIK[p] = Onbellek(Path(p))
        except OSError:
            return None
    return ob
