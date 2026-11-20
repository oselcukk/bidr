"""Kanıt adı ve dosya adı (model yok).

Kanıt adı belgenin çalışma adının kaynağından üretilir: identify `calisma_adi`'yı
`baslik`'tan (yoksa tür etiketinden) ASCII slug olarak kurar; burada aynı kaynak Türkçe
karakterleriyle kullanılır. Başlık işe yaramıyorsa (boş, tek sözcük, bozuk karakter) tür
etiketi geçer. Ad kişi adı taşımaz: unvan/e-posta görülürse ad tür etiketine düşer ve uyarı
verilir. Dosya adı tüm yaygın dosya sistemlerinde güvenli (Windows yasaklı karakterleri yok,
NFC, uzunluk sınırlı).
"""
from __future__ import annotations

import re
import unicodedata

MAX_AD = 80

_PREFIX = {"resmi_yazi": "Yazı", "e_posta": "E-posta"}
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
# Kişi adı işaretleri: akademik/idari unvanlar, hitap, e-posta. Ad üretmek için yeterince
# temkinli; yanlış pozitif yalnız adı tür etiketine düşürür.
_PERSON = re.compile(
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:prof|doç|doc|dr|öğr|ogr|arş|ars|gör|gor|sayın|sayin|"
    r"sn|uzm|okt)\.(?=\s|[A-ZÇĞİÖŞÜ]|$)|"
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])(?:sayın|sayin)(?![A-Za-zçğıöşü])|"   # "öğretim üyesi" tek başına rol adıdır, kişi değil
    r"[\w.+-]+@[\w-]+\.[\w.]+",
    re.IGNORECASE)
_TR_LOWER = str.maketrans("Iİ", "ıi")
_TR_UPPER = str.maketrans("ıi", "Iİ")


def has_person(s: str | None) -> bool:
    return bool(s and _PERSON.search(s))


