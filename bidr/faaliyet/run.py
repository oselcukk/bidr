"""`bidr faaliyet`: decisions.jsonl → faaliyetler.json (bkz. group.py, docs/MODEL_LAYER.md
"Faaliyet kaydı"). Çalışma alanında yalnız `decisions.jsonl` okunur."""
from __future__ import annotations

import json
from pathlib import Path

from bidr.common import Workspace, read_jsonl

from . import group as G

DECISIONS = "decisions.jsonl"
OUT = "faaliyetler.json"
SCHEMA = 1


def entries_of(recs: list[dict]) -> tuple[list[G.Girdi], dict]:
    """İnce kararı faaliyet alanı taşıyan belgeler. Başka birime ait belge (`baska_birim`)
    alınmaz: başka birimin etkinliği bu birimin faaliyet kaydı değildir."""
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
        out.append(G.make_entry(r["doc_id"], f, ek))
        st["faaliyetli"] += 1
    return out, st


def build(recs: list[dict]) -> dict:
    entries, st = entries_of(recs)
    kayitlar = [G.summarize(k) for k in G.group(entries)]
    kayitlar.sort(key=lambda x: ((x["tarih_araligi"] or ["9999"])[0], x["ad"], x["belgeler"][0]["doc_id"]))
    for i, k in enumerate(kayitlar, 1):
        k["id"] = f"F{i:03d}"
    kayitlar = [{"id": k.pop("id"), **k} for k in kayitlar]
    st["faaliyet"] = len(kayitlar)
    st["yalniz_duyuru"] = sum(k["yalniz_duyuru"] for k in kayitlar)
    st["gerceklesme_kanitsiz"] = sum(k["durum"] == "gerceklesme_kanitsiz" for k in kayitlar)
    return {"sema": SCHEMA, "ozet": st, "faaliyetler": kayitlar}


def run(ws_root: Path, out: Path | None = None) -> tuple[Path, dict]:
    ws = Workspace(Path(ws_root))
    src = ws.root / DECISIONS
    if not src.exists():
        raise FileNotFoundError(f"{DECISIONS} yok; önce `bidr decide`")
    data = build(list(read_jsonl(src)))
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
