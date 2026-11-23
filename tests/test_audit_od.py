"""OD rubriği (K27): kod tarafı savunmalar, faaliyet → audit, K→Ö bağı, OD3/OD5 koşulları ve
insanın onayladığı nihai OD (sentetik veri, model yok). Kurallar: docs/AUDIT.md."""
from __future__ import annotations

import json

import yaml
from openpyxl import load_workbook

from bidr.audit.run import FILES, apply, audit, build, review_state
from bidr.audit.sheet import SHEET_SUM, SUM_OD, SUM_NOT
from bidr.common import read_jsonl


def _m(olcut, yuva, asama, alinti, gerekce="g", guven="orta"):
    od = {"planla": 2, "uygula": 3, "kontrol_et": 4, "onlem_al": 4, "ozgun": 5}[asama]
    return {"olcut": olcut, "yuva": yuva, "asama": asama, "od_onerisi": od, "alinti": alinti,
            "gerekce": gerekce, "guven": guven, "denetim": {"red": [], "isaret": []}, "od_kabul": od, "kabul": True}


# Sentetik kurumun bilinen birim adları: başka birim adı yalnız bu listeden tanınır (config `birim_adlari`).
BIRIM_ADLARI = ["Örnek Bölümü", "Kıyas Bölümü", "Deneme Bölümü"]


def _ws(tmp_path, docs: dict, *, birim="Örnek Bölümü", faaliyet=None):
    """docs: {doc_id: (tür, tarih, metin, [eşleşmeler], birim_iliskisi)}."""
    w = tmp_path / "ws"
    (w / "text").mkdir(parents=True)
    with open(w / "decisions.jsonl", "w", encoding="utf-8") as f:
        for did, (_, _, _, ms, *rel) in docs.items():
            f.write(json.dumps({"doc_id": did, "durum": "ok", "asama": "ince", "karar": "olcut_var",
                                "ince": {"karar": "olcut_var", "gerekce": "", "birim_iliskisi": (rel or ["kendi"])[0]},
                                "eslesmeler": ms}, ensure_ascii=False) + "\n")
    with open(w / "documents.jsonl", "w", encoding="utf-8") as f:
        for did, (t, tarih, _, _, *_r) in docs.items():
            f.write(json.dumps({"doc_id": did, "doc_type": t, "tarih": tarih, "donem": 2025,
                                "donem_ici": (tarih[:4] == "2025") if tarih else None,
                                "calisma_adi": did}, ensure_ascii=False) + "\n")
    for did, (_, _, text, _, *_r) in docs.items():
        (w / "text" / f"{did}.txt").write_text(text, encoding="utf-8")
    if birim:
        (w / "config.yaml").write_text(yaml.safe_dump({"bidr": {"birim": birim, "birim_adlari": BIRIM_ADLARI}},
                                                        allow_unicode=True), encoding="utf-8")
    if faaliyet is not None:
        (w / "faaliyetler.json").write_text(json.dumps(faaliyet, ensure_ascii=False), encoding="utf-8")
    return w


def _c(a, cid):
    return next(c for c in a.criteria if c["olcut"] == cid)


H = "Örnek Üniversitesi · Örnek Bölümü\n\n"


# -- satır düzeyi savunmalar -----------------------------------------------------------------

