"""Birim sinyalleri (bidr/audit/savunma.py): metindeki açık birim ifadesi (ad, program adı, bölüm
sayfası yolu, ders kodu öneki) bölümün kendi belgesini `belirsiz`/kurum geneli saydırmaz; model
`belirsiz` dediyse `kendi` önerilir; fakülteye göre maddeli düzenlemede başka fakültenin maddesi
sayılmaz. Birim profili config.yaml ya da kurum profilinden gelir. Yalnız sentetik veri."""
from __future__ import annotations

import yaml

from bidr.audit.run import build
from bidr.decide import prompt as P

from test_audit_od import BIRIM_ADLARI, _m, _ws


def _cfg(w, **extra):
    sec = {"birim": "Örnek Bölümü", "birim_adlari": BIRIM_ADLARI, **extra}
    (w / "config.yaml").write_text(yaml.safe_dump({"bidr": sec}, allow_unicode=True), encoding="utf-8")
    return w


# AKTS sayfası menüsü: satır sonundaki "Bölüm Başkanı / Bölüm Olanakları", "Eğitim Türü ve Dili";
# ders kodu birimin öneki. Eski sezgi bunları "başka birim adı (baskani, dili)" sayıyordu.
AKTS = ("AKTS Bilgi Paketi\n\nAkademik Programlar\n Lisans\n Örnek\n Eğitim Türü ve Dili\n Bölüm Başkanı\n"
        " Bölüm Olanakları\n\nDers Bilgi Formu ( ORN 113 )\nDersin program çıktılarına katkısı tabloda verilmiştir.\n")
SONUC = ("Değerlendirme Form Sonucu\nŞube Kodu/Ders Kodu 1/ORN407\nProgramı Örnek (%100 İngilizce)\n"
         "Birinci Bölüm\nİkinci Bölüm\nDersi değerlendiren öğrenci sayısı 13, ortalama 4,31.\n")
SAYFA = ("ÖRNEK\n 1. Akademik\n 3. Fakülteler\n 5. Örnek Fakültesi\n 7. Bölümler\n 9. Örnek\n 13. Projeler\n"
         "Devam Eden Projeler\nYürütücü: Proje No: 125X001, 2025-2027\n"
         "İletişim © Örnek Üniversitesi Rektörlüğü, 41400, Örnekşehir\n")


def test_own_signals_keep_unit_documents(tmp_path):
    q_akts = "Dersin program çıktılarına katkısı tabloda verilmiştir."
    q_son = "Dersi değerlendiren öğrenci sayısı 13, ortalama 4,31."
    q_say = "Yürütücü: Proje No: 125X001, 2025-2027"
    docs = {
        "akts": ("ders_bilgi_formu", "2025-02-01", AKTS, [_m("B.1.3", "B.1.3/2", "uygula", q_akts)]),
        "sonuc": ("anket_sonucu", "2025-06-26", SONUC, [_m("A.4.2", "A.4.2/2", "uygula", q_son)]),
        "sayfa": ("web_sayfasi", "2025-11-01", SAYFA, [_m("C.2.2", "C.2.2/3", "uygula", q_say)]),
    }
    a = build(_cfg(_ws(tmp_path, docs), ders_kodlari=["ORN"]))
    for key in ("akts|B.1.3/2", "sonuc|A.4.2/2", "sayfa|C.2.2/3"):
        r = a.by_key[key]
        assert r["birim_iliskisi"] == "kendi", key
        assert not r["birim_onay_bekliyor"] and "birim_iliskisi_kod" not in r["flags"], key
        assert "kurum_geneli" not in r["flags"], key           # bölüm sayfası kurum geneli değil
    assert not a.birim["belirsiz"]


