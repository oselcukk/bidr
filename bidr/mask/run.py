"""`bidr maskele`: dosyalanmış kanıtların (evidence/) maskeli yayın kopyası → `evidence-maskeli/`.

Asıl dosyalara dokunulmaz. Her kopya maskelemeden sonra bağımsız olarak yeniden taranır;
kişisel veri, imza şüphesi ya da temizlenmemiş üst veri/yorum/ek kalırsa (`basarisiz`) ya da
metin katmanı olmayan sayfa/görsel OCR'dan geçemezse (`taranamadi`) kopya `evidence-maskeli/`'ye
girmez, `maskeleme-basarisiz/` altına alınır ve `maskeleme-raporu.json`'da `yayimlanamaz`
listesine yazılır (`elle_bakilmali: true`). Desteklenmeyen biçimler kopyalanmaz, aynı listeye girer;
eski biçimler (.doc/.xls/.ppt/.pptx/.msg) çevrilip maskelenir (`eski`). Rapora bulunan değerlerin
kendisi yazılmaz; yalnız tür, sayı ve bölge kutusu.

Bölgeler (`bolge`): her tespit kimlikli bir bölgedir; insan kararları (`maskeleme-kararlari.jsonl`)
bölge kimliğiyle uygulanır, elle maskelenmiş sürümler (`maskeleme-elle.json`) kanıt değişmedikçe
kullanılır (`elle_maskelendi`). Son adım redaksiyon doğrulaması (`dogrula`). Önbellek
(`onbellek`, `<ws>/.cache/maske.sqlite`): değişmeyen dosya yeniden işlenmez, kural değişince OCR
yeniden çalışmaz. Teslim kapısı (`bidr/teslim/run.py`): `bekliyor(kayıt)` doğru olan dosya pakete
girmez.
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .detect import MaskRules, mask_text, read_ws_config
from .formats import MaskError, kind_of, mask_file, pdf_engine, scan_file
from .ocr import ocr_available as raster_ocr_available

OUT_DIR = "evidence-maskeli"
FAIL_DIR = "maskeleme-basarisiz"
REPORT = "maskeleme-raporu.json"
MARKER = ".bidr-maskeleme.json"
INDEX = "evidence-index.csv"
INDEX_OUT = "evidence-index-maskeli.csv"
INDEX_MASK_COLS = ("ad", "alintilar", "kaynak")
SURUM = 1


class MaskRunError(RuntimeError):
    pass


def _inside(a: Path, b: Path) -> bool:
    try:
        a.relative_to(b)
        return True
    except ValueError:
        return False


def _prepare_dir(d: Path) -> None:
    if d.exists():
        if any(d.iterdir()) and not (d / MARKER).exists():
            raise MaskRunError(f"{d} bidr'in üretmediği dosyalar içeriyor; taşıyın ya da başka --out verin")
        shutil.rmtree(d)
    d.mkdir(parents=True)


def _files(ev: Path) -> list[Path]:
    return sorted(p for p in ev.rglob("*")
                  if p.is_file() and not any(part.startswith(".") for part in p.relative_to(ev).parts))


def _c(c) -> dict:
    return dict(sorted((k, v) for k, v in (c or {}).items() if v))


# Modelin görsel okuma metninde (çalışma alanı `text/<doc_id>.txt`; sayfalar form feed ile ayrılır)
# aranan ve maskelemenin o sayfada kapatmış olması gereken türler.
MODEL_KINDS = {"tc_no": "kimlik no", "telefon": "telefon", "eposta": "e-posta", "ogrenci_no": "öğrenci no",
               "iban": "IBAN"}
EL_YAZISI_SORUN = "elle bakılmalı: el yazısı kişisel veri kapatılamadı"


def model_text_gaps(model_text: str, res: dict, rules: MaskRules) -> tuple[list[str], str | None]:
    """Modelin okuduğu metinde bir sayfada kimlik no/telefon/e-posta/öğrenci no varken maskeleme o
    sayfada o türden daha azını kapattıysa (OCR el yazısını okuyamadı, etiketi de bulunamadı) →
    (["s.N: tür, tür", …], uyarı). Değerler yazılmaz; yalnız tür ve sayfa. Maskeleyici sayfa kapsamı
    vermediyse (sayfasız biçim, pypdf motoru) belge bütünü karşılaştırılır ("belge: tür"). Sayfa
    sayısı uyuşmuyorsa denetim yapılmaz (uyarı döner)."""
    from .detect import detect
    kapsam = res.get("sayfa_kapsam")
    if kapsam is None:                    # sayfasız biçim (metin, docx …) ya da pypdf: belge bütünü
        want = Counter(f.kind for f in detect(model_text, rules) if f.kind in MODEL_KINDS)
        have = res.get("maskelenen") or {}
        eksik = [MODEL_KINDS[k] for k in MODEL_KINDS if want[k] > have.get(k, 0)]
        return ([f"belge: {', '.join(eksik)}"] if eksik else []), None
    pages = model_text.split("\f")
    n = res.get("sayfa_sayisi") or len(kapsam)
    if len(pages) == n + 1 and not pages[-1].strip():       # sondaki form feed
        pages = pages[:-1]
    if len(pages) != n:
        return [], f"model metni denetimi yapılamadı (sayfa sayısı uyuşmuyor: metin {len(pages)}, dosya {n})"
    out = []
    for i, t in enumerate(pages, 1):
        want = Counter(f.kind for f in detect(t, rules) if f.kind in MODEL_KINDS)
        have = kapsam.get(i) or kapsam.get(str(i)) or {}
        eksik = [MODEL_KINDS[k] for k in MODEL_KINDS if want[k] > have.get(k, 0)]
        if eksik:
            out.append(f"s.{i}: " + ", ".join(eksik))
    return out, None


def _clean_bolgeler(bolgeler: list[dict]) -> list[dict]:
    return [{k: v for k, v in b.items() if not k.startswith("_")} for b in bolgeler or []]


def _sayfalar(bs: list[dict]) -> str:
    return ", ".join(f"s.{n}" for n in sorted({b["sayfa"] for b in bs}))


def mask_and_check(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None = None, *,
                   kararlar: dict[str, dict] | None = None, sha: str | None = None, kind: str | None = None) -> dict:
    """Tek dosya: tara → maskele (`dst`; bölgeler kimlikli, insan kararları uygulanır) → maskeli kopyayı
    bağımsız yeniden tara → bölgeleri uzlaştır → redaksiyon doğrulaması.

    → kayıt alanları: `durum` (tamam | basarisiz | taranamadi | hata), `elle_bakilmali`, `neden`,
    `bulunan`/`maskelenen`/`kalan` (tür → sayı), `temizlenen`, `kalan_sorunlar`, `uyarilar`, imza
    alanları, `bolgeler` (PDF/PyMuPDF ve görsellerde; bkz. `bolge`). `hata`da `dst` silinir; diğer
    durumlarda maskeli kopya `dst`'de kalır (nereye konacağına çağıran karar verir). Değerlerin
    kendisi yazılmaz. `sha`: kaynak dosyanın sha256'sı (bölge kimliği; verilmezse hesaplanır)."""
    from . import bolge as BG
    from . import dogrula
    from .onbellek import sha256_file
    sha = sha or sha256_file(src)
    kind = kind or kind_of(src) or ""
    bg = BG.Baglam(sha[:8], BG.dosya_kararlari(kararlar or {}, sha[:8]))
    rec: dict = {}
    try:
        before = scan_file(src, rules)
    except Exception as e:
        before = {"bulgular": Counter(), "sorunlar": [f"kaynak taranamadı: {type(e).__name__}"], "imza": []}
    try:
        res = mask_file(src, dst, rules, engine=eng, bolge=bg)
        after = scan_file(dst, rules)
    except (MaskError, Exception) as e:   # bozuk dosya vb.
        if dst.exists():
            dst.unlink()
        rec.update(durum="hata", elle_bakilmali=True, neden=f"maskelenemedi: {type(e).__name__}: {e}"[:300],
                   bulunan=_c(before["bulgular"]))
        return rec
    kalan = after["bulgular"]
    sorunlar = list(after["sorunlar"])
    model_uyari = []
    bolgeli = res.get("bolgeler") is not None and after.get("bolge_adaylari") is not None
    taranamadi = list(after.get("taranamadi") or [])
    if bolgeli:
        # yeniden taramanın adayları: bilinen bölgeyle örtüşen açıklanmış sayılır (kapatıldı/bırakıldı ya
        # da zaten onay bekliyor); örtüşmeyen yeni bölge olarak onay bekler
        for a in after["bolge_adaylari"]:
            if bg.acikla(a) is None:
                bg.sayfa(a["sayfa"], [dict(a, id=None)], ilk=False)
        sorunlar = [s for s in sorunlar if not s.startswith("imza:")]
        taranamadi = []
    gaps: list[str] = []
    if model_text is not None:
        gaps, note = model_text_gaps(model_text, res, rules)
        if note:
            model_uyari.append(note)
        if bolgeli and gaps:
            kalan_gaps = []
            for g in gaps:
                sn = int(g.split(":")[0][2:]) if g.startswith("s.") else 1
                box = (res.get("sayfa_kutulari") or {}).get(sn) or [0, 0, 0, 0]
                b = BG.yeni(sn, box, "kisisel_veri", BG.ONAY, f"model metninde kapatılmamış: {g.split(':', 1)[-1].strip()}",
                            "model_metni", 0.4)
                bg.sayfa(sn, [b], ilk=False)
                if b["karar"] != BG.BIRAKILDI:
                    kalan_gaps.append(g)
            gaps = kalan_gaps
        if gaps:
            rec["el_yazisi_elle"] = gaps
            sorunlar.append(f"{EL_YAZISI_SORUN} ({'; '.join(gaps)})")
    if bolgeli:
        onay = BG.onay_bekleyen(bg.bolgeler)
        # m1 (yapi) bölgeleri: etiketsiz aday / metinle örtüşen (kapatıldı, ad OCR'dan) nedenle ayrılır
        mt = [b for b in onay if b["tur"] == "imza" and (b["kaynak"] == "imza_metin" or "metinle örtüşen" in b["neden"])]
        et = [b for b in onay if b["tur"] == "imza" and b not in mt
              and (b["kaynak"] in ("imza_etiketsiz", "etiketsiz_aday") or "etiketsiz" in b["neden"])]
        kl = [b for b in onay if b["tur"] == "imza" and b not in mt and b not in et]
        if et:
            sorunlar.append("imza: elle bakılmalı (" + _sayfalar(et) + ")")
            rec["imza_elle"] = [f"s.{n}" for n in sorted({b["sayfa"] for b in et})]
        if mt:
            from .formats import IMZA_METIN_SORUN
            sorunlar.append(IMZA_METIN_SORUN + " (" + _sayfalar(mt) + ")")
            rec["imza_metin_elle"] = len(mt)
            rec["imza_metin_yer"] = [f"s.{n}" for n in sorted({b["sayfa"] for b in mt})]
        if kl:
            sorunlar.append(f"imza: kapatılamayan aday ×{len(kl)}")
        taranamadi = [(f"s.{b['sayfa']}: " if res.get("sayfa_sayisi", 1) > 1 or kind == "pdf" else "görsel: ")
                      + b["neden"].removeprefix("okunamadı: ") for b in onay if b["tur"] == "okunamayan_sayfa"]
        dog = dogrula.dogrula(dst, kind, bg.bolgeler, eng)
        if dog:
            rec["redaksiyon_dogrulama"] = dog
            sorunlar.append(f"redaksiyon doğrulaması başarısız ({len(dog)} kutu): " + "; ".join(dog[:3]))
        rec["bolgeler"] = _clean_bolgeler(bg.bolgeler)
        rec["bolge_ozet"] = BG.ozet(bg.bolgeler)
        if onay:
            rec["onay_bekleyen"] = len(onay)
    elif after.get("imza_aday"):
        sorunlar.append(f"imza: kapatılamayan aday ×{after['imza_aday']}")
    rec.update(bulunan=_c(before["bulgular"]), maskelenen=_c(res["maskelenen"]), kalan=_c(kalan),
               temizlenen=res["temizlenen"], kalan_sorunlar=sorunlar,
               uyarilar=list(res["uyarilar"]) + list(after.get("uyarilar") or []) + model_uyari + bg.uyarilar)
    if before["imza"]:
        rec["imza_uyarisi"] = before["imza"]
    if res.get("imza_bolgesi"):
        rec["imza_bolgesi"] = res["imza_bolgesi"]
        rec["imza_ortusen_kelime"] = res.get("ortusen_kelime", 0)
    if not bolgeli:
        if after.get("imza_elle"):
            rec["imza_elle"] = after["imza_elle"]
        if after.get("imza_metin"):
            rec["imza_metin_elle"] = len(after["imza_metin"])         # metinle örtüştüğü için kapatılmayan
            rec["imza_metin_yer"] = after["imza_metin"]
    if taranamadi:
        rec["taranamadi"] = taranamadi
    if kalan or sorunlar or taranamadi:
        parts = [f"{k}×{n}" for k, n in sorted(kalan.items())] + list(sorunlar)
        if kalan or sorunlar:
            durum, neden = "basarisiz", "maskeleme başarısız; kalan: " + ", ".join(parts)
            if taranamadi:
                neden += "; taranamadı: " + "; ".join(taranamadi)
        else:
            durum = "taranamadi"
            neden = "maskeleme eksik, elle bakılmalı: taranamadı (" + "; ".join(taranamadi) + ")"
        rec.update(durum=durum, neden=neden[:600], elle_bakilmali=True)
    else:
        rec.update(durum="tamam", elle_bakilmali=False)
    return rec


