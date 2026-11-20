"""Web kanıtı: özgün adresi bulma ve alınma tarihli PDF kopyası (model yok, ücretli servis yok).

Web kanıtı = kanıt klasöründeki kaydedilmiş web sayfası (`WEB_UZANTILARI`). Özgün adres,
uydurulmadan, şu sırayla aranır (`web_url`):
  1. kanıt dizinindeki bağlantı (`evidence-index.csv` `baglanti`; insan ya da belge metni; kanıt
     klasörü kök bağlantısından türeyen `klasor` bağlantısı özgün adres değildir, sayılmaz)
  2. sayfanın kendi kaydı (`html_url`): tarayıcının "saved from url=" yorumu, SingleFile
     başlığı (`url:`), `<link rel=canonical>`,
     `<meta property=og:url>`, `<base href>` (son üçünde alan adının ana sayfası sayılmaz:
     tek sayfalı sitelerin genel değeri olabilir).
Bulunamazsa adres boş kalır; PDF yine üretilir, damgada ve dizinde "bağlantı bilinmiyor" yazar.

PDF: sayfanın bir kopyasının başına ve sonuna "Kaynak: <URL> · Alınma (erişim) tarihi: <tarih>"
damgası eklenir ve kurulu bir araçla basılır (`pdf_araci`): Google Chrome / Chromium / Edge
(headless `--print-to-pdf`) ya da Python `weasyprint` (isteğe bağlı bağımlılık). Sayfa
betikler kapalı basılır (CSP `script-src 'none'`); yerel sayfa basılırken ağ erişimi de engellenir (sayfa çevrimdışı, değişmeden basılır).
`canli=True`: sayfa özgün adresten yeniden indirilir (ağ açık; betikler yine kapalı).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

WEB_UZANTILARI = (".html", ".htm", ".xhtml")          # ingest'in okuduğu web biçimleri
BILINMIYOR = "bağlantı bilinmiyor"
OKUMA_SINIRI = 4 * 1024 * 1024          # adres aramak için okunan en çok bayt

KURULUM_NOTU = (
    "web sayfası kanıtlarının PDF kopyası için kurulu bir araç bulunamadı. Seçenekler (ücretsiz): "
    "(1) Google Chrome, Chromium ya da Microsoft Edge kurun; standart yerde değilse yolunu BIDR_CHROME "
    "ortam değişkenine yazın (macOS: /Applications/Google Chrome.app/Contents/MacOS/Google Chrome); "
    "(2) `pip install weasyprint` (Python; sistem kütüphaneleri gerekebilir: "
    "https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).")


class PdfHatasi(RuntimeError):
    pass


class PdfAraciYok(PdfHatasi):
    pass


def is_web(path: str | Path) -> bool:
    return Path(str(path)).suffix.lower() in WEB_UZANTILARI


# -- özgün adres ---------------------------------------------------------------------------------

_SAVED_FROM = re.compile(r"<!--\s*saved from url=\(\d+\)\s*(\S+?)\s*-->", re.I)
_SINGLEFILE = re.compile(r"Page saved with SingleFile.{0,200}?\burl:\s*(\S+)", re.I | re.S)
_TAG = re.compile(r"<(link|meta|base)\b([^>]*)>", re.I)
_ATTR = re.compile(r"""([a-zA-Z:_-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")


def _attrs(s: str) -> dict[str, str]:
    return {m.group(1).lower(): (m.group(2) or m.group(3) or m.group(4) or "") for m in _ATTR.finditer(s)}


def _temiz(u: str | None, *, kok_olmaz: bool = False) -> str | None:
    from bidr.file.links import clean_url
    from html import unescape
    u = clean_url(unescape(u or ""))
    if not u:
        return None
    if kok_olmaz:
        sp = urlsplit(u)
        if sp.path in ("", "/") and not sp.query and not sp.fragment:
            return None
    return u


def html_url(path: Path) -> tuple[str | None, str]:
    """Kaydedilmiş sayfanın kendi kaydındaki özgün adres: (adres | None, kaynak)."""
    try:
        with open(path, "rb") as f:
            raw = f.read(OKUMA_SINIRI)
    except OSError:
        return None, ""
    text = raw.decode("utf-8", errors="replace")
    if (m := _SAVED_FROM.search(text[:20_000])) and (u := _temiz(m.group(1))):
        return u, "saved_from"
    if (m := _SINGLEFILE.search(text[:20_000])) and (u := _temiz(m.group(1))):
        return u, "singlefile"
    found: dict[str, str] = {}
    for m in _TAG.finditer(text):
        tag, a = m.group(1).lower(), _attrs(m.group(2))
        if tag == "link" and "canonical" in a.get("rel", "").lower().split():
            found.setdefault("canonical", a.get("href", ""))
        elif tag == "meta" and (a.get("property") or a.get("name") or "").lower() == "og:url":
            found.setdefault("og_url", a.get("content", ""))
        elif tag == "base":
            found.setdefault("base", a.get("href", ""))
    for k in ("canonical", "og_url", "base"):
        if k in found and (u := _temiz(found[k], kok_olmaz=True)):
            return u, k
    return None, ""


def web_url(path: Path | None, baglanti: str | None = None, kaynak: str | None = None) -> tuple[str | None, str]:
    """Web kanıtının özgün adresi: dizindeki bağlantı (klasor hariç) → sayfanın kendi kaydı."""
    if baglanti and (kaynak or "") != "klasor" and (u := _temiz(baglanti)):
        return u, f"dizin:{kaynak or 'bilinmiyor'}"
    if path is not None:
        return html_url(Path(path))
    return None, ""


# -- damga ---------------------------------------------------------------------------------------

def damga_metni(url: str | None, tarih: str) -> str:
    return f"Kaynak: {url or BILINMIYOR} · Alınma (erişim) tarihi: {tarih}"


def _ascii_html(s: str) -> bytes:
    """HTML parçası, ASCII + karakter göndermeleri: sayfanın kodlaması ne olursa olsun doğru görünür."""
    return s.encode("ascii", "xmlcharrefreplace")


_STIL = ("font:9pt/1.3 Arial,Helvetica,sans-serif;color:#000;background:#f2f2f2;border:1px solid #777;"
         "padding:4px 6px;margin:{m};word-break:break-all;text-align:left;position:static;"
         "display:block;visibility:visible;float:none;clear:both;box-sizing:border-box;width:100%;"
         "min-width:100%;max-width:none;flex:0 0 100%;grid-column:1/-1;writing-mode:horizontal-tb")


def _css_dizesi(s: str) -> str:
    """CSS `content` dizesi, ASCII: ASCII dışı karakterler ve tırnaklar onaltılık kaçışla."""
    return '"' + "".join(c if (c.isascii() and c.isprintable() and c not in '"\\') else f"\\{ord(c):06x} "
                         for c in s) + '"'


def damgali_html(raw: bytes, metin: str, *, base: str | None = None) -> bytes:
    """Sayfanın başına (body'den hemen sonra) ve sonuna damga ekler. Alttaki damga `body::after`:
    kapanmamış tablo/kutu içinde kalmaz, her zaman gövdenin son öğesidir."""
    ust = _ascii_html(f'<div class="bidr-damga" style="{_STIL.format(m="0 0 8px 0")}">{escape(metin)}</div>')
    alt = "body::after{content:" + _css_dizesi(metin) + ";" + _STIL.format(m="8px 0 0 0") + "}"
    # betikler kapalı: sayfa kaydedildiği haliyle basılır (Chrome'un scriptEnabled=false ayarı
    # headless basımı bozar; CSP aynı işi sayfa içinden yapar)
    bas = (b'<meta http-equiv="Content-Security-Policy" content="script-src \'none\'">'
           + _ascii_html("<style>@page{margin:12mm}" + alt + "</style>"))
    if base:
        bas = _ascii_html(f'<base href="{escape(base, quote=True)}">') + bas
    m = re.search(rb"<head\b[^>]*>", raw, re.I) or re.search(rb"<html\b[^>]*>", raw, re.I)
    raw = raw[:m.end()] + bas + raw[m.end():] if m else bas + raw
    m = re.search(rb"<body\b[^>]*>", raw, re.I)
    return raw[:m.end()] + ust + raw[m.end():] if m else ust + raw


# -- araçlar -------------------------------------------------------------------------------------

_CHROME_ADLARI = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
                  "microsoft-edge", "msedge")
_CHROME_YOLLARI = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def chrome_yolu() -> str | None:
    env = os.environ.get("BIDR_CHROME")
    if env:
        return env if Path(env).expanduser().exists() else None
    for n in _CHROME_ADLARI:
        if (p := shutil.which(n)):
            return p
    for p in _CHROME_YOLLARI:
        if Path(p).expanduser().exists():
            return str(Path(p).expanduser())
    return None


class ChromeAraci:
    ad = "chrome"

    def __init__(self, exe: str, zaman_asimi: int = 120):
        self.exe, self.zaman_asimi = exe, zaman_asimi

    def bas(self, html: Path, pdf: Path, *, ag: bool = False) -> None:
        with tempfile.TemporaryDirectory(prefix="bidr-chrome-") as prof:
            cmd = [self.exe, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--disable-extensions", "--disable-background-networking", "--disable-sync",
                   "--disable-component-update", "--mute-audio", f"--user-data-dir={prof}",
                   "--no-pdf-header-footer", "--print-to-pdf-no-header",
                   "--run-all-compositor-stages-before-draw",
                   "--virtual-time-budget=5000", f"--print-to-pdf={pdf}"]
            if not ag:
                cmd.append("--host-resolver-rules=MAP * ~NOTFOUND")
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                cmd.append("--no-sandbox")
            cmd.append(Path(html).resolve().as_uri())
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.zaman_asimi)
            except subprocess.TimeoutExpired:
                raise PdfHatasi(f"Chrome {self.zaman_asimi} sn içinde bitirmedi") from None
            except OSError as e:
                raise PdfHatasi(f"Chrome çalıştırılamadı: {e}") from None
        if not _pdf_mi(pdf):
            tail = " ".join((r.stderr or "").split())[-300:]
            raise PdfHatasi(f"Chrome PDF üretmedi (çıkış {r.returncode}): {tail}")


