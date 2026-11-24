"""Açıklama metni denetimleri (model yok): cümle bölme, atıf, OD aşımı, yasak ifade.

`bidr write apply` ve `bidr verify` aynı denetimi kullanır. Kurallar:

- Her cümle en az bir `[n_ODk]` atfı taşır (kılavuz gösterimi). Atıf, ölçütün
  `evidence-index.csv` satırlarından birinin `kanit_no`'su olmalı (OD dahil birebir).
- `[komisyon]` işareti: cümle kanıta değil komisyonun verdiği bilgiye dayanır; yalnız o
  ölçüt için komisyon bilgisi verilmişse geçerlidir. Gelecek zaman / plan ifadesi yalnız
  böyle cümlede olabilir (uydurma vaat yok).
- OD aşımı: metin önerilen OD'nin üstünde olgunluk iddia etmez (açık "OD4" anışı, rubriğin
  üst düzey ifadeleri). İzleme/iyileştirme fiili kullanan cümle OD4+ kanıta, özgün/örnek
  gösterilebilir diyen cümle OD5 kanıta atıf yapmalıdır. Yol/usul izlemek ("yönergedeki adımlar
  izlenerek") ve belge hükmünü aktaran cümledeki ulaç ("… izlenerek değerlendirileceği
  belirtilmektedir") izleme iddiası değildir.
- "öngörülmektedir" gibi belge fiilleri atıflı ve hüküm/düzenleme diliyle (yönerge, madde, koşul,
  ölçüt, program…) anlatılan cümlede belgenin içeriğidir; öteki yerde gelecek vaadi sayılır.
- Kısaltmalar (unvanlar, "A.Ş.", "San. ve Tic.", "Ltd. Şti.") cümleyi bölmez.
- Yasak ifadeler: abartı, slogan, koçluk dili (bkz. YASAK).
- Aracın iç dili (`ic_dil`: "Eksik kanıt notu", "OD'ye sayılmamıştır", "eşleşmiş", "uygulama
  halkası", alt çizgili işaretler): komisyon notudur, metne girmez (bkz. bidr/write/ic_dil.py).
- Belge/birim adı içindeki terim ("GTÜ Yapay Zekâ Politikası", "Sürdürülebilirlik
  Koordinatörlüğü", tırnak içi ad) yasak ifade, vaat ve üst düzey dil denetimlerinden muaftır
  (`name_spans`); ad dışındaki aynı terim yakalanır.
"""
from __future__ import annotations

import re

ATIF = re.compile(r"\[(\d+)_OD([1-5])\]")
KOMISYON = "[komisyon]"
_BRACKET = re.compile(r"\[[^\[\]]{1,40}\]")
_ABBR = {"vb", "vs", "ör", "örn", "bkz", "bk", "dr", "prof", "doç", "öğr", "gör", "arş", "no", "s",
         "sn", "md", "mad", "yy", "st", "yrd", "çev", "ed", "vd", "a.ş", "ltd", "şti", "t.c", "nr", "tel",
         "uzm", "okt", "müh", "yük", "sy", "c", "ss", "bşk", "mah", "cad", "sok", "dk", "sa",
         # şirket unvanı kısaltmaları: "ABC Kimya San. ve Tic. A.Ş.", "XYZ İnş. Taah. Ltd. Şti."
         "san", "tic", "inş", "taah", "paz", "ith", "ihr", "elk", "elekt", "mak", "hiz", "hizm",
         "danş", "org", "bilg", "end", "ürt", "dağ", "koll", "inc", "corp", "co", "gmbh"}
# Harf+nokta dizisi: "T.C.", "A.Ş.", "a.g.e." — son noktadan önceki parça "T.C" biçimindedir.
_LETTER_DOTS = re.compile(r"(?:[^\W\d_]{1,2}\.)+[^\W\d_]{1,2}")
_BOUNDARY = re.compile(r"[.!?…]+(?=\s+[\"“'(\[A-ZÇĞİÖŞÜ0-9])")


def tr_lower(s: str) -> str:
    return s.replace("I", "ı").replace("İ", "i").lower()


def _is_abbrev(before: str) -> bool:
    tok = before.split()[-1] if before.split() else ""
    tok = tok.lstrip("(\"“'")
    low = tr_lower(tok)
    if low in _ABBR or len(tok) == 1 or _LETTER_DOTS.fullmatch(tok):
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
    # "Yapay Zekâ" bir program/ders adı olabilir (ör. Yapay Zekâ YL programı); yalnız metnin yapay zekâyla
    # yazıldığını söyleyen meta ifade yasak
    (r"\byapay zek\w*\s+(tarafından|ile|kullanılarak|desteğiyle|araçlarıyla|aracıyla|araçları ile|aracı ile)"
     r"(\s+\w+){0,2}?\s+\w*(yazıl|üretil|oluştur|hazırlan)", "meta"),
]
_YASAK = [(re.compile(p), t) for p, t in YASAK]

