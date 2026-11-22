"""review.xlsx'in son kullanıcı (kalite komisyonu üyesi) için sade sayfaları.

Teknik sayfalar ("Eşleşmeler", "Ölçüt özeti", "Başka birime ait sayılanlar", "Açıklama") gizli olarak
dosyada kalır; `bidr audit apply` ikisini birlikte okur. Komisyon üyesi yalnız şu sayfaları görür:

- **İnceleme**: satır = bir öneri ("şu belge şu maddeye kanıt"). Düz Türkçe sütunlar ve tek karar
  sütunu (KARARINIZ: Kabul · Kabul — etkinlik yapıldı · Ret · Başka maddeye taşı · Başka maddeye
  taşı — etkinlik yapıldı). Üç bölüm: (1) bakılması gerekenler, (2) sorunsuz görünenler (bölüm
  başlığındaki "Hepsini kabul" boş satırları kabul eder), (3) daha önce karar verilenler.
- **Bölümünüze ait mi?**: birimi belirsiz ya da başka birime ait sayılan belgeler (Evet/Hayır…).
- **Maddeler**: önerilen olgunluk düzeyi ve komisyonun onayladığı düzey.
- **Nasıl doldurulur**.

Okuma (birleştirme) kuralı: her sade satır, yazıldığı andaki değerini gizli bir sütunda taşır
(`yazılan`). Sade hücre yazılandan farklıysa sade değer geçerlidir; değilse teknik sayfanın değeri
(teknik sayfayı doğrudan düzenleyen uzman/ajan yolu bozulmaz). Sade karar teknik karar biçimine
çevrilir (kabul/ret/duzelt + düzelt ölçüt/yuva/aşama); `parse_decision` değişmez.
"""
from __future__ import annotations

import json
import re

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

SH_INC, SH_BIRIM, SH_MADDE, SH_NASIL, SH_LISTE = (
    "İnceleme", "Bölümünüze ait mi", "Maddeler", "Nasıl doldurulur", "_liste")
SADE_SHEETS = (SH_INC, SH_BIRIM, SH_MADDE, SH_NASIL)

# KARARINIZ seçenekleri (açılır liste; virgül içeremez)
K_KABUL, K_ETK, K_RET, K_TASI, K_TASI_ETK = (
    "Kabul", "Kabul — etkinlik yapıldı", "Ret", "Başka maddeye taşı", "Başka maddeye taşı — etkinlik yapıldı")
KARAR_SECENEK = (K_KABUL, K_ETK, K_RET, K_TASI, K_TASI_ETK)
TOPLU = "Hepsini kabul"                         # 2. bölüm başlığındaki toplu kabul seçeneği
TOPLU_NOT = "toplu kabul (sade tablo, 2. bölüm)"
TOPLU_SATIR = "#toplu"                          # gizli kimlik sütununda bölüm başlığı işareti

# Bölümünüze ait mi? seçenekleri → birim ilişkisi
BIRIM_CEVAP = {
    "Evet — bölümümüzün belgesi": "kendi",
    "Hayır — başka birimin belgesi": "baska_birim",
    "Fakültenin geneli için": "fakulte_geneli",
    "Üniversitenin geneli için": "kurum_geneli",
    "Üst birimin bölümümüz hakkındaki kararı": "ust_birim_bu_birim_hakkinda",
    "Önceki cevabı kaldır": "model",
}
BIRIM_AD = {v: k for k, v in BIRIM_CEVAP.items()}

OD_AD = {1: "1 — Henüz yok", 2: "2 — Planlandı", 3: "3 — Uygulanıyor",
         4: "4 — İzlenip iyileştiriliyor", 5: "5 — Örnek gösterilebilir"}
ASAMA_KISA = {"planla": "plan/kural", "uygula": "uygulama (yapıldığı)", "kontrol_et": "izleme sonucu",
              "onlem_al": "iyileştirme", "ozgun": "özgün uygulama"}
ORDER = {"planla": 1, "uygula": 2, "kontrol_et": 3, "onlem_al": 4, "ozgun": 5}

