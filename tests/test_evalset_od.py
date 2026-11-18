"""Kontrollü değerlendirme setleri (evalsets/) ile audit OD hesabı (kod; model yok).

Her belgenin karar kaydı beklenen.yaml'dan sentetik `decisions.jsonl` olarak verilir:
- `ideal`: doğru çalışan ince karar → audit OD'si beklenenle birebir olmalı (zincir aritmetiği,
  kurum geneli tavanı, dönem kuralı, birim aitliği).
- `naif`: tuzağa düşen model kaydı → kod tek başına yakalıyor mu? Yakalayamadığı bilinen
  açıklar `bilinen_acik` gerekçesiyle xfail(strict): açık kapanınca test XPASS verip uyarır.
Araç: tools/degerlendir.py; kullanım: evalsets/README.md.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from bidr.audit.run import build

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("degerlendir", ROOT / "tools" / "degerlendir.py")
dg = importlib.util.module_from_spec(_spec)
sys.modules["degerlendir"] = dg
_spec.loader.exec_module(dg)

TUZAK = dg.load_set(ROOT / "evalsets" / "tuzak")
OD_SINIR = dg.load_set(ROOT / "evalsets" / "od-sinir")


def _crit(a, cid):
    return next(c for c in a.criteria if c["olcut"] == cid)


def _xfail(reason: str | None):
    return [pytest.mark.xfail(strict=True, reason="bilinen açık: " + " ".join(reason.split()))] if reason else []


def _ws(es, out, mod="ideal", vaka=None, birim=True):
    """Sentetik çalışma alanı + config.yaml (birim adı: gerçek çalışma alanında `bidr init` yazar).
    Birim adı metin denetimlerinin (birim aitliği, madde ilkesi, bölümün kendi usul belgesi) girdisidir."""
    ws = dg.make_workspace(es, out, mod, vaka)
    if birim:
        (ws / "config.yaml").write_text(yaml.safe_dump({"bidr": {"birim": es.veri["birim"]}}, allow_unicode=True),
                                        encoding="utf-8")
    return ws


# -- setlerin kendisi ------------------------------------------------------------------------

@pytest.mark.parametrize("es", [TUZAK, OD_SINIR], ids=["tuzak", "od-sinir"])
def test_set_integrity(es):
    assert dg.check_set(es) == []


def test_set_shape():
    assert 25 <= len(TUZAK.belgeler) <= 40
    tuzaklar = {b.kayit.get("tuzak") for b in TUZAK.belgeler}
    for t in ("yalniz_duyuru", "bos_anket", "kurum_geneli_yonerge", "celiskili_sonuc", "baska_bolum",
              "donem_sonrasi", "yururlukten_kalkmis", "cizelge_surumu", "yakin_metin"):
        assert t in tuzaklar, t
    assert sum(b.kayit.get("tuzak") == "cizelge_surumu" for b in TUZAK.belgeler) == 3
    for v in OD_SINIR.vakalar:
        assert 3 <= len(v["belgeler"]) <= 6, v["id"]
    assert {v["beklenen_od"] for v in OD_SINIR.vakalar} == {1, 2, 3, 4, 5}
    assert all(b.kayit.get("yazilmamali") is not None for b in TUZAK.belgeler)


def test_check_set_catches_errors(tmp_path):
    kopya = tmp_path / "set"
    shutil.copytree(ROOT / "evalsets" / "tuzak", kopya)
    p = kopya / "belgeler" / "t01-kariyer-gunu-duyurusu.md"
    p.write_text(p.read_text(encoding="utf-8") + "\nİletişim: birisi@ornek.example · Prof. Dr. Kimse\n"
                 "Gerçek Üniversitesi\n", encoding="utf-8")
    b = yaml.safe_load((kopya / "beklenen.yaml").read_text(encoding="utf-8"))
    b["belgeler"][1]["eslesmeler"][0]["alinti"] = "metinde olmayan alıntı"
    (kopya / "beklenen.yaml").write_text(yaml.safe_dump(b, allow_unicode=True), encoding="utf-8")
    err = "\n".join(dg.check_set(dg.load_set(kopya)))
    assert "e-posta" in err and "unvan" in err and "Gerçek Üniversitesi" in err and "birebir yok" in err


# -- od-sinir: ölçüt OD'si ------------------------------------------------------------------------

def _vaka_params():
    for v in OD_SINIR.vakalar:
        yield pytest.param(v, "ideal", id=f"{v['id']}-ideal")
        yield pytest.param(v, "naif", id=f"{v['id']}-naif", marks=_xfail(v.get("bilinen_acik")))


@pytest.mark.parametrize("vaka,mod", list(_vaka_params()))
def test_od_sinir(vaka, mod, tmp_path):
    ws = _ws(OD_SINIR, tmp_path / "ws", mod, vaka["id"])
    c = _crit(build(ws), vaka["olcut"])
    assert c["od"] == vaka["beklenen_od"], f"{vaka['id']} ({mod}): audit OD{c['od']}, beklenen OD{vaka['beklenen_od']}"
    if mod == "ideal":
        assert sorted(x["halka"] for x in c["eksik"]) == sorted(vaka["eksik_halka"])
        for n in vaka.get("not_icermeli") or []:
            assert any(n in x for x in c["notlar"]), (n, c["notlar"])


def test_od_sinir_single_workspace(tmp_path):
    """Bütün vakalar tek çalışma alanında (ayrı ölçütler): sonuç vaka vaka ile aynı."""
    ws = dg.make_workspace(OD_SINIR, tmp_path / "ws", "ideal")
    r = dg.compare(OD_SINIR, ws)
    assert r["ozet"]["olcut_od"]["tam"] == len(OD_SINIR.vakalar)
    assert r["ozet"]["kacirildi"] == 0 and r["ozet"]["islenen"] == len(OD_SINIR.belgeler)


# -- tuzak: belge başına (kod yakalıyor mu) ve ölçüt OD'si ------------------------------------------

@pytest.fixture(scope="module")
def tuzak_sonuc(tmp_path_factory):
    out = {}
    for mod in dg.MODLAR:
        ws = _ws(TUZAK, tmp_path_factory.mktemp(f"tuzak-{mod}"), mod)
        out[mod] = dg.compare(TUZAK, ws)
    return out


def test_tuzak_ideal_criteria(tuzak_sonuc):
    for c in tuzak_sonuc["ideal"]["olcutler"]:
        assert c["od_sonuc"] == "tam", c
        if c["beklenen_eksik"] is not None:
            assert c["eksik_ayni"], c
        assert c["notlar_tamam"], c
    assert all(d["sonuc"] == "yakalandı" and d["od_sonuc"] == "tam" for d in tuzak_sonuc["ideal"]["belgeler"])


def _naif_params():
    for b in TUZAK.belgeler:
        if b.naif_farkli:
            yield pytest.param(b.dosya, id=b.ad, marks=_xfail(b.kayit.get("bilinen_acik")))


@pytest.mark.parametrize("dosya", list(_naif_params()))
def test_tuzak_naif_caught_by_code(dosya, tuzak_sonuc):
    d = next(x for x in tuzak_sonuc["naif"]["belgeler"] if x["dosya"] == dosya)
    assert d["sonuc"] == "yakalandı", f"{dosya}: sayılan OD{d['sistem']['od']} > beklenen OD{d['beklenen']['od']} ({d['sistem']['halkalar']})"


def test_bolumun_kendi_yonergesi_kurum_geneli_sayilmaz(tuzak_sonuc):
    d = next(x for x in tuzak_sonuc["ideal"]["belgeler"] if x["dosya"].startswith("t14-"))
    assert d["beklenen"]["birim"] == "kendi"
    assert "kurum_geneli" not in d["sistem"]["isaretler"]


# -- araç: iddia denetimi ve yayım engeli -------------------------------------------------------------

def _texts_ws(tmp_path, *, metin_durumu: str, verify_karar: str, taslak: bool | None):
    from bidr.write import run as W
    ws = dg.make_workspace(TUZAK, tmp_path / "ws", "ideal")
    ids = {b.ad: b.doc_id for b in TUZAK.belgeler}
    with open(ws / "evidence-index.csv", "w", encoding="utf-8") as f:
        f.write("kanit_no,olcut,od,ad,dosya,doc_id,sayfalar,yuvalar,alintilar,kopyalar\n")
        f.write(f"1_OD3,A.4.3,3,Faaliyet raporu,x.md,{ids['t08-faaliyet-raporu-ozeti']},,,[],\n")
        f.write(f"2_OD3,A.4.3,3,Mezun anketi raporu,y.md,{ids['t07-mezun-anketi-komisyon-raporu']},,,[],\n")
        f.write(f"1_OD3,B.2.2,3,Sınav takvimi,z.md,{ids['t17-sinav-takvimi-kesin']},,,[],"
                f"{ids['t15-sinav-takvimi-taslak']}; {ids['t16-sinav-takvimi-15-ekim']}\n")
    (ws / "texts").mkdir()
    t = {"olcut": "A.4.3", "od_onerisi": 3, "durum": metin_durumu,
         "paragraflar": [{"metin": "Mezun anketi uygulanmış ve mezun memnuniyeti %87 olarak ölçülmüştür [1_OD3]. "
                                   "Anket sonuçları komisyon raporunda ayrıca değerlendirilmiştir [2_OD3].",
                          "atiflar": ["1_OD3", "2_OD3"]}],
         "kanitlar": [], "eksikler": []}
    (ws / "texts" / "A.4.3.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    t2 = {"olcut": "B.2.2", "od_onerisi": 3, "durum": "dogrulandi",
          "paragraflar": [{"metin": "Yarıyıl sonu sınav takvimi ilan edilmiştir [1_OD3].", "atiflar": ["1_OD3"]}],
          "kanitlar": [], "eksikler": []}
    (ws / "texts" / "B.2.2.json").write_text(json.dumps(t2, ensure_ascii=False), encoding="utf-8")
    rec = {"olcut": "A.4.3", "durum": "reddedildi" if verify_karar != "destekleniyor" else "dogrulandi",
           "metin_sha": W.text_sha(t), "asama": "model", "kod_denetimi": [],
           "cumleler": [{"yer": "p1.c1", "metin": "…", "karar": verify_karar, "gerekce": "g"},
                        {"yer": "p1.c2", "metin": "…", "karar": "destekleniyor", "gerekce": "g"}]}
    rec2 = {"olcut": "B.2.2", "durum": "dogrulandi", "metin_sha": W.text_sha(t2), "asama": "model",
            "kod_denetimi": [], "cumleler": [{"yer": "p1.c1", "metin": "…", "karar": "destekleniyor", "gerekce": "g"}]}
    with open(ws / "verify.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n" + json.dumps(rec2, ensure_ascii=False) + "\n")
    if taslak is not None:
        (ws / ".bidr-render.json").write_text(json.dumps({"surum": 1, "taslak": taslak}), encoding="utf-8")
    return ws


def test_compare_claims_versions_and_publish_block(tmp_path):
    ws = _texts_ws(tmp_path, metin_durumu="reddedildi", verify_karar="desteklenmiyor", taslak=True)
    r = dg.compare(TUZAK, ws)
    by = {c["id"]: c for c in r["iddialar"]}
    assert by["t08-faaliyet-raporu-ozeti#1"]["durum"] == "GEÇTİ"           # çelişkili sayı tek kaynakla
    assert by["t07-mezun-anketi-komisyon-raporu#1"]["durum"] == "geçmedi"
    assert by["t17-sinav-takvimi-kesin#1"]["durum"] == "geçmedi"
    assert by["t01-kariyer-gunu-duyurusu#1"]["durum"] == "metin yok"
    assert r["surumler"][0]["durum"] == "tek kanıt"
    assert r["yayim"]["sonuc"] == "engelliyor"
    n = dg.write_agent_packages(TUZAK, dg.load_texts(ws), dg.load_index(ws), tmp_path / "paket")
    assert n >= 3
    pkg = json.loads((tmp_path / "paket" / "t08-faaliyet-raporu-ozeti--1.json").read_text(encoding="utf-8"))
    assert pkg["cumleler"] and pkg["cumleler"][0]["belgeler"]
    (tmp_path / "paket" / "t08-faaliyet-raporu-ozeti--1.out.json").write_text(
        json.dumps({"karar": "geciyor", "yerler": ["A.4.3:p1.c1"], "gerekce": "g"}), encoding="utf-8")
    r2 = dg.compare(TUZAK, ws, ajan_cevaplari=tmp_path / "paket")
    assert {c["id"]: c for c in r2["iddialar"]}["t08-faaliyet-raporu-ozeti#1"]["ajan"] == "geciyor"
    assert "## Yayıma hazır durumu" in dg.to_markdown(r2)


@pytest.mark.parametrize("metin,taslak,beklenen", [
    ("dogrulandi", True, "ENGELLEMİYOR"),          # desteklenmeyen cümleye rağmen metin doğrulandı
    ("reddedildi", False, "ENGELLEMİYOR"),         # render taslak damgası basmadı
    ("reddedildi", None, "engelliyor"),            # render yok: metin doğrulanmamış
])
def test_publish_block_detects_failures(tmp_path, metin, taslak, beklenen):
    ws = _texts_ws(tmp_path, metin_durumu=metin, verify_karar="kismen", taslak=taslak)
    assert dg.check_publish(ws)["sonuc"] == beklenen


def test_taslak_sinama_real_render(tmp_path):
    """Desteklenmeyen (ya da kısmen desteklenen) tek cümle: metin reddedildi, rapor TASLAK."""
    r = dg.taslak_sinama(tmp_path)
    assert r["tamam"], r


def test_cli(tmp_path, capsys):
    assert dg.main(["denetle", "--set", str(ROOT / "evalsets" / "od-sinir")]) == 0
    ws = tmp_path / "ws"
    assert dg.main(["sentetik", "--set", str(ROOT / "evalsets" / "od-sinir"), "--mod", "naif",
                    "--vaka", "kopuk-puko", "--out", str(ws)]) == 0
    md = tmp_path / "r.md"
    assert dg.main(["karsilastir", "--set", str(ROOT / "evalsets" / "od-sinir"), "-w", str(ws),
                    "--md", str(md), "--json", str(tmp_path / "r.json")]) == 0
    txt = md.read_text(encoding="utf-8")
    assert "| B.1.5 | kopuk-puko | 3 | 3 | tam" in txt          # K→Ö bağı denetimi (kapandı)
    assert json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["ozet"]["belge"] == len(OD_SINIR.belgeler)
