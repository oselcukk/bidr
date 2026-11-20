"""Aynı belgenin farklı sürümlerini (ör. docx taslak ↔ imzalı tarama PDF) bağla.

Yalnız metin içeriğine bakılır: katlanmış sözcüklerin TF-IDF kosinüs benzerliği.
Çok yaygın sözcükler (form şablonu, kurum adı) IDF ile bastırılır; aynı şablonu
kullanan farklı toplantılar bu yüzden birleşmez. İki belgenin birincil tarihleri
farklıysa çok yüksek benzerlik dışında bağlanmaz.

TF-IDF taramadaki OCR gürültüsünde zayıftır: aynı yazının iki taraması her OCR hatasında ayrı
"nadir" sözcük üretir, el yazısı/imza sayfası çöp belirteçle dolar ve kosinüs 0,5–0,6'da kalır.
Bunun için iki ek bağ (ikisi de simetrik; dönem/tarih ayrımı korunur, K20):

- **OCR kopyası** (`CopyIndex.copy`): okunur satırların (sözcük oranı yüksek; el yazısı/imza çöpü
  atılır) harf-rakam akışından 8'li karakter parçacıkları; iki yönlü kapsama (küçükte ≥ COPY_LO,
  büyükte ≥ COPY_HI). Ayrıca: birincil tarihler aynı (ikisi de tarihsizse eşik COPY_UNDATED),
  türler uyumlu, baş bölgedeki kimlikler (tarih, ders kodu, sayı/no) ayrık değil.
- **Kontrollü belge imzası** (`control_signature`): yapı belgesinin (yönerge, yönetmelik, iş akışı,
  stratejik plan) başlığındaki doküman numarası + revizyon (tarih/no) aynıysa aynı belgenin
  sayfa/bölüm kopyalarıdır. Form numarası ("Form No: FR-…") dolu formların hepsinde aynıdır:
  kullanılmaz.

Kapsama (bir belgenin başka bir belgenin içinde olması, ör. ekleriyle taranmış karar) simetrik
değildir; geçişli gruplamada iki farklı eki aynı gruba sokar. O yüzden burada değil, ölçüt
düzeyinde ve alıntı denetimiyle uygulanır (bidr/file/select.py `merge_contained`).
"""
from __future__ import annotations

import math
import re
import zlib
from collections import Counter

_TOK = re.compile(r"[a-z]{3,}")

THRESHOLD = 0.90          # bağlama eşiği
DATE_CONFLICT_MIN = 0.95  # tarihler farklıysa gereken benzerlik
MIN_TOKENS = 25


HEAD_CHARS = 2000
HEAD_MIN = 0.5            # baş bölgeler de benzemeli (aynı şablonu dolduran farklı birimler ayrılır)


def _vectors(texts: dict[str, str], df: Counter | None = None, n: int | None = None
             ) -> dict[str, dict[str, float]]:
    tfs = {k: Counter(_TOK.findall(t)) for k, t in texts.items()}
    if df is None:
        n = len(tfs)
        df = Counter()
        for tf in tfs.values():
            df.update(tf.keys())
    vecs = {}
    for k, tf in tfs.items():
        if sum(tf.values()) < MIN_TOKENS:
            continue
        v = {}
        for w, c in tf.items():
            if n > 4 and df[w] > 0.5 * n:
                continue
            v[w] = (1 + math.log(c)) * math.log((n + 1) / max(df[w], 1))
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs[k] = {w: x / norm for w, x in v.items()}
    return vecs


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


RARE_DF = 4               # en çok bu kadar belgede geçen sözcük "nadir" sayılır
RARE_MIN = 0.5            # nadir sözcüklerde de benzerlik (ortak şablonu dolduran farklı birimler ayrılır)
RARE_MIN_TOKENS = 10
TITLE_CHARS = 200
TITLE_MIN = 0.6
TITLE_CHECK_MAXLEN = 50000  # uzun raporlarda baş kısım kapak/künye farkıyla oynayabilir


def _rare_sets(texts: dict[str, str], df: Counter) -> dict[str, set[str]]:
    return {k: {w for w in set(_TOK.findall(t)) if df[w] <= RARE_DF} for k, t in texts.items()}


