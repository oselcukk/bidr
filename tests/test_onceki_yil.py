"""Geçen yılın raporu (bidr/onceki): ayrıştırıcı, yazım/doğrulama bağlamı, parmak izi, tek seferlik karşılaştırma.

Hepsi sentetik: doldurulmuş FR-0833 bidr'in kendi render'ıyla sentetik şablondan üretilir; model çağrılmaz.
"""
from __future__ import annotations

import json
from pathlib import Path

import docx
import pytest

from bidr.cli import main
from bidr.common import Workspace
from bidr.onceki import baglam as OY
from bidr.onceki import karsilastirma as KS
from bidr.onceki import oku as O
from bidr.render.run import Options, render
from bidr.verify import run as V
from bidr.write import packages as K
from bidr.write import run as W

from test_render import make_template, write_audit, write_text
from test_write import GOOD, answer, make_report_ws

IDS = (("A.1.1", "Yönetişim modeli"), ("A.1.2", "Liderlik"), ("B.1.1", "Programların tasarımı ve onayı"))


def dolu_rapor(tmp_path: Path, *, opts: Options | None = None, ods=None) -> Path:
    """Sentetik doldurulmuş FR-0833: sentetik şablon + metinler, bidr render ile."""
    ws = tmp_path / "gecen"
    ws.mkdir()
    make_template(tmp_path / "sablon.docx", ids=IDS)
    write_text(ws / "texts", "A.1.1")
    write_text(ws / "texts", "A.1.2", paragraflar=[{"metin": "Bölümümüzde komisyonlar toplanmaktadır [1_OD4].",
                                                    "atiflar": ["1_OD4"]}],
               kanitlar=[{"no": "1_OD4", "ad": "Komisyon Tutanakları", "dosya": "x.pdf"}], od_onerisi=4)
    write_audit(ws, ods or {"A.1.1": 3, "A.1.2": 4})
    out = tmp_path / "gecen-yil.docx"
    render(tmp_path / "sablon.docx", out, texts_dir=ws / "texts", audit_path=ws / "audit-olcutler.json",
           opts=opts or Options())
    return out


def test_ayristirici_kalin_isaret_ve_kilavuz_kodlari(tmp_path):
    v = O.oku(dolu_rapor(tmp_path))
    o = v["olcutler"]
    assert set(o) == {"A.1.1", "A.1.2", "B.1.1"}
    a = o["A.1.1"]
    assert a["od"] == 3 and a["od_kaynak"] == "isaret" and a["od_isaretli"] == [3]
    assert "A.1.1 sentetik paragraf bir" in a["aciklama"] and "paragraf iki" in a["aciklama"]
    assert [(k["no"], k["od"], k["ad"]) for k in a["kanitlar"]] == [(1, 3, "Sentetik kanıt bir.pdf"),
                                                                   (2, 2, "Sentetik kanıt iki.pdf")]
    assert o["A.1.2"]["od"] == 4 and o["A.1.2"]["kanitlar"][0]["ad"] == "Komisyon Tutanakları.pdf"
    assert o["B.1.1"]["aciklama"] == "" and o["B.1.1"]["kanitlar"] == []      # metni olmayan ölçüt boş
    assert v["ozet"] == {"olcut": 3, "aciklamali": 2, "od_bulunan": 2, "od_isaret": 2, "od_kanit_kodlari": 0}
    assert v["kaynak"]["bicim"] == "docx" and len(v["kaynak"]["sha256"]) == 64


def test_ayristirici_isaretsiz_rubrikte_kanit_kodlari(tmp_path):
    v = O.oku(dolu_rapor(tmp_path, opts=Options(puan_isareti="yok", kanit_bicimi="mat")))
    a = v["olcutler"]["A.1.1"]
    assert a["od"] == 3 and a["od_kaynak"] == "kanit_kodlari" and a["od_isaretli"] == []
    assert [k["ad"] for k in a["kanitlar"]] == ["Sentetik kanıt bir", "Sentetik kanıt iki"]