def _tr_title(s: str) -> str:
    """Tamamı büyük harfli başlığı Türkçe kurala uygun baş harf büyük yaz."""
    letters = [c for c in s if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return s
    out = []
    for w in s.split(" "):
        low = w.translate(_TR_LOWER).lower()
        out.append(low[:1].translate(_TR_UPPER).upper() + low[1:] if low else low)
    return " ".join(out)


def _usable(t: str | None) -> bool:
    if not t:
        return False
    t = t.strip()
    letters = sum(c.isalpha() for c in t)
    if letters < 3 or letters / max(len(t), 1) < 0.6:
        return False
    if any(unicodedata.category(c) in ("Cc", "Co", "Cn") for c in t):
        return False
    if re.search(r"[^\w\s.,;:()'’&/+\-–\[\]%]", t):      # ¢, ! vb.: bozuk metin katmanı
        return False
    return len(re.findall(r"\w+", t)) >= 2


def safe_name(s: str, max_len: int = MAX_AD) -> str:
    s = unicodedata.normalize("NFC", s)
    s = _FORBIDDEN.sub(" ", s).replace("[", "(").replace("]", ")")
    s = re.sub(r"\s+", " ", s).strip(" .-_")
    if len(s) > max_len:
        cut = s[:max_len]
        s = (cut.rsplit(" ", 1)[0] if " " in cut[max_len // 2:] else cut).rstrip(" .,-_")
    return s or "Belge"


def evidence_name(doc: dict | None, type_label: str | None) -> tuple[str, list[str]]:
    """(kanıt adı, uyarılar). `doc`: documents.jsonl kaydı."""
    doc = doc or {}
    uy: list[str] = []
    label = type_label or "Belge"
    base = doc.get("baslik")
    for field_ in ("calisma_adi", "baslik"):
        if has_person(doc.get(field_)):
            uy.append(f"{doc.get('doc_id')}: {field_} kişi adı içeriyor olabilir; kanıt adı tür etiketinden")
            base = None
            break
    base = _tr_title(base.strip()) if _usable(base) else label
    base = re.sub(r"\s*\(\s*$", "", base)                   # yarım kalmış parantez
    if base.count("(") > base.count(")"):
        base += ")"
    pre = _PREFIX.get(doc.get("doc_type") or "")
    if pre and not base.lower().startswith(pre.lower()):
        base = f"{pre} - {base}"
    return safe_name(base), uy


def date_of(doc: dict | None) -> str | None:
    t = (doc or {}).get("tarih")
    if isinstance(t, str) and re.match(r"\d{4}-\d{2}-\d{2}$", t):
        return t
    m = re.match(r"(\d{4}-\d{2}-\d{2})_", (doc or {}).get("calisma_adi") or "")
    return m.group(1) if m else None


def file_name(olcut: str, sira: int, od: int, ad: str, ext: str) -> str:
    """Kılavuzun kanıt gösterimi: `[1-OD3]. Ad.pdf` (kurumca doğrulandı, 2026-11-19). Ölçüt
    dosya adında değil, klasör yolundadır (`evidence/B/B.1/B.1.1/`); `olcut` imza uyumu için
    tutulur."""
    return f"[{sira}-OD{od}]. {ad}{ext.lower()}"


# -- kanıt kodunun OD'si ve numaralama -------------------------------------------------------
# FR-0833 kanıt gösterimi (`[1-OD3]. Ad.pdf`, metinde `[1_OD3]`): koddaki OD kanıtın gösterdiği
# düzeydir, ölçütün nihai OD'si değil; kanıt ölçütün önerilen OD'sinin üstünde olabilir (kılavuz
# örneği: metin OD2, kanıt [2_OD4]). Ama kodun kendi düşüşleri yansır: audit satırının `od`'si
# etkin aşamadan gelir (kurum geneli düzenleme → planla → OD2; `od_kabul` düşüşü; savunmanın
# "yönlendirme/bilgilendirme iyileştirme değil" düşüşü). Ölçütün OD'sine sayılmayan kanıt (dönem
# kuralı: geçmiş/tarihsiz olay; düşük güven) ölçütün önerilen OD'sinin üstünde düzey göstermez.
# Modelin ham OD'si (`od_kabul`, `od_onerisi`) kullanılmaz.
#
# Tutarlılık (kanıt ilkesi `iyilestirme_kaniti`, kör test 2026-11-20): kod ölçüt OD'sinin üstünde
# bir düzeyi yalnız o düzey ölçütte kurulmuşsa gösterir: düzeyin bütün halkaları (OD4: izleme VE
# iyileştirme) audit zincirinde kanıtlı. Yalnız izleme (K) olan ölçütte "OD4" etiketli kanıt
# okura "izleniyor ve iyileştiriliyor" der ve "iyileştirme kanıtı yok" bulgusuyla çelişir; böyle
# kanıtın kodu ölçüt OD'sine iner. Kılavuz örneği (alt halka eksik ama K+Ö kurulmuş: metin OD2,
# kanıt OD4) korunur.

def _zayif(row: dict) -> bool:
    return bool(row.get("zayif")) and row.get("karar") not in ("kabul", "duzelt")


def level_complete(criterion: dict | None, level: int) -> bool:
    """Ölçütün audit zincirinde düzeyin bütün halkaları kanıtlı mı (yuvasız halka sayılmaz, en az
    biri `var`). Zincir bilgisi yoksa True (eski çağrı: sınır uygulanmaz)."""
    from bidr.audit.rules import LEVELS
    z = (criterion or {}).get("zincir")
    if not isinstance(z, dict):
        return True
    links = LEVELS.get(level, ())
    durum = [(z.get(x) or {}).get("durum") for x in links]
    return bool(links) and all(d in ("var", "yuvasiz") for d in durum) and "var" in durum


def evidence_od(rows: list[dict], criterion_od: int | dict | None = None) -> int | None:
    """Bir ölçütte bir kanıtın (audit satırları) kodundaki OD. `criterion_od`: audit'in önerdiği
    ölçüt OD'si ya da ölçütün audit kaydı (`audit-olcutler.json` satırı: `od`, `zincir`). Kayıt
    verilirse ölçüt OD'sinin üstündeki düzey yalnız o düzey ölçütte kurulmuşsa gösterilir
    (`level_complete`). Düzey yoksa None."""
    crit = criterion_od if isinstance(criterion_od, dict) else None
    c_od = crit.get("od") if crit is not None else criterion_od
    sayilan = [r["od"] for r in rows if r.get("sayilir") and r.get("od") and not _zayif(r)]
    if sayilan:
        od = max(sayilan)
        if crit is not None and c_od and od > c_od:
            ok = [lv for lv in range(int(c_od) + 1, od + 1) if level_complete(crit, lv)]
            od = max([int(c_od), *ok])
        return od
    etkin = [r["od"] for r in rows if r.get("od")]
    if not etkin:
        return None
    od = max(etkin)
    return min(od, c_od) if c_od else od


def source_key(doc_id: str, docs: dict | None = None, item=None) -> str:
    """Numaralamada aynı kaynak: aynı içerik (doc_id = sha önekidir), aynı sürüm grubu (identify;
    OCR'lı tarama kopyaları ve kontrollü belgenin sayfaları dahil) ya da kalemin seçimde aldığı
    kapsanan kopya bağı (`item.kaynak_grubu`, bkz. select.merge_contained)."""
    k = getattr(item, "kaynak_grubu", "") if item is not None else ""
    if k:
        return k
    g = ((docs or {}).get(doc_id) or {}).get("surum_grubu")
    return f"surum:{g}" if g else f"sha:{doc_id}"


def number_sources(items: list, key, od) -> list[tuple[int, int, object]]:
    """Bir ölçütün sıralı kalemlerine kanıt numarası verir → [(sıra, kod OD'si, kalem)].
    Aynı kaynağın (`key(kalem)`; bkz. `source_key`) kalemleri tek numara alır: numara grubun ilk
    göründüğü yerde verilir, üyeler yan yana dizilir, kod OD'si grubun en yüksek `od(kalem)`'idir
    (aynı numara tek OD taşır). Seçimi değiştirmez: kalem atılmaz, yalnız numara paylaşılır."""
    order: dict = {}
    for it in items:
        order.setdefault(key(it), []).append(it)
    out = []
    for sira, (_, mem) in enumerate(order.items(), 1):
        g_od = max(od(it) for it in mem)
        out.extend((sira, g_od, it) for it in mem)
    return out
