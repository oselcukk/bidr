"""bidr yonler: alan düzeyi Güçlü / Gelişmeye Açık Yönler — sentetik çalışma alanı, model yok."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.write import yonler as Y

ALLOWED = {"B.1.1", "B.1.2"}
OD = {"B.1.1": 3, "B.1.2": 2}


def _chk(metin: str, liste: str = "guclu", allowed=ALLOWED) -> set[str]:
    return {i["kod"] for i in Y.check_item(metin, liste=liste, alan="B", allowed=set(allowed), od=OD)}


def test_check_item_rules():
    assert _chk("Bölümümüzde ders bilgi paketleri güncellenmektedir (B.1.1).") == set()
    assert _chk("Bölümümüzde paketler güncellenmektedir (B.1.1). Kurul toplanmaktadır.") == {"olcutsuz"}
    assert _chk("Bölümümüzde paketler güncellenmektedir.") == {"olcutsuz"}
    assert _chk("Bölümümüzde yönetişim modeli tanımlanmıştır (A.1.1).") == {"baska_alan"}
    assert _chk("Bölümümüzde öğrenci iş yükü belirlenmiştir (B.2.3).") == {"dayanaksiz_olcut"}
    assert _chk("Bölümümüzde paketler güncellenmektedir [1_OD3] (B.1.1).") == {"kanit_atfi"}
    # koçluk / öğüt / vaat yok (write'taki kurallar)
    assert "yasak_ifade" in _chk("İzleme kanıtı oluşturulmalıdır (B.1.2).", "gelisme")
    assert "yasak_ifade" in _chk("İzleme mekanizması kurulması önerilir (B.1.2).", "gelisme")
    assert "gelecek_vaat" in _chk("İzleme mekanizması kurulacaktır (B.1.2).", "gelisme")
    assert "gelecek_vaat" in _chk("İzleme mekanizması planlanmaktadır (B.1.2).", "gelisme")
    assert "yasak_ifade" in _chk("Bölümümüzde süreç başarıyla yürütülmektedir (B.1.1).")
    # OD aşımı: ölçütün önerilen OD'si üstünde olgunluk dili
    assert "od_asimi" in _chk("Program çıktıları sistematik olarak izlenmektedir (B.1.1).")
    assert "od_asimi" in _chk("Uygulama içselleştirilmiştir (B.1.1).")
    assert "od_anisi" in _chk("Ölçüt OD3 düzeyindedir (B.1.1).")
    # aracın iç dili (kör test 2026-11-20): komisyon notu maddeye girmez
    assert "ic_dil" in _chk("Birime ait kanıtlar OD'ye sayılmamıştır (B.1.2).", "gelisme")
    assert "ic_dil" in _chk("Dayanaklar yalnız kurum geneli belgelerle eşleşmiştir (B.1.2).", "gelisme")
    assert "ic_dil" in _chk("Uygulama halkasına kurum düzenlemeleri esas alınmıştır (B.1.2).", "gelisme")
    assert "ic_dil" in _chk("Olgunluk düzeyine yalnız kurum geneli düzenleme sayılmıştır (B.1.2).", "gelisme")
    assert _chk("Bölümün bu dönemdeki uygulamasını gösteren belge bulunmamaktadır (B.1.2).", "gelisme") == set()
    # olumsuz bulgu cümlesi üst düzey dil denetimine takılmaz
    assert _chk("Program çıktılarının sistematik olarak izlendiğine ilişkin kanıt bulunmamaktadır (B.1.2).",
                "gelisme") == set()


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    (w / "texts").mkdir(parents=True)
    (w / "audit-olcutler.json").write_text(json.dumps({"olcutler": [
        {"olcut": "B.1.1", "od": 3, "sonraki_od": 4, "zincir_kisa": "P+ U+ K- Ö-",
         "eksik": [{"halka": "kontrol_et", "gereken": "izleme kanıtı"}]},
        {"olcut": "B.1.2", "od": 2, "sonraki_od": 3, "eksik": [], "kurum_geneli_yalniz": True},
        {"olcut": "B.1.3", "od": 5, "sonraki_od": None, "eksik": []}]}, ensure_ascii=False), encoding="utf-8")
    with open(w / "evidence-index.csv", "w", encoding="utf-8", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["kanit_no", "olcut", "od", "ad", "dosya", "doc_id", "sayfalar", "yuvalar",
                                           "alintilar"])
        wr.writeheader()
        for c in ("B.1.1", "B.1.2", "B.1.3"):
            wr.writerow({"kanit_no": "1_OD3", "olcut": c, "od": 3, "ad": "Sentetik kanıt", "dosya": "a.pdf",
                         "doc_id": "d1", "alintilar": "[]", "yuvalar": "[]"})
    t = {"olcut": "B.1.1", "od_onerisi": 3, "durum": "dogrulandi", "kanitlar": [],
         "paragraflar": [{"metin": "Bölümümüzde ders bilgi paketleri güncellenmektedir [1_OD3]. "
                                   "Yeni laboratuvar kurulması planlanmaktadır [komisyon]."}]}
    (w / "texts" / "B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    from bidr.write.run import text_sha
    (w / "verify.jsonl").write_text(json.dumps({"olcut": "B.1.1", "durum": "dogrulandi",
                                                "metin_sha": text_sha(t)}) + "\n", encoding="utf-8")
    t3 = {**t, "olcut": "B.1.3", "durum": "taslak"}                     # doğrulanmamış: güçlü yön olamaz
    (w / "texts" / "B.1.3.json").write_text(json.dumps(t3, ensure_ascii=False), encoding="utf-8")
    return w


def _answer(ws: Path, alan: str, guclu: list[str], gelisme: list[str]) -> None:
    (ws / "work" / "yonler" / f"{alan}.out.json").write_text(json.dumps(
        {"guclu": [{"metin": x} for x in guclu], "gelisme": [{"metin": x} for x in gelisme]}, ensure_ascii=False),
        encoding="utf-8")


def test_inputs_prepare_apply_verify(ws):
    src = Y.Inputs(ws)
    assert src.strong("B") == ["B.1.1"]                                   # yalnız doğrulanmış metin
    assert set(src.weak("B")) >= {"B.1.1", "B.1.2"}                       # eksik halka, kurum geneli, düşük OD
    assert "B.1.3" not in src.weak("B")                                   # OD5, eksik yok, kanıtı var
    assert any("kanıt bulunamadı" in f for f in src.findings("B.2.1"))    # kanıtsız ölçüt de bulgu
    block = src.render_criteria(["B.1.1"])
    assert "[1_OD3]" not in block and "planlanmaktadır" not in block      # atıf ve [komisyon] cümlesi yok
    st = Y.prepare(ws, only=["B"])
    assert st["paket"] == 1 and (ws / "work/yonler/B.json").exists()
    istem = json.loads((ws / "work/yonler/B.json").read_text(encoding="utf-8"))["istem"]
    assert "B.1.1 " in istem and "A.1.1" not in istem                     # yalnız o alan
    # geçersiz: güçlü yön doğrulanmamış ölçütten, gelişmede öğüt
    _answer(ws, "B", ["Bölümümüzde paketler güncellenmektedir (B.1.3)."],
            ["İzleme kanıtı oluşturulmalıdır (B.1.1)."])
    st = Y.apply(ws, model="test")
    assert set(st["gecersiz"]) == {"B"} and not (ws / "yonler/B.json").exists()
    errs = " ".join(st["gecersiz"]["B"])
    assert "dayanaksiz_olcut" in errs and "yasak_ifade" in errs
    _answer(ws, "B", ["Bölümümüzde ders bilgi paketleri güncellenmektedir (B.1.1)."],
            ["Ölçüme ilişkin izleme kanıtı bulunmamaktadır (B.1.1).",
             "Yalnız kurum geneli düzenleme bulunmaktadır (B.1.2)."])
    st = Y.apply(ws, model="test")
    assert st["islenen"] == 1 and not st["gecersiz"]
    t = Y.load(Y.Workspace(ws), "B")
    assert t["durum"] == "taslak" and t["guclu"][0]["olcutler"] == ["B.1.1"]
    # bağımsız doğrulama verify akışında
    from bidr.verify import run as V
    st = V.prepare(ws)
    assert st["yonler"]["paket"] == 1
    pkg = json.loads((ws / "work/verify/yonler/B.json").read_text(encoding="utf-8"))
    assert [m["yer"] for m in pkg["meta"]["maddeler"]] == ["g1", "a1", "a2"]
    assert "B.1.2 " in pkg["istem"] and "B.1.3 " not in pkg["istem"]     # yalnız atıf yapılan ölçütler
    (ws / "work/verify/yonler/B.out.json").write_text(json.dumps({"maddeler": [
        {"yer": y, "karar": "destekleniyor", "gerekce": "var"} for y in ("g1", "a1", "a2")], "genel": ""}),
        encoding="utf-8")
    st = V.apply(ws, model="dogrulayici")
    assert st["yonler"]["dogrulandi"] == ["B"]
    assert Y.load(Y.Workspace(ws), "B")["durum"] == "dogrulandi"
    # ölçüt metni değişirse alan maddeleri eskir; verify bu metni paketlemez
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    t["paragraflar"][0]["metin"] = "Bölümümüzde ders bilgi paketleri yayımlanmaktadır [1_OD3]."
    (ws / "texts/B.1.1.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    assert Y.verify_prepare(ws)["eski_metin"] == ["B"]
    assert Y.apply(ws)["eski"] == ["B"]                                   # eski paketin cevabı uygulanmaz


def test_cli_and_code_reject(ws, capsys):
    assert main(["yonler", "prepare", "-w", str(ws), "--only", "B"]) == 0
    _answer(ws, "B", ["Bölümümüzde ders bilgi paketleri güncellenmektedir (B.1.1)."], [])
    assert main(["yonler", "apply", "-w", str(ws), "--model", "t"]) == 0
    # sonradan elle bozulan madde kod denetiminde reddedilir (model işine gitmez)
    p = ws / "yonler/B.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["guclu"][0]["metin"] = "Bölümümüzde süreç mükemmel yürütülmektedir (B.1.1)."
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    assert main(["verify", "prepare", "-w", str(ws)]) == 1
    assert "reddedildi B (kod)" in capsys.readouterr().out
    assert Y.load(Y.Workspace(ws), "B")["durum"] == "reddedildi"
    assert main(["yonler", "prepare", "-w", str(ws), "--reddedilenler"]) == 0
    pkg = json.loads((ws / "work/yonler/B.json").read_text(encoding="utf-8"))
    assert pkg["meta"]["tur"] == 1 and "yasak_ifade" in pkg["istem"]


# -- yön hücresi için bölüm kararı (bidr/write/yon_karar.py) -------------------------------------------

def _gate(root):
    from bidr.common import Workspace
    from bidr.pipeline.checks import CHECKS, Ctx
    from bidr.pipeline.state import formatter, stage
    return CHECKS["yonler_tamam"](Ctx(Workspace(root), {}, formatter(Workspace(root), {}), stage("yonler")))


def _rejected_after_limit(ws, hukum: dict[str, str]):
    """B alanı yazılır, doğrulayıcı `hukum`'a göre reddeder; tur sınıra (2) çekilir."""
    from bidr.verify import run as V
    Y.prepare(ws, only=["B"])
    _answer(ws, "B", ["Bölümümüzde ders bilgi paketleri güncellenmektedir (B.1.1)."],
            ["Ölçüme ilişkin izleme kanıtı bulunmamaktadır (B.1.1).",
             "Yalnız kurum geneli düzenleme bulunmaktadır (B.1.2)."])
    assert Y.apply(ws, model="test")["islenen"] == 1
    V.prepare(ws)
    (ws / "work/verify/yonler/B.out.json").write_text(json.dumps({"maddeler": [
        {"yer": y, "karar": hukum.get(y, "destekleniyor"), "gerekce": "kısmen dayanak"} for y in ("g1", "a1", "a2")],
        "genel": ""}), encoding="utf-8")
    V.apply(ws, model="dogrulayici")
    p = ws / "yonler/B.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    assert t["durum"] == "reddedildi"
    t["tur"] = 2
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")


