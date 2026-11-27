"""bidr denetle: sentetik FR-0833 benzeri docx (python-docx) → biçim denetimi (gerçek şablon yok)."""
from __future__ import annotations

import json
from pathlib import Path

import docx
import pytest
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from bidr.check.rules import Rules, load_rules
from bidr.check.run import KRITIK, UYARI, denetle
from bidr.cli import main

SUBS = ["A.1.1", "A.1.2"]
BEKLENEN = (SUBS, ["A.1"])
FOOTER = "Form No:FR-0833 Yayın Tarihi:05.08.2025 Değ.No:0 Değ.Tarihi:-"
UYE_YT = "…………………….[Üye Unvan, Adı Soyadı, eposta adresi, Görevi]"
SWOT_YT = "Biriminizin bu ana ölçüt ve alt ölçütleri açışından güçlü yönlerini değerlendiriniz."
ALANLAR = ["LİDERLİK, YÖNETİŞİM VE KALİTE", "EĞİTİM VE ÖĞRETİM", "ARAŞTIRMA VE GELİŞTİRME",
           "TOPLUMSAL KATKI"]


def _run(p, text, *, font="Times New Roman", size=10, bold=False, italic=False):
    r = p.add_run(text)
    r.font.name = font
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    return r


def _body_p(cell_or_doc, text, *, after=0.6, before=0, **kw):
    p = cell_or_doc.add_paragraph()
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    _run(p, text, **kw)
    return p


def _page_field(p):
    r = p.add_run()
    for kind, instr in (("begin", None), (None, " PAGE "), ("separate", None)):
        if kind:
            fc = OxmlElement("w:fldChar")
            fc.set(qn("w:fldCharType"), kind)
            r._r.append(fc)
        else:
            it = OxmlElement("w:instrText")
            it.text = instr
            r._r.append(it)
    r2 = p.add_run("4")
    r3 = p.add_run()
    fc = OxmlElement("w:fldChar")
    fc.set(qn("w:fldCharType"), "end")
    r3._r.append(fc)
    return r2


def _single_row(table, ncols=5):
    row = table.add_row()
    cell = row.cells[0].merge(row.cells[ncols - 1])
    return cell


