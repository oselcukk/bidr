"""Belge kimliği (doc_id): maskeli kaynakta ÖZGÜN dosyanın sha256'sından, maskeli kopyanın baytından değil.

Panel akışında ingest'in kaynağı `bidr maskele --kaynak`ın maskeli kopyasıdır. Maskeli kopya yalnız METİN
kaynağıdır; baytı aynı özgün dosyadan yeniden üretilince değişebilir (PDF `/ID`, docx/xlsx zaman damgası,
maskeleme kodu ya da bölge kararı). Kimlik bayta bağlı kalırsa böyle bir yeniden üretim belgeyi "yeni belge"
yapar ve eski kimliğe bağlı bütün kayıtlar (karar, inceleme kararı, kanıt adı, birim kararı) öksüz kalır.

Kurallar:

- Kaynak bidr'in maskeli kopyasıysa (`.bidr-maskeleme.json`, mod `kaynak`) özgün sha256 maskeleme raporundan
  gelir (`hedef` = maskeli göreli yol → `sha256` = özgün dosyanın sha256'sı; rapor kaydında yoksa özgün dosya
  `kaynak_klasor` altından okunup özetlenir). Yeni belgenin kimliği özgün sha256'nın ilk 16 hanesidir.
- Kaynak maskeli kopya değilse eşleme yoktur: özgün = dosyanın kendisi, davranış eskisiyle aynıdır.
- Eski çalışma alanları (kimlik = maskeli kopyanın sha'sı) göç eder: var olan kimlik korunur ve
  `kimlikler.jsonl`'e sabitlenir (özgün sha256 → doc_id). Maskeli baytı değişmiş eski satırda özgün içerik
  maskeleme önbelleğinden (`kaynak_cikti`: maskeli sha256 → özgün sha256) doğrulanır; doğrulanamazsa ingest
  metin eşitliğine bakar; o da tutmazsa kimlik BELİRSİZDİR: kayıtlar silinmez, `_oksuz/` altına alınır ve
  `bidr next` `bidr kimlik-onar`a yönlendirir (model işi başlamaz).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from bidr.common import doc_id_from_sha, read_jsonl, sha256_file

from . import containers as C

MARKER = ".bidr-maskeleme.json"              # bidr.mask.run.MARKER (test eşitliği denetler)
REPORT_SUFFIX = ".maskeleme-raporu.json"     # bidr.mask.kaynak.REPORT_SUFFIX
ONBELLEK = ".cache/maske.sqlite"             # bidr.mask.onbellek.DOSYA
KAYIT = "kimlikler.jsonl"                    # <ws>: sabitlenen kimlikler {ozgun_sha256, doc_id, rel_path, kaynak, zaman}
OKSUZ_DIR = "_oksuz"                         # <ws>: kimliği belirsiz belgelerin kayıtları (silinmez)
BEKLEYEN = "bekleyen.jsonl"                  # <ws>/_oksuz: çözülmemiş belirsiz kimlikler


class Esleme:
    """Maskeli kopya → özgün dosya eşlemesi (maskeleme raporu)."""

    def __init__(self, source: Path, rapor: dict, rapor_yolu: Path):
        self.source = Path(source)
        self.rapor_yolu = rapor_yolu
        self.kaynak_klasor = Path(rapor["kaynak_klasor"]) if rapor.get("kaynak_klasor") else None
        self.kayit: dict[str, dict] = {}
        for r in rapor.get("dosyalar") or []:
            if isinstance(r, dict) and r.get("hedef"):
                self.kayit.setdefault(str(r["hedef"]), r)
        self._ozet: dict[str, str | None] = {}

    def dosya(self, rel: str) -> str | None:
        """Maskeli göreli yolun özgün göreli yolu (raporda yoksa None)."""
        r = self.kayit.get(rel)
        return str(r["dosya"]) if r and r.get("dosya") else None

    def ozgun(self, rel: str) -> str | None:
        """Maskeli göreli yolun (`rel`) özgün dosyasının sha256'sı; bilinemiyorsa None."""
        if rel in self._ozet:
            return self._ozet[rel]
        r = self.kayit.get(rel)
        sha = None
        if r is not None:
            s = str(r.get("sha256") or "").strip().lower()
            if len(s) == 64 and not r.get("donusum"):      # eski biçimden çevrilende sha çevrilmiş dosyanındır
                sha = s
            elif self.kaynak_klasor is not None and r.get("dosya") and C.SEP not in str(r["dosya"]):
                p = self.kaynak_klasor / str(r["dosya"])
                try:
                    if p.is_file():
                        sha = sha256_file(p)
                except OSError:
                    sha = None
        self._ozet[rel] = sha
        return sha


