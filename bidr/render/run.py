"""render çekirdeği: şablon kopyası + `texts/<olcut>.json` (+ `audit-olcutler.json`) → report.docx.

Şablon dosyasına yazılmaz; çıktı her zaman ayrı bir yoldur. Değişen yerler yalnız:
alt ölçüt bloklarının "Açıklamalar" ve "Kanıtlar" hücreleri, öz değerlendirme işareti
(rubrik hücresi), kapaktaki birim adı / yıl / "Raporu Hazırlayanlar" ve (yeni şablonda) "Raporu Onaylayan Birim
Amiri" satırları, son tablodaki dört alanın "Güçlü Yönler" / "Gelişmeye Açık Yönler" hücreleri ve (gerekirse) üstbilgideki
TASLAK satırı. Altbilgi (form no, yayın/değişiklik bilgisi, sayfa numarası) değişmez.

TASLAK nedenleri: doğrulanmamış metin; doğrulamada reddedilmiş yön alanı; boş ya da şablon yönergesi kalan güçlü/gelişmeye açık
yön hücresi; kapakta kalan hazırlayan yer tutucusu (`rapor.hazirlayanlar` boş); şablonda amir bölümü varken
kalan amir yer tutucusu (`rapor.onaylayan` boş); kapsam kararı
gereken (`karar_gerekli`) ölçüt. Kapsam: bidr/render/kapsam.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bidr.criteria.extract_docx import W, _ptext

from . import docx_ops as ops
from .kapsam import BASKA, KARAR
from .template import (ACIKLAMA, COVER_STOP, GELISME, GUCLU, HAZIRLAYAN_YER_TUTUCU, KANIT, YONLER_YONERGE,
                       cover_sections, find_blocks, find_yonler)

# Metni olmayan ölçüt için varsayılan ifade. Gerekçe: kılavuzun "Kapsam" bölümüne göre rapor
# önceki takvim yılıyla sınırlıdır; ifade yalnız bu dönemde *kanıt* bulunamadığını söyler,
# faaliyetin yapılmadığını iddia etmez (bu bir değerlendirme olur), puan da önermez.
# 2025 Matematik raporundaki "Bu kısım için veri bulunmamaktadır." kullanımıyla aynı tonda.
BOS_IFADE = "Bu ölçüt için bu dönemde kanıt bulunamamıştır."
BOS_KANIT = "Bu ölçüt için kanıt bulunmamaktadır."
# Birimin doldurma sorumluluğunda olmayan ölçüt (kapsam `baska_birim`). Gerekçe: şablonun "Sorumlu
# Birimler" bölümü alt ölçütü kimin dolduracağını ölçüt tablosundaki "DOLDURACAK BİRİMLER"e
# bağlar ve her birimi "kılavuzda ilgili olduğu belirtilen bölümler bazında" sorumlu tutar.
# Hücre boş bırakılırsa unutulmuş sanılır; "kanıt bulunamadı" ise birimin eksiği gibi okunur.
# Kısa bir kapsam ifadesi ikisinden de kaçınır; Kanıtlar hücresi yalnız etiketle kalır.
KAPSAM_DISI = "Bu ölçüt birimin doldurma sorumluluğunda değildir."
KAPSAM_KARARI = ("[kapsam kararı gerekli] Bu ölçütün birimce doldurulup doldurulmayacağı henüz "
                 "belirlenmemiştir (gaps.md).")
MADDE = "• "
TASLAK_METNI = "TASLAK — doğrulanmamış ya da eksik içerik var"
DOGRULANMADI = "[doğrulanmadı]"
GOLGE = "FFE699"
PUAN_ISARETLERI = ("kalin", "golge", "yok")
KANIT_BICIMLERI = ("mat", "kilavuz")
RE_NO = re.compile(r"^(\d+)_OD([1-5])$")
RE_ATIF = re.compile(r"\[(\d+_OD[1-5])\]")
RE_ATIF_IC = re.compile(r"\[(\d+)_OD([1-5])\]")
# Kapaktaki yıl paragrafı: eski şablonda "2025", Değ.No:1 şablonunda yer tutucu "20..".
RE_YIL = re.compile(r"^(19|20)(\d\d|\.\.)$")
RE_OLCUT = re.compile(r"\b([A-E]\.\d+\.\d+)\b")
# `[komisyon]`: yazım/doğrulamada cümlenin komisyon bilgisine dayandığını gösteren iç işaret;
# rapora girmez (atıf yerine geçer, okur için anlamı yok).
RE_KOMISYON = re.compile(r"\s*\[komisyon\]")
MANIFEST = ".bidr-render.json"


def atif_gosterimi(m: str, bicim: str = "kilavuz") -> str:
    """Rapora giden metin içi atıf. İç biçim (yazım istemi, write/verify doğrulaması, parmak izleri, texts/*.json)
    `[n_ODk]` kalır; render kılavuz biçiminde onu kanıt listesi satırıyla aynı gösterime çevirir: `[1_OD3]` →
    `[1-OD3]` (kural 2026-11-19: kılavuz gösterimi `[1-OD3]`). `mat` biçiminde metin olduğu gibi kalır."""
    return RE_ATIF_IC.sub(r"[\1-OD\2]", m) if bicim == "kilavuz" else m


def no_gosterimi(no: str, bicim: str = "kilavuz") -> str:
    """Kanıt numarasının okura görünen hâli: `1_OD3` → `1-OD3` (kılavuz); iç anahtar değişmez."""
    m = RE_NO.match(str(no or "").strip())
    return f"{m.group(1)}-OD{m.group(2)}" if m and bicim == "kilavuz" else str(no or "").strip()


def clean_text(m: str) -> str:
    """Rapora girecek paragraf: iç işaretler temizlenir, noktalama önü boşluk düzeltilir."""
    m = RE_KOMISYON.sub("", m)
    m = re.sub(r"\s+([.,;:])", r"\1", m)
    return " ".join(m.split())


@dataclass
class Options:
    puan_isareti: str = "kalin"    # kalin (Kimya 2025 usulü) | golge | yok (Matematik/Fizik/MBG usulü)
    kanit_bicimi: str = "kilavuz"  # kilavuz: "[1-OD3]. ad" (vars.; kılavuz örneği) | mat: "1_OD3: ad"
    bos_ifade: str = BOS_IFADE
    bos_kanit: str = BOS_KANIT
    # Eski seçenek (eksik kanıt notunu rapora yazma): artık etkisiz; not hiçbir durumda rapora girmez.
    eksik_notu: bool = False
    kapsam_disi: str = KAPSAM_DISI   # boş dize: Açıklamalar hücresi yalnız etiketle kalır


@dataclass
class Result:
    out: Path
    dolu: list[str] = field(default_factory=list)
    bos: list[str] = field(default_factory=list)
    dogrulanmamis: list[str] = field(default_factory=list)
    reddedildi: list[str] = field(default_factory=list)
    od: dict[str, int] = field(default_factory=dict)
    taslak: bool = False
    kapak: dict[str, str] = field(default_factory=dict)
    uyarilar: list[str] = field(default_factory=list)
    degisen_parcalar: list[str] = field(default_factory=list)
    baglantili: int = 0
    baglantisiz: list[str] = field(default_factory=list)
    kapsam_disi: list[str] = field(default_factory=list)
    karar_gerekli: list[str] = field(default_factory=list)
    yonler: dict[str, str] = field(default_factory=dict)        # "A Güçlü Yönler" → dolu | bos | yonerge
    hazirlayan: int = 0
    onaylayan: int = 0                                          # kapağa yazılan birim amiri (0/1)
    taslak_nedenleri: list[str] = field(default_factory=list)
    eksik_notlu: list[str] = field(default_factory=list)       # metni olup eksik kanıt notu (gaps.md) olan ölçütler
    # işaretlenen OD'nin kaynağı: onayli (komisyon, audit `od_onayli`) | kod (audit `od`) | metin
    # (audit kaydı yok: write'ın `od_onerisi`). Onaysız işaretlenenler denetle'de uyarı olur.
    od_kaynagi: dict[str, str] = field(default_factory=dict)
    yon_cikarilan: dict[str, list[str]] = field(default_factory=dict)   # alan → desteklenmeyen madde yerleri
    yon_ifadeli: list[str] = field(default_factory=list)               # madde kalmadığı için açık ifadeli hücreler
    # alan → çıkarılan maddelerle hiçbir yön hücresinde kalmayan ölçütler (rapor TASLAK)
    yon_kapsam_kaybi: dict[str, list[str]] = field(default_factory=dict)
    # kanıt klasöründe olup metinde atıf almayan, numara boşluğu kalmasın diye listelenen kanıtlar
    atifsiz_listelenen: dict[str, list[str]] = field(default_factory=dict)

    @property
    def od_onay_bekliyor(self) -> dict[str, dict]:
        """{ölçüt: {od, kaynak}}: rubrikte işaretli ama insanın onaylamadığı düzeyler."""
        return {c: {"od": o, "kaynak": self.od_kaynagi.get(c, "kod")} for c, o in sorted(self.od.items())
                if self.od_kaynagi.get(c) != "onayli"}

    def ozet(self) -> dict:
        return {"cikti": str(self.out), "dolu": len(self.dolu), "bos": len(self.bos),
                "dogrulanmamis": self.dogrulanmamis, "reddedildi": self.reddedildi,
                "od_isaretli": len(self.od), "od_onay_bekliyor": self.od_onay_bekliyor, "taslak": self.taslak, "taslak_nedenleri": self.taslak_nedenleri,
                "kapak": self.kapak, "hazirlayan": self.hazirlayan, "onaylayan": self.onaylayan,
                "kapsam_disi": self.kapsam_disi, "karar_gerekli": self.karar_gerekli, "yonler": self.yonler,
                "eksik_notlu_metin": self.eksik_notlu, "yon_cikarilan": self.yon_cikarilan,
                "yon_ifadeli": self.yon_ifadeli, "yon_kapsam_kaybi": self.yon_kapsam_kaybi,
                "uyari": len(self.uyarilar), "baglantili_kanit": self.baglantili,
                "baglantisiz_kanit": len(self.baglantisiz), "atifsiz_listelenen": self.atifsiz_listelenen,
                "degisen_parcalar": self.degisen_parcalar}


def load_texts(d: Path) -> tuple[dict[str, dict], list[str]]:
    out, uy = {}, []
    if not d.is_dir():
        return out, [f"metin klasörü yok: {d} (bütün ölçütler boş ifadeyle doldurulur)"]
    for p in sorted(d.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            uy.append(f"{p.name}: okunamadı ({e})")
            continue
        cid = t.get("olcut")
        if not cid:
            uy.append(f"{p.name}: 'olcut' alanı yok")
            continue
        if cid in out:
            uy.append(f"{cid}: birden çok metin dosyası; {p.name} atlandı")
            continue
        out[cid] = t
    return out, uy


def load_audit(p: Path | None) -> tuple[dict[str, dict], list[str]]:
    if p is None or not p.exists():
        return {}, [f"audit-olcutler.json yok ({p}); OD önerisi yalnız metinlerden, eksik notu yok"]
    from bidr.kor.od import apply_overrides
    js = json.loads(p.read_text(encoding="utf-8"))
    return apply_overrides({c["olcut"]: c for c in js.get("olcutler") or []}, p.parent), []


def kanit_parts(k: dict, bicim: str) -> tuple[str, str]:
    """(önek, ad): "1_OD3: " + ad (mat) ya da "[1-OD3]. " + ad (kılavuz)."""
    no, ad = str(k.get("no", "")).strip(), str(k.get("ad", "")).strip()
    if bicim == "kilavuz":
        m = RE_NO.match(no)
        if m:
            # kılavuz örneği dosya adını uzantısıyla yazar ("[1-OD3]. Uygulama Örnekleri.pdf"):
            # dosyalanan kanıtın adı ile listedeki ad aynı olsun
            ext = Path(str(k.get("dosya") or "")).suffix.lower()
            if ext and not ad.lower().endswith(ext):
                ad += ext
            return f"[{m.group(1)}-OD{m.group(2)}]. ", ad
    return f"{no}: ", ad


def kanit_line(k: dict, bicim: str) -> str:
    return "".join(kanit_parts(k, bicim))


def load_links(index: Path | None) -> dict[tuple[str, str], str]:
    """evidence-index.csv → {(ölçüt, kanıt no): bağlantı}. Dosya ya da sütun yoksa boş."""
    import csv
    if index is None or not Path(index).exists():
        return {}
    out = {}
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            u = (r.get("baglanti") or "").strip()
            if u and r.get("olcut") and r.get("kanit_no"):
                out[(r["olcut"].strip(), r["kanit_no"].strip())] = u
    return out


@dataclass
class KanitBaglantisi:
    url: str
    web: bool = False          # kaydedilmiş web sayfası kanıtı (adres listede görünür yazılır)


def load_link_rows(index: Path | None, teslim: str = "baglanti",
                   evidence_dir: Path | None = None) -> dict[tuple[str, str], KanitBaglantisi]:
    """evidence-index.csv → {(ölçüt, kanıt no): KanitBaglantisi}, teslim moduna göre.

    `baglanti` (eski davranış): dizindeki `baglanti` olduğu gibi. `dekanlik`: kanıtlar dekanlığa dosya
    olarak teslim edilir; kanıt klasörü kök bağlantısından türeyen (`klasor`) bağlantı girmez (yükleme
    birimin işi değil). Web sayfası kanıtının (`.html`) özgün adresi dizinde yoksa sayfanın kendi
    kaydından okunur (bidr/teslim/web.py; bulunamazsa bağlantısız kalır, uydurulmaz)."""
    import csv

    from bidr.teslim.mod import DEKANLIK
    from bidr.teslim.web import is_web, web_url
    if index is None or not Path(index).exists():
        return {}
    out: dict[tuple[str, str], KanitBaglantisi] = {}
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            c, no = (r.get("olcut") or "").strip(), (r.get("kanit_no") or "").strip()
            if not (c and no):
                continue
            u, src = (r.get("baglanti") or "").strip(), (r.get("baglanti_kaynagi") or "").strip()
            if teslim != DEKANLIK:
                if u:
                    out[(c, no)] = KanitBaglantisi(u)
                continue
            dosya = (r.get("dosya") or "").strip()
            web = bool(dosya) and is_web(dosya)
            if web:
                u, _ = web_url(Path(evidence_dir) / dosya if evidence_dir else None, u, src)
            elif src == "klasor":
                u = ""
            if u and (c, no) not in out:
                out[(c, no)] = KanitBaglantisi(u, web)
    return out


def load_index_rows(index: Path | None) -> dict[str, list[dict]]:
    """evidence-index.csv → {ölçüt: [{no, ad, dosya}]} (kanıt klasöründeki dosyalar). Yoksa boş."""
    import csv
    if index is None or not Path(index).exists():
        return {}
    out: dict[str, list[dict]] = {}
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            c, no = (r.get("olcut") or "").strip(), (r.get("kanit_no") or "").strip()
            if c and RE_NO.match(no):
                out.setdefault(c, []).append({"no": no, "ad": (r.get("ad") or "").strip(),
                                              "dosya": (r.get("dosya") or "").strip()})
    return out


def _no_key(no: str) -> tuple:
    m = RE_NO.match(str(no))
    return (int(m.group(1)), str(no)) if m else (10 ** 6, str(no))


def evidence_list(cited: list[dict], filed: list[dict]) -> tuple[list[dict], list[str]]:
    """Ölçütün kanıt listesi: metnin atıf verdiği kanıtlar + kanıt klasörüne konmuş ama metinde atıf
    almayanlar, numara sırasıyla. Klasördeki numaralar listede boşluk bırakmaz (`bidr denetle`
    `kanit_numarasi` / `listede_olmayan_dosya`); atıfsız olanlar ikinci değerle döner."""
    by = {str(k.get("no", "")).strip(): k for k in cited}
    extra = [k for k in filed if k["no"] not in by]
    for k in extra:
        by[k["no"]] = k
    return [by[n] for n in sorted(by, key=_no_key)], [k["no"] for k in extra]


def eksik_text(a: dict | None) -> str | None:
    """Ölçütün eksik kanıt notu (komisyon için; gaps.md): audit'in `eksik_kanit_notu.metin`'i varsa
    o, yoksa eksik halkaların gereken metinleri. Rapora yazılmaz (kör test 2026-11-20)."""
    if not a:
        return None
    note = audit_note(a)
    if note:
        return note
    items = [e.get("gereken") for e in a.get("eksik") or [] if e.get("gereken")]
    if not items:
        return None
    return "Eksik kanıt notu: " + "; ".join(items) + "."


def audit_note(a: dict | None) -> str | None:
    """audit-olcutler.json `eksik_kanit_notu.metin` (docs/REPORT_LAYER.md "Eksik kanıt notu"):
    `kanitsiz` ya da `neredeyse_kanitsiz` ölçütte dolu. Komisyon notudur: gaps.md'de kalır, rapor
    metnine girmez. Alan yoksa (eski audit çıktısı) ya da `null` ise None."""
    n = (a or {}).get("eksik_kanit_notu")
    if not isinstance(n, dict) or n.get("durum") not in ("kanitsiz", "neredeyse_kanitsiz"):
        return None
    m = " ".join(str(n.get("metin") or "").split())
    return m or None


def _usable(t: dict | None) -> bool:
    return bool(t) and t.get("durum") != "reddedildi" and any(
        (p.get("metin") or "").strip() for p in t.get("paragraflar") or [])


def _mark_od(block, od: int, mode: str) -> bool:
    """Rubrikte `od` sütununu işaretler. Kalın işarette öteki düzey hücrelerinin kalınlığı açıkça
    kaldırılır (tablo stili ilk sütunu kalın yapabilir); işaret satırdaki tek kalın hücredir."""
    if mode == "yok" or not (1 <= od <= 5) or not block.rubric:
        return False
    if mode == "kalin":
        for row in block.rubric:
            for i, tc in enumerate(row, 1):
                if i != od:
                    ops.clear_bold(tc)
    for tc in block.rubric_cells(od):
        if mode == "kalin":
            ops.mark_bold(tc)
        else:
            ops.mark_shade(tc, GOLGE)
    if mode == "golge" and len(block.numbers) == 5:
        ops.mark_shade(block.numbers[od - 1], GOLGE)
    return True


def choose_od(cid: str, a: dict | None, od_text, res: "Result") -> tuple[int, str]:
    """İşaretlenecek düzey ve kaynağı. Önce komisyonun onayladığı `od_onayli` (insan kararı; metnin
    ve kodun önerisini aşar), yoksa kodun önerisi `od` (metnin önerisi onu aşamaz; docs/AUDIT.md
    "Kod önerisi ve nihai düzey ayrı"), o da yoksa metnin önerisi. Hiçbiri yoksa OD1 (kanıtı
    olmayan ölçüt rubriğin ilk düzeyindedir): kapsam dışı olmayan hiçbir ölçüt işaretsiz kalmaz.
    Onaysız işaretler `od_onay_bekliyor` olarak denetle'de uyarı olur."""
    od_a = a.get("od") if a else None
    od_ok = a.get("od_onayli") if a else None
    od = od_text
    if od_ok in (1, 2, 3, 4, 5):
        if od is not None and od != od_ok:
            res.uyarilar.append(f"{cid}: metnin OD önerisi ({od}) komisyonun onayladığı düzeyden ({od_ok}) "
                                f"farklı; OD{od_ok} işaretlendi (metin yeniden yazılmalı mı bakın)")
        return int(od_ok), "onayli"
    if od is None:
        if od_a in (1, 2, 3, 4, 5):
            return int(od_a), "kod"
        return 1, "varsayilan"
    if od_a is not None and od > od_a:
        res.uyarilar.append(f"{cid}: metnin OD önerisi ({od}) audit önerisini ({od_a}) aşıyor; "
                            f"OD{od_a} işaretlendi")
        return int(od_a), "kod"
    return int(od), "kod" if a else "metin"


def _mark(res: "Result", block, cid: str, a: dict | None, od_text, opts: "Options") -> None:
    od, kaynak = choose_od(cid, a, od_text, res)
    if _mark_od(block, od, opts.puan_isareti):
        res.od[cid] = od
        res.od_kaynagi[cid] = kaynak
    elif opts.puan_isareti != "yok":
        res.uyarilar.append(f"{cid}: rubrik satırı bulunamadı; OD{od} işaretlenemedi")


def cover_paragraphs(doc) -> list:
    out = []
    for el in doc.element.body.iterchildren(W + "p"):
        if _ptext(el).strip() == COVER_STOP:
            break
        out.append(el)
    return out


def fill_cover(doc, birim: str | None, yil: int | str | None) -> dict[str, str]:
    """Kapak: "[Birim Adı]" yer tutucusu ve yalnız bir yıl olan ilk paragraf."""
    done: dict[str, str] = {}
    for el in cover_paragraphs(doc):
        txt = _ptext(el).strip()
        if birim and "birim" not in done and "[Birim Adı]" in txt:
            ops.set_paragraph_text(el, birim)
            done["birim"] = birim
        elif yil and "yil" not in done and RE_YIL.match(txt):
            ops.set_paragraph_text(el, str(yil))
            done["yil"] = str(yil)
    return done


def preparer_line(x: dict) -> str:
    """"Dr. Öğr. Üyesi Örnek Kişi, ornek@example.edu, Görev" (şablon: [Üye Unvan, Adı Soyadı, eposta, Görevi])."""
    head = " ".join(str(x.get(k) or "").strip() for k in ("unvan", "ad_soyad")).strip()
    return ", ".join(v for v in (head, str(x.get("eposta") or "").strip(), str(x.get("gorev") or "").strip()) if v)


def _blank(el) -> bool:
    return el is not None and el.tag == W + "p" and ops.is_blank_paragraph(el)


def fill_preparers(doc, people: list[dict] | None, ph: list | None = None) -> tuple[int, list[str]]:
    """Kapaktaki "Raporu Hazırlayanlar" bölümünün "[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]" yer
    tutucularını doldurur (`ph`: `cover_sections` bölümü; verilmezse kapaktan bulunur). Amir bölümünün yer
    tutucusu hazırlayan sayılmaz. Kişi sayısı şablondaki satır sayısıyla sınırlı değildir: fazlası için son
    hazırlayan satırı kopyalanır (hazırlayan bölümünün içine, amir başlığından önce) ve ardındaki boş
    paragraflardan biri silinir (kapak sayfası taşmasın; sonraki başlıktan önceki son boşluk kalır); azsa
    artan yer tutucular boş paragraf olur. Liste boşsa hiçbir şey değişmez. Döner: (yazılan kişi sayısı, uyarılar)."""
    import copy
    if ph is None:
        ph = cover_sections(cover_paragraphs(doc))["hazirlayan"]
    if not people:
        return 0, []
    if not ph:
        return 0, ["kapakta 'Raporu Hazırlayanlar' yer tutucusu bulunamadı; hazırlayanlar yazılmadı"]
    lines = [preparer_line(x) for x in people]
    last = ph[-1]
    for i, line in enumerate(lines):
        if i < len(ph):
            ops.set_paragraph_text(ph[i], line)
            last = ph[i] if i == len(ph) - 1 else last
            continue
        new = copy.deepcopy(ph[-1])
        ops.set_paragraph_text(new, line)
        nxt = last.getnext()
        last.addnext(new)
        # ardındaki boş paragraflardan biri düşer; sonraki bölümden (amir başlığı, yıl) önceki son boşluk kalır
        if _blank(nxt) and _blank(nxt.getnext()):
            nxt.getparent().remove(nxt)
        last = new
    for p in ph[len(lines):]:
        ops.set_paragraph_text(p, "")
    return len(lines), []


def fill_approver(doc, person: dict | None, ph: list | None = None) -> tuple[int, list[str]]:
    """Kapaktaki "Raporu Onaylayan Birim Amiri" yer tutucusuna amirin satırını yazar (hazırlayanla aynı biçim).
    Bölümde birden çok yer tutucu varsa ilki yazılır, artanlar boş paragraf olur. Kişi yoksa hiçbir şey
    değişmez; şablonda bölüm yoksa (eski şablon) kişi yazılmaz, uyarı döner. Döner: (0/1, uyarılar)."""
    if ph is None:
        ph = cover_sections(cover_paragraphs(doc))["amir"]
    if not person:
        return 0, []
    if not ph:
        return 0, ["şablonun kapağında 'Raporu Onaylayan Birim Amiri' bölümü yok (eski şablon); "
                   "rapor.onaylayan yazılmadı"]
    ops.set_paragraph_text(ph[0], preparer_line(person))
    for p in ph[1:]:
        ops.set_paragraph_text(p, "")
    return 1, []


def _left(ph: list) -> int:
    return sum(1 for p in ph if HAZIRLAYAN_YER_TUTUCU in _ptext(p))


def cover_placeholders_left(doc) -> int:
    """Kapakta kalan hazırlayan yer tutucusu (amir bölümü sayılmaz)."""
    return _left(cover_sections(cover_paragraphs(doc))["hazirlayan"])


# -- Güçlü / Gelişmeye Açık Yönler ------------------------------------------------------------------

def load_yonler(d: Path | None) -> dict[str, dict]:
    out = {}
    if d is None or not Path(d).is_dir():
        return out
    for p in sorted(Path(d).glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if t.get("alan"):
            out[t["alan"]] = t
    return out


def _cell_state(tc) -> str:
    txt = " ".join(_ptext(p) for p in tc.iter(W + "p")).strip()
    if not txt:
        return "bos"
    return "yonerge" if YONLER_YONERGE in txt else "dolu"


# Alanda yazılacak madde kalmadığında hücreye konan açık ifade (şablon yönergesi kalmaz). Gerekçe:
# hücre boş ya da yönergeyle kalırsa unutulmuş sanılır (kör test 2026-11-20, Matematik C).
YON_YOK = {"guclu": "Bu alanda bu dönem için kanıtla doğrulanmış bir güçlü yön belirlenmemiştir.",
           "gelisme": "Bu alanda bu dönem için kanıtla doğrulanmış bir gelişmeye açık yön belirlenmemiştir."}
YONLER_LOG = "verify-yonler.jsonl"


def load_yonler_log(p: Path | None) -> dict[str, dict]:
    """`verify-yonler.jsonl` → {alan: kayıt} (yoksa boş)."""
    out: dict[str, dict] = {}
    if p is None or not Path(p).exists():
        return out
    for line in Path(p).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("alan"):
            out[r["alan"]] = r
    return out


def _yon_sha(t: dict) -> str:
    from bidr.write.yonler import text_sha
    return text_sha(t)


def yon_items(t: dict | None, key: str, rec: dict | None) -> tuple[list[dict], list[str], bool]:
    """(basılacak maddeler, çıkarılan madde yerleri, doğrulanmış mı). Doğrulanmış alan: bütün maddeler.
    Reddedilmiş alan: doğrulayıcının (model aşaması, güncel kayıt) "destekleniyor" dediği maddeler
    basılır, öteki maddeler çıkarılır — tek madde yüzünden bütün hücre boş kalmaz. Kod aşamasında
    reddedilen ya da kaydı eski alanın maddesi doğrulanmamıştır: hiçbiri basılmaz."""
    if not t:
        return [], [], False
    prefix = "g" if key == "guclu" else "a"
    rows = [(f"{prefix}{i}", x) for i, x in enumerate(t.get(key) or [], 1) if (x.get("metin") or "").strip()]
    durum = t.get("durum")
    if durum == "dogrulandi":
        return [x for _, x in rows], [], True
    if durum != "reddedildi":
        return [x for _, x in rows], [], False          # taslak: [doğrulanmadı] işaretiyle basılır
    ok = set()
    if rec and rec.get("durum") == "reddedildi" and rec.get("asama") == "model" and rec.get("metin_sha") == _yon_sha(t):
        ok = {(m.get("yer"), " ".join((m.get("metin") or "").split())) for m in rec.get("maddeler") or []
              if m.get("karar") == "destekleniyor"}
    keep = [x for y, x in rows if (y, " ".join(x["metin"].split())) in ok]
    drop = [y for y, x in rows if (y, " ".join(x["metin"].split())) not in ok]
    return keep, drop, True


def fill_yonler(doc, yonler: dict[str, dict], res: "Result", log: dict[str, dict] | None = None,
                bicim: str = "kilavuz") -> None:
    cells, uy = find_yonler(doc)
    res.uyarilar += uy
    log = log or {}
    for alan in sorted(set(yonler) - set(cells)):
        res.uyarilar.append(f"{alan}: güçlü/gelişmeye açık yön maddeleri var ama şablonda tablosu yok; yazılmadı")
    for alan, c in sorted(cells.items()):
        t = yonler.get(alan)
        kept: set[str] = set()
        lost: set[str] = set()
        for key, tc, label in (("guclu", c.guclu_tc, GUCLU), ("gelisme", c.gelisme_tc, GELISME)):
            items, drop, verified = yon_items(t, key, log.get(alan))
            kept |= {k for x in items for k in RE_OLCUT.findall(x.get("metin") or "")}
            if drop:
                res.yon_cikarilan.setdefault(alan, []).extend(drop)
                byyer = {f"{'g' if key == 'guclu' else 'a'}{i}": x for i, x in enumerate(t.get(key) or [], 1)}
                lost |= {k for y in drop for k in RE_OLCUT.findall((byyer.get(y) or {}).get("metin") or "")}
            paras = []
            if items:
                if not verified:
                    paras.append(ops.make_paragraph([(
                        f"{DOGRULANMADI} Bu maddeler doğrulama aşamasından geçmemiştir "
                        f"(durum: {t.get('durum') or 'belirtilmemiş'}).",
                        {"italic": True, "color": ops.TASLAK_RENK})]))
                paras += [ops.make_paragraph(MADDE + atif_gosterimi(" ".join(x["metin"].split()), bicim)) for x in items]
            elif t is not None and verified:
                # alan işlendi ama basılacak doğrulanmış madde yok: açık ifade (yönerge kalmaz)
                paras = [ops.make_paragraph(YON_YOK[key])]
                res.yon_ifadeli.append(f"{alan} {label}")
            if paras:
                ops.replace_cell(tc, paras)
            res.yonler[f"{alan} {label}"] = _cell_state(tc)
        # Doğrulamada reddedilen maddenin çıkarılması bir ölçütü bütün yön hücrelerinden düşürürse
        # hücre eksiktir (kör test 2026-11-20, Kimya C: C.3.1 hiçbir hücrede kalmadı): rapor TASLAK.
        if lost - kept:
            res.yon_kapsam_kaybi[alan] = sorted(lost - kept, key=lambda x: [int(n) for n in x.split(".")[1:]])
    for alan, ys in res.yon_cikarilan.items():
        res.uyarilar.append(f"{alan}: doğrulamada desteklenmeyen {len(ys)} madde rapora alınmadı ({', '.join(ys)}); "
                            "doğrulanmış maddeler basıldı (gerekçe: verify-yonler.jsonl)")


def render(template: Path, out: Path, *, texts_dir: Path, audit_path: Path | None,
           birim: str | None = None, yil: int | str | None = None,
           opts: Options | None = None, index_path: Path | None = None,
           kapsam: dict[str, str] | None = None, yonler_dir: Path | None = None,
           hazirlayanlar: list[dict] | None = None, teslim: str = "baglanti",
           evidence_dir: Path | None = None, yonler_log: Path | None = None,
           onaylayan: dict | None = None) -> Result:
    """`kapsam`: {ölçüt: bolum|ortak|baska_birim|karar_gerekli} (verilmezse hepsi bolum);
    `yonler_dir`: `yonler/<alan>.json` klasörü (`yonler_log`: doğrulama kaydı, vars. klasörün yanındaki
    verify-yonler.jsonl; reddedilen alanda yalnız desteklenen maddeler basılır); `hazirlayanlar`: config.yaml `rapor.hazirlayanlar`;
    `onaylayan`: config.yaml `rapor.onaylayan` (birim amiri; şablonda amir bölümü varsa);
    `teslim`: config.yaml `rapor.teslim` (bidr/teslim/mod.py). `dekanlik`ta web sayfası kanıtının
    satırı adı (bağlantılı) ve özgün adresi görünür yazar: "[1-OD3]. Ad (https://…)"; `evidence_dir`
    web kanıtının adresini sayfanın kendi kaydından okumak için (vars. dizinin yanındaki evidence/)."""
    import docx

    opts = opts or Options()
    if opts.puan_isareti not in PUAN_ISARETLERI:
        raise ValueError(f"puan işareti: {opts.puan_isareti} (seçenekler: {', '.join(PUAN_ISARETLERI)})")
    if opts.kanit_bicimi not in KANIT_BICIMLERI:
        raise ValueError(f"kanıt biçimi: {opts.kanit_bicimi} (seçenekler: {', '.join(KANIT_BICIMLERI)})")
    template, out = Path(template).expanduser().resolve(), Path(out).expanduser().resolve()
    if not template.exists():
        raise FileNotFoundError(f"şablon yok: {template}")
    if out == template:
        raise ValueError("çıktı şablonun üstüne yazılamaz; --out ile başka bir yol verin")

    res = Result(out)
    texts, uy = load_texts(Path(texts_dir))
    res.uyarilar += uy
    audit, uy = load_audit(audit_path)
    res.uyarilar += uy

    if evidence_dir is None and index_path is not None:
        evidence_dir = Path(index_path).parent / "evidence"
    links = load_link_rows(index_path, teslim, evidence_dir)
    filed = load_index_rows(index_path)
    if index_path is not None and not Path(index_path).exists():
        res.uyarilar.append(f"evidence-index.csv yok ({index_path}); kanıt adları bağlantısız")
    elif index_path is not None:
        # ölçütün kanıtı kalmadı (belge kaynaktan çıkarıldı ya da incelemede reddedildi): eski metin ve
        # atıfları rapora girmez; ölçüt kanıtsız ölçüt gibi boş ifadeyle doldurulur (TASLAK sayılmaz)
        yetim = sorted(c for c in texts if c not in filed)
        for cid in yetim:
            del texts[cid]
        if yetim:
            res.uyarilar.append(f"{len(yetim)} metnin ölçütünde artık kanıt yok; rapora alınmadı: {', '.join(yetim)}")
    doc = docx.Document(str(template))
    blocks, uy = find_blocks(doc)
    res.uyarilar += uy
    if not blocks:
        raise ValueError("şablonda alt ölçüt bloğu bulunamadı (FR-0833 biçimi değil mi?)")
    for cid in sorted(set(texts) - set(blocks)):
        res.uyarilar.append(f"{cid}: metni var ama şablonda bloğu yok; yazılmadı")

    kapsam = kapsam or {}
    for cid, b in blocks.items():
        t, a = texts.get(cid), audit.get(cid)
        aciklama: list = []
        kanit: list = []
        od = None
        k = kapsam.get(cid, "bolum")
        if k == BASKA:
            # birimin doldurma sorumluluğunda değil: kısa kapsam ifadesi; kanıt yokluğu yazılmaz, OD yok
            res.kapsam_disi.append(cid)
            if _usable(t):
                res.uyarilar.append(f"{cid}: kapsam baska_birim ama metni var; rapora alınmadı "
                                    "(kapsam yanlışsa config.yaml rapor.kapsam)")
            if opts.kapsam_disi:
                aciklama.append(ops.make_paragraph(opts.kapsam_disi))
            if b.aciklama_tc is not None:
                ops.fill_cell(b.aciklama_tc, ACIKLAMA, aciklama)
            if b.kanit_tc is not None:
                ops.fill_cell(b.kanit_tc, KANIT, [])
            continue
        if k == KARAR:
            res.karar_gerekli.append(cid)
            if not _usable(t):
                # kim dolduracak belli değil: "kanıt bulunamadı" yazılmaz; görünür işaret + TASLAK
                aciklama.append(ops.make_paragraph([(KAPSAM_KARARI, {"italic": True, "color": ops.TASLAK_RENK})]))
                if b.aciklama_tc is not None:
                    ops.fill_cell(b.aciklama_tc, ACIKLAMA, aciklama)
                if b.kanit_tc is not None:
                    ops.fill_cell(b.kanit_tc, KANIT, [])
                res.bos.append(cid)
                _mark(res, b, cid, a, None, opts)
                continue
        if _usable(t):
            res.dolu.append(cid)
            if t.get("durum") != "dogrulandi":
                res.dogrulanmamis.append(cid)
                aciklama.append(ops.make_paragraph([(
                    f"{DOGRULANMADI} Bu açıklama metni doğrulama aşamasından geçmemiştir "
                    f"(durum: {t.get('durum') or 'belirtilmemiş'}).",
                    {"italic": True, "color": ops.TASLAK_RENK})]))
            known = {str(k.get("no")) for k in t.get("kanitlar") or []}
            for p in t.get("paragraflar") or []:
                m = clean_text(p.get("metin") or "")
                if not m:
                    continue
                for no in RE_ATIF.findall(m):
                    if no not in known:
                        res.uyarilar.append(f"{cid}: metindeki [{no}] kanıt listesinde yok")
                aciklama.append(ops.make_paragraph(atif_gosterimi(m, opts.kanit_bicimi)))
            if clean_text(t.get("onceki_yila_gore") or ""):
                aciklama.append(ops.make_paragraph(atif_gosterimi(clean_text(t["onceki_yila_gore"]),
                                                                  opts.kanit_bicimi)))
            # bölümün bu döneme ait doğrudan kanıtı yoksa (audit) not komisyon içindir: gaps.md'de
            # kalır, rapora girmez (kör test 2026-11-20); yalnız kayda geçer
            if audit_note(a):
                res.eksik_notlu.append(cid)
            kanit = []
            liste, atifsiz = evidence_list(t.get("kanitlar") or [], filed.get(cid, []))
            if atifsiz:
                res.atifsiz_listelenen[cid] = atifsiz
            for k in liste:
                pre, ad = kanit_parts(k, opts.kanit_bicimi)
                kb = links.get((cid, str(k.get("no", "")).strip()))
                if kb:
                    rid = ops.link_rid(doc.part, kb.url)
                    seg = [(pre, {}), (ad, {"rid": rid})]
                    if kb.web and teslim != "baglanti":
                        seg += [(" (", {}), (kb.url, {"rid": rid}), (")", {})]
                    res.baglantili += 1
                else:
                    seg = [(pre + ad, {})]
                    res.baglantisiz.append(f"{cid} [{k.get('no')}] {ad}")
                kanit.append(ops.make_paragraph(seg, jc="left"))
            if not kanit:
                res.uyarilar.append(f"{cid}: metin var, kanıt listesi boş")
                kanit = [ops.make_paragraph(opts.bos_kanit, jc="left")]
            od = t.get("od_onerisi")
        else:
            res.bos.append(cid)
            if t and t.get("durum") == "reddedildi":
                res.reddedildi.append(cid)
                aciklama.append(ops.make_paragraph([(
                    f"{DOGRULANMADI} Bu ölçüt için yazılan metin doğrulamada reddedildiği için "
                    "rapora alınmamıştır.", {"italic": True, "color": ops.TASLAK_RENK})]))
            aciklama.append(ops.make_paragraph(opts.bos_ifade))
            kanit = [ops.make_paragraph(opts.bos_kanit, jc="left")]
        if b.aciklama_tc is not None:
            ops.fill_cell(b.aciklama_tc, ACIKLAMA, aciklama)
        if b.kanit_tc is not None:
            ops.fill_cell(b.kanit_tc, KANIT, kanit)
        _mark(res, b, cid, a, od, opts)

    if yonler_log is None and yonler_dir is not None:
        yonler_log = Path(yonler_dir).parent / YONLER_LOG
    fill_yonler(doc, load_yonler(yonler_dir), res, load_yonler_log(yonler_log), opts.kanit_bicimi)
    # bölümün yön hücresi kararı (bidr/write/yon_karar.py): `cikar` dediği alan raporu TASLAK yapmaz
    from bidr.write import yon_karar as YK
    yon_insan = YK.load_human_path(Path(yonler_log).parent / YK.HUMAN) if yonler_log else []
    yon_onay = {a for a, t in load_yonler(yonler_dir).items() if YK.cikarildi(t, yon_insan)}
    res.kapak = fill_cover(doc, birim, yil)
    if birim and "birim" not in res.kapak:
        res.uyarilar.append("kapakta '[Birim Adı]' yer tutucusu bulunamadı")
    if yil and "yil" not in res.kapak:
        res.uyarilar.append("kapakta yıl paragrafı bulunamadı")
    kapak_ph = cover_sections(cover_paragraphs(doc))     # doldurmadan önce: bölümler başlığa göre
    res.hazirlayan, uy = fill_preparers(doc, hazirlayanlar, kapak_ph["hazirlayan"])
    res.uyarilar += uy
    res.onaylayan, uy = fill_approver(doc, onaylayan, kapak_ph["amir"])
    res.uyarilar += uy
    if not yil and any(_ptext(p).strip() == "20.." for p in cover_paragraphs(doc)):
        res.uyarilar.append("kapaktaki yıl yer tutucusu (20..) kaldı: --yil verilmedi")

    # TASLAK nedenleri. İnsanın raporun dışında bıraktığı reddedilmiş metin (`bidr verify karar …
    # cikar`) rapora girmez ve belgeyi taslak yapmaz; birimin doldurmadığı ölçütün metni de öyle.
    N = res.taslak_nedenleri
    unver = sorted((c for c, t in texts.items() if kapsam.get(c, "bolum") != BASKA and c in blocks
                    and t.get("durum") != "dogrulandi"
                    and not (t.get("durum") == "reddedildi" and t.get("insan_karari") == "cikar")),
                   key=lambda x: [x.split(".")[0], *map(int, x.split(".")[1:])])
    if unver:
        N.append("doğrulanmamış metin: " + ", ".join(unver))
    unver_y = sorted(a for a, t in load_yonler(yonler_dir).items()
                     if t.get("durum") == "taslak" and any(res.yonler.get(f"{a} {x}") == "dolu" for x in (GUCLU, GELISME)))
    if unver_y:
        N.append("doğrulanmamış güçlü/gelişmeye açık yön maddeleri: " + ", ".join(unver_y))
    # Doğrulamada reddedilmiş (son turdan sonra hâlâ) alan: desteklenen maddeler basılsa da alanın
    # yönleri doğrulanmış değildir; rapor her durumda TASLAK (kullanıcı kararı 2026-11-20)
    rej_y = sorted(a for a, t in load_yonler(yonler_dir).items()
                   if t.get("durum") == "reddedildi" and a not in yon_onay
                   and any(f"{a} {x}" in res.yonler for x in (GUCLU, GELISME)))
    if rej_y:
        N.append("doğrulamada reddedilen güçlü/gelişmeye açık yön alanı: " + ", ".join(rej_y)
                 + " (yalnız desteklenen maddeler basıldı; gerekçe verify-yonler.jsonl)")
    kayip = {a: cs for a, cs in res.yon_kapsam_kaybi.items() if a not in yon_onay}
    if yon_onay:
        res.uyarilar.append("bölüm kararıyla desteklenmeyen yön maddeleri çıkarılmış kaldı (TASLAK nedeni değil): "
                            + ", ".join(sorted(yon_onay)))
    if kayip:
        N.append("doğrulamada reddedilen yön maddesi çıkarıldı, ölçüt hiçbir yön hücresinde kalmadı: "
                 + "; ".join(f"{a}: {', '.join(cs)}" for a, cs in sorted(kayip.items()))
                 + " (gerekçe verify-yonler.jsonl; madde düzeltilip yeniden doğrulanır)")
    empty = [k for k, v in res.yonler.items() if v != "dolu"]
    if empty:
        N.append("boş ya da şablon yönergesi kalan güçlü/gelişmeye açık yön hücresi: " + ", ".join(empty))
    left = _left(kapak_ph["hazirlayan"])
    if left:
        N.append(f"kapakta {left} 'Raporu Hazırlayanlar' yer tutucusu kaldı (config.yaml rapor.hazirlayanlar boş)")
        res.uyarilar.append("rapor.hazirlayanlar boş: kapaktaki 'Raporu Hazırlayanlar' yer tutucuları kaldı")
    if _left(kapak_ph["amir"]):
        N.append("kapakta 'Raporu Onaylayan Birim Amiri' yer tutucusu kaldı (config.yaml rapor.onaylayan boş)")
        res.uyarilar.append("rapor.onaylayan boş: kapaktaki 'Raporu Onaylayan Birim Amiri' yer tutucusu kaldı")
    if res.karar_gerekli:
        N.append("kapsam kararı gereken ölçüt (gaps.md): " + ", ".join(res.karar_gerekli))
    res.taslak = bool(N)
    if res.taslak:
        ops.add_draft_mark(doc, TASLAK_METNI)
    out.parent.mkdir(parents=True, exist_ok=True)
    res.degisen_parcalar = ops.save_preserving(doc, template, out)
    return res


# -- çalışma alanı kaydı (render_tamam) ---------------------------------------------------------

def inputs_sha(template: Path, texts_dir: Path, audit_path: Path | None, index_path: Path | None,
               yonler_dir: Path | None = None, extra: dict | None = None) -> str:
    """Raporun girdilerinin özeti: şablon, metinler, audit, kanıt dizini, alan maddeleri
    (`yonler/`) ve `extra` (hazırlayanlar, kapsam görünümü)."""
    import hashlib

    def files(d) -> list[Path]:
        return sorted(Path(d).glob("*.json")) if d and Path(d).is_dir() else []
    h = hashlib.sha256()
    named = [(p.name, p) for p in [Path(template), *files(texts_dir), *(Path(x) for x in (audit_path, index_path) if x)]]
    named += [(f"yonler/{p.name}", p) for p in files(yonler_dir)]
    if yonler_dir is not None and (Path(yonler_dir).parent / YONLER_LOG).exists():
        named.append((YONLER_LOG, Path(yonler_dir).parent / YONLER_LOG))
    from bidr.write.yon_karar import HUMAN as YON_INSAN
    if yonler_dir is not None and (Path(yonler_dir).parent / YON_INSAN).exists():
        named.append((YON_INSAN, Path(yonler_dir).parent / YON_INSAN))
    for name, p in named:
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"-")
    if extra:
        h.update(json.dumps(extra, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()[:16]


def workspace_inputs(ws: Path) -> tuple[dict[str, str], list[dict] | None, list[str]]:
    """Çalışma alanının render girdileri: (kapsam görünümü, hazırlayanlar, uyarılar)."""
    from bidr.init.config import check_preparers
    from bidr.write.sources import rapor_section

    from .kapsam import workspace_scope
    kapsam, uy = workspace_scope(Path(ws))
    raw = rapor_section(Path(ws)).get("hazirlayanlar")
    people, errs = check_preparers(raw)
    uy += [f"config.yaml rapor.hazirlayanlar: {e}" for e in errs]
    return kapsam, people, uy


def workspace_year(ws: Path) -> int | None:
    """Kapak yılı: config.yaml `bidr.donem` (raporun dönem yılı; kullanıcı kararı 2026-11-27). Yoksa None
    (tahmin edilmez; render CLI uyarır)."""
    from bidr.init.config import load_section
    v = (load_section(Path(ws)) or {}).get("donem")
    return int(v) if isinstance(v, int) or (isinstance(v, str) and v.strip().isdigit()) else None


def workspace_approver(ws: Path) -> tuple[dict | None, list[str]]:
    """config.yaml `rapor.onaylayan` (birim amiri; tek kişi): (kişi | None, uyarılar)."""
    from bidr.init.config import check_approver
    from bidr.write.sources import rapor_section
    person, errs = check_approver(rapor_section(Path(ws)).get("onaylayan"))
    return person, [f"config.yaml rapor.{e}" for e in errs]     # e: "onaylayan: …"


def workspace_teslim(ws: Path) -> str:
    """config.yaml `rapor.teslim` (geçersizse ValueError)."""
    from bidr.teslim.mod import teslim_modu
    return teslim_modu(Path(ws))


def workspace_sha(ws: Path, template: Path, texts_dir: Path, audit_path: Path | None,
                  index_path: Path | None) -> str:
    """render_tamam ile render CLI'nin ortak girdi özeti (teslim modu dahil; geçersiz mod da özete
    girer, render onu hatayla durdurur)."""
    kapsam, people, _ = workspace_inputs(ws)
    try:
        teslim = workspace_teslim(ws)
    except ValueError as e:
        teslim = f"gecersiz:{e}"
    extra = {"hazirlayanlar": people or [], "kapsam": kapsam}
    amir, _ = workspace_approver(ws)
    if amir:                            # amir yoksa özet eskisiyle aynı kalır (var olan rapor eskimez)
        extra["onaylayan"] = amir
    if (yil := workspace_year(ws)) is not None:     # kapak yılı (dönem) değişince rapor eskir
        extra["yil"] = yil
    if teslim != "baglanti":            # bağlantı modunda özet eskisiyle aynı kalır
        extra["teslim"] = teslim
    kor_od = _kor_od(audit_path)
    if kor_od:                          # kör denetimde kabul edilen OD (yoksa özet eskisiyle aynı)
        extra["kor_od"] = kor_od
    return inputs_sha(template, texts_dir, audit_path, index_path, Path(ws) / YONLER_DIR, extra)


YONLER_DIR = "yonler"


def _kor_od(audit_path: Path | None) -> dict[str, int]:
    """Kör denetimde kabul edilip audit'e yansıyan OD kararları {ölçüt: od} (bidr/kor/od.py)."""
    if audit_path is None or not Path(audit_path).exists():
        return {}
    try:
        rows, _ = load_audit(Path(audit_path))
    except (OSError, ValueError):
        return {}
    return {c: r["od"] for c, r in sorted(rows.items()) if r.get("od_denetim")}


# -- gaps.md: kapsam kararı soruları -------------------------------------------------------------------
KAPSAM_BEGIN = "<!-- bidr:kapsam -->"
KAPSAM_END = "<!-- /bidr:kapsam -->"


def scope_block(cids: list[str]) -> str:
    from bidr.criteria.loader import load_criteria
    cs = load_criteria()
    L = [KAPSAM_BEGIN, "## Kapsam kararı gereken ölçütler", "",
         "Bu ölçütleri birimin doldurup doldurmayacağı profilden çıkarılamadı; rapor bu yüzden TASLAK. "
         "Kullanıcıya sorun ve cevabını config.yaml'a yazın: `rapor: {kapsam: {<ölçüt>: bolum | ortak | "
         "baska_birim}}` (bolum: birim doldurur; ortak: başka birimlerle birlikte; baska_birim: birimin "
         "sorumluluğunda değil). Sonra `bidr render`.", ""]
    for c in cids:
        try:
            s = cs.get(c)
            L.append(f"- **{c}** {s.title} — DOLDURACAK BİRİMLER: {s.units}. Soru: bu ölçütü birim mi dolduracak?")
        except KeyError:
            L.append(f"- **{c}** — Soru: bu ölçütü birim mi dolduracak?")
    L.append(KAPSAM_END)
    return "\n".join(L) + "\n"


def update_scope_gaps(ws: Path, cids: list[str]) -> None:
    """gaps.md'deki kapsam bölümünü yeniler; soru yoksa bölümü kaldırır."""
    path = Path(ws) / "gaps.md"
    cur = path.read_text(encoding="utf-8") if path.exists() else ""
    a, b = cur.find(KAPSAM_BEGIN), cur.find(KAPSAM_END)
    old = cur[a:b + len(KAPSAM_END)] + ("\n" if cur[b + len(KAPSAM_END):b + len(KAPSAM_END) + 1] == "\n" else "") \
        if a >= 0 and b > a else None
    block = scope_block(cids) if cids else ""
    if old is not None:
        new = cur.replace(old, block)
    elif block:
        new = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
    else:
        return
    if new != cur:
        path.write_text(new, encoding="utf-8")


def write_manifest(ws: Path, res: Result, sha: str, template: Path, *, texts_dir: Path,
                   audit_path: Path | None, index_path: Path | None) -> Path:
    import hashlib
    p = Path(ws) / MANIFEST
    rec = {"surum": 1, "cikti": str(res.out), "girdi_sha": sha, "sablon": str(template),
           "girdiler": {"texts": str(texts_dir), "audit": str(audit_path) if audit_path else None,
                        "index": str(index_path) if index_path else None},
           "cikti_sha": hashlib.sha256(Path(res.out).read_bytes()).hexdigest()[:16],
           **{k: v for k, v in res.ozet().items() if k != "cikti"}}
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_manifest(ws: Path) -> dict | None:
    p = Path(ws) / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def update_link_gaps(ws: Path, index_path: Path | None, teslim: str = "baglanti") -> None:
    """gaps.md "bağlantı yok" bölümünü kanıt dizininden yeniler (bkz. bidr/file/links.py).
    `dekanlik` modunda bölüm bilgi notudur: bağlantı gerekmez, kanıtlar dosya olarak teslim edilir."""
    import csv

    from bidr.file.links import GAPS_BEGIN, GAPS_END, gaps_block, update_gaps
    if index_path is None or not Path(index_path).exists():
        return
    with open(index_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if teslim == "baglanti":
        update_gaps(Path(ws) / "gaps.md", gaps_block(rows))
        return
    miss = [r for r in rows if not (r.get("baglanti") or "").strip() or r.get("baglanti_kaynagi") == "klasor"]
    L = [GAPS_BEGIN, "## Bağlantısı olmayan kanıtlar (bilgi)", "",
         f"Teslim modu `{teslim}` (config.yaml rapor.teslim): rapor ve kanıt dosyaları dekanlığa teslim edilir "
         "(`bidr teslim`); kanıtların bağlantısı gerekmez, bu liste yalnız bilgidir. Web sayfası kanıtlarının "
         "özgün adresi raporda görünür; teslim paketinde alınma tarihli PDF kopyaları vardır. "
         f"Bağlantısı olmayan kanıt: {len(miss)}."]
    L.append(GAPS_END)
    update_gaps(Path(ws) / "gaps.md", "\n".join(L) + "\n")