def group(texts: dict[str, str], dates: dict[str, str | None],
          types: dict[str, str] | None = None) -> dict[str, dict]:
    """doc_id -> {grup, uyeler, benzerlik}. Tek başına olanlar dahil edilmez."""
    vecs = _vectors(texts)
    pairs = copy_pairs(texts, dates, types)
    for a, b, _ in pairs:
        vecs.setdefault(a, {})              # TF-IDF'e girmeyen (kısa) belge yalnız kopya bağıyla katılır
        vecs.setdefault(b, {})
    df: Counter = Counter()
    for t in texts.values():
        df.update(set(_TOK.findall(t)))
    heads = _vectors({k: t[:HEAD_CHARS] for k, t in texts.items()}, df, len(texts))
    rare = _rare_sets(texts, df)
    types = types or {}
    ids = sorted(vecs)
    parent = {i: i for i in ids}
    best: dict[str, float] = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if not vecs[a] or not vecs[b]:
                continue
            s = _cos(vecs[a], vecs[b])
            if s < THRESHOLD:
                continue
            if a in heads and b in heads and _cos(heads[a], heads[b]) < HEAD_MIN:
                continue
            ra, rb = rare[a], rare[b]
            if min(len(ra), len(rb)) >= RARE_MIN_TOKENS:
                if len(ra & rb) / min(len(ra), len(rb)) < RARE_MIN:
                    continue
            elif s < DATE_CONFLICT_MIN:
                # ayırt edici sözcük yok (kısa/şablon belge): neredeyse aynı olmalı
                continue
            ha, hb = set(_TOK.findall(texts[a][:TITLE_CHARS])), set(_TOK.findall(texts[b][:TITLE_CHARS]))
            if (min(len(ha), len(hb)) >= 5 and max(len(texts[a]), len(texts[b])) < TITLE_CHECK_MAXLEN
                    and len(ha & hb) / len(ha | hb) < TITLE_MIN and s < 0.99):
                # başlık bölgesi farklı (ör. aynı anket formu, farklı ders)
                continue
            ta, tb = types.get(a), types.get(b)
            if ta and tb and ta != tb and s < DATE_CONFLICT_MIN:
                continue
            da, db = dates.get(a), dates.get(b)
            if da and db and da != db and s < DATE_CONFLICT_MIN:
                continue
            parent[find(a)] = find(b)
            best[a] = max(best.get(a, 0), s)
            best[b] = max(best.get(b, 0), s)
    # OCR'a dayanıklı ikinci geçiş: OCR kopyaları ve kontrollü belge imzası (tarih/dönem ayrımı korunur)
    for a, b, s in pairs:
        if find(a) != find(b):
            parent[find(a)] = find(b)
            best[a] = max(best.get(a, 0), s)
            best[b] = max(best.get(b, 0), s)
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    out = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        gid = "sg-" + min(members)
        for m in members:
            out[m] = {"grup": gid, "uyeler": sorted(x for x in members if x != m),
                      "benzerlik": round(best.get(m, 0.0), 3)}
    return out


# -- OCR'a dayanıklı kopya benzerliği ------------------------------------------------------------

COPY_K = 8                 # karakter parçacığı uzunluğu (harf-rakam akışında)
COPY_WINDOW = 6            # okunurluk penceresi (belirteç)
COPY_WINDOW_Q = 0.6        # okunur pencere: belirteçlerin en az bu oranı 3+ harfli sözcük
COPY_WINDOW_MIN = 3        # pencerede en az bu kadar belirteç
COPY_MIN_SHINGLES = 150    # okunur kısmı bundan kısa belge kopya sayılmaz
COPY_TEMPLATE_DF = 12      # en az max(DF, FRAC × belge) belgede geçen parçacık şablon/ortak metindir
COPY_TEMPLATE_FRAC = 0.01  # (form/iş akışı kalıbı, kurum başlığı): ayırt edici sayılmaz
COPY_MIN_INFORMATIVE = 120 # şablon dışı parçacığı bundan az belge kopya sayılmaz (yalnız kalıp)
COPY_LO = 0.6              # şablon dışı parçacıklarda: küçüğün büyükte bulunma oranı
COPY_HI = 0.5              # büyüğün küçükte bulunma oranı (fazladan ek/sayfa sınırı)
COPY_STRICT = 0.9          # tarihsiz ya da kalıp türü (yapı belgesi, form) belgede iki yönde gereken oran
COPY_SAMPLE = 8            # aday üretimi için parçacık örneklemi (karma % COPY_SAMPLE == 0)
TITLE_TOKENS = 40          # kardeş kalıp denetimi: baştaki bu kadar belirteç
TITLE_WORD_DF = 3          # bu kadar belgede geçen sözcük gerçek sözcüktür (OCR bozuntusu değil)
TITLE_FUZZY = 0.8          # bozuntu karşılığı sayılan benzerlik (difflib oranı)
HEAD_ID_CHARS = 400
CONTROL_HEAD = 800
# Kalıp türleri: aynı kalıptan üretilmiş kardeş belgeler (iş akışları, formlar, yönergeler) yalnız
# başlıkta ayrışır; kopya için kontrollü belge imzası ya da iki yönde COPY_STRICT gerekir.
TEMPLATE_TYPES = frozenset({"yonerge", "yonetmelik", "is_akisi", "stratejik_plan", "mufredat",
                            "ders_bilgi_formu", "akts_bilgi_paketi", "form_belgesi", "anket_formu",
                            "gorev_dagilimi", "altyapi_listesi"})
