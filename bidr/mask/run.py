"""`bidr maskele`: dosyalanmış kanıtların (evidence/) maskeli yayın kopyası → `evidence-maskeli/`.

Asıl dosyalara dokunulmaz. Her kopya maskelemeden sonra bağımsız olarak yeniden taranır;
kişisel veri, imza şüphesi ya da temizlenmemiş üst veri/yorum/ek kalırsa (`basarisiz`) ya da
metin katmanı olmayan sayfa/görsel OCR'dan geçemezse (`taranamadi`) kopya `evidence-maskeli/`'ye
girmez, `maskeleme-basarisiz/` altına alınır ve `maskeleme-raporu.json`'da `yayimlanamaz`
listesine yazılır (`elle_bakilmali: true`). Kararı verilmemiş öneri bölgesi (`onay_bekliyor`) olan
dosyanın kopyası da (durumu `tamam` olsa bile) `maskeleme-basarisiz/`'e alınır: oradaki inceleme
kopyasında açık öneriler turuncu kesik çerçevelidir; çerçevesiz hâli (kesin kapatmalar uygulanmış,
öneriler açık) teslim paketi için `maskeleme-bekleyen/`'e yazılır (kayıtta `teslim_kopya`). Desteklenmeyen biçimler kopyalanmaz, aynı listeye girer;
eski biçimler (.doc/.xls/.ppt/.pptx/.msg) çevrilip maskelenir (`eski`). Rapora bulunan değerlerin
kendisi yazılmaz; yalnız tür, sayı ve bölge kutusu.

Bölgeler (`bolge`): her tespit kimlikli bir bölgedir; insan kararları (`maskeleme-kararlari.jsonl`)
bölge kimliğiyle uygulanır, elle maskelenmiş sürümler (`maskeleme-elle.json`) kanıt değişmedikçe
kullanılır (`elle_maskelendi`). Son adım redaksiyon doğrulaması (`dogrula`). Önbellek
(`onbellek`, `<ws>/.cache/maske.sqlite`): değişmeyen dosya yeniden işlenmez, kural değişince OCR
yeniden çalışmaz. Teslim (`bidr/teslim/run.py`, politika 2026-11-22 ikinci karar): `bekliyor(kayıt)`
doğru olan dosya pakete o anki maskeli hâliyle (`teslim_kopya`/`kopya`; maskelenemediyse özgünü) girer ve
"maskeleme kararı bekleyen" diye listelenir; `bidr teslim --kararsizlari-disla` eski davranış (girmez).
"""
from __future__ import annotations

import csv
import functools
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
TESLIM_DIR = "maskeleme-bekleyen"     # karar bekleyen dosyanın çerçevesiz maskeli kopyası (teslim paketi için)
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
IMZA_IZI = "imza_izi"                 # güvenlik ağı önerisinin kaynağı (yalnız uyarı; kapatılamaz, çizilir)
IMZA_IZI_NEDEN = "kişisel veri olabilir: imza benzeri iz, kontrol edin"
IMZA_GERI_BASMA_SORUN = "imza: kutu kapatıldı, ad/unvan yalnız OCR'dan okundu: geri basma onayı bekliyor"


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


BOLGESIZ = ("docx", "xlsx", "metin", "html")      # bölge üretmeden metni doğrudan maskeleyen biçimler
METIN_TUR_ADI = {"tc_no": "kimlik no", "iban": "IBAN", "eposta": "e-posta", "telefon": "telefon",
                 "ogrenci_no": "öğrenci no", "ad": "ad"}
IMZA_GORSEL = "imza_gorsel"            # bölgesiz biçimin gömülü görselindeki imza önerisi (kaynak)


def metin_kipi(kind: str | None, eng: str) -> bool:
    """Bölgesiz biçim mi (yalnız öneri kipinde metin önerisi olarak ele alınır): docx/xlsx/düz metin/html ve
    pypdf motoruyla PDF."""
    return kind in BOLGESIZ or (kind == "pdf" and eng != "pymupdf")


def metin_bolgeleri(sha8: str, bulgular, rules: MaskRules, imza_aday: int = 0) -> list[dict]:
    """Bölgesiz biçimin bulguları → desen başına bir öneri bölgesi (`tur: metin`, sayfa 0, kutusuz; kimlik
    `<sha8>-s0-<desen>`), gömülü görselde imza adayı varsa bir de imza önerisi (`<sha8>-s0-imza`). Değer yazılmaz;
    yalnız tür ve sayı."""
    from . import bolge as BG
    from .detect import KINDS
    out = []
    for k in KINDS:
        n = int((bulgular or {}).get(k) or 0)
        if n <= 0 or k not in rules.kinds:
            continue
        b = BG.yeni(BG.METIN_SAYFA, [0, 0, 0, 0], BG.METIN, BG.ONAY,
                    f"metin içinde: {METIN_TUR_ADI.get(k, k)} ×{n}", "metin_deseni", 0.9)
        b.update(id=f"{sha8}-s0-{k}", desen=k, adet=n, konum="metin", oneri=True)
        out.append(b)
    if imza_aday:
        b = BG.yeni(BG.METIN_SAYFA, [0, 0, 0, 0], "imza", BG.ONAY,
                    f"gömülü görselde imza benzeri mürekkep ×{imza_aday}", IMZA_GORSEL, 0.5)
        b.update(id=f"{sha8}-s0-imza", adet=int(imza_aday), konum="gomulu_gorsel", oneri=True)
        out.append(b)
    return out


