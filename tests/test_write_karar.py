"""`bidr write karar`: yeniden yazımlardan sonra kod denetimini geçemeyen metin için insan kararı
(sentetik; ajan cevapları elle yazılır)."""
from __future__ import annotations

import json

import pytest

from test_verify import verdicts
from test_write import GOOD, answer, make_report_ws

from bidr.common import Workspace
from bidr.pipeline import checks as C
from bidr.pipeline.state import formatter, load_spec
from bidr.verify import run as V
from bidr.write import karar as KR
from bidr.write import run as W

P1 = GOOD["paragraflar"][0]["metin"]
P2 = GOOD["paragraflar"][1]["metin"]


def _out(*paras: str) -> dict:
    return {"paragraflar": [{"metin": p} for p in paras], "onceki_yila_gore": ""}


# yalnız üslup bulguları (abartı, slogan, koçluk, tahmin): her deneme farklı cevap
USLUP = [_out(P1.replace("süreç tanımlanmıştır", "süreç başarıyla tanımlanmıştır"), P2),
         _out(P1.replace("süreç tanımlanmıştır", "süreç titizlikle tanımlanmıştır"), P2),
         _out(P1.replace("süreç tanımlanmıştır", "süreç muhtemelen özenle tanımlanmıştır"), P2)]
# atıf kusuru (bilinmeyen atıf) + üslup
ATIF = [_out(P1.replace("[1_OD2]", "[9_OD2]"), P2),
        _out(P1.replace("[1_OD2]", "[8_OD2]"), P2),
        _out(P1.replace("süreç tanımlanmıştır", "süreç başarıyla tanımlanmıştır").replace("[1_OD2]", "[7_OD2]"), P2)]


def _ctx(ws):
    w = Workspace(ws)
    spec = next(s for s in load_spec()["asamalar"] if s["id"] == "write")
    return C.Ctx(w, {}, formatter(w, {}), spec)


def _takil(ws, cevaplar) -> dict:
    W.prepare(ws)
    st = None
    for i, o in enumerate(cevaplar):
        answer(ws, "B.1.1", o)
        st = W.apply(ws, model="test:ajan")
        assert "B.1.1" in st["gecersiz"]
        if i < len(cevaplar) - 1:
            assert not st["insan_gerekli"], i            # ilk yazım + 2 yeniden yazım
    return st


def test_iki_yeniden_yazimdan_sonra_insan_karari(tmp_path):
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    answer(ws, "B.1.1", USLUP[0])
    W.apply(ws)
    W.apply(ws)                                              # aynı cevap ikinci kez sayılmaz
    assert json.loads((ws / KR.DENEMELER).read_text(encoding="utf-8"))["B.1.1"]["denemeler"].__len__() == 1
    ck = C.write_tamam(_ctx(ws))
    assert ck.kim == C.AJAN and not ck.karar_bekleyen
    st = _takil(ws, USLUP)
    assert st["insan_gerekli"] == ["B.1.1"]
    ck = C.write_tamam(_ctx(ws))
    assert ck.kim == C.INSAN and not ck.bitti
    assert [x["olcut"] for x in ck.karar_bekleyen] == ["B.1.1"]
    kb = ck.karar_bekleyen[0]
    assert kb["deneme"] == 3 and kb["sinir"] == 2 and kb["kabul_edilebilir"]
    assert all(KR.uslup_mu(i) for i in kb["sorunlar"])
    assert any("bidr write karar" in k and "cikar" in k for k in ck.komutlar)
    # bidr next metni ve JSON'u karar bekleyen listeyi taşır
    from bidr.pipeline.state import StageState
    assert "karar_bekleyen" in StageState.__dataclass_fields__


def test_tekrar_bir_tur_daha(tmp_path):
    ws = make_report_ws(tmp_path)
    _takil(ws, USLUP)
    r = KR.karar(ws, "B.1.1", "tekrar", "bir kez daha denensin")
    assert r["sinir"] == 2
    ck = C.write_tamam(_ctx(ws))
    assert ck.kim == C.AJAN and not ck.karar_bekleyen        # ajan bir kez daha yazar
    answer(ws, "B.1.1", _out(P1.replace("süreç tanımlanmıştır", "süreç eksiksiz tanımlanmıştır"), P2))
    assert W.apply(ws)["insan_gerekli"] == ["B.1.1"]
    assert C.write_tamam(_ctx(ws)).kim == C.INSAN
    answer(ws, "B.1.1", GOOD)                                # sonunda geçen cevap: kayıt kapanır
    st = W.apply(ws)
    assert st["islenen"] == 1 and not st["insan_gerekli"]
    assert not (ws / KR.DENEMELER).exists()
    assert C.write_tamam(_ctx(ws)).bitti


