"""İsteğin dosyada karşılığı: eksik listesi (`bidr ihtiyac`) kabul edilmiş inceleme kararlarına bakar.

Kabul edilmiş kanıt = yuvayı karşılayan audit satırı (`rapor.karsilar`: sayılan, reddedilmemiş; güveni
orta/yüksek ya da incelemede kabul/düzelt). Bir istek şu sırayla kapanır (ilk tutan kural):

  1. **Aynı belge:** geçen yılın belgesinin bu yılki karşılığı (eşleştirmenin bulduğu belge) herhangi
     bir ölçütte kabul edilmiş.
  2. **Tür düzeyi:** derse özgü geçen yıl belgesi ("MATH407 anket sonucu") bu yıl tür düzeyinde istenir;
     aynı türden kabul edilmiş herhangi bir belge (herhangi bir dersin, herhangi bir ölçütte) kapatır.
  3. **Aynı ölçüt, aynı tür:** ölçütte aynı türden kabul edilmiş, zayıf olmayan başka bir belge var
     ("başka belgeyle" karşılandı). Yuvanın başka türden bir belgeyle dolu olması kapatmaz.
  4. **Kurum belgesi başka ölçütte:** kurum düzeyi belge (yönetmelik, yönerge, iş akışı, form; ya da kurum/
     fakülte geneli satır) adıyla ve türüyle dosyada başka ölçütün kanıtı: istenmez, "dosyada var (X ölçütünde)".

**Tür zorunlu** (`tur_uyumlu`): karşılayan belge isteğin türünden olmalı. Tür, belgenin adındaki tür
ifadesinden (`TUR_IFADE`: anket sonucu, ders bilgi formu / çıktı matrisi, müfredat, seminer, çalıştay, iş
akışı, iş akışları listesi, fotoğraf, yönerge…) ve sınıflandırmanın türünden (`belge_turu`) okunur: iki ad da
tür ifadesi taşıyorsa ortak ifade gerekir (sınıflandırma aynı olsa bile: "toplantı haberi" anket sonucu
değildir); yalnız biri taşıyorsa sınıflandırma birebir aynı olmalı, hiçbiri taşımıyorsa aynı ya da aynı grupta
(`DERS_GRUP`); her durumda adlar aynı belgeyi anlatıyorsa (`ad_ayni`) de uyar. Tür tutmazsa istek kapanmaz. Uyan adaylar arasından gösterilen belge: önce aynı
ölçüt, sonra adın geçen yılki belgeyle ortak sözcük kökü çok olan, sonra tam (zayıf olmayan) kanıt, sonra
aynı yuva (`_sec`; en çok `GOSTER_EN_COK` belge).

Yuva doluluğu: yuvayı karşılayan satırların hepsi zayıfsa yuva **kısmen** doludur; kılavuz isteği somut
biçimde kalır, "Var olan kanıt" sütununda zayıf kanıt gösterilir. Zayıf: alıntı tek soru ya da en çok
`ZAYIF_SOZCUK` sözcük; ya da anket belgesinden tek madde (`anket_maddesi`) ve yuvanın ana metni (ayraç içi
örnekler dışında) anket/geri bildirim istemiyor ("AKTS hesaplama tabloları ve ek belgeler (örn; anketler)":
tek anket maddesi hesap tablosu değildir). Model yok; salt okunur.
"""
from __future__ import annotations

import re

from .tablolar import norm

ZAYIF_SOZCUK = 6
ANKET_MADDE_SOZCUK = 25     # anket belgesinden tek cümlelik alıntı en çok bu kadar sözcükse tek anket maddesidir
GOSTER_EN_COK = 2
# Belge adındaki tür ifadesi (norm'lu ad üzerinde; sıra önemsiz, bir ad birden çok ifade taşıyabilir).
# "iş akışları listesi" tek tek iş akışı değildir: liste ifadesi varsa `is_akisi` yazılmaz.
TUR_IFADE: tuple[tuple[str, str], ...] = (
    ("is_akisi_listesi", r"\bis akis\w*\s+liste"),
    ("is_akisi", r"\bis akis(?!\w*\s+liste)"),
    ("anket_sonucu", r"\banket\w*\s+(?:sonuc|degerlendirme|analiz|rapor)|\bsurvey\w*\s+(?:result|report)"),
    ("anket_formu", r"\banket\w*\s+form|\bsurvey\w*\s+form|\bquestionnaire"),
    ("ders_bilgi", r"\bders bilgi (?:form|paket)|\bizlence|\bsyllabus|\bcourse (?:information|description)"
                   r"|\bprogram ciktilar\w*\s+(?:iliski\s+)?matris|\bciktilar\w*\s+matris"),
    ("mufredat", r"\bmufredat|\bders plani|\bogretim plani|\bcurricul|\bders katalog"),
    ("seminer", r"\bsemine|\bkolokyum|\bcolloqui|\bseminar"),
    ("calistay", r"\bcalistay|\bworkshop|\bsempozyum|\bsymposium|\bkongre|\bkonferans|\bconference"),
    ("fotograf", r"\bfotograf|\bphoto"),
    ("diploma_eki", r"\bdiploma (?:eki|supplement)"),
    ("yonerge", r"\byonerge"),
    ("yonetmelik", r"\byonetmelik"),
    ("usul_esas", r"\busul ve esas|\buygulama esas"),
    ("tutanak", r"\btutanak|\btoplanti"),
    ("protokol", r"\bprotokol|\banlasma"),
)
_TUR_RE = tuple((k, re.compile(d)) for k, d in TUR_IFADE)
_ANKET_AD = re.compile(r"\banket|\bsurvey")
_ANKET_ISTER = re.compile(r"\banket|\bsurvey|geri ?bildirim|\bgorus|\bmemnuniyet")
KURUM_TURLER = frozenset({"yonetmelik", "yonerge", "usul_esas", "is_akisi", "senato_karari", "anket_formu",
                          "form_belgesi", "mevzuat"})
