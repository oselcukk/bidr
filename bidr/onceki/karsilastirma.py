"""`bidr write karsilastirma-ekle prepare|apply|sonuc`: var olan doğrulanmış metinlere TEK SEFERLİK, ucuz
karşılaştırma geçişi (geçen yılın raporu sonradan yüklendiğinde). Kendiliğinden çalışmaz.

prepare: geçen yıl kaydı olan, `dogrulandi` durumundaki, daha önce bu geçişten geçmemiş (`karsilastirma` alanı
  yok) ve geçen yıl bağlamıyla yazılmamış (`kaynak.onceki_yil` yok) her metin için `work/karsilastirma/<ölçüt>.json`.
  Paket: mevcut metnin cümleleri (yer kimliğiyle), ölçütün geçen yılki özeti, bu yılın kanıtları.
apply: cevap `yok` → metne `karsilastirma: {durum: degisiklik_yok}` işareti (metin özeti değişmez, yeniden
  doğrulanmaz). `ekle`/`degistir` → ekleme KODLA yapılır (yalnız o cümleler değişir; geri kalan metin, atıfları ve OD
  aynı); yeni cümlelerin kod denetimi (atıf listede, OD dili, OD anma; değiştirilen cümlenin atıfları korunmuş;
  metne yeni içerik bulgusu gelmemiş). Geçen metin `taslak` olur, eski hâli `karsilastirma.geri`de saklanır.
  Geçemeyen cevap `kod_reddi` olarak işaretlenir, metin aynen kalır.
Ardından yalnız değişen ölçütler `bidr verify prepare --only <liste>` / `verify apply` ile doğrulanır.
sonuc: doğrulamadan geçen ekleme `eklendi`; reddedilen ekleme düşer: eski metin, eski durumu ve eski doğrulama
  kaydı (verify.jsonl satırı) geri gelir, işaret `reddedildi`. `verify apply` sonunda da çağrılır.
Her durumda işaret kalır: aynı ölçütte ikinci çalıştırma paket üretmez.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key
from bidr.write import packages as K

from . import baglam as OY

TASK = "karsilastirma_ekle"
STAGE = "karsilastirma"
ALAN = "karsilastirma"
RULE = ("İstemdeki kurallara uy: metni yeniden yazma; gerekiyorsa 1-2 karşılaştırma cümlesi ekle ya da tek cümleyi "
        "karşılaştırmalı yap; her yeni cümle bu yılın kanıtına atıf yapar; karşılaştırma desteklenmiyorsa \"yok\".")
_OD_ANMA = re.compile(r"(?<![\[\w])OD\s*\d|olgunluk\s+düzey", re.I)


def _work(ws: Workspace) -> Path:
    return ws.root / "work" / STAGE


def _yaz_metin(ws: Workspace, t: dict) -> None:
    from bidr.write import run as W
    p = W.texts_dir(ws) / f"{t['olcut']}.json"
    gecici = p.with_name(p.name + ".yaziliyor")
    gecici.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(p)


def _rows(t: dict) -> list[dict]:
    from bidr.write import text as T
    return [r for r in T.sentence_rows([p["metin"] for p in t.get("paragraflar") or []], "")]


def adaylar(ws_root: Path, only: list[str] | None = None) -> dict:
    """{"paket": [ölçüt], "atlanan": {neden: [ölçüt]}} — paket alacak metinler ve atlanma nedenleri."""
    from bidr.write import run as W
    ws = Workspace(Path(ws_root))
    veri = OY.yukle(ws.root)
    st: dict = {"paket": [], "atlanan": {"gecen_yil_kaydi_yok": [], "dogrulanmamis": [], "zaten_islendi": [],
                                         "gecen_yil_baglamiyla_yazildi": []}}
    td = W.texts_dir(ws)
    if veri is None or not td.exists():
        return st
    for p in sorted((p for p in td.glob("*.json") if re.fullmatch(K.OLCUT_KEY, p.stem)), key=lambda p: id_key(p.stem)):
        if only and p.stem not in only:
            continue
        t = json.loads(p.read_text(encoding="utf-8"))
        c = t.get("olcut") or p.stem
        if OY.kayit(veri, c) is None:
            st["atlanan"]["gecen_yil_kaydi_yok"].append(c)
        elif t.get(ALAN):
            st["atlanan"]["zaten_islendi"].append(c)
        elif (t.get("kaynak") or {}).get("onceki_yil"):
            st["atlanan"]["gecen_yil_baglamiyla_yazildi"].append(c)
        elif t.get("durum") != "dogrulandi" or not t.get("paragraflar"):
            st["atlanan"]["dogrulanmamis"].append(c)
        else:
            st["paket"].append(c)
    return st


def prepare(ws_root: Path, *, only: list[str] | None = None, backend=None) -> dict:
    from bidr.write import run as W
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    veri = OY.yukle(ws.root)
    if veri is None:
        raise FileNotFoundError(f"geçen yılın raporu yok ({OY.yol(ws.root)}); önce `bidr onceki-yil cek`")
    st = adaylar(ws.root, only)
    sp = W.source_paths(ws.root)
    src = W.Sources(ws.root, index=sp["index"], audit=sp["audit"], onceki="", notes=sp["notes"],
                    verify=backend.verify_quote)
    d = _work(ws)
    d.mkdir(parents=True, exist_ok=True)
    yil = OY.yil_adi(src.donem)
    st["yeni"] = 0
    for c in list(st["paket"]):
        t = W.load_text(ws, c)
        rows = _rows(t)
        od = int(t.get("od_onerisi") or src.od(c))
        inputs = {"olcut": W.render_criterion(src.cs, c, od=od),
                  "cumleler": "\n".join(f"{r['yer']}: {r['metin']}" for r in rows),
                  "onceki_ozet": OY.ozet(OY.kayit(veri, c), OY.YAZIM_SINIRI),
                  "kanitlar": W.render_evidence(src.evidence(c), src.cs),
                  "od": str(od), "yil": yil}
        r = backend.render_task(TASK, inputs)
        meta = {"olcut": c, "metin_sha": W.text_sha(t), "od": od, "yil": yil,
                "cumleler": [{"yer": x["yer"], "metin": x["metin"]} for x in rows],
                "onceki_yil": OY.iz(veri, c)}
        st["yeni"] += K.write_pkg(d, c, r, meta)
    st["bekleyen"] = K.write_readme(d, task=TASK, version=W.task_version(TASK), cmd="write karsilastirma-ekle",
                                    rule=RULE)
    st["klasor"] = str(d)
    return st


def _birlestir(paragraflar: list[str], yer: str, islem: str, yeni: list[str]) -> list[str] | None:
    """Cümle düzeyinde kodla ekleme/değiştirme; dokunulmayan paragraflar aynen kalır. Yer yoksa None."""
    from bidr.write import text as T
    m = re.fullmatch(r"p(\d+)\.(\d+)", yer or "")
    if not m:
        return None
    i, j = int(m.group(1)) - 1, int(m.group(2)) - 1
    if not (0 <= i < len(paragraflar)):
        return None
    cs = T.split_sentences(paragraflar[i])
    if not (0 <= j < len(cs)):
        return None
    cs = cs[:j] + yeni + cs[j + 1:] if islem == "degistir" else cs[:j + 1] + yeni + cs[j + 1:]
    out = list(paragraflar)
    out[i] = " ".join(cs)
    return out


def _denetle(src, t: dict, meta: dict, out: dict) -> tuple[list[str] | None, list[str]]:
    """(yeni paragraflar | None, sorunlar)."""
    from bidr.write import text as T
    paras = [p["metin"] for p in t.get("paragraflar") or []]
    yeni = [" ".join(s.split()) for s in out.get("cumleler") or [] if s.strip()]
    if not yeni:
        return None, ["ekle/degistir için en az bir cümle gerekir"]
    sorun = []
    c, od = t["olcut"], int(meta["od"])
    nos = src.index_nos(c)
    for k, s in enumerate(yeni, 1):
        for x in T.check_sentence(s, index_nos=nos, od=od, komisyon=False):
            sorun.append(f"yeni cümle {k} {x['kod']}: {x['ayrinti']}")
        if _OD_ANMA.search(T.ATIF.sub(" ", s)):
            sorun.append(f"yeni cümle {k}: OD ya da olgunluk düzeyi anılıyor (geçen yılın OD'si bu yılınkini belirlemez)")
    eski = {r["yer"]: r["metin"] for r in meta["cumleler"]}
    if out["islem"] == "degistir":
        if out["yer"] not in eski:
            return None, [f"{out['yer']}: metinde böyle bir cümle yok"]
        kayip = set(T.citations(eski[out["yer"]])) - {a for s in yeni for a in T.citations(s)}
        if kayip:
            sorun.append(f"{out['yer']}: değiştirilen cümlenin atfı düştü: {', '.join(sorted(kayip))}")
    birlesik = _birlestir(paras, out["yer"], out["islem"], yeni)
    if birlesik is None:
        return None, [f"{out['yer']}: metinde böyle bir cümle yok"]
    once = {(i["kod"], i["ayrinti"]) for i in T.content_issues(paras, t.get("onceki_yila_gore") or "",
                                                                 donem=src.donem, donem_ici=_donem_ici(src, c),
                                                                 karsilastirma=src.onceki_yil is not None)}
    for i in T.content_issues(birlesik, t.get("onceki_yila_gore") or "", donem=src.donem, donem_ici=_donem_ici(src, c),
                                karsilastirma=src.onceki_yil is not None):
        if (i["kod"], i["ayrinti"]) not in once:
            sorun.append(f"{i.get('yer', '-')} {i['kod']}: {i['ayrinti']}")
    return (None if sorun else birlesik), sorun


def _donem_ici(src, c: str) -> set[str]:
    from bidr.write import run as W
    return set(W.in_period_nos(src.evidence(c), src.donem))


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend=None) -> dict:
    from bidr.write import run as W
    from bidr.verify import run as V
    backend = backend or W.Backend()
    ws = Workspace(Path(ws_root))
    d = _work(ws)
    st = {"degisiklik_yok": [], "eklendi": [], "kod_reddi": {}, "gecersiz": {}, "bekleyen": [], "eski": []}
    if not d.exists():
        return st
    sp = W.source_paths(ws.root)
    src = W.Sources(ws.root, index=sp["index"], audit=sp["audit"], onceki="", notes=sp["notes"],
                    verify=backend.verify_quote)
    log = V.load_log(ws)
    for p in K.pkg_paths(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        c, meta = pkg["olcut"], pkg["meta"]
        outp = d / pkg["cikti_dosyasi"]
        t = W.load_text(ws, c)
        if t and t.get(ALAN):
            continue                                 # işlendi (işaret var)
        if not outp.exists():
            st["bekleyen"].append(c)
            continue
        if not t or W.text_sha(t) != meta["metin_sha"] or t.get("durum") != "dogrulandi":
            st["eski"].append(c)                     # metin paketten sonra değişti
            continue
        raw = outp.read_text(encoding="utf-8")
        out, errs = backend.validate_output(TASK, raw)
        if out is None:
            st["gecersiz"][c] = errs[:5]
            continue
        iz = {"zaman": K.now(), "model": model, "islem": out["islem"], "yer": out.get("yer") or "",
              "cumleler": out.get("cumleler") or [], "gerekce": out.get("gerekce") or "",
              "onceki_yil": meta.get("onceki_yil"), "cevap_sha": K.sha(raw)}
        if out["islem"] == "yok":
            t[ALAN] = {"durum": "degisiklik_yok", **iz}
            _yaz_metin(ws, t)
            st["degisiklik_yok"].append(c)
            continue
        yeni, sorun = _denetle(src, t, meta, out)
        if yeni is None:
            t[ALAN] = {"durum": "kod_reddi", "sorunlar": sorun, **iz}
            _yaz_metin(ws, t)
            st["kod_reddi"][c] = sorun
            continue
        geri = {k: t.get(k) for k in ("paragraflar", "kanitlar", "durum", "dogrulama", "soru_kapsami")}
        geri["dogrulama_kaydi"] = log.get(c)
        from bidr.write import text as T
        t = dict(t)
        t["paragraflar"] = [{"metin": m, "atiflar": W._cited([m], "")} for m in yeni]
        byno = {k["no"]: k for k in t.get("kanitlar") or []}
        for e in src.evidence(c):
            byno.setdefault(e["no"], {"no": e["no"], "ad": e["ad"], "dosya": e["dosya"]})
        t["kanitlar"] = [byno[n] for n in W._cited(yeni, t.get("onceki_yila_gore") or "") if n in byno]
        t["durum"] = "taslak"
        t[ALAN] = {"durum": "dogrulamada", **iz, "geri": geri}
        _yaz_metin(ws, t)
        st["eklendi"].append(c)
    K.write_invalid(d, TASK, {**st["gecersiz"]})
    return st


def sonuc(ws_root: Path) -> dict:
    """Doğrulaması biten eklemeleri sonuçlandırır (bkz. modül belgesi)."""
    from bidr.write import run as W
    from bidr.verify import run as V
    ws = Workspace(Path(ws_root))
    st = {"eklendi": [], "reddedildi": [], "dogrulama_bekliyor": []}
    td = W.texts_dir(ws)
    if not td.exists():
        return st
    log = None
    for p in sorted((p for p in td.glob("*.json") if re.fullmatch(K.OLCUT_KEY, p.stem)), key=lambda p: id_key(p.stem)):
        t = json.loads(p.read_text(encoding="utf-8"))
        k = t.get(ALAN) or {}
        if k.get("durum") != "dogrulamada":
            continue
        c = t["olcut"]
        if t.get("durum") == "dogrulandi":
            k = {x: v for x, v in k.items() if x != "geri"}
            t[ALAN] = {**k, "durum": "eklendi", "sonuc_zamani": K.now()}
            _yaz_metin(ws, t)
            st["eklendi"].append(c)
        elif t.get("durum") == "reddedildi":
            if log is None:
                log = V.load_log(ws)
            geri = k.get("geri") or {}
            ret = (t.get("dogrulama") or {}).get("gerekce") or []
            for f in ("paragraflar", "kanitlar", "durum", "dogrulama", "soru_kapsami"):
                if geri.get(f) is None:
                    t.pop(f, None)
                else:
                    t[f] = geri[f]
            if geri.get("dogrulama_kaydi") is not None:
                log[c] = geri["dogrulama_kaydi"]
            else:
                log.pop(c, None)
            for f in (ws.root / "work" / V.STAGE / f"{c}.json", ws.root / "work" / V.STAGE / f"{c}.out.json"):
                if f.exists():                       # eklemenin doğrulama paketi: eski metne ait değil
                    f.replace(f.with_name(f.name + ".eski"))
            k = {x: v for x, v in k.items() if x != "geri"}
            t[ALAN] = {**k, "durum": "reddedildi", "ret_gerekcesi": ret[:10], "sonuc_zamani": K.now()}
            _yaz_metin(ws, t)
            st["reddedildi"].append(c)
        else:
            st["dogrulama_bekliyor"].append(c)
    if log is not None:
        V.save_log(ws, log)
        V.write_summary(ws, log)
    return st
