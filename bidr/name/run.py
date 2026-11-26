"""`bidr name prepare|apply`: işlenmiş belgelere sonradan kanıt adı (ajan modu; ucuz görev).

  prepare  kabul edilmiş eşleşmesi olan her belge için (mükerrer kopyalar hariç: adı
           temsilcinindir) `work/name/<doc_id>.json` iş paketi yazar: belge metninin başı,
           içerik alanları (tür, tarih, akademik dönem), identify başlığı, eşleştiği ölçütler
           ve alıntılar. Yol/dosya adı/çalışma adı pakete girmez (decide ile aynı ilke).
           Model adı zaten olan belge (`kanit-adlari.jsonl` model kaydı ya da ince kararın
           kabul edilmiş `kanit_adi`'sı) paketlenmez (`--redo` ya da `--only` ile yeniden).
           Uygunluk insan birim kararıyla (`birim-kararlari.jsonl`, insan > model) belirlenir:
           başka birim sayılıp komisyonca geri alınan belgenin geri yüklenen eşleşmeleri kanıttır;
           komisyonun başka birim onayladığı belgeninki değildir (audit/file ile aynı görünüm).
           Varsayılan olarak model adı olan ama derleme olduğu saptanan (`derleme_kaniti`) ve
           görevin bu sürümüyle parça adı sorulmamış belgeler de paketlenir (parça adı için
           yeniden adlandırma; `parca_gerekli`); `--no-parca` bunu kapatır. Aday yoksa paket yok.
  apply    `<doc_id>.out.json` cevaplarını şemaya ve `check_name`'e göre doğrular,
           `kanit-adlari.jsonl`'e `kaynak: model` olarak yazar. Kişi adı/unvan/e-posta içeren
           ya da biçimsiz ad reddedilir (`GECERSIZ.md`), belge kural adında kalır. Belgede
           dayanağı olmayan ad (`ground.grounding`) kabul edilir, kayıtta `dogrulanmali` ve
           `GECERSIZ.md`'de ayrı bölümde listelenir. Derleme belgede isteğe bağlı
           `parca_adlari` ({yuva: ad}) `normalize_parts` ile süzülür: belge derleme
           saptanmamışsa atılır; aynı parçanın yuvaları ilk yuvanın adını alır; belge adıyla
           aynı ad yazılmaz. Kayıtta `parca_adlari`, süzme notları `parca_not`.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from bidr import notlar as N
from bidr.common import Workspace, read_jsonl
from bidr.decide import prompt as P

from .check import YASAKLI_GOSTERIM, check_name_noted
from .ground import _pages, coded_compilation, grounding, page_codes, quote_part
from .resolve import NAMES, decision_name, load_names, part_grounding, upsert

TASK = "name_evidence"
DIZIN = "work/name"
NAME_CHARS = 2500        # belge metni bütçesi (baş ağırlıklı)
QUOTE_CHARS = 200
MAX_MATCH = 6
PART_CHARS = 240         # alıntının sayfasının başı (derlemede parçanın başlığı)

README = """# bidr iş paketleri: {task} (sürüm {version})

Her `<doc_id>.json` bir iş paketidir: belgeye kanıt dosyası adı ver. Sağlayıcı çağrılmaz.

1. Paketi oku; `istem` görevin tamamıdır, `sema` cevabın şemasıdır.
2. Cevabı YALNIZ JSON olarak aynı klasörde `<doc_id>.out.json`'a yaz.
3. Bitince: `bidr name apply -w <çalışma klasörü> --model <ajan/model adı>`.
   Reddedilen cevap kenara alınır (`.red<n>.eski`), gerekçesi `GECERSIZ.md`'de; o paket
   yeniden cevapsızdır: yeni `<doc_id>.out.json` yaz (var olanın üstüne yazma). Aynı nedenle
   ikinci kez reddedilen belge yeniden istenmez (`ELLE-BAKILMALI.md`): kural adında kalır.

Bekleyen paket: {n}
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def task_version() -> str:
    import yaml
    from bidr.llm.tasks import TASKS_DIR
    return str((yaml.safe_load((TASKS_DIR / TASK / "task.yaml").read_text(encoding="utf-8")) or {})["version"])


