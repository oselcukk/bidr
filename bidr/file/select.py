"""Kanıt seçimi (model yok): audit'in eşleşme kümesinden yayımlanan kanıt listesini seçer.

Audit OD'si buradan etkilenmez: `bidr.audit.run.build` bütün kabul edilmiş eşleşmeleri sayar.
Seçim yalnız `evidence-index.csv` / `evidence/`'e neyin gireceğini belirler; elenen her belge
nedeniyle `evidence-secim.json`'a ve gaps.md "Kanıt seçimi" bölümüne yazılır.
Sözleşme ve gerekçe: docs/REPORT_LAYER.md "Kanıt seçimi"; ayarlar
`bidr/data/profiles/kanit_secimi.yaml` (+ config.yaml `rapor.kanit_secimi`).

İki adım, ölçüt ölçüt:

1. **Sürüm ve kopya (K20).** Birebir kopya (ingest `dup_of`) ve mükerrer metin (decide
   `mukerrer`) zaten tek kanıttır (`run.plan`). identify'ın `surum_grubu`'ndaki belgeler (metin
   benzerliği) de tek kanıt sayılır; temsilci en yüksek OD'li, sonra en güncel (tarih), sonra en
   eksiksiz (en uzun metin) olandır. Ayrı kalanlar: farklı döneme ait veri (çeyrek, ay-yıl,
   "YYYY yılı", akademik dönem işaretleri ayrık; ya da tarihler farklı yıllarda) ve boş şablon ↔
   dolu form (kanıt ilkesi `bos_form_zinciri`: yalnız planla olan ile uygula/üstü olan, ya da
   doldurulacak boşluklu metin ile dolu metin). Dönem kanıtı yoksa ve sayılar da aynı değilse
   emin olunamaz: tek sayılır, `surum_belirsiz` işaretlenir ve gaps.md'de listelenir.
   **Kopyalar:** aynı yazının taramaları ve kontrollü belgenin sayfaları (identify'ın OCR'a
   dayanıklı kopya bağı, `bidr/identify/versions.py`) sürüm değil kopyadır: modelin iki kopyaya
   farklı aşama vermesi (planla ↔ uygula) onları ayırmaz; yalnız dönem/tarih/boş form ayırır.
   **Kapsanan kopya** (`merge_contained`, ölçüt içinde): bir kalemin metni (şablon dışı kısmı)
   aynı tarihli başka bir kalemin içinde neredeyse bütünüyle varsa (ör. yazının tek taraması ↔
   yazı + ekleri) ve kalemin bu ölçütteki bütün alıntıları da o belgede geçiyorsa, kapsayan
   belge temsilci olur; kapsanan ayrı numara almaz. Kapsama simetrik olmadığından identify'da
   değil, ölçüt içinde ve alıntı denetimiyle uygulanır (iki farklı ek, aynı derlemeyi
   kapsıyor diye birleşmez).
2. **İlgililik (K18).** (a) write sonrası metinde atıf yapılan kanıt her zaman girer ve üst
   sınıra sayılmaz; (b) atıfsız kanıt yalnız doğrudan ilgiliyse girer: OD'ye sayılır, güveni
   ≥ `en_dusuk_guven`, sayılan eşleşmelerinden en az biri `dolayli_isaretler` taşımıyor; ölçüt
   başına `olcut_basina_en_fazla` (sıra: OD'ye sayılan önce, sonra OD, güven, tarih; dönem kuralı
   yüzünden sayılmayan aday elenmez ama sona kalır); (c) kurum geneli düzenleme bir ölçütte en çok
   `kurum_geneli_en_fazla` (madde alıntısı olan önce). Bu dönemin kanıtı olmayan (dönem sonrası, yürürlükteki sürüm olmayan), audit
   savunmasının kanıt saymadığı (`KANIT_DEGIL`: hariç tür, yürürlükten kaldırılmış, bilgisiz
   ekran, başka birimin maddesi) ve birim aitliği insanca onaylanmamış belge hiç girmez (atıf da aşmaz); geçmiş kanıt (süreklilik)
   ölçüt başına en çok `gecmis_kanit_en_fazla`. İnsanın yerleştirdiği (inceleme
   `duzelt`) kanıt ve OD zincirinin bir halkasını taşıyan tek kanıt sınır yüzünden düşmez
   (yayımlanan liste audit OD'sini desteklemeye devam eder). İnceleme `kabul`ü güven ve
   dolaylılık eşiğini aşar (insan doğruladı) ama sınırlara tabidir: `audit_tamam` her satıra
   karar istediğinden toplu `kabul` seçimi devre dışı bırakmamalı.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

FILE = "kanit_secimi.yaml"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "profiles" / FILE
CONFIG_KEY = "kanit_secimi"                 # config.yaml `rapor:` altında
SECIM = "evidence-secim.json"
TEXTS = "texts"                             # bidr.write.run.TEXTS (write çıktısı; salt okunur)
GAPS_BEGIN = "<!-- bidr:kanit-secimi -->"
GAPS_END = "<!-- /bidr:kanit-secimi -->"
GUVEN = {"dusuk": 0, "orta": 1, "yuksek": 2}
STAGE_OD = {"planla": 2, "uygula": 3, "kontrol_et": 4, "onlem_al": 4, "ozgun": 5}

NEDEN = {
    "atif": "metinde atıf var",
    "insan": "incelemede düzeltildi (insan yerleştirdi)",
    "zincir": "OD zincirinin halkası (tek kanıt)",
    "dogrudan": "doğrudan ilgili",
    "kurum_geneli": "kurum geneli (sınır içinde)",
    "dusuk_guven": "model güveni düşük",
    "dolayli": "yuva/tür bağı dolaylı",
    "ust_sinir": "ölçüt üst sınırı dolu",
    "kurum_geneli_siniri": "ölçütte kurum geneli sınırı dolu",
    "donem_sonrasi": "bu dönemin kanıtı değil (dönem sonrası ya da yürürlükteki sürüm değil)",
    "birim_dogrulanmali": "birim aitliği insanca onaylanmadı",
    "gecmis_siniri": "geçmiş kanıt (süreklilik) sınırı dolu",
    # audit kod tarafı savunmaları (KANIT_DEGIL): kanıt değil
    "haric_tur": "öz-referans tür (BİDR'nin kendisi ya da taslağı): kanıt değil",
    "yururlukten_kalkmis": "başka bir belgeyle yürürlükten kaldırılmış düzenleme: bu dönemin kanıtı değil",
    "bilgisiz_ekran": "bilgi içermeyen ekran/bağlantı sayfası: kanıt değil",
    "madde_baska_birim": "alıntı başka birimi konu alan maddeden (madde ilkesi): kanıt değil",
}
SURUM_NEDEN = {
    "ayni_donem": "aynı dönem işaretleri",
    "ayni_tarih": "aynı tarih",
    "ayni_veri": "sayısal içerik aynı",
    "donem_belirsiz": "dönem bilgisi yok, sayısal içerik farklı (emin olunamadı)",
    "farkli_donem": "farklı dönem verisi",
    "farkli_yil": "farklı yıl",
    "bos_form_dolu_form": "boş şablon / dolu form",
    "parca_grubu": "aynı belgenin parçaları (tek kaynak)",
    "kopya": "aynı belgenin kopyası (OCR'lı tarama ya da aynı kontrollü belge)",
    "kapsanan_kopya": "metni ve alıntıları kapsayan belgede bütünüyle var",
}


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    olcut_en_fazla: int | None
    kurum_geneli_en_fazla: int
    en_dusuk_guven: str
    dolayli: tuple[str, ...]
    surum_birlestir: bool
    gecmis_en_fazla: int = 1

    def sha(self) -> str:
        return hashlib.sha256(repr(self).encode()).hexdigest()[:16]

    def as_dict(self) -> dict:
        return {"olcut_basina_en_fazla": self.olcut_en_fazla,
                "kurum_geneli_en_fazla": self.kurum_geneli_en_fazla,
                "en_dusuk_guven": self.en_dusuk_guven, "dolayli_isaretler": list(self.dolayli),
                "surum_birlestir": self.surum_birlestir, "gecmis_kanit_en_fazla": self.gecmis_en_fazla}


def settings_path() -> Path:
    from bidr.criteria.profiles import profiles_dir
    p = profiles_dir() / FILE
    return p if p.exists() else DEFAULT_PATH


def _nonneg(v, key: str, allow_none: bool) -> int | None:
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        raise SelectionError(f"kanıt seçimi: `{key}` negatif olmayan tam sayı olmalı (verilen: {v!r})")
    return v


def load_settings(ws_root: Path | None = None) -> Settings:
    raw = yaml.safe_load(settings_path().read_text(encoding="utf-8")) or {}
    if ws_root is not None:
        from bidr.write.sources import rapor_section
        over = rapor_section(Path(ws_root)).get(CONFIG_KEY) or {}
        if not isinstance(over, dict):
            raise SelectionError("config.yaml `rapor.kanit_secimi` bir eşleme olmalı")
        raw = {**raw, **over}
    g = raw.get("en_dusuk_guven", "orta")
    if g not in GUVEN:
        raise SelectionError(f"kanıt seçimi: `en_dusuk_guven` {sorted(GUVEN)} içinden olmalı (verilen: {g!r})")
    return Settings(
        olcut_en_fazla=_nonneg(raw.get("olcut_basina_en_fazla", 10), "olcut_basina_en_fazla", True),
        kurum_geneli_en_fazla=_nonneg(raw.get("kurum_geneli_en_fazla", 3), "kurum_geneli_en_fazla", False),
        gecmis_en_fazla=_nonneg(raw.get("gecmis_kanit_en_fazla", 1), "gecmis_kanit_en_fazla", False),
        en_dusuk_guven=g, dolayli=tuple(str(x) for x in raw.get("dolayli_isaretler") or ()),
        surum_birlestir=bool(raw.get("surum_birlestir", True)))


# -- atıflar (write sonrası) -------------------------------------------------------------------

def cited_docs(ws_root: Path, prev_index: Path, prev_record: Path | None = None
               ) -> tuple[dict[str, set[str]], list[dict], list[str]]:
    """({ölçüt: {doc_id}}, eşleme kaydı, uyarılar): `texts/<ölçüt>.json` paragraflarında atıf
    yapılan kanıtlar. Atıf (ölçüt, numara, dosya) önce önceki `evidence-index.csv`'de aranır
    (numara ve dosya ikisi de tutmalı), yoksa önceki `evidence-secim.json`'un atıf eşlemesinde:
    seçim değişip dosyalama yenilenince numara değişir, metnin atfı yine aynı belgeye bağlanır."""
    td = Path(ws_root) / TEXTS
    out: dict[str, set[str]] = {}
    used: list[dict] = []
    uy: list[str] = []
    if not td.is_dir():
        return out, used, uy
    idx: dict[tuple[str, str], dict] = {}
    if prev_index.exists():
        with open(prev_index, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                idx[(r.get("olcut") or "", r.get("kanit_no") or "")] = r
    old: dict[tuple[str, str, str], str] = {}
    if prev_record is not None and prev_record.exists():
        try:
            for a in json.loads(prev_record.read_text(encoding="utf-8")).get("atiflar") or []:
                old[(a["olcut"], a["no"], a.get("dosya") or "")] = a["doc_id"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for p in sorted(td.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c = t.get("olcut") or p.stem
        nos = {n for para in t.get("paragraflar") or [] for n in para.get("atiflar") or []}
        files = {k.get("no"): k.get("dosya") for k in t.get("kanitlar") or []}
        for n in sorted(nos):
            r, dosya = idx.get((c, n)), files.get(n) or ""
            did = None
            if r and r.get("doc_id") and dosya in ("", r.get("dosya")):
                did, dosya = r["doc_id"], r.get("dosya") or dosya
            elif (c, n, dosya) in old:
                did = old[(c, n, dosya)]
            if did:
                out.setdefault(c, set()).add(did)
                used.append({"olcut": c, "no": n, "dosya": dosya, "doc_id": did})
            else:
                uy.append(f"{c} [{n}]: metindeki atıf kanıt dizininde bulunamadı; atıf kuralı uygulanmadı")
    return out, used, uy


# -- sürüm ilişkisi ---------------------------------------------------------------------------

HEAD = 1500
_QUARTER = re.compile(r"\b([1-4])\s*\.?\s*ceyrek|\b(birinci|ikinci|ucuncu|dorduncu)\s+ceyrek|\bq([1-4])\b")
_ORD = {"birinci": "1", "ikinci": "2", "ucuncu": "3", "dorduncu": "4"}
_MONTHS = ("ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim",
           "kasim", "aralik")
_MONTH = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(20\d\d)\b")
_YEAR = re.compile(r"\b(20\d\d)\s+yili\b")
_BLANK = re.compile(r"_{3,}|\.{5,}|…{2,}|\[\s*\]|[☐□]")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def period_marks(doc: dict, text: str) -> dict[str, frozenset[str]]:
    """Belgenin veri dönemi işaretleri (baş bölgeden; tür → değerler)."""
    from bidr.identify.dates import academic_terms
    from bidr.identify.text import fold
    f = fold(text[:HEAD * 2])[:HEAD]
    out: dict[str, set[str]] = {}
    for m in _QUARTER.finditer(f):
        q = m.group(1) or _ORD.get(m.group(2) or "") or m.group(3)
        out.setdefault("ceyrek", set()).add(q)
    for m in _MONTH.finditer(f):
        out.setdefault("ay", set()).add(f"{m.group(2)}-{_MONTHS.index(m.group(1)) + 1:02d}")
    for m in _YEAR.finditer(f):
        out.setdefault("yil", set()).add(m.group(1))
    terms = list(doc.get("akademik_donem") or []) or academic_terms(f)
    if terms:
        out["akademik_donem"] = set(terms)
    return {k: frozenset(v) for k, v in out.items()}


def _blank(text: str) -> bool:
    return len(_BLANK.findall(text)) >= 3


def _top(stages) -> int:
    return max((STAGE_OD.get(s, 0) for s in stages), default=0)


@dataclass
class Version:
    """Sürüm karşılaştırması için belge özeti."""
    doc_id: str
    doc: dict
    text: str
    stages: frozenset

    @property
    def marks(self) -> dict[str, frozenset[str]]:
        if not hasattr(self, "_marks"):
            self._marks = period_marks(self.doc, self.text)
        return self._marks


def relation(a: Version, b: Version, kopya: bool = False) -> tuple[str, str]:
    """(ayni | ayri | belirsiz, neden). `ayri` dışı → tek kanıt. Aynı parça grubundaki belgeler
    (ingest `parca_grubu`: tek belgenin bölünmüş parçaları) tek kaynaktır: dönem/tarih/sayı ve boş
    form karşılaştırması atlanır (parçaların tarihi ve sayıları doğal olarak farklıdır).
    `kopya`: iki belge aynı yazının kopyası (bkz. `is_copy_pair`): aşama farkı (model gürültüsü)
    ayırmaz, OCR'ın bozduğu sayılar belirsizlik yaratmaz; dönem/yıl ve boş form yine ayırır."""
    pa, pb = a.doc.get("parca_grubu"), b.doc.get("parca_grubu")
    if pa and pa == pb:
        return "ayni", "parca_grubu"
    if _blank(a.text) != _blank(b.text) or (not kopya and (_top(a.stages) == 2) != (_top(b.stages) == 2)):
        return "ayri", "bos_form_dolu_form"
    ma, mb = a.marks, b.marks
    common = [k for k in ma if k in mb]
    if common:
        if any(not (ma[k] & mb[k]) for k in common):
            return "ayri", "farkli_donem"
        if all(ma[k] <= mb[k] or mb[k] <= ma[k] for k in common) and not kopya:
            return "ayni", "ayni_donem"     # alt küme: daha kapsamlı (birikimli) sürüm
    ta, tb = a.doc.get("tarih"), b.doc.get("tarih")
    if ta and tb:
        if str(ta)[:4] != str(tb)[:4]:
            return "ayri", "farkli_yil"
        if kopya:
            return "ayni", "kopya"
        if ta == tb:
            return "ayni", "ayni_tarih"
    if kopya:
        return "ayni", "kopya"
    if Counter(_NUM.findall(a.text)) == Counter(_NUM.findall(b.text)):
        return "ayni", "ayni_veri"
    return "belirsiz", "donem_belirsiz"


