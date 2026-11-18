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
        "Kanıtlar/B.1.1/[B.1.1-1-OD3] Kurul Kararı.txt": DOCS["aynı"],
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
    assert ids[:2] == ["kurulum", "ingest"] and ids[-1] == "render"
    for s in spec["asamalar"]:
        if s["uygulandi"]:
            assert s["komut"] and s["skill"], s["id"]
        else:
            assert s["sart"]["denetim"] == "yok"
    assert {s["id"] for s in spec["asamalar"] if not s["uygulandi"]} == {"file", "write", "verify", "render"}


def test_full_pipeline_transitions_and_gates(kurulum, capsys):
    src, ws, ans = kurulum
    # 0. kurulmamış: yalnız kurulum bekler, gerisi engelli; kapı yok (yönetilmeyen WS)
    d = _durum(ws)
    assert d["kurulum"] == "bekliyor" and d["ingest"] == "engelli" and d["audit"] == "engelli"
    assert d["transcribe"] == "engelli" and d["file"] == "yok"
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
    (ws / "work" / "coarse" / f"{ids[0]}.out.json").unlink()
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
    assert rep.get("audit").durum == "bitti"
    assert rep.sonraki.id == "file" and rep.sonraki.durum == "yok"
    capsys.readouterr()
    main(["next", "-w", str(ws)])
    assert "henüz yok" in capsys.readouterr().out

    # kararlar yenilenirse (ör. yeni apply) hakem kuyruğu eskir
    import os
    t = (ws / "label-review.jsonl").stat().st_mtime_ns
    os.utime(ws / "decisions.jsonl", ns=(t + 10**9, t + 10**9))
    assert evaluate(ws).get("hakem").durum == "bekliyor"

    # kaynak salt okunur: hiçbir dosyası değişmedi, içine bir şey yazılmadı
    assert sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()) == sorted(
        ["Kanıtlar/B.1.1/[B.1.1-1-OD3] Kurul Kararı.txt", "Kanıtlar/B.1.1/[B.1.1-2-OD3] Toplantı.txt",
         "Kanıtlar/A.1.2/[A.1.2-1-OD3] Tutanak.txt", "Diğer/menü.txt"])


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
    from bidr.init.config import FIELDS
    assert set(data) == set(FIELDS)


def test_unmanaged_workspace_has_no_gate(tmp_path):
    from bidr.pipeline import require_stage
    (tmp_path / "w").mkdir()
    require_stage(tmp_path / "w", "karar_ince")    # bidr bölümü yok → kapı yok
