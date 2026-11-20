"""Kurum belge kataloğu (`bidr kurum-katalog cek`): kurumun herkese açık mevzuat ve kalite
sayfalarından (yönetmelik, yönerge, usul-esas, iş akışı, form listeleri) yalnız belge **adlarını**
ve bağlantılarını çeker. Ek dosyalar (PDF/DOCX/XLSX) indirilmez; her liste sayfası için tek istek
(sayfalama varsa sonraki sayfalar da birer istek), istekler arasında bekleme.

Sayfa adresleri kurum profilinde (`bidr/data/institutions/<kurum>.yaml`, `katalog:`) verilir:

    katalog:
      - ad: Yönergeler ve usul-esaslar
        adres: https://.../liste.html
        tur: yonerge          # yonetmelik | yonerge | usul_esas | is_akisi | form | anket | talimat
        etkin: true           # false: listede durur, çekilmez

Ayrıştırma geneldir (kuruma özgü kod yok):
- **Tablo**: başlık satırında "... ADI" sütunu (ad), "... NO" sütunu (doküman kodu), "DİLİ",
  "... TARİHİ", "REVİZYON NO" sütunları tanınır; satırdaki ilk bağlantı belgenin bağlantısıdır.
  "BİRİM ADI:" satırı sonraki satırların birimini verir. İngilizce satır aynı kodlu Türkçe öğeye
  `en_baglanti` olarak eklenir.
- **Paragraf/liste**: belge dosyasına (pdf, docx, xlsx…) giden bağlantılar; bağlantı metni ad,
  baştaki kod (FR-0047 gibi) doküman kodu; paragraftaki ikinci bağlantı (parantez içi) İngilizce
  sürüm sayılır. Yalnız kalın yazılmış paragraf/başlık sonraki öğelerin bölümünü verir.

İndirilen HTML güvenilmeyen veridir: yalnız metin ve bağlantı olarak ayrıştırılır.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

import yaml

from .tablolar import norm

FILE = "kurum-katalog.json"
SURUM = 1
USER_AGENT = "bidr-kurum-katalog/1.0 (acik kaynak BIDR araci; yalniz liste sayfalari)"
BEKLEME = 2.0            # istekler arası en az bekleme (sn)
EN_COK_SAYFA = 20        # bir katalog adresinden izlenen en çok sayfa (sayfalama)
MAX_BAYT = 8 * 1024 * 1024
TURLER = ("yonetmelik", "yonerge", "usul_esas", "is_akisi", "form", "anket", "talimat")
TUR_AD = {"yonetmelik": "Yönetmelik", "yonerge": "Yönerge", "usul_esas": "Usul ve esaslar",
          "is_akisi": "İş akışı", "form": "Form", "anket": "Anket formu", "talimat": "Talimat"}
DOC_EXT = (".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".odt", ".ods", ".zip", ".rtf")
_KOD = re.compile(r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])([A-ZÇĞİÖŞÜ]{2}(?:-[A-ZÇĞİÖŞÜ]{2})?)\s*-\s*(\d{3,5})(?!\d)")
_REV = re.compile(r"(?:^|[\s_\-])R(\d{1,2})(?=[\s._\-]|$)")
_SKIP = {"script", "style", "noscript", "svg", "head", "nav", "header", "footer", "template", "button"}
_BLOCK = {"p", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "section", "article", "ul", "ol",
          "blockquote"}


# -- HTML → olaylar -----------------------------------------------------------------------------

class _Parser(HTMLParser):
    """Belgeyi sıralı olaylara çevirir: ("row", [hücre]) ve ("para", metin, [bağlantı], kalın_mı, başlık_mı).
    Hücre/bağlantı: {"text", "links": [(href, metin)]}."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[tuple] = []
        self.skip = 0
        self.table = 0
        self.row: list[dict] | None = None
        self.cell: dict | None = None
        self.para = {"text": [], "links": [], "strong": [], "h": False}
        self.a: list | None = None        # [href, [metin]]
        self.strong = 0
        self.next_links: list[str] = []

    # bağlam
    def _target(self) -> dict:
        return self.cell if self.cell is not None else self.para

    def _flush(self):
        p = self.para
        txt = " ".join("".join(p["text"]).split())
        if txt or p["links"]:
            strong = " ".join("".join(p["strong"]).split())
            self.events.append(("para", txt, list(p["links"]), bool(txt) and strong == txt, p["h"]))
        self.para = {"text": [], "links": [], "strong": [], "h": False}

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        at = dict(attrs)
        if tag == "a":
            href = (at.get("href") or "").strip()
            if (at.get("rel") or "").lower() == "next" and href:
                self.next_links.append(href)
            self.a = [href, []]
        elif tag == "table":
            if not self.table:
                self._flush()
            self.table += 1
        elif tag == "tr" and self.table:
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = {"text": [], "links": [], "strong": []}
        elif tag in ("strong", "b"):
            self.strong += 1
        elif tag == "br":
            self._target()["text"].append(" ")
        elif tag in _BLOCK and not self.table:
            self._flush()
            if tag[0] == "h" and tag[1:].isdigit():
                self.para["h"] = True

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip:
            return
        if tag == "a" and self.a is not None:
            href, parts = self.a
            txt = " ".join("".join(parts).split())
            if href:
                self._target()["links"].append((href, txt))
                if txt in ("Sonraki", "Next", "»", "›", "Sonraki sayfa"):
                    self.next_links.append(href)
            self.a = None
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            c = self.cell
            self.row.append({"text": " ".join("".join(c["text"]).split()), "links": c["links"]})
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if self.row:
                self.events.append(("row", self.row))
            self.row = None
        elif tag == "table" and self.table:
            self.table -= 1
        elif tag in ("strong", "b"):
            self.strong = max(0, self.strong - 1)
        elif tag in _BLOCK and not self.table:
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        t = self._target()
        t["text"].append(data)
        if self.strong and "strong" in t:
            t["strong"].append(data)
        if self.a is not None:
            self.a[1].append(data)

    def close(self):
        super().close()
        self._flush()


