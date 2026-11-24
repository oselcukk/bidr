"""Güçlü / gelişmeye açık yön hücresi doğrulamada takılırsa bölüm kararı: `bidr yonler karar -w WS <alan>
tekrar|kabul|cikar [--not]`.

Bir alanın (A–D) maddeleri ilk yazım + `rapor.yeniden_yazim_siniri` (vars. 2; kullanıcının her `tekrar`ı bir tur
ekler) yeniden yazımdan sonra bağımsız doğrulamada hâlâ reddedilirse `bidr next` yonler aşamasında "KULLANICI
gerekli" ve karar bekleyen alan listesini (`karar_bekleyen`) verir; ajan karar vermez. Kararlar
`yonler-insan.jsonl`'e alanın o anki metnine bağlı yazılır (`metin_sha`; maddeler değişince karar geçmez):
- `tekrar`: bir yeniden yazım turu daha (`bidr yonler prepare --reddedilenler`).
- `kabul`: hücre yazıldığı gibi rapora girer. Yalnız doğrulayıcının reddettiği bütün maddeler "kismen"
  (kısmen destekleniyor) hükmündeyse; "desteklenmiyor" hükümlü ya da kod denetiminde reddedilmiş alanda
  reddedilir. Alan `dogrulandi` olur (insan onayı ve doğrulayıcının reddi kayıtta kalır: `yonler/<alan>.json`
  `dogrulama`, verify-yonler.jsonl `asama: insan`); bu alan raporu TASLAK yapmaz.
- `cikar`: doğrulayıcının desteklemediği maddeler çıkarılmış kalır (render yalnız desteklenenleri basar);
  bölüm onayladığı için bu alan raporu TASLAK yapmaz (çıkarılan maddenin düşürdüğü ölçüt de: `yon_kapsam_kaybi`).
"""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from . import packages as K

HUMAN = "yonler-insan.jsonl"
KARARLAR = ("cikar", "tekrar", "kabul")
KABUL_IZI = "insan onayıyla kabul edildi"


def load_human(ws: Workspace) -> list[dict]:
    p = ws.root / HUMAN
    return [r for r in read_jsonl(p) if r.get("alan") and r.get("karar") in KARARLAR] if p.exists() else []


def load_human_path(p: Path | None) -> list[dict]:
    """render için: dosya yolundan (yoksa boş)."""
    if p is None or not Path(p).exists():
        return []
    return [r for r in read_jsonl(Path(p)) if r.get("alan") and r.get("karar") in KARARLAR]


def sinir(ws: Workspace, alan: str, human: list[dict] | None = None) -> int:
    """Alanın yeniden yazım tur sınırı: yapılandırma + kullanıcının `tekrar` kararları."""
    from . import run as W
    human = load_human(ws) if human is None else human
    return W.rewrite_limit(ws.root) + sum(1 for r in human if r["alan"] == alan and r["karar"] == "tekrar")


def kararli(t: dict | None, human: list[dict]) -> dict | None:
    """Bu metin (aynı maddeler) için kullanıcının son `kabul`/`cikar` kararı."""
    if not t:
        return None
    from .yonler import text_sha
    sha = text_sha(t)
    return next((r for r in reversed(human) if r["alan"] == t.get("alan") and r["karar"] in ("cikar", "kabul")
                 and r.get("metin_sha") == sha), None)


def cikarildi(t: dict | None, human: list[dict]) -> bool:
    k = kararli(t, human)
    return bool(k and k["karar"] == "cikar")


def _maddeler(rec: dict) -> list[dict]:
    out = []
    for m in rec.get("maddeler") or []:
        if m.get("karar") == "destekleniyor":
            continue
        out.append({"yer": m.get("yer", ""), "yon": m.get("liste") or ("guclu" if str(m.get("yer", "")).startswith("g")
                                                                       else "gelisme"),
                    "metin": m.get("metin", ""), "hukum": m.get("karar", ""), "gerekce": m.get("gerekce", "")})
    for i in rec.get("kod_denetimi") or []:
        y = str(i.get("yer") or "")
        out.append({"yer": y, "yon": "guclu" if y.startswith("g") else "gelisme" if y.startswith("a") else "",
                    "metin": "", "hukum": "kod", "gerekce": f"{i.get('kod', '')}: {i.get('ayrinti', '')}".strip(": ")})
    return out