# ---------------------------------------------------------------- önbellekli dosya işi

KURAL_SURUM = 2            # tespit/kapatma kuralları elle sürümü (kod parmak izi ayrıca anahtara girer)
_KOD_MODULLERI = ("detect", "formats", "raster", "imza", "alan", "ocr", "bolge", "dogrula", "yapi", "sablon",
                  "run", "eski")


def _kod_izi() -> str:
    import hashlib
    h = hashlib.sha256()
    base = Path(__file__).parent
    for m in _KOD_MODULLERI:
        f = base / f"{m}.py"
        if f.is_file():
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def kural_izi(rules: MaskRules) -> str:
    """Kural parmak izi (ad listesi yalnız özetiyle)."""
    from .onbellek import anahtar
    return anahtar(list(rules.kinds), list(rules.student_patterns), sorted(rules.names), rules.label_fields,
                   rules.local_model)


def aday_anahtari(sha: str, rules: MaskRules, eng: str, kararlar: dict[str, dict], model_text: str | None,
                  kind: str | None) -> str:
    from .onbellek import anahtar, sha256
    from .ocr import tesseract_version
    kk = sorted((k, v.get("karar"), json.dumps(v.get("kutu")), v.get("kaynak")) for k, v in kararlar.items())
    ocr = raster_ocr_available()
    return anahtar("aday", sha, KURAL_SURUM, _kod_izi(), kural_izi(rules), eng, kind, kk,
                   sha256(model_text.encode("utf-8")) if model_text is not None else None,
                   ocr, tesseract_version() if ocr else None)


