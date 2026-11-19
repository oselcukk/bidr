"""Kanıt adı: classify_fine `kanit_adi`, `bidr name prepare|apply`, review.xlsx düzeltmesi,
öncelik (insan > model > kural) ve file'da kanıt OD'si (düşük güven). Sentetik; model yok."""
from __future__ import annotations

import json

import pytest

from bidr.audit.run import FILES, audit
from bidr.cli import main
from bidr.common import read_jsonl
from bidr.decide import run as DR
from bidr.file import run as FR
from bidr.name import run as NR
from bidr.name.check import check_name
from bidr.name.resolve import NAMES, Resolver, upsert

from test_audit import _fill
from test_file import P2, _index, env  # noqa: F401  (env: fixture)


# -- denetim --------------------------------------------------------------------------------

@pytest.mark.parametrize("s,ok", [
    ("GTÜ Çift Anadal Programı Yönergesi", True),
    ("  MATH113 Örnek Ders İzlencesi. ", True),
    ("Prof. Dr. Ali Veli Ders Dosyası", False),
    ("Doç.Dr. Ayşe Kaya Görevlendirmesi", False),
    ("Ahmet Bey Danışmanlık Yazısı", False),
    ("Sayın Bölüm Başkanı Yazısı", False),
    ("ali.veli@gtu.edu.tr Yazışması", False),
    ("Yönerge", False),                                     # tek sözcük
    (" ".join(["Çok"] * 12), False),                        # uzun
    ("Rapor * Taslak <Sürüm>", False),                      # dosya sisteminde yasaklı karakter
    ("2024/2025 Güz Ders Programı", True),                  # "/" → "-" (reddedilmez)
])
def test_check_name(s, ok):
    ad, errs = check_name(s)
    assert (ad is not None) == ok and bool(errs) != ok
    if ok:
        assert ad == ad.strip() and not ad.endswith(".")


def test_fine_decision_records_name_and_rejects_person():
    ok = DR.evidence_name_of({"kanit_adi": "Bölüm Toplantı Tutanakları"})
    assert ok == {"oneri": "Bölüm Toplantı Tutanakları", "ad": "Bölüm Toplantı Tutanakları",
                  "durum": "kabul", "red": []}
    bad = DR.evidence_name_of({"kanit_adi": "Prof. Dr. Ali Veli Anketi"})
    assert bad["durum"] == "red" and bad["ad"] is None and "kisi_unvan" in bad["red"]
    assert DR.evidence_name_of({}) is None
    # mükerrer üye temsilcinin önerisini devralır
    rep = {"ince": {"karar": "olcut_var", "kanit_adi": bad}, "eslesmeler": []}
    assert DR.rep_output(rep)["kanit_adi"] == "Prof. Dr. Ali Veli Anketi"
    sch = json.loads((DR.TASKS_DIR / DR.FINE / "output.schema.json").read_text(encoding="utf-8"))
    assert "kanit_adi" in sch["required"] and DR.task_version(DR.FINE) == "10"
    assert '"kanit_adi"' in (DR.TASKS_DIR / DR.FINE / "prompt.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("s,ad", [
    ("2024/2025 Güz Ders Programı", "2024-2025 Güz Ders Programı"),
    ("Lisans / Yüksek Lisans Programları", "Lisans - Yüksek Lisans Programları"),
    ("Senato Kararı: Ders Planı Değişikliği", "Senato Kararı - Ders Planı Değişikliği"),
    ("Ölçme\\Değerlendirme | Komisyon Raporu", "Ölçme-Değerlendirme - Komisyon Raporu"),
])
def test_safe_chars_converted_with_note(s, ad):
    from bidr.name.check import check_name_noted
    got, errs, notes = check_name_noted(s)
    assert got == ad and errs == [] and notes and "karakter_donusumu" in notes[0]
    assert check_name(s) == (ad, [])
    assert check_name_noted("Bölüm Toplantı Tutanakları")[2] == []
    # karar kaydı: öneri özgün, ad dönüştürülmüş
    rec = DR.evidence_name_of({"kanit_adi": s})
    assert rec["durum"] == "kabul" and rec["ad"] == ad and rec["oneri"] == s


