"""`bidr decide`: iki adımlı model kararı → decisions.jsonl.

İki yol, aynı görev girdileri ve aynı denetim:
  - ajan modu (birincil): `prepare` iş paketlerini `work/<aşama>/<doc_id>.json` olarak
    yazar; kullanıcının ajanı her paketi okuyup cevabı `<doc_id>.out.json`'a yazar;
    `apply` cevapları doğrular (şema + alıntı) ve decisions.jsonl'e işler. Sağlayıcı
    çağrılmaz.
  - sağlayıcı modu (ikincil): `run` aynı girdileri `bidr.llm.run_task` ile işler.

Akış (belge başına):
  1. Öz-referans tür (`haric_turler.yaml`) ya da metinsiz belge → atlanır (kayda geçer).
  2. classify_coarse: profile göre süzülmüş alt ölçütler → en çok 5 ölçüt.
  3. Aday birleşimi: kaba seçim ∪ candidates.jsonl ilk k (profil içinde), en çok `max_aday`.
  4. classify_fine: aday rubrik + yuvalar → eşleşmeler.
  5. Kod denetimi: aday dışı ölçüt, geçersiz yuva, tutmayan/çok kısa alıntı → eşleşme
     REDDEDİLİR (kayıtta kalır, `kabul: false`). Aşama yuva etiketine uymuyorsa ya da
     OD aşamayla tutarsızsa OD düşük olana çekilir (`od_kabul`), işaretlenir.
     Kurum/fakülte geneli belgenin (model `birim_iliskisi` ya da `kurum_geneli.yaml` türü)
     eşleşmeleri OD2 ile sınırlanır (`uygulama_kaniti_eksik`). Başka birime ait belgenin
     (`birim_iliskisi: baska_birim`) eşleşmeleri reddedilir; `belirsiz` kabul edilir,
     `birim_aitligi_dogrulanmali` işaretlenir. İnsan birim kararı (`birim-kararlari.jsonl`)
     varsa pakete sabit bilgi olarak girer ve modelinkinin önüne geçer.

Yeniden işleme: `prepare --only` yalnız verilen belgeleri yeniden paketler. Görev sürümü ya
da istem değişen işlenmiş belgeler "eski" sayılır; `prepare` önce özet verir, `--yes` ile
kayıtları `yeniden` diye işaretleyip paketler. Metni aynı/çok yakın belgelerden yalnız
temsilci paketlenir, ötekiler kararı devralır (`dedup.py`, `mukerrer` alanı).

Modele yalnız belge metni ve `documents.jsonl` içerik alanları gider (bkz. prompt.py).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from bidr.common import Workspace, read_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import CriteriaSet
from bidr.criteria.profiles import excluded_types, load_profile
from bidr.criteria.slots import STAGE_OD, load_tags

from . import dedup as D
from . import prompt as P

TASKS_DIR = Path(__file__).resolve().parents[1] / "tasks"
COARSE, FINE = "classify_coarse", "classify_fine"
MAX_COARSE = 5
MIN_QUOTE = 20           # bundan kısa alıntı kanıt sayılmaz (ör. yalnız başlık sözcüğü)
DECISIONS = "decisions.jsonl"
SCHEMA = 1
KURUM_OD = 2             # kurum geneli düzenleme tek başına en çok OD2 (komisyon ilkesi)
KURUM_FILE = Path(__file__).resolve().parents[1] / "data" / "profiles" / "kurum_geneli.yaml"
RESTALE = "YENIDEN.json"  # work/<aşama>/: onay bekleyen eski kayıtların özeti


class Backend:
    """`bidr.llm` arayüzü (docs/MODEL_LAYER.md). Verilmeyen işlev çağrıldığında
    `bidr.llm`'den alınır; testler sahtesini verir."""
    NAMES = ("run_task", "load_model_config", "verify_quote", "render_task", "validate_output")

    def __init__(self, **fns):
        bad = set(fns) - set(self.NAMES)
        if bad:
            raise TypeError(f"bilinmeyen işlev: {bad}")
        self._fns = fns

    def __getattr__(self, name):
        if name in Backend.NAMES:
            f = self.__dict__["_fns"].get(name)
            if f is None:
                import bidr.llm as llm
                f = getattr(llm, name)
            return f
        raise AttributeError(name)


def task_version(name: str) -> str:
    raw = yaml.safe_load((TASKS_DIR / name / "task.yaml").read_text(encoding="utf-8"))
    return str(raw["version"])