GELECEK = re.compile(r"\b\w+(acaktır|ecektir|acağız|eceğiz)\b|\bplanlanmaktadır\b|"
                     r"\bhedeflenmektedir\b|\böngörülmektedir\b|\bdüşünülmektedir\b")
DUZENLEME = re.compile(r"yönerge|yönetmeli|iş akış|usul|esaslar|mevzuat|kanun|karar(ı|ında|da)\b|form\b|"
                       r"rehber|kılavuz|misyon|vizyon|politika|strateji|plan(ı|ında|da)\b|sayfa(sı|sında|da)\b|belge(si|sinde|de)\b|"
                       # hüküm dili: "yayın koşulu öngörülmektedir", "maddesinde … öngörülmektedir"
                       r"madde|hüküm|hükm|koşul|şart(ı|lar)|ölçüt|kriter|zorunlu|tüzü|protokol|sözleşme|"
                       r"talimat|prosedür|ilke(si|leri|lerinde|sinde)\b|müfredat|program(ı|ında|da)\b")
# Belge içeriğini aktaran fiiller: atıflı ve bir düzenleme/belge metnine bağlanan cümlede belgeye
# aittir (mevzuat dili), bölümün vaadi ya da öğüdü değildir.
BELGE_FIIL = {"öngörülmektedir", "hedeflenmektedir", "planlanmaktadır"}
# Önerilen OD'nin üstündeki düzeyin rubrik dili (olumlu kullanımda OD aşımı).
UST_DUZEY = {
    4: re.compile(r"sistematik (olarak|biçimde|şekilde) (izlen|değerlendiril|iyileştiril)|"
                  r"pukö döngüsü|puko döngüsü|döngüs\w* kapatıl"),
    5: re.compile(r"içselleştiril|örnek gösterilebilir|örnek teşkil|sürdürülebilir"),
}
# Bu fiiller cümlede olumlu geçiyorsa cümle OD4+ kanıta atıf yapmalı.
FIIL_K = re.compile(r"\b(izlen|iyileştiril|gözden geçiril)(mekte|mektedir|miştir|mekte olup|erek|ir)\b|"
                    r"\bönlem(ler)? alın(mış|makta)")
# "izlemek" = "(adımı, yolu, usulü) takip etmek": nesnesi bir yol/usul olan izleme ölçme-izleme iddiası
# değildir ("yönergedeki adımlar izlenerek", "iş akışı izlenmektedir").
_YALIN = r"(?:lar|ler)?(?:[ıiuü]|s[ıiuü]|n[ıiuü]|y[ıiuü]|s[ıiuü]n[ıiuü]|[ıiuü]n[ıiuü]|lar[ıi]|ler[ıi])?"
# yalnız yalın/belirtme hâli ("adımlar", "akışı", "usulü"); "yoluyla", "aşamada", "sırasında" gibi
# araç/zaman anlatan biçimler ölçme-izleme iddiasıdır, muaf değildir.
_IZLE_USUL = re.compile(rf"\b(?:adım|yol|yöntem|usul|prosedür|akış|sıra|aşama|talimat|kural|esas|hüküm|hükm|"
                        rf"yönerge|yönetmelik|mevzuat|takvim|şema|madde|ilke|protokol){_YALIN}\s+$")

# Belgenin içeriğini aktaran cümle: ulaç ("izlenerek", "iyileştirilerek") belgedeki hükmün parçasıdır,
# cümlenin yüklemi belgeyi aktaran fiildir ("… izlenerek değerlendirileceği belirtilmektedir").
_AKTARIM_SONU = re.compile(r"\b(öngörülmektedir|öngörmektedir|belirtilmektedir|belirtilmiştir|belirtmektedir|"
                           r"tanımlanmıştır|tanımlanmaktadır|tanımlamaktadır|düzenlenmiştir|düzenlenmektedir|"
                           r"düzenlemektedir|hükme bağlanmıştır|ifade edilmektedir|yer almaktadır)\W*$")
