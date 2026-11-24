"""Bölümün elle eklediği belge–ölçüt eşleşmeleri (`elle-eslesmeler.json`): modelin önermediği bir eşleşmeyi
inceleme sırasında bölüm kendisi ekler ("bu eylem planı A.1.3'ün kanıtıdır").

Biçim (çalışma alanında; panel işleyicisi yazar, `bidr audit elle ekle|geri` de yazar; JSON):

    {"surum": 1, "kaynak": "bidr-panel", "eslesmeler": [
      {"anahtar": "panel-12",          # kaydın kimliği (panel: panel-<id>; komut satırı: cli-<kısa özet>)
       "dosya": "kurul/plan.pdf",      # kaynak klasöre göre göreli yol (inventory.csv `rel_path`)
       "sha256": "<64 hane>",          # özgün dosyanın; `dosya` ile ikisinden biri yeter
       "olcut": "A.1.3", "yuva": "A.1.3/2" | null, "asama": "planla|uygula|kontrol_et|onlem_al|ozgun" | null,
       "not": "...", "kim": "...", "tarih": "ISO"}]}

Eşleme belge notlarıyla aynı (bidr/notlar.py): `sha256` ya da `dosya` → inventory.csv → `doc_id` (kopya
satırları dahil; maskeli kaynakta sha değişir, göreli yol tutar). Mükerrer kopyası seçildiyse temsilcisine gider.

`esitle` dosyayı review-decisions.jsonl'e işler: her eşleşme insan kaynaklı bir kabul kaydıdır
(`"kaynak": "insan"`, `"elle": "<anahtar>"`) ve audit/OD, PUKÖ, kanıt dosyalama (file) ve rapor yazımında olağan
kabul gibi sayılır.
- Belgenin aynı ölçütte (yuva verildiyse aynı yuvada) zaten kabul edilmiş satırı varsa kayıt açılmaz
  (`zaten_kabul`); aynı dosyada ikinci kez verilen eşleşme de öyle.
- Belgenin o ölçütte modelin önerdiği ama kabul edilmemiş (karar bekleyen ya da insanın reddettiği) satırı varsa
  kayıt o satıra yazılır: elle ekleme, sonraki ve açık bir insan eylemidir, önceki ret kararını aşar. Önceki karar
  kayıtta (`onceki`) saklanır; ekleme geri alınınca geri gelir. Aşama verildiyse ve satırınkinden farklıysa kayıt
  aşama düzeltmeli kabuldür (`duzelt`, yalnız `asama`).
- Satır yoksa audit belgeye o ölçütte yeni (yapay) bir satır açar (`yapay: true`; yuva verilmediyse aşamaya uyan
  ve ölçütte henüz kimsenin doldurmadığı yuva seçilir, `yuva_kaynagi: otomatik`; ikinci arama belgede o ölçütte
  alıntı bulunca kayıt modelin içeriğe göre seçtiği yuvanın satırına geçer, `yuva_kaynagi: model`; aşama verilmediyse yuvanın tek kesin aşaması, o da yoksa en temkinlisi `planla` sayılır ve satırda
  söylenir). Alıntı: belgenin o ölçütte modelin bulduğu eşleşmenin alıntısı (ikinci arama dahil); yoksa satır
  alıntısızdır ve çift ikinci aramaya zorunlu aday olarak girer (kör denetimin kabul edilen belge önerisiyle aynı
  yol, kaynak `elle`): model belgeden alıntıyı bulur, kod birebir denetler, yazım o alıntıyı kullanır. Modelin o
  ölçütte karar bekleyen satırı elle satırına katılır (ayrı satır olarak sorulmaz).
- Dosyadan çıkarılan eşleşmenin kaydı kaldırılır (yalnız `elle` anahtarı eşleşen kayıtlar kaldırılır).
review-decisions.jsonl değişince inceleme tablosu (`review.xlsx` meta `elle_sha`), kanıt dosyalama ve sonraki
aşamalar eskir ve yeniden koşar. Elle kaydın satırındaki tablo kararı yok sayılır: geri almak dosyadan yapılır.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bidr.common import read_jsonl, write_jsonl

DOSYA = "elle-eslesmeler.json"
DURUM = "elle-eslesmeler-durum.json"     # son eşitlemenin sonucu (panel gösterir) + kaynak dosyanın özeti
KAYNAK = "insan"
ISARET = "elle_eslesme"
VARSAYILAN_ASAMA = "planla"
ASAMALAR = ("planla", "uygula", "kontrol_et", "onlem_al", "ozgun")
REVIEW = "review-decisions.jsonl"


def path(ws_root: Path | str) -> Path:
    return Path(ws_root) / DOSYA


def _s(v) -> str:
    return str(v or "").strip()


def oku_ham(ws_root: Path | str) -> dict:
    p = path(ws_root)
    if not p.is_file():
        return {"surum": 1, "eslesmeler": []}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{p} okunamadı: {e}") from e
    if not isinstance(d, dict) or not isinstance(d.get("eslesmeler", []), list):
        raise ValueError(f"{p}: `eslesmeler` bir liste olmalı")
    return d


def oku(ws_root: Path | str) -> list[dict]:
    """Geçerli biçimdeki girdiler (anahtar ve ölçüt dolu). Aynı anahtar bir kez (son yazılan)."""
    out: dict[str, dict] = {}
    for e in oku_ham(ws_root).get("eslesmeler") or []:
        if not isinstance(e, dict):
            continue
        k, c = _s(e.get("anahtar")), _s(e.get("olcut")).upper()
        if not k or not c:
            continue
        out[k] = {"anahtar": k, "dosya": _s(e.get("dosya")).replace("\\", "/"),
                  "sha256": _s(e.get("sha256")).lower(), "olcut": c, "yuva": _s(e.get("yuva")) or None,
                  "asama": _s(e.get("asama")).lower().replace(" ", "_") or None, "not": _s(e.get("not"))[:1000],
                  "kim": _s(e.get("kim")), "tarih": _s(e.get("tarih"))}
    return [out[k] for k in sorted(out)]


def yaz(ws_root: Path | str, girdiler: list[dict], kaynak: str | None = None) -> None:
    d = oku_ham(ws_root)
    d["surum"] = 1
    if kaynak:
        d["kaynak"] = kaynak
    d["eslesmeler"] = girdiler
    p = path(ws_root)
    tmp = p.with_name(p.name + ".yaziliyor")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def kaynak_sha(ws_root: Path | str) -> str:
    """Kaynak dosyanın özeti (yoksa "")."""
    p = path(ws_root)
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.is_file() else ""


def durum_oku(ws_root: Path | str) -> dict:
    p = Path(ws_root) / DURUM
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        return {}


def eski_mi(ws_root: Path | str) -> bool:
    """Kaynak dosya son eşitlemeden sonra değişti mi (audit eskir; `bidr audit` eşitler)."""
    return (durum_oku(ws_root).get("kaynak_sha") or "") != kaynak_sha(ws_root)


def kayitlar(review: dict[str, dict]) -> dict[str, dict]:
    """review-decisions içindeki elle kayıtları: {anahtar: kayıt}."""
    return {r["elle"]: r for r in review.values() if r.get("elle")}


def elle_sha(review: dict[str, dict]) -> str:
    """Elle kayıtlarının özeti (inceleme tablosunun güncelliği; yoksa "")."""
    ks = sorted((r for r in review.values() if r.get("elle")), key=lambda r: r["satir"])
    if not ks:
        return ""
    return hashlib.sha256(json.dumps(ks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def korunur(onceki: dict | None) -> bool:
    """Satırın kaydı elle eşleşme: inceleme tablosundaki karar onu değiştirmez (geri alma dosyadan)."""
    return bool(onceki and onceki.get("elle"))


def temel(review: dict[str, dict]) -> dict[str, dict]:
    """Elle kayıtları olmadan inceleme kararları (elle kaydın yerine önceki karar geri konur)."""
    out = {k: v for k, v in review.items() if not v.get("elle")}
    for r in review.values():
        if r.get("elle") and r.get("onceki"):
            out[r["satir"]] = r["onceki"]
    return out


def _doc_ids(ws_root: Path, recs: dict[str, dict]):
    from bidr.notlar import _inventory
    by_rel, by_sha = _inventory(ws_root)

    def get(e: dict) -> tuple[str | None, str]:
        did = (by_sha.get(e["sha256"]) if e["sha256"] else None) or (by_rel.get(e["dosya"]) if e["dosya"] else None)
        if not did and e["dosya"] in recs:       # komut satırı: doc_id verilmiş olabilir
            did = e["dosya"]
        if not did:
            return None, "belge çalışma alanında yok (sha256/dosya envanterde bulunamadı)"
        mk = (recs.get(did) or {}).get("mukerrer") or {}
        if mk.get("durum") == "devralindi" and mk.get("temsilci"):
            did = mk["temsilci"]
        return did, ""
    return get


def _tek_asama(tags, yuva: str | None) -> str | None:
    t = tags.get(yuva) if yuva else None
    if t is not None and not t.uncertain and len(t.stages) == 1 and t.stages[0] in ASAMALAR:
        return t.stages[0]
    return None


def _yuva_sec(cs, tags, olcut: str, asama: str, dolu: set[str], bos_degil: set[str] = frozenset()) -> str | None:
    """Yuva verilmemiş elle eşleşmenin yuvası: aşamaya uyan ve ölçütte hiçbir belgenin doldurmadığı yuva
    (OD/yuva kapsamı artsın), yoksa aşamaya uyan, yoksa herhangi bir yuva; `dolu`: bu belgenin kararı olan
    yuvalar (atlanır), `bos_degil`: ölçütte kabul edilmiş ya da karar bekleyen satırı olan yuvalar. Geçici
    seçimdir: ikinci arama belgede bu ölçütte alıntı bulursa kayıt modelin içeriğe göre seçtiği yuvanın
    satırına geçer (`esitle`, `aday`)."""
    slots = [s for s in cs.get(olcut).slots if not s.footnote]
    uy = [s for s in slots if (t := tags.get(s.id)) is not None and not t.uncertain and asama in t.stages]
    sira = [*(s for s in uy if s.id not in bos_degil), *uy, *(s for s in slots if s.id not in bos_degil), *slots]
    for s in sira:
        if s.id not in dolu:
            return s.id
    return None


def esitle(ws_root: Path | str, *, out: Path | None = None) -> dict:
    """`elle-eslesmeler.json` → review-decisions.jsonl (yalnız elle kayıtları değişir). Döner: özet
    {eklenen, guncellenen, kaldirilan, zaten_kabul: [anahtar], bulunamayan: [{anahtar, neden}], degisti}."""
    from bidr.audit.run import build
    from bidr.criteria.loader import load_criteria
    from bidr.criteria.slots import load_tags
    ws_root = Path(ws_root).expanduser().resolve()
    outp = Path(out).expanduser().resolve() if out else ws_root
    rp = outp / REVIEW
    review = {r["satir"]: r for r in read_jsonl(rp) if r.get("satir")} if rp.exists() else {}
    eski = kayitlar(review)
    base = temel(review)
    girdiler = oku(ws_root)
    st = {"eklenen": [], "guncellenen": [], "kaldirilan": [], "zaten_kabul": [], "bulunamayan": [],
          "bekleyen": [], "degisti": False}
    durum: dict[str, dict] = {}
    yeni: dict[str, dict] = {}
    if girdiler:
        cs = load_criteria()
        tags = load_tags(cs)
        dp = ws_root / "decisions.jsonl"
        recs = {r["doc_id"]: r for r in read_jsonl(dp) if r.get("doc_id")} if dp.exists() else {}
        a = build(ws_root, out=outp, review=base) if dp.exists() else None
        rows = a.rows if a is not None else []
        get = _doc_ids(ws_root, recs)
        alinan: set[tuple] = set()            # (doc, ölçüt, yuva|None) bu turda elle kabul edilen
        dolu = {r["satir"] for r in rows} | set(base)
        for e in girdiler:
            k = e["anahtar"]
            try:
                crit = cs.get(e["olcut"])
            except KeyError:
                st["bulunamayan"].append({"anahtar": k, "neden": f"ölçüt {e['olcut']} yok"})
                continue
            if e["yuva"]:
                try:
                    sl = cs.get_slot(e["yuva"])
                except KeyError:
                    st["bulunamayan"].append({"anahtar": k, "neden": f"yuva {e['yuva']} yok"})
                    continue
                if sl.footnote or sl.criterion != crit.id:
                    st["bulunamayan"].append({"anahtar": k, "neden": f"yuva {e['yuva']} {crit.id} ölçütünün kanıt "
                                                                     "yuvası değil"})
                    continue
            if e["asama"] and e["asama"] not in ASAMALAR:
                st["bulunamayan"].append({"anahtar": k, "neden": f"aşama '{e['asama']}' geçersiz "
                                                                 f"({', '.join(ASAMALAR)})"})
                continue
            did, neden = get(e)
            if not did:
                # belge henüz çalışma alanında yok (ör. yeni yüklendi, ingest sonra): bekler, sonraki audit'te denenir
                st["bekleyen"].append({"anahtar": k, "neden": neden})
                continue
            olcut, yuva = crit.id, e["yuva"]
            mine = [r for r in rows if r["doc_id"] == did or did in (r.get("kopyalar") or "").split("; ")]
            kabul = [r for r in mine if r["olcut"] == olcut and (yuva is None or r["yuva"] == yuva)
                     and r["karar"] in ("kabul", "duzelt")]
            if kabul or (did, olcut, yuva) in alinan or (did, olcut, None) in alinan or (
                    yuva is None and any(x[:2] == (did, olcut) for x in alinan)):
                st["zaten_kabul"].append(k)
                durum[k] = {"durum": "zaten_kabul", "neden": "belge bu maddede zaten kabul edilmiş", "doc_id": did,
                            "yuva": kabul[0]["yuva"] if kabul else (yuva or ""),
                            "satir": kabul[0]["satir"] if kabul else ""}
                continue
            aday = [r for r in mine if r["olcut_model"] == olcut and r["olcut"] == olcut
                    and (yuva is None or r["yuva_model"] == yuva) and r["karar"] in ("", "ret")]
            notu = "Bölüm elle ekledi" + (f" ({e['kim']}" + (f", {e['tarih'][:10]}" if e["tarih"] else "") + ")"
                                          if e["kim"] else "") + (f": {e['not']}" if e["not"] else "")
            rec = {"doc_id": did, "olcut": olcut, "karar": "kabul", "duzelt": None, "etiket": None,
                   "not": notu, "kaynak": KAYNAK, "elle": k, "elle_kim": e["kim"], "elle_tarih": e["tarih"]}
            if aday:
                r = aday[0]
                rec |= {"satir": r["satir"], "yuva": r["yuva_model"]}
                if e["asama"] and e["asama"] != r["etkin_asama"]:
                    rec |= {"karar": "duzelt", "duzelt": {"olcut": None, "yuva": None, "asama": e["asama"]}}
                rec["asama"] = e["asama"] or r["etkin_asama"]
            else:
                asama = e["asama"] or _tek_asama(tags, yuva) or VARSAYILAN_ASAMA
                y = yuva
                if y is None:
                    bos_degil = {r["yuva"] for r in rows if r["olcut"] == olcut and r["karar"] != "ret"
                                 and r.get("sayilir", True)} | {x["yuva"] for x in yeni.values() if x["olcut"] == olcut}
                    y = _yuva_sec(cs, tags, olcut, asama, {s.split("|", 1)[1] for s in dolu if s.startswith(did + "|")},
                                  bos_degil)
                    if y is None:
                        st["bulunamayan"].append({"anahtar": k, "neden": f"{olcut} ölçütünde boş yuva yok"})
                        continue
                sid = f"{did}|{y}"
                if sid in base and sid not in {r["satir"] for r in aday}:
                    st["bulunamayan"].append({"anahtar": k, "neden": f"{y} yuvasında bu belgenin başka bir kararı "
                                                                     "var; başka yuva seçin"})
                    continue
                rec |= {"satir": sid, "yuva": y, "asama": asama, "yapay": True,
                        "asama_varsayilan": not e["asama"] and _tek_asama(tags, yuva) is None}
            if yuva is None:                  # yuva seçilmedi: modelin içeriğe göre seçtiği ya da boş yuva
                rec["yuva_kaynagi"] = "model" if aday else "otomatik"
            if base.get(rec["satir"]):
                rec["onceki"] = base[rec["satir"]]
            dolu.add(rec["satir"])
            alinan.add((did, olcut, yuva))
            yeni[k] = {key: rec[key] for key in ("satir", "doc_id", "olcut", "yuva", "karar", "duzelt", "etiket",
                                                 "not", "kaynak", "elle", "elle_kim", "elle_tarih", "asama",
                                                 "yapay", "asama_varsayilan", "yuva_kaynagi", "onceki")
                     if key in rec}
    for b in st["bulunamayan"]:
        durum[b["anahtar"]] = {"durum": "bulunamadi", "neden": b["neden"], "doc_id": "", "yuva": "", "satir": ""}
    for b in st["bekleyen"]:
        durum[b["anahtar"]] = {"durum": "bekliyor", "neden": b["neden"], "doc_id": "", "yuva": "", "satir": ""}
    for k, r in yeni.items():
        durum[k] = {"durum": "uygulandi", "neden": "", "doc_id": r["doc_id"], "yuva": r["yuva"], "satir": r["satir"],
                    **({"yuva_kaynagi": r["yuva_kaynagi"]} if r.get("yuva_kaynagi") else {})}
    _durum_yaz(ws_root, durum)
    for k, r in yeni.items():
        if k not in eski:
            st["eklenen"].append(k)
        elif eski[k] != r:
            st["guncellenen"].append(k)
    st["kaldirilan"] = sorted(k for k in eski if k not in yeni)
    merged = dict(base)
    for r in yeni.values():
        merged[r["satir"]] = r
    if merged != review:
        write_jsonl(rp, [merged[x] for x in sorted(merged)])
        st["degisti"] = True
    return st


def _durum_yaz(ws_root: Path, durum: dict[str, dict]) -> None:
    from datetime import datetime
    d = {"surum": 1, "kaynak_sha": kaynak_sha(ws_root), "zaman": datetime.now().isoformat(timespec="seconds"),
         "eslesmeler": {k: durum[k] for k in sorted(durum)}}
    if not path(ws_root).is_file() and not durum:
        (Path(ws_root) / DURUM).unlink(missing_ok=True)
        return
    p = Path(ws_root) / DURUM
    tmp = p.with_name(p.name + ".yaziliyor")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def gerekli(ws_root: Path | str, out: Path | str | None = None) -> bool:
    """Eşitleme yapılacak bir şey var mı: kaynak dosya, durum dosyası ya da kayıtlarda elle kaydı."""
    ws_root = Path(ws_root)
    if path(ws_root).is_file() or (ws_root / DURUM).is_file():
        return True
    rp = Path(out or ws_root) / REVIEW
    return rp.exists() and any(r.get("elle") for r in read_jsonl(rp))


def ekle(ws_root: Path | str, belge: str, olcut: str, *, yuva: str | None = None, asama: str | None = None,
         notu: str = "", kim: str = "komut satırı") -> str:
    """Komut satırından eşleşme ekler (anahtar `cli-<kısa özet>`). `belge`: kaynak göreli yolu ya da doc_id."""
    from datetime import datetime
    girdi = oku(ws_root)
    belge = belge.replace("\\", "/")
    anahtar = "cli-" + hashlib.sha256(f"{belge}|{olcut}|{yuva or ''}".encode()).hexdigest()[:10]
    girdi = [e for e in girdi if e["anahtar"] != anahtar]
    girdi.append({"anahtar": anahtar, "dosya": belge, "sha256": "", "olcut": olcut.upper(), "yuva": yuva,
                  "asama": asama, "not": notu, "kim": kim, "tarih": datetime.now().isoformat(timespec="seconds")})
    yaz(ws_root, girdi)
    return anahtar


def geri(ws_root: Path | str, anahtar: str) -> bool:
    girdi = oku(ws_root)
    kalan = [e for e in girdi if e["anahtar"] != anahtar]
    if len(kalan) == len(girdi):
        return False
    yaz(ws_root, kalan)
    return True


def ciftler(ws_root: Path | str, recs: dict[str, dict] | None = None, *, bekleyen: bool = True) -> list[dict]:
    """Alıntısız elle satırları: [{doc_id, olcut, anahtar}] — belgede o ölçütte modelin kabul edilmiş eşleşmesi
    (alıntısı) yok. İkinci aramaya zorunlu aday (kaynak `elle`) olarak girer. `bekleyen`: ikinci aramayla o
    kaynakla henüz bakılmamış olanlar. Yalnız ince kararı olan belgeler (paket kurulabilir)."""
    ws_root = Path(ws_root)
    rp = ws_root / REVIEW
    if not rp.exists():
        return []
    ks = [r for r in read_jsonl(rp) if r.get("elle") and r.get("yapay")]
    if not ks:
        return []
    if recs is None:
        dp = ws_root / "decisions.jsonl"
        recs = {r["doc_id"]: r for r in read_jsonl(dp) if r.get("doc_id")} if dp.exists() else {}
    from bidr.candidates.arama import done_criteria
    out = []
    for r in ks:
        rec = recs.get(r["doc_id"]) or {}
        if rec.get("asama") != "ince":
            continue
        if any(m.get("kabul") and m.get("olcut") == r["olcut"] and m.get("alinti")
               for m in rec.get("eslesmeler") or []):
            continue
        if bekleyen:
            oc = ((rec.get("ikinci_arama") or {}).get("olcutler") or {}).get(r["olcut"]) or {}
            if r["olcut"] in done_criteria(rec) and "elle" in (oc.get("kaynak") or []):
                continue
        out.append({"doc_id": r["doc_id"], "olcut": r["olcut"], "anahtar": r["elle"]})
    return out
