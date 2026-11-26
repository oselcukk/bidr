"""Teslim modu ve teslim paketi (bidr/teslim/). Yalnız sentetik veri."""
from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

import docx
import pytest

from bidr.check.run import UYARI, denetle, kanit_listeleri
from bidr.cli import main
from bidr.common import Workspace
from bidr.pipeline.checks import Ctx
from bidr.render.run import Options, render
from bidr.teslim import web
from bidr.teslim.mod import teslim_modu
from bidr.teslim.run import EKSIK, MANIFEST, TeslimError, build, durum
from test_check import BEKLENEN, make_doc
from test_render import make_template, write_text

WEB_URL = "https://birim.ornek.edu.tr/duyuru/1"
KOK = "https://kanit.ornek.edu.tr/2025/A/A.1/A.1.2/%5B1-OD3%5D.%20Kurul%20karari.pdf"


class Sahte:
    """PDF aracı taklidi: damgalı HTML'i kaydeder, sahte PDF yazar."""
    ad = "sahte"

    def __init__(self, hata: bool = False):
        self.htmls: list[bytes] = []
        self.hata = hata

    def bas(self, html: Path, pdf: Path, *, ag: bool = False) -> None:
        self.htmls.append(Path(html).read_bytes())
        if self.hata:
            raise web.PdfHatasi("sahte hata")
        Path(pdf).write_bytes(b"%PDF-1.4 sahte")