def kurum_geneli_types(path: Path | None = None) -> frozenset[str]:
    p = Path(path) if path else KURUM_FILE
    if not p.exists():
        return frozenset()
    return frozenset((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("kurum_geneli_turler") or ())


# Belgenin karar paketindeki birimle ilişkisi (classify_fine v8 `birim_iliskisi`).
BIRIM_ILISKILERI = ("kendi", "ust_birim_bu_birim_hakkinda", "fakulte_geneli", "kurum_geneli",
                    "baska_birim", "belirsiz")
GENEL_ILISKI = frozenset({"fakulte_geneli", "kurum_geneli"})   # OD2 tavanı (kurum geneli kuralı)
BIRIM_DISI = "baska_birim"                                       # bu birim için kanıt değil
BIRIM_BELIRSIZ = "belirsiz"                                      # kabul; aitlik doğrulanmalı
# İnsan (komisyon) birim kararı: review.xlsx "Başka birime ait sayılanlar" sayfası → `bidr audit
# apply` → birim-kararlari.jsonl. İnsan `belirsiz` diyemez (karar vermek içindir).
INSAN_ILISKILERI = tuple(x for x in BIRIM_ILISKILERI if x != BIRIM_BELIRSIZ)
BIRIM_KARARLARI = "birim-kararlari.jsonl"


def load_unit_pins(root: Path) -> dict[str, dict]:
    """{doc_id: insan birim kararı} (`birim-kararlari.jsonl`; yoksa boş). Geçersiz değer atlanır."""
    p = Path(root) / BIRIM_KARARLARI
    if not p.exists():
        return {}
    return {r["doc_id"]: r for r in read_jsonl(p)
            if r.get("doc_id") and r.get("birim_iliskisi") in INSAN_ILISKILERI}


def restorable(m: dict) -> bool:
    """Yalnız birim aitliği yüzünden reddedilmiş eşleşme (başka red nedeni yok): insan birim
    ilişkisini değiştirirse geri yüklenebilir."""
    red = (m.get("denetim") or {}).get("red") or []
    return not m.get("kabul") and bool(red) and set(red) == {BIRIM_DISI}


def pin_applied(rec: dict | None, pin: dict | None) -> bool:
    """Kayıt bu insan kararıyla (paket sabit bilgisiyle) yeniden karara bağlanmış mı."""
    ince = (rec or {}).get("ince") or {}
    return bool(pin) and ince.get("birim_iliskisi_kaynagi") == "insan" \
        and ince.get("birim_iliskisi") == pin.get("birim_iliskisi")


def pending_redecide(recs: dict[str, dict], pins: dict[str, dict]) -> list[str]:
    """İnsan birim ilişkisini değiştirdi ama geri yüklenecek eşleşme kaydı yoktu
    (`yeniden_karar`): `prepare --stage fine --only` ile yeniden ince karar bekleyen belgeler."""
    return sorted(d for d, p in pins.items()
                  if p.get("yeniden_karar") and stage_done(recs.get(d), "fine")
                  and not pin_applied(recs.get(d), p))


def needs_redecide(rec: dict | None, rel: str) -> bool:
    """İnsan kararı `rel` bu kayıtta yeniden ince karar gerektirir mi: (a) model başka birim dedi,
    insan başka bir ilişki verdi ve geri yüklenecek eşleşme yok; (b) kayıt önceki bir insan
    kararıyla (başka birim dışı bir ilişkiyle) yeniden karara bağlanmıştı ve insan ilişkiyi
    değiştirdi: eşleşmeler eski ilişkinin kuralını taşır (ör. önce fakülte geneli → OD2 düşüşü,
    sonra kendi: düşüş kayıtta kalır), görünüm bunu geri alamaz."""
    if rel == BIRIM_DISI or not rec or pin_applied(rec, {"birim_iliskisi": rel}):
        return False
    if ((rec.get("ince") or {}).get("birim_iliskisi_kaynagi") == "insan"
            and record_unit_relation(rec) != BIRIM_DISI):
        return True
    if record_unit_relation(rec) != BIRIM_DISI:
        return False
    return not any(restorable(m) for m in rec.get("eslesmeler") or [])


def unit_view(rec: dict, pins: dict[str, dict] | None, tags: dict) -> dict:
    """Kaydın etkin görünümü (öncelik insan > model): `pins`te (`load_unit_pins`) insan birim
    kararı varsa `override_unit`, yoksa kaydın kendisi. audit, file (audit üzerinden) ve name
    aynı görünümü kullanır; decisions.jsonl değişmez."""
    pin = (pins or {}).get(rec.get("doc_id"))
    return override_unit(rec, pin["birim_iliskisi"], tags) if pin else rec


def override_unit(rec: dict, rel: str, tags: dict) -> dict:
    """Kaydın insan birim kararıyla görünümü (decisions.jsonl değişmez; audit/file bunu kullanır).
    `baska_birim` → kabul edilmiş eşleşmeler birim nedeniyle reddedilir; başka bir değer →
    yalnız birim yüzünden reddedilmiş eşleşmeler geri yüklenir ve yeni ilişkinin kuralı
    uygulanır (fakülte/kurum geneli: OD2 tavanı; kendi/üst birim: tavan yok). Geri yüklenen
    eşleşme `birim_iliskisi_insan` işareti taşır; kararı yine inceleme tablosunda insan verir."""
    ince = dict(rec.get("ince") or {})
    if ince.get("birim_iliskisi") == rel and ince.get("birim_iliskisi_kaynagi") == "insan":
        return rec
    old = record_unit_relation(rec)
    new = {**rec, "ince": {**ince, "birim_iliskisi": rel, "birim_iliskisi_kaynagi": "insan",
                           "birim_iliskisi_model": old}}
    tur = bool((ince.get("kurum_geneli") or {}).get("tur")) if isinstance(ince.get("kurum_geneli"), dict) else False
    kurum = rel in GENEL_ILISKI or tur
    ms = []
    for m in rec.get("eslesmeler") or []:
        m = dict(m)
        den = dict(m.get("denetim") or {})
        if rel == BIRIM_DISI:
            if m.get("kabul"):
                den["red"] = [*(den.get("red") or []), BIRIM_DISI]
                m.update(kabul=False, od_kabul=None, denetim=den)
        elif restorable(m):
            tag = tags.get(m.get("yuva"))
            od_kod = _od_code(m.get("asama"), tag)
            od_model = m.get("od_onerisi")
            cands = [x for x in (od_model if isinstance(od_model, int) else None, od_kod) if x]
            isaret = [x for x in den.get("isaret") or [] if x != "birim_aitligi_dogrulanmali"]
            od = min(cands) if cands else None
            if kurum and od is not None and od > KURUM_OD:
                od = KURUM_OD
                isaret.append("uygulama_kaniti_eksik")
            isaret.append("birim_iliskisi_insan")
            den.update(red=[], isaret=list(dict.fromkeys(isaret)))
            m.update(kabul=od is not None, od_kabul=od, denetim=den)
        ms.append(m)
    new["eslesmeler"] = ms
    return new


def _od_code(asama, tag, slot_ok: bool = True):
    """Kodun aşamadan verdiği OD: aşama yuva etiketine uymuyorsa yuvanın en düşük OD'si."""
    if tag is not None:
        if tag.uncertain or asama in tag.stages:
            return STAGE_OD.get(asama)
        return min(tag.od) if tag.od else None
    return STAGE_OD.get(asama) if slot_ok else None


def unit_relation(out: dict) -> tuple[str, str]:
    """Model cevabından (iliski, kaynak). Geri uyumluluk (v7 ve öncesi): `birim_iliskisi`
    yoksa eski `kurum_geneli: true` → kurum_geneli (kaynak `eski_alan`), değilse `kendi`
    (kaynak `varsayilan`; eski kararlar birim sorulmadan verildi, `belirsiz` sayılmaz)."""
    v = out.get("birim_iliskisi")
    if isinstance(v, str) and v in BIRIM_ILISKILERI:
        return v, "model"
    if out.get("kurum_geneli") is True:
        return "kurum_geneli", "eski_alan"
    return "kendi", "varsayilan"


def record_unit_relation(rec: dict | None) -> str:
    """decisions.jsonl kaydından birim ilişkisi (eski kayıtlar için `unit_relation` kuralı)."""
    ince = (rec or {}).get("ince") or {}
    v = ince.get("birim_iliskisi")
    if isinstance(v, str) and v in BIRIM_ILISKILERI:
        return v
    kg = ince.get("kurum_geneli")
    return "kurum_geneli" if isinstance(kg, dict) and kg.get("model") is True else "kendi"


def kurum_geneli(out: dict, doc: dict | None, types: frozenset[str] | None = None) -> dict:
    """{"model": bool|None, "tur": bool, "karar": bool}. Model (`birim_iliskisi` kurum ya da
    fakülte geneli; eski cevapta `kurum_geneli`) ya da tür listesi yeter (tavan yalnız OD'yi
    düşürür; bkz. kurum_geneli.yaml)."""
    types = kurum_geneli_types() if types is None else types
    rel, src = unit_relation(out)
    m = (rel in GENEL_ILISKI) if src != "varsayilan" else (
        False if out.get("kurum_geneli") is False else None)
    t = bool(doc and doc.get("doc_type") in types)
    return {"model": m, "tur": t, "karar": bool(m) or t}


def _documents(ws: Workspace) -> dict[str, dict]:
    if not ws.documents.exists():
        return {}
    return {r["doc_id"]: r for r in read_jsonl(ws.documents) if r.get("doc_id")}


def _candidates(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {r["doc_id"]: r for r in read_jsonl(path) if r.get("doc_id")}


def _labeled_ids(ws: Workspace) -> set[str]:
    """Yalnız `--only-labeled` süzgeci için: hangi doc_id etiketli. Başka alan okunmaz."""
    if not ws.labels.exists():
        return set()
    return {r["doc_id"] for r in read_jsonl(ws.labels) if r.get("doc_id") and r.get("etiketli")}


def _model_id(res, cfg) -> str:
    m = getattr(res, "model", None)
    return str(m) if m else str(getattr(cfg, "model_id", None) or getattr(cfg, "id", cfg))


def merge_candidates(coarse: list[str], cand_row: dict | None, allowed: set[str], k: int,
                     max_aday: int) -> tuple[list[str], list[str], list[str]]:
    """(adaylar, belirleyici ilk k, kesilenler). Kaba seçim önde, sonra belirleyici sıra."""
    det = [c["olcut"] for c in (cand_row or {}).get("adaylar", [])
           if c.get("olcut") in allowed][:k]
    order: list[str] = []
    for x in [*coarse, *det]:
        if x not in order:
            order.append(x)
    return order[:max_aday], det, order[max_aday:]


def check_matches(out: dict, cands: list[str], cs: CriteriaSet, tags: dict, text: str,
                  verify: Callable, kurum: bool = False, birim: str = "kendi") -> list[dict]:
    """İnce kararın eşleşmelerini kodla denetler; her eşleşmeye `denetim`, `kabul`,
    `od_kabul` ekler. Alıntı tam (kısaltılmamış) metne karşı denetlenir. `kurum`: belge
    kurum/fakülte geneli → kabul edilen OD en çok `KURUM_OD`. `birim`: belgenin birimle
    ilişkisi; `baska_birim` her eşleşmeyi reddeder, `belirsiz` işaretler."""
    rows = []
    seen = set()
    cset = set(cands)
    for m in out.get("eslesmeler") or []:
        r = dict(m)
        red: list[str] = []
        isaret: list[str] = []
        olcut, yuva = r.get("olcut"), r.get("yuva")
        if olcut not in cset:
            red.append("aday_disi_olcut")
        slot = None
        try:
            slot = cs.get_slot(yuva)
        except KeyError:
            red.append("gecersiz_yuva")
        if slot is not None and (slot.criterion != olcut or slot.footnote):
            red.append("yuva_olcute_ait_degil")
            slot = None
        q = (r.get("alinti") or "").strip()
        ok, score, span = verify(q, text) if q else (False, 0.0, None)
        r["denetim"] = {"alinti_tutuyor": bool(ok), "alinti_skor": round(float(score or 0), 4),
                        "alinti_konum": list(span) if span else None}
        if not ok:
            red.append("alinti_tutmuyor")
        if len(q) < MIN_QUOTE:
            red.append("alinti_cok_kisa")
        if (olcut, yuva) in seen:
            red.append("yinelenen")
        seen.add((olcut, yuva))
        if birim == BIRIM_DISI:
            red.append("baska_birim")
        elif birim == BIRIM_BELIRSIZ:
            isaret.append("birim_aitligi_dogrulanmali")
        # OD: aşama yuva etiketine uymalı; uymuyorsa yuvanın en düşük OD'si.
        tag = tags.get(yuva) if slot is not None else None
        asama = r.get("asama")
        od_model = r.get("od_onerisi")
        od_kod = _od_code(asama, tag, slot is not None)
        if tag is not None:
            r["yuva_etiketi"] = {"asama": list(tag.stages), "od": list(tag.od), "durum": tag.state}
            if not tag.uncertain and asama not in tag.stages:
                isaret.append("asama_yuva_etiketine_uymuyor")
        if isinstance(od_model, int) and od_kod is not None and od_model != od_kod:
            isaret.append("od_asamayla_tutarsiz")
        cands_od = [x for x in (od_model if isinstance(od_model, int) else None, od_kod) if x]
        r["od_kabul"] = min(cands_od) if cands_od and not red else None
        if kurum and r["od_kabul"] is not None and r["od_kabul"] > KURUM_OD:
            r["od_kabul"] = KURUM_OD
            isaret.append("uygulama_kaniti_eksik")
        r["denetim"]["red"] = red
        r["denetim"]["isaret"] = isaret
        r["kabul"] = not red
        rows.append(r)
    return rows


def summarize(matches: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for m in matches:
        if not m["kabul"]:
            continue
        e = by.setdefault(m["olcut"], {"olcut": m["olcut"], "ana": m["olcut"].rsplit(".", 1)[0],
                                       "od": None, "yuvalar": []})
        e["yuvalar"].append(m["yuva"])
        if m["od_kabul"] and (e["od"] is None or m["od_kabul"] > e["od"]):
            e["od"] = m["od_kabul"]
    return list(by.values())


# -- bağlam ---------------------------------------------------------------------

@dataclass
class Context:
    ws: Workspace
    cs: CriteriaSet
    tags: dict
    profile: str | None
    allowed: list[str]
    ex_types: frozenset
    docs: dict
    cand: dict
    k: int
    max_aday: int
    unit: dict = None          # {"birim", "kurum"}: config.yaml'dan, ince karar paketine girer
    pins: dict = None          # {doc_id: insan birim kararı} (birim-kararlari.jsonl): sabit bilgi

    def __post_init__(self):
        if self.unit is None:
            self.unit = {"birim": None, "kurum": None}
        if self.pins is None:
            self.pins = {}

    def pin(self, did: str) -> str | None:
        return (self.pins.get(did) or {}).get("birim_iliskisi")

    @classmethod
    def load(cls, ws_root: Path, *, profile: str | None = "akademik_bolum", k: int = 5,
             max_aday: int = 6, candidates_name: str = "candidates.jsonl",
             criteria: CriteriaSet | None = None, exclude_types: frozenset | None = None) -> "Context":
        ws = Workspace(ws_root)
        cs = criteria or load_criteria()
        allowed = load_profile(profile).allowed(cs) if profile else [s.id for s in cs.sub_criteria]
        return cls(ws, cs, load_tags(cs), profile or None, allowed,
                   excluded_types() if exclude_types is None else exclude_types,
                   _documents(ws), _candidates(ws.root / candidates_name), k, max_aday,
                   P.unit_info(ws.root), load_unit_pins(ws.root))

    def text(self, did: str) -> str:
        return self.ws.text_path(did).read_text(encoding="utf-8", errors="replace")

    def det_top(self, did: str) -> list[str]:
        aset = set(self.allowed)
        return [c["olcut"] for c in (self.cand.get(did) or {}).get("adaylar", [])
                if c.get("olcut") in aset][:self.k]

    def skip_reason(self, did: str) -> str | None:
        doc = self.docs.get(did)
        if doc and doc.get("doc_type") in self.ex_types:
            return "oz_referans_turu"
        if not self.ws.text_path(did).exists():
            return "metin_yok"
        if not self.text(did).strip():
            return "metin_bos"
        return None


def select_ids(ctx: Context, *, only_labeled: bool = False, limit: int | None = None,
               ids: list[str] | None = None) -> list[str]:
    out = ids if ids is not None else (
        sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")) if ctx.ws.text_dir.exists() else [])
    if only_labeled:
        lab = _labeled_ids(ctx.ws)
        out = [i for i in out if i in lab]
    return out[:limit] if limit else out


# -- decisions.jsonl deposu ----------------------------------------------------------

def load_decisions(ws: Workspace, name: str = DECISIONS) -> dict[str, dict]:
    p = ws.root / name
    return {r["doc_id"]: r for r in read_jsonl(p)} if p.exists() else {}


def save_decisions(ws: Workspace, recs: dict[str, dict], name: str = DECISIONS) -> Path:
    from bidr.common import write_jsonl
    out = ws.root / name
    write_jsonl(out, [recs[k] for k in sorted(recs)])
    return out


def skipped_record(did: str, reason: str, ctx: Context) -> dict:
    r = {"doc_id": did, "sema": SCHEMA, "durum": "atlandi", "neden": reason, "profil": ctx.profile}
    if reason == "oz_referans_turu":
        r["doc_type"] = ctx.docs[did]["doc_type"]
    return r


# -- görev girdileri ve sonuç işleme (iki yolun ortak çekirdeği) ----------------------

def coarse_inputs(ctx: Context, did: str) -> tuple[dict, dict]:
    """(görev girdileri, meta). Meta, `apply`'ın ihtiyaç duyduğu ve modele gitmeyen bilgi."""
    info = P.content_info(ctx.docs.get(did))
    det = ctx.det_top(did)
    body, ex = P.excerpt(ctx.text(did), P.COARSE_CHARS, P.criteria_terms(ctx.cs, det) if det else None)
    inputs = {"olcutler": P.coarse_list(ctx.cs, ctx.allowed), "belge_bilgisi": P.render_info(info),
              "belge_metni": body}
    meta = {"belge_bilgisi": info, "metin": ex, "profil": ctx.profile, "izinli": list(ctx.allowed),
            "istem_token_tahmini": P.approx_tokens("".join(inputs.values()))}
    return inputs, meta


def apply_coarse(did: str, out: dict, meta: dict, model_id: str, extra: dict | None = None) -> dict:
    aset = set(meta["izinli"])
    picked: list[str] = []
    if out.get("karar") == "olcut_var":
        for o in out.get("olcutler") or []:
            if o.get("olcut") in aset and o["olcut"] not in picked:
                picked.append(o["olcut"])
    return {"doc_id": did, "sema": SCHEMA, "durum": "ok", "asama": "kaba", "profil": meta["profil"],
            "gorev": {COARSE: task_version(COARSE)}, "belge_bilgisi": meta["belge_bilgisi"],
            "kaba": {"karar": out.get("karar"), "olcutler": out.get("olcutler") or [],
                     "secilen": picked[:MAX_COARSE], "gerekce": out.get("gerekce", ""),
                     "liste_disi": [o.get("olcut") for o in out.get("olcutler") or []
                                    if o.get("olcut") not in aset],
                     "model": model_id, "metin": meta["metin"],
                     "istem_token_tahmini": meta["istem_token_tahmini"], **(extra or {})}}


def fine_inputs(ctx: Context, did: str, rec: dict, pin: bool = True) -> tuple[dict, dict] | None:
    """Kaba kayıttan aday birleşimi; aday yoksa None. İnsan birim kararı varsa (`pin`) pakete
    sabit bilgi olarak girer; model bunu değiştiremez (`apply_fine` alanı zorlar)."""
    cands, det, cut = merge_candidates(rec["kaba"]["secilen"], ctx.cand.get(did), set(ctx.allowed),
                                       ctx.k, ctx.max_aday)
    meta = {"adaylar": cands, "belirleyici_ilk_k": det, "adaylar_kesilen": cut}
    if not cands:
        return None, meta
    body, ex = P.excerpt(ctx.text(did), P.FINE_CHARS, P.criteria_terms(ctx.cs, cands))
    inputs = {"adaylar": P.fine_list(ctx.cs, cands, ctx.tags),
              "belge_bilgisi": P.render_info(rec.get("belge_bilgisi") or {}), "belge_metni": body,
              "kanit_ilkeleri": P.evidence_principles(),
              "birim": P.render_unit(ctx.unit, ctx.pin(did) if pin else None)}
    meta.update(metin=ex, istem_token_tahmini=P.approx_tokens("".join(inputs.values())))
    if pin and ctx.pin(did):
        meta["birim_sabit"] = ctx.pin(did)
    return inputs, meta


def _clear_pending(rec: dict) -> dict:
    """Yeni karar işlenince bekleme işaretleri kalkar (`yeniden`, bekleyen `mukerrer`)."""
    rec = dict(rec)
    rec.pop("yeniden", None)
    if (rec.get("mukerrer") or {}).get("durum") == "bekliyor":
        rec.pop("mukerrer")
    return rec


def no_candidate(rec: dict, meta: dict) -> dict:
    rec = _clear_pending(rec)
    rec.update(asama="ince", adaylar=[], belirleyici_ilk_k=meta["belirleyici_ilk_k"],
               adaylar_kesilen=[], ince={"karar": "atlandi", "neden": "aday_yok"},
               eslesmeler=[], olcutler=[], reddedilen_eslesme=0,
               karar="kanit_degil" if rec["kaba"]["karar"] == "kanit_degil" else "olcut_yok")
    return rec


def apply_fine(ctx: Context, did: str, rec: dict, out: dict, meta: dict, model_id: str,
               verify: Callable, extra: dict | None = None) -> dict:
    rec = _clear_pending(rec)
    model_rel = unit_relation(out)[0]
    pin = ctx.pin(did)
    if pin:                                 # insan kararı modelinkinin önüne geçer
        out = {**out, "birim_iliskisi": pin}
    kg = kurum_geneli(out, ctx.docs.get(did))
    rel, rel_src = unit_relation(out)
    if pin:
        rel_src = "insan"
    matches = check_matches(out, meta["adaylar"], ctx.cs, ctx.tags, ctx.text(did), verify, kg["karar"],
                            rel)
    rec["gorev"] = {**rec.get("gorev", {}), FINE: task_version(FINE)}
    rec.update(asama="ince", adaylar=meta["adaylar"], belirleyici_ilk_k=meta["belirleyici_ilk_k"],
               adaylar_kesilen=meta["adaylar_kesilen"])
    rec["ince"] = {"karar": out.get("karar"), "gerekce": out.get("gerekce", ""), "kurum_geneli": kg,
                   "birim_iliskisi": rel, "birim_iliskisi_kaynagi": rel_src,
                   **({"birim_iliskisi_model": model_rel} if pin else {}),
                   "kanit_adi": evidence_name_of(out), "model": model_id,
                   "metin": meta["metin"], "istem_token_tahmini": meta["istem_token_tahmini"],
                   **(extra or {})}
    rec["eslesmeler"] = matches
    rec["olcutler"] = summarize(matches)
    if rec["olcutler"]:
        rec["karar"] = "olcut_var"
    elif out.get("karar") == "kanit_degil" or rel == BIRIM_DISI:   # başka birimin belgesi kanıt değil
        rec["karar"] = "kanit_degil"
    else:
        rec["karar"] = "olcut_yok"
    rec["reddedilen_eslesme"] = sum(not m["kabul"] for m in matches)
    return rec


def evidence_name_of(out: dict) -> dict | None:
    """Belge düzeyi `kanit_adi` (v7). Kişi adı/unvan/e-posta ya da biçimsiz öneri reddedilir
    (`durum: red`, `red`: nedenler); ad o zaman kuraldan gelir (bidr/name/resolve.py)."""
    if "kanit_adi" not in out:
        return None
    from bidr.name.check import check_name
    ad, errs = check_name(out.get("kanit_adi"))
    return {"oneri": out.get("kanit_adi"), "ad": ad, "durum": "red" if errs else "kabul", "red": errs}


def stats_of(recs: dict[str, dict]) -> dict:
    """Belge sayaçları. `olcut_var/olcut_yok/kanit_degil` ince kararın sonucu (yalnız ince
    aşamadaki belgeler); `kaba_karar` kaba seçimin sonucu (kaba kaydı olan her belge)."""
    st = {"belge": len(recs), "ok": 0, "atlandi": 0, "hata": 0, "kaba": 0, "ince": 0,
          "olcut_var": 0, "olcut_yok": 0, "kanit_degil": 0, "kabul_eslesme": 0, "reddedilen_eslesme": 0,
          "kaba_karar": {"olcut_var": 0, "olcut_yok": 0, "kanit_degil": 0}, "devralan": 0,
          "yeniden": 0, "od_tavan": 0, "baska_birim": 0, "birim_belirsiz": 0}
    for r in recs.values():
        st[r["durum"]] = st.get(r["durum"], 0) + 1
        if r["durum"] != "ok":
            continue
        st[r.get("asama", "kaba")] += 1
        kk = (r.get("kaba") or {}).get("karar")
        if kk:
            st["kaba_karar"][kk] = st["kaba_karar"].get(kk, 0) + 1
        st["devralan"] += bool((r.get("mukerrer") or {}).get("durum") == "devralindi")
        st["yeniden"] += bool(r.get("yeniden"))
        if r.get("asama") == "ince":
            st["od_tavan"] += sum("uygulama_kaniti_eksik" in m.get("denetim", {}).get("isaret", ())
                                  for m in r.get("eslesmeler", []))
            st[r["karar"]] += 1
            rel = record_unit_relation(r)
            st["baska_birim"] += rel == BIRIM_DISI
            st["birim_belirsiz"] += rel == BIRIM_BELIRSIZ
            st["kabul_eslesme"] += sum(m["kabul"] for m in r.get("eslesmeler", []))
            st["reddedilen_eslesme"] += r.get("reddedilen_eslesme", 0)
    return st




# -- aşama durumu, eskime, mükerrer metin -------------------------------------------------

STAGES = {"coarse": COARSE, "fine": FINE}
MATCH_KEYS = ("olcut", "yuva", "asama", "od_onerisi", "alinti", "gerekce", "guven")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _section(rec: dict | None, stage: str) -> dict:
    return (rec or {}).get("kaba" if stage == "coarse" else "ince") or {}


def stage_done(rec: dict | None, stage: str) -> bool:
    """Belge bu aşamada sonuçlanmış mı. `yeniden` (onaylı yeniden işleme) ya da bekleyen
    `mukerrer` (temsilcinin kararını bekliyor) işaretli kayıt tamam sayılmaz."""
    if not rec or rec.get("durum") != "ok":
        return False
    if (rec.get("yeniden") or {}).get("asama") == stage:
        return False
    mk = rec.get("mukerrer") or {}
    if mk.get("durum") == "bekliyor" and mk.get("asama") == stage:
        return False
    return "kaba" in rec if stage == "coarse" else rec.get("asama") == "ince"


def version_stale(rec: dict | None, stage: str) -> bool:
    task = STAGES[stage]
    v = ((rec or {}).get("gorev") or {}).get(task)
    return v is not None and str(v) != task_version(task)


def staleness(ctx: Context, did: str, rec: dict, stage: str, backend: Backend) -> str | None:
    """İşlenmiş kayıt eskidi mi: "eski_surum" (görev sürümü değişti) | "istem_degisti"
    (doldurulmuş istem farklı: metin, belge bilgisi, aday, ilke, istem şablonu) | None.
    İstem karşılaştırması yalnız ajan kipinde kaydedilen `istem_sha` ile yapılır."""
    if version_stale(rec, stage):
        return "eski_surum"
    sec = _section(rec, stage)
    if sec.get("devralindi") or not sec.get("istem_sha"):
        return None
    if stage == "coarse":
        inputs, _ = coarse_inputs(ctx, did)
    else:
        # İnsan birim kararı audit'te uygulanır; yalnız kayıt onunla yeniden karara bağlandıysa
        # istem karşılaştırmasına girer (karar değişmedikçe belge "istem değişti" sayılmaz).
        inputs, _ = fine_inputs(ctx, did, rec, pin=_section(rec, "fine").get("birim_iliskisi_kaynagi") == "insan")
        if inputs is None:
            return None
    sha = _sha(backend.render_task(STAGES[stage], inputs)["prompt"])
    return "istem_degisti" if sha != sec["istem_sha"] else None


def stale_summary(ws: Workspace, stage: str, recs: dict | None = None) -> dict[str, str]:
    """Salt okunur: {doc_id: neden} — onay bekleyen yeniden işleme (bidr status için).
    Sürüm farkı kayıttan hesaplanır; istem farkı son `prepare`'in yazdığı YENIDEN.json'dan."""
    recs = load_decisions(ws) if recs is None else recs
    out = {d: "eski_surum" for d, r in recs.items() if stage_done(r, stage) and version_stale(r, stage)}
    f = work_dir(ws, stage) / RESTALE
    if f.exists():
        try:
            for d, why in (json.loads(f.read_text(encoding="utf-8")).get("belgeler") or {}).items():
                if stage_done(recs.get(d), stage):
                    out.setdefault(d, why)
        except (OSError, ValueError):
            pass
    return out


def plan_members(ctx: Context, ids: list[str], recs: dict, stage: str) -> dict[str, dict]:
    """Metni aynı/çok yakın belgeler → {üye: {temsilci, yontem, fark_sozcuk}}. Temsilci:
    bu aşamada işlenmiş olan, yoksa en uzun metin, sonra en küçük doc_id (kararlı seçim).
    Bu aşamada gruptan ayrılmış (`mukerrer.durum: ayrildi`) belge gruplanmaz."""
    ok = [d for d in ids if not ((recs.get(d) or {}).get("mukerrer") or {}).get("durum") == "ayrildi"]
    if len(ok) < 2:
        return {}
    texts = {d: ctx.text(d) for d in ok}
    types = {d: (ctx.docs.get(d) or {}).get("doc_type") for d in ok}
    out = {}
    for g in D.find_groups(texts, types):
        rep = min(g["uyeler"], key=lambda x: (not stage_done(recs.get(x), stage), -len(g["toks"][x]), x))
        for m in g["uyeler"]:
            if m == rep:
                continue
            rel = D.relation(g, rep, m)
            if rel:
                out[m] = {"temsilci": rep, "yontem": rel[0], "fark_sozcuk": rel[1]}
    return out


def _mark_member(ctx: Context, recs: dict, did: str, info: dict, stage: str) -> None:
    rec = recs.get(did)
    if stage == "coarse" and not (rec and rec.get("durum") == "ok" and "kaba" in rec):
        rec = {"doc_id": did, "sema": SCHEMA, "durum": "bekliyor", "profil": ctx.profile}
    rec = dict(rec)
    rec["mukerrer"] = {**info, "asama": stage, "durum": "bekliyor"}
    recs[did] = rec


def rep_output(rep: dict) -> dict:
    """Temsilcinin ince kararından modelin cevabı (kodun eklediği alanlar atılır)."""
    out = {"karar": rep["ince"].get("karar"), "gerekce": rep["ince"].get("gerekce", ""),
           "eslesmeler": [{k: m[k] for k in MATCH_KEYS if k in m} for m in rep.get("eslesmeler") or []]}
    if rep["ince"].get("birim_iliskisi") in BIRIM_ILISKILERI:
        out["birim_iliskisi"] = rep["ince"]["birim_iliskisi"]
    else:                                   # v7 ve öncesi temsilci: eski alan (geri uyumluluk)
        kg = rep["ince"].get("kurum_geneli")
        if isinstance(kg, dict) and isinstance(kg.get("model"), bool):
            out["kurum_geneli"] = kg["model"]
    ka = rep["ince"].get("kanit_adi")
    if isinstance(ka, dict) and isinstance(ka.get("oneri"), str):
        out["kanit_adi"] = ka["oneri"]
    return out


def inherit(ctx: Context, recs: dict, stage: str, verify: Callable) -> dict:
    """Temsilcisi bu aşamada sonuçlanmış bekleyen üyeler kararı devralır. İnce kararda
    temsilcinin eşleşmeleri üyenin KENDİ metnine karşı yeniden denetlenir; kabul edilen
    eşleşme sayısı düşerse üye gruptan ayrılır (`ayrildi`) ve kendisi işlenir."""
    st = {"devralindi": 0, "ayrildi": []}
    for did in sorted(recs):
        rec = recs[did]
        mk = rec.get("mukerrer") or {}
        if mk.get("durum") != "bekliyor" or mk.get("asama") != stage:
            continue
        rid = mk["temsilci"]
        rep = recs.get(rid)
        if not stage_done(rep, stage) or rid == did:
            continue
        if stage == "coarse":
            new = json.loads(json.dumps({k: rep[k] for k in ("sema", "durum", "profil", "kaba") if k in rep},
                                        ensure_ascii=False))
            new.update(doc_id=did, asama="kaba", belge_bilgisi=P.content_info(ctx.docs.get(did)))
            new["gorev"] = {COARSE: rep.get("gorev", {}).get(COARSE)}
            new["kaba"]["devralindi"] = rid
        elif rep["ince"].get("karar") == "atlandi":
            new = no_candidate(rec, {"belirleyici_ilk_k": rep.get("belirleyici_ilk_k", [])})
            new["ince"] = {**new["ince"], "devralindi": rid}
        else:
            meta = {"adaylar": rep.get("adaylar", []), "belirleyici_ilk_k": rep.get("belirleyici_ilk_k", []),
                    "adaylar_kesilen": rep.get("adaylar_kesilen", []), "metin": rep["ince"].get("metin"),
                    "istem_token_tahmini": rep["ince"].get("istem_token_tahmini")}
            extra = {k: rep["ince"][k] for k in ("kip", "istem_sha") if k in rep["ince"]}
            extra["devralindi"] = rid
            new = apply_fine(ctx, did, rec, rep_output(rep), meta, rep["ince"].get("model"), verify, extra)
            new["gorev"] = {**new.get("gorev", {}), FINE: rep.get("gorev", {}).get(FINE)}
            if (sum(m["kabul"] for m in new["eslesmeler"])
                    < sum(bool(m.get("kabul")) for m in rep.get("eslesmeler") or [])):
                r = dict(rec)
                r["mukerrer"] = {**mk, "durum": "ayrildi", "neden": "temsilcinin_alintisi_tutmuyor"}
                recs[did] = r
                if did in (rep.get("kopyalar") or []):
                    recs[rid] = {**rep, "kopyalar": [x for x in rep["kopyalar"] if x != did]}
                st["ayrildi"].append(did)
                continue
        new["mukerrer"] = {**mk, "durum": "devralindi"}
        recs[did] = new
        rep = dict(rep)
        rep["kopyalar"] = sorted(set(rep.get("kopyalar") or []) | {did})
        recs[rid] = rep
        st["devralindi"] += 1
    return st


def resolve_ids(ws: Workspace, raw: list[str]) -> tuple[list[str], list[str]]:
    """Kullanıcının verdiği kimlikler → doc_id (tam ya da en az 6 haneli tek anlamlı önek).
    (bulunanlar, hatalar)."""
    have = sorted(p.stem for p in ws.text_dir.glob("*.txt")) if ws.text_dir.exists() else []
    hs = set(have)
    out, errs = [], []
    for x in raw:
        x = x.strip().lower()
        if not x:
            continue
        if x in hs:
            hit = [x]
        elif len(x) >= 6:
            hit = [h for h in have if h.startswith(x)]
        else:
            hit = []
        if len(hit) != 1:
            errs.append(f"{x}: " + ("bulunamadı" if not hit else f"{len(hit)} belgeyle eşleşiyor"))
        elif hit[0] not in out:
            out.append(hit[0])
    return out, errs


# -- ajan modu: iş paketleri -------------------------------------------------------------

README = """# bidr iş paketleri: {task} (sürüm {version})

Bu klasördeki her `<doc_id>.json` bir iş paketidir. Sağlayıcı/API çağrılmaz; işi sen
(ajan) yaparsın.

1. Paketi oku. `istem` alanı görevin tamamıdır (kurallar, ölçütler, belge metni);
   `sema` cevabın uyması gereken JSON şemasıdır.
2. İstemdeki kurallara uy: yalnız belge metnine dayan, alıntılar belgeden birebir olsun;
   "kanit_degil" ve "olcut_yok" geçerli cevaplardır.
3. Cevabı YALNIZ JSON olarak (açıklama, kod çiti yok) aynı klasörde `<doc_id>.out.json`
   dosyasına yaz. Var olan paketleri ve başka dosyaları değiştirme.
4. Paketler birbirinden bağımsızdır; paralel alt ajanlar kullanabilirsin (her alt ajana
   bir grup paket ver).
5. Bitince: `bidr decide apply -w <çalışma klasörü> --stage {stage} --model <ajan/model adı>`.
   Geçersiz cevaplar listelenir ve `GECERSIZ.md`'ye yazılır; onları yeniden yap.

Bekleyen paket: {n}
"""


def work_dir(ws: Workspace, stage: str) -> Path:
    return ws.root / "work" / stage


def _pkg_paths(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".out.json"))


def _write_pkg(d: Path, did: str, task: str, inputs: dict, meta: dict, backend: Backend,
               force: bool = False) -> bool:
    """Paketi yazar. İstem ya da görev sürümü değiştiyse (ya da `force`) eski cevabı
    `.out.json.eski` yapar. Yeni/değişmiş ise True."""
    r = backend.render_task(task, inputs)
    sha = _sha(r["prompt"])
    pkg = {"gorev": r["task"], "surum": str(r["version"]), "doc_id": did, "istem_sha": sha,
           "cikti_dosyasi": f"{did}.out.json", "istem": r["prompt"], "sema": r["schema"],
           "ozet": {"istem_karakter": len(r["prompt"]), "istem_token_tahmini": P.approx_tokens(r["prompt"]),
                    **{k: v for k, v in meta.items() if k in ("adaylar", "belge_bilgisi")},
                    "metin": meta.get("metin")},
           "meta": meta}
    p = d / f"{did}.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    if (old and not force and old.get("istem_sha") == sha
            and str(old.get("surum")) == str(r["version"])):
        return False
    out = d / f"{did}.out.json"
    if out.exists():
        out.replace(d / f"{did}.out.json.eski")
    p.write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
    return True


def _drop_unanswered_pkg(d: Path, did: str) -> None:
    """Mükerrer üyenin cevapsız eski paketi kalkar (ajan boşuna cevaplamasın)."""
    p = d / f"{did}.json"
    if p.exists() and not (d / f"{did}.out.json").exists():
        p.unlink()


def _stage_inputs(ctx: Context, did: str, rec: dict | None, stage: str):
    return coarse_inputs(ctx, did) if stage == "coarse" else fine_inputs(ctx, did, rec)


def prepare(ws_root: Path, stage: str, *, profile: str | None = "akademik_bolum",
            only_labeled: bool = False, limit: int | None = None, k: int = 5, max_aday: int = 6,
            backend: Backend | None = None, ctx: Context | None = None,
            redo: bool = False, only: list[str] | None = None, yes: bool = False) -> dict:
    """İş paketleri. coarse: atlanacak belgeler decisions.jsonl'e `atlandi` yazılır.
    fine: kaba kaydı olan belgeler; adayı olmayanlar doğrudan sonuçlanır.

    - İşlenmiş belge paketlenmez; ama görev sürümü/istem değiştiyse "eski" sayılır:
      `yes` yoksa yalnız özetlenir (`st["eski"]`, work/<aşama>/YENIDEN.json), `yes` ile
      kayıt `yeniden` işaretlenir ve paketlenir (eski cevap `.eski` olur).
    - `only`: yalnız bu belgeler, işlenmiş olsalar da yeniden paketlenir (eski cevap
      `.eski`); başka hiçbir kayıt ve cevap değişmez.
    - Metni aynı/çok yakın belgelerden yalnız temsilci paketlenir; üyeler kararı devralır.
    - `redo`: işlenmiş belgeleri de paketle (istem aynıysa var olan cevap korunur)."""
    backend = backend or Backend()
    task = STAGES[stage]
    if ctx is None:
        ctx = Context.load(ws_root, profile=profile, k=k, max_aday=max_aday)
    recs = load_decisions(ctx.ws)
    d = work_dir(ctx.ws, stage)
    d.mkdir(parents=True, exist_ok=True)
    force = set(only or ())
    st = {"paket": 0, "yeni": 0, "atlandi": 0, "kaba_yok": 0, "aday_yok": 0, "zaten_tamam": 0,
          "secmeli": 0, "mukerrer": 0, "devralindi": 0, "ayrildi": 0}
    ids = select_ids(ctx, only_labeled=only_labeled, limit=limit,
                     ids=sorted(force) if only is not None else None)
    eligible = []
    for did in ids:
        rec = recs.get(did)
        if stage == "coarse":
            why = ctx.skip_reason(did)
            if why:
                recs[did] = skipped_record(did, why, ctx)
                st["atlandi"] += 1
                continue
        elif not rec or rec.get("durum") != "ok" or "kaba" not in rec:
            st["kaba_yok"] += 1
            continue
        eligible.append(did)
    members = plan_members(ctx, [x for x in eligible if x not in force], recs, stage)
    stale: dict[str, str] = {}
    fresh: set[str] = set()

    def package(did: str, rec: dict | None, forced: bool) -> None:
        inputs, meta = _stage_inputs(ctx, did, rec, stage)
        if inputs is None:
            recs[did] = no_candidate(rec, meta)
            st["aday_yok"] += 1
            return
        st["paket"] += 1
        st["yeni"] += _write_pkg(d, did, task, inputs, meta, backend, force=forced)

    for did in eligible:
        rec = recs.get(did)
        forced = did in force
        done = stage_done(rec, stage)
        if done and not forced:
            why = staleness(ctx, did, rec, stage, backend)
            if why is None:
                fresh.add(did)
                if not redo:
                    st["zaten_tamam"] += 1
                    continue
            else:
                stale[did] = why
                if not yes:
                    continue
                rec = recs[did] = {**rec, "yeniden": {"asama": stage, "neden": why,
                                                      "onceki_surum": (rec.get("gorev") or {}).get(task)}}
                forced = True
        elif forced:
            st["secmeli"] += 1
            if done:
                rec = recs[did] = {**rec, "yeniden": {"asama": stage, "neden": "secmeli",
                                                      "onceki_surum": (rec.get("gorev") or {}).get(task)}}
        if did in members:
            _mark_member(ctx, recs, did, members[did], stage)
            _drop_unanswered_pkg(d, did)
            st["mukerrer"] += 1
            continue
        package(did, rec, forced)
    inh = inherit(ctx, recs, stage, backend.verify_quote)
    st["devralindi"], st["ayrildi"] = inh["devralindi"], len(inh["ayrildi"])
    for did in inh["ayrildi"]:              # temsilcinin alıntısı tutmadı: kendisi işlenir
        package(did, recs[did], False)
    save_decisions(ctx.ws, recs)
    # onay bekleyen eski kayıtlar
    f = d / RESTALE
    prev = {}
    if f.exists():
        try:
            prev = json.loads(f.read_text(encoding="utf-8")).get("belgeler") or {}
        except (OSError, ValueError):
            prev = {}
    pend = {x: w for x, w in {**prev, **({} if yes else stale)}.items()
            if x not in fresh and stage_done(recs.get(x), stage) and not (yes and x in stale)}
    st["eski"] = pend
    st["eski_cagri"] = sum(1 for x in pend if (recs[x].get("mukerrer") or {}).get("durum") != "devralindi")
    st["eski_token"] = sum(int(_section(recs[x], stage).get("istem_token_tahmini") or 0) for x in pend
                           if (recs[x].get("mukerrer") or {}).get("durum") != "devralindi")
    st["onay_gerekli"] = bool(pend)
    if pend:
        f.write_text(json.dumps({"gorev": task, "surum": task_version(task), "belgeler": pend,
                                 "model_cevabi": st["eski_cagri"], "istem_token_tahmini": st["eski_token"]},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    elif f.exists():
        f.unlink()
    pending = sum(1 for p in _pkg_paths(d) if not (d / f"{p.stem}.out.json").exists())
    (d / "README.md").write_text(README.format(task=task, version=task_version(task), stage=stage,
                                               n=pending), encoding="utf-8")
    st["bekleyen"] = pending
    st["klasor"] = str(d)
    return st


def _coarse_unchanged(rec: dict | None, pkg: dict, cevap_sha: str, out: dict) -> bool:
    """Bu kaba cevap zaten işlenmiş mi (yeniden işlemek ince kaydı silerdi)."""
    if not rec or rec.get("durum") != "ok" or "kaba" not in rec:
        return False
    if (rec.get("yeniden") or {}).get("asama") == "coarse":
        return False
    if (rec.get("mukerrer") or {}).get("durum") == "bekliyor":
        return False
    kb = rec["kaba"]
    if kb.get("istem_sha") != pkg["istem_sha"] or str((rec.get("gorev") or {}).get(COARSE)) != str(pkg["surum"]):
        return False
    if kb.get("cevap_sha"):
        return kb["cevap_sha"] == cevap_sha
    return ((kb.get("karar"), kb.get("olcutler") or [], kb.get("gerekce", ""))
            == (out.get("karar"), out.get("olcutler") or [], out.get("gerekce", "")))


def apply(ws_root: Path, stage: str, *, model: str = "ajan:belirtilmemis",
          backend: Backend | None = None, ctx: Context | None = None) -> dict:
    """`.out.json` cevaplarını doğrular ve decisions.jsonl'e işler. Şemaya uymayan ya da
    JSON olmayan cevap işlenmez (`gecersiz`); alıntısı tutmayan eşleşme kayda reddedilmiş
    olarak girer ve `alinti_tutmayan` listesinde yeniden yapılmak üzere gösterilir.
    Paket meta'sı (profil, adaylar) paketten okunur; profil yeniden hesaplanmaz.
    Zaten işlenmiş kaba cevap yeniden işlenmez (`degismedi`): ince kayıt korunur.
    Sonda temsilcisi sonuçlanan mükerrer üyeler kararı devralır."""
    backend = backend or Backend()
    task = STAGES[stage]
    if ctx is None:
        ctx = Context.load(ws_root, profile=None)
    recs = load_decisions(ctx.ws)
    d = work_dir(ctx.ws, stage)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "alinti_tutmayan": {},
          "eski_surum": [], "kanit_adi_red": {}, "baska_birim": [], "birim_belirsiz": []}
    for p in _pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        did = pkg["doc_id"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != task_version(task):
            st["eski_surum"].append(did)
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = backend.validate_output(task, raw)
        if out is None:
            st["gecersiz"][did] = errs[:5]
            continue
        extra = {"kip": "ajan", "istem_sha": pkg["istem_sha"], "cevap_sha": _sha(raw)}
        rec = recs.get(did)
        if stage == "coarse":
            if _coarse_unchanged(rec, pkg, extra["cevap_sha"], out):
                st["degismedi"] += 1
                continue
            if ((rec or {}).get("yeniden") or {}).get("neden") == "secmeli":
                # seçmeli yeniden işleme ince karara da iner: eski ince cevap kullanılmaz
                fo = work_dir(ctx.ws, "fine") / f"{did}.out.json"
                if fo.exists():
                    fo.replace(fo.with_name(fo.name + ".eski"))
            recs[did] = apply_coarse(did, out, pkg["meta"], model, extra)
        else:
            if not rec or "kaba" not in rec:
                st["gecersiz"][did] = ["decisions.jsonl'de kaba kayıt yok"]
                continue
            rec = apply_fine(ctx, did, rec, out, pkg["meta"], model, backend.verify_quote, extra)
            recs[did] = rec
            # başka birimin belgesi yeniden yapılacak iş değil: alıntı listesine girmez
            bad = [f"{m.get('yuva')}: {', '.join(m['denetim']['red'])}"
                   for m in rec["eslesmeler"] if not m["kabul"]
                   and set(m["denetim"]["red"]) - {"baska_birim"}]
            if bad:
                st["alinti_tutmayan"][did] = bad
            rel = rec["ince"]["birim_iliskisi"]
            if rel == BIRIM_DISI:
                st["baska_birim"].append(did)
            elif rel == BIRIM_BELIRSIZ:
                st["birim_belirsiz"].append(did)
            ka = rec["ince"].get("kanit_adi")
            if ka and ka["durum"] == "red":
                st["kanit_adi_red"][did] = ka
        st["islenen"] += 1
    inh = inherit(ctx, recs, stage, backend.verify_quote)
    st["devralindi"], st["ayrildi"] = inh["devralindi"], inh["ayrildi"]
    save_decisions(ctx.ws, recs)
    lines = [f"# Yeniden yapılacak ({task})", ""]
    for did, errs in st["gecersiz"].items():
        lines.append(f"- `{did}.json` — geçersiz cevap: " + "; ".join(errs))
    for did, bad in st["alinti_tutmayan"].items():
        lines.append(f"- `{did}.json` — reddedilen eşleşme (alıntı belgede birebir olmalı): "
                     + "; ".join(bad))
    if d.exists():
        g = d / "GECERSIZ.md"
        if len(lines) > 2:
            g.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    st["durum"] = stats_of(recs)
    return st


# -- sağlayıcı modu ---------------------------------------------------------------------------

def run(ws_root: Path, *, profile: str | None = "akademik_bolum", only_labeled: bool = False,
        limit: int | None = None, k: int = 5, max_aday: int = 6,
        candidates_name: str = "candidates.jsonl", backend: Backend | None = None,
        criteria: CriteriaSet | None = None, exclude_types: frozenset | None = None,
        log: Callable[[str], None] = print) -> tuple[Path, dict]:
    """Sağlayıcılı yol: her belge için kaba + ince `run_task` ile; hata belgeyi işaretler.
    Metni aynı/çok yakın belgelerden yalnız temsilci modele gider; üyeler devralır."""
    backend = backend or Backend()
    ctx = Context.load(ws_root, profile=profile, k=k, max_aday=max_aday,
                       candidates_name=candidates_name, criteria=criteria, exclude_types=exclude_types)
    if not ctx.cand:
        log(f"uyarı: {candidates_name} yok ya da boş; adaylar yalnız kaba seçimden")
    cfg_c = backend.load_model_config(ctx.ws.root, role="coarse")
    cfg_f = backend.load_model_config(ctx.ws.root, role="fine")
    cache = ctx.ws.root / ".cache" / "llm"
    recs = load_decisions(ctx.ws)

    def one(did: str) -> None:
        try:
            inputs, meta = coarse_inputs(ctx, did)
            res = backend.run_task(COARSE, inputs=inputs, model=cfg_c, cache_dir=cache)
            rec = apply_coarse(did, res.output, meta, _model_id(res, cfg_c),
                               {"kip": "saglayici", "onbellek": bool(getattr(res, "cached", False)),
                                "deneme": getattr(res, "attempts", None)})
            inputs, meta = fine_inputs(ctx, did, rec)
            if inputs is None:
                rec = no_candidate(rec, meta)
            else:
                res = backend.run_task(FINE, inputs=inputs, model=cfg_f, cache_dir=cache)
                rec = apply_fine(ctx, did, rec, res.output, meta, _model_id(res, cfg_f),
                                 backend.verify_quote,
                                 {"kip": "saglayici", "onbellek": bool(getattr(res, "cached", False)),
                                  "deneme": getattr(res, "attempts", None)})
        except Exception as e:  # model/şema hatası: belge işaretlenir, sürer
            rec = {"doc_id": did, "sema": SCHEMA, "durum": "hata", "profil": ctx.profile,
                   "hata": f"{type(e).__name__}: {e}"[:500]}
        recs[did] = rec
        log(f"{did} {rec['durum']} {rec.get('karar', '')}")
        save_decisions(ctx.ws, recs)     # her belgeden sonra: kesilirse kaldığı yer korunur

    todo = []
    for did in select_ids(ctx, only_labeled=only_labeled, limit=limit):
        why = ctx.skip_reason(did)
        if why:
            recs[did] = skipped_record(did, why, ctx)
            continue
        todo.append(did)
    # sağlayıcı kipi seçilen her belgeyi yeniden işler: temsilci, bu çalıştırmada işlenecek olandır
    members = plan_members(ctx, todo, {}, "coarse")
    for did in todo:
        if did not in members:
            one(did)
    for did in todo:
        if did not in members:
            continue
        _mark_member(ctx, recs, did, members[did], "coarse")
        inherit(ctx, recs, "coarse", backend.verify_quote)
        if (recs[did].get("mukerrer") or {}).get("durum") != "devralindi":
            one(did)                                   # temsilci hata verdi
            continue
        _mark_member(ctx, recs, did, members[did], "fine")
        if did in inherit(ctx, recs, "fine", backend.verify_quote)["ayrildi"] \
                or (recs[did].get("mukerrer") or {}).get("durum") != "devralindi":
            one(did)
        else:
            log(f"{did} devralindi ← {members[did]['temsilci']}")
    out = save_decisions(ctx.ws, recs)
    return out, stats_of(recs)
