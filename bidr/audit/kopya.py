"""Aynı belgenin kopyaları: incelemede tek satır, kanıt olarak bir kez (salt kod, model yok).

Kullanıcı kararı (2026-11-26, "Kopyalar tek belge"): aynı belgenin farklı biçimleri (docx/pdf/…) ve aynı
metnin yeniden kaydedilmiş dosyaları tek belgedir; birbirinin sürümü sayılıp "sürüm doğrulanmalı" diye
sorulmaz. decide'ın mükerrer devri (`bidr/decide/dedup.py`, `mukerrer.durum: devralindi`) bunları karar
öncesinde yakalar; burada karar SONRASI (dedup'sız çalışmış ya da bağı kurulamamış belgeler) aynı ilke
denetimde uygulanır. decide parmak izi girdileri değişmez: yalnız metin (`text/`), envanter yolu ve
documents.jsonl okunur.

Kopya ölçütü (temkinli; `dedup.skeleton` iskeleti: NFKC, küçük harf, aksansız sözcük dizisi):
  - aynı uzantı: iskelet birebir aynı (sıra dahil; tarih, sayı, ders kodu dahil her sözcük);
  - farklı uzantı (biçim kopyası): bir-iki haneli sayılar dışındaki sözcüklerin çoklu kümesi aynı
    (Word'ün otomatik liste numaraları ve sayfa numaraları dışa aktarmada kaybolur; tablo hücre sırası
    değişebilir), metindeki tarihler (`identify.dates.find_dates`) ve belge kimlikleri
    (`identify.versions.head_ids`, bütün metin) aynı, farklı kısa sayı payı ≤ `KISA_SAYI_PAYI`.
Farklı ders, farklı tarih, farklı sözcük → kopya değil. Görsel dosyalar (fotoğraf, taranmış sayfa) bu
yoldan kopya olmaz: metinleri model betimlemesi ya da OCR'dır; iki ayrı fotoğrafın betimlemesi aynı
olabilir (görüntü karşılaştırması decide'ın tarama kopyası yolundadır). Parçalı belge (`parca_grubu`),
insan birim kararı olan belge ve `NEAR_MIN_TOKENS`'tan kısa metin aday olmaz.

Temsilci: PDF önce (biçim sırası `BICIM_SIRA`), sonra kabul edilmiş eşleşmesi çok olan, sonra dosya yolu.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import PurePosixPath
from typing import Callable

KISA_SAYI_PAYI = 0.05          # biçim kopyasında farklı (≤ 2 haneli) sayı sözcüklerinin metne oranı
BICIM_SIRA = {".pdf": 0, ".docx": 1, ".doc": 2, ".odt": 3, ".rtf": 4, ".xlsx": 5, ".xls": 6, ".pptx": 7}


def _ext(path: str | None) -> str:
    return PurePosixPath((path or "").replace("\\", "/")).suffix.lower()


def _kisa(tok: str) -> bool:
    return tok.isdigit() and len(tok) <= 2


class _Ozet:
    def __init__(self, text: str):
        from bidr.decide.dedup import skeleton
        self.text = text
        self.sk = skeleton(text)
        self.uzun = [t for t in self.sk if not _kisa(t)]
        self._ek: tuple | None = None

    def anahtar(self) -> str:
        return hashlib.sha1(" ".join(sorted(self.uzun)).encode()).hexdigest()

    def ek(self) -> tuple:
        """(tarihler, belge kimlikleri): biçim kopyasında ikisi de aynı olmalı."""
        if self._ek is None:
            from bidr.identify.dates import find_dates
            from bidr.identify.text import collapse, fold
            from bidr.identify.versions import head_ids
            self._ek = (frozenset(f.d for f in find_dates(fold(collapse(self.text)))),
                        head_ids(self.text, None))
        return self._ek


def kopya_mi(a: _Ozet, b: _Ozet, ext_a: str, ext_b: str) -> bool:
    if ext_a == ext_b:
        return a.sk == b.sk
    if Counter(a.uzun) != Counter(b.uzun):
        return False
    fark = sum((Counter(t for t in a.sk if _kisa(t)) - Counter(t for t in b.sk if _kisa(t))).values()) \
        + sum((Counter(t for t in b.sk if _kisa(t)) - Counter(t for t in a.sk if _kisa(t))).values())
    if fark > KISA_SAYI_PAYI * max(len(a.sk), len(b.sk)):
        return False
    return a.ek() == b.ek()


def gruplar(adaylar: list[str], docs: dict[str, dict], text: Callable[[str], str | None],
            paths: dict[str, str], kabul: dict[str, int]) -> dict[str, list[str]]:
    """Temsilci → kopyaları (sıralı). `adaylar`: denetlenecek belgeler (ince kaydı olan, insan birim kararı
    olmayan, decide kopyası olmayan); `paths`: doc_id → envanter göreli yolu; `kabul`: doc_id → kabul
    edilmiş eşleşme sayısı (temsilci seçimi). Her kopya temsilciyle doğrudan kopya bağındadır."""
    from bidr.decide.dedup import NEAR_MIN_TOKENS
    from bidr.faaliyet.dosya import gorsel_mi
    oz: dict[str, _Ozet] = {}
    kova: dict[str, list[str]] = {}
    for did in sorted(set(adaylar)):
        if (docs.get(did) or {}).get("parca_grubu") or gorsel_mi(paths.get(did)):
            continue
        t = text(did) or ""
        o = _Ozet(t)
        if len(o.uzun) < NEAR_MIN_TOKENS:
            continue
        oz[did] = o
        kova.setdefault(o.anahtar(), []).append(did)

    def sira(d):
        return (BICIM_SIRA.get(_ext(paths.get(d)), 9), -kabul.get(d, 0), paths.get(d) or "", d)

    out: dict[str, list[str]] = {}
    for uyeler in kova.values():
        kalan = sorted(uyeler, key=sira)
        while len(kalan) > 1:
            rep, *diger = kalan
            ks = [d for d in diger if kopya_mi(oz[rep], oz[d], _ext(paths.get(rep)), _ext(paths.get(d)))]
            if ks:
                out[rep] = sorted(ks)
            kalan = [d for d in diger if d not in ks]
    return out
