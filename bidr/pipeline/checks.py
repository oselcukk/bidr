"""Tamamlanma şartı denetimleri (salt okunur). Her denetim çalışma alanındaki dosyalara
bakar; hiçbir şey yazmaz, model çağırmaz. `pipeline.yaml`'daki `sart.denetim` adıyla
seçilir.

Her denetim `Check` döndürür:
  bitti / atlandi    aşama tamam ya da bu çalışma alanında uygulanmaz
  kim                bitmediyse sıradaki işi kim yapar: komut | ajan | insan
  neden              kısa açıklama (kullanıcıya/ajana gösterilir)
  komutlar           sıradaki tam komut(lar); None ise aşamanın varsayılan komutları
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from bidr.common import Workspace, read_jsonl

KOMUT, AJAN, INSAN = "komut", "ajan", "insan"


@dataclass
class Check:
    bitti: bool = False
    atlandi: bool = False
    kim: str | None = None
    neden: str = ""
    komutlar: list[str] | None = None
    ilerleme: dict = field(default_factory=dict)
    uyarilar: list[str] = field(default_factory=list)


@dataclass
class Ctx:
    ws: Workspace
    sec: dict | None           # config.yaml `bidr:` bölümü
    fmt: Callable[[str], str]  # komut şablonunu doldurur
    stage: dict                # pipeline.yaml aşama girdisi


def _ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for r in read_jsonl(path):
        if r.get("doc_id"):
            out.add(r["doc_id"])
    return out


def text_ids(ws: Workspace) -> set[str]:
    return {p.stem for p in ws.text_dir.glob("*.txt")} if ws.text_dir.exists() else set()


def _mtime(p: Path) -> int:
    return p.stat().st_mtime_ns if p.exists() else 0


def _sample(xs, n: int = 3) -> str:
    xs = sorted(xs)
    return ", ".join(xs[:n]) + (f" … (+{len(xs) - n})" if len(xs) > n else "")


# -- kurulum ---------------------------------------------------------------------------

def config_gecerli(c: Ctx) -> Check:
    from bidr.init.config import check_section
    if c.sec is None:
        return Check(kim=INSAN, neden="config.yaml'da `bidr:` bölümü yok: çalışma alanı kurulmamış "
                                      "(kullanıcıya kurulum sorularını sor; skill: bidr-kur)")
    errs = check_section(c.sec, c.ws.root)
    if errs:
        return Check(kim=INSAN, neden="config.yaml geçersiz: " + "; ".join(errs))
    return Check(bitti=True, neden=f"{c.sec['birim']} · {c.sec['donem']} · profil {c.sec['profil']}")


# -- ingest ----------------------------------------------------------------------------

def ingest_tamam(c: Ctx) -> Check:
    from bidr.ingest.pipeline import DONE_STATUSES, NOT_DOWNLOADED, scan
    ws = c.ws
    if not ws.inventory.exists():
        return Check(kim=KOMUT, neden="inventory.csv yok: kaynak henüz taranmadı")
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    src = Path(c.sec["kaynak"])
    inv = {r["rel_path"] for r in rows}
    cur = {e.rel for e in scan(src)}
    yeni, giden = cur - inv, inv - cur
    st = {}
    for r in rows:
        st[r["status"] or "?"] = st.get(r["status"] or "?", 0) + 1
    prog = {"dosya": len(rows), "durum": st}
    if yeni or giden:
        return Check(kim=KOMUT, ilerleme=prog,
                     neden=f"kaynak inventory'den farklı: {len(yeni)} yeni, {len(giden)} kaldırılmış dosya "
                           f"({_sample(yeni or giden)})")
    nd = [r["rel_path"] for r in rows if r["status"] == NOT_DOWNLOADED]
    if nd:
        return Check(kim=INSAN, ilerleme=prog,
                     neden=f"{len(nd)} dosya iCloud'da, bu bilgisayara indirilmemiş ({_sample(nd)}). "
                           "Kullanıcı kaynak klasörü Finder'da 'Şimdi İndir' ile indirmeli; sonra ingest yeniden.")
    eksik = [r["doc_id"] for r in rows
             if r["status"] in DONE_STATUSES and not r.get("dup_of") and not ws.text_path(r["doc_id"]).exists()]
    if eksik:
        return Check(kim=KOMUT, ilerleme=prog, neden=f"{len(eksik)} belgenin text/ dosyası yok")
    uy = []
    for k, msg in (("error", "çıkarma hatası"), ("needs_ocr", "OCR gerekli ama yapılamadı"),
                   ("unsupported", "desteklenmeyen biçim"), ("empty", "metinsiz")):
        if st.get(k):
            uy.append(f"{st[k]} dosya: {msg} (inventory.csv status={k}); bu belgeler değerlendirilemez")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                 neden=f"{len(rows)} dosya, {len(text_ids(ws))} metin")


# -- etiketler -------------------------------------------------------------------------

def etiket_tamam(c: Ctx) -> Check:
    if not c.sec.get("gecmis_etiket"):
        return Check(atlandi=True, neden="gecmis_etiket: false (geçmiş etiket kullanılmıyor)")
    n = len(_ids(c.ws.labels))
    if not n:
        return Check(kim=KOMUT, neden="labels.jsonl yok ya da boş")
    return Check(bitti=True, neden=f"{n} kayıt", ilerleme={"kayit": n})


# -- identify / candidates ---------------------------------------------------------------

def identify_tamam(c: Ctx) -> Check:
    t = text_ids(c.ws)
    d = _ids(c.ws.documents)
    eksik = t - d
    prog = {"metin": len(t), "kayit": len(t & d)}
    if not t:
        return Check(kim=KOMUT, neden="text/ boş: işlenecek belge yok", ilerleme=prog)
    if eksik:
        return Check(kim=KOMUT, neden=f"{len(eksik)}/{len(t)} belgenin documents.jsonl kaydı yok", ilerleme=prog)
    return Check(bitti=True, neden=f"{len(t)} belge", ilerleme=prog)


def candidates_tamam(c: Ctx) -> Check:
    d = _ids(c.ws.documents) & text_ids(c.ws)
    k = _ids(c.ws.root / "candidates.jsonl")
    eksik = d - k
    prog = {"belge": len(d), "aday_satiri": len(d & k)}
    if eksik:
        return Check(kim=KOMUT, neden=f"{len(eksik)}/{len(d)} belgenin candidates.jsonl satırı yok", ilerleme=prog)
    return Check(bitti=True, neden=f"{len(d)} belge", ilerleme=prog)


# -- karar (ajan modu) ---------------------------------------------------------------------

def _gecersiz_ids(gfile: Path) -> set[str]:
    if not gfile.exists():
        return set()
    out = set()
    for ln in gfile.read_text(encoding="utf-8").splitlines():
        if "geçersiz cevap" in ln and ln.startswith("- `"):
            out.add(ln[3:].split(".json", 1)[0])
    return out


def karar_tamam(c: Ctx) -> Check:
    from bidr.decide.run import COARSE, FINE, load_decisions, stage_done, stale_summary, task_version
    stage = c.stage["sart"]["asama"]
    task = COARSE if stage == "coarse" else FINE
    ws = c.ws
    recs = load_decisions(ws)
    t = text_ids(ws)
    if stage == "coarse":
        need = t
        done = {d for d in t if (r := recs.get(d)) and (r.get("durum") == "atlandi" or stage_done(r, stage))}
    else:
        need = {d for d in t if (r := recs.get(d)) and r.get("durum") == "ok" and "kaba" in r}
        done = {d for d in need if stage_done(recs[d], stage)}
    missing = need - done
    d = ws.root / "work" / stage
    prog = {"belge": len(need), "tamam": len(done)}
    uy = []
    prep, apply_, = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    if stage == "fine":
        red = sorted(x for x in done if recs[x].get("reddedilen_eslesme"))
        if red:
            uy.append(f"{len(red)} belgede alıntısı tutmayan/kurala uymayan eşleşme kodca reddedildi "
                      f"(kullanılmaz). work/fine/GECERSIZ.md'deki paketleri bir kez yeniden yazıp apply "
                      f"çalıştırmak isteğe bağlıdır.")
    eski = stale_summary(ws, stage, recs)
    if eski:
        prog["yeniden_islenecek"] = len(eski)
        uy.append(f"yeniden işlenecek {len(eski)} belge (görev sürümü ya da istem değişti; eski kararlar "
                  f"kullanılıyor). Pahalı: önce `{prep}` maliyet özetini verir, kullanıcı onaylarsa "
                  f"`{prep} --yes`.")
    if not missing:
        return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                     neden=f"{len(done)} belge {stage} tamam"
                           + (f"; yeniden işlenecek {len(eski)} belge (onay bekliyor)" if eski else ""))
    # temsilcinin kararını bekleyen mükerrer metinler: kendi paketleri yok, olması da gerekmez
    wait = {x for x in missing if ((recs.get(x) or {}).get("mukerrer") or {}).get("durum") == "bekliyor"
            and recs[x]["mukerrer"].get("asama") == stage}
    if wait:
        prog["mukerrer_bekleyen"] = len(wait)
    pkgs = {}
    for did in missing - wait:
        p = d / f"{did}.json"
        if p.exists():
            try:
                pkgs[did] = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    unpack = missing - wait - set(pkgs)
    if unpack:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[prep],
                     neden=f"{len(unpack)} belgenin iş paketi yok: önce prepare")
    old = [x for x, p in pkgs.items() if str(p.get("surum")) != task_version(task)]
    if old:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[prep],
                     neden=f"{len(old)} paket görevin eski sürümüyle hazırlanmış: prepare yeniler")
    no_out = sorted(x for x in pkgs if not (d / f"{x}.out.json").exists())
    bad = _gecersiz_ids(d / "GECERSIZ.md") & set(pkgs)
    prog.update(paket=len(pkgs), cevapsiz=len(no_out), gecersiz=len(bad))
    if no_out or bad:
        parts = []
        if no_out:
            parts.append(f"{len(no_out)} paket cevapsız")
        if bad:
            parts.append(f"{len(bad)} cevap geçersiz (work/{stage}/GECERSIZ.md)")
        rel = f"work/{stage}"
        return Check(kim=AJAN, ilerleme=prog, uyarilar=uy,
                     komutlar=[f"(ajan) {rel}/README.md'yi oku; cevapsız/geçersiz her <doc_id>.json için "
                               f"{rel}/<doc_id>.out.json yaz (yalnız JSON, şemaya uygun, alıntılar birebir)",
                               apply_],
                     neden=", ".join(parts) + f": model işi ajanda ({rel}/)")
    return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[apply_],
                 neden=f"{len(missing)} cevap yazılmış ama işlenmemiş: apply"
                       + (f" ({len(wait)} mükerrer belge temsilcinin kararını devralacak)" if wait else ""))


# -- hakem -----------------------------------------------------------------------------------

def hakem_tamam(c: Ctx) -> Check:
    from bidr.decide.compare import FILES, load_answers, parse_answer, parse_review_md
    ws = c.ws
    if not c.sec.get("gecmis_etiket"):
        return Check(atlandi=True, neden="geçmiş etiket yok: karşılaştırılacak bir şey yok")
    review = ws.root / FILES["review_jsonl"]
    md = ws.root / FILES["review_md"]
    dec = ws.root / "decisions.jsonl"
    if not review.exists() or _mtime(review) < _mtime(dec):
        return Check(kim=KOMUT, komutlar=[c.fmt(c.stage["komut"][0])],
                     neden="hakem kuyruğu yok ya da kararlardan eski")
    qs = list(read_jsonl(review))
    ans = load_answers(ws)
    if md.exists():
        for a in parse_review_md(md.read_text(encoding="utf-8")):   # md, jsonl'in üstüne yazar
            ans[a["soru_id"]] = {**ans.get(a["soru_id"], {}), **a}
    open_ = [q["soru_id"] for q in qs
             if not ((a := ans.get(q["soru_id"])) and parse_answer(q["tur"], a.get("karar", "")))]
    prog = {"soru": len(qs), "cevapli": len(qs) - len(open_)}
    if open_:
        return Check(kim=INSAN, ilerleme=prog,
                     komutlar=[f"(insan) skill bidr-hakem: " + c.fmt("bidr hakem sorular -w {ws}")
                               + f" ile {len(open_)} soruyu kullanıcıya 5'erli, önerinle sor; KULLANICININ "
                               "her kararını " + c.fmt("bidr hakem cevap -w {ws} <soru_id> <karar>") + " ile yaz",
                               c.fmt(c.stage["komut"][2])],
                     neden=f"{len(open_)}/{len(qs)} hakem sorusu kullanıcı kararı bekliyor")
    cons = ws.root / FILES["consensus"]
    if _mtime(cons) < max(_mtime(review), _mtime(ws.root / FILES["answers"]), _mtime(md)):
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[c.fmt(c.stage["komut"][2])],
                     neden="cevaplar tamam; uzlaşı etiketleri yazılmamış ya da eski")
    return Check(bitti=True, ilerleme=prog, neden=f"{len(qs)} soru cevaplandı, uzlaşı yazıldı")


# -- audit ---------------------------------------------------------------------------------

def audit_tamam(c: Ctx) -> Check:
    from bidr.audit.run import FILES, review_state
    ws = c.ws
    run_cmd, apply_cmd = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    try:
        st = review_state(ws.root)
    except Exception as e:     # bozuk tablo: kullanıcı düzeltmeli
        return Check(kim=INSAN, neden=f"{FILES['xlsx']} okunamadı: {e}")
    if not st["tablo"]:
        return Check(kim=KOMUT, komutlar=[run_cmd], neden="review.xlsx yok: denetim çalışmadı")
    prog = {"satir": st["satir"], "kararli": st["kararli"], "gecersiz": st["gecersiz"],
            "uygulanmamis": st["uygulanmamis"]}
    if not st["guncel"]:
        return Check(kim=KOMUT, komutlar=[run_cmd], ilerleme=prog,
                     neden="review.xlsx eski kararlardan üretilmiş (decisions.jsonl değişti); yeniden üret "
                           "(doldurulmuş kararlar yeni tabloya taşınır)")
    acik = st["satir"] - st["kararli"]
    if acik:
        why = f"{acik}/{st['satir']} satır karar bekliyor"
        if st["gecersiz"]:
            why += f" ({st['gecersiz']} geçersiz karar)"
        return Check(kim=INSAN, ilerleme=prog,
                     komutlar=[f"(insan) {ws.root / FILES['xlsx']}: kullanıcı her satıra KARAR yazar "
                               "(kabul/ret/duzelt); gaps.md eksikleri gösterir. Kararı ajan vermez.",
                               apply_cmd],
                     neden=why)
    if st["uygulanmamis"]:
        return Check(kim=KOMUT, komutlar=[apply_cmd], ilerleme=prog,
                     neden=f"{st['uygulanmamis']} karar tabloda var ama işlenmemiş: apply")
    return Check(bitti=True, ilerleme=prog, neden=f"{st['satir']} satır kararlı ve işlendi")


def _transcribe_tamam(c: Ctx) -> Check:
    from bidr.transcribe.check import transcribe_tamam
    return transcribe_tamam(c)


def yok(c: Ctx) -> Check:
    return Check(neden="henüz uygulanmadı")


CHECKS: dict[str, Callable[[Ctx], Check]] = {
    "config_gecerli": config_gecerli,
    "ingest_tamam": ingest_tamam,
    "etiket_tamam": etiket_tamam,
    "identify_tamam": identify_tamam,
    "candidates_tamam": candidates_tamam,
    "karar_tamam": karar_tamam,
    "hakem_tamam": hakem_tamam,
    "audit_tamam": audit_tamam,
    "transcribe_tamam": _transcribe_tamam,
    "yok": yok,
}