def is_copy_pair(a: Version, b: Version) -> bool:
    """İki sürüm grubu üyesi aynı yazının kopyası mı: aynı kontrollü belge imzası (doküman no +
    revizyon) ya da aynı tarihli, iki yönde yüksek OCR'a dayanıklı kapsama (identify'ın kopya
    bağıyla aynı eşikler; şablon süzgeci derlem gerektirdiğinden burada ham parmak izi)."""
    from bidr.identify import versions as V
    sa, sb = V.control_signature(a.text), V.control_signature(b.text)
    if sa and sa == sb:
        return True
    da, db = a.doc.get("tarih"), b.doc.get("tarih")
    if not da or da != db or not V.ids_compatible(V.head_ids(a.text), V.head_ids(b.text)):
        return False
    lo, hi = V.containment(V.fingerprint(a.text), V.fingerprint(b.text))
    return lo >= V.COPY_LO and hi >= V.COPY_HI


def _date_num(doc: dict) -> int:
    t = str((doc or {}).get("tarih") or "")
    return int(t.replace("-", "")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) else 0


def _absorb(rep, it) -> None:
    """`it` kalemini temsilciye katar (yuva, aşama, güven, inceleme izleri birleşir)."""
    rep.kopyalar_surum.extend([it.doc_id, *it.kopyalar, *it.kopyalar_surum])
    rep.yuvalar = sorted(set(rep.yuvalar) | set(it.yuvalar),
                         key=lambda y: (y.split("/")[0], int(y.split("/")[1])))
    rep.asamalar |= it.asamalar
    rep.asamalar_tum |= it.asamalar_tum
    rep.insan = rep.insan or it.insan
    rep.onay = rep.onay or it.onay
    if GUVEN.get(it.guven, 1) > GUVEN.get(rep.guven, 1):
        rep.guven = it.guven