GENEL_ILISKI = frozenset({"kurum_geneli", "fakulte_geneli"})
DERS_GRUP = {"ders_bilgi_formu": "ders_bilgi", "mufredat": "ders_bilgi", "akts_bilgi_paketi": "ders_bilgi"}
_DOLGU = frozenset("gtu gebze teknik universitesi universite ve ile icin iliskin hakkinda bir the of and "
                   "bolum bolumu bolumun".split())


def karsilar(r: dict) -> bool:
    from .rapor import karsilar as k
    return k(r)


def anket_maddesi(r: dict) -> bool:
    """Anket belgesinden tek cümlelik, kısa alıntı: tek bir anket maddesi/cevabı. Anket belgesi: adında anket
    geçer ya da türü anket ve adı başka bir tür ifadesi taşımaz ("… Toplantısı Haberi" anket değildir)."""
    n = ad(r)
    if not (_ANKET_AD.search(norm(n)) or (r.get("belge_turu") in ("anket_sonucu", "anket_formu")
                                         and not tur_ifadeleri(n))):
        return False
    q = " ".join(str(r.get("alinti") or "").replace("|", " ").split())
    cumle = [c for c in re.split(r"(?<=[.!?])\s+", q) if c.strip()]
    return len(cumle) <= 1 and len(q.split()) <= ANKET_MADDE_SOZCUK


def anket_yeter(yuva_metni: str | None) -> bool:
    """Yuvanın ana metni (ayraç içindeki örnekler hariç) anket/geri bildirim istiyor mu."""
    t = re.sub(r"\([^)]*\)?", " ", norm(yuva_metni or ""))
    return bool(_ANKET_ISTER.search(t))


def zayif(r: dict) -> bool:
    """Tek başına yuvayı dolduramayacak kanıt: alıntı tek soru ya da çok kısa; ya da yuva anket istemiyorken
    tek anket maddesi (bkz. modül belgesi)."""
    q = " ".join(str(r.get("alinti") or "").split())
    if q.endswith("?") or len(q.split()) <= ZAYIF_SOZCUK:
        return True
    return anket_maddesi(r) and r.get("yuva_metni") is not None and not anket_yeter(r.get("yuva_metni"))


