"""`bidr kimlik-onar -w WS`: kimliği kaymış belgelerin kayıtlarını eski kimliklerine geri bağlar.

Ne zaman gerekir: maskeli kaynakta (bidr maskele --kaynak) bir belgenin maskeli kopyası yeniden üretilip baytı
değişmiş, eski sürüm ingest bunu "yeni belge" sayıp eski kimliğin türetilmiş kayıtlarını
`kaynaktan-cikarilan/` altına taşımıştır (ya da yeni sürüm ingest kimliği doğrulayamayıp `_oksuz/` altına
almıştır). İnsan kayıtları (review-decisions.jsonl, kanit-adlari.jsonl, birim-kararlari.jsonl) eski kimlikle
yerinde durur ama kararlar gittiği için kullanılmaz.

Yaptığı (varsayılan KURU KOŞU; `--uygula` yazar):

1. Eski kimlik → bugünkü dosya eşlemesini KANITLA kurar: (a) maskeleme önbelleği (`kaynak_cikti`: eski maskeli
   kopyanın sha'sı → özgün sha256) ve maskeleme raporu (özgün sha256 → maskeli yol); (b) arşivdeki eski metin
   ile bugünkü metnin birebir eşitliği (model öncesi taban metin); (c) `--esleme` (elle: doc_id → rel_path).
   (a) ile (b) çelişirse ya da kanıt yoksa belgeye dokunulmaz, raporlanır.
2. Bugünkü (yeni) kimliğin kararı varsa belge yeniden işlenmiştir: dokunulmaz (`yeniden_uretilmis`).
3. Yeni kimliğin bugün üretilen artıkları (metin, betimleme paketi/kaydı) `_oksuz/kimlik-onar-<zaman>/yeni-kimlik/`
   altına alınır; eski kimliğin metni, documents/candidates/decisions satırları ve iş paketleri arşivden yerine
   döner; inventory.csv satırı eski kimliğe çevrilir (alanlar transcribe/describe kayıtlarından yeniden kurulur).
4. Bütün satırlara `ozgun_sha256` yazılır ve eski kimlikler `kimlikler.jsonl`'e sabitlenir (göç): sonraki
   `bidr ingest` hiçbir kimliği değiştirmez.
5. Envanterde olmayan belgelerin model okuma paketleri (`work/describe|transcribe/<doc_id>/`) kenara alınır
   (`apply` onları "envanterde yok" diye geçersiz saymasın).

Hiçbir şey silinmez; değiştirilen dosyaların önceki hâli `_oksuz/kimlik-onar-<zaman>/once/` altındadır.
"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Callable

from bidr.common import Workspace, doc_id_from_sha, read_jsonl, write_jsonl

from . import kimlik as K
from . import pipeline as P

ONAR_PREFIX = "kimlik-onar-"
_ENV_ALAN = ("method", "chars", "ocr_conf", "quality", "low_quality")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _arsivler(ws: Workspace) -> list[Path]:
    out = [ws.root / P.REMOVED_DIR, ws.root / K.OKSUZ_DIR]
    return [a for a in out if a.is_dir()]


def _arsiv_kayitlari(arch: Path) -> dict[str, dict[str, dict]]:
    """doc_id → {dosya adı → {kayit, zaman}} (aynı dosyada en son arşivlenen)."""
    out: dict[str, dict[str, dict]] = {}
    p = arch / "kayitlar.jsonl"
    if p.is_file():
        for r in read_jsonl(p):
            k = r.get("kayit") or {}
            if k.get("doc_id") and r.get("dosya"):
                out.setdefault(k["doc_id"], {})[r["dosya"]] = {"kayit": k, "zaman": r.get("zaman") or ""}
    return out


def _satirlar(p: Path) -> list[dict]:
    return list(read_jsonl(p)) if p.is_file() else []


def plan(ws_root: Path, source: Path, *, yedek: Path | None = None, esleme: dict[str, str] | None = None,
         onbellek: bool = True) -> dict:
    ws = Workspace(ws_root)
    if not ws.inventory.exists():
        raise FileNotFoundError(f"{ws.inventory} yok")
    esl = K.maske_eslemesi(Path(source))
    if esl is None:
        raise ValueError(f"{source} bidr'in maskeli kaynak kopyası değil (ya da maskeleme raporu okunamadı): "
                         "kimlik içerik sha'sıdır, onarılacak kayma olamaz")
    rows = P._read_prior_rows(ws)
    ana = {r["doc_id"]: r for r in rows if r.get("doc_id") and not r.get("dup_of")}
    ozgun = {d: (r.get("ozgun_sha256") or esl.ozgun(r["rel_path"]) or r.get("sha256") or "") for d, r in ana.items()}
    by_ozgun: dict[str, str] = {}
    for d, o in ozgun.items():
        by_ozgun.setdefault(o, d)
    by_rel = {r["rel_path"]: d for d, r in ana.items()}
    kararli = {r["doc_id"] for r in _satirlar(ws.root / "decisions.jsonl") if r.get("doc_id")}

    # kayıp kimlikler: arşivde kaydı/metni olup envanterde olmayanlar (+ yedekteki kararlar)
    kayip: dict[str, dict] = {}
    for arch in _arsivler(ws):
        recs = _arsiv_kayitlari(arch)
        ids = set(recs) | ({p.stem for p in (arch / "text").glob("*.txt")} if (arch / "text").is_dir() else set())
        for d in ids - set(ana):
            z = max((v["zaman"] for v in recs.get(d, {}).values()), default="")
            if d not in kayip or z >= kayip[d]["zaman"]:
                kayip[d] = {"arsiv": arch, "kayitlar": recs.get(d, {}), "zaman": z}
    yedek_karar: dict[str, dict] = {}
    if yedek is not None:
        yedek_karar = {r["doc_id"]: r for r in _satirlar(Path(yedek) / "decisions.jsonl") if r.get("doc_id")}
        for d in set(yedek_karar) - set(ana) - set(kayip):
            kayip[d] = {"arsiv": None, "kayitlar": {}, "zaman": ""}

    tarihce = K.onbellek_tarihce(ws.root) if onbellek and kayip else {}
    metin_idx: dict[str, list[str]] = {}
    for d in ana:
        t = K.taban_metni(ws.root, d)
        if t is not None and any(ch.isalnum() for ch in t):
            metin_idx.setdefault(_sha(t), []).append(d)

    ciftler, sonuc = [], {"cikmis": [], "celiski": [], "cozulemedi": [], "yeniden_uretilmis": [], "eski_surum": []}
    for d in sorted(kayip):
        k = kayip[d]
        kanit, n_ob, n_mt, n_el = [], None, None, None
        o = tarihce.get(d)
        if o is not None:
            n_ob = by_ozgun.get(o)
            if n_ob is None:
                sonuc["cikmis"].append({"doc_id": d, "neden": "özgün dosya artık kaynakta yok (önbellek)"})
                continue
            kanit.append("onbellek")
        t = K.taban_metni(ws.root, d, text_root=k["arsiv"] / "text") if k["arsiv"] is not None else None
        if t is not None and any(ch.isalnum() for ch in t):
            m = metin_idx.get(_sha(t), [])
            if len(m) == 1:
                n_mt = m[0]
                kanit.append("metin")
        if esleme and d in esleme:
            n_el = by_rel.get(esleme[d])
            if n_el is None:
                sonuc["cozulemedi"].append({"doc_id": d, "neden": f"--esleme yolu envanterde yok: {esleme[d]}"})
                continue
            kanit.append("elle")
        if n_el is None and n_ob and n_mt and n_ob != n_mt:
            sonuc["celiski"].append({"doc_id": d, "onbellek": n_ob, "metin": n_mt})
            continue
        n = n_el or n_ob or n_mt
        if n is None:
            sonuc["cozulemedi"].append({"doc_id": d, "neden": "önbellekte ve metin eşitliğinde kanıt yok"})
            continue
        if n in kararli:
            sonuc["yeniden_uretilmis"].append({"doc_id": d, "yeni": n, "rel_path": ana[n]["rel_path"]})
            continue
        ciftler.append({"eski": d, "yeni": n, "rel_path": ana[n]["rel_path"], "ozgun_sha256": ozgun[n],
                        "kanit": kanit, "metin_ayni": n_mt == n, "zaman": k["zaman"],
                        "arsiv": str(k["arsiv"]) if k["arsiv"] is not None else None,
                        "yalniz_yedek": k["arsiv"] is None})
    # aynı yeni kimliğe birden çok eski kimlik: en son arşivlenen geçerli
    son: dict[str, dict] = {}
    for c in ciftler:
        if c["yeni"] not in son or c["zaman"] > son[c["yeni"]]["zaman"]:
            if c["yeni"] in son:
                sonuc["eski_surum"].append({"doc_id": son[c["yeni"]]["eski"], "yeni": c["yeni"]})
            son[c["yeni"]] = c
        else:
            sonuc["eski_surum"].append({"doc_id": c["eski"], "yeni": c["yeni"]})
    ciftler = sorted(son.values(), key=lambda c: c["eski"])

    yeni_to_eski = {c["yeni"]: c["eski"] for c in ciftler}
    son_ids = {yeni_to_eski.get(d, d) for d in ana}
    sabit = K.sabitler(ws.root)
    sabitlenecek = sum(1 for d, o in ozgun.items()
                       if o and (e := yeni_to_eski.get(d, d)) != doc_id_from_sha(o) and sabit.get(o) != e)
    paket = []
    for stage in P.MODEL_WORK:
        sd = ws.root / "work" / stage
        if sd.is_dir():
            paket += [f"work/{stage}/{p.name}" for p in sorted(sd.iterdir())
                      if p.is_dir() and (p / f"{p.name}.json").is_file() and p.name not in son_ids
                      and p.name not in yeni_to_eski]
    insan = {}
    for name in ("review-decisions.jsonl", "kanit-adlari.jsonl", "birim-kararlari.jsonl"):
        ids = {r["doc_id"] for r in _satirlar(ws.root / name) if r.get("doc_id")}
        if ids:
            insan[name] = {"belge": len(ids), "envanter_disi_once": len(ids - set(ana)),
                           "envanter_disi_sonra": len(ids - son_ids)}
    md = sorted(r["doc_id"] for r in _satirlar(ws.root / "decisions.jsonl")
                if r.get("durum") == "metin_degisti" and isinstance(r.get("onceki"), dict))
    for kay in kayip.values():
        r = (kay["kayitlar"].get("decisions.jsonl") or {}).get("kayit") or {}
        if r.get("durum") == "metin_degisti" and isinstance(r.get("onceki"), dict):
            md.append(r["doc_id"])
    return {"ws": str(ws.root), "kaynak": str(source), "rapor": str(esl.rapor_yolu), "envanter": len(ana),
            "kayip": len(kayip), "onbellek_kaydi": len(tarihce), "ciftler": ciftler, **sonuc,
            "sabitlenecek": sabitlenecek, "ozgun_yazilacak": sum(1 for r in rows if not r.get("ozgun_sha256")),
            "oksuz_paket": paket, "insan_kayitlari": insan, "metin_degisti": sorted(set(md)), "bekleyen": len(K.bekleyenler(ws.root)),
            "yedek": str(yedek) if yedek else None, "_yedek_karar": yedek_karar,
            "_kayitlar": {c["eski"]: {n: v["kayit"] for n, v in kayip[c["eski"]]["kayitlar"].items()}
                          for c in ciftler}}


def _envanter_alanlari(ws: Workspace, row: dict, eski: str, yeni_log: dict[str, dict]) -> dict:
    """Eski kimliğin envanter alanları: bugünkü çıkarımın (yeni kimlik) model öncesi değerleri + eski kimliğin
    transcribe/describe kayıtlarının etkisi (`apply`'ın envantere yazdığının aynısı)."""
    from bidr.describe import run as D
    from bidr.ingest.ocr import text_health
    from bidr.transcribe import run as T
    out = {k: row.get(k, "") for k in _ENV_ALAN}
    for name in P.MODEL_JSONL:                       # bugün yeni kimliğe uygulanan okuma: öncesine dön
        once = (yeni_log.get(name) or {}).get("onceki_envanter")
        if once:
            out.update({k: once.get(k, "") for k in _ENV_ALAN})
            break
    p = ws.text_path(eski)
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    kayitlar = []
    for name, log in (("transcribe.jsonl", T.load_log(ws)), ("describe.jsonl", D.load_log(ws))):
        r = log.get(eski)
        if r and r.get("durum") == "uygulandi" and not r.get("metin_ayni"):
            kayitlar.append((str(r.get("zaman") or ""), name, r))
    for _, name, r in sorted(kayitlar, key=lambda x: x[0]):
        if name == "transcribe.jsonl":
            cons = r.get("tutarlilik") or {"okunamadi_payi": 0.0}
            out.update(method=T.METHOD, chars=len(text), quality=T.new_quality(text, cons), ocr_conf="",
                       low_quality="1" if cons.get("okunamadi_payi", 0.0) >= T.LOWQ_UNREADABLE else "")
        else:
            out.update(method=D.METHOD, chars=len(text), quality=round(text_health(text) or 0.0, 2))
            full = r.get("tur") == "gorsel" or (r.get("tur") == "pdf" and str(row.get("pages")) == "1")
            if full and not r.get("metin_sayfasi"):
                out.update(low_quality="", ocr_conf="")
    if not kayitlar and text:
        out["chars"] = len(text)
    return out


def _jsonl_ekle(p: Path, yeni: list[dict]) -> int:
    """Satırları ekle (doc_id zaten varsa atla); dosya doc_id sıralıysa sıra korunur."""
    if not yeni:
        return 0
    cur = _satirlar(p)
    var = {r.get("doc_id") for r in cur}
    ek = [r for r in yeni if r.get("doc_id") not in var]
    if not ek:
        return 0
    ids = [r.get("doc_id") or "" for r in cur]
    out = cur + ek
    if ids == sorted(ids):
        out.sort(key=lambda r: r.get("doc_id") or "")
    elif p.name == "documents.jsonl":
        key = lambda r: (r.get("calisma_adi") or "", r.get("doc_id") or "")          # noqa: E731 — identify sırası
        if [key(r) for r in cur] == sorted(key(r) for r in cur):
            out.sort(key=key)
    write_jsonl(p, out)
    return len(ek)


def _metin_degisti_geri_al(ws: Workspace) -> int:
    """`metin_degisti` kararlarını önceki hâline döndürür (kayıt `onceki` altında durur) ve `.eski` yapılmış
    karar paketlerini geri adlandırır. Metin gerçekten değiştiyse `bidr decide prepare` belgeye özgü girdinin
    (istem) değiştiğini görür ve yalnız o belgeyi yeniden paketler; aynıysa karar olduğu gibi geçerlidir."""
    p = ws.root / "decisions.jsonl"
    rows = _satirlar(p)
    geri = []
    for i, r in enumerate(rows):
        if r.get("durum") == "metin_degisti" and isinstance(r.get("onceki"), dict):
            rows[i] = r["onceki"]
            geri.append(r["doc_id"])
    if geri:
        write_jsonl(p, rows)
        for stage in P.DERIVED_WORK:
            for d in geri:
                for name in (f"{d}.json", f"{d}.out.json"):
                    src, dst = ws.root / "work" / stage / f"{name}.eski", ws.root / "work" / stage / name
                    if src.is_file() and not dst.exists():
                        src.replace(dst)
    return len(geri)


def uygula(ws_root: Path, pl: dict, *, degisen_metin: str = "eski", kabul: bool = False,
           metin_degisti_geri_al: bool = False, log: Callable[[str], None] = print) -> dict:
    ws = Workspace(ws_root)
    when = time.strftime("%Y%m%dT%H%M%S")
    A = ws.root / K.OKSUZ_DIR / f"{ONAR_PREFIX}{when}"
    (A / "once").mkdir(parents=True, exist_ok=True)
    for name in ("inventory.csv", K.KAYIT, *P.DERIVED_JSONL, *P.MODEL_JSONL):
        if (ws.root / name).is_file():
            shutil.copy2(ws.root / name, A / "once" / name)
    esl = K.maske_eslemesi(Path(pl["kaynak"]))
    ciftler = pl["ciftler"]
    yeni_ids = {c["yeni"] for c in ciftler}
    # yeni kimliklerin bugünkü okuma kayıtları (envanter alanlarını geri kurmak için), arşivlenmeden önce
    yeni_log: dict[str, dict[str, dict]] = {}
    for name in P.MODEL_JSONL:
        for r in _satirlar(ws.root / name):
            if r.get("doc_id") in yeni_ids:
                yeni_log.setdefault(r["doc_id"], {})[name] = r
    st = {"geri_baglanan": 0, "satir": {}, "metin": 0, "paket": 0, "degisen_metin": [], "yedekten": 0}
    yeni_metin: dict[str, str] = {}
    for c in ciftler:
        if not c["metin_ayni"]:
            t = K.taban_metni(ws.root, c["yeni"])
            if t is not None:
                yeni_metin[c["eski"]] = t
    P._archive_ids(ws, A / "yeni-kimlik", yeni_ids, P.DERIVED_JSONL + P.MODEL_JSONL)

    ekle: dict[str, list[dict]] = {}
    for c in ciftler:
        d = c["eski"]
        arch = Path(c["arsiv"]) if c["arsiv"] else None
        if arch is not None:
            for name, v in (pl.get("_kayitlar", {}).get(d) or {}).items():
                if name in P.DERIVED_JSONL + P.MODEL_JSONL:
                    ekle.setdefault(name, []).append(v)
            src = arch / "text" / f"{d}.txt"
            if src.is_file() and not ws.text_path(d).exists():
                ws.text_dir.mkdir(exist_ok=True)
                src.replace(ws.text_path(d))
                st["metin"] += 1
            for stage in P.DERIVED_WORK:
                for name in (f"{d}.json", f"{d}.out.json"):
                    src, dst = arch / "work" / stage / name, ws.root / "work" / stage / name
                    if src.is_file() and not dst.exists():
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        src.replace(dst)
                        st["paket"] += 1
            for sub in P.MODEL_TEXT:
                src, dst = arch / sub / f"{d}.txt", ws.root / sub / f"{d}.txt"
                if src.is_file() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.replace(dst)
            for stage in P.MODEL_WORK:
                src, dst = arch / "work" / stage / d, ws.root / "work" / stage / d
                if src.is_dir() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    src.replace(dst)
        elif d in pl.get("_yedek_karar", {}):
            ekle.setdefault("decisions.jsonl", []).append(pl["_yedek_karar"][d])
            st["yedekten"] += 1
        st["geri_baglanan"] += 1
    for name, rs in ekle.items():
        st["satir"][name] = _jsonl_ekle(ws.root / name, rs)

    # envanter: yeni kimlik → eski kimlik; bütün satırlara özgün sha
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    y2c = {c["yeni"]: c for c in ciftler}
    for r in rows:
        c = y2c.get(r.get("doc_id") or "")
        if c is not None:
            if not r.get("dup_of"):
                r.update(_envanter_alanlari(ws, r, c["eski"], yeni_log.get(c["yeni"], {})))
            r["doc_id"] = c["eski"]
    ana = {r["doc_id"]: r for r in rows if r.get("doc_id") and not r.get("dup_of")}
    for r in rows:                                   # kopya satırları ilk örneğin alanlarını paylaşır
        if r.get("dup_of") and r.get("doc_id") in ana:
            for k in P.CARRY:
                r[k] = ana[r["doc_id"]].get(k, "")
    sabit, pin = K.sabitler(ws.root), []
    for r in rows:
        if r.get("doc_id") and r.get("sha256"):
            o = r.get("ozgun_sha256") or (esl.ozgun(r["rel_path"]) if esl else None) or r["sha256"]
            r["ozgun_sha256"] = o
            if not r.get("dup_of") and r["doc_id"] != doc_id_from_sha(o) and sabit.get(o) != r["doc_id"]:
                sabit[o] = r["doc_id"]
                pin.append({"ozgun_sha256": o, "doc_id": r["doc_id"], "rel_path": r["rel_path"],
                            "kaynak": "kimlik-onar" if r["doc_id"] in {c["eski"] for c in ciftler} else "goc"})
    tmp = ws.inventory.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in P.FIELDS} for r in rows])
    tmp.replace(ws.inventory)
    K.sabitle(ws.root, pin)
    st["sabitlenen"] = len(pin)

    # maskeli kopyasının metni gerçekten değişen belgeler
    for c in ciftler:
        if c["metin_ayni"] or c["eski"] not in yeni_metin:
            continue
        st["degisen_metin"].append({"doc_id": c["eski"], "rel_path": c["rel_path"], "metin": degisen_metin})
        if degisen_metin == "yeni":
            P._text_changed_archive(ws, c["eski"])
            ws.text_path(c["eski"]).write_text(yeni_metin[c["eski"]], encoding="utf-8")
            P._archive_ids(ws, ws.root / P.REMOVED_DIR / P.CHANGED_DIR, {c["eski"]}, P.MODEL_JSONL,
                           text=False, work=())
    if degisen_metin == "yeni" and st["degisen_metin"]:
        from bidr.transcribe.run import invalidate_downstream
        invalidate_downstream(ws, {x["doc_id"] for x in st["degisen_metin"]},
                              neden="kimlik-onar: maskeli kopyanın metni değişti")

    st["metin_degisti_geri"] = _metin_degisti_geri_al(ws) if metin_degisti_geri_al else 0

    # envanterde olmayan belgelerin okuma paketleri
    n = 0
    for rel in pl["oksuz_paket"]:
        src = ws.root / rel
        if src.is_dir() and src.name not in ana:
            P._move(src, A / "paketler" / rel)
            n += 1
    st["oksuz_paket"] = n

    bek = K.bekleyenler(ws.root)
    kalan = [] if kabul else [b for b in bek if b.get("doc_id") not in ana]
    K.bekleyen_yaz(ws.root, kalan)
    st["bekleyen_kalan"] = len(kalan)
    st["arsiv"] = str(A)
    (A / "plan.json").write_text(json.dumps({k: v for k, v in pl.items() if not k.startswith("_")} | {"sonuc": st},
                                            ensure_ascii=False, indent=1), encoding="utf-8")
    return st


def yedekle_karsilastir(ws_root: Path, yedek: Path) -> dict:
    """Yedekteki doc_id anahtarlı dosyalar ile çalışma alanı: yedekteki her kayıt aynı kimlikle birebir yerinde mi."""
    out = {}
    for name in (*P.DERIVED_JSONL, "review-decisions.jsonl", "kanit-adlari.jsonl", "birim-kararlari.jsonl"):
        yp = Path(yedek) / name
        if not yp.is_file():
            continue
        def grup(p: Path) -> dict[str, list[str]]:
            g: dict[str, list[str]] = {}
            for r in _satirlar(p):
                g.setdefault(r.get("doc_id") or "", []).append(json.dumps(r, ensure_ascii=False, sort_keys=True))
            return {k: sorted(v) for k, v in g.items()}
        y, w = grup(yp), grup(Path(ws_root) / name)
        out[name] = {"yedek_belge": len(y), "ayni": sum(1 for k in y if w.get(k) == y[k]),
                     "farkli": sorted(k for k in y if k in w and w[k] != y[k]),
                     "eksik": sorted(k for k in y if k not in w), "fazla": len(set(w) - set(y))}
    return out
