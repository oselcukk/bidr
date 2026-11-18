"""Dönem kuralı: belge türüne göre (komisyon kararı, 2026-11-18). Veri:
`bidr/data/profiles/donem_kurali.yaml`; gerekçe: `docs/AUDIT.md` "Dönem kuralı".

yapı  → rapor yılında yürürlükte mi: dönem içi tam sayılır; aksi/bilinmiyor sayılır +
        `guncellik_dogrulanmali`.
        Tarihi rapor yılından sonra: `donem_sonrasi` (sayılmaz) ya da revizyon kanıtı varsa
        sayılır + `revizyon_donem_sonrasi`. Sürüm grubunda yürürlükteki sürüm seçilir.
olay  → rapor yılında mı gerçekleşti: önceki yıl U/K/Ö/Z sayılmaz (`gecmis_kanit`); planla
        hâlâ yürürlükteki usul/karar olarak yapı gibi sayılır (`onceki_olay_plani_sayilir`,
        vars. true; false ile planla da sayılmaz); sonraki yıl `donem_sonrasi`,
        tarihsiz ya da olay tarihi belirsiz `tarih_dogrulanmali`: sayılmaz, satır görünür.
karma → aşama belirler: planla yapı, üstü olay.
Döngü: ölçütte sayılan bir eşleşmenin alıntısı döngü tanımlıyorsa (her N yılda vb.) son N
yılın `gecmis_kanit` satırları o ölçütte sayılır (`dongu_halkasi`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

FILE = "donem_kurali.yaml"
DEFAULT_PATH = Path(__file__).resolve().parents[1] / "data" / "profiles" / FILE
YAPI, OLAY, KARMA = "yapi", "olay", "karma"
ICI, ONCE, SONRA, BILINMIYOR = "ici", "once", "sonra", "bilinmiyor"
SAYI = {"iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6}

# işaret → tabloda okunur metin
ETIKET = {
    "guncellik_dogrulanmali": "güncellik doğrulanmalı",
    "gecmis_kanit": "geçmiş kanıt (süreklilik)",
    "dongu_halkasi": "döngü halkası",
    "donem_sonrasi": "dönem sonrası",
    "tarih_dogrulanmali": "tarih doğrulanmalı",
    "revizyon_donem_sonrasi": "revizyon tarihi dönem sonrası; dönemdeki sürüm aranmalı",
    "surum_yururlukten_kalkmis": "sürüm dönemden önce yenilendi (kanıt değil)",
    "surum_donem_sonrasi": "dönem sonrası sürüm (kanıt değil)",
    "surum_dogrulanmali": "sürüm doğrulanmalı",
}
# sayılmayan dönem işaretleri (satır görünür; yayımlanan listeye girmez: bidr/file/select.py)
DONEM_DISI = ("donem_sonrasi", "surum_yururlukten_kalkmis", "surum_donem_sonrasi")
KAYNAK = {"bas_en_sik": "baş bölgede en sık tarih", "bas_ilk": "baş bölgedeki ilk tarih",
          "metin_ilk": "metindeki ilk tarih"}
_YIL = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
_AKADEMIK = re.compile(r"(?<!\d)(20\d\d)\s*[-_/]\s*(20\d\d)(?!\d)")


@dataclass(frozen=True)
class Rule:
    classes: dict[str, str]                # tür → yapi | olay | karma
    cycle_default: int
    cycle_max: int
    cycle_patterns: tuple[re.Pattern, ...]
    cycle_criteria: dict[str, str]         # ölçüt → öneri metni
    onceki_olay_plani: bool = True         # önceki yıl olayının planla eşleşmesi sayılır mı
    en_gec_turler: frozenset = frozenset()  # olay tarihi belgedeki en geç tarih (duyuru)
    revizyon_etiketleri: tuple[str, ...] = ("revizyon", "degisiklik", "guncelleme")

    def cls(self, doc_type: str | None, stage: str | None) -> str:
        c = self.classes.get(doc_type or "", KARMA)
        if c == KARMA:
            return YAPI if stage == "planla" else OLAY
        return c

    def cycle_years(self, quote: str) -> int | None:
        """Alıntı bir gözden geçirme döngüsü tanımlıyorsa döngü yılı, değilse None."""
        from bidr.identify.text import fold
        f = fold(quote or "")
        for p in self.cycle_patterns:
            m = p.search(f)
            if m:
                n = (m.groupdict() or {}).get("n")
                y = int(n) if n and n.isdigit() else SAYI.get(n or "", self.cycle_default)
                if y < 2:              # yıllık: takvim yılı kuralı zaten geçerli
                    continue
                return min(y, self.cycle_max)
        return None


def rule_path() -> Path:
    from bidr.criteria.profiles import profiles_dir
    p = profiles_dir() / FILE
    return p if p.exists() else DEFAULT_PATH


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> Rule:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    classes: dict[str, str] = {}
    for c in (YAPI, OLAY, KARMA):
        for t in raw.get(c) or []:
            if t in classes:
                raise ValueError(f"{path}: '{t}' iki sınıfta ({classes[t]}, {c})")
            classes[t] = c
    d = raw.get("dongu") or {}
    t = raw.get("tarih") or {}
    return Rule(classes, int(d.get("varsayilan_yil", 4)), int(d.get("en_cok_yil", 6)),
                tuple(re.compile(p) for p in d.get("desenler") or []),
                {k: " ".join(str(v).split()) for k, v in (d.get("olcutler") or {}).items()},
                bool(raw.get("onceki_olay_plani_sayilir", True)),
                frozenset(t.get("olay_tarihi_en_gec") or ()),
                tuple(str(x) for x in t.get("revizyon_etiketleri") or ("revizyon", "degisiklik", "guncelleme")))


def load_rule(path: Path | None = None) -> Rule:
    p = Path(path) if path else rule_path()
    return _load(str(p), p.stat().st_mtime)


def _zaman(y: int | None, period: int | None) -> str:
    if y is None or period is None:
        return BILINMIYOR
    return ICI if y == period else ONCE if y < period else SONRA


def _years(dates) -> list[int]:
    out = []
    for x in dates or []:
        try:
            out.append(int(str(x)[:4]))
        except ValueError:
            pass
    return out


def _source_text(src: str | None) -> str:
    src = src or ""
    if src.startswith("etiket:"):
        return f"metin (etiket: {src[7:].strip()})"
    return f"metin ({KAYNAK.get(src, src or '?')})"


def _from_name(name: str | None, period: int | None) -> tuple[str, int | None] | None:
    """Dosya adındaki yıl ya da akademik yıl (yalnız dosya adı, klasörler değil)."""
    if not name:
        return None
    stem = Path(str(name).replace("\\", "/")).stem
    m = _AKADEMIK.search(stem)
    if m and int(m.group(2)) == int(m.group(1)) + 1:
        a, b = int(m.group(1)), int(m.group(2))
        if period is None:
            return BILINMIYOR, a
        return (ICI, period) if a <= period <= b else (SONRA, a) if a > period else (ONCE, b)
    ys = sorted({int(y) for y in _YIL.findall(stem)})
    if len(ys) == 1:
        return _zaman(ys[0], period), ys[0]
    return None


def doc_time(doc: dict, dosya: str | None = None) -> dict:
    """Belgenin rapor yılına göre zamanı ve tarihin nereden alındığı:
    {zaman: ici|once|sonra|bilinmiyor, yil, kaynak, zayif}. Öncelik: metin içi birincil tarih
    (identify `tarih`, `tarih_kaynagi`), akademik dönem (`akademik_donem`; dönemsiz "2026-2027"
    akademik yılı da), dosya adı (`zayif`: yalnız dışlamada güvenilir)."""
    from bidr.identify.dates import term_year
    ici, period = doc.get("donem_ici"), doc.get("donem")
    year, kaynak = None, ""
    if doc.get("tarih"):
        try:
            year = int(str(doc["tarih"])[:4])
            kaynak = _source_text(doc.get("tarih_kaynagi"))
        except ValueError:
            year = None
    terms = doc.get("akademik_donem") or []
    if year is None:
        ys = [y for y in (term_year(t) for t in terms) if y]
        if ys and period is not None:
            before = [y for y in ys if y < period]
            year = max(before) if before else min(ys)
        elif ys:
            year = max(ys)
        if year is not None:
            kaynak = "akademik dönem (" + ", ".join(terms) + ")"
    if ici is True:
        return {"zaman": ICI, "yil": period if period is not None else year, "kaynak": kaynak, "zayif": False}
    if ici is False:
        z = SONRA if year is not None and period is not None and year > period else ONCE
        return {"zaman": z, "yil": year, "kaynak": kaynak, "zayif": False}
    # identify karar veremedi: dönemsiz akademik yıl ("Komisyonlar 2026-2027"), sonra dosya adı
    if period is not None and terms:
        spans = []
        for t in terms:
            m = re.match(r"(\d{4})-(\d{4})", t)
            if m:
                spans.append((int(m.group(1)), int(m.group(2))))
        if spans:
            k = "akademik yıl (" + ", ".join(terms) + ")"
            if any(a <= period <= b for a, b in spans):
                return {"zaman": ICI, "yil": period, "kaynak": k, "zayif": False}
            if all(a > period for a, _ in spans):
                return {"zaman": SONRA, "yil": min(a for a, _ in spans), "kaynak": k, "zayif": False}
            return {"zaman": ONCE, "yil": max(b for _, b in spans), "kaynak": k, "zayif": False}
    n = _from_name(dosya, period)
    if n and n[0] != BILINMIYOR:
        return {"zaman": n[0], "yil": n[1], "kaynak": f"dosya adı ({Path(str(dosya)).name})", "zayif": True}
    return {"zaman": BILINMIYOR, "yil": year, "kaynak": kaynak, "zayif": False}


def _event_date(rule: Rule, doc: dict, dtype: str, t: dict) -> tuple[dict, str]:
    """Olay belgesinde birden çok tarih: olayın tarihi ile belgede geçen referans tarihlerini
    ayırır. (zaman kaydı, not). Not doluysa ve zaman değişmediyse emin değil: tarih doğrulanmalı."""
    period = doc.get("donem")
    if period is None or t["zayif"] or not doc.get("tarih"):
        return t, ""
    ys = _years(doc.get("tarihler"))
    if not ys:
        return t, ""
    if dtype in rule.en_gec_turler:
        y = max(ys)                     # duyuru: yayım tarihi değil etkinlik tarihi (en geç)
        if y > period and t["zaman"] != SONRA:
            return {**t, "zaman": SONRA, "yil": y,
                    "kaynak": t["kaynak"] + f"; olay tarihi en geç tarih ({y})"}, ""
        return t, ""
    if str(doc.get("tarih_kaynagi") or "").startswith("etiket:"):
        return t, ""                    # etiketli tarih (ör. "Toplantı tarihi:") olayın tarihidir
    zs = {_zaman(y, period) for y in ys}
    if t["zaman"] == ICI and SONRA in zs:
        later = sorted({y for y in ys if y > period})
        return t, f"birincil tarih rapor yılında, belgede dönem sonrası tarih de var ({', '.join(map(str, later))})"
    if t["zaman"] == ONCE and ICI in zs:
        return t, f"birincil tarih {t['yil']}, belgede rapor yılı ({period}) tarihi de var: olay tarihi belirsiz"
    return t, ""


def _revised(rule: Rule, doc: dict) -> bool:
    """Dönem sonrası tarihli yapı belgesinin önceki bir sürümü dönemde yürürlükte olabilir mi:
    tarih bir revizyon/değişiklik etiketinden geliyor ya da metinde rapor yılı ya da öncesine ait
    tarih var."""
    from bidr.identify.text import fold
    src = fold(str(doc.get("tarih_kaynagi") or ""))
    if any(k in src for k in rule.revizyon_etiketleri):
        return True
    period = doc.get("donem")
    return period is not None and any(y <= period for y in _years(doc.get("tarihler")))


def apply_row(rule: Rule, doc: dict, dtype: str, stage: str | None, dosya: str | None = None,
              surum: str | None = None) -> dict:
    """Bir eşleşmeye dönem kuralı: {sinif, zaman, yil, sayilir, flags, kaynak, not}. `sayilir`
    False ise satır görünür kalır ama hiçbir halkayı kanıtlamaz (döngü sonradan açabilir).
    `surum`: belgenin sürüm grubundaki durumu (`version_status`)."""
    cls = rule.cls(dtype, stage)
    t = doc_time(doc, dosya)
    note = ""
    if cls == OLAY:
        t, note = _event_date(rule, doc, dtype, t)
    zaman, yil = t["zaman"], t["yil"]
    flags: list[str] = []
    say = True
    if cls == YAPI:
        if surum in ("surum_yururlukten_kalkmis", "surum_donem_sonrasi"):
            say = False
            flags.append(surum)
        elif zaman == SONRA:
            if not t["zayif"] and _revised(rule, doc):
                flags += ["guncellik_dogrulanmali", "revizyon_donem_sonrasi"]
            else:
                say = False
                flags.append("donem_sonrasi")       # dönemden sonra yürürlüğe girdi
        elif zaman != ICI:
            flags.append("guncellik_dogrulanmali")
        if surum == "surum_dogrulanmali":
            flags.append(surum)
        elif surum == "surum_dogrulanmali_sayilmaz":
            say = False
            flags.append("surum_dogrulanmali")
    elif zaman == SONRA:
        say = False
        flags.append("donem_sonrasi")
    elif zaman == BILINMIYOR or note or (zaman == ICI and t["zayif"]):
        say = False
        flags.append("tarih_dogrulanmali")
        if zaman == ICI and t["zayif"]:
            note = note or "tarih yalnız dosya adından"
    elif zaman == ONCE:
        if stage == "planla" and rule.onceki_olay_plani:
            flags.append("guncellik_dogrulanmali")     # usul tanımlayan eski karar: yapı gibi
        else:
            say = False
            flags.append("gecmis_kanit")
    return {"sinif": cls, "zaman": zaman, "yil": yil, "sayilir": say, "flags": flags,
            "kaynak": t["kaynak"], "not": note}


def version_status(docs: dict[str, dict], rule: Rule, inventory: dict[str, str] | None = None
                   ) -> dict[str, str]:
    """Yapı belgesi sürüm grupları (identify `surum_grubu`): rapor yılında yürürlükte olan sürüm
    seçilir. doc_id → durum:
    - `surum_yururlukten_kalkmis`: rapor yılından önce yerini daha yeni bir sürüme bırakmış
      (yenisinin yılı < rapor yılı); kanıt değil (kanıt ilkesi `yururlukten_kalkmis`);
    - `surum_donem_sonrasi`: dönemde yürürlükte bir sürüm varken rapor yılından sonraki sürüm;
    - `surum_dogrulanmali`: yürürlükteki sürüm belirlenemedi (tarihsiz üye var); sayılır;
    - `surum_dogrulanmali_sayilmaz`: tarihsiz üye, tarihli yürürlükteki aday varken.
    Yalnız katalogda yapı sınıfındaki türler (karma/olay sürümleri select.py birleştirir)."""
    inventory = inventory or {}
    groups: dict[str, list[str]] = {}
    for did, d in docs.items():
        g = d.get("surum_grubu")
        if g and rule.classes.get(d.get("doc_type") or "") == YAPI:
            groups.setdefault(g, []).append(did)
    out: dict[str, str] = {}
    units_all: dict[str, list[str]] = {}
    for g, mem_docs in groups.items():
        # Tek belgenin bölünmüş parçaları (ingest `parca_grubu`; identify sürüm grubuna katar)
        # birbirinin sürümü değildir: parça grubu tek üye sayılır, yılı tarihli ilk parçanın yılı;
        # durum bütün parçalara geçer.
        units: dict[str, list[str]] = {}
        for m in mem_docs:
            units.setdefault(docs[m].get("parca_grubu") or m, []).append(m)
        units_all.update(units)
        mem = list(units)
        if len(mem) < 2:
            continue
        period = next((docs[m].get("donem") for m in mem_docs if docs[m].get("donem") is not None), None)
        if period is None:
            continue
        yrs = {}
        for u, parts in units.items():
            yrs[u] = None
            for m in sorted(parts, key=lambda x: (docs[x].get("parca_sira") or 0, x)):
                t = doc_time(docs[m], inventory.get(m))
                if t["zaman"] != BILINMIYOR:
                    yrs[u] = t["yil"]
                    break
        dated = {m: y for m, y in yrs.items() if y is not None}
        undated = [m for m in mem if m not in dated]
        le = {m: y for m, y in dated.items() if y <= period}
        if le:
            for m, y in le.items():
                if any(y < y2 < period for y2 in le.values()):
                    out[m] = "surum_yururlukten_kalkmis"
            for m, y in dated.items():
                if y > period:
                    out[m] = "surum_donem_sonrasi"
            if undated:
                for m in le:
                    out.setdefault(m, "surum_dogrulanmali")
                for m in undated:
                    out[m] = "surum_dogrulanmali_sayilmaz"
        elif undated:
            for m in undated:
                out[m] = "surum_dogrulanmali"
    for u, parts in units_all.items():          # parça grubu kimliği → parçaların her biri
        if u not in docs and u in out:
            st = out.pop(u)
            for m in parts:
                out[m] = st
    return out


def describe(r: dict) -> str:
    """Tablonun 'dönem kuralı' hücresi."""
    if not r.get("donem_sinif"):
        return ""
    s = {YAPI: "yapı", OLAY: "olay"}[r["donem_sinif"]]
    z = {ICI: "dönem içi", ONCE: "önceki yıl", SONRA: "sonraki yıl", BILINMIYOR: "tarih yok"}[r["donem_zaman"]]
    if r.get("donem_yil") and r["donem_zaman"] != BILINMIYOR:
        z += f" ({r['donem_yil']})"
    marks = [ETIKET[f] for f in dict.fromkeys(r["flags"]) if f in ETIKET]
    return " · ".join([s, z, *marks])