def work_dir(ws: Workspace) -> Path:
    return ws.root / "work" / "name"


def _decisions(ws: Workspace) -> dict[str, dict]:
    p = ws.root / "decisions.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"decisions.jsonl yok: {p}")
    return {r["doc_id"]: r for r in read_jsonl(p) if r.get("doc_id")}


def decisions_view(ws: Workspace, recs: dict[str, dict] | None = None, cs=None) -> dict[str, dict]:
    """Kararların insan birim kararıyla görünümü (`bidr.decide.run.unit_view`; insan > model).
    Birim kararları decide gibi çalışma alanındaki `birim-kararlari.jsonl`'den okunur."""
    from bidr.decide.run import load_unit_pins, unit_view
    recs = _decisions(ws) if recs is None else recs
    pins = load_unit_pins(ws.root)
    if not pins:
        return recs
    from bidr.criteria.slots import load_tags
    if cs is None:
        from bidr.criteria.loader import load_criteria
        cs = load_criteria()
    tags = load_tags(cs)
    return {d: unit_view(r, pins, tags) for d, r in recs.items()}


def eligible(recs: dict[str, dict]) -> list[str]:
    """Kabul edilmiş eşleşmesi olan, kararı devralmamış (temsilci ya da tekil) belgeler."""
    out = []
    for did, r in sorted(recs.items()):
        if r.get("durum") != "ok" or r.get("asama") != "ince":
            continue
        if (r.get("mukerrer") or {}).get("durum") == "devralindi":
            continue
        if any(m.get("kabul") for m in r.get("eslesmeler") or []):
            out.append(did)
    return out


def _text(ws: Workspace, did: str) -> str:
    p = ws.text_path(did)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def part_heads(text: str, quotes: list[tuple[str, str]]) -> str:
    """Çok sayfalı belgede her alıntının geldiği sayfanın başı (derlemede parçanın başlığı;
    model adı belgenin ilk parçasından değil alıntının parçasından kurabilsin)."""
    from bidr.llm.quote import verify_quote
    pages = _pages(text)
    if len(pages) < 2:
        return "(tek sayfa)"
    out = []
    for yuva, q in quotes:
        sp = verify_quote(q, text).span if q else None
        if not sp:
            continue
        i = next((k for k, (a, b) in enumerate(pages) if a <= sp[0] <= b), len(pages) - 1)
        head = " ".join(text[pages[i][0]:pages[i][1]].split())
        head = head if len(head) <= PART_CHARS else head[:PART_CHARS].rsplit(" ", 1)[0] + " …"
        out.append(f"- {yuva}: sayfa {i + 1}/{len(pages)}: \"{head}\"")
    return "\n".join(out) or "(yok)"


def compilation_hint(text: str) -> str:
    """İstem için derleme bilgisi (kodla saptanan parçalar; kodsuz derlemeyi model sayfa
    başlarından da görür)."""
    from bidr.identify.parca import text_parts
    if len(_pages(text)) < 2:
        return "tek sayfa: derleme değil"
    codes = [c for c in dict.fromkeys(page_codes(text)) if c]
    rs = text_parts(text)
    if len(rs) > 1:
        sp = ", ".join(f"s. {a + 1}" if a == b else f"s. {a + 1}-{b + 1}" for a, b, _ in rs[:10])
        return (f"evet: {len(rs)} parça ({sp})"
                + (f"; sayfa başlarında {len(codes)} farklı doküman kodu (" + ", ".join(codes[:8]) + ")"
                   if len(codes) > 1 else ""))
    return "parça ayrımı saptanmadı (sayfa başları farklı belgeler gösteriyorsa derlemedir)"


def accepted_quotes(rec: dict | None) -> dict[str, str]:
    """{yuva: alıntı}, kabul edilmiş eşleşmeler, karar sırasıyla."""
    return {m["yuva"]: m.get("alinti") or "" for m in (rec or {}).get("eslesmeler") or []
            if m.get("kabul") and m.get("yuva")}