def test_prompts_list_forbidden_chars_and_unit_rule():
    fine = (DR.TASKS_DIR / DR.FINE / "prompt.md").read_text(encoding="utf-8")
    name = (DR.TASKS_DIR / "name_evidence" / "prompt.md").read_text(encoding="utf-8")
    for p in (fine, name):
        assert '/ \\ : * ? " < > |' in p
    assert "YALNIZ belge metninden" in fine and "kişileri tanıyarak" in fine and "dış bilgiyle" in fine


# -- öncelik --------------------------------------------------------------------------------

def test_resolver_priority(tmp_path):
    docs = {"d": {"doc_id": "d", "doc_type": "anket_sonucu", "baslik": "35 YANIT"}}
    dec = {"d": {"ince": {"kanit_adi": {"ad": "Karar Adı Önerisi", "durum": "kabul"}}}}
    r = Resolver({}, {}, docs)
    assert r.resolve("d")[1] == "kural"
    r = Resolver({}, dec, docs)
    assert r.resolve("d")[:2] == ("Karar Adı Önerisi", "model")
    names = {"d": {"model": {"ad": "Öğrenci Ders Memnuniyet Anketi"}}}
    assert Resolver(names, dec, docs).resolve("d")[:2] == ("Öğrenci Ders Memnuniyet Anketi", "model")
    names["d"]["insan"] = {"ad": "Ders Memnuniyet Anketi 2025"}
    assert Resolver(names, dec, docs).resolve("d")[:2] == ("Ders Memnuniyet Anketi 2025", "insan")
    # kopyanın satırındaki insan düzeltmesi temsilciye geçer
    assert Resolver({"k": {"insan": {"ad": "Kopya Satırından Ad"}}}, {}, docs).resolve("d", ["k"])[1] == "insan"
    # kişi adı içeren kayıt (elle yazılmış dosya) atlanır, uyarı verilir
    ad, src, uy = Resolver({"d": {"insan": {"ad": "Dr. Ali Anketi"}}}, dec, docs).resolve("d")
    assert src == "model" and uy and "reddedildi" in uy[0]
    # upsert: (doc_id, kaynak) başına tek kayıt
    p = tmp_path / NAMES
    upsert(p, [{"doc_id": "d", "kaynak": "model", "ad": "A B"}, {"doc_id": "d", "kaynak": "insan", "ad": "C D"}])
    upsert(p, [{"doc_id": "d", "kaynak": "model", "ad": "E F"}])
    assert sorted((r["kaynak"], r["ad"]) for r in read_jsonl(p)) == [("insan", "C D"), ("model", "E F")]


# -- bidr name prepare|apply ------------------------------------------------------------------