def test_row_defences(tmp_path):
    docs = {
        "duyuru": ("etkinlik_duyurusu", "2025-03-01", H + "Söyleşi 9 Nisan 2025 günü yapılacaktır.",
                   [_m("B.3.2", "B.3.2/6", "uygula", "Söyleşi 9 Nisan 2025 günü yapılacaktır.")]),
        "gelecek": ("resmi_yazi", "2025-03-01", H + "Bölümde 3 yeni laboratuvar kurulacaktır.",
                    [_m("B.3.3", "B.3.3/2", "uygula", "Bölümde 3 yeni laboratuvar kurulacaktır.")]),
        "form": ("anket_formu", "2025-01-10", H + "1. Ders iyiydi ( ) 1 ( ) 2 ( ) 3",
                 [_m("A.4.2", "A.4.2/2", "uygula", "1. Ders iyiydi")]),
        "dolu_form": ("anket_formu", "2025-06-10", H + "Ders içeriği 4,2 Genel 4,1",
                      [_m("A.4.2", "A.4.2/2", "uygula", "Ders içeriği 4,2 Genel 4,1")]),
        "giris": ("ekran_goruntusu", "2025-03-01", "ÖĞRENCİ BİLGİ SİSTEMİ\nKullanıcı adı: [ ]\nParola: [ ]\n[ Giriş ]",
                  [_m("B.1.6", "B.1.6/3", "uygula", "ÖĞRENCİ BİLGİ SİSTEMİ")]),
        "taslak": ("bidr_raporu", "2025-01-15", H + "Bölümümüz OD5 düzeyindedir.",
                   [_m("A.1.4", "A.1.4/8", "ozgun", "Bölümümüz OD5 düzeyindedir.")]),
        "katilim": ("katilim_listesi", "2025-04-12", H + "Turnuvaya toplam 28 öğrenci katılmıştır.",
                    [_m("B.3.5", "B.3.5/5", "kontrol_et", "toplam 28 öğrenci katılmıştır.")]),
    }
    a = build(_ws(tmp_path, docs))
    k = a.by_key
    assert k["duyuru|B.3.2/6"]["etkin_asama"] == "planla" and "gerceklesme_kaniti_yok" in k["duyuru|B.3.2/6"]["flags"]
    assert k["gelecek|B.3.3/2"]["etkin_asama"] == "planla"
    assert k["form|A.4.2/2"]["etkin_asama"] == "planla" and "bos_form" in k["form|A.4.2/2"]["flags"]
    assert k["dolu_form|A.4.2/2"]["etkin_asama"] == "uygula"                  # sonuçlu form kayıttır
    assert not k["giris|B.1.6/3"]["sayilir"] and "bilgisiz_ekran" in k["giris|B.1.6/3"]["flags"]
    assert not k["taslak|A.1.4/8"]["sayilir"] and "haric_tur" in k["taslak|A.1.4/8"]["flags"]
    assert k["katilim|B.3.5/5"]["etkin_asama"] == "uygula" and "katilim_izleme_degil" in k["katilim|B.3.5/5"]["flags"]
    gaps = __import__("bidr.audit.report", fromlist=["gaps_md"]).gaps_md(a)
    assert "## Kodun düşürdüğü ya da saymadığı eşleşmeler" in gaps and "boş form" in gaps


def test_human_accept_overrides_text_heuristics(tmp_path):
    docs = {"duyuru": ("resmi_yazi", "2025-03-01", H + "Söyleşi yapılacaktır.",
                       [_m("B.3.2", "B.3.2/6", "uygula", "Söyleşi yapılacaktır.")])}
    w = _ws(tmp_path, docs)
    dec = {"satir": "duyuru|B.3.2/6", "doc_id": "duyuru", "olcut": "B.3.2", "yuva": "B.3.2/6", "karar": "kabul",
           "duzelt": None, "etiket": None, "not": ""}
    r = build(w, review={dec["satir"]: dec}).by_key["duyuru|B.3.2/6"]
    assert r["etkin_asama"] == "uygula" and "gerceklesme_kaniti_yok" not in r["flags"]


def test_superseded_regulation_and_own_regulation(tmp_path):
    eski = "# ÖRNEK BÖLÜMÜ STAJ USUL VE ESASLARI\n\nMadde 3 – Staj süresi 20 iş günüdür.\n"
    yeni = ("# ÖRNEK BÖLÜMÜ STAJ USUL VE ESASLARI\n\nMadde 3 – Staj süresi 30 iş günüdür.\n\nMadde 9 – Bu "
            "Usul ve Esasların yürürlüğe girmesiyle 12 Mart 2019 tarihli Örnek Bölümü Staj Usul ve Esasları "
            "yürürlükten kalkar.\n")
    docs = {"eski": ("yonerge", "2019-03-12", eski, [_m("B.1.4", "B.1.4/2", "planla", "Staj süresi 20 iş günüdür.")]),
            "yeni": ("yonerge", "2025-03-05", yeni, [_m("B.1.4", "B.1.4/2", "planla", "Staj süresi 30 iş günüdür.")])}
    a = build(_ws(tmp_path, docs))
    e, y = a.by_key["eski|B.1.4/2"], a.by_key["yeni|B.1.4/2"]
    assert not e["sayilir"] and "yururlukten_kalkmis" in e["flags"]
    assert y["sayilir"] and "kurum_geneli" not in y["flags"]                  # bölümün kendi usul belgesi
    assert any(d["isaret"] == "yururlukten_kalkmis" for d in _c(a, "B.1.4")["donem_sonrasi"])
    # birim adı bilinmiyorsa (config yok) tür tavanı eskisi gibi
    b = build(_ws(tmp_path / "b", docs, birim=None))
    assert "kurum_geneli" in b.by_key["yeni|B.1.4/2"]["flags"]


