"""Açıklama metni denetimleri (model yok): cümle bölme, atıf, OD aşımı, yasak ifade.

`bidr write apply` ve `bidr verify` aynı denetimi kullanır. Kurallar:

- Her cümle en az bir `[n_ODk]` atfı taşır (kılavuz gösterimi). Atıf, ölçütün
  `evidence-index.csv` satırlarından birinin `kanit_no`'su olmalı (OD dahil birebir).
- `[komisyon]` işareti: cümle kanıta değil komisyonun verdiği bilgiye dayanır; yalnız o
  ölçüt için komisyon bilgisi verilmişse geçerlidir. Gelecek zaman / plan ifadesi yalnız
  böyle cümlede olabilir (uydurma vaat yok).
- OD aşımı: metin önerilen OD'nin üstünde olgunluk iddia etmez (açık "OD4" anışı, rubriğin
  üst düzey ifadeleri). İzleme/iyileştirme fiili kullanan cümle OD4+ kanıta, özgün/örnek
  gösterilebilir diyen cümle OD5 kanıta atıf yapmalıdır.
- Yasak ifadeler: abartı, slogan, koçluk dili (bkz. YASAK).
"""
from __future__ import annotations

import re

ATIF = re.compile(r"\[(\d+)_OD([1-5])\]")
KOMISYON = "[komisyon]"
_BRACKET = re.compile(r"\[[^\[\]]{1,40}\]")
_ABBR = {"vb", "vs", "ör", "örn", "bkz", "bk", "dr", "prof", "doç", "öğr", "gör", "arş", "no", "s",
         "sn", "md", "mad", "yy", "st", "yrd", "çev", "ed", "vd", "a.ş", "ltd", "şti"}
_BOUNDARY = re.compile(r"[.!?…]+(?=\s+[\"“'(\[A-ZÇĞİÖŞÜ0-9])")


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def _is_abbrev(before: str) -> bool:
    tok = before.split()[-1] if before.split() else ""
    tok = tok.lstrip("(\"“'")
    low = tr_lower(tok)
    if low in _ABBR or len(tok) == 1:
        return True
    if re.fullmatch(r"[A-E](\.\d+)+", tok):          # ölçüt kimliği: "B.1.1."
        return True
    if re.fullmatch(r"\d{1,3}", tok):                 # sıra sayısı: "3. Ulusal"
        return True
    return False


_LEAD = re.compile(r"^(\s*\[[^\[\]]{1,40}\][\s.,;:]*)+")


def split_sentences(text: str) -> list[str]:
    """Paragrafı cümlelere böler. Kısaltma, ölçüt kimliği ve sıra sayısından sonra bölmez;
    noktadan sonra kalan yalnız-atıf parçası önceki cümleye eklenir."""
    text = " ".join((text or "").split())
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        if _is_abbrev(text[start:m.start()]):
            continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    if text[start:].strip():
        out.append(text[start:].strip())
    merged: list[str] = []
    for s in out:
        lead = _LEAD.match(s) if merged else None
        if lead:                       # noktadan sonra gelen atıf önceki cümleye aittir
            merged[-1] = f"{merged[-1]} {lead.group(0).strip()}"
            s = s[lead.end():].strip()
            if not s:
                continue
        merged.append(s)
    return merged


def citations(s: str) -> list[str]:
    return [f"{a}_OD{b}" for a, b in ATIF.findall(s)]


def citation_od(no: str) -> int:
    return int(no.rsplit("_OD", 1)[1])


# -- kurallar ------------------------------------------------------------------------------

YASAK: list[tuple[str, str]] = [
    # (düzenli ifade, tür) — küçük harfe indirilmiş cümleye uygulanır
    (r"\ben iyi\b", "abartı"), (r"\bmükemmel", "abartı"), (r"\bkusursuz", "abartı"),
    (r"\beşsiz\b", "abartı"), (r"\bbenzersiz", "abartı"), (r"\bson derece\b", "abartı"),
    (r"\bbüyük (bir )?başarı", "abartı"), (r"\bbaşarıyla\b", "abartı"), (r"\btitizlikle\b", "abartı"),
    (r"\bözenle\b", "abartı"), (r"\bdünya standartlarında", "abartı"), (r"\ben üst düzey", "abartı"),
    (r"\beksiksiz", "abartı"), (r"\btam anlamıyla\b", "abartı"), (r"\bher zaman\b", "abartı"),
    (r"\bbüyük önem", "abartı"), (r"\bfark yarat", "slogan"), (r"\bvizyoner", "slogan"),
    (r"\bhaydi\b", "slogan"), (r"!", "slogan"),
    (r"\bunutmay", "koçluk"), (r"\böneririz\b", "koçluk"), (r"\btavsiye\b", "koçluk"),
    (r"\b\w+(malıdır|melidir|malısınız|melisiniz)\b", "koçluk"), (r"\bsiz(in|e|i)?\b", "koçluk"),
    (r"\bmuhtemelen\b", "tahmin"), (r"\bbüyük olasılıkla\b", "tahmin"), (r"\btahminen\b", "tahmin"),
    (r"\byapay zek", "meta"),
]
_YASAK = [(re.compile(p), t) for p, t in YASAK]

GELECEK = re.compile(r"\b\w+(acaktır|ecektir|acağız|eceğiz)\b|\bplanlanmaktadır\b|"
                     r"\bhedeflenmektedir\b|\böngörülmektedir\b|\bdüşünülmektedir\b")