def derleme_kaniti(ad: str | None, text: str, quotes: dict[str, str]) -> bool:
    """Belgenin derleme olduğuna kod kanıtı: birden çok doküman kodu, kabul edilmiş alıntılar
    birleşik belgenin farklı parçalarından (`bidr.identify.parca.part_ranges`) ya da belge adı
    bazı alıntıların çevresinde tutmuyor (`parca_uyumsuz`: alıntı başka parçadan)."""
    if len(_pages(text)) < 2:
        return False
    if coded_compilation(text):
        return True
    keys = {k for k in (quote_part(text, q) for q in quotes.values() if q) if k and k[0] == "parca"}
    if len(keys) > 1:
        return True
    return bool(ad and grounding(ad, text, quotes)["parca_uyumsuz"])


def normalize_parts(raw: dict | None, ad: str, text: str, quotes: dict[str, str]) -> tuple[dict, list[str]]:
    """Modelin `parca_adlari`'nı süzer → ({yuva: ad}, notlar). Yalnız derleme kanıtı olan
    belgede; yalnız kabul edilmiş yuvalar; `check_name`'den geçen adlar. Aynı parça (kodlu
    derlemede aynı kodlu sayfa aralığı, değilse aynı sayfa) tek ad alır: karar sırasıyla ilk
    yuvanın adı. Belge adıyla aynı parça adı yazılmaz (belge adı zaten o)."""
    if not raw:
        return {}, []
    if not derleme_kaniti(ad, text, quotes):
        return {}, ["derleme_saptanmadi: parca_adlari kullanilmadi"]
    notes: list[str] = []
    cand: dict[str, str] = {}
    for y, v in raw.items():
        if y not in quotes:
            notes.append(f"{y}: kabul edilmis yuva degil")
            continue
        ok, errs, _ = check_name_noted(v)
        if errs:
            notes.append(f"{y}: ad reddedildi ({', '.join(errs)})")
            continue
        cand[y] = ok
    first: dict[tuple, str] = {}
    out: dict[str, str] = {}
    for y, q in quotes.items():               # karar sırası: aynı parçada ilk yuva belirler
        if y not in cand:
            continue
        key = quote_part(text, q)
        if key is None:
            notes.append(f"{y}: alinti metinde bulunamadi")
            continue
        if key in first and first[key] != cand[y]:
            notes.append(f"{y}: ayni parca tek ad ({json.dumps(cand[y], ensure_ascii=False)} -> "
                         f"{json.dumps(first[key], ensure_ascii=False)})")
        name = first.setdefault(key, cand[y])
        if name.casefold() != (ad or "").casefold():
            out[y] = name
    return out, notes


def note_stale(did: str, have: dict | None, notes: dict[str, list]) -> bool:
    """Model kanıt adı bölümün şimdiki belge notuyla mı verildi (bidr/notlar.py). Not eklenince/değişince ad
    yeniden sorulur (model adı ince kararın adının önüne geçer, eski not ya da notsuz ad kalmasın)."""
    m = (have or {}).get("model")
    return bool(m) and (m.get("belge_notu") or "") != N.note_sha(notes.get(did))


def inputs_of(ws: Workspace, did: str, rec: dict, doc: dict | None, cs=None, notes: list[dict] | None = None) -> dict:
    if cs is None:
        from bidr.criteria.loader import load_criteria
        cs = load_criteria()
    lines = []
    acc = [m for m in rec.get("eslesmeler") or [] if m.get("kabul")][:MAX_MATCH]
    for m in acc:
        try:
            title = cs.get(m["olcut"]).title
        except KeyError:
            title = ""
        q = (m.get("alinti") or "").replace("\n", " ")
        q = q if len(q) <= QUOTE_CHARS else q[:QUOTE_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"- {m['olcut']} {title} (yuva {m['yuva']}, {m.get('asama')}): \"{q}\"")
    text = _text(ws, did)
    body, _ = P.excerpt(text, NAME_CHARS)
    bas = (doc or {}).get("baslik")
    return {"belge_bilgisi": N.with_note(P.render_info(P.content_info(doc)), notes, "ad"),
            "baslik": bas.strip() if isinstance(bas, str) and bas.strip() else "(yok)",
            "olcutler": "\n".join(lines) or "(yok)",
            "parcalar": part_heads(text, [(m["yuva"], m.get("alinti") or "") for m in acc]),
            "derleme": compilation_hint(text),
            "belge_metni": body or "(metin yok)"}