def test_name_prepare_apply(env, capsys):
    ws, _ = env
    st = NR.prepare(ws)
    d = ws / "work" / "name"
    # kopya (mükerrer üye) paketlenmez: adı temsilcinindir
    assert st["paket"] == 3 and sorted(p.stem for p in NR._pkgs(d)) == ["d_anket", "d_karar", "d_kom"]
    pkg = json.loads((d / "d_anket.json").read_text(encoding="utf-8"))
    assert pkg["gorev"] == "name_evidence" and "Anket sonuçları değerlendirildi" in pkg["istem"]
    assert "B.1.1" in pkg["istem"] and "Ogrenci-Anket" not in pkg["istem"] and "anket.pdf" not in pkg["istem"]
    (d / "d_anket.out.json").write_text(json.dumps(
        {"kanit_adi": "Öğrenci Ders Memnuniyet Anketi Sonuçları", "gerekce": "başlık"}), encoding="utf-8")
    (d / "d_kom.out.json").write_text(json.dumps(
        {"kanit_adi": "Prof. Dr. Deneme Kişi Görevlendirmesi", "gerekce": "x"}), encoding="utf-8")
    (d / "d_karar.out.json").write_text(json.dumps(
        {"kanit_adi": "Bölüm Kurulu Kararları 2024/2025", "gerekce": "x"}), encoding="utf-8")
    assert main(["name", "apply", "-w", str(ws), "--model", "test"]) == 1          # kişi adı: reddedildi
    out = capsys.readouterr().out
    assert "reddedildi d_kom" in out and "bekleyen=0" in out
    g = (d / "GECERSIZ.md").read_text(encoding="utf-8")
    assert "d_kom" in g and "d_karar" not in g and '/ \\ : * ? " < > |' in g
    recs = {r["doc_id"]: r for r in read_jsonl(ws / NAMES)}
    assert [(k, r["ad"], r["kaynak"], r["model"]) for k, r in sorted(recs.items())] == [
        ("d_anket", "Öğrenci Ders Memnuniyet Anketi Sonuçları", "model", "test"),
        ("d_karar", "Bölüm Kurulu Kararları 2024-2025", "model", "test")]
    # "/" reddedilmedi, "-" oldu; kayıtta öneri ve not
    assert recs["d_karar"]["oneri"] == "Bölüm Kurulu Kararları 2024/2025"
    assert "karakter_donusumu" in recs["d_karar"]["not"][0] and "not" not in recs["d_anket"]
    # ikinci apply değişmez; prepare model adı olanı yeniden paketlemez
    assert NR.apply(ws, model="test")["degismedi"] == 2
    assert NR.prepare(ws)["zaten_adli"] == 2
    st = NR.prepare(ws, only=["d_anket", "d_kopya"])
    assert st["paket"] == 1 and st["uygun_degil"] == ["d_kopya"]


# -- file: ad kaynağı ve kanıt OD'si ------------------------------------------------------------

def test_file_uses_names_with_priority_and_collisions(env, tmp_path):
    ws, src = env
    upsert(ws / NAMES, [
        {"doc_id": "d_karar", "kaynak": "model", "ad": "Bölüm Kurulu Kararları 2025"},
        {"doc_id": "d_anket", "kaynak": "model", "ad": "Bölüm Kurulu Kararları 2025"},   # çakışma
    ])
    review = tmp_path / "rev"
    review.mkdir()
    upsert(review / NAMES, [{"doc_id": "d_kom", "kaynak": "insan", "ad": "Bölüm Komisyonları ve Görevleri"}])
    out = tmp_path / "out"
    st = FR.run(ws, out=out, source=src, review_dir=review)
    by = {(r["olcut"], r["doc_id"]): r for r in _index(out)}
    kom = by[("A.1.1", "d_kom")]
    assert kom["ad"] == "Bölüm Komisyonları ve Görevleri" and kom["ad_kaynagi"] == "insan"
    # aynı ölçütte aynı ad: mevcut ayrıştırma kuralı (tarih)
    assert by[("B.1.1", "d_karar")]["ad"] == "Bölüm Kurulu Kararları 2025 (2025-05-23)"
    assert by[("B.1.1", "d_anket")]["ad"] == "Bölüm Kurulu Kararları 2025 (2025-06-01)"
    assert by[("A.1.1", "d_karar")]["ad"] == "Bölüm Kurulu Kararları 2025"           # A.1.1'de tek
    assert by[("A.1.1", "d_karar")]["ad_kaynagi"] == "model"
    assert not any("kişi adı" in u for u in st["uyarilar"])
    assert FR.status(out, ws, review)["guncel"]
    upsert(ws / NAMES, [{"doc_id": "d_karar", "kaynak": "model", "ad": "Başka Bir Ad Önerisi"}])
    assert not FR.status(out, ws, review)["guncel"]                                # ad değişti → eski


