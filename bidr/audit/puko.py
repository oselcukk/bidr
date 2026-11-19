"""PUKÖ zinciri: belgeler arası açık atıfla (bidr.faaliyet.atif) izleme → önlem halkası.

Ölçüt C'de izleme kanıtı olan bir belge X (C'deki sayılan satırı `kontrol_et`, ya da sayılan
satırı olup faaliyet kaydındaki aşaması `degerlendirme`) ve X'e (doğrudan ya da ara belgeler
üzerinden, en çok `atif.DERINLIK` bağ) metnindeki açık göndermeyle dayanan bir **karar** belgesi
Y (tür adı `_karari` ile biter) varsa, Y C'de önlem (Ö) halkasını kanıtlar: Y'nin C'deki satırı
`onlem_al`'a çıkar ya da Y için C'nin önlem yuvasında `puko_zinciri` satırı açılır (alıntı:
Y'deki gönderme cümlesi). İnsan kararı aşar: satır `ret`/`duzelt` aldıysa dokunulmaz, açılan
satır da review.xlsx'te reddedilebilir. Gerekçe: docs/AUDIT.md "PUKÖ zinciri".
"""
from __future__ import annotations

from bidr.criteria.slots import STAGE_OD
from bidr.faaliyet import atif as A

FLAG = "puko_zinciri"
IZLEME_FAALIYET = "degerlendirme"


def is_decision(dtype: str | None) -> bool:
    return bool(dtype) and str(dtype).endswith("_karari")


def build_links(docs: dict, recs: dict, text, kayitlar: list[dict]) -> tuple[list[dict], list[str]]:
    """docs: documents.jsonl; recs: {doc_id: ince kayıt}; text: doc_id → metin."""
    inp = {}
    for did, rec in recs.items():
        tarih = (docs.get(did) or {}).get("tarih") or (rec.get("belge_bilgisi") or {}).get("tarih")
        inp[did] = {"text": text(did), "tarih": tarih}
    return A.links(inp, kayitlar)


def _path_text(path: list[dict], names) -> str:
    parts = [names(path[0]["kaynak"])]
    for b in path:
        hedef = f"{b['faaliyet']} ({len(b['hedef'])} belge)" if b["faaliyet"] else names(b["hedef"][0])
        parts.append(hedef)
    return " → ".join(parts)


def _onlem_slots(slots, tags) -> list[str]:
    """Önlem yuvaları: yalnız onlem_al etiketli olanlar önce, sonra onlem_al içerenler, sonra belirsizler."""
    kesin = [s.id for s in slots if (t := tags.get(s.id)) is not None and not t.uncertain and "onlem_al" in t.stages]
    belirsiz = [s.id for s in slots if (t := tags.get(s.id)) is None or t.uncertain]
    return sorted(kesin, key=lambda i: len(tags[i].stages) > 1) + belirsiz


def apply(by_c: dict[str, list], baglar: list[dict], *, docs: dict, recs: dict, fmap: dict,
          slots_of, tags, make_row, review: dict, names) -> dict[str, list[dict]]:
    """Ölçüt satırlarına zincir halkalarını uygular (yerinde). → {ölçüt: [zincir kaydı]}.

    slots_of(c) → (yuvalar, halka kümesi); make_row(rec, m, dec) → satır;
    names(doc_id) → görünen belge adı."""
    if not baglar:
        return {}
    kaynaklar = sorted({b["kaynak"] for b in baglar if is_decision((docs.get(b["kaynak"]) or {}).get("doc_type"))
                        and b["kaynak"] in recs})
    reach = {y: A.reach(baglar, y) for y in kaynaklar}
    out: dict[str, list[dict]] = {}
    for c, rows in by_c.items():
        if not rows:
            continue
        slots, has = slots_of(c)
        if "onlem_al" not in has:
            continue
        izleme = {}
        for r in rows:
            if not r["sayilir"] or r["zayif"] or r["etkin_asama"] not in ("uygula", "kontrol_et", "onlem_al"):
                continue
            fa = fmap.get(r["doc_id"])
            if r["etkin_asama"] == "kontrol_et" or (fa and fa[1] == IZLEME_FAALIYET):
                izleme.setdefault(r["doc_id"], r)
        if not izleme:
            continue
        for y in kaynaklar:
            hits = [(x, reach[y][x]) for x in sorted(izleme) if x in reach[y] and x != y]
            if not hits:
                continue
            if any(r["doc_id"] == y and r["sayilir"] and not r["zayif"] and r["etkin_asama"] == "onlem_al"
                   and FLAG not in r["flags"] for r in rows):
                continue                                 # Y zaten Ö kanıtı
            x, path = min(hits, key=lambda h: (len(h[1]), h[0]))
            yol = _path_text(path, names)
            ara = [b["kaynak"] for b in path[1:]]
            gerekce = f"PUKÖ zinciri (metindeki açık atıf): {yol}; izleme: {names(x)} ({izleme[x]['yuva']})"
            # insan kararı aşar: Y'nin bu yuvadaki satırı reddedilmiş/düzeltilmişse sıradaki önlem yuvası
            cand = [(sl, next((r for r in rows if r["doc_id"] == y and r["yuva"] == sl), None))
                    for sl in _onlem_slots(slots, tags)]
            cand = [(sl, r) for sl, r in cand if r is None or (r["karar"] not in ("ret", "duzelt") and r["sayilir"])]
            if not cand:
                continue
            slot, row = cand[0]
            if row is not None:
                row["etkin_asama"], row["od"] = "onlem_al", STAGE_OD["onlem_al"]
                row["flags"] = list(dict.fromkeys(row["flags"] + [FLAG]))
                row["gerekce"] = "; ".join(v for v in (row["gerekce"], gerekce) if v)
            else:
                m = {"olcut": c, "yuva": slot, "asama": "onlem_al", "od_kabul": STAGE_OD["onlem_al"],
                     "od_onerisi": STAGE_OD["onlem_al"], "guven": "", "alinti": path[0]["atif"],
                     "gerekce": gerekce}
                row = make_row(recs[y], m, review.get(f"{y}|{slot}"))
                row["flags"] = list(dict.fromkeys(row["flags"] + [FLAG]))
                rows.append(row)
            ek = "Ö: izleme sonucuna açık atıfla dayanan karar (PUKÖ zinciri" + (
                "; ara belgeler de kanıt listesine önerilir)" if ara else ")")
            row["vurgu"] = "; ".join(v for v in (row["vurgu"], ek) if v)
            row["isaretler"] = ", ".join(row["flags"])
            out.setdefault(c, []).append({
                "satir": row["satir"], "onlem": y, "izleme": x, "ara_belgeler": ara,
                "yol": yol, "baglar": [{k: b[k] for k in ("kaynak", "hedef", "faaliyet", "tur", "atif")}
                                       for b in path],
                "sayilir": row["sayilir"]})
    return out
