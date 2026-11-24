"""Faaliyet kaydı: ince kararların `faaliyet` alanlarını (classify_fine v9) aynı toplantı ya
da etkinliğin kayıtlarında toplar. Belirleyici kod; model çağrısı yok.

Bir belge girdisi: `{doc_id, ad, tarih, asama, ...}`. İki belge aynı faaliyettendir:
  1. **Ad benzer:** Türkçe katlanmış (İ/ı/ç/ğ/ö/ş/ü → ascii) sözcükler; iki sözcük, kısası
     (sondaki ünlü atılarak, en az 3 harf) uzununun başıysa eşleşir (ek: "gunu" ~ "gunleri",
     "kurul" ≁ "kurum"). Dice ≥ `AD_DICE` ya da küçük kümenin hepsi eşleşiyor (en az 2 sözcük). Addaki
     yıl dışı sayılar (toplantı no. "2024/3") farklıysa benzer değildir; addaki yıllar
     farklıysa da.
  2. **Tarih yakın:** her tarih bir aralıktır (gün; "YYYY-AA" → ay; tarih yoksa addaki yıl
     → yıl; hiçbiri yoksa tarihsiz). Çapa aşamalar (`gerceklesme`, `katilim`) birbirine
     ±`CAPA_GUN` içinde birleşir; öteki aşamalar faaliyetin olay tarihine göre aşamaya özgü
     pencerede (`PENCERE`: duyuru önce, değerlendirme sonra) en yakın faaliyete bağlanır.
     Aynı klasörde aynı dosya serisinden ("… 2026-1.jpg" … "-5.jpg") gelen belgeler ad sayısı farklı
     olsa da adı benzer sayılır (`Kume.name_ok`, `ek["seri"]`).
  3. **Tarihsiz belge** adı benzer tek faaliyete bağlanır; birden çok aday varsa ayrı kayıt
     olur ve işaretlenir (yanlış birleştirmektense eksik birleştirmek: temkinli taraf).

Sıra: tarihli çapalar → tarihli öteki aşamalar → tarihsizler. Sonuç kararlıdır (girdi
sırası doc_id'ye göre).
"""
from __future__ import annotations

import calendar
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta

ASAMALAR = ("duyuru", "plan", "gerceklesme", "katilim", "degerlendirme", "iyilestirme",
            "duzenleme", "diger")
CAPA = frozenset({"gerceklesme", "katilim"})
CAPA_GUN = 3
# Aşama → olay tarihine göre izinli gün aralığı (önce negatif).
PENCERE = {"duyuru": (-45, CAPA_GUN), "plan": (-60, CAPA_GUN), "duzenleme": (-60, CAPA_GUN),
           "gerceklesme": (-CAPA_GUN, CAPA_GUN), "katilim": (-CAPA_GUN, CAPA_GUN),
           "degerlendirme": (-CAPA_GUN, 90), "iyilestirme": (-CAPA_GUN, 365), "diger": (-45, 90)}
CAPASIZ_GUN = 21          # çapası olmayan (yalnız duyuru/plan…) kayıtların kendi arasında
AD_DICE = 0.6
KOK_MIN = 3

# Aşama → PUKÖ halkası (audit tasarımı, docs/AUDIT.md "Faaliyet kayıtları").
PUKO = {"duyuru": "planla", "plan": "planla", "duzenleme": "planla", "gerceklesme": "uygula",
        "katilim": "uygula", "degerlendirme": "kontrol_et", "iyilestirme": "onlem_al"}
# Eksik aşama denetimi: her faaliyette beklenenler; iyileştirme yalnız değerlendirme varsa.
BEKLENEN = ("gerceklesme", "katilim", "degerlendirme")

_STOP = {"ve", "ile", "icin", "bir", "bu", "de", "da", "the", "of", "and"}
_TR = str.maketrans({"İ": "i", "I": "ı", "ı": "i", "ç": "c", "ğ": "g", "ö": "o", "ş": "s", "ü": "u",
                     "â": "a", "î": "i", "û": "u"})


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").translate(_TR).lower().translate(_TR)
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


@dataclass(frozen=True)
class Ad:
    kok: frozenset
    sayi: frozenset           # yıl dışı sayılar (toplantı no.)
    yil: frozenset


def parse_name(ad: str) -> Ad:
    words = re.findall(r"[a-z]+|[0-9]+", fold(ad))
    kok, sayi, yil = set(), set(), set()
    for w in words:
        if w.isdigit():
            (yil if len(w) == 4 and w[:2] in ("19", "20") else sayi).add(w.lstrip("0") or "0")
        elif w not in _STOP:
            kok.add(w)
    return Ad(frozenset(kok), frozenset(sayi), frozenset(yil))


