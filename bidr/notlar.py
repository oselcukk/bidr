"""Bölümün belge notları (`belge-notlari.yaml`): kullanıcının bir belge hakkındaki kısa beyanı.

Biçim (çalışma alanında; panel işleyicisi yazar, elle de yazılabilir; JSON da geçerli YAML'dır):

    surum: 1
    notlar:
      - dosya: kurul/ek-3.pdf     # kaynak klasöre göre göreli yol (inventory.csv `rel_path`)
        sha256: <64 hane>         # isteğe bağlı; `dosya` ile ikisinden biri yeter
        metin: "2024 bahar dönemi bölüm kurulu kararının ekidir."
        kim: "..."                # kayıt için; modele gitmez
        tarih: "..."              # kayıt için; modele gitmez

Eşleme: `sha256` ya da `dosya` → inventory.csv satırı (kopya satırları dahil) → `doc_id`. Aynı içerikli
kopyaların notları aynı belgeye toplanır (aynı metin bir kez). Eşlenemeyen not yok sayılır, `unmatched` listeler.
Maskeli kaynakta dosyanın sha256'sı değişir; göreli yol tutar.

İlke: not bir İPUCU ve bağlamdır. Model aşamalarına (kaba/ince karar, kanıt adı, görsel betimleme) belgeye özgü
girdinin sonuna "Bölümün belge hakkındaki notu (kullanıcı beyanı)" diye eklenir; yalnız notu olan belgenin istemi
değişir (notsuz belgelerin istemi birebir aynı kalır, eskime olmaz). Not belgede olmayan bir şeyi kanıtlamaz:
alıntı yalnız belge metninden denetlenir (`verify_quote` metne karşı; not `text/`'e girmez), betimleme nottan cümle
aktaramaz (`leaks`). Not ile belge çelişirse karar belgeden verilir; model genel gerekçeyi `[not uyuşmuyor]` ile
başlatır (`conflict`), inceleme satırına uyarı düşer. Görsel okuma (transcribe) notu görmez: yazıya geçirme
birebirdir, not okumayı yanlılaştırabilir.

Notun değişmesi o belgeyi yeniden değerlendirmeye alır: karar paketlerinde not belge bilgisinin parçasıdır
(`decide` `girdi_degisti` → onaysız yeniden paketleme); betimleme ve kanıt adı kayıtları notun parmak izini
(`note_sha`) taşır, değişince yeniden paketlenir.
"""
from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path

import yaml

from bidr.candidates.text import fold

NOTLAR = "belge-notlari.yaml"
EN_COK = 1000                       # not metni sınırı (karakter); aşan kısım kesilir
NOT_ISARETI = "[not uyuşmuyor]"     # modelin genel gerekçesinin başı: not ile belge çelişiyor
_ISARET_RE = re.compile(r"^\s*\[?\s*not\s+uyusmuyor\s*\]?", re.IGNORECASE)
SIZINTI_SOZCUK = 5                  # betimlemede nottan aktarılan ardışık sözcük sayısı sınırı

BASLIK = "Bölümün belge hakkındaki notu (kullanıcı beyanı)"
ILKE = ("Bu not belge metni değildir; yalnız ipucu ve bağlamdır. Belgenin ne olduğunu anlamana yardım eder ama "
        "kanıt sayılmaz: belgede yazmayan bir şeyi not yüzünden var sayma.")
KURAL = {
    "karar": ("Alıntıyı yalnız BELGE METNİ'nden yap, nottan alıntı yapma. Not ile belge metni çelişiyorsa kararı "
              f"belge metnine göre ver ve genel \"gerekce\"yi \"{NOT_ISARETI}\" ile başlat."),
    "ad": ("Adı belge metnine dayandır; notta olup belgede olmayan tür, yıl, toplantı adı ekleme. Not ile belge "
           f"çelişiyorsa belgeye göre adlandır ve \"gerekce\"yi \"{NOT_ISARETI}\" ile başlat."),
    "betimleme": ("Yalnız görüntüde görüneni yaz: nottaki tarih, yer, kurum, kişi ya da etkinlik adını betimlemeye "
                  "ve görünen yazılara aktarma, nottan cümle kopyalama. Not yalnız neye baktığını anlaman içindir."),
}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def path(ws_root: Path | str) -> Path:
    return Path(ws_root) / NOTLAR


