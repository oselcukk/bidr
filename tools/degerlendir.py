#!/usr/bin/env python3
"""Kontrollü değerlendirme setleri (`evalsets/`) ile bidr çıktılarını karşılaştırır.

Sistemin kendi doğrulaması ("35/35 doğrulandı") dış doğrulama değildir. Bu araç, bilinen
hataları içeren küçük sentetik setlerde yazıcı/doğrulayıcının ve OD hesabının hatayı yakalayıp
yakalamadığını ölçer. Model çağırmaz. Ayrıntı: evalsets/README.md.

Alt komutlar:
    denetle        setin kendi tutarlılığı (dosyalar, birebir alıntılar, ölçüt/yuva, kişi verisi)
    sentetik       setin beklenen (ideal) ya da tuzağa düşen (naif) karar kayıtlarından sentetik
                   çalışma alanı (decisions.jsonl, documents.jsonl, text/): audit'i model olmadan sınar
    karsilastir    bir çalışma alanının çıktılarını beklenen.yaml ile karşılaştırır (tablo)
    taslak-sinama  desteklenmeyen tek cümlenin yayıma hazır durumu engelleyip engellemediğini
                   gerçek verify/render koduyla sınar (geçici klasörde)

Kullanım:
    python tools/degerlendir.py denetle --set evalsets/tuzak
    python tools/degerlendir.py sentetik --set evalsets/od-sinir --mod naif --out /tmp/ws
    python tools/degerlendir.py karsilastir --set evalsets/tuzak -w WS [--inceleme DIR]
        [--md rapor.md] [--json sonuc.json] [--ajan-paketi DIR] [--ajan-cevaplari DIR]
    python tools/degerlendir.py taslak-sinama
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from bidr.criteria.slots import STAGE_OD  # noqa: E402
from bidr.identify.text import fold  # noqa: E402

SURUM = 1
MODLAR = ("ideal", "naif")
KANIT = ("evet", "hayir", "gecmis", "dogrulanmali")
SAYILMAZ = ("hayir", "gecmis", "dogrulanmali")     # rapor yılı halkası kurmaması beklenen belge
LINKS = ("planla", "uygula", "kontrol_et", "onlem_al", "ozgun")
GENEL = ("kurum_geneli", "fakulte_geneli")
BASKA = "baska_birim"
EPOSTA = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
UNVAN = re.compile(r"\b(Prof|Doç|Dr|Arş\.\s*Gör|Öğr\.\s*Gör|Öğr\.\s*Üyesi)\.", re.I)
KURUM_ADI = re.compile(r"(\w+)\s+(?:Üniversitesi|ÜNİVERSİTESİ|Universitesi)")
SERBEST_KURUM = {"ornek"}                           # hayalî kurum adı (fold edilmiş)
AJAN_TALIMAT = (
    "Aşağıdaki cümleler bir BİDR ölçüt açıklamasından alınmıştır. Her cümle için, verilen "
    "YAZILMAMASI GEREKEN İDDİA'yı (doğrudan ya da başka sözcüklerle) ileri sürüp sürmediğine karar "
    "ver. Belge metni yalnız bağlam içindir; cümlenin doğruluğunu değil, iddiayı taşıyıp "
    "taşımadığını değerlendir. Çıktı (JSON): {\"karar\": \"geciyor\" | \"gecmiyor\", "
    "\"yerler\": [cümle yerleri], \"gerekce\": \"...\"}.")


def norm(s: str) -> str:
    return " ".join(str(s or "").split())


def fnorm(s: str) -> str:
    return fold(norm(s))


def sha16(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


# -- set ------------------------------------------------------------------------------------

@dataclass
class Belge:
    dosya: str
    yol: Path
    kayit: dict
    vaka: str | None = None

    @property
    def doc_id(self) -> str:
        return sha16(self.yol)

    @property
    def ad(self) -> str:
        return Path(self.dosya).stem

    def eslesmeler(self, mod: str = "ideal") -> list[dict]:
        n = self.kayit.get("naif") or {}
        if mod == "naif" and "eslesmeler" in n:
            return list(n["eslesmeler"] or [])
        return list(self.kayit.get("eslesmeler") or [])

    def birim(self, mod: str = "ideal") -> str:
        n = self.kayit.get("naif") or {}
        if mod == "naif" and n.get("birim_iliskisi"):
            return n["birim_iliskisi"]
        return self.kayit.get("birim_iliskisi") or "kendi"

    @property
    def naif_farkli(self) -> bool:
        return bool(self.kayit.get("naif"))


@dataclass
class EvalSet:
    yol: Path
    veri: dict
    belgeler: list[Belge]
    olcutler: dict[str, dict]                       # ölçüt → {od, eksik, not_icermeli, vaka, bilinen_acik}
    vakalar: list[dict] = field(default_factory=list)

    @property
    def ad(self) -> str:
        return self.veri.get("set") or self.yol.name

    @property
    def donem(self) -> int:
        return int(self.veri.get("donem") or 0)

    def belge(self, ad: str) -> Belge:
        for b in self.belgeler:
            if b.dosya == ad or b.ad == ad or Path(b.dosya).name == ad:
                return b
        raise KeyError(ad)


def load_set(set_dir: Path) -> EvalSet:
    set_dir = Path(set_dir).expanduser().resolve()
    veri = yaml.safe_load((set_dir / "beklenen.yaml").read_text(encoding="utf-8")) or {}
    kok = set_dir / "belgeler"
    belgeler: list[Belge] = []
    olcutler: dict[str, dict] = {}
    for b in veri.get("belgeler") or []:
        belgeler.append(Belge(b["dosya"], kok / b["dosya"], b))
    for v in veri.get("vakalar") or []:
        for b in v.get("belgeler") or []:
            belgeler.append(Belge(b["dosya"], kok / b["dosya"], b, v["id"]))
        olcutler[v["olcut"]] = {"od": v["beklenen_od"], "eksik": v.get("eksik_halka"),
                                "not_icermeli": v.get("not_icermeli") or [], "vaka": v["id"],
                                "bilinen_acik": v.get("bilinen_acik"), "gerekce": v.get("eksik_kosul")}
    for c, o in (veri.get("olcutler") or {}).items():
        olcutler[c] = {"od": o["od"], "eksik": o.get("eksik"), "not_icermeli": o.get("not_icermeli") or [],
                       "vaka": None, "bilinen_acik": o.get("bilinen_acik"), "gerekce": o.get("gerekce")}
    return EvalSet(set_dir, veri, belgeler, olcutler, list(veri.get("vakalar") or []))


# -- denetle ----------------------------------------------------------------------------------

def check_set(es: EvalSet) -> list[str]:
    """Setin kendi tutarlılığı: boş liste = sorun yok."""
    from bidr.criteria.loader import load_criteria
    cs = load_criteria()
    err: list[str] = []
    ids: dict[str, str] = {}
    for b in es.belgeler:
        k = b.kayit
        if not b.yol.exists():
            err.append(f"{b.dosya}: dosya yok")
            continue
        text = b.yol.read_text(encoding="utf-8")
        did = b.doc_id
        if did in ids:
            err.append(f"{b.dosya}: içerik {ids[did]} ile aynı (doc_id çakışması)")
        ids[did] = b.dosya
        if k.get("kanit") not in KANIT:
            err.append(f"{b.dosya}: kanit '{k.get('kanit')}' ({' | '.join(KANIT)})")
        od = k.get("en_yuksek_od")
        if not isinstance(od, int) or not 1 <= od <= 5:
            err.append(f"{b.dosya}: en_yuksek_od 1..5 olmalı")
        elif k.get("kanit") in SAYILMAZ and od != 1:
            err.append(f"{b.dosya}: kanit {k.get('kanit')} iken en_yuksek_od 1 olmalı")
        if not k.get("belge_turu"):
            err.append(f"{b.dosya}: belge_turu yok")
        for mod in MODLAR:
            seen = set()
            for m in b.eslesmeler(mod):
                where = f"{b.dosya} ({mod}) {m.get('yuva')}"
                if m.get("asama") not in LINKS:
                    err.append(f"{where}: aşama '{m.get('asama')}'")
                try:
                    slot = cs.get_slot(m["yuva"])
                    if not m["yuva"].startswith(m["olcut"] + "/"):
                        err.append(f"{where}: yuva ölçüte ait değil ({m['olcut']})")
                    elif slot.footnote:
                        err.append(f"{where}: dipnot yuvası")
                except KeyError:
                    err.append(f"{where}: yuva yok")
                if m["yuva"] in seen:
                    err.append(f"{where}: aynı belgede yuva iki kez")
                seen.add(m["yuva"])
                if norm(m.get("alinti")) not in norm(text):
                    err.append(f"{where}: alıntı belgede birebir yok: «{m.get('alinti')}»")
            if mod == "ideal" and k.get("kanit") == "evet" and not b.eslesmeler(mod):
                err.append(f"{b.dosya}: kanit evet ama ideal eşleşme yok")
        for y in k.get("yazilmamali") or []:
            if not y.get("iddia") or not y.get("anahtar"):
                err.append(f"{b.dosya}: yazilmamali kaydında iddia/anahtar eksik")
        if EPOSTA.search(text):
            err.append(f"{b.dosya}: e-posta adresi içeriyor")
        if UNVAN.search(text):
            err.append(f"{b.dosya}: unvan/kişi adı kalıbı içeriyor ({UNVAN.search(text).group(0)})")
        for m in KURUM_ADI.finditer(text):
            if fold(m.group(1)) not in SERBEST_KURUM:
                err.append(f"{b.dosya}: hayalî olmayan kurum adı olabilir: «{m.group(0)}»")
    for c, o in es.olcutler.items():
        try:
            cs.get(c)
        except KeyError:
            err.append(f"ölçüt yok: {c}")
        if not isinstance(o.get("od"), int) or not 1 <= o["od"] <= 5:
            err.append(f"{c}: od 1..5 olmalı")
    return err


# -- sentetik çalışma alanı ----------------------------------------------------------------------

def _match(m: dict, rel: str) -> dict:
    od = STAGE_OD[m["asama"]]
    kabul = rel != BASKA
    cap = rel in GENEL and od > 2
    return {"olcut": m["olcut"], "yuva": m["yuva"], "asama": m["asama"], "od_onerisi": od,
            "alinti": norm(m["alinti"]), "gerekce": "sentetik (evalsets)", "guven": "orta",
            "denetim": {"red": [] if kabul else [BASKA],
                        "isaret": ["uygulama_kaniti_eksik"] if cap and kabul else []},
            "od_kabul": (2 if cap else od) if kabul else None, "kabul": kabul}


def decision_record(b: Belge, mod: str) -> dict:
    """Belgenin (ideal ya da naif) ince karar kaydı; bidr decide apply_fine biçiminde."""
    rel = b.birim(mod)
    ms = [_match(m, rel) for m in b.eslesmeler(mod)]
    if any(m["kabul"] for m in ms):
        karar = "olcut_var"
    elif rel == BASKA or b.kayit.get("kanit") == "hayir":
        karar = "kanit_degil"
    else:
        karar = "olcut_yok"
    olcutler = sorted({m["olcut"] for m in ms if m["kabul"]})
    return {"doc_id": b.doc_id, "durum": "ok", "asama": "ince", "karar": karar,
            "ince": {"karar": "kanit_degil" if karar == "kanit_degil" else "olcut_var" if ms else "olcut_yok",
                     "gerekce": f"sentetik ({mod})", "birim_iliskisi": rel,
                     "birim_iliskisi_kaynagi": "model", "model": f"evalsets:{mod}"},
            "eslesmeler": ms, "olcutler": olcutler,
            "reddedilen_eslesme": sum(not m["kabul"] for m in ms)}


def document_record(b: Belge, donem: int) -> dict:
    t = b.kayit.get("tarih")
    t = str(t) if t else None
    return {"doc_id": b.doc_id, "doc_type": b.kayit["belge_turu"], "tarih": t, "donem": donem,
            "donem_ici": (int(t[:4]) == donem) if t else None, "akademik_donem": [],
            "calisma_adi": b.ad}


def make_workspace(es: EvalSet, out: Path, mod: str = "ideal", vaka: str | None = None) -> Path:
    """Sentetik çalışma alanı: `bidr audit` model olmadan çalıştırılabilir."""
    if mod not in MODLAR:
        raise ValueError(f"mod: {mod} ({' | '.join(MODLAR)})")
    out = Path(out).expanduser().resolve()
    (out / "text").mkdir(parents=True, exist_ok=True)
    bs = [b for b in es.belgeler if vaka is None or b.vaka == vaka]
    if not bs:
        raise ValueError(f"vaka yok: {vaka}")
    with open(out / "decisions.jsonl", "w", encoding="utf-8") as f:
        for b in bs:
            f.write(json.dumps(decision_record(b, mod), ensure_ascii=False) + "\n")
    with open(out / "documents.jsonl", "w", encoding="utf-8") as f:
        for b in bs:
            f.write(json.dumps(document_record(b, es.donem), ensure_ascii=False) + "\n")
    for b in bs:
        (out / "text" / f"{b.doc_id}.txt").write_text(b.yol.read_text(encoding="utf-8"), encoding="utf-8")
    with open(out / "evalset.json", "w", encoding="utf-8") as f:
        json.dump({"set": es.ad, "mod": mod, "vaka": vaka, "belge": len(bs)}, f, ensure_ascii=False)
    return out


# -- karşılaştırma ----------------------------------------------------------------------------------

def od_class(sistem: int, beklenen: int) -> str:
    d = sistem - beklenen
    if d == 0:
        return "tam"
    if d > 0:
        return f"fazla (+{d})"
    return "-1" if d == -1 else f"eksik ({d})"


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _doc_map(es: EvalSet, ws: Path) -> dict[str, str]:
    """dosya → doc_id. İçerik özeti esas; inventory.csv'de aynı adlı (karıştırılmamış) kopya varsa
    o da eşlenir (ör. set klasörü doğrudan ingest edildiyse)."""
    out = {b.dosya: b.doc_id for b in es.belgeler}
    inv = ws / "inventory.csv"
    if inv.exists():
        with open(inv, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        by_sha = {r.get("doc_id"): r for r in rows}
        for b in es.belgeler:
            if out[b.dosya] in by_sha:
                continue
            for r in rows:
                if (r.get("rel_path") or "").replace("\\", "/").endswith(b.dosya):
                    out[b.dosya] = r["doc_id"]
                    break
    return out


def _audit_rows(ws: Path, inceleme: Path | None) -> tuple[list[dict], list[dict], list[str]]:
    """(satırlar, ölçüt özetleri, uyarılar): audit çekirdeği salt okunur çalıştırılır; ölçüt
    OD'si için varsa audit-olcutler.json (gerçek çıktı) esas alınır."""
    from bidr.audit.run import build
    uy: list[str] = []
    rows, crits = [], []
    try:
        a = build(ws, out=inceleme)
        rows, crits = a.rows, a.criteria
        uy += a.uyarilar
    except Exception as e:      # eksik çalışma alanı: karar kayıtlarıyla devam
        uy.append(f"audit çekirdeği çalışmadı ({e}); belge sonuçları decisions.jsonl'den")
    js = (inceleme or ws) / "audit-olcutler.json"
    if js.exists():
        crits = json.loads(js.read_text(encoding="utf-8")).get("olcutler") or crits
    else:
        uy.append("audit-olcutler.json yok: ölçüt OD'si audit çekirdeğinden hesaplandı")
    return rows, crits, uy


