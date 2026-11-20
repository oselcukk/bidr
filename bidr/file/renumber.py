"""Dosyalama sonrası metin atıflarının kodla yeniden numaralanması (model yok).

Yazılmış ölçüt metni (`texts/<ölçüt>.json`) kanıtlara `[n_ODk]` diye atıf yapar; numara
`evidence-index.csv`'nin numarasıdır. Yeniden dosyalama numaraları değiştirebilir (seçim, ad sırası,
kanıtın çıkarılması). Gerçek veri 2026-11-21: kopyada yeniden dosyalama 27 numarayı başka belgeye
kaydırdı; metinler eski numaralarla kaldı, biçim denetimi `kanit_no_yineleniyor` ve
`atif_od_uyusmuyor` buldu.

Kural: metnin girdisi (`girdi_sha`: ölçütün kanıt listesi (no, doc_id) + OD) önceki dizinle
tutuyorsa ve değişiklik yalnız numaralamadaysa atıflar kodla güncellenir:
- yeni dizindeki her numaranın belgeleri (ve kod OD'si) önceki dizinde tek bir numarayla aynı
  (yeni kanıt eklenmedi: eklenen kanıtı metin hesaba katmalı → yeniden yazım);
- metnin atıf yaptığı her önceki numara böyle bir yeni numaraya düşüyor (atıf yapılan kanıt
  çıkmadı, bölünmedi, kod OD'si değişmedi);
- atıfsız kanıtın çıkması metni geçersiz kılmaz.
Metnin cümleleri değişmez, yalnız `[n_ODk]` numaraları, `atiflar`, `kanitlar` (no/ad/dosya) ve
`girdi_sha` güncellenir; `numara_haritasi` (şimdiki atıf → yazıldığı atıf) `text_sha`'yı
koruduğu için doğrulama ve ona dayanan kayıtlar geçerli kalır. Koşul tutmazsa metin olduğu gibi
kalır, `write_tamam` onu eski sayar (yeniden yazım).
"""
from __future__ import annotations

import json
from pathlib import Path

LOG = "yeniden_numaralama"


def _groups(rows: list[dict]) -> dict[str, dict]:
    """{kanit_no: {docs, yuvalar, od}} — aynı numaralı satırlar (kopya/sürüm) tek grup."""
    out: dict[str, dict] = {}
    for r in rows:
        no = r.get("kanit_no") or ""
        g = out.setdefault(no, {"docs": set(), "yuvalar": set(), "od": no.rsplit("_OD", 1)[-1]})
        g["docs"].add(r.get("doc_id") or "")
        y = r.get("yuvalar") or ""
        g["yuvalar"].update(y if isinstance(y, list) else [x.strip() for x in y.split(";") if x.strip()])
    return out


def number_map(old_rows: list[dict], new_rows: list[dict], cited: list[str]) -> tuple[dict | None, str]:
    """(önceki numara → yeni numara, "") ya da (None, neden). Bkz. modül belgesi."""
    old, new = _groups(old_rows), _groups(new_rows)
    used: set[str] = set()
    m: dict[str, str] = {}
    for n_no, g in new.items():
        cand = [o for o, x in old.items() if x["docs"] == g["docs"] and x["od"] == g["od"] and o not in used]
        if len(cand) > 1:
            cand = [o for o in cand if old[o]["yuvalar"] == g["yuvalar"]]
        if len(cand) != 1:
            return None, f"{n_no}: yeni ya da değişen kanıt (belgesi/kod OD'si önceki listede tek numarayla eşleşmiyor)"
        used.add(cand[0])
        m[cand[0]] = n_no
    lost = [c for c in cited if c not in m]
    if lost:
        return None, f"atıf yapılan kanıt listede yok ya da değişti: {', '.join(lost)}"
    return m, ""


def _cited(t: dict) -> list[str]:
    from bidr.write import text as T
    seen: list[str] = []
    for s in [p.get("metin") or "" for p in t.get("paragraflar") or []] + [t.get("onceki_yila_gore") or ""]:
        for c in T.citations(s):
            if c not in seen:
                seen.append(c)
    return seen


