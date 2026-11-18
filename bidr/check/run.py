"""Biçim denetçisi: üretilmiş FR-0833 docx'ini (ve varsa kanıt klasörünü) salt okur, kılavuz
kurallarına göre bulgu listesi çıkarır. Render'dan bağımsızdır: render kodunu çağırmaz, belgeyi
kim üretmiş olursa olsun (render, elle düzenleme) aynı denetimi yapar.

Bulgu düzeyleri: `kritik` (yayıma hazır değil) | `uyari` (bakılmalı; yayımı durdurmaz).
Kapsam: birimin doldurduğu bölgeler (Açıklamalar/Kanıtlar hücreleri, güçlü/gelişmeye açık
yönler hücreleri, kapak alanları), ölçüt başlıkları, üst/altbilgideki form alanları ve kanıt
klasörü. Şablonun kendi kılavuz metni biçim denetimine girmez (birimin sorumluluğunda değil).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from bidr.criteria.extract_docx import RE_MAIN, RE_SUB, UNITS_PREFIX, W, _cell_lines, _ptext

from .fmt import Resolver, field_signature, has_object, text_runs
from .rules import Rules

KRITIK, UYARI = "kritik", "uyari"

COVER_STOP = "ÖLÇÜTLER VE KANITLAR"
ACIKLAMA, KANIT = "Açıklamalar:", "Kanıtlar:"
YER_TUTUCU_ACIKLAMA = "Bu bölüme açıklayıcı metin yazılmalı"
YER_TUTUCU_KANIT = "Kanıtlar buraya yazılmalı"
YER_TUTUCU_BIRIM = "[Birim Adı]"
YER_TUTUCU_UYE = "[Üye Unvan"
HAZIRLAYANLAR = "Raporu Hazırlayanlar"
SWOT_BASLIK = ("Güçlü Yönler", "Gelişmeye Açık Yönler")
SWOT_YER_TUTUCU = "Biriminizin bu ana ölçüt ve alt ölçütleri"
DOGRULANMADI = "[doğrulanmadı]"
BOS_ACIKLAMA_IPUCU = ("kanıt bulunamamıştır", "veri bulunmamaktadır")

# Kılavuz "Kanıt Gösterimi": metin içinde `[1_OD3]`, ölçüt sonundaki listede `[1-OD3]. Ad.pdf`.
RE_ATIF = re.compile(r"\[(\d+)([_-])OD([1-5])\]")
RE_LISTE_KILAVUZ = re.compile(r"^\[(\d+)-OD([1-5])\]\.\s*(.+)$")
RE_LISTE_MAT = re.compile(r"^(\d+)_OD([1-5])\s*:\s*(.+)$")          # render "mat" biçimi
RE_DOSYA = re.compile(r"^\[([A-D]\.\d+\.\d+)-(\d+)-OD([1-5])\] (.+)\.([A-Za-z0-9]+)$")
RE_ALT_BASLIK = re.compile(r"^([A-D](?:\.\d+){3,})\.?\s+\S")      # A.1.1.1 (A.1.x.x.x)
RE_ACIKLAMA_NESNE = re.compile(r"^(Şekil|Tablo|Grafik)\s*\d+\s*[.:]")
RE_APA_VIRGULSUZ = re.compile(
    r"\(([A-ZÇĞİÖŞÜ][a-zçğıöşü]+(?:\s+(?:ve|&)\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü]+|\s+vd\.)?)\s+((?:19|20)\d\d[a-z]?)\)")
RE_YIL = re.compile(r"^(19|20)\d\d$")
FORM_PARCALARI = ("header", "footer", "first_page_header", "first_page_footer",
                  "even_page_header", "even_page_footer")


@dataclass
class Bulgu:
    seviye: str
    kod: str
    yer: str
    mesaj: str


@dataclass
class Sonuc:
    docx: str
    sablon: str | None
    kanit_klasoru: str | None
    kurallar: dict
    bulgular: list[Bulgu] = field(default_factory=list)
    bilgi: dict = field(default_factory=dict)
    docx_sha: str | None = None     # denetlenen dosyanın içerik özeti (hat: denetle_tamam güncellik)

    def ekle(self, seviye, kod, yer, mesaj):
        self.bulgular.append(Bulgu(seviye, kod, yer, mesaj))

    @property
    def kritik(self) -> int:
        return sum(b.seviye == KRITIK for b in self.bulgular)

    @property
    def uyari(self) -> int:
        return sum(b.seviye == UYARI for b in self.bulgular)

    def to_dict(self) -> dict:
        kodlar: dict[str, dict] = {}
        for b in self.bulgular:
            k = kodlar.setdefault(b.kod, {"seviye": b.seviye, "sayi": 0})
            k["sayi"] += 1
        return {"surum": 1, "docx": self.docx, "docx_sha": self.docx_sha, "sablon": self.sablon,
                "kanit_klasoru": self.kanit_klasoru, "kurallar": self.kurallar,
                "ozet": {"kritik": self.kritik, "uyari": self.uyari,
                         "yayima_hazir": self.kritik == 0, "kodlar": kodlar},
                "bilgi": self.bilgi, "bulgular": [asdict(b) for b in self.bulgular]}


# -- belge yapısı ------------------------------------------------------------------------------

@dataclass
class Blok:
    olcut: str
    baslik_p: object
    aciklama_tc: object | None = None
    kanit_tc: object | None = None


def _body_after_stop(doc) -> list:
    out, seen = [], False
    for el in doc.element.body.iterchildren():
        if el.tag == W + "p" and _ptext(el).strip() == COVER_STOP:
            seen = True
            continue
        if seen and el.tag == W + "tbl":
            out.append(el)
    return out


def bloklar(doc) -> tuple[dict[str, Blok], list[tuple[str, object]], list[str]]:
    """({alt ölçüt: Blok}, [(ölçüt, başlık paragrafı)], yinelenenler)."""
    blks: dict[str, Blok] = {}
    mains: list[tuple[str, object]] = []
    dups: list[str] = []
    cur: Blok | None = None
    for tbl in _body_after_stop(doc):
        for tr in tbl.iter(W + "tr"):
            cells = list(tr.iterchildren(W + "tc"))
            if not cells:
                continue
            lines = _cell_lines(cells[0])
            head = lines[0] if lines else ""
            first_p = next(iter(cells[0].iter(W + "p")), None)
            if len(cells) == 1 and (m := RE_SUB.match(head)):
                sid = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
                cur = Blok(sid, first_p)
                if sid in blks:
                    dups.append(sid)
                else:
                    blks[sid] = cur
                continue
            if len(cells) == 1 and (m := RE_MAIN.match(head)):
                mains.append((f"{m.group(1)}.{m.group(2)}", first_p))
                cur = None
                continue
            if head.startswith(UNITS_PREFIX):
                cur = None
                continue
            if cur is None:
                continue
            if head.startswith(ACIKLAMA):
                cur.aciklama_tc = cells[0]
            elif head.startswith(KANIT):
                cur.kanit_tc = cells[0]
    return blks, mains, dups


def icerik(tc, label: str) -> tuple[list, str]:
    """(etiketten sonraki paragraflar, etiket paragrafında etiketten sonra kalan metin)."""
    ps = list(tc.iter(W + "p"))
    for i, p in enumerate(ps):
        t = _ptext(p).strip()
        if t.startswith(label):
            return ps[i + 1:], t[len(label):].strip()
    return ps, ""


def _ptexts(ps) -> list[str]:
    return [t for t in (" ".join(_ptext(p).split()) for p in ps) if t]


def beklenen_olcutler() -> tuple[list[str], list[str]]:
    from bidr.criteria.loader import read_raw
    raw = read_raw()
    return [s["id"] for s in raw["sub_criteria"]], [c["id"] for c in raw["criteria"]]


# -- denetimler --------------------------------------------------------------------------------

class Denetci:
    def __init__(self, doc, rules: Rules, sonuc: Sonuc):
        self.doc, self.r, self.s = doc, rules, sonuc
        self.res = Resolver(doc)

    # biçim: gövde paragrafı ------------------------------------------------------------------
    def govde(self, p, yer: str) -> None:
        text = " ".join(_ptext(p).split())
        if not text:
            return
        if RE_ACIKLAMA_NESNE.match(text):
            self.nesne_aciklamasi(p, yer, text)
            return
        if (m := RE_ALT_BASLIK.match(text)):
            self.alt_baslik(p, yer, text, m.group(1))
            return
        fonts, sizes = set(), set()
        for r in text_runs(p):
            f = self.res.font(r, p)
            if f is not None and f != self.r.yazi_tipi:
                fonts.add(f)
            sz = self.res.size_half_pt(r, p)
            if sz is not None and sz != round(self.r.govde_punto * 2):
                sizes.add(sz / 2)
        kisa = text[:50]
        if fonts:
            self.s.ekle(KRITIK, "yazi_tipi", yer, f"yazı tipi {', '.join(sorted(fonts))} "
                        f"(beklenen {self.r.yazi_tipi}): «{kisa}»")
        if sizes:
            self.s.ekle(KRITIK, "govde_punto", yer, f"punto {', '.join(f'{x:g}' for x in sorted(sizes))} "
                        f"(beklenen {self.r.govde_punto:g}): «{kisa}»")
        self.aralik(p, yer, kisa)

    def aralik(self, p, yer: str, kisa: str) -> None:
        for side, nk, ad in (("before", self.r.paragraf_oncesi_nk, "öncesi"),
                             ("after", self.r.paragraf_sonrasi_nk, "sonrası")):
            v = self.res.spacing(p, side)
            if v is None or v == self.r.twip(nk):
                continue
            got = "otomatik" if v == -1 else f"{v / 20:g} nk"
            self.s.ekle(UYARI, "aralik", yer, f"paragraf {ad} {got} (beklenen {nk:g} nk): «{kisa}»")

    def baslik(self, p, yer: str, text: str) -> None:
        runs = text_runs(p)
        if not runs:
            return
        sz = {self.res.size_half_pt(r, p) for r in runs} - {None}
        bold = all(self.res.toggle(r, p, "b") for r in runs)
        fonts = {self.res.font(r, p) for r in runs} - {None, self.r.yazi_tipi}
        sorun = []
        if sz and sz != {round(self.r.baslik_punto * 2)}:
            sorun.append("punto " + ", ".join(f"{x / 2:g}" for x in sorted(sz)))
        if not bold:
            sorun.append("kalın değil")
        if fonts:
            sorun.append("yazı tipi " + ", ".join(sorted(fonts)))
        if sorun:
            self.s.ekle(UYARI, "baslik_bicimi", yer,
                        f"başlık {self.r.baslik_punto:g} pt kalın olmalı: {'; '.join(sorun)} «{text[:50]}»")

    def alt_baslik(self, p, yer: str, text: str, no: str) -> None:
        olcut = yer.split()[0]
        if not no.startswith(olcut + "."):
            self.s.ekle(UYARI, "baslik_numarasi", yer,
                        f"alt başlık numarası {no} bu ölçütün ({olcut}) altında değil (A.1.x.x.x düzeni)")
        self.baslik(p, yer, text)

    def nesne_aciklamasi(self, p, yer: str, text: str) -> None:
        runs = text_runs(p)
        sorun = []
        if runs and not all(self.res.toggle(r, p, "i") for r in runs):
            sorun.append("eğik değil")
        if self.res.jc(p) not in ("right", "end"):
            sorun.append(f"hizalama {self.res.jc(p)} (sağa dayalı olmalı)")
        sz = {self.res.size_half_pt(r, p) for r in runs} - {None}
        if sz and sz != {round(self.r.aciklama_punto * 2)}:
            sorun.append("punto " + ", ".join(f"{x / 2:g}" for x in sorted(sz)))
        fonts = {self.res.font(r, p) for r in runs} - {None, self.r.yazi_tipi}
        if fonts:
            sorun.append("yazı tipi " + ", ".join(sorted(fonts)))
        prev, nxt = _komsu(p, -1), _komsu(p, 1)
        if has_object(prev) and not has_object(nxt):
            sorun.append("nesnenin altında (üstte olmalı)")
        if sorun:
            self.s.ekle(UYARI, "nesne_aciklamasi", yer, f"{'; '.join(sorun)}: «{text[:50]}»")

    def apa(self, texts: list[str], yer: str) -> None:
        for t in texts:
            for m in RE_APA_VIRGULSUZ.finditer(t):
                self.s.ekle(UYARI, "apa7", yer, f"metin içi kaynak gösterimi APA 7'ye uymuyor: "
                            f"'{m.group(0)}' → '({m.group(1)}, {m.group(2)})'")
            if re.search(r"\bet al\.", t):
                self.s.ekle(UYARI, "apa7", yer, "Türkçe metinde APA 7 'vd.' kullanır ('et al.' değil)")


def _komsu(p, yon: int):
    """Boş paragrafları atlayarak önceki/sonraki gövde öğesi (w:p / w:tbl)."""
    el = p.getprevious() if yon < 0 else p.getnext()
    while el is not None:
        if el.tag in (W + "p", W + "tbl") and (el.tag == W + "tbl" or has_object(el) or _ptext(el).strip()):
            return el
        el = el.getprevious() if yon < 0 else el.getnext()
    return None


def file_sha(p: Path) -> str:
    """Dosyanın sha256'sı (denetim.json `docx_sha`; `bidr status` raporun değişip değişmediğine bakar)."""
    import hashlib
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def denetle(docx_path: Path, *, rules: Rules | None = None, sablon: Path | None = None,
            kanit_klasoru: Path | None = None, index_path: Path | None = None,
            beklenen: tuple[list[str], list[str]] | None = None) -> Sonuc:
    """`beklenen`: (alt ölçütler, ölçütler); vars. paket ölçüt verisi (46 alt ölçüt)."""
    import docx

    rules = rules or Rules()
    docx_path = Path(docx_path)
    doc = docx.Document(str(docx_path))
    s = Sonuc(str(docx_path), str(sablon) if sablon else None,
              str(kanit_klasoru) if kanit_klasoru else None, rules.to_dict())
    s.docx_sha = file_sha(docx_path)
    d = Denetci(doc, rules, s)

    _kapak(doc, s)
    listeler = _olcutler(doc, d, s, beklenen or beklenen_olcutler())
    _swot(doc, d, s)
    _form_alanlari(doc, s, sablon)
    if sablon is not None and Path(sablon).exists():
        _sablondan(s, Path(sablon), rules)
    if kanit_klasoru is not None:
        _kanit_klasoru(Path(kanit_klasoru), listeler, s)
    if index_path is not None and Path(index_path).exists():
        _kanit_dizini(Path(index_path), listeler, s)
    return s


