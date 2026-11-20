"""Referans set: önceki (bitmiş) çalışma alanının "iyi kanıt"ları + elle eklenen öğeler.

İyi kanıt = incelemede kabul (ya da düzeltilerek kabul) edilmiş, güveni orta/yüksek, önerilen OD'ye
katkısı olan (sayılan) eşleşme. Satırlar `bidr.audit.run.build` ile salt okunur kurulur (audit'in
kuralları: dönem, birim aitliği, kurum geneli tavanı aynen geçerli).

Referans dosyası (JSON) kendi başına yeterlidir: önceki çalışma alanı sonradan silinse de eşleştirme
yapılabilsin diye her belge için anahtar sözcükler ve örneklenmiş içerik parmak izi (karma sayılar,
metin değil) saklanır.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from bidr.common import Workspace, read_jsonl
from bidr.identify.versions import _vectors, fingerprint

from .tablolar import Turler, norm

SURUM = 1
KABUL = ("kabul", "duzelt")
IYI_GUVEN = ("orta", "yuksek")
ANAHTAR_N = 12          # belge başına anahtar sözcük
ORNEK = 16              # parmak izi örneklemesi: karma % ORNEK == 0
BAS = 1500              # tekrarlayan tür deseni için baş bölge
_SOZ = re.compile(r"[a-z]{3,}")
# ad/başlık eşleştirmesinde ayırt edici olmayan sözcükler (katlanmış yazım)
DURAK = frozenset("""ve ile icin olan olarak gibi daha bir bu her tum ilgili hakkinda uzerine ait
iliskin dair yili yillik donem donemi akademik egitim ogretim bolum bolumu bolumun universite
universitesi universitemiz fakulte fakultesi teknik belge belgesi listesi liste sayfasi sayfa
the and for of""".split())


def ad_sozcukleri(*parts: str | None) -> list[str]:
    """Ad/başlıktan ayırt edici sözcükler (sıralı, tekrarsız)."""
    out: list[str] = []
    for p in parts:
        for w in _SOZ.findall(norm(p)):
            if w not in DURAK and w not in out:
                out.append(w)
    return out


def _text(ws: Workspace, did: str) -> str:
    p = ws.text_path(did)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def anahtar_sozcukler(texts: dict[str, str], n: int = ANAHTAR_N) -> dict[str, list[str]]:
    """Belge başına TF-IDF'te en ağır n sözcük (bidr.identify.versions TF-IDF'i; 4+ harf)."""
    vecs = _vectors({k: norm(t) for k, t in texts.items()})
    out = {}
    for k, v in vecs.items():
        ws_ = sorted(((x, w) for w, x in v.items() if len(w) >= 4 and w not in DURAK), reverse=True)
        out[k] = [w for _, w in ws_[:n]]
    return out


def parmak_izi(text: str) -> list[int]:
    return sorted(h for h in fingerprint(text) if h % ORNEK == 0)


def iyi_mi(r: dict) -> bool:
    return (r.get("karar") in KABUL and r.get("guven") in IYI_GUVEN and bool(r.get("sayilir"))
            and not r.get("zayif"))


def from_audit(rows: list[dict], docs: dict[str, dict], texts: dict[str, str], donem: int | None,
               turler: Turler) -> tuple[list[dict], dict[str, dict]]:
    """audit satırlarından referans öğeleri ve belge özetleri ({doc_id: {...}})."""
    secilen = [r for r in rows if iyi_mi(r)]
    ids = sorted({r["doc_id"] for r in secilen})
    kw = anahtar_sozcukler({k: texts.get(k, "") for k in ids})
    belgeler: dict[str, dict] = {}
    for did in ids:
        d = docs.get(did) or {}
        belgeler[did] = {"doc_type": d.get("doc_type") or "", "baslik": d.get("baslik") or "",
                         "tarih": d.get("tarih") or "", "donem_ici": d.get("donem_ici"),
                         "anahtar": kw.get(did, []), "parmak_izi": parmak_izi(texts.get(did, ""))}
    items: list[dict] = []
    seen: dict[tuple, dict] = {}
    for r in sorted(secilen, key=lambda r: (r["olcut"], r["yuva"], r["doc_id"])):
        key = (r["doc_id"], r["olcut"])            # belge × ölçüt başına bir öğe; yuvalar birleşir
        if key in seen:
            it = seen[key]
            if r["yuva"] not in it["yuva"].split(", "):
                it["yuva"] += ", " + r["yuva"]
            continue
        d = docs.get(r["doc_id"]) or {}
        b = belgeler[r["doc_id"]]
        ad = r.get("kanit_adi") or r.get("belge") or r["doc_id"]
        tur = turler.bul(r.get("belge_turu"), " ".join([ad, b["baslik"], texts.get(r["doc_id"], "")[:BAS]]))
        items.append({
            "kaynak": "calisma_alani", "olcut": r["olcut"], "yuva": r["yuva"],
            "asama": r.get("etkin_asama") or r.get("asama") or "", "od": r.get("od"),
            "belge_turu": r.get("belge_turu") or "", "kanit_adi": ad, "doc_id": r["doc_id"],
            "tarih": r.get("tarih") or d.get("tarih") or "", "donem": donem,
            "donem_yil": r.get("donem_yil"), "donem_ici": d.get("donem_ici"),
            "guven": r.get("guven"), "karar": r.get("karar"),
            "tekrarlayan": tur.id if tur else "", "tekrarlayan_ad": tur.ad if tur else "",
            "ad_sozcukleri": ad_sozcukleri(ad, b["baslik"]),
            "anahtar": b["anahtar"] or ad_sozcukleri(ad, b["baslik"]),
            "alinti": (r.get("alinti") or "")[:240],
        })
        seen[key] = items[-1]
    return items, belgeler


EK_ZORUNLU = ("olcut", "belge_turu", "ad")


def from_csv(path: Path, turler: Turler) -> tuple[list[dict], list[str]]:
    """Elle verilen iyi kanıtlar: CSV başlıkları `olcut,belge_turu,ad` (+ isteğe bağlı `yuva`,
    `asama`, `anahtar` — boşlukla ayrılmış sözcükler). Hatalı satır atlanır, uyarı döner."""
    items, uy = [], []
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        miss = [k for k in EK_ZORUNLU if k not in (rd.fieldnames or [])]
        if miss:
            raise ValueError(f"{path}: eksik sütun(lar): {', '.join(miss)} (gerekli: {', '.join(EK_ZORUNLU)})")
        for i, r in enumerate(rd, 2):
            olcut = (r.get("olcut") or "").strip().rstrip(".")
            ad = (r.get("ad") or "").strip()
            if not olcut or not ad:
                uy.append(f"{path.name}:{i}: ölçüt ya da ad boş; atlandı")
                continue
            bt = (r.get("belge_turu") or "").strip()
            tur = turler.bul(bt, ad)
            ek = ad_sozcukleri(r.get("anahtar") or "")
            items.append({
                "kaynak": "elle", "olcut": olcut, "yuva": (r.get("yuva") or "").strip(),
                "asama": (r.get("asama") or "").strip(), "od": None, "belge_turu": bt,
                "kanit_adi": ad, "doc_id": "", "tarih": "", "donem": None, "donem_yil": None,
                "donem_ici": None, "guven": "", "karar": "elle",
                "tekrarlayan": tur.id if tur else "", "tekrarlayan_ad": tur.ad if tur else "",
                "ad_sozcukleri": ad_sozcukleri(ad), "anahtar": ad_sozcukleri(ad) + [w for w in ek if w not in ad_sozcukleri(ad)],
                "alinti": "",
            })
    return items, uy


def build_reference(ws_root: Path | None, *, ek: Path | None = None, turler: Turler | None = None) -> dict:
    turler = turler or Turler()
    items: list[dict] = []
    belgeler: dict[str, dict] = {}
    uy: list[str] = []
    donem = None
    ws_s = ""
    if ws_root is not None:
        from bidr.audit.run import build
        ws = Workspace(ws_root)
        ws_s = str(ws.root)
        a = build(ws.root)
        docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
        ids = {r["doc_id"] for r in a.rows if iyi_mi(r)}
        texts = {k: _text(ws, k) for k in ids}
        items, belgeler = from_audit(a.rows, docs, texts, a.donem, turler)
        donem = a.donem
        uy += a.uyarilar
        if not any(r.get("karar") for r in a.rows):
            uy.append("çalışma alanında inceleme kararı yok: iyi kanıt (kabul edilmiş eşleşme) çıkmadı")
    if ek is not None:
        e_items, e_uy = from_csv(Path(ek), turler)
        items += e_items
        uy += e_uy
    for i, it in enumerate(items, 1):
        it["id"] = f"R{i:03d}"
    return {"surum": SURUM, "uretim": datetime.now().isoformat(timespec="seconds"),
            "kaynak_calisma_alani": ws_s, "donem": donem, "ek_csv": str(ek) if ek else "",
            "uyarilar": uy, "ogeler": items, "belgeler": belgeler}


def write_reference(ref: dict, out: Path) -> Path:
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ref, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_reference(path: Path) -> dict:
    ref = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if ref.get("surum") != SURUM:
        raise ValueError(f"{path}: referans sürümü {ref.get('surum')} (beklenen {SURUM}); yeniden üretin")
    return ref
