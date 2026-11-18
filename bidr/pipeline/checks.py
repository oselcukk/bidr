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
    from bidr.decide.run import (COARSE, FINE, load_decisions, load_unit_pins, pending_redecide, stage_done,
                                 stale_summary, task_version)
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
    redo = pending_redecide(recs, load_unit_pins(ws.root)) if stage == "fine" else []
    if redo:
        prog["birim_yeniden_karar"] = len(redo)
        cmd = f"{prep} --only {','.join(redo)}"
        if not missing:
            return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[cmd],
                         neden=f"{len(redo)} belgenin birim ilişkisini komisyon değiştirdi (review.xlsx), "
                               f"eşleşme kaydı yok: yeniden ince karar gerekli (ilişki pakete sabit yazılır)")
        uy.append(f"{len(redo)} belge birim ilişkisi kararıyla yeniden ince karar bekliyor: `{cmd}`")
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
    if st["uygulanmamis"] or st.get("uygulanmamis_duzeltme"):
        why = []
        if st["uygulanmamis"]:
            why.append(f"{st['uygulanmamis']} karar")
        if st.get("uygulanmamis_duzeltme"):
            why.append(f"{st['uygulanmamis_duzeltme']} kanıt adı/bağlantı düzeltmesi")
        return Check(kim=KOMUT, komutlar=[apply_cmd], ilerleme=prog,
                     neden=" ve ".join(why) + " tabloda var ama işlenmemiş: apply")
    return Check(bitti=True, ilerleme=prog, neden=f"{st['satir']} satır kararlı ve işlendi")


# -- kanıt adı (isteğe bağlı) -------------------------------------------------------------------

def _invalid_keys(gfile: Path, pattern: str) -> set[str]:
    import re
    if not gfile.exists():
        return set()
    rx = re.compile(pattern)
    return {m.group(1) for ln in gfile.read_text(encoding="utf-8").splitlines() if (m := rx.match(ln))}


def name_tamam(c: Ctx) -> Check:
    from bidr.name.resolve import decision_name, load_names
    from bidr.name.run import _pkgs, decisions_view, eligible, task_version, work_dir
    from bidr.write.sources import rapor_section
    ws = c.ws
    if rapor_section(ws.root).get("kanit_adi_modeli") is False:
        return Check(atlandi=True, neden="config.yaml rapor.kanit_adi_modeli: false (adlar kuraldan ve incelemeden)")
    p = ws.root / "decisions.jsonl"
    recs = {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")} if p.exists() else {}
    recs = decisions_view(ws, recs)             # insan birim kararı (name prepare ile aynı görünüm)
    pool = set(eligible(recs))
    if not pool:
        return Check(atlandi=True, neden="kabul edilmiş eşleşmesi olan belge yok")
    names = load_names(ws.root)
    have = {d for d in pool if (names.get(d) or {}).get("model") or (names.get(d) or {}).get("insan")
            or decision_name(recs[d])}
    missing = pool - have
    prog = {"belge": len(pool), "adli": len(have)}
    if not missing:
        return Check(bitti=True, ilerleme=prog, neden=f"{len(pool)} belgenin model/insan kanıt adı var")
    d = work_dir(ws)
    pk = {json.loads(x.read_text(encoding="utf-8"))["doc_id"]: x for x in _pkgs(d)}
    nopkg = missing - set(pk)
    if nopkg:
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[c.fmt(c.stage["komut"][0])],
                     neden=f"{len(nopkg)} belgenin adlandırma paketi yok")
    old = [x for x in missing if str(json.loads(pk[x].read_text(encoding="utf-8")).get("surum")) != task_version()]
    if old:
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[c.fmt(c.stage["komut"][0]) + " --redo"],
                     neden=f"{len(old)} paket görevin eski sürümüyle: prepare yeniler")
    no_out = {x for x in missing if not (d / f"{x}.out.json").exists()}
    bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([^`]+)\.json`") & missing
    apply_ = c.fmt(c.stage["komut"][2])
    if no_out or bad:
        return Check(kim=AJAN, ilerleme=prog,
                     komutlar=["(ajan) work/name/README.md'yi oku; cevapsız/reddedilen her <doc_id>.json için "
                               "<doc_id>.out.json yaz (kişi adı/unvan/e-posta yok, 3-7 sözcük)", apply_],
                     neden=", ".join(x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                                  f"{len(bad)} ad reddedildi (work/name/GECERSIZ.md)" if bad else "")
                                     if x))
    return Check(kim=KOMUT, ilerleme=prog, komutlar=[apply_], neden=f"{len(missing)} cevap işlenmemiş: apply")


# -- file ------------------------------------------------------------------------------------------

def file_tamam(c: Ctx) -> Check:
    from bidr.file.run import status
    st = status(c.ws.root)
    run_cmd = c.fmt(c.stage["komut"][0])
    prog = {"kanit": st["kanit"], "eksik_dosya": st["eksik_dosya"], "baglantisiz": st["baglantisiz"]}
    if not (st["index"] and st["manifest"]):
        return Check(kim=KOMUT, komutlar=[run_cmd], neden="evidence-index.csv / evidence/ yok: dosyalama yapılmadı")
    if not st["guncel"]:
        return Check(kim=KOMUT, komutlar=[run_cmd], ilerleme=prog,
                     neden="kanıt klasörü eski: kararlar, inceleme, kanıt adları ya da bağlantılar değişti")
    uy = []
    if st["eksik_dosya"]:
        uy.append(f"{st['eksik_dosya']} kanıtın dosyası kopyalanamadı (evidence-index.csv `isaretler`: "
                  "kaynak_dosya_yok / envanterde_yok)")
    if st["baglantisiz"]:
        uy.append(f"{st['baglantisiz']} kanıtın bağlantısı yok (gaps.md 'Bağlantısı olmayan kanıtlar'): kamuya açık "
                  "belgenin adresini review.xlsx 'bağlantı' sütununa yazın ya da kanıt klasörünü yükleyip "
                  "config.yaml rapor.kanit_kok_baglanti girin")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"{st['kanit']} kanıt dosyalandı")