def _kapak(doc, s: Sonuc) -> None:
    paras = []
    for el in doc.element.body.iterchildren(W + "p"):
        t = " ".join(_ptext(el).split())
        if t == COVER_STOP:
            break
        paras.append(t)
    kapak = {"birim": None, "yil": None, "hazirlayanlar": 0}
    for t in paras:
        if YER_TUTUCU_BIRIM in t:
            s.ekle(KRITIK, "kapak_birim", "kapak", f"birim adı yer tutucusu duruyor: «{t[:60]}»")
        if kapak["yil"] is None and RE_YIL.match(t):
            kapak["yil"] = t
    uye_yt = sum(YER_TUTUCU_UYE in t for t in paras)
    if uye_yt:
        s.ekle(KRITIK, "kapak_hazirlayanlar", "kapak",
               f"'Raporu Hazırlayanlar' altında {uye_yt} yer tutucu satır duruyor "
               "([Üye Unvan, Adı Soyadı, eposta adresi, Görevi]); komisyon üyeleri elle yazılmalı")
    if HAZIRLAYANLAR in paras:
        i = paras.index(HAZIRLAYANLAR)
        uyeler = []
        for t in paras[i + 1:]:
            if not t:
                continue
            if RE_YIL.match(t):
                break
            uyeler.append(t)
        kapak["hazirlayanlar"] = sum(YER_TUTUCU_UYE not in u for u in uyeler)
        if not uyeler:
            s.ekle(KRITIK, "kapak_hazirlayanlar", "kapak", "'Raporu Hazırlayanlar' altında üye yok")
    else:
        s.ekle(UYARI, "kapak_hazirlayanlar", "kapak", "'Raporu Hazırlayanlar' başlığı bulunamadı")
    birim_i = next((i for i, t in enumerate(paras) if t.startswith("(BİDR)")), None)
    if birim_i is not None:
        kapak["birim"] = next((t for t in paras[birim_i + 1:] if t), None)
    if kapak["yil"] is None:
        s.ekle(UYARI, "kapak_yil", "kapak", "kapakta yıl paragrafı bulunamadı")
    s.bilgi["kapak"] = kapak


