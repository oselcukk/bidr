"""Aşama sözleşmeleri, `bidr init`, `bidr status/next`, kapılar ve hakem cevapları.

Sentetik kaynak klasörle gerçek CLI zinciri: init → ingest → labels → identify →
candidates → decide (ajan modu, cevapları ajan taklidi yazar) → compare-labels → hakem.
Model/sağlayıcı çağrılmaz.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from bidr.cli import main
from bidr.common import read_jsonl
from bidr.pipeline import evaluate, load_spec
from bidr.pipeline.gate import GATE_EXIT

from test_decide import DOCS, FakeLLM

FAKE = FakeLLM()


def _durum(ws) -> dict[str, str]:
    return {s.id: s.durum for s in evaluate(ws).asamalar}


def _kim(ws, sid) -> str | None:
    return evaluate(ws).get(sid).kim


@pytest.fixture
def kurulum(tmp_path):
    src = tmp_path / "kaynak"
    files = {
        "Kanıtlar/B.1.1/[B.1.1-1-OD3] Kurul Kararı.txt": DOCS["aynı"] + "\nhttps://abl.ornek.edu.tr/kararlar/2025-1 1/1",
        "Kanıtlar/B.1.1/[B.1.1-2-OD3] Toplantı.txt": DOCS["uydurma"],
        "Kanıtlar/A.1.2/[A.1.2-1-OD3] Tutanak.txt": DOCS["ekle"],
        "Diğer/menü.txt": DOCS["degil"],
    }
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text + "\n" + "Bu belge sentetik bir sınama belgesidir. " * 5, encoding="utf-8")
    ws = tmp_path / "ws"
    ans = tmp_path / "answers.yaml"
    ans.write_text(yaml.safe_dump({"kaynak": str(src), "birim": "Örnek Bölümü", "profil": "akademik_bolum",
                                   "donem": 2025, "kurum": None, "gecmis_etiket": True,
                                   "etiket_birim": "Örnek", "ajan": "test-ajan"}, allow_unicode=True),
                   encoding="utf-8")
    return src, ws, ans


def _agent_answers(ws: Path, stage: str, broken: set[str] = frozenset()) -> int:
    d = ws / "work" / stage
    n = 0
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".out.json"):
            continue
        out = d / f"{p.stem}.out.json"
        if out.exists() and p.stem not in broken:
            continue
        pkg = json.loads(p.read_text(encoding="utf-8"))
        ans = FAKE.answer(pkg["gorev"], pkg["istem"])
        out.write_text("{bozuk" if p.stem in broken else json.dumps(ans, ensure_ascii=False), encoding="utf-8")
        n += 1
    return n


def test_spec_is_consistent():
    spec = load_spec()
    ids = [s["id"] for s in spec["asamalar"]]
    assert ids[:2] == ["kurulum", "ingest"] and ids[-5:] == ["denetle", "kanit_maskele", "teslim", "kor_denetim", "duzelt"]
    for s in spec["asamalar"]:
        if s["uygulandi"]:
            assert s["komut"] and s["skill"], s["id"]
        else:
            assert s["sart"]["denetim"] == "yok"
    assert not [s["id"] for s in spec["asamalar"] if not s["uygulandi"]]
    by = {s["id"]: s for s in spec["asamalar"]}
    assert by["file"]["onkosul"] == ["audit", "ikinci_arama"] and by["write"]["onkosul"] == ["file"]
    assert by["verify"]["onkosul"] == ["write"] and by["yonler"]["onkosul"] == ["verify"]
    assert by["render"]["onkosul"] == ["yonler"] and by["denetle"]["onkosul"] == ["render"]
    assert "name" in by["audit"]["onkosul"] and by["name"]["istege_bagli"]
    assert by["faaliyet"]["onkosul"] == ["karar_ince", "belirsiz_okuma"] and "faaliyet" in by["audit"]["onkosul"]
    # belirsiz_okuma: koşullu (isteğe bağlı değil), ince karardan hemen sonra; kararı okuyan aşamalar onu bekler
    assert by["belirsiz_okuma"]["onkosul"] == ["karar_ince"] and not by["belirsiz_okuma"].get("istege_bagli")
    assert ids.index("belirsiz_okuma") == ids.index("karar_ince") + 1
    for sid in ("hakem", "name", "faaliyet", "audit"):
        assert "belirsiz_okuma" in by[sid]["onkosul"], sid
    assert by["ikinci_arama"]["onkosul"] == ["audit"] and by["ikinci_arama"]["istege_bagli"]
    assert ids.index("karar_ince") < ids.index("faaliyet") < ids.index("audit") < ids.index("ikinci_arama") \
        < ids.index("file") and ids.index("render") < ids.index("denetle")
    for sid in ("file", "write", "verify", "render", "name", "faaliyet", "ikinci_arama", "denetle"):
        assert by[sid]["sart"]["denetim"] == f"{sid}_tamam"


def test_full_pipeline_transitions_and_gates(kurulum, capsys):
    src, ws, ans = kurulum
    # 0. kurulmamış: yalnız kurulum bekler, gerisi engelli; kapı yok (yönetilmeyen WS)
    d = _durum(ws)
    assert d["kurulum"] == "bekliyor" and d["ingest"] == "engelli" and d["audit"] == "engelli"
    assert d["transcribe"] == "engelli" and d["file"] == "engelli" and d["render"] == "engelli"
    assert _kim(ws, "kurulum") == "insan"
    assert not ws.exists()  # status hiçbir şey yazmaz

    # 1. init
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert (ws / "AGENTS.md").read_text(encoding="utf-8").startswith("<!-- bidr:yonetilen")
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    assert (ws / ".claude" / "skills" / "bidr-rapor" / "SKILL.md").exists()
    d = _durum(ws)
    assert d["kurulum"] == "bitti" and d["ingest"] == "bekliyor" and d["identify"] == "engelli"

    # kapı: ingest bitmeden identify; yanlış kaynakla ingest
    capsys.readouterr()
    assert main(["identify", "-w", str(ws)]) == GATE_EXIT
    assert "önce bitmeli" in capsys.readouterr().err
    assert not (ws / "documents.jsonl").exists()
    other = src.parent / "baska"
    other.mkdir()
    assert main(["ingest", str(other), "-w", str(ws), "--no-ocr"]) == GATE_EXIT

    # 2. ingest
    assert main(["ingest", str(src), "-w", str(ws), "--no-ocr", "--workers", "1"]) == 0
    d = _durum(ws)
    assert d["ingest"] == "bitti" and d["identify"] == "bekliyor" and d["etiketler"] == "bekliyor"
    assert d["transcribe"] == "atlandi"        # düşük kaliteli görsel/PDF yok
    # kaynağa yeni dosya → ingest yeniden bekler, identify engellenir
    extra = src / "Diğer" / "yeni.txt"
    extra.write_text("yeni belge " * 20, encoding="utf-8")
    d = _durum(ws)
    assert d["ingest"] == "bekliyor" and d["identify"] == "engelli"
    assert "1 yeni" in evaluate(ws).get("ingest").neden
    extra.unlink()
    assert _durum(ws)["ingest"] == "bitti"

    # 3. etiketler, identify, candidates
    assert main(["labels", "build", str(src), "-w", str(ws), "--unit", "Örnek"]) == 0
    assert main(["identify", "-w", str(ws), "--period", "2025"]) == 0
    assert _durum(ws)["candidates"] == "bekliyor"
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "coarse"]) == GATE_EXIT
    assert main(["candidates", "-w", str(ws), "--profile", "akademik_bolum"]) == 0
    d = _durum(ws)
    assert [d[k] for k in ("etiketler", "identify", "candidates", "karar_kaba", "karar_ince", "hakem")] == \
        ["bitti", "bitti", "bitti", "bekliyor", "engelli", "engelli"]
    k = evaluate(ws).get("karar_kaba")
    assert k.kim == "komut" and "decide prepare" in k.komutlar[0] and "--stage coarse" in k.komutlar[0]

    # kapı: kaba bitmeden ince ve hakem
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "fine"]) == GATE_EXIT
    assert main(["compare-labels", "-w", str(ws)]) == GATE_EXIT
    assert not (ws / "work" / "fine").exists()

    # 4. kaba: prepare → ajan → apply (biri geçersiz) → düzelt → apply
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "coarse"]) == 0
    k = evaluate(ws).get("karar_kaba")
    assert k.durum == "bekliyor" and k.kim == "ajan" and k.ilerleme["cevapsiz"] == 4
    assert any("decide apply" in c and "test-ajan" in c for c in k.komutlar)
    ids = sorted(p.stem for p in (ws / "work" / "coarse").glob("*.json") if not p.name.endswith(".out.json"))
    _agent_answers(ws, "coarse", broken={ids[0]})
    k = evaluate(ws).get("karar_kaba")
    assert k.kim == "komut" and "decide apply" in k.komutlar[0]
    assert main(["decide", "apply", "-w", str(ws), "--stage", "coarse", "--model", "test-ajan"]) == 1
    k = evaluate(ws).get("karar_kaba")
    assert k.durum == "bekliyor" and k.kim == "ajan" and k.ilerleme["gecersiz"] == 1
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "fine"]) == GATE_EXIT
    # geçersiz cevap kenara alındı (bidr/pipeline/cevap.py): paket yeniden cevapsız, ajan üstüne yazmaz
    assert not (ws / "work" / "coarse" / f"{ids[0]}.out.json").exists()
    assert (ws / "work" / "coarse" / f"{ids[0]}.out.json.red1.eski").exists()
    assert k.bekleyen == [ids[0]]
    _agent_answers(ws, "coarse")
    assert main(["decide", "apply", "-w", str(ws), "--stage", "coarse", "--model", "test-ajan"]) == 0
    d = _durum(ws)
    assert d["karar_kaba"] == "bitti" and d["karar_ince"] == "bekliyor"

    # 5. ince
    assert main(["decide", "prepare", "-w", str(ws), "--stage", "fine"]) == 0
    assert _kim(ws, "karar_ince") == "ajan"
    _agent_answers(ws, "fine")
    assert main(["decide", "apply", "-w", str(ws), "--stage", "fine", "--model", "test-ajan"]) == 0
    st = evaluate(ws).get("karar_ince")
    assert st.durum == "bitti"
    assert any("reddedildi" in u for u in st.uyarilar)       # uydurma alıntı: uyarı, engel değil

    # 6. hakem: kuyruk → insan → cevaplar → uzlaşı
    h = evaluate(ws).get("hakem")
    assert h.durum == "bekliyor" and h.kim == "komut" and "compare-labels" in h.komutlar[0]
    assert main(["compare-labels", "-w", str(ws)]) == 0
    h = evaluate(ws).get("hakem")
    qs = list(read_jsonl(ws / "label-review.jsonl"))
    assert qs and h.kim == "insan" and h.ilerleme == {"soru": len(qs), "cevapli": 0}
    # next: insan onayı gerekli, skill bidr-hakem
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    out = capsys.readouterr().out
    assert "KULLANICI gerekli" in out and "GEREKLİ" in out and "bidr-hakem" in out
    # geçersiz cevap kodca reddedilir
    assert main(["hakem", "cevap", "-w", str(ws), qs[0]["soru_id"], "evet"]) == 2
    assert main(["hakem", "cevap", "-w", str(ws), "yok:A.1.1:ekliyor", "ekle"]) == 2
    for q in qs:
        assert main(["hakem", "cevap", "-w", str(ws), q["soru_id"], q["secenekler"][0],
                     "--not", "sınama"]) == 0
    h = evaluate(ws).get("hakem")
    assert h.kim == "komut" and h.komutlar[0].endswith("--apply")
    assert main(["compare-labels", "-w", str(ws), "--apply"]) == 0
    rep = evaluate(ws)
    assert rep.get("hakem").durum == "bitti"
    # faaliyet kayıtları (karar_ince'den sonra, audit'ten önce): kapı + güncellik
    assert rep.sonraki.id == "faaliyet" and rep.sonraki.kim == "komut" and rep.get("audit").durum == "engelli"
    assert main(["audit", "-w", str(ws)]) == GATE_EXIT
    assert main(["faaliyet", "-w", str(ws)]) == 0
    rep = evaluate(ws)
    assert rep.get("faaliyet").durum == "bitti" and (ws / "faaliyetler.json").exists()
    assert rep.sonraki.id == "audit" and rep.sonraki.durum == "bekliyor" and rep.sonraki.kim == "komut"
    # 7. audit: tablo → insan kararı → apply (ayrıntı: tests/test_audit.py)
    assert main(["audit", "-w", str(ws)]) == 0
    a = evaluate(ws).get("audit")
    assert a.kim == "insan" and a.ilerleme["kararli"] == 0 and a.ilerleme["satir"] > 0
    from openpyxl import load_workbook
    wb = load_workbook(ws / "review.xlsx")
    sh = wb["Eşleşmeler"]
    col = [c.value for c in sh[1]].index("KARAR (kabul/ret/duzelt)") + 1
    for r in range(2, sh.max_row + 1):
        sh.cell(row=r, column=col, value="kabul")
    wb.save(ws / "review.xlsx")
    assert evaluate(ws).get("audit").kim == "komut"       # kararlar var, işlenmemiş
    assert main(["audit", "apply", "-w", str(ws)]) == 0
    rep = evaluate(ws)
    assert rep.get("audit").durum == "bitti" and rep.get("name").durum == "bitti"   # ince karar adları
    # ikinci arama (isteğe bağlı): yapılmadıysa bekler; file kapısı kapalı
    ia = rep.get("ikinci_arama")
    assert rep.sonraki.id == "ikinci_arama" and ia.kim == "komut" and "arama prepare" in ia.komutlar[0]
    assert "ikinci_arama: false" in ia.neden
    assert main(["file", "-w", str(ws)]) == GATE_EXIT
    _ikinci_arama(ws)
    rep = evaluate(ws)
    assert rep.sonraki.id == "file" and rep.sonraki.kim == "komut"
    _report_layer(ws, capsys)

    # kararlar yenilenirse (ör. yeni apply) hakem kuyruğu eskir; yalnız dosyanın yeniden yazılması
    # (içerik aynı, ör. ikinci arama apply'ı) eskitmez
    import os
    t = (ws / "label-review.jsonl").stat().st_mtime_ns
    os.utime(ws / "decisions.jsonl", ns=(t + 10**9, t + 10**9))
    assert evaluate(ws).get("hakem").durum == "bitti"
    recs = list(read_jsonl(ws / "decisions.jsonl"))
    for r in recs:
        for m in r.get("eslesmeler") or []:
            m["kabul"] = False
    (ws / "decisions.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                        encoding="utf-8")
    os.utime(ws / "decisions.jsonl", ns=(t + 10**9, t + 10**9))
    assert evaluate(ws).get("hakem").durum == "bekliyor"

    # kaynak salt okunur: hiçbir dosyası değişmedi, içine bir şey yazılmadı
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()) == sorted(  # noqa: E501
        ["Kanıtlar/B.1.1/[B.1.1-1-OD3] Kurul Kararı.txt", "Kanıtlar/B.1.1/[B.1.1-2-OD3] Toplantı.txt",
         "Kanıtlar/A.1.2/[A.1.2-1-OD3] Tutanak.txt", "Diğer/menü.txt"])


def _rapor_config(ws: Path, **kw) -> None:
    """config.yaml `rapor:` bölümü (kullanıcının yazdığı; `bidr init` korur)."""
    data = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    data.setdefault("rapor", {}).update(kw)
    (ws / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _write_answers(ws: Path, index: dict) -> list[str]:
    """Ajan taklidi: her yazım paketine kanıtın atfıyla kısa bir metin."""
    done = []
    for p in sorted((ws / "work" / "write").glob("*.json")):
        if p.name.endswith(".out.json") or p.stem == "kaynaklar" or (ws / "work" / "write" / f"{p.stem}.out.json").exists():
            continue
        no = index[p.stem][0]["kanit_no"]
        out = {"paragraflar": [{"metin": f"Bölümümüzde ilgili karar alınmıştır [{no}]."}], "onceki_yila_gore": ""}
        (p.parent / f"{p.stem}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        done.append(p.stem)
    return done


def _verify_answers(ws: Path, reject: set[str] = frozenset()) -> None:
    """Ajan taklidi (bağımsız doğrulayıcı): `reject`teki ölçütlerin ilk cümlesi desteklenmiyor."""
    d = ws / "work" / "verify"
    for p in sorted(d.glob("*.json")):
        if p.name.endswith(".out.json") or (d / f"{p.stem}.out.json").exists():
            continue
        cs = json.loads(p.read_text(encoding="utf-8"))["meta"]["cumleler"]
        out = {"cumleler": [{"yer": c["yer"], "karar": "desteklenmiyor" if p.stem in reject and i == 0
                             else "destekleniyor", "gerekce": "alıntı kararı göstermiyor" if p.stem in reject
                             and i == 0 else "alıntıda var"} for i, c in enumerate(cs)],
               "sorular": [{"soru": k, "durum": "cevapsiz", "yerler": [], "gerekce": "kanıt yok"}
                           for k in ("surec", "izleme", "iyilestirme", "kanitlar", "onceki_yil")],
               "genel": ""}
        (d / f"{p.stem}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")


def _yonler_answers(ws: Path, fiil: str = "ilgili karar alınmıştır") -> list[str]:
    """Ajan taklidi (alan maddeleri): güçlü yön doğrulanmış metinden, gelişme bulgudan; ölçüt kodlu."""
    d = ws / "work" / "yonler"
    done = []
    for p in sorted(d.glob("?.json")):
        if (d / f"{p.stem}.out.json").exists():
            continue
        m = json.loads(p.read_text(encoding="utf-8"))["meta"]
        out = {"guclu": [{"metin": f"Bölümümüzde {fiil} ({c})."} for c in m["guclu_olcutler"][:1]],
               "gelisme": [{"metin": f"Ölçüte ilişkin izleme kanıtı bulunmamaktadır ({c})."}
                           for c in m["gelisme_olcutler"][:1]]}
        (d / f"{p.stem}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        done.append(p.stem)
    return done


def _verify_yonler_answers(ws: Path, reject: set[str] = frozenset()) -> list[str]:
    d = ws / "work" / "verify" / "yonler"
    done = []
    for p in sorted(d.glob("?.json")):
        if (d / f"{p.stem}.out.json").exists():
            continue
        ms = json.loads(p.read_text(encoding="utf-8"))["meta"]["maddeler"]
        out = {"maddeler": [{"yer": x["yer"], "karar": "desteklenmiyor" if p.stem in reject and i == 0
                             else "destekleniyor", "gerekce": "metinde yok" if p.stem in reject and i == 0
                             else "metinde var"} for i, x in enumerate(ms)], "genel": ""}
        (d / f"{p.stem}.out.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        done.append(p.stem)
    return done


def _ikinci_arama(ws: Path) -> None:
    """prepare → ajan (uymuyor) → apply; decisions.jsonl değişirse audit yeniden; sonra bitti.
    Atlama kullanıcının kararıdır: config.yaml rapor.ikinci_arama: false → atlandi (status'ta görünür)."""
    ev = lambda sid: evaluate(ws).get(sid)          # noqa: E731
    _rapor_config(ws, ikinci_arama=False)
    ia = ev("ikinci_arama")
    assert ia.durum == "atlandi" and "rapor.ikinci_arama: false" in ia.neden
    data = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    del data["rapor"]["ikinci_arama"]
    (ws / "config.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert main(["arama", "prepare", "-w", str(ws), "--profile", "akademik_bolum", "--olcut", "A.1.1,B.2.1"]) == 0
    d = ws / "work" / "ikinci_arama"
    pkgs = sorted(p for p in d.glob("*.json") if not p.name.endswith(".out.json"))
    assert pkgs
    ia = ev("ikinci_arama")
    assert ia.kim == "ajan" and ia.ilerleme["cevapsiz"] == len(pkgs) and "arama apply" in ia.komutlar[1]
    for p in pkgs:
        (d / f"{p.stem}.out.json").write_text(json.dumps(
            {"karar": "olcut_yok", "gerekce": "uymuyor", "birim_iliskisi": "kendi", "eslesmeler": [],
             "kanit_adi": "Sınama Belgesi"}, ensure_ascii=False), encoding="utf-8")
    assert ev("ikinci_arama").kim == "komut"
    assert main(["arama", "apply", "-w", str(ws), "--model", "test-ajan"]) == 0
    # decisions.jsonl değişti (ikinci arama kaydı): audit tablosu eskir, ikinci arama engellenir
    assert ev("audit").durum == "bekliyor" and ev("ikinci_arama").durum == "engelli"
    assert main(["audit", "-w", str(ws)]) == 0
    a = ev("audit")
    if a.kim == "komut":
        assert main(["audit", "apply", "-w", str(ws)]) == 0
    assert ev("audit").durum == "bitti"
    ia = ev("ikinci_arama")
    assert ia.durum == "bitti" and ia.ilerleme["paket"] == len(pkgs)


def _report_layer(ws: Path, capsys) -> None:
    """audit'ten sonra: file → write → verify (ret → yeniden yazım → sınır → insan) → render."""
    import csv
    from bidr.write.sources import load_index

    from test_render import make_template
    ev = lambda sid: evaluate(ws).get(sid)          # noqa: E731
    # kapılar: file bitmeden write, verify bitmeden render
    assert main(["write", "prepare", "-w", str(ws)]) == GATE_EXIT
    assert main(["render", "-w", str(ws), "--sablon", str(ws / "yok.docx")]) == GATE_EXIT
    assert ev("write").durum == "engelli" and ev("render").durum == "engelli"

    # file: bağlantı — belge metnindeki yayın adresi; kök yoksa öteki kanıt bağlantısız. Bu bölüm bağlantı
    # modunu sınar (config.yaml rapor.teslim: baglanti; varsayılan dekanlik'te bağlantısızlık uyarı değildir)
    _rapor_config(ws, teslim="baglanti")
    assert main(["file", "-w", str(ws)]) == 0
    f = ev("file")
    assert f.durum == "bitti" and any("bağlantısı yok" in u for u in f.uyarilar)
    rows = list(csv.DictReader(open(ws / "evidence-index.csv", encoding="utf-8")))
    by = {r["olcut"]: r for r in rows}
    assert by["B.1.1"]["baglanti"] == "https://abl.ornek.edu.tr/kararlar/2025-1"
    assert by["B.1.1"]["baglanti_kaynagi"] == "belge_metni" and by["B.2.3"]["baglanti"] == ""
    assert "Bağlantısı olmayan kanıtlar" in (ws / "gaps.md").read_text(encoding="utf-8")
    # kök bağlantı girilince dosyalama eskir; yeniden: klasör yolu bağlantısı
    _rapor_config(ws, kanit_kok_baglanti="https://kanit.ornek.edu.tr/2025/", yeniden_yazim_siniri=1)
    assert ev("file").durum == "bekliyor" and ev("file").kim == "komut"
    assert main(["file", "-w", str(ws)]) == 0
    rows = {r["olcut"]: r for r in csv.DictReader(open(ws / "evidence-index.csv", encoding="utf-8"))}
    assert rows["B.2.3"]["baglanti_kaynagi"] == "klasor"
    assert rows["B.2.3"]["baglanti"].startswith("https://kanit.ornek.edu.tr/2025/B/B.2/B.2.3/%5B1-OD")
    assert ev("file").durum == "bitti" and not ev("file").uyarilar
    gaps = (ws / "gaps.md").read_text(encoding="utf-8")
    assert "Bütün kanıtların bağlantısı var" in gaps and "Eksik kanıt raporu" in gaps
    assert main(["audit", "-w", str(ws)]) == 0                       # audit yeniden: bölüm korunur
    assert "Bütün kanıtların bağlantısı var" in (ws / "gaps.md").read_text(encoding="utf-8")
    assert ev("audit").durum == "bitti" and ev("file").durum == "bitti"

    # write: prepare → ajan → apply
    w = ev("write")
    assert w.kim == "komut" and "write prepare" in w.komutlar[0]
    assert main(["write", "prepare", "-w", str(ws)]) == 0
    assert ev("write").kim == "ajan"
    index = load_index(ws / "evidence-index.csv")
    assert sorted(_write_answers(ws, index)) == ["B.1.1", "B.2.3"]
    assert ev("write").kim == "komut"
    assert main(["write", "apply", "-w", str(ws), "--model", "test-ajan"]) == 0
    assert ev("write").durum == "bitti"

    # verify: kod + ajan; B.1.1 reddedilir
    assert ev("verify").kim == "komut"
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    v = ev("verify")
    assert v.kim == "ajan" and "taze" in v.komutlar[0]
    _verify_answers(ws, reject={"B.1.1"})
    assert main(["verify", "apply", "-w", str(ws), "--model", "test-dogrulayici"]) == 1
    v = ev("verify")
    assert v.kim == "komut" and v.komutlar[0].endswith("write prepare -w " + str(ws) + " --reddedilenler")
    assert "tur 1/1" in v.neden and "taze" in v.neden

    # yeniden yazım turu 1: paket doğrulayıcının cümle gerekçesini taşır
    assert main(["write", "prepare", "-w", str(ws), "--reddedilenler"]) == 0
    pkg = json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))
    assert pkg["meta"]["tur"] == 1 and "DOĞRULAMADA REDDEDİLDİ" in pkg["istem"]
    assert "p1.1 (desteklenmiyor)" in pkg["istem"] and "alıntı kararı göstermiyor" in pkg["istem"]
    w = ev("write")
    assert w.durum == "bekliyor" and w.kim == "ajan" and "B.1.1 tur 1" in w.neden
    assert ev("verify").durum == "engelli"
    assert main(["write", "prepare", "-w", str(ws)]) == 0              # normal prepare turu bozmaz
    assert json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["meta"]["tur"] == 1
    _write_answers(ws, index)
    assert main(["write", "apply", "-w", str(ws), "--model", "test-ajan-2"]) == 0
    t = json.loads((ws / "texts/B.1.1.json").read_text(encoding="utf-8"))
    assert t["tur"] == 1 and t["durum"] == "taslak" and t["onceki_ret"]
    assert ev("write").durum == "bitti" and ev("verify").kim == "komut"
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    _verify_answers(ws, reject={"B.1.1"})
    assert main(["verify", "apply", "-w", str(ws), "--model", "test-dogrulayici-2"]) == 1
    # sınır (1) doldu: insan gerekli
    v = ev("verify")
    assert v.kim == "insan" and "insan gerekli" in v.neden and "B.1.1" in v.neden
    assert main(["write", "prepare", "-w", str(ws), "--reddedilenler"]) == 0
    assert json.loads((ws / "work/write/B.1.1.json").read_text(encoding="utf-8"))["meta"]["tur"] == 1
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    out = capsys.readouterr().out
    assert "KULLANICI gerekli" in out and "verify karar" in out
    # kullanıcı: bir tur daha → yeniden komut; sonra rapordan çıkar
    assert main(["verify", "karar", "-w", str(ws), "B.1.1", "tekrar", "--not", "sınama"]) == 0
    assert ev("verify").kim == "komut" and "tur 2/2" in ev("verify").neden
    assert main(["verify", "karar", "-w", str(ws), "B.1.2", "cikar"]) == 2
    assert main(["verify", "karar", "-w", str(ws), "B.1.1", "cikar"]) == 0
    v = ev("verify")
    assert v.durum == "bitti" and any("rapora alınmayacak" in u for u in v.uyarilar)

    # yonler: alan maddeleri → bağımsız doğrulama verify akışında → ret → yeniden yazım → render
    assert ev("render").durum == "engelli"
    y = ev("yonler")
    assert y.kim == "komut" and "yonler prepare" in y.komutlar[0]
    assert main(["yonler", "prepare", "-w", str(ws)]) == 0
    assert ev("yonler").kim == "ajan"
    pk = json.loads((ws / "work/yonler/B.json").read_text(encoding="utf-8"))["meta"]
    assert pk["guclu_olcutler"] == ["B.2.3"]               # B.1.1 kullanıcı kararıyla çıkarıldı
    assert "B.1.1" in pk["gelisme_olcutler"]
    assert sorted(_yonler_answers(ws)) == ["A", "B", "C", "D"]
    assert ev("yonler").kim == "komut"
    assert main(["yonler", "apply", "-w", str(ws), "--model", "test-ajan"]) == 0
    # alan doğrulaması verify komutlarıyla yapılır ama verify aşamasını bekletmez: yonler alan başına
    # izler, kapısı açık kalır (bir alanın düzeltmesi ötekilerin doğrulaması bitmeden uygulanabilir)
    assert ev("verify").durum == "bitti"
    y = ev("yonler")
    assert y.kim == "komut" and any(k.endswith("verify prepare -w " + str(ws)) for k in y.komutlar)
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    y = ev("yonler")
    assert y.kim == "ajan" and any("verify/yonler" in k for k in y.komutlar) and "doğrulama paketi" in y.neden
    from bidr.pipeline.gate import check_gate
    assert check_gate(ws, "yonler") is None                    # doğrulama bekliyorken yonler apply açık
    assert _verify_yonler_answers(ws, reject={"B"})
    assert main(["verify", "apply", "-w", str(ws), "--model", "test-dogrulayici"]) == 1
    assert ev("verify").durum == "bitti"
    y = ev("yonler")
    assert y.kim == "komut" and y.komutlar[0].endswith("yonler prepare -w " + str(ws) + " --reddedilenler")
    assert main(["yonler", "prepare", "-w", str(ws), "--reddedilenler"]) == 0
    pkg = json.loads((ws / "work/yonler/B.json").read_text(encoding="utf-8"))
    assert pkg["meta"]["tur"] == 1 and "g1 (desteklenmiyor)" in pkg["istem"]
    assert _yonler_answers(ws, "ilgili kurul kararı alınmıştır") == ["B"]
    assert main(["yonler", "apply", "-w", str(ws), "--model", "test-ajan-2"]) == 0
    assert main(["verify", "prepare", "-w", str(ws)]) == 0
    _verify_yonler_answers(ws)
    assert main(["verify", "apply", "-w", str(ws), "--model", "test-dogrulayici-2"]) == 0
    assert ev("verify").durum == "bitti" and ev("yonler").durum == "bitti"

    # render: şablon yoksa kullanıcıdan alınır; sonra rapor, bağlantılı kanıt adları
    r = ev("render")
    assert r.kim == "insan" and "şablon" in r.neden
    make_template(ws.parent / "sablon.docx", ids=(("B.1.1", "Programların tasarımı"), ("B.2.3", "Öğrenci iş yükü")))
    _rapor_config(ws, sablon=str(ws.parent / "sablon.docx"))
    assert ev("render").kim == "komut"
    assert main(["render", "-w", str(ws)]) == 0
    r = ev("render")
    assert r.durum == "bitti" and not any("TASLAK" in u for u in r.uyarilar)
    import zipfile
    with zipfile.ZipFile(ws / "report.docx") as z:
        rels = z.read("word/_rels/document.xml.rels").decode()
        body = z.read("word/document.xml").decode()
    assert "https://abl.ornek.edu.tr/kararlar/2025-1" not in rels        # B.1.1 çıkarıldı
    assert "https://kanit.ornek.edu.tr/2025/B/B.2/B.2.3/" in rels and "<w:hyperlink" in body
    assert "[komisyon]" not in body
    # denetle: biçim denetimi (sentetik şablonda 2 blok: kritik bulgu → yayıma hazır değil)
    dn = ev("denetle")
    assert dn.kim == "komut" and "denetle" in dn.komutlar[0] and "denetim.json yok" in dn.neden
    assert main(["denetle", "-w", str(ws)]) == 1
    js = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))
    assert js["docx_sha"] and js["ozet"]["kritik"] > 0
    dn = ev("denetle")
    assert dn.durum == "bekliyor" and dn.kim == "insan" and "yayıma hazır değil" in dn.neden
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    out = capsys.readouterr().out
    assert "denetle" in out and "yayıma hazır değil" in out and "KULLANICI gerekli" in out
    # rapor yeniden üretilince denetim eskir (farklı kanıt gösterimiyle: aynı saniyede aynı girdiyle
    # üretilen docx bayt bayt aynı olabilir, o zaman denetim gerçekten günceldir)
    from bidr.check.run import file_sha
    sha0 = json.loads((ws / "denetim.json").read_text(encoding="utf-8"))["docx_sha"]
    assert main(["render", "-w", str(ws), "--kanit-bicimi", "kilavuz"]) == 0
    if file_sha(ws / "report.docx") != sha0:
        assert ev("denetle").kim == "komut" and "güncel" in ev("denetle").neden
    else:   # aynı saniyede bayt bayt aynı docx: denetim gerçekten güncel (zamanlamaya bağlı düşüş olmasın)
        assert ev("denetle").kim == "insan"
    # metin değişirse rapor eskir
    t = json.loads((ws / "texts/B.2.3.json").read_text(encoding="utf-8"))
    t["eksikler"] = ["değişti"]
    (ws / "texts/B.2.3.json").write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    assert ev("render").durum == "bekliyor"


