"""Kanıt bağlantıları (model yok). Raporun "Kanıtlar" hücresinde kanıt adı tıklanabilir
bağlantı olur. Öncelik: insan > belge metni > klasör.

1. `insan`: review.xlsx "bağlantı" sütunundaki düzeltme (`bidr audit apply` →
   `kanit-baglantilari.jsonl`, `kaynak: insan`). Bağlantı belgeye aittir.
2. `belge_metni`: kamuya açık belge yayımlandığı adrese bağlanır. Adres belge metninden
   bulunur: web sayfası çıktılarının üst/altbilgisi (sayfanın ilk/son satırları) ya da birden
   çok sayfada tek başına satır olarak yinelenen URL; gövdede geçen URL yalnız
   `rapor.yayin_alan_adlari`'ndaki bir alan adındaysa (ör. gtu.edu.tr; alt alan adları dahil).
   Alan adının ana sayfası (kurum yazısı altbilgisindeki "www.….edu.tr") sayılmaz. Model yok;
   yalnız öneridir, insan review.xlsx'te düzeltir.
3. `klasor`: yayımlanmamış belge, kanıt klasörü yüklendikten sonra
   `rapor.kanit_kok_baglanti` + `evidence/`'e göre göreli yol (yüzde kodlu). Yükleme
   kullanıcının işidir; bidr hiçbir yere yüklemez.

Hiçbiri yoksa bağlantı boş kalır ve kanıt gaps.md'nin "bağlantı yok" listesine girer.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlsplit

from bidr.common import read_jsonl, write_jsonl

LINKS = "kanit-baglantilari.jsonl"
KAYNAKLAR = ("insan", "belge_metni", "klasor")
EDGE_LINES = 2                  # sayfanın üst/alt bilgisi sayılan satır sayısı (her uçta)
GAPS_BEGIN = "<!-- bidr:baglanti-yok -->"
GAPS_END = "<!-- /bidr:baglanti-yok -->"

_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'«»“”]+", re.IGNORECASE)
_TRAIL = ".,;:)]}>'\"’”"


def clean_url(u: str) -> str | None:
    """Biçimi geçerli http(s) adresi ya da None. `www.` ile başlayana https eklenir."""
    u = (u or "").strip().rstrip(_TRAIL)
    if not u:
        return None
    if u.lower().startswith("www."):
        u = "https://" + u
    try:
        sp = urlsplit(u)
    except ValueError:
        return None
    if sp.scheme.lower() not in ("http", "https") or "." not in sp.netloc or " " in u:
        return None
    return u


def _host(u: str) -> str:
    return urlsplit(u).hostname or ""


def _in_domains(u: str, domains: list[str]) -> bool:
    h = _host(u).lower()
    return any(h == d or h.endswith("." + d) for d in (x.lower().strip(".") for x in domains if x))


def _is_root(u: str) -> bool:
    """Alan adının ana sayfası (yol/sorgu yok): kurum yazılarının altbilgisindeki "www.…edu.tr"
    gibi; belgenin yayın adresi değildir."""
    sp = urlsplit(u)
    return sp.path in ("", "/") and not sp.query


def published_url(text: str | None, domains: list[str] | tuple = ()) -> str | None:
    """Belge metninde yayın adresi (yoksa None).

    Güçlü: sayfanın üst/altbilgisindeki (ilk/son EDGE_LINES satır) URL ya da birden çok sayfada
    tek başına satır olarak yinelenen URL (tarayıcı çıktısı). Zayıf (yalnız `domains`
    içindeyse): gövdede ya da tek başına satırda bir kez geçen URL. Ana sayfa adresleri
    (yolsuz) sayılmaz. En sık geçen kazanır, eşitlikte ilk."""
    if not text:
        return None
    strong: Counter = Counter()
    weak: Counter = Counter()
    pages_alone: dict[str, set[int]] = {}
    first: dict[str, int] = {}
    pos = 0
    for pno, page in enumerate(text.split("\f")):
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        edge = set(range(min(EDGE_LINES, len(lines)))) | set(range(max(0, len(lines) - EDGE_LINES), len(lines)))
        for i, ln in enumerate(lines):
            for m in _URL.finditer(ln):
                u = clean_url(m.group(0))
                if not u or _is_root(u):
                    continue
                pos += 1
                first.setdefault(u, pos)
                alone = len(ln) - len(m.group(0)) <= 12          # satırda URL'den başka az şey (sayfa no)
                if i in edge:
                    strong[u] += 1
                elif alone:
                    pages_alone.setdefault(u, set()).add(pno)
                if i not in edge and _in_domains(u, list(domains)):
                    weak[u] += 1
    for u, ps in pages_alone.items():
        if len(ps) >= 2:
            strong[u] += len(ps)
    for c in (strong, weak):
        if c:
            return sorted(c, key=lambda u: (-c[u], first[u]))[0]
    return None


def folder_url(root: str | None, rel: str | None) -> str | None:
    """Kök bağlantı + evidence/'e göre göreli yol (her parça yüzde kodlu)."""
    if not root or not rel:
        return None
    root = clean_url(str(root))
    if not root:
        return None
    return root.rstrip("/") + "/" + "/".join(quote(p, safe="") for p in rel.split("/") if p)


