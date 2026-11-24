"""Etkinlik istekleri (eksik listesi): faaliyet kayıtlarından (bidr/faaliyet; etkinlik dosyası) adıyla.

Yalnız **gerçek etkinlikler** (`etkinlik_mi`: adı seminer, konferans, kongre, sempozyum, çalıştay, staj programı,
tanıtım/tercih günü, kulüp etkinliği, şenlik, festival, söyleşi, konuşma/buluşma dizisi, panel; toplantı, kurul,
komisyon, protokol, anlaşma, imza, seçim, başvuru, sınav/mülakat gibi yönetim süreçleri ve dış etkinliğe
katılım DEĞİL) ve yalnız **bölümün** etkinlikleri (belgelerinden en az biri `birim_iliskisi: kendi`; kurum/
fakülte geneli etkinlik bölümden istenmez). Madde başına en çok iki satır:

- Gerçekleşme: planlaması kanıtlı (afiş/duyuru/plan) ama gerçekleşmesi kanıtlanmamış etkinlikler:
  «<ad> (<tarih>)» etkinliğinin (birden çoksa "şu etkinliklerin: «…», «…»") gerçekleştiğini gösteren fotoğraf,
  haber, sosyal medya paylaşımı ya da katılım listesi.
- Değerlendirme: gerçekleşmiş ama değerlendirmesi olmayan etkinlikler, yalnız ölçütü bir üst düzeyde OD4'e
  adaysa (şu an OD3); birleşik tek satır.
- Bağlamsız fotoğraf (faaliyet adı yok, aynı klasör/ad serisinde etkinlik belgesi yok; sahnesi mekân
  değil): "bu fotoğraf hangi etkinliğe ait?" — Belgeler sayfasında belge notu.

İstek etkinliğin belgelerinin (incelemede reddedilmemiş) ölçütlerinden ilkine yazılır; ölçütü yoksa ya da
kapsam dışıysa "Genel". Model yok; çalışma alanı salt okunur.
"""
from __future__ import annotations

import re
from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key

GERCEKLESME = ("«{ad}» etkinliğinin gerçekleştiğini gösteren fotoğraf, haber, sosyal medya paylaşımı ya da "
               "katılım listesi")
GERCEKLESME_COK = ("Şu etkinliklerin gerçekleştiğini gösteren fotoğraf, haber, sosyal medya paylaşımı ya da "
                   "katılım listesi: {adlar}")
DEGERLENDIRME = ("«{ad}» etkinliğinin değerlendirmesi: katılımcı geri bildirimi, değerlendirme toplantısı "
                 "tutanağı ya da sonraki dönem için alınan karar")
DEGERLENDIRME_COK = ("Şu etkinliklerin değerlendirmesi (katılımcı geri bildirimi, değerlendirme toplantısı "
                     "tutanağı ya da sonraki dönem için alınan karar): {adlar}")
# Etkinlik adı (katlanmış) — gerçek etkinlik türleri ve dışarıda kalan yönetim süreçleri
ETKINLIK_TURU = re.compile(r"semine|seminar|kolokyum|colloqui|konferans|conference|kongre|congress|sempozyum|"
                           r"symposium|calistay|workshop|\bstaj|tanitim gun|tercih gun|tercih fuar|kulub|kulup|"
                           r"senli[kg]|festival|soylesi|konusmalar|bulusma|panel|yaz okulu|kis okulu|olimpiyat|yarisma")
ETKINLIK_DEGIL = re.compile(r"toplanti|kurul|komisyon|protokol|anlasma|imza|secim|basvuru|mulakat|sinav|cagri|katilim|"
                            r"degerlendirme toplant|yonetim|gozden gecir")
FOTOGRAF = "Bu fotoğraf hangi etkinliğe ait? Belgeler sayfasında belge notu yazın: {yol}"
FOTOGRAF_EN_COK = 15
PLANLAMA = frozenset({"duyuru", "plan", "duzenleme"})
GENEL = "Genel"


def etkinlik_adi(k: dict) -> str:
    t = k.get("tarih") or ((k.get("tarih_araligi") or [None])[0])
    return f"{k['ad']} ({t})" if t else k["ad"]


def etkinlik_mi(ad: str) -> bool:
    """Adı gerçek bir etkinlik türü mü (bkz. modül belgesi)."""
    from bidr.faaliyet.group import fold
    t = fold(ad)
    return bool(ETKINLIK_TURU.search(t)) and not ETKINLIK_DEGIL.search(t)