def make_doc(path: Path, *, fill=True, aciklama=None, kanitlar=None, footer=FOOTER, swot=True,
             uyeler=None, birim="Matematik Bölümü", extra_aciklama=None, od=3, swot_metin=None, amir=None,
             yil="2025") -> Path:
    """`fill=False`: boş şablon gibi (yer tutucular). Aksi halde kurala uygun dolu rapor; rubrikte `od`
    düzeyi kalın (`od` None: işaretsiz; liste: birden çok düzey kalın)."""
    d = docx.Document()
    sec = d.sections[0]
    fp = sec.footer.paragraphs[0]
    fp.add_run("Sayfa ")
    _page_field(fp)
    sec.footer.add_paragraph(footer)
    d.add_paragraph("BİRİM İÇ DEĞERLENDİRME RAPORU")
    d.add_paragraph("(BİDR)")
    d.add_paragraph(birim if fill else "…………………….[Birim Adı]")
    d.add_paragraph("Raporu Hazırlayanlar")
    for u in (uyeler if uyeler is not None else (["Prof. Dr. Komisyon Üyesi, Başkan"] if fill else [UYE_YT] * 3)):
        d.add_paragraph(u)
    if amir is not None:                    # Değ.No:1 kapağı: amir bölümü (amir: satır metni)
        d.add_paragraph("")
        d.add_paragraph("Raporu Onaylayan Birim Amiri")
        d.add_paragraph(amir)
        d.add_paragraph("")
    d.add_paragraph(yil)
    d.add_paragraph("ÖLÇÜTLER VE KANITLAR")
    t = d.add_table(rows=0, cols=5)
    t.style = "Table Grid"
    c = _single_row(t)
    _run(c.paragraphs[0], "A.1. Liderlik ve Kalite", size=12, bold=True)
    for sid in SUBS:
        c = _single_row(t)
        c.paragraphs[0].text = "DOLDURACAK BİRİMLER: TÜM AKADEMİK BİRİMLER"
        c = _single_row(t)
        _run(c.paragraphs[0], f"{sid}. Sentetik alt ölçüt", size=12, bold=True)
        c.add_paragraph("Sentetik açıklama.")
        r = t.add_row()
        for i, cc in enumerate(r.cells):
            cc.text = str(i + 1)
        r = t.add_row()
        isaret = set(od if isinstance(od, (list, tuple)) else [od]) if fill and od else set()
        for i, cc in enumerate(r.cells):
            cc.text = f"Rubrik {i + 1}"
            if i + 1 in isaret:
                cc.paragraphs[0].runs[0].bold = True
        c = _single_row(t)
        c.paragraphs[0].text = "Örnek Kanıtlar:"
        ca = _single_row(t)
        _run(ca.paragraphs[0], "Açıklamalar:")
        ck = _single_row(t)
        _run(ck.paragraphs[0], "Kanıtlar:")
        if not fill:
            _body_p(ca, "Bu bölüme açıklayıcı metin yazılmalı, Time News Roman 10pt.")
            _body_p(ck, "Kanıtlar buraya yazılmalı, kanıt gösterim şekline bağlı kalınmalı.")
            continue
        for m in (aciklama or {}).get(sid, [f"{sid} süreci tanımlıdır [1_OD3]. İzlenmektedir [2_OD3]."]):
            _body_p(ca, m)
        for extra in (extra_aciklama or {}).get(sid, []):
            extra(ca)
        for k in (kanitlar or {}).get(sid, ["[1-OD3]. Süreç Belgesi", "[2-OD3]. İzleme Raporu"]):
            _body_p(ck, k)
    d.add_paragraph("")
    if swot:
        st = d.add_table(rows=0, cols=2)
        st.style = "Table Grid"
        for alan in ALANLAR:
            c = _single_row(st, 2)
            c.paragraphs[0].text = alan
            r = st.add_row()
            r.cells[0].text, r.cells[1].text = "Güçlü Yönler", "Gelişmeye Açık Yönler"
            r = st.add_row()
            for cc in r.cells:
                if fill:
                    _body_p(cc, swot_metin or "Birimde süreçler tanımlıdır.")
                else:
                    cc.paragraphs[0].text = SWOT_YT
    d.save(str(path))
    return path


def codes(s, level=None):
    return [b.kod for b in s.bulgular if level is None or b.seviye == level]


@pytest.fixture
def sablon(tmp_path):
    return make_doc(tmp_path / "sablon.docx", fill=False)


def test_temiz_rapor_kritik_yok(tmp_path, sablon):
    rep = make_doc(tmp_path / "report.docx")
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    assert codes(s, KRITIK) == [], s.bulgular
    assert "aralik" not in codes(s) and "yazi_tipi" not in codes(s)
    assert s.bilgi["kapak"]["yil"] == "2025" and s.bilgi["kapak"]["birim"] == "Matematik Bölümü"
    assert s.bilgi["kanit_listesi_bicimi"] == {"kilavuz": 4, "mat": 0}
    assert s.bilgi["swot_alan"] == 4


def test_bos_sablon_kritik(tmp_path, sablon):
    s = denetle(sablon, sablon=sablon, beklenen=BEKLENEN)
    k = codes(s, KRITIK)
    for c in ("kapak_birim", "kapak_hazirlayanlar", "sablon_metni", "swot_sablon_metni"):
        assert c in k, c
    assert k.count("swot_sablon_metni") == 8
    assert "form_alani_degisti" not in k


def test_eksik_olcut_ve_46(tmp_path):
    rep = make_doc(tmp_path / "r.docx")
    s = denetle(rep, beklenen=(SUBS + ["A.1.3"], ["A.1"]))
    assert [b.yer for b in s.bulgular if b.kod == "olcut_eksik"] == ["A.1.3"]
    s = denetle(rep)                     # paket verisi: 46 alt ölçüt
    assert s.bilgi["alt_olcut"] == {"beklenen": 46, "bulunan": 2}
    assert codes(s).count("olcut_eksik") == 44