def test_unit_relation_from_text(tmp_path):
    docs = {
        "kiyas": ("bolum_kurulu_karari", "2025-05-07", "Örnek Üniversitesi · Kıyas Bölümü\n\nKıyas Bölümü dersi açtı.",
                  [_m("B.1.1", "B.1.1/3", "uygula", "Kıyas Bölümü dersi açtı.")]),
        "fak": ("faaliyet_raporu", "2025-12-01", "ÖRNEK FAKÜLTESİ RAPORU\n\nFakültemizin bütün bölümlerinde staj yapılmıştır.",
                [_m("B.1.4", "B.1.4/4", "uygula", "Fakültemizin bütün bölümlerinde staj yapılmıştır.")]),
        "fyk": ("yonetim_kurulu_karari", "2025-06-11",
                "FAKÜLTE YÖNETİM KURULU KARARI\n\nMadde 1 – Kıyas Bölümü laboratuvarının yenilenmesine karar verildi.\n\n"
                "Madde 2 – Örnek Bölümü programında MAT 315 dersinin açılmasına karar verildi.\n",
                [_m("B.3.3", "B.3.3/5", "uygula", "Kıyas Bölümü laboratuvarının yenilenmesine karar verildi."),
                 _m("B.1.5", "B.1.5/2", "uygula", "Örnek Bölümü programında MAT 315 dersinin açılmasına karar verildi.")],
                "ust_birim_bu_birim_hakkinda"),
    }
    a = build(_ws(tmp_path, docs))
    k = a.by_key["kiyas|B.1.1/3"]
    assert k["birim_iliskisi"] == "belirsiz" and k["birim_onay_bekliyor"] and not k["sayilir"]
    assert "birim_iliskisi_kod" in k["flags"] and any(x["doc_id"] == "kiyas" for x in a.birim["belirsiz"])
    f = a.by_key["fak|B.1.4/4"]
    assert f["birim_iliskisi"] == "fakulte_geneli" and f["etkin_asama"] == "planla"
    assert not a.by_key["fyk|B.3.3/5"]["sayilir"] and "madde_baska_birim" in a.by_key["fyk|B.3.3/5"]["flags"]
    assert a.by_key["fyk|B.1.5/2"]["sayilir"]


# -- ölçüt düzeyi: K→Ö, OD3, OD5, fotoğraf ---------------------------------------------------

def _chain(extra: dict) -> dict:
    return {
        "plan": ("bolum_kurulu_karari", "2025-01-15", H + "İzleme usulü kabul edildi.",
                 [_m("B.1.5", "B.1.5/1", "planla", "İzleme usulü kabul edildi.")]),
        "uyg": ("mufredat", "2025-09-01", H + "Öğretim planı ilişki tablosunu içerir.",
                [_m("B.1.5", "B.1.5/2", "uygula", "Öğretim planı ilişki tablosunu içerir.")]),
        "izl": ("degerlendirme_raporu", "2025-07-10", H + "PÇ4 ulaşma düzeyi %52, hedefin altında.",
                [_m("B.1.5", "B.1.5/3", "kontrol_et", "PÇ4 ulaşma düzeyi %52, hedefin altında.")]),
        **extra}


def test_improvement_needs_monitoring_link(tmp_path):
    kopuk = {"onl": ("bolum_kurulu_karari", "2025-09-03", H + "Öğretim üyesinin talebi üzerine MAT 214 seçmeli oldu.",
                     [_m("B.1.5", "B.1.5/5", "onlem_al", "Öğretim üyesinin talebi üzerine MAT 214 seçmeli oldu.")])}
    a = build(_ws(tmp_path / "a", _chain(kopuk)))
    r = a.by_key["onl|B.1.5/5"]
    assert r["etkin_asama"] == "uygula" and "onlem_izlemeye_dayanmiyor" in r["flags"] and _c(a, "B.1.5")["od"] == 3
    bagli = {"onl": ("bolum_kurulu_karari", "2025-09-03", H + "Değerlendirme raporundaki bulgular görüşüldü; MAT 214 değişti.",
                     [_m("B.1.5", "B.1.5/5", "onlem_al", "MAT 214 değişti.")])}
    b = build(_ws(tmp_path / "b", _chain(bagli)))
    assert b.by_key["onl|B.1.5/5"]["etkin_asama"] == "onlem_al" and _c(b, "B.1.5")["od"] == 4
    assert any("izlemeden ayrı belgede" in n for n in _c(b, "B.1.5")["notlar"])
    # izleme sonradan (iyileştirmeden sonra) geldiyse bağ kurulmaz
    sonra = {"onl": ("bolum_kurulu_karari", "2025-03-03", H + "Anket sonuçlarına göre MAT 214 değişti.",
                     [_m("B.1.5", "B.1.5/5", "onlem_al", "MAT 214 değişti.")])}
    assert build(_ws(tmp_path / "c", _chain(sonra))).by_key["onl|B.1.5/5"]["etkin_asama"] == "uygula"


