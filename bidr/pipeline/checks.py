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
    bekleyen: list[str] | None = None   # kim=ajan: cevap bekleyen paket anahtarları (`bidr parcala` böler)
    karar_bekleyen: list[dict] = field(default_factory=list)   # kim=insan: karar bekleyen öğeler (panel gösterir)
    # hattı tutmayan, bölüm kararını bekleyen öneriler (kör denetimin OD/kanıt önerileri): aşama bitmiş olsa da
    # `next`/`status` bilgi olarak gösterir; karar sonradan gelirse ilgili düzeltme küçük bir tur olarak koşar
    oneri_bekleyen: list[dict] = field(default_factory=list)
    # kullanıcı uyarısı OLMAYAN, yalnız bilgi düzeyindeki notlar (ör. eski yazım kuralıyla yazılmış ama geçerli
    # metinler): `status`/`next` "bilgi:" satırında, JSON'da aşamanın `bilgi` alanında; panel Durum'da göstermez
    bilgi: list[str] = field(default_factory=list)


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
    from bidr.ingest import kimlik as K
    bek = K.bekleyenler(ws.root)
    if bek:
        return Check(kim=INSAN, komutlar=[c.fmt("bidr kimlik-onar -w {ws}")],
                     neden=f"{len(bek)} belgenin kimliği belirsiz: maskeli kopyası değişmiş, eski kayıtları "
                           f"(karar, metin) {K.OKSUZ_DIR}/ altına alındı ({_sample(b['doc_id'] for b in bek)}). "
                           "Model işi başlamadan önce `bidr kimlik-onar` (önce kuru koşu; --uygula ile yazar) "
                           "eski kimlikleri geri bağlar ya da belgelerin gerçekten değiştiğini onaylar")
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
    """Her metnin kaydı var, kayıt bugünkü identify koduyla (`arac_surumu`) ve config'in
    dönemiyle (`--period`) üretilmiş. Eski sürüm ya da boş/farklı dönem: identify yeniden."""
    from bidr.identify.pipeline import ARAC_SURUMU
    t = text_ids(c.ws)
    recs = {r["doc_id"]: r for r in read_jsonl(c.ws.documents) if r.get("doc_id")} \
        if c.ws.documents.exists() else {}
    d = set(recs)
    eksik = t - d
    prog = {"metin": len(t), "kayit": len(t & d)}
    if not t:
        return Check(kim=KOMUT, neden="text/ boş: işlenecek belge yok", ilerleme=prog)
    if eksik:
        return Check(kim=KOMUT, neden=f"{len(eksik)}/{len(t)} belgenin documents.jsonl kaydı yok", ilerleme=prog)
    old = sorted(x for x in t if recs[x].get("arac_surumu") != ARAC_SURUMU)
    if old:
        vs = sorted({str(recs[x].get("arac_surumu") or 1) for x in old})
        prog["eski"] = len(old)
        return Check(kim=KOMUT, ilerleme=prog,
                     neden=f"{len(old)}/{len(t)} kayıt eski (araç sürümü değişti: identify v{','.join(vs)} → "
                           f"v{ARAC_SURUMU}): identify yeniden (model işi yok)")
    donem = (c.sec or {}).get("donem")
    if donem:
        bos = sorted(x for x in t if recs[x].get("donem") != int(donem))
        if bos:
            prog["donem_eksik"] = len(bos)
            return Check(kim=KOMUT, ilerleme=prog,
                         neden=f"{len(bos)}/{len(t)} kaydın dönem alanı boş ya da {donem} değil (identify "
                               f"--period olmadan çalışmış): tam komutla identify yeniden")
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
    from bidr.decide.run import (COARSE, FINE, _section, input_fingerprint, load_decisions, load_restale,
                                 load_unit_pins, pending_redecide, stage_done, stale_summary, task_version)
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
    allstale = stale_summary(ws, stage, recs)
    kural = sorted(x for x, w in allstale.items() if w == "kural_degisti")
    eski = {x: w for x, w in allstale.items() if w != "kural_degisti"}
    if eski:
        prog["yeniden_islenecek"] = len(eski)
        uy.append(f"yeniden işlenecek {len(eski)} belge (görev sürümü ya da istem değişti; eski kararlar "
                  f"kullanılıyor). Pahalı: önce `{prep}` maliyet özetini verir, kullanıcı onaylarsa "
                  f"`{prep} --yes`.")
    if kural:
        prog["istem_surumu_eski"] = len(kural)
        uy.append(f"istem sürümü eski: {len(kural)} belgenin kararı ortak kural metni değişmeden önce verildi "
                  f"(belgeye özgü girdi aynı; kayıt geçerli). Toptan yeniden işleme isteğe bağlı ve pahalı: "
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
    if not missing and any(_section(recs[x], stage).get("istem_sha") for x in done):
        # ajan kipi kayıtları: araç ya da girdiler son tam prepare'den sonra değiştiyse eskime hesaplanmadı
        h = load_restale(ws, stage)
        if h is None or h.get("parmak") != input_fingerprint(ws, stage):
            return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[prep],
                         neden="eski olabilir (araç sürümü ya da girdiler değişti; son tam prepare'den sonra "
                               "görev/istem kodu, ölçüt verisi, text/, documents.jsonl, candidates.jsonl ya da "
                               "belge-notlari.yaml değişti): prepare (onaysız; model çağrısı yok) etkiyi hesaplar, belgeye özgü "
                               "girdisi değişen belgeleri yeniden paketler, yalnız ortak kural metni değişenleri "
                               "geçerli sayar")
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
        return Check(kim=AJAN, ilerleme=prog, uyarilar=uy, bekleyen=sorted(set(no_out) | bad),
                     komutlar=[f"(ajan) {rel}/README.md'yi oku; cevapsız/geçersiz her <doc_id>.json için "
                               f"{rel}/<doc_id>.out.json yaz (yalnız JSON, şemaya uygun, alıntılar birebir)",
                               apply_],
                     neden=", ".join(parts) + f": model işi ajanda ({rel}/)")
    return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, komutlar=[apply_],
                 neden=f"{len(missing)} cevap yazılmış ama işlenmemiş: apply"
                       + (f" ({len(wait)} mükerrer belge temsilcinin kararını devralacak)" if wait else ""))


