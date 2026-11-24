"""`bidr arama`: ikinci aramanın ince karar paketleri ve sonuçlarının işlenmesi.

Ajan modu, `bidr decide` ile aynı sözleşme: `prepare` paketleri `work/ikinci_arama/<doc_id>.json`
olarak yazar (görev `classify_fine`, aynı istem ve şema; aday listesi yalnız ikinci aramanın
bu belgeye seçtiği ölçütler), ajan `<doc_id>.out.json` yazar, `apply` cevabı aynı kod
denetiminden (`decide.run.check_matches`: aday dışı ölçüt, yuva, birebir alıntı, OD, birim)
geçirip decisions.jsonl'deki kayda EKLER. İlk geçişin eşleşmeleri ve `ince` bölümü değişmez.

İşaret: ikinci aramanın eklediği her eşleşme `ikinci_arama: true` ve `denetim.isaret`te
`ikinci_arama` taşır. Alıntısı (normalize) kayıtta başka bir ölçütte kabul edilmiş eşleşmeninkiyle
aynıysa ayrıca `ayni_alinti_kabul` işareti ve `ayni_alinti_olcut` (o ölçütler) alır; inceleme
kartında "aynı alıntı X ölçütünde kabul" dikkat notu çıkar (`mark_same_quote`). Pakette belge başka
ölçütte kabul edilmişse istem bu kabulleri ve "aynı içeriği taşıma" kuralını taşır (`accepted_note`) (review.xlsx "işaretler" sütununda görünür); kayıtta `ikinci_arama`
bölümü hangi ölçütlerin hangi puanla bakıldığını tutar. Ölçüm: `bidr arama olcum`.

İlk geçiş yeniden karara bağlanırsa (`decide apply`) ikinci aramanın eşleşmeleri düşmez:
`decide.run.carry_second_search` onları yeni birim ilişkisiyle yeniden denetleyip kayda ekler ve
`ince_parmak`'ı günceller (aynı ölçüt/yuvayı ilk geçiş kabul ettiyse ikinci aramanınki düşer).
Cevabı zaten kayıtta olan paket, parmak izi eski olsa da işlenmiş sayılır (`merged`).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key

from . import ikinci as I
from .text import fold

WORK = "ikinci_arama"
ISARET = "ikinci_arama"
AYNI_ALINTI = "ayni_alinti_kabul"
AYNI_ALINTI_MIN = 30        # kapsama (biri ötekinin içinde) yalnız bu uzunluktan sonra aynı sayılır
REVIEW = "review-decisions.jsonl"

README = """# bidr ikinci arama paketleri: classify_fine (sürüm {version})

Bu klasördeki her `<doc_id>.json` bir ince karar paketidir; `bidr decide`'ın ince karar
paketleriyle aynı görev ve aynı kurallar. Fark: aday ölçütler kanıtsız ya da zayıf kalmış
ölçütlerdir (ikinci arama): ya ilk geçişte bu belge için aday olmamışlardır ya da belge başka
bir ölçütte kanıt olarak kabul edilmiştir ve aynı belgenin bu ölçüte de kanıt olup olmadığı
sorulur. Belgenin öteki ölçütteki kabulü bu ölçüt için kanıt değildir; yalnız metne bak. Belge
başka ölçütte kabul edilmişse eşleşme yalnız alıntı bu ölçütün yuvasına AYRI ve özgül bir içerikle
karşılık veriyorsa verilir; aynı alıntıyı ya da aynı içeriği iki ölçüte taşımak "olcut_yok"tur.
Uymuyorsa "olcut_yok" ya da "kanit_degil" geçerli ve beklenen cevaptır; zorlama.

1. Paketi oku; `istem` görevin tamamı, `sema` cevabın JSON şeması.
2. Cevabı YALNIZ JSON olarak aynı klasörde `<doc_id>.out.json` dosyasına yaz.
3. Bitince: `bidr arama apply -w <çalışma klasörü> --model <ajan/model adı>`.

