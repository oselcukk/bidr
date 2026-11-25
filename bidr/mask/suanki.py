"""Kaynak maskelemesinde o an işlenen belgeler (`maskeleme-ilerleme.json` içindeki `suanki` alanı).

İşçi süreçler (ProcessPoolExecutor) ilerleme dosyasına doğrudan yazmaz: her süreç kendi küçük durum dosyasını
(`<dizin>/<pid>.json`: {dosya, sayfa, toplam_sayfa, asama}) yazar; ana süreçteki `Izleyici` iş parçacığı bu
dosyaları birkaç saniyede bir okuyup ilerleme dosyasını (değiştiyse) yeniden yazar. Böylece uzun süren tek bir
belge (ör. 170 sayfalık PDF) bitmeden de hangi belgenin hangi sayfasında olunduğu görünür.

Sayfa bildirimi (`sayfa`) sık çağrılabilir; diske en çok `ARALIK` saniyede bir yazılır. Dizin ortamda
(`BIDR_MASKE_SUANKI`) yoksa her çağrı hiçbir şey yapmaz (tek dosya maskelemesi, testler)."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ENV = "BIDR_MASKE_SUANKI"
ARALIK = 2.0                 # saniye: işçi durum dosyası ve ilerleme dosyası en çok bu sıklıkta yazılır

_durum: dict = {}
_son = 0.0
_metinler: dict | None = None     # metin kaydı (`metin_kaydi_baslat`): bu süreçte taramaya giren metinler (sıralı küme)


def _dizin() -> Path | None:
    d = os.environ.get(ENV)
    return Path(d) if d else None


def _yaz(zorla: bool = False) -> None:
    global _son
    d = _dizin()
    if d is None:
        return
    simdi = time.monotonic()
    if not zorla and simdi - _son < ARALIK:
        return
    _son = simdi
    p = d / f"{os.getpid()}.json"
    try:
        if not _durum:
            p.unlink(missing_ok=True)
            return
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(_durum, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def basla(dosya: str) -> None:
    """Bu süreçte `dosya` (kaynak köküne göre göreli yol) işlenmeye başladı."""
    _durum.clear()
    _durum["dosya"] = dosya
    _yaz(zorla=True)


def sayfa(n: int, toplam: int, asama: str = "maskeleme") -> None:
    """İşlenen belgenin `n`. sayfasına (1'den) geçildi. `asama`: "maskeleme" ya da "denetim"."""
    if "dosya" not in _durum:
        return
    yeni = _durum.get("asama") != asama          # belgenin ilk sayfası ya da yeni aşama: hemen görünsün
    _durum.update(sayfa=int(n), toplam_sayfa=int(toplam), asama=asama)
    _yaz(zorla=yeni)


def metin_kaydi_baslat() -> dict | None:
    """Bu süreçte kişisel veri taramasına (`detect.detect`) giren metinleri kaydetmeye başla → önceki kayıt
    (`metin_kaydi_bitir`e geri verilir). Kayıt, belgenin "ad metni"dir (`kaynak.ad_metni_*`): ad listesine sonradan
    eklenen ad bu metinlerin hiçbirinde geçmiyorsa belgenin sonucu o addan bağımsızdır (yeniden işlenmez)."""
    global _metinler
    once, _metinler = _metinler, {}
    return once


def metin_kaydi_bitir(once: dict | None = None) -> list[str]:
    """Kaydı bitir → kaydedilen metinler (ilk görülme sırasıyla); önceki kayıt (varsa) bunları da içerir."""
    global _metinler
    kayit, _metinler = _metinler or {}, once
    if once is not None:
        once.update(kayit)
    return list(kayit)


def metin(t: str) -> None:
    """Taramaya giren metin (kayıt açıksa kaydedilir; değilse hiçbir şey yapmaz). Sonucu etkilemez."""
    if _metinler is not None and t:
        _metinler[t] = None


def bitir() -> None:
    _durum.clear()
    _yaz(zorla=True)


def oku(d: Path) -> list[dict]:
    """Dizindeki işçi durumları (dosya adına göre sıralı; bozuk/yarım dosya atlanır)."""
    out = []
    try:
        ps = sorted(d.glob("*.json"))
    except OSError:
        return out
    for p in ps:
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and j.get("dosya"):
            out.append({k: j[k] for k in ("dosya", "sayfa", "toplam_sayfa", "asama") if k in j})
    return sorted(out, key=lambda r: r["dosya"])


class Izleyici:
    """Ana süreçte: ilerleme dosyasını `yaz(suanki=…, **son_alan)` ile, işçi durumları değiştikçe en çok `aralik`
    saniyede bir yeniden yazar (`son_alan`: ana sürecin son `yaz` çağrısının alanları: durum, toplam, biten…)."""

    def __init__(self, d: Path, yaz, aralik: float | None = None):
        self.d, self._yaz, self.aralik = d, yaz, ARALIK if aralik is None else aralik
        self._dur = threading.Event()
        self._kilit = threading.Lock()
        self._onceki: list[dict] | None = None
        self._alan: dict = {}
        self._t = threading.Thread(target=self._dongu, name="bidr-maske-suanki", daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._dur.set()
        self._t.join(timeout=5)

    def yaz(self, **alan) -> None:
        """Ana sürecin kendi yazımı (belge bitti): güncel `suanki` ile birlikte, kilit altında."""
        with self._kilit:
            self._alan = dict(alan)
            s = oku(self.d)
            self._onceki = s
            self._yaz(suanki=s, **alan)

    def _dongu(self) -> None:
        while not self._dur.wait(self.aralik):
            with self._kilit:
                s = oku(self.d)
                if s != self._onceki and self._alan:
                    self._onceki = s
                    self._yaz(suanki=s, **self._alan)