def test_bicim_ihlalleri(tmp_path, sablon):
    def calibri(cell):
        _body_p(cell, "Yanlış yazı tipiyle cümle [1_OD3].", font="Calibri")
        _body_p(cell, "Büyük puntolu cümle [1_OD3].", size=12)
        _body_p(cell, "Aralığı sıfır cümle [1_OD3].", after=0)
    rep = make_doc(tmp_path / "r.docx", extra_aciklama={"A.1.1": [calibri]})
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    by = {b.kod: b for b in s.bulgular}
    assert by["yazi_tipi"].seviye == KRITIK and "Calibri" in by["yazi_tipi"].mesaj
    assert by["govde_punto"].seviye == KRITIK and "12" in by["govde_punto"].mesaj
    assert by["aralik"].seviye == UYARI and "sonrası 0 nk" in by["aralik"].mesaj


def test_aralik_yapilandirilabilir(tmp_path, monkeypatch):
    rep = make_doc(tmp_path / "r.docx", aciklama={"A.1.1": ["Cümle [1_OD3] [2_OD3]."]})
    # bütün gövde 0,6 nk sonrası: varsayılanla uyumlu, 6 nk kuralıyla uyumsuz
    assert "aralik" not in codes(denetle(rep, beklenen=BEKLENEN))
    s = denetle(rep, rules=load_rules({"paragraf_sonrasi_nk": 6}), beklenen=BEKLENEN)
    assert "aralik" in codes(s, UYARI)
    assert s.kurallar["paragraf_sonrasi_nk"] == 6 and "0.6 nk" in s.kurallar["not"]
    assert Rules().paragraf_sonrasi_nk == 0.6
    assert load_rules({"paragraf_sonrasi_nk": 0.6}, paragraf_sonrasi_nk=None).twip(0.6) == 12
    assert load_rules({}, paragraf_sonrasi_nk=0.6).paragraf_sonrasi_nk == 0.6


def test_atif_liste_eslesmesi(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx",
                   aciklama={"A.1.1": ["Tanımlıdır [1_OD3]. Ölçülür [3_OD2]. İzlenir [2_OD4]. Bakılır [1-OD3]."]},
                   kanitlar={"A.1.1": ["[1-OD3]. Süreç", "[2-OD3]. İzleme", "[4-OD2]. Atıfsız"]})
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    msg = {(b.kod, b.mesaj) for b in s.bulgular if b.yer == "A.1.1"}
    assert ("atif_listede_yok", "metindeki [3_OD2] kanıt listesinde yok") in msg
    assert ("atif_od_uyusmuyor", "metinde [2_OD4], listede 2. kanıt OD3") in msg
    assert any(k == "atifsiz_kanit" and "4. kanıt" in m for k, m in msg)
    assert any(k == "atif_gosterimi" for k, _ in msg)
    assert any(k == "kanit_numarasi" for k, _ in msg)
    assert s.kritik >= 2


def test_kanit_gosterimi_karar_ve_karisik(tmp_path):
    mat = {"A.1.1": ["1_OD3: Süreç", "2_OD3: İzleme"], "A.1.2": ["1_OD3: Süreç", "2_OD3: İzleme"]}
    s = denetle(make_doc(tmp_path / "m.docx", kanitlar=mat), beklenen=BEKLENEN)
    b = next(b for b in s.bulgular if b.kod == "kanit_gosterimi_karar")
    assert b.seviye == UYARI and "KARAR GEREKLİ" in b.mesaj
    karisik = {"A.1.1": ["1_OD3: Süreç", "[2-OD3]. İzleme"]}
    s = denetle(make_doc(tmp_path / "k.docx", kanitlar=karisik), beklenen=BEKLENEN)
    assert "kanit_gosterimi_karisik" in codes(s, UYARI)
    assert "atif_listede_yok" not in codes(s)


