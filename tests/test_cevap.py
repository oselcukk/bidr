"""Model cevabının reddi bütün ajan aşamalarında ortak kural (bidr/pipeline/cevap.py): geçersiz/şüpheli cevap
kenara alınır → paket yeniden cevapsız (ajan üstüne yazmaz) → aynı nedenle ikinci ret elle bakılmalı → aşama
beklemez, döngü yok. Şema enum'unda bilinmeyen değer `diger`e normalleşir. Sentetik; model yok."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidr.common import Workspace, read_jsonl
from bidr.pipeline import cevap as CV
from bidr.pipeline import checks as C
from bidr.pipeline.state import formatter, load_spec, stage


def _ctx(ws: Path, sid: str, sec: dict | None = None) -> C.Ctx:
    w = Workspace(ws)
    return C.Ctx(w, sec or {}, formatter(w, sec or {}), stage(sid))


def _panel_onceki(ws: Path) -> dict:
    """Panelin cevap koruması (`cevaplari_koru`) çağrıdan önce var olan cevapların görüntüsünü alır."""
    return {p: p.read_bytes() for p in ws.rglob("*.out.json")}


# -- ortak yardımcı ----------------------------------------------------------------------------------

def test_denemeler_kenara_al_yeniden_sor_elle(tmp_path):
    d = tmp_path / "work" / "x"
    d.mkdir(parents=True)
    out = d / "k.out.json"
    den = CV.Denemeler(tmp_path, "work/x")
    out.write_text("{bozuk", encoding="utf-8")
    r = den.reddet("k", out, "sema", ["e1"], parmak="p1", model="m")
    assert r["sonuc"] == "yeniden" and r["dosya"] == "k.out.json.red1.eski"
    assert not out.exists() and (d / "k.out.json.red1.eski").exists()
    assert den.kenarda("k")["neden"] == "sema" and not den.elle("k")
    den.kaydet()
    assert (tmp_path / CV.DOSYA).exists() and not (d / CV.DOSYA).exists()      # ws kökünde, paket klasöründe değil
    # yeni cevap aynı nedenle reddedilir: elle bakılmalı, cevap yerinde kalır (aynı cevap yeniden denenmez)
    den = CV.Denemeler(tmp_path, "work/x")
    out.write_text("{yine bozuk", encoding="utf-8")
    r = den.reddet("k", out, "sema", ["e2"], parmak="p1")
    assert r["sonuc"] == CV.ELLE and r["deneme"] == 2 and out.exists()
    assert den.elle_ayni("k", CV.sha(out.read_bytes()), "p1") and not den.elle("k", "p2")
    den.kaydet()
    CV.elle_raporu(d, den, "x", "anlam")
    assert "`k`" in (d / CV.ELLE_MD).read_text(encoding="utf-8")
    assert CV.elle_kayitlari(tmp_path, "work/x")["k"]["deneme"] == 2


def test_denemeler_farkli_nedenler_ucuncu_retle_elle_ve_parmak_sifirlar(tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    out = d / "k.out.json"
    den = CV.Denemeler(tmp_path, "w")
    for i, kod in enumerate(("sema", "denetim", "supheli"), 1):
        out.write_text(f"cevap {i}", encoding="utf-8")
        r = den.reddet("k", out, kod, [kod], parmak="p")
        assert r["sonuc"] == ("yeniden" if i < 3 else CV.ELLE)
    # girdisi değişen öğe (yeniden prepare): sayaç ve elle işareti baştan
    r = den.reddet("k", out, "sema", ["x"], parmak="yeni")
    assert r["sonuc"] == "yeniden" and r["deneme"] == 1 and not den.elle("k")
    assert den.basarili("k") == 1 and den.son("k") is None
    den.kaydet()
    assert not (tmp_path / CV.DOSYA).exists()                                   # boş kayıt dosya bırakmaz


def test_transcribe_eski_kaydi_tasinir(tmp_path):
    d = tmp_path / "work" / "transcribe"
    d.mkdir(parents=True)
    (d / "denemeler.json").write_text(json.dumps({"a": {"gorsel_sha": "g", "denemeler": [
        {"cevap_sha": "s", "neden": "supheli", "hatalar": [], "dosya": "a.out.json.red1.eski"}]}}), encoding="utf-8")
    den = CV.Denemeler(tmp_path, "work/transcribe")
    assert den.kenarda("a")["dosya"] == "a.out.json.red1.eski" and den.kayit["a"]["parmak"] == "g"
    den.kaydet()
    assert not (d / "denemeler.json").exists() and "a" in json.loads((tmp_path / CV.DOSYA).read_text())["work/transcribe"]


# -- enum normalleştirme --------------------------------------------------------------------------------

def _gorsel(**kw):
    it = {"gorsel": 1, "icerik": "fotograf", "sahne": "s", "etkinlik": "", "kalabalik": "yok", "nesneler": [],
          "gorunen_yazilar": [{"yer": "tabela", "metin": "X"}], "betimleme": "b"}
    it.update(kw)
    return {"gorseller": [it]}


def test_enum_diger_varsa_normallesir_yoksa_gecersiz():
    from bidr.llm import validate_output
    notlar: list = []
    out, errs = validate_output("describe", json.dumps(_gorsel(gorunen_yazilar=[{"yer": "pano", "metin": "X"}],
                                                               icerik="kolaj")), notlar=notlar)
    assert not errs and out["gorseller"][0]["gorunen_yazilar"][0]["yer"] == "diger"
    assert out["gorseller"][0]["icerik"] == "diger"
    assert {(n["yol"], n["deger"]) for n in notlar} == {("gorseller/0/gorunen_yazilar/0/yer", "pano"),
                                                        ("gorseller/0/icerik", "kolaj")}
    out, errs = validate_output("describe", json.dumps(_gorsel(kalabalik="cok")))   # `diger`siz enum
    assert out is None and any("kalabalik" in e for e in errs)
    out, errs = validate_output("describe", json.dumps(_gorsel(notlar="bulanık")))  # görsel başına not şemada
    assert not errs


# -- describe ---------------------------------------------------------------------------------------------

def test_describe_enum_dis_deger_uygulanir_ozgun_kayitta(tmp_path):
    from test_describe import GARBAGE, _item, _out, _ws
    from bidr.describe import run as R
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    R.prepare(ws, only=[did], source=src)
    istem = json.loads((ws / "work/describe" / did / f"{did}.json").read_text(encoding="utf-8"))["istem"]
    assert "`yer` YALNIZ" in istem and "Listede yoksa" in istem and "`diger`" in istem     # talimatta enum listesi
    _out(ws, did, [_item(gorunen_yazilar=[{"yer": "pano", "metin": "BİLGİSAYAR LABORATUVARI"}])])
    st = R.apply(ws)
    assert st["islenen"] == 1 and not st["gecersiz"]
    rec = R.load_log(Workspace(ws))[did]
    assert rec["enum_normallestirme"] == [{"yol": "gorseller/0/gorunen_yazilar/0/yer", "deger": "pano"}]
    assert "Görünen yazı (diger: pano)" in (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")


def test_describe_supheli_bir_kez_yeniden_sorulur_sonra_elle_ocr_kalir(tmp_path, capsys):
    from test_describe import POSTER_OCR, _check, _item, _out, _ws
    from bidr.cli import main
    from bidr.describe import run as R
    ws, src, ids = _ws(tmp_path, {"afis": (".png", POSTER_OCR, 1)})
    did = ids["afis"]
    R.prepare(ws, only=[did], source=src)
    pd = ws / "work/describe" / did
    uydurma = [_item(icerik="afis", gorunen_yazilar=[{"yer": "afis", "metin": "BAHAR ŞENLİĞİ"}])]
    _out(ws, did, uydurma)
    assert main(["describe", "apply", "-w", str(ws)]) == 1                     # kenara alındı, yeniden istenecek
    assert not (pd / f"{did}.out.json").exists() and (pd / f"{did}.out.json.red1.eski").exists()
    g = (ws / "work/describe/GECERSIZ.md").read_text(encoding="utf-8")
    assert "şüpheli" in g and "kenara alındı" in g
    c = _check(ws, src)
    assert c.kim == "ajan" and c.bekleyen == [did] and "reddedildi" in c.neden
    onceki = _panel_onceki(ws)
    _out(ws, did, [_item(icerik="afis", gorunen_yazilar=[{"yer": "afis", "metin": "YAZ ŞENLİĞİ"}])])
    assert (pd / f"{did}.out.json") not in onceki                              # panel koruması yeni cevabı ezmez
    assert main(["describe", "apply", "-w", str(ws)]) == 0                     # ikinci şüpheli: elle bakılmalı
    assert "elle bakılmalı" in capsys.readouterr().out
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == POSTER_OCR   # uydurma yazı rapora girmez
    rec = R.load_log(Workspace(ws))[did]
    assert rec["durum"] == R.ELLE and rec["neden"] == "supheli" and rec["deneme"] == 2
    assert did in (ws / "work/describe" / CV.ELLE_MD).read_text(encoding="utf-8")
    c = _check(ws, src)
    assert c.bitti and c.ilerleme["elle_bakilmali"] == 1 and any("elle bakılmalı" in u for u in c.uyarilar)
    # döngü yok: yeniden apply aynı cevabı denemez, prepare --auto yeniden paketlemez
    st = R.apply(ws)
    assert did in st["elle_bakilmali"] and not st["supheli"] and st["islenen"] == 0
    assert R.prepare(ws, auto=True, source=src)["zaten_tamam"] == 1 and _check(ws, src).bitti
    # bölüm görüntüye bakıp kabul ederse: --kabul-supheli son cevabı uygular
    assert R.apply(ws, accept_suspicious=True, only=[did])["islenen"] == 1


def test_describe_sema_ikinci_ret_elle_ve_paket_guncel_talimatla_yenilenir(tmp_path):
    from test_describe import GARBAGE, _check, _item, _out, _ws
    from bidr.describe import run as R
    ws, src, ids = _ws(tmp_path, {"foto": (".png", GARBAGE, 1)})
    did = ids["foto"]
    R.prepare(ws, auto=True, source=src)
    pkgp = ws / "work/describe" / did / f"{did}.json"
    pkg = json.loads(pkgp.read_text(encoding="utf-8"))
    # paket eski talimatla hazırlanmış olsun (enum listesi yok)
    img = R._gorsel_sha(pkgp.parent, pkg["gorseller"])
    eski = pkg["istem"].replace("`yer` YALNIZ", "`yer`")
    pkgp.write_text(json.dumps({**pkg, "istem": eski, "istem_sha": R._sha(eski + img)[:16]}, ensure_ascii=False),
                    encoding="utf-8")
    _out(ws, did, [_item(kalabalik="cok")])
    # yalnız talimat metni değişen paketin verilmiş cevabı prepare'de korunur
    assert R.prepare(ws, auto=True, source=src)["cevap_korundu"] == 1
    assert (pkgp.parent / f"{did}.out.json").exists()
    st = R.apply(ws)
    assert did in st["gecersiz"] and st["yeniden"][did]["deneme"] == 1
    assert "`yer` YALNIZ" in json.loads(pkgp.read_text(encoding="utf-8"))["istem"]    # reddedilince yenilendi
    _out(ws, did, [_item(kalabalik="cok fazla")])
    st = R.apply(ws)
    assert did in st["elle_bakilmali"] and not st["gecersiz"]
    assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == GARBAGE
    assert _check(ws, src).bitti


# -- karar (kaba / ince) ----------------------------------------------------------------------------------

def test_karar_kaba_iki_ret_elle_insan_incelemesine_duser(tmp_path):
    from test_decide import DOCS, FakeLLM, _agent
    from bidr.audit.run import karar_verilemeyen
    from bidr.decide.run import apply, prepare
    from synth import make_ws
    docs = [{"text": DOCS[k], "gold": ["B.1.1"], "path": f"x/{k}.pdf"} for k in ("aynı", "ekle", "degil")]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(("aynı", "ekle", "degil"), docs)}
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "doc_type": "kurul_karari", "calisma_adi": f"ad-{x}"}) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.1.1"}]}) + "\n")
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    wd = root / "work" / "coarse"
    bad = ids["degil"]
    _agent(root, fake, "coarse", broken={bad})
    st = apply(root, "coarse", model="m", backend=b)
    assert list(st["gecersiz"]) == [bad] and st["yeniden"][bad]["dosya"] == f"{bad}.out.json.red1.eski"
    ck = C.karar_tamam(_ctx(root, "karar_kaba"))
    assert ck.kim == C.AJAN and ck.bekleyen == [bad]
    (wd / f"{bad}.out.json").write_text("yine {bozuk", encoding="utf-8")
    st = apply(root, "coarse", model="m", backend=b)
    assert bad in st["elle_bakilmali"] and not st["gecersiz"] and not (wd / "GECERSIZ.md").exists()
    ck = C.karar_tamam(_ctx(root, "karar_kaba"))
    assert ck.bitti and ck.ilerleme["elle_bakilmali"] == 1 and any("insan incelemesine" in u for u in ck.uyarilar)
    assert bad in (wd / CV.ELLE_MD).read_text(encoding="utf-8")
    # döngü yok: aynı cevap yeniden denenmez; prepare paketi değiştirmez
    assert bad in apply(root, "coarse", model="m", backend=b)["elle_bakilmali"]
    prepare(root, "coarse", backend=b)
    assert C.karar_tamam(_ctx(root, "karar_kaba")).bitti
    # ince karar o belge olmadan ilerler; inceleme tablosunda "model kararı verilemeyen" olarak görünür
    assert prepare(root, "fine", backend=b)["paket"] == 2
    recs = list(read_jsonl(root / "decisions.jsonl"))
    ky = karar_verilemeyen(Workspace(root), recs, {}, {})
    assert [x["doc_id"] for x in ky] == [bad] and ky[0]["asama"] == "kaba karar"


def test_karar_ince_iki_ret_elle(tmp_path):
    from test_decide import DOCS, FakeLLM, _agent
    from bidr.decide.run import apply, prepare
    from synth import make_ws
    docs = [{"text": DOCS[k], "gold": ["B.1.1"], "path": f"x/{k}.pdf"} for k in ("aynı", "ekle")]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(("aynı", "ekle"), docs)}
    with open(root / "documents.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "doc_type": "kurul_karari"}) + "\n")
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.1.1"}]}) + "\n")
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _agent(root, fake, "coarse")
    apply(root, "coarse", model="m", backend=b)
    prepare(root, "fine", backend=b)
    bad = ids["ekle"]
    _agent(root, fake, "fine", broken={bad})
    st = apply(root, "fine", model="m", backend=b)
    assert bad in st["gecersiz"] and not (root / "work/fine" / f"{bad}.out.json").exists()
    (root / "work/fine" / f"{bad}.out.json").write_text("{x", encoding="utf-8")
    st = apply(root, "fine", model="m", backend=b)
    assert bad in st["elle_bakilmali"]
    ck = C.karar_tamam(_ctx(root, "karar_ince"))
    assert ck.bitti and ck.ilerleme["elle_bakilmali"] == 1


# -- ad -----------------------------------------------------------------------------------------------------

def test_name_iki_ret_elle_kural_adinda_kalir(env):  # noqa: F811
    from bidr.name import run as NR
    ws, _ = env
    NR.prepare(ws)
    d = ws / "work" / "name"
    for did in ("d_anket", "d_karar"):
        (d / f"{did}.out.json").write_text(json.dumps({"kanit_adi": "Bölüm Kurulu Kararları Özeti", "gerekce": "x"}),
                                           encoding="utf-8")
    (d / "d_kom.out.json").write_text(json.dumps({"kanit_adi": "Prof. Dr. Deneme Kişi Görevlendirmesi",
                                                 "gerekce": "x"}), encoding="utf-8")
    st = NR.apply(ws, model="t")
    assert "d_kom" in st["reddedilen"] and (d / "d_kom.out.json.red1.eski").exists()
    ck = C.name_tamam(_ctx(ws, "name"))
    assert ck.kim == C.AJAN and ck.bekleyen == ["d_kom"]
    (d / "d_kom.out.json").write_text(json.dumps({"kanit_adi": "Doç. Dr. Ayşe Kaya Görevlendirmesi",
                                                 "gerekce": "x"}), encoding="utf-8")
    st = NR.apply(ws, model="t")
    assert "d_kom" in st["elle_bakilmali"] and not st["reddedilen"]
    ck = C.name_tamam(_ctx(ws, "name"))
    assert ck.bitti and any("kural" in u for u in ck.uyarilar)
    assert "d_kom" in NR.apply(ws, model="t")["elle_bakilmali"]                # aynı cevap yeniden denenmez


from test_file import env  # noqa: E402,F401  (fixture)


# -- ikinci arama --------------------------------------------------------------------------------------------

def test_ikinci_arama_iki_ret_elle(tmp_path):
    from test_ikinci_arama import _check
    from bidr.candidates import arama as A
    root, ids = _fixture("test_ikinci_arama", "ws", tmp_path)
    A.prepare(root, profile=None, olcutler=["B.2.3"])
    d = root / "work" / A.WORK
    pk = [p.stem for p in d.glob("*.json") if not p.name.endswith(".out.json")]
    for k in pk:
        (d / f"{k}.out.json").write_text("{bozuk", encoding="utf-8")
    st = A.apply(root, model="t")
    assert set(st["gecersiz"]) == set(pk)
    assert _check(root).kim == "ajan"
    for k in pk:
        (d / f"{k}.out.json").write_text("{yine bozuk", encoding="utf-8")
    st = A.apply(root, model="t")
    assert set(st["elle_bakilmali"]) == set(pk) and not st["gecersiz"]
    ck = _check(root)
    assert ck.bitti and ck.ilerleme["elle_bakilmali"] == len(pk)


def _fixture(mod: str, name: str, *args):
    """Başka test modülünün fixture gövdesini doğrudan çağırır (ad çakışmasın diye içe aktarmadan)."""
    import importlib
    f = getattr(importlib.import_module(mod), name)
    return f._get_wrapped_function()(*args)


# -- yazım / doğrulama / yönler ---------------------------------------------------------------------------

def test_write_sema_hatasi_kenara_alinir_sinirda_bolum_karari_cikar(tmp_path):
    from test_write import answer, make_report_ws
    from bidr.write import karar as KR
    from bidr.write import run as W
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    d = ws / "work" / "write"
    spec = next(s for s in load_spec()["asamalar"] if s["id"] == "write")
    ctx = C.Ctx(Workspace(ws), {}, formatter(Workspace(ws), {}), spec)
    for i in range(3):
        (d / "B.1.1.out.json").write_text(f"{{bozuk {i}", encoding="utf-8")
        st = W.apply(ws, model="t")
        assert "B.1.1" in st["gecersiz"]
        ck = C.write_tamam(ctx)
        if i < 2:   # yeniden yazım sınırının altında: kenara alındı, ajan yeni cevap yazar (üstüne değil)
            assert not (d / "B.1.1.out.json").exists() and st["yeniden"]["B.1.1"]["deneme"] == i + 1
            assert ck.kim == C.AJAN and ck.bekleyen == ["B.1.1"]
        else:       # sınırda: son cevap yerinde, bölümün kararı (panel yazim_bildir)
            assert st["insan_gerekli"] == ["B.1.1"] and (d / "B.1.1.out.json").exists()
            assert ck.kim == C.INSAN and [x["olcut"] for x in ck.karar_bekleyen] == ["B.1.1"]
            assert not ck.karar_bekleyen[0]["kabul_edilebilir"]
    with pytest.raises(ValueError):
        KR.karar(ws, "B.1.1", "kabul")
    KR.karar(ws, "B.1.1", "cikar", "şemaya uymuyor")                          # şemasız son cevapla da çıkarılır
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    assert t["durum"] == "reddedildi" and t["insan_karari"] == "cikar" and t["paragraflar"] == []
    assert C.write_tamam(ctx).bitti


def test_verify_iki_gecersiz_cevap_bolum_kararina_gider_dongu_yok(tmp_path):
    from test_verify import text, verdicts, written
    from test_write import answer
    from bidr.verify import run as V
    ws = written(tmp_path)
    V.prepare(ws)
    for i in range(2):
        out = verdicts(ws)
        out["cumleler"] = out["cumleler"][:-1]                              # kararı olmayan cümle
        answer(ws, "B.1.1", out, stage="verify")
        st = V.apply(ws)
        if i == 0:
            assert "B.1.1" in st["gecersiz"] and not (ws / "work/verify/B.1.1.out.json").exists()
            assert C.verify_tamam(_ctx(ws, "verify")).kim == C.AJAN
    assert "B.1.1" in st["elle_bakilmali"] and text(ws)["durum"] == "reddedildi"
    ck = C.verify_tamam(_ctx(ws, "verify"))
    assert ck.kim == C.INSAN and "doğrulanamadı" in ck.neden                 # yeniden yazım turu değil
    assert V.apply(ws)["degismedi"] == 1                                    # aynı cevap yeniden işlenmez
    V.decide(ws, "B.1.1", "kabul", "metin doğru")                            # bölüm olduğu gibi kabul edebilir
    assert C.verify_tamam(_ctx(ws, "verify")).bitti


def test_yonler_yazim_ve_dogrulama_iki_ret(ws_yon):
    from test_yonler import _answer
    from bidr.write import yonler as Y
    from bidr.write import yon_karar as YK
    ws = ws_yon
    Y.prepare(ws, only=["B"])
    bad = (["Bölümümüzde paketler güncellenmektedir (B.1.3)."], ["İzleme kanıtı oluşturulmalıdır (B.1.1)."])
    _answer(ws, "B", *bad)
    st = Y.apply(ws, model="t")
    assert "B" in st["gecersiz"] and not (ws / "work/yonler/B.out.json").exists()
    _answer(ws, "B", *bad)
    st = Y.apply(ws, model="t")
    assert "B" in st["elle_bakilmali"]
    ck = C.yonler_tamam(_ctx(ws, "yonler"))
    assert "B" not in (ck.bekleyen or []) and any("şablon yönergesiyle" in u for u in ck.uyarilar)
    assert "B" in Y.apply(ws, model="t")["elle_bakilmali"]
    # doğrulama cevabı iki kez geçersiz → bölümün kararı (kabul edilebilir), yeniden yazım turu yok
    (ws / "work/yonler/B.out.json").unlink()
    _answer(ws, "B", ["Bölümümüzde ders bilgi paketleri güncellenmektedir (B.1.1)."],
            ["B.1.2 ölçütünde yalnız kurum geneli kanıt bulunmaktadır (B.1.2)."])
    assert Y.apply(ws, model="t")["islenen"] == 1
    Y.verify_prepare(ws)
    for _ in range(2):
        (ws / "work/verify/yonler/B.out.json").write_text(json.dumps({"maddeler": [], "genel": ""}), encoding="utf-8")
        st = Y.verify_apply(ws, model="t")
    assert "B" in st["elle_bakilmali"]
    kb = YK.bekleyen(Workspace(ws))
    assert [x["alan"] for x in kb] == ["B"] and kb[0]["kabul_edilebilir"]
    ck = C.yonler_tamam(_ctx(ws, "yonler"))       # öbür alanların (A, C, D) işi sürer; B bölümün kararında
    assert [x["alan"] for x in ck.karar_bekleyen] == ["B"] and "B:" not in ck.neden


@pytest.fixture
def ws_yon(tmp_path):
    return _fixture("test_yonler", "ws", tmp_path)


# -- kör denetim ---------------------------------------------------------------------------------------------

def test_kor_denetim_iki_ret_paket_denetlenemedi_olcum_yazilir(tmp_path):
    from test_kor_denetim import _check, answer_all, make_ws
    from bidr.kor import run as KD
    ws = make_ws(tmp_path)
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": "{bozuk"})
    st = KD.apply(ws)
    assert "B.1.1" in st["gecersiz"] and not st["yazildi"]
    assert _check(ws, "kor_denetim").kim == "ajan"
    answer_all(ws, {"B.1.1": "{yine bozuk"})
    st = KD.apply(ws)
    assert "B.1.1" in st["elle_bakilmali"] and st["yazildi"]
    js = json.loads((ws / KD.OUT_JSON).read_text(encoding="utf-8"))
    assert js["denetlenemedi"] == ["B.1.1"]
    c = _check(ws, "kor_denetim")
    assert c.bitti and any("denetlenemedi" in u for u in c.uyarilar)


# -- transcribe (ortak yardımcıya taşındı; davranış testleri tests/test_transcribe.py) ------------------------

def test_transcribe_ortak_sinirlar():
    from bidr.transcribe import run as R
    assert (R.AYNI_NEDEN_SINIRI, R.DENEME_SINIRI, R.ELLE, R.ELLE_MD) == \
        (CV.AYNI_NEDEN_SINIRI, CV.DENEME_SINIRI, CV.ELLE, CV.ELLE_MD)


# -- bölümün kesin kararı (panel "Bakmanız gerekenler") --------------------------------------------------------

def _describe_elle(tmp_path):
    from test_describe import POSTER_OCR, _item, _out, _ws
    from bidr.describe import run as R
    ws, src, ids = _ws(tmp_path, {"afis": (".png", POSTER_OCR, 1)})
    did = ids["afis"]
    R.prepare(ws, only=[did], source=src)
    for m in ("BAHAR ŞENLİĞİ", "YAZ ŞENLİĞİ"):
        _out(ws, did, [_item(icerik="afis", gorunen_yazilar=[{"yer": "afis", "metin": m}])])
        R.apply(ws)
    return ws, src, did


def test_elle_liste_makine_okunur_ve_karar_kesin_iki_tur(tmp_path, capsys):
    import shutil
    from test_describe import POSTER_OCR, _check
    from bidr.cli import main
    from bidr.describe import run as R
    ws, src, did = _describe_elle(tmp_path)
    assert main(["elle", "liste", "-w", str(ws), "--json"]) == 0
    xs = json.loads(capsys.readouterr().out)
    x = next(i for i in xs if i["anahtar"] == did)
    assert x["asama"] == "describe" and x["neden"] == "supheli" and "uyuşmuyor" in x["neden_metni"]
    assert "YAZ ŞENLİĞİ" in x["model_cevabi"] and x["belge_metni"] == POSTER_OCR and x["karar"] is None
    assert {s["karar"] for s in x["secenekler"]} == {"kabul", "varsayilan", "atla"}
    # karar verilmeden de rapor durmaz (aşama bitti; varsayılan: betimleme yok)
    assert _check(ws, src).bitti
    assert main(["elle", "karar", "-w", str(ws), "describe", did, "varsayilan", "--kim", "bolum@x"]) == 0
    rec = CV.kararlar(ws, "work/describe")[did]
    assert rec["kim"] == "bolum@x" and rec["zaman"] and rec["belge_sha"]
    for _ in range(2):   # iki tur üst üste: paket silinip yeniden hazırlansa da (talimat değişti) yeniden sorulmaz
        shutil.rmtree(ws / "work/describe" / did, ignore_errors=True)
        assert R.prepare(ws, auto=True, source=src)["zaten_tamam"] == 1
        assert not (ws / "work/describe" / did).exists()
        R.apply(ws)
        assert _check(ws, src).bitti
        assert (ws / "text" / f"{did}.txt").read_text(encoding="utf-8") == POSTER_OCR
    assert CV.liste(ws)[0]["karar"]["karar"] == "varsayilan"
    # belgenin içeriği değişirse (envanter sha256) karar düşer: yeniden sorulur
    inv = (ws / "inventory.csv").read_text(encoding="utf-8")
    sha = next(r for r in inv.splitlines() if r.startswith(did)).split(",")[1]
    (ws / "inventory.csv").write_text(inv.replace(sha, "0" * 64), encoding="utf-8")
    assert CV.Kesin(ws, "describe").get(did) is None


def test_elle_karar_kabul_son_cevabi_uygular_ve_yeniden_sorulmaz(tmp_path):
    from test_describe import _check
    from bidr.describe import run as R
    ws, src, did = _describe_elle(tmp_path)
    CV.karar_ver(ws, "describe", did, "kabul", kim="bolum")
    assert "YAZ ŞENLİĞİ" in (ws / "text" / f"{did}.txt").read_text(encoding="utf-8")
    assert R.load_log(Workspace(ws))[did]["durum"] == "uygulandi"
    assert _check(ws, src).bitti and R.prepare(ws, auto=True, source=src)["zaten_tamam"] == 1
    with pytest.raises(ValueError):
        CV.karar_ver(ws, "describe", "yok", "kabul")


def test_elle_karar_kaba_atla_yeniden_sorulmaz(tmp_path):
    from test_decide import DOCS, FakeLLM, _agent
    from bidr.audit.run import karar_verilemeyen
    from bidr.decide.run import apply, prepare
    from synth import make_ws
    docs = [{"text": DOCS[k], "gold": ["B.1.1"], "path": f"x/{k}.pdf"} for k in ("aynı", "degil")]
    root = make_ws(tmp_path / "ws", docs)
    ids = {k: d["id"] for k, d in zip(("aynı", "degil"), docs)}
    with open(root / "candidates.jsonl", "w", encoding="utf-8") as f:
        for x in ids.values():
            f.write(json.dumps({"doc_id": x, "adaylar": [{"olcut": "B.1.1"}]}) + "\n")
    (root / "documents.jsonl").write_text("".join(json.dumps({"doc_id": x, "doc_type": "kurul_karari"}) + "\n"
                                                  for x in ids.values()), encoding="utf-8")
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    bad = ids["degil"]
    _agent(root, fake, "coarse", broken={bad})
    apply(root, "coarse", model="m", backend=b)
    (root / "work/coarse" / f"{bad}.out.json").write_text("{x", encoding="utf-8")
    apply(root, "coarse", model="m", backend=b)
    x = next(i for i in CV.liste(root) if i["anahtar"] == bad)
    assert x["asama"] == "karar_kaba" and {s["karar"] for s in x["secenekler"]} == {"varsayilan", "atla"}
    CV.karar_ver(root, "karar_kaba", bad, "atla", kim="b")
    for _ in range(2):   # paket yenilense de yeniden sorulmaz
        for p in (root / "work/coarse").glob(f"{bad}*"):
            p.unlink()
        prepare(root, "coarse", backend=b)
        assert not (root / "work/coarse" / f"{bad}.json").exists()
        assert C.karar_tamam(_ctx(root, "karar_kaba")).bitti
    assert karar_verilemeyen(Workspace(root), list(read_jsonl(root / "decisions.jsonl")), {}, {}) == []


def _inceleme_ws(tmp_path):
    """test_audit sentetik ws + yalnız transcribe.jsonl'de elle bakılmalı bir belge (4ee6d1c kaydı)."""
    from bidr.common import write_jsonl
    from bidr.transcribe import run as R
    ws = _fixture("test_audit", "ws", tmp_path)
    (ws / "text").mkdir(exist_ok=True)
    (ws / "text" / "d_ocr.txt").write_text("sentetik tarama metni", encoding="utf-8")
    (ws / "inventory.csv").write_text("doc_id,sha256,rel_path\nd_ocr,abc123,klasor/tarama.pdf\n", encoding="utf-8")
    (ws / "work/transcribe/d_ocr").mkdir(parents=True)
    (ws / "work/transcribe/d_ocr/d_ocr.out.json").write_text(json.dumps(
        {"sayfalar": [{"sayfa": 1, "okunabilirlik": "iyi", "metin": "SENTETİK OKUMA"}]}), encoding="utf-8")
    write_jsonl(ws / R.LOG, [{"doc_id": "d_ocr", "durum": R.ELLE, "neden": "supheli", "deneme": 2}])
    return ws