# -- hakem -----------------------------------------------------------------------------------

def _hakem_same(ws: Workspace, review: Path) -> bool:
    """decisions.jsonl kuyruktan sonra yeniden yazıldı (ör. ikinci arama apply'ı yalnız kendi kaydını
    ekledi): karşılaştırma ve sorular bugünkü kararlardan yeniden hesaplanınca aynıysa kuyruk güncel."""
    from bidr.criteria.loader import load_criteria
    from bidr.decide.compare import FILES, build, compare_md
    try:
        cs = load_criteria()
        res = build(ws.root, criteria=cs)
        cmp_ = ws.root / FILES["compare"]
        return (json.loads(json.dumps(res["sorular"], ensure_ascii=False)) == list(read_jsonl(review))
                and cmp_.exists() and cmp_.read_text(encoding="utf-8") == compare_md(res, cs))
    except Exception:          # okunamayan girdi: temkinli taraf, eski say
        return False


def hakem_tamam(c: Ctx) -> Check:
    from bidr.decide.compare import FILES, load_answers, parse_answer, parse_review_md
    ws = c.ws
    if not c.sec.get("gecmis_etiket"):
        return Check(atlandi=True, neden="geçmiş etiket yok: karşılaştırılacak bir şey yok")
    review = ws.root / FILES["review_jsonl"]
    md = ws.root / FILES["review_md"]
    dec = ws.root / "decisions.jsonl"
    if not review.exists() or (_mtime(review) < _mtime(dec) and not _hakem_same(ws, review)):
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
        why = ("review.xlsx eski kararlardan üretilmiş (decisions.jsonl değişti); yeniden üret "
               "(doldurulmuş kararlar yeni tabloya taşınır)")
        n_ia = _ikinci_arama_kabul(ws)
        if n_ia:
            why += (f". İkinci arama {n_ia} kabul edilmiş eşleşme ekledi: yeni satırlar (işaret `ikinci_arama`) "
                    "kullanıcının kararını bekleyecek")
        return Check(kim=KOMUT, komutlar=[run_cmd], ilerleme=prog, neden=why)
    acik = st["satir"] - st["kararli"]
    if acik:
        why = f"{acik}/{st['satir']} satır karar bekliyor"
        if st["gecersiz"]:
            why += f" ({st['gecersiz']} geçersiz karar)"
        return Check(kim=INSAN, ilerleme=prog,
                     komutlar=[f"(insan) {ws.root / FILES['xlsx']}: kullanıcı 'İnceleme' sayfasında her satır için "
                               "KARARINIZ'ı seçer (2. bölüm 'Hepsini kabul' ile toplu kabul edilebilir) ya da ajan "
                               "satırları kullanıcıya tek tek sorup cevabı yazar; gaps.md eksikleri gösterir. "
                               "Kararı ajan vermez.",
                               apply_cmd],
                     neden=why)
    if st["uygulanmamis"] or st.get("uygulanmamis_duzeltme"):
        why = []
        if st["uygulanmamis"]:
            why.append(f"{st['uygulanmamis']} karar")
        if st.get("uygulanmamis_duzeltme"):
            why.append(f"{st['uygulanmamis_duzeltme']} kanıt adı/bağlantı düzeltmesi ya da 'bakıldı' işareti")
        return Check(kim=KOMUT, komutlar=[apply_cmd], ilerleme=prog,
                     neden=" ve ".join(why) + " tabloda var ama işlenmemiş: apply")
    if st.get("yeniden_bak"):
        # karar korunur (insan kararı ezilmez); karardan sonra satırın dayanağı değişti
        prog["yeniden_bak"] = st["yeniden_bak"]
        return Check(kim=INSAN, ilerleme=prog,
                     komutlar=[f"(insan) {ws.root / FILES['xlsx']}: 'İnceleme' 1. bölümde \"Daha önce … demiştiniz\" "
                               "satırları. Kullanıcı satıra yeniden bakar ve KARARINIZ'ı yeniden seçer (aynı kalacaksa "
                               "aynısını; teknik sayfada 'bakıldı' = evet de olur). Kararı ajan vermez.", apply_cmd],
                     neden=f"{st['yeniden_bak']} kararlı satır yeniden bakılmalı: karardan sonra yeni inceleme "
                           "işareti eklendi ya da sayılan aşama/OD değişti (eski karar korundu ve geçerli)")
    return Check(bitti=True, ilerleme=prog, neden=f"{st['satir']} satır kararlı ve işlendi")


def _ikinci_arama_kabul(ws: Workspace) -> int:
    """decisions.jsonl'de ikinci aramanın eklediği kabul edilmiş eşleşme sayısı."""
    p = ws.root / "decisions.jsonl"
    if not p.exists():
        return 0
    return sum(1 for r in read_jsonl(p) for m in r.get("eslesmeler") or []
               if m.get("ikinci_arama") and m.get("kabul"))