def _metin_onerisi(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None, bg, before: dict,
                   temiz: Path | None) -> dict:
    """Yalnız öneri kipi, bölgesiz biçim: bulunan desenler öneri bölgesidir; metin YALNIZ insanın "kapat" dediği
    desenlerde değiştirilir (aynı metin değiştirme yolu, kurallar o desenlere daraltılmış), üst veri/yorum temizliği
    her zaman yapılır. Açık kalan desen yeniden taramada "kalan" sayılmaz (öneridir); kapatılan desen kalırsa başarısız."""
    from . import bolge as BG
    imza_aday = int(before.get("imza_aday") or 0) if kind_of(src) == "docx" else 0    # gömülü görsel imzası
    regs = metin_bolgeleri(bg.sha8, before["bulgular"], rules, imza_aday)
    bg.sayfa(BG.METIN_SAYFA, regs, ilk=False)
    kapat = {b["desen"] for b in regs if b.get("desen") and b["karar"] == BG.KAPATILDI}
    imza_kapat = any(b["kaynak"] == IMZA_GORSEL and b["karar"] == BG.KAPATILDI for b in regs)
    r2 = replace(rules, kinds=tuple(k for k in rules.kinds if k in kapat), label_fields=False)
    rec: dict = {"yalniz_oneri": True}
    try:
        res = mask_file(src, dst, r2, engine=eng, imza=imza_kapat)
        after = scan_file(dst, rules)
    except Exception as e:                    # noqa: BLE001 — bozuk dosya vb.
        if dst.exists():
            dst.unlink()
        rec.update(durum="hata", elle_bakilmali=True, neden=f"maskelenemedi: {type(e).__name__}: {e}"[:300],
                   bulunan=_c(before["bulgular"]))
        return rec
    acik = {b["desen"] for b in regs if b.get("desen") and b["karar"] != BG.KAPATILDI}
    kalan = Counter({k: n for k, n in after["bulgular"].items() if n and k not in acik})
    sorunlar = list(after["sorunlar"])
    if after.get("imza_aday") and imza_kapat:
        sorunlar.append(f"imza: kapatılamayan aday ×{after['imza_aday']}")
    model_uyari = []
    if model_text is not None:
        gaps, note = model_text_gaps(model_text, dict(res, maskelenen=before["bulgular"]), rules)
        if note:
            model_uyari.append(note)
        if gaps:
            rec["el_yazisi_elle"] = gaps
            sorunlar.append(f"{EL_YAZISI_SORUN} ({'; '.join(gaps)})")
    onay = BG.onay_bekleyen(bg.bolgeler)
    if onay and dst.is_file() and temiz is not None:      # teslim paketi: özgün içerik (üst verisi temiz)
        temiz.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dst, temiz)
    rec.update(bulunan=_c(before["bulgular"]), maskelenen=_c(res["maskelenen"]), kalan=_c(kalan),
               oneri_acik=_c({k: n for k, n in after["bulgular"].items() if k in acik}),
               temizlenen=res["temizlenen"], kalan_sorunlar=sorunlar, bolgeler=_clean_bolgeler(bg.bolgeler),
               bolge_ozet=BG.ozet(bg.bolgeler),
               uyarilar=list(res["uyarilar"]) + list(after.get("uyarilar") or []) + model_uyari + bg.uyarilar)
    if onay:
        rec["onay_bekleyen"] = len(onay)
    if before.get("imza"):
        rec["imza_uyarisi"] = before["imza"]
    if after.get("imza_metin"):
        rec["imza_metin_elle"] = len(after["imza_metin"])
        rec["imza_metin_yer"] = after["imza_metin"]
    if kalan or sorunlar:
        parts = [f"{k}×{n}" for k, n in sorted(kalan.items())] + sorunlar
        rec.update(durum="basarisiz", neden=("maskeleme başarısız; kalan: " + ", ".join(parts))[:600],
                   elle_bakilmali=True)
    else:
        rec.update(durum="tamam", elle_bakilmali=False)
    return rec


