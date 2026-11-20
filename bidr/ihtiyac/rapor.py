"""Ölçüt satırları, talepler (öncelik + puan + gerekçe) ve çıktılar (ihtiyac.xlsx, ihtiyac.md).

Öncelik (yüksekten düşüğe):
  1. kanıtsız ölçüt                  (puan 100)
  2. tek belgeyle OD artışı           (puan 80–84; düşük OD'de biraz daha yüksek)
  3. karşılığı olmayan iyi kanıt      (puan 60; eski sürümü olan 58)
  4. diğer (bir üst düzey için)       (puan 20)
Kapsam dışı ölçütler (sorumlu birim kapsamı `baska_birim`) listelenmez.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from bidr.audit.rules import GEREKEN, KISA, LEVELS, criterion_od
from bidr.criteria.model import id_key

from .eslestir import ESKI, VAR, YOK
from .tablolar import Sorumlular

P_KANITSIZ, P_TEK, P_REF, P_REF_ESKI, P_DIGER = 100, 80, 60, 58, 20
GRUP = {P_KANITSIZ: "kanıtsız ölçüt", P_TEK: "tek belgeyle OD artışı", P_REF: "karşılığı olmayan iyi kanıt",
        P_DIGER: "diğer"}
HALKA_AD = {"planla": "planlama", "uygula": "uygulama", "kontrol_et": "izleme (kontrol)",
            "onlem_al": "iyileştirme (önlem)", "ozgun": "özgün uygulama"}
FILES = {"xlsx": "ihtiyac.xlsx", "md": "ihtiyac.md", "json": "ihtiyac.json"}


def _grup(puan: int) -> str:
    if puan >= P_KANITSIZ:
        return GRUP[P_KANITSIZ]
    if puan >= P_TEK:
        return GRUP[P_TEK]
    if puan >= P_REF_ESKI:
        return GRUP[P_REF]
    return GRUP[P_DIGER]


def yuva_metinleri(cs, tags, cid: str, halka: str) -> list[str]:
    """Kılavuzda ölçütün bu aşamaya etiketli yuvaları (`A.1.1/3: metin`)."""
    out = []
    try:
        slots = [s for s in cs.get(cid).slots if not s.footnote]
    except KeyError:
        return out
    for s in slots:
        t = tags.get(s.id)
        if t is not None and halka in t.stages:
            out.append(f"{s.id}: {s.text}")
    return out


def en_iyi_halka(present: set[str], has: set[str], tek: list[str]) -> str | None:
    """OD'yi tek başına en çok yükselten halka; eşitlikte zincirde önce gelen, özgün en son."""
    if not tek:
        return None
    sira = list(KISA)
    return max(tek, key=lambda h: (criterion_od(present | {h}, has).od, h != "ozgun", -sira.index(h)))