def _inc_satirlari(xlsx):
    from openpyxl import load_workbook
    from bidr.audit import sade as S
    wb = load_workbook(xlsx)
    sh = wb[S.SH_INC]
    head = [c.value for c in sh[1]]
    col = {k: head.index(h) + 1 for k, h, _, _ in S.INC_COLS}
    rows = {}
    for r in range(S.INC_ILK, sh.max_row + 1):
        sid = sh.cell(r, col["satir"]).value
        if sid:
            rows[sid] = {k: sh.cell(r, c).value for k, c in col.items()} | {"_r": r}
    return wb, sh, col, rows


def test_elle_inceleme_sayfasinda_satir_karar_kesin_iki_tur(tmp_path):
    from bidr.audit.run import apply as audit_apply, audit
    ws = _inceleme_ws(tmp_path)
    audit(ws)
    wb, sh, col, rows = _inc_satirlari(ws / "review.xlsx")
    r = rows["d_ocr|elle:transcribe"]
    assert r["bolum"] == 1 and r["oneri"] == "Bakın" and not r["karar"] and r["belge"] == "tarama.pdf"
    assert "SENTETİK OKUMA" in r["alinti_kisa"] and "taramayla uyuşmayan" in r["neden"]
    assert "Kabul" in r["dikkat"] and "Ret" in r["dikkat"] and "bir daha sorulmaz" in r["dikkat"]
    # karar verilmeden apply: varsayılan, kayıt yok (raporu durdurmaz)
    assert audit_apply(ws)["elle"] == {} and not CV.Kesin(ws, "transcribe").get("d_ocr")
    sh.cell(r["_r"], col["karar"], "Ret")
    wb.save(ws / "review.xlsx")
    st = audit_apply(ws)
    assert st["elle"] == {"varsayilan": 1} and not st["elle_gecersiz"]
    assert CV.Kesin(ws, "transcribe").get("d_ocr")["karar"] == "varsayilan"
    for _ in range(2):   # iki tur üst üste: satır 3. bölümde kararıyla, yeniden sorulmaz, apply yeniden yazmaz
        audit(ws)
        _, _, _, rows = _inc_satirlari(ws / "review.xlsx")
        assert rows["d_ocr|elle:transcribe"]["bolum"] == 3 and rows["d_ocr|elle:transcribe"]["karar"] == "Ret"
        assert audit_apply(ws)["elle"] == {}
    assert len((ws / "work/transcribe" / CV.KARAR_DOSYA).read_text(encoding="utf-8").splitlines()) == 1