def test_kabul_yalniz_uslupte_ve_dogrulamaya_gider(tmp_path):
    ws = make_report_ws(tmp_path)
    _takil(ws, USLUP)
    r = KR.karar(ws, "B.1.1", "kabul", "üslup yerinde")
    assert r["karar"] == "kabul" and r["metin_sha"]
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    assert t["durum"] == "taslak" and t["yazim_karari"]["karar"] == "kabul"
    assert "muhtemelen" in t["paragraflar"][0]["metin"]
    assert t["kaynak"]["model"] == "test:ajan"
    assert not (ws / "work/write/GECERSIZ.md").exists()
    assert C.write_tamam(_ctx(ws)).bitti
    assert W.apply(ws)["degismedi"] == 1                     # aynı cevap yeniden işlenmez
    # doğrulama: kod denetimi kabul edilen üslup bulgularını yok sayar, bağımsız doğrulama yine yapılır
    st = V.prepare(ws)
    assert not st["kod_reddi"] and st["paket"] == 1
    answer(ws, "B.1.1", verdicts(ws), stage="verify")
    V.apply(ws, model="test:dogrulayici")
    assert json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))["durum"] == "dogrulandi"
    with pytest.raises(ValueError):                         # artık karar bekleyen değil
        KR.karar(ws, "B.1.1", "kabul")


def test_kabul_atif_bulgusunda_reddedilir(tmp_path):
    ws = make_report_ws(tmp_path)
    _takil(ws, ATIF)
    kb = C.write_tamam(_ctx(ws)).karar_bekleyen
    assert kb and not kb[0]["kabul_edilebilir"]
    with pytest.raises(ValueError, match="bilinmeyen_atif"):
        KR.karar(ws, "B.1.1", "kabul")
    assert not (ws / "texts/B.1.1.json").exists()
    assert not (ws / KR.HUMAN).exists()


def test_cikar_metni_rapordan_cikarir_dogrulama_beklemez(tmp_path):
    ws = make_report_ws(tmp_path)
    _takil(ws, ATIF)
    KR.karar(ws, "B.1.1", "cikar", "kanıt yok")
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    assert t["durum"] == "reddedildi" and t["insan_karari"] == "cikar"
    assert C.write_tamam(_ctx(ws)).bitti
    w = Workspace(ws)
    assert V.excluded(t, V.load_human(w))
    st = V.prepare(ws)
    assert not st["kod_reddi"] and st["paket"] == 0
    spec = next(s for s in load_spec()["asamalar"] if s["id"] == "verify")
    r = C.verify_tamam(C.Ctx(w, {}, formatter(w, {}), spec))
    assert r.bitti and any("rapora alınmayacak" in u for u in r.uyarilar)
    # yeniden yazım turu da açılmaz
    assert W.prepare_rejected(ws)["cikarildi"] == ["B.1.1"]


def test_karar_bekleyen_olmayan_olcut_ve_cli(tmp_path, capsys):
    from bidr.cli import main
    ws = make_report_ws(tmp_path)
    W.prepare(ws)
    assert main(["write", "karar", "-w", str(ws), "B.1.1", "cikar"]) == 2
    assert "insan kararı bekleyen bir ölçüt değil" in capsys.readouterr().out
    _takil(ws, USLUP)
    assert main(["write", "karar", "-w", str(ws), "B.1.1", "kabul", "--not", "uygun"]) == 0
    assert "insan onayıyla" in capsys.readouterr().out
    rec = [json.loads(x) for x in (ws / KR.HUMAN).read_text(encoding="utf-8").splitlines()]
    assert rec[-1]["karar"] == "kabul" and rec[-1]["not"] == "uygun"


def test_next_cikti_karar_bekleyen(tmp_path, capsys):
    from bidr.pipeline import cli as PC
    from bidr.pipeline.state import StageState
    s = StageState(id="write", ad="yazım", durum="bekliyor", kim="insan", neden="n", komutlar=["k"], sart="s",
                   onay="yok", katman="rapor", skill=None,
                   karar_bekleyen=[{"olcut": "B.1.1", "deneme": 3, "sinir": 2, "kabul_edilebilir": True,
                                    "sorunlar": [{"yer": "p1.1", "kod": "yasak_ifade", "ayrinti": "abartı: “x”"}]}])

    class Rep:
        calisma_alani, yonetilen, sonraki = str(tmp_path), True, s
    import types
    monkey = types.SimpleNamespace(workspace=str(tmp_path), json=False)
    import bidr.pipeline.state as ST
    orig = ST.evaluate
    ST.evaluate = lambda ws: Rep()
    try:
        PC._next(monkey)
    finally:
        ST.evaluate = orig
    out = capsys.readouterr().out
    assert "Karar bekleyen:" in out and "B.1.1 (deneme 3, kabul edilebilir)" in out