class WeasyAraci:
    ad = "weasyprint"

    def bas(self, html: Path, pdf: Path, *, ag: bool = False) -> None:
        import weasyprint

        def fetcher(url, *a, **kw):
            if not ag and urlsplit(url).scheme in ("http", "https"):
                raise ValueError("ağ erişimi kapalı (yerel sayfa)")
            return weasyprint.default_url_fetcher(url, *a, **kw)
        try:
            weasyprint.HTML(filename=str(html), url_fetcher=fetcher).write_pdf(str(pdf))
        except Exception as e:  # noqa: BLE001 — aracın her hatası kanıt düzeyinde raporlanır
            raise PdfHatasi(f"weasyprint: {type(e).__name__}: {e}") from None
        if not _pdf_mi(pdf):
            raise PdfHatasi("weasyprint PDF üretmedi")


def _pdf_mi(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


ARACLAR = ("otomatik", "chrome", "weasyprint")


def pdf_araci(tercih: str = "otomatik"):
    """Kurulu PDF aracı; yoksa PdfAraciYok (kurulum notuyla)."""
    if tercih not in ARACLAR:
        raise ValueError(f"PDF aracı: {tercih} (seçenekler: {', '.join(ARACLAR)})")
    if tercih in ("otomatik", "chrome") and (exe := chrome_yolu()):
        return ChromeAraci(exe)
    if tercih in ("otomatik", "weasyprint"):
        try:
            import weasyprint  # noqa: F401
            return WeasyAraci()
        except Exception:  # noqa: BLE001 — kurulu değil ya da sistem kütüphanesi eksik
            pass
    if tercih == "chrome":
        raise PdfAraciYok("Chrome/Chromium/Edge bulunamadı. " + KURULUM_NOTU)
    raise PdfAraciYok(KURULUM_NOTU)


def _indir(url: str, zaman_asimi: int = 30) -> bytes:
    from urllib.request import Request, urlopen
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (bidr teslim)"})
    with urlopen(req, timeout=zaman_asimi) as r:      # noqa: S310 — yalnız http(s) (clean_url)
        return r.read()


def web_pdf(kaynak: Path, hedef: Path, *, url: str | None, tarih: str, arac, canli: bool = False) -> str:
    """Web kanıtının damgalı PDF kopyası → `hedef`. Döner: kullanılan kaynak (yerel | canli).
    Hata: PdfHatasi (hedef yazılmaz)."""
    if canli and url:
        try:
            raw, base, nereden = _indir(url), url, "canli"
        except Exception as e:  # noqa: BLE001
            raise PdfHatasi(f"sayfa indirilemedi ({url}): {type(e).__name__}: {e}") from None
    else:
        raw, base, nereden = Path(kaynak).read_bytes(), None, "yerel"
    with tempfile.TemporaryDirectory(prefix="bidr-teslim-") as td:
        src = Path(td) / "sayfa.html"
        src.write_bytes(damgali_html(raw, damga_metni(url, tarih), base=base))
        out = Path(td) / "cikti.pdf"
        arac.bas(src, out, ag=nereden == "canli")
        hedef.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out, hedef)
    return nereden