# -- write ------------------------------------------------------------------------------------------

def _write_inputs(ws: Workspace):
    from bidr.write import run as W
    from bidr.write import sources as S
    sp = W.source_paths(ws.root)
    idx = Path(sp["index"]) if sp["index"] else ws.root / S.INDEX
    aud = Path(sp["audit"]) if sp["audit"] else ws.root / S.AUDIT
    return idx, aud


def write_tamam(c: Ctx) -> Check:
    from bidr.write import packages as K
    from bidr.write import run as W
    from bidr.write import sources as S
    ws = c.ws
    prep = c.fmt(c.stage["komut"][0])
    apply_ = c.fmt(c.stage["komut"][2])
    idx, aud = _write_inputs(ws)
    if not idx.exists() or not aud.exists():
        return Check(kim=KOMUT, komutlar=[prep], neden=f"{idx.name} ya da {aud.name} yok")
    index, audit = S.load_index(idx), S.load_audit(aud)
    need = set(index)
    if not need:
        return Check(atlandi=True, neden="kanıtı olan ölçüt yok: yazılacak metin yok")
    td, d = W.texts_dir(ws), W.work_dir(ws)
    texts = {c_: W.load_text(ws, c_) for c_ in need}
    texts = {k: v for k, v in texts.items() if v}
    pkgs = {}
    for pp in K.pkg_paths(d) if d.exists() else []:
        try:
            pkgs[pp.stem] = json.loads(pp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    ver = W.task_version()
    pending = {k for k in need if k in pkgs and ((texts.get(k) or {}).get("kaynak") or {}).get("istem_sha")
               != pkgs[k].get("istem_sha")}
    stale = {k for k, t in texts.items() if t.get("girdi_sha")
             and t["girdi_sha"] != W.girdi_sha(index[k], int((audit.get(k) or {}).get("od") or 1))}
    old_pkg = {k for k in pending if str(pkgs[k].get("surum")) != ver}
    todo = (need - set(texts) - pending) | (stale - pending) | old_pkg
    prog = {"olcut": len(need), "metin": len(set(texts) - stale), "bekleyen_paket": len(pending)}
    rounds = sorted(k for k in pending if int((pkgs[k].get("meta") or {}).get("tur") or 0) > 0)
    if rounds:
        prog["yeniden_yazim"] = len(rounds)
    uy = []
    extra = sorted(p.stem for p in td.glob("*.json") if p.stem not in need) if td.exists() else []
    if extra:
        uy.append(f"{len(extra)} metnin ölçütünde artık kanıt yok ({_sample(extra)}); doğrulama bu metinleri reddeder")
    if todo:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[prep],
                     neden=f"{len(todo)} ölçütün metni yok ya da eski (kanıt listesi/OD değişti): prepare")
    if pending:
        no_out = {k for k in pending if not (d / f"{k}.out.json").exists()}
        bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([A-E]\.\d+\.\d+)\.json`") & pending
        tur = (f" (yeniden yazım turu: {', '.join(f'{k} tur {pkgs[k]['meta'].get('tur')}' for k in rounds)})"
               if rounds else "")
        if no_out or bad:
            parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                 f"{len(bad)} cevap geçersiz (work/write/GECERSIZ.md)" if bad else "") if x]
            who = ("metni ilk yazandan ve doğrulayıcıdan AYRI, taze bir ajan" if rounds
                   else "ajan (doğrulamayı sonra başka, taze bir ajan yapar)")
            return Check(kim=AJAN, ilerleme=prog, uyarilar=uy,
                         komutlar=[f"({who}) work/write/README.md'yi oku; cevapsız/geçersiz her <ölçüt>.json için "
                                   "work/write/<ölçüt>.out.json yaz (her cümle [n_ODk] atıflı; yalnız kanıttaki)",
                                   apply_],
                         neden=", ".join(parts) + ": model işi ajanda" + tur)
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[apply_],
                     neden=f"{len(pending)} cevap yazılmış ama işlenmemiş: apply" + tur)
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"{len(need)} ölçütün metni yazıldı")


# -- verify -------------------------------------------------------------------------------------------

def verify_tamam(c: Ctx) -> Check:
    from bidr.verify import run as V
    from bidr.write import packages as K
    from bidr.write import run as W
    ws = c.ws
    prep, apply_ = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    texts = V._texts(ws, None)
    if not texts:
        return Check(atlandi=True, neden="doğrulanacak metin yok")
    from bidr.write import yonler as Y
    yp = Y.verify_pending(ws)              # alan düzeyi güçlü/gelişmeye açık yönler (aynı akış)
    log, human = V.load_log(ws), V.load_human(ws)
    unsettled = []
    for t in texts:
        r = log.get(t["olcut"])
        if not (r and r.get("metin_sha") == W.text_sha(t) and r.get("durum") in V.FINAL
                and t.get("durum") == r["durum"]):
            unsettled.append(t)
    ok = [t["olcut"] for t in texts if t.get("durum") == "dogrulandi" and t not in unsettled]
    rej = V.rejected(ws, log)
    out = {k for k, t in rej.items() if V.excluded(t, human)}
    prog = {"metin": len(texts), "dogrulandi": len(ok), "reddedildi": len(rej), "cikarildi": len(out),
            "bekleyen": len(unsettled)}
    if yp["bekleyen"]:
        prog["yonler_bekleyen"] = len(yp["bekleyen"])
    if unsettled or yp["bekleyen"]:
        d = W.work_dir(ws, V.STAGE)
        pk = {}
        for pp in K.pkg_paths(d) if d.exists() else []:
            try:
                pk[pp.stem] = json.loads(pp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        cur = {t["olcut"] for t in unsettled if (x := pk.get(t["olcut"]))
               and (x.get("meta") or {}).get("metin_sha") == W.text_sha(t)
               and str(x.get("surum")) == W.task_version(V.TASK)}
        nopkg = ({t["olcut"] for t in unsettled} - cur) | (yp["bekleyen"] - yp["paketli"])
        if nopkg:
            return Check(kim=KOMUT, ilerleme=prog, komutlar=[prep],
                         neden=f"{len(nopkg)} metin doğrulanmadı (paketi yok ya da metin değişti): prepare "
                               "(kod denetimi burada; geçemeyen metin model işine gitmeden reddedilir)")
        no_out = {k for k in cur if not (d / f"{k}.out.json").exists()} | yp["cevapsiz"]
        bad = (_invalid_keys(d / "GECERSIZ.md", r"^- `([A-E]\.\d+\.\d+)\.json`") & cur) | yp["gecersiz"]
        if no_out or bad:
            parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                 f"{len(bad)} cevap geçersiz (work/verify/GECERSIZ.md)" if bad else "") if x]
            cmds = ["(metni YAZMAMIŞ, taze ve bağımsız bir ajan) work/verify/README.md'yi oku; her "
                    "<ölçüt>.json için work/verify/<ölçüt>.out.json yaz: her cümleye destekleniyor/"
                    "kismen/desteklenmiyor + gerekçe, yalnız atıf yapılan kanıtın alıntısına göre"]
            if yp["cevapsiz"] or yp["gecersiz"]:
                cmds.append("(aynı bağımsız ajan) work/verify/yonler/README.md'yi oku; her <alan>.json için "
                            "work/verify/yonler/<alan>.out.json yaz: her maddeye destekleniyor/kismen/desteklenmiyor "
                            "+ gerekçe, yalnız atıf yapılan ölçütün doğrulanmış metni ya da bulgusuna göre")
            return Check(kim=AJAN, ilerleme=prog, komutlar=cmds + [apply_],
                         neden=", ".join(parts) + ": bağımsız doğrulama ajanda")
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[apply_],
                     neden=f"{len(cur) + len(yp['paketli'])} doğrulama cevabı işlenmemiş: apply")
    from bidr.write import sources as S
    idx, _ = _write_inputs(ws)
    have = set(S.load_index(idx)) if idx.exists() else set()
    orphan = sorted((k for k in rej if k not in out and k not in have), key=_crit_key)
    open_ = {k: t for k, t in rej.items() if k not in out and k in have}
    lims = {k: V.limit_for(ws, k, human) for k in open_}
    under = sorted((k for k, t in open_.items() if int(t.get("tur") or 0) < lims[k]), key=_crit_key)
    over = sorted((k for k in open_ if k not in under), key=_crit_key)
    uy = []
    if orphan:
        uy.append(f"{len(orphan)} reddedilen metnin ölçütünde artık kanıt yok; rapora girmez: {', '.join(orphan)}")
    human_cmds = [f"(insan) reddedilen metni ve gerekçesini (texts/<ölçüt>.json `dogrulama.gerekce`, verify.jsonl) "
                  "kullanıcıya göster; kanıt eklemek, komisyon bilgisi vermek (rapor-notlari.yaml) ya da "
                  "metni rapordan çıkarmak kullanıcının kararıdır",
                  c.fmt("bidr verify karar -w {ws}") + " <ölçüt> cikar   # KULLANICI derse: metin rapora girmez",
                  c.fmt("bidr verify karar -w {ws}") + " <ölçüt> tekrar  # KULLANICI derse: bir tur daha"]
    if over:
        uy.append(f"{len(over)} ölçüt yeniden yazım sınırından sonra hâlâ reddedildi, insan gerekli: "
                  + ", ".join(f"{k} (tur {rej[k].get('tur') or 0}/{lims[k]})" for k in over))
    if under:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy,
                     komutlar=[c.fmt("bidr write prepare -w {ws} --reddedilenler")],
                     neden=f"{len(under)} ölçüt doğrulamada reddedildi; yeniden yazım turu: "
                           + ", ".join(f"{k} (tur {int(rej[k].get('tur') or 0) + 1}/{lims[k]})" for k in under)
                           + ". Yeniden yazımı ve doğrulamayı ayrı, taze ajanlara ver")
    if over:
        return Check(kim=INSAN, ilerleme=prog, komutlar=human_cmds,
                     neden=f"{len(over)} ölçüt {min(lims[k] for k in over)} yeniden yazım turundan sonra hâlâ "
                           f"reddedildi: insan gerekli ({', '.join(over)})")
    if out:
        uy.append(f"{len(out)} ölçütün metni kullanıcı kararıyla rapora alınmayacak: {', '.join(sorted(out, key=_crit_key))}")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                 neden=f"{len(ok)} metin doğrulandı" + (f", {len(out)} rapordan çıkarıldı" if out else ""))


# -- yonler (alan düzeyi Güçlü / Gelişmeye Açık Yönler) ---------------------------------------------

def yonler_tamam(c: Ctx) -> Check:
    from bidr.write import packages as K
    from bidr.write import run as W
    from bidr.write import yonler as Y
    ws = c.ws
    prep, apply_ = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    try:
        src = Y.Inputs(ws.root)
    except FileNotFoundError as e:
        return Check(kim=KOMUT, komutlar=[prep], neden=str(e))
    need = [a for a in Y.ALANLAR if src.criteria(a)]
    if not need:
        return Check(atlandi=True, neden="birimin doldurduğu ölçüt yok: alan maddesi yazılmaz")
    cur_sha = {a: src.girdi_sha(a) for a in need}
    texts = {a: t for a in need if (t := Y.load(ws, a))}
    d = Y.work_dir(ws)
    pkgs = {}
    for pp in K.pkg_paths(d, K.ALAN_KEY) if d.exists() else []:
        try:
            pkgs[pp.stem] = json.loads(pp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    ver = W.task_version(Y.TASK)
    pending = {a for a in need if a in pkgs and ((texts.get(a) or {}).get("kaynak") or {}).get("istem_sha")
               != pkgs[a].get("istem_sha")}
    bad_pkg = {a for a in pending if str(pkgs[a].get("surum")) != ver
               or (pkgs[a].get("meta") or {}).get("girdi_sha") != cur_sha[a]}
    stale = {a for a, t in texts.items() if t.get("girdi_sha") != cur_sha[a]}
    todo = (set(need) - set(texts) - pending) | (stale - pending) | bad_pkg
    log = Y.load_log(ws)
    rej = Y.rejected(ws, log)
    lim = W.rewrite_limit(ws.root)
    prog = {"alan": len(need), "metin": len(set(texts) - stale), "bekleyen_paket": len(pending),
            "dogrulandi": sum(1 for a, t in texts.items() if a not in stale and t.get("durum") == "dogrulandi")}
    uy = list(src.uyarilar)
    if todo:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[prep],
                     neden=f"{len(todo)} alanın maddeleri yok ya da eski (ölçüt metinleri/audit değişti): prepare")
    if pending:
        rounds = sorted(a for a in pending if int((pkgs[a].get("meta") or {}).get("tur") or 0) > 0)
        no_out = {a for a in pending if not (d / f"{a}.out.json").exists()}
        bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([A-E])\.json`") & pending
        if no_out or bad:
            parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                 f"{len(bad)} cevap geçersiz (work/yonler/GECERSIZ.md)" if bad else "") if x]
            who = ("maddeleri ilk yazandan ve doğrulayıcıdan AYRI, taze bir ajan" if rounds
                   else "ajan (doğrulamayı sonra başka, taze bir ajan yapar)")
            return Check(kim=AJAN, ilerleme=prog, uyarilar=uy,
                         komutlar=[f"({who}) work/yonler/README.md'yi oku; cevapsız/geçersiz her <alan>.json için "
                                   "work/yonler/<alan>.out.json yaz (her cümle ölçüt kodlu; güçlü yön yalnız "
                                   "doğrulanmış metinden, gelişmeye açık yön yalnız audit bulgusundan)", apply_],
                         neden=", ".join(parts) + ": model işi ajanda")
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[apply_],
                     neden=f"{len(pending)} cevap yazılmış ama işlenmemiş: apply")
    unverified = sorted(a for a, t in texts.items() if t.get("durum") not in Y.FINAL)
    if unverified:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[c.fmt("bidr verify prepare -w {ws}")],
                     neden=f"{len(unverified)} alanın maddeleri doğrulanmadı: {', '.join(unverified)}")
    under = sorted(a for a, t in rej.items() if int(t.get("tur") or 0) < lim)
    over = sorted(a for a in rej if a not in under)
    if over:
        uy.append(f"{len(over)} alanın maddeleri {lim} yeniden yazım turundan sonra hâlâ reddedildi ({', '.join(over)}): "
                  "hücreler şablon yönergesiyle kalır, rapor TASLAK damgalı olur; gerekçeyi (verify-yonler.jsonl) "
                  "kullanıcıya göster")
    if under:
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy,
                     komutlar=[c.fmt("bidr yonler prepare -w {ws} --reddedilenler")],
                     neden=f"{len(under)} alanın maddeleri doğrulamada reddedildi; yeniden yazım turu: "
                           + ", ".join(f"{a} (tur {int(rej[a].get('tur') or 0) + 1}/{lim})" for a in under)
                           + ". Yeniden yazımı ve doğrulamayı ayrı, taze ajanlara ver")
    empty = sorted(a for a, t in texts.items() if a not in rej and not (t.get("guclu") and t.get("gelisme")))
    if empty:
        uy.append(f"dayanağı olmadığı için boş liste kalan alan ({', '.join(empty)}): o hücre şablon yönergesiyle "
                  "kalır, rapor TASLAK damgalı olur")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                 neden=f"{prog['dogrulandi']} alanın güçlü/gelişmeye açık yönleri doğrulandı")