_CEKIMLI = re.compile(r"[;:]|\w+(d[ıiuü]r|t[ıiuü]r|m[ıiuü]ş|d[ıiuü])\b")
FIIL_Z = re.compile(r"\bözgün\b|örnek gösterilebilir|içselleştiril")
OLUMSUZ = re.compile(r"\w+(mamaktadır|memektedir|mamıştır|memiştir|mamakta|memekte)\b|"
                     r"bulunmamaktadır|\byoktur\b|\bdeğildir\b")
OD_ANIS = re.compile(r"\b(?:od|olgunluk düzeyi\w*)\s*[-:]?\s*([1-5])\b")


# -- özel adlar (belge/birim adı) ------------------------------------------------------------
# Belge ya da birim adının içindeki terim ("GTÜ Yapay Zekâ Politikası", "Sürdürülebilirlik
# Koordinatörlüğü") metnin kendi iddiası değildir: yasak ifade ve üst düzey dil denetimleri
# ad öbeklerini görmez. Ad öbeği: tırnak içi ad; büyük harfle başlayan en az iki sözcüklük öbek
# (arada "ve/ile/için" olabilir); ya da bir ad ekiyle (Politikası, Koordinatörlüğü, …) biten öbek.
_AD_EKI = ("politika", "yönerge", "yönetmeli", "koordinatörlü", "ofis", "merkez", "komisyon", "kurul",
           "birim", "müdürlü", "başkanlı", "rektörlü", "dekanlı", "bölüm", "fakülte", "enstitü",
           "üniversite", "program", "plan", "rapor", "strateji", "esasları", "usul", "kılavuz", "rehber",
           "amaçları", "proje", "topluluğ", "kulüb", "laboratuvar", "platform", "grub", "çalıştay",
           "sempozyum", "kongre", "ödül", "ağı", "akademi", "okulu", "konsey", "kanun", "ilke")
_BAGLAC = {"ve", "ile", "için", "&", "-", "–", "veya", "ve/veya"}
_TIRNAK = re.compile(r"“[^“”]{1,150}”|\"[^\"]{1,150}\"|«[^«»]{1,150}»|‘[^‘’]{1,150}’")
_TOKEN = re.compile(r"\S+")
_UPPER = "ABCÇDEFGĞHIİJKLMNOÖPQRSŞTUÜVWXYZÂÎÛ"


def _core(tok: str) -> str:
    return tok.strip("\"“”«»‘'(),;:.!?…[]")


def _is_cap(tok: str) -> bool:
    c = _core(tok)
    return bool(c) and c[0] in _UPPER and not re.match(r"OD\s*\d", c)


def _has_eki(tok: str) -> bool:
    w = tr_lower(re.split(r"['’]", _core(tok))[0])
    return any(w.startswith(e) for e in _AD_EKI)


def _ends_run(tok: str) -> bool:
    return tok[-1:] in ",;:.!?…)]\"”»"


def name_spans(s: str) -> list[tuple[int, int]]:
    """Cümledeki belge/birim adı öbeklerinin [başlangıç, bitiş) aralıkları."""
    spans = [(m.start(), m.end()) for m in _TIRNAK.finditer(s)]
    toks = list(_TOKEN.finditer(s))
    first = next((i for i, t in enumerate(toks) if not t.group(0).startswith("[")), 0)
    i = 0
    while i < len(toks):
        if not _is_cap(toks[i].group(0)):
            i += 1
            continue
        run, j = [i], i
        while not _ends_run(toks[j].group(0)) and j + 1 < len(toks):
            nxt = toks[j + 1].group(0)
            if _is_cap(nxt):
                j += 1
            elif (nxt.lower() in _BAGLAC and j + 2 < len(toks) and _is_cap(toks[j + 2].group(0))):
                j += 2
            else:
                break
            run.append(j)
        eki = _has_eki(toks[run[-1]].group(0))
        # Cümle başındaki sözcük her durumda büyük harfle yazılır: öbek ad ekiyle bitmiyorsa ve
        # sözcük kısaltma değilse ada sayılmaz ("Mükemmel GTÜ ortamı" → yalnız "GTÜ").
        if run[0] == first and not eki and not _core(toks[run[0]].group(0)).isupper():
            run = run[1:]
        if run and (len(run) >= 2 or eki):
            spans.append((toks[run[0]].start(), toks[run[-1]].end()))
        i = j + 1
    return spans


def mask_names(s: str) -> str:
    """Ad öbeklerini boşlukla örter (uzunluk korunur)."""
    for a, b in name_spans(s):
        s = s[:a] + " " * (b - a) + s[b:]
    return s