def merge_versions(items: list, docs: dict, text_of, cited: set[str]) -> tuple[list, list[dict]]:
    """Bir ölçütün kalemlerinde sürüm gruplarını birleştirir → (kalan kalemler, birleştirme kayıtları).
    Atıf yapılan kalem başka kaleme katılmaz (kendisi temsilci olabilir)."""
    groups: dict[str, list] = {}
    for it in items:
        g = (docs.get(it.doc_id) or {}).get("surum_grubu")
        if g:
            groups.setdefault(g, []).append(it)
    gone: set[int] = set()
    merges: list[dict] = []
    for g, mem in sorted(groups.items()):
        if len(mem) < 2:
            continue
        ver = {id(it): Version(it.doc_id, docs.get(it.doc_id) or {}, text_of(it.doc_id),
                               frozenset(it.asamalar_tum)) for it in mem}
        mem = sorted(mem, key=lambda it: (not it.sayilir, -_level(it), it.doc_id not in cited, -_date_num(docs.get(it.doc_id)),
                                          -len(ver[id(it)].text), it.doc_id))
        clusters: list[list[tuple]] = []        # [(kalem, (karar, neden) | None)]
        for it in mem:
            placed = False
            if it.doc_id not in cited:
                for cl in clusters:
                    rels = [relation(ver[id(it)], ver[id(x)], kopya=is_copy_pair(ver[id(it)], ver[id(x)]))
                            for x, _ in cl]
                    if any(r[0] == "ayri" for r in rels):
                        continue
                    worst = next((r for r in rels if r[0] == "belirsiz"), rels[0])
                    if worst[0] == "belirsiz" and it.insan:
                        continue        # emin olunamayanı insan onayladı: ayrı kanıt kalır
                    cl.append((it, worst))
                    placed = True
                    break
            if not placed:
                clusters.append([(it, None)])
        for cl in clusters:
            if len(cl) < 2:
                continue
            rep = cl[0][0]
            uyeler = []
            for it, (karar, neden) in cl[1:]:
                gone.add(id(it))
                _absorb(rep, it)
                uyeler.append({"doc_id": it.doc_id, "karar": karar, "neden": neden})
                if karar == "belirsiz" and "surum_belirsiz" not in rep.isaretler:
                    rep.isaretler.append("surum_belirsiz")
            rep.isaretler.append("surum_temsilcisi")
            merges.append({"olcut": rep.olcut, "grup": g, "temsilci": rep.doc_id, "uyeler": uyeler})
    rest = [it for it in items if id(it) not in gone]
    rest, cm = merge_contained(rest, docs, text_of, cited)
    return rest, merges + cm