def test_status_and_next_json(kurulum, capsys):
    src, ws, ans = kurulum
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    capsys.readouterr()
    assert main(["status", "-w", str(ws), "--json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert rep["yonetilen"] and rep["sonraki"]["id"] == "ingest"
    assert str(src.resolve()) in rep["sonraki"]["komutlar"][0]
    assert main(["next", "-w", str(ws), "--json"]) == 0
    n = json.loads(capsys.readouterr().out)["sonraki"]
    assert n["id"] == "ingest" and n["kim"] == "komut" and "ingest" in n["komutlar"][0] and n["sart"]
    assert main(["status", "-w", str(ws), "--kisa"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 3


def test_skipped_labels_skip_hakem(kurulum):
    src, ws, ans = kurulum
    a = yaml.safe_load(ans.read_text(encoding="utf-8"))
    a["gecmis_etiket"] = False
    ans.write_text(yaml.safe_dump(a, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    d = _durum(ws)
    assert d["etiketler"] == "atlandi"
    assert main(["labels", "build", str(src), "-w", str(ws)]) == 0   # önkoşulu (kurulum) tamam


# -- init -----------------------------------------------------------------------------------

def _answers(tmp_path, **kw):
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    a = {"kaynak": str(src), "birim": "B", "profil": "akademik_bolum", "donem": 2025, **kw}
    p = tmp_path / "a.yaml"
    p.write_text(yaml.safe_dump(a, allow_unicode=True), encoding="utf-8")
    return p


@pytest.mark.parametrize("kw,msg", [
    ({"profil": "yok_boyle"}, "bilinmeyen profil"),
    ({"kurum": "yok_boyle"}, "bilinmeyen kurum"),
    ({"donem": 1890}, "dönem"),
    ({"api_key": "x"}, "bilinmeyen alan"),
    ({"birim": None}, "`birim` gerekli"),
])
def test_init_rejects_bad_answers(tmp_path, capsys, kw, msg):
    p = _answers(tmp_path, **kw)
    assert main(["init", "-w", str(tmp_path / "ws"), "--answers", str(p)]) == 2
    assert msg in capsys.readouterr().err
    assert not (tmp_path / "ws" / "config.yaml").exists()


def test_init_workspace_inside_source_or_repo(tmp_path, capsys):
    p = _answers(tmp_path)
    assert main(["init", "-w", str(tmp_path / "src" / "ws"), "--answers", str(p)]) == 2
    assert "kaynak klasörün içinde" in capsys.readouterr().err
    repo = Path(__file__).resolve().parents[1]
    assert main(["init", "-w", str(repo / "_tmp" / "ws-sinama"), "--answers", str(p)]) == 2
    assert "reposunun" in capsys.readouterr().err


def test_init_change_needs_approval_and_keeps_models(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "config.yaml").write_text("# model ayarı\nmodels:\n  default: {provider: fake}\n", encoding="utf-8")
    p = _answers(tmp_path)
    assert main(["init", "-w", str(ws), "--answers", str(p)]) == 0
    cfg = (ws / "config.yaml").read_text(encoding="utf-8")
    assert "# model ayarı" in cfg and yaml.safe_load(cfg)["models"]["default"]["provider"] == "fake"
    assert yaml.safe_load(cfg)["bidr"]["birim"] == "B"
    # aynı cevaplar: onay gerekmez (dosyalar tazelenir)
    assert main(["init", "-w", str(ws), "--answers", str(p)]) == 0
    p = _answers(tmp_path, donem=2026)
    capsys.readouterr()
    assert main(["init", "-w", str(ws), "--answers", str(p)]) == 5
    assert "2025 → 2026" in capsys.readouterr().out
    assert yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))["bidr"]["donem"] == 2025
    assert main(["init", "-w", str(ws), "--answers", str(p), "--yes"]) == 0
    data = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert data["bidr"]["donem"] == 2026 and data["models"]["default"]["provider"] == "fake"
    assert (ws / "config.yaml").read_text(encoding="utf-8").count("bidr:") == 1


def test_init_does_not_overwrite_user_agents_md(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("benim notlarım\n", encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(_answers(tmp_path)), "--claude-hook"]) == 0
    assert (ws / "AGENTS.md").read_text(encoding="utf-8") == "benim notlarım\n"
    assert "dokunulmadı" in capsys.readouterr().out
    hook = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmd = hook["hooks"]["SessionStart"][0]["hooks"][0]["command"]
    assert "status" in cmd and "--kisa" in cmd


def test_init_sablon_is_valid_shape(capsys):
    assert main(["init", "--sablon"]) == 0
    data = yaml.safe_load(capsys.readouterr().out)
    from bidr.init.config import FIELDS, RAPOR_FIELDS
    assert set(data) == set(FIELDS) | set(RAPOR_FIELDS)
    assert data["hazirlayanlar"] == []             # örnek kişi yok: kullanıcıya sorulur


def test_unmanaged_workspace_has_no_gate(tmp_path):
    from bidr.pipeline import require_stage
    (tmp_path / "w").mkdir()
    require_stage(tmp_path / "w", "karar_ince")    # bidr bölümü yok → kapı yok


def test_init_preparers(kurulum, capsys):
    """`hazirlayanlar` cevabı config.yaml `rapor.hazirlayanlar`'a gider; rapor bölümünün öteki anahtarları
    korunur; cevapta yoksa liste korunur; değişiklik kullanıcı onayı ister."""
    src, ws, ans = kurulum
    a = yaml.safe_load(ans.read_text(encoding="utf-8"))
    people = [{"unvan": "Dr. Öğr. Üyesi", "ad_soyad": "Örnek Kişi", "eposta": "ornek@example.edu",
               "gorev": "Komisyon Başkanı"}]
    bad = {**a, "hazirlayanlar": [{"unvan": "Dr.", "eposta": "ornek-at-example"}]}
    ans.write_text(yaml.safe_dump(bad, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 2
    err = capsys.readouterr().err
    assert "ad_soyad" in err and "e-posta" in err
    ans.write_text(yaml.safe_dump({**a, "hazirlayanlar": people}, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert "raporu hazırlayanlar: 1 kişi" in capsys.readouterr().out
    _rapor_config(ws, sablon="/yok/sablon.docx")
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["rapor"]["hazirlayanlar"] == people and cfg["bidr"]["birim"] == "Örnek Bölümü"
    # cevapta hazirlayanlar yok: liste ve rapor bölümü korunur
    ans.write_text(yaml.safe_dump(a, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["rapor"] == {"hazirlayanlar": people, "sablon": "/yok/sablon.docx"}
    # farklı liste: onay gerekir
    two = people + [{"ad_soyad": "Deneme Ad", "eposta": "deneme@example.edu", "gorev": "Üye"}]
    ans.write_text(yaml.safe_dump({**a, "hazirlayanlar": two}, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 5          # onay gerekir
    assert "rapor.hazirlayanlar: 1 kişi → 2 kişi" in capsys.readouterr().out
    assert main(["init", "-w", str(ws), "--answers", str(ans), "--yes"]) == 0
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert len(cfg["rapor"]["hazirlayanlar"]) == 2 and cfg["rapor"]["hazirlayanlar"][1]["unvan"] == ""
    assert cfg["rapor"]["sablon"] == "/yok/sablon.docx"


def test_init_approver(kurulum, capsys):
    """`onaylayan` (birim amiri, tek kişi) config.yaml `rapor.onaylayan`'a gider; boş alanlı kayıt verilmemiş
    sayılır; cevapta yoksa korunur; değişiklik onay ister; liste verilirse hata."""
    src, ws, ans = kurulum
    a = yaml.safe_load(ans.read_text(encoding="utf-8"))
    amir = {"unvan": "Prof. Dr.", "ad_soyad": "Amir Örnek", "eposta": "amir@example.edu", "gorev": "Bölüm Başkanı"}
    for bad in ([amir], {"unvan": "Dr.", "eposta": "x"}, {**amir, "telefon": "1"}):
        ans.write_text(yaml.safe_dump({**a, "onaylayan": bad}, allow_unicode=True), encoding="utf-8")
        assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 2
        assert "onaylayan" in capsys.readouterr().err
    ans.write_text(yaml.safe_dump({**a, "onaylayan": amir}, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert "raporu onaylayan birim amiri: Amir Örnek" in capsys.readouterr().out
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["rapor"]["onaylayan"] == amir
    ans.write_text(yaml.safe_dump(a, allow_unicode=True), encoding="utf-8")          # cevapta yok: korunur
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))["rapor"]["onaylayan"] == amir
    bos = {k: "" for k in amir}                                                       # panelin boş formu
    ans.write_text(yaml.safe_dump({**a, "onaylayan": bos}, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 5
    assert "rapor.onaylayan: Amir Örnek → (boş)" in capsys.readouterr().out
    assert main(["init", "-w", str(ws), "--answers", str(ans), "--yes"]) == 0
    assert yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))["rapor"]["onaylayan"] is None


def _docx_stub(p: Path) -> Path:
    import zipfile
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return p


def test_init_report_template(kurulum, capsys):
    """`sablon` cevabı config.yaml `rapor.sablon`'a gider (kör test: config'i elle düzenlemeden
    şablon yolunu yazacak resmi yol yoktu); boşsa var olan korunur; değişiklik onay ister."""
    src, ws, ans = kurulum
    a = yaml.safe_load(ans.read_text(encoding="utf-8"))
    for bad, msg in (("/yok/FR-0833.docx", "rapor şablonu yok"), (str(ans), ".docx olmalı")):
        ans.write_text(yaml.safe_dump({**a, "sablon": bad}, allow_unicode=True), encoding="utf-8")
        assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 2
        assert msg in capsys.readouterr().err
    notdocx = ans.parent / "bozuk.docx"
    notdocx.write_text("docx değil", encoding="utf-8")
    ans.write_text(yaml.safe_dump({**a, "sablon": str(notdocx)}, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 2
    assert "açılamadı" in capsys.readouterr().err
    t1 = _docx_stub(ans.parent / "sablon" / "FR-0833.docx")
    ans.write_text(yaml.safe_dump({**a, "sablon": str(t1)}, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert f"rapor şablonu: {t1}" in capsys.readouterr().out
    cfg = yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["rapor"]["sablon"] == str(t1)
    assert "şablon bilinmiyor" not in (evaluate(ws).get("render").neden or "")
    # cevapta sablon null: var olan korunur
    ans.write_text(yaml.safe_dump({**a, "sablon": None}, allow_unicode=True), encoding="utf-8")
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 0
    assert yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))["rapor"]["sablon"] == str(t1)
    # farklı şablon: kullanıcı onayı
    t2 = _docx_stub(ans.parent / "sablon" / "FR-0833-r1.docx")
    ans.write_text(yaml.safe_dump({**a, "sablon": str(t2)}, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["init", "-w", str(ws), "--answers", str(ans)]) == 5
    assert "rapor.sablon:" in capsys.readouterr().out
    assert main(["init", "-w", str(ws), "--answers", str(ans), "--yes"]) == 0
    assert yaml.safe_load((ws / "config.yaml").read_text(encoding="utf-8"))["rapor"]["sablon"] == str(t2)


def test_sandbox_wrapper_command(tmp_path, monkeypatch):
    """`tools/sandbox.sh` ile çalışan bidr, sonraki komutları da sarmalayıcıyla yazdırır."""
    import subprocess
    from bidr.pipeline.state import bidr_command
    repo = Path(__file__).resolve().parents[1]
    wrap = repo / "tools" / "sandbox.sh"
    assert wrap.is_file()
    monkeypatch.setenv("BIDR_SARMALAYICI", str(wrap))
    assert bidr_command() == f"sh {wrap}" or bidr_command() == f"sh '{wrap}'"
    monkeypatch.setenv("BIDR_SARMALAYICI", str(tmp_path / "yok.sh"))
    assert "sandbox.sh" not in bidr_command()
    r = subprocess.run(["sh", str(wrap), "--help"], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0 and "sh tools/sandbox.sh kur" in r.stdout