def _basliklar(doc, d: Denetci) -> None:
    """Ölçüt ve alt ölçüt başlık satırlarının biçimi (12 pt kalın)."""
    blks, mains, _ = bloklar(doc)
    for mid, p in mains:
        if p is not None:
            d.baslik(p, f"{mid} başlık", " ".join(_ptext(p).split()))
    for sid, b in blks.items():
        if b.baslik_p is not None:
            d.baslik(b.baslik_p, f"{sid} başlık", " ".join(_ptext(b.baslik_p).split()))


def _sablondan(s: Sonuc, sablon: Path, rules: Rules) -> None:
    """Başlık biçimi bulgusu şablonun kendisinde de varsa işaretlenir (birimin hatası değil)."""
    import docx
    tdoc = docx.Document(str(sablon))
    ts = Sonuc(str(sablon), None, None, {})
    _basliklar(tdoc, Denetci(tdoc, rules, ts))
    ayni = {(b.yer, b.mesaj) for b in ts.bulgular}
    for b in s.bulgular:
        if b.kod == "baslik_bicimi" and (b.yer, b.mesaj) in ayni:
            b.mesaj += " — şablonda da böyle (şablon kusuru)"


def _liste_satiri(t: str):
    if (m := RE_LISTE_KILAVUZ.match(t)):
        return "kilavuz", int(m.group(1)), int(m.group(2)), m.group(3).strip()
    if (m := RE_LISTE_MAT.match(t)):
        return "mat", int(m.group(1)), int(m.group(2)), m.group(3).strip()
    return None