# -- kapsanan kopya (ölçüt içinde) ----------------------------------------------------------------

CONTAIN_MIN = 0.9           # kapsananın şablon dışı parçacıklarının kapsayanda bulunma oranı
CONTAIN_UNDATED = 0.95      # iki belge de tarihsizse
QUOTE_MIN = 0.6             # alıntının (OCR'ı farklı) kapsayan belgede bulunma oranı
_COPY_INDEX: dict = {}      # derlem özeti önbelleği: id(docs) → CopyIndex


def copy_index(docs: dict, text_of):
    """Çalışma alanındaki bütün belgelerin kopya özeti (şablon parçacıkları derlem sıklığından).
    Bir `file` koşusunda bir kez kurulur."""
    from bidr.identify.versions import CopyIndex
    key = (id(docs), len(docs))
    if key not in _COPY_INDEX:
        _COPY_INDEX.clear()
        _COPY_INDEX[key] = CopyIndex({d: text_of(d) for d in docs})
    return _COPY_INDEX[key]


def _quotes_in(quotes: list[str], fp: frozenset) -> bool:
    from bidr.identify.versions import quote_fingerprint
    qs = [quote_fingerprint(q) for q in quotes if q]
    qs = [q for q in qs if len(q) >= 10]
    return bool(qs) and all(len(q & fp) / len(q) >= QUOTE_MIN for q in qs)