def _yalniz_b(monkeypatch):
    asil = Y.Inputs.criteria
    monkeypatch.setattr(Y.Inputs, "criteria", lambda self, alan: asil(self, alan) if alan == "B" else [])


def test_yon_gate_and_accept(ws, capsys, monkeypatch):
    from bidr.write import yon_karar as YK
    _rejected_after_limit(ws, {"g1": "kismen", "a2": "kismen"})
    c = _gate(ws)                       # öteki alanların işi sürerken karar bekleyen yine listelenir (write gibi)
    assert c.kim == "komut" and [x["alan"] for x in c.karar_bekleyen] == ["B"]
    _yalniz_b(monkeypatch)
    c = _gate(ws)
    assert c.kim == "insan" and "insan gerekli (B)" in c.neden
    kb = c.karar_bekleyen
    assert [x["alan"] for x in kb] == ["B"] and kb[0]["kabul_edilebilir"] and kb[0]["sinir"] == 2
    assert {m["yer"]: m["hukum"] for m in kb[0]["maddeler"]} == {"g1": "kismen", "a2": "kismen"}
    assert kb[0]["maddeler"][0]["yon"] == "guclu" and kb[0]["metin_sha"]
    assert main(["yonler", "karar", "-w", str(ws), "B", "kabul", "--not", "bölüm onayı"]) == 0
    t = Y.load(Y.Workspace(ws), "B")
    assert t["durum"] == "dogrulandi" and t["insan_karari"] == "kabul" and t["dogrulama"]["dogrulayici_reddi"]
    assert Y.load_log(Y.Workspace(ws))["B"]["asama"] == "insan"
    assert _gate(ws).bitti and not YK.bekleyen(Y.Workspace(ws))
    # ikinci karar: artık bekleyen değil
    assert main(["yonler", "karar", "-w", str(ws), "B", "cikar"]) == 2