def bekleyen(ws: Workspace, log: dict | None = None) -> list[dict]:
    """Bölüm kararı bekleyen alanlar: [{alan, tur, sinir, metin_sha, kabul_edilebilir, maddeler: [{yer, yon,
    metin, hukum, gerekce}]}]. `hukum`: doğrulayıcının kararı ("kismen" | "desteklenmiyor") ya da kod reddinde
    "kod". `kabul_edilebilir`: model doğrulaması ve bütün reddedilen maddeler "kismen"."""
    from . import yonler as Y
    log = Y.load_log(ws) if log is None else log
    human = load_human(ws)
    out = []
    for a, t in sorted(Y.rejected(ws, log).items()):
        lim = sinir(ws, a, human)
        if int(t.get("tur") or 0) < lim or kararli(t, human):
            continue
        rec = log.get(a) or {}
        ms = _maddeler(rec)
        out.append({"alan": a, "tur": int(t.get("tur") or 0), "sinir": lim, "metin_sha": Y.text_sha(t),
                    "kabul_edilebilir": rec.get("asama") == "model" and bool(ms)
                    and all(m["hukum"] == "kismen" for m in ms), "maddeler": ms})
    return out


def karar(ws_root: Path, alan: str, k: str, note: str = "") -> dict:
    """KULLANICININ kararı (ajan kendi kararını yazmaz) → yonler-insan.jsonl (+ kabul: alan doğrulandı)."""
    from . import yonler as Y
    ws = Workspace(Path(ws_root))
    alan = str(alan).strip().upper()
    if k not in KARARLAR:
        raise ValueError(f"karar '{k}' geçersiz ({' | '.join(KARARLAR)})")
    b = {x["alan"]: x for x in bekleyen(ws)}
    if alan not in b:
        raise ValueError(f"{alan} alanı doğrulamada takılıp bölüm kararı bekleyen bir yön hücresi değil "
                         f"(bekleyen: {', '.join(b) or 'yok'})")
    x = b[alan]
    if k == "kabul" and not x["kabul_edilebilir"]:
        hk = sorted({m["hukum"] for m in x["maddeler"] if m["hukum"] != "kismen"})
        raise ValueError(f"{alan}: 'olduğu gibi kabul' yalnız doğrulayıcının 'kısmen' dediği maddelerde geçerli; "
                         f"bu alanda {', '.join(hk) or 'kısmen olmayan'} hükümlü madde var: `tekrar` ya da `cikar`")
    rec = {"alan": alan, "karar": k, "metin_sha": x["metin_sha"], "tur": x["tur"], "maddeler": x["maddeler"],
           "not": note, "zaman": K.now()}
    with open(ws.root / HUMAN, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if k == "kabul":
        _accept(ws, alan, rec)
    elif k == "cikar":
        t = dict(Y.load(ws, alan))
        t["insan_karari"] = "cikar"
        Y.save(ws, t)
    return {**rec, "sinir": sinir(ws, alan)}


def _accept(ws: Workspace, alan: str, rec: dict) -> None:
    """`kabul`: alan `dogrulandi` olur (render bütün maddeleri basar, TASLAK nedeni olmaz); doğrulayıcının reddi
    kayıtta kalır."""
    from . import yonler as Y
    log = Y.load_log(ws)
    prev = log[alan]
    why = list(prev.get("gerekce") or [])
    iz = f"{KABUL_IZI} (doğrulayıcı reddi: {'; '.join(why) or 'gerekçe yok'})"
    onay = {"karar": "kabul", "kayit": HUMAN, "not": rec["not"], "zaman": rec["zaman"]}
    t = dict(Y.load(ws, alan))
    t["durum"] = "dogrulandi"
    t["insan_karari"] = "kabul"
    t["dogrulama"] = {"kayit": Y.LOG, "model": prev.get("model"), "gerekce": [iz], "insan_onayi": onay,
                      "dogrulayici_reddi": why, "zaman": rec["zaman"]}
    Y.save(ws, t)
    log[alan] = {**prev, "durum": "dogrulandi", "asama": "insan", "gerekce": [iz], "insan_onayi": onay,
                 "dogrulayici_reddi": {"asama": prev.get("asama"), "model": prev.get("model"),
                                       "maddeler": prev.get("maddeler"), "gerekce": why, "zaman": prev.get("zaman")}}
    Y.save_log(ws, log)
