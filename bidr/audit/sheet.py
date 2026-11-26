"""review.xlsx yazımı ve okunması (openpyxl). Sütunlar başlık adıyla okunur; kullanıcı
sütun sırasını değiştirse ya da sütun eklese de karar sütunları bulunur.

Bu modül teknik sayfaları yazar ("Eşleşmeler", "Ölçüt özeti", birim sayfası, "Açıklama"); son
kullanıcının gördüğü sade sayfalar (İnceleme, Bölümünüze ait mi?, Maddeler, Nasıl doldurulur)
`sade.py`'dedir. Teknik sayfalar gizlenir; okuma iki katmanı birleştirir (sade değişiklik önce gelir)."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .rules import LINKS

SHEET_ROWS, SHEET_SUM, SHEET_META, SHEET_HELP = "Eşleşmeler", "Ölçüt özeti", "_meta", "Açıklama"
SHEET_UNIT = "Başka birime ait sayılanlar"

# Birim sayfası: (anahtar, başlık, genişlik, kullanıcı doldurur mu). Başlık satırı açıklamanın altında.
UNIT_COLS = [
    ("doc_id", "belge kimliği", 20, False),
    ("belge", "belge (çalışma adı)", 36, False),
    ("kaynak_dosya", "kaynak dosya (özgün ad)", 40, False),
    ("kanit_adi", "kanıt adı", 30, False),
    ("gerekce", "modelin gerekçesi", 50, False),
    ("eslesmeler", "eşleşmeler: başka birimde reddedilen, belirsizde onay bekleyen (ölçüt yuva · aşama · OD: alıntı)", 70, False),
    ("durum", "durum", 30, False),
    ("insan_birim_iliskisi", "insan_birim_iliskisi", 22, True),
    ("not", "not", 40, True),
]
UNIT_HEAD = {h: k for k, h, _, _ in UNIT_COLS}
UNIT_NOTE = ("İnce karar bu belgeleri başka bir bölüm/birimin belgesi saydı (eşleşmeleri reddedildi, kanıt "
             "sayılmadı) ya da birim aitliğini anlayamadı (belirsiz: insan onaylayana dek kanıt sayılmaz, "
             "yayımlanan listeye girmez). Yanlışsa ya da belirsiz belgeyi onaylamak için 'insan_birim_iliskisi' sütununda doğru ilişkiyi seçin (kendi, "
             "ust_birim_bu_birim_hakkinda, fakulte_geneli, kurum_geneli; başka birim olduğunu onaylamak için "
             "baska_birim) ve `bidr audit apply` çalıştırın. İnsan kararı modelinkinin önüne geçer: reddedilen "
             "eşleşmeler geri gelir (fakülte/kurum geneli yalnız P, OD2) ve `bidr audit` ile tabloyu "
             "yenileyince 'Eşleşmeler' sayfasında karar bekler. Eşleşme kaydı yoksa belge yeniden karara "
             "işaretlenir (`bidr decide prepare --stage fine --only <belge kimliği>`; ilişkiyi model "
             "değiştiremez). Boş hücre: önceki insan kararı korunur (karar yoksa model kararı geçerli); "
             "insan kararını kaldırıp modelin kararına dönmek için 'model' seçin.")

# (anahtar, başlık, genişlik, kullanıcı doldurur mu)
COLS = [
    ("satir", "satır kimliği", 24, False),
    ("belge", "belge (çalışma adı)", 42, False),
    ("kaynak_dosya", "kaynak dosya (özgün ad)", 40, False),
    ("kopyalar", "kopyaları (aynı belgenin kararı devralan kopyaları; karar hepsine uygulanır)", 24, False),
    ("kanit_adi", "kanıt adı (düzeltilebilir)", 36, True),
    ("belge_turu", "belge türü", 18, False),
    ("birim_iliskisi", "birim ilişkisi", 14, False),
    ("donem_ici", "dönem içi", 9, False),
    ("donem_kurali", "dönem kuralı", 26, False),
    ("tarih_bilgisi", "tarih · kaynağı", 26, False),
    ("olcut", "ölçüt", 8, False),
    ("yuva", "yuva", 9, False),
    ("yuva_metni", "yuva metni", 42, False),
    ("asama", "aşama (model)", 12, False),
    ("etkin_asama", "aşama (sayılan)", 12, False),
    ("od", "OD (sayılan)", 8, False),
    ("etiket", "yuva etiketi", 24, False),
    ("etiket_durumu", "etiket durumu", 10, False),
    ("vurgu", "vurgu", 26, False),
    ("guven", "güven", 8, False),
    ("isaretler", "işaretler", 30, False),
    ("alinti_kaynagi", "alıntı kaynağı (belge/betimleme)", 10, False),
    ("alinti", "alıntı", 60, False),
    ("gerekce", "gerekçe", 50, False),
    ("yeniden_bak", "YENİDEN BAK: karardan sonra değişen", 30, False),
    ("bakildi", "bakıldı (evet)", 9, True),
    ("karar", "KARAR (kabul/ret/duzelt)", 14, True),
    ("duzelt_olcut", "düzelt: ölçüt", 10, True),
    ("duzelt_yuva", "düzelt: yuva", 10, True),
    ("duzelt_asama", "düzelt: aşama", 12, True),
    ("etiket_karari", "yuva etiketi kararı (onayla/duzelt)", 14, True),
    ("etiket_yeni", "yuva etiketi: yeni aşama(lar)", 22, True),
    ("not", "NOT", 40, True),
    ("olcut_model", "ölçüt (model)", 8, False),
    ("kanit_adi_oneri", "kanıt adı (öneri)", 30, False),
    ("kanit_adi_kaynagi", "kanıt adı kaynağı", 10, False),
    ("baglanti", "bağlantı (düzeltilebilir)", 40, True),
    ("baglanti_oneri", "bağlantı (öneri)", 30, False),
    ("baglanti_kaynagi", "bağlantı kaynağı", 10, False),
]
HEAD = {h: k for k, h, _, _ in COLS}

# "Ölçüt özeti": kodun önerdiği OD ile komisyonun onayladığı nihai OD ayrı sütunlarda
SUM_OD, SUM_NOT = "ONAYLANAN OD (insan)", "OD notu"
SUM_USER = (SUM_OD, SUM_NOT)
SUM_COLS = [("ölçüt", 8), ("başlık", 40), ("önerilen OD", 10), ("OD (düşük güven dahil)", 10), ("P planla", 9),
            ("U uygula", 9), ("K kontrol_et", 9), ("Ö onlem_al", 9), ("Z ozgun", 9), ("eşleşme", 8), ("belge", 7),
            ("dolu yuva", 9), ("öncelik", 8), ("eksikler", 70), ("notlar", 50), (SUM_OD, 12), (SUM_NOT, 30)]

F_HEAD = PatternFill("solid", fgColor="DDDDDD")
F_USER = PatternFill("solid", fgColor="E8F0FE")
F_OD4 = PatternFill("solid", fgColor="FCE4D6")
F_ONERI = PatternFill("solid", fgColor="F8CBAD")
F_LOW = PatternFill("solid", fgColor="FFF2CC")
F_OFF = PatternFill("solid", fgColor="EDEDED")
F_OK = PatternFill("solid", fgColor="E2EFDA")
F_GAP = PatternFill("solid", fgColor="F4CCCC")

HELP = [
    "Her satır kodun kabul ettiği bir eşleşmedir (alıntı belgede birebir doğrulandı).",
    "KARAR: kabul | ret | duzelt. Her satır kararlı olmadan audit aşaması bitmez.",
    "duzelt: 'düzelt: yuva' (ör. B.1.2/3; ölçüt yuvadan çıkar) ve/veya 'düzelt: aşama' "
    "(planla, uygula, kontrol_et, onlem_al, ozgun) doldurun.",
    "Yuva etiketi kararı (isteğe bağlı): onayla = yuvanın PUKÖ etiketi doğru; duzelt = "
    "'yeni aşama(lar)' sütununa virgülle yazın. Bunlar etiket dosyasını DEĞİŞTİRMEZ; "
    "`bidr audit apply` slot-tags-oneri.yaml önerisi üretir.",
    "Turuncu OD hücresi: ölçütü OD4/OD5'e yükselten eşleşme; koyu turuncu: yükselten etiket henüz öneri.",
    "Sarı güven: düşük güven; bu eşleşme önerilen OD'ye katılmaz (yalnız 'OD düşük güven dahil'). "
    "KARAR kabul ya da duzelt verilirse insan kararı kuralı aşar: eşleşme önerilen OD'ye katılır.",
    "Alıntı kaynağı 'betimleme' (sarı): alıntı belgenin kendi yazısından değil, ajanın görüntüden "
    "yazdığı betimlemeden (bidr describe). Fotoğraf bir tesisin/etkinliğin varlığını gösterir; "
    "kullanım sıklığını ya da iyileştirmeyi göstermez.",
    "Bağlantı: raporda kanıt adı bu adrese bağlanır (öncelik: insan > belge metni > klasör). Öneri, "
    "belge metnindeki yayın adresidir (web çıktısının üst/altbilgisi). Kamuya açık belgenin yayımlandığı "
    "adresi 'bağlantı' hücresine yazın (https://…); ad gibi belgeye aittir. Yayımlanmamış belge için boş "
    "bırakın: config.yaml `rapor.kanit_kok_baglanti` tanımlıysa kanıt klasöründeki yoluna bağlanır.",
    "Birim ilişkisi (ince karar): kendi = birimin belgesi; ust_birim_bu_birim_hakkinda = dekanlık/"
    "fakülte yönetim kurulu/senato/rektörlüğün bu birimi konu alan kararı (OD tavanı yok); "
    "fakulte_geneli / kurum_geneli = bütün birimleri kapsayan düzenleme ya da faaliyet (yalnız P, OD2); "
    "belirsiz = model aitliği anlayamadı: bu satırlar tablonun başında (turuncu) ve insan onaylayana dek "
    "SAYILMAZ, yayımlanan kanıt listesine girmez. Birimin belgesiyse KARAR kabul (ya da birim sayfasında "
    "ilişkiyi seçin), değilse ret. Başka birime ait belgeler bu sayfaya gelmez; ayrı sayfada listelenir ve oradan geri alınabilir.",
    "Gri satır: sayılmayan eşleşme (ret; önceki yıl olayı = geçmiş kanıt; tarihi bilinmeyen ya da "
    "rapor yılından sonraki belge; yürürlükteki sürüm olmayan düzenleme; birim aitliği onay bekleyen).",
    "'tarih · kaynağı': belgenin tarihi ve nereden alındığı (metin içi etiket, baş bölge, akademik dönem, "
    "dosya adı); birden çok tarih olay tarihini belirsiz kılıyorsa nedeni yazar.",
    "Dönem kuralı (komisyon kararı): yapı belgesi (müfredat, ders kataloğu/bilgi formu, yönerge, iş akışı, "
    "görev dağılımı, stratejik plan) rapor yılında yürürlükteyse sayılır; tarihi başka yıl ya da yoksa "
    "'güncellik doğrulanmalı' (sarı). Olay belgesi (karar, tutanak, anket sonucu, etkinlik, rapor, yazışma) "
    "rapor yılında gerçekleşmiş olmalı: önceki yıl 'geçmiş kanıt (süreklilik)', tarihsiz 'tarih doğrulanmalı' "
    "(sayılmaz; tarih rapor yılındaysa duzelt + aşama ile sayın). Rapor yılından sonra tarihli belge o "
    "dönemin kanıtı değildir; düzenlemenin revizyon tarihi dönem sonrasıysa dönemdeki sürüm aranmalı. Aynı "
    "düzenlemenin sürümlerinden en yenisi (rapor yılından sonraki sürüm hariç) yürürlükte sayılır; eskileri sayılmaz "
    "('daha yeni sürümü var', sorulmaz; o sürüm de yürürlükteyse KARAR kabul). Sıra kurulamazsa (tarihsiz sürüm) "
    "'sürüm doğrulanmalı' sorulur. Ölçütte gözden geçirme döngüsü tanımlıysa "
    "döngü içindeki önceki yıl olayı 'döngü halkası' olarak sayılır.",
    "Önerilen OD kuralı: P→OD2, +U→OD3, +K ve Ö (ikisi)→OD4, +Z→OD5; zincir eksikse düşük düzey. "
    "Kurum geneli yönetmelik/yönerge yalnız P sayılır. Ayrıntı: docs/AUDIT.md.",
    "Kanıt adı: kanıt dosyasının adı (öncelik: insan > model > kural; 'kanıt adı kaynağı' sütunu). "
    "Düzeltmek için 'kanıt adı' hücresini değiştirin; ad belgeye aittir, belgenin bir satırında "
    "değiştirmek yeter (satırlarda farklı adlar geçersiz). Kişi adı, unvan, e-posta yazmayın. "
    "`bidr audit apply` düzeltmeyi kanit-adlari.jsonl'e (kaynak: insan) yazar.",
    f"'{SHEET_UNIT}' sayfası: modelin başka birime ait saydığı belgeler. 'insan_birim_iliskisi' "
    "doldurulursa insan kararı modelinkinin önüne geçer (ayrıntı sayfanın ilk satırında).",
    "Gri satırlarda ve işaretlerde kodun savunmaları: hariç tür, bilgisiz ekran, yürürlükten kaldırılmış "
    "düzenleme, başka birimin maddesi, boş form, duyuru/gelecek zaman, katılım ≠ izleme, öneri/bilgilendirme/"
    "sürüm notu ≠ iyileştirme, izlemeye dayanmayan iyileştirme, özgünlük kanıtı yetersiz. Yanlışsa satırı "
    "kabul (modelin aşaması) ya da duzelt edin. Ayrıntı: docs/AUDIT.md \"Kod tarafı savunmalar\".",
    f"'{SHEET_SUM}' sayfası: 'önerilen OD' kodun önerisidir; komisyonun onayladığı nihai düzeyi "
    f"'{SUM_OD}' sütununa (1-5) yazın, gerekirse '{SUM_NOT}'. Kod önerisi değişmez; ikisi ayrı kaydedilir "
    "(olcut-od-kararlari.jsonl, audit-olcutler.json `od_kod_onerisi` / `od_onayli`). OD5 önerisi insan onayı bekler.",
    "YENİDEN BAK (turuncu): satırın kararı verildikten sonra audit yeniden çalıştı ve satıra yeni bir "
    "inceleme işareti eklendi (ör. tarih_dogrulanmali, birim_sayfasi, fotograf_mekan) ya da sayılan aşaması/OD'si "
    "değişti. Eski karar KORUNUR ve geçerlidir; satıra yeniden bakın: karar aynı kalacaksa 'bakıldı' sütununa "
    "evet yazın, değilse KARAR/NOT'u değiştirin; sonra `bidr audit apply`. Bu satırlar tablonun başındadır.",
    "Tabloyu doldurduktan sonra: bidr audit apply -w <çalışma alanı>",
]


def _fmt(v):
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    return v


def write_review(a, path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_ROWS
    ws.append([h for _, h, _, _ in COLS])
    for i, (_, _, w, user) in enumerate(COLS, 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = F_USER if user else F_HEAD
        c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.column_dimensions[get_column_letter(i)].width = w
    idx = {k: i for i, (k, _, _, _) in enumerate(COLS, 1)}
    # birim aitliği onay bekleyen satırlar öne (insan onaylamadıkça sayılmaz)
    for r in sorted(a.rows, key=lambda r: (not r.get("birim_onay_bekliyor"), not r.get("yeniden_bak"))):
        ws.append([_fmt(r.get(k, "")) for k, _, _, _ in COLS])
        n = ws.max_row
        for i in range(1, len(COLS) + 1):
            ws.cell(row=n, column=i).alignment = Alignment(wrap_text=True, vertical="top")
        if not r["sayilir"]:
            for i in range(1, idx["karar"]):
                ws.cell(row=n, column=i).fill = F_OFF
        if r["od"] and r["od"] >= 4 and r["sayilir"]:
            fill = F_ONERI if r["etiket_durumu"] != "onayli" else F_OD4
            for k in ("od", "etiket", "etiket_durumu", "vurgu"):
                ws.cell(row=n, column=idx[k]).fill = fill
            ws.cell(row=n, column=idx["od"]).font = Font(bold=True)
        if {"guncellik_dogrulanmali", "tarih_dogrulanmali", "revizyon_donem_sonrasi",
                "surum_dogrulanmali"} & set(r["flags"]):
            ws.cell(row=n, column=idx["donem_kurali"]).fill = F_LOW
        if r["zayif"]:
            ws.cell(row=n, column=idx["guven"]).fill = F_LOW
            ws.cell(row=n, column=idx["vurgu"]).fill = F_LOW
        if r.get("birim_onay_bekliyor"):
            for k in ("birim_iliskisi", "vurgu", "karar"):
                ws.cell(row=n, column=idx[k]).fill = F_ONERI
            ws.cell(row=n, column=idx["vurgu"]).font = Font(bold=True)
        elif r.get("birim_iliskisi") == "belirsiz":
            ws.cell(row=n, column=idx["birim_iliskisi"]).fill = F_LOW
        if r.get("yeniden_bak"):
            for k in ("yeniden_bak", "bakildi"):
                ws.cell(row=n, column=idx[k]).fill = F_ONERI
            ws.cell(row=n, column=idx["yeniden_bak"]).font = Font(bold=True)
        if r.get("alinti_kaynagi") == "betimleme":
            ws.cell(row=n, column=idx["alinti_kaynagi"]).fill = F_LOW
        for k in ("kanit_adi", "baglanti", "karar", "duzelt_olcut", "duzelt_yuva", "duzelt_asama", "etiket_karari", "etiket_yeni", "not"):
            ws.cell(row=n, column=idx[k]).fill = F_USER
    last = max(ws.max_row, 2)
    for key, opts in (("karar", "kabul,ret,duzelt"), ("bakildi", "evet"), ("etiket_karari", "onayla,duzelt"),
                      ("duzelt_asama", ",".join(LINKS))):
        dv = DataValidation(type="list", formula1=f'"{opts}"', allow_blank=True)
        col = get_column_letter(idx[key])
        dv.add(f"{col}2:{col}{last}")
        ws.add_data_validation(dv)
    ws.freeze_panes = ws.cell(row=2, column=idx["olcut"])
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLS))}{last}"

    s = wb.create_sheet(SHEET_SUM)
    head = [h for h, _ in SUM_COLS]
    s.append(head)
    for i, (h, w) in enumerate(SUM_COLS, 1):
        s.column_dimensions[get_column_letter(i)].width = w
        s.cell(row=1, column=i).font = Font(bold=True)
        s.cell(row=1, column=i).fill = F_USER if h in SUM_USER else F_HEAD
        s.cell(row=1, column=i).alignment = Alignment(wrap_text=True, vertical="top")
    lab = {"var": "var", "dusuk": "düşük", "yok": "—", "yuvasiz": "yuvasız"}
    for c in a.criteria:
        eks = "; ".join(f"OD{c['sonraki_od']} için {e['halka']}: {e['gereken']}"
                        + (" (şablonda yuvası yok)" if e["yuvasiz"] else
                           " → yuva " + ", ".join(y["yuva"] for y in e["yuvalar"]))
                        for e in c["eksik"])
        row = [c["olcut"], c["baslik"], c["od"], c["od_dusuk_dahil"],
               *[f"{lab[c['zincir'][x]['durum']]}" + (f" ({c['zincir'][x]['eslesme']})"
                                                       if c['zincir'][x]['eslesme'] else "") for x in LINKS],
               c["eslesme"], c["belge"], f"{c['yuva_dolu']}/{c['yuva_toplam']}", c["oncelik_grubu"],
               eks, "; ".join(c["notlar"]), c.get("od_onayli") or "", ((c.get("od_onay") or {}).get("not") or "")]
        s.append(row)
        n = s.max_row
        for i in (len(head) - 1, len(head)):
            s.cell(row=n, column=i).fill = F_USER
        for i in range(1, len(head) + 1):
            s.cell(row=n, column=i).alignment = Alignment(wrap_text=True, vertical="top")
        for j, x in enumerate(LINKS, 5):
            d = c["zincir"][x]["durum"]
            s.cell(row=n, column=j).fill = {"var": F_OK, "dusuk": F_LOW, "yuvasiz": F_OFF}.get(
                d, F_GAP if x in {e["halka"] for e in c["eksik"]} else PatternFill())
        if c["od"] >= 4:
            s.cell(row=n, column=3).fill = F_OD4
        s.cell(row=n, column=3).font = Font(bold=True)
    s.freeze_panes = "C2"
    dv = DataValidation(type="list", formula1='"1,2,3,4,5"', allow_blank=True)
    col = get_column_letter(len(head) - 1)
    dv.add(f"{col}2:{col}{max(s.max_row, 2)}")
    s.add_data_validation(dv)

    _write_units(wb, getattr(a, "birim_sayfa", None) or [])

    h = wb.create_sheet(SHEET_HELP)
    h.column_dimensions["A"].width = 120
    for t in HELP:
        h.append([t])
        h.cell(row=h.max_row, column=1).alignment = Alignment(wrap_text=True)

    m = wb.create_sheet(SHEET_META)
    for k, v in (("surum", 1), ("kararlar_sha", a.decisions_sha), ("profil", a.profile or ""),
                 ("calisma_alani", str(a.ws.root)), ("satir", len(a.rows)),
                 ("birim_sha", getattr(a, "birim_sha", "") or ""),
                 ("faaliyet_sha", getattr(a, "faaliyet_sha", "") or ""),
                 ("elle_sha", getattr(a, "elle_sha", "") or "")):
        m.append([k, v])
    m.sheet_state = "hidden"
    from . import sade
    sade.write_sade(wb, a, a.cs)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    wb.save(tmp)
    tmp.replace(path)


def _write_units(wb, items: list[dict]) -> None:
    from .run import BIRIM_SECENEKLERI
    u = wb.create_sheet(SHEET_UNIT)
    u.append([UNIT_NOTE])
    u.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(UNIT_COLS))
    u.cell(row=1, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    u.row_dimensions[1].height = 90
    u.append([h for _, h, _, _ in UNIT_COLS])
    for i, (_, _, w, user) in enumerate(UNIT_COLS, 1):
        c = u.cell(row=2, column=i)
        c.font = Font(bold=True)
        c.fill = F_USER if user else F_HEAD
        c.alignment = Alignment(wrap_text=True, vertical="top")
        u.column_dimensions[get_column_letter(i)].width = w
    idx = {k: i for i, (k, _, _, _) in enumerate(UNIT_COLS, 1)}
    for x in items:
        u.append([x.get(k, "") for k, _, _, _ in UNIT_COLS])
        n = u.max_row
        for i in range(1, len(UNIT_COLS) + 1):
            u.cell(row=n, column=i).alignment = Alignment(wrap_text=True, vertical="top")
        for k in ("insan_birim_iliskisi", "not"):
            u.cell(row=n, column=idx[k]).fill = F_USER
    last = max(u.max_row, 3)
    dv = DataValidation(type="list", formula1=f'"{",".join(BIRIM_SECENEKLERI)}"', allow_blank=True)
    col = get_column_letter(idx["insan_birim_iliskisi"])
    dv.add(f"{col}3:{col}{last}")
    u.add_data_validation(dv)
    u.freeze_panes = "C3"


def read_unit_sheet(path: Path) -> list[dict] | None:
    """Birim sayfasının satırları (iç anahtarlarla); sayfa yoksa (eski tablo) None. Başlık satırı
    'belge kimliği' hücresiyle bulunur (üstteki açıklama satırı atlanır)."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_UNIT not in wb.sheetnames:
            return None
        keys, rows = None, []
        for vals in wb[SHEET_UNIT].iter_rows(values_only=True):
            if keys is None:
                hs = [str(v).strip() if v is not None else "" for v in vals]
                if "belge kimliği" in hs:
                    keys = [UNIT_HEAD.get(h) for h in hs]
                    if "insan_birim_iliskisi" not in keys:
                        raise ValueError(f"'{SHEET_UNIT}' başlıkları bozuk: insan_birim_iliskisi yok")
                continue
            r = {k: ("" if v is None else v) for k, v in zip(keys, vals) if k}
            if str(r.get("doc_id") or "").strip():
                r["doc_id"] = str(r["doc_id"]).strip()
                rows.append(r)
        if keys is None:
            raise ValueError(f"'{SHEET_UNIT}' sayfasında 'belge kimliği' başlığı yok")
        from . import sade
        return sade.merge_units(rows, wb)
    finally:
        wb.close()