def apply_map(t: dict, m: dict[str, str], new_rows: list[dict], girdi: str) -> dict:
    """Metnin atıflarını `m` ile günceller (cümleler değişmez) → yeni kayıt."""
    from bidr.write import run as W
    from bidr.write import text as T

    def sub(s: str) -> str:
        return T.ATIF.sub(lambda x: "[" + m.get(f"{x.group(1)}_OD{x.group(2)}", f"{x.group(1)}_OD{x.group(2)}")
                          + "]", s)

    first: dict[str, dict] = {}
    for r in new_rows:
        first.setdefault(r["kanit_no"], r)
    old_h = t.get(W.NUMARA_HARITASI) or {}
    cited = _cited(t)
    h = {m.get(c, c): old_h.get(c, c) for c in cited}
    h = {k: v for k, v in h.items() if k != v}
    out = dict(t)
    out["paragraflar"] = [{**p, "metin": sub(p.get("metin") or ""),
                           "atiflar": [m.get(a, a) for a in p.get("atiflar") or []]}
                          for p in t.get("paragraflar") or []]
    if t.get("onceki_yila_gore"):
        out["onceki_yila_gore"] = sub(t["onceki_yila_gore"])
    ks = []
    for k in t.get("kanitlar") or []:
        no = m.get(str(k.get("no")), str(k.get("no")))
        r = first.get(no) or {}
        ks.append({**k, "no": no, **{f: r[f] for f in ("ad", "dosya") if r.get(f)}})
    out["kanitlar"] = sorted(ks, key=lambda k: int(str(k["no"]).split("_")[0]))
    if h:
        out[W.NUMARA_HARITASI] = h
    else:
        out.pop(W.NUMARA_HARITASI, None)
    out["girdi_sha"] = girdi
    changed = {o: n for o, n in m.items() if o != n and o in cited}
    if changed:
        from bidr.write import packages as K
        out[LOG] = [*(t.get(LOG) or []), {"harita": changed, "zaman": K.now()}]
    return out


def renumber_texts(ws_root: Path, old_rows: list[dict], new_rows: list[dict]) -> dict:
    """Dosyalamadan sonra: girdisi önceki dizinle tutan, yalnız numarası değişen metinlerin
    atıflarını günceller → {"yeniden_numaralanan": [ölçüt], "yeniden_yazilacak": {ölçüt: neden}}.
    `yeniden_yazilacak`: girdisi yeni dizinle tutmayan bütün metinler (write_tamam bunları eski sayar)."""
    from bidr.write import run as W
    from bidr.write.sources import AUDIT, load_audit
    res: dict = {"yeniden_numaralanan": [], "yeniden_yazilacak": {}}
    td = Path(ws_root) / W.TEXTS
    if not td.is_dir():
        return res
    try:
        audit = load_audit(Path(ws_root) / AUDIT) if (Path(ws_root) / AUDIT).exists() else {}
    except (OSError, ValueError, KeyError, TypeError):
        audit = {}
    by_new: dict[str, list[dict]] = {}
    by_old: dict[str, list[dict]] = {}
    for r in new_rows:
        by_new.setdefault(r["olcut"], []).append(r)
    for r in old_rows:
        by_old.setdefault(r.get("olcut") or "", []).append(r)
    for p in sorted(td.glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c = t.get("olcut") if isinstance(t, dict) else None
        if not c or not t.get("girdi_sha"):
            continue
        new_c = by_new.get(c, [])
        od_cur = int((audit.get(c) or {}).get("od") or 1)     # write_tamam'ın OD'si
        if not new_c:
            res["yeniden_yazilacak"][c] = "ölçütte artık kanıt yok"
            continue
        if t["girdi_sha"] == W.girdi_sha(new_c, od_cur):
            continue
        old_c = by_old.get(c, [])
        if not old_c or t["girdi_sha"] != W.girdi_sha(old_c, od_cur):
            res["yeniden_yazilacak"][c] = "metin önceki kanıt listesine de dayanmıyor (liste ya da OD değişti)"
            continue
        m, why = number_map(old_c, new_c, _cited(t))
        if m is None:
            res["yeniden_yazilacak"][c] = why
            continue
        rec = apply_map(t, m, new_c, W.girdi_sha(new_c, od_cur))
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        res["yeniden_numaralanan"].append(c)
    return res
