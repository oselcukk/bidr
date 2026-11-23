"""Kaynak maskelemesinde o an işlenen belge (`maskeleme-ilerleme.json` → `suanki`): işçi durum dosyaları,
yazım sıklığı, ilerleme dosyasına aktarım ve eski alanların korunması (yalnız sentetik veri)."""
from __future__ import annotations

import json
import time

from bidr.mask import kaynak as K
from bidr.mask import suanki as S

from test_mask import PDF_OK, make_pdf
from test_mask_kaynak import RULES, _ob_temiz


def test_basla_sayfa_bitir_ve_seyrek_yazim(tmp_path, monkeypatch):
    d = tmp_path / "d"
    d.mkdir()
    monkeypatch.setenv(S.ENV, str(d))
    monkeypatch.setattr(S, "ARALIK", 60.0)
    S.basla("Kurul/karar.pdf")
    assert S.oku(d) == [{"dosya": "Kurul/karar.pdf"}]           # başlangıç hemen yazılır
    S.sayfa(1, 173)                                             # ilk sayfa (toplam sayfa) hemen yazılır
    assert S.oku(d)[0]["sayfa"] == 1
    S.sayfa(2, 173)
    S.sayfa(3, 173)
    assert S.oku(d)[0]["sayfa"] == 1                            # sonraki sayfalar ARALIK dolmadan diske gitmez
    monkeypatch.setattr(S, "ARALIK", 0.0)
    S.sayfa(112, 173)
    assert S.oku(d) == [{"dosya": "Kurul/karar.pdf", "sayfa": 112, "toplam_sayfa": 173, "asama": "maskeleme"}]
    S.sayfa(5, 173, "denetim")
    assert S.oku(d)[0]["asama"] == "denetim"
    assert not list(d.glob("*.tmp"))                            # atomik yazım: geçici dosya kalmaz
    S.bitir()
    assert S.oku(d) == [] and not list(d.iterdir())


def test_ortam_yoksa_hicbir_sey_yazmaz(tmp_path, monkeypatch):
    monkeypatch.delenv(S.ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    S.basla("a.pdf")
    S.sayfa(1, 2)
    S.bitir()
    assert not list(tmp_path.iterdir())


def test_oku_birden_cok_isci_ve_bozuk_dosya(tmp_path):
    (tmp_path / "11.json").write_text(json.dumps({"dosya": "b/ikinci.pdf", "sayfa": 3, "toplam_sayfa": 9}),
                                      encoding="utf-8")
    (tmp_path / "22.json").write_text(json.dumps({"dosya": "a/birinci.docx"}), encoding="utf-8")
    (tmp_path / "33.json").write_text("{yarim", encoding="utf-8")
    (tmp_path / "44.json").write_text(json.dumps({"sayfa": 1}), encoding="utf-8")
    assert S.oku(tmp_path) == [{"dosya": "a/birinci.docx"},
                               {"dosya": "b/ikinci.pdf", "sayfa": 3, "toplam_sayfa": 9}]
    assert S.oku(tmp_path / "yok") == []


def test_izleyici_degisince_yazar_son_alanlarla(tmp_path):
    yazilan = []
    with S.Izleyici(tmp_path, lambda **a: yazilan.append(a), aralik=0.02) as iz:
        iz.yaz(durum="suruyor", toplam=4, biten=1)
        (tmp_path / "1.json").write_text(json.dumps({"dosya": "x.pdf", "sayfa": 2, "toplam_sayfa": 5}),
                                         encoding="utf-8")
        for _ in range(100):
            if len(yazilan) >= 2:
                break
            time.sleep(0.02)
        time.sleep(0.1)                                          # değişmeyen durum yeniden yazılmaz
    assert yazilan[0] == {"suanki": [], "durum": "suruyor", "toplam": 4, "biten": 1}
    assert len(yazilan) == 2
    assert yazilan[1] == {"suanki": [{"dosya": "x.pdf", "sayfa": 2, "toplam_sayfa": 5}],
                          "durum": "suruyor", "toplam": 4, "biten": 1}


def test_kaynak_kosusu_suanki_belgeyi_yazar(tmp_path, monkeypatch):
    """Uzun süren belge bitmeden ilerleme dosyasında adı ve sayfası görünür; koşu bitince `suanki` boşalır ve
    eski alanlar (surum, mod, durum, toplam, biten, baslangic, zaman) yerinde kalır."""
    _ob_temiz()
    src = tmp_path / "bolum"
    make_pdf(src / "Kurul/karar.pdf", PDF_OK, annot=False, attach=False)
    (src / "not.txt").write_text("sentetik\n", encoding="utf-8")
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(S, "ARALIK", 0.02)
    gorulen = []
    asil = K._handle

    def yavas(src_, rel, *a, **kw):
        if rel == "Kurul/karar.pdf":
            S.sayfa(112, 173)
            time.sleep(0.3)
            gorulen.append(json.loads((ws / K.ILERLEME).read_text(encoding="utf-8")))
        return asil(src_, rel, *a, **kw)
    monkeypatch.setattr(K, "_handle", yavas)
    K.run_source(src, tmp_path / "maskeli", rules=RULES, engine="pypdf", ws=ws)
    assert gorulen and gorulen[0]["durum"] == "suruyor"
    assert gorulen[0]["suanki"] == [{"dosya": "Kurul/karar.pdf", "sayfa": 112, "toplam_sayfa": 173,
                                     "asama": "maskeleme"}]
    il = json.loads((ws / K.ILERLEME).read_text(encoding="utf-8"))
    assert il["durum"] == "bitti" and il["suanki"] == [] and il["toplam"] == il["biten"] == 2
    assert {"surum", "mod", "baslangic", "zaman"} <= set(il)
    assert not list(ws.glob("*.tmp"))
    import os
    assert os.environ.get(S.ENV) is None                         # ortam geri alındı
    _ob_temiz()


def test_paralel_kosu_bitince_suanki_bos(tmp_path):
    _ob_temiz()
    src = tmp_path / "bolum"
    for i in range(3):
        make_pdf(src / f"d{i}.pdf", PDF_OK, annot=False, attach=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    K.run_source(src, tmp_path / "maskeli", rules=RULES, engine="pypdf", ws=ws, workers=2)
    il = json.loads((ws / K.ILERLEME).read_text(encoding="utf-8"))
    assert il["durum"] == "bitti" and il["suanki"] == [] and il["biten"] == 3
    _ob_temiz()