Bekleyen paket: {n}
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def norm_quote(s: str | None) -> str:
    """Alıntı karşılaştırması için: aksan/büyük harf katlanmış, yalnız sözcükler."""
    return " ".join(re.findall(r"[a-z0-9]+", fold(s or "")))


def _same_quote(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= AYNI_ALINTI_MIN and short in long_


def mark_same_quote(did: str, matches: list[dict], review: dict[str, dict] | None = None) -> list[dict]:
    """İkinci arama eşleşmelerinden alıntısı başka ölçütte kabul edilmiş (insan reddetmemiş) bir
    eşleşmeninkiyle aynı olanlara `ayni_alinti_kabul` işareti ve `ayni_alinti_olcut` koyar (yerinde;
    eski işaret önce kalkar). Eşleşme reddedilmez: karar incelemede, kartta dikkat notuyla."""
    review = review or {}
    acc = [(norm_quote(m.get("alinti")), m.get("olcut")) for m in matches
           if m.get("kabul") and not I.human_rejected(review, did, m.get("yuva"))]
    for m in matches:
        if not m.get("ikinci_arama"):
            continue
        den = m.setdefault("denetim", {})
        den["isaret"] = [x for x in den.get("isaret") or [] if x != AYNI_ALINTI]
        m.pop("ayni_alinti_olcut", None)
        q = norm_quote(m.get("alinti"))
        hits = sorted({c for nq, c in acc if c and c != m.get("olcut") and _same_quote(q, nq)}, key=id_key)
        if hits:
            den["isaret"].append(AYNI_ALINTI)
            m["ayni_alinti_olcut"] = hits
    return matches


def accepted_note(did: str, view: dict, crits: list[str], review: dict[str, dict]) -> str:
    """İkinci arama paketine: belgenin başka ölçütlerde kabul edilmiş alıntıları ve kural."""
    rows = [m for m in view.get("eslesmeler") or []
            if m.get("kabul") and m.get("olcut") not in crits
            and not I.human_rejected(review, did, m.get("yuva"))]
    if not rows:
        return ""
    lines = ["İKİNCİ ARAMA — BU BELGE BAŞKA ÖLÇÜTLERDE KABUL EDİLDİ:"]
    for m in sorted(rows, key=lambda m: (id_key(m["olcut"]), str(m.get("yuva"))))[:8]:
        q = " ".join(str(m.get("alinti") or "").split())
        lines.append(f"- {m.get('yuva') or m['olcut']}: \"{q[:300]}{'…' if len(q) > 300 else ''}\"")
    lines.append("Aday ölçütlere eşleşmeyi yalnız alıntı o ölçütün yuvasına AYRI ve özgül bir içerikle "
                 "karşılık veriyorsa ver. Yukarıdaki alıntıyı ya da aynı içeriği (aynı bilgi, başka "
                 "sözcüklerle) benzer bir ölçüte taşımak eşleşme değildir: o durumda \"olcut_yok\".")
    return "\n".join(lines)


def first_pass_print(rec: dict) -> str:
    """İlk geçişin ince kararının parmak izi (ikinci aramanın eşleşmeleri hariç)."""
    ince = rec.get("ince") or {}
    ms = [[m.get("olcut"), m.get("yuva"), m.get("alinti")] for m in rec.get("eslesmeler") or []
          if not m.get("ikinci_arama")]
    return _sha(json.dumps([rec.get("adaylar") or [], ince.get("istem_sha"), ince.get("cevap_sha"),
                            ince.get("model"), ms], ensure_ascii=False, sort_keys=True))


def done_criteria(rec: dict) -> set[str]:
    """Bu kayıtta ikinci aramayla bakılmış ölçütler (ilk geçiş değişmediyse)."""
    ia = rec.get("ikinci_arama") or {}
    if not ia or ia.get("ince_parmak") != first_pass_print(rec):
        return set()
    n = sum(bool(m.get("ikinci_arama")) for m in rec.get("eslesmeler") or [])
    if n != ia.get("eslesme", 0):
        return set()
    return set((ia.get("olcutler") or {}))


def merged(rec: dict | None, pkg: dict, cevap: str) -> bool:
    """Paketin bu cevabı kayda zaten işlenmiş mi (ilk geçiş sonradan yeniden uygulanmış olsa da)."""
    if not rec:
        return False
    oc = (rec.get("ikinci_arama") or {}).get("olcutler") or {}
    adaylar = (pkg.get("meta") or {}).get("adaylar") or []
    return done_criteria(rec) >= set(adaylar) and all(
        (oc.get(c) or {}).get("cevap_sha") == cevap and (oc.get(c) or {}).get("istem_sha") == pkg.get("istem_sha")
        for c in adaylar)


def pkg_status(d: Path, pkg: dict, rec: dict | None, ver: str) -> str:
    """Paketin durumu: "merged" (cevabı kayıtta), "eski" (görev sürümü değişmiş, kayıt ince değil
    ya da ilk geçişin parmak izi pakettekinden farklı) ya da "guncel". `prepare` ile
    `ikinci_arama_tamam` aynı tanımı kullanır: prepare'den sonra eski paket kalmaz."""
    outp = d / pkg["cikti_dosyasi"]
    ok_rec = bool(rec) and rec.get("asama") == "ince"
    if (str(pkg.get("surum")) == ver and ok_rec and outp.exists()
            and merged(rec, pkg, _sha(outp.read_text(encoding="utf-8")))):
        return "merged"
    if (str(pkg.get("surum")) != ver or not ok_rec
            or first_pass_print(rec) != ((pkg.get("meta") or {}).get("ikinci_arama") or {}).get("ince_parmak")):
        return "eski"
    return "guncel"


def stale_pkgs(d: Path, recs: dict[str, dict]) -> list[str]:
    """Klasördeki eski paketlerin doc_id'leri (`pkg_status` == "eski")."""
    from bidr.decide.run import FINE, _load_pkg, _pkg_paths, task_version
    if not d.exists():
        return []
    ver = task_version(FINE)
    return [pkg["doc_id"] for p in _pkg_paths(d) if (pkg := _load_pkg(p)) is not None
            and pkg_status(d, pkg, recs.get(pkg["doc_id"]), ver) == "eski"]


def _archive(d: Path, did: str) -> list[str]:
    """Adaylıktan düşen eski paketi ve cevaplarını `_eski/` altına taşır (silmez; ad çakışırsa
    sonuna sayı eklenir)."""
    arc = d / "_eski"
    arc.mkdir(exist_ok=True)
    moved = []
    for name in (f"{did}.json", f"{did}.out.json", f"{did}.out.json.eski"):
        src = d / name
        if not src.exists():
            continue
        dst, i = arc / name, 1
        while dst.exists():
            dst, i = arc / f"{name}.{i}", i + 1
        src.replace(dst)
        moved.append(name)
    return moved


def eligible_map(ctx, recs: dict[str, dict], weak: set[str], *, redo: bool = False) -> tuple[dict, dict]:
    """({doc_id: ikinci aramaya açık zayıf ölçütler}, sayaçlar)."""
    from bidr.decide.run import BIRIM_DISI, record_unit_relation, unit_view

    st = {"ince_yok": 0, "haric": 0, "baska_birim": 0, "devralan": 0}
    allowed = set(ctx.allowed)
    out: dict[str, set[str]] = {}
    for did in sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")):
        rec = recs.get(did)
        if not rec or rec.get("durum") != "ok" or rec.get("asama") != "ince":
            st["ince_yok"] += 1
            continue
        if ctx.skip_reason(did):
            st["haric"] += 1
            continue
        if record_unit_relation(unit_view(rec, ctx.pins, ctx.tags)) == BIRIM_DISI:
            st["baska_birim"] += 1
            continue
        if (rec.get("mukerrer") or {}).get("durum") == "devralindi":
            st["devralan"] += 1                 # temsilcisi aranır; aynı metin iki kez paketlenmez
            continue
        skip = I.first_pass_candidates(rec) | (set() if redo else done_criteria(rec))
        ok = {c for c in weak if c in allowed and c not in skip}
        if ok:
            out[did] = ok
    return out, st


def cross_pool(ctx, recs: dict[str, dict], weak: set[str], review: dict[str, dict], *,
               redo: bool = False) -> dict[str, dict]:
    """Çapraz yolun havuzu: {doc_id: {"acik": zayıf ölçütler, "kabul": başka ölçütler}}.
    Belge ince kararı sonuçlanmış, hariç tutulmamış, devralan mükerrer değil, birimin kendi
    belgesi (`ikinci.unit_own`, insan birim kararı öncelikli) ve en az bir ölçütte kabul edilmiş
    (insan reddetmemiş) olmalı. Açık ölçüt: ilk geçişte o belgeyle eşleşmesi olmayan, ikinci
    aramayla bakılmamış (`redo` değilse) zayıf ölçüt; ilk geçişin adayı olmuş olabilir."""
    from bidr.decide.run import unit_view

    allowed = set(ctx.allowed)
    out: dict[str, dict] = {}
    for did in sorted(p.stem for p in ctx.ws.text_dir.glob("*.txt")):
        rec = recs.get(did)
        if not rec or rec.get("durum") != "ok" or rec.get("asama") != "ince" or ctx.skip_reason(did):
            continue
        if (rec.get("mukerrer") or {}).get("durum") == "devralindi":
            continue
        view = unit_view(rec, ctx.pins, ctx.tags)
        if not I.unit_own(view, ctx.docs.get(did)):
            continue
        kabul = I.accepted_elsewhere(rec, view, review)
        if not kabul:
            continue
        skip = I.first_pass_matched(rec) | (set() if redo else done_criteria(rec))
        acik = {c for c in weak if c in allowed and c not in skip}
        if acik:
            out[did] = {"acik": acik, "kabul": kabul}
    return out


def load_review(ws_root: Path) -> dict[str, dict]:
    """review-decisions.jsonl (`bidr audit apply`): {"<doc_id>|<yuva>": karar}; yoksa boş."""
    from bidr.common import read_jsonl
    p = Path(ws_root) / REVIEW
    return {r["satir"]: r for r in read_jsonl(p) if r.get("satir")} if p.exists() else {}


def _write_readme(d: Path) -> int:
    from bidr.decide.run import FINE, _pkg_paths, task_version
    pending = sum(1 for p in _pkg_paths(d) if not (d / f"{p.stem}.out.json").exists())
    (d / "README.md").write_text(README.format(version=task_version(FINE), n=pending), encoding="utf-8")
    return pending


def prepare(ws_root: Path, *, profile: str | None = "akademik_bolum", n: int = I.N_BELGE,
            max_aday: int = 6, od_esik: int = I.OD_ESIK, olcutler: list[str] | None = None,
            synonyms: bool = True, redo: bool = False, capraz: bool = True, backend=None,
            ctx=None, yalniz_denetim: bool = False) -> dict:
    """Zayıf ölçütleri bulur, arşivde arar, belge başına bir ince karar paketi yazar.
    `olcutler` verilirse zayıflık hesaplanmaz, yalnız bu ölçütler aranır. `capraz`: başka
    ölçütte kabul edilmiş birim belgeleri de zayıf ölçütlere aday olur (çapraz yol).
    Kör denetimin bölümce kabul edilen kullanılmamış belge önerileri (bidr/kor/run.py `kanit_ciftleri`)
    her zaman pakete girer (kaynak `denetim`; ilk geçişin adayı olsa da). `yalniz_denetim`: yalnız onlar
    (zayıflık hesaplanmaz, arşiv ve çapraz yol çalışmaz)."""
    from bidr.decide.run import (FINE, Backend, Context, _write_pkg, fine_inputs, load_decisions,
                                 task_version, work_dir)

    backend = backend or Backend()
    if ctx is None:
        ctx = Context.load(ws_root, profile=profile, max_aday=max_aday)
    recs = load_decisions(ctx.ws)
    audit = I.load_audit(ctx.ws.root / I.AUDIT_JSON)
    if yalniz_denetim:
        weak, capraz = {}, False
    elif olcutler:
        weak = {c: {"olcut": c, "nedenler": ["elle"], "kaynak": "elle"} for c in olcutler}
    else:
        weak = I.weak_criteria(ctx.allowed, recs, audit=audit, pins=ctx.pins, tags=ctx.tags,
                               docs=ctx.docs, od_esik=od_esik)
    elig, est = eligible_map(ctx, recs, set(weak), redo=redo)
    searcher = I.Searcher(ctx.cs, I.Archive.load(ctx.ws.root), synonyms=synonyms)
    picks = I.select(searcher, weak, elig, n=n)
    by_doc: dict[str, dict[str, dict]] = {}
    for c, rows in picks.items():
        for r in rows:
            by_doc.setdefault(r["doc_id"], {})[c] = {
                "olcut": c, "puan": r["puan"], "sira": r["sira"], "sinyaller": r["sinyaller"],
                "nedenler": weak[c]["nedenler"], "kaynak": ["arsiv"]}
    pool = cross_pool(ctx, recs, set(weak), load_review(ctx.ws.root), redo=redo) if capraz else {}
    cross = I.select_cross(searcher, weak, pool, max_aday=max_aday)
    for did, rows in cross.items():
        slot = by_doc.setdefault(did, {})
        for r in rows:
            row = slot.setdefault(r["olcut"], {
                "olcut": r["olcut"], "puan": r["puan"], "sira": r["sira"], "sinyaller": r["sinyaller"],
                "nedenler": weak[r["olcut"]]["nedenler"], "kaynak": []})
            row["kaynak"].append("capraz")
            row["kabul_olcutler"] = pool[did]["kabul"]
    from bidr.kor.run import kanit_ciftleri
    denetim = [x for x in kanit_ciftleri(ctx.ws.root, recs=recs)
               if (recs.get(x["doc_id"]) or {}).get("asama") == "ince"]
    for x in denetim:                       # bölümün kabul ettiği kör denetim önerisi: zorunlu aday
        row = by_doc.setdefault(x["doc_id"], {}).setdefault(x["olcut"], {
            "olcut": x["olcut"], "puan": 0.0, "sira": 0, "sinyaller": {}, "nedenler": [], "kaynak": []})
        row["kaynak"].append("denetim")
        row["nedenler"].append(f"kör denetim önerisi, bölüm kabul etti ({x['bulgu_id']})")
    d = work_dir(ctx.ws, WORK)
    d.mkdir(parents=True, exist_ok=True)
    secim_capraz: dict[str, list[str]] = {}
    for did, rows in cross.items():
        for r in rows:
            secim_capraz.setdefault(r["olcut"], []).append(did)
    st = {"zayif": weak, "audit": audit is not None, "paket": 0, "yeni": 0, "kesilen": 0,
          "secim": {c: [r["doc_id"] for r in rows] for c, rows in picks.items()},
          "secim_capraz": secim_capraz, "capraz_havuz": len(pool), "capraz_paket": len(cross),
          "capraz_cift": sum(len(v) for v in cross.values()), "tasinan": [],
          "denetim": [f"{x['doc_id']}:{x['olcut']}" for x in denetim], **est}
    stale = set(stale_pkgs(d, recs))
    from bidr.decide.run import unit_view
    review = load_review(ctx.ws.root)
    for did in sorted(by_doc):
        rows = sorted(by_doc[did].values(),          # denetim önerisi kesilmez
                      key=lambda r: ("denetim" not in r["kaynak"], -r["puan"], id_key(r["olcut"])))
        st["kesilen"] += max(0, len(rows) - max_aday)
        rows = rows[:max_aday]
        crits = [r["olcut"] for r in rows]
        rec = recs[did]
        sub = dataclasses.replace(ctx, cand={}, max_aday=len(crits))
        inputs, meta = fine_inputs(sub, did, {"kaba": {"secilen": crits},
                                              "belge_bilgisi": rec.get("belge_bilgisi") or {}},
                                   komisyon=False)
        note = accepted_note(did, unit_view(rec, ctx.pins, ctx.tags), crits, review)
        if note:                            # yalnız bekleyen/yeni paketin istemi değişir (bakılmış çift paketlenmez)
            inputs["belge_bilgisi"] = (inputs["belge_bilgisi"].rstrip() + "\n\n" + note).strip()
            meta["ikinci_arama_kabul_notu"] = True
        meta["ikinci_arama"] = {"olcutler": rows, "ince_parmak": first_pass_print(rec)}
        st["paket"] += 1
        # ilk geçiş değişmişse istem aynı kalsa da paket (ve parmak izi) yenilenir, eski cevap `.eski` olur
        st["yeni"] += _write_pkg(d, did, FINE, inputs, meta, backend, force=redo or did in stale)
    for did in sorted(stale - set(by_doc)):      # artık aday değil: eski paket `_eski/`'ye
        if _archive(d, did):
            st["tasinan"].append(did)
    st["eski_kalan"] = len(stale_pkgs(d, recs))
    st["bekleyen"] = _write_readme(d)
    st["klasor"] = str(d)
    return st


def merge(ctx, did: str, rec: dict, out: dict, pkg: dict, model: str, verify, cevap_sha: str | None = None,
          review: dict[str, dict] | None = None) -> dict:
    """İkinci aramanın cevabını kayda ekler. Paketteki ölçütlerin önceki ikinci arama
    eşleşmeleri yenisiyle değişir; ilk geçişin eşleşmeleri ve `ince` bölümü değişmez.
    Birim ilişkisi kayıttan (insan kararı öncelikli): ilk geçişte verilmiş karar esastır."""
    from bidr.decide.run import (BIRIM_DISI, check_matches, kurum_geneli, record_unit_relation,
                                 summarize, unit_relation)
    meta = pkg["meta"]
    crits = meta["adaylar"]
    pin = ctx.pin(did)
    rel = pin or (record_unit_relation(rec) if (rec.get("ince") or {}).get("birim_iliskisi")
                  else unit_relation(out)[0])
    kg = kurum_geneli({**out, "birim_iliskisi": rel}, ctx.docs.get(did))
    new = check_matches(out, crits, ctx.cs, ctx.tags, ctx.text(did), verify, kg["karar"], rel)
    for m in new:
        m["ikinci_arama"] = True
        m["denetim"]["isaret"] = [*m["denetim"]["isaret"], ISARET]
    for m in new:
        m["ikinci_arama_paket"] = pkg["istem_sha"]
    # önceki ikinci arama eşleşmelerinden bu paketin ölçütlerine ait olanlar ve aynı paketin
    # önceki cevabından kalanlar (aday dışı dahil) yenisiyle değişir
    cset = set(crits)
    keep = [m for m in rec.get("eslesmeler") or []
            if not (m.get("ikinci_arama") and (m.get("olcut") in cset
                                                or m.get("ikinci_arama_paket") == pkg["istem_sha"]))]
    rec = dict(rec)
    rec["eslesmeler"] = mark_same_quote(did, keep + new, review)
    rec["olcutler"] = summarize(rec["eslesmeler"])
    if rec["olcutler"]:
        rec["karar"] = "olcut_var"
    rec["reddedilen_eslesme"] = sum(not m["kabul"] for m in rec["eslesmeler"])
    ia = dict(rec.get("ikinci_arama") or {})
    if ia.get("ince_parmak") != meta["ikinci_arama"]["ince_parmak"]:
        ia = {}                                  # ilk geçiş değişmiş: eski ikinci arama geçersiz
    info = {r["olcut"]: r for r in meta["ikinci_arama"]["olcutler"]}
    oc = dict(ia.get("olcutler") or {})
    for c in crits:
        oc[c] = {"puan": info.get(c, {}).get("puan"), "sira": info.get(c, {}).get("sira"),
                 "nedenler": info.get(c, {}).get("nedenler", []),
                 "kaynak": info.get(c, {}).get("kaynak", ["arsiv"]), "istem_sha": pkg["istem_sha"],
                 "cevap_sha": cevap_sha, "model": model,
                 "eslesme": sum(m["olcut"] == c for m in new),
                 "kabul": sum(m["olcut"] == c and m["kabul"] for m in new)}
    ia.update(olcutler=oc, ince_parmak=meta["ikinci_arama"]["ince_parmak"],
              eslesme=sum(bool(m.get("ikinci_arama")) for m in rec["eslesmeler"]),
              son={"karar": out.get("karar"), "gerekce": out.get("gerekce", ""), "model": model,
                   "birim_iliskisi_model": unit_relation(out)[0], "birim_iliskisi": rel})
    rec["ikinci_arama"] = ia
    if rel == BIRIM_DISI:
        ia["son"]["not"] = "başka birime ait: eşleşmeler reddedildi"
    return rec, new


def apply(ws_root: Path, *, model: str = "ajan:belirtilmemis", backend=None, ctx=None) -> dict:
    """`.out.json` cevaplarını doğrular, ikinci arama eşleşmesi olarak decisions.jsonl'e ekler."""
    from bidr.decide.run import FINE, Backend, Context, _load_pkg, _pkg_paths, load_decisions, \
        save_decisions, task_version, work_dir

    backend = backend or Backend()
    if ctx is None:
        ctx = Context.load(ws_root, profile=None)
    recs = load_decisions(ctx.ws)
    review = load_review(ctx.ws.root)
    d = work_dir(ctx.ws, WORK)
    st = {"islenen": 0, "degismedi": 0, "bekleyen": [], "gecersiz": {}, "eski_surum": [],
          "eski_paket": [], "eklenen_kabul": 0, "eklenen_red": 0}
    for p in _pkg_paths(d) if d.exists() else []:
        pkg = _load_pkg(p)
        if pkg is None:
            continue
        did = pkg["doc_id"]
        outp = d / pkg["cikti_dosyasi"]
        if not outp.exists():
            st["bekleyen"].append(did)
            continue
        if str(pkg["surum"]) != task_version(FINE):
            st["eski_surum"].append(did)
            continue
        rec = recs.get(did)
        raw = outp.read_text(encoding="utf-8")
        cevap = _sha(raw)
        if rec and rec.get("asama") == "ince" and merged(rec, pkg, cevap):
            st["degismedi"] += 1                # ilk geçiş yeniden uygulandıysa da eşleşmeler kayıtta
            continue
        if not rec or rec.get("asama") != "ince" or \
                first_pass_print(rec) != pkg["meta"]["ikinci_arama"]["ince_parmak"]:
            st["eski_paket"].append(did)        # ilk geçiş değişmiş: `arama prepare` yeniden paketler
            continue
        out, errs = backend.validate_output(FINE, raw)
        if out is None:
            st["gecersiz"][did] = errs[:5]
            continue
        rec, new = merge(ctx, did, rec, out, pkg, model, backend.verify_quote, cevap, review=review)
        recs[did] = rec
        for m in new:
            st["eklenen_kabul" if m["kabul"] else "eklenen_red"] += 1
        st["islenen"] += 1
    save_decisions(ctx.ws, recs)
    if d.exists():
        lines = [f"- `{did}.json` — geçersiz cevap: " + "; ".join(e) for did, e in st["gecersiz"].items()]
        g = d / "GECERSIZ.md"
        if lines:
            g.write_text("# Yeniden yapılacak (ikinci arama)\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
        elif g.exists():
            g.unlink()
    return st
