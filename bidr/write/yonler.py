"""`bidr yonler prepare|apply`: alan düzeyinde Güçlü / Gelişmeye Açık Yönler (ajan modu)
→ `yonler/<alan>.json` (A, B, C, D; FR-0833'ün son tablosu).

Dayanak YALNIZ o alanın, birimin doldurduğu (kapsam `bolum`/`ortak`, bkz. bidr/render/kapsam.py)
alt ölçütleridir:
  - güçlü yön → ölçütün doğrulanmış açıklama metni (`texts/<ölçüt>.json`, `durum: dogrulandi`;
    kullanıcının `cikar` dediği metin sayılmaz);
  - gelişmeye açık yön → audit bulgusu (`audit-olcutler.json`: önerilen OD ≤ 2, eksik PUKÖ
    halkası, yalnız kurum geneli düzenleme; `evidence-index.csv`'de kanıtı olmayan ölçüt).
Her madde ilgili ölçüt kodunu parantez içinde taşır: "… (B.1.1)."

apply: şema + kod denetimi (ölçüt atfı her cümlede, atıf alanda ve listenin dayanağı olan
ölçütlerde mi, kanıt numarası yok, yasak ifade/koçluk/gelecek vaadi ve OD aşımı —
bidr/write/text.py'deki kurallar) ve kanıtla çapraz denetim (`cross_check`, kör test
2026-11-20): gelişmeye açık yönün "X kanıtı yok" hükmü audit zinciri, kanıt listesi ve ölçütün
doğrulanmış metniyle çelişmez (izleme/iyileştirme halkası kanıtlıyken "yok", listede birime ait
kanıt varken "bölüm düzeyinde kanıt yok/yalnız kurum geneli"; audit halkayı eksik saysa da
doğrulanmış metin izlemeyi/değerlendirmeyi/iyileştirmeyi anlatıyorsa "yok" — `text_rings`; metin
yalnız izleme verisini anlatıyorsa hüküm "sonuçların birimce değerlendirilmesi"ne daraltılır);
aynı ölçütte güçlü yönün söylediği uygulamayı ya da sonuçların değerlendirilmesini gelişmeye
açık yön yok saymaz; hedefe ulaşıldığı metinde görünmeyen gösterge değeri güçlü yön
olmaz (metindeki hedef/gerçekleşme sayıları da karşılaştırılır); fakülte/kurum geneli değer bölümün
değeri yanında olmadan verilmez (`fakulte_degeri`); aracın iç dili yok (`ic_dil`, bidr/write/ic_dil.py;
bulgular da sade dille verilir). Geçen cevap `yonler/<alan>.json`, `durum: taslak`.

Bağımsız doğrulama `bidr verify prepare|apply` akışına katılır (`work/verify/yonler/`,
görev `verify_yonler`, kayıt `verify-yonler.jsonl`): her madde atıf yaptığı ölçütün metni ya
da bulgusuyla karşılaştırılır; hepsi "destekleniyor" ise `dogrulandi`. Reddedilen alan
`bidr yonler prepare --reddedilenler` ile gerekçeli yeniden yazıma gider (sınır
`rapor.yeniden_yazim_siniri`); render reddedilmiş alanda doğrulayıcının desteklediği maddeleri
basar, desteklenmeyenleri çıkarır; madde kalmazsa hücreye açık ifade yazar; çıkarılan madde bir
ölçütü bütün yön hücrelerinden düşürürse rapor TASLAK olur (`yon_kapsam_kaybi`, bidr/render/run.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl

from . import packages as K
from . import run as W
from . import sources as S
from . import ic_dil as IC
from . import text as T

TASK = "write_yonler"
VTASK = "verify_yonler"
STAGE = "yonler"
DIR = "yonler"
LOG = "verify-yonler.jsonl"
ALANLAR = ("A", "B", "C", "D")
FINAL = ("dogrulandi", "reddedildi")
KOD = re.compile(r"\b([A-E]\.\d+\.\d+)\b")
RULE = ("İstemdeki kurallara uy: her cümle dayandığı ölçüt kodunu parantez içinde taşır \"(B.1.1)\"; "
        "güçlü yön yalnız doğrulanmış metinden, gelişmeye açık yön yalnız bulgudan; öğüt ve vaat yok; "
        "\"kanıt yok\" hükmü KANIT DURUMU, doğrulanmış metin ve güçlü yönlerle çelişmez; belgenin neden bu dönemin "
        "kanıtı sayılmadığı yazılmaz; aracın iç dili (\"OD'ye sayılmamıştır\", \"eşleşmiş\", \"uygulama halkası\") "
        "yok; hedefin altındaki gösterge güçlü yön değil.")
VRULE = ("Her maddeyi yalnız atıf yaptığı ölçütün doğrulanmış metni (g) ya da bulgusu (a) ile karşılaştır "
         "(destekleniyor / kismen / desteklenmiyor + gerekçe); listedeki her maddeye bir karar ver.")


# -- yollar ve kayıtlar --------------------------------------------------------------------------

def yonler_dir(ws: Workspace) -> Path:
    return ws.root / DIR


def work_dir(ws: Workspace) -> Path:
    return ws.root / "work" / STAGE


def verify_dir(ws: Workspace) -> Path:
    return ws.root / "work" / "verify" / STAGE


def load(ws: Workspace, alan: str) -> dict | None:
    p = yonler_dir(ws) / f"{alan}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def save(ws: Workspace, rec: dict) -> None:
    d = yonler_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{rec['alan']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")


def load_all(ws: Workspace) -> dict[str, dict]:
    return {a: t for a in ALANLAR if (t := load(ws, a))}


def load_log(ws: Workspace) -> dict[str, dict]:
    p = ws.root / LOG
    return {r["alan"]: r for r in read_jsonl(p) if r.get("alan")} if p.exists() else {}


def save_log(ws: Workspace, recs: dict[str, dict]) -> None:
    write_jsonl(ws.root / LOG, [recs[k] for k in sorted(recs)])


def text_sha(t: dict) -> str:
    return K.sha(json.dumps({"g": [x["metin"] for x in t.get("guclu") or []],
                             "a": [x["metin"] for x in t.get("gelisme") or []]}, ensure_ascii=False))


def items(t: dict) -> list[dict]:
    """[{yer, liste, metin}] — güçlü `g<i>`, gelişmeye açık `a<i>`."""
    out = [{"yer": f"g{i}", "liste": "guclu", "metin": x["metin"]} for i, x in enumerate(t.get("guclu") or [], 1)]
    out += [{"yer": f"a{i}", "liste": "gelisme", "metin": x["metin"]} for i, x in enumerate(t.get("gelisme") or [], 1)]
    return out


# -- girdiler ------------------------------------------------------------------------------------

def _clean_criterion_text(t: dict) -> str:
    """Doğrulanmış metin: `[komisyon]` cümleleri (kanıta değil komisyon bilgisine dayanır) çıkar,
    kanıt atıfları silinir (maddeler ölçüt koduna atıf yapar)."""
    out = []
    for p in t.get("paragraflar") or []:
        for s in T.split_sentences(p.get("metin") or ""):
            if T.KOMISYON in s:
                continue
            s = re.sub(r"\s*\[\d+_OD[1-5]\](?:\s*,\s*\[\d+_OD[1-5]\])*", "", s)
            s = re.sub(r"\s+([.,;:])", r"\1", s).strip()
            if s:
                out.append(s)
    return " ".join(out)


# Eksik PUKÖ halkasının sade karşılığı (gelişmeye açık yönün olgusu).
EKSIK_SADE = {"planla": "birimin bu konudaki tanımlı süreç ya da planını gösteren belge yok",
              "uygula": "birimin bu dönemdeki uygulamasını gösteren belge yok",
              "kontrol_et": "uygulamanın izlendiğini ya da sonuçlarının değerlendirildiğini gösteren belge yok",
              "onlem_al": "izleme sonuçlarına dayanan iyileştirmeyi gösteren belge yok",
              "ozgun": "birime özgü, örnek gösterilebilir uygulamayı gösteren belge yok"}


def unit_rows(rows: list[dict] | None) -> list[dict]:
    """Kanıt listesinde birime ait (kurum/fakülte geneli işareti taşımayan) satırlar. Eski dizinde
    `isaretler` sütunu yoksa bilinemez: boş."""
    return [r for r in rows or [] if "isaretler" in r and "kurum_geneli" not in (r.get("isaretler") or "")]


def findings(a: dict | None, has_evidence: bool, rows: list[dict] | None = None,
             metin: dict | None = None) -> list[str]:
    """Audit bulguları (gelişmeye açık yönün tek dayanağı), rapor okurunun dilinde: düzey, halka,
    "OD'ye sayılmadı", "eşleşti" gibi iç terim yok (kör test 2026-11-20: model bulguyu olduğu gibi
    maddeye kopyalıyordu). `rows`: ölçütün kanıt listesi satırları; birime ait belge varken "yalnız
    kurum geneli" denmez. Bir belgenin bu dönemin kanıtı neden sayılmadığı (dönem sonrası, tarihi
    görülmüyor) bulguya girmez: kanıt yönetimi notudur (gaps.md), gelişmeye açık yön bölümün eksiğini
    söyler (kör test 2026-11-20, Kimya A.1.5/B.1.6).
    `metin`: doğrulanmış ölçüt metninin anlattığı halkalar (`text_rings`). Audit zincirinde eksik
    sayılan halkayı metin anlatıyorsa "belge yok" bulgusu yazılmaz ya da eksik olan kısma daraltılır
    (kör test 2026-11-20: Mat C.3.1 izleme tablosu, Kimya D.2.1 raporlama, Kimya B.1.1 değerlendirme
    toplantısı → "izlendiğini gösteren belge yok")."""
    out = []
    if not has_evidence:
        out.append("bu dönemde ölçüte ilişkin kanıt bulunamadı")
    if not a:
        return out
    metin = metin or {}
    unit = unit_rows(rows)
    eksik = a.get("eksik") or []
    halkalar = {e.get("halka") for e in eksik}
    od = a.get("od")
    if od is not None and int(od) <= 2 and has_evidence and not eksik:
        out.append("birimin bu dönemdeki uygulamasını gösteren belge sınırlı" if int(od) == 2
                   else "birimin bu konudaki tanımlı süreç ya da planını gösteren belge sınırlı")
    for e in eksik:
        h = e.get("halka")
        if h == "kontrol_et" and (metin.get("degerlendirme") or metin.get("iyilestirme")):
            continue                       # metin sonuçların değerlendirildiğini anlatıyor
        if h == "kontrol_et" and metin.get("izleme"):
            out.append(IZLEME_DAR)
            continue
        if h == "onlem_al" and metin.get("iyilestirme"):
            continue                       # metin değerlendirmeye dayanan değişikliği anlatıyor
        out.append(EKSIK_SADE.get(h, f"{W.HALKA.get(h, h)} belgesi yok"))
    if a.get("kurum_geneli_yalniz"):
        if unit:
            out.append("dayanak çoğunlukla kurum geneli düzenleme"
                       + ("" if "uygula" in halkalar else "; birimin bu dönemdeki uygulamasını gösteren belge yok"))
        else:
            out.append("dayanak yalnız kurum geneli düzenleme; birimin kendi uygulamasını gösteren belge yok")
    return out


# Audit izleme halkasını eksik saysa da doğrulanmış metin izleme verisini (izleme tablosu, raporlama)
# anlatıyorsa eksik olan, sonuçların birimce değerlendirilmesidir.
IZLEME_DAR = "izleme verisi var; izleme sonuçlarının birimce değerlendirildiğini gösteren belge yok"

# -- doğrulanmış metnin anlattığı halkalar ----------------------------------------------------------
# Katlanmış (ascii, küçük harf) cümle desenleri. Yalnız düzenleme/plan dili ("… tanımlanmıştır",
# "yönergeye göre …", "izlenme sıklığı … belirlenmiştir") halka anlatımı sayılmaz.
PLAN_CUMLE = re.compile(r"(?:tanimlan|belirlen|duzenlen|ongorul|hukme baglan|belirtil|ifade edil|istenmis"
                        r"|esas alin|teslim eder|sunar\b|bildirir\b)\w*\W*$")
PLAN_BELGE = re.compile(r"\b(?:yonerge|yonetmeli|esaslar|is akis|rehber|kilavuz|usul)\w*")
TARIH_TAM = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-](?:19|20)\d\d\b")
METIN_IZLEME = re.compile(r"izleme (?:ve )?(?:degerlendirme )?tablo|izleme raporu|izlen(?:mis|mekte|di)\w*"
                          r"|takip edil(?:mis|mekte|di)\w*|raporlan(?:mis|makta|di)\w*|gerceklesme degeri"
                          r"|veri\w* (?:yer al|kaydedil|toplan)|veri\w* \w+ (?:kaydedil|toplan)\w*|\bkaydedilmis")
METIN_DEGERLENDIRME = re.compile(
    r"degerlendirme toplanti|(?<!ic )degerlendirme raporu|gozden gecir(?:mis|il|di)\w*"
    r"|(?:anket|geri bildirim|sonuc|gosterge|performans|veri)\w*(?: \w+){0,3} (?:degerlendiril|incelen|analiz edil)"
    r"(?:mis|mistir|mekte|di)\w*"
    r"|geri bildirim\w* (?:yer veril|alin|toplan)\w*|degerlendirme\w* (?:ve \w+ )?(?:\w+ )?geri bildirim\w* yer veril")
METIN_IYILESTIRME = re.compile(
    r"(?:degerlendirme|anket|geri bildirim|izleme|gorus|oneri)\w*[^.;]{0,120}?"
    r"(?:dogrultusunda|uzerine|sonucunda|dayanarak|alinan karar\w* ile)[^.;]{0,200}?"
    r"(?:guncellen|degistiril|artiril|arttiril|azaltil|kaldiril|acil|eklen|hazirlan|revize|iyilestiril)\w*")


def _plan_sentence(low: str) -> bool:
    """Düzenleme/plan dilinde cümle: yüklemi tanım/belirleme fiili ya da tarihsiz yönerge anlatımı."""
    return bool(PLAN_CUMLE.search(low) or (PLAN_BELGE.search(low) and not TARIH_TAM.search(low)))


def text_rings(text: str | None) -> dict:
    """Doğrulanmış ölçüt metninin anlattığı halkalar → {izleme, degerlendirme, iyilestirme: kısa alıntı
    ya da ""} (plan/düzenleme cümleleri sayılmaz)."""
    out = {"izleme": "", "degerlendirme": "", "iyilestirme": ""}
    for s in T.split_sentences(text or ""):
        low = _f(s)
        if _plan_sentence(low):
            continue
        for k, rx in (("izleme", METIN_IZLEME), ("degerlendirme", METIN_DEGERLENDIRME),
                      ("iyilestirme", METIN_IYILESTIRME)):
            if not out[k] and rx.search(low):
                out[k] = " ".join(s.split())[:140]
    return out


# -- kanıt durumu (çapraz denetim için olgular) -------------------------------------------------

_KISA = {"uygula": "U", "kontrol_et": "K", "onlem_al": "Ö"}


def facts(a: dict | None, rows: list[dict] | None, metin: dict | None = None) -> dict:
    """Ölçütün kanıt olguları: audit zincirinde kanıtlı halkalar, kanıt listesindeki birim kanıtı ve
    doğrulanmış metnin anlattığı halkalar (`metin_*`: kısa alıntı ya da "")."""
    a = a or {}
    metin = metin or {}
    z = a.get("zincir") if isinstance(a.get("zincir"), dict) else {}

    def var(x: str) -> bool:
        if x in z:
            return (z[x] or {}).get("durum") == "var"
        return f"{_KISA[x]}+" in (a.get("zincir_kisa") or "")
    unit = unit_rows(rows)
    return {"kanit": bool(rows), "uygulama": var("uygula"), "izleme": var("kontrol_et"),
            "iyilestirme": var("onlem_al"), "birim_kaniti": [r.get("ad") or r.get("doc_id") or "" for r in unit][:5],
            **{f"metin_{k}": metin.get(k) or "" for k in ("izleme", "degerlendirme", "iyilestirme")}}


HEDEF_BULGU = ("doğrulanmış metindeki göstergenin gerçekleşme değeri hedefin altında kalmış (değer, düzeyi ve "
               "dönemi metinde yazıldığı gibi verilir; fakülte/kurum geneli değer bölümün değeri sayılmaz)")
HEDEF_OK = re.compile(r"hedef\w* (?:ulasil|asil|karsilan|tuttur|gerceklestiril)|hedefin (?:uzerinde|ustunde)"
                      r"|hedef\w* (?:ustunde|uzerinde)")
HEDEF_ALTI = re.compile(r"hedefin (?:altinda|gerisinde)|hedef\w* (?:ulasilama|tutturulama|karsilanama|"
                        r"gerceklestirileme)|performans\w* %\s*0\b|%\s*0 (?:performans|gerceklesme)")


# Sayısal karşılaştırma: "hedeflenen değeri 1.08 … gerçekleşme değeri 0.36" (kör test 2026-11-20:
# değerler yan yana yazılıyor, "hedefin altında" denmiyordu). Yıl (2025) değer sayılmaz.
_SAYI = r"((?:\d+[.,])?\d+)(?![\d.,]*\d)"
_HEDEF_SAYI = re.compile(r"\bhedef\w*(?:\s+(?:edilen|olunan))?(?:\s+(?:deger\w*|olarak))?\s*(?:[:=]\s*)?" + _SAYI)
_GERCEK_SAYI = re.compile(r"\bgerceklesme\w*(?:\s+(?:deger\w*|orani\w*|olarak))?\s*(?:[:=]\s*)?" + _SAYI
                          + r"|\bgerceklesen\w*(?:\s+deger\w*)?\s*(?:[:=]\s*)?" + _SAYI)


def _num(x: str | None) -> float | None:
    if not x or re.fullmatch(r"(?:19|20)\d\d", x):
        return None
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def numeric_target(t: str) -> str | None:
    """Katlanmış metinde hedef ve gerçekleşme değerleri: hepsi hedefin altındaysa "alti", biri
    hedefe ulaşıyorsa "ok", karşılaştırılacak değer yoksa None."""
    hed = [v for m in _HEDEF_SAYI.finditer(t) if (v := _num(m.group(1))) is not None]
    ger = [v for m in _GERCEK_SAYI.finditer(t) if (v := _num(m.group(1) or m.group(2))) is not None]
    if not hed or not ger:
        return None
    return "ok" if max(ger) >= min(hed) else "alti"


def target_state(text: str | None) -> str | None:
    """Doğrulanmış metinde gösterge/hedef durumu: "ok" (hedefe ulaşıldı), "alti" (hedefin altında)
    ya da None (hedefle karşılaştırma yok). Söz ("hedefin altında") yoksa hedef ve gerçekleşme
    değerleri karşılaştırılır."""
    from bidr.identify.text import fold
    t = " ".join(fold(text or "").split())
    if HEDEF_ALTI.search(t):
        return "alti"
    if HEDEF_OK.search(t):
        return "ok"
    return numeric_target(t)


class Inputs:
    """Bir çalışma alanının alan düzeyi girdileri (salt okunur)."""

    def __init__(self, ws_root: Path, *, index: Path | None = None, audit: Path | None = None):
        from bidr.criteria.loader import load_criteria
        from bidr.render.kapsam import workspace_scope
        from bidr.verify import run as V
        self.ws = Workspace(Path(ws_root))
        sp = W.source_paths(self.ws.root, index=index, audit=audit)
        self.index_path = Path(sp["index"]) if sp["index"] else self.ws.root / S.INDEX
        self.audit_path = Path(sp["audit"]) if sp["audit"] else self.ws.root / S.AUDIT
        if not self.audit_path.exists():
            raise FileNotFoundError(f"{S.AUDIT} yok: {self.audit_path} (önce `bidr audit`)")
        self.index = S.load_index(self.index_path) if self.index_path.exists() else {}
        self.audit = S.load_audit(self.audit_path)
        self.cs = load_criteria()
        self.kapsam, self.uyarilar = workspace_scope(self.ws.root, self.cs)
        human = V.load_human(self.ws)
        self.verified: dict[str, dict] = {}
        for s in self.cs.sub_criteria:
            t = W.load_text(self.ws, s.id)
            if t and t.get("durum") == "dogrulandi" and not V.excluded(t, human):
                self.verified[s.id] = t

    def criteria(self, alan: str) -> list[str]:
        """Alanın birimce doldurulan alt ölçütleri (kapsam bolum | ortak)."""
        from bidr.render.kapsam import fills
        return [s.id for s in self.cs.sub_criteria if s.area == alan and fills(self.kapsam, s.id)]

    def od(self, c: str) -> int:
        return int((self.audit.get(c) or {}).get("od") or 1)

    def findings(self, c: str) -> list[str]:
        """Gelişmeye açık yönün dayanağı (BULGULAR satırı; yazar ve doğrulayıcı aynısını görür). Audit
        bulgularına, doğrulanmış metindeki göstergenin hedefin altında kalması eklenir: kod bunu güçlü
        yön saymaz (`hedef_alti_guclu`), doğrulayıcı da gelişmeye açık yön olarak ancak BULGULAR'da
        görürse kabul eder (kör test 2026-11-20: iki kural birbirini dışlıyordu)."""
        out = self.base_findings(c)
        if self.target(c) == "alti":
            out.append(HEDEF_BULGU)
        return out

    def base_findings(self, c: str) -> list[str]:
        return findings(self.audit.get(c), bool(self.index.get(c)), self.index.get(c), self.rings(c))

    def rings(self, c: str) -> dict:
        """Doğrulanmış metnin anlattığı halkalar (metin yoksa boş)."""
        return text_rings(_clean_criterion_text(self.verified[c])) if c in self.verified else {}

    def facts(self, c: str) -> dict:
        return facts(self.audit.get(c), self.index.get(c), self.rings(c))

    def target(self, c: str) -> str | None:
        return target_state(_clean_criterion_text(self.verified[c])) if c in self.verified else None

    def strong(self, alan: str) -> list[str]:
        return [c for c in self.criteria(alan) if c in self.verified]

    def weak(self, alan: str) -> list[str]:
        return [c for c in self.criteria(alan) if self.findings(c)]

    def girdi_sha(self, alan: str) -> str:
        # hedef bulgusu doğrulanmış metinden türer (metin özeti zaten girdide): taban bulgular yeter
        rows = [(c, W.text_sha(self.verified[c]) if c in self.verified else None, self.od(c), self.base_findings(c),
                 self.facts(c)) for c in self.criteria(alan)]
        return K.sha(json.dumps(rows, ensure_ascii=False))

    def render_criteria(self, cids: list[str]) -> str:
        blocks = []
        for c in cids:
            s = self.cs.get(c)
            a = self.audit.get(c) or {}
            L = [f"{c} {s.title}",
                 f"  Önerilen OD: {self.od(c)}" + (f" · PUKÖ zinciri: {a['zincir_kisa']}" if a.get("zincir_kisa") else "")]
            if c in self.verified:
                L.append(f"  DOĞRULANMIŞ METİN: «{_clean_criterion_text(self.verified[c])}»")
            else:
                L.append("  DOĞRULANMIŞ METİN: yok")
            f = self.findings(c)
            L.append("  BULGULAR: " + ("; ".join(f) if f else "yok"))
            o = self.facts(c)
            yn = lambda b: "var" if b else "yok"         # noqa: E731
            izl = ("var" if o["izleme"] else "metinde var (sonuçların değerlendirilmesi)"
                   if o["metin_degerlendirme"] or o["metin_iyilestirme"]
                   else "metinde izleme verisi var (birimce değerlendirme belgesi yok)" if o["metin_izleme"] else "yok")
            iyi = "var" if o["iyilestirme"] else "metinde var" if o["metin_iyilestirme"] else "yok"
            L.append(f"  KANIT DURUMU: uygulama {yn(o['uygulama'])}, izleme {izl}, "
                     f"iyileştirme {iyi}; listede birime ait kanıt "
                     + (f"var ({len(o['birim_kaniti'])})" if o["birim_kaniti"] else "yok"))
            if self.target(c) == "alti":
                L.append("  HEDEF: metindeki gösterge hedefin altında (güçlü yön olamaz)")
            blocks.append("\n".join(L))
        return "\n\n".join(blocks) if blocks else "yok"

    def alan_title(self, alan: str) -> str:
        try:
            return f"{alan} {self.cs.get(alan).title}"
        except KeyError:
            return alan


def write_inputs(src: Inputs, alan: str, hitap: str) -> tuple[dict, dict]:
    strong, weak = src.strong(alan), src.weak(alan)
    inputs = {"hitap": hitap, "alan": src.alan_title(alan), "olcutler": src.render_criteria(src.criteria(alan)),
              "guclu_olcutler": ", ".join(strong) or "yok (güçlü yön listesi boş kalır)",
              "gelisme_olcutler": ", ".join(weak) or "yok (gelişmeye açık yön listesi boş kalır)"}
    meta = {"alan": alan, "olcutler": src.criteria(alan), "guclu_olcutler": strong, "gelisme_olcutler": weak,
            "od": {c: src.od(c) for c in src.criteria(alan)}, "girdi_sha": src.girdi_sha(alan),
            "olgular": {c: src.facts(c) for c in src.criteria(alan)},
            "hedef": {c: src.target(c) for c in src.criteria(alan)}}
    return inputs, meta


# -- kod denetimi -------------------------------------------------------------------------------

def check_item(metin: str, *, liste: str, alan: str, allowed: set[str], od: dict[str, int]) -> list[dict]:
    """Tek maddenin kod denetimi → [{kod, ayrinti}] (write'taki yasak ifade/vaat/OD kuralları)."""
    issues: list[dict] = []
    codes = KOD.findall(metin)
    if T.ATIF.search(metin):
        issues.append({"kod": "kanit_atfi", "ayrinti": "kanıt numarası ([n_ODk]) yerine ölçüt kodu kullanılır: (B.1.1)"})
    for s in T.split_sentences(metin):
        if not KOD.search(s):
            issues.append({"kod": "olcutsuz", "ayrinti": f"cümlede ölçüt kodu yok: «{s[:80]}»"})
    for c in dict.fromkeys(codes):
        if not c.startswith(alan + "."):
            issues.append({"kod": "baska_alan", "ayrinti": f"({c}) bu alanın ({alan}) ölçütü değil"})
        elif c not in allowed:
            why = ("doğrulanmış metni yok (ya da birimin doldurduğu ölçüt değil)" if liste == "guclu"
                   else "audit bulgusu yok (ya da birimin doldurduğu ölçüt değil)")
            issues.append({"kod": "dayanaksiz_olcut", "ayrinti": f"({c}) {why}"})
    low = T.tr_lower(KOD.sub(" ", metin))
    issues += IC.sorunlar(KOD.sub(" ", metin))
    for rx, kind in T._YASAK:
        m = rx.search(low)
        if m:
            issues.append({"kod": "yasak_ifade", "ayrinti": f"{kind}: “{m.group(0)}”"})
    for rx in (T.GELECEK, re.compile(r"\böneril\w*|\bgerekmektedir\b|\bgereklidir\b|\bihtiyaç duyulmaktadır\b")):
        m = rx.search(low)
        if m:
            issues.append({"kod": "gelecek_vaat" if rx is T.GELECEK else "yasak_ifade",
                           "ayrinti": f"“{m.group(0).strip()}”: öğüt/vaat dili; eksik olgu olarak yazılır"})
    cited = [od.get(c, 1) for c in codes if c in allowed]
    cap, top = (min(cited), max(cited)) if cited else (1, 0)
    for m in T.OD_ANIS.finditer(low):
        issues.append({"kod": "od_anisi", "ayrinti": f"“{m.group(0)}”: düzey anılmaz"})
    if not T.OLUMSUZ.search(low):
        for lvl, rx in T.UST_DUZEY.items():
            m = rx.search(low)
            if m and cap < lvl:
                issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” OD{lvl} dili; ölçüt OD{cap}"})
        m = T.FIIL_K.search(low)
        if m and top < 4:
            issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” izleme/iyileştirme iddiası OD4+ ölçüt ister"})
        m = T.FIIL_Z.search(low)
        if m and top < 5:
            issues.append({"kod": "od_asimi", "ayrinti": f"“{m.group(0)}” özgünlük iddiası OD5 ölçüt ister"})
    return issues


# -- kanıtla çapraz denetim -----------------------------------------------------------------------
# Katlanmış (ascii, küçük harf) cümle desenleri. Gelişmeye açık yön bir eksikliği söyler; söylediği
# eksiklik audit zinciri ve kanıt listesiyle çelişmemeli. "OD'ye sayılmadı / doğrulanmalı" gibi
# nedenli hüküm çelişki değildir (kanıt var ama sayılmadı).
YOK = re.compile(r"bulunmamak|bulunmadig|yer almamak|yer almadig|yoktur|bulunamam|eksik|gorulmemekte"
                 r"|gosterilmemis|sinirli kal|ulasilamam|ortaya konmamis|kanitlanmamis")
NEDENLI = re.compile(r"\bsayil|dogrulanama|dogrulanmali|donem disi|donem sonrasi|onceki yil|tarih\w* (?:belirsiz|dogrulan)"
                     r"|belgede (?:gorulme|acik degil)|kaniti olarak gosterilemi")
H_IZLEME = re.compile(r"izlen|izleme|olcme|olcum|olculme|degerlendirme sonuc|sonuclarin\w* (?:degerlendir|izlen)")
H_IYILESTIRME = re.compile(r"iyilestir|eylem plani|duzeltici|onleyici|sonuclara dayanan (?:degisiklik|karar)")
H_BIRIM = re.compile(r"bolum(?:un|umuzun)? (?:duzeyinde|donem icindeki|kendi|tarafindan)|bolumun\b[^.]*uygulama"
                     r"|birim(?:in)? (?:duzeyinde|uygulama)|yalniz(?:ca)? kurum|kurum(?: geneli)? duzeyinde"
                     r"|kurum geneli\w*(?: \w+){0,2} (?:ile|yle) sinirli|kurum geneli duzenleme\w*le eslesmekte")
H_UYGULAMA = re.compile(r"uygulama(?:sina|ya|larina)? (?:iliskin |dair )?(?:\w+ )?kanit|uygulama kanit|uygulandig")
YALNIZ_KURUM = re.compile(r"yalniz(?:ca)? kurum|kurum geneli\w*(?: \w+){0,2} (?:ile|yle) sinirli")
H_HIC = re.compile(r"(?:bu donemde |olcute iliskin |hicbir )?kanit bulunama|kanit(?:i)? (?:yoktur|bulunmamaktadir)")
# güçlü yönde birimin bir uygulamayı yaptığını/kaydettiğini söyleyen fiil (yalnız "tanımlanmıştır",
# "hazırlanmıştır" gibi plan dili değil; "izlenmesi" gibi ad biçimleri değil)
UYGULAMA_FIIL = re.compile(r"(?:yurutul|gerceklestiril|yapil|kaydedil|karara baglan|gorusul|degerlendiril|uygulan"
                           r"|kabul edil|akredite edil|gorevlendiril|ilan edil|yayimlan|izlen|toplan|iletil"
                           r"|surdurul|acil|alin|katil)(?:mis|mak|mek|di|ir)\w*"
                           r"|\bbulunmaktadir|\byer almaktadir|\byer almakta\b")
# güçlü yönde gösterge/performans değeri iddiası
PERF = re.compile(r"gosterge|performans|hedef|gerceklesme|yayin (?:sayisi|degeri)")
DEGER = re.compile(r"\bdeger(?:i|leri)?\b|\boran(?:i|lari)?\b|\bsayisi\b|\bortalama"
                   r"|(?<![\d.\-])(?!(?:19|20)\d\d\b)\d+(?:[.,]\d+)?(?![\d\-])")
# hedefin altında kalan göstergenin izleme verisini anan güçlü yön ("tabloda Kimya verisi yer almaktadır")
VERI = re.compile(r"\bveri\w*|\btablo\w*|\bizleme\b|\byayin\w*")
# fakülte/kurum geneli değer (bölümün değeri varken fakülte değeri verilmesin)
UST_BIRIM = re.compile(r"\bfakulte(?!\w* (?:yonetim )?kurul)\w*|\btbf\b|universite genel\w*|kurum genel\w*")
TARIH = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
BOLUM_DEGER = re.compile(r"\bbolum\w*[^.;]{0,60}?\d|\d[^.;]{0,40}?\bbolum\w*")
SAYI = re.compile(r"(?<![\d.\-])(?!(?:19|20)\d\d\b)\d+(?:[.,]\d+)?(?![\d\-])")
# izleme sözcüğü iyileştirmenin niteleyicisi ("izleme sonuçlarına dayanan iyileştirme") ise izleme hükmü değil
NITELEYICI = re.compile(r"^\W*(?:\w+\W+){0,3}?(?:dayan|dayali|dogrultusunda|uzerine)")
# Daraltılmış izleme hükmü: izleme verisi var, eksik olan sonuçların birimce değerlendirilmesi
# ("izleme sonuçlarının bölümce değerlendirildiğini gösteren belge yok") — metin izleme verisini
# anlatsa da çelişki değildir (bulgu `IZLEME_DAR`).
DAR = re.compile(r"(?:izleme|izlenen)\w* (?:veri|sonuc)\w*[^.;]{0,80}?(?:birimce|bolumce|bolum tarafindan"
                 r"|birim tarafindan|bolumun kendi|birimin kendi)|sonuc\w* (?:birimce|bolumce|bolum tarafindan)")
# Var olanı kabul edip eksiği söyleyen cümle ("geri bildirimler dışında …", "izlenmekle birlikte …"):
# kabul kısmı bir izleme/değerlendirme/iyileştirme olgusu anıyorsa yokluk hükmü daraltılmıştır.
KABUL = re.compile(r"\b(?:disinda|birlikte|ragmen|karsin)\b")
KABUL_OLGU = re.compile(r"izle|takip|rapor|tablo|geri bildirim|anket|degerlendir|gozden gecir|iyilestir|guncellen")


def _f(s: str) -> str:
    from bidr.identify.text import fold
    return " ".join(fold(s or "").split())


def _claims(sentence: str) -> set[str]:
    """Gelişmeye açık cümlenin "yok" hükümleri: izleme | iyilestirme | birim | uygulama | hic."""
    low = _f(sentence)
    if not YOK.search(low) or NEDENLI.search(low):
        return set()
    out = set()
    for m in H_IZLEME.finditer(low):
        if not (H_IYILESTIRME.search(low) and NITELEYICI.search(low[m.end():m.end() + 60])):
            out.add("izleme")
            break
    if H_IYILESTIRME.search(low):
        out.add("iyilestirme")
    if H_BIRIM.search(low):
        out.add("birim")
    if H_UYGULAMA.search(low):
        out.add("uygulama")
    if not out and H_HIC.search(low):
        out.add("hic")
    return out


def _acknowledged(low: str) -> bool:
    m = KABUL.search(low)
    return bool(m and KABUL_OLGU.search(low[:m.start()]))


def cross_check(t: dict, meta: dict) -> list[dict]:
    """Maddelerin kanıt olgularıyla ve birbiriyle çelişkisi → [{yer, metin, kod, ayrinti}].
    `meta["olgular"]` yoksa (eski paket) yalnız iç çelişki denetlenir."""
    olg = meta.get("olgular") or {}
    hedef = meta.get("hedef") or {}
    out: list[dict] = []
    rows = items(t)
    practice: dict[str, list[str]] = {}
    review: dict[str, list[str]] = {}         # güçlü yönde sonuçların değerlendirilmesi / buna dayanan değişiklik
    for r in rows:
        if r["liste"] != "guclu":
            continue
        for s in T.split_sentences(r["metin"]):
            low = _f(KOD.sub(" ", s))
            for c in KOD.findall(s):
                if UYGULAMA_FIIL.search(low):
                    practice.setdefault(c, []).append(r["yer"])
                if not _plan_sentence(low) and (METIN_DEGERLENDIRME.search(low) or METIN_IYILESTIRME.search(low)):
                    review.setdefault(c, []).append(r["yer"])
                if ((PERF.search(low) and DEGER.search(low) and hedef.get(c) != "ok")
                        or (hedef.get(c) == "alti" and (PERF.search(low) or VERI.search(low)))):
                    why = ("metindeki gösterge hedefin altında" if hedef.get(c) == "alti"
                           else "metin hedefe ulaşıldığını göstermiyor")
                    out.append({"yer": r["yer"], "metin": r["metin"], "kod": "hedef_alti_guclu",
                                "ayrinti": f"({c}) gösterge/performans değeri ya da izleme verisi güçlü yön "
                                           f"değildir: {why}"})
    for r in rows:
        for s in T.split_sentences(r["metin"]):
            low = TARIH.sub(" ", _f(KOD.sub(" ", s)))
            if UST_BIRIM.search(low) and PERF.search(low) and SAYI.search(low) and not BOLUM_DEGER.search(low):
                out.append({"yer": r["yer"], "metin": r["metin"], "kod": "fakulte_degeri",
                            "ayrinti": "fakülte/kurum geneli değer bölümün değeri gibi verilmez: bölümün kendi değeri "
                                       "yazılır (metinde yoksa değer maddeye konmaz)"})
                break
    for r in rows:
        if r["liste"] != "gelisme":
            continue
        for s in T.split_sentences(r["metin"]):
            cl = _claims(KOD.sub(" ", s))
            if not cl:
                continue
            low = _f(KOD.sub(" ", s))
            ack = _acknowledged(low)
            dar = bool(DAR.search(low))
            for c in dict.fromkeys(KOD.findall(s)):
                o = olg.get(c) or {}
                bad = []
                if "izleme" in cl and o.get("izleme"):
                    bad.append("izleme kanıtlı")
                elif "izleme" in cl and not ack:
                    # audit zinciri izlemeyi eksik saysa da doğrulanmış metin anlatıyor olabilir
                    # (kör test 2026-11-20: Mat C.3.1 izleme tablosu, Kimya D.2.1, B.1.1)
                    if o.get("metin_degerlendirme") or o.get("metin_iyilestirme"):
                        bad.append("ölçütün doğrulanmış metni sonuçların değerlendirildiğini anlatıyor: «"
                                   + (o.get("metin_degerlendirme") or o.get("metin_iyilestirme"))[:100] + "…»")
                    elif o.get("metin_izleme") and not dar:
                        bad.append("ölçütün doğrulanmış metni izleme verisini anlatıyor: «" + o["metin_izleme"][:100]
                                   + "…»; yokluk değil eksik olan yazılır (izleme sonuçlarının birimce "
                                     "değerlendirildiğini gösteren belge yok)")
                if "iyilestirme" in cl and o.get("iyilestirme"):
                    bad.append("iyileştirme kanıtlı")
                elif "iyilestirme" in cl and not ack and o.get("metin_iyilestirme"):
                    bad.append("ölçütün doğrulanmış metni değerlendirmeye dayanan değişikliği anlatıyor: «"
                               + o["metin_iyilestirme"][:100] + "…»")
                if ({"birim", "uygulama"} & cl) and o.get("uygulama"):
                    bad.append("uygulama halkası kanıtlı")
                elif "birim" in cl and o.get("birim_kaniti") and (YALNIZ_KURUM.search(low) or "uygula" not in low):
                    # "bölümün bu dönemdeki uygulamasını gösteren belge yok" BULGULAR satırının kendisidir
                    # (uygulama halkası yok; birime ait kanıt izleme/plan olabilir): çelişki değil. Genel
                    # "bölüm düzeyinde kanıt yok" ya da "yalnız kurum geneli" hükmü birim kanıtıyla çelişir.
                    bad.append("kanıt listesinde birime ait kanıt var (" + "; ".join(o["birim_kaniti"][:2])
                               + "): \"yalnız kurum geneli\" / \"bölüm düzeyinde kanıt yok\" denmez; eksik olgu "
                                 "yazılır (\"dayanak çoğunlukla kurum geneli; bölümün bu dönemdeki uygulamasını "
                                 "gösteren belge bulunmamaktadır\"), belgenin neden sayılmadığı yazılmaz")
                if "hic" in cl and o.get("kanit"):
                    bad.append("ölçütün kanıt listesi boş değil")
                for b in bad:
                    out.append({"yer": r["yer"], "metin": r["metin"], "kod": "kanitla_celiski",
                                "ayrinti": f"({c}) \"yok\" hükmü kanıtla çelişiyor: {b}"})
                if ({"birim", "uygulama", "hic"} & cl) and practice.get(c):
                    out.append({"yer": r["yer"], "metin": r["metin"], "kod": "ic_celiski",
                                "ayrinti": f"({c}) güçlü yön ({', '.join(practice[c])}) bu ölçütte birimin "
                                           "uygulamasını söylüyor; gelişmeye açık yön onu yok sayamaz"})
                elif ({"izleme", "iyilestirme"} & cl) and review.get(c) and not ack and not dar:
                    out.append({"yer": r["yer"], "metin": r["metin"], "kod": "ic_celiski",
                                "ayrinti": f"({c}) güçlü yön ({', '.join(review[c])}) bu ölçütte sonuçların "
                                           "değerlendirildiğini/buna dayanan değişikliği söylüyor; gelişmeye açık yön "
                                           "onu yok sayamaz"})
    return out


def tutarlilik(t: dict) -> list[dict]:
    """Basit tutarlılık uyarısı (kör denetim 2026-11-24): aynı ölçüt kodu hem bir güçlü yön maddesinde
    hem yokluk hükmü kuran ("bulunmamaktadır", "yer almamaktadır", "eksik" …) bir gelişmeye açık yön
    maddesinde geçiyorsa → [{olcut, guclu: [yer], gelisme: yer, metin}]. Engel değildir (eksik halkayı
    adıyla söyleyen madde doğrudur); `cross_check`'in `ic_celiski`'si dar kalıplara bakar, bu uyarı
    geniş: yonler_tamam uyarı olarak gösterir, doğrulama paketine "DİKKAT" satırı olarak girer."""
    strong: dict[str, list[str]] = {}
    rows = items(t)
    for r in rows:
        if r["liste"] == "guclu":
            for c in dict.fromkeys(KOD.findall(r["metin"])):
                strong.setdefault(c, []).append(r["yer"])
    out = []
    for r in rows:
        if r["liste"] != "gelisme":
            continue
        for s in T.split_sentences(r["metin"]):
            low = _f(KOD.sub(" ", s))
            if not YOK.search(low) or NEDENLI.search(low):
                continue
            for c in dict.fromkeys(KOD.findall(s)):
                if c in strong and not any(x["olcut"] == c and x["gelisme"] == r["yer"] for x in out):
                    out.append({"olcut": c, "guclu": strong[c], "gelisme": r["yer"], "metin": s})
    return out


def tutarlilik_satirlari(t: dict) -> list[str]:
    return [f"{x['olcut']}: güçlü yön ({', '.join(x['guclu'])}) ile gelişmeye açık yön ({x['gelisme']}) aynı "
            "ölçütte; gelişmeye açık madde yokluk hükmü kuruyor, güçlü yönle ya da ölçüt metniyle çelişmediğini "
            "denetleyin" for x in tutarlilik(t)]


def check(t: dict, meta: dict) -> list[dict]:
    """Bütün maddelerin denetimi → [{yer, metin, kod, ayrinti}]."""
    out = []
    allowed = {"guclu": set(meta["guclu_olcutler"]), "gelisme": set(meta["gelisme_olcutler"])}
    for r in items(t):
        for x in check_item(r["metin"], liste=r["liste"], alan=meta["alan"], allowed=allowed[r["liste"]],
                            od=meta.get("od") or {}):
            out.append({"yer": r["yer"], "metin": r["metin"], **x})
    return out + cross_check(t, meta)


# -- prepare / apply -------------------------------------------------------------------------------

def _limit(ws: Workspace) -> int:
    return W.rewrite_limit(ws.root)


def rejection_section(t: dict, rec: dict | None, tur: int, limit: int) -> str:
    rec = rec or {}
    L = [f"DOĞRULAMADA REDDEDİLDİ — YENİDEN YAZIM (tur {tur}/{limit})",
         "Bu alan için daha önce yazılan maddeler bağımsız doğrulamada reddedildi. Maddeleri yukarıdaki "
         "kurallarla ve yalnız ALT ÖLÇÜTLER bölümüne dayanarak yeniden yaz: desteklenmeyen maddeyi metnin/bulgunun "
         "gösterdiği kadarına indir ya da çıkar; yeni iddia ekleme.", ""]
    rows = [r for r in rec.get("maddeler") or [] if r.get("karar") != "destekleniyor"]
    if rows:
        L.append("Doğrulayıcının desteklemediği maddeler (yer, karar, gerekçe):")
        L += [f"- {r['yer']} ({r['karar']}): «{r.get('metin', '')}» — {r.get('gerekce', '')}" for r in rows]
    for i in rec.get("kod_denetimi") or []:
        L.append(f"- {i.get('yer', '-')} {i.get('kod', '')}: {i.get('ayrinti', '')}")
    L += ["", "REDDEDİLEN MADDELER (yalnız düzeltme için; dayanak değildir)", "<<<"]
    L += [f"{r['yer']}: {r['metin']}" for r in items(t)]
    L.append(">>>")
    return "\n".join(L)


def rejected(ws: Workspace, log: dict | None = None) -> dict[str, dict]:
    log = load_log(ws) if log is None else log
    return {a: t for a, t in load_all(ws).items()
            if t.get("durum") == "reddedildi" and (r := log.get(a)) and r.get("durum") == "reddedildi"
            and r.get("metin_sha") == text_sha(t)}


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False, rejected_only: bool = False,
            hitap: str | None = None, backend: W.Backend | None = None, index=None, audit=None) -> dict:
    backend = backend or W.Backend()
    src = Inputs(ws_root, index=index, audit=audit)
    ws = src.ws
    _, profile = S.unit_name(ws.root)
    h = W.hitap_for(profile, hitap)
    d = work_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    log = load_log(ws)
    rej = rejected(ws, log)
    lim = _limit(ws)
    st = {"paket": 0, "yeni": 0, "zaten_tamam": 0, "bos_alan": [], "insan_gerekli": [], "tur": {},
          "uyarilar": list(src.uyarilar)}
    for alan in only or ALANLAR:
        if alan not in ALANLAR:
            raise KeyError(f"bilinmeyen alan: {alan} ({', '.join(ALANLAR)})")
        if not src.criteria(alan):
            st["bos_alan"].append(alan)
            continue
        inputs, meta = write_inputs(src, alan, h)
        r = backend.render_task(TASK, inputs)
        t = load(ws, alan)
        cur = t and t.get("girdi_sha") == meta["girdi_sha"]
        from bidr.kor import run as KD          # kör denetimin bekleyen düzeltme notu (bidr/kor/run.py)
        dz_sec, dz = KD.duzeltme(ws, f"{KD.YON}{alan}", t)
        if dz:
            meta["duzeltme"] = dz
        if rejected_only:
            if alan not in rej or not cur:
                continue
            tur = int(t.get("tur") or 0)
            if tur >= lim:
                st["insan_gerekli"].append(alan)
                continue
            base = K.sha(r["prompt"])
            r = {**r, "prompt": r["prompt"] + "\n\n" + rejection_section(t, log.get(alan), tur + 1, lim)}
            meta.update({"tur": tur + 1, "temel_istem_sha": base})
            st["tur"][alan] = tur + 1
        else:
            kay = (t or {}).get("kaynak") or {}
            if (cur and not redo and not dz_sec
                    and (kay.get("temel_istem_sha") or kay.get("istem_sha")) == K.sha(r["prompt"])
                    and str(kay.get("gorev_surumu")) == str(r["version"])):
                st["zaten_tamam"] += 1
                continue
            # kör denetim düzeltmesi kendi sayacıyla başlar (bidr/write/run.py prepare ile aynı)
            meta.update({"tur": int((t or {}).get("tur") or 0) if cur and not dz_sec else 0,
                         "temel_istem_sha": K.sha(r["prompt"])})
        if dz_sec:
            r = {**r, "prompt": r["prompt"] + "\n\n" + dz_sec}
            st.setdefault("duzeltme", []).append(alan)
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, alan, r, meta, force=bool(redo and t))
    st["bekleyen"] = K.write_readme(d, task=TASK, version=W.task_version(TASK), cmd="yonler", rule=RULE,
                                    pattern=K.ALAN_KEY, key="alan")
    st["klasor"] = str(d)
    return st


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend: W.Backend | None = None,
          index=None, audit=None) -> dict:
    backend = backend or W.Backend()
    src = Inputs(ws_root, index=index, audit=audit)
    ws = src.ws
    d = work_dir(ws)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "eski": []}
    version = W.task_version(TASK)
    for p in K.pkg_paths(d, K.ALAN_KEY) if d.exists() else []:
        pkg = json.loads(p.read_text(encoding="utf-8"))
        alan, meta = pkg["olcut"], pkg["meta"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(alan)
            continue
        if str(pkg["surum"]) != version or src.girdi_sha(alan) != meta["girdi_sha"]:
            st["eski"].append(alan)
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = backend.validate_output(TASK, raw)
        if out is None:
            st["gecersiz"][alan] = errs[:5]
            continue
        rec = {"alan": alan, "baslik": src.alan_title(alan), "durum": "taslak", "tur": int(meta.get("tur") or 0),
               "girdi_sha": meta["girdi_sha"],
               "guclu": [{"metin": " ".join(x["metin"].split()), "olcutler": sorted(set(KOD.findall(x["metin"])))}
                         for x in out["guclu"]],
               "gelisme": [{"metin": " ".join(x["metin"].split()), "olcutler": sorted(set(KOD.findall(x["metin"])))}
                           for x in out["gelisme"]],
               "kaynak": {"model": model, "gorev_surumu": str(pkg["surum"]), "istem_sha": pkg["istem_sha"],
                          "temel_istem_sha": meta.get("temel_istem_sha") or pkg["istem_sha"],
                          "cevap_sha": K.sha(raw), "zaman": K.now()},
               **({"duzeltme": meta["duzeltme"]} if meta.get("duzeltme") else {})}
        issues = check(rec, meta)
        if issues:
            st["gecersiz"][alan] = [f"{i['yer']} {i['kod']}: {i['ayrinti']}" for i in issues]
            continue
        old = load(ws, alan)
        if old and text_sha(old) == text_sha(rec) and (old.get("kaynak") or {}).get("istem_sha") == pkg["istem_sha"]:
            st["degismedi"] += 1
            continue
        save(ws, rec)
        st["islenen"] += 1
    K.write_invalid(d, TASK, st["gecersiz"])
    return st


# -- bağımsız doğrulama (bidr verify prepare|apply içinden) ---------------------------------------------

def _set_status(ws: Workspace, t: dict, durum: str, gerekce: list[str], model: str | None) -> None:
    t = dict(t)
    t["durum"] = durum
    t["dogrulama"] = {"kayit": LOG, "model": model, "gerekce": gerekce, "zaman": K.now()}
    save(ws, t)


def _meta_for(src: Inputs, alan: str) -> dict:
    return {"alan": alan, "guclu_olcutler": src.strong(alan), "gelisme_olcutler": src.weak(alan),
            "od": {c: src.od(c) for c in src.criteria(alan)},
            "olgular": {c: src.facts(c) for c in src.criteria(alan)},
            "hedef": {c: src.target(c) for c in src.criteria(alan)}}


def verify_prepare(ws_root: Path, *, redo: bool = False, backend: W.Backend | None = None) -> dict:
    """Güncel (girdisi değişmemiş) her alan metni: kod denetimi, geçen için doğrulama paketi."""
    backend = backend or W.Backend()
    st = {"paket": 0, "yeni": 0, "zaten_tamam": 0, "kod_reddi": {}, "metin": 0, "eski_metin": []}
    ws = Workspace(Path(ws_root))
    texts = load_all(ws)
    if not texts:
        return st
    src = Inputs(ws_root)
    log = load_log(ws)
    d = verify_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    for alan, t in texts.items():
        if t.get("girdi_sha") != src.girdi_sha(alan):
            st["eski_metin"].append(alan)      # girdisi değişti: önce `bidr yonler prepare`
            continue
        st["metin"] += 1
        sha = text_sha(t)
        prev = log.get(alan)
        if (not redo and prev and prev.get("metin_sha") == sha and prev.get("durum") in FINAL
                and t.get("durum") == prev["durum"]):
            st["zaten_tamam"] += 1
            continue
        meta = _meta_for(src, alan)
        issues = check(t, meta)
        rows = items(t)
        if issues or not rows:
            durum = "reddedildi" if issues else "dogrulandi"
            why = [f"{i['yer']} {i['kod']}: {i['ayrinti']}" for i in issues]
            log[alan] = {"alan": alan, "durum": durum, "metin_sha": sha, "asama": "kod", "tur": int(t.get("tur") or 0),
                         "kod_denetimi": issues, "maddeler": [], "gerekce": why, "model": None, "zaman": K.now()}
            _set_status(ws, t, durum, why, None)
            for f in (d / f"{alan}.json", d / f"{alan}.out.json"):
                if f.exists():
                    f.replace(f.with_name(f.name + ".eski"))
            if issues:
                st["kod_reddi"][alan] = why
            continue
        cited = sorted({c for r in rows for c in KOD.findall(r["metin"]) if c in src.criteria(alan)},
                       key=lambda x: [int(n) for n in x.split(".")[1:]])
        maddeler = "\n".join(f"{r['yer']}: {r['metin']}" for r in rows)
        dikkat = tutarlilik(t)
        if dikkat:      # kodun basit tutarlılık uyarısı: doğrulayıcı kural 5'e göre bakar (karar onun)
            maddeler += "\n\nDİKKAT (kod uyarısı; karar senin): " + "; ".join(
                f"{x['gelisme']} ile {', '.join(x['guclu'])} aynı ölçüte ({x['olcut']}) atıf yapıyor ve {x['gelisme']} "
                "yokluk hükmü kuruyor — kural 4 ve 5'e göre çelişip çelişmediğine bak" for x in dikkat)
        inputs = {"alan": src.alan_title(alan), "maddeler": maddeler, "olcutler": src.render_criteria(cited)}
        vmeta = {"alan": alan, "metin_sha": sha, "maddeler": [{"yer": r["yer"], "metin": r["metin"]} for r in rows]}
        r = backend.render_task(VTASK, inputs)
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, alan, r, vmeta, force=redo)
        if t.get("durum") in FINAL:
            _set_status(ws, t, "taslak", [], None)
    save_log(ws, log)
    st["bekleyen"] = K.write_readme(d, task=VTASK, version=W.task_version(VTASK), cmd="verify", rule=VRULE,
                                    pattern=K.ALAN_KEY, key="alan")
    st["klasor"] = str(d)
    return st