def _mevcut(rows: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("sayilir") and r.get("karar") != "ret":
            by.setdefault(r["olcut"], []).append(r)
    return by


def olcut_satirlari(criteria: list[dict], rows: list[dict], kapsam: dict[str, str], cs, tags,
                    ref_items: list[dict], matches: dict[str, dict], sor: Sorumlular
                    ) -> tuple[list[dict], list[dict]]:
    """(ölçüt satırları, talepler). `matches`: referans öğe id → eşleştirme sonucu."""
    mev = _mevcut(rows)
    ref_by: dict[str, list[dict]] = {}
    for it in ref_items:
        ref_by.setdefault(it["olcut"], []).append(it)
    satirlar, talepler = [], []
    for c in sorted(criteria, key=lambda c: id_key(c["olcut"])):
        cid = c["olcut"]
        kps = kapsam.get(cid, "bolum")
        if kps == "baska_birim":
            continue
        od = int(c.get("od") or 1)
        z = c.get("zincir") or {}
        present = {h for h, v in z.items() if v.get("durum") == "var"}
        has = {h for h, v in z.items() if v.get("durum") != "yuvasiz"}
        nxt = c.get("sonraki_od") or (od + 1 if od < 5 else None)
        eksik_next = [h for h in LEVELS.get(nxt, ()) if h not in present] if nxt else []
        tek = [h for h in sorted(has - present, key=lambda x: list(KISA).index(x))
               if criterion_od(present | {h}, has).od > od]
        kanitlar = mev.get(cid, [])
        adlar = list(dict.fromkeys(r.get("kanit_adi") or r.get("belge") or r["doc_id"] for r in kanitlar))
        kanitsiz = not kanitlar
        refs = ref_by.get(cid, [])
        karsiliksiz = [it for it in refs if (matches.get(it["id"]) or {}).get("durum") in (YOK, ESKI)]
        gereken = []
        for h in eksik_next:
            ys = yuva_metinleri(cs, tags, cid, h)
            gereken.append(f"{HALKA_AD[h]}: {GEREKEN[h]}" + (" — yuvalar: " + " | ".join(ys) if ys else ""))
        ctal: list[dict] = []

        def ornek(h: str) -> str:
            xs = [it["kanit_adi"] for it in refs if it.get("asama") == h]
            return "; ".join(dict.fromkeys(xs))

        if kanitsiz or tek:
            h = en_iyi_halka(present, has, tek) or (eksik_next or ["planla"])[0]
            yeni = criterion_od(present | {h}, has).od
            alt = [x for x in tek if x != h and criterion_od(present | {x}, has).od == yeni and x != "ozgun"]
            ys = yuva_metinleri(cs, tags, cid, h)
            neden = (f"ölçütte sayılan kanıt yok (OD{od}); tek {HALKA_AD[h]} belgesi OD{yeni}'ü açar" if kanitsiz
                     else f"tek {HALKA_AD[h]} belgesi OD{od} → OD{yeni} yapar (zincir {c.get('zincir_kisa', '')})")
            if alt:
                neden += "; aynı etkiyi " + " ya da ".join(HALKA_AD[x] for x in alt) + " belgesi de yapar"
            ctal.append({"puan": P_KANITSIZ if kanitsiz else P_TEK + max(0, 3 - od) * 2, "halka": h,
                         "hedef_od": yeni, "istenecek": f"{HALKA_AD[h]} kanıtı: {GEREKEN[h]}",
                         "yuvalar": " | ".join(ys), "belge_turu": "",
                         "kimden": sor.kim(asama=h, olcut=cid), "ornek": ornek(h), "gerekce": neden})
        for it in karsiliksiz:
            m = matches.get(it["id"]) or {}
            eski = m.get("durum") == ESKI
            ctal.append({"puan": P_REF_ESKI if eski else P_REF, "halka": it.get("asama") or "",
                         "hedef_od": None,
                         "istenecek": (f"bu yılki sürümü: {it['kanit_adi']}" if eski
                                       else f"bu yılki karşılığı: {it['kanit_adi']}"),
                         "yuvalar": it.get("yuva") or "", "belge_turu": it.get("belge_turu") or "",
                         "kimden": sor.kim(it.get("belge_turu"), it.get("asama"), cid),
                         "ornek": it["kanit_adi"],
                         "gerekce": ("geçen yılın iyi kanıtı" + (f" ({it['tekrarlayan_ad']}, tekrarlayan)"
                                                                if it.get("tekrarlayan") else "")
                                     + "; " + (m.get("gerekce") or ""))})
        if not ctal and nxt:
            ys = []
            for h in eksik_next:
                ys += yuva_metinleri(cs, tags, cid, h)
            ctal.append({"puan": P_DIGER, "halka": ",".join(eksik_next), "hedef_od": nxt,
                         "istenecek": "; ".join(f"{HALKA_AD[h]} kanıtı" for h in eksik_next) or "—",
                         "yuvalar": " | ".join(ys), "belge_turu": "",
                         "kimden": "; ".join(dict.fromkeys(sor.kim(asama=h, olcut=cid) for h in eksik_next))
                                   or sor.kim(olcut=cid),
                         "ornek": "",
                         "gerekce": f"OD{nxt} için {len(eksik_next)} halka birlikte gerekli "
                                    f"({', '.join(HALKA_AD[h] for h in eksik_next)})"})
        for t in ctal:
            t.update({"olcut": cid, "baslik": c.get("baslik") or "", "od": od, "oncelik": _grup(t["puan"])})
        talepler += ctal
        puan = max((t["puan"] for t in ctal), default=0)
        gerek = [t["gerekce"] for t in ctal if t["puan"] == puan][:1]
        satirlar.append({
            "olcut": cid, "baslik": c.get("baslik") or "", "kapsam": kps, "od": od,
            "zincir": c.get("zincir_kisa") or "", "kanit_sayisi": len(adlar), "kanitlar": adlar,
            "eksik_halkalar": [HALKA_AD[h] for h in eksik_next], "sonraki_od": nxt, "gereken": gereken,
            "karsiliksiz": [f"{it['kanit_adi']} ({(matches.get(it['id']) or {}).get('durum')})" for it in karsiliksiz],
            "kimden": list(dict.fromkeys(t["kimden"] for t in ctal)),
            "oncelik": _grup(puan) if ctal else "—", "puan": puan, "gerekce": gerek[0] if gerek else "",
            "tek_belge": tek,
        })
    talepler.sort(key=lambda t: (-t["puan"], id_key(t["olcut"]), t["halka"], t["istenecek"]))
    for i, t in enumerate(talepler, 1):
        t["sira"] = i
    return satirlar, talepler


# -- çıktılar -----------------------------------------------------------------------------------

T_COLS = [("sira", "Sıra", 6), ("puan", "Puan", 6), ("oncelik", "Öncelik", 24), ("olcut", "Ölçüt", 8),
          ("baslik", "Ölçüt başlığı", 30), ("od", "Önerilen OD", 8), ("hedef_od", "Hedef OD", 8),
          ("istenecek", "İstenecek kanıt", 60), ("yuvalar", "Kılavuz yuvaları", 60),
          ("belge_turu", "Belge türü", 18), ("kimden", "Kimden istenir", 30),
          ("ornek", "Geçen yılın örneği", 40), ("gerekce", "Gerekçe", 70)]
O_COLS = [("olcut", "Ölçüt", 8), ("baslik", "Başlık", 30), ("kapsam", "Kapsam", 12), ("od", "Önerilen OD", 8),
          ("zincir", "PUKÖ zinciri", 16), ("kanit_sayisi", "Mevcut kanıt sayısı", 8),
          ("kanitlar", "Mevcut kanıtlar", 50), ("eksik_halkalar", "Eksik halkalar (bir üst düzey)", 26),
          ("gereken", "Bir üst düzey için gereken", 80),
          ("karsiliksiz", "Geçen yılın karşılığı olmayan iyi kanıtları", 50),
          ("kimden", "Kimden istenir", 30), ("oncelik", "Öncelik", 22), ("puan", "Puan", 6),
          ("gerekce", "Gerekçe", 60)]
G_COLS = [("id", "No", 6), ("olcut", "Ölçüt", 8), ("yuva", "Yuva", 9), ("asama", "Aşama", 10),
          ("kanit_adi", "Geçen yılın kanıtı", 44), ("belge_turu", "Belge türü", 18), ("tarih", "Tarih", 11),
          ("tekrarlayan_ad", "Tekrarlayan tür", 24), ("kaynak", "Kaynak", 12), ("durum", "Durum", 14),
          ("karsilik_ad", "Bu yılki karşılık", 44), ("karsilik_tarih", "Karşılığın tarihi", 11),
          ("benzerlik", "Benzerlik", 9), ("olcute_eslesmis", "Bu ölçüte eşleşmiş mi", 16),
          ("gerekce", "Eşleştirme gerekçesi", 70)]
SHEETS = ("Öncelikli talepler", "Ölçüt özeti", "Geçen yıl karşılıkları", "Açıklama")
DURUM_AD = {VAR: "var", ESKI: "eski sürüm", YOK: "yok — istenmeli"}
ACIKLAMA = [
    "Kanıt ihtiyaç raporu (bidr ihtiyac). Hatırlatma ve öncelik aracıdır, kesin kontrol listesi değildir.",
    "Kaynak: çalışma alanının mevcut çıktıları (decisions, inceleme kararları, audit). Model çağrısı yok.",
    "Öncelik: kanıtsız ölçüt (100) > tek belgeyle OD artışı (80–84) > geçen yılın karşılığı olmayan iyi "
    "kanıtı (60; eski sürümü olan 58) > diğer (20).",
    "Geçen yıl karşılıkları: var = dönem içi (ya da dönemden bağımsız yapı belgesi) karşılık; eski sürüm = "
    "yalnız önceki dönemden; yok = aynı türden benzer belge yok, istenmeli. Eşleşme benzerliğe dayanır: "
    "'var' satırlarını gözle doğrulayın.",
    "Kimden istenir: bidr/data/ihtiyac_sorumlular.yaml (genel varsayılanlar; --sorumlular ile değiştirilir).",
    "Kapsam dışı (başka birimin doldurduğu) ölçütler listelenmez.",
]


def _cell(v):
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    return v


def write_xlsx(path: Path, talepler: list[dict], satirlar: list[dict], gecen: list[dict]) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="DDE7F0")
    for name, cols, rows in ((SHEETS[0], T_COLS, talepler), (SHEETS[1], O_COLS, satirlar),
                             (SHEETS[2], G_COLS, gecen)):
        sh = wb.create_sheet(name)
        sh.append([h for _, h, _ in cols])
        for i, (_, _, w) in enumerate(cols, 1):
            sh.column_dimensions[get_column_letter(i)].width = w
            c = sh.cell(row=1, column=i)
            c.font = Font(bold=True)
            c.fill = head_fill
            c.alignment = Alignment(wrap_text=True, vertical="top")
        for r in rows:
            sh.append([_cell(r.get(k)) for k, _, _ in cols])
        for row in sh.iter_rows(min_row=2):
            for c in row:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        sh.freeze_panes = "A2"
        if rows:
            sh.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"
    sh = wb.create_sheet(SHEETS[3])
    sh.column_dimensions["A"].width = 120
    for line in ACIKLAMA:
        sh.append([line])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def md_ozet(meta: dict, talepler: list[dict], satirlar: list[dict], gecen: list[dict], n: int = 15) -> str:
    from collections import Counter
    g = Counter(t["oncelik"] for t in talepler)
    d = Counter(x.get("durum") for x in gecen)
    kanitsiz = [s["olcut"] for s in satirlar if s["kanit_sayisi"] == 0]
    tek = [s["olcut"] for s in satirlar if s["tek_belge"] and s["kanit_sayisi"]]
    L = ["# Kanıt ihtiyaç raporu", "",
         f"Çalışma alanı: `{meta['calisma_alani']}` · dönem {meta.get('donem')} · üretim {meta['uretim']}",
         "", "Hatırlatma ve öncelik aracıdır, kesin kontrol listesi değildir. Ayrıntı: `ihtiyac.xlsx`.", "",
         "## Sayılar", "",
         f"- Listelenen ölçüt: {len(satirlar)} (kapsam dışı ölçütler hariç)",
         f"- Kanıtsız ölçüt: {len(kanitsiz)}" + (f" ({', '.join(kanitsiz)})" if kanitsiz else ""),
         f"- Tek belgeyle OD'si artacak ölçüt: {len(tek)}" + (f" ({', '.join(tek)})" if tek else ""),
         f"- Talep: {len(talepler)} — " + ", ".join(f"{k}: {v}" for k, v in g.most_common())]
    if meta.get("referans"):
        L.append(f"- Geçen yılın iyi kanıtı: {len(gecen)} — var {d.get(VAR, 0)}, eski sürüm {d.get(ESKI, 0)}, "
                 f"yok (istenmeli) {d.get(YOK, 0)}; dönemi doğrulanmalı {sum(1 for x in gecen if x.get('donem_dogrulanmali'))}")
    else:
        L.append("- Referans set verilmedi: geçen yıl karşılaştırması yapılmadı (`--referans`).")
    for u in meta.get("uyarilar") or []:
        L.append(f"- Uyarı: {u}")
    L += ["", f"## İlk {min(n, len(talepler))} talep", ""]
    for t in talepler[:n]:
        L.append(f"{t['sira']}. **{t['olcut']}** ({t['oncelik']}, puan {t['puan']}): {t['istenecek']} — "
                 f"kimden: {t['kimden']}. _{t['gerekce']}_")
    yok = [x for x in gecen if x.get("durum") in (YOK, ESKI)]
    if yok:
        L += ["", "## Geçen yılın karşılığı bulunmayan iyi kanıtları", ""]
        for x in yok[:30]:
            L.append(f"- {x['olcut']} · {x['kanit_adi']} ({DURUM_AD[x['durum']]})")
        if len(yok) > 30:
            L.append(f"- … ve {len(yok) - 30} öğe daha (xlsx)")
    return "\n".join(L) + "\n"