def mask_and_check(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None = None, *,
                   kararlar: dict[str, dict] | None = None, sha: str | None = None, kind: str | None = None,
                   temiz: Path | None = None, yalniz_oneri: bool = False) -> dict:
    """Tek dosya: tara → maskele (`dst`; bölgeler kimlikli, insan kararları uygulanır) → maskeli kopyayı
    bağımsız yeniden tara → bölgeleri uzlaştır → redaksiyon doğrulaması.

    → kayıt alanları: `durum` (tamam | basarisiz | taranamadi | hata), `elle_bakilmali`, `neden`,
    `bulunan`/`maskelenen`/`kalan` (tür → sayı), `temizlenen`, `kalan_sorunlar`, `uyarilar`, imza
    alanları, `bolgeler` (PDF/PyMuPDF ve görsellerde; bkz. `bolge`). `hata`da `dst` silinir; diğer
    durumlarda maskeli kopya `dst`'de kalır (nereye konacağına çağıran karar verir). Değerlerin
    kendisi yazılmaz. `sha`: kaynak dosyanın sha256'sı (bölge kimliği; verilmezse hesaplanır). `temiz`:
    açık öneri çerçevesi çizilecekse kopyanın çerçevesiz hâli önce buraya yazılır (teslim paketi).

    `yalniz_oneri` (`bidr maskele --yalniz-oneri`): hiçbir tespit kendiliğinden kapatılmaz; hepsi açık öneri
    (`onay_bekliyor`) olur, yalnız insan kararları (`kapat`, `ciz`, `yukle`) uygulanır. Bölgesiz biçimler
    (`metin_kipi`) desen başına öneri bölgesi alır (`_metin_onerisi`). Açık önerinin kendisi (kalan desen, imza
    adayı) dosyayı başarısız saymaz; dosya karar bekler (`onay_bekleyen`)."""
    from . import bolge as BG
    from . import dogrula
    from .onbellek import sha256_file
    sha = sha or sha256_file(src)
    kind = kind or kind_of(src) or ""
    bg = BG.Baglam(sha[:8], BG.dosya_kararlari(kararlar or {}, sha[:8]), yalniz_oneri=yalniz_oneri)
    rec: dict = {}
    try:
        before = scan_file(src, rules)
    except Exception as e:
        before = {"bulgular": Counter(), "sorunlar": [f"kaynak taranamadı: {type(e).__name__}"], "imza": []}
    if yalniz_oneri and metin_kipi(kind, eng):
        return _metin_onerisi(src, dst, rules, eng, model_text, bg, before, temiz)
    if yalniz_oneri:
        rec["yalniz_oneri"] = True
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
        okunamayan = {b["sayfa"] for b in bg.bolgeler if b["tur"] == "okunamayan_sayfa"}
        for a in after["bolge_adaylari"]:
            if a.get("kaynak") == "sablon":
                continue          # şablon önerisi tarama içindir (ilk turda sorulur); kopyada yeniden önerilmez
            if a["tur"] == "okunamayan_sayfa" and a["sayfa"] not in okunamayan:
                continue          # özgün sayfa okundu; maskeli kopyanın OCR kalitesi kapatma kutularıyla düşebilir
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
    if bolgeli and not bg.bolgeler and kind in ("pdf", "gorsel"):
        # güvenlik ağı: hiç bölge yokken taranmış sayfada imza benzeri iz → sayfa başına tek öneri (sessiz yayın yok)
        try:
            from .raster import imza_izi
            izler = imza_izi(src, kind)
        except Exception as e:                           # noqa: BLE001 — ağ tespiti düşürmesin: uyarı
            izler = []
            model_uyari.append(f"imza izi denetimi yapılamadı ({type(e).__name__})")
        acik_iz = []
        for sn, kutu in izler:
            b = BG.yeni(sn, kutu, "kisisel_veri", BG.ONAY, IMZA_IZI_NEDEN, IMZA_IZI, 0.3)
            bg.sayfa(sn, [b], ilk=False)
            if b["karar"] == BG.ONAY:
                acik_iz.append(b)
        if acik_iz and not yalniz_oneri:
            sorunlar.append(f"{IMZA_IZI_NEDEN} ({_sayfalar(acik_iz)})")
    if bolgeli:
        onay = BG.onay_bekleyen(bg.bolgeler)
        # m1 (yapi) bölgeleri: kutusu kapalı geri basma onayı / metinle örtüşen kapatılmamış / etiketsiz aday
        gb = [b for b in onay if b["tur"] == "imza" and b.get("kapali")]
        mt = [b for b in onay if b["tur"] == "imza" and b not in gb
              and (b["kaynak"] == "imza_metin" or "metinle örtüşen" in b["neden"])]
        et = [b for b in onay if b["tur"] == "imza" and b not in mt and b not in gb
              and (b["kaynak"] in ("imza_etiketsiz", "etiketsiz_aday", "etiketsiz_sayfa") or "etiketsiz" in b["neden"])]
        kl = [b for b in onay if b["tur"] == "imza" and b not in mt and b not in et and b not in gb]
        n_sorun = len(sorunlar)
        if gb:
            sorunlar.append(f"{IMZA_GERI_BASMA_SORUN} ({_sayfalar(gb)})")
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
        if yalniz_oneri:              # açık imza önerileri öneridir, eksik maskeleme değil (dosya karar bekler)
            del sorunlar[n_sorun:]
        taranamadi = [(f"s.{b['sayfa']}: " if res.get("sayfa_sayisi", 1) > 1 or kind == "pdf" else "görsel: ")
                      + b["neden"].removeprefix("okunamadı: ") for b in onay if b["tur"] == "okunamayan_sayfa"]
        dog = dogrula.dogrula(dst, kind, bg.bolgeler, eng)
        if dog:
            rec["redaksiyon_dogrulama"] = dog
            sorunlar.append(f"redaksiyon doğrulaması başarısız ({len(dog)} kutu): " + "; ".join(dog[:3]))
        acik = [b for b in onay if not b.get("kapali")]
        if acik and dst.is_file():
            if temiz is not None:                       # teslim paketi: çerçevesiz (öneriler açık) hâl
                temiz.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dst, temiz)
            # inceleme kopyası (maskeleme-basarisiz/ ya da --kaynak ağacı): açık kalan öneriler renkli kesik
            # çerçeveyle çizilir; inceleyici kopyayı tamamen maskeli sanmasın
            try:
                onay_cercevesi(dst, kind, acik, eng)
            except Exception as e:                       # noqa: BLE001 — çerçeve çizilemedi: uyarı
                model_uyari.append(f"onay çerçevesi çizilemedi ({type(e).__name__})")
        rec["bolgeler"] = _clean_bolgeler(bg.bolgeler)
        rec["bolge_ozet"] = BG.ozet(bg.bolgeler)
        if res.get("sayfalar"):
            rec["sayfalar"] = res["sayfalar"]
        if res.get("kapatma_olcumu"):
            rec["kapatma_olcumu"] = kapatma_ozeti(res["kapatma_olcumu"], bg.bolgeler)
            oz = rec["kapatma_olcumu"]
            if oz["siyah_altinda"] or oz["dusuk_guven_altinda"] or oz["gorsel_zemin_payi"] or oz["yazi_altinda"]:
                model_uyari.append(f"aşırı kapatma ölçümü: {oz['siyah_altinda']} basılı kelime, "
                                   f"{oz['dusuk_guven_altinda']} düşük güvenli (el yazısı) kelime, "
                                   f"{oz['yazi_altinda']} yazı benzeri satır parçası siyah kutu altında, "
                                   f"görsel zemin üstünde siyah alan %{100 * oz['gorsel_zemin_payi']:.1f} "
                                   "(kişisel veri bölgeleri dışında)")
            if oz["esik_asildi"]:
                rec["asiri_kapatma_bekliyor"] = True     # yalnız uyarı değil: dosya insan kararı bekler
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
    if yalniz_oneri and bolgeli:
        # açık önerilerin kendisi kopyada kalır (yalnız öneri); kapatılan kutuların doğrulaması `dogrula`da
        rec["oneri_acik"] = _c(kalan)
        kalan = Counter()
        rec["kalan"] = {}
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