def test_intent_info_and_version_note_are_not_improvement(tmp_path):
    ex = {"niyet": ("komisyon_tutanagi", "2025-08-01", H + "Kazanımların güncellenmesi önerilmiştir.",
                    [_m("B.1.5", "B.1.5/5", "onlem_al", "Kazanımların güncellenmesi önerilmiştir.")]),
          "bilgi": ("toplanti_tutanagi", "2025-08-02", H + "Sonuçlar kurul üyelerinin bilgisine sunulmuştur.",
                    [_m("B.1.5", "B.1.5/4", "onlem_al", "Sonuçlar kurul üyelerinin bilgisine sunulmuştur.")]),
          "surum": ("ders_programi", "2025-10-28", H + "Bu takvim derslik çakışması nedeniyle revize edilmiştir.",
                    [_m("B.1.5", "B.1.5/6", "onlem_al", "Bu takvim derslik çakışması nedeniyle revize edilmiştir.")])}
    a = build(_ws(tmp_path, _chain(ex)))
    assert a.by_key["niyet|B.1.5/5"]["etkin_asama"] == "kontrol_et"
    assert a.by_key["bilgi|B.1.5/4"]["etkin_asama"] == "uygula"
    assert a.by_key["surum|B.1.5/6"]["etkin_asama"] == "uygula"
    assert _c(a, "B.1.5")["od"] == 3


def test_same_document_closed_loop(tmp_path):
    t = H + "Anket sonuçları incelenmiştir. MAT 102 ödev sayısının azaltılmasına karar verilmiştir."
    docs = {"tut": ("komisyon_tutanagi", "2025-09-15", t,
                    [_m("A.4.2", "A.4.2/5", "kontrol_et", "Anket sonuçları incelenmiştir."),
                     _m("A.4.2", "A.4.2/3", "onlem_al", "MAT 102 ödev sayısının azaltılmasına karar verilmiştir.")])}
    a = build(_ws(tmp_path, docs))
    assert a.by_key["tut|A.4.2/3"]["etkin_asama"] == "onlem_al"
    assert any("kapalı döngü" in n for n in _c(a, "A.4.2")["notlar"])


def test_od5_needs_independent_and_sustained_evidence(tmp_path):
    base = _chain({"onl": ("bolum_kurulu_karari", "2025-09-03", H + "Değerlendirme raporu bulgularına göre değişti.",
                           [_m("B.1.5", "B.1.5/5", "onlem_al", "Değerlendirme raporu bulgularına göre değişti.")])})
    oz = {"web": ("web_sayfasi", "2025-03-03", H + "Bölümümüz öncü ve örnek gösterilen uygulamalara sahiptir. "
                  "Öğrencilerimiz derslerde aktif rol alır ve yenilikçi yöntemler kullanılır.",
                  [_m("B.1.5", "B.1.5/7", "ozgun", "Bölümümüz öncü ve örnek gösterilen uygulamalara sahiptir.")])}
    a = build(_ws(tmp_path / "a", {**base, **oz}))
    assert "ozgun_kanitsiz" in a.by_key["web|B.1.5/7"]["flags"] and _c(a, "B.1.5")["od"] == 4
    dis = {"yazi": ("resmi_yazi", "2025-11-14",
                    "REKTÖRLÜK YAZISI\n\nÖrnek Bölümünde 2021 yılından bu yana yürütülen program iyi uygulama "
                    "örneği seçilmiştir.", [_m("B.1.5", "B.1.5/7", "ozgun", "iyi uygulama örneği seçilmiştir.")],
                    "ust_birim_bu_birim_hakkinda")}
    b = build(_ws(tmp_path / "b", {**base, **dis}))
    c = _c(b, "B.1.5")
    assert c["od"] == 5 and c["od_kod_onerisi"] == 5 and c["od_onayli"] is None
    assert any("insan onayı bekliyor" in n for n in c["notlar"])
    tek = {"yazi": ("resmi_yazi", "2025-11-14", "REKTÖRLÜK YAZISI\n\nÖrnek Bölümünün programı iyi uygulama örneği seçilmiştir.",
                    [_m("B.1.5", "B.1.5/7", "ozgun", "iyi uygulama örneği seçilmiştir.")], "ust_birim_bu_birim_hakkinda")}
    assert _c(build(_ws(tmp_path / "c", {**base, **tek})), "B.1.5")["od"] == 4        # tek dönem


