"""Kanıt adının belgede dayanağı (model yok). Model adı belgenin tamamını değil bir parçasını
ya da belgede olmayan bir niteliği anlatabilir: derleme PDF'te ilk parçanın adı, "ve Ekleri",
"Derlemesi" gibi. Ad, dosya listesinde değerlendiricinin gördüğü tek bilgidir; yanıltıcı ad
alıntının bağlamını da yanlış kurar.

Denetim ucuz ve sözcük düzeyindedir (yalnız Türkçe metinde; yabancı dildeki belgenin Türkçe
adı sözcük sözcük eşlenemez):
- Belge düzeyi: adın resmî tür sözcüğü (yönerge, yönetmelik, karar, tutanak, esaslar …),
  birim sözcüğü (bölüm, fakülte, senato …), bileşim niteliği (derleme, ekler, belgeler …) ya da
  sayısı (yıl, karar sayısı) belge metninde hiç geçmiyorsa: `tur_yok`, `birim_yok`,
  `nitelik_yok`, `sayi_yok`. Betimleyici türler (rapor, liste, form, anket, yazı, duyuru)
  denetlenmez: belge kendine "rapor" demese de rapordur.
- Yuva düzeyi: adın resmî tür sözcüğü, kabul edilmiş alıntının sayfasında ve çevresinde
  (bir önceki, bir sonraki sayfa; maddeli düzenlemede "Madde N"
  yapısı da yeter) hiç geçmiyorsa o yuva `parca_uyumsuz` olur (derlemenin
  başka parçasından alıntı).

Sonuç adı reddetmez: `dogrulanmali` işaretidir (insan bakar).
"""
from __future__ import annotations

import re

from bidr.llm.quote import _fold_char, verify_quote

STOP = {"ve", "ile", "icin", "de", "da", "bir", "bu", "ait", "olan", "uzerine", "hakkinda",
        "ilgili", "ki", "veya", "ya"}
# Belgenin kendini adlandırdığı resmî türler (katlanmış kök önekleri; ünsüz yumuşaması için
# kısa: tutanak/tutanağı → "tutana").
TUR = ("yonerge", "yonetmeli", "karar", "tutana", "esasla", "esasi", "usul", "protokol",
       "sozlesme", "politika", "genelge")
BIRIM = ("bolum", "fakulte", "senato", "rektorlu", "dekanli", "enstitu", "koordinatorlu",
         "yuksekokul")
# Bileşim nitelikleri: belge kendisi böyle demiyorsa ad eklemez.
NITELIK = ("derleme", "ekler", "ekleri", "belgeler", "toplu", "koleksiyon")
_EK = re.compile(r"\bek\s*[-:.]?\s*\d|\bekler|\bekte\b|\beki\b|\bekleri\b")
_TR_W = re.compile(r"\b(?:ve|bir|bu|ile|icin|olarak|olan|tarafindan|madde)\b")
_EN_W = re.compile(r"\b(?:the|and|of|to|in|for|is|by|with|shall)\b")
SAYFA_ONCE, SAYFA_SONRA = 1, 1
TEK_SAYFA_PENCERE = 3000
# Maddeli düzenleme türleri: alıntının çevresinde "Madde N" yapısı varsa düzenlemenin gövdesidir
# (uzun yönergenin ortasındaki sayfa kendi adını anmayabilir).
MADDELI = ("yonerge", "yonetmeli", "esasla", "esasi", "usul", "genelge")
_MADDE = re.compile(r"\bmadde\s*\d")


def fold(s: str) -> str:
    """Türkçe katlanmış, harf/rakam dışı boşluk; sözcük sınırları korunur."""
    out = []
    for ch in str(s or ""):
        f = _fold_char(ch)
        out.append(f if f else " ")
    return re.sub(r"\s+", " ", "".join(out)).strip()


def turkish(ftext: str) -> bool:
    """Katlanmış metin Türkçe mi (Türkçe işlev sözcükleri İngilizcelerden az değil)."""
    tr = len(_TR_W.findall(ftext))
    return tr > 0 and tr >= len(_EN_W.findall(ftext))


def _prefix(w: str, table) -> str | None:
    return next((p for p in table if w.startswith(p)), None)


def tokens(ad: str) -> list[tuple[str, str, str]]:
    """(katlanmış sözcük, sınıf, aranacak kök) — sınıf: tur | birim | nitelik | sayi | konu."""
    out = []
    for w in fold(ad).split():
        if w in STOP or (len(w) < 2 and not w.isdigit()):
            continue
        if any(c.isdigit() for c in w):
            out.append((w, "sayi", w))
        elif p := _prefix(w, NITELIK):
            out.append((w, "nitelik", p))
        elif p := _prefix(w, TUR):
            out.append((w, "tur", p))
        elif p := _prefix(w, BIRIM):
            out.append((w, "birim", p))
        else:
            out.append((w, "konu", w if len(w) <= 5 else w[:max(5, len(w) - 3)]))
    return out