def _word_match(x: str, y: str) -> bool:
    if x == y:
        return True
    s, l = sorted((x, y), key=len)
    if s[-1] in "aeiou" and len(s) > KOK_MIN:
        s = s[:-1]
    return len(s) >= KOK_MIN and l.startswith(s)


def similar(a: Ad, b: Ad) -> bool:
    if not a.kok or not b.kok:
        return False
    if a.sayi and b.sayi and a.sayi != b.sayi:
        return False
    if a.yil and b.yil and not (a.yil & b.yil):
        return False
    small_set, big_set = sorted((a.kok, b.kok), key=len)
    common = sum(any(_word_match(x, y) for y in big_set) for x in small_set)
    small = min(len(a.kok), len(b.kok))
    return 2 * common / (len(a.kok) + len(b.kok)) >= AD_DICE or (small >= 2 and common == small)


def parse_date(tarih, ad: Ad | None = None) -> tuple[tuple[date, date] | None, str, str | None]:
    """(aralık | None, kesinlik gun|ay|yil|yok, not). Geçersiz tarih yok sayılır, not düşer."""
    note = None
    if isinstance(tarih, str):
        m = re.fullmatch(r"(\d{4})-(\d{2})(?:-(\d{2}))?", tarih.strip())
        if m:
            y, mo = int(m[1]), int(m[2])
            try:
                if m[3]:
                    d = date(y, mo, int(m[3]))
                    return (d, d), "gun", None
                return (date(y, mo, 1), date(y, mo, calendar.monthrange(y, mo)[1])), "ay", None
            except ValueError:
                pass
        note = f"geçersiz tarih yok sayıldı: {tarih}"
    if ad is not None and len(ad.yil) == 1:
        y = int(next(iter(ad.yil)))
        return (date(y, 1, 1), date(y, 12, 31)), "yil", note
    return None, "yok", note


def _gap(a: tuple[date, date], b: tuple[date, date]) -> int:
    """İki aralık arasındaki gün (kesişiyorsa 0)."""
    if a[1] < b[0]:
        return (b[0] - a[1]).days
    if b[1] < a[0]:
        return (a[0] - b[1]).days
    return 0


def _fits(x: tuple[date, date], olay: tuple[date, date], asama: str) -> bool:
    lo, hi = PENCERE.get(asama, PENCERE["diger"])
    return x[1] >= olay[0] + timedelta(days=lo) and x[0] <= olay[1] + timedelta(days=hi)


@dataclass
class Girdi:
    doc_id: str
    ad: str
    asama: str
    tarih: str | None
    adk: Ad
    aralik: tuple[date, date] | None
    kesinlik: str
    ek: dict = field(default_factory=dict)
    notlar: list[str] = field(default_factory=list)


@dataclass
class Kume:
    uyeler: list[Girdi] = field(default_factory=list)
    notlar: list[str] = field(default_factory=list)

    @property
    def capalar(self) -> list[Girdi]:
        return [g for g in self.uyeler if g.asama in CAPA and g.aralik]

    def olay(self) -> tuple[date, date] | None:
        """Olay tarihi: en kesin, en erken çapa aralığı."""
        c = sorted(self.capalar, key=lambda g: (("gun", "ay", "yil").index(g.kesinlik), g.aralik[0]))
        return c[0].aralik if c else None

    def name_ok(self, g: Girdi) -> bool:
        """Ad benzer ya da aynı dosya serisinden (`ek["seri"]`: klasör + sıra numarasız dosya adı;
        bidr/faaliyet/dosya.py): "Ulusal Staj 2026-1" … "-5" fotoğrafları aynı etkinliktir."""
        s = g.ek.get("seri")
        return any(similar(g.adk, m.adk) or (s and m.ek.get("seri") == s) for m in self.uyeler)


def make_entry(doc_id: str, f: dict, ek: dict | None = None) -> Girdi:
    ad = " ".join(str(f.get("ad") or "").split())
    adk = parse_name(ad)
    asama = f.get("asama") if f.get("asama") in ASAMALAR else "diger"
    aralik, kes, note = parse_date(f.get("tarih"), adk)
    g = Girdi(doc_id, ad, asama, f.get("tarih") if kes in ("gun", "ay") else None, adk, aralik, kes, ek or {})
    if note:
        g.notlar.append(note)
    return g