# `yazi_altinda`: OCR güveninden bağımsız yapı ölçümü (siyah altında kalan "yazı benzeri satır" parçası; `yapi` /
# `satir`): OCR'ın okuyamadığı (imza altında kalmış, el yazısı) ad satırı da sayılır
ASIRI_ESIK = {"siyah_altinda": 1, "dusuk_guven_altinda": 4, "yazi_altinda": 2, "gorsel_zemin_payi": 0.01,
              "siyah_alan_payi": 0.3}


def kapatma_ozeti(olcum: dict, bolgeler: list[dict] | None = None) -> dict:
    """Sayfa ölçümleri (`raster.asiri_kapatma`) + bölge ölçümleri (`kapatma_olcumu`) → dosya özeti: toplam basılı
    kelime, siyah altında kalan (kişisel veri bölgeleri dışında), düşük güvenli (el yazısı ad/unvan) kelime, görsel/
    fotoğraf zemini üstündeki siyah alan, en büyük kutu ve en yüksek sayfa siyah alan payı, sayfa listesi.
    `esik_asildi`: `ASIRI_ESIK`'ten biri aşıldı (dosya "karar bekliyor")."""
    v = list(olcum.values())
    bo = [b["kapatma_olcumu"] for b in bolgeler or [] if b.get("kapali") and b.get("kapatma_olcumu")
          and not b["kapatma_olcumu"].get("kasitli")]
    oz = {"basili_kelime": sum(x["basili_kelime"] for x in v), "siyah_altinda": sum(x["siyah_altinda"] for x in v),
          "dusuk_guven_altinda": sum(x.get("dusuk_guven_kelime", 0) for x in bo),
          "yazi_altinda": sum(x.get("yazi_parca", 0) for x in bo),
          "gorsel_zemin_payi": round(sum(x.get("gorsel_zemin_payi", 0.0) for x in bo), 4),
          "en_buyuk_kutu_payi": max((x["en_buyuk_kutu_payi"] for x in v), default=0.0),
          "siyah_alan_payi": max((x["siyah_alan_payi"] for x in v), default=0.0),
          "sayfalar": sorted(int(k) for k, x in olcum.items() if x["siyah_altinda"])}
    oz["esik_asildi"] = any(oz[k] >= e for k, e in ASIRI_ESIK.items())
    return oz


ONAY_RENK = (1.0, 0.45, 0.0)          # turuncu: açık kalan öneri çerçevesi


def onay_cercevesi(dst: Path, kind: str, bolgeler: list[dict], eng: str) -> None:
    """Maskeli kopyada açık kalan (`onay_bekliyor`, kutusu kapatılmamış) bölgelerin çevresine turuncu kesik
    çerçeve ve "[ONAY BEKLİYOR]" işareti. Yeniden taramadan ve redaksiyon doğrulamasından SONRA çizilir
    (çerçeve çizgisi imza/tablo adayı sayılmasın). Kopyanın kendisi teslim paketine girmez."""
    if kind == "pdf" and eng == "pymupdf":
        from .formats import _fitz
        fitz = _fitz()
        doc = fitz.open(str(dst))
        try:
            for b in bolgeler:
                sn = int(b["sayfa"])
                if not 1 <= sn <= doc.page_count:
                    continue
                page = doc[sn - 1]
                r = fitz.Rect(*b["kutu"]) & page.rect
                if r.is_empty:
                    continue
                page.draw_rect(r, color=ONAY_RENK, width=1.6, dashes="[4 2] 0")
                try:
                    page.insert_text((r.x0 + 1, max(r.y0 - 2, 7)), "[ONAY BEKLIYOR]", fontsize=6, color=ONAY_RENK)
                except Exception:
                    pass
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            from .belirlenimci import pdf_kaydet
            pdf_kaydet(doc, tmp, garbage=3, deflate=True)
        finally:
            doc.close()
        tmp.replace(dst)
    elif kind == "gorsel":
        from PIL import ImageDraw
        from .raster import _open_image, image_scale, save_like
        img = _open_image(dst)
        img = img.convert("RGB")
        sc = image_scale(img)
        d = ImageDraw.Draw(img)
        col = tuple(int(255 * v) for v in ONAY_RENK)
        lw = max(2, int(min(img.size) / 400))
        for b in bolgeler:
            x0, y0, x1, y1 = [v / sc for v in b["kutu"]]
            step = 6 * lw
            for x in range(int(x0), int(x1), 2 * step):          # kesik çizgi
                d.line([(x, y0), (min(x + step, x1), y0)], fill=col, width=lw)
                d.line([(x, y1), (min(x + step, x1), y1)], fill=col, width=lw)
            for y in range(int(y0), int(y1), 2 * step):
                d.line([(x0, y), (x0, min(y + step, y1))], fill=col, width=lw)
                d.line([(x1, y), (x1, min(y + step, y1))], fill=col, width=lw)
        save_like(img, dst, dst.suffix)


# ---------------------------------------------------------------- önbellekli dosya işi

