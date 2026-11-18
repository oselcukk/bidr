"""`bidr write`: metin denetimleri ve prepare/apply (sentetik; ajan cevapları elle yazılır)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

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
    assert t["kaynak"]["model"] == "test:ajan" and t["kaynak"]["gorev_surumu"] == "1"
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