def compare_docs(es: EvalSet, ws: Path, rows: list[dict], decisions: dict[str, dict],
                 ids: dict[str, str]) -> list[dict]:
    from bidr.decide.run import record_unit_relation
    by_doc: dict[str, list[dict]] = {}
    for r in rows:
        by_doc.setdefault(r["doc_id"], []).append(r)
    out = []
    for b in es.belgeler:
        k = b.kayit
        did = ids[b.dosya]
        rec = decisions.get(did)
        rs = by_doc.get(did, [])
        counted = [r for r in rs if r["sayilir"] and not r.get("zayif")]
        if not rows and rec:      # audit çekirdeği yoksa: kabul edilmiş eşleşmelerin kod OD'si
            counted = [{"olcut": m["olcut"], "etkin_asama": m.get("asama"), "od": m.get("od_kabul")}
                       for m in rec.get("eslesmeler") or [] if m.get("kabul") and m.get("od_kabul")]
        s_od = max([r["od"] for r in counted if r.get("od")] or [1])
        e_od = int(k["en_yuksek_od"])
        birim = record_unit_relation(rec) if rec else None
        if rec is None:
            sonuc = "işlenmemiş"
        else:
            ok = s_od <= e_od if k["kanit"] == "evet" else s_od == 1
            if k.get("birim_iliskisi") == BASKA and birim != BASKA and counted:
                ok = False
            sonuc = "yakalandı" if ok else "kaçırıldı"
        flags = sorted({f for r in rs for f in r.get("flags") or []})
        out.append({
            "dosya": b.dosya, "vaka": b.vaka, "tuzak": k.get("tuzak") or "", "doc_id": did,
            "beklenen": {"kanit": k["kanit"], "birim": k.get("birim_iliskisi"), "od": e_od,
                         "halkalar": sorted({f"{m['olcut']}:{m['asama']}" for m in b.eslesmeler()})},
            "sistem": {"karar": (rec or {}).get("karar"), "birim": birim, "od": s_od,
                       "halkalar": sorted({f"{r['olcut']}:{r['etkin_asama']}" for r in counted}),
                       "isaretler": flags},
            "sonuc": sonuc, "od_sonuc": od_class(s_od, e_od) if rec else "—",
        })
    return out