def prepare(ws_root: Path, *, only: list[str] | None = None, redo: bool = False,
            parca: bool = True, render=None) -> dict:
    if render is None:
        from bidr.llm import render_task as render
    from bidr.criteria.loader import load_criteria
    ws = Workspace(ws_root)
    cs = load_criteria()
    recs = decisions_view(ws, cs=cs)
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    have = load_names(ws.root)
    notes = N.load(ws.root)
    d = work_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    st = {"paket": 0, "yeni": 0, "zaten_adli": 0, "derleme": 0, "uygun_degil": [], "klasor": str(d)}
    cache = load_derleme_cache(ws)
    pool = eligible(recs)
    if only is not None:
        ids = list(dict.fromkeys(only))
        st["uygun_degil"] = [x for x in ids if x not in pool]
        ids = [x for x in ids if x in pool]
    else:
        ids = pool
    for did in ids:
        if only is None and not redo and ("model" in (have.get(did) or {}) or decision_name(recs[did])) \
                and not note_stale(did, have.get(did), notes):
            if not (parca and _needs_parts(ws, did, recs[did], have.get(did) or {}, cache)):
                st["zaten_adli"] += 1
                continue
            st["derleme"] += 1
        r = render(TASK, inputs_of(ws, did, recs[did], docs.get(did), cs, notes.get(did)))
        sha = _sha(r["prompt"])[:16]
        p = d / f"{did}.json"
        st["paket"] += 1
        old = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
        if old and old.get("istem_sha") == sha and str(old.get("surum")) == str(r["version"]):
            continue
        out = d / f"{did}.out.json"
        if out.exists():
            out.replace(d / f"{did}.out.json.eski")
        p.write_text(json.dumps({"gorev": r["task"], "surum": str(r["version"]), "doc_id": did,
                                 "istem_sha": sha, "cikti_dosyasi": f"{did}.out.json",
                                 **({"belge_notu": N.note_sha(notes[did])} if notes.get(did) else {}),
                                 "istem": r["prompt"], "sema": r["schema"]}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
        st["yeni"] += 1
    if parca:
        save_derleme_cache(ws, cache)
    n = _pending(d)
    (d / "README.md").write_text(README.format(task=TASK, version=task_version(), n=n), encoding="utf-8")
    st["bekleyen"] = n
    return st


DERLEME_ONBELLEK = "derleme.onbellek"  # work/name/: derleme kanıtı önbelleği (JSON; prepare/apply yazar)
DERLEME_SURUM = "1"                   # derleme_kaniti/parça sınırı kodu değişirse artır


def _derleme_key(ad: str | None, text: str, quotes: dict[str, str]) -> str:
    return _sha(json.dumps([DERLEME_SURUM, ad or "", _sha(text), sorted(quotes.items())],
                           ensure_ascii=False))[:20]


def load_derleme_cache(ws: Workspace) -> dict:
    p = work_dir(ws) / DERLEME_ONBELLEK
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_derleme_cache(ws: Workspace, cache: dict) -> None:
    d = work_dir(ws)
    d.mkdir(parents=True, exist_ok=True)
    (d / DERLEME_ONBELLEK).write_text(json.dumps(cache, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _derleme(did: str, ad: str | None, text: str, quotes: dict[str, str], cache: dict | None) -> bool:
    """`derleme_kaniti`, önbellekle (anahtar: ad, metin özeti, alıntılar, kod sürümü)."""
    if cache is None:
        return derleme_kaniti(ad, text, quotes)
    k = _derleme_key(ad, text, quotes)
    hit = cache.get(did)
    if hit and hit.get("k") == k:
        return bool(hit["d"])
    v = derleme_kaniti(ad, text, quotes)
    cache[did] = {"k": k, "d": v}
    return v


def _needs_parts(ws: Workspace, did: str, rec: dict, have: dict, cache: dict | None = None) -> bool:
    """Belge parça adı için (yeniden) paketlenmeli mi: insan adı yok, derleme kanıtı var ve ad
    görevin bu sürümüyle derleme bilgisi verilerek (`derleme: true` kaydı) alınmamış."""
    if "insan" in have:
        return False
    m = have.get("model") or {}
    if str((m.get("gorev") or {}).get(TASK)) == task_version() and m.get("derleme"):
        return False
    q = accepted_quotes(rec)
    return len(q) > 0 and _derleme(did, m.get("ad") or decision_name(rec), _text(ws, did), q, cache)


def parts_pending(ws: Workspace, recs: dict[str, dict], names: dict[str, dict],
                  pool: list[str] | None = None, cache: dict | None = None) -> list[str]:
    """Adı olan ama parça adı bekleyen derleme belgeleri (`_needs_parts`); hattın name aşaması
    bunları da bekler (`bidr name prepare` varsayılan olarak paketler). `cache` verilmezse
    `work/name/derleme.json` okunur (yazılmaz: durum denetimi salt okunur)."""
    pool = eligible(recs) if pool is None else pool
    cache = load_derleme_cache(ws) if cache is None else cache
    out = []
    for did in pool:
        h = names.get(did) or {}
        if ("model" in h or decision_name(recs[did])) and _needs_parts(ws, did, recs[did], h, cache):
            out.append(did)
    return out


def _pkgs(d: Path) -> list[Path]:
    return sorted(p for p in d.glob("*.json") if not p.name.endswith(".out.json")) if d.exists() else []


def _pending(d: Path) -> int:
    return sum(1 for p in _pkgs(d) if not (d / f"{p.stem}.out.json").exists())


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", only: list[str] | None = None,
          validate=None) -> dict:
    from bidr.pipeline import cevap as CV
    if validate is None:
        from bidr.llm import validate_output as validate
    ws = Workspace(ws_root)
    d = work_dir(ws)
    den = CV.Denemeler(ws.root, DIZIN)
    kesin = CV.Kesin(ws.root, "name")
    ver = task_version()
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "reddedilen": {}, "eski_surum": [],
          "dogrulanmali": {}, "parca": {}, "parca_not": {}, "elle_bakilmali": {}, "yeniden": {}}
    have = load_names(ws.root)
    dp = ws.root / "decisions.jsonl"
    recs = {r["doc_id"]: r for r in read_jsonl(dp) if r.get("doc_id")} if dp.exists() else {}
    cache = load_derleme_cache(ws)
    new: list[dict] = []
    for p in _pkgs(d):
        pkg = json.loads(p.read_text(encoding="utf-8"))
        did = pkg["doc_id"]
        if only and did not in only:
            continue
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != ver:
            st["eski_surum"].append(did)
            continue
        raw = outp.read_text(encoding="utf-8")
        if el := (kesin.get(did) or den.elle_ayni(did, CV.sha(raw), pkg["istem_sha"])):
            st["elle_bakilmali"][did] = el     # karar verilmiş (kural adında kalır): aynı cevap yeniden denenmez
            continue
        out, errs, enum_not = CV.dogrula(validate, TASK, raw)
        kod = "sema"
        if out is not None:
            ad, errs, notes = check_name_noted(out.get("kanit_adi"))
            kod = "ad"
        if errs:
            # ret bir denemedir: cevap kenara alınır, paket yeniden cevap bekler; aynı nedenle ikinci ret →
            # elle bakılmalı (belge kural adında kalır)
            r = den.reddet(did, outp, kod, [str(e) for e in errs][:5], parmak=pkg["istem_sha"], model=model)
            if r["sonuc"] == CV.ELLE:
                st["elle_bakilmali"][did] = den.elle(did)
            elif kod == "sema":
                st["gecersiz"][did] = errs[:5]
            else:
                st["reddedilen"][did] = {"oneri": out.get("kanit_adi"), "neden": errs}
            if r["sonuc"] != CV.ELLE:
                st["yeniden"][did] = r
            continue
        den.basarili(did)
        rec = {"doc_id": did, "ad": ad, "kaynak": "model", "model": model, "gorev": {TASK: ver},
               "istem_sha": pkg["istem_sha"], "cevap_sha": _sha(raw)[:16],
               "gerekce": out.get("gerekce", "")}
        if pkg.get("belge_notu"):           # ad yükleyenin notu görülerek verildi (bidr/notlar.py)
            rec["belge_notu"] = pkg["belge_notu"]
            rec["not_uyusmuyor"] = N.conflict(out.get("gerekce"))
        if notes:
            rec["oneri"] = out.get("kanit_adi")
            rec["not"] = notes
        text, quotes = _text(ws, did), accepted_quotes(recs.get(did))
        parts, pnotes = normalize_parts(out.get("parca_adlari"), ad, text, quotes)
        if parts:
            rec["parca_adlari"] = st["parca"][did] = parts
        if pnotes:
            rec["parca_not"] = st["parca_not"][did] = pnotes
        g = grounding(ad, text, {y: q for y, q in quotes.items() if y not in parts})
        g = part_grounding(g, text, quotes, parts)
        # derleme bilgisi (parça adı soruldu mu): parça adı adımı bu kayıtla biter (`_needs_parts`)
        rec["derleme"] = bool(quotes) and _derleme(did, ad, text, quotes, cache)
        if g["dogrulanmali"]:
            rec["dogrulanmali"] = {"belge": g["belge"], "parca_uyumsuz": g["parca_uyumsuz"]}
            st["dogrulanmali"][did] = {"ad": ad, **rec["dogrulanmali"]}
        prev = (have.get(did) or {}).get("model")
        if prev and {k: v for k, v in prev.items() if k != "zaman"} == rec:
            st["degismedi"] += 1
            continue
        new.append({**rec, "zaman": time.strftime("%Y-%m-%dT%H:%M:%S")})
        st["islenen"] += 1
    if new:
        upsert(ws.root / NAMES, new)
        save_derleme_cache(ws, cache)
    den.kaydet()
    lines = [f"# Yeniden yapılacak ({TASK})", ""]
    for did, errs in st["gecersiz"].items():
        lines.append(f"- `{did}.json` — geçersiz cevap: " + "; ".join(errs)
                     + CV.kenar_notu(st["yeniden"].get(did), did))
    for did, x in st["reddedilen"].items():
        lines.append(f"- `{did}.json` — ad reddedildi ({', '.join(x['neden'])}): "
                     + json.dumps(x["oneri"], ensure_ascii=False)
                     + f". Kişi adı/unvan/e-posta yok; 3-7 sözcük; yasaklı karakter yok ({YASAKLI_GOSTERIM})."
                     + CV.kenar_notu(st["yeniden"].get(did), did))
    lines += CV.onceki_red_satirlari(den, st["bekleyen"], set(st["gecersiz"]) | set(st["reddedilen"]),
                                     lambda k: f"`{k}.json`")
    if st["dogrulanmali"]:
        lines += ["", "## Kabul edildi, doğrulanmalı (ad belgede dayanaksız ya da başka parçayı anlatıyor)", ""]
        for did, x in st["dogrulanmali"].items():
            why = x["belge"] + ([f"parca_uyumsuz: {', '.join(x['parca_uyumsuz'])}"] if x["parca_uyumsuz"] else [])
            lines.append(f"- `{did}.json` — {json.dumps(x['ad'], ensure_ascii=False)} ({'; '.join(why)}). "
                         "Ad alıntının geldiği belgeyi/parçayı adlandırmalı; belgede olmayan nitelik yok.")
    if d.exists():
        g = d / "GECERSIZ.md"
        if len(lines) > 2:
            g.write_text("\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    CV.elle_raporu(d, den, TASK, "Bu belgeler model adı almadı: kanıt adı kuraldan (ya da incelemedeki insan "
                   "adından) gelir.", "Doğru ad `name/<doc_id>.out.json`'a yazılıp apply ile işlenebilir.")
    st["dosya"] = str(ws.root / NAMES)
    return st
