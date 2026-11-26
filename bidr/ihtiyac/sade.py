"""Son kullanıcı için sade "İstenen kanıtlar" listesi (`istenen-kanitlar.xlsx`).

`ihtiyac.xlsx` model/teknik kullanım içindir (puan, kaynak, yuva kimliği, PUKÖ halkası). Bu dosya
bölümdeki kişilere/birimlere iletilecek listedir: ölçüt başına bir kayıt (`satirlar_kur`), Excel'de tek sayfa,
her istenen belge işaretlenebilir (☐/☑) ayrı satır (`write_xlsx`), düz Türkçe somut belge listesi.
Model yok; metinler kodla şablonlanır:

- İstenen belgeler (sıra): komisyonun elle eklediği istekler (`--istenecekler`) → geçen yılki raporda
  olup bu yıl karşılığı bulunamayan belgeler (tekrarlayan belgede yıl ilerletilir) → komisyonun
  "istenebilecek kanıtlar" önerileri (`ihtiyac_oneriler.yaml`; eşlendiği kılavuz maddesi karşılanmamışsa)
  → karşılanmamış kılavuz maddelerinin somut karşılıkları (`ihtiyac_somut.yaml`) → kılavuz ekinin
  örnek uygulamaları ("Örnek Uygulama ve Kanıtlar Listesi"; `ihtiyac_ornek_uygulama.yaml` eşlemesiyle,
  önceki maddelerle örtüşmeyenler) → kurumun bu maddeyle eşlenmiş belgeleri (`kurum-katalog-esleme.json`;
  ad, kod, bağlantı). Kılavuz kaynaklı satırlar en çok `KILAVUZ_EN_COK` (tam liste ihtiyac.xlsx'te),
  örnek uygulamalar en çok `ORNEK_EN_COK`, kurum belgeleri en çok `KURUM_EN_COK` madde.
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
ORNEK_ESLEME_FILE = DATA / "ihtiyac_ornek_uygulama.yaml"
FILE = "istenen-kanitlar.xlsx"
KILAVUZ_EN_COK = 6          # kılavuz/öneri kaynaklı madde sayısı (satır başına)
ELDE_EN_COK = 4
ORNEK_EN_COK = 3            # kılavuz eki örnek uygulamalarından madde sayısı (satır başına)
ORNEK_KLV_EN_COK = 4        # "Kılavuzdaki örnek kanıtlar" sütununda listelenen ek örnek uygulama
# Örnek uygulama, önceki bir maddeyle uygulama metninin sözcük kökü (ilk 4 harf) örtüşmesi bu orana ulaşırsa
# yazılmaz (tekrar); eşlendiği yuvaların hepsi listede zaten bir maddeyle istenmişse daha düşük eşik.
ORNEK_ORTUSME = 0.5
ORNEK_ORTUSME_YAZILAN = 0.34
_ORNEK_DOLGU = frozenset("ilgili iliskin vb vs ile olan olarak olmasi yapilmasi edilmesi gosteren belge belgeler "
                         "birim birimin birime bolum bolumun bolume ya da".split())
KURUM_EN_COK = 10           # kurum belge kataloğundan madde sayısı (satır başına)
# Kurum geneli belgeler eksik listesinden adıyla istenir (kullanıcı kararı 2026-11-26 20:35; ortak havuz yok): bölümün
# bu maddede kendi kanıtı yoksa kurumun bu maddeyle eşlenmiş düzenlemesi (katalog) "İstenen belgeler"de adıyla
# istenir (en çok `KURUM_ISTEK_EN_COK`). Bölümün kendi yönetimini soran maddelerde başka idari birimin iş akışı
# istenmez (audit `savunma.BOLUM_SURECI_MADDELERI`; o belge orada kanıt sayılmaz).
KURUM_ISTEK_EN_COK = 3
KURUM_ISTEK_TURLER = ("yonetmelik", "yonerge", "usul_esas", "is_akisi")
# Sade listeye giren kurum belgesi türleri: düzenlemeler ve iş akışları (form girmez; kullanıcı kararı)
KURUM_TURLER = {"yonetmelik", "yonerge", "usul_esas", "mevzuat", "is_akisi", "anket"}
KURUM_REF_TURLER = frozenset({"yonetmelik", "yonerge", "usul_esas", "is_akisi", "senato_karari", "anket_formu"})
_KURUM_SIRA = {t: i for i, t in enumerate(("yonetmelik", "yonerge", "usul_esas", "is_akisi", "anket", "form",
                                           "talimat"))}
_DOLGU = frozenset("gtu gebze teknik universitesi universite akis akisi is ve ile icin iliskin hakkinda bir the of and".split())
REF_GRUP_EN_AZ = 3          # geçen yılın aynı türden bu kadar belgesi tek maddede toplanır
# Derse özgü geçen yıl belgesi (adında ders kodu: MATH407, MAT 106): bu yıl aynı dersin belgesi değil, aynı TÜRden
# herhangi bir dersin belgesi istenir; geçen yılki belge yalnız örnektir. Aynı türden birden çok belge tek istek olur.
DERS_KODU = re.compile(r"\b[A-ZÇĞİÖŞÜ]{2,5} ?\d{3}[A-Z]?\b")
DERS_GRUP = {"ders_bilgi_formu": "ders_bilgi", "mufredat": "ders_bilgi"}
DERS_IFADE = {"ders_degerlendirme": "ders değerlendirme anketi sonucu",
              "ders_bilgi": "ders bilgi formu / ders–program çıktıları matrisi"}
DERS_ORNEK_EN_COK = 2
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
# Durum (ilk durum veriden; Excel'de ☑ işaretleriyle formül günceller)
HIC, EKSIK, AZ = "Hiç belge yok", "Eksiği var", "Az eksik"
TAMAM, KISMEN = "Tamamlandı", "Kısmen bulundu"
DURUM_RENK = {HIC: "F4B183", EKSIK: "FFE699", AZ: "E2EFDA", KISMEN: "FFE699", TAMAM: "9DC3E6"}
BULUNDU_RENK = "C6EFCE"
BOS, DOLU = "☐", "☑"
# Sütunlar: ana (A–F) + katlanabilir soluk ayrıntı (G–L). (anahtar, başlık, genişlik)
COLS = [("madde", "Madde", 32), ("bulundu", "Bulundu", 9), ("durum", "Durum", 22),
        ("belge", "Eksik / istenen belge", 60), ("kimden", "Kimden", 28),
        ("dosyada", "Var olan kanıt (dosyada)", 40),
        ("oncelik", "Öncelik", 9), ("neden", "Neden gerekli (gerekçe)", 44),
        ("gecen_yil", "Geçen yıl kullanılan", 34),
        ("kurum_belgeler", "Kurumun ilgili yönerge/form/iş akışları", 44),
        ("kilavuz", "Kılavuzdaki örnek kanıtlar", 50), ("sira", "Öncelik sırası", 8)]
N_ANA = 6
BASLIK_SATIRI = 4
SHEETS = ("İstenen kanıtlar",)
BOLUM = {"A": "A — Liderlik, Yönetişim ve Kalite", "B": "B — Eğitim ve Öğretim",
         "C": "C — Araştırma ve Geliştirme", "D": "D — Toplumsal Katkı", "E": "E — Uluslararasılaşma"}
BOLUM_GENEL = "Genel — madde belirtilmeyen istekler"
NASIL = [
    "Bu liste, kalite raporu (BİDR) için bölümden istenecek belgeleri gösterir. Her madde raporun bir "
    "maddesidir; maddenin her istenen belgesi ayrı satırdadır.",
    "Öncelik: Yüksek = maddede hiç belge yok ya da tek bir belge maddeyi belirgin biçimde güçlendirir; "
    "Orta = geçen yıl verilen bir belgenin bu yılki hâli eksik ya da bir sonraki düzey için belge gerekiyor; "
    "Düşük = tamamlayıcı belgeler.",
    "“Eksik / istenen belge” sütunundaki belgelerden biri ya da birkaçı yeterlidir; hepsi zorunlu değildir. "
    "Elde olan benzer bir belge de iş görür.",
    "Kimden istenebileceği öneridir; bölümün iş bölümüne göre değişebilir. Kişi/birim başına liste için "
    "«Kimden» sütununun filtresini (metin içerir) kullanın.",
    "“Kurumun ilgili … yönerge/form/iş akışı” satırı kurumun yayımladığı yönetmelik, yönerge, iş akışı ve "
    "formlardır; adları sağdaki “Kurumun ilgili yönerge/form/iş akışları” sütunundadır (adlarından bu "
    "maddeyle ilgili oldukları düşünülmüştür; uygun olanı seçilir).",
    "“Kılavuzdaki örnek kanıtlar” YÖKAK kılavuzunun bu madde için örnek verdiği ve henüz karşılanmamış "
    "belgelerdir (kılavuz metni). Liste bir hatırlatmadır, kesin kontrol listesi değildir.",
    "“Kanıt — uygulama” biçimindeki maddeler BİDR şablonunun sonundaki “Örnek Uygulama ve Kanıtlar Listesi”nden "
    "gelir: önce istenen kanıt, sonra hangi uygulamayı gösterdiği. Kanıt hazırlanırken şablonun uyarısı geçerlidir: "
    "Excel/Word ekran görüntüsü ve maddeyle ilgisiz dosya yığını kanıt sayılmaz, web sayfaları PDF olarak da "
    "eklenir, kişisel veriler maskelenir.",
    "Bu listede olmayan maddelerden belge istenmiyor.",
]
UST_NOT = ("Belge bulununca «Bulundu» hücresinden ☑ seçin; maddenin Durum'u (bulunan/toplam) kendiliğinden "
           "güncellenir. İlk durum: maddede hiç belge yoksa «Hiç belge yok»; Yüksek öncelik → «Eksiği var»; "
           "Orta/Düşük → «Az eksik». Gri sütunlar (G→) ayrıntıdır; üstteki [–] ile katlanır.")


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


def ornekler_yukle(esleme: Path | str | None = None, satirlar: Path | str | None = None) -> list[dict]:
    """Kılavuz eki örnek uygulamaları + alt ölçüt eşlemesi. Öğe: id, alan, uygulama, kanit, yuvalar,
    olcutler, belirsiz, sade. Eşlemesi olmayan satır `yuvalar` boş döner (sade listeye girmez)."""
    from bidr.criteria.loader import load_ornek_uygulamalar
    raw = load_ornek_uygulamalar(satirlar)
    es = (yaml.safe_load(Path(esleme or ORNEK_ESLEME_FILE).read_text(encoding="utf-8")) or {}).get("eslesme") or {}
    out = []
    for r in raw.get("satirlar") or []:
        e = es.get(r["id"]) or {}
        ys = [str(y) for y in e.get("yuvalar") or []]
        out.append({"id": r["id"], "alan": r["alan"], "uygulama": str(r["uygulama"]), "kanit": str(r["kanit"]),
                    "yuvalar": ys, "olcutler": list(dict.fromkeys(y.split("/")[0] for y in ys)),
                    "belirsiz": bool(e.get("belirsiz")), "sade": e.get("sade", True) is not False})
    return out


_KORU = frozenset({"Proliz", "Avrupa", "Yükseköğretim", "Bologna"})


def _kucuk_bas(s: str) -> str:
    """Cümle başını küçültür (Türkçe I/İ). Kısaltma, özel ad ya da ad öbeğiyle ("Ana Bilim Dalı",
    "Ölçme ve Değerlendirme komisyonu", "Birim/Program") başlıyorsa olduğu gibi bırakır."""
    s = s.strip()
    ws = [w for w in re.split(r"[\s/’'–-]+", s) if w][:3]
    if not ws or ws[0] in _KORU or (len(ws[0]) > 1 and ws[0].upper() == ws[0]):
        return s
    if any(w[:1].isupper() and w[1:] != w[1:].upper() for w in ws[1:]):
        return s
    return {"I": "ı", "İ": "i"}.get(s[0], s[0].lower()) + s[1:]


def ornek_metni(o: dict) -> str:
    """Sade liste maddesi: "{kanıt} — {uygulama}" (şablon metni birebir; yalnız uygulamanın başı küçük harf)."""
    return f"{o['kanit'].strip()} — {_kucuk_bas(o['uygulama'])}"


def _kisalt(s: str, n: int = 90) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _kokler4(s: str) -> set[str]:
    from .tablolar import norm
    return {w[:4] for w in re.findall(r"[a-z0-9]+", norm(s))
            if len(w) > 2 and w not in _DOLGU and w not in _ORNEK_DOLGU}


def _ortusur(metin: str, onceki: list[str], esik: float = ORNEK_ORTUSME) -> bool:
    """`metin`in sözcük köklerinin en az `esik` kadarı önceki maddelerden birinde geçiyor mu."""
    a = _kokler4(metin)
    if len(a) < 2:
        return False
    return any(len(a & b) / len(a) >= esik for b in (_kokler4(x) for x in onceki) if b)


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


def _neden(sat: dict | None, tal: list[dict], ref_n: int, elle: bool, etkinlik: bool = False) -> str:
    L = []
    if elle:
        L.append("Komisyon incelemede bu madde için belge istedi (listenin başındakiler).")
    if etkinlik:
        L.append("Bölümün etkinlikleri adıyla listelendi: duyurusu olan etkinliğin yapıldığını, yapılan etkinliğin "
                 "değerlendirildiğini gösteren belge ya da etkinliği belli olmayan fotoğrafın notu isteniyor.")
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
                 oneriler: list[dict] | None = None, kurum: dict | None = None,
                 ornekler: list[dict] | None = None, karsilama=None,
                 etkinlik: list[dict] | None = None) -> list[dict]:
    """Ölçüt başına bir sade satır (öncelik sırasıyla). Her satırda `maddeler`: [{metin, kimden, tur,
    dosyada}]. `kurum`: kurum belge kataloğu eşlemesi (`katalog_esle.esleme_oku`); ilgili belgeler madde
    olur. `ornekler`: kılavuz eki örnek uygulamaları (`ornekler_yukle`; vars. paket verisi).
    `karsilama` (`karsilama.Karsilama`): kurum belgesi dosyada (herhangi bir ölçütte) kabul edilmişse
    istenmez. `etkinlik` (`etkinlik.etkinlik_istekleri`): etkinlik adıyla istekler (elle isteklerden
    sonra). Geçen yılın dosyada karşılığı bulunan (`karsilama`lı) belgesi kendi satırında, işaretli (☑)
    durur; "Var olan kanıt" hücresinde karşılayan belge (`bulundu`, `dosyada`). Dosyadaki kurum belgeleri
    (`karsilanan`) ve kısmen dolu yuvanın zayıf kanıtı da "Var olan kanıt" sütununda gösterilir."""
    from .katalog_esle import madde_metni, olcut_belgeleri
    k_by = olcut_belgeleri(kurum)
    k_hepsi = list((kurum or {}).get("ogeler") or [])
    somut = somut or Somut()
    oneriler = oneriler if oneriler is not None else oneriler_yukle()
    ornekler = ornekler if ornekler is not None else ornekler_yukle()
    istekler = istekler or []
    fark = (int(yil) - int(ref_yil)) if yil and ref_yil else 0
    sat_by = {s["olcut"]: s for s in satirlar}
    tal_by: dict[str, list[dict]] = {}
    for t in talepler:
        tal_by.setdefault(t["olcut"], []).append(t)
    ref_by: dict[str, list[dict]] = {}
    kap_by: dict[str, list[dict]] = {}           # dosyada karşılığı bulunan geçen yıl belgeleri: işaretli satır
    for g in gecen:
        if g.get("durum") in (YOK, ESKI):
            ref_by.setdefault(g["olcut"], []).append(g)
        elif g.get("karsilama"):
            kap_by.setdefault(g["olcut"], []).append(g)
    ist_by: dict[str, list[dict]] = {}
    for x in istekler:
        ist_by.setdefault(_madde_anahtar(x["madde"], cs), []).append(x)
    etk_by: dict[str, list[dict]] = {}
    for x in etkinlik or []:
        etk_by.setdefault(x["olcut"], []).append(x)

    out = []
    for cid in sorted(set(tal_by) | set(ist_by) | set(etk_by) | set(kap_by),
                      key=lambda c: (c == "Genel", _guvenli_key(c))):
        tal = sorted(tal_by.get(cid, []), key=lambda t: -t["puan"])
        sat = sat_by.get(cid)
        if sat is not None:
            sat = {**sat, "eksik_asamalar": [h for h in sat.get("eksik_kod") or [] if h in ASAMA_SADE]}
        maddeler: list[dict] = []

        kismen = (sat or {}).get("kismen_yuvalar") or {}
        karsilanan: list[str] = []

        def ekle(metin: str, kimden: str, tur: str, dosyada: str = "", bulundu: bool = False):
            metin = _yil(metin, yil)
            if metin and metin not in {m["metin"] for m in maddeler}:
                maddeler.append({"metin": metin, "kimden": kimden, "tur": tur,
                                 **({"dosyada": dosyada} if dosyada else {}), **({"bulundu": True} if bulundu else {})})

        def kismen_notu(ys) -> str:
            xs = [x for y in ys for x in kismen.get(y, [])]
            return ("kısmen: " + "; ".join(f"«{x}»" for x in dict.fromkeys(xs)) + " (tek soru ya da kısa alıntı)"
                    if xs else "")

        # 1. elle istekler; etkinlik adıyla istekler
        ist = ist_by.get(cid, [])
        for x in ist:
            ekle(x["metin"], x["kimden"] or sor.kim(olcut=cid if cid[:1] in "ABCDE" else None), "elle")
        etk = etk_by.get(cid, [])
        for x in etk:
            ekle(x["metin"], x["kimden"], "etkinlik", x.get("dosyada") or "")
        # 2. geçen yılın karşılığı bulunamayan belgeleri
        refs = ref_by.get(cid, [])
        k_ref: list[dict] = []                 # geçen yılın kurum belgesi kataloğda bulundu: bağlantısıyla
        if k_hepsi:
            kalan = []
            for g in refs:
                o = katalog_karsiligi(g, k_hepsi)
                (kalan if o is None else k_ref).append(g if o is None else o)
            refs = kalan
        dersler: dict[str, list[dict]] = {}
        kalan = []
        for g in refs:
            k = _ders_anahtari(g)
            (dersler.setdefault(k, []) if k else kalan).append(g)
        refs = kalan
        for k, xs in dersler.items():
            ekle(ders_istegi(k, xs, yil), _kim_ref(sor, xs[0], cid), "gecen")
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
        # 2b. geçen yılın dosyada karşılığı bulunan belgeleri: isteğin kendi satırı, işaretli (☑)
        kap_ders: dict[str, list[dict]] = {}
        for g in kap_by.get(cid, []):
            k = _ders_anahtari(g)
            if k:
                kap_ders.setdefault(k, []).append(g)
                continue
            ad = g.get("kanit_adi") or ""
            m = (f"«{ad}» belgesinin bu yılki ({yil or 'güncel'}) hâli (geçen yılki raporda vardı)" if g.get("tekrarlayan")
                 else f"«{ad}» ya da güncel hâli (geçen yılki raporda vardı)")
            ekle(m, _kim_ref(sor, g, cid), "gecen", _kapali_not([g]), bulundu=True)
        for k, xs in kap_ders.items():
            ekle(ders_istegi(k, xs, yil), _kim_ref(sor, xs[0], cid), "gecen", _kapali_not(xs), bulundu=True)
        # 3–4. karşılanmamış kılavuz maddeleri: önce komisyon önerileri, sonra somut karşılıklar
        ref_yuva = {y for t in tal if t["kaynak"].startswith("geçen yıl") for y in _yuva_ids(t["yuvalar"])}
        acik = [y for y in (sat or {}).get("karsilanmamis_yuvalar") or []]
        puan = {y: max((t["puan"] for t in tal if y in _yuva_ids(t["yuvalar"])), default=0) for y in acik}
        sira = sorted((y for y in acik if y not in ref_yuva),
                      key=lambda y: (-puan[y], int(y.rsplit("/", 1)[1])))
        n_klv, kapsanan, yazilan = 0, set(), set()
        for o in sorted((o for o in oneriler if set(o["yuvalar"]) & set(sira)),
                        key=lambda o: min(sira.index(y) for y in o["yuvalar"] if y in sira)):
            if n_klv >= KILAVUZ_EN_COK:
                break
            y0 = next(y for y in sira if y in o["yuvalar"])
            n0 = len(maddeler)
            ekle(o["metin"], o["kimden"] or _kim(sor, tags, somut, y0, cid), "oneri", kismen_notu(o["yuvalar"]))
            if len(maddeler) > n0:
                n_klv += 1
                kapsanan |= set(o["yuvalar"])
                yazilan |= set(o["yuvalar"])
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
                ekle(x, _kim(sor, tags, somut, y, cid), "kilavuz", kismen_notu([y]))
                n_klv += len(maddeler) > n0
                if len(maddeler) > n0:
                    yazilan.add(y)
        # 4b. kılavuz ekinin örnek uygulamaları: karşılanmamış yuvaya eşlenmiş, önceki maddelerle örtüşmeyen;
        # önce listede henüz karşılığı olmayan yuvalarınkiler, sonra yuvanın önceliği, sonra şablon sırası
        aday = [o for o in ornekler if o["sade"] and set(o["yuvalar"]) & set(sira)]
        aday.sort(key=lambda o: (all(y in yazilan for y in o["yuvalar"] if y in sira),
                                 min(sira.index(y) for y in o["yuvalar"] if y in sira)))
        n_orn, orn_yazilan = 0, set()
        for o in aday:
            if n_orn >= ORNEK_EN_COK:
                break
            hep_yazili = all(y in yazilan for y in o["yuvalar"] if y in sira)
            if _ortusur(o["uygulama"], [m["metin"] for m in maddeler],
                        ORNEK_ORTUSME_YAZILAN if hep_yazili else ORNEK_ORTUSME):
                continue
            y0 = next(y for y in sira if y in o["yuvalar"])
            n0 = len(maddeler)
            ekle(ornek_metni(o), _kim(sor, tags, somut, y0, cid), "ornek")
            if len(maddeler) > n0:
                n_orn += 1
                orn_yazilan.add(o["id"])
        # 5. kurumun bu maddeyle ilgili belgeleri (katalog eşlemesi; geçen yıl kullanılanlar önce)
        from bidr.audit.savunma import BOLUM_SURECI_MADDELERI
        kb = [o for o in {o["id"]: o for o in k_ref + k_by.get(cid, [])}.values()
              if (o.get("tur") or "") in KURUM_TURLER
              and not (o.get("tur") == "is_akisi" and cid in BOLUM_SURECI_MADDELERI)]
        if karsilama is not None:               # kurum belgesi dosyada (herhangi bir ölçütte) kabul edilmiş
            kalan = []
            for o in kb:
                k = karsilama.kurum(o, cid)
                if k:
                    karsilanan.append(f"«{madde_metni(o)}»: dosyada {k['metin']}")
                else:
                    kalan.append(o)
            kb = kalan
        if sat is not None and not sat.get("kendi_kanit_sayisi", sat.get("kanit_sayisi", 0)):
            # bölümün kendi kanıtı yok: kurumun bu maddedeki düzenlemesi adıyla istenir (kurum listesinden çıkar)
            n_ist, kalan = 0, []
            for o in sorted(kb, key=lambda o: KURUM_ISTEK_TURLER.index(o["tur"]) if o.get("tur") in KURUM_ISTEK_TURLER
                            else len(KURUM_ISTEK_TURLER)):
                if n_ist < KURUM_ISTEK_EN_COK and o.get("tur") in KURUM_ISTEK_TURLER:
                    n0 = len(maddeler)
                    ekle(kurum_istegi(o), sor.kim(belge_turu=o.get("tur"), olcut=cid), "kurum_istek")
                    n_ist += len(maddeler) > n0
                else:
                    kalan.append(o)
            kb = kalan
        n_kur = 0
        for o in kb:
            if n_kur >= KURUM_EN_COK:
                ekle(f"… ve kurumun bu maddeyle ilgili {len(kb) - n_kur} belgesi daha var (kurumun mevzuat ve kalite sayfalarında)",
                     sor.kim(belge_turu=o.get("tur"), olcut=cid), "kurum")
                break
            n0 = len(maddeler)
            ekle(madde_metni(o), sor.kim(belge_turu=o.get("tur"), olcut=cid), "kurum")
            n_kur += len(maddeler) > n0
        # öncelik, gerekçe, durum, var olan kanıt
        oto = _oncelik(tal[0]["puan"]) if tal else DUSUK
        onc = min([oto] + [x["oncelik"] for x in ist + etk], key=SIRA.get)
        kanitsiz = bool(sat) and sat.get("kanit_sayisi", 0) == 0
        ks = list((sat or {}).get("kanitlar") or [])
        dosyada = ("; ".join(ks[:ELDE_EN_COK])
                   + (f" ve {len(ks) - ELDE_EN_COK} belge daha" if len(ks) > ELDE_EN_COK else "")) if ks else ""
        karsilanan = list(dict.fromkeys(karsilanan))
        ornek = list(dict.fromkeys(t["ornek"] for t in tal if t.get("ornek") and not t["kaynak"].startswith("geçen")))
        gecen_yil = "; ".join(ornek[:3])
        notlar = ([f"Dosyada olanlar: {dosyada}"] if dosyada else []) + (
            [f"Geçen yıl bu amaçla kullanılan: {gecen_yil}"] if gecen_yil else []) + (
            [f"Dosyada karşılığı olduğu için istenmeyen: {x}" for x in karsilanan])
        klv_metin = [_yuva_metni(cs, y) for y in sorted(acik, key=lambda y: int(y.rsplit("/", 1)[1]))]
        # kılavuz ekinin bu maddenin karşılanmamış yuvalarına eşlenmiş, listeye alınmamış örnek uygulamaları
        ek = [o for o in ornekler if o["sade"] and o["id"] not in orn_yazilan and set(o["yuvalar"]) & set(acik)]
        klv_ek = [f"{_kisalt(o['uygulama'])} ({_kisalt(o['kanit'], 50)})" for o in ek[:ORNEK_KLV_EN_COK]]
        if len(ek) > ORNEK_KLV_EN_COK:
            klv_ek.append(f"… ve {len(ek) - ORNEK_KLV_EN_COK} örnek daha")
        # kurum mevzuatı/iş akışları ayrı liste: ana listede tek işaretlenebilir satır olur (bkz. write_xlsx)
        kurum_m = [m for m in maddeler if m["tur"] == "kurum"]
        maddeler = [m for m in maddeler if m["tur"] != "kurum"]
        out.append({
            "olcut": cid, "madde": _madde_ad(cs, cid), "oncelik": onc, "maddeler": maddeler,
            "belgeler": "\n".join(f"• {m['metin']}" for m in maddeler),
            "kurum": kurum_m, "kurum_n": len(kb),
            "kurum_belgeler": "\n".join(f"• {m['metin']}" for m in kurum_m),
            "durum": HIC if kanitsiz else EKSIK if onc == YUKSEK else AZ,
            "neden": _neden(sat, tal, len(refs), bool(ist), bool(etk)),
            "kimden": "\n".join(list(dict.fromkeys(m["kimden"] for m in maddeler + kurum_m if m["kimden"]))[:3]),
            "kilavuz": "\n\n".join(x for x in (
                ("Kılavuzun bu madde için örnek verdiği, henüz karşılanmamış belgeler:\n"
                 + "\n".join(f"• {x}" for x in klv_metin)) if klv_metin else "",
                ("Kılavuz ekindeki örnek uygulamalar (uygulama ve olası kanıt):\n"
                 + "\n".join(f"• {x}" for x in klv_ek)) if klv_ek else "") if x),
            "dosyada": dosyada, "karsilanan": karsilanan, "gecen_yil": gecen_yil, "not": "\n".join(notlar),
            "ornek_idler": sorted(orn_yazilan, key=lambda i: (i[0], int(i.split("/")[1]))),
            "_anahtar": (SIRA[onc], not kanitsiz, -(tal[0]["puan"] if tal else 0), _guvenli_key(cid)),
        })
    out.sort(key=lambda r: r["_anahtar"])
    for i, r in enumerate(out, 1):
        r["sira"] = i
        del r["_anahtar"]
    return out


def kurum_istegi(o: dict) -> str:
    """Kurumun düzenlemesini adıyla isteyen madde: belge adı (kod), türü ve bölümün uygulamasından bir örnek."""
    from .katalog import TUR_AD
    from .katalog_esle import madde_metni
    tur = TUR_AD.get(o.get("tur") or "", "")
    return (f"Kurumun «{madde_metni(o)}» belgesi{f' ({tur.lower()})' if tur else ''} ve bölümün bu düzenlemeyi "
            "nasıl uyguladığını gösteren bir örnek")


def _kapali_not(xs: list[dict]) -> str:
    """Kapanan geçen yıl isteğinin "Var olan kanıt" notu: karşılayan belge(ler) ve ölçütü."""
    ms = list(dict.fromkeys(g["karsilama"]["metin"] for g in xs))
    return "Dosyada var: " + "; ".join(ms)


def _sozcukler(s: str) -> set[str]:
    from .tablolar import norm
    return {w[:5] for w in re.findall(r"[a-z0-9]+", norm(s)) if len(w) > 2 and w not in _DOLGU}


def katalog_karsiligi(g: dict, ogeler: list[dict]) -> dict | None:
    """Geçen yılın kurum geneli belgesinin (yönetmelik, yönerge, iş akışı…) katalogdaki karşılığı:
    addaki doküman kodu, yoksa ad sözcük köklerinin (ilk 5 harf) örtüşmesi (kısa adın ≥ %80'i ve
    Jaccard ≥ 0,5)."""
    if g.get("belge_turu") not in KURUM_REF_TURLER:
        return None
    from .katalog import kod_bul
    ad = g.get("kanit_adi") or ""
    kod = kod_bul(ad)
    if kod:
        o = next((o for o in ogeler if o.get("kod") == kod), None)
        if o is not None:
            return o
    a = _sozcukler(ad)
    if len(a) < 2:
        return None
    best, bs = None, 0.0
    for o in ogeler:
        b = _sozcukler(o.get("ad") or "")
        if len(b) < 2:
            continue
        ort = len(a & b)
        sk = ort / min(len(a), len(b))
        jc = ort / len(a | b)
        if sk >= 0.8 and jc >= 0.5 and (sk + jc) > bs:
            best, bs = o, sk + jc
    return best


_ETIKET: dict[str, str] = {}


def _ders_anahtari(g: dict) -> str | None:
    """Derse özgü geçen yıl belgesinin tür anahtarı (tekrarlayan tür ya da belge türü grubu); değilse None."""
    if not DERS_KODU.search(g.get("kanit_adi") or ""):
        return None
    bt = g.get("belge_turu") or ""
    return g.get("tekrarlayan") or DERS_GRUP.get(bt, bt) or "belge"


def ders_istegi(k: str, xs: list[dict], yil=None) -> str:
    """Derse özgü geçen yıl belgeleri (aynı tür) → tür düzeyinde tek istek; geçen yılki belgeler örnek."""
    x0 = xs[0]
    ifade = DERS_IFADE.get(k) or ((x0.get("tekrarlayan_ad") or "").lower() if k == x0.get("tekrarlayan")
                                  else _tur_etiketi(k)) or "belge"
    zaman = f"{int(yil) - 1}-{int(yil)}" if any(x.get("tekrarlayan") for x in xs) and str(yil or "").isdigit() \
        else "güncel"
    ornek = "; ".join(f"«{x.get('kanit_adi') or ''}»" for x in xs[:DERS_ORNEK_EN_COK])
    if len(xs) > DERS_ORNEK_EN_COK:
        ornek += f" ve {len(xs) - DERS_ORNEK_EN_COK} belge daha"
    bas = "Herhangi bir dersin" if len(xs) == 1 else "En az bir ders için"
    m = f"{bas} {ifade} ({zaman}) (geçen yıl örnek: {ornek})"
    if any(x.get("durum") == ESKI for x in xs):
        m += "; elde yalnız eski sürümü var"
    return m


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
    """Kişi/birim × madde başına istekler (eski "Kime gönderilecek" sayfasının içeriği; yeni dosyada bu bilgi
    her belge satırının «Kimden» hücresindedir)."""
    by: dict[tuple, list[str]] = {}
    for r in rows:
        for m in r["maddeler"] + r.get("kurum", []):
            by.setdefault((m["kimden"] or "Belirtilmedi", r["sira"]), []).append(m["metin"])
    rs = {r["sira"]: r for r in rows}
    out = [{"kimden": k, "madde": rs[s]["madde"], "oncelik": rs[s]["oncelik"],
            "belgeler": "\n".join(f"• {x}" for x in xs), "_s": s} for (k, s), xs in by.items()]
    out.sort(key=lambda x: (x["kimden"], x["_s"]))
    return out


def kurum_satiri(n: int) -> str:
    return f"Kurumun ilgili {n} yönerge/form/iş akışı (adları sağdaki ayrıntı sütununda)"


def belge_satirlari(r: dict) -> list[dict]:
    """Maddenin işaretlenebilir satırları: her istenen belge bir satır; kurum belgeleri tek satır."""
    xs = [{"metin": m["metin"], "kimden": m["kimden"], "dosyada": m.get("dosyada") or "",
           "bulundu": bool(m.get("bulundu"))} for m in r["maddeler"]]
    if r.get("kurum"):
        xs.append({"metin": kurum_satiri(r.get("kurum_n") or len(r["kurum"])), "kurum": True,
                   "kimden": "\n".join(dict.fromkeys(m["kimden"] for m in r["kurum"] if m["kimden"]))})
    return xs or [{"metin": "—", "kimden": r.get("kimden") or ""}]


def dosyada_hucresi(r: dict, bel: dict, ilk: bool) -> str | None:
    """"Var olan kanıt" hücresi: ilk satırda maddenin dosyadaki kanıtları; kurum belgeleri satırında (yoksa ilk
    satırda) karşılığı dosyada olduğu için istenmeyen kurum belgeleri; her satırda o isteği karşılayan, kısmen
    karşılayan (ya da etkinliğin) belge."""
    xs = []
    if ilk:
        xs.append(r.get("dosyada") or "—")
    if bel.get("kurum") or (ilk and not r.get("kurum")):
        xs += [f"İstenmedi (dosyada var): {x}" for x in r.get("karsilanan") or []]
    if bel.get("dosyada"):
        xs.append(f"Bu istek için: {bel['dosyada']}")
    return "\n".join(xs) if xs else None


def _madde_kisa(madde: str) -> str:
    return madde.replace(" — ", " ", 1)


def _bolum(cid: str) -> str:
    return BOLUM.get(cid[:1], BOLUM_GENEL) if re.match(r"[A-E]\.", cid) else BOLUM_GENEL


# -- xlsx ---------------------------------------------------------------------------------------

def _satir_say(v, w: float) -> int:
    if v is None:
        return 1
    return sum(max(1, -(-len(p) // max(1, int(w * 1.05)))) for p in str(v).split("\n"))


def write_xlsx(path: Path, rows: list[dict], *, baslik: str = "") -> Path:
    """Tek sayfa: üstte renk açıklaması ve formüllü özet; madde başına belge satırları (☐/☑), Durum formülü;
    sağda katlanabilir ayrıntı sütunları; altta "nasıl okunur" notu."""
    from openpyxl import Workbook
    from openpyxl.formatting.rule import Rule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.styles.differential import DifferentialStyle
    from openpyxl.utils import get_column_letter as L
    from openpyxl.worksheet.datavalidation import DataValidation

    FONT = "Calibri"

    def fill(c):
        return PatternFill("solid", fgColor=c)

    H = BASLIK_SATIRI
    ncol = len(COLS)
    widths = [w for _, _, w in COLS]
    ince = Side(style="thin", color="BFBFBF")
    kutu = Border(left=ince, right=ince, top=ince, bottom=ince)
    ust = Alignment(wrap_text=True, vertical="top")
    detay_font = Font(name=FONT, sz=9, color="595959")
    soluk = Font(name=FONT, sz=9, color="A6A6A6")
    wb = Workbook()
    ws = wb.active
    ws.title = SHEETS[0]
    # 1: renk açıklaması
    ws["A1"] = "Renkler:"
    ws["A1"].font = Font(name=FONT, b=True)
    for col, ad in zip("CDEFHI", (HIC, EKSIK, AZ, KISMEN, TAMAM, f"{DOLU} bulunan belge")):
        c = ws[f"{col}1"]
        c.value, c.fill = ad, fill(DURUM_RENK.get(ad, BULUNDU_RENK))
        c.font = Font(name=FONT, b=True, sz=10)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 22
    # 3: kullanım notu
    ws["A3"] = UST_NOT
    ws["A3"].font = Font(name=FONT, i=True, sz=9, color="595959")
    ws.merge_cells(f"A3:{L(N_ANA)}3")
    ws["A3"].alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[3].height = 30
    # 4: başlık
    for i, (_, h, w) in enumerate(COLS, 1):
        c = ws.cell(H, i, h)
        ana = i <= N_ANA
        c.fill = fill("305496" if ana else "8EA9DB")
        c.font = Font(name=FONT, b=True, sz=11 if ana else 9, color="FFFFFF")
        c.alignment = Alignment(vertical="center", wrap_text=True, horizontal="center" if i == 2 else None)
        c.border = kutu
        ws.column_dimensions[L(i)].width = w
        if not ana:     # sütun sütun: column_dimensions.group() genişlikleri ilk sütuna indiriyor
            ws.column_dimensions[L(i)].outline_level = 1
    ws.row_dimensions[H].height = 30
    eff = [w if i < N_ANA else w * 1.25 for i, w in enumerate(widths)]
    dv = DataValidation(type="list", formula1=f'"{BOS},{DOLU}"', allow_blank=False, showDropDown=False)
    dv.promptTitle, dv.prompt, dv.showInputMessage = "Bulundu mu?", f"{DOLU} = belge bulundu", True
    ws.add_data_validation(dv)
    r, bolum, istek_say = H + 1, None, 0
    sirali = sorted(rows, key=lambda x: (x["olcut"] == "Genel", _guvenli_key(x["olcut"])))
    for x in sirali:
        b = _bolum(x["olcut"])
        if b != bolum:
            bolum = b
            for i in range(1, ncol + 1):
                c = ws.cell(r, i)
                c.fill, c.border = fill("D9E1F2"), kutu
            ws.cell(r, 1, b).font = Font(name=FONT, b=True, sz=12, color="1F3864")
            ws.row_dimensions[r].height = 20
            r += 1
        bs = belge_satirlari(x)
        r0, r1 = r, r + len(bs) - 1
        rng = f"$B${r0}:$B${r1}"
        n_ok = f'COUNTIF({rng},"{DOLU}")'
        durum_f = (f'=IF({n_ok}=ROWS({rng}),"{TAMAM}",IF({n_ok}>0,"{KISMEN}","{x["durum"]}"))'
                   f'&" · "&{n_ok}&"/"&ROWS({rng})&" bulundu"')
        madde = _madde_kisa(x["madde"])
        det = [x["oncelik"], x["neden"] or "—", x.get("gecen_yil") or "—", x.get("kurum_belgeler") or "—",
               x["kilavuz"] or "—", x["sira"]]
        for j, bel in enumerate(bs):
            rr, ilk = r0 + j, j == 0
            vals = [madde, DOLU if bel.get("bulundu") else BOS, durum_f if ilk else None, bel["metin"],
                    bel["kimden"] or None,
                    dosyada_hucresi(x, bel, ilk)]
            for i, v in enumerate(vals + (det if ilk else [None] * len(det)), 1):
                c = ws.cell(rr, i, v)
                c.alignment, c.border = ust, kutu
                c.font = Font(name=FONT, sz=11) if i <= N_ANA else detay_font
            c = ws.cell(rr, 2)
            c.alignment, c.font = Alignment(horizontal="center", vertical="top"), Font(name=FONT, sz=14)
            dv.add(c)
            istek_say += 1
            if ilk:
                for i in (1, 3):
                    ws.cell(rr, i).fill = fill(DURUM_RENK[x["durum"]])
                ws.cell(rr, 1).font = Font(name=FONT, b=True, sz=11)
                ws.cell(rr, 3).font = Font(name=FONT, b=True, sz=10)
                mh = max(_satir_say(v, w) for v, w in zip(vals, eff[:N_ANA])) * 15 + 4
                dh = max(_satir_say(v, w) for v, w in zip(det, eff[N_ANA:])) * 12 + 4
                mh = max(mh, min(dh, 100 if len(bs) > 1 else max(mh * 1.6, 60)))
            else:
                ws.cell(rr, 1).font = soluk
                mh = max(_satir_say(vals[3], eff[3]), _satir_say(vals[4], eff[4]),
                         _satir_say(vals[5], eff[5])) * 15 + 4
            ws.row_dimensions[rr].height = min(409, mh)
        r = r1 + 1
    son = max(r - 1, H + 1)
    B = f"$B${H + 1}:$B${son}"
    ws["A2"] = (f'="Toplam istek: "&(COUNTIF({B},"{BOS}")+COUNTIF({B},"{DOLU}"))&"     Bulunan: "&COUNTIF({B},"{DOLU}")'
                f'&"     Kalan: "&COUNTIF({B},"{BOS}")&"     ·     Tamamlanan madde: "'
                f'&COUNTIF($C${H + 1}:$C${son},"{TAMAM}*")&" / {len(rows)}"')
    ws["A2"].font = Font(name=FONT, b=True, sz=12, color="1F3864")
    ws.merge_cells(f"A2:{L(N_ANA)}2")
    ws["A2"].alignment = Alignment(vertical="center")
    ws.row_dimensions[2].height = 22

    def dx(renk, **f):
        return DifferentialStyle(fill=PatternFill("solid", bgColor=renk, fgColor=renk), font=Font(**f) if f else None)

    a, z = H + 1, son
    cf = ws.conditional_formatting
    cf.add(f"D{a}:D{z}", Rule(type="expression", dxf=dx(BULUNDU_RENK, strike=True, color="808080"),
                              formula=[f'$B{a}="{DOLU}"']))
    for col in "BEF":
        cf.add(f"{col}{a}:{col}{z}", Rule(type="expression", dxf=dx(BULUNDU_RENK), formula=[f'$B{a}="{DOLU}"']))
    cf.add(f"A{a}:A{z} C{a}:C{z}", Rule(type="expression", dxf=dx(DURUM_RENK[TAMAM]),
                                        formula=[f'LEFT($C{a},{len(TAMAM)})="{TAMAM}"'], stopIfTrue=True))
    cf.add(f"A{a}:A{z} C{a}:C{z}", Rule(type="expression", dxf=dx(DURUM_RENK[KISMEN]),
                                        formula=[f'LEFT($C{a},{len(KISMEN.split()[0])})="{KISMEN.split()[0]}"']))
    ws.freeze_panes = f"C{H + 1}"
    ws.auto_filter.ref = f"A{H}:{L(ncol)}{son}"
    r += 1
    ws.cell(r, 1, f"Toplam {len(rows)} madde, {istek_say} istek").font = Font(name=FONT, b=True)
    r += 2
    for k, t in enumerate(NASIL):
        c = ws.cell(r, 1, t)
        c.font = Font(name=FONT, sz=9, color="595959", b=k == 0)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=N_ANA)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = _satir_say(t, 180) * 13 + 4
        r += 1
    ws.print_title_rows = f"{H}:{H}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.4
    if baslik:
        ws.oddHeader.center.text = baslik
    ws.oddFooter.right.text = "Sayfa &P / &N"
    ws.sheet_view.zoomScale = 110
    wb.calculation.fullCalcOnLoad = True
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# -- bilgi kaybı denetimi ------------------------------------------------------------------------

def oku_xlsx(path: Path) -> dict:
    """`write_xlsx` çıktısını geri okur: madde bloğu → satırlar; altındaki notlar."""
    from openpyxl import load_workbook
    ws = load_workbook(path)[SHEETS[0]]
    bloklar: dict[str, list[list]] = {}
    notlar: list[str] = []
    bitti = False
    for row in ws.iter_rows(min_row=BASLIK_SATIRI + 1, max_col=len(COLS), values_only=True):
        a = row[0]
        if bitti:
            if a:
                notlar.append(str(a))
            continue
        if isinstance(a, str) and re.match(r"Toplam \d+ madde, \d+ istek$", a):
            bitti = True
            notlar.append(a)
            continue
        if a is None or row[1] not in (BOS, DOLU):
            continue                                  # bölüm ayracı / boş satır
        bloklar.setdefault(str(a), []).append(list(row))
    return {"bloklar": bloklar, "notlar": notlar}


def bilgi_denetimi(rows: list[dict], path: Path) -> list[str]:
    """Eski biçimin (ölçüt başına satır + "Kime gönderilecek" + "Nasıl okunur") her hücre bilgisinin yeni
    dosyada bulunup bulunmadığı. Bulunamayanların listesi (boşsa kayıp yok)."""
    x = oku_xlsx(path)
    bl, eksik = x["bloklar"], []
    idx = {k: i for i, (k, _, _) in enumerate(COLS)}

    def satirlar(v):
        return [s for s in str(v or "").split("\n") if s]

    for r in rows:
        ad = _madde_kisa(r["madde"])
        b = bl.get(ad)
        if not b:
            eksik.append(f"madde: {r['madde']}")
            continue
        ilk = b[0]
        D = [s[idx["belge"]] for s in b]
        E = {e for s in b for e in satirlar(s[idx["kimden"]])}
        J = satirlar(ilk[idx["kurum_belgeler"]])
        for etiket, deger, hucre in (("sıra", r["sira"], ilk[idx["sira"]]),
                                     ("öncelik", r["oncelik"], ilk[idx["oncelik"]]),
                                     ("gerekçe", r["neden"] or "—", ilk[idx["neden"]]),
                                     ("kılavuz", r["kilavuz"] or "—", ilk[idx["kilavuz"]])):
            if deger != hucre:
                eksik.append(f"{ad} {etiket}: {deger!r}")
        if not str(ilk[idx["durum"]] or "").count(f'"{r["durum"]}"'):
            eksik.append(f"{ad} durum: {r['durum']}")
        for m in r["maddeler"]:
            if m["metin"] not in D:
                eksik.append(f"{ad} istek: {m['metin']}")
        for m in r.get("kurum", []):
            if f"• {m['metin']}" not in J:
                eksik.append(f"{ad} kurum belgesi: {m['metin']}")
        if r.get("kurum") and kurum_satiri(r.get("kurum_n") or len(r["kurum"])) not in D:
            eksik.append(f"{ad} kurum satırı")
        for k in satirlar(r["kimden"]):
            if k not in E:
                eksik.append(f"{ad} kimden: {k}")
        for n in satirlar(r["not"]):
            for on, col in (("Dosyada olanlar: ", "dosyada"), ("Geçen yıl bu amaçla kullanılan: ", "gecen_yil")):
                if n.startswith(on) and n[len(on):] != (satirlar(ilk[idx[col]]) or [None])[0]:
                    eksik.append(f"{ad} not: {n}")
            on = "Dosyada karşılığı olduğu için istenmeyen: "
            if n.startswith(on) and not any(f"İstenmedi (dosyada var): {n[len(on):]}" in satirlar(s[idx["dosyada"]])
                                            for s in b):
                eksik.append(f"{ad} not: {n}")
    # kişi sayfası: (kimden, madde, istek) üçlüsü aynı satırda (kurum belgeleri: kurum satırında)
    by_sira = {r["sira"]: r for r in rows}
    for k in kime_gore(rows):
        r = by_sira[k["_s"]]
        b = bl.get(_madde_kisa(r["madde"])) or []
        kurum = {m["metin"] for m in r.get("kurum", [])}
        for s in satirlar(k["belgeler"]):
            metin = s[2:]
            hedef = kurum_satiri(r.get("kurum_n") or len(r.get("kurum") or [])) if metin in kurum else metin
            ok = any(row[idx["belge"]] == hedef and (k["kimden"] == "Belirtilmedi" and not row[idx["kimden"]]
                                                       or k["kimden"] in satirlar(row[idx["kimden"]])) for row in b)
            if not ok:
                eksik.append(f"kişi: {k['kimden']} / {r['madde']} / {metin}")
    for t in NASIL:
        if t not in x["notlar"]:
            eksik.append(f"nasıl okunur: {t[:60]}")
    return eksik