def _set_guven(ws, did, yuva, guven):
    recs = list(read_jsonl(ws / "decisions.jsonl"))
    for r in recs:
        for m in r.get("eslesmeler") or []:
            if r["doc_id"] == did and m["yuva"] == yuva:
                m["guven"] = guven
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")


def test_file_od_excludes_low_confidence_unless_reviewed(env, tmp_path):
    ws, src = env
    _set_guven(ws, "d_anket", "B.1.1/6", "dusuk")      # K (OD4) düşük güven; Ö (OD4) yüksek
    _set_guven(ws, "d_karar", "B.1.1/3", "dusuk")      # U (OD3) düşük; P (OD2) yüksek
    out = tmp_path / "out"
    FR.run(ws, out=out, source=src)
    by = {(r["olcut"], r["doc_id"]): r for r in _index(out)}
    k = by[("B.1.1", "d_karar")]
    assert k["od"] == "2" and "dusuk_guven_od_disi" in k["isaretler"]            # eskiden OD3
    assert by[("B.1.1", "d_anket")]["od"] == "4"                                   # yüksek güvenli Ö
    # yalnız düşük güvenli eşleşmesi olan: kanıt seçimi (K18) yayımlamaz; gaps.md'de nedeniyle görünür
    _set_guven(ws, "d_kom", "A.1.1/1", "dusuk")
    st = FR.run(ws, out=out, source=src)
    assert not any(r["doc_id"] == "d_kom" for r in _index(out)) and st["elenen"] == 1
    sec = json.loads((out / "evidence-secim.json").read_text(encoding="utf-8"))
    assert [(d["doc_id"], d["neden"]) for d in sec["elenen"]] == [("d_kom", "dusuk_guven")]
    assert "`d_kom`" in (out / "gaps.md").read_text(encoding="utf-8")
    # inceleme kabul ederse katılır
    (ws / FR.REVIEW).write_text(json.dumps(
        {"satir": "d_karar|B.1.1/3", "doc_id": "d_karar", "olcut": "B.1.1", "yuva": "B.1.1/3",
         "karar": "kabul", "duzelt": None, "etiket": None, "not": ""}) + "\n", encoding="utf-8")
    FR.run(ws, out=out, source=src)
    k = next(r for r in _index(out) if r["olcut"] == "B.1.1" and r["doc_id"] == "d_karar")
    assert k["od"] == "3" and "dusuk_guven_od_disi" not in k["isaretler"]


# -- review.xlsx: insan düzeltmesi ---------------------------------------------------------------