def _raw(ws_root: Path | str) -> list[dict]:
    p = path(ws_root)
    if not p.is_file():
        return []
    try:
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        raise ValueError(f"{p} okunamadı: {e}") from e
    items = (d or {}).get("notlar") if isinstance(d, dict) else d
    if items is None:
        return []
    if not isinstance(items, list):
        raise ValueError(f"{p}: `notlar` bir liste olmalı")
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        satirlar = str(it.get("metin") or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        metin = "\n".join(x for x in (re.sub(r"[ \t]+", " ", s).strip() for s in satirlar) if x)[:EN_COK].strip()
        if not metin:
            continue
        out.append({"dosya": str(it.get("dosya") or "").replace("\\", "/").strip("/"),
                    "sha256": str(it.get("sha256") or "").strip().lower(), "metin": metin,
                    "kim": str(it.get("kim") or ""), "tarih": str(it.get("tarih") or "")})
    return out


def _inventory(ws_root: Path | str) -> tuple[dict[str, str], dict[str, str]]:
    """(rel_path → doc_id, sha256 → doc_id); kopya satırları dahil (kopyanın doc_id'si özgününkiyle aynı)."""
    p = Path(ws_root) / "inventory.csv"
    by_rel, by_sha = {}, {}
    if not p.is_file():
        return by_rel, by_sha
    with open(p, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            did = r.get("doc_id") or ""
            if not did:
                continue
            if r.get("rel_path"):
                by_rel[r["rel_path"].replace("\\", "/")] = did
            if r.get("sha256"):
                by_sha[r["sha256"].lower()] = did
    return by_rel, by_sha


def load(ws_root: Path | str) -> dict[str, list[dict]]:
    """doc_id → notlar (dosya sırasıyla; aynı metin bir kez). Not dosyası ya da envanter yoksa boş."""
    by_rel, by_sha = _inventory(ws_root)
    out: dict[str, list[dict]] = {}
    for n in _raw(ws_root):
        did = by_sha.get(n["sha256"]) or by_rel.get(n["dosya"])
        if not did:
            continue
        lst = out.setdefault(did, [])
        if all(x["metin"] != n["metin"] for x in lst):
            lst.append(n)
    return out


def unmatched(ws_root: Path | str) -> list[dict]:
    """Envanterde karşılığı olmayan notlar (dosya kaldırılmış ya da yol/sha yanlış)."""
    by_rel, by_sha = _inventory(ws_root)
    return [n for n in _raw(ws_root) if not (by_sha.get(n["sha256"]) or by_rel.get(n["dosya"]))]


def text_of(notes: list[dict] | None) -> str:
    """Modele gidecek not metni (kim/tarih yok). Birden çok not ayrı satırda."""
    ms = [n["metin"] for n in notes or []]
    return "\n".join(ms) if len(ms) < 2 else "\n".join(f"- {m}" for m in ms)


def note_sha(notes: list[dict] | None) -> str:
    """Notun parmak izi (boş: not yok). Kayıtlar bunu taşır; değişince belge yeniden değerlendirilir."""
    t = text_of(notes)
    return _sha(t) if t else ""


def block(notes: list[dict] | None, kind: str = "karar") -> str:
    """İsteme eklenen not bloğu (not yoksa boş dize)."""
    t = text_of(notes)
    if not t:
        return ""
    t = t.replace("<<<", "‹‹‹").replace(">>>", "›››")
    return f"{BASLIK}:\n<<<\n{t}\n>>>\n{ILKE} {KURAL[kind]}"


def with_note(base: str, notes: list[dict] | None, kind: str = "karar") -> str:
    """Belgeye özgü bir girdinin (ör. belge bilgisi) sonuna not bloğu; not yoksa `base` aynen döner."""
    b = block(notes, kind)
    return f"{base}\n\n{b}" if b else base


def conflict(gerekce: str | None) -> bool:
    """Model genel gerekçeyi `[not uyuşmuyor]` ile başlattı mı (not ile belge içeriği çelişiyor)."""
    return bool(_ISARET_RE.match(fold(gerekce or "")))


def _words(s: str) -> list[str]:
    return re.findall(r"\w+", fold(s))


def leaks(notes: list[dict] | None, text: str, n: int = SIZINTI_SOZCUK) -> list[str]:
    """Metinde nottan birebir aktarılmış `n` sözcüklük diziler (betimleme denetimi). Boş: sızıntı yok."""
    nw = _words(text_of(notes))
    if len(nw) < n:
        return []
    grams = {tuple(nw[i:i + n]) for i in range(len(nw) - n + 1)}
    tw = _words(text)
    hits = []
    for i in range(len(tw) - n + 1):
        g = tuple(tw[i:i + n])
        if g in grams and " ".join(g) not in hits:
            hits.append(" ".join(g))
    return hits