def _olcutler(doc, d: Denetci, s: Sonuc, beklenen) -> dict[str, dict[int, int]]:
    """Ölçüt bloklarını denetler; {ölçüt: {kanıt no: OD}} (belgedeki kanıt listeleri) döner."""
    blks, mains, dups = bloklar(doc)
    exp_sub, exp_main = beklenen
    s.bilgi["alt_olcut"] = {"beklenen": len(exp_sub), "bulunan": len(blks)}
    for sid in dups:
        s.ekle(KRITIK, "olcut_yineleniyor", sid, "alt ölçüt bloğu belgede iki kez geçiyor")
    for sid in exp_sub:
        if sid not in blks:
            s.ekle(KRITIK, "olcut_eksik", sid, "alt ölçüt bloğu belgede yok")
    for sid in blks:
        if sid not in exp_sub:
            s.ekle(UYARI, "olcut_fazla", sid, "kılavuzda olmayan alt ölçüt bloğu")
    sira = [x for x in blks if x in exp_sub]
    if sira != [x for x in exp_sub if x in blks]:
        s.ekle(UYARI, "baslik_sirasi", "belge", "alt ölçüt başlıkları kılavuz sırasında değil")
    bulunan_main = [m for m, _ in mains]
    for mid in exp_main:
        if mid not in bulunan_main:
            s.ekle(UYARI, "olcut_basligi_eksik", mid, "ölçüt başlığı satırı bulunamadı")
    _basliklar(doc, d)

    listeler: dict[str, dict[int, int]] = {}
    bicimler: dict[str, int] = {"kilavuz": 0, "mat": 0}
    bos_olcut: list[str] = []
    for sid, b in blks.items():
        if b.aciklama_tc is None:
            s.ekle(KRITIK, "hucre_eksik", sid, "'Açıklamalar:' hücresi yok")
        if b.kanit_tc is None:
            s.ekle(KRITIK, "hucre_eksik", sid, "'Kanıtlar:' hücresi yok")
        if b.aciklama_tc is None or b.kanit_tc is None:
            continue
        a_ps, a_rest = icerik(b.aciklama_tc, ACIKLAMA)
        k_ps, k_rest = icerik(b.kanit_tc, KANIT)
        a_txt = ([a_rest] if a_rest else []) + _ptexts(a_ps)
        k_txt = ([k_rest] if k_rest else []) + _ptexts(k_ps)
        if not a_txt:
            s.ekle(KRITIK, "aciklama_bos", sid, "'Açıklamalar' hücresi boş")
        if any(YER_TUTUCU_ACIKLAMA in t for t in a_txt):
            s.ekle(KRITIK, "sablon_metni", sid, "'Açıklamalar' hücresinde şablon yönerge metni duruyor")
        if any(YER_TUTUCU_KANIT in t for t in k_txt):
            s.ekle(KRITIK, "sablon_metni", sid, "'Kanıtlar' hücresinde şablon yönerge metni duruyor")
        if any(DOGRULANMADI in t for t in a_txt):
            s.ekle(KRITIK, "dogrulanmamis_metin", sid, f"'{DOGRULANMADI}' işaretli metin var")
        joined = " ".join(a_txt)
        if any(ip in joined for ip in BOS_ACIKLAMA_IPUCU) and not RE_ATIF.search(joined):
            bos_olcut.append(sid)
        for p in a_ps:
            d.govde(p, f"{sid} Açıklamalar")
        for p in k_ps:
            d.govde(p, f"{sid} Kanıtlar")
        d.apa(a_txt, f"{sid} Açıklamalar")

        # atıf ↔ liste
        atif: dict[int, set[int]] = {}
        for t in a_txt:
            for m in RE_ATIF.finditer(t):
                n, sep, od = int(m.group(1)), m.group(2), int(m.group(3))
                atif.setdefault(n, set()).add(od)
                if sep == "-":
                    s.ekle(UYARI, "atif_gosterimi", sid,
                           f"metin içi atıf [{n}-OD{od}]: kılavuz metin içinde [{n}_OD{od}] ister")
        liste: dict[int, int] = {}
        for t in k_txt:
            parsed = _liste_satiri(t)
            if parsed is None:
                if not (t.startswith("Bu ölçüt için") and "kanıt" in t):
                    s.ekle(UYARI, "kanit_satiri", sid, f"kanıt satırı tanınmadı: «{t[:60]}»")
                continue
            bic, n, od, _ad = parsed
            bicimler[bic] += 1
            if n in liste:
                s.ekle(KRITIK, "kanit_no_yineleniyor", sid, f"kanıt listesinde {n} numarası iki kez")
                continue
            liste[n] = od
        listeler[sid] = liste
        for n, ods in sorted(atif.items()):
            if n not in liste:
                s.ekle(KRITIK, "atif_listede_yok", sid,
                       f"metindeki [{n}_OD{min(ods)}] kanıt listesinde yok")
                continue
            for od in sorted(ods - {liste[n]}):
                s.ekle(KRITIK, "atif_od_uyusmuyor", sid,
                       f"metinde [{n}_OD{od}], listede {n}. kanıt OD{liste[n]}")
        for n in sorted(set(liste) - set(atif)):
            s.ekle(UYARI, "atifsiz_kanit", sid, f"listedeki {n}. kanıt (OD{liste[n]}) metinde atıf almıyor")
        if liste and sorted(liste) != list(range(1, len(liste) + 1)):
            s.ekle(UYARI, "kanit_numarasi", sid,
                   f"kanıt numaraları 1..{len(liste)} sıralı değil: {sorted(liste)}")

    s.bilgi["kanit_listesi_bicimi"] = bicimler
    s.bilgi["bos_olcut"] = bos_olcut
    if bos_olcut:
        s.ekle(UYARI, "bos_olcut", ", ".join(bos_olcut),
               f"{len(bos_olcut)} alt ölçütte kanıtsız 'bulunamadı' ifadesi var (insan kararı gerekir)")
    if bicimler["kilavuz"] and bicimler["mat"]:
        s.ekle(UYARI, "kanit_gosterimi_karisik", "belge",
               f"kanıt listelerinde iki gösterim karışık: kılavuz [n-ODk]. {bicimler['kilavuz']} satır, "
               f"n_ODk: {bicimler['mat']} satır")
    elif bicimler["mat"]:
        s.ekle(UYARI, "kanit_gosterimi_karar", "belge",
               f"KARAR GEREKLİ: kanıt listeleri 'n_ODk: ad' biçiminde ({bicimler['mat']} satır); kılavuzun "
               "'Kanıt Gösterimi' örneği ölçüt sonunda '[n-ODk]. ad' ister (metin içinde '[n_ODk]'). "
               "render --kanit-bicimi kilavuz kılavuz gösterimini üretir")
    return listeler


