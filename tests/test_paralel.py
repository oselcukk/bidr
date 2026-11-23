"""Paralel model aşamaları: `bidr parcala` (ayrık/eksiksiz/dengeli bölme, tavan), bölünmez aşama,
parça dışı yazım/ezme denetimi ve paralel koşunun tek ajanlı koşuyla aynı sonucu (karar, faaliyet,
audit-olcutler.json) vermesi. Sentetik veri; model çağrısı yok."""
from __future__ import annotations

import json
import random
import shutil

import pytest

from bidr.common import read_jsonl
from bidr.pipeline import paralel as P
from bidr.pipeline.state import load_spec

from test_decide import FakeLLM
from test_decide import ws as decide_ws  # noqa: F401  (fixture)


# -- sayı ve bölme ---------------------------------------------------------------------------------

def test_parca_sayisi_grows_with_packages_and_is_capped():
    f = P.parca_sayisi
    assert [f(n) for n in (0, 1, 20, 21, 60, 61, 100, 101, 380, 443, 5000)] == [0, 1, 1, 2, 2, 3, 3, 4, 10, 10, 10]
    assert f(443, azami=3) == 3
    assert f(30, esik=5, adim=5) == 6
    assert f(3, esik=1, adim=1) == 3                 # paket sayısını aşmaz
    assert f(10 ** 6, azami=99) == P.TAVAN           # kesin tavan 10


def test_bol_disjoint_complete_balanced():
    rnd = random.Random(7)
    w = {f"d{i:03d}": rnd.randint(1, 50_000) for i in range(443)}
    parts = P.bol(w, 10)
    flat = [k for p in parts for k in p]
    assert len(parts) == 10 and len(flat) == len(set(flat)) == len(w) and set(flat) == set(w)
    loads = [sum(w[k] for k in p) for p in parts]
    assert max(loads) - min(loads) <= max(w.values())   # LPT: fark en ağır paketi aşmaz
    assert P.bol(w, 10) == parts                         # belirlenimci
    assert P.bol({"a": 1, "b": 1}, 5) == [["a"], ["b"]]  # boş parça yok


def test_bol_keeps_subsection_together():
    info = {"grup": "alt_bolum"}
    keys = [f"{a}.{b}.{c}" for a in "AB" for b in (1, 2, 3) for c in (1, 2, 3, 4)]
    parts = P.bol({k: 1 for k in keys}, 4, lambda k: P.grup_anahtari(info, k))
    assert len(parts) == 4 and sorted(k for p in parts for k in p) == sorted(keys)
    owner = {k: i for i, p in enumerate(parts) for k in p}
    for k in keys:
        same = [x for x in keys if x.rsplit(".", 1)[0] == k.rsplit(".", 1)[0]]
        assert {owner[x] for x in same} == {owner[k]}, k   # A.1.x hep aynı parçada


def test_ayarlar_env_and_config_lower_the_cap(tmp_path, monkeypatch):
    monkeypatch.delenv(P.ENV_AZAMI, raising=False)
    assert P.ayarlar(tmp_path) == {"esik": 20, "adim": 40, "azami": 10}
    (tmp_path / "config.yaml").write_text("rapor:\n  paralel_azami: 4\n  paralel_esik: 10\n", encoding="utf-8")
    assert P.ayarlar(tmp_path) == {"esik": 10, "adim": 40, "azami": 4}
    monkeypatch.setenv(P.ENV_AZAMI, "3")
    assert P.ayarlar(tmp_path)["azami"] == 3
    assert P.ayarlar(tmp_path, azami=2)["azami"] == 2
    (tmp_path / "config.yaml").write_text("rapor:\n  paralel_azami: 50\n", encoding="utf-8")
    monkeypatch.delenv(P.ENV_AZAMI)
    assert P.ayarlar(tmp_path)["azami"] == 10        # 10'u aşamaz
    with pytest.raises(P.ParcaHatasi):
        P.ayarlar(tmp_path, azami=0)


def test_every_model_stage_declares_parallelism():
    st = {s["id"]: s for s in load_spec()["asamalar"]}
    for sid, s in st.items():
        if s["katman"] == "M":
            assert isinstance(s["paralel"]["bolunebilir"], bool) and s["paralel"]["gerekce"].strip(), sid
    assert {k for k, s in st.items() if (s.get("paralel") or {}).get("bolunebilir")} == {
        "transcribe", "describe", "karar_kaba", "karar_ince", "belirsiz_okuma", "ikinci_arama", "name", "write",
        "verify"}
    assert st["yonler"]["paralel"]["bolunebilir"] is False
    assert st["write"]["paralel"]["grup"] == "alt_bolum"


def test_unsplittable_stage_refuses(tmp_path):
    with pytest.raises(P.ParcaHatasi, match="bölünmez"):
        P.parcala(tmp_path, "yonler")
    with pytest.raises(P.ParcaHatasi, match="model aşaması değil"):
        P.parcala(tmp_path, "audit")