def test_review_sheet_name_column_and_apply(env, tmp_path, capsys):
    ws, src = env
    upsert(ws / NAMES, [{"doc_id": "d_anket", "kaynak": "model", "ad": "Öğrenci Anketi Sonuçları"}])
    out = tmp_path / "out"
    a, _ = audit(ws, out=out)
    rows = {r["satir"]: r for r in a.rows}
    assert rows["d_anket|B.1.1/6"]["kanit_adi"] == "Öğrenci Anketi Sonuçları"
    assert rows["d_anket|B.1.1/6"]["kanit_adi_kaynagi"] == "model"
    assert rows["d_kom|A.1.1/1"]["kanit_adi_kaynagi"] == "kural"
    x = out / FILES["xlsx"]
    # aynı belgenin iki satırında farklı ad + kişi adı: geçersiz, kayda girmez
    _fill(x, {"d_karar|B.1.1/3": {"kanit_adi": "Bölüm Kurulu Kararları 2025"},
              "d_karar|B.1.1/1": {"kanit_adi": "Bölüm Kurul Kararı"},
              "d_kom|A.1.1/1": {"kanit_adi": "Prof. Dr. Deneme Görevlendirmesi"}})
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 1
    err = capsys.readouterr().out
    assert "kanit_adi:d_karar" in err and "kanit_adi:d_kom" in err
    assert not (out / NAMES).exists()
    # tek satırda düzeltme yeter; ötekiler öneride kalır
    _fill(x, {"d_karar|B.1.1/1": {"kanit_adi": "Bölüm Kurulu Kararları 2025"},
              "d_kom|A.1.1/1": {"kanit_adi": "Bölüm Komisyonları Görev Tanımları"},
              "d_anket|B.1.1/6": {"kanit_adi": "Öğrenci Anketi Sonuçları"}})       # değişmedi: yok sayılır
    assert main(["audit", "apply", "-w", str(ws), "--out", str(out)]) == 0
    hum = {r["doc_id"]: r for r in read_jsonl(out / NAMES)}
    assert set(hum) == {"d_karar", "d_kom"} and {r["kaynak"] for r in hum.values()} == {"insan"}
    assert hum["d_kom"]["onceki"] and hum["d_karar"]["satirlar"] == ["d_karar|B.1.1/1", "d_karar|B.1.1/3"]
    assert not (ws / NAMES).read_text(encoding="utf-8").count('"insan"')           # WS'ye yazılmaz
    # yeniden audit: insan adı öneri olur; file insan adını kullanır
    a, _ = audit(ws, out=out)
    rows = {r["satir"]: r for r in a.rows}
    assert rows["d_kom|A.1.1/1"]["kanit_adi"] == "Bölüm Komisyonları Görev Tanımları"
    assert rows["d_kom|A.1.1/1"]["kanit_adi_kaynagi"] == "insan"
    assert not any("kanıt adı" in u for u in a.uyarilar)
    FR.run(ws, out=tmp_path / "ev", source=src, review_dir=out)
    idx = {(r["olcut"], r["doc_id"]): r for r in _index(tmp_path / "ev")}
    assert idx[("A.1.1", "d_kom")]["ad"] == "Bölüm Komisyonları Görev Tanımları"
    assert idx[("B.1.1", "d_anket")]["ad_kaynagi"] == "model"
    # uygulanmamış ad düzeltmesi yeniden audit'te kaybolmaz
    _fill(out / FILES["xlsx"], {"d_anket|B.1.1/6": {"kanit_adi": "Ders Memnuniyet Anketi 2025"}})
    a, _ = audit(ws, out=out)
    assert {r["satir"]: r for r in a.rows}["d_anket|B.1.1/6"]["kanit_adi"] == "Ders Memnuniyet Anketi 2025"
    assert any("kanıt adı" in u for u in a.uyarilar)


def test_cli_lists_name(env):
    ws, _ = env
    assert main(["name", "prepare", "-w", str(ws), "--only", "d_anket"]) == 0
    assert P2 and (ws / "work" / "name" / "d_anket.json").exists()


def test_rol_adi_kisi_sayilmaz():
    from bidr.name.check import check_name
    ad, errs = check_name("Öğretim Üyesi Yayın Performansı Takip Tablosu")
    assert ad and not errs
    assert "kisi_unvan" in check_name("Dr. Öğr. Üyesi Ahmet Yılmaz Ders Notu")[1]


# -- adın belgede dayanağı (bidr/name/ground.py) ------------------------------------------------

from bidr.name.ground import grounding  # noqa: E402

_STAJ = ("Doküman No ÖR-0101 ÖRNEK ÜNİVERSİTESİ STAJ ESASLARI Madde 1 Bu esasların amacı öğrencilerin "
         "staj çalışmalarının düzenlenmesidir ve bir kurum içi uygulamadır.")
_ARAS = ("Doküman No ÖR-0202 ÖRNEK ÜNİVERSİTESİ ARAŞTIRMA BİRİMİ YÖNERGESİ Madde 1 Bu yönergenin amacı "
         "araştırma süreçlerinin planlanması ve izlenmesidir. Madde 2 Birim, araştırma politikasını "
         "hazırlar ve her yıl gözden geçirir.")