def test_ayristirici_golge_isaret(tmp_path):
    v = O.oku(dolu_rapor(tmp_path, opts=Options(puan_isareti="golge")))
    assert v["olcutler"]["A.1.2"]["od"] == 4 and v["olcutler"]["A.1.2"]["od_kaynak"] == "isaret"


def test_ayristirici_etiketsiz_aciklama_ve_bos_ifade(tmp_path):
    p = make_template(tmp_path / "s.docx", ids=IDS[:2])
    d = docx.Document(str(p))
    from bidr.criteria.extract_docx import W as WN
    from bidr.render.template import find_blocks
    blocks, _ = find_blocks(d)
    b1 = blocks["A.1.1"]
    for par in list(b1.aciklama_tc.iter(WN + "p")):          # bölüm etiketi silip metni yazmış
        for t in par.iter(WN + "t"):
            t.text = ""
    b1.aciklama_tc.findall(".//" + WN + "t")[0].text = "Etiketsiz sentetik açıklama metni."
    kt = b1.kanit_tc.findall(".//" + WN + "t")
    kt[0].text, kt[1].text = "Kanıtlar:", "1_OD2: Sentetik belge"
    b2 = blocks["A.1.2"]
    b2.aciklama_tc.findall(".//" + WN + "t")[1].text = "Bu kısım için veri bulunmamaktadır."
    d.save(str(tmp_path / "f.docx"))
    v = O.oku(tmp_path / "f.docx")
    assert v["olcutler"]["A.1.1"]["aciklama"] == "Etiketsiz sentetik açıklama metni."
    assert v["olcutler"]["A.1.1"]["od"] == 2
    assert v["olcutler"]["A.1.2"]["aciklama"] == ""
    assert any("etiketi silinmiş" in u for u in v["uyarilar"])


def test_ayristirici_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    satirlar = ["ÖLÇÜTLER VE KANITLAR", "A.1.2. Liderlik", "1 2 3 4 5", "Örnek Kanıtlar:", "● örnek",
                "Açıklamalar:", "", "Bölümümüzde sentetik liderlik", "uygulaması vardır [1_OD4].", "",
                "Sayfa 3 / 9", "Form No:FR-0833 Yayın Tarihi:01.01.2000", "Kanıtlar:", "1_OD4: Sentetik komisyon listesi",
                "2_OD5: A.1.2 Sentetik tutanak.pdf", "DOLDURACAK BİRİMLER: TÜM AKADEMİK BİRİMLER",
                "A.1.3. Kurumsal dönüşüm kapasitesi", "Açıklamalar:", "Bu kısım için veri bulunmamaktadır.",
                "Kanıtlar:", "Bu kısım için veri bulunmamaktadır."]
    font = next((f for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                             "C:/Windows/Fonts/arial.ttf") if Path(f).exists()), None)
    if font is None:
        pytest.skip("Türkçe karakterli TTF yazı tipi yok")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_font(fontname="F0", fontfile=font)
    y = 40
    for s in satirlar:
        page.insert_text((40, y), s, fontname="F0", fontsize=9)
        y += 14
    doc.save(str(tmp_path / "r.pdf"))
    v = O.oku(tmp_path / "r.pdf")
    if "A.1.2" not in v["olcutler"]:
        pytest.skip("fitz yazı tipi Türkçe karakteri metin katmanına yazmadı")
    r = v["olcutler"]["A.1.2"]
    assert r["od"] == 5 and r["od_kaynak"] == "kanit_kodlari"
    assert "sentetik liderlik uygulaması vardır" in r["aciklama"] and "Sayfa" not in r["aciklama"]
    assert [k["no"] for k in r["kanitlar"]] == [1, 2]