# -- faaliyet kayıtları -------------------------------------------------------------------------

def faaliyet_tamam(c: Ctx) -> Check:
    from bidr.faaliyet import run as F
    ws = c.ws
    cmd = c.fmt(c.stage["komut"][0])
    src, out = ws.root / F.DECISIONS, ws.root / F.OUT
    if not src.exists():
        return Check(kim=KOMUT, komutlar=[cmd], neden=f"{F.DECISIONS} yok")
    if not out.exists():
        return Check(kim=KOMUT, komutlar=[cmd], neden=f"{F.OUT} yok: faaliyet kayıtları üretilmedi")
    want = json.loads(json.dumps(F.build_ws(ws), ensure_ascii=False))
    try:
        have = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        have = None
    if have != want:
        return Check(kim=KOMUT, komutlar=[cmd],
                     neden=f"{F.OUT} eski: decisions.jsonl değişti (yeniden karar ya da ikinci arama)")
    st = want["ozet"]
    prog = {"faaliyet": st["faaliyet"], "belge": st["faaliyetli"], "yalniz_duyuru": st["yalniz_duyuru"]}
    uy = []
    if st["yalniz_duyuru"]:
        uy.append(f"{st['yalniz_duyuru']} faaliyetin yalnız duyuru/plan belgesi var: metinde "
                  "'düzenlenmiştir/gerçekleştirilmiştir' denemez (gerçekleşme kanıtı gerekir)")
    if st["alansiz_eski"]:
        uy.append(f"{st['alansiz_eski']} ince karar classify_fine v8 ve öncesinden (faaliyet alanı yok; "
                  "faaliyetsiz sayılır)")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy,
                 neden=f"{st['faaliyet']} faaliyet kaydı ({st['faaliyetli']} belge) güncel")


# -- ikinci arama (isteğe bağlı) ------------------------------------------------------------------

def ikinci_arama_tamam(c: Ctx) -> Check:
    from bidr.candidates import arama as A
    from bidr.decide.run import FINE, _load_pkg, _pkg_paths, load_decisions, task_version
    from bidr.write.sources import rapor_section
    from bidr.kor.run import kanit_ciftleri
    ws = c.ws
    # kör denetimde bölümün kabul ettiği kullanılmamış belge önerisi: ikinci aramayla bakılmadıysa bekler
    # (rapor.ikinci_arama: false olsa da; yalnız o çiftler paketlenir)
    den = kanit_ciftleri(ws.root) if (ws.root / "kor-denetim-kararlar.jsonl").exists() else []
    # bölümün elle eklediği alıntısız eşleşme (bidr/audit/elle.py): alıntı ikinci aramayla belgeden aranır
    from bidr.audit.elle import ciftler as elle_ciftleri
    den = den + [{**x, "bulgu_id": f"elle {x['anahtar']}", "kaynak": "elle"} for x in elle_ciftleri(ws.root)]
    if rapor_section(ws.root).get("ikinci_arama") is False and not den:
        return Check(atlandi=True, neden="atlandı: config.yaml rapor.ikinci_arama: false (kanıtsız/zayıf ölçütler "
                                         "için ikinci arama yapılmadı)")
    prep, apply_ = c.fmt(c.stage["komut"][0]), c.fmt(c.stage["komut"][2])
    d = ws.root / "work" / A.WORK
    if den:
        packed = set()
        for p in (_pkg_paths(d) if d.exists() else []):
            pkg = _load_pkg(p)
            for r in ((pkg or {}).get("meta") or {}).get("ikinci_arama", {}).get("olcutler") or []:
                for kay in {"denetim", "elle"} & set(r.get("kaynak") or []):
                    packed.add((pkg.get("doc_id"), r.get("olcut"), kay))
        yeni = [x for x in den if (x["doc_id"], x["olcut"], x.get("kaynak", "denetim")) not in packed]
        if yeni:
            return Check(kim=KOMUT, komutlar=[prep + " --yalniz-denetim"],
                         neden=f"bölümün kabul ettiği/elle eklediği {len(yeni)} belge–madde çifti ikinci aramaya "
                               "girecek (kör denetim önerisi eşleşirse inceleme tablosunda aday olur; elle eşleşmede "
                               "alıntı belgeden aranır): " + ", ".join(f"{x['bulgu_id']}" for x in yeni[:6]))
    if not (d / "README.md").exists():
        return Check(kim=KOMUT, komutlar=[prep],
                     neden="ikinci arama yapılmadı (isteğe bağlı): kanıtsız/zayıf ölçütler için arşivde ters arama. "
                           "Atlamak kullanıcının kararıdır: config.yaml `rapor: {ikinci_arama: false}`")
    recs = load_decisions(ws)
    ver = task_version(FINE)
    pkgs = [pkg for p in _pkg_paths(d) if (pkg := _load_pkg(p)) is not None]
    bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([^`]+)\.json`")
    n_ia = _ikinci_arama_kabul(ws)
    prog = {"paket": len(pkgs), "kabul_eslesme": n_ia}
    eski, no_out, gecersiz, acik = [], [], [], []
    for pkg in pkgs:
        did = pkg.get("doc_id")
        rec = recs.get(did)
        outp = d / pkg["cikti_dosyasi"]
        durum = A.pkg_status(d, pkg, rec, ver)   # prepare ile ortak "eski" tanımı
        if durum == "merged":
            continue                         # cevap kayıtta (ilk geçiş sonradan yeniden uygulanmış olsa da)
        if durum == "eski":
            eski.append(did)
            continue
        if not outp.exists():
            no_out.append(did)
            continue
        if did in bad:
            gecersiz.append(did)
            continue
        cevap = A._sha(outp.read_text(encoding="utf-8"))
        oc = (rec.get("ikinci_arama") or {}).get("olcutler") or {}
        adaylar = pkg["meta"]["adaylar"]
        if not (A.done_criteria(rec) >= set(adaylar) and all(
                (oc.get(x) or {}).get("cevap_sha") == cevap and (oc.get(x) or {}).get("istem_sha") == pkg["istem_sha"]
                for x in adaylar)):
            acik.append(did)
    prog.update(cevapsiz=len(no_out), gecersiz=len(gecersiz), islenmemis=len(acik), eski=len(eski))
    if eski:
        return Check(kim=KOMUT, komutlar=[prep], ilerleme=prog,
                     neden=f"{len(eski)} paket eski (görev sürümü değişti ya da ilk geçiş yeniden karara bağlandı): "
                           "prepare yeniler")
    if no_out or gecersiz:
        parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                             f"{len(gecersiz)} cevap geçersiz (work/ikinci_arama/GECERSIZ.md)" if gecersiz else "") if x]
        return Check(kim=AJAN, ilerleme=prog, bekleyen=sorted(set(no_out) | set(gecersiz)),
                     komutlar=["(ajan) work/ikinci_arama/README.md'yi oku; cevapsız/geçersiz her <doc_id>.json için "
                               "<doc_id>.out.json yaz (ince karar kuralları; uymuyorsa olcut_yok/kanit_degil)", apply_],
                     neden=", ".join(parts) + ": model işi ajanda (work/ikinci_arama/)")
    if acik:
        return Check(kim=KOMUT, komutlar=[apply_], ilerleme=prog,
                     neden=f"{len(acik)} cevap yazılmış ama işlenmemiş: apply (kabul edilen eşleşme audit'i yeniden ister)")
    return Check(bitti=True, ilerleme=prog,
                 neden=(f"{len(pkgs)} paket işlendi; ikinci arama {n_ia} kabul edilmiş eşleşme ekledi (audit'te incelendi)"
                        if pkgs else "ikinci arama çalıştı: zayıf ölçüt için aranacak belge yok"))