def merge_contained(items: list, docs: dict, text_of, cited: set[str]) -> tuple[list, list[dict]]:
    """Ölçüt içinde kapsanan kopyaları kapsayan kaleme bağlar → (kalan kalemler, birleştirme kayıtları).
    Koşullar: aynı birincil tarih (ikisi de tarihsizse daha yüksek eşik ve ortak bir kimlik: ders
    kodu, sayı, tarih), uyumlu tür, kapsananın baş bölge kimlikleri kapsayanda, şablon dışı metnin ≥ CONTAIN_MIN'i kapsayanda, kalemin bu ölçütteki bütün alıntıları
    kapsayanda, dönem/boş form ayrımı yok (`relation`). Atıfsız kapsanan kalem kapsayana katılır
    (listeden çıkar); atıf yapılan kalem listede kalır ama kapsayanla aynı kaynak anahtarını
    (`kaynak_grubu`, bkz. naming.source_key) alır: ikisi tek numara ve tek kod OD'si taşır."""
    from bidr.identify import versions as V

    from .naming import source_key
    if len(items) < 2:
        return items, []
    ix = None
    gone: set[int] = set()
    merges: list[dict] = []
    parent: dict[str, str] = {}

    def find(k: str) -> str:
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    nat = {id(it): source_key(it.doc_id, docs, it) for it in items}
    order = sorted(items, key=lambda it: (len(text_of(it.doc_id)), it.doc_id))   # küçükten büyüğe
    for x in order:
        if id(x) in gone:
            continue
        dx = docs.get(x.doc_id) or {}
        for y in sorted(items, key=lambda it: (-len(text_of(it.doc_id)), it.doc_id)):
            if y is x or id(y) in gone or find(nat[id(y)]) == find(nat[id(x)]):
                continue
            dy = docs.get(y.doc_id) or {}
            if (dx.get("tarih") or None) != (dy.get("tarih") or None):
                continue
            if not V.types_compatible(dx.get("doc_type"), dy.get("doc_type")):
                continue
            if ix is None:
                ix = copy_index(docs, text_of)
            if not ix.usable(x.doc_id) or y.doc_id not in ix.inf:
                continue
            need = CONTAIN_MIN if dx.get("tarih") else CONTAIN_UNDATED
            if ix.contained(x.doc_id, y.doc_id) < need:
                continue
            if not ix.ids_within(x.doc_id, y.doc_id, shared=not dx.get("tarih")):
                continue
            if not _quotes_in(x.alintilar, ix.fp[y.doc_id]):
                continue
            vx = Version(x.doc_id, dx, text_of(x.doc_id), frozenset(x.asamalar_tum))
            vy = Version(y.doc_id, dy, text_of(y.doc_id), frozenset(y.asamalar_tum))
            if relation(vx, vy, kopya=True)[0] == "ayri":
                continue
            merges.append({"olcut": y.olcut, "grup": "kapsama:" + y.doc_id, "temsilci": y.doc_id,
                           "uyeler": [{"doc_id": x.doc_id, "karar": "ayni", "neden": "kapsanan_kopya"}]})
            if x.doc_id in cited:               # metin numarasına atıf yapıyor: listede kalır, numarayı paylaşır
                parent[find(nat[id(x)])] = find(nat[id(y)])
            else:
                gone.add(id(x))
                _absorb(y, x)
                if x.od > y.od:                 # aynı içerik: kodun OD'si kopyalarınkinin en yükseği
                    y.od = x.od
                y.sayilir = y.sayilir or x.sayilir
                if "surum_temsilcisi" not in y.isaretler:
                    y.isaretler.append("surum_temsilcisi")
            break
    rest = [it for it in items if id(it) not in gone]
    size = Counter(find(k) for k in list(parent))
    for it in rest:
        k = nat[id(it)]
        if k in parent and size[find(k)] > 1:
            it.kaynak_grubu = find(k)
    return rest, merges