def _swot(doc, d: Denetci, s: Sonuc) -> None:
    bulunan = 0
    for tbl in doc.element.body.iter(W + "tbl"):
        rows = list(tbl.iterchildren(W + "tr"))
        for i, tr in enumerate(rows):
            cells = list(tr.iterchildren(W + "tc"))
            if tuple(" ".join(_cell_lines(c)) for c in cells) != SWOT_BASLIK:
                continue
            bulunan += 1
            alan = " ".join(_cell_lines(rows[i - 1].find(W + "tc"))) if i > 0 else f"alan {bulunan}"
            if i + 1 >= len(rows):
                s.ekle(KRITIK, "swot_eksik", alan, "güçlü/gelişmeye açık yönler hücre satırı yok")
                continue
            for ad, tc in zip(SWOT_BASLIK, rows[i + 1].iterchildren(W + "tc")):
                txt = _ptexts(tc.iter(W + "p"))
                yer = f"{alan} / {ad}"
                if not txt:
                    s.ekle(KRITIK, "swot_bos", yer, "hücre boş")
                elif any(SWOT_YER_TUTUCU in t for t in txt):
                    s.ekle(KRITIK, "swot_sablon_metni", yer, "şablon yönerge metni duruyor")
                else:
                    for p in tc.iter(W + "p"):
                        d.govde(p, yer)
    s.bilgi["swot_alan"] = bulunan
    if bulunan != 4:
        s.ekle(KRITIK if bulunan == 0 else UYARI, "swot_eksik", "belge",
               f"güçlü/gelişmeye açık yönler tablosu {bulunan} alan için bulundu (beklenen 4: A–D)")