KURAL_SURUM = 7            # tespit/kapatma kuralları elle sürümü (kod parmak izi ayrıca anahtara girer); 3: m4; 4: m5 en küçük yeterli maske; 5: m6 aşırı kapatma (zarf, kelime koruması, sayfa toplamı); 6: m7 yazı satırı yapısı, tablo kuralı, sessiz kaçak yok, paraf grubu; 7: m10 imza izi güvenlik ağı

# Kod izi (önbellek `aday` anahtarı): maskeleme SONUCUNU belirleyen kod değişince belgeler yeniden maskelenir;
# sonucu etkilemeyen değişiklik (ilerleme göstergesi, belge dizgesi/yorum, komut satırı, kaynak kip yönetimi,
# run.py'nin klasör/rapor yönetimi) yeniden maskeletmez. Seçim: elle artırılan bir sonuç sürümü yerine daraltılmış
# kod izi — maskeleme kişisel veriyi kapatır; unutulan bir sürüm artırımı eski (eksik maskeli) sonucu önbellekten
# verirdi. Güvenli taraf: sınıflandırılmamış kod izde kalır; dışarıda bırakılan her şey adıyla ve gerekçesiyle
# aşağıda; testler (tests/test_mask_kod_izi.py) yeni modülün sınıflandırılmasını ve sonuç kodunun dışarıdaki
# koda bağlanmamasını zorlar.
_KOD_MODULLERI = ("detect", "formats", "raster", "imza", "alan", "ocr", "bolge", "dogrula", "yapi", "sablon",
                  "run", "eski", "satir", "belirlenimci")
_KOD_DISI = {                     # bidr/mask'in sonucu belirlemeyen modülleri → gerekçe
    "__init__": "paket girişi (yeniden dışa aktarım)",
    "cli": "komut satırı",
    "kaynak": "kaynak kip yönetimi (ağaç, arşiv/e-posta paketleme, adlandırma); dosyanın maskesi mask_cached'te",
    "suanki": "ilerleme göstergesi (o an işlenen belge/sayfa)",
    "onbellek": "önbellek deposu (anahtarın kendisi; içerik adresli)",
    "inceleme": "inceleme görüntüleri ve listesi (maskelemeden sonra)",
    "model": "model öncesi metin maskeleme (ayrı yol, aday önbelleğine girmez)",
}
_YAN_MODULLER = frozenset({"suanki"})      # yalnız yan etkili çağrılar: çağrı ve içe aktarım izden çıkarılır
# run.py'nin sonuca girmeyen (klasör, iş dağıtımı, rapor, model metni yolu) üst düzey fonksiyonları
_RUN_DISI = frozenset({"_inside", "_prepare_dir", "_files", "read_model_text", "_doc_texts", "evidence_model_texts",
                       "source_model_texts", "elle_kayit", "_isle", "_temiz_yolu", "_teslim_kopya", "run",
                       "yaz_rapor", "bekliyor", "_mask_index", "_kod_izi", "modul_izi"})


def modul_izi(ad: str, kaynak: str) -> str:
    """Modül kaynağının sonuçla ilgili izi: belge dizgeleri, yorumlar, biçim, `_YAN_MODULLER` çağrıları ve
    (run.py'de) `_RUN_DISI` fonksiyonları çıkarılmış sözdizimi ağacının metni (`ast.unparse`)."""
    import ast
    tree = ast.parse(kaynak)

    def yan(st) -> bool:
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
            return True                                    # belge dizgesi / çıplak dizge
        if isinstance(st, ast.Expr) and isinstance(st.value, ast.Call):
            f = st.value.func
            return isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in _YAN_MODULLER
        if isinstance(st, ast.ImportFrom) and st.level == 1 and not st.module:
            st.names = [a for a in st.names if a.name not in _YAN_MODULLER]
            return not st.names
        if isinstance(st, ast.ImportFrom) and st.level == 1 and st.module in _YAN_MODULLER:
            return True
        return False

    for node in ast.walk(tree):
        for alan in ("body", "orelse", "finalbody"):
            gov = getattr(node, alan, None)
            if not isinstance(gov, list) or not gov or not isinstance(gov[0], ast.stmt):
                continue
            yeni = [st for st in gov if not yan(st)]
            if ad == "run" and node is tree:
                yeni = [st for st in yeni if not (isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))
                                                  and st.name in _RUN_DISI)]
            if not yeni and alan == "body":
                yeni = [ast.Pass()]
            setattr(node, alan, yeni)
    import hashlib
    return hashlib.sha256(f"{ad}\n{ast.unparse(tree)}".encode("utf-8")).hexdigest()


@functools.lru_cache(maxsize=1)
def _kod_izi() -> str:
    """Sonucu belirleyen kodun izi (süreç başına bir kez hesaplanır; dosya baytı değil sözdizimi)."""
    import hashlib
    h = hashlib.sha256()
    base = Path(__file__).parent
    for m in _KOD_MODULLERI:
        f = base / f"{m}.py"
        if f.is_file():
            h.update(modul_izi(m, f.read_text(encoding="utf-8")).encode())
    return h.hexdigest()[:16]


def kural_izi(rules: MaskRules) -> str:
    """Kural parmak izi (ad listesi yalnız özetiyle)."""
    from .onbellek import anahtar
    return anahtar(list(rules.kinds), list(rules.student_patterns), sorted(rules.names), rules.label_fields,
                   rules.local_model)


