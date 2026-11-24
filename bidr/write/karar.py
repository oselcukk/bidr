"""Yazım kod denetimi takılırsa insan kararı: `bidr write karar -w WS <ölçüt> cikar|tekrar|kabul`.

`bidr write apply` kod denetimini (bidr/write/text.py: atıf, alıntı, OD, yasak ifade …) geçemeyen cevabı
yazmaz (GECERSIZ.md) ve ajan yeniden yazar. Aynı paket için yazılan ve geçemeyen her ayrı cevap bir
deneme sayılır (`write-kod-denemeleri.json`, cevabın özeti ve sorunları). İlk yazım + sınır kadar
yeniden yazım (`rapor.yeniden_yazim_siniri`, vars. 2; kullanıcının her `tekrar` kararı bir tur ekler)
sonra hâlâ geçemeyen ölçüt insan kararı bekler: `bidr next` "KULLANICI gerekli" ve karar bekleyen
ölçüt listesi (`karar_bekleyen`) verir; ajan karar vermez.

Kararlar (`write-insan.jsonl`, son geçemeyen cevaba bağlı):
- `cikar`: ölçütün metni rapora girmez. Son cevap `texts/<ölçüt>.json` olarak `durum: reddedildi`,
  `insan_karari: cikar` yazılır; doğrulama kaydına (`verify.jsonl`) `asama: yazim_kod` reddi girer,
  `bidr verify` bu metni kullanıcı kararıyla çıkarılmış sayar (yeniden yazıma göndermez).
- `tekrar`: bir yeniden yazım turu daha (ajan GECERSIZ.md'deki gerekçeyle yeniden yazar).
- `kabul`: yalnız bütün bulgular üslup türündeyse (`USLUP`: abartı, slogan, koçluk, tahmin dili ve OD
  dili `od_asimi`); atıf, alıntı, bilinmeyen atıf, gelecek vaadi, dönem, içerik bulgularından biri bile
  varsa reddedilir. Metin `texts/<ölçüt>.json` olur (`durum: taslak`, `yazim_karari`); bağımsız
  doğrulama (`bidr verify`) yine yapılır, kod denetimi yalnız kabul edilen üslup bulgularını yok sayar.
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from . import packages as K

DENEMELER = "write-kod-denemeleri.json"
HUMAN = "write-insan.jsonl"
KARARLAR = ("cikar", "tekrar", "kabul")
USLUP_TURLERI = ("abartı", "slogan", "koçluk", "tahmin")      # yasak_ifade türleri (text.YASAK)
USLUP_KODLARI = ("od_asimi",)                                  # OD dili


def uslup_mu(issue: dict) -> bool:
    """Bulgu yalnız üslup mu (insan kabulüyle geçebilir)."""
    kod = issue.get("kod")
    if kod in USLUP_KODLARI:
        return True
    if kod == "yasak_ifade":
        return str(issue.get("ayrinti") or "").split(":", 1)[0].strip() in USLUP_TURLERI
    return False


def _load(ws: Workspace) -> dict:
    p = ws.root / DENEMELER
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _save(ws: Workspace, d: dict) -> None:
    p = ws.root / DENEMELER
    if not d:
        if p.exists():
            p.unlink()
        return
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def load_human(ws: Workspace) -> list[dict]:
    p = ws.root / HUMAN
    return [r for r in read_jsonl(p) if r.get("olcut") and r.get("karar") in KARARLAR] if p.exists() else []


def basarisiz(ws: Workspace, olcut: str, istem_sha: str, raw: str, issues: list[dict],
              model: str | None = None) -> int:
    """Kod denetimini geçemeyen cevap → deneme kaydı (aynı cevap ikinci kez sayılmaz). → deneme sayısı."""
    d = _load(ws)
    e = d.get(olcut)
    if not e or e.get("istem_sha") != istem_sha:             # yeni paket: sayaç baştan
        e = {"istem_sha": istem_sha, "denemeler": []}
    cs = K.sha(raw)
    if not any(x["cevap_sha"] == cs for x in e["denemeler"]):
        e["denemeler"].append({"cevap_sha": cs, "cevap": raw, "model": model, "zaman": K.now(),
                               "sorunlar": [{k: i.get(k, "") for k in ("yer", "kod", "ayrinti")} for i in issues]})
    d[olcut] = e
    _save(ws, d)
    return len(e["denemeler"])


def gecti(ws: Workspace, olcut: str) -> None:
    """Cevap kod denetimini geçti: deneme kaydı kapanır."""
    d = _load(ws)
    if d.pop(olcut, None) is not None:
        _save(ws, d)


def sinir(ws: Workspace, olcut: str, istem_sha: str, human: list[dict] | None = None) -> int:
    """Yeniden yazım sınırı: yapılandırma + bu paket için kullanıcının `tekrar` kararları."""
    from . import run as W
    human = load_human(ws) if human is None else human
    return W.rewrite_limit(ws.root) + sum(1 for r in human if r["olcut"] == olcut and r["karar"] == "tekrar"
                                          and r.get("istem_sha") == istem_sha)


def _kararli(human: list[dict], olcut: str, istem_sha: str, cevap_sha: str) -> dict | None:
    return next((r for r in reversed(human) if r["olcut"] == olcut and r["karar"] in ("cikar", "kabul")
                 and r.get("istem_sha") == istem_sha and r.get("cevap_sha") == cevap_sha), None)


def bekleyen(ws: Workspace, istemler: dict[str, str] | None = None) -> list[dict]:
    """İnsan kararı bekleyen ölçütler: [{olcut, deneme, sinir, sorunlar, kabul_edilebilir}].
    `istemler`: {ölçüt: güncel paketin istem_sha'sı} (verilmezse work/write'tan okunur); paketi
    değişmiş ölçütün eski denemeleri sayılmaz."""
    from . import run as W
    if istemler is None:
        istemler = {}
        d = W.work_dir(ws)
        for p in K.pkg_paths(d) if d.exists() else []:
            try:
                istemler[p.stem] = json.loads(p.read_text(encoding="utf-8")).get("istem_sha")
            except (OSError, ValueError):
                pass
    human = load_human(ws)
    out = []
    for c, e in sorted(_load(ws).items()):
        if istemler.get(c) != e.get("istem_sha") or not e.get("denemeler"):
            continue
        son = e["denemeler"][-1]
        lim = sinir(ws, c, e["istem_sha"], human)
        if len(e["denemeler"]) <= lim or _kararli(human, c, e["istem_sha"], son["cevap_sha"]):
            continue
        out.append({"olcut": c, "deneme": len(e["denemeler"]), "sinir": lim, "sorunlar": son["sorunlar"],
                    "kabul_edilebilir": bool(son["sorunlar"]) and all(uslup_mu(i) for i in son["sorunlar"])})
    from bidr.criteria.model import id_key
    return sorted(out, key=lambda x: id_key(x["olcut"]))


def karar(ws_root: Path, olcut: str, k: str, note: str = "") -> dict:
    """KULLANICININ kararı (ajan kendi kararını yazmaz) → write-insan.jsonl (+ cikar/kabul: texts/)."""
    from . import run as W
    ws = Workspace(Path(ws_root))
    if k not in KARARLAR:
        raise ValueError(f"karar '{k}' geçersiz ({' | '.join(KARARLAR)})")
    b = {x["olcut"]: x for x in bekleyen(ws)}
    if olcut not in b:
        raise ValueError(f"{olcut} yazım kod denetiminde insan kararı bekleyen bir ölçüt değil "
                         f"(bekleyen: {', '.join(b) or 'yok'})")
    e = _load(ws)[olcut]
    son = e["denemeler"][-1]
    if k == "kabul" and not b[olcut]["kabul_edilebilir"]:
        diger = sorted({i["kod"] for i in son["sorunlar"] if not uslup_mu(i)})
        raise ValueError(f"{olcut}: kabul yalnız üslup bulgularında (abartı/slogan/koçluk/tahmin/OD dili) "
                         f"geçerli; bu cevapta {', '.join(diger)} var (atıf/alıntı/içerik kusuru): "
                         "`tekrar` ya da `cikar`")
    rec = {"olcut": olcut, "karar": k, "istem_sha": e["istem_sha"], "cevap_sha": son["cevap_sha"],
           "deneme": len(e["denemeler"]), "sorunlar": son["sorunlar"], "not": note, "zaman": K.now()}
    if k in ("cikar", "kabul"):
        t = W.insan_metni(ws.root, olcut, son["cevap"], {**rec, "model": son.get("model")})
        rec["metin_sha"] = W.text_sha(t)
    with open(ws.root / HUMAN, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if k in ("cikar", "kabul"):
        W.texts_dir(ws).mkdir(parents=True, exist_ok=True)
        (W.texts_dir(ws) / f"{olcut}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
        if k == "cikar":
            _dogrulama_reddi(ws, t, rec)
        _gecersizden_cikar(W.work_dir(ws) / "GECERSIZ.md", olcut)   # artık yeniden yapılacak değil
    return {**rec, "sinir": b[olcut]["sinir"]}


def _gecersizden_cikar(g: Path, olcut: str) -> None:
    if not g.exists():
        return
    lines = g.read_text(encoding="utf-8").splitlines()
    out, skip = [], False
    for ln in lines:
        if ln.startswith("- `"):
            skip = ln.startswith(f"- `{olcut}.json`")
        if not skip:
            out.append(ln)
    if not any(ln.startswith("- `") for ln in out):
        g.unlink()
    else:
        g.write_text("\n".join(out) + "\n", encoding="utf-8")


def _dogrulama_reddi(ws: Workspace, t: dict, rec: dict) -> None:
    """`cikar`: doğrulama kaydına kod reddi (`asama: yazim_kod`); verify metni çıkarılmış sayar."""
    from bidr.verify import run as V
    log = V.load_log(ws)
    why = [f"{i.get('yer', '-')} {i['kod']}: {i['ayrinti']}" for i in rec["sorunlar"]]
    log[t["olcut"]] = {"olcut": t["olcut"], "durum": "reddedildi", "metin_sha": rec["metin_sha"],
                       "asama": "yazim_kod", "tur": int(t.get("tur") or 0), "kod_denetimi": rec["sorunlar"],
                       "cumleler": [], "soru_kapsami": V.unchecked(), "gerekce": why, "model": None,
                       "gorev_surumu": None, "zaman": rec["zaman"]}
    V.save_log(ws, log)
    V.write_summary(ws, log)


def kabul_edilen(ws: Workspace, t: dict) -> set[tuple[str, str]]:
    """Bu metin (aynı içerik) için kullanıcının `kabul` ettiği üslup bulguları {(kod, ayrıntı)}."""
    from . import run as W
    sha = W.text_sha(t)
    out: set[tuple[str, str]] = set()
    for r in load_human(ws):
        if r["olcut"] == t["olcut"] and r["karar"] == "kabul" and r.get("metin_sha") == sha:
            out |= {(i["kod"], i["ayrinti"]) for i in r.get("sorunlar") or [] if uslup_mu(i)}
    return out