def group(entries: list[Girdi]) -> list[Kume]:
    entries = sorted(entries, key=lambda g: g.doc_id)
    kumeler: list[Kume] = []
    key = lambda g: (g.aralik[0], ("gun", "ay", "yil").index(g.kesinlik), g.doc_id)  # noqa: E731

    # 1. tarihli çapalar
    for g in sorted((g for g in entries if g.asama in CAPA and g.aralik), key=key):
        best = None
        for k in kumeler:
            if k.name_ok(g) and any(_gap(g.aralik, c.aralik) <= CAPA_GUN for c in k.capalar):
                d = min(_gap(g.aralik, c.aralik) for c in k.capalar)
                if best is None or d < best[0]:
                    best = (d, k)
        (best[1].uyeler.append(g) if best else kumeler.append(Kume([g])))

    # 2. tarihli öteki aşamalar
    for g in sorted((g for g in entries if g.asama not in CAPA and g.aralik), key=key):
        cands = []
        for k in kumeler:
            if not k.name_ok(g):
                continue
            olay = k.olay()
            if olay is not None:
                if _fits(g.aralik, olay, g.asama):
                    cands.append((0, _gap(g.aralik, olay), kumeler.index(k), k))
            else:
                d = min(_gap(g.aralik, m.aralik) for m in k.uyeler if m.aralik) \
                    if any(m.aralik for m in k.uyeler) else None
                if d is not None and d <= CAPASIZ_GUN:
                    cands.append((1, d, kumeler.index(k), k))
        if cands:
            min(cands, key=lambda c: c[:3])[3].uyeler.append(g)
        else:
            kumeler.append(Kume([g]))

    # 3. tarihsizler
    for g in (g for g in entries if not g.aralik):
        cands = [k for k in kumeler if k.name_ok(g)]
        dated = [k for k in cands if any(m.aralik for m in k.uyeler)]
        undated = [k for k in cands if k not in dated]
        if len(dated) == 1:
            dated[0].uyeler.append(g)
            dated[0].notlar.append(f"{g.doc_id}: tarihsiz, adla bağlandı")
        elif len(dated) > 1:
            g.notlar.append(f"tarihsiz; adı benzer {len(dated)} faaliyet var, bağlanmadı")
            kumeler.append(Kume([g]))
        elif undated:
            undated[0].uyeler.append(g)
        else:
            kumeler.append(Kume([g]))
    return kumeler


def _iso(d: date) -> str:
    return d.isoformat()


def summarize(k: Kume) -> dict:
    """Faaliyet kaydı (kimlik çağıranda verilir)."""
    names = Counter(g.ad for g in k.uyeler if g.ad)
    ad = max(names, key=lambda n: (names[n], len(n), n)) if names else ""
    olay = k.olay()
    dated = [g for g in k.uyeler if g.aralik]
    if olay is not None:
        tarih = next(g.tarih for g in k.capalar if g.aralik == olay) or None
    else:
        best = sorted(dated, key=lambda g: (("gun", "ay", "yil").index(g.kesinlik), g.aralik[0]))
        tarih = best[0].tarih if best else None
    asamalar: dict[str, list[str]] = {}
    for g in sorted(k.uyeler, key=lambda g: (ASAMALAR.index(g.asama), g.doc_id)):
        asamalar.setdefault(g.asama, []).append(g.doc_id)
    eksik = [f"{a} yok" for a in BEKLENEN if a not in asamalar]
    if "degerlendirme" in asamalar and "iyilestirme" not in asamalar:
        eksik.append("iyilestirme yok")
    if "gerceklesme" in asamalar:
        durum = "gerceklesme_kanitli"
    elif asamalar.keys() & {"katilim", "degerlendirme", "iyilestirme"}:
        durum = "gerceklesme_dolayli"
    else:
        durum = "gerceklesme_kanitsiz"
    notlar = list(k.notlar) + [f"{g.doc_id}: {n}" for g in k.uyeler for n in g.notlar]
    return {
        "ad": ad,
        "adlar": sorted(names),
        "tarih": tarih,
        "tarih_araligi": [_iso(min(g.aralik[0] for g in dated)), _iso(max(g.aralik[1] for g in dated))]
        if dated else None,
        "durum": durum,
        "yalniz_duyuru": set(asamalar) <= {"duyuru", "plan", "duzenleme", "diger"},
        "asamalar": asamalar,
        "halkalar": sorted({PUKO[a] for a in asamalar if a in PUKO},
                           key=("planla", "uygula", "kontrol_et", "onlem_al").index),
        "eksik": eksik,
        "belgeler": [{"doc_id": g.doc_id, "asama": g.asama, "ad": g.ad, "tarih": g.tarih,
                      **{k: v for k, v in g.ek.items() if k != "seri"}}
                     for g in sorted(k.uyeler, key=lambda g: (ASAMALAR.index(g.asama), g.doc_id))],
        "notlar": notlar,
    }