def _crit_key(k: str):
    from bidr.criteria.model import id_key
    return id_key(k)


# -- render --------------------------------------------------------------------------------------------

def render_tamam(c: Ctx) -> Check:
    from bidr.render.run import load_manifest, workspace_sha
    from bidr.write.sources import rapor_section
    ws = c.ws
    cmd = c.fmt(c.stage["komut"][0])
    sablon = rapor_section(ws.root).get("sablon")
    m = load_manifest(ws.root)
    if not sablon and not m:
        return Check(kim=INSAN, komutlar=[
            "(insan) boş FR-0833 şablonunun (.docx) yolunu kullanıcıdan al; config.yaml'a "
            "`rapor: {sablon: <yol>}` olarak yazılır (ya da komuta --sablon <yol>)", cmd],
            neden="rapor şablonu bilinmiyor (config.yaml rapor.sablon yok)")
    if not m or not Path(m.get("cikti") or "").exists():
        return Check(kim=KOMUT, komutlar=[cmd], neden="report.docx üretilmedi")
    g = m.get("girdiler") or {}
    sp = Path(str(sablon)).expanduser() if sablon else Path(m["sablon"])
    cur = workspace_sha(ws.root, sp, Path(g.get("texts") or ws.root / "texts"),
                        Path(g["audit"]) if g.get("audit") else ws.root / "audit-olcutler.json",
                        Path(g["index"]) if g.get("index") else ws.root / "evidence-index.csv")
    if cur != m.get("girdi_sha"):
        return Check(kim=KOMUT, komutlar=[cmd], neden="rapor eski: şablon, metinler, alan maddeleri, audit, kanıt "
                                                      "dizini, hazırlayanlar ya da kapsam değişti")
    uy = []
    if m.get("taslak"):
        why = m.get("taslak_nedenleri") or ["doğrulanmamış metin: " + ", ".join(m.get("dogrulanmamis") or [])]
        uy.append("rapor TASLAK damgalı: " + "; ".join(why))
    if m.get("karar_gerekli"):
        uy.append(f"{len(m['karar_gerekli'])} ölçütte kapsam kararı gerekli (gaps.md 'Kapsam kararı gereken "
                  "ölçütler'): KULLANICI karar verir, cevabı config.yaml rapor.kapsam'a yazılır")
    if m.get("baglantisiz_kanit"):
        uy.append(f"{m['baglantisiz_kanit']} kanıtın adı bağlantısız (gaps.md)")
    prog = {"dolu": m.get("dolu"), "bos": m.get("bos"), "baglantili_kanit": m.get("baglantili_kanit")}
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"report: {m['cikti']}")


def _transcribe_tamam(c: Ctx) -> Check:
    from bidr.transcribe.check import transcribe_tamam
    return transcribe_tamam(c)


def _describe_tamam(c: Ctx) -> Check:
    from bidr.describe.check import describe_tamam
    return describe_tamam(c)


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
    "describe_tamam": _describe_tamam,
    "name_tamam": name_tamam,
    "file_tamam": file_tamam,
    "write_tamam": write_tamam,
    "verify_tamam": verify_tamam,
    "yonler_tamam": yonler_tamam,
    "render_tamam": render_tamam,
    "yok": yok,
}