def kok(s: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", norm(s)) if len(w) > 2 and w not in _DOLGU}


def ad_ayni(a: str, b: str) -> bool:
    """İki belge adı aynı belgeyi mi anlatıyor (yıl/sayı dışı sözcük kökleri; kısa adın ≥ %80'i, Jaccard ≥ 0,5)."""
    x, y = kok(a), kok(b)
    if len(x) < 2 or len(y) < 2:
        return False
    o = len(x & y)
    return o / min(len(x), len(y)) >= 0.8 and o / len(x | y) >= 0.5


def tur_ayni(a: str | None, b: str | None) -> bool:
    if not a or not b or a == "bilinmiyor" or b == "bilinmiyor":
        return False
    return a == b or DERS_GRUP.get(a, a) == DERS_GRUP.get(b, b)


def ad(r: dict) -> str:
    return r.get("kanit_adi") or r.get("belge") or r.get("doc_id") or ""


def tur_ifadeleri(s: str) -> frozenset[str]:
    """Belge adındaki tür ifadeleri (`TUR_IFADE`)."""
    t = norm(s)
    return frozenset(k for k, rx in _TUR_RE if rx.search(t))


def tur_uyumlu(g_ad: str, g_tur: str | None, r: dict) -> bool:
    """Karşılayan aday `r`, geçen yılın belgesiyle (ad, tür) aynı türden mi (bkz. modül belgesi)."""
    a, b = tur_ifadeleri(g_ad), tur_ifadeleri(ad(r))
    if a and b:
        return bool(a & b)
    if a or b:              # yalnız biri tür söylüyor: sınıflandırma birebir aynı olmalı (grup yetmez)
        bt = r.get("belge_turu")
        return bool(g_tur) and g_tur == bt and bt != "bilinmiyor" or ad_ayni(g_ad, ad(r))
    return tur_ayni(g_tur, r.get("belge_turu")) or ad_ayni(g_ad, ad(r))


def ortak_kok(a: str, b: str) -> int:
    return len(kok(a) & kok(b))


def kurum_mu(r: dict) -> bool:
    return (r.get("belge_turu") in KURUM_TURLER or r.get("birim_iliskisi") in GENEL_ILISKI
            or "kurum_geneli" in (r.get("flags") or []))


class Karsilama:
    def __init__(self, rows: list[dict]):
        self.rows = [r for r in rows if karsilar(r)]

    # -- yuva doluluğu ------------------------------------------------------------------------
    def yuva(self, cid: str) -> dict[str, dict]:
        """{yuva: {"durum": "dolu"|"kismen", "belgeler": [ad]}} (ölçütün kabul edilmiş satırlarından)."""
        out: dict[str, dict] = {}
        for r in self.rows:
            if r.get("olcut") != cid:
                continue
            e = out.setdefault(r["yuva"], {"durum": "kismen", "belgeler": [], "zayif": []})
            if not zayif(r):
                e["durum"] = "dolu"
                e["belgeler"].append(ad(r))
            else:
                e["zayif"].append(ad(r))
        for e in out.values():
            e["belgeler"] = list(dict.fromkeys(e["belgeler"] if e["durum"] == "dolu" else e["zayif"]))
            del e["zayif"]
        return out

    def dolu(self, cid: str) -> set[str]:
        return {y for y, e in self.yuva(cid).items() if e["durum"] == "dolu"}

    def kismen(self, cid: str) -> dict[str, list[str]]:
        return {y: e["belgeler"] for y, e in self.yuva(cid).items() if e["durum"] == "kismen"}

    # -- geçen yılın belgesi -------------------------------------------------------------------
    def _not(self, xs: list[dict], cid: str, neden: str) -> dict:
        """Karşılayan belge(ler): ilk aday asıl, en çok `GOSTER_EN_COK` farklı ad gösterilir."""
        r = xs[0]
        adlar = list(dict.fromkeys(ad(x) for x in xs))[:GOSTER_EN_COK]
        oc: dict[str, str] = {}
        for x in xs:
            oc.setdefault(ad(x), x["olcut"])
        return {"ad": ad(r), "adlar": adlar, "olcut": r["olcut"], "doc_id": r.get("doc_id"), "neden": neden,
                "metin": "; ".join(f"«{a}»" + ("" if oc[a] == cid else f" ({oc[a]} ölçütünde)") for a in adlar)}

    def _sec(self, xs: list[dict], cid: str, g: dict | None = None) -> list[dict]:
        """Adaylar sıralı: aynı ölçüt, adın geçen yılki belgeyle ortaklığı, tam kanıt, aynı yuva, ölçüt kimliği
        (kararlı)."""
        ga = (g or {}).get("kanit_adi") or ""
        gy = (g or {}).get("yuva")
        return sorted(xs, key=lambda r: (r["olcut"] != cid, -ortak_kok(ga, ad(r)), zayif(r),
                                         r.get("yuva") != gy, r["olcut"], ad(r)))

    def gecen(self, g: dict, tur_duzeyi: bool) -> dict | None:
        """Geçen yılın belgesinin (referans öğe + eşleştirme sonucu) dosyadaki karşılığı; yoksa None."""
        cid = g["olcut"]
        bt = g.get("belge_turu") or ""
        ga = g.get("kanit_adi") or ""
        kd = g.get("karsilik_doc_id")
        if kd:
            xs = self._sec([r for r in self.rows if r.get("doc_id") == kd], cid, g)
            if xs:
                return self._not(xs, cid, "aynı belge kabul edilmiş")
        uyan = [r for r in self.rows if tur_uyumlu(ga, bt, r)]
        if tur_duzeyi:
            xs = self._sec(uyan, cid, g)
            if xs:
                return self._not(xs, cid, "aynı türden belge kabul edilmiş (tür düzeyinde istek)")
        xs = self._sec([r for r in uyan if r["olcut"] == cid and not zayif(r)], cid, g)
        if xs:
            return self._not(xs, cid, "ölçütte aynı türden başka belgeyle karşılanmış")
        if bt in KURUM_TURLER or g.get("kurum"):
            xs = self._sec([r for r in uyan if kurum_mu(r) and ad_ayni(ga, ad(r))], cid, g)
            if xs:
                return self._not(xs, cid, "kurum belgesi dosyada başka ölçütün kanıtı")
        return None

    def kurum(self, o: dict, cid: str) -> dict | None:
        """Kurum kataloğundaki belgenin (ad, kod) dosyada kabul edilmiş karşılığı (herhangi bir ölçütte)."""
        kod = norm(o.get("kod") or "")
        xs = [r for r in self.rows if (kod and kod in norm(ad(r))) or ad_ayni(o.get("ad") or "", ad(r))]
        xs = self._sec(xs, cid, {"kanit_adi": o.get("ad") or ""})
        return self._not(xs[:1], cid, "kurum belgesi dosyada") if xs else None
