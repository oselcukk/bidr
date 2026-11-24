"""Etkinlik istekleri (eksik listesi): faaliyet kayıtlarından (bidr/faaliyet; etkinlik dosyası) adıyla.

- Planlaması kanıtlı (afiş/duyuru/plan) ama gerçekleşmesi kanıtlanmamış her etkinlik için:
  «<ad> (<tarih>)» etkinliğinin gerçekleştiğini gösteren fotoğraf, haber, sosyal medya paylaşımı ya da
  katılım listesi.
- Gerçekleşmiş ama değerlendirmesi olmayan etkinlik, ölçütü bir üst düzeyde OD4'e adaysa (şu an OD3):
  değerlendirme / geri bildirim / sonraki dönem için alınan karar.
- Bağlamsız fotoğraf (faaliyet adı yok, aynı klasör/ad serisinde etkinlik belgesi yok; sahnesi mekân
  değil): "bu fotoğraf hangi etkinliğe ait?" — Belgeler sayfasında belge notu.

İstek etkinliğin belgelerinin (incelemede reddedilmemiş) ölçütlerinden ilkine yazılır; ölçütü yoksa ya da
kapsam dışıysa "Genel". Model yok; çalışma alanı salt okunur.
"""
from __future__ import annotations

from pathlib import Path

from bidr.common import Workspace
from bidr.criteria.model import id_key

GERCEKLESME = ("«{ad}» etkinliğinin gerçekleştiğini gösteren fotoğraf, haber, sosyal medya paylaşımı ya da "
               "katılım listesi")
DEGERLENDIRME = ("«{ad}» etkinliğinin değerlendirmesi: katılımcı geri bildirimi, değerlendirme toplantısı "
                 "tutanağı ya da sonraki dönem için alınan karar")
FOTOGRAF = "Bu fotoğraf hangi etkinliğe ait? Belgeler sayfasında belge notu yazın: {yol}"
FOTOGRAF_EN_COK = 15
PLANLAMA = frozenset({"duyuru", "plan", "duzenleme"})
GENEL = "Genel"


def etkinlik_adi(k: dict) -> str:
    t = k.get("tarih") or ((k.get("tarih_araligi") or [None])[0])
    return f"{k['ad']} ({t})" if t else k["ad"]


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
    for k in data["faaliyetler"]:
        asm = set(k.get("asamalar") or {})
        cid = _olcut(k, rows_by_doc, sat)
        adi = etkinlik_adi(k)
        belgeler = "; ".join(dict.fromkeys(b.get("kanit_adi") or b["ad"] for b in k["belgeler"]))
        if k["durum"] == "gerceklesme_kanitsiz" and asm & PLANLAMA:
            out.append({"olcut": cid, "metin": GERCEKLESME.format(ad=adi), "kimden": kim, "tur": "etkinlik",
                        "oncelik": ORTA, "dosyada": f"planlama: {belgeler}"})
        elif k["durum"] != "gerceklesme_kanitsiz" and "degerlendirme" not in asm and cid in sat \
                and int(sat[cid].get("od") or 0) == 3 and sat[cid].get("sonraki_od") == 4:
            out.append({"olcut": cid, "metin": DEGERLENDIRME.format(ad=adi), "kimden": kim, "tur": "etkinlik",
                        "oncelik": ORTA, "dosyada": f"gerçekleşme: {belgeler}"})
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