def read_od_sheet(path: Path) -> list[dict] | None:
    """"Ölçüt özeti" sayfasından insan OD kararları: [{olcut, od (ham), not, kod_onerisi}]; sayfada
    ONAYLANAN OD sütunu yoksa (eski tablo) None."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_SUM not in wb.sheetnames:
            return None
        it = wb[SHEET_SUM].iter_rows(values_only=True)
        hs = [str(v).strip() if v is not None else "" for v in (next(it, None) or ())]
        if SUM_OD not in hs:
            return None
        i_c, i_od, i_k = hs.index("ölçüt"), hs.index(SUM_OD), hs.index("önerilen OD")
        i_n = hs.index(SUM_NOT) if SUM_NOT in hs else None
        out = []
        for vals in it:
            if not vals or vals[i_c] is None:
                continue
            out.append({"olcut": str(vals[i_c]).strip(),
                        "od": "" if vals[i_od] is None else str(vals[i_od]).strip(),
                        "not": "" if i_n is None or vals[i_n] is None else str(vals[i_n]).strip(),
                        "kod_onerisi": vals[i_k]})
        from . import sade
        return sade.merge_od(out, wb)
    finally:
        wb.close()


def read_review(path: Path) -> tuple[dict, list[dict]]:
    """(meta, satırlar). Satırlar iç anahtarlarla; boş satırlar atlanır."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET_ROWS not in wb.sheetnames:
            raise ValueError(f"'{SHEET_ROWS}' sayfası yok")
        meta = {}
        if SHEET_META in wb.sheetnames:
            for row in wb[SHEET_META].iter_rows(values_only=True):
                if row and row[0]:
                    meta[str(row[0])] = row[1] if len(row) > 1 else None
        it = wb[SHEET_ROWS].iter_rows(values_only=True)
        header = next(it, None) or ()
        keys = [HEAD.get(str(h).strip()) if h is not None else None for h in header]
        if "satir" not in keys or "karar" not in keys:
            raise ValueError("başlıklar bozuk: 'satır kimliği' ve karar sütunu bulunamadı")
        rows = []
        for vals in it:
            r = {k: v for k, v in zip(keys, vals) if k}
            if not r.get("satir"):
                continue
            r = {k: ("" if v is None else v) for k, v in r.items()}
            rows.append(r)
        from . import sade
        return meta, sade.merge_rows(rows, sade.read_inceleme(wb), gruplar=sade.read_gruplar(wb))
    finally:
        wb.close()