DERLEME = _STAJ + "\f" + _STAJ.replace("Madde 1", "Madde 5") + "\f" + _ARAS + "\f" + _ARAS
Q_ARAS = "Birim, araştırma politikasını hazırlar ve her yıl gözden geçirir."

KARAR_EKLI = ("BÖLÜM KURULU KARARLARI Toplantı Sayısı 2025/1 Karar 2025/1-1: Örnek dersinin adı bu "
              "dönemden itibaren değiştirilmiştir ve bölüme bildirilmiştir.\f"
              "Duyuru: eğitim programı başvuruları bu ay açılmıştır ve bir hafta sürecektir.\f"
              "Fotoğraf sayfası, bu sayfada görsel bulunmaktadır.\f"
              "Etkinlik Raporu: Bölüm tarafından okul öğrencileri için bir laboratuvar etkinliği "
              "düzenlenmiştir ve katılımcılara deneyler gösterilmiştir.")
Q_ETK = "Bölüm tarafından okul öğrencileri için bir laboratuvar etkinliği düzenlenmiştir"
Q_KARAR = "Örnek dersinin adı bu dönemden itibaren değiştirilmiştir"


def test_grounding_compilation_names_wrong_part():
    """Kodlu derleme: ad ilk parçayı ve uydurma niteliği anlatıyor, alıntı ikinci parçadan."""
    g = grounding("Staj Esasları ve Kurum Yönergeleri Derlemesi", DERLEME, {"C.1.1/1": Q_ARAS})
    assert g["dogrulanmali"] and g["belge"] == ["nitelik_yok"] and g["parca_uyumsuz"] == ["C.1.1/1"]
    g = grounding("Araştırma Birimi Yönergesi", DERLEME, {"C.1.1/1": Q_ARAS})
    assert not g["dogrulanmali"], g


def test_grounding_decision_with_appended_report():
    """Kodsuz derleme: karar + duyuru + fotoğraf + etkinlik raporu; "ve Ekleri" metinde yok."""
    g = grounding("Bölüm Kurulu Kararı 2025-1 ve Ekleri", KARAR_EKLI, {"B.1.5/2": Q_KARAR, "D.1.1/3": Q_ETK})
    assert g["belge"] == ["nitelik_yok"] and g["parca_uyumsuz"] == ["D.1.1/3"]
    g = grounding("Bölüm Kurulu Kararı 2025-1", KARAR_EKLI, {"B.1.5/2": Q_KARAR})
    assert not g["dogrulanmali"], g
    # metinde ek gösterimi varsa "Ekleri" dayanaklıdır
    assert grounding("Bölüm Kurulu Kararı ve Ekleri", KARAR_EKLI.replace("Duyuru:", "Ek-1 Duyuru:"))["belge"] == []


@pytest.mark.parametrize("ad,text,beklenen", [
    ("Örnek Fakülte Yönetmeliği 2031", "Bu metin bir kurul kararıdır ve bölüm tarafından yazılmıştır.",
     ["birim_yok", "sayi_yok", "tur_yok"]),
    # betimleyici tür (rapor, liste) metinde geçmese de dayanaksız sayılmaz
    ("Laboratuvar Etkinliği Raporu", "Bölüm tarafından bir laboratuvar etkinliği düzenlenmiştir.", []),
    # yabancı dildeki belgenin Türkçe adı sözcük sözcük eşlenmez
    ("Uluslararası Öğrenci Kabul Yönergesi", "Directive for the admission of international students "
     "and the rules of the application to the university.", []),
    # ünsüz yumuşaması: "Tutanakları" ~ "TUTANAĞI"
    ("Anket Komisyonu Toplantı Tutanakları", "ANKET KOMİSYONU TOPLANTI TUTANAĞI bu toplantı ile yapıldı.", []),
])
def test_grounding_doc_level(ad, text, beklenen):
    assert grounding(ad, text)["belge"] == beklenen


