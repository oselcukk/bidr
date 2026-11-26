"""Kopyalar tek belge (kullanıcı kararı 2026-11-26 19:11; sentetik veri, model yok): aynı belgenin farklı
biçimleri (docx/pdf) ve aynı metnin yeniden kaydedilmiş dosyaları birbirinin sürümü değildir, "sürüm
doğrulanmalı" diye sorulmaz; incelemede yuva başına tek satır, kopyaları "kopyaları" sütununda. Farklı içerik
(ders, tarih, sözcük) kopya değildir; görsel dosyalar metin yoluyla kopya olmaz."""
from __future__ import annotations

from bidr.audit import donem as D
from bidr.audit import kopya as K
from bidr.audit.run import collapse_copies

GOVDE = ("Program bilgileri. Programın amacı mühendislik alanında nitelikli mezun "
         "yetiştirmektir. Program çıktıları aşağıda listelenmiştir ve her yıl kurulda gözden geçirilir. "
         "Laboratuvar olanakları bilgisayar laboratuvarı ve proje odasından oluşur. Mezunlar sağlık finans "
         "kamu ve sanayi alanlarında çalışabilir. Ders planı zorunlu ve seçmeli derslerden oluşur. "
         "Staj yaz döneminde tamamlanır ve komisyon tarafından değerlendirilir. ABC 104 dersi temel "
         "programlama becerisi kazandırır.") * 2
MADDE = ["Analitik düşünme becerisi", "Takım çalışması", "Etik sorumluluk"]


def _pdf(govde=GOVDE, madde=MADDE, ek=""):
    # PDF dışa aktarımı Word'ün otomatik liste numaralarını ve sayfa numarasını metne yazar
    return govde + "\n" + "\n".join(f"{i}. {m}" for i, m in enumerate(madde, 1)) + ek + "\n2\n"


def _docx(govde=GOVDE, madde=MADDE, ek=""):
    return govde + "\n" + "\n".join(madde) + ek + "\n"


def _grp(metin, yol, kabul=None, docs=None):
    return K.gruplar(list(metin), docs or {d: {} for d in metin}, metin.get, yol, kabul or {})


def test_bicim_kopyasi_pdf_temsilci():
    metin = {"w": _docx(), "p": _pdf(), "p2": _pdf()}
    yol = {"w": "a/program-v3.docx", "p": "a/Bilgiler.pdf", "p2": "a/istenen.pdf"}
    # PDF önce; iki PDF'ten kabul edilmiş eşleşmesi çok olan temsilci
    assert _grp(metin, yol, {"p": 3, "p2": 4, "w": 3}) == {"p2": ["p", "w"]}
    assert _grp(metin, yol) == {"p": ["p2", "w"]}


def test_farkli_icerik_kopya_degil():
    yol = {"w": "a/x.docx", "p": "a/x.pdf"}
    # başka ders kodu (üç haneli sayı) ya da başka sözcük: farklı belge
    assert _grp({"w": _docx(), "p": _pdf(GOVDE.replace("ABC 104", "ABC 204"))}, yol) == {}
    assert _grp({"w": _docx(), "p": _pdf(madde=[*MADDE[:2], "Girişimcilik"])}, yol) == {}
    # metindeki tarih farkı (gün/ay kısa sayı olsa da): farklı belge
    assert _grp({"w": _docx(ek="\nKurul tarihi 12.03.2025"), "p": _pdf(ek="\nKurul tarihi 15.03.2025")}, yol) == {}
    assert _grp({"w": _docx(ek="\nKurul tarihi 12.03.2025"), "p": _pdf(ek="\nKurul tarihi 12.03.2025")}, yol) \
        == {"p": ["w"]}


def test_ayni_bicim_birebir_metin():
    yol = {"a": "x/a.docx", "b": "y/a (1).docx"}
    assert _grp({"a": _docx(), "b": _docx()}, yol) == {"a": ["b"]}
    # aynı biçimde liste sırası/numarası farkı birebir değil: kopya sayılmaz (sürüm olabilir)
    assert _grp({"a": _docx(), "b": _docx(madde=MADDE[::-1])}, yol) == {}
    assert _grp({"a": _pdf(), "b": _pdf(ek="\n4. Etik sorumluluk")}, {"a": "a.pdf", "b": "b.pdf"}) == {}


def test_gorsel_parcali_kisa_aday_degil():
    m = {"a": _docx(), "b": _docx()}
    assert _grp(m, {"a": "f/1.jpg", "b": "f/2.jpg"}) == {}            # betimleme metni aynı iki fotoğraf
    assert _grp(m, {"a": "a.docx", "b": "b.docx"}, docs={"a": {"parca_grubu": "pg"}, "b": {}}) == {}
    assert _grp({"a": "Kısa yazı 1", "b": "Kısa yazı 1"}, {"a": "a.docx", "b": "b.docx"}) == {}


def test_kopyalar_surum_sayilmaz():
    g = {"surum_grubu": "g", "doc_type": "altyapi_listesi", "tarih": None, "donem": 2025,
         "akademik_donem": [], "donem_ici": None}
    docs = {"w": dict(g), "p": dict(g), "p2": dict(g)}
    assert D.version_status(docs, D.load_rule()) == {x: "surum_dogrulanmali" for x in docs}
    assert D.version_status(docs, D.load_rule(), kopyalar={"p2": ["p", "w"]}) == {}
    # kopya grubu ile gerçek bir sürüm: grup tek üye, sıralanamazsa ikisi de sorulur (durum kopyalara geçer)
    docs["v"] = dict(g)
    st = D.version_status(docs, D.load_rule(), kopyalar={"p2": ["p", "w"]})
    assert st == {x: "surum_dogrulanmali" for x in docs}
    docs["v"] = {**g, "tarih": "2024-05-01", "donem_ici": False}
    st = D.version_status(docs, D.load_rule(), kopyalar={"p2": ["p", "w"]})
    assert st == {x: "surum_dogrulanmali_sayilmaz" for x in ("p2", "p", "w")}


def _r(did, yuva, karar=None):
    return {"doc_id": did, "yuva": yuva, "yuva_model": yuva, "satir": f"{did}|{yuva}", "karar": karar}


def test_yuva_basina_tek_satir():
    rows = [_r("w", "B.1.1/3"), _r("p", "B.1.1/3"), _r("p2", "B.1.1/3"), _r("p2", "B.3.2/5"),
            _r("w", "B.1.4/1"), _r("x", "B.1.1/3")]
    out = collapse_copies(rows, {"p2": ["p", "w"]})
    assert [r["satir"] for r in out] == ["p2|B.1.1/3", "p2|B.3.2/5", "w|B.1.4/1", "x|B.1.1/3"]
    assert all(r["kopya_temsilci"] == "p2" and r["_kopya"] == ["p2", "p", "w"] for r in out[:3])
    assert "kopya_temsilci" not in out[3]
    # insan kararı verilmiş satır düşürülmez; aynı yuvadaki kararsız kopya satırı düşer
    out = collapse_copies([_r("p2", "B.1.1/3"), _r("w", "B.1.1/3", "kabul")], {"p2": ["w"]})
    assert [r["satir"] for r in out] == ["w|B.1.1/3"]
    # tabloda olup henüz uygulanmamış karar (audit taşır): satırı da düşmez
    out = collapse_copies([_r("p2", "B.1.1/3"), _r("w", "B.1.1/3")], {"p2": ["w"]}, {"w|B.1.1/3"})
    assert [r["satir"] for r in out] == ["w|B.1.1/3"]