def test_od3_spread_and_photo(tmp_path):
    tek = {"rap": ("faaliyet_raporu", "2025-12-01", H + "Bir derste proje sunumu yapılmıştır.",
                   [_m("B.2.1", "B.2.1/1", "uygula", "Bir derste proje sunumu yapılmıştır.")])}
    c = _c(build(_ws(tmp_path / "a", tek)), "B.2.1")
    assert c["od"] == 3 and c["uygulama_yayilimi"] == "kismi" and any("OD3 kısmi" in n for n in c["notlar"])
    kurul = {"kar": ("bolum_kurulu_karari", "2025-02-01", H + "Bütün derslerde sunum uygulanmasına karar verilmiştir.",
                     [_m("B.2.1", "B.2.1/1", "uygula", "Bütün derslerde sunum uygulanmasına karar verilmiştir.")])}
    assert _c(build(_ws(tmp_path / "b", kurul)), "B.2.1")["uygulama_yayilimi"] == "yaygin"
    # sahnesi belirsiz fotoğraf destekleyicidir: sayılmaz
    foto = {"foto": ("fotograf", "2025-05-01", H + "[GÖRSEL] Tahtada çözülmüş bir örnek.",
                     [_m("B.2.1", "B.2.1/1", "uygula", "Tahtada çözülmüş bir örnek.")])}
    a = build(_ws(tmp_path / "c", foto))
    assert "fotograf_destekleyici" in a.by_key["foto|B.2.1/1"]["flags"] and _c(a, "B.2.1")["od"] < 3
    # etkinlik sahnesi (öğrenciler, sunum) gerçekleşmeyi kanıtlar: uygula sayılır
    foto = {"foto": ("fotograf", "2025-05-01", H + "[GÖRSEL] Öğrenciler proje sunumu yapıyor.",
                     [_m("B.2.1", "B.2.1/1", "uygula", "Öğrenciler proje sunumu yapıyor.")])}
    a = build(_ws(tmp_path / "d", foto))
    r = a.by_key["foto|B.2.1/1"]
    assert r["sayilir"] and r["etkin_asama"] == "uygula" and not {"fotograf_destekleyici", "fotograf_mekan"} & set(r["flags"])
    assert _c(a, "B.2.1")["od"] == 3


# -- faaliyet → audit ----------------------------------------------------------------------

def _fa(id_, ad, durum, asamalar: dict, yalniz=False, eksik=()):
    return {"id": id_, "ad": ad, "tarih": "2025-04-09", "durum": durum, "yalniz_duyuru": yalniz,
            "asamalar": {k: list(v) for k, v in asamalar.items()}, "eksik": list(eksik),
            "belgeler": [{"doc_id": d, "asama": k} for k, v in asamalar.items() for d in v]}