# -- ilgililik --------------------------------------------------------------------------------

# Audit'in "kanıt değil" savunma işaretleri (bidr/audit/savunma.py; docs/AUDIT.md "Kod tarafı
# savunmalar"): satır sayılmaz ve belge yayımlanan listeye hiç girmez (atıf ve zincir de aşmaz).
# Sıra = gaps.md'de gösterilecek nedenin önceliği. `ozgun_kanitsiz` ve `fotograf_destekleyici`
# burada değil: belge kanıttır, yalnız o halkayı tek başına kanıtlamaz (destekleyici kalabilir).
KANIT_DEGIL = ("haric_tur", "yururlukten_kalkmis", "bilgisiz_ekran", "madde_baska_birim")


def _sonra_flags() -> frozenset[str]:
    from bidr.audit.donem import DONEM_DISI      # tek kaynak: audit'in dönem dışı listesi
    return frozenset(DONEM_DISI) - set(KANIT_DEGIL)


def donem_disi(rows: list[dict]) -> str:
    """OD'ye sayılmayan kalemin durumu (audit satırlarından). Bütün satırlar kanıt dışıysa:
    `KANIT_DEGIL` işaretlerinden biri (bütün satırlarda ortak olan, yoksa öncelikli olan; ör.
    `yururlukten_kalkmis`) ya da "sonra" (dönem sonrası / yürürlükteki sürüm değil); "gecmis" =
    önceki yıl olayı (geçmiş kanıt, süreklilik); aksi "". İnsan `duzelt`i satırı sayar, buraya
    gelmez."""
    fl = [set(r.get("flags") or []) for r in rows]
    sonra, kd = _sonra_flags(), set(KANIT_DEGIL)
    if fl and all(f & (sonra | kd) for f in fl):
        ortak = set.intersection(*fl) & kd
        if ortak:
            return next(x for x in KANIT_DEGIL if x in ortak)
        if all(f & sonra for f in fl):
            return "sonra"
        return next(x for x in KANIT_DEGIL if any(x in f for f in fl))
    if any("gecmis_kanit" in f for f in fl):
        return "gecmis"
    return ""


def _level(it) -> int:
    """Sıralama düzeyi: kanıtın taşıdığı en yüksek sayılan halka (kodun OD'si ölçüt zinciriyle
    sınırlanmış olabilir, naming.evidence_od; üst halkayı taşıyan kanıt yine önce gelir)."""
    return max(it.od, _top(it.asamalar))


def _rank_direct(it, docs) -> tuple:
    # OD'ye sayılmayan (dönem kuralı: tarihsiz/geçmiş olay) aday sona: sınır önce onları eler
    return (not it.sayilir, -_level(it), -GUVEN.get(it.guven, 1), -_date_num(docs.get(it.doc_id)), it.doc_id)


def _rank_kg(it, docs) -> tuple:
    return (not it.sayilir, not it.madde, -GUVEN.get(it.guven, 1), -_level(it), -_date_num(docs.get(it.doc_id)),
            it.doc_id)


