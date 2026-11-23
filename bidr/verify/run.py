"""`bidr verify prepare|apply`: `texts/<ölçüt>.json` doğrulaması → `verify.jsonl`.

İki katman:
  1. Kod (prepare'de): bidr/write/text.py denetimi güncel kanıt listesi ve OD'yle yeniden
     (atıf listede mi, her cümlede atıf, OD aşımı, yasak ifade) + atıf yapılan kanıtın
     alıntıları belge metninde mi (verify_quote) + metnin OD'si güncel önerilen OD'yi aşıyor
     mu. Geçemeyen metin model işine gitmeden `reddedildi`.
  2. Bağımsız ajan: her cümle atıf yaptığı kanıtın alıntısı/bağlamıyla karşılaştırılır →
     destekleniyor | kismen | desteklenmiyor + gerekçe (görev `verify_text`; yazarın paketi ve
     gerekçesi verilmez). `apply`: her cümle "destekleniyor" ise `dogrulandi`; en az bir
     "desteklenmiyor" ya da "kismen" varsa `reddedildi` (gerekçeli; kısmen desteklenen cümle
     de düzeltilmeden rapora girmez).

Beş zorunlu soru (FR-0833 / K29; `SORULAR`): doğrulayıcı her soru için
kanitla_cevaplandi | cevapsiz | uydurma_suphesi + cümle yerleri verir (görev v2). `cevapsiz`
metni reddettirmez (kanıt yoksa cevapsız kalması doğrudur); `uydurma_suphesi` (kanıtsız genel
ifadeyle doldurulmuş soru) reddettirir. Ölçüt başına kapsam `verify.jsonl` ve
`texts/<ölçüt>.json` `soru_kapsami` alanına, özet `soru-kapsami.json`'a yazılır; alanı olmayan
(eski sürüm ya da kod reddi) kayıt "denetlenmedi" sayılır.

`verify.jsonl` ölçüt başına son doğrulama kaydını tutar; `texts/<ölçüt>.json` `durum` ve
`dogrulama` alanı güncellenir. Metin sonradan değişirse (`metin_sha`) kayıt geçersizleşir.

Yeniden yazım döngüsü: reddedilen metin `bidr write prepare --reddedilenler` ile gerekçeli
yeniden yazıma gider (tur sayısı metnin `tur` alanı). `limit_for` turdan (config.yaml
`rapor.yeniden_yazim_siniri`, vars. 2; kullanıcının her `tekrar` kararı bir tur ekler) sonra
hâlâ reddedilen ölçüt "insan gerekli"dir. Kullanıcının kararı `bidr verify karar`:
`cikar` (metin rapora girmez; render "rapora alınmamıştır" yazar, belge bu yüzden taslak
sayılmaz), `tekrar` (bir yeniden yazım turu daha) ya da `kabul` (doğrulayıcının itirazı yerinde
değil: metin olduğu gibi rapora girer; `durum: dogrulandi`, `insan_karari: kabul`, kayıtta "insan
onayıyla kabul (doğrulayıcı reddi: …)" izi ve doğrulayıcının gerekçesi kalır; yalnız ajan reddi —
kod denetimi reddi atıf/alıntı/OD kusurudur, insan onayıyla geçilmez) → `verify-insan.jsonl`.
İnsan onayı o metnin içeriğine (`metin_sha`) bağlıdır; `prepare` (`--redo` dahil) onu yeniden doğrulamaz.
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import Workspace, read_jsonl, write_jsonl
from bidr.criteria.model import id_key
from bidr.write import packages as K
from bidr.write import run as W
from bidr.write import text as T

TASK = "verify_text"
STAGE = "verify"
LOG = "verify.jsonl"
HUMAN = "verify-insan.jsonl"
HUMAN_KARARLAR = ("cikar", "tekrar", "kabul")
KABUL_IZI = "insan onayıyla kabul"
FINAL = ("dogrulandi", "reddedildi")
RULE = ("Her cümleyi yalnız atıf yaptığı kanıtın alıntısı ve bağlamıyla karşılaştır "
        "(destekleniyor / kismen / desteklenmiyor + gerekçe); listedeki her cümleye bir karar ver. "
        "Beş soruya kapsam kararı ver (kanitla_cevaplandi / cevapsiz / uydurma_suphesi + cümle yerleri).")
SUMMARY = "soru-kapsami.json"
# FR-0833 "Açıklama Metni Yazımı" bölümünün beş sorusu (sıra kılavuzdaki gibi; kimlikler sabit).
SORULAR = (("surec", "Süreç nasıl yürütülüyor / planlama ve uygulama nasıl yapılıyor?"),
           ("izleme", "İzleme ve değerlendirme nasıl yapılıyor?"),
           ("iyilestirme", "İyileştirmeye yönelik adımlar atılıyor mu?"),
           ("kanitlar", "Hangi kanıtlarınız mevcut / Biriminize özgü örnek olabilecek uygulama kanıtınız var mı?"),
           ("onceki_yil", "Bir önceki yıla göre farklı neler var?"))
SORU_DURUM = ("kanitla_cevaplandi", "cevapsiz", "uydurma_suphesi")
DENETLENMEDI = "denetlenmedi"


def load_log(ws: Workspace) -> dict[str, dict]:
    p = ws.root / LOG
    return {r["olcut"]: r for r in read_jsonl(p)} if p.exists() else {}


def save_log(ws: Workspace, recs: dict[str, dict]) -> Path:
    p = ws.root / LOG
    write_jsonl(p, [recs[k] for k in sorted(recs, key=id_key)])
    return p


def load_human(ws: Workspace) -> list[dict]:
    p = ws.root / HUMAN
    return [r for r in read_jsonl(p) if r.get("olcut") and r.get("karar") in HUMAN_KARARLAR] if p.exists() else []


def limit_for(ws: Workspace, olcut: str, human: list[dict] | None = None) -> int:
    """Ölçütün yeniden yazım tur sınırı: yapılandırma + kullanıcının `tekrar` kararları."""
    human = load_human(ws) if human is None else human
    return W.rewrite_limit(ws.root) + sum(1 for r in human if r["olcut"] == olcut and r["karar"] == "tekrar")


def excluded(t: dict, human: list[dict]) -> bool:
    """Kullanıcı bu metni (aynı içerik) rapordan çıkarmaya karar verdi mi."""
    sha = W.text_sha(t)
    return any(r["olcut"] == t["olcut"] and r["karar"] == "cikar" and r.get("metin_sha") == sha for r in human)


def accepted(t: dict, human: list[dict]) -> bool:
    """Kullanıcı bu reddedilmiş metni (aynı içerik) olduğu gibi kabul etti mi."""
    sha = W.text_sha(t)
    return any(r["olcut"] == t["olcut"] and r["karar"] == "kabul" and r.get("metin_sha") == sha for r in human)


def rejected(ws: Workspace, log: dict | None = None, only: list[str] | None = None) -> dict[str, dict]:
    """Doğrulamada (kod ya da ajan) reddedilmiş, kaydı güncel metinler: {ölçüt: metin}."""
    log = load_log(ws) if log is None else log
    out = {}
    for t in _texts(ws, only):
        rec = log.get(t["olcut"])
        if (t.get("durum") == "reddedildi" and rec and rec.get("durum") == "reddedildi"
                and rec.get("metin_sha") == W.text_sha(t)):
            out[t["olcut"]] = t
    return out


def decide(ws_root: Path, olcut: str, karar: str, note: str = "") -> dict:
    """Kullanıcının reddedilen metin kararı → verify-insan.jsonl (ajan kendi kararını yazmaz)."""
    ws = Workspace(Path(ws_root))
    if karar not in HUMAN_KARARLAR:
        raise ValueError(f"karar '{karar}' geçersiz ({' | '.join(HUMAN_KARARLAR)})")
    t = W.load_text(ws, olcut)
    if not t:
        raise FileNotFoundError(f"texts/{olcut}.json yok")
    log = load_log(ws)
    if olcut not in rejected(ws, log, only=[olcut]):
        raise ValueError(f"{olcut} doğrulamada reddedilmiş (güncel kayıtlı) bir metin değil (durum: {t.get('durum')})")
    prev = log[olcut]
    if karar == "kabul" and prev.get("asama") != "model":
        raise ValueError(f"{olcut} kod denetiminde reddedildi (atıf/alıntı/OD kusuru); insan onayıyla "
                         "kabul edilemez: `tekrar` ya da `cikar`")
    rec = {"olcut": olcut, "karar": karar, "metin_sha": W.text_sha(t), "tur": int(t.get("tur") or 0),
           "not": note, "zaman": K.now()}
    if karar == "kabul":
        rec["dogrulayici_reddi"] = list(prev.get("gerekce") or [])
    with open(ws.root / HUMAN, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if karar == "cikar":
        t = dict(t)
        t["insan_karari"] = "cikar"
        (W.texts_dir(ws) / f"{olcut}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    if karar == "kabul":
        _accept(ws, t, prev, rec, log)
    return {**rec, "sinir": limit_for(ws, olcut)}


def accept_trace(why: list[str]) -> str:
    return f"{KABUL_IZI} (doğrulayıcı reddi: {'; '.join(why) or 'gerekçe yok'})"


def _accept(ws: Workspace, t: dict, prev: dict, rec: dict, log: dict) -> None:
    """`kabul`: metin `dogrulandi` olur (render/denetle/yonler geçerli sayar); doğrulayıcının reddi
    kayıtta kalır (texts `dogrulama.dogrulayici_reddi`, verify.jsonl `dogrulayici_reddi`)."""
    why = list(prev.get("gerekce") or [])
    iz = accept_trace(why)
    onay = {"karar": "kabul", "kayit": HUMAN, "not": rec["not"], "zaman": rec["zaman"]}
    t = dict(t)
    t["durum"] = "dogrulandi"
    t["insan_karari"] = "kabul"
    t["dogrulama"] = {"kayit": LOG, "model": prev.get("model"), "gerekce": [iz], "insan_onayi": onay,
                      "dogrulayici_reddi": why, "zaman": rec["zaman"]}
    (W.texts_dir(ws) / f"{t['olcut']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    log[t["olcut"]] = {**prev, "durum": "dogrulandi", "asama": "insan", "gerekce": [iz],
                       "insan_onayi": onay,
                       "dogrulayici_reddi": {"asama": prev.get("asama"), "model": prev.get("model"),
                                             "gorev_surumu": prev.get("gorev_surumu"), "gerekce": why,
                                             "zaman": prev.get("zaman")}}
    save_log(ws, log)
    write_summary(ws, log)


def _texts(ws: Workspace, only: list[str] | None) -> list[dict]:
    d = W.texts_dir(ws)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob("*.json"), key=lambda p: id_key(p.stem)):
        if only and p.stem not in only:
            continue
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


def _paras(t: dict) -> tuple[list[str], str]:
    return [p["metin"] for p in t.get("paragraflar") or []], t.get("onceki_yila_gore") or ""


def code_check(src: W.Sources, t: dict) -> list[dict]:
    """Kod denetimi (model yok) → sorun listesi [{yer, kod, ayrinti}]."""
    c = t["olcut"]
    od_now = src.od(c)
    paras, onceki = _paras(t)
    issues = T.check_text(paras, onceki, index_nos=src.index_nos(c), od=min(od_now, int(t.get("od_onerisi") or od_now)),
                          komisyon=bool(src.notes.get(c)))
    if int(t.get("od_onerisi") or 0) > od_now:
        issues.append({"yer": "-", "metin": "", "kod": "od_asimi",
                       "ayrinti": f"metin OD{t['od_onerisi']} için yazıldı; güncel önerilen OD{od_now}"})
    cited = set(W._cited(paras, onceki))
    ev = src.evidence(c, only=cited)
    issues += T.content_issues(paras, onceki, donem=src.donem, donem_ici=set(W.in_period_nos(ev, src.donem)))
    for e in ev:
        if src.doc_text(e["doc_id"]) is None:
            issues.append({"yer": "-", "metin": "", "kod": "belge_metni_yok",
                           "ayrinti": f"[{e['no']}] belge metni yok ({e['doc_id'] or 'doc_id boş'}); alıntı denetlenemedi"})
            continue
        if not e["alintilar"]:
            issues.append({"yer": "-", "metin": "", "kod": "alintisiz_kanit", "ayrinti": f"[{e['no']}] alıntı yok"})
        for q in e["alintilar"]:
            if not q["alinti_belgede"]:
                issues.append({"yer": "-", "metin": "", "kod": "alinti_belgede_yok",
                               "ayrinti": f"[{e['no']}] «{q['alinti'][:80]}…» belge metninde bulunamadı"})
    return issues


def content_check(src: W.Sources, t: dict) -> list[dict]:
    """Kanıt paketine göre içerik denetimi (dönem içi kayıt, fakülte değeri; bkz. text.content_issues):
    doğrulanmış eski metinlere de uygulanır — kural metin yazıldıktan sonra eklendiyse metin yeni
    kuralla yeniden yazıma gider (kör test 2026-11-20: v3 kuralı eski metinlere uygulanmamıştı)."""
    c = t["olcut"]
    paras, onceki = _paras(t)
    cited = set(W._cited(paras, onceki))
    ev = src.evidence(c, only=cited)
    return T.content_issues(paras, onceki, donem=src.donem, donem_ici=set(W.in_period_nos(ev, src.donem)))


def render_sentences(rows: list[dict]) -> str:
    return "\n".join(f"{r['yer']}: {r['metin']}" for r in rows)


def render_questions() -> str:
    return "\n".join(f"- {k}: {q}" for k, q in SORULAR)


def verify_inputs(src: W.Sources, t: dict) -> tuple[dict, dict]:
    c = t["olcut"]
    paras, onceki = _paras(t)
    rows = T.sentence_rows(paras, onceki)
    cited = set(W._cited(paras, onceki))
    ev = src.evidence(c, only=cited)
    inputs = {"olcut": W.render_criterion(src.cs, c, od=t.get("od_onerisi")),
              "cumleler": render_sentences(rows),
              "kanitlar": W.render_evidence(ev, src.cs),
              "onceki_metin": src.previous_text(c) if any(r["bolum"] == "onceki_yila_gore" for r in rows) else "yok",
              "komisyon_bilgisi": src.notes_text(c),
              "sorular": render_questions()}
    meta = {"olcut": c, "metin_sha": W.text_sha(t),
            "cumleler": [{"yer": r["yer"], "metin": r["metin"], "atiflar": T.citations(r["metin"])} for r in rows]}
    return inputs, meta


def _set_status(ws: Workspace, t: dict, durum: str, gerekce: list[str], model: str | None,
                kapsam: dict | None = None) -> None:
    t = dict(t)
    t["durum"] = durum
    t["dogrulama"] = {"kayit": LOG, "model": model, "gerekce": gerekce, "zaman": K.now()}
    t["soru_kapsami"] = kapsam or unchecked()
    (W.texts_dir(ws) / f"{t['olcut']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")


def _sources(ws_root, index, audit, onceki, notes, backend) -> W.Sources:
    sp = W.source_paths(ws_root, index=index, audit=audit, onceki=onceki, notes=notes)
    return W.Sources(ws_root, index=sp["index"], audit=sp["audit"], onceki=sp["onceki"], notes=sp["notes"],
                     verify=backend.verify_quote)


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False, index=None, audit=None,
            onceki=None, notes=None, backend: W.Backend | None = None) -> dict:
    backend = backend or W.Backend()
    src = _sources(ws_root, index, audit, onceki, notes, backend)
    ws = src.ws
    log = load_log(ws)
    d = W.work_dir(ws, STAGE)
    d.mkdir(parents=True, exist_ok=True)
    human = load_human(ws)
    st = {"paket": 0, "yeni": 0, "zaten_tamam": 0, "kod_reddi": {}, "metin": 0, "yeni_kural": [],
          "insan_kabulu": []}
    for t in _texts(ws, only):
        st["metin"] += 1
        c = t["olcut"]
        sha = W.text_sha(t)
        prev = log.get(c)
        renew = False
        if accepted(t, human) and t.get("durum") == "dogrulandi":
            # insan onayı (`verify karar … kabul`) bu içeriğe bağlıdır; model yeniden sorulmaz
            st["zaten_tamam"] += 1
            st["insan_kabulu"].append(c)
            continue
        if (not redo and not only and prev and prev.get("metin_sha") == sha and prev.get("durum") in FINAL
                and t.get("durum") == prev["durum"]):
            # doğrulanmış metin sonradan eklenen içerik kuralına takılıyorsa yeniden yazıma gider;
            # yeni kural reddi tur sayacını sıfırlar (eski turlar bu kurala göre yapılmadı)
            if t.get("durum") != "dogrulandi" or not content_check(src, t):
                st["zaten_tamam"] += 1
                continue
            renew = True
        issues = code_check(src, t)
        if renew and issues:
            t = {**t, "tur": 0}
            st["yeni_kural"].append(c)
        if issues:
            why = [f"{i['yer']} {i['kod']}: {i['ayrinti']}" for i in issues]
            log[c] = {"olcut": c, "durum": "reddedildi", "metin_sha": sha, "asama": "kod",
                      "tur": int(t.get("tur") or 0),
                      "kod_denetimi": issues, "cumleler": [], "soru_kapsami": unchecked(), "gerekce": why,
                      "model": None, "gorev_surumu": None, "zaman": K.now()}
            _set_status(ws, t, "reddedildi", why, None)
            for f in (d / f"{c}.json", d / f"{c}.out.json"):
                if f.exists():
                    f.replace(f.with_name(f.name + ".eski"))
            st["kod_reddi"][c] = why
            continue
        inputs, meta = verify_inputs(src, t)
        r = backend.render_task(TASK, inputs)
        st["paket"] += 1
        st["yeni"] += K.write_pkg(d, c, r, meta, force=redo)
        if t.get("durum") in FINAL:          # yeniden doğrulanacak: eski karar geçersiz
            _set_status(ws, t, "taslak", [], None)
    save_log(ws, log)
    write_summary(ws, log)
    st["bekleyen"] = K.write_readme(d, task=TASK, version=W.task_version(TASK), cmd="verify", rule=RULE)
    st["klasor"] = str(d)
    # alan düzeyi Güçlü / Gelişmeye Açık Yönler (bidr/write/yonler.py) aynı akışla doğrulanır
    if not only:
        from bidr.write import yonler as Y
        st["yonler"] = Y.verify_prepare(ws_root, redo=redo, backend=backend)
    return st


def judge(meta: dict, out: dict) -> tuple[str | None, list[dict], list[str]]:
    """(durum | None, cümle kararları, hatalar). Her cümleye tam bir karar gerekir."""
    want = [c["yer"] for c in meta["cumleler"]]
    got: dict[str, dict] = {}
    errs = []
    for x in out.get("cumleler") or []:
        if x["yer"] in got:
            errs.append(f"{x['yer']}: birden çok karar")
        elif x["yer"] not in want:
            errs.append(f"{x['yer']}: metinde böyle bir cümle yok")
        got[x["yer"]] = x
    miss = [y for y in want if y not in got]
    if miss:
        errs.append(f"kararı olmayan cümle: {', '.join(miss)}")
    if errs:
        return None, [], errs
    rows = [{**c, "karar": got[c["yer"]]["karar"], "gerekce": got[c["yer"]]["gerekce"]} for c in meta["cumleler"]]
    bad = [r for r in rows if r["karar"] != "destekleniyor"]
    return ("reddedildi" if bad else "dogrulandi"), rows, []


def unchecked() -> dict:
    return {"durum": DENETLENMEDI, "sorular": []}


def judge_questions(meta: dict, out: dict) -> tuple[dict | None, list[str]]:
    """Beş sorunun kapsam kararı → (soru_kapsami | None, hatalar). Her soruya tam bir karar;
    `kanitla_cevaplandi` ve `uydurma_suphesi` metindeki cümlelere yer verir, `cevapsiz` vermez;
    `kanitla_cevaplandi` en az bir kanıt atıflı cümleye dayanır (`[komisyon]` kanıt değildir)."""
    by_yer = {c["yer"]: c for c in meta["cumleler"]}
    got: dict[str, dict] = {}
    errs = []
    for x in out.get("sorular") or []:
        k = x["soru"]
        if k in got:
            errs.append(f"soru {k}: birden çok karar")
            continue
        got[k] = x
        yer = x.get("yerler") or []
        unknown = [y for y in yer if y not in by_yer]
        if unknown:
            errs.append(f"soru {k}: metinde böyle bir cümle yok ({', '.join(unknown)})")
        if len(set(yer)) != len(yer):
            errs.append(f"soru {k}: yer yinelenmiş")
        if x["durum"] == "cevapsiz" and yer:
            errs.append(f"soru {k}: cevapsiz ama cümle yeri verilmiş")
        if x["durum"] != "cevapsiz" and not yer:
            errs.append(f"soru {k}: {x['durum']} için cümle yeri gerekir")
        if (x["durum"] == "kanitla_cevaplandi" and yer and not unknown
                and not any(by_yer[y].get("atiflar") for y in yer)):
            errs.append(f"soru {k}: kanitla_cevaplandi ama cümleler kanıta atıf yapmıyor")
    miss = [k for k, _ in SORULAR if k not in got]
    if miss:
        errs.append(f"kararı olmayan soru: {', '.join(miss)}")
    if errs:
        return None, errs
    qs = [{"soru": k, "baslik": q, "durum": got[k]["durum"], "yerler": list(got[k].get("yerler") or []),
           "gerekce": got[k].get("gerekce") or ""} for k, q in SORULAR]
    return {"durum": "denetlendi", "sorular": qs}, []


def coverage_of(rec: dict | None, t: dict | None) -> dict:
    """Kaydın güncel metne ait soru kapsamı; alan yoksa (eski görev sürümü, kod reddi) ya da
    kayıt eskidiyse "denetlenmedi"."""
    if not rec or not t or rec.get("metin_sha") != W.text_sha(t):
        return unchecked()
    k = rec.get("soru_kapsami")
    return k if k and k.get("durum") == "denetlendi" else unchecked()


def summary(ws: Workspace, log: dict | None = None) -> dict:
    """`soru-kapsami.json`: ölçüt başına beş sorunun kapsamı + gaps.md için "kanıtla
    cevaplanmayan sorular" listesi (yalnız denetlenmiş metinler; denetlenmeyenler ayrı)."""
    log = load_log(ws) if log is None else log
    olc, open_, unchk = {}, [], []
    for t in _texts(ws, None):
        c = t["olcut"]
        k = coverage_of(log.get(c), t)
        e = {"durum": k["durum"], "metin_durumu": t.get("durum"), "metin_sha": W.text_sha(t),
             "sorular": {q["soru"]: {"durum": q["durum"], "yerler": q["yerler"], "gerekce": q["gerekce"]}
                         for q in k["sorular"]}}
        if t.get("insan_karari"):
            e["insan_karari"] = t["insan_karari"]
        e["kanitla_cevaplanmayan"] = [q["soru"] for q in k["sorular"] if q["durum"] != "kanitla_cevaplandi"]
        olc[c] = e
        if k["durum"] != "denetlendi":
            unchk.append(c)
        for q in k["sorular"]:
            if q["durum"] != "kanitla_cevaplandi":
                open_.append({"olcut": c, "soru": q["soru"], "baslik": q["baslik"], "durum": q["durum"],
                              "yerler": q["yerler"], "gerekce": q["gerekce"]})
    return {"gorev": TASK, "sorular": [{"soru": k, "baslik": q} for k, q in SORULAR],
            "olcutler": olc, "kanitla_cevaplanmayan": open_, "denetlenmedi": unchk}


