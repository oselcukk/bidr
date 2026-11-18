"""`bidr labels build`: kaynak klasördeki her dosya için insan etiketlerini çıkarır.

Etiket kaynakları:
  klasor  — yol bileşenlerindeki ölçüt kodları (A.1.4, B1.5, A.1. Liderlik…, A.1.4- 2-OD3] …)
  ad      — dosya adının başındaki kod (A.1.2 …, [A.1.2-2-OD5] …, [1.OD4] … → ölçüt klasörden)
  rapor   — aynı birimdeki BİDR raporunun (docx) "Kanıtlar:" satırları, dosyaya eşlenebildiyse

Kayıt anahtarı içerik kimliğidir (doc_id). Aynı içerik birden çok yerdeyse etiketler
birleşir. Göreli yollar yalnız iz sürmek içindir; sınıflandırıcıya verilmez.
"""
from __future__ import annotations

import fnmatch
import os
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from bidr.common import doc_id as hesapla_doc_id

from .parse import ALT, DUZEY_SIRASI, RaporKaniti, ad_benzerlik, ad_kodu, ad_normal
from .report import rapor_kanitlari

SF_DATALESS = 0x40000000  # macOS: iCloud dosyası yerelde yok (indirilmemiş)
KOK_BIRIM = "(kök)"
RAPOR_ADI = re.compile(r"(FR-0833|B[İI]DR)", re.I)

ESIK_AD = 0.85        # yalnız ada dayalı eşleşme için en düşük benzerlik
ESIK_KOD_AD = 0.5     # kod tuttuğunda adın en az bu kadar benzemesi
YAKIN_FARK = 0.02     # en iyi iki aday bu kadar yakınsa ad tek başına karar vermez


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


@dataclass
class Dosya:
    yol: str                      # kaynak köküne göre, NFC, '/' ayraçlı
    mutlak: Path
    birim: str
    durum: str = "ok"             # ok | indirilmemis | okunamadi
    doc_id: str | None = None
    boyut: int | None = None
    etiket_disi: bool = False     # --etiketsiz kalıbına uyuyor: yoldan/addan/rapordan etiket alınmaz
    rapor: bool = False           # BİDR raporu dosyası (kanıt değil)
    kanitlar: list[dict] = field(default_factory=list)
    anahtarlar: set = field(default_factory=set)   # (ölçüt, kanıt_no)
    sorunlar: list[dict] = field(default_factory=list)

    @property
    def kayit(self) -> str:
        return f"doc:{self.doc_id}" if self.doc_id else f"yol:{self.yol}"

    def kod_adlari(self, anahtar: tuple[str, int]) -> list[str]:
        """Bu kodu taşıyan ad(lar): dosya adı ve kodu taşıyan klasör adı."""
        adlar = [self.govde]
        for k in self.kanitlar:
            if k["kaynak"] == "klasor" and (k["olcut"], k.get("kanit_no")) == anahtar:
                adlar.append(k["ham"])
        return adlar

    @property
    def ad(self) -> str:
        return self.yol.rsplit("/", 1)[-1]

    @property
    def govde(self) -> str:
        ad = self.ad
        return ad.rsplit(".", 1)[0] if "." in ad else ad


def birim_adi(klasor: str, takma: dict[str, str]) -> str:
    if klasor in takma:
        return takma[klasor]
    return re.sub(r"\s+Bölümü\s*$", "", klasor).strip() or klasor


def tara(kaynak: Path, birim: str | None, takma: dict[str, str], etiketsiz: list[str]) -> list[Dosya]:
    kaynak = Path(kaynak).expanduser()
    out: list[Dosya] = []
    for kok, dizinler, dosyalar in os.walk(kaynak):
        dizinler[:] = sorted(d for d in dizinler if not d.startswith("."))
        for ad in sorted(dosyalar):
            if ad.startswith(".") or ad.startswith("~$"):
                continue
            p = Path(kok) / ad
            rel = nfc(p.relative_to(kaynak).as_posix())
            if birim:
                b = birim
            else:
                parca = rel.split("/")
                b = birim_adi(parca[0], takma) if len(parca) > 1 else KOK_BIRIM
            d = Dosya(yol=rel, mutlak=p, birim=b)
            d.etiket_disi = any(fnmatch.fnmatch(rel, nfc(g)) for g in etiketsiz)
            d.rapor = p.suffix.lower() in (".docx", ".pdf") and bool(RAPOR_ADI.search(ad))
            try:
                st = p.stat()
                d.boyut = st.st_size
                if getattr(st, "st_flags", 0) & SF_DATALESS:
                    d.durum = "indirilmemis"   # okumak indirmeyi tetikler; dokunmuyoruz
                else:
                    d.doc_id = hesapla_doc_id(p)
            except OSError as e:
                d.durum = "okunamadi"
                d.sorunlar.append({"sorun": "okunamadi", "ayrinti": str(e)})
            out.append(d)
    return out