def test_grounding_long_regulation_article_page():
    """Uzun düzenlemenin ortasındaki sayfa kendi türünü anmayabilir: "Madde N" yapısı yeter."""
    t = ("ÖRNEK ÖĞRENCİ KABUL YÖNERGESİ Madde 1 Bu yönergenin amacı kabul usulüdür.\f"
         "Madde 3 Başvurular bir komisyon tarafından değerlendirilir ve sonuçlandırılır.\f"
         "Ülke sınavları tablosu bu sayfada yer alır ve puanlar listelenir.\f"
         "Madde 9 Kontenjanlar bölüm önerileri ile belirlenir ve ilan edilir.")
    q = {"B.2.3/1": "Madde 9 Kontenjanlar bölüm önerileri ile belirlenir"}
    assert grounding("Öğrenci Kabul Yönergesi", t, q)["parca_uyumsuz"] == []


def test_resolver_flags_ungrounded_model_name():
    docs = {"d": {"doc_id": "d", "doc_type": "bolum_kurulu_karari"}}
    dec = {"d": {"ince": {"kanit_adi": {"ad": "Bölüm Kurulu Kararı 2025-1 ve Ekleri", "durum": "kabul"}},
                 "eslesmeler": [{"yuva": "D.1.1/3", "alinti": Q_ETK, "kabul": True},
                                {"yuva": "B.1.5/2", "alinti": Q_KARAR, "kabul": True}]}}
    r = Resolver({}, dec, docs, text_of=lambda did: KARAR_EKLI)
    ad, src, uy = r.resolve("d")
    assert (ad, src) == ("Bölüm Kurulu Kararı 2025-1 ve Ekleri", "model")      # ad kullanılır
    assert len(uy) == 1 and "doğrulanmalı" in uy[0] and "nitelik_yok" in uy[0] and "D.1.1/3" in uy[0]
    assert r.slot_flags("d", "D.1.1/3") == ["ad_dogrulanmali", "ad_parca_uyumsuz"]
    assert r.slot_flags("d", "B.1.5/2") == ["ad_dogrulanmali"]
    # insan adı denetlenmez; metin verilmemişse denetim yok
    names = {"d": {"insan": {"ad": "Etkinlik Raporu ve Ekleri"}}}
    assert Resolver(names, dec, docs, text_of=lambda did: KARAR_EKLI).resolve("d")[2] == []
    assert Resolver({}, dec, docs).resolve("d")[2] == []


def test_name_task_parts_and_grounding_record(env, capsys):
    ws, _ = env
    NR.prepare(ws)
    d = ws / "work" / "name"
    pkg = json.loads((d / "d_karar.json").read_text(encoding="utf-8"))
    # çok sayfalı belgede alıntının sayfası ve sayfanın başı istemde
    assert "ALINTILARIN SAYFALARI" in pkg["istem"] and "sayfa 2/3" in pkg["istem"]
    (d / "d_anket.out.json").write_text(json.dumps(
        {"kanit_adi": "Öğrenci Anket Uygulama Yönergesi", "gerekce": "x"}), encoding="utf-8")
    (d / "d_karar.out.json").write_text(json.dumps(
        {"kanit_adi": "Bölüm Kurulu Uygulama Kararı", "gerekce": "x"}), encoding="utf-8")
    assert main(["name", "apply", "-w", str(ws), "--model", "test", "--only", "d_anket,d_karar"]) == 0
    out = capsys.readouterr().out
    assert "doğrulanmalı=1" in out and "doğrulanmalı d_anket (tur_yok; parca_uyumsuz: B.1.1/5, B.1.1/6)" in out
    recs = {r["doc_id"]: r for r in read_jsonl(ws / NAMES)}
    assert recs["d_anket"]["dogrulanmali"] == {"belge": ["tur_yok"], "parca_uyumsuz": ["B.1.1/5", "B.1.1/6"]}
    assert "dogrulanmali" not in recs["d_karar"]
    assert "d_anket" in (d / "GECERSIZ.md").read_text(encoding="utf-8")