CONTROL_TYPES = frozenset({"yonerge", "yonetmelik", "is_akisi", "stratejik_plan"})
_UNKNOWN_TYPES = (None, "", "bilinmiyor")

_WORD = re.compile(r"[a-z]{3,}")
_TWORD = re.compile(r"[a-z]{4,}")
_STRIP = ".,;:()[]{}\"'!?-/|*“”‘’«»"
_ALNUM = re.compile(r"[^a-z0-9]")
# baş bölge kimlikleri: tarih (gg.aa.yyyy), ders kodu (chem 202, mat101), sayı (e.184506, 2025/14),
# doküman no (yo-0058)
_HID_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d\d)\b")
_HID_CODE = re.compile(r"\b([a-z]{2,5})\s?-?(\d{3})\b")
_HID_NO = re.compile(r"\b(?:sayi|sayisi|karar)\s*[:.]?\s*([a-z]?[.\-]?\s?\d[\d/.\-]{2,})")
_HID_CODE_SKIP = frozenset({"madde", "sayfa", "tel", "fax", "faks", "oda", "no"})
# kontrollü belge başlığı: "doküman no yo-0058 … revizyon tarihi 04.09.2024 … revizyon no 5". Form
# numarası ("form no: fr-0044") kullanılmaz: dolu formların hepsinde aynıdır.
_CTRL_NO = re.compile(r"\b(?:dokuman|belge)\s*(?:no|numarasi|kodu)\s*[:.]?\s*([a-z]{1,4}\s?[-.]\s?\d{2,5})")
_CTRL_REV_T = re.compile(r"\brevizyon\s*tarihi\s*[:.]?\s*(\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d\d)")
_CTRL_REV_N = re.compile(r"\brevizyon\s*(?:no|numarasi)\s*[:.]?\s*(\d{1,3})\b")


def _fold(t: str) -> str:
    from .text import fold
    return " ".join(fold(t or "").split())


def readable(text: str) -> str:
    """Okunur bölgelerin katlanmış harf-rakam akışı. Metin COPY_WINDOW belirteçlik pencerelere
    bölünür (identify satır sonlarını sıkıştırır); sözcük oranı düşük pencere (OCR çöpü, imza/el
    yazısı, tablo artığı) atılır."""
    toks = _fold(text).split()
    keep = []
    for i in range(0, len(toks), COPY_WINDOW):
        w = toks[i:i + COPY_WINDOW]
        if len(w) < COPY_WINDOW_MIN:
            continue
        if sum(1 for x in w if _WORD.fullmatch(x.strip(_STRIP))) / len(w) >= COPY_WINDOW_Q:
            keep.extend(w)
    return _ALNUM.sub("", " ".join(keep))


def shingles(stream: str) -> frozenset[int]:
    return frozenset(zlib.crc32(stream[i:i + COPY_K].encode()) for i in range(len(stream) - COPY_K + 1))


def fingerprint(text: str) -> frozenset[int]:
    """OCR'a dayanıklı içerik parmak izi: okunur akışın COPY_K'lı karakter parçacıkları (karma)."""
    return shingles(readable(text))


def quote_fingerprint(q: str) -> frozenset[int]:
    """Alıntının parmak izi (kısa metin: okunurluk süzgeci uygulanmaz)."""
    return shingles(_ALNUM.sub("", _fold(q)))