def yol_etiketleri(d: Dosya) -> None:
    """Klasör ve ad kodlarından etiket kanıtları üretir (d.kanitlar, d.anahtarlar)."""
    if d.etiket_disi:
        return
    parca = d.yol.split("/")
    en_yakin_klasor: dict | None = None
    for derinlik, klasor in enumerate(parca[:-1]):
        k = ad_kodu(klasor, klasor=True)
        if k.sorun:
            d.sorunlar.append({"sorun": k.sorun, "kaynak": "klasor", "ham": klasor})
            continue
        if k.olcut is None:
            continue
        kn = {"kaynak": "klasor", "olcut": k.olcut, "duzey": k.duzey, "od": k.od,
              "kanit_no": k.kanit_no, "ham": klasor}
        d.kanitlar.append(kn)
        en_yakin_klasor = kn
        if k.kanit_no is not None:
            d.anahtarlar.add((k.olcut, k.kanit_no))
    if d.rapor:
        return
    k = ad_kodu(d.govde)
    if k.sorun:
        d.sorunlar.append({"sorun": k.sorun, "kaynak": "ad", "ham": d.ad})
        return
    if k.olcut is not None:
        d.kanitlar.append({"kaynak": "ad", "olcut": k.olcut, "duzey": k.duzey, "od": k.od,
                           "kanit_no": k.kanit_no, "ham": d.ad})
        if k.kanit_no is not None:
            d.anahtarlar.add((k.olcut, k.kanit_no))
    elif k.od is not None or k.kanit_no is not None:
        # "[1.OD4] YÖK YAZISI.pdf": ölçüt yalnız klasörde
        if en_yakin_klasor is None:
            d.sorunlar.append({"sorun": "olcutsuz_od_kodu", "kaynak": "ad", "ham": d.ad})
            return
        d.kanitlar.append({"kaynak": "ad", "olcut": en_yakin_klasor["olcut"],
                           "duzey": en_yakin_klasor["duzey"], "od": k.od, "kanit_no": k.kanit_no,
                           "ham": d.ad, "olcut_klasorden": True})
        if k.kanit_no is not None:
            d.anahtarlar.add((en_yakin_klasor["olcut"], k.kanit_no))


# --- rapor eşleme ----------------------------------------------------------

@dataclass
class Eslesmeyen:
    birim: str
    rapor: str
    bolum: str
    ham: str
    neden: str
    en_yakin: str | None = None
    benzerlik: float | None = None


def _yol_olcutleri(d: Dosya) -> set[str]:
    return {k["olcut"] for k in d.kanitlar if k["kaynak"] in ("klasor", "ad")}


def _kod_catisir(dosyalar: list[Dosya], anahtar: tuple[str, int]) -> bool:
    """Hiçbir kopya bu kodu taşımıyor ama en az biri aynı ölçütte başka numara taşıyor."""
    if any(anahtar in d.anahtarlar for d in dosyalar):
        return False
    return any(o == anahtar[0] for d in dosyalar for (o, _n) in d.anahtarlar)