def select(items: list, s: Settings, cited: set[str], docs: dict) -> tuple[list, list[dict]]:
    """Bir ölçütün kalemleri → (yayımlanacaklar, elenenler [{doc_id, neden, kurum_geneli, ...}])."""
    keep: dict[int, str] = {}
    drop: dict[int, str] = {}
    for it in items:
        # bu dönemin kanıtı olmayan ya da birim aitliği onaylanmamış belge hiçbir yoldan girmez
        # (atıf da aşmaz; insan `duzelt`i audit'te dönem/birim kuralını zaten kaldırır)
        if getattr(it, "birim_bekliyor", False):
            drop[id(it)] = "birim_dogrulanmali"
        elif getattr(it, "donem_disi", "") == "sonra":
            drop[id(it)] = "donem_sonrasi"
        elif getattr(it, "donem_disi", "") in KANIT_DEGIL:
            drop[id(it)] = it.donem_disi
        elif it.doc_id in cited:
            keep[id(it)] = "atif"
        elif it.insan:
            keep[id(it)] = "insan"
    n_open = sum(1 for it in items if id(it) in keep and keep[id(it)] != "atif")   # atıf sınıra sayılmaz
    n_kg = sum(1 for it in items if id(it) in keep and it.kurum_geneli)
    cap = s.olcut_en_fazla
    direct, kg = [], []
    for it in items:
        if id(it) in keep or id(it) in drop:
            continue
        if GUVEN.get(it.guven, 1) < GUVEN[s.en_dusuk_guven] and not it.onay:
            drop[id(it)] = "dusuk_guven"
        elif it.kurum_geneli:
            kg.append(it)
        elif it.dolayli and not it.onay:
            drop[id(it)] = "dolayli"
        else:
            direct.append(it)
    n_gecmis = sum(1 for it in items if id(it) in keep and getattr(it, "donem_disi", "") == "gecmis")
    for it in sorted(direct, key=lambda x: _rank_direct(x, docs)):
        gecmis = getattr(it, "donem_disi", "") == "gecmis"
        if gecmis and n_gecmis >= s.gecmis_en_fazla:
            drop[id(it)] = "gecmis_siniri"
            continue
        if cap is not None and n_open >= cap:
            drop[id(it)] = "ust_sinir"
            continue
        keep[id(it)] = "dogrudan"
        n_open += 1
        n_gecmis += gecmis
    for it in sorted(kg, key=lambda x: _rank_kg(x, docs)):
        if n_kg >= s.kurum_geneli_en_fazla:
            drop[id(it)] = "kurum_geneli_siniri"
        elif cap is not None and n_open >= cap:
            drop[id(it)] = "ust_sinir"
        else:
            keep[id(it)] = "kurum_geneli"
            n_open += 1
            n_kg += 1
    # OD zinciri: audit'in saydığı (düşük güvenli olmayan) her halka listede en az bir kanıtla
    # kalır; seçilmemişse en iyi aday sınırlara rağmen girer (yayımlanan liste audit OD'sini destekler)
    stages = sorted({x for it in items for x in it.asamalar}, key=lambda x: STAGE_OD.get(x, 9))
    for st in stages:
        if any(st in it.asamalar for it in items if id(it) in keep):
            continue
        cand = [it for it in items if st in it.asamalar and id(it) not in keep
                and drop.get(id(it)) not in ("donem_sonrasi", "birim_dogrulanmali", *KANIT_DEGIL)]
        if cand:
            best = min(cand, key=lambda it: (it.kurum_geneli, it.dolayli, not it.madde, *_rank_direct(it, docs)))
            keep[id(best)] = "zincir"
            drop.pop(id(best), None)
            best.isaretler.append("zincir_icin_secildi")
    kept, out = [], []
    for it in items:
        if id(it) in keep:
            it.secim = keep[id(it)]
            kept.append(it)
        else:
            n = drop[id(it)]
            d = docs.get(it.doc_id) or {}
            out.append({"olcut": it.olcut, "doc_id": it.doc_id, "belge": d.get("calisma_adi") or it.doc_id,
                        "od": it.od, "neden": n, "kurum_geneli": it.kurum_geneli, "madde": it.madde,
                        "guven": it.guven, "yuvalar": it.yuvalar,
                        "dolayli_isaretler": sorted(it.dolayli_isaretler) if n == "dolayli" else [],
                        "kopyalar": [*it.kopyalar, *it.kopyalar_surum]})
    return kept, out


# -- kayıt ve gaps.md --------------------------------------------------------------------------