def test_belirsiz_promoted_only_with_explicit_signal(tmp_path):
    q = "Dersin program çıktılarına katkısı tabloda verilmiştir."
    docs = {
        # model belirsiz dedi; metinde birimin ders kodu (çoğunluk) var → kod `kendi` önerir
        "kod": ("ders_bilgi_formu", "2025-02-01", "Ders Bilgi Formu ORN 210\n" + q,
                [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
        # birimin kodu azınlıkta (başka bölümün müfredatında servis dersi) → sinyal değil
        "azinlik": ("mufredat", "2025-02-01", "KIY 101\nKIY 102\nKIY 201\nORN 101\n" + q,
                    [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
        # sinyal var ama başka birimin adı da geçiyor → belirsiz kalır; kendi sinyali olduğundan çelişki değil
        "karisik": ("resmi_yazi", "2025-02-01", "Kıyas Bölümü Başkanlığına\nProgramı Örnek\n" + q,
                    [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
        # hiçbir açık ifade yok → belirsiz kalır (sinyal uydurulmaz), yükleyenin belgesi varsayılır
        "yok": ("bilinmiyor", "2025-02-01", "YAYINLAR 2025\n1. Bir makale.\n" + q,
                [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
        # birimin hiçbir sinyali yok, başka birimin adı geçiyor → açık çelişki: sorulur
        "baska": ("resmi_yazi", "2025-02-01", "Kıyas Bölümü Başkanlığına\n" + q,
                  [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
    }
    a = build(_cfg(_ws(tmp_path, docs), ders_kodlari=["ORN"]))
    k = a.by_key["kod|B.1.3/2"]
    assert k["birim_iliskisi"] == "kendi" and k["sayilir"] and not k["birim_onay_bekliyor"]
    # model belirsiz dedi, kod birimi buldu: varsayımla aynı sonuç, sorulmaz (bilgi işareti)
    assert "birim_iliskisi_kod_bilgi" in k["flags"] and "birim_iliskisi_kod" not in k["flags"]
    assert "birim kodca bulundu" in k["vurgu"]
    # yükleyen birimin belgesi varsayılır (kullanıcı kararı 2026-11-26): ilişki belirsiz kalır, satır sayılır
    for d in ("azinlik", "karisik", "yok"):
        r = a.by_key[f"{d}|B.1.3/2"]
        assert r["birim_iliskisi"] == "belirsiz" and not r["birim_onay_bekliyor"] and r["sayilir"], d
        assert "birim_varsayildi" in r["flags"], d
    # birimin sinyali yokken başka birimin adı: açık çelişki, onaylanana dek sayılmaz
    r = a.by_key["baska|B.1.3/2"]
    assert r["birim_onay_bekliyor"] and not r["sayilir"] and "birim_varsayildi" not in r["flags"]
    assert [x["doc_id"] for x in a.birim["belirsiz"]] == ["baska"]
    assert [x["doc_id"] for x in a.birim_sayfa] == ["baska"]
    # ders kodu öneki yapılandırılmamışsa kod sinyal saymaz
    b = build(_cfg(_ws(tmp_path / "b", docs)))
    assert b.by_key["kod|B.1.3/2"]["birim_iliskisi"] == "belirsiz"


def test_other_unit_still_detected(tmp_path):
    t = "Kıyas Bölümü Kurulu toplandı.\nDanışma kurulunun güncellenmesine karar verildi."
    docs = {"kiyas": ("bolum_kurulu_karari", "2025-05-07", t,
                      [_m("A.1.1", "A.1.1/3", "uygula", "Danışma kurulunun güncellenmesine karar verildi.")])}
    r = build(_cfg(_ws(tmp_path, docs), ders_kodlari=["ORN"])).by_key["kiyas|A.1.1/3"]
    assert r["birim_iliskisi"] == "belirsiz" and r["birim_onay_bekliyor"]


# Fakülteye göre maddeli kurum yönergesi: tam metin ve başlığı içermeyen sayfa parçası (aynı tarih/tür)
YONERGE = ("ATAMA KOŞULLARI YÖNERGESİ\n\nMADDE 1. Genel ilkeler bütün fakültelere uygulanır.\n\n"
           "  ÖRNEK FAKÜLTESİ ve ÜÇÜNCÜ FAKÜLTESİ\n  YÜKSELTME VE ATAMA KOŞULLARI\n\n"
           "MADDE 3. Profesör kadrolarına atamada toplam en az 400 puan almış olmak.\n\n"
           "  KIYAS FAKÜLTESİ YÜKSELTME VE ATAMA KOŞULLARI\n\n"
           "MADDE 9. Profesör kadrolarına atamada toplam en az 300 puan almış olmak.\n\n"
           "  ENSTİTÜLERDE ATAMA KOŞULLARI\n\nMADDE 12. Enstitülerde ilgili fakültenin koşulları uygulanır.\n")
PARCA = "Sayfa 6\n\nMADDE 9. Profesör kadrolarına atamada toplam en az 300 puan almış olmak.\n"


def test_other_faculty_clause_not_counted(tmp_path):
    q_kiyas = "MADDE 9. Profesör kadrolarına atamada toplam en az 300 puan almış olmak."
    q_own = "MADDE 3. Profesör kadrolarına atamada toplam en az 400 puan almış olmak."
    q_ortak = "MADDE 12. Enstitülerde ilgili fakültenin koşulları uygulanır."
    docs = {
        "tam": ("yonerge", "2023-09-27", YONERGE,
                [_m("B.4.1", "B.4.1/1", "planla", q_own), _m("B.4.2", "B.4.2/1", "planla", q_ortak),
                 _m("C.3.2", "C.3.2/1", "planla", q_kiyas)], "kurum_geneli"),
        "parca": ("yonerge", "2023-09-27", PARCA, [_m("B.4.1", "B.4.1/1", "planla", q_kiyas)], "kurum_geneli"),
    }
    a = build(_cfg(_ws(tmp_path, docs), fakulte="Örnek Fakültesi"))
    k = a.by_key
    for key in ("parca|B.4.1/1", "tam|C.3.2/1"):
        assert not k[key]["sayilir"] and "madde_baska_fakulte" in k[key]["flags"], key
        assert "başka fakültenin maddesinden" in k[key]["vurgu"], key
    assert "madde_baska_fakulte" not in k["tam|B.4.1/1"]["flags"]     # birimin fakültesinin maddesi
    assert "madde_baska_fakulte" not in k["tam|B.4.2/1"]["flags"]     # ortak bölüm
    gaps = __import__("bidr.audit.report", fromlist=["gaps_md"]).gaps_md(a)
    assert "başka fakültenin maddesinden" in gaps
    # fakülte bilinmiyorsa denetim yok
    b = build(_cfg(_ws(tmp_path / "b", docs)))
    assert "madde_baska_fakulte" not in b.by_key["parca|B.4.1/1"]["flags"]


def test_unit_profile_sources(tmp_path, monkeypatch):
    inst = tmp_path / "kurumlar"
    inst.mkdir()
    (inst / "ornek.yaml").write_text(yaml.safe_dump({
        "kurum": "ornek", "ad": "Örnek Üniversitesi",
        "birimler": [{"ad": "ÖRNEK BÖLÜMÜ", "fakulte": "Örnek Fakültesi", "ders_kodlari": ["ORN", "ÖRN"]}]},
        allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("BIDR_INSTITUTIONS_DIR", str(inst))
    w = tmp_path / "w"
    w.mkdir()
    _cfg(w, kurum="ornek", birim_adlari=["Kıyas Bölümü"])
    assert P.unit_profile(w) == {"birim": "Örnek Bölümü", "fakulte": "Örnek Fakültesi",
                                 "ders_kodlari": ["ORN", "ÖRN"],
                                 "birim_adlari": ["Kıyas Bölümü", "ÖRNEK BÖLÜMÜ"]}   # config + kurum profili
    info = P.unit_info(w)
    assert P.render_unit(info) == "Birim: Örnek Bölümü\nFakülte: Örnek Fakültesi\nKurum: Örnek Üniversitesi"
    _cfg(w, kurum="ornek", fakulte="Başka Fakülte", ders_kodlari=["XYZ"])    # config kurum profilini aşar
    assert P.unit_profile(w)["fakulte"] == "Başka Fakülte" and P.unit_profile(w)["ders_kodlari"] == ["XYZ"]
    _cfg(w, kurum="ornek", birim="Kıyas Bölümü", birim_adlari=[])            # profilde kaydı yok: boş
    assert P.unit_profile(w) == {"birim": "Kıyas Bölümü", "fakulte": "", "ders_kodlari": [],
                                 "birim_adlari": ["ÖRNEK BÖLÜMÜ"]}


def test_config_accepts_unit_signals(tmp_path):
    from bidr.init.config import validate
    src = tmp_path / "kaynak"
    src.mkdir()
    ans = {"kaynak": str(src), "birim": "Örnek Bölümü", "profil": "akademik_bolum", "donem": 2025,
           "fakulte": "Örnek Fakültesi", "ders_kodlari": ["ORN"]}
    sec, errs = validate(ans, tmp_path / "ws")
    assert not errs and sec["fakulte"] == "Örnek Fakültesi" and sec["ders_kodlari"] == ["ORN"]
    sec, errs = validate({k: v for k, v in ans.items() if k not in ("fakulte", "ders_kodlari")}, tmp_path / "ws")
    assert not errs and "fakulte" not in sec and "ders_kodlari" not in sec


def test_rules_in_prompt_and_skill():
    from pathlib import Path
    from bidr.decide.run import FINE, TASKS_DIR
    fine = (TASKS_DIR / FINE / "prompt.md").read_text(encoding="utf-8")
    assert "kurum sitesinde olsa da \"kendi\"" in fine and "ders kodu" in fine
    assert "fakültesinin ya da bütün fakültelere ortak maddeyi" in P.evidence_principles()
    skill = (Path(__file__).resolve().parents[1] / ".claude/skills/bidr-rapor/SKILL.md").read_text(encoding="utf-8")
    assert "emin olmadığın satır `ret`" not in skill                 # yetki devrinde bölüm belgesi atılmaz
    assert "işaretsiz satır\n     `kabul`" in skill and "\"birim doğrulanamıyor\"" in skill


# -- başka birim adı yalnız bilinen birim listesinden (kurum profili gtu `birimler:`) ----------

def _gtu(w):
    (w / "config.yaml").write_text(yaml.safe_dump({"bidr": {"birim": "Matematik Bölümü", "kurum": "gtu"}},
                                                  allow_unicode=True), encoding="utf-8")
    return w


# imzalı tutanak: kişi adı + soyad (büyük harf) + "Bölüm Başkanı"; sıradan sözcük + "Bölüm Kurulu"
TUTANAK = ("TOPLANTI TUTANAĞI\nToplantı Tarihi: 12.03.2025\nDeğerlendirme Turu Bölüm Kurulunda görüşüldü.\n"
           "Ders planındaki güncellemeler kabul edilmiştir.\n\n"
           "Prof. Dr. Deneme KİŞİOĞLU  Bölüm Başkanı\nDoç. Dr. Örnek SOYADLI  Bölüm Sekreteri\n"
           "Dr. Öğr. Üyesi Kişi ADSIZ  Bölüm Kurulu Üyesi\n")


def test_signed_minutes_not_other_unit(tmp_path):
    q = "Ders planındaki güncellemeler kabul edilmiştir."
    docs = {"tut": ("toplanti_tutanagi", "2025-03-12", TUTANAK, [_m("B.1.3", "B.1.3/2", "uygula", q)])}
    w = _gtu(_ws(tmp_path, docs))
    a = build(w)
    r = a.by_key["tut|B.1.3/2"]
    assert r["birim_iliskisi"] == "kendi" and not r["birim_onay_bekliyor"] and r["sayilir"]
    assert not a.birim["belirsiz"]


def test_known_other_unit_detected_unknown_ignored(tmp_path):
    q = "Ders planındaki güncellemeler kabul edilmiştir."
    docs = {
        "fiz": ("resmi_yazi", "2025-03-12", "Fizik Bölümü Başkanlığı\n" + q, [_m("B.1.3", "B.1.3/2", "uygula", q)]),
        "uyd": ("resmi_yazi", "2025-03-12", "Xyzabc Bölümü Başkanlığı\n" + q, [_m("B.1.3", "B.1.3/2", "uygula", q)]),
    }
    a = build(_gtu(_ws(tmp_path, docs)))
    f_ = a.by_key["fiz|B.1.3/2"]
    assert f_["birim_iliskisi"] == "belirsiz" and f_["birim_onay_bekliyor"]
    assert "(fizik)" in str([x for x in a.birim["belirsiz"] if x["doc_id"] == "fiz"])
    u = a.by_key["uyd|B.1.3/2"]
    assert u["birim_iliskisi"] == "kendi" and not u["birim_onay_bekliyor"]      # uydurma ad birim sayılmaz


def test_other_units_matcher():
    from bidr.audit.savunma import other_units, unit_names
    from bidr.decide.prompt import unit_profile
    names = unit_names(["Matematik Bölümü", "Kimya Bölümü", "Kimya Mühendisliği Bölümü",
                        "Moleküler Biyoloji ve Genetik Bölümü"])
    raw = ("Kimya Mühendisliği Bölümünün önerisi\nMoleküler Biyoloji ve Genetik Bölüm Başkanlığına\n"
           "Matematik Bölümü\nAd KİMYA Bölüm Okuması\nProf. Dr. Ad SOYAD Bölüm Başkanı\n")
    assert other_units(raw, names, "matematik") == {"kimya muhendisligi", "moleküler biyoloji ve genetik"
                                                    .replace("ü", "u")}
    assert other_units("KİMYA BÖLÜMÜ BAŞKANLIĞI", names, "matematik") == {"kimya"}
    assert other_units("Xyz Bölümü", names, "matematik") == set()
    assert other_units("Kimya Bölümü", (), "matematik") == set()                # liste yoksa tanı yok


def test_gtu_profile_lists_departments(tmp_path):
    from bidr.decide.prompt import unit_profile
    w = _gtu(tmp_path)
    adlar = unit_profile(w)["birim_adlari"]
    for ad in ("Matematik Bölümü", "Fizik Bölümü", "Kimya Bölümü", "Moleküler Biyoloji ve Genetik Bölümü",
               "Veri Bilimi ve Analitiği Bölümü", "Bilgisayar Mühendisliği Bölümü", "İşletme Bölümü"):
        assert ad in adlar


def test_official_long_name_is_own_unit(tmp_path):
    """Yapılandırmadaki ad kurum profilindeki resmî adın kısaltmasıysa ("Deneme Bölümü" ↔ "Deneme ve
    Analiz Bölümü") resmî ad birim sinyalidir, başka birim sayılmaz; aday birden çoksa eşlenmez."""
    from bidr.audit.savunma import own_aliases
    adlar = ["Örnek Bölümü", "Deneme ve Analiz Bölümü", "Kıyas Bölümü"]
    assert own_aliases("Deneme Bölümü", adlar) == ("deneme ve analiz",)
    assert own_aliases("Örnek Bölümü", adlar + ["Örnek Mühendisliği Bölümü"]) == ()     # birebir ad var
    assert own_aliases("Kıyas", ["Kıyas Mühendisliği Bölümü", "Kıyas Eğitimi Bölümü"]) == ()  # iki aday
    q = "Ders kazanımları gözden geçirilmiştir."
    docs = {
        "resmi": ("resmi_yazi", "2025-02-01", "Deneme ve Analiz Bölümü Başkanlığına\n" + q,
                  [_m("B.1.3", "B.1.3/2", "uygula", q)], "kendi"),
        "baska": ("resmi_yazi", "2025-02-01", "Kıyas Bölümü Başkanlığına\n" + q,
                  [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
    }
    w = _ws(tmp_path, docs)
    (w / "config.yaml").write_text(yaml.safe_dump({"bidr": {"birim": "Deneme Bölümü", "birim_adlari": adlar}},
                                                  allow_unicode=True), encoding="utf-8")
    a = build(w)
    r = a.by_key["resmi|B.1.3/2"]
    assert r["birim_iliskisi"] == "kendi" and r["sayilir"] and not r["birim_onay_bekliyor"]
    r = a.by_key["baska|B.1.3/2"]
    assert r["birim_onay_bekliyor"] and not r["sayilir"]


def test_kisa_ad_resmi_kayda_baglanir(tmp_path, monkeypatch):
    """Yapılandırmadaki kısa ad ("Deneme Bölümü") kurum profilindeki resmî adın önekiyse ("Deneme ve Analiz
    Bölümü") karar aşaması da o kaydın fakültesini ve ders kodlarını kullanır (audit'in `own_aliases` kuralı);
    `tam_ad` eski (birebir) davranışı verir. Fakülte bilinince başka fakültenin maddesi sayılmaz."""
    inst = tmp_path / "kurumlar"
    inst.mkdir()
    (inst / "ornek.yaml").write_text(yaml.safe_dump({
        "kurum": "ornek", "ad": "Örnek Üniversitesi",
        "birimler": [{"ad": "Deneme ve Analiz Bölümü", "fakulte": "Örnek Fakültesi", "ders_kodlari": ["DNA"]},
                     {"ad": "Kıyas Bölümü", "fakulte": "Kıyas Fakültesi"}]}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setenv("BIDR_INSTITUTIONS_DIR", str(inst))
    w = tmp_path / "w"
    w.mkdir()
    (w / "config.yaml").write_text(yaml.safe_dump({"bidr": {"birim": "Deneme Bölümü", "kurum": "ornek"}},
                                                  allow_unicode=True), encoding="utf-8")
    up = P.unit_profile(w)
    assert up["fakulte"] == "Örnek Fakültesi" and up["ders_kodlari"] == ["DNA"]
    assert up["resmi_ad"] == "Deneme ve Analiz Bölümü"
    assert P.unit_profile(w, tam_ad=True)["fakulte"] == "" and "fakulte" not in P.unit_info(w, tam_ad=True)
    assert P.unit_info(w)["fakulte"] == "Örnek Fakültesi"
    from bidr.audit.savunma import Savunma
    sv = Savunma.load(w, {}, 2025)                 # audit (fakülte maddesi denetimi, ders kodu sinyali) aynı kaydı görür
    assert sv.fakulte == "Örnek Fakültesi" and sv.ders_kodlari == ("DNA",)


def test_fakulte_satiri_karari_eskitmez(tmp_path, monkeypatch):
    """Önek kuralıyla pakete eklenen ortak "Fakülte:" satırı belgeye özgü girdi değildir: eski kararın birim
    girdisi eski bilgiyle üretilmiş metne eşitse belge `kural_degisti` (model yeniden çalışmaz)."""
    from bidr.decide import run as R
    old = R.girdi_sha({"birim": P.render_unit({"birim": "Deneme Bölümü", "kurum": "Örnek Üniversitesi"})})
    yeni = {"birim": P.render_unit({"birim": "Deneme Bölümü", "kurum": "Örnek Üniversitesi",
                                    "fakulte": "Örnek Fakültesi"}), "adaylar": "a", "belge_bilgisi": "b",
            "belge_metni": "m"}
    sec = {"girdi_sha": {**R.girdi_sha({k: yeni[k] for k in ("adaylar", "belge_bilgisi", "belge_metni")}), **old}}
    meta = {"birim_eski": P.render_unit({"birim": "Deneme Bölümü", "kurum": "Örnek Üniversitesi"})}
    assert R.doc_inputs_same(None, "d", "fine", sec, yeni, meta) is True
    assert R.doc_inputs_same(None, "d", "fine", sec, yeni, {}) is False
