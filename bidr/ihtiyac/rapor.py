"""Ölçüt satırları, talepler (öncelik + puan + gerekçe) ve çıktılar (ihtiyac.xlsx, ihtiyac.md).

Öncelik (yüksekten düşüğe):
  1. kanıtsız ölçüt                  (puan 100)
  2. tek belgeyle OD artışı           (puan 80–84; düşük OD'de biraz daha yüksek)
  3. karşılığı olmayan iyi kanıt      (puan 60; eski sürümü olan 58)
  4. kılavuz önerisi                  (puan 32–45: kabul edilmiş hiçbir kanıtın karşılamadığı "Örnek
                                       Kanıtlar" yuvası; bir üst düzeyin eksik halkası 45, daha üst
                                       düzeyin halkası 38, kanıtı olan halka 32)
  5. diğer (bir üst düzey için)       (puan 20)
Aynı öneri iki kaynaktan geliyorsa (eksik halka / geçen yıl talebinin yuvaları + karşılanmamış yuva)
tek satırda birleşir: satır en yüksek puanı alır, `kaynak` alanında bütün kaynaklar yazılır.
Kapsam dışı ölçütler (sorumlu birim kapsamı `baska_birim`) listelenmez.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import re

from bidr.audit.rules import GEREKEN, KISA, LEVELS, criterion_od
from bidr.criteria.model import id_key
from bidr.criteria.slots import STAGE_OD

from .eslestir import ESKI, VAR, YOK
from .referans import IYI_GUVEN, KABUL, ad_sozcukleri
from .tablolar import Sorumlular

P_KANITSIZ, P_TEK, P_REF, P_REF_ESKI, P_DIGER = 100, 80, 60, 58, 20
P_KLV_HALKA, P_KLV_UST, P_KLV_MEVCUT = 45, 38, 32     # kılavuz önerisi (karşılanmamış yuva)
GRUP = {P_KANITSIZ: "kanıtsız ölçüt", P_TEK: "tek belgeyle OD artışı", P_REF: "karşılığı olmayan iyi kanıt",
        P_KLV_HALKA: "kılavuz önerisi", P_DIGER: "diğer"}
K_KANITSIZ, K_OD, K_REF, K_KLV = "kanıtsız", "OD artışı", "geçen yıl", "kılavuz"
KAYNAKLAR = (K_KANITSIZ, K_OD, K_REF, K_KLV)
RUBRIK_N = 160          # gerekçeye eklenen rubrik tanımı en çok bu kadar karakter
ACIKLAMA_MIN = 2        # açıklama cümlesi için en az ortak sözcük kökü
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
    if puan >= P_KLV_MEVCUT:
        return GRUP[P_KLV_HALKA]
    return GRUP[P_DIGER]


def karsilar(r: dict) -> bool:
    """Satır yuvasını karşılayan kabul edilmiş kanıt mı: sayılan, reddedilmemiş; güveni orta/yüksek ya
    da incelemede kabul/düzelt edilmiş (insan kararı düşük güveni aşar; audit ve referans setle aynı)."""
    return (bool(r.get("sayilir")) and r.get("karar") != "ret"
            and (r.get("guven") in IYI_GUVEN or r.get("karar") in KABUL))


def kisalt(s: str, n: int = RUBRIK_N) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "…"


def rubrik(cs, cid: str, od: int | None) -> str:
    """Kılavuzdaki olgunluk düzeyi tanımı (kısaltılmış; uydurma yok, yoksa boş)."""
    if not od:
        return ""
    try:
        return kisalt(cs.get(cid).rubric.get(od) or "")
    except KeyError:
        return ""


def _kok(s: str) -> set[str]:
    return {w[:5] for w in ad_sozcukleri(s) if len(w) >= 4}


def aciklama_cumlesi(cs, cid: str, metin: str) -> str:
    """Ölçüt açıklamasından (kılavuz `description`) metinle en çok ortak sözcük kökü olan cümle
    (en az ACIKLAMA_MIN kök); yoksa boş."""
    try:
        paras = cs.get(cid).description
    except KeyError:
        return ""
    k = _kok(metin)
    best, n = "", ACIKLAMA_MIN - 1
    for p in paras:
        for c in re.split(r"(?<=[.;])\s+", p):
            m = len(k & _kok(c))
            if m > n:
                best, n = c.strip(), m
    return kisalt(best, 200)


def _rubrik_ek(cs, cid: str, od: int | None) -> str:
    r = rubrik(cs, cid, od)
    return f" · OD{od} tanımı (kılavuz): «{r}»" if r else ""


def _yuvalar(cs, cid: str) -> list:
    try:
        return [s for s in cs.get(cid).slots if not s.footnote]
    except KeyError:
        return []


def yuva_metinleri(cs, tags, cid: str, halka: str) -> list[str]:
    """Kılavuzda ölçütün bu aşamaya etiketli yuvaları (`A.1.1/3: metin`)."""
    out = []
    for s in _yuvalar(cs, cid):
        t = tags.get(s.id)
        if t is not None and halka in t.stages:
            out.append(f"{s.id}: {s.text}")
    return out


def _yuva_idleri(yuvalar: str) -> set[str]:
    """Talebin `yuvalar` alanındaki yuva kimlikleri (`A.1.1/3: metin | …` ya da `A.1.1/2, A.1.1/3`)."""
    return set(re.findall(r"\b[A-E]\.\d+\.\d+/\d+\b", yuvalar or ""))


def kilavuz_onerileri(cs, tags, cid: str, rows: list[dict], od: int, present: set[str],
                      eksik_next: list[str], nxt: int | None, sor: Sorumlular) -> list[dict]:
    """Kabul edilmiş hiçbir kanıtın karşılamadığı "Örnek Kanıtlar" yuvaları (dipnotlar hariç)."""
    dolu = {r["yuva"] for r in rows if r.get("olcut") == cid and karsilar(r)}
    out = []
    for s in _yuvalar(cs, cid):
        if s.id in dolu:
            continue
        t = tags.get(s.id)
        st = [h for h in (t.stages if t is not None else ()) if h in HALKA_AD]
        if any(h in eksik_next for h in st):
            puan, hedef = P_KLV_HALKA, nxt
        elif any(h not in present for h in st):
            puan, hedef = P_KLV_UST, None
        else:
            puan, hedef = P_KLV_MEVCUT, None
        eksik = [h for h in st if h not in present]
        h0 = ([h for h in st if h in eksik_next] or eksik or st or [""])[0]
        duzey = nxt if puan == P_KLV_HALKA else min((STAGE_OD[h] for h in (eksik or st)), default=None)
        if puan == P_KLV_HALKA:
            neden = f"karşılanmamış kılavuz yuvası; OD{nxt} için eksik {HALKA_AD[h0]} halkası"
        elif puan == P_KLV_UST:
            neden = f"karşılanmamış kılavuz yuvası; daha üst düzeyin ({HALKA_AD[h0]}, OD{duzey}) halkası"
        else:
            neden = ("karşılanmamış kılavuz yuvası; halkada kanıt var, yuva boş"
                     if st else "karşılanmamış kılavuz yuvası (PUKÖ etiketi yok)")
        out.append({"puan": puan, "halka": ",".join(st), "hedef_od": hedef, "istenecek": s.text,
                    "yuvalar": s.id, "belge_turu": "",
                    "kimden": sor.kim(asama=h0 or None, olcut=cid), "ornek": "",
                    "gerekce": neden + (_rubrik_ek(cs, cid, duzey) if puan != P_KLV_MEVCUT else ""),
                    "kaynak": K_KLV})
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
                         "kimden": sor.kim(asama=h, olcut=cid), "ornek": ornek(h),
                         "gerekce": neden + _rubrik_ek(cs, cid, yeni),
                         "kaynak": K_KANITSIZ if kanitsiz else K_OD})
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
                                     + "; " + (m.get("gerekce") or "")),
                         "kaynak": K_REF})
        if not ctal and nxt:
            ys = []
            for h in eksik_next:
                ys += yuva_metinleri(cs, tags, cid, h)
            ys = list(dict.fromkeys(ys))                  # birden çok halkaya etiketli yuva bir kez
            ctal.append({"puan": P_DIGER, "halka": ",".join(eksik_next), "hedef_od": nxt,
                         "istenecek": "; ".join(f"{HALKA_AD[h]} kanıtı" for h in eksik_next) or "—",
                         "yuvalar": " | ".join(ys), "belge_turu": "",
                         "kimden": "; ".join(dict.fromkeys(sor.kim(asama=h, olcut=cid) for h in eksik_next))
                                   or sor.kim(olcut=cid),
                         "ornek": "",
                         "gerekce": f"OD{nxt} için {len(eksik_next)} halka birlikte gerekli "
                                    f"({', '.join(HALKA_AD[h] for h in eksik_next)})" + _rubrik_ek(cs, cid, nxt),
                         "kaynak": K_OD})
        # kılavuz önerileri: aynı yuva zaten bir talepte istenmişse o satıra kaynak olarak birleşir
        klv = kilavuz_onerileri(cs, tags, cid, rows, od, present, eksik_next, nxt, sor)
        for k in klv:
            sahip = [t for t in ctal if k["yuvalar"] in _yuva_idleri(t["yuvalar"])]
            if not sahip:
                ctal.append(k)
                continue
            for t in sahip:
                if K_KLV not in t["kaynak"].split(" + "):
                    t["kaynak"] += " + " + K_KLV
                if k["puan"] > t["puan"]:
                    t["puan"] = k["puan"]
                    if t["hedef_od"] is None:
                        t["hedef_od"] = k["hedef_od"]
        for t in ctal:
            ac = aciklama_cumlesi(cs, cid, t["istenecek"] + " " + t["yuvalar"]) if t["yuvalar"] else ""
            t.update({"olcut": cid, "baslik": c.get("baslik") or "", "od": od, "oncelik": _grup(t["puan"]),
                      "halka_ad": ", ".join(HALKA_AD[h] for h in t["halka"].split(",") if h in HALKA_AD),
                      "aciklama": ac})
        talepler += ctal
        puan = max((t["puan"] for t in ctal), default=0)
        gerek = [t["gerekce"] for t in ctal if t["puan"] == puan][:1]
        satirlar.append({
            "olcut": cid, "baslik": c.get("baslik") or "", "kapsam": kps, "od": od,
            "zincir": c.get("zincir_kisa") or "", "kanit_sayisi": len(adlar), "kanitlar": adlar,
            "eksik_halkalar": [HALKA_AD[h] for h in eksik_next], "eksik_kod": eksik_next,
            "sonraki_od": nxt, "gereken": gereken,
            "karsiliksiz": [f"{it['kanit_adi']} ({(matches.get(it['id']) or {}).get('durum')})" for it in karsiliksiz],
            "kimden": list(dict.fromkeys(t["kimden"] for t in ctal)),
            "oncelik": _grup(puan) if ctal else "—", "puan": puan, "gerekce": gerek[0] if gerek else "",
            "tek_belge": tek,
            "karsilanmamis_yuvalar": [k["yuvalar"] for k in klv],
            "sonraki_od_tanimi": rubrik(cs, cid, nxt),
        })
    talepler.sort(key=lambda t: (-t["puan"], id_key(t["olcut"]), t["halka"], t["istenecek"]))
    for i, t in enumerate(talepler, 1):
        t["sira"] = i
    return satirlar, talepler


# -- çıktılar -----------------------------------------------------------------------------------

T_COLS = [("sira", "Sıra", 6), ("puan", "Puan", 6), ("oncelik", "Öncelik", 24),
          ("kaynak", "Kaynak", 22), ("olcut", "Ölçüt", 8),
          ("baslik", "Ölçüt başlığı", 30), ("od", "Önerilen OD", 8), ("hedef_od", "Hedef OD", 8),
          ("halka_ad", "PUKÖ halkası", 16),
          ("istenecek", "İstenecek kanıt", 60), ("yuvalar", "Kılavuz yuvaları", 60),
          ("belge_turu", "Belge türü", 18), ("kimden", "Kimden istenir", 30),
          ("ornek", "Geçen yılın örneği", 40), ("gerekce", "Gerekçe", 70),
          ("aciklama", "Ölçüt açıklamasından (kılavuz)", 60)]
O_COLS = [("olcut", "Ölçüt", 8), ("baslik", "Başlık", 30), ("kapsam", "Kapsam", 12), ("od", "Önerilen OD", 8),
          ("zincir", "PUKÖ zinciri", 16), ("kanit_sayisi", "Mevcut kanıt sayısı", 8),
          ("kanitlar", "Mevcut kanıtlar", 50), ("eksik_halkalar", "Eksik halkalar (bir üst düzey)", 26),
          ("gereken", "Bir üst düzey için gereken", 80),
          ("karsiliksiz", "Geçen yılın karşılığı olmayan iyi kanıtları", 50),
          ("karsilanmamis_yuvalar", "Karşılanmamış kılavuz yuvaları", 24),
          ("sonraki_od_tanimi", "Bir üst düzeyin tanımı (kılavuz)", 60),
          ("kimden", "Kimden istenir", 30), ("oncelik", "Öncelik", 22), ("puan", "Puan", 6),
          ("gerekce", "Gerekçe", 60)]
G_COLS = [("id", "No", 6), ("olcut", "Ölçüt", 8), ("yuva", "Yuva", 9), ("asama", "Aşama", 10),
          ("kanit_adi", "Geçen yılın kanıtı", 44), ("belge_turu", "Belge türü", 18), ("tarih", "Tarih", 11),
          ("tekrarlayan_ad", "Tekrarlayan tür", 24), ("kaynak", "Kaynak", 12), ("durum", "Durum", 14),
          ("karsilik_ad", "Bu yılki karşılık", 44), ("karsilik_tarih", "Karşılığın tarihi", 11),
          ("benzerlik", "Benzerlik", 9), ("olcute_eslesmis", "Bu ölçüte eşleşmiş mi", 16),
          ("gerekce", "Eşleştirme gerekçesi", 70)]
SHEETS = ("Öncelikli talepler", "Ölçüt özeti", "Geçen yıl karşılıkları", "Açıklama", "Kılavuz eki örnekleri")
E_COLS = [("id", "Satır", 7), ("uygulama", "Uygulama (kılavuz eki)", 60), ("kanit", "Kanıt (kılavuz eki)", 40),
          ("olcutler", "Eşlenen alt ölçüt", 14), ("yuvalar", "Kılavuz yuvaları", 18),
          ("acik", "Karşılanmamış yuvası", 18), ("belirsiz", "Eşleme belirsiz", 9),
          ("sade", "istenen-kanitlar.xlsx", 24)]
DURUM_AD = {VAR: "var", ESKI: "eski sürüm", YOK: "yok — istenmeli"}
ACIKLAMA = [
    "Kanıt ihtiyaç raporu (bidr ihtiyac). Hatırlatma ve öncelik aracıdır, kesin kontrol listesi değildir.",
    "Kaynak: çalışma alanının mevcut çıktıları (decisions, inceleme kararları, audit). Model çağrısı yok.",
    "Öncelik: kanıtsız ölçüt (100) > tek belgeyle OD artışı (80–84) > geçen yılın karşılığı olmayan iyi "
    "kanıtı (60; eski sürümü olan 58) > kılavuz önerisi (32–45) > diğer (20).",
    "Kılavuz önerisi: boş FR-0833 şablonundaki 'Örnek Kanıtlar' yuvalarından, kabul edilmiş (sayılan, "
    "reddedilmemiş; güveni orta/yüksek ya da incelemede kabul edilmiş) hiçbir kanıtın karşılamadığı yuva. "
    "Bir üst düzeyin eksik halkası 45, daha üst düzeyin halkası 38, kanıtı olan halkanın boş yuvası 32. "
    "Referans set verilmese de üretilir.",
    "Kaynak sütunu: kanıtsız / OD artışı / geçen yıl / kılavuz. Aynı öneri birden çok kaynaktan geliyorsa "
    "tek satırdır (en yüksek puan; kaynaklar '+' ile).",
    "Gerekçedeki 'OD n tanımı' ve 'Ölçüt açıklamasından' sütunu kılavuz metnidir (kısaltılmış); "
    "açıklama cümlesi sözcük örtüşmesiyle seçilir, ipucudur.",
    "Geçen yıl karşılıkları: var = dönem içi (ya da dönemden bağımsız yapı belgesi) karşılık; eski sürüm = "
    "yalnız önceki dönemden; yok = aynı türden benzer belge yok, istenmeli. Eşleşme benzerliğe dayanır: "
    "'var' satırlarını gözle doğrulayın.",
    "Kimden istenir: bidr/data/ihtiyac_sorumlular.yaml (genel varsayılanlar; --sorumlular ile değiştirilir).",
    "Kapsam dışı (başka birimin doldurduğu) ölçütler listelenmez.",
    "Kılavuz eki örnekleri: boş FR-0833 şablonunun sonundaki 'Örnek Uygulama ve Kanıtlar Listesi' satırları "
    "(alan düzeyinde; alt ölçüt eşlemesi elle: bidr/data/ihtiyac_ornek_uygulama.yaml). Satır, eşlendiği "
    "yuvalardan biri karşılanmamışsa sade listeye öneri olur (madde başına en çok 3, önceki maddelerle "
    "örtüşmeyen); son sütun satırın bu çalışmada nerede kaldığını gösterir.",
]


def _cell(v):
    if isinstance(v, list):
        return "\n".join(str(x) for x in v)
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    return v


def ornek_satirlari(ornekler: list[dict], satirlar: list[dict], sade_rows: list[dict]) -> list[dict]:
    """Kılavuz eki örnek uygulamalarının bu çalışma alanındaki durumu (teknik liste)."""
    acik = {s["olcut"]: set(s.get("karsilanmamis_yuvalar") or []) for s in satirlar}
    listede: dict[str, list[str]] = {}
    for r in sade_rows:
        for i in r.get("ornek_idler") or []:
            listede.setdefault(i, []).append(r["olcut"])
    out = []
    for o in ornekler:
        a = [y for y in o["yuvalar"] if y in acik.get(y.split("/")[0], set())]
        sd = ("listede (" + ", ".join(listede[o["id"]]) + ")" if o["id"] in listede
              else "kurum düzeyi: sade listeye girmez" if not o["sade"]
              else "yuvası karşılanmış (ya da madde listede yok)" if not a else "sınır ya da örtüşme nedeniyle yazılmadı")
        out.append({"id": o["id"], "uygulama": o["uygulama"], "kanit": o["kanit"],
                    "olcutler": ", ".join(o["olcutler"]), "yuvalar": ", ".join(o["yuvalar"]),
                    "acik": ", ".join(a), "belirsiz": "evet" if o["belirsiz"] else "", "sade": sd})
    return out


def write_xlsx(path: Path, talepler: list[dict], satirlar: list[dict], gecen: list[dict],
               ornek: list[dict] | None = None) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    head_fill = PatternFill("solid", fgColor="DDE7F0")
    sayfalar = [(SHEETS[0], T_COLS, talepler), (SHEETS[1], O_COLS, satirlar), (SHEETS[2], G_COLS, gecen)]
    if ornek:
        sayfalar.append((SHEETS[4], E_COLS, ornek))
    for name, cols, rows in sayfalar:
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
    kc = Counter(k for t in talepler for k in t.get("kaynak", "").split(" + ") if k)
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
         f"- Talep: {len(talepler)} — " + ", ".join(f"{k}: {v}" for k, v in g.most_common()),
         "- Kaynağa göre (birleşen satır her kaynağında sayılır): "
         + ", ".join(f"{k}: {kc.get(k, 0)}" for k in KAYNAKLAR)]
    if meta.get("referans"):
        L.append(f"- Geçen yılın iyi kanıtı: {len(gecen)} — var {d.get(VAR, 0)}, eski sürüm {d.get(ESKI, 0)}, "
                 f"yok (istenmeli) {d.get(YOK, 0)}; dönemi doğrulanmalı {sum(1 for x in gecen if x.get('donem_dogrulanmali'))}")
    else:
        L.append("- Referans set verilmedi: geçen yıl karşılaştırması yapılmadı (`--referans`).")
    for u in meta.get("uyarilar") or []:
        L.append(f"- Uyarı: {u}")
    L += ["", f"## İlk {min(n, len(talepler))} talep", ""]
    for t in talepler[:n]:
        L.append(f"{t['sira']}. **{t['olcut']}** ({t['oncelik']}, puan {t['puan']}; kaynak: {t.get('kaynak', '')}): "
                 f"{t['istenecek']} — kimden: {t['kimden']}. _{t['gerekce']}_")
    klv = [t for t in talepler if t.get("kaynak") == K_KLV]
    if klv:
        by: dict[str, list[dict]] = {}
        for t in klv:
            by.setdefault(t["olcut"], []).append(t)
        L += ["", "## Kılavuz önerileri (karşılanmamış örnek kanıt yuvaları)", "",
              f"{len(klv)} yuva, {len(by)} ölçüt; başka kaynakla birleşenler yukarıdaki satırlardadır. "
              "Metinler `ihtiyac.xlsx`'te.", ""]
        for cid in sorted(by, key=id_key):
            xs = sorted(by[cid], key=lambda t: (-t["puan"], t["yuvalar"]))
            L.append(f"- **{cid}**: " + "; ".join(
                f"{t['yuvalar']} ({t['halka_ad'] or '?'}, {t['puan']})" for t in xs))
    yok = [x for x in gecen if x.get("durum") in (YOK, ESKI)]
    if yok:
        L += ["", "## Geçen yılın karşılığı bulunmayan iyi kanıtları", ""]
        for x in yok[:30]:
            L.append(f"- {x['olcut']} · {x['kanit_adi']} ({DURUM_AD[x['durum']]})")
        if len(yok) > 30:
            L.append(f"- … ve {len(yok) - 30} öğe daha (xlsx)")
    return "\n".join(L) + "\n"


def run(ws_root: Path, *, referans: dict | None = None, out: Path | None = None, sorumlular=None,
        turler=None, istekler: list[dict] | None = None, somut=None, oneriler: list[dict] | None = None,
        kurum: dict | None = None, ornekler: list[dict] | None = None) -> dict:
    """Raporu üretir; {"paths", "talepler", "satirlar", "gecen", "meta", "sade"} döner. `istekler`:
    elle istekler (`sade.istekler_oku`); `somut`/`oneriler`: sade liste tabloları (vars. bidr/data);
    `kurum`: kurum belge kataloğu eşlemesi (`kurum-katalog-esleme.json`, bkz. katalog_esle)."""
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
    from . import sade
    ornekler = ornekler if ornekler is not None else sade.ornekler_yukle()
    sade_rows = sade.satirlar_kur(a.cs, tags, sor, talepler, satirlar, gecen, yil=a.donem,
                                  ref_yil=(referans or {}).get("donem"), istekler=istekler, somut=somut,
                                  oneriler=oneriler, kurum=kurum, ornekler=ornekler)
    write_xlsx(paths["xlsx"], talepler, satirlar, gecen_x, ornek_satirlari(ornekler, satirlar, sade_rows))
    paths["md"].write_text(md_ozet(meta, talepler, satirlar, gecen), encoding="utf-8")
    paths["sade"] = sade.write_xlsx(out / sade.FILE, sade_rows,
                                    baslik=f"İstenen kanıtlar ({a.donem})" if a.donem else "İstenen kanıtlar")
    return {"paths": paths, "talepler": talepler, "satirlar": satirlar, "gecen": gecen, "meta": meta,
            "audit": a, "sade": sade_rows}