def _has(stem: str, ftext: str) -> bool:
    return re.search(r"\b" + re.escape(stem), ftext) is not None


def _num_ok(w: str, ftext: str) -> bool:
    runs = [r for r in re.findall(r"\d+", w) if len(r) >= 2]
    return all(re.search(r"(?<!\d)" + r + r"(?!\d)", ftext) for r in runs)


def doc_issues(ad: str, text: str) -> list[str]:
    """Adın tür/birim/nitelik/sayı sözcüklerinden belge metninde hiç geçmeyenler."""
    ft = fold(text)
    if not ft or not turkish(ft):
        return []
    errs: set[str] = set()
    for w, k, stem in tokens(ad):
        if k == "sayi" and not _num_ok(w, ft):
            errs.add("sayi_yok")
        elif k == "nitelik" and not (_has(stem, ft) or (stem.startswith("ek") and _EK.search(ft))):
            errs.add("nitelik_yok")
        elif k in ("tur", "birim") and not _has(stem, ft):
            errs.add(f"{k}_yok")
    return sorted(errs)


def _pages(text: str) -> list[tuple[int, int]]:
    out, a = [], 0
    for m in re.finditer("\f", text):
        out.append((a, m.start()))
        a = m.end()
    out.append((a, len(text)))
    return out


_KOD = re.compile(r"(?<![a-z0-9])([a-z]{2}) ?[-;:]? ?(\d{3,4})(?!\d)")
KOD_BOLGE = 400


def _page_code(page: str) -> str | None:
    """Sayfa başındaki doküman/form kodu (YÖ-0087, FR-0356 …): derlemede parça sınırı."""
    m = _KOD.search(fold(page[:KOD_BOLGE]))
    return f"{m.group(1)}{int(m.group(2))}" if m else None


def quote_window(text: str, quote: str) -> tuple[str, bool] | None:
    """(alıntının çevresi, parça kodlu mu). Çevre: sayfası, bir önceki ve bir sonraki sayfa
    (sayfa sonu yoksa ±3000 karakter). Sayfa başlarında birden çok doküman kodu varsa belge
    bir derlemedir: çevre, alıntı sayfasıyla aynı kodu taşıyan bitişik sayfalardır (parça).
    Alıntı metinde bulunamazsa None."""
    m = verify_quote(quote, text)
    if not m.span:
        return None
    s, e = m.span
    pages = _pages(text)
    if len(pages) == 1:
        return text[max(0, s - TEK_SAYFA_PENCERE):e + TEK_SAYFA_PENCERE], False
    i = next((k for k, (a, b) in enumerate(pages) if a <= s <= b), len(pages) - 1)
    codes = [_page_code(text[a:b]) for a, b in pages]
    own = codes[i]
    if own and len({c for c in codes if c}) > 1:
        lo = hi = i
        while lo > 0 and codes[lo - 1] in (own, None):
            lo -= 1
        while hi < len(pages) - 1 and codes[hi + 1] in (own, None):
            hi += 1
        return text[pages[lo][0]:pages[hi][1]], True
    lo, hi = max(0, i - SAYFA_ONCE), min(len(pages) - 1, i + SAYFA_SONRA)
    return text[pages[lo][0]:pages[hi][1]], False


def slot_issues(ad: str, text: str, quotes: dict[str, str]) -> list[str]:
    """Adın resmî tür sözcüğü alıntının çevresinde hiç geçmeyen yuvalar (`parca_uyumsuz`)."""
    toks = tokens(ad)
    tur = [stem for _, k, stem in toks if k == "tur"]
    konu = [stem for _, k, stem in toks if k == "konu"]
    if not (tur or konu) or not text or not turkish(fold(text)):
        return []
    bad = []
    for yuva, q in quotes.items():
        got = quote_window(text, q or "")
        if got is None:
            continue
        fw, parca = fold(got[0]), got[1]
        if not turkish(fw):
            continue
        tur_ok = not tur or any(_has(t, fw) or (not parca and t in MADDELI and _MADDE.search(fw))
                                for t in tur)
        # kodlu derlemede parçanın konusu da adla örtüşmeli (konu sözcüklerinin yarısından çoğu)
        konu_ok = not (parca and len(konu) >= 2) or sum(_has(k, fw) for k in konu) * 2 > len(konu)
        if not (tur_ok and konu_ok):
            bad.append(yuva)
    return sorted(bad)


def grounding(ad: str, text: str, quotes: dict[str, str] | None = None) -> dict:
    """{"dogrulanmali": bool, "belge": [nedenler], "parca_uyumsuz": [yuvalar]}."""
    d = doc_issues(ad, text)
    p = slot_issues(ad, text, quotes or {})
    return {"dogrulanmali": bool(d or p), "belge": d, "parca_uyumsuz": p}