def sablon_parcasi(izler: list) -> str | None:
    """Form şablon belleğinin (`maske-sablonlari.json`; `BIDR_MASKE_WS`) BU dosyaya katkısı: dosya işlenirken
    belleğe danışılan sayfa izlerine (`sablon.iz_kaydi_*`) belleğin bugün verdiği sonuç. Başka belgede öğrenilen
    bölge (kullanıcı çizimi, kapat kararı) yalnız bu dosyanın sayfalarıyla eşleşen şablonu değiştirdiyse anahtarı
    değiştirir; belleğin tamamının özeti girmez (bir belgeye çizim bütün dosyaları geçersiz kılmasın)."""
    import os
    from . import sablon as SB
    from .onbellek import anahtar
    if not os.environ.get("BIDR_MASKE_WS"):
        return None
    from .raster import _sablonlar
    try:
        sb = _sablonlar()
    except Exception:                    # noqa: BLE001 — okunamayan bellek: işlemedeki gibi yok sayılır
        sb = None
    return anahtar(SB.bagimlilik_ozeti(sb, izler))


def model_sha(model_text: str | None) -> str | None:
    from .onbellek import sha256
    return sha256(model_text.encode("utf-8")) if model_text is not None else None


def aday_anahtari(sha: str, rules: MaskRules, eng: str, kararlar: dict[str, dict], model_text: str | None,
                  kind: str | None, sablon: str | None = None, *, mt_sha: str | None = None,
                  yalniz_oneri: bool = False) -> str:
    """Dosyanın `aday` anahtarı. `kararlar`: YALNIZ bu dosyanın kararları (`bolge.dosya_kararlari`); `sablon`:
    `sablon_parcasi` (bu dosyanın şablon belleği bağımlılığı). `mt_sha`: model metni yerine özeti (metin yoksa).
    `yalniz_oneri`: yalnız öneri kipinin sonucu ayrı anahtardadır (normal kipin anahtarı değişmez)."""
    from .onbellek import anahtar
    from .ocr import tesseract_version
    kk = sorted((k, v.get("karar"), json.dumps(v.get("kutu")), v.get("kaynak")) for k, v in kararlar.items())
    ocr = raster_ocr_available()
    return anahtar("aday", sha, KURAL_SURUM, _kod_izi(), kural_izi(rules), eng, kind, kk,
                   model_sha(model_text) if model_text is not None else mt_sha,
                   ocr, tesseract_version() if ocr else None, sablon, *(["yalniz_oneri"] if yalniz_oneri else []))


def mask_cached(src: Path, dst: Path, rules: MaskRules, eng: str, model_text: str | None = None, *,
                kararlar: dict[str, dict] | None = None, sha: str | None = None, kind: str | None = None,
                temiz: Path | None = None, cikti_kaydet: bool = False, yalniz_oneri: bool = False) -> dict:
    """`mask_and_check` + önbellek `aday` katmanı: değişmeyen dosya (aynı içerik, kural, BU dosyanın kararları,
    model metni, şablon belleğinin bu dosyaya katkısı) yeniden işlenmez; kayıt, maskeli kopya ve çerçevesiz hâli
    önbellekten gelir. Anahtar iki adımlıdır: temel anahtar (şablon dışı her şey) → `aday_iz` katmanında dosyanın
    son işlenişinde belleğe danıştığı sayfa izleri → bu izlerin bugünkü bellek sonucu tam anahtara girer.
    `cikti_kaydet` (kaynak kip): maskeli kopyanın sha256'sı → bu sonuç (`kaynak_cikti`; bkz. `kaynak_sonucu`)."""
    from . import bolge as BG
    from . import onbellek
    from . import sablon as SB
    sha = sha or onbellek.sha256_file(src)
    ob = onbellek.aktif()
    mine = BG.dosya_kararlari(kararlar or {}, sha[:8])
    temel = aday_anahtari(sha, rules, eng, mine, model_text, kind, yalniz_oneri=yalniz_oneri) if ob is not None else None
    if ob is not None:
        dep = ob.get_json("aday_iz", temel)
        hit = None
        if isinstance(dep, dict) and isinstance(dep.get("izler"), list):
            key = onbellek.anahtar(temel, sablon_parcasi(dep["izler"]))
            hit = ob.get_json("aday", key)
        if hit is not None:
            blob = ob.get("aday_cikti", key) if hit.get("cikti") else None
            tblob = ob.get("aday_temiz", key) if hit.get("temiz") and temiz is not None else None
            if (not hit.get("cikti") or blob is not None) and (not hit.get("temiz") or temiz is None
                                                               or tblob is not None):
                if blob is not None:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(blob)
                if tblob is not None:
                    temiz.parent.mkdir(parents=True, exist_ok=True)
                    temiz.write_bytes(tblob)
                rec = hit["rec"]
                if cikti_kaydet and not yalniz_oneri:
                    _cikti_kaydet(ob, dst, temiz, rec, key, {"sha": sha, "kind": kind,
                                                             "mt": model_sha(model_text), "izler": dep["izler"]})
                rec["onbellek"] = True
                return rec
    once = SB.iz_kaydi_baslat()
    try:
        rec = mask_and_check(src, dst, rules, eng, model_text=model_text, kararlar=mine, sha=sha, kind=kind,
                             temiz=temiz, yalniz_oneri=yalniz_oneri)
    finally:
        izler = SB.iz_kaydi_bitir(once)
    if ob is not None:
        key = onbellek.anahtar(temel, sablon_parcasi(izler))
        has = dst.is_file()
        if has:
            ob.put("aday_cikti", key, dst.read_bytes())
        has_t = temiz is not None and temiz.is_file()
        if has_t:
            ob.put("aday_temiz", key, temiz.read_bytes())
        ob.put_json("aday", key, {"rec": rec, "cikti": has, "temiz": has_t})
        ob.put_json("aday_iz", temel, {"izler": izler})
        if cikti_kaydet and not yalniz_oneri:
            _cikti_kaydet(ob, dst, temiz, rec, key, {"sha": sha, "kind": kind, "mt": model_sha(model_text),
                                                     "izler": izler})
    return rec