def mask_cached(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None = None, *,
                kararlar: dict[str, dict] | None = None, sha: str | None = None, kind: str | None = None) -> dict:
    """`mask_and_check` + önbellek `aday` katmanı: değişmeyen dosya (aynı içerik, kural, karar, model
    metni) yeniden işlenmez; kayıt ve maskeli kopya önbellekten gelir."""
    from . import bolge as BG
    from . import onbellek
    sha = sha or onbellek.sha256_file(src)
    ob = onbellek.aktif()
    mine = BG.dosya_kararlari(kararlar or {}, sha[:8])
    key = aday_anahtari(sha, rules, eng, mine, model_text, kind) if ob is not None else None
    if ob is not None:
        hit = ob.get_json("aday", key)
        if hit is not None:
            blob = ob.get("aday_cikti", key) if hit.get("cikti") else None
            if not hit.get("cikti") or blob is not None:
                if blob is not None:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(blob)
                rec = hit["rec"]
                rec["onbellek"] = True
                return rec
    rec = mask_and_check(src, dst, rules, eng, model_text=model_text, kararlar=mine, sha=sha, kind=kind)
    if ob is not None:
        has = dst.is_file()
        if has:
            ob.put("aday_cikti", key, dst.read_bytes())
        ob.put_json("aday", key, {"rec": rec, "cikti": has})
    return rec


