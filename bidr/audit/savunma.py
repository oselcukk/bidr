"""Kod tarafı savunmalar: modelin bilinen yanlışlarını ucuz, belirleyici denetimlerle yakalar.

Model yok. Girdi: belge türü (`documents.jsonl`), alıntı, model gerekçesi, belge metni
(`text/`), birim adı (`config.yaml` `bidr.birim`) ve varsa faaliyet kayıtları
(`faaliyetler.json`). Gerekçe ve örnekler: docs/AUDIT.md "Kod tarafı savunmalar" ve
"Faaliyet kayıtları". Her düşürme satırda işaretlenir; insan `kabul` ya da `duzelt` derse
metin sezgileri uygulanmaz (insan kararı kuralı aşar; tür ve birim kuralları gibi).

Satır düzeyi (`row`): hariç tür, bilgisiz ekran, yürürlükten kaldırılmış düzenleme, madde
ilkesi, boş form, duyuru/gelecek zaman, kurum geneli ifade, faaliyet aşaması, aşama
sözcük denetimleri (katılım ≠ izleme; niyet, bilgilendirme, sürüm notu ve yönlendirme/talep —
"Başkanlığa iletilmesine karar" — ≠ iyileştirme). Etkinlik dosyası: gerçekleşmesi kanıtlı faaliyetin
duyurusu/afişi, gerçekleşme belgesi aynı ölçütte kabul edilmişse ve yuva uygulamayı kabul ediyorsa `uygula`
sayılır (`etkinlik_gerceklesti`); gerçekleşme başka ölçütteyse afiş planlama kalır.
Belge düzeyi (`unit_relation`): metinde birimin açık sinyali (adı, program adı, bölüm sayfası
yolu, ders kodu öneki) hiç yokken başka birim adı geçen belge `belirsiz`, bütün birimleri kapsayan
belge kurum/fakülte geneli sayılır; model `belirsiz` dediyse ve metinde birimin sinyali varsa
(başka birim adı, kurum geneli ifade yoksa) `kendi` önerilir. Fakülteye göre maddeli kurum
düzenlemesinde başka fakültenin maddesinden alıntı sayılmaz (`madde_baska_fakulte`).
Ölçüt düzeyi (`criterion`): iyileştirme–izleme bağı (K→Ö), özgünlük (bağımsız kanıt ve
süreklilik), fotoğrafın sahnesine göre değeri (etkinlik sayılır; mekân/altyapı planla; belirsiz
destekleyici), uygulamanın yayılımı (OD3 kısmi).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from bidr.identify.text import fold

from .rules import LINKS

ORDER = {x: i for i, x in enumerate(LINKS)}
FAALIYET = "faaliyetler.json"

# -- tür listeleri --------------------------------------------------------------------------
DUYURU_TURLER = frozenset({"etkinlik_duyurusu"})
FORM_TURLER = frozenset({"anket_formu", "form_belgesi"})
FOTOGRAF_TURLER = frozenset({"fotograf"})
# Bilgisiz ekran denetimi yalnız bu türlerde (gerçek içerikli madde listelerini korumak için).
EKRAN_TURLER = frozenset({"web_sayfasi", "ekran_goruntusu", "form_belgesi", "bilinmiyor", "", None})
# Bölümün kendi tanıtım/öz beyan metinleri: özgünlüğün bağımsız kanıtı olamaz.
OZ_BEYAN_TURLER = frozenset({"web_sayfasi", "ekran_goruntusu", "etkinlik_duyurusu", "faaliyet_raporu",
                             "oz_degerlendirme_raporu", "bidr_raporu", "bidr_sablonu", "olcut_aciklama_taslagi"})
# Tek belgesi bile bölüm geneline yayılmış uygulama sayılan türler (kurul kararı bölüm uygulamasıdır).
YAYGIN_TURLER = frozenset({"bolum_kurulu_karari", "anabilim_dali_kurulu_karari", "mufredat", "akts_bilgi_paketi",
                           "ders_programi", "acilan_dersler", "gorev_dagilimi", "istatistik_tablosu"})

# -- katlanmış (ascii, küçük harf) metin desenleri -------------------------------------------
GELECEK = re.compile(r"\b(?!gelecek)\w{2,}(?:acak|ecek)(?:lar|ler)?(?:tir|dir)\b"
                     r"|\b(?!gelecek)\w{2,}(?:acak|ecek)\s*,")
NIYET = re.compile(r"oneril|onumuzdeki|planlanmakta|planlanmistir|dusunulmekte|hedeflenmekte|tavsiye edil")
BILGI = re.compile(r"bilgi(?:si)?(?:ne|ye) sunul|bilgi veril|bilgilendiril|bilgi edinil")
SURUM = re.compile(r"revize|\bsurum|versiyon|guncellenmis hali|duzeltilmis hali")
# Yönlendirme/talep: geri bildirimin ya da talebin bir makama iletilmesi kararı, üst yazı ("gereğini
# arz ederiz"), talep. Kanıt ilkesi `iyilestirme_kaniti`: iyileştirme değildir (izleme sonucu
# değerlendirilip iletildiyse kontrol_et). Karar alıntısındaki "…-mesine/-masına" fiillerinin hepsi
# yönlendirme fiiliyse yönlendirmedir; aynı alıntıda başka bir fiille alınmış karar (ör. "soruların ayrı
# hazırlanmasına karar") yapılmış değişikliktir.
KARAR_FIIL = re.compile(r"\b(\w+?)(?:ma|me)s[iı]n[ae]\b")
YONLENDIRME_FIIL = ("iletil", "ilet", "bildiril", "bildir", "gonderil", "gonder", "sunul", "havale",
                    "aktaril", "yazil", "talep", "istenil", "isten", "duyurul", "paylasil")
YONLENDIRME = re.compile(r"iletil\w*|bildiril\w*|gonderil\w*|havale edil\w*|arz eder|talep edil\w*"
                         r"|talebinde bulun\w*|talep olunur")
DEGISIKLIK = re.compile(r"degistiril|degisiklik yapil|guncellen|eklen|cikaril|kaldiril|acil|"
                        r"yeniden duzenlen|yeniden yapilandir|uygulamaya kon|baslatil")


def yonlendirme(q: str) -> bool:
    """Katlanmış alıntı yalnız yönlendirme/talep mi (yapılmış bir değişiklik söylemiyor)."""
    fiil = KARAR_FIIL.findall(q) if "karar" in q else []
    if fiil:
        return all(v.startswith(YONLENDIRME_FIIL) for v in fiil)
    return bool(YONLENDIRME.search(q)) and not DEGISIKLIK.search(q)
# izleme/ölçme sonucunu gösteren sözcükler (kontrol_et alıntısında aranır)
IZLEME = re.compile(r"anket|sonuc|bulgu|degerlendir|izlen|incelen|olcul|olcme|ortalama|%|\boran|hedef"
                    r"|memnuniyet|geri ?bildirim|analiz|tespit|belirlen|gorul|yetersiz|zayif|oneril"
                    r"|gozden gecir|karsilastir")
# faaliyetin yapıldığını (izlendiğini değil) söyleyen kayıt
ETKINLIK = re.compile(r"katil|sergilen|duzenlen|gerceklestiril|yapilmistir|dagitil|atan")
# iyileştirmenin bir izleme sonucuna dayandığını gösteren bağ (alıntı, gerekçe ya da belge metni)
BAG = re.compile(r"sonuc|bulgu|anket|degerlendirme|izleme|rapor|geri ?bildirim|analiz|tespit|yetersiz"
                 r"|hedefin alt|inceleme")
# alıntıda bütün birimleri kapsayan ifade
GENEL_IFADE = re.compile(r"(?:fakultemiz|universitemiz|fakulte|universite)\w* (?:butun|tum|cesitli|bagli butun)"
                         r" (?:bolum|birim|fakulte|akademik birim)|(?:butun|tum) (?:bolumlerinde|birimlerinde"
                         r"|fakultelerde)|(?:fakulte|universite) genelinde")
KURUM_BELGE = re.compile(r"rektorlug|senato|universitemiz|universitesine bagli butun|butun akademik birim"
                         r"|butun fakulte|universite genelinde|universitesinin butun")
FAKULTE_BELGE = re.compile(r"fakultemiz|fakulte genelinde|dekanlig|fakulte (?:yonetim )?kurulu|fakulte staj"
                           r"|butun bolumlerinde|tum bolumlerinde")
DIS_TANINMA = re.compile(r"iyi uygulama|odul|akredit|ornek (?:gosteril|uygulama)\w* (?:secil|olarak)|secil"
                         r"|yayginlastir|tescil|disaridan|dis paydas")
SUREKLILIK = re.compile(r"\b(?:19|20)\d\d\s*(?:yilindan|'?(?:den|dan|ten|tan))\s*(?:bu yana|beri)"
                        r"|\d+\s*yildir|yillardir|kesintisiz|her yil|surdurul")
# formun doldurulmuş sonuçlarını gösteren işaret (yanıt sayısı, ortalama, yüzde, ondalık puan)
SONUC_VAR = re.compile(r"\d+\s*(?:yanit|katilimci|kisi)|ortalama|%|(?<![\d.,])\d[.,]\d(?![\d.,])")
KALKMA = re.compile(r"yururlukten (?:kalk|kaldir)|ilga edil")
GIRIS = re.compile(r"kullanici adi|parola|sifre")
MADDE = re.compile(r"(?m)^\s*(?:madde|gundem|karar)\s*(?:no\.?\s*)?\d+|^\s*\d+\s*[.)-]\s")
# başka birim adı geçişi: bilinen birim adı (kurum profili `birimler:` / config `birim_adlari`)
# + "Bölümü…" ya da "Bölüm Başkan…/Kurul…/Sekreter…" (aynı satırda, katlanmış sözcük dizisi).
# Listede olmayan ad (kişi soyadı "Ad SOYAD Bölüm Başkanı", "Birinci Bölüm", menü öğeleri)
# hiçbir zaman başka birim sayılmaz: serbest büyük harfli sözcük kalıbı yok.
_SOZ = re.compile(r"[^\W\d_]+")
_BOLUM_ROL = ("baskan", "kurul", "sekreter")


def unit_names(adlar) -> tuple[tuple[str, ...], ...]:
    """Birim adları → katlanmış sözcük dizileri ("Fizik Bölümü" → ("fizik",)), uzundan kısaya."""
    out = {tuple(_SOZ.findall(_stem(a))) for a in adlar or ()}
    return tuple(sorted((x for x in out if x), key=lambda x: (-len(x), x)))


def other_units(raw: str, names, own: str = "") -> set[str]:
    """Metinde geçen bilinen başka birim adları (katlanmış kök, ör. "fizik"). `names`:
    `unit_names` çıktısı; `own`: birimin kendi kökü (`_stem`) hariç tutulur."""
    found: set[str] = set()
    if not names:
        return found
    own_t = tuple(_SOZ.findall(own))
    for line in raw.splitlines():
        w = [fold(x) for x in _SOZ.findall(line)]
        for i, x in enumerate(w):
            if not (x.startswith("bolumu") or (x == "bolum" and i + 1 < len(w) and w[i + 1].startswith(_BOLUM_ROL))):
                continue
            for n in names:
                if i >= len(n) and tuple(w[i - len(n):i]) == n:
                    if n != own_t:
                        found.add(" ".join(n))
                    break
    return found


# sayfa altlığı / adres satırındaki kurum adı ("© … Rektörlüğü, 41400 …"): belge kurum geneli değildir
ADRES = re.compile(r"(?:©|\(c\)|copyright)[^|]{0,80}?rektorlug\w*|rektorlug\w*\s*,?\s*(?:p\.?\s?k\b|\d{5})")
# ders kodu: 2-5 büyük harf önek + 3 hane ("MATH407", "MAT 113"); 4 haneli sayı (yıl, proje no) değil
DERS_KODU = re.compile(r"(?<![A-Za-zÇĞİÖŞÜçğıöşü0-9-])([A-ZÇĞİÖŞÜ]{2,5})[ \t]?(\d{3})(?![\d])")
# hitap: "X Bölüm(ü) Başkanlığına" (katlanmış; "Başkanlığı' na" OCR'ı dahil). Kök tek sözcük.
HITAP = re.compile(r"\b([a-z]+)\s+bolum\w*\s+baskanlig\w*\W{0,3}n?[ae]\b")
HITAP_SATIR = 12               # baş bölge (satır): hitap burada aranır
BAS_ODAK = 600                 # baş bölge (karakter): ders kodu / program adı
# "Birim Bölümü:" kaydının altındaki satır başka bir kaydın etiketi değilse içeriktir
BLOK_ETIKET = re.compile(r"^[a-z ]+\s+bolum\w*\s*:$|^(?:dekanlik|rektorluk)\w*\s*:$")
# fakülte başlığı (fakülteye göre maddeli düzenleme): büyük harfli satırda "… FAKÜLTESİ"
_BUYUK = re.compile(r"[A-ZÇĞİÖŞÜ]")
_HARF = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüâîû]")


# görselli belge: gömülü görsel işareti (docx/pdf çıkarımı) ya da bidr describe betimlemesi
GORSEL = re.compile(r"\[gömülü görsel|GÖRSEL BETİMLEME|Betimleme\s*:")
# Fotoğrafın sahnesi (kullanıcı kararı 2026-11-20): etkinlik/seminer/toplantı/tören fotoğrafı
# gerçekleşmeyi (uygula) kanıtlar; mekân/altyapı/ekipman fotoğrafı tek başına süreç uygulaması
# değildir. Önce `bidr describe` bloğunun alanları (Görsel türü, Etkinlik, Kalabalık), yoksa sahne/
# betimleme/altyazı sözcükleri (katlanmış). "Toplantı salonu" gibi mekân adları etkinlik sayılmaz.
BETIMLEME_BLOK = re.compile(r"\[Betimleme · [^\]\n]*\]\n(.*?)(?=\n\s*\n|\n\[|\f|\Z)", re.S)
MEKAN_ADI = re.compile(r"\b(?:toplanti|seminer|konferans|sunum|etkinlik|tore\w*)\s+(?:salon|oda|alan|merkez)\w*")
SAHNE_ETKINLIK = re.compile(r"\b(?:seminer|konferans|konusma|konusmaci|katilimci|sunum|sunan|tore\w*|toplanti"
                            r"|panel|soylesi|calistay|egitim programi|dinleyici|mezuniyet|kutlama|yarisma"
                            r"|ogrenciler|ziyaret|gezi|etkinlik)\w*")
SAHNE_MEKAN = re.compile(r"\b(?:(?:derslik|amfi|anfi|laboratuvar|koridor|bina|tuvalet|kantin|kutuphane"
                         r"|alan|salon|ofis|asansor|rampa|otopark|bahce|cihaz|ekipman|makine|donanim"
                         r"|bilgisayar|tabela|mekan|dinlenme|atolye|depo|sinif)\w*|lab|giris(?:i|leri)?|oda(?:si|lari)?)\b")
DUYURU_SOZ = re.compile(r"duyuru|afis|tanitim|kapak|davet")
ALTYAZI_SOZCUK = 8
# yüklem (cümle) sonu: -dır/-tır, -mış, -yor, -acak/-ecek (katlanmış). "-di/-ti" iyelik ekiyle
# karışır ("Tuvaleti"): yüklem sayılmaz.
YUKLEM = re.compile(r"(?:[dt][iu]r(?:lar|ler)?|m[iu]s(?:tir)?|yor|[ae]c[ae]k)$")


def altyazi(q: str, text: str) -> bool:
    """Alıntı bir fotoğraf altyazısı mı: en çok ALTYAZI_SOZCUK sözcük, yüklemle/noktayla bitmiyor ve
    metinde kendi satırı (ya da en çok 10 sözcüklük bir satırın parçası)."""
    fq = f(q).strip(" .,;:")
    w = fq.split()
    if not w or len(w) > ALTYAZI_SOZCUK or q.strip().endswith(".") or YUKLEM.search(w[-1]):
        return False
    return any(fq == x or (fq in x and len(x.split()) <= 10) for x in (f(y) for y in text.splitlines() if y.strip()))


def sahne_sozcuk(text: str, kisi_yok: bool = False) -> str:
    """Katlanmamış sahne/betimleme/altyazı metninden sahne türü: etkinlik | mekan | belirsiz."""
    t = MEKAN_ADI.sub(" mekan ", f(text))
    if not kisi_yok and SAHNE_ETKINLIK.search(t):
        return "etkinlik"
    return "mekan" if SAHNE_MEKAN.search(t) else "belirsiz"


def sahne_blok(blok: str) -> str:
    """`bidr describe` betimleme bloğundan sahne türü. Yalnız fotoğraf sınıflanır; afiş, ekran, şema,
    diğer → belirsiz (afişteki etkinlik duyurudur). Etkinlik alanı dolu (yok/duyuru değil) → etkinlik."""
    alan = {}
    for x in blok.splitlines():
        k, _, v = x.partition(":")
        alan.setdefault(f(k), v.strip())
    if f(alan.get("gorsel turu")) not in ("fotograf", ""):
        return "belirsiz"
    etk = f(alan.get("etkinlik"))
    yok = not etk or etk.startswith(("yok", "etkinlik yok"))
    if not yok and not DUYURU_SOZ.search(etk):
        return "etkinlik"
    return sahne_sozcuk(" ".join((alan.get("sahne", ""), alan.get("betimleme", ""), "" if yok else etk)),
                        kisi_yok=yok or f(alan.get("kalabalik")).startswith("kisi yok"))


def sahne(q: str, text: str) -> str:
    """Fotoğraf alıntısının sahnesi: alıntıyı içeren betimleme bloğu, yoksa belgenin bütün blokları
    (hepsi aynı türdeyse), blok yoksa alıntının (altyazının) kendisi."""
    bloklar = [m.group(1) for m in BETIMLEME_BLOK.finditer(text)]
    if not bloklar:
        return sahne_sozcuk(q)
    fq = f(q)
    ilgili = [b for b in bloklar if fq and fq in f(b)] or bloklar
    turler = {sahne_blok(b) for b in ilgili}
    return turler.pop() if len(turler) == 1 else "belirsiz"


def f(s: str | None) -> str:
    """Katlanmış, boşlukları sıkıştırılmış metin."""
    return " ".join(fold(s or "").split())


def _stem(birim: str) -> str:
    s = f(birim)
    s = re.sub(r"\s*\bbolum\w*$", "", s).strip()
    return s


def birim_pattern(birim: str) -> re.Pattern | None:
    """Birimin adının katlanmış metindeki geçişi ("Örnek Bölümü" → `ornek bolum…`; ek alır)."""
    s = _stem(birim)
    if not s:
        return None
    tail = r"\s*bolum" if re.search(r"\bbolum\w*$", f(birim)) else r"\b"
    return re.compile(r"\b" + re.escape(s).replace(r"\ ", r"\s+") + tail)


def own_patterns(birim: str) -> list[tuple[str, re.Pattern]]:
    """Birim adı "Bölüm" sözcüğü olmadan da birimi gösterdiği açık bağlamlar (katlanmış metin):
    program adı ("Programı: Örnek", "Örnek lisans programı") ve web sayfası yolu ("Bölümler › Örnek").
    "Örnek Mühendisliği/Eğitimi/Öğretmenliği" başka programdır, sayılmaz."""
    s = _stem(birim)
    if not s:
        return []
    n = re.escape(s).replace(r"\ ", r"\s+")
    dur = r"\b(?!\s+(?:muhendisligi|egitimi|ogretmenligi)\b)"
    return [("program adı", re.compile(rf"\bprogram\w*\s*:?\s+{n}{dur}|\b{n}\s+(?:(?:lisans|yuksek lisans|doktora"
                                      rf"|lisansustu)\s+)?program")),
            ("bölüm sayfası yolu", re.compile(rf"\bbolumler\W+(?:\d+\W+)*{n}{dur}"
                                               rf"|\bakademik programlar\W+(?:(?:on lisans|lisans|yuksek lisans"
                                               rf"|doktora)\W+)*{n}{dur}"))]


@dataclass
class Savunma:
    ws_root: Path
    birim: str = ""                                   # config.yaml `bidr.birim`
    fakulte: str = ""                                 # birimin fakültesi (config / kurum profili)
    ders_kodlari: tuple = ()                          # birimin ders kodu önekleri (config / kurum profili)
    birim_adlari: tuple = ()                          # bilinen birim adları (unit_names; başka birim tanısı)
    donem: int | None = None
    docs: dict = field(default_factory=dict)
    haric: frozenset = frozenset()
    faaliyet: dict | None = None                     # faaliyetler.json (yoksa None)
    faaliyet_sha: str = ""
    _text: dict = field(default_factory=dict)
    _sig: dict = field(default_factory=dict)
    _fak: dict = field(default_factory=dict)
    kaldirilan: dict = field(default_factory=dict)   # doc_id → kaldıran belgenin adı
    fmap: dict = field(default_factory=dict)         # doc_id → (faaliyet kaydı, belgenin aşaması)

    @classmethod
    def load(cls, ws_root: Path, docs: dict, donem: int | None) -> "Savunma":
        from bidr.criteria.profiles import excluded_types
        from bidr.init.config import load_section
        from .run import file_sha
        from bidr.decide.prompt import unit_profile
        birim = str((load_section(ws_root) or {}).get("birim") or "").strip()
        up = unit_profile(ws_root) if birim else {}
        sv = cls(Path(ws_root), birim, up.get("fakulte") or "", tuple(up.get("ders_kodlari") or ()),
                 unit_names(up.get("birim_adlari")), donem, docs, excluded_types())
        fp = Path(ws_root) / FAALIYET
        if fp.exists():
            try:
                sv.faaliyet = json.loads(fp.read_text(encoding="utf-8"))
                sv.faaliyet_sha = file_sha(fp)
            except (OSError, ValueError):
                sv.faaliyet = None
        for k in (sv.faaliyet or {}).get("faaliyetler") or []:
            for b in k.get("belgeler") or []:
                sv.fmap.setdefault(b.get("doc_id"), (k, b.get("asama")))
        sv.kaldirilan = sv._superseded()
        return sv

    # -- metin ------------------------------------------------------------------------------
    def text(self, did: str) -> str:
        if did not in self._text:
            p = self.ws_root / "text" / f"{did}.txt"
            try:
                self._text[did] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                self._text[did] = ""
        return self._text[did]

    def sig(self, did: str) -> dict:
        """Belge düzeyi işaretler (önbellekli)."""
        if did in self._sig:
            return self._sig[did]
        raw = self.text(did)
        t = f(raw)
        stem = _stem(self.birim) if self.birim else ""
        bp = birim_pattern(self.birim) if self.birim else None
        birim_var = bool(bp and bp.search(t))
        others = other_units(raw, self.birim_adlari, stem) if stem else set()
        lines = [x.strip() for x in raw.splitlines() if x.strip()]
        madde = [x for x in lines if re.match(r"^([-*•]|\w[\w.-]*\.(example|com|org|edu|tr)\b|https?://)", x)]
        kisa = [x for x in madde if len(x.split()) <= 7]
        nesir = [x for x in lines if x not in madde and not x.startswith("#") and len(x.split()) >= 8]
        ekran = (self.docs.get(did) or {}).get("doc_type") in EKRAN_TURLER
        giris = ekran and bool(GIRIS.search(t)) and "giris" in t and len(t) < 800
        own = []
        if birim_var:
            own.append("birim adı")
        for ad, pat in own_patterns(self.birim) if self.birim else []:
            if pat.search(t):
                own.append(ad)
        kod = self._course_codes(raw)
        if kod:
            own.append(f"ders kodu ({kod})")
        s = {"birim_var": birim_var, "own": own, "baska": sorted(others),
             "bilgisiz": giris or (ekran and len(kisa) >= 3 and len(kisa) == len(madde) and not nesir),
             "kurum": bool(KURUM_BELGE.search(ADRES.sub(" ", t))), "fakulte": bool(FAKULTE_BELGE.search(t)),
             "bas": f(raw[:300])}
        self._sig[did] = s
        return s

    def _course_codes(self, raw: str) -> str:
        """Birimin ders kodu önekiyle yazılmış kodlar metindeki ders kodlarının en az yarısıysa
        örnek kod (ör. "MATH407"), değilse "" (başka bölümün müfredatında birimin servis dersi
        geçmesi birim sinyali değildir)."""
        if not self.ders_kodlari:
            return ""
        own = {fold(x).upper() for x in self.ders_kodlari}
        hits = [(fold(m.group(1)).upper(), m.group(0)) for m in DERS_KODU.finditer(raw)]
        mine = [h for p_, h in hits if p_ in own]
        return " ".join(mine[0].split()) if mine and 2 * len(mine) >= len(hits) else ""

    # -- belge düzeyi: birim ilişkisi ----------------------------------------------------------
    def unit_relation(self, rec: dict, rel: str) -> tuple[str, str] | None:
        """(yeni ilişki, gerekçe) ya da None. Yalnız birim adı biliniyorsa; insan birim kararı
        varsa çağrılmaz. Metinde birimin açık sinyali (birim adı, program adı, bölüm sayfası
        yolu, birimin ders kodları) varsa model `kendi` / üst birim dediğinde düşürülmez; model
        `belirsiz` dediyse ve başka birim adı ya da bütün birimleri kapsayan ifade yoksa `kendi`
        önerilir (satır işaretli; insan/ajan incelemede reddedebilir)."""
        if not self.birim:
            return None
        s = self.sig(rec["doc_id"])
        if rel in ("kurum_geneli", "fakulte_geneli"):
            odak = self.unit_focus(rec["doc_id"])
            if not odak:
                return None
            rel2 = "ust_birim_bu_birim_hakkinda" if s["kurum"] or s["fakulte"] else "kendi"
            return rel2, "kod: bütün birimleri kapsamıyor, birime özgü (" + ", ".join(odak) + ")"
        if rel == "belirsiz":
            if s["own"] and not s["baska"] and not (s["kurum"] or s["fakulte"]):
                return ("kendi", "kod: metinde birim sinyali (" + ", ".join(s["own"]) + "), başka birim adı yok")
            return None
        if rel not in ("kendi", "ust_birim_bu_birim_hakkinda"):
            return None
        if s["own"]:
            return None
        if s["baska"]:
            return ("belirsiz", "kod: metinde birimin adı yok, başka birim adı var ("
                    + ", ".join(s["baska"][:3]) + ")")
        if s["kurum"] or s["fakulte"]:
            rel2 = "fakulte_geneli" if s["fakulte"] and not s["kurum"] else "kurum_geneli"
            return rel2, "kod: metinde birimin adı yok; bütün birimleri kapsayan belge"
        return None

    # -- birime özgü odak (kurum/fakülte geneli dendiğinde) -------------------------------------
    def _hitap(self, raw: str) -> tuple[set[str], bool]:
        """(belgede "X Bölüm(ü) Başkanlığına" hitabı geçen birim kökleri, birimin hitabı baş
        bölgede mi). Dağıtım listesinde bütün bölümler geçer: birden çok kök = hitap değil."""
        roots, head = set(), False
        stem = _stem(self.birim)
        for line in raw.splitlines():
            for m in HITAP.finditer(f(line)):
                roots.add(m.group(1))
        lines = [x for x in raw.splitlines() if x.strip()][:HITAP_SATIR]
        if stem and any(re.search(rf"\b{re.escape(stem)}\s+bolum\w*\s+baskanlig", f(x)) for x in lines):
            head = True
        return roots, head

    def unit_focus(self, did: str) -> list[str]:
        """Bütün birimleri kapsayan görünen belgede birime özgü odak: belge yalnız birime hitap
        ediyor (baş bölgede "Birim Başkanlığına", başka bölüme hitap yok), birimin adı bir kaydın
        başlığı ("Birim Bölümü:" satırı ve altında içerik: üst birim yazısında birime ait kayıt;
        madde ilkesi) ya da baş bölgede birimin ders kodu/program adı (birimin ders/program
        belgesi). Boşsa odak yok."""
        if not self.birim:
            return []
        raw = self.text(did)
        stem = _stem(self.birim)
        out = []
        roots, head = self._hitap(raw)
        if head and len(roots) == 1:
            out.append("hitap birime")
        lines = [x for x in raw.splitlines() if x.strip()]
        lab = re.compile(rf"^{re.escape(stem)}\s+bolum\w*\s*:$")
        for i, x in enumerate(lines[:-1]):
            if lab.match(f(x)) and not BLOK_ETIKET.match(f(lines[i + 1])):
                out.append("birimin kaydı (\"" + x.strip() + "\")")
                break
        bas = raw[:BAS_ODAK]
        kod = self._course_codes(bas)
        if kod:
            out.append(f"baş bölgede ders kodu ({kod})")
        fb = f(bas)
        for ad, pat in own_patterns(self.birim):
            if ad == "program adı" and pat.search(fb):
                out.append("baş bölgede program adı")
        return out

    def unit_page(self, did: str, q: str) -> str:
        """Birleşik (çok sayfalı) belgede alıntının sayfası birimin kendi belgesi mi: o sayfada
        birim sinyali (ders kodu, program adı, birim adı) var; madde yapısı (düzenleme), bütün
        birimleri kapsayan ifade ve başka birim adı yok. Gerekçe ya da ""."""
        if not self.birim or not q:
            return ""
        pages = self.text(did).split("\f")
        if len([p for p in pages if p.strip()]) < 2:
            return ""
        key = f(q)[:60]
        page = next((p for p in pages if key and key in f(p)), None)
        if page is None:
            return ""
        t = f(page)
        if re.search(r"(?m)^\s*madde\s*\d", fold(page)):
            return ""                         # düzenleme sayfası (madde yapısı): kurum geneli kalır
        if KURUM_BELGE.search(ADRES.sub(" ", t)) or FAKULTE_BELGE.search(t) or GENEL_IFADE.search(t):
            return ""
        if other_units(page, self.birim_adlari, _stem(self.birim)):
            return ""
        sig = []
        kod = self._course_codes(page)
        if kod:
            sig.append(f"ders kodu ({kod})")
        for ad, pat in own_patterns(self.birim):
            if pat.search(t):
                sig.append(ad)
        bp = birim_pattern(self.birim)
        if bp and bp.search(t):
            sig.append("birim adı")
        return ", ".join(sig)

    def own_regulation(self, did: str) -> bool:
        """Bölümün kendi usul belgesi: başlığında birimin adı var, bütün birimleri kapsamıyor."""
        if not self.birim:
            return False
        s = self.sig(did)
        bp = birim_pattern(self.birim)
        return bool(bp and bp.search(s["bas"])) and not s["kurum"]

    # -- yürürlükten kaldırma ------------------------------------------------------------------
    def _superseded(self) -> dict[str, str]:
        from bidr.identify.dates import find_dates
        by_date: dict[str, list[str]] = {}
        for did, d in self.docs.items():
            t = str(d.get("tarih") or "")[:10]
            if len(t) == 10:
                by_date.setdefault(t, []).append(did)
        out: dict[str, str] = {}
        for did, d in self.docs.items():
            own = str(d.get("tarih") or "")[:10]
            if self.donem and own[:4].isdigit() and int(own[:4]) > self.donem:
                continue                  # dönemden sonra kaldırılan dönemde yürürlükteydi
            t = fold(self.text(did))
            for sent in re.split(r"(?<=[.;])\s+|\n\s*\n", t):
                if not KALKMA.search(sent):
                    continue
                for fd in find_dates(" ".join(sent.split())):
                    iso = fd.d.isoformat()
                    if own and iso >= own:
                        continue
                    for other in by_date.get(iso, []):
                        if other != did:
                            out.setdefault(other, (self.docs[did].get("calisma_adi") or did))
        return out

    # -- satır düzeyi ------------------------------------------------------------------------
    def _ayni_olcutte_gerceklesme(self, k: dict, olcut: str | None) -> bool:
        """Faaliyetin gerçekleşme belgesi (gerçekleşme/katılım aşaması) AYNI ölçütte kabul edilmiş mi: kod
        denetiminden geçmiş eşleşme ve incelemede reddedilmemiş. Başka ölçütteki fotoğraf afişi kendi ölçütünde
        uygulama yapmaz (OD şişmesin; şef kararı 2026-11-24)."""
        if getattr(self, "_ret", None) is None:
            self._ret = set()
            p = Path(self.ws_root) / "review-decisions.jsonl"
            if p.exists():
                for x in p.read_text(encoding="utf-8").splitlines():
                    try:
                        r = json.loads(x)
                    except ValueError:
                        continue
                    if r.get("karar") == "ret":
                        self._ret.add(r.get("satir") or f"{r.get('doc_id')}|{r.get('yuva')}")
        for b in k.get("belgeler") or []:
            if b.get("asama") not in ("gerceklesme", "katilim"):
                continue
            for e in b.get("eslesmeler") or []:
                if e.get("olcut") == olcut and f"{b.get('doc_id')}|{e.get('yuva')}" not in self._ret:
                    return True
        return False

    def _uygula_yuvasi(self, yuva: str | None) -> bool:
        """Yuvanın PUKÖ etiketi uygulamayı kabul ediyor mu (belirsiz etiket: içeriğe bağlı, kabul)."""
        if getattr(self, "_tags", None) is None:
            from bidr.criteria.loader import load_criteria
            from bidr.criteria.slots import load_tags
            self._tags = load_tags(load_criteria())
        t = self._tags.get(yuva or "")
        return t is not None and (t.uncertain or "uygula" in t.stages)

    def row(self, rec: dict, m: dict, dtype: str, etkin: str | None, human: bool) -> dict:
        """{"etkin", "sayilir" (None: değişmez), "flags", "vurgu", "rel"}."""
        did = rec["doc_id"]
        out = {"etkin": etkin, "sayilir": None, "flags": [], "vurgu": [], "rel": None}
        fl, vu = out["flags"], out["vurgu"]
        if dtype in self.haric:
            out["sayilir"] = False
            fl.append("haric_tur")
            vu.append("öz-referans tür (BİDR'nin kendisi/taslağı): kanıt değil")
        if did in self.kaldirilan:
            out["sayilir"] = False
            fl.append("yururlukten_kalkmis")
            vu.append(f"yürürlükten kaldırılmış (`{self.kaldirilan[did]}`)")
        if human or not etkin:
            return out
        s = self.sig(did)
        q = f(m.get("alinti"))
        if s["bilgisiz"]:
            out["sayilir"] = False
            fl.append("bilgisiz_ekran")
            vu.append("bilgi içermeyen ekran/bağlantı sayfası: kanıt değil")
        if self.fakulte:
            h = self.other_faculty(did, m.get("alinti") or "")
            if h:
                out["sayilir"] = False
                # madde_baska_birim: dosyalama (bidr/file/select.py KANIT_DEGIL) aynı kuralla dışlar
                fl += ["madde_baska_birim", "madde_baska_fakulte"]
                vu.append(f"alıntı başka fakültenin maddesinden (\"{h[:60]}\"): {self.fakulte} için kanıt değil")
        if self.birim and s["birim_var"]:
            blk = self._block(did, q)
            if blk is not None:
                bs = f(blk)
                if not birim_pattern(self.birim).search(bs) and any(re.search(rf"\b{re.escape(w)} bolum", bs) for w in s["baska"]):
                    out["sayilir"] = False
                    fl.append("madde_baska_birim")
                    vu.append("alıntı başka birimi konu alan maddeden (madde ilkesi)")
        e = etkin

        def down(to: str, flag: str, why: str):
            nonlocal e
            if ORDER[to] < ORDER[e]:
                e = to
                fl.append(flag)
                vu.append(why)

        if dtype in FORM_TURLER and e != "planla" and not SONUC_VAR.search(f(self.text(did))):
            down("planla", "bos_form", "boş form/şablon: uygulama değil, mekanizma tanımı (planla)")
        fa = self.fmap.get(did)
        # Etkinlik dosyası (kanıt ilkesi `etkinlik_dosyasi`): bölümün etkinliğinin afişi/duyurusu planlama
        # kanıtıdır; aynı faaliyet kaydında gerçekleşme belgesi (fotoğraf, haber, tutanak) varsa uygulama.
        gerceklesti = bool(fa) and fa[0].get("durum") == "gerceklesme_kanitli" and fa[1] in ("duyuru", "plan")
        if dtype in DUYURU_TURLER and e != "planla" and not gerceklesti:
            down("planla", "gerceklesme_kaniti_yok", "duyuru: gerçekleşmenin kanıtı değil (planla)")
        if e != "planla" and GELECEK.search(q) and not gerceklesti:
            down("planla", "gerceklesme_kaniti_yok", "gelecek zamanlı ifade: gerçekleşme kanıtı değil (planla)")
        if fa:
            k, asama = fa
            from bidr.faaliyet.group import PUKO
            h = PUKO.get(asama)
            if (k.get("yalniz_duyuru") or k.get("durum") == "gerceklesme_kanitsiz") and e != "planla":
                down("planla", "gerceklesme_kaniti_yok", f"faaliyetin ({k.get('id')}) gerçekleşme kaydı yok")
            if h and ORDER.get(h, 0) < ORDER[e] and not gerceklesti:
                down(h, "faaliyet_asamasi_uyusmuyor", f"faaliyet kaydında aşama '{asama}' ({k.get('id')})")
            if k.get("durum") == "gerceklesme_dolayli" and e == "uygula":
                vu.append(f"gerçekleşme belgesi önerilir ({k.get('id')}: yalnız katılım/değerlendirme kaydı)")
            if gerceklesti and e == "planla" and self._uygula_yuvasi(m.get("yuva")) \
                    and self._ayni_olcutte_gerceklesme(k, m.get("olcut")):
                e = "uygula"
                fl.append("etkinlik_gerceklesti")
                vu.append(f"etkinlik dosyasında gerçekleşme belgesi var ({k.get('id')} {k.get('ad') or ''}): "
                          "duyuru uygulama sayıldı")
        if e != "planla" and GENEL_IFADE.search(q):
            down("planla", "uygulama_kaniti_eksik", "alıntı bütün birimleri kapsıyor (kurum/fakülte geneli)")
            fl.append("kurum_geneli")
        if e == "kontrol_et" and ETKINLIK.search(q) and not IZLEME.search(q):
            down("uygula", "katilim_izleme_degil", "katılım/yapılma kaydı izleme sonucu değil (uygula)")
        if e == "onlem_al":
            if NIYET.search(q) or GELECEK.search(q):
                down("kontrol_et", "niyet_onlem_degil", "öneri/niyet: yapılmış iyileştirme değil")
            elif BILGI.search(q):
                down("uygula", "bilgilendirme_onlem_degil", "kurula bilgi verilmesi iyileştirme değil")
            elif SURUM.search(q) and not IZLEME.search(q):
                down("uygula", "surum_notu_onlem_degil", "sürüm notu (revize): izlemeye dayanan iyileştirme değil")
            elif yonlendirme(q):
                down("kontrol_et" if IZLEME.search(q) else "uygula", "yonlendirme_onlem_degil",
                     "talebin/geri bildirimin bir makama iletilmesi (yönlendirme, talep): yapılmış iyileştirme değil")
        out["etkin"] = e
        return out

    # -- fakülte maddesi -----------------------------------------------------------------------
    def _sections(self, did: str) -> tuple[str, list[tuple[int, str]]]:
        """(katlanmış birleşik metin, [(başlangıç, başlık)]): büyük harfli başlık satırları (ardışık
        satırlar tek başlık; sayfa üst bilgisi gibi tekrarlanan satırlar başlık değil)."""
        if did in self._fak:
            return self._fak[did]
        lines = self.text(did).splitlines()
        from collections import Counter
        rep_ = Counter(f(x) for x in lines if x.strip())
        parts, heads, pos, prev = [], [], 0, False
        for x in lines:
            fx = f(x)
            if not fx:
                prev = False
                continue
            harf = _HARF.findall(x)
            h = (len(harf) >= 6 and len(_BUYUK.findall(x)) >= 0.85 * len(harf) and rep_[fx] == 1
                 and not fx.startswith("madde"))
            if h and prev and heads:
                heads[-1] = (heads[-1][0], heads[-1][1] + " " + fx)
            elif h:
                heads.append((pos, fx))
            prev = h
            parts.append(fx)
            pos += len(fx) + 1
        self._fak[did] = (" ".join(parts), heads)
        return self._fak[did]

    def other_faculty(self, did: str, q: str) -> str | None:
        """Alıntı fakülteye göre maddeli bir düzenlemede yalnız başka fakültenin bölümünde geçiyorsa
        o bölümün başlığı, değilse None. Belge parçası başlığı içermiyorsa aynı tarih ve türdeki
        belgelerde (aynı düzenlemenin tam metni) aranır. Birimin fakültesi bilinmiyorsa None."""
        own = f(self.fakulte)
        key = f(q)[:80]
        if not own or len(key) < 20:
            return None
        doc = self.docs.get(did) or {}
        tarih, tur = str(doc.get("tarih") or "")[:10], doc.get("doc_type")
        cands = [did] + ([o for o, d in self.docs.items() if o != did and tarih and d.get("doc_type") == tur
                          and str(d.get("tarih") or "")[:10] == tarih] if tarih else [])
        for c in cands[:30]:
            text, heads = self._sections(c)
            fh = [h for _, h in heads if "fakultesi" in h]
            if len({h for h in fh}) < 2 or key not in text:
                continue
            others = []
            for m in re.finditer(re.escape(key), text):
                h = next((h for p_, h in reversed(heads) if p_ <= m.start()), "")
                if "fakultesi" not in h or own in h:
                    return None                       # birimin fakültesinin ya da ortak bölüm
                others.append(h)
            return others[0]
        return None

    def _block(self, did: str, q: str) -> str | None:
        """Alıntının bulunduğu madde/gündem bloğu (madde yapısı yoksa None)."""
        raw = self.text(did)
        cuts = [m.start() for m in MADDE.finditer(fold(raw))]
        if len(cuts) < 2 or not q:
            return None
        cuts = [0, *cuts, len(raw)]
        for a, b in zip(cuts, cuts[1:]):
            if q[:60] in f(raw[a:b]):
                return raw[a:b]
        return None

    # -- ölçüt düzeyi ---------------------------------------------------------------------------
    def criterion(self, rows: list[dict], has: set[str]) -> dict:
        """Satırları yerinde günceller; ölçüt özeti alanlarını döndürür."""
        notlar: list[str] = []
        live = [r for r in rows if r.get("karar") not in ("kabul", "duzelt", "ret")]

        def drop(r, flag, why, to=None):
            r["flags"].append(flag)
            if to:
                r["etkin_asama"] = to
                from bidr.criteria.slots import STAGE_OD
                r["od"] = STAGE_OD.get(to)
            else:
                r["sayilir"] = False
            r["vurgu"] = "; ".join(x for x in (r["vurgu"], why) if x)

        # fotoğrafın kanıt değeri sahnesine bağlıdır (kullanıcı kararı 2026-11-20). Ölçütün uygulaması
        # yalnız fotoğrafa dayanıyorsa: etkinlik/seminer/toplantı/tören sahnesi gerçekleşmeyi kanıtlar
        # (sayılır); mekân/altyapı/ekipman sahnesi süreç uygulaması değildir, planla olarak kalır
        # (`fotograf_mekan`); sahnesi belirsiz fotoğraf destekleyicidir, sayılmaz
        # (`fotograf_destekleyici`). Fotoğraf: tür `fotograf` ya da görselli belgede alıntının bir
        # fotoğraf altyazısı olması. İnceleme `kabul`ü eşleşmeyi onaylar, fotoğrafı uygulama kanıtına
        # çevirmez; yalnız insanın aşamayı yerleştirdiği `duzelt` aşar.
        u = [r for r in rows if r["sayilir"] and r["etkin_asama"] == "uygula" and not r["zayif"]]
        if u and all(self.photo_row(r) for r in u):
            for r in u:
                if r.get("karar") == "duzelt":
                    continue
                sh = sahne(r.get("alinti") or "", self.text(r["doc_id"]))
                if sh == "mekan":
                    drop(r, "fotograf_mekan", "mekân/altyapı fotoğrafı süreç uygulaması kanıtlamaz: planla",
                         to="planla")
                elif sh != "etkinlik":
                    drop(r, "fotograf_destekleyici", "fotoğraf destekleyici kanıttır: tek başına uygulama sayılmaz")
            if any("fotograf_mekan" in r["flags"] for r in u):
                notlar.append("uygulama kanıtı yalnız mekân/altyapı fotoğrafı: planla sayıldı, OD3 için "
                              "uygulama belgesi ya da etkinlik fotoğrafı gerekir")
            if any("fotograf_destekleyici" in r["flags"] for r in u):
                notlar.append("uygulama kanıtı yalnız fotoğraf: destekleyici sayıldı, OD3 için belge gerekir")
        # K→Ö bağı: iyileştirme bir izleme sonucuna dayanmalı
        ks = [r for r in rows if r["etkin_asama"] == "kontrol_et"
              and (r["sayilir"] or {"gecmis_kanit", "dongu_halkasi"} & set(r["flags"]))]
        kapali, ayri = 0, 0
        for r in live:
            if r["etkin_asama"] != "onlem_al" or not r["sayilir"]:
                continue
            fa = self.fmap.get(r["doc_id"])
            fids = {self.fmap[k["doc_id"]][0].get("id") for k in ks if k["doc_id"] in self.fmap}
            ayni_f = bool(fa) and ("degerlendirme" in (fa[0].get("asamalar") or {}) or fa[0].get("id") in fids)
            if any(k["doc_id"] == r["doc_id"] for k in ks) or ayni_f:
                kapali += 1
                continue
            once = [k for k in ks if not k["tarih"] or not r["tarih"] or str(k["tarih"]) <= str(r["tarih"])]
            bag = BAG.search(f(" ".join((r["alinti"], r["gerekce"], self.text(r["doc_id"])))))
            if bag and (once or "kontrol_et" not in has):
                ayri += 1
                continue
            drop(r, "onlem_izlemeye_dayanmiyor",
                 "iyileştirme bir izleme sonucuna dayanmıyor (önceki izleme kanıtı ya da metinde bağ yok): uygula",
                 to="uygula")
        if kapali:
            notlar.append("kapalı döngü: izleme ve iyileştirme aynı belgede/faaliyette")
        if ayri:
            notlar.append(f"{ayri} iyileştirme izlemeden ayrı belgede: dayandığı sonuç metinde anılıyor, doğrulanmalı")
        if any("onlem_izlemeye_dayanmiyor" in r["flags"] for r in rows):
            notlar.append("izleme sonucuna dayanmayan değişiklik iyileştirme (Ö) sayılmadı")
        # özgün: bağımsız kanıt (üst birim/dış tanınma) ve birden çok dönem
        sure = any({"gecmis_kanit", "dongu_halkasi"} & set(r["flags"]) for r in rows)
        for r in live:
            if r["etkin_asama"] != "ozgun" or not r["sayilir"]:
                continue
            t = f(" ".join((r["alinti"], self.text(r["doc_id"]))))
            bagimsiz = (r["birim_iliskisi"] == "ust_birim_bu_birim_hakkinda"
                        or (r["belge_turu"] not in OZ_BEYAN_TURLER and bool(DIS_TANINMA.search(f(r["alinti"])))))
            surekli = sure or bool(SUREKLILIK.search(t))
            if not (bagimsiz and surekli):
                eks = [x for x, ok in (("bağımsız kanıt/dış tanınma", bagimsiz), ("birden çok dönem", surekli)) if not ok]
                drop(r, "ozgun_kanitsiz", "özgünlük kanıtı yetersiz (" + ", ".join(eks) + "): OD5 sayılmadı")
        if any("ozgun_kanitsiz" in r["flags"] for r in rows):
            notlar.append("OD5 için sürdürülebilir ve bağımsızca örnek gösterilen uygulama kanıtı gerekir "
                          "(öz beyan ya da tek dönem yetmez)")
        # OD3 yayılımı
        u = [r for r in rows if r["sayilir"] and r["etkin_asama"] == "uygula" and not r["zayif"]]
        ud = {r["doc_id"] for r in u}
        yayilim = None
        if u:
            yayilim = "yaygin" if len(ud) > 1 or any(r["belge_turu"] in YAYGIN_TURLER for r in u) else "kismi"
            if yayilim == "kismi":
                notlar.append(f"OD3 kısmi: tek uygulama örneği (`{u[0]['belge']}`); uygulamanın bölüm geneline "
                              "yayıldığını gösteren kanıt önerilir")
        for r in rows:
            r["isaretler"] = ", ".join(dict.fromkeys(r["flags"]))
        return {"notlar": notlar, "uygulama_yayilimi": yayilim,
                "dongu_kapali": kapali, "dongu_ayri": ayri}

    def photo_row(self, r: dict) -> bool:
        """Satırın uygulama dayanağı fotoğraf mı: tür `fotograf` (incelemede kabul edilmiş uzun metin
        alıntısı hariç), ya da görselli belgede (gömülü görsel / görsel betimleme) ya da betimlemeden
        alınmış alıntı bir fotoğraf altyazısı (kısa, yüklemsiz, metinde kendi satırı)."""
        if r.get("belge_turu") in FOTOGRAF_TURLER:
            # incelemede kabul edilmiş uzun metin alıntısı (afiş/katalog yazısı) fotoğraf değildir
            return r.get("karar") != "kabul" or len(f(r.get("alinti")).split()) <= ALTYAZI_SOZCUK
        t = self.text(r["doc_id"])
        if not (GORSEL.search(t) or r.get("alinti_kaynagi") == "betimleme"):
            return False
        return altyazi(r.get("alinti") or "", t)

    # -- faaliyet özetleri ----------------------------------------------------------------------
    def activities_for(self, rows: list[dict]) -> list[dict]:
        seen, out = set(), []
        for r in rows:
            fa = self.fmap.get(r["doc_id"])
            if fa and fa[0].get("id") not in seen:
                k = fa[0]
                seen.add(k.get("id"))
                out.append({"id": k.get("id"), "ad": k.get("ad"), "tarih": k.get("tarih"), "durum": k.get("durum"),
                            "yalniz_duyuru": bool(k.get("yalniz_duyuru")),
                            "asamalar": sorted(k.get("asamalar") or {}), "eksik": list(k.get("eksik") or [])})
        return out

    def unrealized(self) -> list[dict]:
        return [k for k in (self.faaliyet or {}).get("faaliyetler") or []
                if k.get("yalniz_duyuru") or k.get("durum") == "gerceklesme_kanitsiz"]