def test_form_alanlari(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx", footer="Form No:FR-0833 Yayın Tarihi:05.08.2025 Değ.No:1")
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    assert "form_alani_degisti" in codes(s, KRITIK)
    # şablonsuz: yalnız varlık
    s = denetle(make_doc(tmp_path / "r2.docx", footer="Altbilgi"), beklenen=BEKLENEN)
    eksik = [b.mesaj for b in s.bulgular if b.kod == "form_alani_eksik"]
    assert any("Form No" in m for m in eksik) and any("Değ.No" in m for m in eksik)
    assert not any("PAGE" in m for m in eksik)       # sayfa alanı duruyor


def test_sayfa_alani_sonucu_imzaya_girmez(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx")
    d = docx.Document(str(rep))
    for t in d.sections[0].footer._element.iter(qn("w:t")):
        if t.text == "4":
            t.text = "17"                 # sayfa numarası sonucu değişir, alan aynı
    d.save(str(rep))
    assert "form_alani_degisti" not in codes(denetle(rep, sablon=sablon, beklenen=BEKLENEN))


def test_kapak_ve_swot(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx", uyeler=[UYE_YT, UYE_YT], swot=False)
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    b = next(b for b in s.bulgular if b.kod == "kapak_hazirlayanlar")
    assert b.seviye == KRITIK and "2 yer tutucu" in b.mesaj
    assert "swot_eksik" in codes(s, KRITIK)


def test_kapak_amir_bolumu(tmp_path, sablon):
    """Değ.No:1 kapağı: amir yer tutucusu hazırlayan sayılmaz, ayrı bulgu olur; amir dolu ise bulgu yok;
    kalan "20.." yıl yer tutucusu uyarıdır."""
    rep = make_doc(tmp_path / "r.docx", amir=UYE_YT, yil="20..")
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    assert "kapak_hazirlayanlar" not in codes(s)
    assert "kapak_onaylayan" in codes(s, KRITIK)
    assert s.bilgi["kapak"]["hazirlayanlar"] == 1 and s.bilgi["kapak"]["onaylayan"] == 0
    assert any(b.kod == "kapak_yil" and "20.." in b.mesaj for b in s.bulgular if b.seviye == UYARI)
    rep = make_doc(tmp_path / "r2.docx", uyeler=[UYE_YT] * 3, amir="Prof. Dr. Amir Örnek, Bölüm Başkanı")
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    b = next(b for b in s.bulgular if b.kod == "kapak_hazirlayanlar")
    assert "3 yer tutucu" in b.mesaj and "kapak_onaylayan" not in codes(s)
    assert s.bilgi["kapak"]["onaylayan"] == 1 and "kapak_yil" not in codes(s)
    rep = make_doc(tmp_path / "r3.docx")                      # eski kapak: amir bölümü yok, bulgu yok
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    assert "kapak_onaylayan" not in codes(s) and "onaylayan" not in s.bilgi["kapak"]


def test_nesne_aciklamasi_ve_alt_baslik(tmp_path):
    def nesne(cell):
        cell.add_table(rows=1, cols=2)
        _body_p(cell, "Tablo 1. Öğrenci sayıları")              # altta, eğik değil, sola yaslı
        p = _body_p(cell, "Şekil 1. Süreç akışı", italic=True)
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        _body_p(cell, "A.1.2.1. Yanlış ölçüt altında başlık", size=12, bold=True)
        _body_p(cell, "A.1.1.1. Doğru alt başlık", size=10)
        _body_p(cell, "Bu yaklaşım (Yılmaz 2020) çalışmasına dayanır [1_OD3].")
    rep = make_doc(tmp_path / "r.docx", extra_aciklama={"A.1.1": [nesne]})
    s = denetle(rep, beklenen=BEKLENEN)
    nes = [b.mesaj for b in s.bulgular if b.kod == "nesne_aciklamasi"]
    assert len(nes) == 1 and "eğik değil" in nes[0] and "altında" in nes[0] and "sağa" in nes[0]
    assert "baslik_numarasi" in codes(s, UYARI)
    assert any(b.kod == "baslik_bicimi" and "A.1.1.1" in b.mesaj for b in s.bulgular)
    assert any(b.kod == "apa7" and "(Yılmaz, 2020)" in b.mesaj for b in s.bulgular)


def test_baslik_bicimi(tmp_path):
    rep = make_doc(tmp_path / "r.docx")
    d = docx.Document(str(rep))
    for r in d.element.body.iter(qn("w:r")):
        t = "".join(x.text or "" for x in r.iter(qn("w:t")))
        if t.startswith("A.1.2. Sentetik"):
            r.find(qn("w:rPr")).find(qn("w:b")).set(qn("w:val"), "0")
    d.save(str(rep))
    s = denetle(rep, beklenen=BEKLENEN)
    assert [b.yer for b in s.bulgular if b.kod == "baslik_bicimi"] == ["A.1.2 başlık"]


def _evidence(root: Path, names: dict[str, list[str]]) -> Path:
    ev = root / "evidence"
    for sid, files in names.items():
        a, m = sid.split(".")[0], ".".join(sid.split(".")[:2])
        d = ev / a / m / sid
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_bytes(b"%PDF-1.4 sentetik")
    (ev / ".bidr-evidence.json").write_text("{}")
    return ev


def test_kanit_klasoru(tmp_path):
    rep = make_doc(tmp_path / "r.docx")
    ev = _evidence(tmp_path, {"A.1.1": ["[1-OD3]. Süreç.pdf", "[2-OD2]. İzleme.pdf",
                                        "[3-OD2]. Fazla.pdf", "rastgele ad.pdf"],
                              "A.1.2": ["[1-OD3]. Süreç.pdf"]})
    (ev / "A" / "A.1" / "[9-OD3]. Yanlış yer.pdf").write_bytes(b"x")     # alt ölçüt klasöründe değil
    s = denetle(rep, kanit_klasoru=ev, beklenen=BEKLENEN)
    m = {(b.kod, b.yer): b for b in s.bulgular}
    assert m[("kanit_dosyasi_od", "A.1.1")].seviye == KRITIK          # listede 2_OD3, dosya OD2
    assert m[("kanit_dosyasi_yok", "A.1.2")].seviye == KRITIK         # 2. kanıtın dosyası yok
    assert ("listede_olmayan_dosya", "A.1.1") in m
    assert any(k == "kanit_dosya_adi" and "rastgele" in y for k, y in m)
    assert any(k == "kanit_klasor_yeri" and "Yanlış yer" in y for k, y in m)
    assert s.bilgi["kanit_dosyasi"] == 6                              # gizli dosya sayılmaz


def test_kanit_dizini(tmp_path):
    rep = make_doc(tmp_path / "r.docx")
    idx = tmp_path / "evidence-index.csv"
    idx.write_text("kanit_no,olcut,od,ad\n1_OD3,A.1.1,3,a\n2_OD2,A.1.1,2,b\n1_OD3,A.1.2,3,c\n2_OD3,A.1.2,3,d\n",
                   encoding="utf-8")
    s = denetle(rep, index_path=idx, beklenen=BEKLENEN)
    assert [b.mesaj for b in s.bulgular if b.kod == "dizinle_uyusmuyor"] == \
        ["belgedeki 2_OD3 evidence-index.csv'de 2_OD2"]


def test_taslak_ve_dogrulanmamis(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx", aciklama={"A.1.1": ["[doğrulanmadı] Bu metin doğrulanmadı.",
                                                           "Cümle [1_OD3] [2_OD3]."]})
    d = docx.Document(str(rep))
    d.sections[0].header.add_paragraph("TASLAK — doğrulanmamış metin içerir")
    d.save(str(rep))
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    assert "taslak_damgasi" in codes(s, KRITIK) and "dogrulanmamis_metin" in codes(s, KRITIK)
    assert "form_alani_degisti" not in codes(s)          # TASLAK satırı form karşılaştırmasına girmez


@pytest.fixture
def mini_criteria(tmp_path, monkeypatch):
    cdir = tmp_path / "criteria"
    cdir.mkdir()
    (cdir / "yokak-2025.yaml").write_text(
        "areas: [{id: A, title: x}]\ncriteria: [{id: A.1, title: x}]\n"
        "sub_criteria: [{id: A.1.1, title: x}, {id: A.1.2, title: y}]\n", encoding="utf-8")
    monkeypatch.setenv("BIDR_CRITERIA_DIR", str(cdir))


def test_cli(tmp_path, sablon, mini_criteria, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    make_doc(ws / "report.docx")
    rc = main(["denetle", "-w", str(ws), "--sablon", str(sablon)])
    out = capsys.readouterr().out
    assert rc == 0, out
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert js["ozet"]["yayima_hazir"] is True and js["ozet"]["kritik"] == 0
    assert "yayıma hazır" in out

    bad = make_doc(tmp_path / "bad.docx", fill=False)
    o = tmp_path / "out" / "d.json"
    rc = main(["denetle", "-w", str(ws), "--docx", str(bad), "--sablon", str(sablon), "--out", str(o)])
    out = capsys.readouterr().out
    assert rc == 1 and "YAYIMA HAZIR DEĞİL" in out
    js = json.loads(o.read_text(encoding="utf-8"))
    assert js["ozet"]["kodlar"]["swot_sablon_metni"] == {"seviye": KRITIK, "sayi": 8}

    assert main(["denetle", "-w", str(ws), "--docx", str(tmp_path / "yok.docx")]) == 2


def test_cli_config_denetim(tmp_path, mini_criteria, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    make_doc(ws / "report.docx")
    (ws / "config.yaml").write_text("rapor:\n  denetim:\n    paragraf_sonrasi_nk: 6\n", encoding="utf-8")
    rc = main(["denetle", "-w", str(ws)])
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert js["kurallar"]["paragraf_sonrasi_nk"] == 6
    assert js["ozet"]["kodlar"]["aralik"]["seviye"] == UYARI
    assert "sablon_yok" in js["ozet"]["kodlar"]
    assert rc == 0                         # aralık uyarıdır, kritik değil
    rc = main(["denetle", "-w", str(ws), "--paragraf-sonrasi", "0.6"])
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert "aralik" not in js["ozet"]["kodlar"]


def test_taslak_nedeni_render_kaydindan(tmp_path, sablon, mini_criteria, capsys):
    """denetle TASLAK nedenini tahmin etmez: bu docx'i üreten render kaydının gerekçesini yazar
    (kör test: neden boş hazırlayanlarken "doğrulanmamış metin" deniyordu)."""
    import hashlib
    ws = tmp_path / "ws"
    ws.mkdir()
    rep = make_doc(ws / "report.docx")
    d = docx.Document(str(rep))
    d.sections[0].header.add_paragraph("TASLAK — doğrulanmamış ya da eksik içerik var")
    d.save(str(rep))
    neden = "kapakta 5 'Raporu Hazırlayanlar' yer tutucusu kaldı (config.yaml rapor.hazirlayanlar boş)"
    sha = hashlib.sha256(rep.read_bytes()).hexdigest()[:16]
    (ws / ".bidr-render.json").write_text(json.dumps({"cikti": str(rep), "cikti_sha": sha,
                                                      "taslak_nedenleri": [neden]}), encoding="utf-8")
    assert main(["denetle", "-w", str(ws), "--sablon", str(sablon)]) == 1
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    msg = [b["mesaj"] for b in js["bulgular"] if b["kod"] == "taslak_damgasi"]
    assert msg and all(neden in m and "doğrulanmamış metin" not in m for m in msg)
    # belge render'dan sonra değiştiyse neden tahmin edilmez
    d.sections[0].header.add_paragraph("elle eklenen satır")
    d.save(str(rep))
    capsys.readouterr()
    main(["denetle", "-w", str(ws), "--sablon", str(sablon)])
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    msg = [b["mesaj"] for b in js["bulgular"] if b["kod"] == "taslak_damgasi"]
    assert msg and all("bilinmiyor" in m and neden not in m for m in msg)


# -- son çıktı içerik denetimi (kör test 2026-11-20) ---------------------------------------------

def test_ic_dil_kritik(tmp_path, sablon):
    rep = make_doc(tmp_path / "r.docx", aciklama={
        "A.1.1": ["Süreç tanımlıdır [1_OD3]. İzlenmektedir [2_OD3].",
                  "Eksik kanıt notu: bölümün bu döneme ait doğrudan kanıtı yok. Gereken: kurul kararı."]},
        swot_metin="• Birime ait belgeler OD'ye sayılmamıştır (A.1.1).")
    s = denetle(rep, sablon=sablon, beklenen=BEKLENEN)
    ic = [b for b in s.bulgular if b.kod == "ic_dil"]
    assert all(b.seviye == KRITIK for b in ic)
    assert {b.yer for b in ic} >= {"A.1.1 Açıklamalar"} and sum("Güçlü Yönler" in b.yer for b in ic) == 4
    # temiz metinde yok
    s = denetle(make_doc(tmp_path / "t.docx"), sablon=sablon, beklenen=BEKLENEN)
    assert "ic_dil" not in codes(s)


def test_od_isareti_kritik(tmp_path, sablon):
    s = denetle(make_doc(tmp_path / "ok.docx", od=1), sablon=sablon, beklenen=BEKLENEN)
    assert not {"od_isaretsiz", "od_isareti_belirsiz"} & set(codes(s))
    assert s.bilgi["od_isareti"] == {c: 1 for c in SUBS}
    s = denetle(make_doc(tmp_path / "yok.docx", od=None), sablon=sablon, beklenen=BEKLENEN)
    assert codes(s, KRITIK).count("od_isaretsiz") == len(SUBS)
    s = denetle(make_doc(tmp_path / "iki.docx", od=[1, 3]), sablon=sablon, beklenen=BEKLENEN)
    assert codes(s, KRITIK).count("od_isareti_belirsiz") == len(SUBS)
    # kapsam dışı ölçüt atlanır (render kaydı ya da kapsam ifadesi)
    s = denetle(make_doc(tmp_path / "kd.docx", od=None), sablon=sablon, beklenen=BEKLENEN, kapsam_disi=SUBS[:1])
    assert codes(s, KRITIK).count("od_isaretsiz") == len(SUBS) - 1
    rep = make_doc(tmp_path / "kd2.docx", od=None,
                   aciklama={c: ["Bu ölçüt birimin doldurma sorumluluğunda değildir."] for c in SUBS})
    assert "od_isaretsiz" not in codes(denetle(rep, beklenen=BEKLENEN))


def test_od_isareti_tablo_stili_ilk_sutun(tmp_path):
    """Tablo stilinin ilk sütun biçimi (firstCol kalın) açıkça kapatılmamışsa 1. düzey kalın görünür:
    render başka düzeyi işaretlediğinde iki düzey kalın okunur (belirsiz); kapatılmışsa tek düzey."""
    from bidr.check.fmt import Resolver
    from bidr.check.run import bloklar, isaretli_duzeyler
    from bidr.render import docx_ops as ops
    rep = make_doc(tmp_path / "r.docx", od=3)
    d = docx.Document(str(rep))
    st = d.styles["Table Grid"].element
    tsp = OxmlElement("w:tblStylePr")
    tsp.set(qn("w:type"), "firstCol")
    rpr = OxmlElement("w:rPr")
    rpr.append(OxmlElement("w:b"))
    tsp.append(rpr)
    st.append(tsp)
    for tbl in d.element.body.iter(qn("w:tbl")):
        look = tbl.find(qn("w:tblPr") + "/" + qn("w:tblLook"))
        if look is not None:
            look.set(qn("w:firstColumn"), "1")
    b = bloklar(d)[0][SUBS[0]]
    assert isaretli_duzeyler(b, Resolver(d), d) == {1, 3}
    for row in b.rubrik:
        ops.clear_bold(row[0])
    assert isaretli_duzeyler(b, Resolver(d), d) == {3}
