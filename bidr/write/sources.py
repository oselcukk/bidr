"""Yazım girdileri: `evidence-index.csv`, `audit-olcutler.json`, önceki yılın metni,
komisyon bilgisi. Hepsi salt okunur."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Callable

import yaml

INDEX = "evidence-index.csv"
AUDIT = "audit-olcutler.json"
NOTES = "rapor-notlari.yaml"       # isteğe bağlı: {ölçüt: [komisyonun verdiği bilgi, ...]}
CONFIG_SECTION = "rapor"           # config.yaml: rapor: {onceki_rapor: <docx | klasör>}
CTX = 350                          # alıntı çevresinde bağlam (karakter, her yan)
MAX_QUOTES = 3


def _list(v: str) -> list:
    v = (v or "").strip()
    if not v:
        return []
    if v.startswith("["):
        try:
            x = json.loads(v)
            return x if isinstance(x, list) else [x]
        except ValueError:
            pass
    return [x for x in re.split(r"[;,\s]+", v) if x]


def _quotes(v: str) -> list[str]:
    """`alintilar` sütunu: JSON liste (sözleşme); düz metin tek alıntı sayılır."""
    v = (v or "").strip()
    if v.startswith("["):
        try:
            x = json.loads(v)
            if isinstance(x, list):
                return [str(q) for q in x if str(q).strip()]
        except ValueError:
            pass
    return [v] if v else []


def load_index(path: Path) -> dict[str, list[dict]]:
    """{ölçüt: [satır, …]} — satır alanları sözleşmedeki sütunlar; `alintilar`/`yuvalar` liste."""
    out: dict[str, list[dict]] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if not r.get("kanit_no") or not r.get("olcut"):
                continue
            r = {k: (v or "").strip() for k, v in r.items() if k}
            r["alintilar"] = _quotes(r.get("alintilar", ""))
            r["yuvalar"] = [str(x) for x in _list(r.get("yuvalar", ""))]
            try:
                r["od"] = int(r.get("od") or r["kanit_no"].rsplit("_OD", 1)[1])
            except (ValueError, IndexError):
                r["od"] = None
            out.setdefault(r["olcut"], []).append(r)
    for rows in out.values():
        rows.sort(key=lambda r: int(r["kanit_no"].split("_")[0]) if r["kanit_no"].split("_")[0].isdigit() else 0)
    return out


def load_audit(path: Path) -> dict[str, dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = d.get("olcutler", d) if isinstance(d, dict) else d
    return {r["olcut"]: r for r in rows}


def load_notes(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): [str(x) for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
            for k, v in d.items() if v}


def part_scope(text: str | None, parts: list[dict], quotes: list[str],
               verify: Callable) -> tuple[str | None, dict | None]:
    """Birleşik belgede kanıt paketinin metin penceresi: yalnız alıntıların geçtiği parçaların
    sayfaları (`documents.jsonl` `parcalar`; sayfalar metinde form feed ile ayrılır) → (kısıtlı
    metin, alıntının ilk parçası). Parçasız belgede, metin yoksa ya da hiçbir alıntı bir parçaya
    yerleşmezse (metin, None): pencere değişmez.

    Kör test 2026-11-20: alıntı bağlamı, "dönem içi bilgi" ve "ölçütle ilgili bilgi" pencereleri
    bütün metinden alınınca aynı PDF'e eklenmiş ilgisiz bir yönergenin Senato kararı ya da başka
    tarihli bir tutanak kanıtın kendisine mal ediliyordu."""
    if not text or len(parts or []) < 2:
        return text, None
    from bidr.identify.parca import part_of_page
    pages = text.split("\f")
    starts, pos = [], 0
    for p in pages:
        starts.append(pos)
        pos += len(p) + 1
    hit: list[int] = []
    for q in quotes[:MAX_QUOTES]:
        ok, _score, span = verify(q, text)
        if not (ok and span):
            continue
        pg = max(i for i, s in enumerate(starts) if s <= span[0])
        j = part_of_page(parts, pg)
        if j is not None and j not in hit:
            hit.append(j)
    if not hit:
        return text, None
    keep = sorted({i for j in hit for i in range(parts[j]["sayfa"][0] - 1, parts[j]["sayfa"][1])
                   if 0 <= i < len(pages)})
    return "\f".join(pages[i] for i in keep), parts[hit[0]]


def evidence_context(text: str | None, quotes: list[str], verify: Callable) -> list[dict]:
    """Her alıntı için belgedeki konumu ve çevresi. Metin yoksa yalnız alıntı."""
    out = []
    for q in quotes[:MAX_QUOTES]:
        item = {"alinti": q, "alinti_belgede": None, "baglam": ""}
        if text:
            ok, _score, span = verify(q, text)
            item["alinti_belgede"] = bool(ok)
            if ok and span:
                a, b = span
                item["baglam"] = " ".join(text[max(0, a - CTX):min(len(text), b + CTX)].split())
        out.append(item)
    return out


# -- dönem içi ve ölçütle ilgili bilgi (alıntı dışında) -------------------------------------------
# Kör test 2026-11-20: yazar yalnız alıntıyı ve ±350 karakter bağlamını gördüğü için kullanılan
# belgedeki dönem içi kayıtları (listede 2025 başlangıçlı proje) ve ölçütün sorduğu bilgiyi
# ("etkinlik bütçesi üniversitemiz tarafından karşılanmıştır") atlıyordu. Pakete, alıntı bağlamının
# dışında kalan dönem yılını anan pencereler ve ölçüt konusuna ait cümleler eklenir (önce bunlar).
DONEM_PENCERE = 220                # dönem yılının her yanında (karakter)
MAX_DONEM = 4
MAX_KONU = 3
# ölçüt tanımında geçen konu → belgede aranacak (katlanmış) ifade
KONU_IPUCU: list[tuple[str, str]] = [
    (r"\bmali\b|kaynak", r"\bbutce\w*|\bodenek\w*|karsilan\w*|finanse\w*"),
    (r"gorev tanim|organizasyonel|yetki", r"temsilci\w*|gorevlendir\w*|\bsorumlu\w*|koordinator\w*"),
    (r"performans|gosterge|hedeflerle", r"gerceklesme\w*|hedef(?:lenen)? deger\w*|hedefin (?:alti|ustu)\w*"),
]


_BASLIK_TARIHI = re.compile(r"yayin tarihi|evrak tarih|deg\.? ?tarihi|degisiklik tarihi|revizyon tarihi|gazete"
                            r"|son guncelleme|yururluk tarihi|\bsayi\s*:|\btarih\s*:")


def _spans_overlap(a: int, b: int, spans: list[tuple[int, int]]) -> bool:
    return any(min(b, y) - max(a, x) > (b - a) // 2 for x, y in spans)


def quote_spans(text: str | None, quotes: list[str], verify: Callable) -> list[tuple[int, int]]:
    """Alıntı bağlamlarının [başlangıç, bitiş) aralıkları (evidence_context ile aynı genişlik)."""
    out = []
    if not text:
        return out
    for q in quotes[:MAX_QUOTES]:
        ok, _score, span = verify(q, text)
        if ok and span:
            out.append((max(0, span[0] - CTX), min(len(text), span[1] + CTX)))
    return out


def _window(text: str, a: int, b: int) -> tuple[int, int]:
    """Pencereyi sözcük sınırına genişletir."""
    while a > 0 and not text[a - 1].isspace():
        a -= 1
    while b < len(text) and not text[b].isspace():
        b += 1
    return a, b


def period_snippets(text: str | None, year: int | None, covered: list[tuple[int, int]],
                    limit: int = MAX_DONEM) -> list[str]:
    """Belgede dönem yılını anan (ör. "27.03.2025", "2025/1") ve alıntı bağlamının dışında kalan
    pencereler, belge sırasıyla; örtüşenler birleştirilir."""
    if not text or not year:
        return []
    from bidr.identify.text import fold
    wins: list[list[int]] = []
    for m in re.finditer(rf"(?<!\d){year}(?!\d)", text):
        if _BASLIK_TARIHI.search(fold(text[max(0, m.start() - 45):m.start()])):
            continue                      # belge künyesi: yayın/evrak/değişiklik tarihi bilgi değildir
        a, b = _window(text, max(0, m.start() - DONEM_PENCERE), min(len(text), m.end() + DONEM_PENCERE))
        if wins and a <= wins[-1][1]:
            wins[-1][1] = max(wins[-1][1], b)
        else:
            wins.append([a, b])
    out: list[str] = []
    for a, b in wins:
        x = " ".join(text[a:b].split())
        if _spans_overlap(a, b, covered) or x in out:
            continue
        out.append(x)
        if len(out) >= limit:
            break
    return out


_CUMLE = re.compile(r"[^.!?\n]*(?:[.!?]|$)")


def topic_snippets(text: str | None, description: str, covered: list[tuple[int, int]],
                   limit: int = MAX_KONU) -> list[str]:
    """Ölçüt tanımının konusuna ait (bütçe/kaynak, görevli/temsilci, gerçekleşme/hedef) ve alıntı
    bağlamının dışında kalan cümleler."""
    from bidr.identify.text import fold
    if not text:
        return []
    d = fold(description or "")
    pats = [re.compile(x) for t, x in KONU_IPUCU if re.search(t, d)]
    if not pats:
        return []
    # satır sonu cümleyi bölmesin (PDF metni): satırları birleştirerek konumları koru
    flat = text.replace("\n", " ")
    out: list[str] = []
    for m in re.finditer(r"[^.!?]{20,400}[.!?]", flat):
        a, b = m.start(), m.end()
        if _spans_overlap(a, b, covered):
            continue
        low = fold(m.group(0))
        hit = next((h for p in pats if (h := p.search(low))), None)
        if hit is None:
            continue
        # cümle başı satır kırılımında yitmiş olabilir: konu sözcüğünden en çok 160 karakter geri,
        # satır başından (büyük harf) başlat
        seg = m.group(0)
        if hit.start() > 160:
            seg = seg[hit.start() - 160:]
        lines = text[a:b].split("\n")
        if len(lines) > 1:
            last = next((ln for ln in reversed(lines) if fold(ln).find(low[hit.start():hit.end()]) >= 0), None)
            if last is not None and last.strip()[:1].isupper():
                seg = flat[a:b][flat[a:b].find(last.strip()):]
        x = " ".join(seg.split())
        if x not in out:
            out.append(x)
            if len(out) >= limit:
                break
    return out


# Gösterge tablosunda birimin kendi satırı (kör test 2026-11-20, Kimya A.2.2/C.3.1): tablo fakülte
# geneli gerçekleşme değerini (0,36) verip bölümün ham verisini ("kimya bölümü: 8 yayın 28 öğretim
# üyesi") ayrı satırda tutuyordu; yazar fakülte değerini bölümün değeri gibi yazdı. Birimin adını
# sayıyla birlikte anan satırlar pakette ayrıca ve önce verilir (alıntı bağlamında olsa da).
GOSTERGE_BELGE = re.compile(r"gerceklesme|performans gosterge|\bpg\.\d|hedeflenen deger|izleme degerlendirme")
MAX_BIRIM_VERI = 3


def unit_value_snippets(text: str | None, unit: str | None, limit: int = MAX_BIRIM_VERI) -> list[str]:
    """Gösterge/izleme belgesinde birimin adıyla başlayan ve sayı taşıyan kısa parçalar
    ("kimya bölümü: 8 yayın 28 öğretim üyesi"). Belge gösterge belgesi değilse ya da birim adı
    bilinmiyorsa boş."""
    from bidr.identify.text import fold
    if not text or not unit:
        return []
    flat = " ".join(text.split())
    low = fold(flat)
    if len(low) != len(flat) or not GOSTERGE_BELGE.search(low):
        return []
    head = fold(unit).split()[0] if fold(unit).split() else ""
    if len(head) < 3:
        return []
    out: list[str] = []
    rx = re.compile(rf"\b{re.escape(head)}\w*(?:\s+(?:bolum|birim|anabilim)\w*)?\s*(?:[:\-–]|icin|ait)?\s*"
                    rf"(?:\w+\s+){{0,3}}?(?!(?:19|20)\d\d\b)\d+(?:[.,]\d+)?(?![\d\-])[^.;\n]{{0,120}}")
    for m in rx.finditer(low):
        x = flat[m.start():m.end()].strip(" ,")
        if x not in out:
            out.append(x)
            if len(out) >= limit:
                break
    return out


# -- önceki yılın metni ---------------------------------------------------------------------

_SUB = re.compile(r"^\s*([A-E]\.\d+\.\d+)\.?\s")
_HEAD = re.compile(r"^\s*(Açıklamalar|Kanıtlar)\s*:?\s*", re.I)


def _cells(table) -> list[str]:
    seen: list = []                    # birleşik hücre aynı öğeyi döndürür; öğe tutulur (id yeniden kullanılır)
    out = []
    for row in table.rows:
        for c in row.cells:
            if any(c._tc is x for x in seen):
                continue
            seen.append(c._tc)
            out.append(c.text)
    return out


def previous_from_docx(path: Path) -> dict[str, dict]:
    """FR-0833 biçimli eski rapor → {ölçüt: {"aciklama": str, "kanitlar": str}}. Hücreler
    tablo sırasıyla okunur; "B.1.1. Başlık" hücresi geçerli ölçütü belirler, ardından gelen
    "Açıklamalar:" / "Kanıtlar:" hücreleri ona yazılır."""
    import docx
    d = docx.Document(str(path))
    out: dict[str, dict] = {}
    for t in d.tables:
        cur = None
        for cell in _cells(t):
            m = _SUB.match(cell)
            if m:
                cur = m.group(1)
                continue
            h = _HEAD.match(cell)
            if cur and h:
                key = "aciklama" if h.group(1).lower().startswith("aç") else "kanitlar"
                body = "\n".join(x.strip() for x in cell[h.end():].splitlines() if x.strip())
                if body:
                    out.setdefault(cur, {})[key] = body
    return out


def previous_from_dir(path: Path) -> dict[str, dict]:
    """`<ölçüt>.txt` dosyaları ("Açıklamalar:" / "Kanıtlar:" bölümleri isteğe bağlı)."""
    out = {}
    for p in sorted(Path(path).glob("*.txt")):
        if not re.fullmatch(r"[A-E]\.\d+\.\d+", p.stem):
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        parts = re.split(r"(?im)^\s*Kanıtlar\s*:\s*$", raw, maxsplit=1)
        ac = _HEAD.sub("", parts[0].strip(), count=1).strip()
        rec = {"aciklama": ac}
        if len(parts) > 1 and parts[1].strip():
            rec["kanitlar"] = parts[1].strip()
        out[p.stem] = rec
    return out


def load_previous(path: Path | None) -> tuple[dict[str, dict], str | None]:
    """(ölçüt → metin, kaynak adı). Yol yoksa boş."""
    if not path:
        return {}, None
    p = Path(path).expanduser()
    if p.is_dir():
        return previous_from_dir(p), p.name
    if p.suffix.lower() == ".docx" and p.exists():
        return previous_from_docx(p), p.name
    raise FileNotFoundError(f"önceki yıl metni bulunamadı ya da desteklenmiyor (docx ya da klasör): {p}")


def rapor_section(ws_root: Path) -> dict:
    """config.yaml `rapor:` bölümü (yoksa ya da bozuksa {}). Anahtarlar (hepsi isteğe bağlı):
    `onceki_rapor` (geçen yılın FR-0833 docx'i ya da <ölçüt>.txt klasörü), `sablon` (boş FR-0833
    şablonu, render), `kanit_kok_baglanti` (kanıt klasörünün yüklendiği kök adres),
    `yayin_alan_adlari` (belge gövdesindeki URL'nin yayın adresi sayılacağı alan adları),
    `yeniden_yazim_siniri` (reddedilen metin için en çok yeniden yazım turu; vars. 2),
    `paralel_esik` / `paralel_adim` / `paralel_azami` (model aşamalarının parça sayısı; `bidr parcala`)."""
    p = Path(ws_root) / "config.yaml"
    if not p.exists():
        return {}
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    sec = d.get(CONFIG_SECTION) if isinstance(d, dict) else None
    return sec if isinstance(sec, dict) else {}


def configured_previous(ws_root: Path) -> str | None:
    """config.yaml `rapor.onceki_rapor` (yoksa None)."""
    v = rapor_section(ws_root).get("onceki_rapor")
    return str(v) if v else None


def unit_name(ws_root: Path) -> tuple[str | None, str | None]:
    """(birim adı, profil) config.yaml `bidr:` bölümünden; yoksa (None, None)."""
    from bidr.init.config import load_section
    sec = load_section(Path(ws_root)) or {}
    return sec.get("birim"), sec.get("profil")