def rapor_esle(
    kanit: RaporKaniti, hedefler: list[Dosya]
) -> tuple[list[Dosya], str | None, float | None, Eslesmeyen | None]:
    """Bir rapor satırını birimin dosyalarına eşler. (eşleşenler, yöntem, benzerlik, eşleşmeme)."""
    hedef_ad = ad_normal(kanit.ad)
    # rapordaki ada eklenmiş açıklama/not parantezi ("Ders Planı (… HALA AYNISI MI …)") olmadan da dene
    parantezsiz = ad_normal(re.sub(r"\([^)]*(\)|$)", " ", kanit.ad))
    adlar = [a for a in {hedef_ad, parantezsiz} if a]

    def benzer(x: str) -> float:
        return max((ad_benzerlik(a, x) for a in adlar), default=0.0)
    ad_kod = ad_kodu(re.sub(r"^\W+", "", kanit.ad))
    ilgili_olcut = {kanit.bolum}
    if kanit.kod_olcut:
        ilgili_olcut.add(kanit.kod_olcut)
    if ad_kod.olcut and ad_kod.duzey == ALT:
        ilgili_olcut.add(ad_kod.olcut)

    not_kod = None
    kod_ne = None
    anahtar = None
    if kanit.sorun is None and kanit.kanit_no is not None:
        anahtar = (kanit.kod_olcut or kanit.bolum, kanit.kanit_no)
        adaylar = [d for d in hedefler if anahtar in d.anahtarlar]
        if adaylar:
            skor = {id(d): max(benzer(ad_normal(a)) for a in d.kod_adlari(anahtar))
                    for d in adaylar}
            iyi = [d for d in adaylar if not hedef_ad or skor[id(d)] >= ESIK_KOD_AD]
            if iyi:
                return iyi, "kod", round(max(skor[id(d)] for d in iyi), 3), None
            not_kod = "kod_tuttu_ad_tutmadi"
            if hedef_ad:
                en = max(adaylar, key=lambda d: skor[id(d)])
                kod_ne = Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham, not_kod, en.yol,
                                    round(skor[id(en)], 3))

    if not hedef_ad:
        return [], None, None, Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham, "ad_bos")
    skorlar: dict[str, float] = {}
    gruplar: dict[str, list[Dosya]] = defaultdict(list)
    for d in hedefler:
        s = benzer(ad_normal(d.govde))
        gruplar[d.kayit].append(d)
        skorlar[d.kayit] = max(skorlar.get(d.kayit, 0.0), s)
    if not skorlar:
        return [], None, None, Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham, "birimde_dosya_yok")
    sirali = sorted(skorlar.items(), key=lambda x: -x[1])
    en_kayit, en_skor = sirali[0]
    en_yakin = gruplar[en_kayit][0].yol
    if en_skor < ESIK_AD:
        if kod_ne is not None:
            return [], None, None, kod_ne
        return [], None, None, Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham,
                                          not_kod or "ad_eslesmedi", en_yakin, round(en_skor, 3))
    yakin = [k for k, s in sirali if s >= en_skor - YAKIN_FARK]
    secilen, yontem = None, None
    if len(yakin) == 1:
        secilen, yontem = en_kayit, "ad"
    else:
        # birden çok içerik aynı ada yakın: yol etiketi ilgili ölçütü taşıyan tek aday varsa o
        uygun = [k for k in yakin if any(_yol_olcutleri(d) & ilgili_olcut for d in gruplar[k])]
        if len(uygun) == 1:
            secilen, yontem = uygun[0], "ad+olcut"
    if secilen is not None:
        if anahtar is not None and _kod_catisir(gruplar[secilen], anahtar):
            # ad benziyor ama dosya aynı ölçütte başka kanıt numarası taşıyor: ayrı kanıt olabilir
            return [], None, None, Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham, "kod_farkli_ad_benzer",
                                              gruplar[secilen][0].yol, round(skorlar[secilen], 3))
        return gruplar[secilen], yontem, round(skorlar[secilen], 3), None
    return [], None, None, Eslesmeyen("", kanit.rapor, kanit.bolum, kanit.ham, "belirsiz_cok_aday",
                                      ", ".join(gruplar[k][0].yol for k in yakin[:4]), round(en_skor, 3))


# --- birleştirme -----------------------------------------------------------

def _etiketler(kanitlar: list[dict]) -> list[dict]:
    by: dict[str, dict] = {}
    for k in kanitlar:
        e = by.setdefault(k["olcut"], {"olcut": k["olcut"], "duzey": k["duzey"], "od": set(),
                                       "kaynaklar": set(), "kanitlar": []})
        if k.get("od"):
            e["od"].add(k["od"])
        e["kaynaklar"].add(k["kaynak"])
        sade = {a: v for a, v in k.items() if a not in ("olcut", "duzey") and v not in (None, False)}
        if sade not in e["kanitlar"]:
            e["kanitlar"].append(sade)
    out = []
    for oid in sorted(by, key=lambda o: (o.split("."), o)):
        e = by[oid]
        ince = any(o != oid and o.startswith(oid + ".") for o in by)
        out.append({
            "olcut": oid,
            "duzey": e["duzey"],
            "od": sorted(e["od"]),
            "od_celiski": len(e["od"]) > 1,
            "kaynaklar": sorted(e["kaynaklar"]),
            "ince_etiket_var": ince,
            "kanitlar": e["kanitlar"],
        })
    return out