def judge(meta: dict, out: dict) -> tuple[str | None, list[dict], list[str]]:
    want = [m["yer"] for m in meta["maddeler"]]
    got: dict[str, dict] = {}
    errs = []
    for x in out.get("maddeler") or []:
        if x["yer"] in got:
            errs.append(f"{x['yer']}: birden çok karar")
        elif x["yer"] not in want:
            errs.append(f"{x['yer']}: böyle bir madde yok")
        got[x["yer"]] = x
    miss = [y for y in want if y not in got]
    if miss:
        errs.append(f"kararı olmayan madde: {', '.join(miss)}")
    if errs:
        return None, [], errs
    rows = [{**m, "karar": got[m["yer"]]["karar"], "gerekce": got[m["yer"]]["gerekce"]} for m in meta["maddeler"]]
    return ("reddedildi" if any(r["karar"] != "destekleniyor" for r in rows) else "dogrulandi"), rows, []


def verify_apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend: W.Backend | None = None) -> dict:
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    d = verify_dir(ws)
    st = {"dogrulandi": [], "reddedildi": {}, "bekleyen": [], "gecersiz": {}, "eski": [], "degismedi": 0}
    if not d.exists():
        return st
    log = load_log(ws)
    version = W.task_version(VTASK)
    for p in K.pkg_paths(d, K.ALAN_KEY):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        alan, meta = pkg["olcut"], pkg["meta"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(alan)
            continue
        t = load(ws, alan)
        if str(pkg["surum"]) != version or not t or text_sha(t) != meta["metin_sha"]:
            st["eski"].append(alan)
            continue
        raw = outp.read_text(encoding="utf-8")
        csha = K.sha(raw)
        prev = log.get(alan)
        if (prev and prev.get("cevap_sha") == csha and prev.get("metin_sha") == meta["metin_sha"]
                and t.get("durum") == prev.get("durum")):
            st["degismedi"] += 1
            continue
        out, errs = backend.validate_output(VTASK, raw)
        if out is None:
            st["gecersiz"][alan] = errs[:5]
            continue
        durum, rows, errs = judge(meta, out)
        if durum is None:
            st["gecersiz"][alan] = errs
            continue
        why = [f"{r['yer']} ({r['karar']}): {r['gerekce']} — «{r['metin']}»" for r in rows
               if r["karar"] != "destekleniyor"]
        log[alan] = {"alan": alan, "durum": durum, "metin_sha": meta["metin_sha"], "asama": "model",
                     "tur": int(t.get("tur") or 0), "kod_denetimi": [], "maddeler": rows,
                     "genel": out.get("genel", ""), "gerekce": why, "model": model,
                     "gorev_surumu": str(pkg["surum"]), "istem_sha": pkg["istem_sha"], "cevap_sha": csha,
                     "zaman": K.now()}
        _set_status(ws, t, durum, why, model)
        if durum == "dogrulandi":
            st["dogrulandi"].append(alan)
        else:
            st["reddedildi"][alan] = why
    save_log(ws, log)
    K.write_invalid(d, VTASK, st["gecersiz"])
    return st


def verify_pending(ws: Workspace) -> dict:
    """verify aşaması için: güncel ama doğrulama kaydı oturmamış alan metinleri.
    {bekleyen: set, paketli: set (güncel paketi var), cevapsiz: set, gecersiz: set}."""
    out = {"bekleyen": set(), "paketli": set(), "cevapsiz": set(), "gecersiz": set()}
    texts = load_all(ws)
    if not texts:
        return out
    try:
        src = Inputs(ws.root)
    except FileNotFoundError:
        return out
    log = load_log(ws)
    for a, t in texts.items():
        if t.get("girdi_sha") != src.girdi_sha(a):
            continue
        r = log.get(a)
        if not (r and r.get("metin_sha") == text_sha(t) and r.get("durum") in FINAL and t.get("durum") == r["durum"]):
            out["bekleyen"].add(a)
    if not out["bekleyen"]:
        return out
    d = verify_dir(ws)
    from bidr.pipeline.checks import _invalid_keys
    for a in out["bekleyen"]:
        pp = d / f"{a}.json"
        try:
            x = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None
        except (OSError, ValueError):
            x = None
        if x and (x.get("meta") or {}).get("metin_sha") == text_sha(texts[a]) \
                and str(x.get("surum")) == W.task_version(VTASK):
            out["paketli"].add(a)
            if not (d / f"{a}.out.json").exists():
                out["cevapsiz"].add(a)
    out["gecersiz"] = _invalid_keys(d / "GECERSIZ.md", r"^- `([A-E])\.json`") & out["paketli"]
    return out
