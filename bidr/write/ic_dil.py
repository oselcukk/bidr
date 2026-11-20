"""Aracın iç dili: komisyona/inceleyiciye yönelik puanlama ve eşleştirme terimleri.

Bu ifadeler gaps.md, review.xlsx ve audit-olcutler.json içindir; rapor metnine (Açıklamalar,
Güçlü/Gelişmeye Açık Yönler) girmez. Kör test 2026-11-20: "Eksik kanıt notu: … Gereken: …",
"OD'ye sayılmamıştır", "yalnız kurum geneli belgelerle eşleşmiş", "uygulama halkasına … esas
alındığından", "olgunluk düzeyine sayılmamış" rapora sızdı.

Üç yerde kullanılır: ölçüt metni denetimi (`bidr/write/text.py`, kod `ic_dil`), alan maddeleri
denetimi (`bidr/write/yonler.py`, kod `ic_dil`) ve son çıktı denetimi (`bidr denetle`, KRİTİK
`ic_dil`). Desenler katlanmış (ascii, küçük harf; `bidr.identify.text.fold`) metne uygulanır.

Sade karşılıklar (yazım istemleri ve bulgular bunları kullanır):
  "OD'ye sayılmadı (tarihi doğrulanmalı)" → "tarihi belgede görülmüyor"
  "yalnız kurum geneli düzenlemeyle eşleşti" → "dayanak yalnız kurum geneli düzenleme"
  "uygulama halkası kanıtı eksik" → "birimin bu dönemdeki uygulamasını gösteren belge yok"
  "… dönem sonrasına ait olduğundan bu dönemin kanıtı olarak gösterilememektedir" → (yazılmaz;
      eksik olgu) "bölümün bu dönemdeki uygulamasını gösteren belge yok"
"""
from __future__ import annotations

import re

# (desen, kısa ad) — katlanmış metne
DESENLER: list[tuple[str, str]] = [
    (r"eksik kanit notu", "eksik kanıt notu"),
    (r"\bgereken\s*:", "'Gereken:' notu"),
    (r"\bod\W{0,2}(?:y?e|y?a|nin|un)?\b[^.;]{0,80}?\bsayil", "OD'ye sayılma"),
    (r"olgunluk duzey\w*[^.;]{0,80}?\b(?:sayil|esas al)", "olgunluk düzeyine sayılma"),
    (r"olgunluk degerlendirme\w*", "olgunluk değerlendirmesi (puanlama dili)"),
    (r"dusuk olgunluk duzeyinde kal", "düşük olgunluk düzeyinde kalma (puanlama dili)"),
    (r"\b(?:puko|pukoo|uygulama|planlama|planla|izleme|kontrol|iyilestirme|onlem alma|eksik)\s+halka\w*",
     "PUKÖ halkası"),
    (r"(?:belge|duzenleme|kanit|yonerge)\w*\s*(?:ile\s+|y?le\s+|y?la\s+)?eslesm", "eşleşme"),
    (r"\beslesmis\w*|\beslesmekte\w*|\beslesti\b", "eşleşme"),
    (r"\b[a-z]+_[a-z_]+\b", "iç işaret (alt çizgili)"),
    (r"\bonerilen od\b|\bod onerisi|\bkod onerisi", "OD önerisi"),
    (r"\baudit\b|gaps\.md|review\.xlsx|evidence-index", "araç dosyası"),
    (r"donem\w* ait dogrudan kanit", "doğrudan kanıt notu"),
    (r"\bdogrulanmali\b", "'doğrulanmalı' işareti"),
    (r"kurum/fakulte geneli", "kurum/fakülte geneli notu"),
    (r"\bneredeyse kanitsiz", "neredeyse kanıtsız notu"),
    # Kanıt yönetimi kararı (kör test 2026-11-20, Kimya A.1.5, B.1.6): aracın bir belgeyi bu dönemin
    # kanıtı saymama gerekçesi komisyon notudur; gelişmeye açık yön bölümün eksiğini söyler.
    (r"\b(?:bu )?donem\w* kaniti (?:olarak )?(?:gosterile|sayila|kabul edile|kullanila)\w*",
     "dönem kanıtı sayma kararı"),
    (r"\bkanit\w* olarak (?:gosterilem|gosterilme|sayilma|sayilam|kabul edilem|kullanilam)\w*",
     "kanıt sayma kararı"),
    (r"\bkanit\w* (?:olarak )?sayilma(?:mis|di)\w*", "kanıt sayma kararı"),
    (r"\b(?:donem sonrasina|donem disina|donem oncesine|onceki yila|gecmis yila|gecmis doneme)"
     r" ait oldugu(?:ndan|ndan dolayi| icin)\b", "dönem dışı gerekçesi"),
    (r"\btarih\w* (?:belgede )?(?:gorulmedig|gorulmemesi|dogrulanamadig)\w*", "tarih görülmüyor gerekçesi"),
]
_RX = [(re.compile(p), ad) for p, ad in DESENLER]


def _fold(s: str) -> str:
    from bidr.identify.text import fold
    return " ".join(fold(s or "").split())


def bul(metin: str) -> list[tuple[str, str]]:
    """Metindeki iç dil eşleşmeleri: [(kısa ad, eşleşen parça)] (boş liste: temiz)."""
    low = _fold(metin)
    out = []
    for rx, ad in _RX:
        m = rx.search(low)
        if m:
            out.append((ad, m.group(0)))
    return out


def sorunlar(metin: str) -> list[dict]:
    """Yazım denetimi biçiminde: [{kod: "ic_dil", ayrinti}]."""
    return [{"kod": "ic_dil", "ayrinti": f"aracın iç dili ({ad}): “{p}” — rapor okuruna sade olguyla yazılır"}
            for ad, p in bul(metin)]