# -- işaretlerin düz Türkçe karşılığı -------------------------------------------------------------
# (metin, bakılmalı mı). {yil}: rapor yılı, {byil}: belgenin yılı. Bakılmalı olmayanlar yalnız bilgi.
DIKKAT = {
    "birim_onay_bekliyor": ("Bu belgenin bölümünüze ait olduğundan emin değiliz; onaylanana dek kanıt "
                            "sayılmıyor. Bölümünüzün belgesiyse Kabul, değilse Ret seçin.", True),
    "birim_iliskisi_kod": ("Bölüme ait olduğu belgedeki bir ifadeden çıkarıldı. Doğruysa Kabul.", True),
    "tarih_dogrulanmali": ("Belgenin tarihi okunamadı. {yil} yılına aitse Kabul, değilse Ret seçin.", True),
    "guncellik_dogrulanmali": ("Bu kural/plan belgesinin tarihi {yil} değil ya da yok. {yil} yılında "
                               "yürürlükteyse Kabul, değilse Ret seçin.", True),
    "gecmis_kanit": ("Belge önceki bir yıla ait{byil}; bu yılın kanıtı sayılmadı. Olay {yil} yılında da "
                     "yapıldıysa ya da tarih yanlışsa Kabul, değilse Ret seçin.", True),
    "donem_sonrasi": ("Belge {yil} yılından sonraya ait; bu raporun kanıtı sayılmadı. Tarih yanlışsa Kabul, "
                      "değilse Ret seçin.", True),
    "surum_donem_sonrasi": ("Belgenin {yil} yılından sonraki bir sürümü; {yil} sürümü varsa o kullanılmalı. "
                            "Genelde Ret.", True),
    "sayfa_donem_sonrasi": ("Sayfa {yil} yılından sonra güncellenmiş, içinde {yil} tarihi yok. İçerik {yil} "
                            "yılını anlatıyorsa Kabul, değilse Ret.", True),
    "revizyon_donem_sonrasi": ("Belge {yil} yılından sonra yenilenmiş; mümkünse {yil} yılındaki sürümünü "
                               "ekleyin. Bu sürüm kullanılacaksa Kabul.", True),
    "surum_yururlukten_kalkmis": ("Belgenin daha yeni bir sürümü var (bu sürüm yürürlükte değil); kanıt "
                                  "sayılmadı. Genelde Ret.", True),
    "yururlukten_kalkmis": ("Belge başka bir belgeyle yürürlükten kaldırılmış; kanıt sayılmadı. Genelde Ret.", True),
    "surum_dogrulanmali": ("Aynı belgenin birden çok sürümü var; hangisinin {yil} yılında yürürlükte olduğu "
                           "anlaşılamadı. Bu sürüm yürürlükteyse Kabul, değilse Ret.", True),
    "surum_dogrulanmali_sayilmaz": ("Aynı belgenin tarihli başka bir sürümü var; bu tarihsiz sürüm sayılmadı. "
                                    "Bu sürüm {yil} yılında yürürlükteyse Kabul, değilse Ret.", True),
    "kurum_geneli": ("Üniversitenin ya da fakültenin geneli için bir düzenleme: yalnız \"kural var\" "
                     "(planlama) kanıtı sayılır. Fakültenizi/bölümünüzü kapsıyorsa Kabul, başka bir "
                     "birimin maddesiyse Ret.", True),
    "gerceklesme_kaniti_yok": ("Yalnız duyuru ya da plan görünüyor; etkinliğin yapıldığı belgede yok. Etkinlik "
                               "yapıldıysa \"Kabul — etkinlik yapıldı\" seçin; yapılmadıysa Kabul (yalnız plan "
                               "sayılır).", True),
    "bos_form": ("Boş form/şablon: yalnız \"yöntem tanımlı\" (plan) sayılır. Uygunsa Kabul; doldurulmuş "
                 "örneği varsa ayrıca ekleyin.", True),
    "katilim_izleme_degil": ("Katılım/yapılma kaydı: \"yapıldı\" sayılır, \"izleme sonucu\" sayılmaz. "
                             "Uygunsa Kabul.", True),
    "niyet_onlem_degil": ("Öneri ya da niyet; yapılmış bir iyileştirme değil (düşük düzeyde sayılır). "
                          "Uygunsa Kabul, değilse Ret.", True),
    "bilgilendirme_onlem_degil": ("Kurula bilgi verilmesi; iyileştirme sayılmadı (\"yapıldı\" sayılır). "
                                  "Uygunsa Kabul.", True),
    "surum_notu_onlem_degil": ("Belgenin yenilendiği yazıyor ama bir izlemeye dayandığı görünmüyor; "
                               "iyileştirme sayılmadı. Uygunsa Kabul.", True),
    "yonlendirme_onlem_degil": ("Bir talebin/geri bildirimin bir makama iletilmesi; yapılmış iyileştirme "
                                "sayılmadı. Uygunsa Kabul.", True),
    "onlem_izlemeye_dayanmiyor": ("İyileştirmenin bir izleme sonucuna dayandığı görünmüyor; iyileştirme "
                                  "sayılmadı. Uygunsa Kabul.", True),
    "ozgun_kanitsiz": ("Özgün/örnek uygulama için kanıt yetersiz; en üst düzey sayılmadı. Uygunsa Kabul.", True),
    "fotograf_mekan": ("Mekân/altyapı fotoğrafı: yapılan bir işi değil olanağı gösterir (plan sayıldı). "
                       "Uygunsa Kabul.", True),
    "fotograf_destekleyici": ("Fotoğraf tek başına kanıt sayılmadı. Bir etkinliğin fotoğrafıysa "
                              "\"Kabul — etkinlik yapıldı\", değilse Ret.", True),
    "haric_tur": ("Bu belge raporun kendisi ya da taslağı; kanıt olamaz. Ret seçin.", True),
    "bilgisiz_ekran": ("Bilgi içermeyen bir ekran/bağlantı sayfası; kanıt sayılmadı. Genelde Ret.", True),
    "madde_baska_birim": ("Alıntı başka bir birimin maddesinden; kanıt sayılmadı. Genelde Ret.", True),
    "not_uyusmuyor": ("Belgeyi yükleyenin notu ile belge içeriği uyuşmuyor; öneri belgeye göre yapıldı. Belge bu "
                      "maddeye gerçekten kanıtsa Kabul, değilse Ret seçin.", True),
    "betimleme_alintisi": ("Alıntı belgenin yazısı değil, görselin betimlemesi. Görsel bunu gerçekten "
                           "gösteriyorsa Kabul.", True),
    "dongu_halkasi": ("Önceki yıla ait ama maddedeki düzenli gözden geçirme döngüsünün parçası olarak "
                      "sayıldı.", False),
    "faaliyet_asamasi_uyusmuyor": ("Faaliyet kaydına göre daha düşük bir aşama sayıldı.", False),
}
# metni olmayan, bakılmayı gerektirmeyen işaretler (karar sonucu ya da kodun kendi düzeltmesi)
BILGI = frozenset({"belge_notu", "insan_reddetti", "insan_duzeltti", "birim_aitligi_onaylandi", "birim_iliskisi_insan",
                   "kurum_tavani_kaldirildi", "birim_sayfasi", "ikinci_arama", "asama_dusuruldu",
                   "asama_yuva_etiketine_uymuyor", "od_asamayla_tutarsiz", "fakulte_geneli",
                   "uygulama_kaniti_eksik", "madde_baska_fakulte", "birim_aitligi_dogrulanmali",
                   "puko_zinciri", "puko_onlem"})