# -- hat üzerinde: decide paketleri -------------------------------------------------------------------

def _fine_ready(root):
    """Kaba aşamayı tek ajanla bitirir, ince paketleri hazırlar."""
    from bidr.decide.run import apply, prepare
    fake = FakeLLM()
    b = fake.backend()
    prepare(root, "coarse", backend=b)
    _answer_all(root / "work" / "coarse", fake)
    apply(root, "coarse", model="test-ajan", backend=b)
    prepare(root, "fine", backend=b)
    return fake, b


def _answer(d, fake, key):
    pkg = json.loads((d / f"{key}.json").read_text(encoding="utf-8"))
    (d / pkg["cikti_dosyasi"]).write_text(json.dumps(fake.answer(pkg["gorev"], pkg["istem"]), ensure_ascii=False),
                                          encoding="utf-8")


def _answer_all(d, fake):
    for p in sorted(d.glob("*.json")):
        if not p.name.endswith(".out.json"):
            _answer(d, fake, p.stem)


def _part_keys(root, part):
    """Parça ajanı taklidi: yalnız parça dosyasındaki paketleri okur."""
    lines = (root / part["dosya"]).read_text(encoding="utf-8").splitlines()
    return [ln.rsplit("/", 1)[-1][:-len(".json")] for ln in lines if ln and not ln.startswith("#")]


def test_parcala_writes_disjoint_lists(decide_ws):  # noqa: F811
    root, ids = decide_ws
    _fine_ready(root)
    man = P.parcala(root, "karar_ince", esik=1, adim=1)
    pend = P.bekleyen(root, "karar_ince")
    assert len(pend) == 4 and len(man["parcalar"]) == 4
    lists = [_part_keys(root, p) for p in man["parcalar"]]
    assert sorted(k for ks in lists for k in ks) == sorted(pend) and all(len(ks) == 1 for ks in lists)
    assert (root / "work/fine/_parca/parcalar.json").exists()
    # tavan: 2'ye düşer
    man = P.parcala(root, "karar_ince", esik=1, adim=1, azami=2)
    assert len(man["parcalar"]) == 2 and not (root / "work/fine/_parca/3.txt").exists()
    # _parca klasörü paket sayılmaz (prepare/apply/denetim etkilenmez)
    from bidr.decide.run import _pkg_paths
    assert len(_pkg_paths(root / "work" / "fine")) == 4


def test_out_of_list_and_overwrite_rejected(decide_ws):  # noqa: F811
    from bidr.decide.run import apply
    root, ids = decide_ws
    fake, b = _fine_ready(root)
    d = root / "work" / "fine"
    pre = ids["aynı"]
    _answer(d, fake, pre)                           # bölmeden önce cevaplanmış: listelere girmez
    good = (d / f"{pre}.out.json").read_bytes()
    man = P.parcala(root, "karar_ince", esik=1, adim=1)
    listed = {k for p in man["parcalar"] for k in p["paketler"]}
    assert pre not in listed and len(listed) == 3
    assert P.denetle(root, "karar_ince")["durum"] == "temiz"
    for p in man["parcalar"]:
        for k in _part_keys(root, p):
            _answer(d, fake, k)
    assert P.denetle(root, "karar_ince")["durum"] == "temiz"
    # bir parça ajanı listesi dışındaki cevabı ezer ve paketi olmayan bir cevap yazar
    (d / f"{pre}.out.json").write_text('{"karar": "kanit_degil", "gerekce": "ezildi", "eslesmeler": []}',
                                       encoding="utf-8")
    (d / "yabanci.out.json").write_text("{}", encoding="utf-8")
    r = P.denetle(root, "karar_ince", duzelt=False)
    assert r["durum"] == "ihlal" and {x["anahtar"] for x in r["ihlaller"]} == {pre, "yabanci"}
    assert (d / "yabanci.out.json").exists()        # --kuru dokunmaz
    # apply öncesi denetim: ezilen geri konur, liste dışı yazılan reddedilenlere taşınır
    assert P.apply_oncesi(root, "work/fine", log=lambda m: None) == 2
    assert (d / f"{pre}.out.json").read_bytes() == good and not (d / "yabanci.out.json").exists()
    assert len(list((d / "_parca" / "reddedilen").glob("*.out.json"))) == 2
    st = apply(root, "fine", model="test-ajan", backend=b)
    assert st["islenen"] == 4 and not st["gecersiz"]
    # paketler değişirse (yeniden prepare) bildirim eskir: tek ajanlı iş engellenmez
    (d / f"{pre}.json").write_text((d / f"{pre}.json").read_text(encoding="utf-8") + " ", encoding="utf-8")
    assert P.denetle(root, "karar_ince")["durum"] == "eski"