def run(ws_root: Path, *, referans: dict | None = None, out: Path | None = None, sorumlular=None,
        turler=None) -> dict:
    """Raporu üretir; {"paths", "talepler", "satirlar", "gecen", "meta"} döner."""
    from bidr.audit.run import FILES as AFILES
    from bidr.audit.run import build
    from bidr.criteria.slots import load_tags
    from bidr.render.kapsam import workspace_scope

    from .eslestir import eslestir_hepsi, load_target
    from .tablolar import Turler

    ws_root = Path(ws_root).expanduser().resolve()
    out = Path(out).expanduser().resolve() if out else ws_root
    turler = turler or Turler()
    sor = sorumlular or Sorumlular()
    a = build(ws_root)
    uy = list(a.uyarilar)
    criteria = a.criteria
    aj = ws_root / AFILES["json"]
    if aj.exists():
        js = json.loads(aj.read_text(encoding="utf-8"))
        if js.get("kararlar_sha") == a.decisions_sha and js.get("olcutler"):
            criteria = js["olcutler"]
        else:
            uy.append("audit-olcutler.json güncel değil (decisions.jsonl değişmiş): OD yeniden hesaplandı; "
                      "`bidr audit` çalıştırın")
    else:
        uy.append("audit-olcutler.json yok: OD yeniden hesaplandı")
    kapsam, kuy = workspace_scope(ws_root, a.cs)
    uy += kuy
    tags = load_tags(a.cs)
    items = (referans or {}).get("ogeler") or []
    items = [it for it in items if kapsam.get(it["olcut"], "bolum") != "baska_birim"]
    matches: dict[str, dict] = {}
    if items:
        h = load_target(ws_root, a, turler)
        for m in eslestir_hepsi({**referans, "ogeler": items}, h):
            matches[m["id"]] = m
    satirlar, talepler = olcut_satirlari(criteria, a.rows, kapsam, a.cs, tags, items, matches, sor)
    gecen = [{**it, "durum": "", **matches.get(it["id"], {})} for it in items]
    gecen.sort(key=lambda x: ({YOK: 0, ESKI: 1, VAR: 2}.get(x["durum"], 3), id_key(x["olcut"]), x["id"]))
    meta = {"calisma_alani": str(ws_root), "donem": a.donem,
            "uretim": datetime.now().isoformat(timespec="seconds"),
            "referans": bool(referans), "referans_kaynak": (referans or {}).get("kaynak_calisma_alani", ""),
            "uyarilar": uy}
    paths = {"xlsx": out / FILES["xlsx"], "md": out / FILES["md"]}
    gecen_x = [{**x, "durum": DURUM_AD.get(x["durum"], x["durum"])} for x in gecen]
    write_xlsx(paths["xlsx"], talepler, satirlar, gecen_x)
    paths["md"].write_text(md_ozet(meta, talepler, satirlar, gecen), encoding="utf-8")
    return {"paths": paths, "talepler": talepler, "satirlar": satirlar, "gecen": gecen, "meta": meta,
            "audit": a}