F_HEAD = PatternFill("solid", fgColor="DDE7F0")
F_BOLUM = PatternFill("solid", fgColor="C9D6E3")
F_BAK = PatternFill("solid", fgColor="FFF6D5")       # bakılacak satır (açık sarı)
F_KARAR = PatternFill("solid", fgColor="E8F0FE")     # doldurulacak hücre
_INCE = Side(style="thin", color="B7C3CE")
KENAR = Border(left=_INCE, right=_INCE, top=_INCE, bottom=_INCE)

# (anahtar, başlık, genişlik, kullanıcı)
INC_COLS = [
    ("sira", "Sıra", 5, False),
    ("madde", "Madde", 26, False),
    ("belge", "Belge (klasördeki dosya)", 26, False),
    ("ad", "Önerilen kanıt adı (düzeltebilirsiniz)", 26, True),
    ("alinti", "Belgede ne yazıyor", 46, False),
    ("neden", "Neden bu maddeye", 36, False),
    ("dikkat", "Dikkat", 38, False),
    ("oneri", "Önerimiz", 9, False),
    ("karar", "KARARINIZ", 17, True),
    ("dogru", "Doğru madde (yalnız taşınacaksa)", 16, True),
    ("not", "Not", 24, True),
    ("satir", "satır kimliği", 10, False),       # gizli
    ("bolum", "bölüm", 4, False),                # gizli
    ("yazilan", "yazılan", 10, False),           # gizli
]
INC_GIZLI = ("satir", "bolum", "yazilan")
BIR_COLS = [
    ("sira", "Sıra", 5, False),
    ("belge", "Belge (klasördeki dosya)", 34, False),
    ("ad", "Kanıt adı", 28, False),
    ("neden", "Neden soruyoruz", 50, False),
    ("maddeler", "Hangi maddeler için önerildi", 36, False),
    ("cevap", "CEVABINIZ", 26, True),
    ("not", "Not", 28, True),
    ("doc_id", "belge kimliği", 10, False),      # gizli
    ("yazilan", "yazılan", 10, False),           # gizli
]
MAD_COLS = [
    ("madde", "Madde", 40, False),
    ("oneri", "Önerilen düzey", 22, False),
    ("neden", "Neden bu düzey", 60, False),
    ("onay", "Onayladığınız düzey (boş = öneri)", 22, True),
    ("not", "Not", 30, True),
    ("olcut", "ölçüt", 8, False),                # gizli
    ("yazilan", "yazılan", 10, False),           # gizli
]

NASIL = [
    "Bu dosya, aracın bulduğu kanıt önerilerini onaylamanız içindir. \"İnceleme\" sayfasında her satır "
    "bir öneridir: \"şu belge, şu maddeye kanıttır\". Belgeyi klasörde \"Belge\" sütunundaki adla bulabilirsiniz.",
    "\"İnceleme\" üç bölümdür. 1) Bakmanız gerekenler: \"Dikkat\" sütununu okuyun ve KARARINIZ'ı seçin. "
    "2) Sorunsuz görünenler: bölüm başlığındaki KARARINIZ hücresinde \"Hepsini kabul\" seçerseniz boş "
    "bıraktığınız satırlar kabul sayılır; itiraz ettiğiniz satırı tek tek değiştirin. 3) Daha önce karar "
    "verdikleriniz: değiştirmek istemedikçe dokunmayın.",
    "KARARINIZ: Kabul = belge bu maddeye kanıttır. Kabul — etkinlik yapıldı = belgede yalnız duyuru/plan "
    "görünse de etkinlik gerçekten yapıldı. Ret = kanıt değil. Başka maddeye taşı = kanıt ama başka bir "
    "maddeye; \"Doğru madde\" sütununda maddeyi seçin (ör. B.3.2). Başka maddeye taşı — etkinlik yapıldı = "
    "ikisi birden.",
    "\"Önerilen kanıt adı\" raporda görünecek addır; düzeltebilirsiniz (kişi adı, unvan, e-posta yazmayın). "
    "\"Not\" isteğe bağlıdır; Ret ya da taşıma nedenini kısaca yazmanız sonradan işe yarar.",
    "\"Bölümünüze ait mi\" sayfası: aracın hangi birime ait olduğundan emin olamadığı ya da başka birime "
    "ait saydığı belgeler. CEVABINIZ'ı seçin; boş bırakırsanız aracın kararı geçerli kalır.",
    "\"Maddeler\" sayfası: her madde için önerilen olgunluk düzeyi (1–5). Katılmıyorsanız \"Onayladığınız "
    "düzey\"i seçin; boş bırakırsanız öneri geçerlidir.",
    "Bitince dosyayı kaydedip kapatın ve hazırlayan kişiye haber verin. Sütun ya da sayfa silmeyin; gizli "
    "sayfalar ve sütunlar araç içindir.",
]