def test_activity_records_drive_stages(tmp_path):
    docs = {
        "afis": ("web_sayfasi", "2025-03-01", H + "Kariyer Günü etkinliği düzenledik ve mezunlar konuştu.",
                 [_m("B.3.2", "B.3.2/6", "uygula", "Kariyer Günü etkinliği düzenledik ve mezunlar konuştu.")]),
        "anket": ("anket_sonucu", "2025-05-01", H + "Söyleşi anketi: memnuniyet ortalaması 3,1.",
                  [_m("B.3.5", "B.3.5/5", "kontrol_et", "memnuniyet ortalaması 3,1.")]),
        "karar": ("bolum_kurulu_karari", "2025-05-20", H + "Söyleşi süresinin uzatılmasına karar verilmiştir.",
                  [_m("B.3.5", "B.3.5/6", "onlem_al", "Söyleşi süresinin uzatılmasına karar verilmiştir.")]),
        "tutanak": ("toplanti_tutanagi", "2025-04-10", H + "Söyleşi yapılmış, 40 öğrenci katılmıştır.",
                    [_m("B.3.5", "B.3.5/4", "onlem_al", "Söyleşi yapılmış, 40 öğrenci katılmıştır.")]),
    }
    fa = {"sema": 1, "faaliyetler": [
        _fa("F001", "Kariyer Günü", "gerceklesme_kanitsiz", {"duyuru": ["afis"]}, yalniz=True,
            eksik=["gerceklesme yok", "katilim yok", "degerlendirme yok"]),
        _fa("F002", "Mezun Söyleşisi", "gerceklesme_kanitli",
            {"gerceklesme": ["tutanak"], "degerlendirme": ["anket"], "iyilestirme": ["karar"]})]}
    w = _ws(tmp_path, docs, faaliyet=fa)
    out = tmp_path / "out"
    a, paths = audit(w, out=out)
    k = a.by_key
    assert k["afis|B.3.2/6"]["etkin_asama"] == "planla" and "gerceklesme_kaniti_yok" in k["afis|B.3.2/6"]["flags"]
    t = k["tutanak|B.3.5/4"]           # faaliyette gerçekleşme: model "onlem_al" dese de uygula
    assert t["etkin_asama"] == "uygula" and "faaliyet_asamasi_uyusmuyor" in t["flags"]
    assert k["karar|B.3.5/6"]["etkin_asama"] == "onlem_al"
    c = _c(a, "B.3.5")
    assert any("kapalı döngü" in n for n in c["notlar"]) and c["faaliyetler"][0]["id"] == "F002"
    gaps = paths["gaps"].read_text(encoding="utf-8")
    assert "## Gerçekleşmesi kanıtlanmamış faaliyetler" in gaps and "F001 Kariyer Günü" in gaps
    js = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert next(x for x in js["olcutler"] if x["olcut"] == "B.3.2")["faaliyetler"][0]["yalniz_duyuru"]
    # faaliyetler.json değişince tablo güncel sayılmaz
    st = review_state(out, w)
    assert st["guncel"]
    (w / "faaliyetler.json").write_text(json.dumps({"sema": 1, "faaliyetler": []}), encoding="utf-8")
    assert not review_state(out, w)["guncel"]
    # faaliyet dosyası yoksa bugünkü davranış
    (w / "faaliyetler.json").unlink()
    b = build(w)
    assert b.by_key["tutanak|B.3.5/4"]["etkin_asama"] == "uygula"      # katılım ≠ izleme/önlem: yine düşer
    assert "faaliyet_asamasi_uyusmuyor" not in b.by_key["tutanak|B.3.5/4"]["flags"]
    assert not b.faaliyetler


# -- insanın onayladığı nihai OD ---------------------------------------------------------------

def test_human_final_od_separate_from_code(tmp_path):
    docs = _chain({})
    w = _ws(tmp_path, docs)
    out = tmp_path / "out"
    audit(w, out=out)
    x = out / FILES["xlsx"]
    wb = load_workbook(x)
    s = wb[SHEET_SUM]
    head = [c.value for c in s[1]]
    assert SUM_OD in head and SUM_NOT in head
    for i in range(2, s.max_row + 1):
        if s.cell(row=i, column=1).value == "B.1.5":
            s.cell(row=i, column=head.index(SUM_OD) + 1).value = 2
            s.cell(row=i, column=head.index(SUM_NOT) + 1).value = "komisyon: uygulama kanıtı zayıf"
        if s.cell(row=i, column=1).value == "B.1.1":
            s.cell(row=i, column=head.index(SUM_OD) + 1).value = "yedi"
    wb.save(x)
    assert review_state(out, w)["uygulanmamis_duzeltme"] == 2
    r = apply(w, out=out)
    assert r["od_onayli"] == 1 and "od:B.1.1" in r["od_gecersiz"]
    rec = {x["olcut"]: x for x in read_jsonl(out / FILES["od"])}
    assert rec["B.1.5"]["od"] == 2 and rec["B.1.5"]["kod_onerisi"] == 3 and rec["B.1.5"]["kaynak"] == "insan"
    js = json.loads((out / FILES["json"]).read_text(encoding="utf-8"))
    c = next(c for c in js["olcutler"] if c["olcut"] == "B.1.5")
    assert c["od"] == 3 and c["od_kod_onerisi"] == 3 and c["od_onayli"] == 2
    assert any("komisyonun onayladığı düzey OD2" in n for n in c["notlar"])
    # yeniden üretilen tabloda onay dolu kalır
    audit(w, out=out)
    s = load_workbook(out / FILES["xlsx"])[SHEET_SUM]
    row = next(r for r in s.iter_rows(values_only=True) if r[0] == "B.1.5")
    assert row[head.index(SUM_OD)] == 2
