"""Birim sinyalleri (bidr/audit/savunma.py): metindeki açık birim ifadesi (ad, program adı, bölüm
sayfası yolu, ders kodu öneki) bölümün kendi belgesini `belirsiz`/kurum geneli saydırmaz; model
`belirsiz` dediyse `kendi` önerilir; fakülteye göre maddeli düzenlemede başka fakültenin maddesi
sayılmaz. Birim profili config.yaml ya da kurum profilinden gelir. Yalnız sentetik veri."""
from __future__ import annotations

import yaml

from bidr.audit.run import build
from bidr.decide import prompt as P

from test_audit_od import _m, _ws


def _cfg(w, **extra):
    sec = {"birim": "Örnek Bölümü", **extra}
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
        # sinyal var ama başka birimin adı da geçiyor → belirsiz kalır
        "karisik": ("resmi_yazi", "2025-02-01", "Kıyas Bölümü Başkanlığına\nProgramı Örnek\n" + q,
                    [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
        # hiçbir açık ifade yok → belirsiz kalır (sinyal uydurulmaz)
        "yok": ("bilinmiyor", "2025-02-01", "YAYINLAR 2025\n1. Bir makale.\n" + q,
                [_m("B.1.3", "B.1.3/2", "uygula", q)], "belirsiz"),
    }
    a = build(_cfg(_ws(tmp_path, docs), ders_kodlari=["ORN"]))
    k = a.by_key["kod|B.1.3/2"]
    assert k["birim_iliskisi"] == "kendi" and k["sayilir"] and not k["birim_onay_bekliyor"]
    assert "birim_iliskisi_kod" in k["flags"] and "birim kodca önerildi" in k["vurgu"]
    for d in ("azinlik", "karisik", "yok"):
        r = a.by_key[f"{d}|B.1.3/2"]
        assert r["birim_iliskisi"] == "belirsiz" and r["birim_onay_bekliyor"] and not r["sayilir"], d
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
    _cfg(w, kurum="ornek")
    assert P.unit_profile(w) == {"birim": "Örnek Bölümü", "fakulte": "Örnek Fakültesi",
                                 "ders_kodlari": ["ORN", "ÖRN"]}
    info = P.unit_info(w)
    assert P.render_unit(info) == "Birim: Örnek Bölümü\nFakülte: Örnek Fakültesi\nKurum: Örnek Üniversitesi"
    _cfg(w, kurum="ornek", fakulte="Başka Fakülte", ders_kodlari=["XYZ"])    # config kurum profilini aşar
    assert P.unit_profile(w)["fakulte"] == "Başka Fakülte" and P.unit_profile(w)["ders_kodlari"] == ["XYZ"]
    _cfg(w, kurum="ornek", birim="Kıyas Bölümü")                             # profilde kaydı yok: boş
    assert P.unit_profile(w) == {"birim": "Kıyas Bölümü", "fakulte": "", "ders_kodlari": []}


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