# -- yardımcılar --------------------------------------------------------------------------------

def _key(v) -> str:
    """Seçenek karşılaştırma anahtarı: Türkçe harfler sadeleşir, harf/rakam dışı atılır."""
    from .run import _norm
    return re.sub(r"[^a-z0-9]", "", _norm(v))


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _baslik(cs, cid: str) -> str:
    try:
        return cs.get(cid).title.replace("*", "").strip()
    except Exception:
        return ""


def madde_ad(cs, cid: str) -> str:
    b = _baslik(cs, cid)
    return f"{cid} — {b}" if b else cid


def _kisalt(q: str, n: int) -> str:
    q = " ".join(str(q or "").split())
    return q if len(q) <= n else q[:n].rsplit(" ", 1)[0] + " …"


def _yukseklik(vals: list, widths: list[float]) -> float:
    n = 1
    for v, w in zip(vals, widths):
        if v in (None, "") or not w:
            continue
        n = max(n, sum(max(1, -(-len(s) // max(1, int(w * 1.15)))) for s in str(v).split("\n")))
    return min(409, 15 * n + 4)


def _page(sh, ncols: int, title_rows: str = "1:1") -> None:
    sh.print_title_rows = title_rows
    sh.page_setup.orientation = "landscape"
    sh.page_setup.paperSize = sh.PAPERSIZE_A4
    sh.page_setup.fitToWidth = 1
    sh.page_setup.fitToHeight = 0
    sh.sheet_properties.pageSetUpPr.fitToPage = True
    sh.page_margins.left = sh.page_margins.right = 0.3
    sh.oddFooter.right.text = "Sayfa &P / &N"


def _head(sh, cols) -> None:
    sh.append([h for _, h, _, _ in cols])
    for i, (k, _, w, user) in enumerate(cols, 1):
        c = sh.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = F_KARAR if user else F_HEAD
        c.border = KENAR
        c.alignment = Alignment(wrap_text=True, vertical="center")
        sh.column_dimensions[get_column_letter(i)].width = w
    sh.row_dimensions[1].height = 32


def _hide(sh, cols, gizli) -> None:
    for i, (k, _, _, _) in enumerate(cols, 1):
        if k in gizli:
            sh.column_dimensions[get_column_letter(i)].hidden = True


def _row(sh, cols, vals: dict, fill: PatternFill | None = None) -> int:
    row = [vals.get(k, "") for k, _, _, _ in cols]
    sh.append(row)
    n = sh.max_row
    widths = [w if k not in ("satir", "bolum", "yazilan", "doc_id", "olcut") else 0 for k, _, w, _ in cols]
    sh.row_dimensions[n].height = _yukseklik(row, widths)
    for i, (k, _, _, user) in enumerate(cols, 1):
        c = sh.cell(row=n, column=i)
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.border = KENAR
        if user:
            c.fill = F_KARAR
        elif fill is not None:
            c.fill = fill
    return n


# -- İnceleme: satır içeriği -----------------------------------------------------------------------

def karar_etiketi(r: dict) -> tuple[str, str]:
    """Satırın (teknik) karar hücreleri → (KARARINIZ etiketi, Doğru madde)."""
    k = r.get("karar") or ""
    if k == "kabul":
        return K_KABUL, ""
    if k == "ret":
        return K_RET, ""
    if k != "duzelt":
        return "", ""
    y, o, a = r.get("duzelt_yuva") or "", r.get("duzelt_olcut") or "", r.get("duzelt_asama") or ""
    asil = r.get("yuva_model") or str(r.get("satir") or "").split("|")[-1]
    tasi = bool(y and y != asil) or bool(o and o != (r.get("olcut_model") or asil.split("/")[0]))
    if tasi and a in ("", "uygula"):
        return (K_TASI_ETK if a == "uygula" else K_TASI), (y or o)
    if not tasi and a == "uygula":
        return K_ETK, ""
    if not tasi and not a:
        return K_KABUL, ""
    return "Düzeltildi: " + " · ".join(x for x in ((y or o) if tasi else "", ASAMA_KISA.get(a, a)) if x), \
        (y or o if tasi else "")


def dikkat(r: dict, yil: int | None) -> tuple[list[str], bool]:
    """(düz Türkçe uyarılar, bakılmalı mı)."""
    out, bak = [], False
    ys = str(yil) if yil else "rapor"
    byil = f" ({r['donem_yil']})" if r.get("donem_yil") else ""
    fl = list(dict.fromkeys(r.get("flags") or []))
    if r.get("birim_onay_bekliyor") and "birim_onay_bekliyor" not in fl:
        fl.insert(0, "birim_onay_bekliyor")
    for f in fl:
        if f in DIKKAT:
            t, b = DIKKAT[f]
            out.append(t.format(yil=ys, byil=byil))
            bak = bak or b
        elif f not in BILGI:
            bak = True
    if "madde_baska_fakulte" in fl and "madde_baska_birim" not in fl:
        out.append(DIKKAT["madde_baska_birim"][0])
    if r.get("zayif"):
        out.insert(0, "Model bu eşleşmeden emin değil. Alıntı maddeye gerçekten uyuyorsa Kabul, uymuyorsa Ret.")
        bak = True
    if r.get("od") and r["od"] >= 4 and r.get("sayilir") and not r.get("karar"):
        out.append(f"Bu satır maddeyi {r['od']}. düzeye çıkarıyor. Alıntı gerçekten "
                   + ("izleme sonucu/iyileştirme" if r["od"] == 4 else "özgün, örnek gösterilebilir bir uygulama")
                   + " gösteriyorsa Kabul, değilse Ret.")
        bak = True
    if not r.get("sayilir") and not r.get("karar") and not out:
        out.append("Şu an kanıt sayılmıyor" + (f": {r['vurgu']}" if r.get("vurgu") else "") + ".")
        bak = True
    elif not out and bak and r.get("vurgu"):
        out.append("Kontrol edin: " + r["vurgu"])
    return list(dict.fromkeys(out)), bak


def _yeniden(r: dict) -> str:
    """'Yeniden bak' gerekçesini düz Türkçeye çevirir."""
    lab, dog = karar_etiketi(r)
    t = f"Daha önce \"{lab}{(' → ' + dog) if dog else ''}\" demiştiniz. O karardan sonra bu satırda değişiklik oldu"
    parts = []
    for p in str(r.get("yeniden_bak") or "").split("; "):
        if p.startswith("yeni işaret:"):
            continue                          # uyarılar ayrıca yazılır
        p = p.replace("sayılan aşama", "sayılan kısım").replace("OD", "düzey")
        for k, v in ASAMA_KISA.items():
            p = p.replace(k, v)
        parts.append(p)
    t += (f" ({'; '.join(parts)})" if parts else "") + ". Kararınızı yeniden seçin; aynı kalacaksa aynısını seçin."
    return t


def inceleme_satirlari(a, cs) -> list[dict]:
    """Sade satırlar (bölüm sırasıyla). bolum: 1 bakılacak, 2 sorunsuz, 3 karar verilmiş."""
    out = []
    for r in a.rows:
        uy, bak = dikkat(r, a.donem)
        rb = bool(r.get("yeniden_bak"))
        lab, dog = karar_etiketi(r)
        if rb:
            uy.insert(0, _yeniden(r))
            lab, dog = "", ""
        bolum = 1 if (rb or (bak and not r.get("karar"))) else 3 if r.get("karar") else 2
        om = r.get("olcut_model") or r["olcut"]
        ym = r.get("yuva_model") or r["yuva"]
        try:
            ymetin = cs.get_slot(ym).text
        except KeyError:
            ymetin = r.get("yuva_metni") or ""
        madde = madde_ad(cs, om) + (f"\nKılavuz örneği: {_kisalt(ymetin, 140)}" if ymetin else "")
        dosya = r.get("kaynak_dosya") or ""
        belge = (dosya.replace("\\", "/").rsplit("/", 1)[-1] + (f"\n(klasör: {dosya.rsplit('/', 1)[0]})"
                                                               if "/" in dosya else "")) if dosya else r.get("belge") or ""
        asama = r.get("asama") or ""
        neden = (f"Maddenin \"{ASAMA_KISA[asama]}\" kısmı için. " if asama in ASAMA_KISA else "") + (r.get("gerekce") or "")
        if "belge_notu" in (r.get("flags") or []):
            neden = neden.rstrip() + " Yükleyenin notu dikkate alındı."
        alinti = r.get("alinti") or ""
        out.append({
            "satir": r["satir"], "bolum": bolum, "_rb": rb, "_birim": bool(r.get("birim_onay_bekliyor")),
            "_olcut": om, "madde": madde, "belge": belge, "ad": r.get("kanit_adi") or "",
            "alinti": f"“{_kisalt(alinti, 600)}”" if alinti else "",
            "neden": neden.strip(), "dikkat": "\n".join(f"• {x}" for x in uy) if len(uy) > 1 else "".join(uy),
            "oneri": "Bakın" if bak or rb else "Kabul",
            "karar": lab, "dogru": dog, "not": r.get("not") or "",
        })
    from bidr.criteria.model import id_key
    out.sort(key=lambda x: (x["bolum"], not x["_rb"], not x["_birim"], id_key(x["_olcut"]), x["satir"]))
    for x in out:
        x["yazilan"] = json.dumps({"k": x["karar"], "m": x["dogru"], "n": x["not"], "a": x["ad"]}, ensure_ascii=False)
    return out


BOLUM_BASLIK = {
    1: "1. BAKMANIZ GEREKENLER ({n} satır) — \"Dikkat\" sütununu okuyup her satırda KARARINIZ'ı seçin.",
    2: "2. SORUNSUZ GÖRÜNENLER ({n} satır) — Hepsini kabul etmek için bu satırın KARARINIZ hücresinde "
       "\"Hepsini kabul\" seçin; itiraz ettiğiniz satırı tek tek değiştirin (tek tek seçtiğiniz karar geçerlidir).",
    3: "3. DAHA ÖNCE KARAR VERDİKLERİNİZ ({n} satır) — Değiştirmek istemedikçe dokunmayın.",
}


def write_sade(wb, a, cs) -> None:
    """Sade sayfaları kitabın başına ekler; teknik sayfaları gizler."""
    teknik = list(wb.sheetnames)
    sh = wb.create_sheet(SH_INC, 0)
    _head(sh, INC_COLS)
    idx = {k: i for i, (k, _, _, _) in enumerate(INC_COLS, 1)}
    rows = inceleme_satirlari(a, cs)
    sira = 0
    for b in (1, 2, 3):
        grp = [x for x in rows if x["bolum"] == b]
        if not grp:
            continue
        sh.append([BOLUM_BASLIK[b].format(n=len(grp))])
        n = sh.max_row
        sh.merge_cells(start_row=n, start_column=1, end_row=n, end_column=idx["karar"] - 1)
        c = sh.cell(row=n, column=1)
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="center")
        for i in range(1, idx["not"] + 1):
            sh.cell(row=n, column=i).fill = F_BOLUM
        sh.row_dimensions[n].height = 34 if b == 2 else 20
        if b == 2:
            sh.cell(row=n, column=idx["satir"], value=TOPLU_SATIR)
            t = sh.cell(row=n, column=idx["karar"])
            t.fill = F_KARAR
            t.border = KENAR
            t.font = Font(bold=True)
            dv = DataValidation(type="list", formula1=f'"{TOPLU}"', allow_blank=True)
            dv.add(t.coordinate)
            sh.add_data_validation(dv)
        for x in grp:
            sira += 1
            x["sira"] = sira
            _row(sh, INC_COLS, x, F_BAK if b == 1 else None)
    last = max(sh.max_row, 2)
    kcol, dcol = get_column_letter(idx["karar"]), get_column_letter(idx["dogru"])
    dv = DataValidation(type="list", formula1='"' + ",".join(KARAR_SECENEK) + '"', allow_blank=True,
                        showErrorMessage=True, errorTitle="KARARINIZ", error="Listeden seçin.")
    for r in range(2, last + 1):
        if sh.cell(row=r, column=idx["satir"]).value not in (None, TOPLU_SATIR):
            dv.add(f"{kcol}{r}")
    sh.add_data_validation(dv)
    # Doğru madde: madde listesi (açılır), elle yazmak da serbest (ör. yuva: B.3.2/3)
    ls = wb.create_sheet(SH_LISTE)
    for s in cs.sub_criteria:
        ls.append([madde_ad(cs, s.id)])
    ls.sheet_state = "hidden"
    dv2 = DataValidation(type="list", formula1=f"'{SH_LISTE}'!$A$1:$A${max(1, ls.max_row)}",
                         allow_blank=True, showErrorMessage=False)
    dv2.add(f"{dcol}2:{dcol}{last}")
    sh.add_data_validation(dv2)
    _hide(sh, INC_COLS, INC_GIZLI)
    sh.freeze_panes = "C2"
    _page(sh, idx["not"])
    sh.print_area = f"A1:{get_column_letter(idx['not'])}{last}"

    pos = 1
    if a.birim_sayfa:
        _write_birim(wb.create_sheet(SH_BIRIM, pos), a, cs)
        pos += 1
    _write_madde(wb.create_sheet(SH_MADDE, pos), a, cs)
    pos += 1
    n = wb.create_sheet(SH_NASIL, pos)
    n.column_dimensions["A"].width = 110
    n.append(["Nasıl doldurulur"])
    n["A1"].font = Font(bold=True, size=13)
    for i, line in enumerate(NASIL, 1):
        n.append([f"{i}. {line}"])
        n.cell(row=n.max_row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        n.row_dimensions[n.max_row].height = _yukseklik([line], [110])
    _page(n, 1)
    for name in teknik:
        wb[name].sheet_state = "hidden"
    wb.active = 0


def _write_birim(sh, a, cs) -> None:
    _head(sh, BIR_COLS)
    from bidr.criteria.model import id_key
    for i, x in enumerate(a.birim_sayfa, 1):
        rel = x.get("insan_birim_iliskisi") or ""
        if rel:
            neden = f"Cevabınız kayıtlı: \"{BIRIM_AD.get(rel, rel)}\"."
        elif (x.get("model_iliskisi") or "") == "belirsiz" or "belirsiz" in (x.get("durum") or ""):
            neden = "Araç bu belgenin hangi birime ait olduğunu anlayamadı; onaylanana dek kanıt sayılmıyor."
        else:
            neden = "Araç bu belgeyi başka bir birimin belgesi saydı ve kanıt listesine almadı."
        if x.get("gerekce"):
            neden += f"\nAracın gerekçesi: {_kisalt(x['gerekce'], 300)}"
        md = [madde_ad(cs, c) for c in sorted(set(x.get("olcutler") or []), key=id_key)]
        dosya = x.get("kaynak_dosya") or ""
        cev = BIRIM_AD.get(rel, "")
        _row(sh, BIR_COLS, {
            "sira": i, "belge": dosya.replace("\\", "/").rsplit("/", 1)[-1] if dosya else x.get("belge") or "",
            "ad": x.get("kanit_adi") or "", "neden": neden, "maddeler": "\n".join(md),
            "cevap": cev, "not": x.get("not") or "", "doc_id": x["doc_id"],
            "yazilan": json.dumps({"c": cev, "n": x.get("not") or ""}, ensure_ascii=False)})
    last = max(sh.max_row, 2)
    idx = {k: i for i, (k, _, _, _) in enumerate(BIR_COLS, 1)}
    col = get_column_letter(idx["cevap"])
    dv = DataValidation(type="list", formula1='"' + ",".join(BIRIM_CEVAP) + '"', allow_blank=True)
    dv.add(f"{col}2:{col}{last}")
    sh.add_data_validation(dv)
    _hide(sh, BIR_COLS, ("doc_id", "yazilan"))
    sh.freeze_panes = "C2"
    _page(sh, idx["not"])


def _madde_neden(c: dict) -> str:
    var = [f"{ASAMA_KISA[x]} ({c['zincir'][x]['eslesme']})" for x in ORDER
           if c["zincir"][x]["durum"] in ("var", "dusuk")]
    yok = [ASAMA_KISA[x] for x in ORDER if c["zincir"][x]["durum"] == "yok"]
    L = [("Kanıtı olan kısımlar: " + ", ".join(var)) if var else "Bu madde için kanıt bulunmadı."]
    if yok:
        L.append("Kanıtı olmayan kısımlar: " + ", ".join(yok) + ".")
    if c.get("eksik"):
        e = c["eksik"][0]
        L.append(f"Bir üst düzey ({c['sonraki_od']}) için gereken: {e['gereken']}.")
    return "\n".join(L)


def _write_madde(sh, a, cs) -> None:
    _head(sh, MAD_COLS)
    for c in a.criteria:
        onay = OD_AD.get(c.get("od_onayli"), "") if c.get("od_onayli") else ""
        nt = (c.get("od_onay") or {}).get("not") or ""
        _row(sh, MAD_COLS, {
            "madde": madde_ad(cs, c["olcut"]), "oneri": OD_AD.get(c["od"], str(c["od"])),
            "neden": _madde_neden(c), "onay": onay, "not": nt, "olcut": c["olcut"],
            "yazilan": json.dumps({"o": onay, "n": nt}, ensure_ascii=False)})
    last = max(sh.max_row, 2)
    idx = {k: i for i, (k, _, _, _) in enumerate(MAD_COLS, 1)}
    col = get_column_letter(idx["onay"])
    dv = DataValidation(type="list", formula1='"' + ",".join(OD_AD.values()) + '"', allow_blank=True)
    dv.add(f"{col}2:{col}{last}")
    sh.add_data_validation(dv)
    _hide(sh, MAD_COLS, ("olcut", "yazilan"))
    sh.freeze_panes = "B2"
    _page(sh, idx["not"])


# -- okuma ve birleştirme ----------------------------------------------------------------------

def _read(wb, name: str, cols) -> list[dict]:
    if name not in wb.sheetnames:
        return []
    it = wb[name].iter_rows(values_only=True)
    head = [_s(v) for v in (next(it, None) or ())]
    keys = {h: k for k, h, _, _ in cols}
    ks = [keys.get(h) for h in head]
    out = []
    for vals in it:
        r = {k: v for k, v in zip(ks, vals) if k}
        if any(_s(v) for v in r.values()):
            out.append(r)
    return out


def _yazilan(v) -> dict:
    try:
        d = json.loads(_s(v) or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def read_inceleme(wb) -> tuple[dict[str, dict], bool] | None:
    """{satır kimliği: sade satır}, toplu kabul seçildi mi. Sayfa yoksa (eski tablo) None."""
    if SH_INC not in wb.sheetnames:
        return None
    rows, toplu = {}, False
    for r in _read(wb, SH_INC, INC_COLS):
        sid = _s(r.get("satir"))
        if sid == TOPLU_SATIR:
            toplu = _key(r.get("karar")) == _key(TOPLU)
        elif "|" in sid:
            rows[sid] = r
    return rows, toplu


def _madde_kodu(v: str) -> str:
    m = re.search(r"\b([A-Za-z])\s*\.\s*(\d+)\s*\.\s*(\d+)(?:\s*/\s*(\d+))?", v or "")
    if not m:
        return ""
    s = f"{m.group(1).upper()}.{m.group(2)}.{m.group(3)}"
    return s + (f"/{m.group(4)}" if m.group(4) else "")


def _yuva_sec(cs, tags, olcut: str, asama: str) -> tuple[str, bool]:
    """Ölçütte aşamaya uyan yuva; (yuva, kesin mi). Tek uyan yoksa ilk yuva, kesin değil."""
    slots = [s for s in cs.get(olcut).slots if not s.footnote]
    uy = [s for s in slots if (t := tags.get(s.id)) is not None and not t.uncertain and asama in t.stages]
    if len(uy) == 1:
        return uy[0].id, True
    return (uy or slots)[0].id, False


def _karar_hucreleri(s: dict, xr: dict, cs, tags) -> dict:
    """Sade karar → teknik karar hücreleri (hata: `sade_hata`)."""
    k = _key(s.get("karar"))
    bos = {"duzelt_olcut": "", "duzelt_yuva": "", "duzelt_asama": ""}
    etkin = _s(xr.get("etkin_asama"))
    if k == _key(K_KABUL):
        return {"karar": "kabul", **bos}
    if k in (_key(K_RET), "red"):
        return {"karar": "ret", **bos}
    if k == _key(K_ETK):
        if ORDER.get(etkin, 0) > ORDER["uygula"] and _s(xr.get("karar")) != "duzelt":
            return {"karar": "kabul", **bos}           # zaten üst kısım sayılıyor: düşürme
        return {"karar": "duzelt", **bos, "duzelt_asama": "uygula"}
    if k in (_key(K_TASI), _key(K_TASI_ETK)):
        kod = _madde_kodu(_s(s.get("dogru")))
        if not kod:
            return {"sade_hata": f"\"{_s(s.get('karar'))}\": \"Doğru madde\" sütununda maddeyi seçin (ör. B.3.2)"}
        olcut = kod.split("/")[0]
        try:
            cs.get(olcut)
        except KeyError:
            return {"sade_hata": f"Doğru madde '{_s(s.get('dogru'))}' kılavuzda yok"}
        etk = k == _key(K_TASI_ETK)
        if "/" in kod:
            yuva, kesin = kod, True
        else:
            yuva, kesin = _yuva_sec(cs, tags, olcut, "uygula" if etk else (etkin or "planla"))
        out = {"karar": "duzelt", "duzelt_olcut": olcut, "duzelt_yuva": yuva,
               "duzelt_asama": "uygula" if etk else ""}
        if not kesin:
            out["_yuva_notu"] = f"[maddedeki yeri kodca seçildi: {yuva}; yeniden bakılmalı]"
        return out
    if not k:
        return {"karar": "", **bos}
    return {"sade_hata": f"KARARINIZ '{_s(s.get('karar'))}' geçersiz ({' · '.join(KARAR_SECENEK)})"}


def merge_rows(xrows: list[dict], sade: tuple[dict[str, dict], bool] | None, cs=None) -> list[dict]:
    """Teknik satırların üstüne sade sayfadaki değişiklikleri yazar (yerinde; listeyi döndürür)."""
    if not sade:
        return xrows
    srows, toplu = sade
    from bidr.criteria.slots import load_tags
    tags = None
    for xr in xrows:
        s = srows.get(_s(xr.get("satir")))
        if s is None:
            continue
        w = _yazilan(s.get("yazilan"))
        rb = bool(_s(xr.get("yeniden_bak")))
        degisti = (_key(s.get("karar")) != _key(w.get("k")) or _madde_kodu(_s(s.get("dogru")))
                   != _madde_kodu(_s(w.get("m"))))
        yn = ""
        if degisti and not (rb and not _s(s.get("karar"))):
            if tags is None:
                if cs is None:
                    from bidr.criteria.loader import load_criteria
                    cs = load_criteria()
                tags = load_tags(cs)
            cells = _karar_hucreleri(s, xr, cs, tags)
            yn = cells.pop("_yuva_notu", "")
            xr.update(cells)
            if rb and _s(s.get("karar")):
                xr["bakildi"] = "evet"
        if _s(s.get("not")) != _s(w.get("n")):
            xr["not"] = _s(s.get("not"))
        if yn:
            xr["not"] = " ".join(x for x in (_s(xr.get("not")), yn) if x)
        if _s(s.get("ad")) != _s(w.get("a")):
            xr["kanit_adi"] = _s(s.get("ad"))
        if (toplu and _s(s.get("bolum")) == "2" and not _s(xr.get("karar")) and not rb
                and not xr.get("sade_hata")):
            xr["karar"] = "kabul"
            xr["not"] = " ".join(x for x in (_s(xr.get("not")), TOPLU_NOT) if x)
    return xrows


def merge_units(urows: list[dict] | None, wb) -> list[dict] | None:
    if urows is None or SH_BIRIM not in wb.sheetnames:
        return urows
    by = {_s(r.get("doc_id")): r for r in _read(wb, SH_BIRIM, BIR_COLS) if _s(r.get("doc_id"))}
    cevap = {_key(k): v for k, v in BIRIM_CEVAP.items()}
    for ur in urows:
        s = by.get(ur["doc_id"])
        if s is None:
            continue
        w = _yazilan(s.get("yazilan"))
        if _key(s.get("cevap")) != _key(w.get("c")):
            c = _key(s.get("cevap"))
            ur["insan_birim_iliskisi"] = cevap.get(c, _s(s.get("cevap"))) if c else ""
        if _s(s.get("not")) != _s(w.get("n")):
            ur["not"] = _s(s.get("not"))
    return urows


def merge_od(orows: list[dict] | None, wb) -> list[dict] | None:
    if orows is None or SH_MADDE not in wb.sheetnames:
        return orows
    by = {_s(r.get("olcut")): r for r in _read(wb, SH_MADDE, MAD_COLS) if _s(r.get("olcut"))}
    for o in orows:
        s = by.get(o["olcut"])
        if s is None:
            continue
        w = _yazilan(s.get("yazilan"))
        if _key(s.get("onay")) != _key(w.get("o")):
            v = _s(s.get("onay"))
            m = re.match(r"\s*(?:OD\s*)?([0-9]+)\b", v, re.I)
            o["od"] = m.group(1) if m else v
        if _s(s.get("not")) != _s(w.get("n")):
            o["not"] = _s(s.get("not"))
    return orows
