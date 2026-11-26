"""bidr kurum-katalog: liste sayfası ayrıştırma, çekme (ağsız), kural eşlemesi, model paketleri ve
sade listeye ekleme. HTML ve adlar sentetiktir; ağ çağrısı yok."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from bidr.cli import main
from bidr.ihtiyac import katalog as K
from bidr.ihtiyac import katalog_esle as E
from bidr.ihtiyac import rapor as R
from bidr.ihtiyac import sade as S
from test_ihtiyac import PLAN, YONERGE, _m, _ws

BASE = "https://ornek.example/liste/101/sayfa.html"

TABLO = """<html><head><title>x</title><script>var a = "<a href='/x.pdf'>YZ-9999 Gizli</a>";</script></head>
<body><nav><a href="/menu.pdf">YZ-0000 Menü Belgesi</a></nav>
<div class="icerik">
<table><tr><td>Açıklama satırı: taslak teklifler mevzuat birimine iletilir.</td></tr></table>
<table>
<tr><th>YÖNERGE NO</th><th>YÖNERGE ADI</th><th>DİLİ</th><th>SENATO KARAR TARİHİ</th><th>EYS REVİZYON NO</th><th>LİNK</th></tr>
<tr><td>YZ-0001</td><td>Sentetik Danışmanlık Yönergesi</td><td>Türkçe</td><td>01.02.2024</td><td>R3</td>
    <td><a href="/dosya/YZ-0001 Sentetik R3.pdf"><img src="/pdf.png"></a></td></tr>
<tr><td>YZ-0001</td><td>Synthetic Advising Directive</td><td>İngilizce</td><td>01.02.2024</td><td>R3</td>
    <td><a href="/dosya/YZ-0001 Synthetic R3.pdf">pdf</a></td></tr>
<tr><td>YZ-0002</td><td>Sentetik Ders Muafiyeti Uygulama Esasları - (FR-0001 için tıklayınız)</td><td>Türkçe</td>
    <td>-</td><td>R0</td><td><a href="/dosya/YZ-0002.pdf">pdf</a></td></tr>
<tr><td>YZ-0003</td><td>Sentetik Taşınır Kayıt Yönergesi</td><td>Türkçe</td><td>03.03.2020</td><td>R1</td>
    <td><a href="/dosya/YZ-0003.pdf">pdf</a></td></tr>
</table>
<table>
<tr><td><strong>BİRİM ADI:</strong></td><td>ÖRNEK DAİRE BAŞKANLIĞI</td></tr>
<tr><td>İŞ AKIŞ NO</td><td>İŞ AKIŞ ADI</td><td>LİNK</td></tr>
<tr><td>AK-0010</td><td>Yatay Geçiş Başvurusu</td><td><a href="/akis/AK-0010.pdf">pdf</a></td></tr>
<tr><td><strong>BİRİM ADI:</strong></td><td>ÖRNEK SATIN ALMA MÜDÜRLÜĞÜ</td></tr>
<tr><td>AK-0011</td><td>Doğrudan Temin Süreci</td><td><a href="/akis/AK-0011.pdf">pdf</a></td></tr>
</table>
</div></body></html>"""

PARAGRAF = """<html><body><div class="rich-text-content">
<p>Güncel anketler için <a href="https://ornek.example/liste/102/sayfa.html">tıklayınız</a></p>
<p><span><strong>ANKETLER</strong></span></p>
<p><a href="/form/FR-0006 Mezun Anketi R2.xlsx">FR-0006&nbsp;Mezun Memnuniyet Anketi</a>
 (<a href="/form/FR-0006 Alumni Survey.xlsx"><span>FR-0006 Alumni Satisfaction Survey</span></a>)</p>
