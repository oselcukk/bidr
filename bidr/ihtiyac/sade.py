"""Son kullanıcı için sade "İstenen kanıtlar" listesi (`istenen-kanitlar.xlsx`).

`ihtiyac.xlsx` model/teknik kullanım içindir (puan, kaynak, yuva kimliği, PUKÖ halkası). Bu dosya
bölümdeki kişilere/birimlere iletilecek listedir: **ölçüt başına bir satır**, düz Türkçe, madde madde
somut belge listesi. Model yok; metinler kodla şablonlanır:

- İstenen belgeler (sıra): komisyonun elle eklediği istekler (`--istenecekler`) → geçen yılki raporda
  olup bu yıl karşılığı bulunamayan belgeler (tekrarlayan belgede yıl ilerletilir) → komisyonun
  "istenebilecek kanıtlar" önerileri (`ihtiyac_oneriler.yaml`; eşlendiği kılavuz maddesi karşılanmamışsa)
  → karşılanmamış kılavuz maddelerinin somut karşılıkları (`ihtiyac_somut.yaml`). Kılavuz
  kaynaklı satırlar en çok `KILAVUZ_EN_COK` madde; tam liste ihtiyac.xlsx'te.
- Neden gerekli: ölçütün durumuna göre hazır cümleler (olgunluk düzeyi, eksik aşama sade adıyla).
- Öncelik: Yüksek (kanıtsız ya da tek belgeyle olgunluk düzeyi artan) / Orta (geçen yılın karşılığı
  yok ya da bir üst düzeyin eksik belgesi; elle istek varsayılanı) / Düşük (yalnız tamamlayıcı).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import yaml

from bidr.criteria.model import id_key

from .eslestir import ESKI, YOK

DATA = Path(__file__).resolve().parents[1] / "data"
SOMUT_FILE = DATA / "ihtiyac_somut.yaml"
ONERILER_FILE = DATA / "ihtiyac_oneriler.yaml"
FILE = "istenen-kanitlar.xlsx"
KILAVUZ_EN_COK = 6          # kılavuz/öneri kaynaklı madde sayısı (satır başına)
ELDE_EN_COK = 4
REF_GRUP_EN_AZ = 3          # geçen yılın aynı türden bu kadar belgesi tek maddede toplanır
REF_GRUP = {"yonerge": "mevzuat", "yonetmelik": "mevzuat", "is_akisi": "mevzuat"}
YUKSEK, ORTA, DUSUK = "Yüksek", "Orta", "Düşük"
SIRA = {YUKSEK: 0, ORTA: 1, DUSUK: 2}
ASAMA_SADE = {"planla": "işin nasıl yapılacağının kurala bağlandığını (yönerge, süreç tanımı, plan)",
              "uygula": "bu işin bölümde bu dönem gerçekten yapıldığını (karar, tutanak, liste, duyuru)",
              "kontrol_et": "sonuçların izlenip değerlendirildiğini (anket sonucu, değerlendirme raporu)",
              "onlem_al": "izleme sonucuna göre bir iyileştirme yapıldığını (değişiklik kararı)",
              "ozgun": "bölüme özgü, örnek gösterilebilir bir uygulamayı"}
ASAMA_KISA = {"planla": "plan/kural", "uygula": "uygulama", "kontrol_et": "izleme sonucu",
              "onlem_al": "iyileştirme", "ozgun": "özgün uygulama"}
_DEN = {1: "1'den", 2: "2'den", 3: "3'ten", 4: "4'ten", 5: "5'ten"}
_E = {1: "1'e", 2: "2'ye", 3: "3'e", 4: "4'e", 5: "5'e"}
_DE = {1: "1'de", 2: "2'de", 3: "3'te", 4: "4'te", 5: "5'te"}
COLS = [("sira", "Sıra", 5), ("madde", "Madde", 26), ("oncelik", "Öncelik", 9),
        ("belgeler", "İstenen belgeler", 62), ("neden", "Neden gerekli", 42),
        ("kimden", "Kimden istenebilir", 24), ("kilavuz", "Kılavuzdaki örnek kanıtlar", 46),
        ("not", "Not / örnek", 32)]
K_COLS = [("kimden", "Kimden", 26), ("madde", "Madde", 30), ("oncelik", "Öncelik", 9),
          ("belgeler", "İstenen belgeler", 70)]
SHEETS = ("İstenen kanıtlar", "Kime gönderilecek", "Nasıl okunur")
NASIL = [
    "Bu liste, kalite raporu (BİDR) için bölümden istenecek belgeleri gösterir. Her satır raporun bir maddesidir.",
    "Öncelik: Yüksek = maddede hiç belge yok ya da tek bir belge maddeyi belirgin biçimde güçlendirir; "
    "Orta = geçen yıl verilen bir belgenin bu yılki hâli eksik ya da bir sonraki düzey için belge gerekiyor; "
    "Düşük = tamamlayıcı belgeler.",
    "“İstenen belgeler” sütunundaki maddelerden biri ya da birkaçı yeterlidir; hepsi zorunlu değildir. "
    "Elde olan benzer bir belge de iş görür.",
    "“Kime gönderilecek” sayfası aynı istekleri kişi/birim başına toplar. Kimden istenebileceği öneridir; "
    "bölümün iş bölümüne göre değişebilir.",
    "“Kılavuzdaki örnek kanıtlar” YÖKAK kılavuzunun bu madde için örnek verdiği ve henüz karşılanmamış "
    "belgelerdir (kılavuz metni). Liste bir hatırlatmadır, kesin kontrol listesi değildir.",
]


# -- tablolar -----------------------------------------------------------------------------------

class Somut:
    """Kılavuz maddesi → somut belge listesi (+ isteğe bağlı kimden)."""

    def __init__(self, path: Path | str | None = None):
        raw = yaml.safe_load(Path(path or SOMUT_FILE).read_text(encoding="utf-8")) or {}
        self.ozgun = [str(x) for x in raw.get("ozgun") or []]
        self.yuva: dict[str, list[str]] = {}
        self.kimden: dict[str, str] = {}
        for k, v in (raw.get("yuva") or {}).items():
            if isinstance(v, dict):
                self.yuva[str(k)] = [str(x) for x in v.get("belgeler") or []]
                if v.get("kimden"):
                    self.kimden[str(k)] = str(v["kimden"])
            else:
                self.yuva[str(k)] = [str(x) for x in v or []]


def oneriler_yukle(path: Path | str | None = None) -> list[dict]:
    raw = yaml.safe_load(Path(path or ONERILER_FILE).read_text(encoding="utf-8")) or {}
    out = []
    for r in raw.get("oneriler") or []:
        ys = [str(y) for y in r.get("yuvalar") or []]
        if r.get("metin") and ys:
            out.append({"metin": str(r["metin"]), "yuvalar": ys, "kimden": str(r.get("kimden") or "")})
    return out


# -- elle istekler (istenecekler.md / .csv) -----------------------------------------------------

_MADDE = r"[A-E](?:\.(?:\d+|[xX]))*"
_BULLET = re.compile(r"^\s*(?:[-*•+]|\d+[.)])\s+(.*\S)\s*$")
_BAS = re.compile(rf"^\**\s*({_MADDE})\s*\**\s*(?:[—–:]|-(?=\s))\s*(.*)$")
_ONC = re.compile(r"\[\s*(y[üu]ksek|orta|d[üu][şs][üu]k)\s*\]", re.I)
_KIM = re.compile(r"\(\s*kimden\s*:\s*([^)]*)\)", re.I)


def _oncelik_ad(s: str) -> str:
    from .tablolar import norm
    return {"yuksek": YUKSEK, "orta": ORTA, "dusuk": DUSUK}.get(norm(s), ORTA)


def _temiz(s: str) -> str:
    return " ".join(s.replace("**", "").replace("`", "").split()).strip()


def istek(madde: str, metin: str, oncelik: str = "", kimden: str = "") -> dict:
    m = _ONC.search(metin)
    if m:
        oncelik, metin = oncelik or m.group(1), _ONC.sub("", metin)
    k = _KIM.search(metin)
    if k:
        kimden, metin = kimden or k.group(1), _KIM.sub("", metin)
    return {"madde": madde.strip().rstrip(".") or "Genel", "metin": _temiz(metin),
            "oncelik": _oncelik_ad(oncelik) if oncelik else ORTA, "kimden": _temiz(kimden)}


def istekler_oku(path: Path | str) -> list[dict]:
    """Elle istekler. Markdown: madde işaretli satırlar `- B.3.2 — metin [yüksek] (kimden: …)`
    (ayırıcı —, –, : ya da " - "; madde kodu yoksa "Genel"); başka satırlar yok sayılır. CSV: başlıklar
    `madde,istek` zorunlu, `oncelik`, `kimden` isteğe bağlı."""
    p = Path(path).expanduser()
    txt = p.read_text(encoding="utf-8-sig")
    out = []
    if p.suffix.lower() == ".csv":
        rd = csv.DictReader(txt.splitlines())
        if not rd.fieldnames or not {"madde", "istek"} <= {f.strip() for f in rd.fieldnames}:
            raise ValueError(f"{p.name}: CSV başlıkları 'madde,istek' olmalı (isteğe bağlı: oncelik, kimden)")
        for r in rd:
            r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
            if r.get("istek"):
                out.append(istek(r.get("madde") or "", r["istek"], r.get("oncelik", ""), r.get("kimden", "")))
        return out
    for line in txt.splitlines():
        b = _BULLET.match(line)
        if not b:
            continue
        m = _BAS.match(b.group(1))
        out.append(istek(m.group(1), m.group(2)) if m else istek("", b.group(1)))
    return [x for x in out if x["metin"]]


# -- satırlar -----------------------------------------------------------------------------------

def _yil(s: str, yil) -> str:
    return s.replace("{yil}", str(yil or "").strip() or "bu yıl")


def yil_ilerlet(ad: str, fark: int) -> str:
    if fark <= 0:
        return ad
    return re.sub(r"(?<!\d)(20\d\d)(?!\d)", lambda m: str(int(m.group(1)) + fark), ad)


def _oncelik(puan: int) -> str:
    if puan >= 80:
        return YUKSEK
    if puan >= 45:
        return ORTA
    return DUSUK


def _yuva_ids(s: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b[A-E]\.\d+\.\d+/\d+\b", s or "")))


def _baslik(cs, cid: str) -> str:
    try:
        return cs.get(cid).title
    except KeyError:
        return ""


def _madde_anahtar(madde: str, cs) -> str:
    """`B.1.x` → `B.1`; bilinmeyen kod olduğu gibi."""
    m = re.sub(r"(\.[xX])+$", "", madde)
    try:
        cs.get(m)
        return m
    except KeyError:
        return madde


def _kim(sor, tags, somut: Somut, sid: str, cid: str) -> str:
    if sid in somut.kimden:
        return somut.kimden[sid]
    t = tags.get(sid)
    st = [h for h in (t.stages if t is not None else ()) if h in ASAMA_SADE]
    # "uygula" için aşama tablosu ("İlgili komisyon") belirsiz: alanın sorumlusu yazılır
    return sor.kim(asama=st[0] if st and st[0] != "uygula" else None, olcut=cid)


def _kim_ref(sor, g: dict, cid: str) -> str:
    k = sor.kim(g.get("belge_turu"), g.get("asama"), cid)
    # aşama tablosunun "uygula" karşılığı ("İlgili komisyon") belirsiz: alanın sorumlusu yazılır
    if g.get("belge_turu") not in sor.belge_turu and g.get("asama") == "uygula":
        return sor.kim(olcut=cid)
    return k


def _neden(sat: dict | None, tal: list[dict], ref_n: int, elle: bool) -> str:
    L = []
    if elle:
        L.append("Komisyon incelemede bu madde için belge istedi (listenin başındakiler).")
    if sat is None:
        return " ".join(L)
    od = int(sat.get("od") or 1)
    ana = next((t for t in tal if t["kaynak"].split(" + ")[0] in ("kanıtsız", "OD artışı")
                and t["puan"] >= 80), None)
    if ana and ana["halka"] in ASAMA_SADE:
        yeni = ana.get("hedef_od") or od + 1
        if sat.get("kanit_sayisi", 0) == 0:
            L.append(f"Bu madde için şu an rapora konabilecek hiç belge yok. En çok işe yarayacak belge "
                     f"{ASAMA_SADE[ana['halka']]} gösteren bir belgedir: tek başına maddenin olgunluk "
                     f"düzeyini {_DEN.get(od, od)} {_E.get(yeni, yeni)} çıkarır.")
        else:
            L.append(f"Bu maddede {sat['kanit_sayisi']} belge var ama {ASAMA_SADE[ana['halka']]} gösteren "
                     f"belge yok. Böyle tek bir belge olgunluk düzeyini {_DEN.get(od, od)} "
                     f"{_E.get(yeni, yeni)} çıkarır.")
    if ref_n:
        L.append(f"Geçen yılki raporda bu maddede kullanılan {ref_n} belgenin bu yılki hâli bulunamadı."
                 if ref_n > 1 else "Geçen yılki raporda bu maddede kullanılan bir belgenin bu yılki hâli "
                                   "bulunamadı.")
    if not ana and not ref_n:
        nxt, eksik = sat.get("sonraki_od"), sat.get("eksik_asamalar") or []
        if any(t["puan"] >= 45 for t in tal) and nxt and eksik:
            L.append(f"Madde şu an olgunluk düzeyi {_DE.get(od, od)}. Bir üst düzeye ({nxt}) çıkmak için "
                     + " ve ".join(ASAMA_SADE[h] for h in eksik) + " gösteren belgeler gerekiyor.")
        elif tal:
            L.append(f"Madde şu an olgunluk düzeyi {_DE.get(od, od)}. Aşağıdaki belgeler zorunlu değil; "
                     "kılavuzun örnek verdiği ama dosyada henüz olmayan belgelerdir, eklenirse madde güçlenir.")
    return " ".join(L)


def satirlar_kur(cs, tags, sor, talepler: list[dict], satirlar: list[dict], gecen: list[dict], *,
                 yil=None, ref_yil=None, istekler: list[dict] | None = None, somut: Somut | None = None,
                 oneriler: list[dict] | None = None) -> list[dict]:
    """Ölçüt başına bir sade satır (öncelik sırasıyla). Her satırda `maddeler`: [{metin, kimden}]."""
    somut = somut or Somut()
    oneriler = oneriler if oneriler is not None else oneriler_yukle()
    istekler = istekler or []
    fark = (int(yil) - int(ref_yil)) if yil and ref_yil else 0
    sat_by = {s["olcut"]: s for s in satirlar}
    tal_by: dict[str, list[dict]] = {}
    for t in talepler:
        tal_by.setdefault(t["olcut"], []).append(t)
    ref_by: dict[str, list[dict]] = {}
    for g in gecen:
        if g.get("durum") in (YOK, ESKI):
            ref_by.setdefault(g["olcut"], []).append(g)
    ist_by: dict[str, list[dict]] = {}
    for x in istekler:
        ist_by.setdefault(_madde_anahtar(x["madde"], cs), []).append(x)

    out = []
    for cid in sorted(set(tal_by) | set(ist_by), key=lambda c: (c == "Genel", _guvenli_key(c))):
        tal = sorted(tal_by.get(cid, []), key=lambda t: -t["puan"])
        sat = sat_by.get(cid)
        if sat is not None:
            sat = {**sat, "eksik_asamalar": [h for h in sat.get("eksik_kod") or [] if h in ASAMA_SADE]}
        maddeler: list[dict] = []

        def ekle(metin: str, kimden: str, tur: str):
            metin = _yil(metin, yil)
            if metin and metin not in {m["metin"] for m in maddeler}:
                maddeler.append({"metin": metin, "kimden": kimden, "tur": tur})

        # 1. elle istekler
        ist = ist_by.get(cid, [])
        for x in ist:
            ekle(x["metin"], x["kimden"] or sor.kim(olcut=cid if cid[:1] in "ABCDE" else None), "elle")
        # 2. geçen yılın karşılığı bulunamayan belgeleri
        refs = ref_by.get(cid, [])
        gruplar: dict[str, list[dict]] = {}
        for g in refs:
            gruplar.setdefault(REF_GRUP.get(g.get("belge_turu") or "", g.get("belge_turu") or ""), []).append(g)
        for g in refs:
            grp = REF_GRUP.get(g.get("belge_turu") or "", g.get("belge_turu") or "")
            xs = gruplar.get(grp) or []
            if grp and len(xs) >= REF_GRUP_EN_AZ:
                if xs[0] is g:                # aynı türden çok belge: tek madde
                    ad = _tur_etiketi(grp)
                    ekle(f"Geçen yılki raporda olan {ad} belgelerinin güncel hâli: "
                         + "; ".join(f"«{yil_ilerlet(x.get('kanit_adi') or '', fark)}»" for x in xs),
                         _kim_ref(sor, g, cid), "gecen")
                continue
            ad = g.get("kanit_adi") or ""
            if g.get("tekrarlayan"):
                yeni = yil_ilerlet(ad, fark)
                m = (f"{yeni} (geçen yılki raporda: «{ad}»)" if yeni != ad
                     else f"«{ad}» belgesinin bu yılki ({yil or 'güncel'}) hâli (geçen yılki raporda vardı)")
                if g.get("durum") == ESKI:
                    m += "; elde yalnız eski sürümü var"
            else:
                m = f"«{ad}» ya da güncel hâli (geçen yılki raporda vardı, bu yılki dosyalarda bulunamadı)"
            ekle(m, _kim_ref(sor, g, cid), "gecen")
        # 3–4. karşılanmamış kılavuz maddeleri: önce komisyon önerileri, sonra somut karşılıklar
        ref_yuva = {y for t in tal if t["kaynak"].startswith("geçen yıl") for y in _yuva_ids(t["yuvalar"])}
        acik = [y for y in (sat or {}).get("karsilanmamis_yuvalar") or []]
        puan = {y: max((t["puan"] for t in tal if y in _yuva_ids(t["yuvalar"])), default=0) for y in acik}
        sira = sorted((y for y in acik if y not in ref_yuva),
                      key=lambda y: (-puan[y], int(y.rsplit("/", 1)[1])))
        n_klv, kapsanan = 0, set()
        for o in sorted((o for o in oneriler if set(o["yuvalar"]) & set(sira)),
                        key=lambda o: min(sira.index(y) for y in o["yuvalar"] if y in sira)):
            if n_klv >= KILAVUZ_EN_COK:
                break
            y0 = next(y for y in sira if y in o["yuvalar"])
            n0 = len(maddeler)
            ekle(o["metin"], o["kimden"] or _kim(sor, tags, somut, y0, cid), "oneri")
            if len(maddeler) > n0:
                n_klv += 1
                kapsanan |= set(o["yuvalar"])
        for y in sira:
            if n_klv >= KILAVUZ_EN_COK:
                break
            if y in kapsanan:
                continue
            t = tags.get(y)
            ozg = t is not None and "ozgun" in t.stages
            if ozg and (sat or {}).get("sonraki_od") != 5 and not any(
                    t["halka"] == "ozgun" and t["puan"] >= 80 for t in tal):
                continue                      # özgün uygulama yalnız son düzeyde istenir
            xs = somut.yuva.get(y) or (somut.ozgun if ozg else []) or [_yuva_metni(cs, y)]
            for x in xs:
                if n_klv >= KILAVUZ_EN_COK:
                    break
                n0 = len(maddeler)
                ekle(x, _kim(sor, tags, somut, y, cid), "kilavuz")
                n_klv += len(maddeler) > n0
        # öncelik, gerekçe, not
        oto = _oncelik(tal[0]["puan"]) if tal else DUSUK
        onc = min([oto] + [x["oncelik"] for x in ist], key=SIRA.get)
        kanitsiz = bool(sat) and sat.get("kanit_sayisi", 0) == 0
        notlar = []
        if sat and sat.get("kanitlar"):
            ks = sat["kanitlar"]
            notlar.append("Dosyada olanlar: " + "; ".join(ks[:ELDE_EN_COK])
                          + (f" ve {len(ks) - ELDE_EN_COK} belge daha" if len(ks) > ELDE_EN_COK else ""))
        ornek = list(dict.fromkeys(t["ornek"] for t in tal if t.get("ornek") and not t["kaynak"].startswith("geçen")))
        if ornek:
            notlar.append("Geçen yıl bu amaçla kullanılan: " + "; ".join(ornek[:3]))
        klv_metin = [_yuva_metni(cs, y) for y in sorted(acik, key=lambda y: int(y.rsplit("/", 1)[1]))]
        out.append({
            "olcut": cid, "madde": _madde_ad(cs, cid), "oncelik": onc, "maddeler": maddeler,
            "belgeler": "\n".join(f"• {m['metin']}" for m in maddeler),
            "neden": _neden(sat, tal, len(refs), bool(ist)),
            "kimden": "\n".join(list(dict.fromkeys(m["kimden"] for m in maddeler if m["kimden"]))[:3]),
            "kilavuz": ("Kılavuzun bu madde için örnek verdiği, henüz karşılanmamış belgeler:\n"
                        + "\n".join(f"• {x}" for x in klv_metin)) if klv_metin else "",
            "not": "\n".join(notlar),
            "_anahtar": (SIRA[onc], not kanitsiz, -(tal[0]["puan"] if tal else 0), _guvenli_key(cid)),
        })
    out.sort(key=lambda r: r["_anahtar"])
    for i, r in enumerate(out, 1):
        r["sira"] = i
        del r["_anahtar"]
    return out


_ETIKET: dict[str, str] = {}


def _tur_etiketi(tur: str) -> str:
    """Belge türünün okunur adı (küçük harf; doc_types.yaml `etiket`)."""
    if tur == "mevzuat":
        return "kurum yönetmelik, yönerge ve iş akışı"
    if not _ETIKET:
        raw = yaml.safe_load((DATA / "doc_types.yaml").read_text(encoding="utf-8")) or {}
        for v in raw.values():
            for r in v if isinstance(v, list) else []:
                if isinstance(r, dict) and r.get("ad") and r.get("etiket"):
                    _ETIKET[str(r["ad"])] = str(r["etiket"])
    e = _ETIKET.get(tur, tur.replace("_", " "))
    return e.replace("I", "ı").replace("İ", "i").lower() if not e.isupper() else e


def _guvenli_key(cid: str) -> tuple:
    try:
        return (0, *id_key(cid))
    except (ValueError, IndexError):
        return (1, cid)


def _yuva_metni(cs, sid: str) -> str:
    try:
        return cs.get_slot(sid).text.replace("*", "").strip()
    except KeyError:
        return sid


def _madde_ad(cs, cid: str) -> str:
    if cid == "Genel":
        return "Genel (madde belirtilmedi)"
    b = _baslik(cs, cid).replace("*", "").strip()
    if not b:
        return cid
    return f"{cid} — {b}" + ("" if cid.count(".") >= 2 else " (alt madde belirtilmedi)")


def kime_gore(rows: list[dict]) -> list[dict]:
    by: dict[tuple, list[str]] = {}
    for r in rows:
        for m in r["maddeler"]:
            by.setdefault((m["kimden"] or "Belirtilmedi", r["sira"]), []).append(m["metin"])
    rs = {r["sira"]: r for r in rows}
    out = [{"kimden": k, "madde": rs[s]["madde"], "oncelik": rs[s]["oncelik"],
            "belgeler": "\n".join(f"• {x}" for x in xs), "_s": s} for (k, s), xs in by.items()]
    out.sort(key=lambda x: (x["kimden"], x["_s"]))
    return out


# -- xlsx ---------------------------------------------------------------------------------------

def _yukseklik(row: list, widths: list[int]) -> float:
    n = 1
    for v, w in zip(row, widths):
        if v is None:
            continue
        lines = sum(max(1, -(-len(s) // max(1, int(w * 1.1)))) for s in str(v).split("\n"))
        n = max(n, lines)
    return min(409, 15 * n + 3)


def write_xlsx(path: Path, rows: list[dict], *, baslik: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    head = PatternFill("solid", fgColor="DDE7F0")
    renk = {YUKSEK: "F8D7D3", ORTA: "FCEFCF", DUSUK: "E4F1E1"}
    ince = Side(style="thin", color="B7C3CE")
    kenar = Border(left=ince, right=ince, top=ince, bottom=ince)
    for name, cols, data in ((SHEETS[0], COLS, rows), (SHEETS[1], K_COLS, kime_gore(rows))):
        sh = wb.create_sheet(name)
        widths = [w for _, _, w in cols]
        sh.append([h for _, h, _ in cols])
        for i, w in enumerate(widths, 1):
            sh.column_dimensions[get_column_letter(i)].width = w
            c = sh.cell(row=1, column=i)
            c.font = Font(bold=True)
            c.fill = head
            c.border = kenar
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for r in data:
            vals = [r.get(k) for k, _, _ in cols]
            sh.append(vals)
            ri = sh.max_row
            sh.row_dimensions[ri].height = _yukseklik(vals, widths)
            for ci, (k, _, _) in enumerate(cols, 1):
                c = sh.cell(row=ri, column=ci)
                c.alignment = Alignment(wrap_text=True, vertical="top")
                c.border = kenar
                if k == "oncelik":
                    c.fill = PatternFill("solid", fgColor=renk.get(r["oncelik"], "FFFFFF"))
                    c.font = Font(bold=True)
        sh.freeze_panes = "A2"
        sh.print_title_rows = "1:1"
        sh.page_setup.orientation = "landscape"
        sh.page_setup.paperSize = sh.PAPERSIZE_A4
        sh.page_setup.fitToWidth = 1
        sh.page_setup.fitToHeight = 0
        sh.sheet_properties.pageSetUpPr.fitToPage = True
        sh.page_margins.left = sh.page_margins.right = 0.4
        if baslik:
            sh.oddHeader.center.text = baslik
        sh.oddFooter.right.text = "Sayfa &P / &N"
        if data:
            sh.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(data) + 1}"
    sh = wb.create_sheet(SHEETS[2])
    sh.column_dimensions["A"].width = 110
    sh.append(["Nasıl okunur"])
    sh["A1"].font = Font(bold=True, size=13)
    for line in NASIL:
        sh.append([line])
        sh.cell(row=sh.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        sh.row_dimensions[sh.max_row].height = _yukseklik([line], [110])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