# Kaynak kip (`--kaynak -w`) ile kanıt kipi (`-w`) arasında sonuç paylaşımı. Panel akışında bidr'in kaynağı kaynak
# kipin maskeli ağacıdır; kanıt dosyası o ağaçtaki maskeli kopyanın bayt bayt aynısıdır (PDF parçası kesilmediyse).
# Kanıt kipi bu dosyanın sha256'sıyla `kaynak_cikti`'ya bakar; kaynak kipteki sonuç bugün de geçerliyse (aynı
# özgün içerik, kural/kod sürümü, motor, o belgenin kararları, şablon katkısı) yeniden maskelemez: kayıt (bölgeler,
# kararlar), maskeli kopya (dosyanın kendisi) ve çerçevesiz hâli önbellekten gelir.

def _acik_oneri(rec: dict) -> bool:
    from . import bolge as BG
    return any(not b.get("kapali") for b in BG.onay_bekleyen(rec.get("bolgeler")))


def _cikti_kaydet(ob, dst: Path, temiz: Path | None, rec: dict, key: str, girdi: dict) -> None:
    from . import onbellek
    if rec.get("durum") == "hata" or not dst.is_file():
        return
    has_t = temiz is not None and temiz.is_file()
    if _acik_oneri(rec) and not has_t:
        return                     # çerçeveli kopyanın çerçevesiz hâli yok (eski önbellek kaydı): paylaşılmaz
    ck = onbellek.anahtar("kaynak_cikti", onbellek.sha256_file(dst))
    if has_t:
        ob.put("kaynak_cikti_temiz", ck, temiz.read_bytes())
    ob.put_json("kaynak_cikti", ck, {"key": key, "girdi": girdi, "temiz": has_t,
                                     "rec": {k: v for k, v in rec.items() if k != "onbellek"}})


def kaynak_sonucu(src: Path, sha: str, dst: Path, rules: MaskRules, eng: str, model_text: str | None, *,
                  kararlar: dict[str, dict] | None = None, temiz: Path | None = None) -> dict | None:
    """Kanıt dosyası (`src`, sha256 `sha`) kaynak kipin maskeli çıktısıysa ve o sonuç bugün de geçerliyse kaydı
    (`dst`'ye dosyanın kopyası, `temiz`'e çerçevesiz hâli yazılır); değilse None (dosya normal işlenir). Modelin
    okuma metni kaynak kipte denetlenmediyse ve metinde kişisel veri türü (`MODEL_KINDS`) görünüyorsa paylaşılmaz."""
    from . import bolge as BG
    from . import onbellek
    from .detect import detect
    ob = onbellek.aktif()
    if ob is None:
        return None
    ck = onbellek.anahtar("kaynak_cikti", sha)
    v = ob.get_json("kaynak_cikti", ck)
    if not isinstance(v, dict) or not isinstance(v.get("girdi"), dict) or not isinstance(v.get("rec"), dict):
        return None
    g = v["girdi"]
    try:
        mine = BG.dosya_kararlari(kararlar or {}, g["sha"][:8])
        temel = aday_anahtari(g["sha"], rules, eng, mine, None, g.get("kind"), mt_sha=g.get("mt"))
        if onbellek.anahtar(temel, sablon_parcasi(g.get("izler") or [])) != v.get("key"):
            return None
    except (KeyError, TypeError):
        return None
    if model_text is not None and model_sha(model_text) != g.get("mt") and \
            any(f.kind in MODEL_KINDS for f in detect(model_text, rules)):
        return None
    tblob = ob.get("kaynak_cikti_temiz", ck) if v.get("temiz") and temiz is not None else None
    if v.get("temiz") and temiz is not None and tblob is None:
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    if tblob is not None:
        temiz.parent.mkdir(parents=True, exist_ok=True)
        temiz.write_bytes(tblob)
    rec = dict(v["rec"])
    rec["onbellek"] = True
    rec["kaynak_kipten"] = True
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
    elle = job.get("elle") or (job.get("elle_sha") or {}).get(sha)    # ön işlemede yüklenen: aynı sha256
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
                           onay_bekliyor=True, neden=f"eski biçim çevrilemedi: {e}; karar bekliyor (teslimde özgün hâliyle, uyarıyla)")
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
            temiz = _temiz_yolu(job, out)
            rec.update(mask_cached(conv, out, rules, eng, model_text=mt, kararlar=job.get("kararlar"), sha=sha, kind=k2,
                                   temiz=temiz, yalniz_oneri=bool(job.get("yalniz_oneri"))))
            _teslim_kopya(rec, job, temiz)
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
    temiz = _temiz_yolu(job, dst)
    oneri = bool(job.get("yalniz_oneri"))
    # yalnız öneri: kaynak kipin (kapatılmış) sonucu paylaşılmaz
    hit = None if oneri else kaynak_sonucu(src, sha, dst, rules, eng, mt, kararlar=job.get("kararlar"), temiz=temiz)
    rec.update(hit if hit is not None else
               mask_cached(src, dst, rules, eng, model_text=mt, kararlar=job.get("kararlar"), sha=sha, kind=kind,
                           temiz=temiz, yalniz_oneri=oneri))
    _teslim_kopya(rec, job, temiz)
    return rec


def _temiz_yolu(job: dict, dst: Path) -> Path | None:
    """Maskeli kopyanın (`dst`, `dst_root` altında) çerçevesiz teslim hâlinin yolu (`maskeleme-bekleyen/`)."""
    if not job.get("teslim_root"):
        return None
    return Path(job["teslim_root"]) / Path(dst).relative_to(Path(job["dst_root"]))