def test_yon_accept_refused_when_unsupported_then_remove(ws, capsys, monkeypatch):
    from bidr.write import yon_karar as YK
    _rejected_after_limit(ws, {"g1": "kismen", "a2": "desteklenmiyor"})
    _yalniz_b(monkeypatch)
    kb = _gate(ws).karar_bekleyen
    assert not kb[0]["kabul_edilebilir"]
    assert main(["yonler", "karar", "-w", str(ws), "B", "kabul"]) == 2
    assert "kısmen" in capsys.readouterr().out
    assert main(["yonler", "karar", "-w", str(ws), "B", "cikar"]) == 0
    w = Y.Workspace(ws)
    t = Y.load(w, "B")
    assert t["durum"] == "reddedildi" and YK.cikarildi(t, YK.load_human(w))
    assert _gate(ws).bitti
    # metin değişirse karar geçmez (metin_sha)
    t["guclu"][0]["metin"] = "Bölümümüzde ders bilgi paketleri yayımlanmaktadır (B.1.1)."
    assert not YK.kararli(t, YK.load_human(w))


def test_yon_repeat_adds_round(ws, monkeypatch):
    from bidr.write import yon_karar as YK
    _rejected_after_limit(ws, {"a1": "desteklenmiyor"})
    _yalniz_b(monkeypatch)
    assert main(["yonler", "karar", "-w", str(ws), "B", "tekrar"]) == 0
    w = Y.Workspace(ws)
    assert YK.sinir(w, "B") == 3 and not YK.bekleyen(w)
    c = _gate(ws)
    assert c.kim == "komut" and any("--reddedilenler" in k for k in c.komutlar)
    st = Y.prepare(ws, rejected_only=True)
    assert st["tur"] == {"B": 3}