def bolumun(k: dict) -> bool:
    """Etkinlik bölümün mü (belgelerinden en az biri `birim_iliskisi: kendi`)."""
    return any(b.get("birim_iliskisi") == "kendi" for b in k.get("belgeler") or [])


def _olcut(k: dict, rows_by_doc: dict[str, list[dict]], satirlar: dict[str, dict]) -> str:
    cs = set()
    for b in k.get("belgeler") or []:
        rs = rows_by_doc.get(b["doc_id"])
        if rs is not None:
            cs |= {r["olcut"] for r in rs if r.get("karar") != "ret"}
        else:
            cs |= {m["olcut"] for m in b.get("eslesmeler") or [] if m.get("olcut")}
    cs = [c for c in cs if c in satirlar]
    return min(cs, key=id_key) if cs else GENEL


def _sahne_mekan(text: str) -> bool:
    from bidr.audit.savunma import sahne
    return sahne("", text) == "mekan"


def etkinlik_istekleri(ws_root: Path, audit, satirlar: list[dict], sor) -> list[dict]:
    """[{olcut, metin, kimden, tur: "etkinlik", oncelik, dosyada}] (bkz. modül belgesi)."""
    from bidr.faaliyet import run as F
    from .sade import ORTA
    ws = Workspace(Path(ws_root))
    if not (ws.root / F.DECISIONS).exists():
        return []
    data = F.build_ws(ws)
    sat = {s["olcut"]: s for s in satirlar}
    rows_by_doc: dict[str, list[dict]] = {}
    for r in audit.rows:
        rows_by_doc.setdefault(r["doc_id"], []).append(r)
    kim = sor.kim(belge_turu="etkinlik_duyurusu")
    out = []
    ger: dict[str, list[tuple[str, str]]] = {}          # ölçüt → [(etkinlik adı, belgeleri)]
    deg: dict[str, list[tuple[str, str]]] = {}
    for k in data["faaliyetler"]:
        if not etkinlik_mi(k["ad"]) or not bolumun(k):
            continue
        asm = set(k.get("asamalar") or {})
        cid = _olcut(k, rows_by_doc, sat)
        belgeler = "; ".join(dict.fromkeys(b.get("kanit_adi") or b["ad"] for b in k["belgeler"]))
        if k["durum"] == "gerceklesme_kanitsiz" and asm & PLANLAMA:
            ger.setdefault(cid, []).append((etkinlik_adi(k), belgeler))
        elif k["durum"] != "gerceklesme_kanitsiz" and "degerlendirme" not in asm and cid in sat \
                and int(sat[cid].get("od") or 0) == 3 and sat[cid].get("sonraki_od") == 4:
            deg.setdefault(cid, []).append((etkinlik_adi(k), belgeler))
    for by, tek, cok, etiket in ((ger, GERCEKLESME, GERCEKLESME_COK, "planlama"),
                                 (deg, DEGERLENDIRME, DEGERLENDIRME_COK, "gerçekleşme")):
        for cid, xs in by.items():
            xs = list(dict.fromkeys(xs))
            metin = tek.format(ad=xs[0][0]) if len(xs) == 1 else cok.format(adlar=", ".join(f"«{a}»" for a, _ in xs))
            dosyada = (f"{etiket}: {xs[0][1]}" if len(xs) == 1
                       else f"{etiket}: " + " · ".join(f"{a}: {b}" for a, b in xs))
            out.append({"olcut": cid, "metin": metin, "kimden": kim, "tur": "etkinlik", "oncelik": ORTA,
                        "dosyada": dosyada})
    fotolar = []
    for x in data.get("baglamsiz_fotograflar") or []:
        p = ws.text_path(x["doc_id"])
        if p.exists() and _sahne_mekan(p.read_text(encoding="utf-8", errors="replace")):
            continue                        # mekân/altyapı fotoğrafı: etkinlik sorulmaz
        fotolar.append(x)
    for x in fotolar[:FOTOGRAF_EN_COK]:
        out.append({"olcut": GENEL, "metin": FOTOGRAF.format(yol=x["yol"] or x["doc_id"]), "kimden": kim,
                    "tur": "etkinlik", "oncelik": ORTA, "dosyada": ""})
    if len(fotolar) > FOTOGRAF_EN_COK:
        out.append({"olcut": GENEL, "kimden": kim, "tur": "etkinlik", "oncelik": ORTA, "dosyada": "",
                    "metin": f"… ve etkinliği belirlenemeyen {len(fotolar) - FOTOGRAF_EN_COK} fotoğraf daha: "
                             "Belgeler sayfasında belge notu yazın"})
    return out