# -- kanıt adı (isteğe bağlı) -------------------------------------------------------------------

def _invalid_keys(gfile: Path, pattern: str) -> set[str]:
    import re
    if not gfile.exists():
        return set()
    rx = re.compile(pattern)
    return {m.group(1) for ln in gfile.read_text(encoding="utf-8").splitlines() if (m := rx.match(ln))}


def name_tamam(c: Ctx) -> Check:
    from bidr.name.resolve import decision_name, load_names
    from bidr import notlar as N
    from bidr.name.run import (_pkgs, _text, compilation_hint, decisions_view, eligible, note_stale, parts_pending,
                               task_version, work_dir)
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
    notes = N.load(ws.root)
    # belge notu değişen belgenin model adı eskidir (model adı ince kararın adının önüne geçer): yeniden sorulur
    noted = {d for d in pool if note_stale(d, names.get(d), notes) and not (names.get(d) or {}).get("insan")}
    have = {d for d in pool if (names.get(d) or {}).get("model") or (names.get(d) or {}).get("insan")
            or decision_name(recs[d])} - noted
    # parça adı: adı olan ama derleme olduğu saptanan (birleşik belge; alıntılar farklı
    # parçalardan) belge, görevin bu sürümüyle parça adı sorulana dek bekler. Aday yoksa adım biter.
    parca = set(parts_pending(ws, recs, names, sorted(have)))
    missing = (pool - have) | parca
    prog = {"belge": len(pool), "adli": len(have), "parca_adi_bekleyen": len(parca)}
    if not missing:
        return Check(bitti=True, ilerleme=prog, neden=f"{len(pool)} belgenin model/insan kanıt adı var"
                     " (derleme belgelerin parça adı soruldu)")
    d = work_dir(ws)
    pk = {json.loads(x.read_text(encoding="utf-8"))["doc_id"]: x for x in _pkgs(d)}
    nopkg = missing - set(pk)
    # parça adı bekleyen belgenin paketi eski bir adlandırmadan kalmış olabilir: istemde güncel
    # derleme bilgisi yoksa prepare yeniler (cevaplanmış eski paket apply ile parça adı almaz)
    stale = {x for x in parca & set(pk)
             if compilation_hint(_text(ws, x)) not in json.loads(pk[x].read_text(encoding="utf-8")).get("istem", "")}
    # notu değişen belgenin paketi eski notla (ya da notsuz) yazılmış: prepare yeniler
    stale |= {x for x in noted & set(pk)
              if json.loads(pk[x].read_text(encoding="utf-8")).get("belge_notu", "") != N.note_sha(notes.get(x))}
    if nopkg or stale:
        why = [f"{len(nopkg - parca)} belgenin adlandırma paketi yok" if nopkg - parca else "",
               f"{len(parca)} derleme belgenin parça adı yok (birleşik belge)" if parca else "",
               f"{len(noted)} belgenin notu değişti (yükleyenin notu): ad yeniden sorulacak" if noted else ""]
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[c.fmt(c.stage["komut"][0])],
                     neden=", ".join(x for x in why if x))
    old = [x for x in missing if str(json.loads(pk[x].read_text(encoding="utf-8")).get("surum")) != task_version()]
    if old:
        return Check(kim=KOMUT, ilerleme=prog,
                     komutlar=[c.fmt(c.stage["komut"][0]) + ("" if set(old) <= parca else " --redo")],
                     neden=f"{len(old)} paket görevin eski sürümüyle: prepare yeniler")
    no_out = {x for x in missing if not (d / f"{x}.out.json").exists()}
    bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([^`]+)\.json`") & missing
    apply_ = c.fmt(c.stage["komut"][2])
    if no_out or bad:
        return Check(kim=AJAN, ilerleme=prog, bekleyen=sorted(no_out | bad),
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
    if st.get("eski_kesim"):
        return Check(kim=KOMUT, komutlar=[run_cmd], ilerleme=prog,
                     neden="kanıt klasörü eski kuralla (alıntı sayfasına kesilerek) üretildi: yeniden dosyalayın "
                           "(dosya tam; birleşik dosyada her belge kendi bütün sayfalarıyla)")
    if not st["guncel"]:
        return Check(kim=KOMUT, komutlar=[run_cmd], ilerleme=prog,
                     neden="kanıt klasörü eski: kararlar, inceleme, kanıt adları ya da bağlantılar değişti")
    uy = []
    if st["eksik_dosya"]:
        uy.append(f"{st['eksik_dosya']} kanıtın dosyası kopyalanamadı (evidence-index.csv `isaretler`: "
                  "kaynak_dosya_yok / envanterde_yok)")
    if st["baglantisiz"] and _teslim(c) == "baglanti":
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
    if stale - pending:
        prog["eski_metin"] = len(stale - pending)
    rounds = sorted(k for k in pending if int((pkgs[k].get("meta") or {}).get("tur") or 0) > 0)
    if rounds:
        prog["yeniden_yazim"] = len(rounds)
    uy = []
    extra = sorted(p.stem for p in td.glob("*.json") if p.stem not in need) if td.exists() else []
    if extra:
        uy.append(f"{len(extra)} metnin ölçütünde artık kanıt yok ({_sample(extra)}); rapora alınmaz (ölçüt kanıtsız yazılır)")
    eski_surum = [k for k in W.old_rule_texts(ws, index, audit, ver) if k not in pending]
    bil = []
    if eski_surum:
        prog["eski_kural"] = len(eski_surum)
        bil.append(f"{len(eski_surum)} metin eski yazım kuralıyla yazıldı ({_sample(eski_surum)}): geçerli kalır; "
                  f"isteğe bağlı yenileme (yalnız bunlar, sonra yeniden doğrulanır): `{prep} --eski-kurallar`")
    if todo:
        yok = need - set(texts) - pending
        eski = sorted(stale - pending, key=_crit_key)
        parts = [x for x in (f"{len(yok)} ölçütün metni yok" if yok else "",
                             f"{len(eski)} ölçütün metni eski ({_sample(eski)}): kanıt listesi ya da OD "
                             "değişti, yalnız numara kayması `bidr file` sırasında kodla düzeltilir; "
                             "belge/OD değiştiyse yeniden yazılır" if eski else "",
                             f"{len(old_pkg)} paket eski görev sürümünde" if old_pkg else "") if x]
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, bilgi=bil, komutlar=[prep],
                     neden="; ".join(parts) + ": prepare")
    if pending:
        from bidr.write import karar as KR
        # kod denetimini yeniden yazım sınırından sonra hâlâ geçemeyen: insan kararı (bidr write karar)
        kb = KR.bekleyen(ws, {k: pkgs[k].get("istem_sha") for k in pending})
        kbset = {x["olcut"] for x in kb}
        no_out = {k for k in pending if not (d / f"{k}.out.json").exists()}
        bad = (_invalid_keys(d / "GECERSIZ.md", r"^- `([A-E]\.\d+\.\d+)\.json`") & pending) - kbset
        tur = (f" (yeniden yazım turu: {', '.join(f'{k} tur {pkgs[k]['meta'].get('tur')}' for k in rounds)})"
               if rounds else "")
        if kb:
            prog["insan_karari_bekleyen"] = len(kb)
            uy.append(f"{len(kb)} ölçütün metni {kb[0]['sinir']} yeniden yazımdan sonra kod denetimini hâlâ "
                      f"geçemedi, KULLANICI kararı bekliyor: {', '.join(sorted(kbset, key=_crit_key))}")
        if no_out or bad:
            parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                 f"{len(bad)} cevap geçersiz (work/write/GECERSIZ.md)" if bad else "") if x]
            who = ("metni ilk yazandan ve doğrulayıcıdan AYRI, taze bir ajan" if rounds
                   else "ajan (doğrulamayı sonra başka, taze bir ajan yapar)")
            return Check(kim=AJAN, ilerleme=prog, uyarilar=uy, bilgi=bil, bekleyen=sorted(no_out | bad), karar_bekleyen=kb,
                         komutlar=[f"({who}) work/write/README.md'yi oku; cevapsız/geçersiz her <ölçüt>.json için "
                                   "work/write/<ölçüt>.out.json yaz (her cümle [n_ODk] atıflı; yalnız kanıttaki)"
                                   + (f"; insan kararı bekleyenlere ({', '.join(sorted(kbset))}) yazma" if kb else ""),
                                   apply_],
                         neden=", ".join(parts) + ": model işi ajanda" + tur)
        if kb:
            karar = c.fmt("bidr write karar -w {ws}")
            return Check(kim=INSAN, ilerleme=prog, uyarilar=uy, bilgi=bil, karar_bekleyen=kb,
                         komutlar=["(insan) reddedilen son cevabı ve kod denetiminin bulgularını (work/write/GECERSIZ.md, "
                                   "work/write/<ölçüt>.out.json) kullanıcıya göster; karar kullanıcınındır",
                                   f"{karar} <ölçüt> cikar   # KULLANICI derse: metin rapora girmez",
                                   f"{karar} <ölçüt> tekrar  # KULLANICI derse: bir yeniden yazım turu daha",
                                   f"{karar} <ölçüt> kabul   # KULLANICI derse; yalnız bütün bulgular üslup türündeyse "
                                   "(abartı/slogan/ODn dili); atıf/alıntı bulgusunda reddedilir"],
                         neden=f"{len(kb)} ölçütün metni yeniden yazımlardan sonra kod denetimini geçemedi: "
                               "insan kararı gerekli (" + ", ".join(
                                   f"{x['olcut']}: deneme {x['deneme']}/{x['sinir'] + 1}"
                                   + (", kabul edilebilir" if x["kabul_edilebilir"] else "") for x in kb) + ")")
        return Check(kim=KOMUT, ilerleme=prog, uyarilar=uy, bilgi=bil, komutlar=[apply_],
                     neden=f"{len(pending)} cevap yazılmış ama işlenmemiş: apply" + tur)
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, bilgi=bil, neden=f"{len(need)} ölçütün metni yazıldı")


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
    log, human = V.load_log(ws), V.load_human(ws)
    unsettled = []
    for t in texts:
        r = log.get(t["olcut"])
        if not (r and r.get("metin_sha") == W.text_sha(t) and r.get("durum") in V.FINAL
                and t.get("durum") == r["durum"]) or (t.get("durum") == "reddedildi" and V.stale_reject(r)):
            unsettled.append(t)     # eski görev sürümüyle verilen ajan reddi: yeni kuralla bir kez yeniden doğrulanır
    ok = [t["olcut"] for t in texts if t.get("durum") == "dogrulandi" and t not in unsettled]
    rej = V.rejected(ws, log)
    out = {k for k, t in rej.items() if V.excluded(t, human)}
    kabul = sorted((t["olcut"] for t in texts if t["olcut"] in ok and V.accepted(t, human)), key=_crit_key)
    prog = {"metin": len(texts), "dogrulandi": len(ok), "reddedildi": len(rej), "cikarildi": len(out),
            "bekleyen": len(unsettled)}
    # Alan düzeyi yönlerin doğrulaması (aynı `verify prepare|apply` komutları) bu aşamayı bekletmez:
    # yonler_tamam alan başına izler; bir alanın düzeltmesi ötekilerin doğrulaması bitmeden uygulanabilir
    # (yonler kapısı verify'a bağlı; yonler doğrulaması verify'ı bekletseydi kısır döngü olurdu).
    if unsettled:
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
        nopkg = {t["olcut"] for t in unsettled} - cur
        if nopkg:
            return Check(kim=KOMUT, ilerleme=prog, komutlar=[prep],
                         neden=f"{len(nopkg)} metin doğrulanmadı (paketi yok ya da metin değişti): prepare "
                               "(kod denetimi burada; geçemeyen metin model işine gitmeden reddedilir)")
        no_out = {k for k in cur if not (d / f"{k}.out.json").exists()}
        bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([A-E]\.\d+\.\d+)\.json`") & cur
        if no_out or bad:
            parts = [x for x in (f"{len(no_out)} paket cevapsız" if no_out else "",
                                 f"{len(bad)} cevap geçersiz (work/verify/GECERSIZ.md)" if bad else "") if x]
            cmds = ["(metni YAZMAMIŞ, taze ve bağımsız bir ajan) work/verify/README.md'yi oku; her "
                    "<ölçüt>.json için work/verify/<ölçüt>.out.json yaz: her cümleye destekleniyor/"
                    "kismen/desteklenmiyor + gerekçe, yalnız atıf yapılan kanıtın alıntısına göre"]
            return Check(kim=AJAN, ilerleme=prog, komutlar=cmds + [apply_], bekleyen=sorted(no_out | bad),
                         neden=", ".join(parts) + ": bağımsız doğrulama ajanda")
        return Check(kim=KOMUT, ilerleme=prog, komutlar=[apply_],
                     neden=f"{len(cur)} doğrulama cevabı işlenmemiş: apply")
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
                  c.fmt("bidr verify karar -w {ws}") + " <ölçüt> tekrar  # KULLANICI derse: bir tur daha",
                  c.fmt("bidr verify karar -w {ws}") + " <ölçüt> kabul   # KULLANICI derse: doğrulayıcının "
                  "itirazı yerinde değil, metin olduğu gibi rapora girer"]
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
    if kabul:
        uy.append(f"{len(kabul)} ölçütün metni doğrulayıcı reddine rağmen insan onayıyla kabul edildi: {', '.join(kabul)}")
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
    from bidr.write import yon_karar as YK
    human = YK.load_human(ws)
    # bölümün kabul/çıkar dediği alan (aynı metin) yeniden yazılmaz, karar beklemez (bidr/write/yon_karar.py)
    rej = {a: t for a, t in Y.rejected(ws, log).items() if not YK.kararli(t, human)}
    lims = {a: YK.sinir(ws, a, human) for a in rej}
    prog = {"alan": len(need), "metin": len(set(texts) - stale), "bekleyen_paket": len(pending),
            "dogrulandi": sum(1 for a, t in texts.items() if a not in stale and t.get("durum") == "dogrulandi")}
    uy = list(src.uyarilar)
    # Alan başına bağımsız ilerleme: bir alanın yeniden yazımı/düzeltmesi ötekilerin doğrulaması
    # bitmeden yapılabilir. Her alanın sıradaki işi ayrı listelenir; komutlar her alan için aynıdır
    # (prepare/apply yalnız işi olan alanlara dokunur).
    rounds = sorted(a for a in pending if int((pkgs[a].get("meta") or {}).get("tur") or 0) > 0)
    no_out = {a for a in pending if not (d / f"{a}.out.json").exists()}
    bad = _invalid_keys(d / "GECERSIZ.md", r"^- `([A-E])\.json`") & pending
    yp = Y.verify_pending(ws)
    v_todo = (yp["bekleyen"] - yp["paketli"]) - todo - pending
    v_agent = (yp["cevapsiz"] | yp["gecersiz"]) - todo - pending
    v_apply = yp["paketli"] - v_agent - todo - pending
    under = sorted(a for a, t in rej.items() if int(t.get("tur") or 0) < lims[a] and a not in pending | todo)
    over = sorted(a for a in rej if int(rej[a].get("tur") or 0) >= lims[a] and a not in pending | todo)
    kb = [x for x in YK.bekleyen(ws, log) if x["alan"] in over]
    if kb:
        prog["insan_karari_bekleyen"] = len(kb)
        uy.append(f"{len(kb)} alanın maddeleri yeniden yazımlardan sonra doğrulamada hâlâ reddedildi, KULLANICI "
                  f"kararı bekliyor: {', '.join(x['alan'] for x in kb)}")
    why: list[str] = []
    komut: list[str] = []
    ajan: list[str] = []
    son: list[str] = []
    if todo:
        why.append(f"{', '.join(sorted(todo))}: maddeler yok ya da eski (ölçüt metinleri/audit değişti)")
        komut.append(prep)
    if under:
        why.append(f"{', '.join(under)}: doğrulamada reddedildi, yeniden yazım turu "
                   + ", ".join(f"{a} tur {int(rej[a].get('tur') or 0) + 1}/{lims[a]}" for a in under))
        komut.append(c.fmt("bidr yonler prepare -w {ws} --reddedilenler"))
    if v_todo:
        why.append(f"{', '.join(sorted(v_todo))}: maddeler doğrulanmadı (paket yok)")
        komut.append(c.fmt("bidr verify prepare -w {ws}"))
    if no_out or bad:
        ab = sorted(no_out | bad)
        durum = "cevapsız/geçersiz" if no_out and bad else "cevapsız" if no_out else \
            "cevabı geçersiz (work/yonler/GECERSIZ.md)"
        why.append(f"{', '.join(ab)}: yazım paketi {durum}" + (" (yeniden yazım turu)" if set(ab) & set(rounds) else ""))
        who = ("maddeleri ilk yazandan ve doğrulayıcıdan AYRI, taze bir ajan" if set(ab) & set(rounds)
               else "ajan (doğrulamayı sonra başka, taze bir ajan yapar)")
        ajan.append(f"({who}) work/yonler/README.md'yi oku; cevapsız/geçersiz her <alan>.json için "
                    "work/yonler/<alan>.out.json yaz (her cümle ölçüt kodlu; güçlü yön yalnız "
                    "doğrulanmış metinden, gelişmeye açık yön yalnız BULGULAR satırından)")
        son.append(apply_)
    elif pending:
        why.append(f"{', '.join(sorted(pending))}: cevap yazılmış ama işlenmemiş")
        son.append(apply_)
    if v_agent:
        why.append(f"{', '.join(sorted(v_agent))}: doğrulama paketi cevapsız/geçersiz")
        ajan.append("(maddeleri YAZMAMIŞ, taze ve bağımsız bir ajan) work/verify/yonler/README.md'yi oku; her "
                    "<alan>.json için work/verify/yonler/<alan>.out.json yaz: her maddeye destekleniyor/kismen/"
                    "desteklenmiyor + gerekçe, yalnız atıf yapılan ölçütün doğrulanmış metni ya da BULGULAR satırına göre")
        son.append(c.fmt("bidr verify apply -w {ws} --model {ajan}"))
    elif v_apply:
        why.append(f"{', '.join(sorted(v_apply))}: doğrulama cevabı işlenmemiş")
        son.append(c.fmt("bidr verify apply -w {ws} --model {ajan}"))
    if why:
        cmds = list(dict.fromkeys(komut + ajan + son))
        if len(why) > 1:
            cmds.append("(alanlar birbirini beklemez: yukarıdaki işler herhangi bir sırayla yapılabilir; "
                        "yeniden yazımı ve doğrulamayı ayrı, taze ajanlara ver)")
        return Check(kim=AJAN if ajan else KOMUT, ilerleme=prog, uyarilar=uy, komutlar=cmds,
                     neden="; ".join(why), bekleyen=sorted(no_out | bad | v_agent) if ajan else None,
                     karar_bekleyen=kb)
    if kb:
        karar = c.fmt("bidr yonler karar -w {ws}")
        return Check(kim=INSAN, ilerleme=prog, uyarilar=uy, karar_bekleyen=kb,
                     komutlar=["(insan) reddedilen maddeleri ve doğrulayıcının gerekçesini (verify-yonler.jsonl) "
                               "kullanıcıya göster; karar kullanıcınındır",
                               f"{karar} <alan> tekrar  # KULLANICI derse: bir yeniden yazım turu daha",
                               f"{karar} <alan> kabul   # KULLANICI derse; yalnız bütün reddedilen maddeler 'kismen' "
                               "ise: maddeler yazıldığı gibi rapora girer",
                               f"{karar} <alan> cikar   # KULLANICI derse: desteklenmeyen maddeler çıkarılmış kalır"],
                     neden=f"{len(kb)} alanın güçlü/gelişmeye açık yön maddeleri yeniden yazımlardan sonra "
                           "doğrulamada hâlâ reddedildi: insan gerekli (" + ", ".join(x["alan"] for x in kb) + ")")
    for a, t in sorted(texts.items()):
        uy += [f"{a} alanı: {x}" for x in Y.tutarlilik_satirlari(t)]
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
            "(insan) boş FR-0833 şablonunun (.docx) yolunu kullanıcıdan al; answers.yaml'a "
            "`sablon: <tam yol>` yaz ve `bidr init --answers <answers.yaml>` yeniden çalıştır "
            "(config.yaml rapor.sablon'a o yazar; tek seferlik: komuta --sablon <yol>)", cmd],
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
    if m.get("baglantisiz_kanit") and _teslim(c) == "baglanti":
        uy.append(f"{m['baglantisiz_kanit']} kanıtın adı bağlantısız (gaps.md)")
    prog = {"dolu": m.get("dolu"), "bos": m.get("bos"), "baglantili_kanit": m.get("baglantili_kanit")}
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"report: {m['cikti']}")


def denetle_tamam(c: Ctx) -> Check:
    from bidr.check.run import file_sha
    from bidr.render.run import load_manifest
    ws = c.ws
    cmd = c.fmt(c.stage["komut"][0])
    m = load_manifest(ws.root) or {}
    docx = Path(m.get("cikti") or ws.root / "report.docx")
    if not docx.exists():
        return Check(kim=KOMUT, komutlar=[cmd], neden=f"{docx.name} yok: önce render")
    p = ws.root / "denetim.json"
    if not p.exists():
        return Check(kim=KOMUT, komutlar=[cmd], neden="denetim.json yok: biçim denetimi yapılmadı")
    try:
        js = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Check(kim=KOMUT, komutlar=[cmd], neden="denetim.json okunamadı: yeniden denetle")
    same = js.get("docx") and Path(js["docx"]).expanduser().resolve() == docx.resolve()
    if not same or js.get("docx_sha") != file_sha(docx):
        return Check(kim=KOMUT, komutlar=[cmd], neden=f"denetim.json güncel {docx.name}'e ait değil (rapor yeniden "
                                                      "üretildi ya da elle değişti): yeniden denetle")
    oz = js.get("ozet") or {}
    kritik, uyari = int(oz.get("kritik") or 0), int(oz.get("uyari") or 0)
    prog = {"kritik": kritik, "uyari": uyari}
    kod = oz.get("kodlar") or {}
    if kritik:
        top = ", ".join(f"{k} ({v.get('sayi')})" for k, v in sorted(kod.items()) if v.get("seviye") == "kritik")
        return Check(kim=INSAN, ilerleme=prog, komutlar=[
            f"(insan) {p}: kritik bulguları kullanıcıya göster; kaynağını (metin, kapsam kararı, hazırlayanlar, "
            "şablon, kanıt klasörü) düzelt — report.docx'i elle düzeltme", c.fmt("bidr render -w {ws}"), cmd],
            neden=f"yayıma hazır değil: {kritik} kritik bulgu ({top})")
    uy = [f"{uyari} biçim uyarısı (denetim.json; engel değil, kullanıcı gözden geçirir)"] if uyari else []
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden="yayıma hazır: kritik bulgu yok")


def _teslim(c: Ctx) -> str:
    """config.yaml `rapor.teslim` (geçersiz değerde `gecersiz`). dekanlik'te bağlantısız kanıt bilgidir."""
    from bidr.teslim.mod import teslim_modu
    try:
        return teslim_modu(c.ws.root)
    except ValueError:
        return "gecersiz"


def teslim_tamam(c: Ctx) -> Check:
    from bidr.teslim.run import durum
    return durum(c)


def _transcribe_tamam(c: Ctx) -> Check:
    from bidr.transcribe.check import transcribe_tamam
    return transcribe_tamam(c)


def _belirsiz_okuma_tamam(c: Ctx) -> Check:
    from bidr.transcribe.check import belirsiz_okuma_tamam
    return belirsiz_okuma_tamam(c)


def _describe_tamam(c: Ctx) -> Check:
    from bidr.describe.check import describe_tamam
    return describe_tamam(c)


def _kor_denetim_tamam(c: Ctx) -> Check:
    from bidr.kor.check import kor_denetim_tamam
    return kor_denetim_tamam(c)


def _duzelt_tamam(c: Ctx) -> Check:
    from bidr.kor.check import duzelt_tamam
    return duzelt_tamam(c)


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
    "faaliyet_tamam": faaliyet_tamam,
    "ikinci_arama_tamam": ikinci_arama_tamam,
    "denetle_tamam": denetle_tamam,
    "transcribe_tamam": _transcribe_tamam,
    "belirsiz_okuma_tamam": _belirsiz_okuma_tamam,
    "describe_tamam": _describe_tamam,
    "name_tamam": name_tamam,
    "file_tamam": file_tamam,
    "write_tamam": write_tamam,
    "verify_tamam": verify_tamam,
    "yonler_tamam": yonler_tamam,
    "render_tamam": render_tamam,
    "teslim_tamam": teslim_tamam,
    "kor_denetim_tamam": _kor_denetim_tamam,
    "duzelt_tamam": _duzelt_tamam,
    "yok": yok,
}