def _parca_imzalari(doc) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i, sec in enumerate(doc.sections):
        for kind in FORM_PARCALARI:
            hf = getattr(sec, kind)
            if hf.is_linked_to_previous:
                continue
            sig = [x for x in field_signature(hf._element) if not x.startswith("TASLAK")]
            out[f"bölüm {i + 1} {kind}"] = sig
    return out


def _form_alanlari(doc, s: Sonuc, sablon: Path | None) -> None:
    import docx
    imza = _parca_imzalari(doc)
    taslak = [k for i, sec in enumerate(doc.sections) for k in FORM_PARCALARI
              if not getattr(sec, k).is_linked_to_previous
              and any(x.startswith("TASLAK") for x in field_signature(getattr(sec, k)._element))]
    for k in taslak:
        s.ekle(KRITIK, "taslak_damgasi", k, "üstbilgide TASLAK damgası var (doğrulanmamış metin)")
    hepsi = " ".join(x for v in imza.values() for x in v)
    s.bilgi["form_alanlari"] = imza
    if sablon is not None and Path(sablon).exists():
        sdoc = docx.Document(str(sablon))
        simza = _parca_imzalari(sdoc)
        for k in sorted(set(simza) | set(imza)):
            if simza.get(k, []) != imza.get(k, []):
                s.ekle(KRITIK, "form_alani_degisti", k,
                       f"şablonda {simza.get(k)!r}, belgede {imza.get(k)!r}")
        if len(sdoc.sections) != len(doc.sections):
            s.ekle(UYARI, "bolum_sayisi", "belge",
                   f"bölüm sayısı şablonda {len(sdoc.sections)}, belgede {len(doc.sections)}")
        return
    if sablon is not None:
        s.ekle(UYARI, "sablon_yok", str(sablon), "şablon bulunamadı; form alanları yalnız varlık için denetlendi")
    else:
        s.ekle(UYARI, "sablon_yok", "belge",
               "şablon verilmedi; form alanları yalnız varlık için denetlendi (--sablon)")
    for parca, ad in ((r"Form No:\s*FR-\d+", "form kimliği (Form No)"), (r"Değ\.\s*No", "revizyon (Değ.No)"),
                      (r"\{PAGE\}", "sayfa numarası alanı (PAGE)")):
        if not re.search(parca, hepsi):
            s.ekle(KRITIK, "form_alani_eksik", "üst/altbilgi", f"{ad} bulunamadı")