def _strip(o):
    """Zaman damgaları ve çalışma alanı yolu dışında karşılaştırma."""
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in ("zaman", "tarih_uretim", "olusturma", "uretildi", "calisma_alani")}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def test_parallel_split_gives_same_chain_and_od_as_single_agent(decide_ws, tmp_path):  # noqa: F811
    """Aynı cevaplar farklı parçalara (ve ters sırayla) dağıtılınca kararlar, faaliyet kayıtları ve
    audit-olcutler.json tek ajanlı koşuyla birebir aynı: zincir/OD modelsiz aşamalarda bütün kararlardan."""
    from bidr.audit.run import audit
    from bidr.decide.run import apply
    from bidr.faaliyet import run as F
    root, ids = decide_ws
    fake, b = _fine_ready(root)
    par = tmp_path / "paralel"
    shutil.copytree(root, par)
    # tek ajan
    _answer_all(root / "work" / "fine", fake)
    apply(root, "fine", model="test-ajan", backend=b)
    # paralel: 3 parça, her parça kendi listesini ters sırayla, parçalar da ters sırayla
    man = P.parcala(par, "karar_ince", parca=3)
    assert len(man["parcalar"]) == 3
    for p in reversed(man["parcalar"]):
        for k in reversed(_part_keys(par, p)):
            _answer(par / "work" / "fine", fake, k)
    assert P.denetle(par, "karar_ince")["durum"] == "temiz"
    apply(par, "fine", model="test-ajan", backend=b)
    for w in (root, par):
        F.run(w)
        audit(w)
    dec = lambda w: _strip({r["doc_id"]: r for r in read_jsonl(w / "decisions.jsonl")})
    assert dec(root) == dec(par)
    js = lambda w, n: _strip(json.loads((w / n).read_text(encoding="utf-8")))
    assert js(root, "faaliyetler.json") == js(par, "faaliyetler.json")
    assert js(root, "audit-olcutler.json") == js(par, "audit-olcutler.json")
    assert js(root, "audit-olcutler.json")["olcutler"]   # boş karşılaştırma değil


# -- yönetilen çalışma alanı: bidr next ve CLI ---------------------------------------------------------

def test_next_offers_split_and_cli_round_trip(tmp_path, capsys, monkeypatch):
    import yaml

    from bidr.cli import main
    from bidr.pipeline import evaluate

    from test_pipeline import _agent_answers
    monkeypatch.delenv(P.ENV_AZAMI, raising=False)
    src, ws, ans = _kurulum(tmp_path)
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert main(["ingest", str(src), "-w", str(ws), "--no-ocr", "--workers", "1"]) == 0
    assert main(["labels", "build", str(src), "-w", str(ws), "--unit", "Örnek"]) == 0
    assert main(["identify", "-w", str(ws), "--period", "2025"]) == 0
    assert main(["candidates", "-w", str(ws), "--profile", "akademik_bolum"]) == 0
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "coarse"]) == 0
    k = evaluate(ws).get("karar_kaba")
    assert k.kim == "ajan" and len(k.bekleyen) == 4
    assert k.paralel["bolunebilir"] and k.paralel["parca_sayisi"] == 1      # 4 paket ≤ eşik 20
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    assert "Paralel: gerekmez" in capsys.readouterr().out
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    cfg.setdefault("rapor", {}).update(paralel_esik=1, paralel_adim=1)
    (ws / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert evaluate(ws).get("karar_kaba").paralel["parca_sayisi"] == 4
    monkeypatch.setenv(P.ENV_AZAMI, "2")
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    out = capsys.readouterr().out
    assert "Paralel: bu aşama 2 ajanla" in out and "parcala" in out and "parca-denetle" in out
    main(["next", "-w", str(ws), "--json"])
    j = json.loads(capsys.readouterr().out)
    assert j["sonraki"]["paralel"]["parca_sayisi"] == 2 and "bekleyen" not in j["sonraki"]
    assert main(["parcala", "-w", str(ws)]) == 0                 # aşama verilmezse sıradaki
    assert "2 ayrık parçaya" in capsys.readouterr().out
    assert sorted(p.name for p in (ws / "work/coarse/_parca").glob("*.txt")) == ["1.txt", "2.txt"]
    _agent_answers(ws, "coarse")
    assert main(["parca-denetle", "-w", str(ws), "karar_kaba"]) == 0
    (ws / "work/coarse/yabanci.out.json").write_text("{}", encoding="utf-8")
    assert main(["parca-denetle", "-w", str(ws), "karar_kaba", "--kuru"]) == 1
    capsys.readouterr()
    assert main(["decide", "apply", "-w", str(ws), "--stage", "coarse", "--model", "test-ajan"]) == 0
    assert "parça denetimi" in capsys.readouterr().err and not (ws / "work/coarse/yabanci.out.json").exists()
    assert evaluate(ws).get("karar_kaba").durum == "bitti"
    assert main(["parcala", "-w", str(ws), "yonler"]) == 2       # bölünmez aşama


def _kurulum(tmp_path):
    """test_pipeline'ın `kurulum` fikstürünün gövdesi (sentetik kaynak + answers.yaml)."""
    import test_pipeline
    return test_pipeline.kurulum.__wrapped__(tmp_path)
