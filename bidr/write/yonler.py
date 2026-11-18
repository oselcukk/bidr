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
bidr/write/text.py'deki kurallar). Geçen cevap `yonler/<alan>.json`, `durum: taslak`.

Bağımsız doğrulama `bidr verify prepare|apply` akışına katılır (`work/verify/yonler/`,
görev `verify_yonler`, kayıt `verify-yonler.jsonl`): her madde atıf yaptığı ölçütün metni ya
da bulgusuyla karşılaştırılır; hepsi "destekleniyor" ise `dogrulandi`. Reddedilen alan
`bidr yonler prepare --reddedilenler` ile gerekçeli yeniden yazıma gider (sınır
`rapor.yeniden_yazim_siniri`); sınırdan sonra hücreler şablon yönergesiyle kalır ve rapor
TASLAK damgalı olur.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl

from . import packages as K
from . import run as W
from . import sources as S
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
        "güçlü yön yalnız doğrulanmış metinden, gelişmeye açık yön yalnız bulgudan; öğüt ve vaat yok.")
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


def findings(a: dict | None, has_evidence: bool) -> list[str]:
    """Audit bulguları (gelişmeye açık yönün tek dayanağı)."""
    out = []
    if not has_evidence:
        out.append("bu dönemde ölçüte ilişkin kanıt bulunamadı")
    if not a:
        return out
    od = a.get("od")
    if od is not None and int(od) <= 2 and has_evidence:
        out.append(f"önerilen OD{od} (düşük olgunluk düzeyi)")
    for e in a.get("eksik") or []:
        out.append(f"OD{a.get('sonraki_od')} için {W.HALKA.get(e.get('halka'), e.get('halka'))} kanıtı eksik"
                   + (f": {e['gereken']}" if e.get("gereken") else ""))
    if a.get("kurum_geneli_yalniz"):
        out.append("yalnız kurum geneli düzenlemeyle eşleşti; birimin uygulama kanıtı eksik")
    return out


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
        return findings(self.audit.get(c), bool(self.index.get(c)))

    def strong(self, alan: str) -> list[str]:
        return [c for c in self.criteria(alan) if c in self.verified]

    def weak(self, alan: str) -> list[str]:
        return [c for c in self.criteria(alan) if self.findings(c)]

    def girdi_sha(self, alan: str) -> str:
        rows = [(c, W.text_sha(self.verified[c]) if c in self.verified else None, self.od(c), self.findings(c))
                for c in self.criteria(alan)]
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
            "od": {c: src.od(c) for c in src.criteria(alan)}, "girdi_sha": src.girdi_sha(alan)}
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


def check(t: dict, meta: dict) -> list[dict]:
    """Bütün maddelerin denetimi → [{yer, metin, kod, ayrinti}]."""
    out = []
    allowed = {"guclu": set(meta["guclu_olcutler"]), "gelisme": set(meta["gelisme_olcutler"])}
    for r in items(t):
        for x in check_item(r["metin"], liste=r["liste"], alan=meta["alan"], allowed=allowed[r["liste"]],
                            od=meta.get("od") or {}):
            out.append({"yer": r["yer"], "metin": r["metin"], **x})
    return out


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
            if (cur and not redo and (kay.get("temel_istem_sha") or kay.get("istem_sha")) == K.sha(r["prompt"])
                    and str(kay.get("gorev_surumu")) == str(r["version"])):
                st["zaten_tamam"] += 1
                continue
            meta.update({"tur": int((t or {}).get("tur") or 0) if cur else 0, "temel_istem_sha": K.sha(r["prompt"])})
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
                          "cevap_sha": K.sha(raw), "zaman": K.now()}}
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
            "od": {c: src.od(c) for c in src.criteria(alan)}}


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
        inputs = {"alan": src.alan_title(alan), "maddeler": "\n".join(f"{r['yer']}: {r['metin']}" for r in rows),
                  "olcutler": src.render_criteria(cited)}
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