def _fiil_k(ad: str, low: str, cites: list[str]):
    """Olumlu izleme/iyileştirme fiili (OD4+ iddiası); yol/usul izlemek ve belge içeriğini aktaran
    cümledeki ulaç sayılmaz."""
    for m in FIIL_K.finditer(ad):
        w = m.group(0)
        if w.startswith("izlen") and _IZLE_USUL.search(ad[:m.start()]):
            continue
        son = _AKTARIM_SONU.search(ad.rstrip())
        if w.endswith("erek") and son and cites and DUZENLEME.search(low) \
                and not _CEKIMLI.search(ad[m.end():son.start()]):
            continue   # ulaç ile aktaran fiil arasında başka yüklem (";", "-mıştır") yoksa
        return m
    return None


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
    bare = ATIF.sub(" ", s).replace(KOMISYON, " ")
    low = tr_lower(bare)
    # Yasak ifade, vaat ve üst düzey dil denetimleri belge/birim adlarını görmez (`ad`).
    ad = tr_lower(mask_names(bare))
    for rx, kind in _YASAK:
        m = rx.search(ad)
        if m and kind == "koçluk" and m.group(0).startswith("tavsiye") and "tavsiye edil" in low \
                and cites and DUZENLEME.search(low):
            continue   # "yönergede … tavsiye edilmektedir": belgenin içeriği, öğüt değil
        if m:
            issues.append({"kod": "yasak_ifade", "ayrinti": f"{kind}: “{m.group(0)}”"})
    from .ic_dil import sorunlar as _ic_dil
    issues += _ic_dil(bare)
    g = GELECEK.search(ad)
    # Mevzuat dili: "yönergede … öngörülmektedir" gelecek vaadi değil, "hükme bağlanmıştır"
    # anlamındadır; atıflı ve bir düzenleme belgesini anlatan cümlede kabul edilir.
    if g and g.group(0).strip() in BELGE_FIIL and cites and DUZENLEME.search(low):
        g = None
    if g and not kom:
        issues.append({"kod": "gelecek_vaat", "ayrinti": f"“{g.group(0).strip()}”: gelecek/plan ifadesi "
                                                         f"yalnız komisyon bilgisine dayanabilir"})
    for m in OD_ANIS.finditer(low):
        if int(m.group(1)) > od:
            issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” > önerilen OD{od}"})
    neg = bool(OLUMSUZ.search(low))
    if not neg:
        for lvl, rx in UST_DUZEY.items():
            m = rx.search(ad)
            if m and od < lvl:
                issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” OD{lvl} dili; önerilen OD{od}"})
        top = max((citation_od(c) for c in cites if c in index_nos), default=0)
        m = _fiil_k(ad, low, cites)
        if m and top < 4:
            issues.append({"kod": "kanitsiz_ust_duzey",
                           "ayrinti": f"“{m.group(0)}” izleme/iyileştirme iddiası OD4+ kanıt atfı ister"})
        m = FIIL_Z.search(ad)
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


# -- içerik denetimleri (kanıt paketine göre; kör test 2026-11-20 güncelleme ölçümü) ---------------
# 1) Dönem içi kaydı atlama (Kimya C.2.2): belgede dönem içi tarihli kayıt (2025'te başlayan RSC
#    projesi) varken metin o belgeyle yalnız dönem dışı kayıtları (2018–2022 projeleri) anlatıyor.
# 2) Fakülte değeri (Kimya A.2.2/C.3.1): fakülte/kurum geneli gerçekleşme değeri (0,36) bölümün
#    kendi değeri (8/28 = 0,29) olmadan veriliyor; okur fakülte değerini bölümünkü sanır.

def _fold(s: str) -> str:
    from bidr.identify.text import fold
    return " ".join(fold(s or "").split())


def dated_in_period(snippets: list[str], donem: int | None) -> bool:
    """Parçalardan biri dönem yılında tam tarih ("27.03.2025", "12-09-2025") ya da "2025 yılı" taşıyor mu."""
    if not donem:
        return False
    rx = re.compile(rf"(?<!\d)\d{{1,2}}[./-]\d{{1,2}}[./-]{donem}(?!\d)|(?<!\d){donem} yil")
    return any(rx.search(_fold(x)) for x in snippets or [])


_YIL = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")


def period_state(sentence: str, donem: int) -> str | None:
    """Cümlenin anlattığı dönem: "ic" (dönem yılı ya da dönemi kapsayan aralık: 2023–2026), "dis"
    (yalnız dönem dışı yıllar) ya da None (yıl yok)."""
    years = [int(y) for y in _YIL.findall(ATIF.sub(" ", sentence))]
    if not years:
        return None
    if donem in years or any(a < donem < b for a, b in zip(years, years[1:])):
        return "ic"
    return "dis"


