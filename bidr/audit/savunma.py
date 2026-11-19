"""Kod tarafı savunmalar: modelin bilinen yanlışlarını ucuz, belirleyici denetimlerle yakalar.

Model yok. Girdi: belge türü (`documents.jsonl`), alıntı, model gerekçesi, belge metni
(`text/`), birim adı (`config.yaml` `bidr.birim`) ve varsa faaliyet kayıtları
(`faaliyetler.json`). Gerekçe ve örnekler: docs/AUDIT.md "Kod tarafı savunmalar" ve
"Faaliyet kayıtları". Her düşürme satırda işaretlenir; insan `kabul` ya da `duzelt` derse
metin sezgileri uygulanmaz (insan kararı kuralı aşar; tür ve birim kuralları gibi).

Satır düzeyi (`row`): hariç tür, bilgisiz ekran, yürürlükten kaldırılmış düzenleme, madde
ilkesi, boş form, duyuru/gelecek zaman, kurum geneli ifade, faaliyet aşaması, aşama
sözcük denetimleri (katılım ≠ izleme; niyet, bilgilendirme, sürüm notu ve yönlendirme/talep —
"Başkanlığa iletilmesine karar" — ≠ iyileştirme).
Belge düzeyi (`unit_relation`): metinde birimin adı hiç yokken başka birim adı geçen belge
`belirsiz`, bütün birimleri kapsayan belge kurum/fakülte geneli sayılır.
Ölçüt düzeyi (`criterion`): iyileştirme–izleme bağı (K→Ö), özgünlük (bağımsız kanıt ve
süreklilik), fotoğrafın tek başına uygulama sayılmaması, uygulamanın yayılımı (OD3 kısmi).
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
# birim adı geçişi (özgün yazımda büyük harfle başlayan ad + "Bölüm…")
BIRIM_ADI = re.compile(r"\b([A-ZÇĞİÖŞÜ][A-Za-zÇĞİÖŞÜçğıöşüâîû]+)\s+(?:Bölüm|BÖLÜM)")
_GENEL_SOZ = frozenset({"her", "ilgili", "bu", "ayni", "diger", "hangi", "bir", "tum", "butun", "ana", "alt",
                        "ilk", "son", "kendi", "ogrencinin", "gore", "fakulte", "universite", "egitim"})


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


@dataclass
class Savunma:
    ws_root: Path
    birim: str = ""                                   # config.yaml `bidr.birim`
    donem: int | None = None
    docs: dict = field(default_factory=dict)
    haric: frozenset = frozenset()
    faaliyet: dict | None = None                     # faaliyetler.json (yoksa None)
    faaliyet_sha: str = ""
    _text: dict = field(default_factory=dict)
    _sig: dict = field(default_factory=dict)
    kaldirilan: dict = field(default_factory=dict)   # doc_id → kaldıran belgenin adı
    fmap: dict = field(default_factory=dict)         # doc_id → (faaliyet kaydı, belgenin aşaması)

    @classmethod
    def load(cls, ws_root: Path, docs: dict, donem: int | None) -> "Savunma":
        from bidr.criteria.profiles import excluded_types
        from bidr.init.config import load_section
        from .run import file_sha
        birim = str((load_section(ws_root) or {}).get("birim") or "").strip()
        sv = cls(Path(ws_root), birim, donem, docs, excluded_types())
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
        others = set()
        if stem:
            last = stem.split()[-1]
            for m in BIRIM_ADI.finditer(raw):
                w = f(m.group(1))
                if w not in _GENEL_SOZ and w != last and w not in stem.split():
                    others.add(w)
        lines = [x.strip() for x in raw.splitlines() if x.strip()]
        madde = [x for x in lines if re.match(r"^([-*•]|\w[\w.-]*\.(example|com|org|edu|tr)\b|https?://)", x)]
        kisa = [x for x in madde if len(x.split()) <= 7]
        nesir = [x for x in lines if x not in madde and not x.startswith("#") and len(x.split()) >= 8]
        ekran = (self.docs.get(did) or {}).get("doc_type") in EKRAN_TURLER
        giris = ekran and bool(GIRIS.search(t)) and "giris" in t and len(t) < 800
        s = {"birim_var": birim_var, "baska": sorted(others),
             "bilgisiz": giris or (ekran and len(kisa) >= 3 and len(kisa) == len(madde) and not nesir),
             "kurum": bool(KURUM_BELGE.search(t)), "fakulte": bool(FAKULTE_BELGE.search(t)),
             "bas": f(raw[:300])}
        self._sig[did] = s
        return s

    # -- belge düzeyi: birim ilişkisi ----------------------------------------------------------
    def unit_relation(self, rec: dict, rel: str) -> tuple[str, str] | None:
        """(yeni ilişki, gerekçe) ya da None. Yalnız birim adı biliniyorsa ve model `kendi` /
        `ust_birim_bu_birim_hakkinda` dediyse; insan birim kararı varsa çağrılmaz."""
        if not self.birim or rel not in ("kendi", "ust_birim_bu_birim_hakkinda"):
            return None
        s = self.sig(rec["doc_id"])
        if s["birim_var"]:
            return None
        if s["baska"]:
            return ("belirsiz", "kod: metinde birimin adı yok, başka birim adı var ("
                    + ", ".join(s["baska"][:3]) + ")")
        if s["kurum"] or s["fakulte"]:
            rel2 = "fakulte_geneli" if s["fakulte"] and not s["kurum"] else "kurum_geneli"
            return rel2, "kod: metinde birimin adı yok; bütün birimleri kapsayan belge"
        return None

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
        if dtype in DUYURU_TURLER and e != "planla":
            down("planla", "gerceklesme_kaniti_yok", "duyuru: gerçekleşmenin kanıtı değil (planla)")
        if e != "planla" and GELECEK.search(q):
            down("planla", "gerceklesme_kaniti_yok", "gelecek zamanlı ifade: gerçekleşme kanıtı değil (planla)")
        fa = self.fmap.get(did)
        if fa:
            k, asama = fa
            from bidr.faaliyet.group import PUKO
            h = PUKO.get(asama)
            if (k.get("yalniz_duyuru") or k.get("durum") == "gerceklesme_kanitsiz") and e != "planla":
                down("planla", "gerceklesme_kaniti_yok", f"faaliyetin ({k.get('id')}) gerçekleşme kaydı yok")
            if h and ORDER.get(h, 0) < ORDER[e]:
                down(h, "faaliyet_asamasi_uyusmuyor", f"faaliyet kaydında aşama '{asama}' ({k.get('id')})")
            if k.get("durum") == "gerceklesme_dolayli" and e == "uygula":
                vu.append(f"gerçekleşme belgesi önerilir ({k.get('id')}: yalnız katılım/değerlendirme kaydı)")
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

        # fotoğraf tek başına uygulama değildir (destekleyici kanıt)
        u = [r for r in rows if r["sayilir"] and r["etkin_asama"] == "uygula" and not r["zayif"]]
        if u and all(r["belge_turu"] in FOTOGRAF_TURLER for r in u):
            for r in u:
                if r.get("karar") not in ("kabul", "duzelt"):
                    drop(r, "fotograf_destekleyici", "fotoğraf destekleyici kanıttır: tek başına uygulama sayılmaz")
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