def compare_criteria(es: EvalSet, crits: list[dict]) -> list[dict]:
    by = {c["olcut"]: c for c in crits}
    out = []
    for cid, e in sorted(es.olcutler.items()):
        c = by.get(cid)
        s_od = c["od"] if c else 1
        s_eksik = [x["halka"] for x in (c or {}).get("eksik") or []]
        notlar = (c or {}).get("notlar") or []
        notes_ok = all(any(fold(n_) in fold(x) for x in notlar) for n_ in e.get("not_icermeli") or [])
        out.append({"olcut": cid, "vaka": e.get("vaka"), "beklenen_od": e["od"], "sistem_od": s_od,
                    "od_sonuc": od_class(s_od, e["od"]),
                    "beklenen_eksik": e.get("eksik"), "sistem_eksik": s_eksik,
                    "eksik_ayni": None if e.get("eksik") is None else sorted(e["eksik"]) == sorted(s_eksik),
                    "notlar_tamam": notes_ok, "bilinen_acik": e.get("bilinen_acik"),
                    "audit_kaydi": bool(c)})
    return out


def load_index(ws: Path) -> dict[tuple[str, str], set[str]]:
    """evidence-index.csv → {(ölçüt, kanıt no): {doc_id, kopyalar…}}."""
    p = ws / "evidence-index.csv"
    out: dict[tuple[str, str], set[str]] = {}
    if not p.exists():
        return out
    with open(p, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            ids = {r.get("doc_id") or ""} | {x.strip() for x in (r.get("kopyalar") or "").split(";")}
            out[(r.get("olcut") or "", r.get("kanit_no") or "")] = {x for x in ids if x}
    return out


def load_texts(ws: Path) -> dict[str, dict]:
    d = ws / "texts"
    out = {}
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                t = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if t.get("olcut"):
                out[t["olcut"]] = t
    return out


def sentences(t: dict, index: dict) -> list[dict]:
    from bidr.write import text as T
    out = []
    for i, p in enumerate(t.get("paragraflar") or [], 1):
        for j, s in enumerate(T.split_sentences(p.get("metin") or ""), 1):
            nos = T.citations(s)
            docs = set().union(*[index.get((t["olcut"], n), set()) for n in nos]) if nos else set()
            out.append({"yer": f"{t['olcut']}:p{i}.c{j}", "metin": s, "atiflar": nos, "belgeler": sorted(docs)})
    return out


def check_claims(es: EvalSet, texts: dict[str, dict], index: dict, ids: dict[str, str],
                 ajan: dict[str, dict] | None = None) -> list[dict]:
    """Yazılmaması gereken iddialar: anahtar ifade denetimi (+ varsa ajan cevabı)."""
    sents = {c: sentences(t, index) for c, t in texts.items()}
    out = []
    for b in es.belgeler:
        for n, y in enumerate(b.kayit.get("yazilmamali") or [], 1):
            cid = f"{b.ad}#{n}"
            scope = [y["olcut"]] if y.get("olcut") else sorted(texts)
            pool = [s for c in scope for s in sents.get(c, [])]
            keys = [fnorm(a) for a in y["anahtar"]]
            exc = [fnorm(a) for a in y.get("haric") or []]
            atif = y.get("atif_sart", True)
            ihlal, supheli = [], []
            for s in pool:
                f = fnorm(s["metin"])
                if not any(k in f for k in keys) or any(x in f for x in exc):
                    continue
                if not atif or ids[b.dosya] in s["belgeler"]:
                    ihlal.append(s)
                else:
                    supheli.append(s)
            if not pool:
                durum = "metin yok"
            elif ihlal:
                durum = "GEÇTİ"
            else:
                durum = "geçmedi"
            rec = {"id": cid, "dosya": b.dosya, "olcut": y.get("olcut") or "", "iddia": y["iddia"],
                   "durum": durum, "ihlal": [{"yer": s["yer"], "metin": s["metin"]} for s in ihlal],
                   "supheli": [{"yer": s["yer"], "metin": s["metin"]} for s in supheli],
                   "ajan": None}
            if ajan and cid in ajan:
                rec["ajan"] = ajan[cid].get("karar")
            out.append(rec)
    return out


def write_agent_packages(es: EvalSet, texts: dict[str, dict], index: dict, d: Path) -> int:
    """Her yazılmaması gereken iddia için ajan iş paketi (`<id>.json`; cevap `<id>.out.json`)."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for b in es.belgeler:
        for i, y in enumerate(b.kayit.get("yazilmamali") or [], 1):
            scope = [y["olcut"]] if y.get("olcut") else sorted(texts)
            cum = [s for c in scope if c in texts for s in sentences(texts[c], index)]
            if not cum:
                continue
            cid = f"{b.ad}#{i}"
            fn = cid.replace("#", "--")
            pkg = {"surum": SURUM, "gorev": "iddia_denetimi", "id": cid, "talimat": AJAN_TALIMAT,
                   "iddia": y["iddia"], "belge": {"dosya": b.dosya, "metin": b.yol.read_text(encoding="utf-8")},
                   "cumleler": cum, "cikti_dosyasi": f"{fn}.out.json"}
            (d / f"{fn}.json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1), encoding="utf-8")
            n += 1
    return n


def read_agent_answers(d: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(Path(d).glob("*.out.json")):
        try:
            a = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if a.get("karar") in ("geciyor", "gecmiyor"):
            out[p.name[:-len(".out.json")].replace("--", "#")] = a
    return out


def check_versions(es: EvalSet, index: dict, ids: dict[str, str]) -> list[dict]:
    out = []
    for g in es.veri.get("surum_gruplari") or []:
        gid = {ids[es.belge(x).dosya] for x in g["belgeler"]}
        rep = ids[es.belge(g["temsilci"]).dosya] if g.get("temsilci") else None
        if not index:
            out.append({"grup": g["ad"], "durum": "dosyalama yok (evidence-index.csv)"})
            continue
        rows = [(k, v) for k, v in index.items() if v & gid]
        per_c: dict[str, int] = {}
        for (c, _), _v in rows:
            per_c[c] = per_c.get(c, 0) + 1
        tek = all(n == 1 for n in per_c.values())
        out.append({"grup": g["ad"], "durum": "tek kanıt" if tek else "ayrı kanıt",
                    "olcut_satir": per_c, "temsilci_listede": any(rep in v for _, v in rows) if rep else None})
    return out


def check_publish(ws: Path) -> dict:
    """Desteklenmeyen (ya da kısmen desteklenen) cümlesi olan metin yayıma hazır durumu
    engelliyor mu: metin `dogrulandi` olmamalı; render TASLAK damgası basmalı (ya da metin
    insan kararıyla çıkarılmış olmalı)."""
    from bidr.write import run as W
    texts = load_texts(ws)
    log = {r["olcut"]: r for r in _read_jsonl(ws / "verify.jsonl")}
    man_p = ws / ".bidr-render.json"
    man = json.loads(man_p.read_text(encoding="utf-8")) if man_p.exists() else None
    rows = []
    for c, t in sorted(texts.items()):
        rec = log.get(c)
        bad = [x for x in (rec or {}).get("cumleler") or [] if x.get("karar") != "destekleniyor"]
        kod = (rec or {}).get("kod_denetimi") or []
        stale = bool(rec) and rec.get("metin_sha") != W.text_sha(t)
        cikar = t.get("durum") == "reddedildi" and t.get("insan_karari") == "cikar"
        engel_gerekli = bool(bad or kod or (rec or {}).get("durum") == "reddedildi")
        if not rec:
            durum = "doğrulama kaydı yok" + (" (metin dogrulandi diyor!)" if t.get("durum") == "dogrulandi" else "")
        elif stale:
            durum = "doğrulama kaydı eski (metin değişmiş)"
        elif not engel_gerekli:
            durum = "desteklenmeyen cümle yok"
        elif t.get("durum") == "dogrulandi":
            durum = "ENGELLEMİYOR: metin dogrulandi"
        elif cikar:
            durum = "engelliyor (metin insan kararıyla rapordan çıkarıldı)"
        elif man is None:
            durum = "engelliyor (metin doğrulanmadı; render çalıştırılmamış)"
        elif man.get("taslak"):
            durum = "engelliyor (render TASLAK)"
        else:
            durum = "ENGELLEMİYOR: render taslak değil"
        rows.append({"olcut": c, "metin_durumu": t.get("durum"), "desteklenmeyen": len(bad),
                     "kod_sorunu": len(kod), "durum": durum})
    hata = [r for r in rows if r["durum"].startswith("ENGELLEMİYOR") or "dogrulandi diyor" in r["durum"]]
    return {"metinler": rows, "render": None if man is None else {"taslak": man.get("taslak")},
            "sonuc": "metin yok" if not rows else ("ENGELLEMİYOR" if hata else "engelliyor")}


def compare(es: EvalSet, ws: Path, inceleme: Path | None = None,
            ajan_cevaplari: Path | None = None) -> dict:
    ws = Path(ws).expanduser().resolve()
    inceleme = Path(inceleme).expanduser().resolve() if inceleme else None
    decisions = {r["doc_id"]: r for r in _read_jsonl(ws / "decisions.jsonl") if r.get("doc_id")}
    ids = _doc_map(es, ws)
    rows, crits, uy = _audit_rows(ws, inceleme) if decisions else ([], [], ["decisions.jsonl yok"])
    index = load_index(ws)
    texts = load_texts(ws)
    ajan = read_agent_answers(ajan_cevaplari) if ajan_cevaplari else None
    docs = compare_docs(es, ws, rows, decisions, ids)
    cr = compare_criteria(es, crits)
    claims = check_claims(es, texts, index, ids, ajan)
    pub = check_publish(ws)
    ozet = {
        "belge": len(docs),
        "islenen": sum(d["sonuc"] != "işlenmemiş" for d in docs),
        "tuzak": sum(1 for d in docs if d["tuzak"] not in ("", "yok")),
        "yakalandi": sum(d["sonuc"] == "yakalandı" for d in docs),
        "kacirildi": sum(d["sonuc"] == "kaçırıldı" for d in docs),
        "belge_od": _od_counts([d["od_sonuc"] for d in docs if d["sonuc"] != "işlenmemiş"]),
        "olcut_od": _od_counts([c["od_sonuc"] for c in cr]),
        "iddia": {k: sum(c["durum"] == k for c in claims) for k in ("GEÇTİ", "geçmedi", "metin yok")},
        "yayim_engeli": pub["sonuc"],
    }
    return {"surum": SURUM, "set": es.ad, "calisma_alani": str(ws), "uyarilar": uy, "ozet": ozet,
            "belgeler": docs, "olcutler": cr, "surumler": check_versions(es, index, ids),
            "celiskiler": es.veri.get("celiskiler") or [], "iddialar": claims, "yayim": pub}


def _od_counts(xs: list[str]) -> dict:
    return {"tam": sum(x == "tam" for x in xs), "±1": sum(x in ("-1", "fazla (+1)") for x in xs),
            "fazla": sum(x.startswith("fazla") for x in xs), "eksik": sum(x.startswith("eksik") for x in xs)}


def _cell(x) -> str:
    if x is None:
        return "—"
    if isinstance(x, (list, tuple)):
        return ", ".join(map(str, x)) or "—"
    return str(x).replace("|", "\\|").replace("\n", " ")


def to_markdown(r: dict) -> str:
    o = r["ozet"]
    L = [f"# Değerlendirme: {r['set']}", "", f"Çalışma alanı: `{r['calisma_alani']}`", ""]
    for u in r["uyarilar"]:
        L.append(f"> uyarı: {u}")
    L += ["", "## Özet", "",
          f"- belge: {o['belge']} (işlenen {o['islenen']}); tuzak içeren: {o['tuzak']}",
          f"- yakalandı / kaçırıldı: {o['yakalandi']} / {o['kacirildi']}",
          f"- belge OD: tam {o['belge_od']['tam']}, ±1 {o['belge_od']['±1']}, fazla {o['belge_od']['fazla']}, "
          f"eksik {o['belge_od']['eksik']}",
          f"- ölçüt OD: tam {o['olcut_od']['tam']}, ±1 {o['olcut_od']['±1']}, fazla {o['olcut_od']['fazla']}, "
          f"eksik {o['olcut_od']['eksik']}",
          f"- yazılmaması gereken iddia: geçti {o['iddia']['GEÇTİ']}, geçmedi {o['iddia']['geçmedi']}, "
          f"metin yok {o['iddia']['metin yok']}",
          f"- desteklenmeyen cümle yayıma hazır durumu: {o['yayim_engeli']}", "",
          "## Belgeler", "",
          "| belge | tuzak | beklenen (kanıt · birim · OD) | sistem (karar · birim · OD) | sonuç | OD | beklenen halkalar | sayılan halkalar | işaretler |",
          "|---|---|---|---|---|---|---|---|---|"]
    for d in r["belgeler"]:
        e, s = d["beklenen"], d["sistem"]
        L.append("| " + " | ".join(_cell(x) for x in (
            d["dosya"], d["tuzak"], f"{e['kanit']} · {e['birim']} · OD{e['od']}",
            f"{s['karar'] or '—'} · {s['birim'] or '—'} · OD{s['od']}", d["sonuc"], d["od_sonuc"],
            e["halkalar"], s["halkalar"], s["isaretler"])) + " |")
    L += ["", "## Ölçütler", "",
          "| ölçüt | vaka | beklenen OD | sistem OD | OD | eksik halka (beklenen → sistem) | not | bilinen açık |",
          "|---|---|---|---|---|---|---|---|"]
    for c in r["olcutler"]:
        L.append("| " + " | ".join(_cell(x) for x in (
            c["olcut"], c["vaka"], c["beklenen_od"], c["sistem_od"], c["od_sonuc"],
            f"{_cell(c['beklenen_eksik'])} → {_cell(c['sistem_eksik'])}"
            + ("" if c["eksik_ayni"] in (None, True) else " (farklı)"),
            "tamam" if c["notlar_tamam"] else "EKSİK", "var" if c["bilinen_acik"] else "")) + " |")
    if r["surumler"]:
        L += ["", "## Sürüm grupları", ""]
        for v in r["surumler"]:
            L.append(f"- {v['grup']}: {v['durum']}" + (f" {v.get('olcut_satir')}" if v.get("olcut_satir") else ""))
    if r["celiskiler"]:
        L += ["", "## Çelişkiler (metinde uzlaştırılmadan yazılmamalı)", ""]
        for c in r["celiskiler"]:
            L.append(f"- {', '.join(c['belgeler'])}: {c['konu']}")
    L += ["", "## Yazılmaması gereken iddialar", "", "| id | ölçüt | iddia | durum | cümle(ler) | şüpheli | ajan |",
          "|---|---|---|---|---|---|---|"]
    for c in r["iddialar"]:
        L.append("| " + " | ".join(_cell(x) for x in (
            c["id"], c["olcut"], c["iddia"], c["durum"], [f"{s['yer']}: {s['metin']}" for s in c["ihlal"]],
            [s["yer"] for s in c["supheli"]], c["ajan"])) + " |")
    L += ["", "## Yayıma hazır durumu (desteklenmeyen cümle)", "",
          "| ölçüt | metin durumu | desteklenmeyen cümle | kod sorunu | sonuç |", "|---|---|---|---|---|"]
    for m in r["yayim"]["metinler"]:
        L.append("| " + " | ".join(_cell(x) for x in (m["olcut"], m["metin_durumu"], m["desteklenmeyen"],
                                                         m["kod_sorunu"], m["durum"])) + " |")
    return "\n".join(L) + "\n"


# -- taslak sınaması ------------------------------------------------------------------------------

def _template(path: Path, ids: tuple[str, ...]) -> Path:
    """FR-0833 biçiminde en küçük sentetik şablon (tests/test_render.py ile aynı yapı)."""
    import docx
    d = docx.Document()

    def merged(t, lines):
        row = t.add_row()
        cell = row.cells[0].merge(row.cells[4])
        cell.paragraphs[0].text = lines[0]
        for x in lines[1:]:
            cell.add_paragraph(x)

    d.add_paragraph("BİRİM İÇ DEĞERLENDİRME RAPORU")
    d.add_paragraph("…………………….[Birim Adı]")
    d.add_paragraph("ÖLÇÜTLER VE KANITLAR")
    for sid in ids:
        t = d.add_table(rows=0, cols=5)
        t.style = "Table Grid"
        merged(t, ["DOLDURACAK BİRİMLER: TÜM AKADEMİK BİRİMLER"])
        merged(t, [f"{sid}. Sentetik ölçüt", "Sentetik ölçüt açıklaması."])
        r = t.add_row()
        for i, c in enumerate(r.cells):
            c.text = str(i + 1)
        r = t.add_row()
        for i, c in enumerate(r.cells):
            c.text = f"Sentetik rubrik düzey {i + 1} ({sid})"
        merged(t, ["Örnek Kanıtlar:", "Sentetik örnek kanıt"])
        merged(t, ["Açıklamalar:", "Bu bölüme açıklayıcı metin yazılmalı.", "", ""])
        merged(t, ["Kanıtlar:", "Kanıtlar buraya yazılmalı.", ""])
        d.add_paragraph("")
    d.save(str(path))
    return path


def taslak_sinama(tmp: Path | None = None) -> dict:
    """Gerçek `verify.judge` ve `render` ile: (1) bütün cümleler desteklenince metin
    `dogrulandi`, rapor taslak değil; (2) tek cümle desteklenmeyince metin `reddedildi`, rapor
    TASLAK; (3) tek cümle 'kısmen' → yine reddedildi; (4) reddedilen metin insan kararıyla
    çıkarılınca rapora girmez ve taslak saymaz."""
    from bidr.render.run import render
    from bidr.verify.run import judge
    own = tmp is None
    td = tempfile.TemporaryDirectory() if own else None
    root = Path(td.name if own else tmp)
    try:
        meta = {"cumleler": [{"yer": "p1.c1", "metin": "Bölümde danışman ataması yapılmıştır [1_OD3]."},
                             {"yer": "p1.c2", "metin": "Atamalar her yıl izlenmektedir [1_OD3]."}]}

        def out(*k):
            return {"cumleler": [{"yer": c["yer"], "karar": x, "gerekce": "sentetik"}
                                 for c, x in zip(meta["cumleler"], k)]}

        d_ok = judge(meta, out("destekleniyor", "destekleniyor"))[0]
        d_bad = judge(meta, out("destekleniyor", "desteklenmiyor"))[0]
        d_kis = judge(meta, out("destekleniyor", "kismen"))[0]
        sab = _template(root / "sablon.docx", ("A.1.1", "A.1.2"))

        def run(name, durumlar: dict[str, tuple[str, str | None]]):
            tx = root / name / "texts"
            tx.mkdir(parents=True)
            for c, (du, ik) in durumlar.items():
                t = {"olcut": c, "od_onerisi": 3, "durum": du,
                     "paragraflar": [{"metin": " ".join(x["metin"] for x in meta["cumleler"]), "atiflar": ["1_OD3"]}],
                     "kanitlar": [{"no": "1_OD3", "ad": "Sentetik kanıt", "dosya": "a.pdf"}], "eksikler": []}
                if ik:
                    t["insan_karari"] = ik
                (tx / f"{c}.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
            return render(sab, root / name / "rapor.docx", texts_dir=tx, audit_path=None).taslak

        cases = {
            "hepsi_destekleniyor": {"metin": d_ok, "taslak": run("a", {"A.1.1": (d_ok, None), "A.1.2": (d_ok, None)})},
            "tek_cumle_desteklenmiyor": {"metin": d_bad, "taslak": run("b", {"A.1.1": (d_bad, None), "A.1.2": (d_ok, None)})},
            "tek_cumle_kismen": {"metin": d_kis, "taslak": run("c", {"A.1.1": (d_kis, None), "A.1.2": (d_ok, None)})},
            "reddedilen_insan_cikardi": {"metin": d_bad, "taslak": run("d", {"A.1.1": (d_bad, "cikar"), "A.1.2": (d_ok, None)})},
        }
        beklenen = {"hepsi_destekleniyor": ("dogrulandi", False), "tek_cumle_desteklenmiyor": ("reddedildi", True),
                    "tek_cumle_kismen": ("reddedildi", True), "reddedilen_insan_cikardi": ("reddedildi", False)}
        for k, v in cases.items():
            v["beklenen"] = {"metin": beklenen[k][0], "taslak": beklenen[k][1]}
            v["tamam"] = (v["metin"], v["taslak"]) == beklenen[k]
        return {"durumlar": cases, "tamam": all(v["tamam"] for v in cases.values())}
    finally:
        if td:
            td.cleanup()


# -- CLI ----------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="degerlendir", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="komut", required=True)
    p = sub.add_parser("denetle", help="setin tutarlılığı")
    p.add_argument("--set", required=True, type=Path)
    p = sub.add_parser("sentetik", help="beklenen karar kayıtlarından sentetik çalışma alanı")
    p.add_argument("--set", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--mod", default="ideal", choices=MODLAR)
    p.add_argument("--vaka", default=None)
    p = sub.add_parser("karsilastir", help="çalışma alanı çıktılarını beklenen.yaml ile karşılaştır")
    p.add_argument("--set", required=True, type=Path)
    p.add_argument("-w", "--workspace", required=True, type=Path)
    p.add_argument("--inceleme", type=Path, default=None, help="audit --out klasörü (varsayılan çalışma alanı)")
    p.add_argument("--md", type=Path, default=None)
    p.add_argument("--json", type=Path, default=None)
    p.add_argument("--ajan-paketi", type=Path, default=None, help="iddia denetimi için ajan iş paketleri")
    p.add_argument("--ajan-cevaplari", type=Path, default=None)
    sub.add_parser("taslak-sinama", help="desteklenmeyen cümle → TASLAK (gerçek verify/render koduyla)")
    a = ap.parse_args(argv)

    if a.komut == "denetle":
        err = check_set(load_set(a.set))
        for e in err:
            print("HATA", e)
        print("tamam" if not err else f"{len(err)} sorun")
        return 1 if err else 0
    if a.komut == "sentetik":
        es = load_set(a.set)
        w = make_workspace(es, a.out, a.mod, a.vaka)
        print(f"sentetik çalışma alanı: {w} ({a.mod}); sonra: bidr audit -w {w}")
        return 0
    if a.komut == "taslak-sinama":
        r = taslak_sinama()
        for k, v in r["durumlar"].items():
            print(f"{'ok ' if v['tamam'] else 'HATA'} {k}: metin {v['metin']}, taslak {v['taslak']} "
                  f"(beklenen {v['beklenen']['metin']}, {v['beklenen']['taslak']})")
        return 0 if r["tamam"] else 1
    es = load_set(a.set)
    r = compare(es, a.workspace, a.inceleme, a.ajan_cevaplari)
    if a.ajan_paketi:
        n = write_agent_packages(es, load_texts(Path(a.workspace).expanduser().resolve()),
                                 load_index(Path(a.workspace).expanduser().resolve()), a.ajan_paketi)
        print(f"ajan iş paketi: {n} ({a.ajan_paketi})")
    md = to_markdown(r)
    if a.md:
        a.md.write_text(md, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    if not a.md:
        print(md)
    else:
        o = r["ozet"]
        print(f"{r['set']}: yakalandı {o['yakalandi']}/{o['islenen']}, ölçüt OD {o['olcut_od']}, "
              f"iddia {o['iddia']}, yayım engeli: {o['yayim_engeli']} → {a.md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