def _kanit_klasoru(ev: Path, listeler: dict[str, dict[int, int]], s: Sonuc) -> None:
    if not ev.is_dir():
        s.ekle(UYARI, "kanit_klasoru_yok", str(ev), "kanıt klasörü yok")
        return
    dosyalar: dict[str, dict[int, list[tuple[int, str]]]] = {}
    sayi = 0
    for f in sorted(ev.rglob("*")):
        if not f.is_file() or any(part.startswith(".") for part in f.relative_to(ev).parts) \
                or f.suffix.lower() == ".zip":
            continue
        sayi += 1
        rel = f.relative_to(ev).as_posix()
        m = RE_DOSYA.match(f.name)
        if not m:
            s.ekle(UYARI, "kanit_dosya_adi", rel, "ad '[Ölçüt-sıra-ODk] Ad.uzantı' düzeninde değil")
            continue
        olcut, n, od = m.group(1), int(m.group(2)), int(m.group(3))
        parts = olcut.split(".")
        beklenen = "/".join(".".join(parts[:i]) for i in range(1, 4))
        if f.parent.relative_to(ev).as_posix() != beklenen:
            s.ekle(UYARI, "kanit_klasor_yeri", rel, f"dosya {beklenen}/ altında olmalı")
        dosyalar.setdefault(olcut, {}).setdefault(n, []).append((od, rel))
    s.bilgi["kanit_dosyasi"] = sayi
    for olcut, nums in dosyalar.items():
        for n, lst in nums.items():
            if len(lst) > 1:
                s.ekle(UYARI, "kanit_dosyasi_yineleniyor", olcut,
                       f"{n} numaralı birden çok dosya: {', '.join(r for _, r in lst)}")
        if sorted(nums) != list(range(1, len(nums) + 1)):
            s.ekle(UYARI, "kanit_dosya_sirasi", olcut, f"dosya sıra numaraları 1..{len(nums)} değil: {sorted(nums)}")
    for olcut, liste in listeler.items():
        nums = dosyalar.get(olcut, {})
        for n, od in sorted(liste.items()):
            if n not in nums:
                s.ekle(KRITIK, "kanit_dosyasi_yok", olcut, f"listedeki {n}. kanıtın (OD{od}) dosyası yok")
            elif od not in {o for o, _ in nums[n]}:
                s.ekle(KRITIK, "kanit_dosyasi_od", olcut,
                       f"listede {n}_OD{od}, dosya adında OD{'/'.join(str(o) for o, _ in nums[n])}")
        for n in sorted(set(nums) - set(liste)):
            s.ekle(UYARI, "listede_olmayan_dosya", olcut,
                   f"{n} numaralı dosya raporun kanıt listesinde yok: {nums[n][0][1]}")
    for olcut in sorted(set(dosyalar) - set(listeler)):
        s.ekle(UYARI, "listede_olmayan_dosya", olcut, "ölçüt bloğu belgede yok ama kanıt dosyaları var")


