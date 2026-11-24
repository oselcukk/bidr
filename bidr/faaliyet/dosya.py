"""Etkinlik dosyası: aynı etkinliğe ait olabilecek belgelerin (afiş, fotoğraf, haber, katılım listesi)
aday grupları. Belirleyici kod; model çağrısı yok. Karar modelindir: kod yalnız aday grubu ve
grubun etkinlik adını (ipucu) ince karar paketine koyar (bkz. kanıt ilkesi `etkinlik_dosyasi`).

Gruplama sinyalleri (birlik-bul):
  1. **Ad serisi:** aynı klasörde, dosya adı sondaki sıra numarası atılınca aynı olan belgeler
     ("ulusal staj 2026-1.jpg" … "-5.jpg", "afis (2).png"). Sıra numarası olmayan ad seri değildir.
  2. **Aynı klasör + yakın tarih:** aynı klasörde, içerik tarihi (gün kesinliğinde) en çok
     `YAKIN_GUN` gün ayrık bir fotoğraf ile faaliyet adı taşıyan belge.
  3. **Aynı faaliyet adı/tarihi:** faaliyet kayıtlarında (`bidr.faaliyet.group`) zaten birleşir;
     burada ayrıca kurulmaz.
Kök klasördeki (klasörsüz) belgelere klasör sinyali uygulanmaz.

Bağlam kaynağı: grubun faaliyet adı taşıyan ve bu adı **kendi içeriğinden** (paketinde etkinlik
dosyası ipucu olmadan) almış üyeleri. İpucuyla karar verilmiş belge kaynak olmaz: ipucu zincirlenmez,
sonuç kararlıdır (bir fotoğrafın kararı başka fotoğrafın paketini değiştirmez, döngü yok).

**Fotoğraf** (`fotograf_mi`) = türü `fotograf` VE dosyası gerçek bir görsel (uzantı `GORSEL_UZANTI`: jpg, jpeg,
png, heic, heif, webp). `fotograf` diye sınıflanmış PDF (giriş ekranı, kılavuz, karar belgesi) fotoğraf
sayılmaz: ne yakın-tarih sinyaline girer, ne ipucu alır, ne de "bu fotoğraf hangi etkinliğe ait?" diye sorulur.

İpucu yalnız fotoğrafa verilir ve yalnız şu durumda: belge henüz ince karar
almadı, ya da kararında faaliyet adı yok, ya da kararı zaten ipucuyla verildi. Kendi içeriğinden
faaliyet adı almış fotoğrafın paketi değişmez (gereksiz yeniden karar yok).
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date
from pathlib import Path, PurePosixPath

from bidr.common import Workspace, read_jsonl

from .group import fold

FOTOGRAF_TURLER = frozenset({"fotograf"})
GORSEL_UZANTI = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"})
YAKIN_GUN = 7
BAGLAM_EN_COK = 3
ALAN = "etkinlik_baglami"          # ince kayıtta: kararın verildiği ipucunun kaynak belgeleri
_SIRA = re.compile(r"^(.*?[a-z].*?)[\s_\-.]*(?:\(\s*\d{1,4}\s*\)|\d{1,4})$")


def seri_koku(rel_path: str) -> str | None:
    """Dosya adının sondaki sıra numarası atılmış, katlanmış kökü; sıra numarası yoksa None."""
    stem = fold(PurePosixPath(rel_path.replace("\\", "/")).stem).strip()
    m = _SIRA.match(stem)
    if not m:
        return None
    kok = re.sub(r"[\s_\-.]+", " ", m.group(1)).strip()
    return kok if len(re.sub(r"[^a-z]", "", kok)) >= 3 else None


def gorsel_mi(rel_path: str | None) -> bool:
    """Dosya uzantısı gerçek bir görsel mi (PDF değil)."""
    return PurePosixPath((rel_path or "").replace("\\", "/")).suffix.lower() in GORSEL_UZANTI


def fotograf_mi(doc_id: str, paths: dict[str, str], docs: dict[str, dict]) -> bool:
    """Türü fotoğraf ve dosyası görsel (bkz. modül belgesi)."""
    return (docs.get(doc_id) or {}).get("doc_type") in FOTOGRAF_TURLER and gorsel_mi(paths.get(doc_id))


def klasor(rel_path: str) -> str:
    p = PurePosixPath(rel_path.replace("\\", "/")).parent
    return "" if str(p) in ("", ".") else str(p)


def _gun(t) -> date | None:
    if isinstance(t, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", t.strip()):
        try:
            return date.fromisoformat(t.strip())
        except ValueError:
            return None
    return None


def kaynak_faaliyet(rec: dict | None) -> dict | None:
    """Belgenin kendi içeriğinden aldığı faaliyet (ad dolu, ipucuyla verilmemiş ince karar); yoksa None."""
    ince = (rec or {}).get("ince") or {}
    if (rec or {}).get("durum") != "ok" or (rec or {}).get("asama") != "ince" or ince.get(ALAN):
        return None
    if ince.get("birim_iliskisi") == "baska_birim":
        return None
    f = ince.get("faaliyet")
    if not isinstance(f, dict) or not str(f.get("ad") or "").strip():
        return None
    return f


def gruplar(paths: dict[str, str], docs: dict[str, dict], recs: dict[str, dict]) -> list[list[str]]:
    """Aday etkinlik dosyaları (en az iki üyeli; üyeler ve gruplar doc_id sırasıyla)."""
    ids = sorted(paths)
    ana = {d: d for d in ids}

    def bul(x):
        while ana[x] != x:
            ana[x] = ana[ana[x]]
            x = ana[x]
        return x

    def birles(a, b):
        ra, rb = bul(a), bul(b)
        if ra != rb:
            ana[max(ra, rb)] = min(ra, rb)

    seri: dict[tuple, str] = {}
    by_dir: dict[str, list[str]] = {}
    for d in ids:
        k = klasor(paths[d])
        if not k:
            continue
        by_dir.setdefault(k, []).append(d)
        s = seri_koku(paths[d])
        if s:
            if (k, s) in seri:
                birles(seri[(k, s)], d)
            else:
                seri[(k, s)] = d
    for xs in by_dir.values():
        foto = [d for d in xs if fotograf_mi(d, paths, docs) and _gun((docs.get(d) or {}).get("tarih"))]
        olay = [d for d in xs if kaynak_faaliyet(recs.get(d))]
        for f in foto:
            tf = _gun(docs[f].get("tarih"))
            for o in olay:
                fa = kaynak_faaliyet(recs.get(o))
                to = _gun(fa.get("tarih")) or _gun((docs.get(o) or {}).get("tarih"))
                if o != f and to and abs((tf - to).days) <= YAKIN_GUN:
                    birles(f, o)
    out: dict[str, list[str]] = {}
    for d in ids:
        out.setdefault(bul(d), []).append(d)
    return [g for g in out.values() if len(g) > 1]


def baglamlar(paths: dict[str, str], docs: dict[str, dict], recs: dict[str, dict]) -> dict[str, list[dict]]:
    """{fotoğraf doc_id: [{ad, tarih, asama, doc_id}]}: grubundaki kaynak üyelerin faaliyetleri
    (aynı ad bir kez; en çok `BAGLAM_EN_COK`). Kaynağı olmayan fotoğraf yer almaz."""
    out: dict[str, list[dict]] = {}
    for g in gruplar(paths, docs, recs):
        src = []
        for d in g:
            f = kaynak_faaliyet(recs.get(d))
            if f:
                src.append({"ad": " ".join(str(f["ad"]).split()), "tarih": f.get("tarih"),
                            "asama": f.get("asama"), "doc_id": d})
        for d in g:
            if not fotograf_mi(d, paths, docs):
                continue
            seen, xs = set(), []
            for s in src:
                if s["doc_id"] == d or fold(s["ad"]) in seen:
                    continue
                seen.add(fold(s["ad"]))
                xs.append(s)
            if xs:
                out[d] = xs[:BAGLAM_EN_COK]
    return out


def ipucu_alir(rec: dict | None) -> bool:
    """Bu kayıtlı belgeye ipucu verilir mi (modül belgesindeki kararlılık kuralı)."""
    ince = (rec or {}).get("ince") or {}
    if not rec or rec.get("asama") != "ince" or ince.get("karar") == "atlandi":
        return True
    if ince.get(ALAN):
        return True
    f = ince.get("faaliyet")
    return not (isinstance(f, dict) and str(f.get("ad") or "").strip())


def satir(xs: list[dict]) -> str:
    """Belge bilgisine eklenen ipucu satırı."""
    return ("etkinlik dosyası adayı (aynı klasör/ad serisindeki belgelerin etkinliği; ipucu, kanıt değil): "
            + "; ".join(f"«{x['ad']}» ({x.get('tarih') or 'tarih yok'}, {x.get('asama') or '?'})" for x in xs))


def kaynak_yollari(ws: Workspace) -> dict[str, str]:
    """inventory.csv: doc_id → ilk kaynak yolu (tekrar eden dosyada alfabetik ilk)."""
    out: dict[str, str] = {}
    if not ws.inventory.exists():
        return out
    with open(ws.inventory, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            d, p = r.get("doc_id"), (r.get("rel_path") or "").replace("\\", "/")
            if d and p and (d not in out or p < out[d]):
                out[d] = p
    return out


def yukle(ws_root: Path, recs: dict[str, dict] | None = None) -> dict[str, list[dict]]:
    """Çalışma alanından ipucu haritası (salt okunur)."""
    ws = Workspace(Path(ws_root))
    docs = {r["doc_id"]: r for r in read_jsonl(ws.documents)} if ws.documents.exists() else {}
    if recs is None:
        p = ws.root / "decisions.jsonl"
        recs = {r["doc_id"]: r for r in read_jsonl(p)} if p.exists() else {}
    return baglamlar(kaynak_yollari(ws), docs, recs)


def parmak(harita: dict[str, list[dict]]) -> str:
    return json.dumps(harita, ensure_ascii=False, sort_keys=True)