def maske_eslemesi(source: Path) -> Esleme | None:
    """`source` bidr'in maskeli kaynak kopyasıysa eşleme; değilse (ya da rapor okunamıyorsa) None."""
    source = Path(source)
    try:
        m = json.loads((source / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("mod") != "kaynak":
        return None
    adaylar = [Path(m["rapor"])] if m.get("rapor") else []
    adaylar.append(source.parent / (source.name + REPORT_SUFFIX))
    for p in adaylar:
        try:
            rapor = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rapor, dict) and isinstance(rapor.get("dosyalar"), list):
            return Esleme(source, rapor, p)
    return None


# ------------------------------------------------------------------ maskeleme önbelleği (salt okunur)

def _anahtar(*parts) -> str:
    """`bidr.mask.onbellek.anahtar` ile aynı (test eşitliği denetler); ingest maskeleme paketini yüklemesin."""
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
                          .encode("utf-8")).hexdigest()


def _onbellek_ac(ws_root: Path) -> sqlite3.Connection | None:
    p = Path(ws_root) / ONBELLEK
    if not p.is_file():
        return None
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=30)
        con.execute("SELECT 1 FROM k LIMIT 1").fetchone()
        return con
    except sqlite3.Error:
        return None


def onbellek_ozgun(ws_root: Path, maskeli_sha: str) -> str | None:
    """Maskeleme önbelleğine göre bu maskeli kopyanın (tam sha256) üretildiği özgün dosyanın sha256'sı."""
    con = _onbellek_ac(ws_root)
    if con is None or not maskeli_sha:
        return None
    try:
        row = con.execute("SELECT deger FROM k WHERE katman='kaynak_cikti' AND anahtar=?",
                          (_anahtar("kaynak_cikti", maskeli_sha),)).fetchone()
        v = json.loads(bytes(row[0]).decode("utf-8")) if row else None
    except (sqlite3.Error, ValueError):
        v = None
    finally:
        con.close()
    g = v.get("girdi") if isinstance(v, dict) else None
    s = str(g.get("sha") or "") if isinstance(g, dict) else ""
    return s if len(s) == 64 else None


def onbellek_tarihce(ws_root: Path) -> dict[str, str]:
    """Önbellekteki bütün kaynak kip çıktıları: maskeli kopyanın sha256'sının ilk 16 hanesi (eski doc_id) →
    özgün sha256. Tam maskeli sha'sı bilinmeyen eski kimlikler için (`bidr kimlik-onar`); çıktı baytlarını
    okuyup özetler (yavaş: önbellek boyutuyla orantılı)."""
    con = _onbellek_ac(ws_root)
    out: dict[str, str] = {}
    if con is None:
        return out
    try:
        rows = con.execute("SELECT deger FROM k WHERE katman='kaynak_cikti'").fetchall()
        for (d,) in rows:
            try:
                v = json.loads(bytes(d).decode("utf-8"))
                o, key = v["girdi"]["sha"], v["key"]
            except (ValueError, KeyError, TypeError):
                continue
            b = con.execute("SELECT deger FROM k WHERE katman='aday_cikti' AND anahtar=?", (key,)).fetchone()
            if b is not None and len(str(o)) == 64:
                out.setdefault(doc_id_from_sha(hashlib.sha256(bytes(b[0])).hexdigest()), str(o))
    except sqlite3.Error:
        pass
    finally:
        con.close()
    return out


# ------------------------------------------------------------------ sabitlenen kimlikler

def sabitler(ws_root: Path) -> dict[str, str]:
    """`kimlikler.jsonl`: özgün sha256 → doc_id (son kayıt geçerli)."""
    p = Path(ws_root) / KAYIT
    out: dict[str, str] = {}
    if p.is_file():
        for r in read_jsonl(p):
            if r.get("ozgun_sha256") and r.get("doc_id"):
                out[str(r["ozgun_sha256"])] = str(r["doc_id"])
    return out


def sabitle(ws_root: Path, yeni: list[dict]) -> None:
    if not yeni:
        return
    p = Path(ws_root) / KAYIT
    when = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(p, "a", encoding="utf-8") as f:
        for r in yeni:
            f.write(json.dumps({**r, "zaman": when}, ensure_ascii=False) + "\n")


def taban_metni(ws_root: Path, did: str, text_root: Path | None = None) -> str | None:
    """Belgenin ingest'ten çıkan (model öncesi) metni: ilk OCR (`text_ocr/`), yoksa betimleme öncesi
    (`text_pre_describe/`), yoksa `text/`. `text_root`: `text/` yerine bakılacak klasör (arşiv)."""
    ws_root = Path(ws_root)
    for p in (ws_root / "text_ocr" / f"{did}.txt", ws_root / "text_pre_describe" / f"{did}.txt",
              (text_root or ws_root / "text") / f"{did}.txt"):
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