def _kanit_dizini(index: Path, listeler: dict[str, dict[int, int]], s: Sonuc) -> None:
    """evidence-index.csv ↔ belgedeki listeler (aynı numara, aynı OD)."""
    idx: dict[str, dict[int, int]] = {}
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^(\d+)_OD([1-5])$", (r.get("kanit_no") or "").strip())
            if m and r.get("olcut"):
                idx.setdefault(r["olcut"].strip(), {})[int(m.group(1))] = int(m.group(2))
    for olcut, liste in listeler.items():
        ix = idx.get(olcut, {})
        for n, od in liste.items():
            if ix.get(n) != od:
                s.ekle(UYARI, "dizinle_uyusmuyor", olcut,
                       f"belgedeki {n}_OD{od} evidence-index.csv'de "
                       + (f"{n}_OD{ix[n]}" if n in ix else "yok"))


# -- çıktı -------------------------------------------------------------------------------------

def tablo(s: Sonuc, satir_siniri: int = 12) -> str:
    """Okunur tablo: önce kod özeti, sonra her koddan en çok `satir_siniri` bulgu."""
    lines = []
    durum = "YAYIMA HAZIR DEĞİL" if s.kritik else "yayıma hazır (kritik bulgu yok)"
    lines.append(f"Denetim: {s.docx}")
    lines.append(f"Sonuç: {durum} — kritik {s.kritik}, uyarı {s.uyari}")
    lines.append("")
    kodlar: dict[str, list[Bulgu]] = {}
    for b in s.bulgular:
        kodlar.setdefault(b.kod, []).append(b)
    sirali = sorted(kodlar.items(), key=lambda kv: (kv[1][0].seviye != KRITIK, kv[0]))
    w = max([len(k) for k in kodlar] + [3])
    lines.append(f"{'düzey':<7} {'kod':<{w}} {'sayı':>5}")
    for k, bs in sirali:
        lines.append(f"{bs[0].seviye:<7} {k:<{w}} {len(bs):>5}")
    for k, bs in sirali:
        lines.append("")
        lines.append(f"[{bs[0].seviye}] {k} ({len(bs)})")
        for b in bs[:satir_siniri]:
            lines.append(f"  {b.yer:<28} {b.mesaj}")
        if len(bs) > satir_siniri:
            lines.append(f"  … {len(bs) - satir_siniri} bulgu daha (denetim.json)")
    return "\n".join(lines)


def yaz(s: Sonuc, out: Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(s.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return out
