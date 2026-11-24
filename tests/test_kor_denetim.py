"""Kör denetim ve düzeltme (`bidr denetim`, `bidr duzelt`; isteğe bağlı aşamalar kor_denetim, duzelt).

Sentetik çalışma alanı: yazılmış bir ölçüt metni (B.1.1), kanıt dizini, audit, bir alanın yön maddeleri,
ölçütte aday olup kanıt listesine girmemiş bir belge. Denetçi cevabını test yazar (sahte denetçi);
alıntı doğrulama, sınıflama, geçersiz cevap, düzeltme paketleri, karar komutu ve aşama sözleşmesi
sınanır. Model/sağlayıcı çağrılmaz.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.common import Workspace
from bidr.kor import duzelt as D
from bidr.kor import run as KD
from bidr.pipeline.checks import CHECKS, Ctx
from bidr.pipeline.state import formatter, load_spec, stage
from bidr.write import run as W
from bidr.write import sources as S
from bidr.write import yonler as Y

from test_write import GOOD, answer, make_report_ws

REL_ID = "dddd000000000004"
REL_TEXT = ("Bölüm Kurulu Toplantı Tutanağı. Ders planlarının izlenmesine ilişkin anket sonuçları kurulda "
            "görüşülmüş ve iki dersin değerlendirme yöntemi güncellenmiştir.")
YON_B = {"alan": "B", "baslik": "B Eğitim", "durum": "dogrulandi", "tur": 0, "girdi_sha": "x",
         "guclu": [{"metin": "Bölümümüzde ders planı değişiklikleri Bölüm Kurulunda görüşülmektedir (B.1.1).",
                    "olcutler": ["B.1.1"]}],
         "gelisme": [{"metin": "Ders planlarının izlenmesine ilişkin belge bulunmamaktadır (B.1.1).",
                      "olcutler": ["B.1.1"]}]}


def make_ws(root: Path) -> Path:
    ws = make_report_ws(root, with_c=True)
    W.prepare(ws)
    answer(ws, "B.1.1", GOOD)
    assert W.apply(ws)["islenen"] == 1
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    t["durum"] = "dogrulandi"
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    (ws / "text" / f"{REL_ID}.txt").write_text(REL_TEXT, encoding="utf-8")
    recs = [{"doc_id": REL_ID, "durum": "ok", "asama": "ince", "adaylar": ["B.1.1"], "kaba": {"secilen": ["B.1.1"]},
             "ince": {"birim_iliskisi": "kendi"}, "eslesmeler": []},
            {"doc_id": "aaaa000000000001", "durum": "ok", "asama": "ince", "adaylar": ["B.1.1"],
             "eslesmeler": [{"olcut": "B.1.1", "kabul": True}]}]
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    docs = [{"doc_id": REL_ID, "calisma_adi": "2025 Bölüm Kurulu Tutanağı", "doc_type": "tutanak", "tarih": "2025-03-01"},
            {"doc_id": "aaaa000000000001", "calisma_adi": "İş Akışı", "doc_type": "is_akisi"}]
    (ws / "documents.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in docs),
                                        encoding="utf-8")
    (ws / "yonler").mkdir(exist_ok=True)
    (ws / "yonler/B.json").write_text(json.dumps(YON_B, ensure_ascii=False), encoding="utf-8")
    (ws / ".bidr-render.json").write_text(json.dumps({"surum": 1}), encoding="utf-8")
    return ws


def _default(pkg: dict) -> dict:
    if KD.is_yon(pkg["olcut"]):
        return {"hucreler": [{"hucre": h, "puan": 4, "sorun": ""} for h in pkg["meta"]["hucreler"]],
                "bulgular": [], "genel": ""}
    return {"puan": 3, "puan_gerekce": "g", "denetci_od": pkg["meta"]["rapor_od"] or 1, "od_gerekce": "g",
            "cumleler": [], "bulgular": [], "kullanilmayan": [], "genel": ""}


def answer_all(ws: Path, special: dict | None = None) -> None:
    d = ws / "work" / KD.WORK
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".out.json") or p.name.startswith("_"):
            continue
        pkg = json.loads(p.read_text(encoding="utf-8"))
        out = (special or {}).get(p.stem) or _default(pkg)
        p.with_name(f"{p.stem}.out.json").write_text(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                                                    encoding="utf-8")


B11 = {"puan": 2, "puan_gerekce": "sayı hatası var", "denetci_od": 2, "od_gerekce": "OD3 kanıtı yalnız bir form",
       "cumleler": [
           {"alinti": "değişiklik Bölüm Kurulunda görüşülür", "etiket": "D", "doc_id": "aaaa000000000001",
            "kanit_alintisi": "Ders planı değişikliği Bölüm Kurulunda görüşülür", "gerekce": ""},
           {"alinti": "toplam iş yükü 150 olarak verilmiştir", "etiket": "U", "doc_id": "bbbb000000000002",
            "kanit_alintisi": "Toplam iş yükü: 150", "gerekce": "örnek tek formdan genellenmiş"},
           {"alinti": "bu cümle raporda hiç yok ve uydurmadır", "etiket": "U", "doc_id": "", "kanit_alintisi": "",
            "gerekce": "x"}],
       "bulgular": [
           {"tur": "sayi", "alinti": "AKTS kredisinin toplam iş yükünün 25'e bölümü", "doc_id": "bbbb000000000002",
            "kanit_alintisi": "AKTS kredisi, toplam iş yükünün 25'e bölümüdür", "aciklama": "biçim farkı",
            "oneri": "kaynaktaki gibi yaz"},
           {"tur": "abarti", "alinti": "raporda geçmeyen bir abartılı ifade burada", "doc_id": "", "kanit_alintisi": "",
            "aciklama": "x", "oneri": ""}],
       "kullanilmayan": [
           {"doc_id": REL_ID, "neden": "izleme sonuçlarının görüşüldüğünü gösteriyor",
            "kanit_alintisi": "anket sonuçları kurulda görüşülmüş"},
           {"doc_id": "aaaa000000000001", "neden": "x", "kanit_alintisi": "Ders planı değişikliği Bölüm Kurulunda"}],
       "genel": ""}
YON = {"hucreler": [{"hucre": "guclu", "puan": 4, "sorun": ""}, {"hucre": "gelisme", "puan": 2, "sorun": "çelişki"}],
       "bulgular": [{"tur": "olcut_metniyle_celiski", "yer": "a1", "alinti": "izlenmesine ilişkin belge bulunmamaktadır",
                     "olcut": "B.1.1", "aciklama": "metin izlemeyi anlatıyor", "oneri": "madde çıkarılmalı"}],
       "genel": ""}


def _ctx(ws: Path, sid: str) -> Ctx:
    return Ctx(Workspace(ws), {}, formatter(Workspace(ws), {}), stage(sid))


def _check(ws: Path, sid: str):
    return CHECKS[stage(sid)["sart"]["denetim"]](_ctx(ws, sid))


@pytest.fixture
def ws(tmp_path):
    return make_ws(tmp_path)


def test_spec_optional_and_default_line_unchanged(ws):
    st = {s["id"]: s for s in load_spec()["asamalar"]}
    assert st["kor_denetim"]["istege_bagli"] and st["duzelt"]["istege_bagli"]
    assert st["kor_denetim"]["onkosul"] == ["render"] and st["duzelt"]["onkosul"] == ["kor_denetim"]
    assert st["kor_denetim"]["paralel"]["bolunebilir"] and st["kor_denetim"]["katman"] == "M"
    # istenmedi: ikisi de atlanır (varsayılan hat eskisi gibi biter), hiçbir şey yazılmaz
    k, d = _check(ws, "kor_denetim"), _check(ws, "duzelt")
    assert k.atlandi and "istenmedi" in k.neden and "denetim prepare" in k.neden
    assert d.atlandi
    assert not (ws / "work" / KD.WORK).exists() and not (ws / KD.OUT_JSON).exists()


def test_prepare_requires_report(tmp_path):
    ws = make_report_ws(tmp_path)
    with pytest.raises(KD.DenetimHatasi, match="render"):
        KD.prepare(ws)


def test_prepare_packages_are_blind(ws):
    st = KD.prepare(ws)
    assert st["tur"] == 1 and st["yon"] == 1 and st["olcut"] > 1
    d = ws / "work" / KD.WORK
    pkg = json.loads((d / "B.1.1.json").read_text(encoding="utf-8"))
    ist = pkg["istem"]
    assert pkg["gorev"] == "kor_denetim" and pkg["meta"]["rapor_od"] == 3
    assert "İşaretlenen OD: 3" in ist and "Bölüm Kurulunda görüşülür [1_OD2]" in ist      # rapor metni
    assert "Toplam iş yükü: 150" in ist                                                    # kanıtın METNİ
    assert REL_ID in ist and "anket sonuçları kurulda görüşülmüş" in ist                   # ilgili belge
    assert pkg["meta"]["ilgili"] == [REL_ID] and pkg["meta"]["kanit_docs"] == ["aaaa000000000001",
                                                                               "bbbb000000000002",
                                                                               "cccc000000000003"]
    # yazar bağlamı yok: yazım istemi, eksik notları, ince karar alıntısı bloğu, doğrulama gerekçesi
    for bad in ("KANITLAR (atıf yapılabilecek tek liste)", "örnek not", "alıntı 1:", "DOĞRULAMADA", "Eksikler"):
        assert bad not in ist, bad
    yon = json.loads((d / "yon_B.json").read_text(encoding="utf-8"))
    assert yon["gorev"] == "kor_denetim_yon" and "a1 (gelişmeye açık)" in yon["istem"]
    assert "Bölümümüzde ders planı değişiklikleri için süreç tanımlanmıştır" in yon["istem"]
    assert "[1_OD2]" not in yon["istem"]                                                   # atıfsız metin
    # kanıtsız ölçüt de paketlenir (kapsam kaybı için)
    b12 = json.loads((d / "B.1.2.json").read_text(encoding="utf-8"))
    assert "yazılmamış" in b12["istem"] and b12["meta"]["metin_var"] is False
    # aynı tur yeniden prepare: değişmez; bitmiş tur yeniden istenemez
    assert KD.prepare(ws)["yeni"] == 0


def test_apply_validates_quotes_and_classifies(ws):
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": B11, "yon_B": YON})
    st = KD.apply(ws, model="test-denetci")
    assert st["yazildi"] and not st["gecersiz"]
    js = json.loads((ws / KD.OUT_JSON).read_text(encoding="utf-8"))
    assert js["ic_olcum"] is True and "iç ölçüm" in js["aciklama"] and js["model"] == "test-denetci"
    f = {x["id"]: x for x in js["bulgular"]}
    assert f["B.1.1-1"]["sinif"] == "metin" and f["B.1.1-1"]["dogrulama"] == "dogrulandi"
    assert f["B.1.1-2"]["dogrulama"] == "dogrulanamadi" and "raporun bu bölümünde" in f["B.1.1-2"]["dogrulama_nedeni"]
    # doğrulanmış U cümlesi metin bulgusu olur; doğrulanamayan cümle sayılmaz
    u = [x for x in js["bulgular"] if x["tur"] == "cumle_U"]
    assert len(u) == 1 and u[0]["alinti"] == "toplam iş yükü 150 olarak verilmiştir"
    row = next(r for r in js["olcutler"] if r["olcut"] == "B.1.1")
    assert (row["D"], row["K"], row["U"]) == (1, 0, 1) and row["puan"] == 2 and row["rapor_od"] == 3
    assert f["B.1.1-od"]["sinif"] == "od" and f["B.1.1-od"]["tur"] == "od_dusur" and f["B.1.1-od"]["denetci_od"] == 2
    assert f["B.1.1-k1"]["sinif"] == "kanit" and f["B.1.1-k1"]["dogrulama"] == "dogrulandi"
    assert f["B.1.1-k1"]["belge_adi"] == "2025 Bölüm Kurulu Tutanağı"
    assert f["B.1.1-k2"]["dogrulama"] == "dogrulanamadi" and "zaten" in f["B.1.1-k2"]["dogrulama_nedeni"]
    assert f["yon_B-1"]["alan"] == "B" and f["yon_B-1"]["dogrulama"] == "dogrulandi"
    assert js["ozet"]["bulgu"] == {"metin": 3, "od": 1, "kanit": 1, "dogrulanamadi": 2}
    md = (ws / KD.OUT_MD).read_text(encoding="utf-8")
    assert "İç ölçüm" in md and "Doğrulanamayan bulgular" in md and "| B.1.1 | 3 | 2 |" in md
    # bitmiş tur yeniden istenemez (ikinci denetim ayrı komut)
    with pytest.raises(KD.DenetimHatasi, match="--ikinci"):
        KD.prepare(ws)


def test_invalid_answer_is_listed_and_nothing_written(ws):
    KD.prepare(ws)
    bad_yon = {**YON, "hucreler": [{"hucre": "guclu", "puan": 4, "sorun": ""}] * 2}
    answer_all(ws, {"B.1.1": "{bozuk", "yon_B": bad_yon})
    st = KD.apply(ws)
    assert set(st["gecersiz"]) == {"B.1.1", "yon_B"} and not st["yazildi"]
    assert not (ws / KD.OUT_JSON).exists()
    g = (ws / "work" / KD.WORK / "GECERSIZ.md").read_text(encoding="utf-8")
    assert "- `B.1.1.json`:" in g and "aynı hücre" in g
    c = _check(ws, "kor_denetim")
    assert c.kim == "ajan" and set(c.bekleyen) == {"B.1.1", "yon_B"} and "taze" in c.komutlar[0]


def test_stage_contract_and_duzelt_cycle(ws, capsys):
    # istek → ajan → apply → bitti
    KD.prepare(ws)
    c = _check(ws, "kor_denetim")
    assert c.kim == "ajan" and "B.1.1" in c.bekleyen and "Opus" in c.komutlar[0]
    answer_all(ws, {"B.1.1": B11, "yon_B": YON})
    assert _check(ws, "kor_denetim").kim == "komut"
    KD.apply(ws)
    c = _check(ws, "kor_denetim")
    assert c.bitti and "iç ölçüm" in c.neden
    # düzelt: metin bulgusu olan ölçüt ve alan → komut
    d = _check(ws, "duzelt")
    assert d.kim == "komut" and "duzelt prepare" in d.komutlar[0] and "B.1.1" in d.neden and "B" in d.neden
    assert any("bölüm kararı" in u for u in d.uyarilar)
    st = D.prepare(ws)
    assert st["olcut"] == ["B.1.1"] and st["alan"] == ["B"]
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert "DENETİM DÜZELTME NOTU" in pkg["istem"] and "[B.1.1-1]" in pkg["istem"] and "[B.1.1-2]" not in pkg["istem"]
    assert "toplam iş yükü 150 olarak verilmiştir" in pkg["istem"] and "MEVCUT METİN" in pkg["istem"]
    assert pkg["istem"].index("ALT ÖLÇÜT") < pkg["istem"].index("DENETİM DÜZELTME NOTU")   # olağan yazım paketi + not
    ids = pkg["meta"]["duzeltme"]["bulgular"]
    assert set(ids) == {"B.1.1-1", "B.1.1-3"} and pkg["meta"]["duzeltme"]["denetim"] == KD.load(Workspace(ws))["id"]
    ypkg = json.loads((ws / "work/yonler/B.json").read_text(encoding="utf-8"))
    assert "DENETİM DÜZELTME NOTU" in ypkg["istem"] and "[yon_B-1]" in ypkg["istem"]
    # normal write prepare notu kaybetmez (aynı paket)
    W.prepare(ws)
    assert "DENETİM DÜZELTME NOTU" in json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["istem"]
    # yazar düzeltir; kod denetimi aynen işler; metin izi taşır → bulgular düzeltildi
    fixed = {"paragraflar": [GOOD["paragraflar"][0],
                             {"metin": "Ders bilgi formlarında AKTS kredisinin toplam iş yükünün 25'e bölümü olduğu "
                                       "belirtilmektedir [2_OD3]."}], "onceki_yila_gore": ""}
    answer(ws, "B.1.1", fixed)
    assert W.apply(ws, model="test-ajan-2")["islenen"] == 1
    t = W.load_text(Workspace(ws), "B.1.1")
    assert t["duzeltme"]["bulgular"] == sorted(ids) and t["durum"] == "taslak"      # yeniden doğrulamaya gider
    stt = KD.statuses(Workspace(ws), KD.load(Workspace(ws)))
    assert stt["B.1.1-1"][0] == "duzeltildi" and stt["B.1.1-3"][0] == "duzeltildi"
    assert stt["B.1.1-2"][0] == "dogrulanamadi"
    # yön maddesi henüz yeniden yazılmadı → düzelt hâlâ komut (yalnız alan B)
    crit, areas = D.targets(Workspace(ws))
    assert crit == [] and areas == ["B"]
    # yön düzeltmesinin izi: kayda geçince bitti sayılır
    y = Y.load(Workspace(ws), "B")
    y["duzeltme"] = ypkg["meta"]["duzeltme"]
    (ws / "yonler/B.json").write_text(json.dumps(y, ensure_ascii=False), encoding="utf-8")
    d = _check(ws, "duzelt")
    assert d.kim == "insan" and {x["bulgu_id"] for x in d.karar_bekleyen} == {"B.1.1-od", "B.1.1-k1"}
    kb = {x["bulgu_id"]: x for x in d.karar_bekleyen}
    assert kb["B.1.1-od"]["rapor_od"] == 3 and kb["B.1.1-od"]["denetci_od"] == 2
    assert kb["B.1.1-k1"]["doc_id"] == REL_ID and "deneme" not in kb["B.1.1-k1"]
    assert "denetim karar" in d.komutlar[1]
    # karar komutu: metin bulgusuna karar verilmez; doğrulanamayan bulguya da
    assert main(["denetim", "karar", "-w", str(ws), "B.1.1-1", "kabul"]) == 2
    assert main(["denetim", "karar", "-w", str(ws), "B.1.1-k2", "kabul"]) == 2
    assert main(["denetim", "karar", "-w", str(ws), "B.1.1-od", "kabul", "--not", "bölüm kurulu"]) == 0
    assert main(["denetim", "karar", "-w", str(ws), "B.1.1-k1", "kabul"]) == 0
    capsys.readouterr()
    # kabul edilen OD audit okunurken ölçütün OD'si olur; metin OD notuyla yeniden yazılır
    a = S.load_audit(ws / S.AUDIT)["B.1.1"]
    assert a["od"] == 2 and a["od_denetim"]["bulgu_id"] == "B.1.1-od"
    crit, _ = D.targets(Workspace(ws))
    assert crit == ["B.1.1"]
    W.prepare(ws)
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert "OD2 olarak kabul etti" in pkg["istem"] and pkg["meta"]["od_onerisi"] == 2
    assert set(pkg["meta"]["duzeltme"]["bulgular"]) == {"B.1.1-1", "B.1.1-3", "B.1.1-od"}
    # kabul edilen belge önerisi ikinci aramaya girer (bekliyor)
    assert KD.kanit_ciftleri(ws) == [{"doc_id": REL_ID, "olcut": "B.1.1", "bulgu_id": "B.1.1-k1"}]
    # ozet --json: durum ve karar
    assert main(["denetim", "ozet", "-w", str(ws), "--json"]) == 0
    v = json.loads(capsys.readouterr().out)
    f = {x["id"]: x for x in v["bulgular"]}
    assert f["B.1.1-od"]["durum"] == "kabul" and f["B.1.1-od"]["karar"]["not"] == "bölüm kurulu"
    assert f["B.1.1-1"]["durum"] == "duzeltildi" and "cumleler" not in v["olcutler"][0]
    assert v["dku"]["U"] == "kaynakla uyuşmuyor" and v["tur_adlari"]["sayi"] == "sayı hatası"


def test_od_decision_blocked_by_committee_approval(ws):
    a = json.loads((ws / S.AUDIT).read_text(encoding="utf-8"))
    a["olcutler"][0]["od_onayli"] = 3
    (ws / S.AUDIT).write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": {**B11, "bulgular": [], "cumleler": [], "kullanilmayan": []}})
    KD.apply(ws)
    st = KD.statuses(Workspace(ws), KD.load(Workspace(ws)))
    assert st["B.1.1-od"][0] == "bilgi" and "komisyon" in st["B.1.1-od"][1]
    with pytest.raises(KD.DenetimHatasi, match="komisyonca onaylanmış"):
        KD.decide(ws, "B.1.1-od", "kabul")


def test_od_override_goes_stale_when_code_od_changes(ws):
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": {**B11, "bulgular": [], "cumleler": [], "kullanilmayan": []}})
    KD.apply(ws)
    KD.decide(ws, "B.1.1-od", "kabul")
    assert S.load_audit(ws / S.AUDIT)["B.1.1"]["od"] == 2
    make_report_ws(ws, od=4, with_c=True)                    # kanıt/inceleme değişti: kod önerisi 4
    assert S.load_audit(ws / S.AUDIT)["B.1.1"]["od"] == 4    # karar eskidi, uygulanmaz


def test_second_round_is_measurement_with_comparison(ws):
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": {**B11, "bulgular": [], "cumleler": [], "kullanilmayan": [], "denetci_od": 3}})
    KD.apply(ws)
    assert _check(ws, "duzelt").bitti
    st = KD.prepare(ws, ikinci=True)
    assert st["tur"] == 2 and (ws / "kor-denetim-1.json").exists()
    assert (ws / "work" / KD.WORK / "_tur1" / "B.1.1.out.json").exists()
    assert _check(ws, "kor_denetim").kim == "ajan"
    answer_all(ws, {"B.1.1": {**B11, "puan": 4, "denetci_od": 2, "cumleler": [], "kullanilmayan": []}})
    KD.apply(ws)
    js = KD.load(Workspace(ws))
    k = js["karsilastirma"]
    assert js["tur"] == 2 and k["onceki_tur"] == 1
    assert next(r for r in k["olcutler"] if r["olcut"] == "B.1.1") == {"olcut": "B.1.1", "once": 2, "sonra": 4}
    stt = KD.statuses(Workspace(ws), js)
    assert all(d in ("bilgi", "dogrulanamadi") for d, _ in stt.values())       # ölçüm: düzeltilmez
    assert D.targets(Workspace(ws)) == ([], []) and _check(ws, "duzelt").bitti
    with pytest.raises(KD.DenetimHatasi):
        KD.decide(ws, "B.1.1-od", "kabul")


def test_second_round_waits_for_first_round_fixes(ws):
    KD.prepare(ws)
    answer_all(ws, {"B.1.1": B11, "yon_B": YON})
    KD.apply(ws)
    with pytest.raises(KD.DenetimHatasi, match="düzeltmesi bitmedi"):
        KD.prepare(ws, ikinci=True)


def test_report_change_makes_packages_stale(ws):
    KD.prepare(ws)
    answer_all(ws)
    t = W.load_text(Workspace(ws), "B.1.1")
    t["paragraflar"][0]["metin"] = t["paragraflar"][0]["metin"].replace("süreç", "işleyiş")
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    st = KD.apply(ws)
    assert st["eski"] == ["B.1.1"] and not st["yazildi"]
    c = _check(ws, "kor_denetim")
    assert c.kim == "komut" and "eski" in c.neden


def test_next_prints_audit_decisions(ws, capsys, monkeypatch):
    import bidr.pipeline.cli as PC
    import bidr.pipeline.state as ST
    s = ST.StageState(id="duzelt", ad="x", durum="bekliyor", kim="insan", neden="n", komutlar=[], sart="",
                      onay="yok", katman="D", skill=None,
                      karar_bekleyen=[{"bulgu_id": "B.1.1-od", "sinif": "od", "olcut": "B.1.1", "ozet": "OD 3 → 2"}])
    rep = ST.Report(str(ws), False, [s])
    monkeypatch.setattr(ST, "evaluate", lambda w: rep)
    monkeypatch.setattr(PC, "_head", lambda r: "bidr durum")

    class A:
        workspace, json = str(ws), False
    PC._next(A())
    assert "B.1.1-od (od): OD 3 → 2" in capsys.readouterr().out


def test_related_documents_in_write_package(ws):
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert "İLGİLİ AMA KANIT SAYILMAMIŞ BELGELER" in pkg["istem"]
    W.prepare(ws, only=["B.1.1"])
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    sec = pkg["istem"].split("İLGİLİ AMA KANIT SAYILMAMIŞ BELGELER")[-1]
    assert "2025 Bölüm Kurulu Tutanağı (tutanak, 2025-03-01)" in sec and pkg["meta"]["ilgili"] == [REL_ID]
    assert "İş Akışı" not in sec                                   # kanıt listesindeki belge değil
    assert "kanıt bulunmamaktadır / belge yoktur" in pkg["istem"]  # kural 16


def test_yonler_consistency_warning():
    t = {"guclu": [{"metin": "Bölümümüzde ders planları kurulda görüşülmektedir (B.1.1)."}],
         "gelisme": [{"metin": "Ders planlarına ilişkin belge bulunmamaktadır (B.1.1)."},
                     {"metin": "İzleme sonuçlarına ilişkin kanıt bulunmamaktadır (B.1.2)."}]}
    w = Y.tutarlilik(t)
    assert [(x["olcut"], x["guclu"], x["gelisme"]) for x in w] == [("B.1.1", ["g1"], "a1")]
    assert "çelişmediğini" in Y.tutarlilik_satirlari(t)[0]


from test_pipeline import kurulum  # noqa: E402,F401  (pytest fixture: yönetilen çalışma alanı)


def test_managed_next_contract(kurulum, capsys, monkeypatch):  # noqa: F811
    """Yönetilen çalışma alanında: önceki aşamalar bitmişken denetim istenmezse hat eskisi gibi biter;
    istenince `bidr next` kor_denetim'i ajan işi olarak verir (paralel bölünebilir)."""
    import bidr.pipeline.checks as C
    from bidr.pipeline.checks import Check
    src, ws, ans = kurulum
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    for s in load_spec()["asamalar"]:
        if s["id"] not in ("kor_denetim", "duzelt"):
            monkeypatch.setitem(C.CHECKS, s["sart"]["denetim"], lambda c: Check(bitti=True, neden="sınama"))
    capsys.readouterr()
    assert main(["next", "-w", str(ws)]) == 0
    assert "Bütün aşamalar bitti." in capsys.readouterr().out
    assert main(["status", "-w", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "[-] kor_denetim" in out and "[-] duzelt" in out
    # karar komutu denetim yokken hata
    assert main(["denetim", "karar", "-w", str(ws), "B.1.1-od", "kabul"]) == 2
    (ws / ".bidr-render.json").write_text(json.dumps({"surum": 1}), encoding="utf-8")
    assert main(["denetim", "prepare", "-w", str(ws)]) == 0
    capsys.readouterr()
    assert main(["next", "-w", str(ws), "--json"]) == 0
    n = json.loads(capsys.readouterr().out)["sonraki"]
    assert n["id"] == "kor_denetim" and n["kim"] == "ajan" and n["paralel"]["bolunebilir"]
    assert any("denetim apply" in k for k in n["komutlar"])
    answer_all(ws)
    assert main(["denetim", "apply", "-w", str(ws), "--model", "test-denetci"]) == 0
    capsys.readouterr()
    assert main(["next", "-w", str(ws)]) == 0
    assert "Bütün aşamalar bitti." in capsys.readouterr().out          # bulgu yok: düzelt de biter
    assert main(["denetim", "ozet", "-w", str(ws)]) == 0
    assert "İç ölçüm" in capsys.readouterr().out
