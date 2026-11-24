"""`bidr faaliyet`: decisions.jsonl → faaliyetler.json (bkz. group.py, docs/MODEL_LAYER.md
"Faaliyet kaydı"). Çalışma alanında yalnız `decisions.jsonl` okunur."""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from . import dosya as D
from . import group as G

DECISIONS = "decisions.jsonl"
OUT = "faaliyetler.json"
SCHEMA = 1


def entries_of(recs: list[dict], paths: dict[str, str] | None = None) -> tuple[list[G.Girdi], dict]:
    """İnce kararı faaliyet alanı taşıyan belgeler. Başka birime ait belge (`baska_birim`)
    alınmaz: başka birimin etkinliği bu birimin faaliyet kaydı değildir. `paths` (doc_id → kaynak
    yolu) verilirse dosya serisi (klasör + sıra numarasız ad) gruplamaya girer."""
    st = {"ince": 0, "faaliyetli": 0, "faaliyetsiz": 0, "alansiz_eski": 0, "baska_birim": 0}
    out = []
    for r in recs:
        ince = r.get("ince") or {}
        if r.get("durum") != "ok" or r.get("asama") != "ince" or ince.get("karar") == "atlandi":
            continue
        st["ince"] += 1
        if "faaliyet" not in ince:
            st["alansiz_eski"] += 1           # v8 ve öncesi kayıt: faaliyetsiz sayılır
            continue
        f = ince["faaliyet"]
        if not isinstance(f, dict) or not str(f.get("ad") or "").strip():
            st["faaliyetsiz"] += 1
            continue
        if ince.get("birim_iliskisi") == "baska_birim":
            st["baska_birim"] += 1
            continue
        ka = ince.get("kanit_adi") if isinstance(ince.get("kanit_adi"), dict) else {}
        ek = {"karar": r.get("karar"), "kanit_adi": ka.get("ad"),
              "birim_iliskisi": ince.get("birim_iliskisi"),
              "eslesmeler": [{"olcut": m.get("olcut"), "yuva": m.get("yuva"), "asama": m.get("asama"),
                              "od_kabul": m.get("od_kabul")}
                             for m in r.get("eslesmeler") or [] if m.get("kabul")]}
        yol = (paths or {}).get(r["doc_id"])
        if yol and D.klasor(yol) and D.seri_koku(yol):
            ek["seri"] = f"{D.klasor(yol)}|{D.seri_koku(yol)}"
        if ince.get(D.ALAN):
            ek["etkinlik_baglami"] = list(ince[D.ALAN])
        out.append(G.make_entry(r["doc_id"], f, ek))
        st["faaliyetli"] += 1
    return out, st


def build(recs: list[dict], paths: dict[str, str] | None = None, docs: dict[str, dict] | None = None) -> dict:
    """Faaliyet kayıtları. `paths`/`docs` (inventory, documents.jsonl) verilirse etkinlik dosyası
    (bidr/faaliyet/dosya.py) da kurulur: her kayda `dosya` (aynı klasör/ad serisinden, kayda girmemiş
    aday belgeler) ve üstte `baglamsiz_fotograflar` (faaliyet adı yok, hiçbir etkinlik grubuna bağlı
    değil: bölümden belge notu istenir)."""
    entries, st = entries_of(recs, paths)
    kayitlar = [G.summarize(k) for k in G.group(entries)]
    kayitlar.sort(key=lambda x: ((x["tarih_araligi"] or ["9999"])[0], x["ad"], x["belgeler"][0]["doc_id"]))
    for i, k in enumerate(kayitlar, 1):
        k["id"] = f"F{i:03d}"
    kayitlar = [{"id": k.pop("id"), **k} for k in kayitlar]
    st["faaliyet"] = len(kayitlar)
    st["yalniz_duyuru"] = sum(k["yalniz_duyuru"] for k in kayitlar)
    st["gerceklesme_kanitsiz"] = sum(k["durum"] == "gerceklesme_kanitsiz" for k in kayitlar)
    out = {"sema": SCHEMA, "ozet": st, "faaliyetler": kayitlar}
    if paths is not None and docs is not None:
        by_doc = {r["doc_id"]: r for r in recs}
        gr = D.gruplar(paths, docs, by_doc)
        kayitli = {b["doc_id"] for k in kayitlar for b in k["belgeler"]}
        for k in kayitlar:
            uy = {b["doc_id"] for b in k["belgeler"]}
            ek = sorted({d for g in gr if uy & set(g) for d in g} - kayitli)
            k["dosya"] = [{"doc_id": d, "yol": paths.get(d, ""), "tur": (docs.get(d) or {}).get("doc_type") or ""}
                          for d in ek]
        bagli = kayitli | {d for k in kayitlar for d in (x["doc_id"] for x in k["dosya"])}
        out["baglamsiz_fotograflar"] = [
            {"doc_id": d, "yol": paths.get(d, "")} for d in sorted(paths)
            if (docs.get(d) or {}).get("doc_type") in D.FOTOGRAF_TURLER and d not in bagli
            and (by_doc.get(d) or {}).get("durum") == "ok"
            and ((by_doc.get(d) or {}).get("ince") or {}).get("birim_iliskisi") != "baska_birim"]
        st["baglamsiz_fotograf"] = len(out["baglamsiz_fotograflar"])
    return out


def build_ws(ws: Workspace) -> dict:
    """Çalışma alanından (decisions, inventory, documents.jsonl) faaliyet kayıtları; salt okunur."""
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    return build(list(read_jsonl(ws.root / DECISIONS)), D.kaynak_yollari(ws), docs)


def run(ws_root: Path, out: Path | None = None) -> tuple[Path, dict]:
    ws = Workspace(Path(ws_root))
    src = ws.root / DECISIONS
    if not src.exists():
        raise FileNotFoundError(f"{DECISIONS} yok; önce `bidr decide`")
    data = build_ws(ws)
    dest = Path(out) if out else ws.root / OUT
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(dest)
    return dest, data


KISA = {"duyuru": "D", "plan": "P", "duzenleme": "Z", "gerceklesme": "G", "katilim": "K",
        "degerlendirme": "DG", "iyilestirme": "İ", "diger": "?"}


def table(data: dict) -> str:
    rows = [("Kimlik", "Tarih", "Faaliyet", "Aşamalar", "Eksik")]
    for k in data["faaliyetler"]:
        asm = " ".join(f"{KISA[a]}{len(v) if len(v) > 1 else ''}" for a, v in k["asamalar"].items())
        rows.append((k["id"], k["tarih"] or "-", k["ad"][:40], asm,
                     ("YALNIZ DUYURU; " if k["yalniz_duyuru"] else "") + ", ".join(k["eksik"]) or "-"))
    w = [max(len(r[i]) for r in rows) for i in range(4)]
    lines = ["  ".join(c.ljust(w[i]) if i < 4 else c for i, c in enumerate(r)) for r in rows]
    lines.insert(1, "  ".join("-" * x for x in w) + "  -----")
    return "\n".join(lines)
