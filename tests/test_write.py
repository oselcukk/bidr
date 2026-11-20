"""`bidr write`: metin denetimleri ve prepare/apply (sentetik; ajan cevapları elle yazılır)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bidr.criteria.loader import load_criteria
from bidr.write import run as W
from bidr.write import sources as S
from bidr.write import text as T

DOC_A = ("Ders Planı Güncelleme İş Akışı. Bölüm Müfredat Komisyonu ders planında yapılacak değişiklik için "
         "uygunluk kontrolü yapar. Ders planı değişikliği Bölüm Kurulunda görüşülür ve karara bağlanır.")
DOC_B = ("Ders Bilgi Formu. Dersin öğrenme kazanımları tanımlanmıştır. Toplam iş yükü: 150. "
         "AKTS kredisi, toplam iş yükünün 25'e bölümüdür. Program Çıktılarına Katkıları bölümü doludur.")
DOC_C = "Bölüm danışma kurulu toplantısında öğrenci anket sonuçları görüşülmüş ve iki dersin içeriği güncellenmiştir."

GOOD = {"paragraflar": [
    {"metin": "Bölümümüzde ders planı değişiklikleri için süreç tanımlanmıştır; değişiklik Bölüm Kurulunda "
              "görüşülür [1_OD2]."},
    {"metin": "Ders bilgi formlarında AKTS kredisinin toplam iş yükünün 25'e bölümü olduğu belirtilmektedir "
              "[2_OD3]. Örneğin incelenen formda toplam iş yükü 150 olarak verilmiştir [2_OD3]."}],
    "onceki_yila_gore": ""}


def make_report_ws(root: Path, *, od: int = 3, with_c: bool = False, previous: dict | None = None,
                   notes: dict | None = None) -> Path:
    """Sentetik çalışma alanı: text/, evidence-index.csv, audit-olcutler.json."""
    (root / "text").mkdir(parents=True, exist_ok=True)
    docs = {"aaaa000000000001": DOC_A, "bbbb000000000002": DOC_B}
    if with_c:
        docs["cccc000000000003"] = DOC_C
    for k, v in docs.items():
        (root / "text" / f"{k}.txt").write_text(v, encoding="utf-8")
    rows = [
        {"kanit_no": "1_OD2", "olcut": "B.1.1", "od": 2, "ad": "Ders Planı Güncelleme İş Akışı",
         "dosya": "B/B.1/B.1.1/1_OD2.pdf", "doc_id": "aaaa000000000001", "sayfalar": "",
         "yuvalar": json.dumps(["B.1.1/2"]),
         "alintilar": json.dumps(["Ders planı değişikliği Bölüm Kurulunda görüşülür"], ensure_ascii=False)},
        {"kanit_no": "2_OD3", "olcut": "B.1.1", "od": 3, "ad": "Ders Bilgi Formu",
         "dosya": "B/B.1/B.1.1/2_OD3.pdf", "doc_id": "bbbb000000000002", "sayfalar": "",
         "yuvalar": json.dumps(["B.1.1/3"]),
         "alintilar": json.dumps(["AKTS kredisi, toplam iş yükünün 25'e bölümüdür."], ensure_ascii=False)},
    ]
    if with_c:
        rows.append({"kanit_no": "3_OD4", "olcut": "B.1.1", "od": 4, "ad": "Danışma Kurulu Tutanağı",
                     "dosya": "B/B.1/B.1.1/3_OD4.pdf", "doc_id": "cccc000000000003", "sayfalar": "",
                     "yuvalar": json.dumps(["B.1.1/6"]),
                     "alintilar": json.dumps(["öğrenci anket sonuçları görüşülmüş"], ensure_ascii=False)})
    with open(root / S.INDEX, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    audit = {"surum": 1, "olcutler": [
        {"olcut": "B.1.1", "baslik": "Programların tasarımı ve onayı", "od": od,
         "zincir_kisa": "P+ U+ K- Ö- Z-",
         "zincir": {"planla": {"durum": "var", "eslesme": 1}, "uygula": {"durum": "var", "eslesme": 1}},
         "sonraki_od": od + 1,
         "eksik": [{"halka": "kontrol_et", "gereken": "izleme/ölçme sonucu",
                    "yuvalar": [{"yuva": "B.1.1/6", "metin": "izleme kanıtları"}]}],
         "notlar": ["örnek not"]},
        {"olcut": "B.1.2", "od": 1, "eksik": [], "notlar": []}]}
    (root / S.AUDIT).write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    if previous:
        d = root / "onceki"
        d.mkdir(exist_ok=True)
        for k, v in previous.items():
            (d / f"{k}.txt").write_text(v, encoding="utf-8")
    if notes:
        import yaml
        (root / S.NOTES).write_text(yaml.safe_dump(notes, allow_unicode=True), encoding="utf-8")
    return root


def answer(root: Path, olcut: str, out, stage: str = "write") -> None:
    p = root / "work" / stage / f"{olcut}.out.json"
    p.write_text(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False), encoding="utf-8")


# -- metin denetimleri ---------------------------------------------------------------------------

def test_split_sentences():
    s = ("Bölümümüzde ör. MAT 113 vb. dersler B.1.1. ölçütüne göre 3. Dönem planlarında yer alır [1_OD2]. "
         "İkinci cümle burada biter. [2_OD3] Üçüncü cümle de biter [1_OD2].")
    out = T.split_sentences(s)
    assert out == ["Bölümümüzde ör. MAT 113 vb. dersler B.1.1. ölçütüne göre 3. Dönem planlarında yer alır [1_OD2].",
                   "İkinci cümle burada biter. [2_OD3]", "Üçüncü cümle de biter [1_OD2]."]
    assert T.citations(out[1]) == ["2_OD3"]


@pytest.mark.parametrize("sentence,kod", [
    ("Bölümümüzde süreç tanımlanmıştır.", "atifsiz"),
    ("Bölümümüzde süreç tanımlanmıştır [9_OD3].", "bilinmeyen_atif"),
    ("Bölümümüzde süreç tanımlanmıştır [1_OD3].", "bilinmeyen_atif"),        # OD listedekinden farklı
    ("Bölümümüzde süreç tanımlanmıştır [B.1.1-2-OD3].", "gecersiz_atif_bicimi"),
    ("Süreç sistematik olarak izlenmektedir [2_OD3].", "od_asimi"),
    ("Bölüm bu ölçütte OD4 düzeyindedir [2_OD3].", "od_asimi"),
    ("Uygulamalar içselleştirilmiştir [2_OD3].", "od_asimi"),
    ("Ders planları izlenmekte ve iyileştirilmektedir [2_OD3].", "kanitsiz_ust_duzey"),
    ("Bölümümüzde süreç titizlikle yürütülmektedir [2_OD3].", "yasak_ifade"),
    ("Ders planları mükemmel biçimde hazırlanmıştır [2_OD3].", "yasak_ifade"),
    ("Komisyon kararları dikkate alınmalıdır [2_OD3].", "yasak_ifade"),
    ("İzleme mekanizmasının kurulması planlanmaktadır [2_OD3].", "gelecek_vaat"),
    ("Anket sistemi kurulacaktır [2_OD3].", "gelecek_vaat"),
    ("Anket sistemi kurulacaktır [komisyon].", "komisyon_bilgisi_yok"),
    # aracın iç dili (kör test 2026-11-20)
    ("Eksik kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok [2_OD3].", "ic_dil"),
    ("Bölüm kurulu kararı OD'ye sayılmamıştır [2_OD3].", "ic_dil"),
    ("Yönerge yalnız kurum geneli belgelerle eşleşmiştir [1_OD2].", "ic_dil"),
    ("Kanıt kurum_geneli olarak işaretlidir [1_OD2].", "ic_dil"),
])
def test_check_sentence_flags(sentence, kod):
    got = T.check_sentence(sentence, index_nos={"1_OD2", "2_OD3"}, od=3, komisyon=False)
    assert kod in {x["kod"] for x in got}, got


@pytest.mark.parametrize("sentence,komisyon,nos", [
    ("Bölümümüzde ders planı değişiklikleri Bölüm Kurulunda görüşülür [1_OD2], [2_OD3].", False, None),
    ("Ders planları izlenmekte ve iyileştirilmektedir [3_OD4].", False, {"3_OD4"}),   # OD4 kanıtla
    ("Ders planlarının izlenmesine ilişkin bir kayıt bulunmamaktadır [2_OD3].", False, None),  # olumsuz
    ("Anket sisteminin 2026 yılında kurulacağı komisyonca bildirilmiştir [komisyon].", True, None),
    ("Anket sistemi kurulacaktır [komisyon].", True, None),
    ("Ders öğrenme kazanımları program çıktılarıyla ilişkilendirilmiştir [2_OD3].", False, None),
    ("Bölümümüzde araştırma odak alanları belirlenmiştir [1_OD2].", False, None),
])
def test_check_sentence_passes(sentence, komisyon, nos):
    nos = nos or {"1_OD2", "2_OD3"}
    assert T.check_sentence(sentence, index_nos=nos, od=3, komisyon=komisyon) == []


def test_od_claim_in_text_checks_level_5():
    s = "Bölümümüzde özgün bir uygulama yürütülmektedir [3_OD4]."
    assert {"kanitsiz_ust_duzey", "od_asimi"} & {x["kod"] for x in
                                                 T.check_sentence(s, index_nos={"3_OD4"}, od=4, komisyon=False)}


# -- kaynaklar ----------------------------------------------------------------------------------------

def test_index_quotes_and_context(tmp_path):
    ws = make_report_ws(tmp_path)
    idx = S.load_index(ws / S.INDEX)
    assert [r["kanit_no"] for r in idx["B.1.1"]] == ["1_OD2", "2_OD3"]
    assert idx["B.1.1"][0]["alintilar"] == ["Ders planı değişikliği Bölüm Kurulunda görüşülür"]
    from bidr.llm import verify_quote
    ctx = S.evidence_context(DOC_A, idx["B.1.1"][0]["alintilar"], verify_quote)
    assert ctx[0]["alinti_belgede"] and "Müfredat Komisyonu" in ctx[0]["baglam"]
    ctx = S.evidence_context(DOC_A, ["bu alıntı belgede hiç geçmeyen bir cümledir"], verify_quote)
    assert ctx[0]["alinti_belgede"] is False and ctx[0]["baglam"] == ""


def test_previous_from_docx(tmp_path):
    import docx
    d = docx.Document()
    t = d.add_table(rows=4, cols=2)
    t.cell(0, 0).merge(t.cell(0, 1)).text = "B.1.1. Programların tasarımı ve onayı\nTanım"
    t.cell(1, 0).text = "Örnek Kanıtlar:\nx"
    t.cell(1, 1).text = "1"
    t.cell(2, 0).merge(t.cell(2, 1)).text = "Açıklamalar:\n\nGeçen yıl metni [B.1.1-1-OD3]."
    t.cell(3, 0).merge(t.cell(3, 1)).text = "Kanıtlar:\n[B.1.1-1-OD3] Yönetmelik"
    p = tmp_path / "eski.docx"
    d.save(p)
    prev = S.previous_from_docx(p)
    assert prev == {"B.1.1": {"aciklama": "Geçen yıl metni [B.1.1-1-OD3].", "kanitlar": "[B.1.1-1-OD3] Yönetmelik"}}


def test_previous_from_dir(tmp_path):
    (tmp_path / "B.1.1.txt").write_text("Açıklamalar:\n\nEski metin.\n\nKanıtlar:\n[B.1.1-1-OD3]. X\n", encoding="utf-8")
    (tmp_path / "notlar.txt").write_text("başka", encoding="utf-8")
    prev = S.previous_from_dir(tmp_path)
    assert prev == {"B.1.1": {"aciklama": "Eski metin.", "kanitlar": "[B.1.1-1-OD3]. X"}}


# -- prepare / apply ------------------------------------------------------------------------------------

def test_prepare_package(tmp_path):
    ws = make_report_ws(tmp_path, previous={"B.1.1": "Açıklamalar:\nGeçen yılın üslup örneği.\n"})
    st = W.prepare(ws, onceki=ws / "onceki")
    assert st["paket"] == 1 and st["kanitsiz"] == ["B.1.2"] and st["bekleyen"] == 1
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    ist = pkg["istem"]
    for s in ("[1_OD2] Ders Planı Güncelleme İş Akışı", "bağlam 1: «", "Önerilen OD: 3",
              "izleme/ölçme sonucu", "Geçen yılın üslup örneği", "Bir önceki yıla göre farklı neler var?",
              "Bölümümüzde", "B.1.1/2: Program tasarımı ve onayı süreçlerinin"):
        assert s in ist, s
    assert pkg["meta"]["od_onerisi"] == 3 and pkg["meta"]["onceki"] == "onceki"
    assert [k["no"] for k in pkg["meta"]["kanitlar"]] == ["1_OD2", "2_OD3"]
    assert (ws / "work/write/README.md").exists()
    # aynı girdiyle ikinci prepare paketi değiştirmez
    assert W.prepare(ws, onceki=ws / "onceki")["yeni"] == 0


def test_apply_writes_text_per_contract(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    st = W.apply(ws, model="test:ajan")
    assert st["islenen"] == 1 and not st["gecersiz"]
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    assert t["olcut"] == "B.1.1" and t["od_onerisi"] == 3 and t["durum"] == "taslak"
    assert t["paragraflar"][1]["atiflar"] == ["2_OD3"]
    assert t["kanitlar"] == [{"no": "1_OD2", "ad": "Ders Planı Güncelleme İş Akışı", "dosya": "B/B.1/B.1.1/1_OD2.pdf"},
                             {"no": "2_OD3", "ad": "Ders Bilgi Formu", "dosya": "B/B.1/B.1.1/2_OD3.pdf"}]
    assert t["eksikler"][0].startswith("OD4 için kontrol") and "örnek not" in t["eksikler"]
    assert t["kaynak"]["model"] == "test:ajan" and t["kaynak"]["gorev_surumu"] == "3"
    assert W.apply(ws)["degismedi"] == 1                       # aynı cevap yeniden işlenmez
    assert W.prepare(ws)["zaten_tamam"] == 1                   # yazılmış metin yeniden paketlenmez


@pytest.mark.parametrize("metin,kod", [
    ("Bölümümüzde ders planı değişiklikleri Bölüm Kurulunda görüşülür. İkinci cümle atıflıdır [1_OD2].", "atifsiz"),
    ("Bölümümüzde ders planı değişiklikleri Bölüm Kurulunda görüşülür [7_OD3].", "bilinmeyen_atif"),
    ("Bölümümüzde program tasarım süreci sistematik olarak izlenmekte ve iyileştirilmektedir [2_OD3].", "od_asimi"),
    ("Bölümümüzde izleme mekanizmasının kurulması planlanmaktadır [1_OD2].", "gelecek_vaat"),
])
def test_apply_rejects_bad_text(tmp_path, metin, kod):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", {"paragraflar": [{"metin": metin}], "onceki_yila_gore": ""})
    st = W.apply(ws)
    assert "B.1.1" in st["gecersiz"] and any(kod in e for e in st["gecersiz"]["B.1.1"]), st
    assert not (ws / "texts/B.1.1.json").exists()
    assert kod in (ws / "work/write/GECERSIZ.md").read_text(encoding="utf-8")


def test_apply_rejects_uncited_comparison_and_schema(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", {**GOOD, "onceki_yila_gore": "Önceki yıla göre yeni bir uygulama başlamıştır."})
    assert any("o.1 atifsiz" in e for e in W.apply(ws)["gecersiz"]["B.1.1"])
    answer(ws, "B.1.1", "metin ama JSON değil")
    assert "B.1.1" in W.apply(ws)["gecersiz"]


def test_komisyon_note_allows_plan_sentence(tmp_path):
    ws = make_report_ws(tmp_path, notes={"B.1.1": ["Öğrenci iş yükü anketi 2026 güz döneminde uygulanacaktır."]})
    W.prepare(ws)
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert "iş yükü anketi 2026" in pkg["istem"] and pkg["meta"]["komisyon"] is True
    out = {"paragraflar": GOOD["paragraflar"] + [
        {"metin": "Öğrenci iş yükü anketinin 2026 güz döneminde uygulanacağı komisyonca bildirilmiştir [komisyon]."}],
        "onceki_yila_gore": ""}
    answer(ws, "B.1.1", out)
    assert W.apply(ws)["islenen"] == 1


def test_index_change_makes_package_stale(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    make_report_ws(tmp_path, with_c=True)                   # paketten sonra yeni kanıt
    st = W.apply(ws)
    assert st["eski"] == ["B.1.1"] and not (ws / "texts/B.1.1.json").exists()


def test_cli(tmp_path, capsys):
    from bidr.cli import main
    ws = make_report_ws(tmp_path)
    assert main(["write", "prepare", "-w", str(ws), "--only", "B.1.1"]) == 0
    answer(ws, "B.1.1", {"paragraflar": [{"metin": "Atıfsız bir cümle yazılmıştır."}], "onceki_yila_gore": ""})
    assert main(["write", "apply", "-w", str(ws)]) == 1
    assert "atifsiz" in capsys.readouterr().out
    answer(ws, "B.1.1", GOOD)
    assert main(["write", "apply", "-w", str(ws), "--model", "x"]) == 0
    assert main(["write", "prepare", "-w", str(ws), "--only", "Z.9.9"]) == 2


def test_ongorulmektedir_mevzuat_dili_kabul():
    from bidr.write.text import check_sentence
    s = "Yönergede taleplerin Muafiyet ve İntibak Komisyonunca incelenmesi öngörülmektedir [1_OD2]."
    assert not [i for i in check_sentence(s, index_nos={"1_OD2"}, od=2, komisyon=False) if i["kod"] == "gelecek_vaat"]
    s2 = "Bölümde yeni bir anket uygulanması öngörülmektedir [1_OD2]."
    assert [i for i in check_sentence(s2, index_nos={"1_OD2"}, od=2, komisyon=False) if i["kod"] == "gelecek_vaat"]


def test_belge_icerigi_aktaran_fiiller_kabul():
    from bidr.write.text import check_sentence
    ok = ["Misyon ifadesinde araştırma yapılması hedeflenmektedir [1_OD2].",
          "Yönergede öğrencilerin 30 AKTS almaları tavsiye edilmektedir [1_OD2].",
          "Rehberde tez önerisinin savunulması öngörülmektedir [1_OD2]."]
    for s in ok:
        assert not check_sentence(s, index_nos={"1_OD2"}, od=2, komisyon=False), s
    kotu = ["Bölümde yeni bir anket yapılması hedeflenmektedir [1_OD2].",
            "Öğrencilere düzenli çalışmaları tavsiye edilir [1_OD2]."]
    for s in kotu:
        assert check_sentence(s, index_nos={"1_OD2"}, od=2, komisyon=False), s


# -- özel adlar ve kısaltmalar (kör test bulguları) --------------------------------------------------

@pytest.mark.parametrize("sentence", [
    "Ders izlenceleri GTÜ Yapay Zekâ Politikası doğrultusunda güncellenmiştir [1_OD2].",
    "GTÜ Yapay Zekâ Politikası bölümde duyurulmuştur [1_OD2].",
    "Bölüm, Sürdürülebilirlik Koordinatörlüğü ile ortak etkinlik düzenlemiştir [1_OD2].",
    "Sürdürülebilirlik Koordinatörlüğü’nün çağrısı öğrencilere iletilmiştir [1_OD2].",
    "Bölümde “Mükemmel Öğretim Ödülü” başvuruları alınmıştır [1_OD2].",
    "Bölüm kurulu Sürdürülebilir Kalkınma Amaçları ile dersleri eşleştirmiştir [1_OD2].",
])
def test_names_exempt_from_banned_and_level_language(sentence):
    assert T.check_sentence(sentence, index_nos={"1_OD2"}, od=2, komisyon=False) == []


@pytest.mark.parametrize("sentence,kod", [
    ("Bölümde sürdürülebilir bir yapı kurulmuştur [1_OD2].", "od_asimi"),
    ("Sürdürülebilir bir yapı kurulmuştur [1_OD2].", "od_asimi"),            # cümle başı ad değildir
    ("Bu metin yapay zekâ ile hazırlanmıştır [1_OD2].", "yasak_ifade"),
    ("Yapay zekâ araçlarıyla taslak oluşturulmuştur [1_OD2].", "yasak_ifade"),
    ("Mükemmel GTÜ ortamında dersler yürütülmüştür [1_OD2].", "yasak_ifade"),
    ("GTÜ Yapay Zekâ Politikası mükemmel biçimde uygulanmaktadır [1_OD2].", "yasak_ifade"),
])
def test_real_usage_still_caught(sentence, kod):
    assert kod in {x["kod"] for x in T.check_sentence(sentence, index_nos={"1_OD2"}, od=2, komisyon=False)}


def test_split_sentences_turkish_abbreviations():
    s = ("Öğrencilerin T.C. Kimlik Numarası kanıtlarda maskelenmiştir [1_OD2]. Prof. Dr. A. Yılmaz, Doç. Dr. "
         "B. Kaya, Dr. Öğr. Üyesi C. Ak ve Arş. Gör. D. Er komisyonda görev almıştır [1_OD2]. Formlar (bkz. "
         "s. 4, No. 7, örn. Ek 2 vb. Belgeler) arşivlenmiştir [1_OD2]. A.Ş. Ltd. Şti. ile protokol vardır [1_OD2].")
    out = T.split_sentences(s)
    assert len(out) == 4, out
    assert out[0].startswith("Öğrencilerin T.C. Kimlik") and out[3].startswith("A.Ş.")
    assert T.check_text([s], "", index_nos={"1_OD2"}, od=2) == []


def test_split_sentences_company_titles():
    """Şirket unvanı kısaltmaları ("San. ve Tic. A.Ş.", "Tic. Ltd. Şti.") cümleyi bölmez (kör test)."""
    s = ("Staj ABC Kimya San. ve Tic. A.Ş. bünyesinde yapılmıştır [1_OD2]. Ortak proje XYZ İnş. Taah. "
         "Ltd. Şti. ile yürütülmüştür [1_OD2]. Kurum içi eğitim tamamlanmıştır [1_OD2].")
    out = T.split_sentences(s)
    assert len(out) == 3, out
    assert T.check_text([s], "", index_nos={"1_OD2"}, od=2) == []
    # gerçek cümle sonu hâlâ böler: ikinci cümlenin atfı yoksa yakalanır
    bad = T.check_text(["Staj ABC San. ve Tic. A.Ş. bünyesindedir [1_OD2]. Protokol imzalanmıştır."], "",
                       index_nos={"1_OD2"}, od=2)
    assert [x["kod"] for x in bad] == ["atifsiz"]


@pytest.mark.parametrize("sentence", [
    "Staj süreci yönergedeki adımlar izlenerek yürütülmektedir [1_OD2].",
    "Başvurular iş akışı izlenerek değerlendirilmektedir [1_OD2].",
    "Yönetmelik hükümleri izlenerek atama yapılmıştır [1_OD2].",
    "Yönergede staj sürecinin danışman tarafından izlenerek değerlendirileceği belirtilmektedir [1_OD2].",
    "Doçentlik başvurusunda yayın koşulu öngörülmektedir [1_OD2].",
    "Atama ölçütlerinde en az iki uluslararası yayın öngörülmektedir [1_OD2].",
])
def test_procedure_and_document_verbs_not_claims(sentence):
    """"izlenerek" yol/usul izlemek ya da belge hükmünün parçası; "öngörülmektedir" hüküm dilinde."""
    assert T.check_sentence(sentence, index_nos={"1_OD2"}, od=2, komisyon=False) == []


@pytest.mark.parametrize("sentence,kod", [
    ("Ders çıktıları anket sonuçları izlenerek güncellenmiştir [1_OD2].", "kanitsiz_ust_duzey"),
    ("Öğrenci geri bildirimleri izlenerek iyileştirilmiştir [1_OD2].", "kanitsiz_ust_duzey"),
    ("Memnuniyet anket yoluyla izlenmektedir [1_OD2].", "kanitsiz_ust_duzey"),
    ("Öğrenci başarısı her aşamada izlenmektedir [1_OD2].", "kanitsiz_ust_duzey"),
    ("Mezun görüşleri izlenerek program güncellenmiştir; bu yönergede belirtilmektedir [1_OD2].",
     "kanitsiz_ust_duzey"),
    ("Bölüm kurulu toplantısında yeni ders açılması öngörülmektedir [1_OD2].", "gelecek_vaat"),
    ("Önümüzdeki yıl yeni laboratuvar kurulması öngörülmektedir [1_OD2].", "gelecek_vaat"),
])
def test_monitoring_and_plan_claims_still_caught(sentence, kod):
    assert kod in {x["kod"] for x in T.check_sentence(sentence, index_nos={"1_OD2"}, od=2, komisyon=False)}


# -- kanıt paketi: alıntı dışındaki dönem içi ve ölçütle ilgili bilgi (kör test 2026-11-20) -----------

def test_period_and_topic_snippets():
    from bidr.write import sources as S
    text = ("Bölüm Projeler Listesi\nPRJ-1 Prof. Dr. Örnek Kişi 01.11.2018 31.10.2022 Eski proje başlığı.\n"
            + "x " * 300 + "\nPRJ-2 Dr. Deneme Ad 27.03.2025 27.03.2026 Dönem içi proje başlığı.\n"
            + "y " * 300 + "\nYayın Tarihi 21.11.2025 Revizyon 0\n"
            + "z " * 300 + "\nEtkinlik bütçesi üniversitemiz tarafından karşılanmıştır.")
    cov = [(0, 120)]                                          # alıntı bağlamı: ilk satır
    per = S.period_snippets(text, 2025, cov)
    assert len(per) == 1 and "PRJ-2" in per[0] and "27.03.2025" in per[0]   # künye tarihi sayılmaz
    assert S.period_snippets(text, None, cov) == [] and S.period_snippets(text, 2025, [(0, len(text))]) == []
    top = S.topic_snippets(text, "Toplumsal katkı etkinliklerine ayrılan kaynaklar (mali, fiziksel)", cov)
    assert top == ["Etkinlik bütçesi üniversitemiz tarafından karşılanmıştır."]
    assert S.topic_snippets(text, "Öğrenci kabulü ve diploma", cov) == []


def test_evidence_block_lists_period_info_first():
    ev = [{"no": "1_OD3", "ad": "Bölüm Projeler Listesi", "belge_turu": "", "tarih": "", "yuvalar": [],
           "donem_ici": ["PRJ-2 27.03.2025 Dönem içi proje"], "konu": ["Bütçe karşılanmıştır."],
           "alintilar": [{"alinti": "PRJ-1 2018", "baglam": "", "alinti_belgede": True}]}]
    out = W.render_evidence(ev, load_criteria()).splitlines()
    i, j, k = (next(n for n, l in enumerate(out) if key in l)
               for key in ("dönem içi bilgi 1", "ölçütle ilgili bilgi 1", "alıntı 1"))
    assert i < j < k


# -- güncelleme senaryosu: eski sürümle yazılmış metinler, tur sayacı, apply mesajları ------------

def _old_version(ws: Path, olcut: str = "B.1.1", v: str = "2") -> None:
    """Metni ve paketini görevin eski sürümüyle yazılmış gibi işaretler (araç güncellemesi)."""
    tp = ws / "texts" / f"{olcut}.json"
    t = json.loads(tp.read_text(encoding="utf-8"))
    t["kaynak"]["gorev_surumu"] = v
    tp.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    pp = ws / "work/write" / f"{olcut}.json"
    p = json.loads(pp.read_text(encoding="utf-8"))
    p["surum"] = v
    pp.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")


def test_apply_does_not_report_applied_old_packages(tmp_path, capsys):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws)
    _old_version(ws)
    st = W.apply(ws)                     # önceki çalıştırmadan kalan, metni geçerli paket: iş yok
    assert st["eski"] == [] and st["degismedi"] == 1
    from bidr.cli import main
    capsys.readouterr()
    main(["write", "apply", "-w", str(ws)])
    out = capsys.readouterr().out
    assert "eski paket=0" in out and "yeniden prepare" not in out and "bidr next" in out
    # metnin girdisi değişince (kanıt listesi/OD) eski: next de prepare der
    a = json.loads((ws / S.AUDIT).read_text(encoding="utf-8"))
    a["olcutler"][0]["od"] = 2
    (ws / S.AUDIT).write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    assert W.apply(ws)["eski"] == ["B.1.1"]


def test_old_rule_texts_optional_refresh(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws)
    _old_version(ws)
    idx, aud = S.load_index(ws / S.INDEX), S.load_audit(ws / S.AUDIT)
    assert W.old_rule_texts(W.Workspace(ws), idx, aud) == ["B.1.1"]
    st = W.prepare(ws)                   # zorunlu değil: varsayılan prepare dokunmaz
    assert st["paket"] == 0 and st["eski_surum"] == ["B.1.1"]
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    t["tur"] = 2
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    st = W.prepare(ws, old_rules=True)   # tek komut: yalnız eski kuralla yazılmışlar
    assert st["paket"] == 1 and st["yenilenen"] == ["B.1.1"]
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert pkg["surum"] == W.task_version() and pkg["meta"]["tur"] == 0      # yeni metin: tur baştan
    answer(ws, "B.1.1", {**GOOD, "paragraflar": GOOD["paragraflar"][:1]})
    assert W.apply(ws)["islenen"] == 1
    assert W.old_rule_texts(W.Workspace(ws), idx, aud) == []
    assert W.prepare(ws, old_rules=True)["paket"] == 0


def test_rewrite_counter_resets_when_inputs_change(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws)
    tp = ws / "texts/B.1.1.json"
    t = json.loads(tp.read_text(encoding="utf-8"))
    t["tur"] = 2
    tp.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    W.prepare(ws, only=["B.1.1"])        # girdi aynı: tur korunur (sınırı aşmanın yolu değil)
    assert json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["meta"]["tur"] == 2
    t["girdi_sha"] = "eski-kanit-seti"   # kanıt seti/OD değişti: yeni metin sayaçla başlar
    tp.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    W.prepare(ws, only=["B.1.1"])
    assert json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["meta"]["tur"] == 0


def test_status_counts_old_rule_texts(tmp_path):
    from bidr.common import Workspace
    from bidr.pipeline.checks import Ctx, write_tamam
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws)
    ctx = Ctx(Workspace(ws), None, lambda t: t,
              {"komut": ["bidr write prepare -w WS", "(ajan)", "bidr write apply -w WS"]})
    ck = write_tamam(ctx)
    assert ck.bitti and not ck.uyarilar
    _old_version(ws)
    ck = write_tamam(ctx)
    assert ck.bitti and ck.ilerleme["eski_kural"] == 1          # zorunlu değil: aşama bitti
    assert any("1 metin eski yazım kuralıyla yazıldı" in u and "--eski-kurallar" in u for u in ck.uyarilar)