def olaylar(html_text: str) -> tuple[list[tuple], list[str]]:
    p = _Parser()
    p.feed(html_text)
    p.close()
    return p.events, p.next_links


# -- öğeler -------------------------------------------------------------------------------------

def kod_bul(s: str) -> str:
    m = _KOD.search(s or "")
    return f"{m.group(1)}-{m.group(2)}" if m else ""


def _kod_sil(ad: str, kod: str) -> str:
    if not kod:
        return ad.strip()
    pre, num = kod.rsplit("-", 1)
    ad = re.sub(rf"^\s*{re.escape(pre)}\s*-\s*{num}\s*[-–:.]?\s*", "", ad)
    return ad.strip(" -–:")


def _abs(base: str, href: str) -> str:
    href = href.strip()
    if not href or href.startswith(("#", "mailto:", "javascript:", "tel:")):
        return ""
    u = urllib.parse.urljoin(base, href)
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https"):
        return ""
    path = urllib.parse.quote(urllib.parse.unquote(p.path), safe="/%:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit((p.scheme, p.netloc, path, p.query, ""))


def _belge_mi(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    low = urllib.parse.unquote(p.path).lower()
    return low.endswith(DOC_EXT) or "sharepoint." in p.netloc or "drive.google." in p.netloc


def _rev(url: str, ad: str = "") -> str:
    base = urllib.parse.unquote(urllib.parse.urlsplit(url).path).rsplit("/", 1)[-1]
    base = re.sub(r"\.[A-Za-z]{2,4}$", "", base)
    m = _REV.search(base) or _REV.search(ad or "")
    return f"R{m.group(1)}" if m else ""


def tur_belirle(sayfa_tur: str, ad: str, bolum: str = "") -> str:
    a = norm(ad)
    if sayfa_tur in ("yonerge", "yonetmelik", "usul_esas"):
        if re.search(r"usul ve esas|uygulama esas|esaslari\b|ilkeleri\b|usul ve ilke", a):
            return "usul_esas"
        if sayfa_tur == "yonerge" and re.search(r"yonetmeli", a) and "yonerge" not in a:
            return "yonetmelik"
        return sayfa_tur
    if sayfa_tur in ("form", "anket"):
        return "anket" if ("anket" in a or "survey" in a or "anket" in norm(bolum)) else "form"
    return sayfa_tur


def _ingilizce(s: str) -> bool:
    a = norm(s)
    return bool(re.search(r"\b(the|of|and|for|form|survey|directive|regulation|procedure|request|application"
                          r"|evaluation|principles)\b", a)) and not re.search(r"[çğışöüÇĞİŞÖÜ]", s)


def _sutunlar(cells: list[str]) -> dict | None:
    """Başlık satırı mı: {"ad": i, "kod": i, "dil": i, "tarih": [(i, etiket)], "rev": i}."""
    f = [norm(c) for c in cells]
    ad = next((i for i, x in enumerate(f) if re.search(r"\badi$", x) and "birim" not in x), None)
    if ad is None:
        return None
    kod = next((i for i, x in enumerate(f) if re.search(r"\b(no|kodu|numarasi)$", x) and "rev" not in x), None)
    dil = next((i for i, x in enumerate(f) if x in ("dili", "dil")), None)
    rev = next((i for i, x in enumerate(f) if "revizyon no" in x or x == "rev"), None)
    tarih = [(i, cells[i]) for i, x in enumerate(f) if "tarih" in x or "sayisi" in x]
    return {"ad": ad, "kod": kod, "dil": dil, "rev": rev, "tarih": tarih}


def ayristir(html_text: str, sayfa: dict, base: str) -> tuple[list[dict], list[str]]:
    """Bir liste sayfasının öğeleri (İngilizce sürümler birleştirilmeden) ve sonraki sayfa adresleri."""
    evs, nxt = olaylar(html_text)
    out: list[dict] = []
    cols = None
    birim = bolum = ""
    stur = sayfa.get("tur") or "form"

    def ekle(ad, kod, url, en=False, dil="", tarihler=None, rev=""):
        ad = " ".join(re.sub(r"\s*-?\s*\([^()]*t[ıi]klay[ıi]n[ıi]z\)", "", ad or "").split()).strip(" -")
        if not ad and not kod:
            return
        out.append({"ad": ad, "kod": kod, "tur": tur_belirle(stur, ad, bolum), "baglanti": url,
                    "dil": dil or ("İngilizce" if en else "Türkçe"), "birim": birim, "bolum": bolum,
                    "tarihler": tarihler or {}, "revizyon": rev or _rev(url, ad),
                    "sayfa": sayfa.get("ad") or "", "sayfa_adresi": base})

    for ev in evs:
        if ev[0] == "row":
            cells = ev[1]
            texts = [c["text"] for c in cells]
            if len(texts) >= 2 and norm(texts[0]).startswith("birim adi"):
                birim, cols = texts[1].strip(), cols
                continue
            h = _sutunlar(texts)
            if h is not None:
                cols = h
                continue
            if cols is None or len(texts) <= cols["ad"]:
                continue
            ad = texts[cols["ad"]]
            kod = kod_bul(texts[cols["kod"]]) if cols["kod"] is not None and cols["kod"] < len(texts) else ""
            kod = kod or kod_bul(ad)
            links = [_abs(base, hr) for c in cells for hr, _ in c["links"]]
            url = next((u for u in links if u), "")
            if not ad or (not kod and not url):
                continue
            dil = texts[cols["dil"]] if cols["dil"] is not None and cols["dil"] < len(texts) else ""
            tarihler = {lab: texts[i] for i, lab in cols["tarih"] if i < len(texts) and texts[i].strip(" -")}
            rev = texts[cols["rev"]] if cols["rev"] is not None and cols["rev"] < len(texts) else ""
            ekle(_kod_sil(ad, kod), kod, url, en=norm(dil).startswith("ingilizce"), dil=dil,
                 tarihler=tarihler, rev=rev.strip(" -"))
            continue
        _, txt, links, kalin, baslik = ev
        docs = [(u, t) for u, t in ((_abs(base, hr), t) for hr, t in links) if u and _belge_mi(u)]
        if not docs:
            if txt and (kalin or baslik) and len(txt) <= 120:
                bolum = txt.strip(" :")
            continue
        u0, t0 = docs[0]
        t0 = t0 or txt
        kod = kod_bul(t0) or kod_bul(txt)
        ad = _kod_sil(t0, kod)
        # aynı paragrafta ikinci bağlantı: parantez içindeki İngilizce sürüm
        en = next((u for u, t in docs[1:] if t and (_ingilizce(_kod_sil(t, kod_bul(t))) or kod_bul(t) == kod)), "")
        ad = re.sub(r"\s*\((?=[^()]*\)\s*$)[^()]*\)\s*$", "", ad) if _ingilizce(
            (re.search(r"\(([^()]*)\)\s*$", ad) or [None, ""])[1]) else ad
        if _ingilizce(ad) and not kod:
            continue
        ekle(ad, kod, u0)
        if en:
            out[-1]["en_baglanti"] = en
    return out, [u for u in (_abs(base, x) for x in nxt) if u]


def birlestir(items: list[dict]) -> list[dict]:
    """İngilizce satırları aynı kodlu Türkçe öğeye bağla; aynı (tür, kod, ad) tekrarını at; kimlik ver."""
    tr: dict[tuple, dict] = {}
    out: list[dict] = []
    en: list[dict] = []
    for it in items:
        if norm(it.get("dil")).startswith("ingilizce"):
            en.append(it)
            continue
        k = (it["tur"], it["kod"] or norm(it["ad"]), norm(it["ad"]) if not it["kod"] else "")
        k2 = (it["tur"], it["kod"], norm(it["ad"]))
        if k2 in {(o["tur"], o["kod"], norm(o["ad"])) for o in tr.values()}:
            continue
        if it["kod"] and (it["tur"], it["kod"], "") in tr:
            k = (it["tur"], it["kod"], norm(it["ad"]))      # aynı kodlu farklı ad (birim kopyası)
        tr[k] = it
        out.append(it)
    by_kod = {(o["kod"]): o for o in out if o["kod"]}
    for it in en:
        o = by_kod.get(it["kod"]) if it["kod"] else None
        if o is not None:
            o.setdefault("en_baglanti", it["baglanti"])
        else:
            out.append(it)
    seen: dict[str, int] = {}
    for it in out:
        base = f"{it['tur']}:{it['kod'] or hashlib.sha256(norm(it['ad']).encode()).hexdigest()[:8]}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        it["id"] = base if not n else f"{base}#{n + 1}"
        it["anahtar"] = anahtar(it)
    return out


def anahtar(it: dict) -> str:
    """Eşleme önbelleği anahtarı: ad, kod, tür, birim, bölüm (bağlantı/revizyon değişince eşleme değişmez)."""
    s = "|".join(norm(it.get(k) or "") for k in ("tur", "kod", "ad", "birim", "bolum"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


# -- çekme --------------------------------------------------------------------------------------

Getir = Callable[[str], "tuple[int | str, str, str]"]      # adres → (durum, html, son adres)


def http_getir(bekleme: float = BEKLEME) -> Getir:
    son = [0.0]

    def getir(url: str):
        dt = time.time() - son[0]
        if dt < bekleme:
            time.sleep(bekleme - dt)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html",
                                                   "Accept-Language": "tr,en;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                ct = r.headers.get("Content-Type", "")
                if "html" not in ct.lower():
                    return (f"html değil ({ct.split(';')[0]})", "", r.geturl())
                data = r.read(MAX_BAYT + 1)
                if len(data) > MAX_BAYT:
                    return ("çok büyük", "", r.geturl())
                cs = r.headers.get_content_charset() or "utf-8"
                return (r.status, data.decode(cs, "replace"), r.geturl())
        except urllib.error.HTTPError as e:
            return (e.code, "", url)
        except Exception as e:  # noqa: BLE001 — ağ hatası rapora yazılır
            return (f"hata: {type(e).__name__}", "", url)
        finally:
            son[0] = time.time()
    return getir


def profil_sayfalari(kurum: str, path: Path | None = None) -> tuple[dict, list[dict]]:
    """Kurum profili ve `katalog:` kayıtları."""
    from bidr.identify.catalog import institution_paths
    p = path or next(iter(institution_paths([kurum])), None)
    raw = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    sayfalar = []
    for i, s in enumerate(raw.get("katalog") or []):
        if not isinstance(s, dict) or not s.get("adres"):
            raise ValueError(f"{Path(p).name}: katalog[{i}] `adres` gerekli")
        tur = str(s.get("tur") or "form")
        if tur not in TURLER:
            raise ValueError(f"{Path(p).name}: katalog[{i}] bilinmeyen tür {tur!r} (geçerli: {', '.join(TURLER)})")
        sayfalar.append({"ad": str(s.get("ad") or s["adres"]), "adres": str(s["adres"]), "tur": tur,
                         "etkin": bool(s.get("etkin", True)), "not": str(s.get("not") or "")})
    return raw, sayfalar


def cek(sayfalar: list[dict], getir: Getir | None = None, *, kurum: str = "", log=print) -> dict:
    getir = getir or http_getir()
    items: list[dict] = []
    rapor = []
    for s in sayfalar:
        if not s.get("etkin", True):
            rapor.append({**s, "durum": "atlandı (etkin: false)", "oge_sayisi": 0, "istek": 0})
            continue
        url, gorulen, n0, istek, durum = s["adres"], set(), len(items), 0, "ok"
        while url and url not in gorulen and istek < EN_COK_SAYFA:
            gorulen.add(url)
            st, html_text, son = getir(url)
            istek += 1
            if st != 200 or not html_text:
                durum = f"başarısız: {st}"
                log(f"  {s['ad']}: {url} → {st}")
                break
            its, nxt = ayristir(html_text, s, son or url)
            items += its
            pre = urllib.parse.urlsplit(s["adres"]).path.rsplit("/", 1)[0]
            url = next((u for u in nxt if u not in gorulen and urllib.parse.urlsplit(u).path.startswith(pre)), "")
        n = len(items) - n0
        if durum == "ok" and n == 0:
            durum = "öğe bulunamadı (sayfa yapısı tanınmadı)"
        rapor.append({**s, "durum": durum, "oge_sayisi": n, "istek": istek})
        log(f"  {s['ad']}: {n} öğe ({istek} istek) {'' if durum == 'ok' else durum}")
    ogeler = birlestir(items)
    return {"surum": SURUM, "kurum": kurum, "uretim": datetime.now().isoformat(timespec="seconds"),
            "sayfalar": rapor, "ogeler": ogeler, "sha": katalog_sha(ogeler)}


def katalog_sha(ogeler: list[dict]) -> str:
    return hashlib.sha256("\n".join(sorted(o["id"] + "|" + o["anahtar"] for o in ogeler)).encode()).hexdigest()[:16]


def yaz(kat: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / FILE
    p.write_text(json.dumps(kat, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def oku(path: Path) -> dict:
    p = Path(path)
    if p.is_dir():
        p = p / FILE
    return json.loads(p.read_text(encoding="utf-8"))