def _teslim_kopya(rec: dict, job: dict, temiz: Path | None) -> None:
    if temiz is not None and temiz.is_file():
        rec["teslim_kopya"] = f"{TESLIM_DIR}/{temiz.relative_to(Path(job['teslim_root'])).as_posix()}"


def run(ws_root: Path, *, evidence: Path | None = None, out: Path | None = None, engine: str = "auto",
        names: list[str] | None = None, rules: MaskRules | None = None, workers: int = 1,
        onbellek_kullan: bool = True, progress=None, yalniz_oneri: bool = False) -> dict:
    """`workers`: paralel işçi süreç (CLI varsayılanı 2; tesseract tek iş parçacığı). `onbellek_kullan`:
    çalışma alanının `.cache/maske.sqlite` önbelleği. `yalniz_oneri` (`--yalniz-oneri`): tespitler kendiliğinden
    kapatılmaz, öneri olur (bkz. `mask_and_check`); insan kararları uygulanır."""
    import time as _time
    from . import bolge as BG
    from . import onbellek
    t0 = _time.monotonic()
    ws = Path(ws_root).expanduser().resolve()
    ev = Path(evidence).expanduser().resolve() if evidence else ws / "evidence"
    if not ev.is_dir():
        raise FileNotFoundError(f"kanıt klasörü yok: {ev} (önce `bidr file`)")
    out = Path(out).expanduser().resolve() if out else ev.parent
    dst_root, fail_root, teslim_root = out / OUT_DIR, out / FAIL_DIR, out / TESLIM_DIR
    for d in (dst_root, fail_root, teslim_root):
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
    _prepare_dir(teslim_root)
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
    elle_sha = {v["kaynak_sha"]: dict(v, yol=str(ws / v["dosya"])) for v in elle.values()
                if v.get("kaynak_sha") and v.get("dosya")}
    jobs = []
    for src in _files(ev):
        rel = src.relative_to(ev).as_posix()
        e = elle.get(rel)
        if e:
            e = dict(e, yol=str(ws / e["dosya"]))
        mt = read_model_text(model_texts.get(rel))
        jobs.append({"src": str(src), "rel": rel, "dst": str(dst_root / rel), "dst_root": str(dst_root),
                     "teslim_root": str(teslim_root),
                     "rules": rules, "eng": eng, "model_text": mt, "kararlar": kararlar, "elle": e,
                     "elle_sha": elle_sha, "onbellek": ob_yol, "yalniz_oneri": yalniz_oneri})
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
        elif bekliyor(rec):
            # maskelemesi eksik ya da kararı verilmemiş önerisi olan: inceleme kopyası maskeleme-basarisiz/'e
            mrel = rec.get("maskeli") or rel
            dst, target = dst_root / mrel, fail_root / mrel
            if dst.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(target))
                rec["kopya"] = f"{FAIL_DIR}/{mrel}"
            if rec["durum"] != "tamam":
                yayimlanamaz.append({"dosya": rel, "neden": rec["neden"]})
        kayitlar.append(rec)

    # boş kalan klasörleri temizle
    for d in sorted((p for root in (dst_root, teslim_root) for p in root.rglob("*") if p.is_dir()),
                    key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()

    durumlar = Counter(r["durum"] for r in kayitlar)
    index_out = _mask_index(ev.parent / INDEX, out / INDEX_OUT, rules, {r["dosya"]: r["durum"] for r in kayitlar})
    bekleyen = [r for r in kayitlar if bekliyor(r)]
    rapor = {
        "surum": SURUM, "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kanit_klasoru": str(ev), "maskeli_klasor": str(dst_root), "pdf_motoru": eng, "yalniz_oneri": yalniz_oneri,
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
                 "asiri_kapatma": {"dosya": sum(1 for r in kayitlar if (r.get("kapatma_olcumu") or {}).get("siyah_altinda")),
                                   "karar_bekleyen": sum(1 for r in kayitlar if r.get("asiri_kapatma_bekliyor")),
                                   "siyah_altinda_kelime": sum((r.get("kapatma_olcumu") or {}).get("siyah_altinda", 0)
                                                               for r in kayitlar)},
                 "onbellekten": sum(1 for r in kayitlar if r.get("onbellek")),
                 "kaynak_kipten": sum(1 for r in kayitlar if r.get("kaynak_kipten")),
                 "sure_sn": round(_time.monotonic() - t0, 2)},
        "ocr": raster_ocr_available(),
        "yayimlanamaz": yayimlanamaz, "uyarilar": uyarilar, "dosyalar": kayitlar,
        "maskeli_dizin": str(index_out) if index_out else None,
    }
    yaz_rapor(out / REPORT, rapor)
    marker = {"surum": SURUM, "zaman": rapor["zaman"], "kaynak": str(ev), "rapor": str(out / REPORT)}
    for d in (dst_root, fail_root, teslim_root):
        d.mkdir(parents=True, exist_ok=True)
        (d / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=1), encoding="utf-8")
    return rapor


def yaz_rapor(p: Path, rapor: dict) -> None:
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def bekliyor(rec: dict) -> bool:
    """Dosyanın maskelemesi insan kararı bekliyor mu: `tamam` ya da `elle_maskelendi` dışındaki her durum ve
    kararı verilmemiş öneri bölgesi (`onay_bekliyor`) olan `tamam` dosya. Teslimde dışlanmaz, listelenir."""
    d = rec.get("durum")
    if d == ELLE:
        return False
    return d != "tamam" or bool(rec.get("onay_bekleyen")) or bool(rec.get("asiri_kapatma_bekliyor"))


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