def _ws(tmp_path: Path, teslim: str | None = None) -> Path:
    """Sentetik çalışma alanı: iki ölçüt, iki PDF ve iki kaydedilmiş web sayfası kanıtı."""
    ws = tmp_path / "ws"
    ws.mkdir()
    make_template(tmp_path / "sablon.docx")
    write_text(ws / "texts", "A.1.1", kanitlar=[{"no": "1_OD3", "ad": "Sentetik kanıt bir", "dosya": "x"},
                                                {"no": "2_OD2", "ad": "Sentetik web sayfası", "dosya": "y"}])
    write_text(ws / "texts", "A.1.2", kanitlar=[{"no": "1_OD3", "ad": "Kurul kararı", "dosya": "x"},
                                                {"no": "2_OD2", "ad": "Adressiz sayfa", "dosya": "y"}])
    ev = ws / "evidence" / "A" / "A.1"
    (ev / "A.1.1").mkdir(parents=True)
    (ev / "A.1.2").mkdir(parents=True)
    (ev / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf").write_bytes(b"%PDF-1.4 sentetik")
    (ev / "A.1.1" / "[2-OD2]. Sentetik web sayfası.html").write_text(
        f'<html><head><link rel="canonical" href="{WEB_URL}"><title>x</title></head>'
        "<body><p>Sentetik duyuru metni ığüşöç.</p></body></html>", encoding="utf-8")
    (ev / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").write_bytes(b"%PDF-1.4 sentetik")
    (ev / "A.1.2" / "[2-OD2]. Adressiz sayfa.html").write_text(
        "<html><body><table><tr><td>Kapanmamış tablo", encoding="utf-8")
    (ws / "evidence" / ".bidr-evidence.json").write_text("{}", encoding="utf-8")
    rows = [("1_OD3", "A.1.1", 3, "Sentetik kanıt bir", "A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf", "", ""),
            ("2_OD2", "A.1.1", 2, "Sentetik web sayfası", "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html", "", ""),
            ("1_OD3", "A.1.2", 3, "Kurul kararı", "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf", KOK, "klasor"),
            ("2_OD2", "A.1.2", 2, "Adressiz sayfa", "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html", "", "")]
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["kanit_no", "olcut", "od", "ad", "dosya", "baglanti", "baglanti_kaynagi"])
        w.writerows(rows)
    if teslim:
        (ws / "config.yaml").write_text(f"rapor:\n  teslim: {teslim}\n", encoding="utf-8")
    return ws


def _render(ws: Path, tmp_path: Path, teslim: str) -> dict[str, list]:
    render(tmp_path / "sablon.docx", ws / "report.docx", texts_dir=ws / "texts", audit_path=None,
           index_path=ws / "evidence-index.csv", opts=Options(kanit_bicimi="kilavuz"), teslim=teslim)
    return kanit_listeleri(docx.Document(str(ws / "report.docx")))


# -- mod ----------------------------------------------------------------------------------------

def test_teslim_modu(tmp_path):
    assert teslim_modu(tmp_path) == "dekanlik"                     # config yok: varsayılan
    (tmp_path / "config.yaml").write_text("rapor:\n  teslim: Baglanti\n", encoding="utf-8")
    assert teslim_modu(tmp_path) == "baglanti"
    (tmp_path / "config.yaml").write_text("rapor:\n  teslim: posta\n", encoding="utf-8")
    with pytest.raises(ValueError, match="rapor.teslim"):
        teslim_modu(tmp_path)


# -- web: adres ve damga -----------------------------------------------------------------------

@pytest.mark.parametrize("html,beklenen", [
    ('<!-- saved from url=(0035)https://ornek.edu.tr/sayfa/42?x=1 -->\n<html>', ("https://ornek.edu.tr/sayfa/42?x=1", "saved_from")),
    ('<!--\n Page saved with SingleFile \n url: https://ornek.edu.tr/a/b \n saved date: x\n-->', ("https://ornek.edu.tr/a/b", "singlefile")),
    ('<head><link href="https://ornek.edu.tr/c" rel="alternate canonical"></head>', ("https://ornek.edu.tr/c", "canonical")),
    ("<head><meta content='https://ornek.edu.tr/d&amp;e' property='og:url'></head>", ("https://ornek.edu.tr/d&e", "og_url")),
    ('<head><link rel="canonical" href="https://ornek.edu.tr/"><base href="https://ornek.edu.tr/e/"></head>',
     ("https://ornek.edu.tr/e/", "base")),                         # ana sayfa canonical'ı sayılmaz
    ('<head><link rel="canonical" href="/goreli"></head><a href="https://baska.org/x">', (None, "")),
])
def test_html_url(tmp_path, html, beklenen):
    p = tmp_path / "s.html"
    p.write_text(html, encoding="utf-8")
    assert web.html_url(p) == beklenen


def test_web_url_oncelik(tmp_path):
    p = tmp_path / "s.html"
    p.write_text(f'<link rel="canonical" href="{WEB_URL}">', encoding="utf-8")
    assert web.web_url(p, "https://insan.ornek.edu.tr/x", "insan") == ("https://insan.ornek.edu.tr/x", "dizin:insan")
    assert web.web_url(p, KOK, "klasor") == (WEB_URL, "canonical")      # kök klasör bağlantısı özgün adres değil
    assert web.web_url(None, "", "") == (None, "")


def test_damgali_html():
    raw = "<html><head><title>t</title></head><body class='x'><p>ığ</p></body></html>".encode("iso-8859-9")
    out = web.damgali_html(raw, web.damga_metni(None, "20.11.2026"))
    i_body = out.index(b"<body class='x'>")
    assert out.index(b'class="bidr-damga"') > i_body                # üst damga gövdenin başında
    assert b"script-src 'none'" in out and b"body::after" in out       # betik kapalı; alt damga CSS
    assert raw[raw.index(b"<p>"):] in out                              # sayfa baytları değişmeden
    metin = "Kaynak: bağlantı bilinmiyor · Alınma (erişim) tarihi: 20.11.2026"
    assert out[i_body:].decode("latin-1").count("Kaynak: ba&#287;lant&#305; bilinmiyor") == 1
    assert web._css_dizesi(metin).startswith('"Kaynak: ba\\00011f l') and web._css_dizesi(metin).isascii()
    g = web.damgali_html(b"<p>govdesiz</p>", "K")               # body/head yok: damga ve stil başa
    assert g.startswith(b'<div class="bidr-damga"') and b"script-src 'none'" in g and g.endswith(b"<p>govdesiz</p>")


def test_pdf_araci_yok(monkeypatch):
    monkeypatch.setenv("BIDR_CHROME", "/yok/chrome")
    import builtins
    gercek = builtins.__import__

    def imp(name, *a, **kw):
        if name == "weasyprint":
            raise ImportError("yok")
        return gercek(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", imp)
    with pytest.raises(web.PdfAraciYok, match="BIDR_CHROME"):
        web.pdf_araci()


@pytest.mark.skipif(web.chrome_yolu() is None, reason="Chrome/Chromium kurulu değil")
def test_chrome_gercek_pdf(tmp_path):
    from pypdf import PdfReader
    src = tmp_path / "s.html"
    src.write_text("<html><body><table><tr><td>Sentetik tablo ığüş", encoding="utf-8")
    out = tmp_path / "s.pdf"
    assert web.web_pdf(src, out, url=WEB_URL, tarih="20.11.2026", arac=web.pdf_araci("chrome")) == "yerel"
    text = " ".join(" ".join(p.extract_text().split()) for p in PdfReader(out).pages)
    assert text.count(f"Kaynak: {WEB_URL} · Alınma (erişim) tarihi: 20.11.2026") == 2
    assert "Sentetik tablo ığüş" in text


# -- render: teslim moduna göre kanıt satırı ------------------------------------------------------

def test_render_dekanlik_ve_baglanti(tmp_path):
    ws = _ws(tmp_path)
    L = _render(ws, tmp_path, "dekanlik")
    a1, a2 = L["A.1.1"], L["A.1.2"]
    assert a1[1].metin == f"[2-OD2]. Sentetik web sayfası ({WEB_URL})" and a1[1].baglanti == WEB_URL
    assert a1[0].baglanti is None
    assert a2[0].baglanti is None and a2[0].metin == "[1-OD3]. Kurul kararı"     # kök klasör bağlantısı yok
    assert a2[1].metin == "[2-OD2]. Adressiz sayfa" and a2[1].baglanti is None   # adres uydurulmaz
    L = _render(ws, tmp_path, "baglanti")                                       # eski davranış
    assert L["A.1.1"][1].metin == "[2-OD2]. Sentetik web sayfası" and L["A.1.1"][1].baglanti is None
    assert L["A.1.2"][0].baglanti == KOK


# -- denetle: bağlantısız kanıt -----------------------------------------------------------------

def test_denetle_baglantisiz_moda_gore(tmp_path):
    rep = make_doc(tmp_path / "r.docx")
    s = denetle(rep, beklenen=BEKLENEN, teslim_modu="dekanlik")
    assert "baglantisiz_kanit" not in [b.kod for b in s.bulgular]
    assert s.kritik == 0 and s.bilgi["baglanti"]["baglantisiz"] == 4 and "dekanlik" in s.bilgi["baglanti"]["not"]
    s = denetle(rep, beklenen=BEKLENEN, teslim_modu="baglanti")
    b = [x for x in s.bulgular if x.kod == "baglantisiz_kanit"]
    assert len(b) == 4 and {x.seviye for x in b} == {UYARI} and s.kritik == 0
    s = denetle(rep, beklenen=BEKLENEN)                                         # mod verilmezse denetim yok
    assert "baglanti" not in s.bilgi


def test_denetle_cli_dekanlik(tmp_path, monkeypatch, capsys):
    cdir = tmp_path / "criteria"
    cdir.mkdir()
    (cdir / "yokak-2025.yaml").write_text(
        "areas: [{id: A, title: x}]\ncriteria: [{id: A.1, title: x}]\n"
        "sub_criteria: [{id: A.1.1, title: x}, {id: A.1.2, title: y}]\n", encoding="utf-8")
    monkeypatch.setenv("BIDR_CRITERIA_DIR", str(cdir))
    ws = tmp_path / "ws"
    ws.mkdir()
    make_doc(ws / "report.docx")
    assert main(["denetle", "-w", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "bilgi: 4/4 kanıt satırı bağlantısız" in out
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert js["ozet"]["yayima_hazir"] and js["bilgi"]["teslim_modu"] == "dekanlik"
    (ws / "config.yaml").write_text("rapor:\n  teslim: baglanti\n", encoding="utf-8")
    assert main(["denetle", "-w", str(ws)]) == 0                              # uyarı engel değil
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert js["ozet"]["kodlar"]["baglantisiz_kanit"] == {"seviye": UYARI, "sayi": 4}
    (ws / "config.yaml").write_text("rapor:\n  teslim: yok\n", encoding="utf-8")
    assert main(["denetle", "-w", str(ws)]) == 2


# -- teslim paketi ------------------------------------------------------------------------------

def _rows(p: Path) -> list[dict]:
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_paket(tmp_path):
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    (ws / "evidence" / "A" / "A.1" / "A.1.2" / "[3-OD1]. Listede yok.pdf").write_bytes(b"%PDF-1.4")
    arac = Sahte()
    res = build(ws, tarih="2025-12-31", arac=arac)
    out = ws / "teslim"
    assert res.eksik == [] and Path(res.cikti) == out
    assert (out / "report.docx").read_bytes() == (ws / "report.docx").read_bytes()
    k = out / "kanitlar" / "A" / "A.1"
    assert sorted(p.name for p in (k / "A.1.1").iterdir()) == [
        "[1-OD3]. Sentetik kanıt bir.pdf", "[2-OD2]. Sentetik web sayfası.html", "[2-OD2]. Sentetik web sayfası.pdf"]
    assert not (k / "A.1.2" / "[3-OD1]. Listede yok.pdf").exists()                 # listede değil: alınmaz
    assert any("Listede yok" in u for u in res.uyarilar)
    assert any("Adressiz sayfa" in u and "bulunamadı" in u for u in res.uyarilar)
    # damga: özgün adres ve alınma tarihi; adres bilinmiyorsa uydurulmaz
    h = [x.decode("latin-1") for x in arac.htmls]
    assert any(f"Kaynak: {WEB_URL} &#183; Al&#305;nma (eri&#351;im) tarihi: 31.12.2025" in x for x in h)
    assert any("Kaynak: ba&#287;lant&#305; bilinmiyor" in x for x in h)
    rows = {(r["Ölçüt"], r["Kanıt no"]): r for r in _rows(out / "kanit-dizini.csv")}
    assert len(rows) == 4 and all("-OD" in no for _, no in rows)            # kılavuz gösterimi (iç n_ODk değil)
    w = rows[("A.1.1", "2-OD2")]
    assert w["Kanıt adı"] == "Sentetik web sayfası" and w["Özgün bağlantı"] == WEB_URL
    assert w["Paketteki dosya"] == "kanitlar/A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html"
    assert w["PDF kopyası"].endswith("Sentetik web sayfası.pdf") and w["Alınma tarihi"] == "2025-12-31"
    assert rows[("A.1.2", "2-OD2")]["Özgün bağlantı"] == "bağlantı bilinmiyor"
    assert rows[("A.1.2", "1-OD3")]["Özgün bağlantı"] == ""                        # kök klasör bağlantısı değil
    assert all(r["Durum"] == "tamam" for r in rows.values())
    assert all((out / r["Paketteki dosya"]).is_file() for r in rows.values())     # her satır bir dosya
    from openpyxl import load_workbook
    sh = load_workbook(out / "kanit-dizini.xlsx").active
    assert sh.max_row == 5 and sh["G3"].hyperlink.target == WEB_URL
    with zipfile.ZipFile(ws / "teslim.zip") as z:
        names = z.namelist()
    assert "teslim/report.docx" in names and "teslim/kanit-dizini.xlsx" in names
    assert "teslim/kanitlar/A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.pdf" in names
    assert not any("/." in n for n in names) and not (out / EKSIK).exists()
    m = json.loads((ws / MANIFEST).read_text(encoding="utf-8"))
    assert m["web"] == 2 and m["web_pdf"] == 2 and m["baglanti_bilinmiyor"] == 1 and m["pdf_araci"] == "sahte"
    # yeniden üretim: eski paket güvenle silinir
    assert build(ws, tarih="2025-12-31", arac=Sahte(), zip_yap=False).eksik == []


def test_paket_eksik(tmp_path):
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    (ws / "evidence" / "A" / "A.1" / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf").rename(
        ws / "evidence" / "A" / "A.1" / "A.1.1" / "[1-OD2]. Sentetik kanıt bir.pdf")
    (ws / "evidence" / "A" / "A.1" / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").unlink()
    res = build(ws, arac=Sahte(hata=True))
    e = "\n".join(res.eksik)
    assert len(res.eksik) == 4
    assert "OD uyuşmuyor" in e and "dosya yok" in e and e.count("PDF kopyası üretilemedi") == 2
    txt = (ws / "teslim" / EKSIK).read_text(encoding="utf-8")
    assert "EKSİK TESLİM PAKETİ" in txt and "Kurul kararı" in txt
    assert "A.1.2 [1-OD3] Kurul kararı" in txt and "_OD" not in txt         # raporun kılavuz gösterimi
    rows = _rows(ws / "teslim" / "kanit-dizini.csv")
    assert sum(r["Durum"].startswith("eksik") for r in rows) == 4


def test_paket_ayni_kaynak_tek_numara(tmp_path):
    """Aynı kaynağın belgeleri tek numarayı paylaşır (dizinde numaranın birden çok satırı): dizinin o
    numaraya yazdığı dosyaların hepsi pakete girer; dizinde olmayan artık dosya eksik saydırmaz
    (kör test 2026-11-20, Kimya: 18 EKSIK satırının 17'si)."""
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    d = ws / "evidence" / "A" / "A.1" / "A.1.2"
    (d / "[1-OD3]. Kurul kararı.pdf").rename(d / "[1-OD3]. Kurul kararı (2025-01-14).pdf")
    (d / "[1-OD3]. Kurul kararı (2025-03-17).pdf").write_bytes(b"%PDF-1.4 ikinci")
    (d / "[1-OD3]. Eski dosyalama artığı.pdf").write_bytes(b"%PDF-1.4 artik")
    with open(ws / "evidence-index.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    for r in rows:
        if r[4].endswith("Kurul kararı.pdf"):
            r[4] = r[4].replace("Kurul kararı.pdf", "Kurul kararı (2025-01-14).pdf")
    rows.append(["1_OD3", "A.1.2", "3", "Kurul kararı", "A/A.1/A.1.2/[1-OD3]. Kurul kararı (2025-03-17).pdf", "", ""])
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    res = build(ws, tarih="2025-12-31", arac=Sahte(), zip_yap=False)
    assert res.eksik == []
    got = sorted(p.name for p in (ws / "teslim" / "kanitlar" / "A" / "A.1" / "A.1.2").iterdir())
    assert got == ["[1-OD3]. Kurul kararı (2025-01-14).pdf", "[1-OD3]. Kurul kararı (2025-03-17).pdf",
                   "[2-OD2]. Adressiz sayfa.html", "[2-OD2]. Adressiz sayfa.pdf"]
    assert any("Eski dosyalama artığı" in u and "dizinde olmayan" in u for u in res.uyarilar)
    dz = [r for r in _rows(ws / "teslim" / "kanit-dizini.csv") if r["Ölçüt"] == "A.1.2" and r["Kanıt no"] == "1-OD3"]
    assert len(dz) == 2 and all(r["Durum"] == "tamam" and r["Kanıt adı"] == "Kurul kararı" for r in dz)
    # dizin numaranın dosyalarını bilmiyorsa (dizinde tek satır, klasörde iki aday) eski kural: eksik
    rows = [r for r in rows if not r[4].endswith("(2025-03-17).pdf")]
    with open(ws / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows(rows)
    (d / "[1-OD3]. Eski dosyalama artığı.pdf").unlink()
    (d / "[1-OD3]. Kurul kararı (2025-01-14).pdf").rename(d / "[1-OD3]. Başka ad.pdf")
    res = build(ws, tarih="2025-12-31", arac=Sahte(), zip_yap=False)
    assert len(res.eksik) == 1 and "birden çok dosya" in res.eksik[0]


def test_paket_hatalar(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    with pytest.raises(TeslimError, match="rapor yok"):
        build(ws, arac=Sahte())
    _render(ws, tmp_path, "dekanlik")
    other = tmp_path / "dolu"
    other.mkdir()
    (other / "not.txt").write_text("x")
    with pytest.raises(TeslimError, match="boş değil"):
        build(ws, other, arac=Sahte())
    with pytest.raises(TeslimError, match="çalışma alanının"):
        build(ws, ws, arac=Sahte())
    # web kanıtı var, araç yok: hiçbir şey yazılmaz
    import bidr.teslim.run as R

    def yok(tercih="otomatik"):
        raise web.PdfAraciYok("yok")
    monkeypatch.setattr(R, "pdf_araci", yok)
    with pytest.raises(web.PdfAraciYok):
        build(ws)
    assert not (ws / "teslim").exists() and not (ws / MANIFEST).exists()


def test_cli_ve_hat_durumu(tmp_path, monkeypatch, capsys):
    import bidr.teslim.run as R
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    ctx = Ctx(Workspace(ws), None, lambda s: s.replace("{ws}", str(ws)), {"komut": ["bidr teslim -w {ws}"]})
    c = durum(ctx)
    assert c.kim == "komut" and "üretilmedi" in c.neden
    monkeypatch.setattr(R, "pdf_araci", lambda tercih="otomatik": Sahte())
    assert main(["teslim", "-w", str(ws), "--tarih", "2025-12-31"]) == 0       # yönetilmeyen WS: kapı yok
    out = capsys.readouterr().out
    assert "zip:" in out and '"web_pdf": 2' in out
    c = durum(ctx)
    assert c.bitti and c.ilerleme["web_pdf"] == 2 and any("özgün adresi" in u for u in c.uyarilar)
    _render(ws, tmp_path, "baglanti")                                          # rapor değişti: paket eski
    assert durum(ctx).kim == "komut" and "eski" in durum(ctx).neden
    (ws / "evidence" / "A" / "A.1" / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").unlink()
    assert main(["teslim", "-w", str(ws)]) == 1
    assert "EKSİK PAKET" in capsys.readouterr().out
    c = durum(ctx)
    assert c.kim == "insan" and "paket eksik (1)" in c.neden
    assert main(["teslim", "-w", str(ws), "--tarih", "31.12.2025"]) == 2
    # bağlantı modu: paket yoksa aşama atlanır
    (ws / MANIFEST).unlink()
    (ws / "config.yaml").write_text("rapor:\n  teslim: baglanti\n", encoding="utf-8")
    assert durum(ctx).atlandi


def _maskele(ws: Path, kayitlar: dict[str, str]) -> None:
    """`bidr maskele` çıktısı taklidi: rapor + maskeli kopyalar (durum tamam olanlar)."""
    import os
    import time
    mk = ws / "evidence-maskeli"
    recs = []
    for rel, d in kayitlar.items():
        recs.append({"dosya": rel, "durum": d, "neden": "" if d == "tamam" else "kalan: eposta×1"})
        if d == "basarisiz":                             # kısmen maskeli kopya (maskeleme-basarisiz/)
            kp = ws / "maskeleme-basarisiz" / rel
            kp.parent.mkdir(parents=True, exist_ok=True)
            kp.write_bytes((ws / "evidence" / rel).read_bytes().replace(b"sentetik", b"KISMI"))
            recs[-1]["kopya"] = f"maskeleme-basarisiz/{rel}"
        if d in ("tamam", "elle_maskelendi"):
            (mk / rel).parent.mkdir(parents=True, exist_ok=True)
            src = (ws / "evidence" / rel).read_bytes()
            (mk / rel).write_bytes(src.replace(b"Sentetik", b"MASKELI").replace(b"sentetik", b"MASKELI"))
    (ws / "maskeleme-raporu.json").write_text(json.dumps({"surum": 1, "maskeli_klasor": str(mk),
                                                          "dosyalar": recs}), encoding="utf-8")
    t = time.time() + 5                                  # rapor kanıt dosyalarından sonra
    os.utime(ws / "maskeleme-raporu.json", (t, t))


def test_paket_maskeleme(tmp_path, capsys):
    """Politika 2026-11-22 (ikinci karar): maskeleme kararı bekleyen kanıt dışlanmaz; o anki maskeli hâli (yoksa
    özgünü) pakete girer ve listelenir. `--kararsizlari-disla` eski davranış."""
    from bidr.teslim.run import MASKE_UYARI
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    _acik(ws)
    _maskele(ws, {"A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf": "tamam",
                  "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html": "tamam",
                  "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf": "basarisiz",
                  "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html": "hata"})     # maskelenemedi: özgünü girer
    arac = Sahte()
    res = build(ws, arac=arac, zip_yap=False)
    k = ws / "teslim" / "kanitlar" / "A" / "A.1"
    assert (k / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf").read_bytes() == b"%PDF-1.4 MASKELI"
    assert any(b"MASKELI duyuru" in h for h in arac.htmls)                 # web PDF maskeli HTML'den
    # kararı bekleyen: kısmen maskeli kopya pakette; maskelenemeyen: özgünü pakette (+ web PDF'i)
    assert (k / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").read_bytes() == b"%PDF-1.4 KISMI"
    assert (k / "A.1.2" / "[2-OD2]. Adressiz sayfa.html").is_file()
    assert (k / "A.1.2" / "[2-OD2]. Adressiz sayfa.pdf").is_file()
    assert res.eksik == [] and res.kontrol_bekliyor == [] and not (ws / "teslim" / EKSIK).exists()
    rows = {(r["Ölçüt"], r["Kanıt no"]): r for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert {key: r["Maskeleme"] for key, r in rows.items()} == {
        ("A.1.1", "1-OD3"): "tamam", ("A.1.1", "2-OD2"): "tamam",
        ("A.1.2", "1-OD3"): "karar bekliyor", ("A.1.2", "2-OD2"): "maskelenmedi"}
    assert rows[("A.1.2", "1-OD3")]["Paketteki dosya"] == "kanitlar/A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf"
    kb = {x["kanit"].rsplit("/", 1)[1]: x for x in res.karar_bekleyen}
    assert set(kb) == {"[1-OD3]. Kurul kararı.pdf", "[2-OD2]. Adressiz sayfa.html"}
    assert all(x["pakette"] and x["dosya"].startswith("kanitlar/") for x in kb.values())
    assert "basarisiz" in kb["[1-OD3]. Kurul kararı.pdf"]["neden"]
    assert "maskeleme hata" in kb["[2-OD2]. Adressiz sayfa.html"]["neden"]
    assert any("maskeleme kararı bekleyen belge: 2" in u and "1 tanesi MASKELENMEDİ" in u for u in res.uyarilar)
    uy = (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    assert "MASKELEME KARARI BEKLEYEN BELGELER: 2" in uy and "Kurul kararı" in uy and "maskelenmedi" in uy
    m = json.loads((ws / MANIFEST).read_text(encoding="utf-8"))
    assert m["maskeleme"] == {"rapor": True, "tamam": 2, "elle maskelendi": 0, "karar bekliyor": 1, "maskelenmedi": 1,
                              "kontrol bekliyor": 0, "yapılmadı": 0}
    assert len(m["karar_bekleyen"]) == 2 and m["karar_bekleyen_uyarisi"].startswith("maskeleme kararı bekleyen belge: 2")
    ctx = Ctx(Workspace(ws), None, lambda s: s, {"komut": ["bidr teslim -w {ws}"]})
    c = durum(ctx)
    assert c.bitti and any("maskeleme kararı bekleyen belge: 2" in u for u in c.uyarilar)
    # eski davranış (isteğe bağlı): kararı bekleyen pakete girmez, dizinde satır kalır, insan bekler
    res = build(ws, arac=Sahte(), zip_yap=False, kararsizlari_disla=True)
    assert not (k / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").exists()
    assert not (k / "A.1.2" / "[2-OD2]. Adressiz sayfa.html").exists()
    assert len(res.kontrol_bekliyor) == 2 and res.eksik == []
    rows = {(r["Ölçüt"], r["Kanıt no"]): r for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert rows[("A.1.2", "1-OD3")]["Maskeleme"] == "kontrol bekliyor" and rows[("A.1.2", "1-OD3")]["Paketteki dosya"] == ""
    assert "KONTROL BEKLİYOR: 2 DOSYA" in (ws / "teslim" / EKSIK).read_text(encoding="utf-8")
    c = durum(ctx)
    assert c.kim == "insan" and "kontrol bekliyor: 2 dosya" in c.neden
    # CLI: varsayılan çıkış 0 + uyarı; --kararsizlari-disla 1
    import bidr.teslim.run as TR
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(TR, "pdf_araci", lambda tercih="otomatik": Sahte())
    try:
        assert main(["teslim", "-w", str(ws), "--tarih", "2025-12-31"]) == 0
        err = capsys.readouterr().err
        assert "MASKELEME KARARI BEKLEYEN BELGELER: 2" in err and "MASKELENMEDİ" in err
        assert main(["teslim", "-w", str(ws), "--tarih", "2025-12-31", "--kararsizlari-disla"]) == 1
    finally:
        mp.undo()
    capsys.readouterr()
    # karar / elle yükleme sonrası (rapor: tamam ya da elle_maskelendi): liste boşalır
    _maskele(ws, {"A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf": "tamam",
                  "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html": "tamam",
                  "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf": "tamam",
                  "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html": "elle_maskelendi"})
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert (k / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").read_bytes() == b"%PDF-1.4 MASKELI"
    assert res.karar_bekleyen == [] and durum(ctx).bitti and not (ws / "teslim" / MASKE_UYARI).exists()
    assert not any("kararı bekleyen" in u for u in durum(ctx).uyarilar)
    rows = {(r["Ölçüt"], r["Kanıt no"]): r["Maskeleme"] for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert rows[("A.1.2", "2-OD2")] == "elle maskelendi"
    # tamam ama kararı verilmemiş öneri bölgesi var: karar bekliyor, çerçevesiz teslim kopyası girer
    rep = json.loads((ws / "maskeleme-raporu.json").read_text(encoding="utf-8"))
    rel = "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf"
    r = next(x for x in rep["dosyalar"] if x["dosya"] == rel)
    tk = ws / "maskeleme-bekleyen" / rel
    tk.parent.mkdir(parents=True, exist_ok=True)
    tk.write_bytes(b"%PDF-1.4 CERCEVESIZ")
    r.update(onay_bekleyen=1, teslim_kopya=f"maskeleme-bekleyen/{rel}")
    (ws / "maskeleme-raporu.json").write_text(json.dumps(rep), encoding="utf-8")
    import os
    import time
    t = time.time() + 5
    os.utime(ws / "maskeleme-raporu.json", (t, t))
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert (k / "A.1.2" / "[1-OD3]. Kurul kararı.pdf").read_bytes() == b"%PDF-1.4 CERCEVESIZ"
    assert [x["kanit"] for x in res.karar_bekleyen] == [rel] and "öneri bölgesi 1" in res.karar_bekleyen[0]["neden"]
    # kanıt maskelemeden sonra yeniden yazıldı: maskeli kopya eski → teslim DURMAZ; özgünü girer, adıyla uyarılır
    f = ws / "evidence" / "A" / "A.1" / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf"
    t = (ws / "maskeleme-raporu.json").stat().st_mtime + 10
    os.utime(f, (t, t))
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert (k / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf").read_bytes() == b"%PDF-1.4 sentetik"
    assert "kanıt kümesinden eski" in res.maskeleme_eksigi and "maskelenmeden" in res.maskeleme_uyarisi
    kb = {x["kanit"]: x for x in res.karar_bekleyen}
    assert kb["A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf"]["maskeleme"] == "maskelenmedi"
    uy = (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    assert "KİŞİSEL VERİ MASKELEMESİ" in uy and "Sentetik kanıt bir" in uy
    c = durum(ctx)
    assert c.bitti and any("maskelenmeden" in u for u in c.uyarilar)
    # maskeleme raporu değişince paket eskir
    t = time.time() + 30
    os.utime(f, (t - 10, t - 10))
    (ws / "maskeleme-raporu.json").write_text(json.dumps(dict(rep, zaman="yeni koşu")), encoding="utf-8")
    os.utime(ws / "maskeleme-raporu.json", (t, t))
    assert durum(ctx).kim == "komut" and "paketi eski" in durum(ctx).neden


def test_paket_maskeleme_yapilmadi(tmp_path):
    """Maskeleme seçili değil: paket özgün dosyalarla, "kanıtlar maskelenmeden paketlendi" uyarısıyla."""
    from bidr.teslim.run import MASKE_UYARI, MASKESIZ_NOT
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert {r["Maskeleme"] for r in _rows(ws / "teslim" / "kanit-dizini.csv")} == {"yapılmadı"}
    assert res.elle_bakilacak == [] and not res.maskeleme and not res.maskeleme_acik
    assert MASKESIZ_NOT in res.maskeleme_uyarisi and res.karar_bekleyen == [] and res.maskesiz == []
    assert MASKESIZ_NOT in (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    c = durum(Ctx(Workspace(ws), None, lambda s: s, {"komut": ["bidr teslim -w {ws}"]}))
    assert c.bitti and any(MASKESIZ_NOT in u for u in c.uyarilar)


def test_paket_adi_birim_ve_donemden(tmp_path):
    from bidr.teslim.run import paket_adi
    assert paket_adi(tmp_path) == "teslim"
    (tmp_path / "config.yaml").write_text("bidr:\n  birim: Sentetik Bölümü\n  donem: 2025\n", encoding="utf-8")
    assert paket_adi(tmp_path) == "BIDR-2025-Sentetik-Bölümü"


def _acik(ws: Path) -> None:
    """Bölüm kişisel veri maskelemesini seçmiş (config.yaml privacy.maskeleme)."""
    (ws / "config.yaml").write_text("privacy:\n  maskeleme:\n    etiket_alani: true\n", encoding="utf-8")


def test_maskeleme_uyarisi_engel_degil(tmp_path, capsys, monkeypatch):
    """Karar 2026-11-25: maskeleme teslimi durdurmaz. Maskeleme seçimi bölümün ŞİMDİKİ seçimidir (config / kaynak
    maskeli kopya); çalışma alanında kalan rapor dosyası seçim sayılmaz. Açıkken maskeli kopya yok / eksik / eskiyse
    paket yine üretilir, maskeli kopyası olmayan kanıt özgünüyle girer ve adıyla listelenir; hat `kanit_maskele`
    yalnız açıkken ve yalnız yeniden koşunun gidereceği eksikte komut önerir; teslimin önkoşulu değildir."""
    import os
    import time

    import bidr.teslim.run as TR
    from bidr.teslim.run import (MASKE_UYARI, MASKESIZ_NOT, kanit_maskele_durum, maske_eksigi, maskeleme_kullaniliyor,
                                 maskeleme_secimi)
    monkeypatch.setattr(TR, "pdf_araci", lambda tercih="otomatik": Sahte())
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    kctx = Ctx(Workspace(ws), None, lambda s: s.replace("{ws}", str(ws)), {"komut": ["bidr maskele -w {ws}"]})
    tctx = Ctx(Workspace(ws), None, lambda s: s.replace("{ws}", str(ws)), {"komut": ["bidr teslim -w {ws}"]})
    # seçim yok: aşama atlanır, paket uyarıyla
    assert maskeleme_kullaniliyor(ws) is None and maske_eksigi(ws) is None and kanit_maskele_durum(kctx).atlandi
    # eski rapor dosyaları seçim sayılmaz
    (ws / "maskeleme-kaynak-raporu.json").write_text("{}", encoding="utf-8")
    assert maskeleme_secimi(ws) == (None, "") and kanit_maskele_durum(kctx).atlandi
    assert main(["teslim", "-w", str(ws)]) == 0
    io = capsys.readouterr()
    assert MASKESIZ_NOT in io.err and (ws / "teslim" / MASKE_UYARI).is_file()
    # açıkça kapalı: maskeleme raporu olsa da kullanılmaz
    hepsi = {"A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf": "tamam",
             "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html": "tamam",
             "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf": "tamam",
             "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html": "tamam"}
    _maskele(ws, hepsi)
    (ws / "config.yaml").write_text("privacy:\n  maskeleme: false\n", encoding="utf-8")
    assert maskeleme_secimi(ws)[0] is False and kanit_maskele_durum(kctx).atlandi
    res = build(ws, arac=Sahte(), zip_yap=False)
    k = ws / "teslim" / "kanitlar" / "A" / "A.1" / "A.1.1" / "[1-OD3]. Sentetik kanıt bir.pdf"
    assert k.read_bytes() == b"%PDF-1.4 sentetik" and MASKESIZ_NOT in res.maskeleme_uyarisi
    # açık, kanıt maskelemesi yapılmamış: paket yine üretilir, her kanıt adıyla "maskelenmedi"
    _acik(ws)
    (ws / "maskeleme-raporu.json").unlink()
    shutil.rmtree(ws / "evidence-maskeli")
    assert maskeleme_kullaniliyor(ws) == "config.yaml privacy.maskeleme" and "yapılmamış" in maske_eksigi(ws)
    c = kanit_maskele_durum(kctx)
    assert c.kim == "komut" and c.komutlar == [f"bidr maskele -w {ws}"]
    assert main(["teslim", "-w", str(ws)]) == 0
    assert main(["teslim", "-w", str(ws), "--taslak"]) == 0
    err = capsys.readouterr().err
    assert "UYARI kişisel veri" in err and "MASKELENMEDİ" in err
    m = json.loads((ws / MANIFEST).read_text(encoding="utf-8"))
    assert m["maskeleme_acik"] and len(m["maskesiz"]) == 4 and "yapılmamış" in m["maskeleme_eksigi"]
    uy = (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    assert "MASKELİ KOPYASI OLMAYAN KANITLAR (ÖZGÜN HÂLİYLE PAKETTE): 4" in uy and "Kurul kararı" in uy
    c = durum(tctx)
    assert c.kim == "komut" and "taslak" in c.neden                 # --taslak paketi bitmiş sayılmaz (eski kural)
    assert main(["teslim", "-w", str(ws)]) == 0
    capsys.readouterr()
    c = durum(tctx)
    assert c.bitti and any("maskelenmeden" in u for u in c.uyarilar)
    # rapor var ama maskeli klasör yok / kopya eksik / raporda olmayan / eski
    _maskele(ws, hepsi)
    shutil.rmtree(ws / "evidence-maskeli")
    assert "klasörü yok" in maske_eksigi(ws) and kanit_maskele_durum(kctx).kim == "komut"
    _maskele(ws, hepsi)
    (ws / "evidence-maskeli" / "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf").unlink()
    assert "1 kanıtın maskeli kopyası" in maske_eksigi(ws)
    c = kanit_maskele_durum(kctx)                                    # yeniden koşu gidermez: uyarıyla biter, döngü yok
    assert c.bitti and any("gidermez" in u for u in c.uyarilar)
    res = build(ws, arac=Sahte(), zip_yap=False)
    kb = {x["kanit"]: x for x in res.karar_bekleyen}
    assert kb["A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf"]["maskeleme"] == "maskelenmedi"
    _maskele(ws, dict(list(hepsi.items())[:3]))
    assert "1 kanıt maskeleme raporunda yok" in maske_eksigi(ws) and kanit_maskele_durum(kctx).kim == "komut"
    _maskele(ws, hepsi)
    t = (ws / "maskeleme-raporu.json").stat().st_mtime + 10
    os.utime(ws / "evidence" / ".bidr-evidence.json", (t, t))
    assert "kanıt kümesinden eski" in maske_eksigi(ws) and kanit_maskele_durum(kctx).kim == "komut"
    # güncel: aşama bitti, paket maskeli kopyalardan, uyarı yok
    _maskele(ws, hepsi)
    t = time.time() + 20
    os.utime(ws / "maskeleme-raporu.json", (t, t))
    assert maske_eksigi(ws) is None and kanit_maskele_durum(kctx).bitti
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert res.maskeleme_uyarisi is None and not (ws / "teslim" / MASKE_UYARI).exists()
    assert k.read_bytes() == b"%PDF-1.4 MASKELI" and durum(tctx).bitti
    # teslimin önkoşulu değil
    from bidr.pipeline.state import stage
    assert stage("teslim")["onkosul"] == ["denetle"]
    # bağlantı modu, paket yok: aşama atlanır
    (ws / MANIFEST).unlink()
    (ws / "config.yaml").write_text("privacy:\n  maskeleme:\n    etiket_alani: true\nrapor:\n  teslim: baglanti\n",
                                    encoding="utf-8")
    assert kanit_maskele_durum(kctx).atlandi


def test_maskeleme_kapisi_asiri_kapatma_bekliyor(tmp_path, capsys, monkeypatch):
    """`tamam` ama aşırı kapatma ölçümü eşiği aşan kayıt (`asiri_kapatma_bekliyor`; kopyası
    `maskeleme-basarisiz/` altında, `evidence-maskeli/` altında değil) karar bekleyendir (`bidr.mask.run.bekliyor`):
    eksik sayılmaz (hat `kanit_maskele` bitti; `bidr next` maskeleme döngüsüne girmez), pakete diğer karar
    bekleyenler gibi o anki maskeli hâliyle girer ve "karar bekliyor" diye listelenir; `--kararsizlari-disla` ile
    girmez."""
    import os
    import time

    import bidr.teslim.run as TR
    from bidr.mask.run import bekliyor
    from bidr.teslim.run import MASKE_KARAR, MASKE_UYARI, kanit_maskele_durum, maske_eksigi
    monkeypatch.setattr(TR, "pdf_araci", lambda tercih="otomatik": Sahte())
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    _acik(ws)
    rel = "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf"
    _maskele(ws, {"A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf": "tamam",
                  "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html": "tamam",
                  rel: "tamam",
                  "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html": "tamam"})
    # bidr maskele'nin yaptığı gibi: bekleyen dosyanın kopyası maskeleme-basarisiz/'e taşınır
    kp = ws / "maskeleme-basarisiz" / rel
    kp.parent.mkdir(parents=True, exist_ok=True)
    (ws / "evidence-maskeli" / rel).replace(kp)
    rep = json.loads((ws / "maskeleme-raporu.json").read_text(encoding="utf-8"))
    r = next(x for x in rep["dosyalar"] if x["dosya"] == rel)
    r.update(asiri_kapatma_bekliyor=True, kopya=f"maskeleme-basarisiz/{rel}")
    assert r["durum"] == "tamam" and not r.get("onay_bekleyen") and bekliyor(r)
    (ws / "maskeleme-raporu.json").write_text(json.dumps(rep), encoding="utf-8")
    t = time.time() + 20
    os.utime(ws / "maskeleme-raporu.json", (t, t))
    kctx = Ctx(Workspace(ws), None, lambda s: s.replace("{ws}", str(ws)), {"komut": ["bidr maskele -w {ws}"]})
    tctx = Ctx(Workspace(ws), None, lambda s: s.replace("{ws}", str(ws)), {"komut": ["bidr teslim -w {ws}"]})
    assert maske_eksigi(ws) is None
    c = kanit_maskele_durum(kctx)
    assert c.bitti and not c.uyarilar                      # next: kanit_maskele bitti, döngü yok
    res = build(ws, arac=Sahte(), zip_yap=False)
    k = ws / "teslim" / "kanitlar" / "A" / "A.1" / "A.1.2" / "[1-OD3]. Kurul kararı.pdf"
    assert k.read_bytes() == kp.read_bytes()
    assert [x["kanit"] for x in res.karar_bekleyen] == [rel]
    kb = res.karar_bekleyen[0]
    assert kb["pakette"] and kb["maskeleme"] == MASKE_KARAR and "aşırı kapatma" in kb["neden"]
    assert res.eksik == [] and res.kontrol_bekliyor == [] and res.maskeleme_uyarisi is None
    rows = {(r["Ölçüt"], r["Kanıt no"]): r["Maskeleme"] for r in _rows(ws / "teslim" / "kanit-dizini.csv")}
    assert rows[("A.1.2", "1-OD3")] == "karar bekliyor"
    uy = (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    assert "MASKELEME KARARI BEKLEYEN BELGELER: 1" in uy and "Kurul kararı" in uy and "aşırı kapatma" in uy
    c = durum(tctx)
    assert c.bitti and any("maskeleme kararı bekleyen belge: 1" in u for u in c.uyarilar)
    assert main(["teslim", "-w", str(ws), "--tarih", "2025-12-31"]) == 0
    assert main(["teslim", "-w", str(ws), "--tarih", "2025-12-31", "--taslak"]) == 0
    capsys.readouterr()
    res = build(ws, arac=Sahte(), zip_yap=False, kararsizlari_disla=True)
    assert not k.exists() and [x["kanit"] for x in res.kontrol_bekliyor] == [rel]
    # maskeleme kapalıyken karar bekleyen kuralı uygulanmaz: listelenmez, dışlanmaz (özgün dosya, uyarıyla)
    (ws / "config.yaml").write_text("privacy:\n  maskeleme: false\n", encoding="utf-8")
    res = build(ws, arac=Sahte(), zip_yap=False, kararsizlari_disla=True)
    assert k.read_bytes() == (ws / "evidence" / rel).read_bytes()
    assert res.karar_bekleyen == [] and "maskelenmeden" in res.maskeleme_uyarisi
    # seçim yazılmamış ama kanıt maskelemesi bugünkü kanıtlarda koşturulmuş: açık sayılır (geçmiş iz değil)
    from bidr.teslim.run import maskeleme_secimi
    (ws / "config.yaml").unlink()
    assert maskeleme_secimi(ws)[0] is True
    t = (ws / "maskeleme-raporu.json").stat().st_mtime + 10
    os.utime(ws / "evidence" / rel, (t, t))                # kanıt sonradan değişti: rapor geçmiş iz
    assert maskeleme_secimi(ws) == (None, "")


def test_maskeleme_kapisi_kaynak_isareti(tmp_path):
    """Kaynak klasör bölüm kaynak maskelemesinin kopyasıysa (işaret dosyası) maskeleme kullanılıyor sayılır."""
    from bidr.teslim.run import maskeleme_kullaniliyor
    ws = _ws(tmp_path)
    kaynak = tmp_path / "bolum-maskeli"
    kaynak.mkdir()
    (ws / "config.yaml").write_text(f"bidr:\n  kaynak: {kaynak}\n", encoding="utf-8")
    assert maskeleme_kullaniliyor(ws) is None
    (kaynak / ".bidr-maskeleme.json").write_text('{"durum": "tamam"}', encoding="utf-8")
    assert "kaynak maskelemesinin kopyası" in maskeleme_kullaniliyor(ws)


def test_oldugu_gibi_devam(tmp_path, capsys, monkeypatch):
    """"Olduğu gibi devam" (bölümün seçimi `<ws>/maskeleme-oldugu-gibi.json` ya da `--oldugu-gibi`): karar bekleyen
    kanıtlar o anki (kendiliğinden maskelenmiş) hâlleriyle girer, `--kararsizlari-disla` uygulanmaz, uyarı dosyasında
    "incelenmemiş öneri vardı, olduğu gibi eklendi" diye listelenir; seçim değişince paket eskir; geri alınabilir."""
    import bidr.teslim.run as TR
    from bidr.teslim.run import MASKE_UYARI, OLDUGU_GIBI
    monkeypatch.setattr(TR, "pdf_araci", lambda tercih="otomatik": Sahte())
    ws = _ws(tmp_path)
    _render(ws, tmp_path, "dekanlik")
    _acik(ws)
    _maskele(ws, {"A/A.1/A.1.1/[1-OD3]. Sentetik kanıt bir.pdf": "tamam",
                  "A/A.1/A.1.1/[2-OD2]. Sentetik web sayfası.html": "tamam",
                  "A/A.1/A.1.2/[1-OD3]. Kurul kararı.pdf": "basarisiz",
                  "A/A.1/A.1.2/[2-OD2]. Adressiz sayfa.html": "tamam"})
    ctx = Ctx(Workspace(ws), None, lambda s: s, {"komut": ["bidr teslim -w {ws}"]})
    k = ws / "teslim" / "kanitlar" / "A" / "A.1" / "A.1.2" / "[1-OD3]. Kurul kararı.pdf"
    res = build(ws, arac=Sahte(), zip_yap=False, kararsizlari_disla=True)
    assert not k.exists() and res.oldugu_gibi is None                 # seçilmemiş: eski davranış isteğe bağlı
    (ws / OLDUGU_GIBI).write_text(json.dumps({"kim": "uye@ornek.invalid", "zaman": "2026-11-25T10:00:00+03:00"}),
                                  encoding="utf-8")
    assert durum(ctx).kim == "komut" and "olduğu gibi" in durum(ctx).neden    # seçim değişti: paket eski
    res = build(ws, arac=Sahte(), zip_yap=False, kararsizlari_disla=True)
    assert k.read_bytes() == b"%PDF-1.4 KISMI" and res.kontrol_bekliyor == []
    assert res.oldugu_gibi["kim"] == "uye@ornek.invalid" and res.karar_bekleyen[0]["oldugu_gibi"]
    uy = (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    assert "OLDUĞU GİBİ EKLENDİ): 1" in uy and "1 dosyada incelenmemiş öneri vardı, olduğu gibi eklendi" in uy
    assert "Kurul kararı" in uy
    c = durum(ctx)
    assert c.bitti and any("olduğu gibi eklendi" in u for u in c.uyarilar)
    m = json.loads((ws / MANIFEST).read_text(encoding="utf-8"))
    assert m["oldugu_gibi"]["zaman"].startswith("2026-11-25") and "olduğu gibi" in m["karar_bekleyen_uyarisi"]
    # geri alındı: paket eskir, sonraki paket eski davranışla
    (ws / OLDUGU_GIBI).unlink()
    assert durum(ctx).kim == "komut"
    res = build(ws, arac=Sahte(), zip_yap=False)
    assert res.oldugu_gibi is None and "OLDUĞU GİBİ" not in (ws / "teslim" / MASKE_UYARI).read_text(encoding="utf-8")
    # CLI bayrağı
    assert main(["teslim", "-w", str(ws), "--oldugu-gibi", "--kararsizlari-disla"]) == 0
    assert "olduğu gibi eklendi" in capsys.readouterr().out