def write_summary(ws: Workspace, log: dict | None = None) -> Path:
    p = ws.root / SUMMARY
    p.write_text(json.dumps(summary(ws, log), ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend: W.Backend | None = None) -> dict:
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    log = load_log(ws)
    d = W.work_dir(ws, STAGE)
    st = {"dogrulandi": [], "reddedildi": {}, "bekleyen": [], "gecersiz": {}, "eski": [], "degismedi": 0}
    version = W.task_version(TASK)
    human = load_human(ws)
    for p in K.pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        c, meta = pkg["olcut"], pkg["meta"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(c)
            continue
        t = W.load_text(ws, c)
        if t and accepted(t, human) and t.get("durum") == "dogrulandi" and W.text_sha(t) == meta["metin_sha"]:
            st["degismedi"] += 1          # insan onaylı metin: doğrulayıcı cevabı yeniden işlenmez
            continue
        if str(pkg["surum"]) != version or not t or W.text_sha(t) != meta["metin_sha"]:
            st["eski"].append(c)
            continue
        raw = outp.read_text(encoding="utf-8")
        csha = K.sha(raw)
        prev = log.get(c)
        if (prev and prev.get("cevap_sha") == csha and prev.get("metin_sha") == meta["metin_sha"]
                and t.get("durum") == prev.get("durum")):
            st["degismedi"] += 1
            continue
        out, errs = backend.validate_output(TASK, raw)
        if out is None:
            st["gecersiz"][c] = errs[:5]
            continue
        durum, rows, errs = judge(meta, out)
        kapsam, qerrs = judge_questions(meta, out)
        if durum is None or kapsam is None:
            st["gecersiz"][c] = errs + qerrs
            continue
        why = [f"{r['yer']} ({r['karar']}): {r['gerekce']} — «{r['metin']}»" for r in rows
               if r["karar"] != "destekleniyor"]
        fab = [q for q in kapsam["sorular"] if q["durum"] == "uydurma_suphesi"]
        why += [f"soru {q['soru']} (uydurma_suphesi; {', '.join(q['yerler'])}): {q['gerekce']}" for q in fab]
        if fab:
            durum = "reddedildi"
        log[c] = {"olcut": c, "durum": durum, "metin_sha": meta["metin_sha"], "asama": "model",
                  "tur": int(t.get("tur") or 0),
                  "kod_denetimi": [], "cumleler": rows, "soru_kapsami": kapsam, "genel": out.get("genel", ""),
                  "gerekce": why, "model": model, "gorev_surumu": str(pkg["surum"]), "istem_sha": pkg["istem_sha"],
                  "cevap_sha": csha, "zaman": K.now()}
        _set_status(ws, t, durum, why, model, kapsam)
        if durum == "dogrulandi":
            st["dogrulandi"].append(c)
        else:
            st["reddedildi"][c] = why
    save_log(ws, log)
    write_summary(ws, log)
    K.write_invalid(d, TASK, st["gecersiz"])
    from bidr.write import yonler as Y
    st["yonler"] = Y.verify_apply(ws_root, model=model, backend=backend)
    return st