def containment(fa: frozenset, fb: frozenset) -> tuple[float, float]:
    """(küçüğün büyükte bulunma oranı, büyüğün küçükte bulunma oranı)."""
    if not fa or not fb:
        return 0.0, 0.0
    i = len(fa & fb)
    return i / min(len(fa), len(fb)), i / max(len(fa), len(fb))


def head_ids(text: str, chars: int | None = HEAD_ID_CHARS) -> frozenset[str]:
    """Baş bölgedeki kimlikler (tarih, ders kodu, sayı, doküman no): iki kopyada ortak olmalı.
    `chars=None`: bütün metnin kimlikleri (kapsayan belgede aramak için)."""
    h = _fold(text[:chars * 3])[:chars] if chars else _fold(text)
    out = {f"t:{int(d):02d}.{int(m):02d}.{y}" for d, m, y in _HID_DATE.findall(h)}
    out |= {f"k:{a}{n}" for a, n in _HID_CODE.findall(h) if a not in _HID_CODE_SKIP}
    out |= {"n:" + re.sub(r"\D", "", x) for x in _HID_NO.findall(h) if len(re.sub(r"\D", "", x)) >= 3}
    out |= {"d:" + re.sub(r"[\s.\-]", "", x) for x in _CTRL_NO.findall(h)}
    return frozenset(out)


def ids_compatible(ha: frozenset, hb: frozenset) -> bool:
    """Aynı türden kimlik iki tarafta da varsa en az biri ortak olmalı (farklı ders/sayı/tarih ayırır)."""
    for kind in ("t:", "k:", "n:", "d:"):
        a = {x for x in ha if x.startswith(kind)}
        b = {x for x in hb if x.startswith(kind)}
        if a and b and not (a & b):
            return False
    return True


def control_signature(text: str) -> tuple[str, str] | None:
    """Kontrollü belge imzası (doküman no, revizyon) başlıktan; revizyon bilgisi yoksa None."""
    h = _fold(text[:CONTROL_HEAD * 3])[:CONTROL_HEAD]
    m = _CTRL_NO.search(h)
    if not m:
        return None
    rt, rn = _CTRL_REV_T.search(h), _CTRL_REV_N.search(h)
    if not rt and not rn:
        return None
    rev = (re.sub(r"[./-]", ".", rt.group(1)) if rt else "") + "|" + (rn.group(1) if rn else "")
    return re.sub(r"[\s.\-]", "", m.group(1)), rev


def types_compatible(ta: str | None, tb: str | None) -> bool:
    return ta in _UNKNOWN_TYPES or tb in _UNKNOWN_TYPES or ta == tb


