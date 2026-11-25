"""Teslim paketi (model yok): dekanlığa teslim edilecek tek klasör + zip.

    <out>/                      (vars. WS/BIDR-<dönem>-<Birim>/ (yapılandırma yoksa WS/teslim/); zip: aynı adla .zip)
      report.docx               dolu FR-0833 raporu (WS/report.docx'in kopyası)
      kanitlar/A/A.1/A.1.1/[1-OD3]. Ad.pdf
      kanitlar/.../[2-OD2]. Sayfa.html  +  [2-OD2]. Sayfa.pdf   (web kanıtının alınma tarihli PDF kopyası)
      kanit-dizini.xlsx / .csv  ölçüt, kanıt no, OD, ad, paketteki dosya, PDF kopyası, özgün bağlantı,
                                bağlantı kaynağı, alınma tarihi, durum
      EKSIK.txt                 yalnız eşleşmeyen satır ya da üretilemeyen PDF varsa
      MASKELEME-UYARI.txt       yalnız maskeleme kararı bekleyen / maskelenemeyen kanıt varsa

Eşleşme: raporun "Kanıtlar" listesindeki her satır (ölçüt, sıra no, OD) kanıt klasöründe
(`evidence/<A>/<A.1>/<A.1.1>/[n-ODk]. Ad.uzantı`) tam bir dosyayla eşleşmeli; aynı kaynağın
belgeleri tek numarayı paylaşıyorsa (`evidence-index.csv`'de numaranın birden çok satırı) dizinin
o numaraya yazdığı dosyaların hepsi pakete girer (dizinde her biri ayrı satır). Pakete yalnız listedeki
kanıtlar girer; listede olmayan dosya pakete alınmaz (uyarı). Eşleşmeyen satır, birden çok aday ya da
üretilemeyen web PDF'i paketi "eksik" yapar: paket yine yazılır, eksikler listelenir.

Kişisel veri maskeleme (`bidr maskele` çıktısı; yalnız okunur): `maskeleme-raporu.json` ve
`evidence-maskeli/` varsa kanıtın maskeli kopyası pakete girer (web kanıtının PDF'i de maskeli
HTML'den basılır; eski biçimden çevrilen kanıtın maskeli kopyası yeni uzantısıyla). Politika
(2026-11-22, ikinci karar; "maskelenecek yeri çözülmemiş dosya pakete girmez" kuralının yerine):
maskeleme kararı bekleyen kanıt paketten DIŞLANMAZ:
  - kararı verilmemiş öneri bölgesi olan, aşırı kapatma ölçümü eşiği aşan (`asiri_kapatma_bekliyor`) ya da
    maskelemesi eksik kalan (`basarisiz`, `taranamadi`) kanıt (`bidr.mask.run.bekliyor`) o anki maskeli hâliyle girer: kesin kapatmalar uygulanmış, kararsız öneriler açık
    (`maskeleme-bekleyen/` çerçevesiz kopya, yoksa `maskeleme-basarisiz/` kopyası); Maskeleme
    `karar bekliyor`;
  - maskelenemeyen (`hata`, `desteklenmiyor`) kanıt ÖZGÜN hâliyle girer; Maskeleme `maskelenmedi`.
Maskeleme teslimi durdurmaz (karar 2026-11-25; bkz. `maskeleme_secimi`): bölüm maskelemeyi seçmişse
maskeleme raporunda olmayan, maskelemeden sonra değişen ya da maskeli kopyası bulunamayan kanıt pakete ÖZGÜN
hâliyle girer ve adıyla listelenir; maskeleme hiç yapılmadıysa ya da kapalıysa paket yine üretilir ve "kanıtlar
maskelenmeden paketlendi, kişisel veri içerebilir" uyarısı konsola, `MASKELEME-UYARI.txt`'ye ve manifeste
(`maskeleme_uyarisi`) yazılır. Aşağıdaki karar bekleyen kuralları yalnız maskeleme açıkken uygulanır.
Bunlar özetin `karar_bekleyen` listesinde (makinece okunur: ölçüt, kanıt no, kanıt, paketteki dosya,
maskeleme, neden), paketteki `MASKELEME-UYARI.txt`'de ("maskeleme kararı bekleyen belgeler") ve
konsolda uyarıyla listelenir; paket eksik sayılmaz. `kararsizlari_disla=True`
(`bidr teslim --kararsizlari-disla`) eski davranış: bu kanıtlar pakete girmez (dizinde satır kalır,
dosya boş, Maskeleme `kontrol bekliyor`) ve hat aşaması insan bekler. Maskeleme hiç
çalıştırılmadıysa özgün dosya girer (`yapılmadı`; hat uyarır). Dizinin "Maskeleme" sütunu: `tamam` |
`elle maskelendi` | `karar bekliyor` | `maskelenmedi` | `kontrol bekliyor` (yalnız dışlamada) |
`yapılmadı`.

Kaynak ve çalışma alanı dosyalarına yalnız okumak için dokunulur; çıktı klasörü yalnız daha önce
bidr teslim'in yazdığı bir klasörse (işaret dosyası) silinip yeniden yazılır.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .mod import BAGLANTI, teslim_modu
from .web import BILINMIYOR, PdfHatasi, is_web, pdf_araci, web_pdf, web_url

SURUM = 1
MANIFEST = ".bidr-teslim.json"          # çalışma alanında (hat: teslim_tamam)
ISARET = ".bidr-teslim"                 # paket klasöründe (güvenli yeniden yazım); zip'e girmez
KANITLAR = "kanitlar"
RAPOR = "report.docx"
DIZIN = "kanit-dizini"
EKSIK = "EKSIK.txt"
SUTUNLAR = ["olcut", "kanit_no", "od", "ad", "dosya", "pdf_kopya", "ozgun_baglanti", "baglanti_kaynagi",
            "alinma_tarihi", "maskeleme", "isaretler", "durum"]
BASLIKLAR = ["Ölçüt", "Kanıt no", "OD", "Kanıt adı", "Paketteki dosya", "PDF kopyası", "Özgün bağlantı",
             "Bağlantı kaynağı", "Alınma tarihi", "Maskeleme", "İşaretler", "Durum"]
# bidr maskele çıktısı (bidr/mask/run.py; yalnız okunur)
MASKE_RAPOR, MASKE_KLASOR = "maskeleme-raporu.json", "evidence-maskeli"
MASKE_TAMAM, MASKE_YOK = "tamam", "yapılmadı"
MASKE_ELLE_YUKLENDI = "elle maskelendi"
MASKE_KARAR = "karar bekliyor"          # o anki maskeli hâli pakette (kesin kapatmalar uygulanmış, öneriler açık)
MASKE_OZGUN = "maskelenmedi"            # maskelenemedi / raporda yok / maskeli kopya eski: özgünü pakette
MASKE_DISLANDI = "kontrol bekliyor"     # --kararsizlari-disla: pakete girmedi
MASKE_UYARI = "MASKELEME-UYARI.txt"
KARAR_UYARI = "maskeleme kararı bekleyen belge: {n} (pakette, listelendi)"
KARAR_BASLIK = "MASKELEME KARARI BEKLEYEN BELGELER: {n}"
KONTROL_UYARI = "maskelenecek yeri var, kontrol bekliyor: {n} dosya"       # --kararsizlari-disla
KONTROL_BASLIK = "MASKELENECEK YERİ VAR, KONTROL BEKLİYOR: {n} DOSYA"
# "Olduğu gibi devam" (bölümün seçimi; panel işleyicisi yazar, CLI: `bidr teslim --oldugu-gibi`): karar bekleyen kanıt
# incelenmeden o anki (kendiliğinden maskelenmiş) hâliyle girer, `--kararsizlari-disla` uygulanmaz, liste bu başlıkla
OLDUGU_GIBI = "maskeleme-oldugu-gibi.json"      # <ws>/: {"kim": …, "zaman": …}
OLDUGU_GIBI_UYARI = "{n} dosyada incelenmemiş öneri vardı, olduğu gibi eklendi"
OLDUGU_GIBI_BASLIK = "İNCELENMEMİŞ ÖNERİSİ OLAN DOSYALAR (OLDUĞU GİBİ EKLENDİ): {n}"
RE_DOSYA = re.compile(r"^\[(\d+)-OD([1-5])\]\. (.+)\.([A-Za-z0-9]+)$")
RE_OLCUT = re.compile(r"^[A-D]\.\d+\.\d+$")


class TeslimError(RuntimeError):
    pass


@dataclass
class Sonuc:
    cikti: str
    zip: str | None
    tarih: str
    teslim_modu: str
    satirlar: list[dict] = field(default_factory=list)
    eksik: list[str] = field(default_factory=list)
    uyarilar: list[str] = field(default_factory=list)
    pdf_araci: str | None = None
    taslak: bool = False
    maskeleme: bool = False                                        # maskeleme raporu bulundu mu
    elle_bakilacak: list[dict] = field(default_factory=list)       # {dosya, neden}
    # maskeleme kararı bekleyen: {olcut, kanit_no, kanit, dosya (paketteki; dışlandıysa ""), maskeleme, neden, pakette}
    karar_bekleyen: list[dict] = field(default_factory=list)
    kararsizlari_disla: bool = False
    maskeleme_acik: bool | None = None        # bölümün şimdiki seçimi (`maskeleme_secimi`)
    maskeleme_eksigi: str | None = None       # açıkken teslime hazır olmayış nedeni (`maske_eksigi`)
    maskesiz: list[dict] = field(default_factory=list)   # açıkken maskeli kopyası olmadan (özgün) girenler
    maskeleme_uyarisi: str | None = None      # kısa uyarı cümlesi (panel Durum / indirme yanı)
    oldugu_gibi: dict | None = None           # "olduğu gibi devam" seçimi ({kim, zaman}); yoksa None

    @property
    def kontrol_bekliyor(self) -> list[dict]:
        """Pakete girmeyen (yalnız `--kararsizlari-disla`)."""
        return [x for x in self.karar_bekleyen if not x["pakette"]]

    def ozet(self) -> dict:
        web = [r for r in self.satirlar if r["_web"]]
        return {"cikti": self.cikti, "zip": self.zip, "tarih": self.tarih, "teslim_modu": self.teslim_modu,
                "kanit": len(self.satirlar), "web": len(web), "web_pdf": sum(1 for r in web if r["pdf_kopya"]),
                "baglanti_bilinmiyor": sum(1 for r in web if r["ozgun_baglanti"] == BILINMIYOR),
                "eksik": self.eksik, "uyarilar": self.uyarilar, "pdf_araci": self.pdf_araci,
                "taslak": self.taslak,
                "maskeleme": {"rapor": self.maskeleme,
                              **{d: sum(1 for r in self.satirlar if r["maskeleme"] == d)
                                 for d in (MASKE_TAMAM, MASKE_ELLE_YUKLENDI, MASKE_KARAR, MASKE_OZGUN, MASKE_DISLANDI,
                                           MASKE_YOK)}},
                "elle_bakilacak": self.elle_bakilacak, "karar_bekleyen": self.karar_bekleyen,
                "karar_bekleyen_uyarisi": ((OLDUGU_GIBI_UYARI if self.oldugu_gibi else KARAR_UYARI)
                                           .format(n=len(self.karar_bekleyen)) if self.karar_bekleyen else None),
                "oldugu_gibi": self.oldugu_gibi,
                "kararsizlari_disla": self.kararsizlari_disla, "kontrol_bekliyor": self.kontrol_bekliyor,
                "kontrol_uyarisi": KONTROL_UYARI.format(n=len(self.kontrol_bekliyor)) if self.kontrol_bekliyor else None,
                "maskeleme_acik": self.maskeleme_acik, "maskeleme_eksigi": self.maskeleme_eksigi,
                "maskesiz": self.maskesiz, "maskeleme_uyarisi": self.maskeleme_uyarisi}


def sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16] if Path(p).exists() else ""


def _kanit_dosyalari(ev: Path) -> dict[tuple[str, int], list[tuple[int, Path]]]:
    """evidence/ → {(ölçüt, sıra): [(OD, dosya)]}; yalnız alt ölçüt klasöründeki kılavuz adlı dosyalar."""
    out: dict[tuple[str, int], list[tuple[int, Path]]] = {}
    for f in sorted(ev.rglob("*")):
        rel = f.relative_to(ev)
        if not f.is_file() or any(p.startswith(".") for p in rel.parts):
            continue
        m = RE_DOSYA.match(f.name)
        if not m or not RE_OLCUT.match(f.parent.name):
            continue
        out.setdefault((f.parent.name, int(m.group(1))), []).append((int(m.group(2)), f))
    return out


def _dizin(index: Path) -> dict[tuple[str, int], list[dict]]:
    """evidence-index.csv → {(ölçüt, sıra): [satır, …]}. Yalnız aynı belgenin kopyaları ve sürümleri
    (sürüm/kopya grubu, tek belgenin bölünmüş taramaları; `ayni_kaynak_tek_numara`) bir ölçütte tek
    numarayı paylaşır: numarada birden çok satır. Birleşik dosyanın farklı parçaları ayrı numaradır
    (`parca_ayrildi`, bkz. bidr/file/run.py split_parts)."""
    out: dict[tuple[str, int], list[dict]] = {}
    if not index.exists():
        return out
    with open(index, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            m = re.match(r"^(\d+)_OD([1-5])$", (r.get("kanit_no") or "").strip())
            if m and r.get("olcut"):
                out.setdefault((r["olcut"].strip(), int(m.group(1))), []).append(r)
    return out


def _dizin_dosyalari(rows: list[dict]) -> dict[str, dict]:
    """Numaranın dizin satırları → {dosya adı (NFC): satır}."""
    return {unicodedata.normalize("NFC", Path(r.get("dosya") or "").name): r for r in rows if r.get("dosya")}


def _eslestir(k, cand: list[tuple[int, Path]], rows: list[dict]) -> tuple[list[Path], str, list[Path]]:
    """Rapor satırı → (pakete girecek dosyalar, eksik nedeni, dizinde olmayan artık dosyalar).

    Bir numarada birden çok dosya varsa dizinin o numaraya yazdığı dosyalar (aynı kaynağın
    belgeleri: `bidr file` aynı kaynağa tek numara verir, her belgeyi kendi adıyla dosyalar) birlikte
    pakete girer. Kör test 2026-11-20 (Kimya): 18 EKSIK satırının 17'si buydu: paket tek dosya
    beklediği için numarayı "birden çok dosya" diye eksik sayıyordu. Dizinde olmayan dosyalar
    (eski dosyalamadan kalan) ya da dizin yoksa eski kural: birden çok aday eksiktir."""
    same = [f for od, f in cand if od == k.od]
    if len(same) == 1:
        return same, "", []
    if len(same) > 1:
        names = _dizin_dosyalari(rows)
        listed = [f for f in same if unicodedata.normalize("NFC", f.name) in names]
        if listed and len(listed) == len(names):
            return listed, "", [f for f in same if f not in listed]
        return [], "birden çok dosya: " + ", ".join(f.name for f in same), []
    if cand:
        return [], (f"OD uyuşmuyor: listede OD{k.od}, dosyada OD" + "/".join(str(od) for od, _ in cand)), []
    return [], "kanıt klasöründe dosya yok", []


class Maske:
    """`bidr maskele` çıktısının okunur görünümü (rapor yoksa `var` False)."""

    def __init__(self, ws: Path, ev: Path):
        self.ev = ev
        self.ws = ws
        self.rapor_yolu = ws / MASKE_RAPOR
        self.kayit: dict[str, dict] = {}
        self.klasor = ws / MASKE_KLASOR
        self.var = False
        try:
            js = json.loads(self.rapor_yolu.read_text(encoding="utf-8")) if self.rapor_yolu.exists() else None
        except (OSError, ValueError):
            js = None
        if isinstance(js, dict):
            self.var = True
            if js.get("maskeli_klasor"):
                self.klasor = Path(js["maskeli_klasor"])
            self.kayit = {unicodedata.normalize("NFC", str(r.get("dosya"))): r
                          for r in js.get("dosyalar") or [] if r.get("dosya")}
            self.zaman = self.rapor_yolu.stat().st_mtime

    def sec(self, f: Path) -> tuple[Path, str, str, bool]:
        """→ (pakete girecek dosya, Maskeleme değeri, neden, karar bekliyor mu). Karar bekleyen kanıt o anki
        maskeli hâliyle (yoksa özgünüyle) döner; dışlama kararı çağıranındır."""
        if not self.var:
            return f, MASKE_YOK, "", False
        rel = f.relative_to(self.ev).as_posix()
        r = self.kayit.get(unicodedata.normalize("NFC", rel))
        if r is None:
            return f, MASKE_OZGUN, "maskeleme raporunda yok (maskelemeden sonra dosyalandı mı? bidr maskele yeniden)", True
        from bidr.mask.run import bekliyor
        d = r.get("durum")
        n = int(r.get("onay_bekleyen") or 0)
        eski = f.stat().st_mtime > self.zaman
        if d in ("tamam", "elle_maskelendi") and not bekliyor(r):
            m = self.klasor / (r.get("maskeli") or rel)
            if not m.is_file():
                return f, MASKE_OZGUN, "maskeli kopya bulunamadı (bidr maskele yeniden)", True
            if eski:
                return f, MASKE_OZGUN, "maskeli kopya eski (kanıt maskelemeden sonra yeniden dosyalandı; bidr maskele yeniden)", True
            return m, (MASKE_ELLE_YUKLENDI if d == "elle_maskelendi" else MASKE_TAMAM), "", False
        neden = (f"maskeleme {d or 'bilinmiyor'}" + (f", kararı verilmemiş öneri bölgesi {n}" if n else "")
                 + (", aşırı kapatma ölçümü eşiği aştı (insan kararı bekliyor)" if r.get("asiri_kapatma_bekliyor")
                    else "")
                 + f": {r.get('neden') or ''}").rstrip(": ")[:400]
        if eski:
            return f, MASKE_OZGUN, "maskeli kopya eski (kanıt maskelemeden sonra yeniden dosyalandı; bidr maskele "\
                                   "yeniden); " + neden, True
        adaylar = [self.ws / r[k] for k in ("teslim_kopya", "kopya") if r.get(k)]
        adaylar.append(self.klasor / (r.get("maskeli") or rel))
        m = next((p for p in adaylar if p.is_file()), None)
        if m is None:                    # hata / desteklenmiyor: maskeli kopya yok
            return f, MASKE_OZGUN, neden, True
        if r.get("kopya") and m == self.ws / r["kopya"] and n and not r.get("teslim_kopya"):
            neden += " (eski rapor: inceleme kopyasında öneri çerçeveleri var)"
        return m, MASKE_KARAR, neden, True


# -- kanıt maskelemesi: bölümün seçimi ve teslim uyarısı -------------------------------------------
# Teslim maskeleme yüzünden DURMAZ (karar 2026-11-25): maskeleme eksik/eski ya da kapalı olsa da paket üretilir,
# durum konsolda, `MASKELEME-UYARI.txt`'de ve manifestte (`maskeleme_uyarisi`) açıkça yazılır. Maskelemenin açık
# olup olmadığını bölümün ŞİMDİKİ seçimi belirler (`maskeleme_secimi`): config.yaml `privacy.maskeleme` (true/false,
# açıkça yazılmışsa her şeyden önce gelir), `privacy.mask_before_model` ya da kaynağın bidr'in maskeli kopyası olması
# (panel: bölüm model öncesi maskelemeyi seçti) ya da kanıt maskelemesinin bugünkü kanıt kümesi üzerinde koşturulmuş
# olması (`bidr maskele -w`; rapor kanıtlardan yeni). Kanıtlardan eski rapor ve kaynak raporu geçmiş izdir, seçim sayılmaz.
# Açıkken: maskeli kopya varsa o kullanılır; yoksa/eskiyse özgün dosya girer ve adıyla listelenir; karar bekleyen
# kanıt politika 2026-11-22 (ikinci karar) ile ele alınır. Kapalıyken bu kurallar uygulanmaz: açıkça kapatılmışsa
# (`privacy.maskeleme: false`) özgün dosyalar girer; seçim yoksa ve kanıt maskeleme raporu varsa (ör. panelin yalnız
# öneri kipi: yalnız bölümün "Kapat" dediği yerler kapalı) maskeli kopyalar kullanılır. Hattın `kanit_maskele`
# aşaması yalnız maskeleme açıkken görünür ve teslimin önkoşulu değildir (öneri).
MASKE_KAYNAK_RAPOR = "maskeleme-kaynak-raporu.json"     # bidr/mask/kaynak.py WS_RAPOR
MASKE_ISARET = ".bidr-maskeleme.json"                    # bidr/mask/run.py MARKER
MASKE_KOMUT = "bidr maskele -w {ws}"
MASKESIZ_NOT = "kanıtlar maskelenmeden paketlendi, kişisel veri içerebilir"
MASKESIZ_BASLIK = "MASKELİ KOPYASI OLMAYAN KANITLAR (ÖZGÜN HÂLİYLE PAKETTE): {n}"
# `_maske_eksigi` türleri: bidr maskele yeniden koşunca giderilenler (hat aşaması bunlarda komut önerir)
EKSIK_YENIDEN = frozenset({"rapor_yok", "klasor_yok", "raporda_yok", "eski"})


def maskeleme_secimi(ws: Path) -> tuple[bool | None, str]:
    """Bölümün şimdiki kişisel veri maskelemesi seçimi → (True: açık | False: açıkça kapalı | None: seçim yok,
    kapalı sayılır; kısa açıklama). Geçmiş izler (çalışma alanındaki rapor dosyaları) seçim değildir."""
    ws = Path(ws)
    try:
        from bidr.mask.detect import read_ws_config
        cfg = read_ws_config(ws)
    except Exception:  # noqa: BLE001 — okunamayan yapılandırma seçim sayılmaz (başka denetimler yakalar)
        cfg = {}
    priv = cfg.get("privacy") if isinstance(cfg.get("privacy"), dict) else {}
    if "maskeleme" in priv:
        v = priv["maskeleme"]
        kapali = v is False or v is None or (isinstance(v, str) and v.strip().lower() in
                                               ("false", "hayir", "hayır", "kapali", "kapalı", "yok", "0"))
        return (False, "config.yaml privacy.maskeleme: kapalı") if kapali else (True, "config.yaml privacy.maskeleme")
    if priv.get("mask_before_model"):
        return True, "config.yaml privacy.mask_before_model"
    try:
        k = _kaynak(ws)
    except Exception:  # noqa: BLE001
        k = None
    if k is not None and ((k / MASKE_ISARET).exists() or (k.parent / (k.name + ".maskeleme-raporu.json")).exists()):
        return True, f"kaynak klasör bölüm kaynak maskelemesinin kopyası ({k.name})"
    if _rapor_guncel(ws):
        return True, f"kanıt maskelemesi bugünkü kanıt kümesinde koşturulmuş ({MASKE_RAPOR})"
    return None, ""


def _rapor_guncel(ws: Path) -> bool:
    """Kanıt maskeleme raporu bugünkü kanıt kümesinden yeni mi (kanıtlar maskelemeden sonra yeniden dosyalanmadı):
    `bidr maskele -w` bu kanıtlar üzerinde koşturulmuş, yani şimdiki bir eylemdir. Kanıtlardan eski rapor geçmiş izdir,
    seçim sayılmaz."""
    rp, ev = ws / MASKE_RAPOR, ws / "evidence"
    if not rp.is_file() or not ev.is_dir():
        return False
    t = rp.stat().st_mtime
    isa = ev / ".bidr-evidence.json"
    if isa.exists() and isa.stat().st_mtime > t:
        return False
    return not any(f.is_file() and f.stat().st_mtime > t for f in ev.rglob("*")
                   if not any(x.startswith(".") for x in f.relative_to(ev).parts))


def maskeleme_kullaniliyor(ws: Path) -> str | None:
    """Bölüm şimdi kişisel veri maskelemesini seçmiş mi → seçimin kısa açıklaması (seçmemişse None)."""
    acik, neden = maskeleme_secimi(ws)
    return neden if acik else None


def _maske_eksigi(ws: Path) -> tuple[str | None, str | None]:
    """Maskeleme açıkken kanıt maskelemesinin teslime hazır olmayışı → (tür, açıklama); hazırsa ya da maskeleme
    kapalıysa (None, None). Türler: `rapor_yok`, `klasor_yok`, `raporda_yok`, `eski` (bidr maskele yeniden koşunca
    giderilir: `EKSIK_YENIDEN`) ve `kopya_yok` (karar beklemeyen tamam/elle kaydın maskeli kopyası yok). Karar
    bekleyen kayıtlar (`bidr.mask.run.bekliyor`: kararı verilmemiş öneri bölgesi, aşırı kapatma ölçümü eşiği,
    maskelenemeyen dosya) eksik değildir; teslim politikası onları listeler."""
    ws = Path(ws)
    isaret = maskeleme_kullaniliyor(ws)
    if isaret is None:
        return None, None
    ev = ws / "evidence"
    if not ev.is_dir():
        return None, None                            # kanıt yok: teslim zaten "önce bidr file" der
    on = f"maskeleme açık ({isaret}) ama "
    maske = Maske(ws, ev)
    if not maske.var:
        return "rapor_yok", on + f"kanıt maskelemesi yapılmamış ({MASKE_RAPOR} yok ya da okunamıyor)"
    if not maske.klasor.is_dir():
        return "klasor_yok", on + f"maskeli kanıt klasörü yok ({maske.klasor.name}/)"
    dosyalar = [f for f in ev.rglob("*") if f.is_file()
                and not any(x.startswith(".") for x in f.relative_to(ev).parts)]
    rel = {f: unicodedata.normalize("NFC", f.relative_to(ev).as_posix()) for f in dosyalar}
    yok = sorted(r for r in rel.values() if r not in maske.kayit)
    if yok:
        return "raporda_yok", on + f"{len(yok)} kanıt maskeleme raporunda yok (maskelemeden sonra dosyalandı): " \
            + ", ".join(yok[:3]) + (" …" if len(yok) > 3 else "")
    isa = ev / ".bidr-evidence.json"
    eski = sorted(rel[f] for f in dosyalar if f.stat().st_mtime > maske.zaman)
    if eski or (isa.exists() and isa.stat().st_mtime > maske.zaman):
        return "eski", on + "maskeli kopyalar kanıt kümesinden eski (kanıtlar maskelemeden sonra yeniden dosyalandı)" \
            + (": " + ", ".join(eski[:3]) + (" …" if len(eski) > 3 else "") if eski else "")
    from bidr.mask.run import bekliyor         # karar bekleyen (öneri / aşırı kapatma): teslim politikası
    eksik = sorted(r for r in rel.values() if (k := maske.kayit[r]).get("durum") in ("tamam", "elle_maskelendi")
                   and not bekliyor(k)
                   and not (maske.klasor / (k.get("maskeli") or r)).is_file())
    if eksik:
        return "kopya_yok", on + f"{len(eksik)} kanıtın maskeli kopyası {maske.klasor.name}/ içinde yok: " \
            + ", ".join(eksik[:3]) + (" …" if len(eksik) > 3 else "")
    return None, None


def maske_eksigi(ws: Path) -> str | None:
    """`_maske_eksigi`nin açıklaması (hazırsa ya da maskeleme kapalıysa None). Teslimi durdurmaz; uyarıdır."""
    return _maske_eksigi(ws)[1]


def oldugu_gibi_secimi(ws: Path) -> dict | None:
    """`<ws>/maskeleme-oldugu-gibi.json` → {kim, zaman} (bölüm "olduğu gibi devam" dedi); yoksa/okunamazsa None."""
    try:
        j = json.loads((Path(ws) / OLDUGU_GIBI).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(j, dict):
        return None
    return {"kim": str(j.get("kim") or ""), "zaman": str(j.get("zaman") or "")}


def _tarih(s: str | None) -> dt.date:
    if not s:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(str(s))
    except ValueError:
        raise TeslimError(f"tarih YYYY-AA-GG olmalı: {s}") from None


def _hazirla_cikti(out: Path, ws: Path, kaynak: Path | None) -> None:
    out = out.resolve()
    if out == ws or out in ws.parents:
        raise TeslimError(f"çıktı klasörü çalışma alanının kendisi ya da üstü olamaz: {out}")
    if kaynak is not None and (out == kaynak or kaynak in out.parents or out in kaynak.parents):
        raise TeslimError(f"çıktı klasörü kaynak klasörle iç içe olamaz: {out}")
    if out.exists():
        if not (out / ISARET).exists():
            if any(out.iterdir()):
                raise TeslimError(f"çıktı klasörü boş değil ve bidr teslim paketi değil: {out} "
                                  "(başka bir --out verin ya da klasörü boşaltın)")
        else:
            shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / ISARET).write_text("bidr teslim paketi: bu klasör `bidr teslim` ile yeniden yazılır\n", encoding="utf-8")


def _kaynak(ws: Path) -> Path | None:
    from bidr.init.config import load_section
    k = (load_section(ws) or {}).get("kaynak")
    return Path(k).expanduser().resolve() if k else None


def paket_adi(ws: Path) -> str:
    """Varsayılan paket adı: `BIDR-<dönem>-<Birim>` (ör. BIDR-2025-Matematik-Bölümü); bilgi yoksa `teslim`."""
    try:
        from bidr.init.config import load_section
        sec = load_section(Path(ws)) or {}
    except Exception:  # noqa: BLE001 — ad için yapılandırma yoksa düz ad
        sec = {}
    birim = re.sub(r"[^\w]+", "-", str(sec.get("birim") or "")).strip("-")
    donem = sec.get("donem")
    if not birim or not donem:
        return "teslim"
    return f"BIDR-{donem}-{birim}"


def build(ws: Path, out: Path | None = None, *, docx_path: Path | None = None, tarih: str | None = None,
          zip_yap: bool = True, arac: str | object = "otomatik", canli: bool = False,
          taslak: bool = False, kararsizlari_disla: bool = False, oldugu_gibi: bool | dict | None = None) -> Sonuc:
    """Teslim paketini yazar. `arac`: "otomatik" | "chrome" | "weasyprint" ya da `bas(html, pdf, ag=)`
    yöntemi olan nesne. Web kanıtı varken araç yoksa PdfAraciYok (hiçbir şey yazılmadan).
    `kararsizlari_disla`: maskeleme kararı bekleyen kanıt pakete girmez (eski davranış). `oldugu_gibi`: "olduğu gibi
    devam" (None: `<ws>/maskeleme-oldugu-gibi.json`'a bakılır; True/dict: seçili): karar bekleyen kanıt incelenmeden o
    anki hâliyle girer (`kararsizlari_disla` uygulanmaz) ve "incelenmemiş öneri vardı, olduğu gibi eklendi" diye
    listelenir."""
    import docx

    from bidr.check.run import kanit_listeleri

    ws = Path(ws).expanduser().resolve()
    mod = teslim_modu(ws)
    rep = Path(docx_path).expanduser().resolve() if docx_path else ws / RAPOR
    ev, index = ws / "evidence", ws / "evidence-index.csv"
    if not rep.exists():
        raise TeslimError(f"rapor yok: {rep} (önce bidr render)")
    if not ev.is_dir():
        raise TeslimError(f"kanıt klasörü yok: {ev} (önce bidr file)")
    gun = _tarih(tarih)
    acik, secim_neden = maskeleme_secimi(ws)
    eksik_maske = maske_eksigi(ws) if acik else None      # uyarı: teslim durmaz
    out = Path(out).expanduser().resolve() if out else ws / paket_adi(ws)

    listeler = kanit_listeleri(docx.Document(str(rep)))
    dosyalar = _kanit_dosyalari(ev)
    dizin = _dizin(index)
    res = Sonuc(str(out), None, gun.isoformat(), mod, taslak=taslak, kararsizlari_disla=kararsizlari_disla)
    maske = Maske(ws, ev)
    if acik is False:                    # bölüm maskelemeyi açıkça kapattı: maskeleme çıktısı kullanılmaz
        maske.var = False
    res.maskeleme = maske.var
    res.maskeleme_acik = bool(acik)
    res.maskeleme_eksigi = eksik_maske
    if oldugu_gibi is None:
        oldugu_gibi = oldugu_gibi_secimi(ws)
    if oldugu_gibi:
        res.oldugu_gibi = oldugu_gibi if isinstance(oldugu_gibi, dict) else {"kim": "", "zaman": dt.datetime.now()
                                                                            .astimezone().isoformat(timespec="seconds")}
        kararsizlari_disla = res.kararsizlari_disla = False
    if not any(listeler.values()):
        res.eksik.append("raporda tanınan kanıt listesi satırı yok ('[1-OD3]. Ad' ya da '1_OD3: Ad')")

    # eşleşme (önce, araç gerekip gerekmediği bilinsin)
    plan: list[tuple[object, list[Path], str]] = []
    for olcut in sorted(listeler, key=_olcut_key):
        for k in listeler[olcut]:
            fs, neden, artik = _eslestir(k, dosyalar.get((olcut, k.no), []), dizin.get((olcut, k.no), []))
            plan.append((k, fs, neden))
            for f in artik:
                res.uyarilar.append(f"dizinde olmayan dosya pakete alınmadı: {olcut}/{f.name}")
    listed = {(k.olcut, k.no) for k, _, _ in plan}
    for (olcut, n), lst in sorted(dosyalar.items(), key=lambda kv: (_olcut_key(kv[0][0]), kv[0][1])):
        if (olcut, n) not in listed:
            res.uyarilar.append(f"listede olmayan dosya pakete alınmadı: {olcut}/{lst[0][1].name}")

    pdf = None
    if any(is_web(f) for _, fs, _ in plan for f in fs):
        pdf = pdf_araci(arac) if isinstance(arac, str) else arac       # PdfAraciYok: hiçbir şey yazılmaz
        res.pdf_araci = getattr(pdf, "ad", type(pdf).__name__)

    _hazirla_cikti(out, ws, _kaynak(ws))
    shutil.copyfile(rep, out / RAPOR)
    kok = out / KANITLAR
    damga_tarihi = gun.strftime("%d.%m.%Y")
    for k, f, r, neden in _satirlar(plan, dizin):
        no = f"{k.no}_OD{k.od}"
        ad = (r.get("ad") or "").strip() or _ad_sade(k.ad, k.baglanti)
        row = {"olcut": k.olcut, "kanit_no": no, "od": k.od, "ad": ad, "dosya": "", "pdf_kopya": "",
               "ozgun_baglanti": "", "baglanti_kaynagi": "", "alinma_tarihi": "", "maskeleme": "",
               "isaretler": (r.get("isaretler") or "").strip(), "durum": "tamam", "_web": False}
        res.satirlar.append(row)
        if f is None:
            row["durum"] = f"eksik: {neden}"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: {neden}")
            continue
        # paketteki adlar NFC (Windows'ta ayrışık Türkçe karakter bozuk görünür)
        rel = Path(unicodedata.normalize("NFC", f.relative_to(ev).as_posix()))
        kaynak, row["maskeleme"], elle, bekleyen = maske.sec(f)
        if not acik:                    # karar bekleyen kuralları yalnız maskeleme açıkken
            bekleyen = False
        kanit = rel.as_posix()
        if bekleyen and kararsizlari_disla:      # eski davranış: maskeleme kararı bekleyen pakete girmez
            row["maskeleme"] = MASKE_DISLANDI
            row["durum"] = "kontrol bekliyor: maskeleme kararı bekliyor (pakete girmedi; --kararsizlari-disla)"
            res.karar_bekleyen.append({"olcut": k.olcut, "kanit_no": no, "kanit": kanit, "dosya": "",
                                       "maskeleme": MASKE_DISLANDI, "neden": elle, "pakette": False})
            continue
        if kaynak.suffix.lower() != f.suffix.lower():       # eski biçimden çevrilen maskeli kopya
            rel = rel.with_suffix(kaynak.suffix)
        dst = kok / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(kaynak, dst)
        row["dosya"] = f"{KANITLAR}/{rel.as_posix()}"
        if acik and row["maskeleme"] == MASKE_YOK:      # maskeleme açık, rapor yok: özgün dosya
            row["durum"] = "tamam; MASKELENMEDİ (kanıt maskelemesi yapılmamış; özgün dosya pakette)"
            res.maskesiz.append({"olcut": k.olcut, "kanit_no": no, "kanit": kanit, "dosya": row["dosya"],
                                 "neden": eksik_maske or "kanıt maskelemesi yapılmamış"})
        if bekleyen:
            row["durum"] = ("tamam; maskeleme kararı bekliyor (o anki maskeli hâli pakette)" if row["maskeleme"] == MASKE_KARAR
                            else "tamam; MASKELENMEDİ (özgün dosya pakette)")
            res.karar_bekleyen.append({"olcut": k.olcut, "kanit_no": no, "kanit": kanit, "dosya": row["dosya"],
                                       "maskeleme": row["maskeleme"], "neden": elle, "pakette": True,
                                       **({"oldugu_gibi": True} if res.oldugu_gibi else {})})
            if res.oldugu_gibi:
                row["durum"] = "tamam; incelenmemiş öneri vardı, olduğu gibi eklendi"
        elif elle:
            res.elle_bakilacak.append({"dosya": row["dosya"], "neden": elle})
        url_dizin, src = (r.get("baglanti") or "").strip(), (r.get("baglanti_kaynagi") or "").strip()
        if not is_web(f):
            if url_dizin and (src != "klasor" or mod == BAGLANTI):
                row["ozgun_baglanti"], row["baglanti_kaynagi"] = url_dizin, src or "dizin"
            continue
        row["_web"] = True
        url, nereden = web_url(f, url_dizin, src)
        row["ozgun_baglanti"] = url or BILINMIYOR
        row["baglanti_kaynagi"] = nereden or ""
        pdf_dst = dst.with_suffix(".pdf")
        if pdf_dst.exists() or (f.with_suffix(".pdf")).exists():
            row["durum"] = "eksik: PDF kopyasının adı başka bir dosyayla çakışıyor"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: PDF kopyası adı çakışıyor ({pdf_dst.name})")
            continue
        try:
            web_pdf(kaynak, pdf_dst, url=url, tarih=damga_tarihi, arac=pdf, canli=canli and kaynak == f)
        except PdfHatasi as e:
            row["durum"] = f"eksik: PDF kopyası üretilemedi ({e})"
            res.eksik.append(f"{k.olcut} [{no}] {ad}: PDF kopyası üretilemedi ({e})")
            continue
        row["pdf_kopya"] = f"{KANITLAR}/{pdf_dst.relative_to(kok).as_posix()}"
        row["alinma_tarihi"] = gun.isoformat()
        if not url:
            res.uyarilar.append(f"{k.olcut} [{no}] {ad}: web sayfasının özgün adresi bulunamadı "
                                f"(dizinde '{BILINMIYOR}'; biliniyorsa review.xlsx 'bağlantı' sütununa yazın)")

    _dizin_yaz(out, res.satirlar)
    _maske_uyarisi(res, acik, secim_neden, ws)
    if res.kontrol_bekliyor:
        res.uyarilar.append(KONTROL_UYARI.format(n=len(res.kontrol_bekliyor)) + " (pakete girmedi; bidr maskele "
                            "bolgeler -w WS ile bölgelere karar verin ya da maskeli sürümü yükleyin, sonra bidr "
                            "maskele ve bidr teslim yeniden)")
    pakette = [x for x in res.karar_bekleyen if x["pakette"]]
    UL: list[str] = []
    if res.maskeleme_uyarisi:
        UL += ["KİŞİSEL VERİ MASKELEMESİ", "", res.maskeleme_uyarisi, ""]
    if res.maskesiz:
        UL += [MASKESIZ_BASLIK.format(n=len(res.maskesiz)), ""]
        UL += [f"- {x['olcut']} [{x['kanit_no']}] {x['dosya']}" for x in res.maskesiz] + [""]
    if pakette and res.oldugu_gibi:
        kim = res.oldugu_gibi.get("kim") or ""
        res.uyarilar.append(OLDUGU_GIBI_UYARI.format(n=len(pakette)) + f" (\"olduğu gibi devam\"{' — ' + kim if kim else ''}"
                            f"; {MASKE_UYARI}): kendiliğinden maskelenmiş hâlleri pakette, kalan kişisel veri "
                            "içerebilir")
        UL += [OLDUGU_GIBI_BASLIK.format(n=len(pakette)), "",
               f"Bölüm maskeleme önerilerini incelemeden devam etti (\"olduğu gibi devam\""
               + (f", {kim}" if kim else "") + (f", {res.oldugu_gibi.get('zaman')}" if res.oldugu_gibi.get("zaman") else "")
               + "). " + OLDUGU_GIBI_UYARI.format(n=len(pakette)) + ": kesin kapatmalar uygulanmış, incelenmemiş "
               "öneriler AÇIK; kalan kişisel veri içerebilir.", ""]
        UL += [f"- {x['olcut']} [{x['kanit_no']}] {x['dosya']} ({x['maskeleme']}): {x['neden']}" for x in pakette]
    elif pakette:
        ozg = sum(1 for x in pakette if x["maskeleme"] == MASKE_OZGUN)
        res.uyarilar.append(KARAR_UYARI.format(n=len(pakette)) + (f"; {ozg} tanesi MASKELENMEDİ (özgün dosya)" if ozg else "")
                            + f" — {MASKE_UYARI}; karar: bidr maskele bolgeler/karar/yukle, sonra bidr maskele ve "
                            "bidr teslim yeniden")
        L = [KARAR_BASLIK.format(n=len(pakette)), "",
             "Şu kanıtlar pakette ama kişisel veri maskelemesi tamamlanmadı. \"karar bekliyor\": kesin kapatmalar "
             "uygulanmış, kararı verilmemiş öneriler AÇIK; \"maskelenmedi\": maskeleme yapılamadı, ÖZGÜN dosya. "
             "Teslimden önce gözden geçirin (bidr maskele bolgeler / karar / yukle, sonra bidr maskele ve bidr "
             "teslim):", ""]
        L += [f"- {x['olcut']} [{x['kanit_no']}] {x['dosya']} ({x['maskeleme']}): {x['neden']}" for x in pakette]
        UL += L
    if UL:
        (out / MASKE_UYARI).write_text("\n".join(UL).rstrip("\n") + "\n", encoding="utf-8")
    if res.eksik or taslak or res.kontrol_bekliyor:
        L = []
        if taslak:
            L += ["TASLAK PAKET", "", "Bu paket biçim denetimi (bidr denetle) geçmeden `--taslak` ile üretildi; "
                  "teslim edilmeden önce yeniden üretilmelidir.", ""]
        if res.eksik:
            L += ["EKSİK TESLİM PAKETİ", "", "Raporun kanıt listesindeki şu satırlar paketteki bir dosyayla "
                  "eşleşmedi ya da web kanıtının PDF kopyası üretilemedi:", ""]
            L += [f"- {e}" for e in res.eksik]
        if res.kontrol_bekliyor:
            L += ["", KONTROL_BASLIK.format(n=len(res.kontrol_bekliyor)), "",
                  "Şu kanıtlar raporda atıflı (numaraları değişmedi) ama pakete girmedi: kişisel veri maskelemesi "
                  "insan kontrolü bekliyor (bidr maskele bolgeler / karar / yukle, sonra bidr maskele ve bidr teslim):", ""]
            L += [f"- {x['olcut']} [{x['kanit_no']}] {x['kanit']}: {x['neden']}" for x in res.kontrol_bekliyor]
        (out / EKSIK).write_text("\n".join(L) + "\n", encoding="utf-8")
    if zip_yap:
        z = out.with_name(out.name + ".zip")
        _zip(out, z)
        res.zip = str(z)
    man = {"surum": SURUM, **res.ozet(), "report": str(rep), "report_sha": sha(rep), "index_sha": sha(index),
           "evidence_sha": sha(ev / ".bidr-evidence.json"), "maske_sha": sha(ws / MASKE_RAPOR)}
    (ws / MANIFEST).write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def _maske_uyarisi(res: Sonuc, acik: bool | None, secim_neden: str, ws: Path) -> None:
    """Maskeleme durumunun kısa uyarı cümlesi (`res.maskeleme_uyarisi`) ve konsol uyarısı. Karar bekleyen listesi
    ayrıca (`KARAR_UYARI`)."""
    girdi = [r for r in res.satirlar if r["dosya"]]
    if not girdi:
        return
    if not acik:
        if res.maskeleme:
            m = ("kişisel veri maskelemesi bölümde seçili değil; mevcut maskeleme raporundaki maskeli kopyalar "
                 "kullanıldı (yalnız raporda kapatılan yerler kapalı), maskeli kopyası olmayan kanıtlar özgün hâliyle "
                 "pakette; kişisel veri içerebilir")
        else:
            m = ("kişisel veri maskelemesi " + ("kapalı (" + secim_neden + ")" if acik is False else "seçili değil")
                 + f": {MASKESIZ_NOT}")
        res.maskeleme_uyarisi = m
        res.uyarilar.append(m)
        return
    ozgun = [r for r in girdi if r["maskeleme"] in (MASKE_OZGUN, MASKE_YOK)]
    if res.maskeleme_eksigi or ozgun:
        m = (f"kanıt maskelemesi tamamlanmadı ({res.maskeleme_eksigi}); " if res.maskeleme_eksigi else "") \
            + (f"{len(ozgun)} kanıt maskelenmeden (özgün hâliyle) pakette, kişisel veri içerebilir — {MASKE_UYARI}; "
               f"düzeltmek için {MASKE_KOMUT.format(ws=ws)}, sonra bidr teslim" if ozgun else
               f"paket yine üretildi — {MASKE_UYARI}")
        res.maskeleme_uyarisi = m
        res.uyarilar.append(m)


def _satirlar(plan, dizin):
    """Plan → (rapor satırı, dosya ya da None, dizin satırı, eksik nedeni); numaranın her dosyası
    kanıt dizininde ayrı satır (aynı numara) olur."""
    for k, fs, neden in plan:
        rows = dizin.get((k.olcut, k.no)) or []
        if not fs:
            yield k, None, (rows[0] if rows else {}), neden
            continue
        by = _dizin_dosyalari(rows)
        for f in fs:
            yield k, f, by.get(unicodedata.normalize("NFC", f.name)) or (rows[0] if rows else {}), ""


def _ad_sade(ad: str, url: str | None) -> str:
    """Rapordaki satır adından görünür adres ekini çıkarır: "Ad (https://…)" → "Ad"."""
    if url and ad.endswith(f"({url})"):
        return ad[: -len(url) - 2].rstrip()
    return re.sub(r"\s*\(https?://[^)]*\)$", "", ad)


def _olcut_key(c: str) -> tuple:
    p = c.split(".")
    return (p[0], *[int(x) if x.isdigit() else 0 for x in p[1:]])


def _dizin_yaz(out: Path, satirlar: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    rows = [{k: r[k] for k in SUTUNLAR} for r in satirlar]
    with open(out / f"{DIZIN}.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(BASLIKLAR)
        for r in rows:
            w.writerow([r[k] for k in SUTUNLAR])
    wb = Workbook()
    ws = wb.active
    ws.title = "Kanıt dizini"
    ws.append(BASLIKLAR)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([r[k] for k in SUTUNLAR])
        url = r["ozgun_baglanti"]
        if url.startswith(("http://", "https://")):
            cell = ws.cell(row=ws.max_row, column=SUTUNLAR.index("ozgun_baglanti") + 1)
            cell.hyperlink = url
            cell.font = Font(color="0563C1", underline="single")
    widths = [9, 9, 5, 50, 60, 60, 50, 16, 13, 22, 30]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = wdt
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(vertical="top", wrap_text=c.column in (4, 5, 6, 11))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(out / f"{DIZIN}.xlsx")


def _zip(out: Path, z: Path) -> None:
    tmp = z.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(out.rglob("*")):
            rel = p.relative_to(out)
            if not p.is_file() or any(x.startswith(".") for x in rel.parts):
                continue
            ad = unicodedata.normalize("NFC", f"{out.name}/{rel.as_posix()}")
            zi = zipfile.ZipInfo(ad, (1980, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.flag_bits |= 0x800          # UTF-8 dosya adı (Türkçe karakter)
            zf.writestr(zi, p.read_bytes())
    tmp.replace(z)


# -- hat denetimi ----------------------------------------------------------------------------------

def load_manifest(ws: Path) -> dict | None:
    p = Path(ws) / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def durum(c):
    """`teslim_tamam` (bidr/pipeline/checks.py): paket güncel ve eksiksiz mi."""
    from bidr.pipeline.checks import INSAN, KOMUT, Check
    ws = c.ws.root
    cmd = c.fmt(c.stage["komut"][0])
    try:
        mod = teslim_modu(ws)
    except ValueError as e:
        return Check(kim=INSAN, neden=str(e))
    m = load_manifest(ws)
    if not m:
        if mod == BAGLANTI:
            return Check(atlandi=True, neden="teslim modu baglanti: kanıtlar raporda bağlantıyla verilir; paket "
                                             "istenirse bidr teslim")
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi üretilmedi (rapor ve kanıtlar dekanlığa "
                                                      "dosya olarak teslim edilecek)")
    rep = Path(m.get("report") or ws / RAPOR)
    if not Path(m.get("cikti") or "").is_dir() or (m.get("zip") and not Path(m["zip"]).exists()):
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi klasörü ya da zip'i yok: yeniden üret")
    if (m.get("report_sha") != sha(rep) or m.get("index_sha") != sha(ws / "evidence-index.csv")
            or m.get("evidence_sha") != sha(ws / "evidence" / ".bidr-evidence.json")
            or m.get("teslim_modu") != mod or m.get("maske_sha", "") != sha(ws / MASKE_RAPOR)
            or m.get("maskeleme_acik", bool(maskeleme_secimi(ws)[0])) != bool(maskeleme_secimi(ws)[0])
            or bool(m.get("oldugu_gibi")) != bool(oldugu_gibi_secimi(ws))):
        return Check(kim=KOMUT, komutlar=[cmd], neden="teslim paketi eski: rapor, kanıt klasörü, maskeleme raporu, "
                                                      "maskeleme seçimi (olduğu gibi devam dahil) ya da teslim modu değişti")
    prog = {k: m.get(k) for k in ("kanit", "web", "web_pdf", "baglanti_bilinmiyor")}
    if m.get("taslak"):
        return Check(kim=KOMUT, komutlar=[cmd], ilerleme=prog,
                     neden="paket --taslak ile (denetim geçmeden) üretildi: denetim geçince yeniden üret")
    if m.get("eksik"):
        e = m["eksik"]
        return Check(kim=INSAN, komutlar=[cmd], ilerleme=prog,
                     neden=f"paket eksik ({len(e)}): " + "; ".join(e[:3]) + (" …" if len(e) > 3 else "")
                           + " — kaynağı düzelt (kanıt klasörü / PDF aracı) ve yeniden üret")
    if m.get("kontrol_bekliyor"):                 # yalnız --kararsizlari-disla: pakete girmedi
        e = m["kontrol_bekliyor"]
        return Check(kim=INSAN, komutlar=["bidr maskele bolgeler -w {ws}".replace("{ws}", str(ws)), cmd], ilerleme=prog,
                     neden=KONTROL_UYARI.format(n=len(e)) + ": " + ", ".join(x["kanit"] for x in e[:3])
                           + (" …" if len(e) > 3 else "") + " — bölge kararı (bidr maskele karar) ya da maskeli "
                           "sürüm (bidr maskele yukle), sonra bidr maskele ve bidr teslim")
    uy = []
    if m.get("maskeleme_uyarisi"):
        uy.append(m["maskeleme_uyarisi"])
    if m.get("karar_bekleyen"):
        e = m["karar_bekleyen"]
        ozg = sum(1 for x in e if x.get("maskeleme") == MASKE_OZGUN)
        uy.append((OLDUGU_GIBI_UYARI if m.get("oldugu_gibi") else KARAR_UYARI).format(n=len(e))
                  + (f" ({ozg} MASKELENMEDİ)" if ozg else "") + ": "
                  + ", ".join(x["kanit"] for x in e[:3]) + (" …" if len(e) > 3 else "")
                  + f" — {MASKE_UYARI}; bidr maskele bolgeler -w {ws}")
    if m.get("elle_bakilacak"):
        e = m["elle_bakilacak"]
        uy.append(f"{len(e)} kanıt için not (kanıt dizini 'Maskeleme'; {MANIFEST} elle_bakilacak): "
                  + ", ".join(x["dosya"] for x in e[:3]) + (" …" if len(e) > 3 else ""))
    if (m.get("maskeleme") or {}).get("rapor") is False and not m.get("maskeleme_uyarisi"):
        uy.append("kişisel veri maskelemesi yapılmadı (kanıt dizini 'Maskeleme: yapılmadı'): bidr maskele")
    if m.get("baglanti_bilinmiyor"):
        uy.append(f"{m['baglanti_bilinmiyor']} web kanıtının özgün adresi bulunamadı (kanıt dizininde "
                  f"'{BILINMIYOR}'); biliniyorsa review.xlsx 'bağlantı' sütununa yazılır")
    return Check(bitti=True, ilerleme=prog, uyarilar=uy, neden=f"teslim paketi: {m['cikti']}"
                                                               + (f" + {m['zip']}" if m.get("zip") else ""))


def kanit_maskele_durum(c):
    """`kanit_maskele_tamam` (bidr/pipeline/checks.py): bölüm maskelemeyi seçmişse kanıtların maskeli kopyası güncel mi.
    Öneridir, teslimin önkoşulu değildir: maskeleme seçili değilse (ya da teslim modu `baglanti` iken paket yoksa)
    atlanır; `bidr maskele` yeniden koşunca giderilecek eksikte (rapor yok, maskeli klasör yok, raporda olmayan ya da
    maskelemeden sonra değişen kanıt) komut önerir; yeniden koşunun gidermeyeceği eksikte (karar beklemeyen kaydın
    maskeli kopyası yok) uyarıyla biter (döngü yok; teslim o kanıtı özgün hâliyle koyar ve adıyla listeler)."""
    from bidr.pipeline.checks import INSAN, KOMUT, Check
    ws = c.ws.root
    isaret = maskeleme_kullaniliyor(ws)
    if isaret is None:
        return Check(atlandi=True, neden="kişisel veri maskelemesi seçili değil (config.yaml privacy.maskeleme ya da "
                                         "bölüm kaynak maskelemesi yok); teslim paketi uyarıyla maskesiz kurulur")
    try:
        mod = teslim_modu(ws)
    except ValueError as e:
        return Check(kim=INSAN, neden=str(e))
    if mod == BAGLANTI and not load_manifest(ws):
        return Check(atlandi=True, neden="teslim modu baglanti: paket üretilmiyor; paket istenirse önce bidr "
                                         "maskele, sonra bidr teslim")
    tur, e = _maske_eksigi(ws)
    if tur in EKSIK_YENIDEN:
        return Check(kim=KOMUT, komutlar=[c.fmt(c.stage["komut"][0])], neden=e)
    m = Maske(ws, ws / "evidence")
    if e:
        return Check(bitti=True, ilerleme={"dosya": len(m.kayit)}, neden=f"kanıt maskelemesi koştu ({isaret})",
                     uyarilar=[f"{e} — bidr maskele yeniden koşmak bunu gidermez; teslim paketi bu kanıtları "
                               f"özgün hâliyle koyar ve {MASKE_UYARI}'de adıyla listeler"])
    return Check(bitti=True, ilerleme={"dosya": len(m.kayit)},
                 neden=f"maskeli kanıt kopyası güncel ({isaret}; {m.klasor.name}/)")


def ozet_json(res: Sonuc) -> str:
    return json.dumps(res.ozet(), ensure_ascii=False, indent=1)