class Kimlik:
    """Bir ingest koşusunun kimlik çözücüsü. `esleme` None ise (maskeli kaynak değil) kimlik içerik sha'sıdır."""

    def __init__(self, ws_root: Path, esleme: Esleme | None, prior_rows: list[dict]):
        self.ws = Path(ws_root)
        self.esleme = esleme
        self.sabit = sabitler(self.ws) if esleme is not None else {}
        self.yeni_sabit: list[dict] = []
        self.belirsiz: dict[str, dict] = {}        # yeni doc_id → {eski, rel_path, ozgun}: metin eşitliği bekliyor
        self.degisen: dict[str, str] = {}          # eski doc_id → neden (aynı yol, başka özgün: gerçekten değişti)
        ana = [r for r in prior_rows if r.get("doc_id") and not r.get("dup_of")]
        self._by_ozgun = {r["ozgun_sha256"]: r for r in ana if r.get("ozgun_sha256")}
        eski = [r for r in ana if not r.get("ozgun_sha256")]          # göç etmemiş satırlar
        self._eski_by_sha = {r["sha256"]: r for r in eski if r.get("sha256")}
        self._eski_by_rel = {r["rel_path"]: r for r in eski if r.get("rel_path")}

    def ozgun(self, rel: str, sha: str) -> str:
        """Satırın `ozgun_sha256` değeri: maskeli kaynakta özgün dosyanın sha'sı (bilinmiyorsa içerik sha'sı);
        maskeli kaynak değilse boş (kimlik içerik sha'sıdır, eski davranış)."""
        if self.esleme is None:
            return ""
        return self.esleme.ozgun(rel) or sha

    def _pin(self, ozgun: str, did: str, rel: str, kaynak: str) -> str:
        if self.sabit.get(ozgun) != did:
            self.sabit[ozgun] = did
            if did != doc_id_from_sha(ozgun):
                self.yeni_sabit.append({"ozgun_sha256": ozgun, "doc_id": did, "rel_path": rel, "kaynak": kaynak})
        return did

    def doc_id(self, ozgun: str, sha: str, rel: str) -> str:
        if self.esleme is None:
            return doc_id_from_sha(sha)
        if ozgun in self.sabit:
            return self.sabit[ozgun]
        r = self._by_ozgun.get(ozgun)
        if r is not None:                                   # kayıt dosyası yitmiş: envanter kimliği korur
            return self._pin(ozgun, r["doc_id"], rel, "envanter")
        r = self._eski_by_sha.get(sha)
        if r is not None:                                   # göç: maskeli bayt aynı → aynı belge
            return self._pin(ozgun, r["doc_id"], rel, "goc")
        r = self._eski_by_rel.get(rel)
        yeni = doc_id_from_sha(ozgun)
        if r is not None and r["doc_id"] != yeni:           # göç: aynı yol, maskeli bayt değişmiş
            once = onbellek_ozgun(self.ws, r.get("sha256") or "")
            if once == ozgun:
                return self._pin(ozgun, r["doc_id"], rel, "goc-onbellek")
            if once is None:
                self.belirsiz[yeni] = {"eski": r["doc_id"], "rel_path": rel, "ozgun": ozgun}
            else:
                self.degisen[r["doc_id"]] = "aynı yolda başka özgün dosya"
        return yeni

    def metinle_dogrula(self, yeni: str) -> str | None:
        """Belirsiz kimlik: yeni çıkarılan metin eski belgenin taban metniyle birebir aynıysa eski kimlik
        sabitlenir ve döner (yeni metin dosyası kaldırılır); değilse None (kimlik belirsiz kalır)."""
        b = self.belirsiz.get(yeni)
        if b is None:
            return None
        p = self.ws / "text" / f"{yeni}.txt"
        once = taban_metni(self.ws, b["eski"])
        if once is None or not p.is_file() or not any(ch.isalnum() for ch in once) \
                or p.read_text(encoding="utf-8", errors="replace") != once:
            return None
        p.unlink()
        del self.belirsiz[yeni]
        return self._pin(b["ozgun"], b["eski"], b["rel_path"], "goc-metin")

    def kaydet(self) -> None:
        sabitle(self.ws, self.yeni_sabit)
        self.yeni_sabit = []


# ------------------------------------------------------------------ belirsiz kimlikler

def bekleyenler(ws_root: Path) -> list[dict]:
    p = Path(ws_root) / OKSUZ_DIR / BEKLEYEN
    return list(read_jsonl(p)) if p.is_file() else []


def bekleyen_yaz(ws_root: Path, rows: list[dict]) -> None:
    p = Path(ws_root) / OKSUZ_DIR / BEKLEYEN
    if not rows:
        if p.exists():
            p.unlink()
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)