# Önerilen OD'nin üstündeki düzeyin rubrik dili (olumlu kullanımda OD aşımı).
UST_DUZEY = {
    4: re.compile(r"sistematik (olarak|biçimde|şekilde) (izlen|değerlendiril|iyileştiril)|"
                  r"pukö döngüsü|puko döngüsü|döngüs\w* kapatıl"),
    5: re.compile(r"içselleştiril|örnek gösterilebilir|örnek teşkil|sürdürülebilir"),
}
# Bu fiiller cümlede olumlu geçiyorsa cümle OD4+ kanıta atıf yapmalı.
FIIL_K = re.compile(r"\b(izlen|iyileştiril|gözden geçiril)(mekte|mektedir|miştir|mekte olup|erek|ir)\b|"
                    r"\bönlem(ler)? alın(mış|makta)")
FIIL_Z = re.compile(r"\bözgün\b|örnek gösterilebilir|içselleştiril")
OLUMSUZ = re.compile(r"\w+(mamaktadır|memektedir|mamıştır|memiştir|mamakta|memekte)\b|"
                     r"bulunmamaktadır|\byoktur\b|\bdeğildir\b")
OD_ANIS = re.compile(r"\b(?:od|olgunluk düzeyi\w*)\s*[-:]?\s*([1-5])\b")


def check_sentence(s: str, *, index_nos: set[str], od: int, komisyon: bool) -> list[dict]:
    """Tek cümlenin kod denetimi → sorun listesi [{kod, ayrinti}]."""
    issues: list[dict] = []
    cites = citations(s)
    kom = KOMISYON in s
    for b in _BRACKET.findall(s):
        if b != KOMISYON and not ATIF.fullmatch(b) and re.search(r"od\s*\d", tr_lower(b)):
            issues.append({"kod": "gecersiz_atif_bicimi", "ayrinti": f"{b} (biçim: [1_OD3])"})
    if not cites and not kom:
        issues.append({"kod": "atifsiz", "ayrinti": "cümlede [n_ODk] atfı yok"})
    for c in cites:
        if c not in index_nos:
            issues.append({"kod": "bilinmeyen_atif", "ayrinti": f"[{c}] bu ölçütün kanıt listesinde yok"})
    if kom and not komisyon:
        issues.append({"kod": "komisyon_bilgisi_yok", "ayrinti": "[komisyon] işareti var ama bu ölçüt için "
                                                                 "komisyon bilgisi verilmedi"})
    low = tr_lower(ATIF.sub(" ", s).replace(KOMISYON, " "))
    for rx, kind in _YASAK:
        m = rx.search(low)
        if m:
            issues.append({"kod": "yasak_ifade", "ayrinti": f"{kind}: “{m.group(0)}”"})
    g = GELECEK.search(low)
    if g and not kom:
        issues.append({"kod": "gelecek_vaat", "ayrinti": f"“{g.group(0).strip()}”: gelecek/plan ifadesi "
                                                         f"yalnız komisyon bilgisine dayanabilir"})
    for m in OD_ANIS.finditer(low):
        if int(m.group(1)) > od:
            issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” > önerilen OD{od}"})
    neg = bool(OLUMSUZ.search(low))
    if not neg:
        for lvl, rx in UST_DUZEY.items():
            m = rx.search(low)
            if m and od < lvl:
                issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” OD{lvl} dili; önerilen OD{od}"})
        top = max((citation_od(c) for c in cites if c in index_nos), default=0)
        m = FIIL_K.search(low)
        if m and top < 4:
            issues.append({"kod": "kanitsiz_ust_duzey",
                           "ayrinti": f"“{m.group(0)}” izleme/iyileştirme iddiası OD4+ kanıt atfı ister"})
        m = FIIL_Z.search(low)
        if m and top < 5:
            issues.append({"kod": "kanitsiz_ust_duzey",
                           "ayrinti": f"“{m.group(0)}” özgünlük iddiası OD5 kanıt atfı ister"})
    return issues


def sentence_rows(paragraphs: list[str], onceki: str = "") -> list[dict]:
    """[{yer, bolum, metin}] — paragraf cümleleri `p<i>.<j>`, önceki yıl karşılaştırması `o.<j>`."""
    rows = []
    for i, p in enumerate(paragraphs, 1):
        for j, s in enumerate(split_sentences(p), 1):
            rows.append({"yer": f"p{i}.{j}", "bolum": "paragraf", "metin": s})
    for j, s in enumerate(split_sentences(onceki or ""), 1):
        rows.append({"yer": f"o.{j}", "bolum": "onceki_yila_gore", "metin": s})
    return rows


def check_text(paragraphs: list[str], onceki: str, *, index_nos: set[str], od: int,
               komisyon: bool = False) -> list[dict]:
    """Tüm metnin kod denetimi → [{yer, metin, kod, ayrinti}] (boş liste: geçti)."""
    out = []
    if not any(p.strip() for p in paragraphs):
        out.append({"yer": "-", "metin": "", "kod": "bos_metin", "ayrinti": "paragraf yok"})
    for r in sentence_rows(paragraphs, onceki):
        for x in check_sentence(r["metin"], index_nos=index_nos, od=od, komisyon=komisyon):
            out.append({"yer": r["yer"], "metin": r["metin"], **x})
    return out
