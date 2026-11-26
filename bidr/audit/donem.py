"""Dönem kuralı: belge türüne göre (komisyon kararı, 2026-11-18). Veri:
`bidr/data/profiles/donem_kurali.yaml`; gerekçe: `docs/AUDIT.md` "Dönem kuralı".

yapı  → rapor yılında yürürlükte mi: dönem içi tam sayılır; önceki yıl tarihli ya da tarihsiz yapı
        belgesi, daha yeni sürüm ya da yürürlükten kaldırma yoksa yürürlükte varsayılır ve sorulmadan
        sayılır (`yururluk_varsayildi` / `tarih_varsayildi`, kullanıcı kararı 2026-11-26).
        Tarihi rapor yılından sonra: `donem_sonrasi` (sayılmaz) ya da revizyon kanıtı varsa
        sayılır + `revizyon_donem_sonrasi`. Sürüm grubunda en yeni sürüm yürürlükte sayılır (eskisi
        `surum_eski`, bilgi; kullanıcı kararı 2026-11-26).
olay  → rapor yılında mı gerçekleşti: önceki yıl U/K/Ö/Z sayılmaz (`gecmis_kanit`); planla
        hâlâ yürürlükteki usul/karar olarak yapı gibi sayılır (`onceki_olay_plani_sayilir`,
        vars. true; false ile planla da sayılmaz); sonraki yıl `donem_sonrasi`. Tarihsiz (ya da
        tarihi yalnız dosya adından) olay belgesi aksi görülmedikçe dönem içi varsayılır ve sayılır
        (`tarih_varsayildi`); olay tarihi çelişkili (birden çok yılın tarihi) `tarih_dogrulanmali`:
        sayılmaz, satır görünür.
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
    "tarih_varsayildi": "tarih yok: dönem içi varsayıldı",
    "yururluk_varsayildi": "rapor yılında yürürlükte varsayıldı",
    "yururluk_bitmis": "yürürlük aralığı rapor yılından önce bitiyor",
    "revizyon_donem_sonrasi": "revizyon tarihi dönem sonrası; dönemdeki sürüm aranmalı",
    "surum_eski": "daha yeni sürümü var: en yeni sürüm yürürlükte sayıldı (bu sürüm sayılmadı)",
    "surum_donem_sonrasi": "dönem sonrası sürüm (kanıt değil)",
    "surum_dogrulanmali": "sürüm doğrulanmalı",
    "yururlukten_kalkmis": "başka bir belgeyle yürürlükten kaldırılmış (kanıt değil)",
    "sayfa_donem_sonrasi": "sayfa dönem sonrası güncellemeli; içerikte rapor yılı tarihi yok",
}
# sayılmayan dönem işaretleri (satır görünür; yayımlanan listeye girmez: bidr/file/select.py)
DONEM_DISI = ("donem_sonrasi", "surum_eski", "surum_donem_sonrasi", "yururlukten_kalkmis")
KAYNAK = {"bas_en_sik": "baş bölgede en sık tarih", "bas_ilk": "baş bölgedeki ilk tarih",
          "metin_ilk": "metindeki ilk tarih", "yanit_zaman_damgasi": "yanıt zaman damgaları"}
ARALIK_TABLOSU = 3      # en az bu kadar başlangıç–bitiş çifti: proje/sözleşme listesi
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


def _span(doc: dict) -> tuple[int, int] | None:
    """Belgenin çok yıllı yürürlük aralığı (identify `yururluk_araligi`; eski kayıtta başlıktan)."""
    sp = doc.get("yururluk_araligi")
    if isinstance(sp, (list, tuple)) and len(sp) == 2:
        try:
            return int(sp[0]), int(sp[1])
        except (TypeError, ValueError):
            return None
    from bidr.identify.dates import plan_span
    from bidr.identify.text import fold
    b = fold(str(doc.get("baslik") or ""))
    return plan_span(b, len(b)) if b else None


def doc_time(doc: dict, dosya: str | None = None) -> dict:
    """Belgenin rapor yılına göre zamanı ve tarihin nereden alındığı:
    {zaman: ici|once|sonra|bilinmiyor, yil, kaynak, zayif}. Öncelik: metin içi birincil tarih
    (identify `tarih`, `tarih_kaynagi`), akademik dönem (`akademik_donem`; dönemsiz "2026-2027"
    akademik yılı da), metindeki yıl ifadesi (`yil_ifadeleri`: "2025 yılı içerisinde"), dosya
    adı (`zayif`: yalnız dışlamada güvenilir). Yapı belgesinde yürürlük aralığı için
    `yapi_time`."""
    from bidr.identify.dates import term_year
    ici, period = doc.get("donem_ici"), doc.get("donem")
    year, kaynak = None, ""
    if doc.get("tarih"):
        try:
            year = int(str(doc["tarih"])[:4])
            kaynak = _source_text(doc.get("tarih_kaynagi"))
            ya = doc.get("yanit_araligi")
            if doc.get("tarih_kaynagi") == "yanit_zaman_damgasi" and isinstance(ya, (list, tuple)) and len(ya) == 2:
                kaynak = f"metin (yanıt zaman damgaları: {ya[0]} – {ya[1]})"
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
    # açık takvim yılı ifadesi ("2025 yılı içerisinde", "2025 yılında"): metin içi tarih kaynağı
    ys = _years(doc.get("yil_ifadeleri"))
    if ys:
        k = "metin (yıl ifadesi: " + ", ".join(f"{y} yılı" for y in ys) + ")"
        if period is not None and period in ys:
            return {"zaman": ICI, "yil": period, "kaynak": k, "zayif": False}
        # yalnız daha sonraki yıllar: içerik dönem sonrasına ait. Yalnız önceki yıllar ise çoğu
        # kez anılan geçmiştir ("1994 yılında kuruldu"), belgenin tarihi değil: bilinmiyor kalır.
        if period is not None and all(y > period for y in ys):
            return {"zaman": SONRA, "yil": min(ys), "kaynak": k, "zayif": False}
    n = _from_name(dosya, period)
    if n and n[0] != BILINMIYOR:
        return {"zaman": n[0], "yil": n[1], "kaynak": f"dosya adı ({Path(str(dosya)).name})", "zayif": True}
    return {"zaman": BILINMIYOR, "yil": year, "kaynak": kaynak, "zayif": False}


def yapi_time(doc: dict, dosya: str | None = None) -> dict:
    """Yapı belgesinin zamanı: `doc_time`, ama çok yıllı yürürlük aralığı ("2022-2026 Stratejik
    Planı", identify `yururluk_araligi`) rapor yılını kapsıyorsa önceki/bilinmeyen tarih belgeyi
    dönem içi yapar: hazırlık tarihi değil yürürlük belirler. Dönem sonrası tarihi aşmaz
    (sonraki sürüm/revizyon kuralı geçerli)."""
    t = doc_time(doc, dosya)
    period, sp = doc.get("donem"), _span(doc)
    weak = t["zaman"] in (ONCE, BILINMIYOR) or (t["zaman"] == ICI and t["zayif"])
    if sp and period is not None and sp[0] <= period <= sp[1] and weak:
        k = f"yürürlük aralığı ({sp[0]}-{sp[1]})"
        return {"zaman": ICI, "yil": period, "kaynak": k + (f"; {t['kaynak']}" if t["kaynak"] else ""),
                "zayif": False}
    return t


def _event_date(rule: Rule, doc: dict, dtype: str, t: dict) -> tuple[dict, str]:
    """Olay belgesinde birden çok tarih: olayın tarihi ile belgede geçen referans tarihlerini
    ayırır. (zaman kaydı, not). Not doluysa ve zaman değişmediyse emin değil: tarih doğrulanmalı."""
    period = doc.get("donem")
    if period is None or t["zayif"]:
        return t, ""
    # Başlangıç–bitiş çiftleri (proje, sözleşme, görevlendirme): bitiş tarihi olayın tarihi
    # değildir; ileri bitiş tarihi belgeyi "dönem sonrası" ya da "tarih belirsiz" yapmaz.
    # Aralık tablosunda (en az ARALIK_TABLOSU çift) eşleşmemiş ileri tarihler de bitiş/OCR
    # kalıntısı sayılır; belgenin dönemi başlangıçlardan okunur.
    ranges = [r for r in doc.get("tarih_araliklari") or [] if isinstance(r, (list, tuple)) and len(r) == 2]
    starts = {r[0] for r in ranges if r[0]}
    ends = {r[1] for r in ranges} - starts
    dates = [x for x in doc.get("tarihler") or [] if x not in ends]
    if len(starts) >= ARALIK_TABLOSU:
        dates = [x for x in dates if _years([x]) and _years([x])[0] <= period] + sorted(starts)
    ys = _years(dates)
    sy = _years(starts)
    if (sy and period in sy and t["zaman"] in (ONCE, BILINMIYOR)
            and not str(doc.get("tarih_kaynagi") or "").startswith("etiket:")):
        return {**t, "zaman": ICI, "yil": period,
                "kaynak": (t["kaynak"] + "; " if t["kaynak"] else "") + f"aralık başlangıcı ({period})"}, ""
    if not doc.get("tarih") or not ys:
        return t, ""
    if doc.get("tarih_kaynagi") == "yanit_zaman_damgasi":
        return t, ""                    # form yanıt tablosu: dönemi yanıt aralığı belirledi (identify)
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


def _stale_page(doc: dict, t: dict) -> str | None:
    """Sayfa güncelleme damgası (identify `guncelleme_tarihi`) rapor yılından sonra ve içerikte
    rapor yılını gösteren tarih yoksa damganın tarihi, değilse None."""
    upd, period = str(doc.get("guncelleme_tarihi") or ""), doc.get("donem")
    if not upd[:4].isdigit() or period is None or int(upd[:4]) <= period:
        return None
    if t["zaman"] == BILINMIYOR or (t["zaman"] == ICI and t["zayif"]):
        return upd
    return None


def apply_row(rule: Rule, doc: dict, dtype: str, stage: str | None, dosya: str | None = None,
              surum: str | None = None, parca: dict | None = None) -> dict:
    """Bir eşleşmeye dönem kuralı: {sinif, zaman, yil, sayilir, flags, kaynak, not}. `sayilir`
    False ise satır görünür kalır ama hiçbir halkayı kanıtlamaz (döngü sonradan açabilir).
    `surum`: belgenin sürüm grubundaki durumu (`version_status`).
    `parca`: birleşik belgede alıntının parçası (`bidr.identify.parca.part_view`): kural belgenin
    değil parçanın tarih alanlarıyla işler; parça tarihi bilinmiyorsa belge tarihiyle işler ve
    satır sessiz `tarih_varsayildi` alır (aksi görülmedikçe dönem içi). Kuralın kendisi değişmez."""
    if parca:
        out = _apply_row(rule, {**doc, **parca["alanlar"]}, dtype, stage, dosya, surum)
        if parca.get("etiket") and out["kaynak"]:
            out["kaynak"] = f"{parca['etiket']}: {out['kaynak']}"
        if parca.get("dogrulanmali") and not {"tarih_dogrulanmali", "tarih_varsayildi"} & set(out["flags"]):
            out["flags"].append("tarih_varsayildi")
            out["not"] = "; ".join(x for x in (out["not"], parca.get("not")) if x)
        return out
    return _apply_row(rule, doc, dtype, stage, dosya, surum)


def _apply_row(rule: Rule, doc: dict, dtype: str, stage: str | None, dosya: str | None = None,
               surum: str | None = None) -> dict:
    cls = rule.cls(dtype, stage)
    t = yapi_time(doc, dosya) if cls == YAPI else doc_time(doc, dosya)
    note = ""
    if cls == OLAY:
        t, note = _event_date(rule, doc, dtype, t)
    zaman, yil = t["zaman"], t["yil"]
    flags: list[str] = []
    say = True
    stale = _stale_page(doc, t)
    if stale:
        # Sayfanın kopyası dönemden sonra güncellenmiş ve içerikte rapor yılına ait tarih yok:
        # sayfanın gösterdiği hâl (kurul üyeleri, haberler) rapor yılına ait değil olabilir.
        # Plan halkası (yapı: tanım/yürürlük) güncellik uyarısıyla sayılır; üstü sayılmaz.
        flags.append("sayfa_donem_sonrasi")
        note = f"sayfa {stale} güncellemeli; içerikte {doc.get('donem')} tarihi ya da yıl ifadesi yok"
        if stage != "planla":
            return {"sinif": cls, "zaman": zaman, "yil": yil, "sayilir": False,
                    "flags": ["tarih_dogrulanmali", *flags], "kaynak": t["kaynak"], "not": note}
    if cls == YAPI:
        if surum in ("surum_eski", "surum_donem_sonrasi"):
            say = False
            flags.append(surum)
        elif zaman == SONRA:
            if not t["zayif"] and _revised(rule, doc):
                flags += ["guncellik_dogrulanmali", "revizyon_donem_sonrasi"]
            else:
                say = False
                flags.append("donem_sonrasi")       # dönemden sonra yürürlüğe girdi
        elif zaman == BILINMIYOR:
            flags.append("tarih_varsayildi")            # tarihsiz kural/plan: yürürlükte varsayılır
        elif zaman != ICI:
            # önceki yıl tarihli, yenisi yok: yürürlükte varsayılır; belgenin kendi yürürlük aralığı rapor
            # yılından önce bittiyse açık çelişki: sorulur
            sp = _span(doc)
            ended = sp is not None and doc.get("donem") is not None and sp[1] < doc["donem"]
            flags += ["guncellik_dogrulanmali", "yururluk_bitmis"] if ended else ["yururluk_varsayildi"]
            if ended:
                note = f"yürürlük aralığı {sp[0]}-{sp[1]}: rapor yılından önce bitiyor"
        if surum == "surum_dogrulanmali":
            flags.append(surum)
        elif surum == "surum_dogrulanmali_sayilmaz":
            say = False
            flags.append("surum_dogrulanmali")
    elif zaman == SONRA:
        say = False
        flags.append("donem_sonrasi")
    elif note:
        say = False                                 # birden çok yılın tarihi: olayın yılı çelişkili
        flags.append("tarih_dogrulanmali")
    elif zaman == BILINMIYOR or (zaman == ICI and t["zayif"]):
        # tarih yok ya da yalnız dosya adından: aksi görülmedikçe dönem içi (kullanıcı kararı 2026-11-26)
        flags.append("tarih_varsayildi")
        if zaman == ICI and t["zayif"]:
            note = "tarih yalnız dosya adından"
    elif zaman == ONCE:
        if stage == "planla" and rule.onceki_olay_plani:
            flags.append("yururluk_varsayildi")        # usul tanımlayan eski karar: yapı gibi, yürürlükte
        else:
            say = False
            flags.append("gecmis_kanit")
    return {"sinif": cls, "zaman": zaman, "yil": yil, "sayilir": say, "flags": flags,
            "kaynak": t["kaynak"], "not": note}


def _version_key(doc: dict, inventory: dict[str, str], did: str, text=None) -> dict:
    """Sürüm sıralama anahtarı: {yil, tarih (YYYY-MM-DD, yılla tutarlıysa), rev (revizyon no)}.
    Yıl `doc_time`'dan (metin içi tarih, akademik dönem, yıl ifadesi, dosya adı); tam tarih identify
    `tarih`ından; revizyon numarası kontrollü belge başlığından (`identify.versions.control_signature`;
    metin verilmişse)."""
    t = doc_time(doc, inventory.get(did))
    yil = t["yil"] if t["zaman"] != BILINMIYOR else None
    ts = str(doc.get("tarih") or "")[:10]
    tarih = ts if yil is not None and re.fullmatch(r"\d{4}-\d{2}-\d{2}", ts) and int(ts[:4]) == yil else None
    rev = None
    if text is not None:
        from bidr.identify.versions import control_signature
        sig = control_signature(text(did) or "")
        no = sig[1].split("|", 1)[1] if sig else ""
        rev = int(no) if no.isdigit() else None
    return {"yil": yil, "tarih": tarih, "rev": rev}


def version_cmp(a: dict, b: dict) -> int:
    """İki sürüm anahtarını karşılaştırır: >0 a daha yeni, <0 b daha yeni, 0 sıralanamıyor. Sıra:
    (1) ikisinin de yılı varsa yıl, (2) ikisinin de tam tarihi varsa tarih, (3) ikisinin de revizyon
    numarası varsa revizyon. Hiçbiri ayırmıyorsa (aynı tarih, tarihsiz ve revizyonsuz) 0."""
    for k in ("yil", "tarih", "rev"):
        x, y = a.get(k), b.get(k)
        if x is not None and y is not None and x != y:
            return 1 if x > y else -1
    return 0


def version_status(docs: dict[str, dict], rule: Rule, inventory: dict[str, str] | None = None,
                   text=None) -> dict[str, str]:
    """Yapı belgesi sürüm grupları (identify `surum_grubu`). Kullanıcı kararı (2026-11-26, "Kural belliyse
    sorulmaz"): rapor yılında EN YENİ sürüm yürürlükte varsayılır ve sayılır; ondan eski sürümler yerini
    bırakmıştır. Sıra `version_cmp` (yıl, tam tarih, revizyon no). doc_id → durum:
    - `surum_eski`: aynı grupta (rapor yılından sonra olmayan) daha yeni bir sürüm var; sayılmaz, satır
      bilgi olarak görünür ("Bakın" yapmaz; eski `surum_yururlukten_kalkmis` bunun içindedir);
    - `surum_donem_sonrasi`: dönemde ya da öncesinde tarihli bir sürüm varken rapor yılından sonraki
      sürüm (eski kural, sorulur);
    - `surum_dogrulanmali`: hiçbir sıra kurulamadı (bütün adaylar tarihsiz/revizyonsuz ya da aynı): sayılır,
      sorulur;
    - `surum_dogrulanmali_sayilmaz`: tarihsiz (sıralanamayan) üye, sırası belli en yeni tarihli sürüm
      varken: sayılmaz, sorulur (tarihli en yeni sürüm sorulmadan sayılır).
    Aynı yılın/tarihin iki tarihli sürümü sıralanamaz; ikisi de sayılır (eski davranış, sorulmaz).
    `text(did)`: belge metni (revizyon numarası için; verilmezse yalnız tarihler).
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
        # birbirinin sürümü değildir: parça grubu tek üye sayılır, anahtarı tarihli ilk parçanın
        # anahtarı; durum bütün parçalara geçer.
        units: dict[str, list[str]] = {}
        for m in mem_docs:
            units.setdefault(docs[m].get("parca_grubu") or m, []).append(m)
        units_all.update(units)
        if len(units) < 2:
            continue
        period = next((docs[m].get("donem") for m in mem_docs if docs[m].get("donem") is not None), None)
        if period is None:
            continue
        for sub in _same_document(units, text):
            _order_versions(sub, docs, inventory, text, period, out)
    for u, parts in units_all.items():          # parça grubu kimliği → parçaların her biri
        if u not in docs and u in out:
            st = out.pop(u)
            for m in parts:
                out[m] = st
    return out


def _same_document(units: dict[str, list[str]], text=None) -> list[dict[str, list[str]]]:
    """Sürüm grubunu aynı belgenin sürümlerine böler. identify'ın benzerlik grubu aynı şablonu dolduran farklı
    belgeleri (ör. iki dersin bilgi formu) birleştirebilir; baş bölgedeki belge kimlikleri (ders kodu, doküman/iş
    akışı no; `identify.versions.head_ids` "k:"/"d:") çelişen üyeler birbirinin sürümü değildir. Tarih ve karar
    sayısı kullanılmaz: sürümlerde zaten farklıdır. Grupta çelişen bir çift varsa üyeler kimlik kümelerine göre
    ayrılır (kimliksizler kendi aralarında); yoksa grup olduğu gibi kalır. Metin verilmezse bölünmez."""
    if text is None:
        return [units]
    from bidr.identify.versions import head_ids, ids_compatible
    ids = {u: frozenset(x for x in head_ids(text(sorted(parts)[0]) or "") if x[:2] in ("k:", "d:"))
           for u, parts in units.items()}
    us = sorted(units)
    if all(ids_compatible(ids[a], ids[b]) for i, a in enumerate(us) for b in us[i + 1:]):
        return [units]
    subs: dict[frozenset, dict[str, list[str]]] = {}
    for u in us:
        subs.setdefault(ids[u], {})[u] = units[u]
    return [x for x in subs.values() if len(x) > 1]


def _order_versions(units: dict[str, list[str]], docs: dict[str, dict], inventory: dict[str, str], text,
                    period: int, out: dict[str, str]) -> None:
    """Bir belgenin sürümlerine durum yazar (`version_status`)."""
    key: dict[str, dict] = {}
    for u, parts in units.items():
        ks = [_version_key(docs[m], inventory, m, text)
              for m in sorted(parts, key=lambda x: (docs[x].get("parca_sira") or 0, x))]
        key[u] = next((k for k in ks if k["yil"] is not None), ks[0])
    sonra = [u for u, k in key.items() if k["yil"] is not None and k["yil"] > period]
    aday = sorted(u for u in key if u not in sonra)
    if not aday:
        return
    if any(key[u]["yil"] is not None for u in aday):
        for u in sonra:
            out[u] = "surum_donem_sonrasi"           # dönemde yürürlükte bir sürüm varken sonraki sürüm
    # en yeni: başka hiçbir aday tarafından geçilmeyenler. Geçilen her aday eskidir.
    tepe = [u for u in aday if not any(version_cmp(key[v], key[u]) > 0 for v in aday if v != u)]
    for u in aday:
        if u not in tepe:
            out[u] = "surum_eski"
    tarihli = [u for u in tepe if key[u]["yil"] is not None]
    tarihsiz = [u for u in tepe if key[u]["yil"] is None]
    if len(tepe) < 2 and not (tarihsiz and sonra):
        return                                       # en yeni sürüm belli: sorulmadan sayılır
    # aynı yıl/tarihli tarihli adaylar: ikisi de sayılır (sorulmaz). Tarihsiz aday sıralanamaz (tek
    # adaysa da dönem sonrası sürümün tarihsiz kopyası olabilir): sorulur.
    for u in tarihsiz:
        out[u] = "surum_dogrulanmali_sayilmaz" if tarihli else "surum_dogrulanmali"


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
