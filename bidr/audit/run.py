"""Denetim çekirdeği: decisions.jsonl (+ inceleme kararları) → satırlar ve ölçüt özetleri.

Salt okunur girdi: `decisions.jsonl`, `documents.jsonl` (çalışma alanı), ölçütler ve yuva
etiketleri (paket verisi). Çıktılar `out` klasörüne (varsayılan çalışma alanı):
`review.xlsx`, `gaps.md`, `audit-olcutler.json`; `apply` ayrıca
`review-decisions.jsonl` ve `slot-tags-oneri.yaml`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl
from bidr.criteria.loader import load_criteria
from bidr.criteria.model import CriteriaSet, id_key
from bidr.criteria.profiles import load_profile
from bidr.criteria.slots import STAGE_OD, SlotTag, load_tags

from .rules import GEREKEN, KISA, KURUM_GENELI_TURLER, LINKS, criterion_od, effective_stage

SURUM = 1
FILES = {"xlsx": "review.xlsx", "gaps": "gaps.md", "json": "audit-olcutler.json",
         "decisions": "review-decisions.jsonl", "tag_oneri": "slot-tags-oneri.yaml"}
KARARLAR = ("kabul", "ret", "duzelt")
ETIKET_KARARLARI = ("onayla", "duzelt")
DEFAULT_PROFILE = "akademik_bolum"


def file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else ""


def load_review_decisions(out: Path) -> dict[str, dict]:
    p = Path(out) / FILES["decisions"]
    return {r["satir"]: r for r in read_jsonl(p)} if p.exists() else {}


@dataclass
class Audit:
    ws: Workspace
    out: Path
    profile: str | None
    cs: CriteriaSet
    tags: dict[str, SlotTag]
    rows: list[dict]
    criteria: list[dict]
    decisions_sha: str
    uyarilar: list[str] = field(default_factory=list)

    @property
    def by_key(self) -> dict[str, dict]:
        return {r["satir"]: r for r in self.rows}


def _tag_text(t: SlotTag | None) -> str:
    if t is None:
        return ""
    if t.uncertain:
        return "belirsiz (aşama içeriğe bağlı)"
    return ", ".join(t.stages) + " → OD" + "/".join(str(x) for x in t.od)


def _row(cs, tags, docs, rec, m, dec) -> dict:
    did = rec["doc_id"]
    doc = docs.get(did) or {}
    key = f"{did}|{m['yuva']}"
    flags = list((m.get("denetim") or {}).get("isaret") or [])
    olcut, yuva, asama = m["olcut"], m["yuva"], m.get("asama")
    etkin = effective_stage(asama, m.get("od_kabul"))
    if etkin != asama:
        flags.append("asama_dusuruldu")
    dtype = doc.get("doc_type") or (rec.get("belge_bilgisi") or {}).get("tur") or ""
    donem_ici = doc.get("donem_ici")
    sayilir, karar = True, None
    if dec:
        karar = dec["karar"]
    if karar == "ret":
        sayilir = False
        flags.append("insan_reddetti")
    elif karar == "duzelt":
        dz = dec.get("duzelt") or {}
        olcut = dz.get("olcut") or olcut
        yuva = dz.get("yuva") or yuva
        etkin = dz.get("asama") or etkin
        flags.append("insan_duzeltti")
    else:
        if dtype in KURUM_GENELI_TURLER:
            flags.append("kurum_geneli")
            if etkin and etkin != "planla":
                etkin = "planla"
                flags.append("uygulama_kaniti_eksik")
        if donem_ici is False and etkin and etkin != "planla":
            sayilir = False
            flags.append("donem_disi")
    od = STAGE_OD.get(etkin) if etkin else None
    if od is None:
        sayilir = False
    tag = tags.get(yuva)
    if (tag and etkin and not tag.uncertain and etkin not in tag.stages
            and "uygulama_kaniti_eksik" not in flags):
        flags.append("asama_yuva_etiketine_uymuyor")
    zayif = m.get("guven") == "dusuk"
    vurgu = []
    if od and od >= 4 and sayilir:
        vurgu.append(f"OD{od}'e yükselten" + (" (ÖNERİ etiket)" if tag and tag.state != "onayli" else ""))
    if zayif:
        vurgu.append("düşük güven")
    try:
        ymetin = cs.get_slot(yuva).text
    except KeyError:
        ymetin = ""
    return {
        "satir": key, "doc_id": did, "belge": doc.get("calisma_adi") or did, "belge_turu": dtype,
        "donem_ici": {True: "evet", False: "hayır"}.get(donem_ici, "?"),
        "olcut": olcut, "yuva": yuva, "yuva_metni": ymetin,
        "olcut_model": m["olcut"], "yuva_model": m["yuva"],
        "asama": asama, "od_model": m.get("od_onerisi"), "od_kabul": m.get("od_kabul"),
        "etkin_asama": etkin, "od": od, "sayilir": sayilir, "zayif": zayif,
        "etiket": _tag_text(tag), "etiket_durumu": tag.state if tag else "",
        "vurgu": "; ".join(vurgu), "guven": m.get("guven") or "",
        "isaretler": ", ".join(dict.fromkeys(flags)), "flags": list(dict.fromkeys(flags)),
        "alinti": m.get("alinti") or "", "gerekce": m.get("gerekce") or "",
        **_decision_cells(dec),
    }


def _decision_cells(dec: dict | None) -> dict:
    dec = dec or {}
    dz, et = dec.get("duzelt") or {}, dec.get("etiket") or {}
    return {"karar": dec.get("karar") or "", "duzelt_olcut": dz.get("olcut") or "",
            "duzelt_yuva": dz.get("yuva") or "", "duzelt_asama": dz.get("asama") or "",
            "etiket_karari": et.get("karar") or "", "etiket_yeni": ", ".join(et.get("asama") or []),
            "not": dec.get("not") or ""}


def _slot_links(cs, tags, cid) -> tuple[list, set[str]]:
    slots = [s for s in cs.get(cid).slots if not s.footnote]
    has: set[str] = set()
    for s in slots:
        t = tags.get(s.id)
        if t is None or t.uncertain:
            has.update(LINKS)
        else:
            has.update(x for x in t.stages if x in LINKS)
    return slots, has


def _criterion(cs, tags, cid, rows, allowed) -> dict:
    slots, has = _slot_links(cs, tags, cid)
    counted = [r for r in rows if r["sayilir"]]
    strong = {r["etkin_asama"] for r in counted if not r["zayif"]}
    every = {r["etkin_asama"] for r in counted}
    rs, ra = criterion_od(strong, has), criterion_od(every, has)
    filled = {r["yuva"] for r in counted}
    empty = [s for s in slots if s.id not in filled]
    halka = {}
    for x in LINKS:
        n_s = sum(1 for r in counted if r["etkin_asama"] == x and not r["zayif"])
        n_w = sum(1 for r in counted if r["etkin_asama"] == x and r["zayif"])
        halka[x] = ("var" if n_s else "dusuk" if n_w else "yuvasiz" if x not in has else "yok", n_s + n_w)
    kg = [r for r in counted if "kurum_geneli" in r["flags"]]
    kg_only = bool(kg) and "uygula" not in every
    eksik = []
    for x in rs.eksik:
        ys = [(s.id, s.text) for s in slots
              if (t := tags.get(s.id)) is None or t.uncertain or x in t.stages]
        eksik.append({"halka": x, "gereken": GEREKEN[x], "yuvasiz": x not in has,
                      "yuvalar": [{"yuva": i, "metin": t} for i, t in ys]})
    if counted and rs.od <= 2:
        grup = 1
    elif not counted:
        grup = 2
    elif rs.od == 3:
        grup = 3
    elif rs.od == 4:
        grup = 4
    else:
        grup = 9
    notlar = []
    if rs.ortuk_plan:
        notlar.append("plan belgesi önerilir: plan belgesi yok, uygulama/izleme kanıtı tanımlı sürecin örtük kanıtı sayıldı")
    if kg_only:
        notlar.append("yalnız kurum geneli düzenlemeyle eşleşti: bölümün uygulama kanıtı eksik")
    if ra.od > rs.od:
        notlar.append(f"düşük güvenli eşleşmeler doğrulanırsa OD{ra.od}")
    dd = sum("donem_disi" in r["flags"] for r in rows)
    if dd:
        notlar.append(f"{dd} eşleşme dönem dışı belgeden (plan dışı aşama sayılmadı)")
    if cid not in allowed:
        notlar.append("profil dışı ölçüt")
    sub = cs.get(cid)
    return {
        "olcut": cid, "baslik": sub.title, "od": rs.od, "od_dusuk_dahil": ra.od,
        "zincir": {x: {"durum": d, "eslesme": n} for x, (d, n) in halka.items()},
        "zincir_kisa": " ".join(f"{KISA[x]}{'+' if d == 'var' else '~' if d == 'dusuk' else '·' if d == 'yuvasiz' else '-'}"
                                for x, (d, _) in halka.items()),
        "duzeyler": {str(k): v for k, v in rs.duzeyler.items()},
        "sonraki_od": rs.sonraki, "eksik": eksik,
        "eslesme": len(counted), "belge": len({r["doc_id"] for r in counted}),
        "yuva_toplam": len(slots), "yuva_dolu": len(slots) - len(empty),
        "bos_yuvalar": [{"yuva": s.id, "metin": s.text,
                         "etiket": _tag_text(tags.get(s.id))} for s in empty],
        "kurum_geneli_yalniz": kg_only, "notlar": notlar, "oncelik_grubu": grup,
        "rubrik": {str(k): v for k, v in sub.rubric.items()},
    }


def priority_key(c: dict) -> tuple:
    return (c["oncelik_grubu"], -(c["yuva_toplam"] - c["yuva_dolu"]), id_key(c["olcut"]))


def build(ws_root: Path, *, out: Path | None = None, profile: str | None = None,
          criteria: CriteriaSet | None = None, review: dict[str, dict] | None = None) -> Audit:
    ws = Workspace(ws_root)
    out = Path(out).expanduser().resolve() if out else ws.root
    dpath = ws.root / "decisions.jsonl"
    if not dpath.exists():
        raise FileNotFoundError(f"decisions.jsonl yok: {dpath}")
    cs = criteria or load_criteria()
    tags = load_tags(cs)
    if profile is None:
        from bidr.init.config import load_section
        profile = (load_section(ws.root) or {}).get("profil") or DEFAULT_PROFILE
    allowed = set(load_profile(profile).allowed(cs)) if profile else {s.id for s in cs.sub_criteria}
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    review = load_review_decisions(out) if review is None else review
    rows, uy = [], []
    n_ince = 0
    for rec in read_jsonl(dpath):
        if rec.get("durum") != "ok" or rec.get("asama") != "ince":
            continue
        n_ince += 1
        for m in rec.get("eslesmeler") or []:
            if m.get("kabul"):
                rows.append(_row(cs, tags, docs, rec, m, review.get(f"{rec['doc_id']}|{m['yuva']}")))
    if not n_ince:
        uy.append("decisions.jsonl'de ince karar yok: tablo boş")
    rows.sort(key=lambda r: (id_key(r["olcut"]), r["yuva"], r["belge"]))
    by_c: dict[str, list] = {}
    for r in rows:
        by_c.setdefault(r["olcut"], []).append(r)
    ids = sorted(allowed | set(by_c), key=id_key)
    crits = [_criterion(cs, tags, c, by_c.get(c, []), allowed) for c in ids]
    return Audit(ws, out, profile, cs, tags, rows, crits, file_sha(dpath), uy)


def od_distribution(a: Audit) -> dict[int, int]:
    d = {k: 0 for k in range(1, 6)}
    for c in a.criteria:
        d[c["od"]] += 1
    return d


def write_outputs(a: Audit, *, xlsx: bool = True) -> dict[str, Path]:
    from . import report, sheet
    a.out.mkdir(parents=True, exist_ok=True)
    paths = {"gaps": a.out / FILES["gaps"], "json": a.out / FILES["json"]}
    paths["gaps"].write_text(report.gaps_md(a), encoding="utf-8")
    js = {"surum": SURUM, "calisma_alani": str(a.ws.root), "profil": a.profile,
          "kararlar_sha": a.decisions_sha, "od_dagilimi": od_distribution(a),
          "olcutler": a.criteria}
    paths["json"].write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
    if xlsx:
        paths["xlsx"] = a.out / FILES["xlsx"]
        sheet.write_review(a, paths["xlsx"])
    return paths


def audit(ws_root: Path, *, out: Path | None = None, profile: str | None = None) -> tuple[Audit, dict]:
    """Tabloyu üretir. Var olan review.xlsx'teki henüz uygulanmamış kararlar kaybolmaz:
    yeni tabloya taşınır (önceki tablo `review.onceki.xlsx` olarak saklanır)."""
    from . import sheet
    ws = Workspace(ws_root)
    outp = Path(out).expanduser().resolve() if out else ws.root
    applied = load_review_decisions(outp)
    carry: dict[str, dict] = {}
    old = outp / FILES["xlsx"]
    uy = []
    if old.exists():
        try:
            _, xrows = sheet.read_review(old)
        except Exception as e:   # bozuk/eski tablo: kararları taşıyamayız, üzerine yazmayız
            raise RuntimeError(f"var olan {old.name} okunamadı ({e}); taşıyın ya da silin") from e
        cs = load_criteria()
        for xr in xrows:
            dec, err = parse_decision(xr, cs)
            if dec and applied.get(dec["satir"]) != dec:
                carry[dec["satir"]] = dec
        if carry:
            uy.append(f"{len(carry)} karar tabloda vardı ama uygulanmamıştı: yeni tabloya taşındı "
                      f"(OD'ye yansıması için `bidr audit apply`)")
        old.replace(outp / "review.onceki.xlsx")
    a = build(ws_root, out=outp, profile=profile, review=applied)
    a.uyarilar.extend(uy)
    if carry:   # tabloda göster, OD hesabına katma (uygulanmadı)
        for r in a.rows:
            d = carry.get(r["satir"])
            if d:
                r.update(_decision_cells(d))
    paths = write_outputs(a)
    return a, paths


# -- karar okuma / uygulama ---------------------------------------------------------------

_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def _norm(v) -> str:
    return str(v or "").strip().translate(_TR).lower()


def parse_decision(xr: dict, cs: CriteriaSet) -> tuple[dict | None, str | None]:
    """Tablo satırı → karar kaydı. (None, None): karar boş. (None, hata): geçersiz."""
    from bidr.criteria.slots import STAGES
    k = _norm(xr.get("karar"))
    k = {"red": "ret", "reddet": "ret", "onay": "kabul", "duzeltme": "duzelt"}.get(k, k)
    sid = xr.get("satir") or ""
    if "|" not in sid:
        return None, "satır kimliği bozuk"
    did, yuva = sid.split("|", 1)
    et_k = _norm(xr.get("etiket_karari"))
    if not k:
        return (None, "etiket kararı var ama satır kararı boş") if et_k else (None, None)
    if k not in KARARLAR:
        return None, f"karar '{xr.get('karar')}' geçersiz (kabul/ret/duzelt)"
    rec = {"satir": sid, "doc_id": did, "olcut": xr.get("olcut_model") or yuva.split("/")[0],
           "yuva": yuva, "karar": k, "duzelt": None, "etiket": None,
           "not": str(xr.get("not") or "").strip()}
    if k == "duzelt":
        yo = str(xr.get("duzelt_yuva") or "").strip()
        oo = str(xr.get("duzelt_olcut") or "").strip()
        aa = _norm(xr.get("duzelt_asama")).replace(" ", "_")
        if not (yo or oo or aa):
            return None, "duzelt: en az bir düzelt sütunu dolu olmalı"
        if oo and not yo:
            return None, "duzelt: ölçüt değişince yuva da verilmeli (ör. B.1.2/3)"
        if yo:
            try:
                sl = cs.get_slot(yo)
            except KeyError:
                return None, f"duzelt: yuva '{yo}' yok"
            if sl.footnote:
                return None, f"duzelt: '{yo}' dipnot, kanıt yuvası değil"
            if oo and oo != sl.criterion:
                return None, f"duzelt: yuva {yo} ölçüt {oo}'a ait değil"
            oo = sl.criterion
        if aa and aa not in LINKS:
            return None, f"duzelt: aşama '{xr.get('duzelt_asama')}' geçersiz ({', '.join(LINKS)})"
        rec["duzelt"] = {"olcut": oo or None, "yuva": yo or None, "asama": aa or None}
    if et_k:
        if et_k not in ETIKET_KARARLARI:
            return None, f"yuva etiketi kararı '{xr.get('etiket_karari')}' geçersiz (onayla/duzelt)"
        yeni = [_norm(x).replace(" ", "_") for x in str(xr.get("etiket_yeni") or "").replace(";", ",").split(",")
                if x.strip()]
        if et_k == "duzelt":
            if not yeni or any(x not in STAGES for x in yeni):
                return None, f"yuva etiketi düzeltmesi: aşamalar {', '.join(STAGES)} içinden, virgülle"
            if "belirsiz" in yeni and len(yeni) > 1:
                return None, "yuva etiketi: belirsiz başka aşamayla birlikte olamaz"
        target = (rec["duzelt"] or {}).get("yuva") or yuva
        rec["etiket"] = {"karar": et_k, "yuva": target, "asama": list(dict.fromkeys(yeni)) if et_k == "duzelt" else []}
    return rec, None


def review_state(out: Path, ws_root: Path | None = None) -> dict:
    """Tamamlanma denetimi için salt okunur durum."""
    from . import sheet
    out = Path(out)
    x = out / FILES["xlsx"]
    st = {"tablo": x.exists(), "guncel": False, "satir": 0, "kararli": 0, "gecersiz": 0,
          "uygulanmamis": 0}
    if not x.exists():
        return st
    meta, xrows = sheet.read_review(x)
    dsha = file_sha(Path(ws_root or out) / "decisions.jsonl")
    st["guncel"] = meta.get("kararlar_sha") == dsha
    applied = load_review_decisions(out)
    cs = load_criteria()
    st["satir"] = len(xrows)
    for xr in xrows:
        dec, err = parse_decision(xr, cs)
        if err:
            st["gecersiz"] += 1
        elif dec:
            st["kararli"] += 1
            if applied.get(dec["satir"]) != dec:
                st["uygulanmamis"] += 1
    return st


def apply(ws_root: Path, *, out: Path | None = None, profile: str | None = None) -> dict:
    """review.xlsx → review-decisions.jsonl (+ slot-tags-oneri.yaml); gaps.md ve
    audit-olcutler.json yeni kararlarla yeniden yazılır (tablo yeniden yazılmaz)."""
    from . import sheet
    ws = Workspace(ws_root)
    outp = Path(out).expanduser().resolve() if out else ws.root
    x = outp / FILES["xlsx"]
    if not x.exists():
        raise FileNotFoundError(f"{x} yok: önce `bidr audit`")
    _, xrows = sheet.read_review(x)
    cs = load_criteria()
    prev = load_review_decisions(outp)
    hatalar, yeni = {}, {}
    bos = 0
    for xr in xrows:
        dec, err = parse_decision(xr, cs)
        if err:
            hatalar[xr.get("satir") or "?"] = err
        elif dec:
            yeni[dec["satir"]] = dec
        else:
            bos += 1
    merged = {**prev, **yeni}
    for sid in hatalar:            # geçersiz satırın eski kararı da geçersizdir
        merged.pop(sid, None)
    write_jsonl(outp / FILES["decisions"], [merged[k] for k in sorted(merged)])
    oneri = write_tag_proposals(outp, merged, cs)
    a = build(ws.root, out=outp, profile=profile, review=merged)
    write_outputs(a, xlsx=False)
    from collections import Counter
    return {"satir": len(xrows), "kararli": len(yeni), "bos": bos, "gecersiz": hatalar,
            "karar": dict(Counter(d["karar"] for d in yeni.values())),
            "etiket_onerisi": oneri, "od_dagilimi": od_distribution(a)}


def write_tag_proposals(out: Path, decisions: dict[str, dict], cs: CriteriaSet) -> int:
    """Yuva etiketi kararlarını öneri dosyasına toplar. Paket verisini DEĞİŞTİRMEZ."""
    import yaml
    from bidr.criteria.slots import read_tags
    tags = load_tags(cs)
    by: dict[str, list] = {}
    for d in decisions.values():
        e = d.get("etiket")
        if e:
            by.setdefault(e["yuva"], []).append((d["satir"], e, d.get("not") or ""))
    oneriler, celiski = [], []
    for yuva in sorted(by, key=lambda s: (id_key(s.split("/")[0]), int(s.split("/")[1]))):
        t = tags.get(yuva)
        cur = list(t.stages) if t else []
        variants = {}
        for sid, e, nt in by[yuva]:
            st = tuple(cur) if e["karar"] == "onayla" else tuple(e["asama"])
            variants.setdefault(st, []).append((sid, nt))
        if len(variants) > 1:
            celiski.append({"yuva": yuva, "secenekler": [{"asama": list(k), "satirlar": [s for s, _ in v]}
                                                         for k, v in variants.items()]})
            continue
        (st, src), = variants.items()
        oneriler.append({
            "yuva": yuva, "metin": cs.get_slot(yuva).text,
            "mevcut": {"asama": cur, "od": list(t.od) if t else [], "durum": t.state if t else None},
            "oneri": {"asama": list(st), "od": sorted({STAGE_OD[x] for x in st if x in STAGE_OD}),
                      "durum": "onayli"},
            "degisiklik": "yalniz_onay" if list(st) == cur else "asama_degisiyor",
            "satirlar": [s for s, _ in src], "notlar": [n for _, n in src if n]})
    p = Path(out) / FILES["tag_oneri"]
    if not oneriler and not celiski:
        if p.exists():
            p.unlink()
        return 0
    head = ("# Yuva etiketi ÖNERİLERİ (bidr audit apply). Bu dosya hiçbir şeyi değiştirmez.\n"
            "# Kullanıcı onaylarsa `bidr/data/criteria/slot-tags-yokak-2025.yaml`'daki ilgili kayıtlara\n"
            "# asama/od/durum olarak elle (ya da şefin aracıyla) işlenir; `bidr criteria` doğrulaması sonra\n"
            "# çalıştırılmalı. Çelişkiler (aynı yuvaya farklı öneri) önce çözülmeli.\n")
    body = {"surum": 1, "olcut_surumu": read_tags().get("olcut_surumu"), "oneriler": oneriler,
            "celiskiler": celiski}
    p.write_text(head + yaml.safe_dump(body, allow_unicode=True, sort_keys=False, width=110), encoding="utf-8")
    return len(oneriler)