def test_desteklenmeyen_bicim(tmp_path):
    (tmp_path / "r.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        O.oku(tmp_path / "r.txt")


def test_cek_komutu(tmp_path, capsys):
    rapor = dolu_rapor(tmp_path)
    ws = tmp_path / "ws"
    ws.mkdir()
    assert main(["onceki-yil", "cek", "-w", str(ws), "--rapor", str(rapor)]) == 0
    v = OY.yukle(ws)
    assert v and v["olcutler"]["A.1.1"]["od"] == 3
    assert main(["onceki-yil", "goster", "-w", str(ws), "--olcut", "A.1.1"]) == 0
    assert "geçen yıl OD: 3" in capsys.readouterr().out
    assert main(["onceki-yil", "kaldir", "-w", str(ws)]) == 0 and OY.yukle(ws) is None


# -- yazım bağlamı ve parmak izi ------------------------------------------------------------------

def onceki_yaz(ws: Path, olcutler: dict) -> None:
    O.yaz({"surum": O.SURUM, "kaynak": {"ad": "gecen.docx", "bicim": "docx", "sha256": "ab" * 32},
           "ozet": {}, "uyarilar": [], "olcutler": olcutler}, ws / O.DOSYA)


KAYIT = {"olcut": "B.1.1", "od": 2, "od_kaynak": "isaret", "od_isaretli": [2],
         "aciklama": "Geçen yıl ders planı değişikliği süreci tanımlıydı; danışma kurulu toplantısı yapılmamıştı.",
         "kanitlar": [{"no": 1, "od": 2, "ad": "Eski iş akışı", "kod_olcut": "B.1.1"}]}


def _pkg(ws: Path, stage: str = "write") -> dict:
    return json.loads((ws / "work" / stage / "B.1.1.json").read_text(encoding="utf-8"))


def test_raporsuz_bolumde_paket_ve_izler_aynı(tmp_path):
    a = make_report_ws(tmp_path / "a")
    W.prepare(a)
    p1 = _pkg(a)
    assert "GEÇEN YILIN RAPORU" not in p1["istem"] and "onceki_yil" not in p1["meta"]
    assert p1["istem_sha"] == p1["meta"]["temel_istem_sha"]          # ek bölüm yok: tam istem = temel istem
    # başka bir ölçütün geçen yıl kaydı B.1.1'in paketini değiştirmez (yalnız ilgili ölçüt)
    b = make_report_ws(tmp_path / "b")
    onceki_yaz(b, {"A.1.1": {**KAYIT, "olcut": "A.1.1"}})
    W.prepare(b)
    p2 = _pkg(b)
    assert (p2["istem"], p2["istem_sha"], p2["meta"]) == (p1["istem"], p1["istem_sha"], p1["meta"])
    answer(a, "B.1.1", GOOD)
    W.apply(a, model="t")
    t = W.load_text(Workspace(a), "B.1.1")
    assert "onceki_yil" not in t["kaynak"]


def test_rapor_gelince_var_olan_metin_kendiliginden_yeniden_yazilmaz(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws, model="t")
    onceki_yaz(ws, {"B.1.1": KAYIT})
    st = W.prepare(ws)
    assert st["zaten_tamam"] == 1 and st["yeni"] == 0                 # metin güncel sayılır
    # bir sonraki yazımda (burada --only) bağlam pakete girer; temel istem özeti değişmez
    W.prepare(ws, only=["B.1.1"])
    p = _pkg(ws)
    assert "GEÇEN YILIN RAPORU (geçen yıl)" in p["istem"] and "danışma kurulu toplantısı yapılmamıştı" in p["istem"]
    assert "geçen yıl OD: 2 (rubrikte işaretli)" in p["istem"] and "Eski iş akışı" in p["istem"]
    assert p["meta"]["onceki_yil"] == {"kaynak_sha": "ab" * 8, "od": 2}
    t = W.load_text(Workspace(ws), "B.1.1")
    assert p["meta"]["temel_istem_sha"] == t["kaynak"]["temel_istem_sha"]
    answer(ws, "B.1.1", GOOD)
    W.apply(ws, model="t")
    assert W.load_text(Workspace(ws), "B.1.1")["kaynak"]["onceki_yil"]["od"] == 2


def test_yeniden_yazim_paketi_de_baglam_alir(tmp_path):
    ws = make_report_ws(tmp_path)
    onceki_yaz(ws, {"B.1.1": KAYIT})
    W.prepare(ws)
    assert "GEÇEN YILIN RAPORU" in _pkg(ws)["istem"]


def test_dogrulama_paketi_gecen_yil_metnini_alir(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws, model="t")
    V.prepare(ws)
    assert "KARŞILAŞTIRMA DENETİMİ" not in _pkg(ws, "verify")["istem"]
    onceki_yaz(ws, {"B.1.1": KAYIT})
    V.prepare(ws, redo=True)
    ist = _pkg(ws, "verify")["istem"]
    assert "KARŞILAŞTIRMA DENETİMİ" in ist and "danışma kurulu toplantısı yapılmamıştı" in ist


def test_ozette_gecen_yilin_atiflari_yok():
    r = {**KAYIT, "aciklama": "Süreç tanımlıdır [1_OD2]. Komisyon vardır [A.1.2-1-OD3]. Toplantı yapılır [2-OD4]."}
    s = OY.ozet(r, 1000)
    assert "Süreç tanımlıdır. Komisyon vardır. Toplantı yapılır." in s and "OD2]" not in s


def test_kisaltma_cumle_sinirinda():
    s = OY.kisalt("Bir. " * 400, 100)
    assert s.endswith("[…]") and len(s) < 110


# -- tek seferlik karşılaştırma geçişi ------------------------------------------------------------

def dogrulanmis(tmp_path: Path) -> Path:
    ws = make_report_ws(tmp_path, with_c=True, od=4)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    W.apply(ws, model="t")
    t = W.load_text(Workspace(ws), "B.1.1")
    t["durum"] = "dogrulandi"
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    log = {"B.1.1": {"olcut": "B.1.1", "durum": "dogrulandi", "metin_sha": W.text_sha(t), "asama": "model"}}
    V.save_log(Workspace(ws), log)
    return ws


EKLE = {"islem": "ekle", "yer": "p1.1", "gerekce": "danışma kurulu bu yıl yapıldı",
        "cumleler": ["Geçen yıl danışma kurulu toplantısı yapılmamışken bu yıl öğrenci anket sonuçları danışma "
                     "kurulunda görüşülmüştür [3_OD4]."]}


def test_karsilastirma_yalniz_aciklikla_calisir_ve_raporsuzda_hata(tmp_path):
    ws = dogrulanmis(tmp_path)
    with pytest.raises(FileNotFoundError):
        KS.prepare(ws)
    assert not (ws / "work/karsilastirma").exists()


def test_karsilastirma_ekle_dogrulama_ve_tek_sefer(tmp_path):
    ws = dogrulanmis(tmp_path)
    onceki_yaz(ws, {"B.1.1": KAYIT})
    eski = W.load_text(Workspace(ws), "B.1.1")
    st = KS.prepare(ws)
    assert st["paket"] == ["B.1.1"]
    ist = _pkg(ws, "karsilastirma")["istem"]
    assert "p1.1: Bölümümüzde ders planı" in ist and "danışma kurulu toplantısı yapılmamıştı" in ist and "[3_OD4]" in ist
    answer(ws, "B.1.1", EKLE, "karsilastirma")
    st = KS.apply(ws, model="t")
    assert st["eklendi"] == ["B.1.1"]
    t = W.load_text(Workspace(ws), "B.1.1")
    assert t["durum"] == "taslak" and t["karsilastirma"]["durum"] == "dogrulamada"
    assert t["paragraflar"][1] == eski["paragraflar"][1]                     # öteki paragraf aynen
    assert t["paragraflar"][0]["metin"].startswith(eski["paragraflar"][0]["metin"])
    assert "3_OD4" in [k["no"] for k in t["kanitlar"]] and t["od_onerisi"] == eski["od_onerisi"]
    # yalnız değişen ölçüt doğrulamaya gider; ikinci prepare paket üretmez (işaret)
    assert KS.prepare(ws)["paket"] == []
    V.prepare(ws, only=["B.1.1"])
    vp = _pkg(ws, "verify")
    assert "KARŞILAŞTIRMA DENETİMİ" in vp["istem"]
    # doğrulama ekli metni reddederse: ekleme düşer, eski metin ve eski doğrulama kaydı geri gelir
    rows = [{"yer": c["yer"], "karar": "desteklenmiyor" if "Geçen yıl" in c["metin"] else "destekleniyor",
             "gerekce": "g"} for c in vp["meta"]["cumleler"]]
    sorular = [{"soru": q, "durum": "cevapsiz", "yerler": [], "gerekce": "g"}
               for q in ("surec", "izleme", "iyilestirme", "kanitlar", "onceki_yil")]
    answer(ws, "B.1.1", {"cumleler": rows, "sorular": sorular, "genel": "g"}, "verify")
    vs = V.apply(ws, model="t")
    assert vs["karsilastirma"]["reddedildi"] == ["B.1.1"]
    t = W.load_text(Workspace(ws), "B.1.1")
    assert t["paragraflar"] == eski["paragraflar"] and t["durum"] == "dogrulandi"
    assert t["karsilastirma"]["durum"] == "reddedildi" and "geri" not in t["karsilastirma"]
    assert V.load_log(Workspace(ws))["B.1.1"]["metin_sha"] == W.text_sha(eski)
    assert V.prepare(ws)["zaten_tamam"] >= 1                                 # eski metin yeniden doğrulanmaz
    assert KS.prepare(ws)["atlanan"]["zaten_islendi"] == ["B.1.1"]


def test_karsilastirma_dogrulanirsa_kalir(tmp_path):
    ws = dogrulanmis(tmp_path)
    onceki_yaz(ws, {"B.1.1": KAYIT})
    KS.prepare(ws)
    answer(ws, "B.1.1", EKLE, "karsilastirma")
    KS.apply(ws, model="t")
    t = W.load_text(Workspace(ws), "B.1.1")
    t["durum"] = "dogrulandi"                                               # verify geçti (benzetim)
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    assert KS.sonuc(ws)["eklendi"] == ["B.1.1"]
    t = W.load_text(Workspace(ws), "B.1.1")
    assert "Geçen yıl danışma kurulu" in t["paragraflar"][0]["metin"] and t["karsilastirma"]["durum"] == "eklendi"


def test_karsilastirma_yok_ve_kod_reddi(tmp_path):
    ws = dogrulanmis(tmp_path)
    onceki_yaz(ws, {"B.1.1": KAYIT})
    eski = W.load_text(Workspace(ws), "B.1.1")
    KS.prepare(ws)
    kotu = {**EKLE, "cumleler": ["Geçen yıl OD2 iken bu yıl olgunluk düzeyi yükselmiştir [9_OD4]."]}
    answer(ws, "B.1.1", kotu, "karsilastirma")
    st = KS.apply(ws, model="t")
    assert "B.1.1" in st["kod_reddi"]
    t = W.load_text(Workspace(ws), "B.1.1")
    assert t["paragraflar"] == eski["paragraflar"] and t["durum"] == "dogrulandi"
    assert W.text_sha(t) == W.text_sha(eski) and t["karsilastirma"]["durum"] == "kod_reddi"

    ws2 = dogrulanmis(tmp_path / "iki")
    onceki_yaz(ws2, {"B.1.1": KAYIT})
    KS.prepare(ws2)
    answer(ws2, "B.1.1", {"islem": "yok", "yer": "", "cumleler": [], "gerekce": "fark kanıtlı değil"}, "karsilastirma")
    assert KS.apply(ws2, model="t")["degisiklik_yok"] == ["B.1.1"]
    t = W.load_text(Workspace(ws2), "B.1.1")
    assert t["durum"] == "dogrulandi" and t["karsilastirma"]["durum"] == "degisiklik_yok"
    assert V.prepare(ws2)["paket"] == 0                                    # metin özeti aynı: yeniden doğrulanmaz
    assert KS.prepare(ws2)["paket"] == []


def test_karsilastirma_degistir_atfi_korur(tmp_path):
    ws = dogrulanmis(tmp_path)
    onceki_yaz(ws, {"B.1.1": KAYIT})
    KS.prepare(ws)
    dg = {"islem": "degistir", "yer": "p1.1", "gerekce": "g",
          "cumleler": ["Geçen yılda olduğu gibi bu yıl da ders planı değişiklikleri Bölüm Kurulunda görüşülür [3_OD4]."]}
    answer(ws, "B.1.1", dg, "karsilastirma")
    st = KS.apply(ws, model="t")
    assert any("atfı düştü" in s for s in st["kod_reddi"]["B.1.1"])