class CopyIndex:
    """Bir derlemin kopya karşılaştırması için özeti: parmak izleri, şablon parçacıkları (belge
    sıklığı), sözcük sıklığı. identify (bütün belgeler) ve dosyalama (ölçüt kalemleri) kullanır."""

    def __init__(self, texts: dict[str, str]):
        self.texts = texts
        self.fp = {k: fingerprint(t) for k, t in texts.items()}
        df: Counter = Counter()
        for v in self.fp.values():
            if len(v) >= COPY_MIN_SHINGLES:
                df.update(v)
        lim = max(COPY_TEMPLATE_DF, int(COPY_TEMPLATE_FRAC * len(texts)))
        self.inf = {k: frozenset(h for h in v if df[h] < lim) for k, v in self.fp.items()}
        self.words = {k: set(_WORD.findall(_fold(t))) for k, t in texts.items()}
        self.wdf: Counter = Counter()
        for v in self.words.values():
            self.wdf.update(v)
        self._heads: dict[str, frozenset] = {}

    def head(self, k: str) -> frozenset:
        if k not in self._heads:
            self._heads[k] = head_ids(self.texts[k])
        return self._heads[k]

    def usable(self, k: str) -> bool:
        return len(self.fp.get(k, ())) >= COPY_MIN_SHINGLES and len(self.inf.get(k, ())) >= COPY_MIN_INFORMATIVE

    def siblings(self, a: str, b: str) -> bool:
        """Kardeş kalıp: iki belgenin başında da ötekinde hiç geçmeyen gerçek bir sözcük var ve
        karşı tarafta bozuntu karşılığı yok (ör. "gelen"/"giden", "açma"/"kapatma"). OCR bozuntusu
        ("bahar"/"buar") karşılığıyla eşleşir."""
        def title_words(x: str) -> set[str]:
            return {w for w in _fold(self.texts[x]).split()[:TITLE_TOKENS]
                    if _TWORD.fullmatch(w) and self.wdf[w] >= TITLE_WORD_DF}

        def unexplained(miss: set[str], other: set[str]) -> set[str]:
            import difflib
            return {w for w in miss if not any(difflib.SequenceMatcher(None, w, o).ratio() >= TITLE_FUZZY
                                               for o in other if abs(len(o) - len(w)) <= 3)}
        ma = unexplained(title_words(a) - self.words[b], self.words[b])
        mb = unexplained(title_words(b) - self.words[a], self.words[a])
        return bool(ma and mb)

    def copy(self, a: str, b: str, da: str | None, db: str | None, ta: str | None = None,
             tb: str | None = None) -> float | None:
        """İki belge aynı yazının kopyası mı → benzerlik (şablon dışı kapsama) ya da None.
        Simetriktir: küçük de büyük de ötekinde büyük ölçüde bulunmalı. Tarihler farklıysa asla
        (farklı dönemin/toplantının belgesi ayrı kalır, K20)."""
        if not (self.usable(a) and self.usable(b)):
            return None
        if (da or db) and da != db:
            return None
        if not types_compatible(ta, tb) or not ids_compatible(self.head(a), self.head(b)):
            return None
        lo, hi = containment(self.inf[a], self.inf[b])
        strict = not da or ta in TEMPLATE_TYPES or tb in TEMPLATE_TYPES
        need_lo, need_hi = (COPY_STRICT, COPY_STRICT) if strict else (COPY_LO, COPY_HI)
        if lo < need_lo or hi < need_hi:
            return None
        if (ta in _UNKNOWN_TYPES or ta in TEMPLATE_TYPES or tb in TEMPLATE_TYPES) and self.siblings(a, b):
            return None
        return round(lo, 3)

    def ids_within(self, small: str, big: str, shared: bool = False) -> bool:
        """Küçüğün baş bölge kimlikleri kapsayanın metninde de var mı (tür tür, `ids_compatible`).
        `shared`: en az bir kimlik ortak olmalı (kimliksiz parça hiçbir belgeye bağlanmaz)."""
        if ("all", big) not in self._heads:
            self._heads[("all", big)] = head_ids(self.texts[big], None)
        ha, hb = self.head(small), self._heads[("all", big)]
        return ids_compatible(ha, hb) and (not shared or bool(ha & hb))

    def contained(self, small: str, big: str) -> float:
        """Küçüğün (şablon dışı) büyükte bulunma oranı (kapsama; simetrik değil)."""
        a, b = self.inf.get(small) or frozenset(), self.inf.get(big) or frozenset()
        return len(a & b) / len(a) if a else 0.0


def copy_pairs(texts: dict[str, str], dates: dict[str, str | None],
               types: dict[str, str] | None = None) -> list[tuple[str, str, float]]:
    """OCR kopyası ve kontrollü belge imzası bağları → [(a, b, benzerlik)]. Aday çiftler
    örneklenmiş parçacıkların ters dizininden (büyük derlemde ikili tarama yerine)."""
    types = types or {}
    out: list[tuple[str, str, float]] = []
    by_sig: dict[tuple[str, str], list[str]] = {}
    for k, t in texts.items():
        if types.get(k) in CONTROL_TYPES:
            sig = control_signature(t)
            if sig:
                by_sig.setdefault(sig, []).append(k)
    for mem in by_sig.values():
        mem = sorted(mem)
        out.extend((mem[0], b, 1.0) for b in mem[1:])
    ix = CopyIndex(texts)
    samp = {k: {h for h in ix.inf[k] if h % COPY_SAMPLE == 0} for k in texts if ix.usable(k)}
    inv: dict[int, list[str]] = {}
    for k, v in samp.items():
        for h in v:
            inv.setdefault(h, []).append(k)
    co: Counter = Counter()
    for mem in inv.values():
        if len(mem) < 2:
            continue
        mem = sorted(mem)
        for i, a in enumerate(mem):
            for b in mem[i + 1:]:
                co[(a, b)] += 1
    for (a, b), n in co.items():
        if n < 0.5 * COPY_HI * min(len(samp[a]), len(samp[b])):
            continue
        s = ix.copy(a, b, dates.get(a), dates.get(b), types.get(a), types.get(b))
        if s is not None:
            out.append((a, b, s))
    return out