# -- insan düzeltmeleri ----------------------------------------------------------------------

def load_links(*dirs) -> dict[str, dict]:
    """doc_id → insan bağlantı kaydı. Sonraki klasör öncekini ezer."""
    out: dict[str, dict] = {}
    seen: set[Path] = set()
    for d in dirs:
        if not d:
            continue
        p = Path(d).expanduser().resolve() / LINKS
        if p in seen or not p.exists():
            continue
        seen.add(p)
        for r in read_jsonl(p):
            if r.get("doc_id") and r.get("baglanti") and r.get("kaynak") == "insan":
                out[r["doc_id"]] = r
    return out


def upsert_links(path: Path, recs: list[dict]) -> int:
    path = Path(path)
    cur = {r["doc_id"]: r for r in read_jsonl(path)} if path.exists() else {}
    n = 0
    for r in recs:
        if cur.get(r["doc_id"], {}).get("baglanti") != r["baglanti"]:
            n += 1
        cur[r["doc_id"]] = r
    path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(path, [cur[k] for k in sorted(cur)])
    return n


def parse_link_edits(xrows: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """review.xlsx "bağlantı" düzeltmeleri → `kanit-baglantilari.jsonl` kayıtları (`kaynak: insan`).
    Düzeltme = hücre dolu ve öneriden farklı. Aynı belgenin satırlarında farklı bağlantı ya da
    http(s) olmayan değer geçersiz (hata anahtarı `baglanti:<doc_id>`)."""
    by: dict[str, dict[str, list[str]]] = {}
    prev: dict[str, str] = {}
    for xr in xrows:
        sid = str(xr.get("satir") or "")
        v = str(xr.get("baglanti") or "").strip()
        o = str(xr.get("baglanti_oneri") or "").strip()
        if not sid or "|" not in sid or not v or v == o:
            continue
        did = sid.split("|", 1)[0]
        by.setdefault(did, {}).setdefault(v, []).append(sid)
        prev[did] = o
    recs, errs = [], {}
    for did in sorted(by):
        vs = by[did]
        if len(vs) > 1:
            errs[f"baglanti:{did}"] = "aynı belgenin satırlarında farklı bağlantılar: " + " | ".join(vs)
            continue
        (v, sids), = vs.items()
        u = clean_url(v)
        if not u:
            errs[f"baglanti:{did}"] = f"bağlantı '{v}' geçersiz (http:// ya da https:// ile tam adres)"
            continue
        recs.append({"doc_id": did, "baglanti": u, "kaynak": "insan", "onceki": prev[did],
                     "satirlar": sorted(sids), "zaman": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return recs, errs


# -- çözümleyici -------------------------------------------------------------------------------

class LinkResolver:
    """Belge → (bağlantı, kaynak). `text_of(doc_id)` belge metnini verir (yoksa None)."""

    def __init__(self, human: dict[str, dict], text_of, *, root: str | None = None,
                 domains: list[str] | tuple = ()):
        self.human, self.text_of, self.root, self.domains = human, text_of, root, list(domains or [])
        self._pub: dict[str, str | None] = {}

    @classmethod
    def load(cls, ws_root: Path, *extra_dirs, text_of=None) -> "LinkResolver":
        from bidr.common import Workspace
        from bidr.write.sources import rapor_section
        ws = Workspace(Path(ws_root))
        if text_of is None:
            def text_of(did: str) -> str | None:
                p = ws.text_path(did)
                return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None
        sec = rapor_section(ws.root)
        doms = sec.get("yayin_alan_adlari")
        if not doms:
            doms = _institution_domains(ws.root)   # yapılandırmada yoksa kurum profilinden
        if isinstance(doms, str):
            doms = [doms]
        doms = doms or []
        return cls(load_links(ws.root, *extra_dirs), text_of, root=sec.get("kanit_kok_baglanti"),
                   domains=[str(d) for d in doms])

    def published(self, did: str) -> str | None:
        if did not in self._pub:
            self._pub[did] = published_url(self.text_of(did), self.domains)
        return self._pub[did]

    def suggest(self, did: str, aliases: list[str] | tuple = ()) -> tuple[str, str]:
        """Dosya yolu bilinmeden (audit): insan ya da belge metni."""
        for x in [did, *aliases]:
            r = self.human.get(x)
            if r:
                return r["baglanti"], "insan"
        u = self.published(did)
        return (u, "belge_metni") if u else ("", "")

    def resolve(self, did: str, rel: str | None, aliases: list[str] | tuple = ()) -> tuple[str, str]:
        u, src = self.suggest(did, aliases)
        if u:
            return u, src
        f = folder_url(self.root, rel)
        return (f, "klasor") if f else ("", "")


def links_sha(ws_root: Path, review_dir: Path | None = None) -> str:
    """Bağlantı kaynaklarının özeti (insan kayıtları + rapor yapılandırması): file güncelliği için."""
    from bidr.write.sources import rapor_section
    ps = dict.fromkeys([(Path(ws_root) / LINKS).resolve(), (Path(review_dir or ws_root) / LINKS).resolve()])
    h = hashlib.sha256()
    for p in ps:
        h.update(p.read_bytes() if p.exists() else b"-")
    sec = rapor_section(Path(ws_root))
    h.update(repr((sec.get("kanit_kok_baglanti"), sec.get("yayin_alan_adlari"))).encode())
    return h.hexdigest()[:16]


# -- gaps.md "bağlantı yok" bölümü -------------------------------------------------------------

def gaps_block(rows: list[dict]) -> str:
    """evidence-index satırlarından "bağlantı yok" bölümü (işaretleyicilerle)."""
    miss = [r for r in rows if not (r.get("baglanti") or "").strip()]
    L = [GAPS_BEGIN, "## Bağlantısı olmayan kanıtlar", ""]
    if not miss:
        L.append("Bütün kanıtların bağlantısı var.")
    else:
        L += ["Bu kanıtların raporda tıklanabilir bağlantısı yok: belge metninde yayın adresi bulunamadı, "
              "review.xlsx'te bağlantı yazılmadı ve config.yaml `rapor.kanit_kok_baglanti` tanımlı değil. "
              "Kamuya açık belgeyse yayımlandığı adresi review.xlsx \"bağlantı\" sütununa yazın "
              "(sonra `bidr audit apply` ve `bidr file`); değilse kanıt klasörünü yükleyip kök adresi "
              "config.yaml'a girin.", ""]
        for r in miss:
            L.append(f"- {r.get('olcut')} [{r.get('kanit_no')}] {r.get('ad')} (`{r.get('doc_id')}`)")
    L.append(GAPS_END)
    return "\n".join(L) + "\n"


def extract_block(text: str, begin: str = GAPS_BEGIN, end: str = GAPS_END) -> str | None:
    a, b = text.find(begin), text.find(end)
    if a < 0 or b < a:
        return None
    return text[a:b + len(end)] + "\n"


def update_gaps(path: Path, block: str, begin: str = GAPS_BEGIN, end: str = GAPS_END) -> None:
    """gaps.md'deki işaretli bölümü değiştirir (yoksa sona ekler). gaps.md yoksa yalnız bölüm
    yazılır. Varsayılan bölüm "bağlantı yok"; `bidr file` ayrıca "kanıt seçimi" bölümünü yazar."""
    path = Path(path)
    cur = path.read_text(encoding="utf-8") if path.exists() else ""
    old = extract_block(cur, begin, end)
    if old is not None:
        new = cur.replace(old, block)
    else:
        new = (cur.rstrip() + "\n\n" if cur.strip() else "") + block
    if new != cur:
        path.write_text(new, encoding="utf-8")


def _institution_domains(ws_root: Path) -> list[str]:
    """`config.yaml` `bidr.kurum` → `bidr/data/institutions/<kurum>.yaml` `yayin_alan_adlari`."""
    import yaml
    try:
        cfg = yaml.safe_load((Path(ws_root) / "config.yaml").read_text(encoding="utf-8")) or {}
        kurum = (cfg.get("bidr") or {}).get("kurum")
        if not kurum:
            return []
        p = Path(__file__).resolve().parents[1] / "data" / "institutions" / f"{kurum}.yaml"
        return list((yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("yayin_alan_adlari") or [])
    except Exception:
        return []