def donem_issues(paragraphs: list[str], onceki: str, *, donem: int | None, donem_ici: set[str]) -> list[dict]:
    """Dönem içi kaydı olan kanıta atıf yapan cümlelerin hiçbiri dönem içini anlatmıyor, en az biri
    yalnız dönem dışı kayıt anlatıyorsa → `donem_ici_atlandi`."""
    if not donem or not donem_ici:
        return []
    rows = sentence_rows(paragraphs, onceki)
    out = []
    for no in sorted(donem_ici, key=lambda x: int(x.split("_")[0])):
        states = [(r, period_state(r["metin"], donem)) for r in rows if no in citations(r["metin"])]
        if states and not any(st == "ic" for _, st in states) and any(st == "dis" for _, st in states):
            r = next(r for r, st in states if st == "dis")
            out.append({"yer": r["yer"], "metin": r["metin"], "kod": "donem_ici_atlandi",
                        "ayrinti": f"[{no}] belgesinde {donem} dönemine ait kayıt var (paketteki \"dönem içi bilgi\"); "
                                   "metin bu kanıtla yalnız dönem dışı kayıtları anlatıyor: önce dönem içi kayıt "
                                   "anlatılır, eski kayıt yalnız bağlam olarak anılır"})
    return out


UST_BIRIM = re.compile(r"\bfakulte(?!\w* (?:yonetim )?kurul)\w*|\btbf\b|universite genel\w*|kurum genel\w*")
GERCEK_DEGER = re.compile(r"(?:gerceklesme|gerceklesen|gerceklest)\w*[^.;]{0,50}?(?<![\d.,])\d+[.,]\d+"
                          r"|\b(?:orani|ortalamasi)\b[^.;]{0,30}?(?<![\d.,])\d+[.,]\d+")
BOLUM_DEGER = re.compile(r"\bbolum\w*[^.;]{0,100}?(?:(?<![\d.,])\d+[.,]\d+|\d+\s*/\s*\d+)"
                         r"|(?:(?<![\d.,])\d+[.,]\d+|\d+\s*/\s*\d+)[^.;]{0,60}?\bbolum\w*")


# bölümün ham verisi ("kimya bölümü için 8 yayın ve 28 öğretim üyesi"): gerçekleşme değeri başka düzeye aittir
BOLUM_HAM = re.compile(r"\bbolum\w*[^.;]{0,60}?(?<![\d.,])\d+\s+(?:adet\s+)?(?:yayin|ogretim|ogrenci|proje|makale|atif"
                       r"|kisi|personel|arastirmaci)"
                       r"|(?<![\d.,])\d+\s+(?:yayin|ogretim|ogrenci|proje|makale)\w*[^.;]{0,60}?\bbolum")


def faculty_value_issues(paragraphs: list[str]) -> list[dict]:
    """Paragrafta gerçekleşme değeri var, fakülte/kurum geneli anılıyor ya da bölümün yalnız ham verisi
    veriliyor, ama bölümün kendi değeri yok → `fakulte_degeri` (okur değeri bölümünkü sanar)."""
    out = []
    for i, p in enumerate(paragraphs, 1):
        low = _fold(ATIF.sub(" ", p))
        if not GERCEK_DEGER.search(low) or not (UST_BIRIM.search(low) or BOLUM_HAM.search(low)) \
                or BOLUM_DEGER.search(low):
            continue
        sents = split_sentences(p)
        j = next((j for j, s in enumerate(sents, 1) if GERCEK_DEGER.search(_fold(ATIF.sub(" ", s)))), 1)
        out.append({"yer": f"p{i}.{j}", "metin": sents[j - 1] if sents else p, "kod": "fakulte_degeri",
                    "ayrinti": "fakülte/kurum geneli gerçekleşme değeri bölümün kendi değeri olmadan verilmiş: önce "
                               "bölümün değeri yazılır (tabloda bölümün yalnız ham verisi varsa hesabıyla: \"8 yayın / "
                               "28 öğretim üyesi = 0,29\"), fakülte değeri ancak ardından ve fakülte geneli diye "
                               "nitelenerek verilir; hedefle karşılaştırma bölümün değeriyle yapılır"})
    return out


def content_issues(paragraphs: list[str], onceki: str = "", *, donem: int | None = None,
                   donem_ici: set[str] | None = None) -> list[dict]:
    """Kanıt paketine göre içerik denetimleri (dönem içi kayıt, fakülte değeri)."""
    return (donem_issues(paragraphs, onceki, donem=donem, donem_ici=donem_ici or set())
            + faculty_value_issues(paragraphs))
