"""`bidr guncel` / `bidr guncelle` / `bidr next` hatırlatması. Ağ yok: uzak, geçici klasörde
yerel bir bare depodur; "çevrimdışı" var olmayan bir uzak adresle sınanır."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bidr.cli import main
from bidr.guncel import core

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _git_env(tmp_path, monkeypatch):
    g = tmp_path / "gitconfig"
    g.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(g))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "Sentetik")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "sentetik@example.invalid")
    monkeypatch.delenv("BIDR_GUNCEL_DENETIM", raising=False)


def run(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def commit(repo: Path, msg: str, files: dict[str, str]) -> str:
    for k, v in files.items():
        write(repo / k, v)
    run(repo, "add", "-A")
    run(repo, "commit", "-q", "-m", msg)
    return run(repo, "rev-parse", "HEAD")


@pytest.fixture
def depo(tmp_path):
    """(bare uzak, yayıncı klonu, kullanıcı klonu)."""
    bare = tmp_path / "remote.git"
    run(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    up = tmp_path / "up"
    run(tmp_path, "clone", "-q", str(bare), str(up))
    run(up, "checkout", "-q", "-b", "main")
    commit(up, "ilk", {"bidr/__init__.py": '__version__ = "0.1.0"\n',
                       "pyproject.toml": '[project]\nname = "bidr"\nversion = "0.1.0"\n',
                       "CHANGELOG.md": "# Değişiklikler\n"})
    run(up, "push", "-q", "origin", "main")
    user = tmp_path / "user"
    run(tmp_path, "clone", "-q", str(bare), str(user))
    return bare, up, user


def yayinla(up: Path, msg: str, files: dict[str, str]) -> str:
    h = commit(up, msg, files)
    run(up, "push", "-q", "origin", "main")
    return h


def test_guncel_ve_geride(depo):
    _, up, user = depo
    d = core.check(user)
    assert d.denetlendi and d.geride == 0 and d.ileride == 0 and d.yerel_surum == "0.1.0"
    assert any("güncel" in x for x in core.summary_lines(d))
    yayinla(up, "a", {"a.txt": "1"})
    yayinla(up, "b", {"bidr/__init__.py": '__version__ = "0.2.0"\n'})
    d = core.check(user)
    assert d.geride == 2 and d.uzak_surum == "0.2.0" and d.yerel_surum == "0.1.0"
    s = "\n".join(core.summary_lines(d))
    assert "2 commit geride" in s and "guncelle" in s


def test_cevrimdisi_sessizce_denetlenemedi(depo, tmp_path, capsys):
    _, _, user = depo
    run(user, "remote", "set-url", "origin", str(tmp_path / "yok.git"))
    d = core.check(user)
    assert not d.denetlendi and "ulaşılamadı" in d.neden
    assert "denetlenemedi" in "\n".join(core.summary_lines(d))
    head = run(user, "rev-parse", "HEAD")
    assert core.update(user) == 1
    assert run(user, "rev-parse", "HEAD") == head
    assert "denetlenemedi" in capsys.readouterr().out


def test_git_klonu_degil(tmp_path, monkeypatch, capsys):
    src = tmp_path / "kopya"
    write(src / "bidr/__init__.py", '__version__ = "0.1.0"\n')

    def boom(*a, **k):
        raise AssertionError("alt süreç başlatılmamalı")
    monkeypatch.setattr(core.subprocess, "run", boom)
    assert core.clone_root(src) is None
    assert core.next_notice(root=src) is None
    d = core.check(src)
    assert not d.denetlendi and "git klonu değil" in d.neden
    assert core.update(src) == 1
    assert "git klonu değil" in capsys.readouterr().out


def test_kirli_agac_ve_baska_dal_dokunulmaz(depo, capsys):
    _, up, user = depo
    yayinla(up, "a", {"a.txt": "1"})
    head = run(user, "rev-parse", "HEAD")
    write(user / "CHANGELOG.md", "elle değişti\n")
    assert core.check(user).kirli == ["CHANGELOG.md"]
    assert core.update(user) == 1
    assert "yerel değişiklik" in capsys.readouterr().out
    assert run(user, "rev-parse", "HEAD") == head
    run(user, "checkout", "-q", "--", "CHANGELOG.md")
    run(user, "checkout", "-q", "-b", "deneme")
    assert core.update(user) == 1
    assert "main değil" in capsys.readouterr().out
    assert run(user, "rev-parse", "HEAD") == head
    assert core.next_notice(root=user) is None
    # izlenmeyen dosya engel değil
    run(user, "checkout", "-q", "main")
    write(user / "notum.txt", "x")
    assert core.check(user).kirli == []


def test_ileride_ve_ayrilmis(depo, capsys):
    _, up, user = depo
    commit(user, "yerel", {"yerel.txt": "1"})
    d = core.check(user)
    assert d.ileride == 1 and d.geride == 0
    assert core.update(user) == 0
    assert "zaten güncel" in capsys.readouterr().out
    yayinla(up, "uzak", {"uzak.txt": "1"})
    head = run(user, "rev-parse", "HEAD")
    assert core.update(user) == 1
    assert "ayrılmış" in capsys.readouterr().out
    assert run(user, "rev-parse", "HEAD") == head


def test_guncelle_ileri_sarar_ozet_ve_yeniden_kurulum(depo, monkeypatch, capsys):
    _, up, user = depo
    calls = []
    monkeypatch.setattr(core, "install_command",
                        lambda root, extras: calls.append(extras) or [sys.executable, "-c", "pass"])
    yayinla(up, "yalnız kod", {"x.py": "1\n"})
    assert core.update(user) == 0
    out = capsys.readouterr().out
    assert "bidr güncellendi" in out and "yalnız kod" in out and not calls
    new = yayinla(up, "bağımlılık", {"pyproject.toml": '[project]\nname = "bidr"\nversion = "0.2.0"\n'
                                     'dependencies = ["pyyaml"]\n',
                                     "bidr/__init__.py": '__version__ = "0.2.0"\n',
                                     "CHANGELOG.md": "# Değişiklikler\n\n- 0.2.0: yeni bağımlılık\n"})
    assert core.update(user) == 0
    out = capsys.readouterr().out
    assert run(user, "rev-parse", "HEAD") == new
    assert "0.1.0 → 0.2.0" in out and "- 0.2.0: yeni bağımlılık" in out and "yeniden kuruluyor" in out
    assert calls == [[]]


def test_yeniden_kurulum_basarisizsa_bildirir(depo, monkeypatch, capsys):
    _, up, user = depo
    monkeypatch.setattr(core, "install_command", lambda root, extras: [sys.executable, "-c", "raise SystemExit(3)"])
    yayinla(up, "dep", {"pyproject.toml": '[project]\nname = "bidr"\nversion = "0.3.0"\n'})
    assert core.update(user) == 1
    assert "başarısız" in capsys.readouterr().out


def test_acik_is_paketi_varken_asama_sinirini_bekler(depo, tmp_path, capsys):
    _, up, user = depo
    yayinla(up, "a", {"a.txt": "1"})
    ws = tmp_path / "ws"
    write(ws / "work/fine/d1.json", "{}")
    write(ws / "work/fine/d2.json", "{}")
    write(ws / "work/fine/d2.out.json", "{}")
    write(ws / "work/fine/YENIDEN.json", "{}")
    write(ws / "work/_durum/x.json", "{}")
    write(ws / "work/verify/yonler/A.json", "{}")
    assert core.open_packages(ws) == {"fine": 1, "verify/yonler": 1}
    head = run(user, "rev-parse", "HEAD")
    assert core.update(user, str(ws)) == 1
    assert "açık iş paketi" in capsys.readouterr().out
    assert run(user, "rev-parse", "HEAD") == head
    s = "\n".join(core.summary_lines(core.check(user), str(ws)))
    assert "aşama bitince" in s
    assert core.update(user, str(ws), force=True) == 0
    assert run(user, "rev-parse", "HEAD") != head


def test_next_hatirlatmasi_gunde_bir(depo, tmp_path, monkeypatch):
    _, up, user = depo
    t0 = 1_000_000.0
    assert core.next_notice(root=user, now=t0) is None          # güncel; denetim zamanı yazıldı
    assert (user / "_tmp" / core.CACHE_NAME).exists()
    yayinla(up, "a", {"a.txt": "1"})
    assert core.next_notice(root=user, now=t0 + 60) is None     # aynı gün: ağa çıkmaz
    line = core.next_notice("/ws", root=user, now=t0 + core.DAY + 1)
    assert line and "Yeni bidr sürümü var" in line and "guncelle -w /ws" in line and "1 commit" in line
    yayinla(up, "b", {"b.txt": "1"})
    assert "1 commit" in core.next_notice(root=user, now=t0 + core.DAY + 100)   # önbellekten, ağsız
    monkeypatch.setenv("BIDR_GUNCEL_DENETIM", "0")
    assert core.next_notice(root=user, now=t0 + 10 * core.DAY) is None
    monkeypatch.delenv("BIDR_GUNCEL_DENETIM")
    assert "2 commit" in core.next_notice(root=user, now=t0 + 10 * core.DAY)


def test_next_hatirlatmasi_cevrimdisi_sessiz(depo, tmp_path):
    _, _, user = depo
    run(user, "remote", "set-url", "origin", str(tmp_path / "yok.git"))
    assert core.next_notice(root=user, now=5.0) is None


def test_next_satiri_ciktinin_sonunda_json_da_yok(tmp_path, monkeypatch, capsys):
    from bidr.guncel import core as c
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(c, "next_notice", lambda w: "Yeni bidr sürümü var: `bidr guncelle`")
    assert main(["next", "-w", str(ws)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == "Yeni bidr sürümü var: `bidr guncelle`"
    assert main(["next", "-w", str(ws), "--json"]) == 0
    assert "Yeni bidr" not in capsys.readouterr().out


def test_guncel_komutu_hata_vermez(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "fetch", lambda root, timeout=0: "uzak depoya ulaşılamadı (sınama)")
    assert main(["guncel"]) == 0
    assert "denetlenemedi" in capsys.readouterr().out
    assert main(["guncel", "--json"]) == 0
    assert '"denetlendi": false' in capsys.readouterr().out


def test_calisma_alani_dosyalari_yeni_kodla_yenilenir(tmp_path):
    ws = tmp_path / "ws"
    write(ws / "config.yaml", "bidr:\n  birim: Sentetik Bölüm\n  donem: 2025\n  profil: akademik_bolum\n"
                              f"  kaynak: {tmp_path / 'kaynak'}\n")
    msgs = []
    core.refresh_workspace(REPO, ws, msgs.append)
    assert (ws / "AGENTS.md").exists() and (ws / ".claude/skills/bidr-rapor/SKILL.md").exists()
    assert "guncel" in (ws / "AGENTS.md").read_text(encoding="utf-8")
    assert msgs and "AGENTS.md" in msgs[0]


def test_kurulu_ek_gruplar():
    t = ('[project]\nname="x"\n[project.optional-dependencies]\nvar = ["pytest>=8"]\n'
         'yok = ["bu-paket-kurulu-degil-xyz>=1"]\n')
    assert core.installed_extras(t) == ["var"]
    assert core.installed_extras("bozuk = [") == []


def test_ajan_dosyalari_oturum_basinda_guncel_der():
    for p in ["AGENTS.md", "bidr/data/workspace/AGENTS.md",
              *(f".agents/skills/bidr-{s}/SKILL.md" for s in ("kur", "rapor", "hakem"))]:
        t = (REPO / p).read_text(encoding="utf-8")
        assert "bidr guncel" in t and "guncelle" in t, p
    assert "## Güncelleme" in (REPO / "README.md").read_text(encoding="utf-8")
    assert (REPO / "CHANGELOG.md").exists()