def kayitlar(dosyalar: list[Dosya]) -> list[dict]:
    gruplar: dict[str, list[Dosya]] = defaultdict(list)
    for d in dosyalar:
        gruplar[d.kayit].append(d)
    out = []
    for kayit, ds in gruplar.items():
        kanitlar = []
        for d in ds:
            for k in d.kanitlar:
                kanitlar.append({**k, "yol": d.yol, "birim": d.birim})
        etiketler = _etiketler(kanitlar)
        ilk = ds[0]
        out.append({
            "kayit": kayit,
            "doc_id": ilk.doc_id,
            "durum": ilk.durum,
            "boyut": ilk.boyut,
            "uzanti": Path(ilk.yol).suffix.lower(),
            "birimler": sorted({d.birim for d in ds}),
            "kopya_sayisi": len(ds),
            "rapor_dosyasi": all(d.rapor for d in ds),
            "etiket_disi": all(d.etiket_disi for d in ds),
            "etiketli": bool(etiketler),
            "en_ince_duzey": max((e["duzey"] for e in etiketler), key=DUZEY_SIRASI.get, default=None),
            "etiketler": etiketler,
            "sorunlar": [s for d in ds for s in d.sorunlar],
            "kullanim": "degerlendirme_etiketi",
            "iz": {
                "yalniz_iz": True,
                "siniflandiriciya_verilmez": True,
                "not": "Yol ve ad yalnız iz sürmek için; sınıflandırıcı girdisi değildir.",
                "yollar": [{"yol": d.yol, "birim": d.birim} for d in ds],
            },
        })
    out.sort(key=lambda r: (r["birimler"][0], r["iz"]["yollar"][0]["yol"]))
    return out


@dataclass
class Sonuc:
    kayitlar: list[dict]
    dosyalar: list[Dosya]
    raporlar: list[dict]
    eslesmeyen: list[Eslesmeyen]
    eslesen_satir: int


def build(kaynak: Path, birim: str | None = None, takma: dict[str, str] | None = None,
          etiketsiz: list[str] | None = None, raporlar: list[str] | None = None) -> Sonuc:
    """raporlar: rapor olarak okunacak göreli yollar (verilmezse adından bulunur)."""
    dosyalar = tara(kaynak, birim, takma or {}, etiketsiz or [])
    for d in dosyalar:
        yol_etiketleri(d)

    if raporlar is not None:
        istenen = {nfc(r) for r in raporlar}
        for d in dosyalar:
            d.rapor = d.yol in istenen
    rapor_bilgi = []
    eslesmeyen: list[Eslesmeyen] = []
    eslesen = 0
    birime_gore: dict[str, list[Dosya]] = defaultdict(list)
    for d in dosyalar:
        if not d.rapor and not d.etiket_disi:
            birime_gore[d.birim].append(d)
    for r in dosyalar:
        if not r.rapor or r.etiket_disi or not r.yol.lower().endswith(".docx"):
            continue
        bilgi = {"yol": r.yol, "birim": r.birim, "durum": r.durum, "satir": 0, "eslesen": 0}
        rapor_bilgi.append(bilgi)
        if r.durum != "ok":
            continue
        try:
            satirlar = rapor_kanitlari(r.mutlak, r.yol)
        except Exception as e:  # bozuk docx: raporda belirt, devam et
            bilgi["durum"] = f"okunamadi: {e}"
            continue
        bilgi["satir"] = len(satirlar)
        for s in satirlar:
            hedef, yontem, skor, ne = rapor_esle(s, birime_gore[r.birim])
            if not hedef:
                ne.birim = r.birim
                eslesmeyen.append(ne)
                continue
            bilgi["eslesen"] += 1
            eslesen += 1
            for d in hedef:
                d.kanitlar.append({
                    "kaynak": "rapor", "olcut": s.bolum, "duzey": ALT, "od": s.od,
                    "kanit_no": s.kanit_no, "ham": s.ham, "rapor": r.yol, "eslesme": yontem,
                    "benzerlik": skor, "bolum_cikarim": s.bolum_cikarim,
                })
    return Sonuc(kayitlar(dosyalar), dosyalar, rapor_bilgi, eslesmeyen, eslesen)