def record(path: Path, s: Settings, kept: list, dropped: list[dict], merges: list[dict],
           uyarilar: list[str], atiflar: list[dict]) -> None:
    rec = {"surum": 1, "ayarlar": s.as_dict(), "ayar_sha": s.sha(),
           "secilen": [{"olcut": it.olcut, "doc_id": it.doc_id, "od": it.od, "neden": it.secim}
                       for it in kept],
           "elenen": dropped, "surum_birlestirme": merges, "atiflar": atiflar, "uyarilar": uyarilar}
    Path(path).write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def gaps_block(s: Settings, kept: list, dropped: list[dict], merges: list[dict], docs: dict,
               n_cand: int, metin_var: bool = False) -> str:
    from bidr.criteria.model import id_key

    def nm(did: str) -> str:
        return (docs.get(did) or {}).get("calisma_adi") or did

    cap = "sınırsız" if s.olcut_en_fazla is None else str(s.olcut_en_fazla)
    L = [GAPS_BEGIN, "## Kanıt seçimi (yayımlanan kanıt listesi)", "",
         "Audit OD'si bütün kabul edilmiş eşleşmelerden hesaplanır; bu bölüm yalnız yayımlanan kanıt "
         "listesine (`evidence-index.csv`, `evidence/`) girmeyenleri ve tek kanıt sayılan sürümleri gösterir. "
         f"Ayarlar: ölçüt başına en çok {cap} atıfsız kanıt, kurum geneli en çok {s.kurum_geneli_en_fazla}, "
         f"en düşük güven `{s.en_dusuk_guven}` (`bidr/data/profiles/kanit_secimi.yaml`, config.yaml "
         "`rapor.kanit_secimi`). Elenen bir belgeyi listeye almak için review.xlsx'te satırı `duzelt` edin "
         "(yuva aynı kalabilir; insan yerleştirmesi sınırlara tabi değildir), sonra `bidr audit apply` ve "
         "`bidr file`.", "",
         f"Özet: {n_cand} aday kanıt, {len(kept)} yayımlandı, {len(dropped)} elendi, "
         f"{sum(len(m['uyeler']) for m in merges)} sürüm/kopya temsilciye katıldı.", ""]
    srt = lambda xs: sorted(xs, key=lambda x: (id_key(x["olcut"]), x["belge"] if "belge" in x else "", x.get("doc_id", "")))
    kg = [d for d in dropped if d["kurum_geneli"]]
    if kg:
        L += ["### Elenen kurum geneli belgeler", ""]
        for d in srt(kg):
            L.append(f"- {d['olcut']}: {d['belge']} (`{d['doc_id']}`, OD{d['od']}) — {NEDEN[d['neden']]}"
                     + ("" if d["madde"] else "; madde alıntısı yok"))
        L.append("")
    other = [d for d in dropped if not d["kurum_geneli"]]
    if other:
        L += ["### Kanıt listesine alınmayan diğer belgeler", ""]
        for d in srt(other):
            why = NEDEN[d["neden"]] + (f" ({', '.join(d['dolayli_isaretler'])})" if d["dolayli_isaretler"] else "")
            L.append(f"- {d['olcut']}: {d['belge']} (`{d['doc_id']}`, OD{d['od']}) — {why}")
        L.append("")
    if merges:
        L += ["### Tek kanıt sayılan sürümler", ""]
        for m in sorted(merges, key=lambda m: (id_key(m["olcut"]), m["temsilci"])):
            us = ", ".join(f"{nm(u['doc_id'])} (`{u['doc_id']}`: {SURUM_NEDEN[u['neden']]})" for u in m["uyeler"])
            L.append(f"- {m['olcut']}: temsilci {nm(m['temsilci'])} (`{m['temsilci']}`) ← {us}")
        L.append("")
        unsure = [(m, u) for m in merges for u in m["uyeler"] if u["karar"] == "belirsiz"]
        if unsure:
            L += ["### Sürümü doğrulanacak belgeler (emin olunamadı; tek sayıldı)", "",
                  "Metinleri çok benzer ama dönem bilgisi yok ve sayısal içerik farklı: aynı belgenin sürümü mü, "
                  "başka döneme ait veri mi kodla ayrılamadı. Farklı dönemse review.xlsx'te üyenin satırını "
                  "`duzelt` edin (yuva aynı kalabilir); ayrı kanıt olarak listeye girer.", ""]
            for m, u in sorted(unsure, key=lambda x: (id_key(x[0]["olcut"]), x[1]["doc_id"])):
                L.append(f"- {m['olcut']}: {nm(u['doc_id'])} (`{u['doc_id']}`) ↔ temsilci {nm(m['temsilci'])} "
                         f"(`{m['temsilci']}`)")
            L.append("")
    if metin_var:
        un = [it for it in kept if it.secim != "atif"]
        if un:
            L += ["### Listede olup metinde atıf almayan kanıtlar", "",
                  "Yayımlanan listede ama ölçüt metninde atıf yapılmamış: değerlendirici açısından açıklanmamış "
                  "kanıt. Metinde kullanın (`bidr write`) ya da gerekmiyorsa satırı `ret` edin.", ""]
            by: dict[str, list] = {}
            for it in un:
                by.setdefault(it.olcut, []).append(it)
            for c in sorted(by, key=id_key):
                L.append(f"- {c}: " + "; ".join(f"{nm(it.doc_id)} (`{it.doc_id}`, OD{it.od})"
                                                 for it in sorted(by[c], key=lambda x: x.doc_id)))
            L.append("")
    if not dropped and not merges:
        L += ["Bütün adaylar yayımlandı.", ""]
    L.append(GAPS_END)
    return "\n".join(L) + "\n"