def read_model_text(p: Path | None) -> str | None:
    if p is None or not p.is_file():
        return None
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _doc_texts(ws: Path, csv_name: str, path_col: str) -> dict[str, Path]:
    """`<ws>/<csv>`'deki yol → `<ws>/text/<doc_id>.txt` (yalnız var olanlar)."""
    f = ws / csv_name
    out: dict[str, Path] = {}
    if not f.is_file():
        return out
    try:
        with open(f, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rel, did = (row.get(path_col) or "").strip(), (row.get("doc_id") or "").strip()
                if rel and did and rel not in out and (ws / "text" / f"{did}.txt").is_file():
                    out[rel] = ws / "text" / f"{did}.txt"
    except (OSError, csv.Error):
        return {}
    return out


def evidence_model_texts(ws: Path) -> dict[str, Path]:
    """Kanıt dosyası (evidence/ göreli yolu) → modelin okuma metni (`evidence-index.csv` doc_id)."""
    return _doc_texts(ws, INDEX, "dosya")


def source_model_texts(ws: Path) -> dict[str, Path]:
    """Kaynak dosyası (kaynak klasöre göreli yol) → modelin okuma metni (`inventory.csv` doc_id)."""
    return _doc_texts(ws, "inventory.csv", "rel_path")


ELLE_DIR = "maskeleme-elle"            # elle maskelenmiş sürümler (bidr maskele yukle); çalıştırmalar arasında kalır
ELLE_KAYIT = "maskeleme-elle.json"
ELLE = "elle_maskelendi"


def elle_kayit(ws: Path) -> dict[str, dict]:
    p = Path(ws) / ELLE_KAYIT
    try:
        d = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _legacy(src: Path, td: Path):
    """Eski biçim → (çevrilmiş yol, yöntem); önbellek `donusum` katmanı. ConvertError fırlatır."""
    from . import onbellek
    from .eski import convert, converter_id
    ob = onbellek.aktif()
    key = None
    if ob is not None:
        key = onbellek.anahtar("donusum", onbellek.sha256_file(src), src.suffix.lower(), converter_id(src))
        hit = ob.get_json("donusum", key)
        blob = ob.get("donusum_cikti", key) if hit else None
        if hit and blob is not None:
            out = td / hit["ad"]
            out.write_bytes(blob)
            return out, hit["yontem"]
    out, how = convert(src, td)
    if ob is not None:
        ob.put("donusum_cikti", key, out.read_bytes())
        ob.put_json("donusum", key, {"ad": out.name, "yontem": how})
    return out, how


def _isle(job: dict) -> dict:
    """Tek kanıt dosyası (işçi sürecinde de çalışır). → kayıt."""
    import tempfile
    from . import onbellek
    from .eski import LEGACY_EXT, ConvertError
    if job.get("onbellek"):
        os_env = __import__("os").environ
        os_env[onbellek.ENV] = job["onbellek"]
    src, rel, dst = Path(job["src"]), job["rel"], Path(job["dst"])
    rules, eng = job["rules"], job["eng"]
    rec: dict = {"dosya": rel}
    sha = onbellek.sha256_file(src)
    rec["sha256"] = sha
    elle = job.get("elle")
    if elle and elle.get("kaynak_sha") == sha and Path(elle["yol"]).is_file():
        out = dst.with_suffix(Path(elle["yol"]).suffix) if Path(elle["yol"]).suffix else dst
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(elle["yol"], out)
        rec.update(bicim=kind_of(out) or out.suffix.lstrip("."), durum=ELLE, elle_bakilmali=False,
                   neden="elle maskelendi (bidr maskele yukle)", elle_yukleme={k: elle.get(k) for k in ("kim", "zaman", "sha256")})
        if out != dst:
            rec["maskeli"] = out.relative_to(Path(job["dst_root"])).as_posix()
        return rec
    if elle:
        rec.setdefault("uyarilar", []).append("elle maskelenmiş sürüm yok sayıldı: kanıt dosyası yüklemeden sonra değişti")
    kind = kind_of(src)
    mt = job.get("model_text")
    if kind is None and src.suffix.lower() in LEGACY_EXT:
        with tempfile.TemporaryDirectory(prefix="bidr-eski-") as td:
            try:
                conv, how = _legacy(src, Path(td))
            except ConvertError as e:
                rec.update(bicim=src.suffix.lower().lstrip("."), durum="desteklenmiyor", elle_bakilmali=True,
                           onay_bekliyor=True, neden=f"eski biçim çevrilemedi: {e}; kontrol bekliyor (pakete girmez)")
                return rec
            except Exception as e:
                rec.update(bicim=src.suffix.lower().lstrip("."), durum="hata", elle_bakilmali=True, onay_bekliyor=True,
                           neden=f"eski biçim çevrilemedi ({type(e).__name__}: {str(e)[:160]})")
                return rec
            k2 = kind_of(conv)
            if k2 is None:
                rec.update(bicim=src.suffix.lower().lstrip("."), durum="desteklenmiyor", elle_bakilmali=True,
                           onay_bekliyor=True, neden=f"eski biçim {conv.suffix} biçimine çevrildi ama maskelenemiyor")
                return rec
            out = dst.with_suffix(conv.suffix)
            rec.update(bicim=k2, ozgun_bicim=src.suffix.lower().lstrip("."),
                       donusum=f"{src.suffix.lower().lstrip('.')} → {conv.suffix.lstrip('.')} ({how})",
                       maskeli=out.relative_to(Path(job["dst_root"])).as_posix())
            if k2 == "pdf":
                rec["motor"] = eng
            rec.update(mask_cached(conv, out, rules, eng, model_text=mt, kararlar=job.get("kararlar"), sha=sha, kind=k2))
            return rec
    rec["bicim"] = kind or (src.suffix.lower().lstrip(".") or "?")
    if kind is None:
        rec.update(durum="desteklenmiyor", elle_bakilmali=True,
                   neden="biçim taranamıyor (sunum vb.); kopyalanmadı, elle incelenmeli")
        return rec
    if kind == "pdf":
        rec["motor"] = eng
    if mt is not None:
        rec["model_metni"] = True
    rec.update(mask_cached(src, dst, rules, eng, model_text=mt, kararlar=job.get("kararlar"), sha=sha, kind=kind))
    return rec


def run(ws_root: Path, *, evidence: Path | None = None, out: Path | None = None, engine: str = "auto",
        names: list[str] | None = None, rules: MaskRules | None = None, workers: int = 1,
        onbellek_kullan: bool = True, progress=None) -> dict:
    """`workers`: paralel işçi süreç (CLI varsayılanı 2; tesseract tek iş parçacığı). `onbellek_kullan`:
    çalışma alanının `.cache/maske.sqlite` önbelleği."""
    import time as _time
    from . import bolge as BG
    from . import onbellek
    t0 = _time.monotonic()
    ws = Path(ws_root).expanduser().resolve()
    ev = Path(evidence).expanduser().resolve() if evidence else ws / "evidence"
    if not ev.is_dir():
        raise FileNotFoundError(f"kanıt klasörü yok: {ev} (önce `bidr file`)")
    out = Path(out).expanduser().resolve() if out else ev.parent
    dst_root, fail_root = out / OUT_DIR, out / FAIL_DIR
    for d in (dst_root, fail_root):
        if _inside(d, ev) or _inside(ev, d):
            raise MaskRunError(f"çıktı klasörü kanıt klasörüyle iç içe olamaz: {d} / {ev}")
    if rules is None:
        rules = MaskRules.from_config(read_ws_config(ws), ws)
    if names:
        rules = replace(rules, names=tuple(rules.names) + tuple(names))
    model_texts = evidence_model_texts(ws)
    eng = pdf_engine(engine)
    _prepare_dir(dst_root)
    _prepare_dir(fail_root)
    ob_yol = None
    if onbellek_kullan:
        onbellek.ac(ws)
        ob_yol = str((ws / onbellek.DOSYA).resolve())
    else:
        onbellek.ac(None)
    kararlar = BG.kararlar_yukle(ws)
    elle = elle_kayit(ws)

    uyarilar = list(rules.warnings)
    if not raster_ocr_available():
        uyarilar.append("OCR yok (tesseract + tur/eng dil verisi): metin katmanı olmayan PDF sayfaları ve "
                        "görseller taranamadı; bu dosyalar 'taranamadi' durumunda kalır")
    if eng == "pypdf":
        uyarilar.append("PyMuPDF kurulu değil: PDF'ler pypdf ile en iyi çaba ile maskelendi; gerçek "
                        "kaldırma (redaction) için `pip install 'bidr[maske]'`")
    jobs = []
    for src in _files(ev):
        rel = src.relative_to(ev).as_posix()
        e = elle.get(rel)
        if e:
            e = dict(e, yol=str(ws / e["dosya"]))
        mt = read_model_text(model_texts.get(rel))
        jobs.append({"src": str(src), "rel": rel, "dst": str(dst_root / rel), "dst_root": str(dst_root),
                     "rules": rules, "eng": eng, "model_text": mt, "kararlar": kararlar, "elle": e,
                     "onbellek": ob_yol})
    if workers > 1 and len(jobs) > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            recs = []
            for i, r in enumerate(ex.map(_isle, jobs, chunksize=1), 1):
                recs.append(r)
                if progress:
                    progress(i, len(jobs), r["dosya"])
    else:
        recs = []
        for i, j in enumerate(jobs, 1):
            recs.append(_isle(j))
            if progress:
                progress(i, len(jobs), j["rel"])

    kayitlar, yayimlanamaz = [], []
    toplam = {"bulunan": Counter(), "maskelenen": Counter(), "kalan": Counter()}
    toplam_imza = Counter()
    for rec in recs:
        rel = rec["dosya"]
        toplam["bulunan"].update(rec.get("bulunan") or {})
        toplam["maskelenen"].update(rec.get("maskelenen") or {})
        toplam["kalan"].update(rec.get("kalan") or {})
        toplam_imza["bolge"] += rec.get("imza_bolgesi", 0)
        toplam_imza["ortusen_kelime"] += rec.get("imza_ortusen_kelime", 0)
        if rec["durum"] in ("hata", "desteklenmiyor"):
            yayimlanamaz.append({"dosya": rel, "neden": rec["neden"]})
        elif rec["durum"] not in ("tamam", ELLE):
            mrel = rec.get("maskeli") or rel
            dst, target = dst_root / mrel, fail_root / mrel
            if dst.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(target))
                rec["kopya"] = f"{FAIL_DIR}/{mrel}"
            yayimlanamaz.append({"dosya": rel, "neden": rec["neden"]})
        kayitlar.append(rec)

    # boş kalan klasörleri temizle
    for d in sorted((p for p in dst_root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()

    durumlar = Counter(r["durum"] for r in kayitlar)
    index_out = _mask_index(ev.parent / INDEX, out / INDEX_OUT, rules, {r["dosya"]: r["durum"] for r in kayitlar})
    bekleyen = [r for r in kayitlar if bekliyor(r)]
    rapor = {
        "surum": SURUM, "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kanit_klasoru": str(ev), "maskeli_klasor": str(dst_root), "pdf_motoru": eng,
        "kurallar": {"turler": list(rules.kinds), "ogrenci_no_desen_sayisi": len(rules.student_patterns),
                     "ad_listesi_sayisi": len(rules.names), "etiket_alani": rules.label_fields,
                     "kural_surumu": KURAL_SURUM},
        "ozet": {"dosya": len(kayitlar), **dict(sorted(durumlar.items())),
                 **{k: _c(v) for k, v in toplam.items()},
                 "imza_bolgesi": toplam_imza["bolge"], "imza_ortusen_kelime": toplam_imza["ortusen_kelime"],
                 "imza_elle_dosya": sum(1 for r in kayitlar if r.get("imza_elle")),
                 "imza_metinle_ortusen_elle": sum(r.get("imza_metin_elle", 0) for r in kayitlar),
                 "model_metni_denetlenen": sum(1 for r in kayitlar if r.get("model_metni")),
                 "el_yazisi_elle_dosya": sum(1 for r in kayitlar if r.get("el_yazisi_elle")),
                 "bolge": BG.ozet([b for r in kayitlar for b in r.get("bolgeler") or []]),
                 "kontrol_bekleyen_dosya": len(bekleyen),
                 "onbellekten": sum(1 for r in kayitlar if r.get("onbellek")),
                 "sure_sn": round(_time.monotonic() - t0, 2)},
        "ocr": raster_ocr_available(),
        "yayimlanamaz": yayimlanamaz, "uyarilar": uyarilar, "dosyalar": kayitlar,
        "maskeli_dizin": str(index_out) if index_out else None,
    }
    yaz_rapor(out / REPORT, rapor)
    marker = {"surum": SURUM, "zaman": rapor["zaman"], "kaynak": str(ev), "rapor": str(out / REPORT)}
    for d in (dst_root, fail_root):
        d.mkdir(parents=True, exist_ok=True)
        (d / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=1), encoding="utf-8")
    return rapor


def yaz_rapor(p: Path, rapor: dict) -> None:
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def bekliyor(rec: dict) -> bool:
    """Dosya kanıt paketine girmeden önce insan kontrolü bekliyor mu (maskelenecek yeri çözülmemiş):
    `tamam` ya da `elle_maskelendi` dışındaki her durum."""
    return rec.get("durum") not in ("tamam", ELLE)


def _mask_index(src: Path, dst: Path, rules: MaskRules, durum: dict[str, str]) -> Path | None:
    """`evidence-index.csv` varsa yayına uygun kopyası: ad/alıntı/kaynak maskeli, `maskeleme` sütunu."""
    if not src.is_file():
        return None
    with open(src, encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        cols = list(r.fieldnames or [])
        rows = list(r)
    if "maskeleme" not in cols:
        cols.append("maskeleme")
    for row in rows:
        for c in INDEX_MASK_COLS:
            if row.get(c):
                row[c] = mask_text(row[c], rules)[0]
        row["maskeleme"] = durum.get(row.get("dosya") or "", "yok") if row.get("dosya") else "yok"
    with open(dst, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    return dst