<p><strong>EĞİTİM-ÖĞRETİM FORMLARI</strong></p>
<p><a href="/form/FR- 0784 Sinav.docx">FR- 0784 Sınav Notu İtiraz Dilekçesi</a></p>
<p><a href="/form/Proje Ara Rapor Formu.doc">Proje Ara Rapor Formu</a></p>
<p><strong>PERSONEL İŞLERİ İLE İLGİLİ FORMLAR</strong></p>
<p><a href="/form/FR-0500 Ders Yuku.docx">FR-0500 Ders Yükü Bildirim Formu</a></p>
<p><a href="/form/FR-0501.docx">FR-0501 Yıllık İzin Formu</a></p>
<p><a href="?sayfa=2" rel="next">2</a></p>
</div></body></html>"""

PARAGRAF2 = """<html><body><p><a href="/form/FR-0600.pdf">FR-0600 Öğrenci Kulübü Etkinlik Formu</a></p></body></html>"""


def _sayfa(tur="yonerge", ad="Yönergeler"):
    return {"ad": ad, "tur": tur, "adres": BASE}


def test_table_parsing():
    its, nxt = K.ayristir(TABLO, _sayfa(), BASE)
    assert nxt == []
    ad = {i["ad"]: i for i in its}
    assert "Menü Belgesi" not in ad and "Gizli" not in ad               # nav/script dışarıda
    y = ad["Sentetik Danışmanlık Yönergesi"]
    assert y["kod"] == "YZ-0001" and y["tur"] == "yonerge" and y["revizyon"] == "R3"
    assert y["baglanti"] == "https://ornek.example/dosya/YZ-0001%20Sentetik%20R3.pdf"
    assert y["tarihler"] == {"SENATO KARAR TARİHİ": "01.02.2024"}
    u = ad["Sentetik Ders Muafiyeti Uygulama Esasları"]                 # "(… için tıklayınız)" atıldı
    assert u["tur"] == "usul_esas" and u["tarihler"] == {}
    assert ad["Yatay Geçiş Başvurusu"]["birim"] == "ÖRNEK DAİRE BAŞKANLIĞI"
    assert ad["Doğrudan Temin Süreci"]["birim"] == "ÖRNEK SATIN ALMA MÜDÜRLÜĞÜ"
    m = K.birlestir(its)
    yz1 = [o for o in m if o["kod"] == "YZ-0001"]
    assert len(yz1) == 1 and yz1[0]["en_baglanti"].endswith("Synthetic%20R3.pdf")
    assert len({o["id"] for o in m}) == len(m) and all(o["anahtar"] for o in m)


def test_paragraph_parsing():
    its, nxt = K.ayristir(PARAGRAF, _sayfa("form", "Formlar"), BASE)
    assert nxt == ["https://ornek.example/liste/101/sayfa.html?sayfa=2"]
    ad = {i["ad"]: i for i in its}
    assert set(ad) == {"Mezun Memnuniyet Anketi", "Sınav Notu İtiraz Dilekçesi", "Proje Ara Rapor Formu",
                       "Ders Yükü Bildirim Formu", "Yıllık İzin Formu"}
    a = ad["Mezun Memnuniyet Anketi"]
    assert a["kod"] == "FR-0006" and a["tur"] == "anket" and a["bolum"] == "ANKETLER" and a["revizyon"] == "R2"
    assert a["en_baglanti"].endswith("Alumni%20Survey.xlsx")
    s = ad["Sınav Notu İtiraz Dilekçesi"]
    assert s["kod"] == "FR-0784" and s["tur"] == "form" and s["bolum"] == "EĞİTİM-ÖĞRETİM FORMLARI"
    assert ad["Proje Ara Rapor Formu"]["kod"] == ""
    assert ad["Yıllık İzin Formu"]["bolum"] == "PERSONEL İŞLERİ İLE İLGİLİ FORMLAR"


def _fake(pages: dict):
    calls = []

    def getir(url):
        calls.append(url)
        if url in pages:
            return 200, pages[url], url
        return 404, "", url
    return getir, calls


def test_fetch_follows_pagination_and_reports_failures():
    s2 = BASE + "?sayfa=2"
    getir, calls = _fake({BASE: PARAGRAF, s2: PARAGRAF2})
    sayfalar = [{"ad": "Formlar", "adres": BASE, "tur": "form", "etkin": True},
                {"ad": "Kırık", "adres": "https://ornek.example/yok.html", "tur": "yonerge", "etkin": True},
                {"ad": "Kapalı", "adres": "https://ornek.example/kapali.html", "tur": "talimat", "etkin": False}]
    kat = K.cek(sayfalar, getir, kurum="ornek", log=lambda *a: None)
    assert calls == [BASE, s2, "https://ornek.example/yok.html"]      # sayfa başına tek istek; kapalı çekilmez
    durum = {s["ad"]: s for s in kat["sayfalar"]}
    assert durum["Formlar"]["istek"] == 2 and durum["Formlar"]["oge_sayisi"] == 6
    assert durum["Kırık"]["durum"].startswith("başarısız") and durum["Kapalı"]["durum"].startswith("atlandı")
    assert len(kat["ogeler"]) == 6 and kat["sha"]
    # ek dosya istenmedi
    assert not any(c.endswith((".pdf", ".docx", ".xlsx", ".doc")) for c in calls)


def _katalog():
    a, _ = K.ayristir(TABLO, _sayfa(), BASE)
    b, _ = K.ayristir(PARAGRAF, _sayfa("form", "Formlar"), BASE)
    c, _ = K.ayristir(PARAGRAF2, _sayfa("form", "Formlar"), BASE)
    o = K.birlestir(a + b + c)
    return {"surum": 1, "kurum": "ornek", "sayfalar": [], "ogeler": o, "sha": K.katalog_sha(o)}


def test_rules():
    kur = E.Kurallar()
    by = {o["ad"]: kur.uygula(o) for o in _katalog()["ogeler"]}
    assert by["Sentetik Taşınır Kayıt Yönergesi"]["elendi"]                    # mali/taşınır
    assert by["Doğrudan Temin Süreci"]["elendi"]                               # satın alma birimi
    assert by["Yıllık İzin Formu"]["elendi"] and not by["Yıllık İzin Formu"]["ilgili"]
    # personel bölümünde ama "ders" geçiyor: tut desenleri elemeyi aşar
    assert not by["Ders Yükü Bildirim Formu"]["elendi"]
    assert by["Yatay Geçiş Başvurusu"]["olcutler"] == ["B.2.3"]
    assert by["Sentetik Danışmanlık Yönergesi"]["olcutler"][0] == "B.3.2"
    assert by["Mezun Memnuniyet Anketi"]["olcutler"][:1] == ["A.4.3"]
    assert by["Sınav Notu İtiraz Dilekçesi"]["olcutler"] == ["B.2.2"]
    assert all(len(r["olcutler"]) <= kur.en_cok for r in by.values())


def _cevapla(d: Path, fn):
    for p in sorted(d.glob("kk-*.json")):
        if p.name.endswith(".out.json"):
            continue
        pkg = json.loads(p.read_text(encoding="utf-8"))
        (d / f"{p.stem}.out.json").write_text(json.dumps({"ogeler": [fn(i) for i in pkg["meta"]["ids"]]},
                                                         ensure_ascii=False), encoding="utf-8")


def test_prepare_apply_and_cache(tmp_path):
    kat = _katalog()
    st = E.prepare(kat, tmp_path)
    es = E.esleme_oku(tmp_path)
    d = tmp_path / E.WORK
    assert st["paket"] == 1 and (d / "kk-001.json").exists() and (d / "README.md").exists()
    pkg = json.loads((d / "kk-001.json").read_text(encoding="utf-8"))
    ids = set(pkg["meta"]["ids"])
    by = {o["id"]: o for o in es["ogeler"]}
    assert all(not by[i]["elendi"] for i in ids)
    assert not any(o["elendi"] for o in es["ogeler"] if o["id"] in ids)
    assert "Sentetik Danışmanlık Yönergesi" in pkg["istem"] and "B.3.2 — " in pkg["istem"]
    assert all(o["kaynak"] == "kural" for o in es["ogeler"])
    # geçersiz cevap: bilinmeyen ölçüt
    _cevapla(d, lambda i: {"id": i, "olcutler": ["B.9.9"], "gerekce": "x"})
    st = E.apply(tmp_path, model="test")
    assert st["gecersiz"] and (d / "GECERSIZ.md").exists()
    # geçerli cevap: yönerge B.3.2, gerisi ilgisiz
    yid = next(o["id"] for o in es["ogeler"] if o["kod"] == "YZ-0001")
    _cevapla(d, lambda i: {"id": i, "olcutler": ["B.3.2"] if i == yid else [], "gerekce": "addan"})
    st = E.apply(tmp_path, model="test")
    assert not st["gecersiz"] and st["islenen"] == len(ids)
    es = E.esleme_oku(tmp_path)
    by = {o["id"]: o for o in es["ogeler"]}
    assert by[yid]["kaynak"] == "model" and by[yid]["olcutler"] == ["B.3.2"] and by[yid]["model"] == "test"
    assert sum(o["ilgili"] for o in es["ogeler"]) == 1
    # katalog değişmedi: model eşlemesi korunur, yeniden paketlenmez
    st = E.prepare(kat, tmp_path)
    assert st["guncel"] and st["paketlenen"] == 0 and st["model_korunan"] == len(ids)
    # bir öğenin adı değişti: yalnız o yeniden paketlenir
    kat2 = json.loads(json.dumps(kat))
    o = next(x for x in kat2["ogeler"] if x["id"] == yid)
    o["ad"] = "Sentetik Akademik Danışmanlık Yönergesi"
    o["anahtar"] = K.anahtar(o)
    kat2["sha"] = K.katalog_sha(kat2["ogeler"])
    st = E.prepare(kat2, tmp_path)
    assert not st["guncel"] and st["paketlenen"] == 1 and st["model_korunan"] == len(ids) - 1


def test_sade_lists_institution_documents(ref_ws_yok, tmp_path):
    ref_ws, tgt = ref_ws_yok
    from bidr.ihtiyac.referans import build_reference
    kat = _katalog()
    E.prepare(kat, tmp_path / "k")
    es = E.esleme_oku(tmp_path / "k")
    for o in es["ogeler"]:                      # model cevabı yerine: sınav dilekçesi B.1.1 de olsun
        if o["kod"] == "FR-0784":
            o.update({"ilgili": True, "olcutler": ["B.1.1", "B.2.2"]})
    res = R.run(tgt, referans=build_reference(ref_ws), out=tmp_path / "o", kurum=es)
    r = {x["olcut"]: x for x in res["sade"]}
    b11 = r["B.1.1"]
    assert "FR-0784" not in b11["belgeler"] + b11["kurum_belgeler"]  # form sade listeye girmez
    # geçen yılın kurum yönergesi katalogda bulundu: ad ve kodla (bağlantı yazılmaz), "ya da güncel hâli" yok.
    # B.2.3'te bölümün kendi kanıtı yok: düzenleme "İstenen belgeler"de adıyla istenir (kullanıcı kararı 2026-11-26
    # 20:35, "Kurum geneli belgeler eksik listesinden istenir"); kurum listesinde yinelenmez
    b23 = r["B.2.3"]
    ist = [x for x in b23["maddeler"] if x["tur"] == "kurum_istek"]
    assert 1 <= len(ist) <= S.KURUM_ISTEK_EN_COK
    assert any("«Sentetik Danışmanlık Yönergesi (YZ-0001)»" in x["metin"] for x in ist)
    assert "YZ-0001" not in b23["kurum_belgeler"] and "https://" not in b23["belgeler"]
    assert "OD2" not in b23["belgeler"] and "«Sentetik Danismanlik Yonergesi»" not in b23["belgeler"]
    assert all(x["tur"] != "kurum" for row in res["sade"] for x in row["maddeler"])
    # bölümün kendi kanıtı olan maddede kurum belgeleri ayrı listede kalır (ana listede tek işaretlenebilir satır)
    for o in es["ogeler"]:
        if o["kod"] == "YZ-0001":
            o["olcutler"] = ["B.2.3", "B.1.1"]
    res = R.run(tgt, referans=build_reference(ref_ws), out=tmp_path / "o1", kurum=es)
    r = {x["olcut"]: x for x in res["sade"]}
    b11 = r["B.1.1"]
    assert "• Sentetik Danışmanlık Yönergesi (YZ-0001)" in b11["kurum_belgeler"].split("\n")
    assert not [x for x in b11["maddeler"] if x["tur"] == "kurum_istek"]
    m = next(x for x in b11["kurum"] if x["tur"] == "kurum")
    wb = load_workbook(res["paths"]["sade"])
    assert wb.sheetnames == list(S.SHEETS)
    sh = wb[S.SHEETS[0]]
    assert [c.value for c in sh[S.BASLIK_SATIRI]] == [h for _, h, _ in S.COLS]
    ad = S._madde_kisa(b11["madde"])
    blok = [row for row in sh.iter_rows(min_row=S.BASLIK_SATIRI + 1) if row[0].value == ad]
    ks = [row for row in blok if row[3].value == S.kurum_satiri(b11["kurum_n"])]
    assert len(ks) == 1 and m["kimden"] in ks[0][4].value.split("\n")
    assert S.bilgi_denetimi(res["sade"], res["paths"]["sade"]) == []
    # eşleme yokken satırlar değişmez
    res0 = R.run(tgt, referans=build_reference(ref_ws), out=tmp_path / "o0")
    assert all(x["tur"] != "kurum" for row in res0["sade"] for x in row["maddeler"])


def test_kurum_ref_match_needs_overlap():
    ogeler = _katalog()["ogeler"]
    g = {"belge_turu": "yonerge", "kanit_adi": "Kurum Sentetik Danismanlik Yonergesi"}
    assert S.katalog_karsiligi(g, ogeler)["kod"] == "YZ-0001"
    assert S.katalog_karsiligi({"belge_turu": "yonerge", "kanit_adi": "Bölüm Seminer Yönergesi"}, ogeler) is None
    assert S.katalog_karsiligi({"belge_turu": "mufredat", "kanit_adi": "Sentetik Danismanlik Yonergesi"},
                               ogeler) is None
    assert S.katalog_karsiligi({"belge_turu": "is_akisi", "kanit_adi": "AK-0010 iş akışı"}, ogeler)["kod"] == "AK-0010"


@pytest.fixture
def ref_ws_yok(tmp_path):
    ref = _ws(tmp_path / "onceki", 2024, {
        "r_yon": ("yonerge", None, "2020-01-01", "Sentetik Danismanlik Yonergesi", YONERGE,
                  [_m("B.2.3", "B.2.3/1", "planla", 2)], "kabul"),
    })
    tgt = _ws(tmp_path / "guncel", 2025, {
        "t_plan": ("bolum_kurulu_karari", True, "2025-02-01", "Bolum Kurulu Karari 2025", PLAN,
                   [_m("B.1.1", "B.1.1/1", "planla", 2)], "kabul"),
    })
    return ref, tgt


def test_cli(tmp_path, monkeypatch, ref_ws_yok, capsys):
    prof = tmp_path / "ornek.yaml"
    prof.write_text(f"kurum: ornek\nad: Örnek\nkatalog:\n  - ad: Yönergeler\n    adres: {BASE}\n    tur: yonerge\n"
                    "  - ad: Talimatlar\n    adres: https://ornek.example/t.html\n    tur: talimat\n    etkin: false\n",
                    encoding="utf-8")
    getir, calls = _fake({BASE: TABLO})
    monkeypatch.setattr(K, "http_getir", lambda *a, **k: getir)
    out = tmp_path / "out"
    assert main(["kurum-katalog", "cek", "--profil", str(prof), "--out", str(out)]) == 0
    assert (out / K.FILE).exists() and calls == [BASE]
    assert main(["kurum-katalog", "prepare", "--out", str(out)]) == 0
    assert (out / E.FILE).exists()
    _cevapla(out / E.WORK, lambda i: {"id": i, "olcutler": ["B.2.3"] if "AK-0010" in i else [], "gerekce": "ad"})
    assert main(["kurum-katalog", "apply", "--out", str(out), "--model", "t"]) == 0
    _, tgt = ref_ws_yok
    assert main(["ihtiyac", "-w", str(tgt), "--out", str(out)]) == 0
    o = capsys.readouterr().out
    assert "kurum belgeleri: 1 ilgili" in o
    bad = tmp_path / "kotu.yaml"
    bad.write_text("katalog:\n  - ad: x\n    adres: https://ornek.example\n    tur: bilinmez\n", encoding="utf-8")
    assert main(["kurum-katalog", "cek", "--profil", str(bad), "--out", str(out)]) == 2


def test_prepare_applies_pending_answers_first(tmp_path):
    """Cevaplanmış ama uygulanmamış paket yeniden `prepare`da kaybolmaz."""
    kat = _katalog()
    E.prepare(kat, tmp_path)
    _cevapla(tmp_path / E.WORK, lambda i: {"id": i, "olcutler": ["A.1.4"], "gerekce": "ad"})
    st = E.prepare(kat, tmp_path, kurallar=E.Kurallar())
    es = E.esleme_oku(tmp_path)
    assert st["paketlenen"] == 0 and st["model_korunan"] > 0
    assert all(o["olcutler"] == ["A.1.4"] for o in es["ogeler"] if o["kaynak"] == "model")