def test_elle_inceleme_kabul_gecersiz_oldugunda_hata(tmp_path):
    from bidr.audit.run import apply as audit_apply, audit
    ws = _inceleme_ws(tmp_path)
    audit(ws)
    wb, sh, col, rows = _inc_satirlari(ws / "review.xlsx")
    sh.cell(rows["d_ocr|elle:transcribe"]["_r"], col["karar"], "Başka maddeye taşı")
    wb.save(ws / "review.xlsx")
    assert "d_ocr|elle:transcribe" in audit_apply(ws)["elle_gecersiz"]


def test_elle_transcribe_dunku_kayit_listede_ve_karar_kesin(tmp_path):
    """4ee6d1c'nin elle bakılmalı kaydı (yalnız transcribe.jsonl'de) da listede; karar sonrası yeniden sorulmaz."""
    import test_transcribe as TT
    from bidr.transcribe import run as R
    from bidr.common import write_jsonl
    ws = tmp_path / "ws"
    (ws / "text").mkdir(parents=True)
    (ws / "inventory.csv").write_text("doc_id,sha256,rel_path\nd1,abc,a/b.pdf\n", encoding="utf-8")
    (ws / "text" / "d1.txt").write_text("ocr metni", encoding="utf-8")
    write_jsonl(ws / R.LOG, [{"doc_id": "d1", "durum": R.ELLE, "neden": "supheli", "deneme": 2, "istem_sha": "x"}])
    x = CV.liste(ws)[0]
    assert (x["asama"], x["anahtar"], x["belge"]) == ("transcribe", "d1", "b.pdf") and x["belge_metni"] == "ocr metni"
    CV.karar_ver(ws, "transcribe", "d1", "varsayilan")
    assert CV.Kesin(ws, "transcribe").get("d1")["karar"] == "varsayilan"
    assert TT is not None
