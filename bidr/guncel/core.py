"""Güncellik denetimi ve güncelleme. Ağ yalnız `git fetch` ile, kısa zaman aşımıyla; her
başarısızlık "denetlenemedi" olur, hata fırlatılmaz.

Uzak: `origin`'in `main` dalı (README'deki kurulum git clone'dur). Çekme
`refs/remotes/origin/main`'e açık refspec'le yapılır; tek dal klonunda da çalışır."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REMOTE = "origin"
BRANCH = "main"
REMOTE_REF = f"refs/remotes/{REMOTE}/{BRANCH}"
ENV_OFF = "BIDR_GUNCEL_DENETIM"
CACHE_NAME = "guncel-denetim.json"
DAY = 24 * 3600
FETCH_TIMEOUT = 8          # bidr guncel / guncelle
NEXT_TIMEOUT = 4           # bidr next içindeki günlük denetim
HELPER_FILES = {"YENIDEN.json"}   # bidr.decide.run.LEGACY_RESTALE
VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


@dataclass
class Durum:
    denetlendi: bool
    neden: str | None = None          # denetlenemediyse kısa neden
    yerel: str | None = None          # HEAD
    yerel_surum: str | None = None
    dal: str | None = None            # None: ayrık HEAD
    kirli: list[str] = field(default_factory=list)
    uzak: str | None = None
    uzak_surum: str | None = None
    geride: int = 0
    ileride: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


# --- git ---------------------------------------------------------------------------------

def _env() -> dict:
    e = dict(os.environ)
    e["GIT_TERMINAL_PROMPT"] = "0"          # parola/kimlik sormasın, beklemesin
    e.setdefault("GCM_INTERACTIVE", "never")
    e.setdefault("GIT_SSH_COMMAND", f"ssh -o BatchMode=yes -o ConnectTimeout={NEXT_TIMEOUT}")
    return e


def git(root: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess | None:
    """`git -C root …`; git yoksa, zaman aşımında ya da başlatılamazsa None."""
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=timeout, env=_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None


def _out(root: Path, *args: str, timeout: float = 10) -> str | None:
    r = git(root, *args, timeout=timeout)
    return r.stdout.strip() if r is not None and r.returncode == 0 else None


def clone_root(root: Path | None = None) -> Path | None:
    """bidr'in git klonu kökü; düzenlenebilir kurulum değilse, `.git` yoksa ya da git kurulu
    değilse None. Alt süreç başlatmaz (panel/docker ortamında gecikme eklemez)."""
    if root is None:
        from bidr.init.config import repo_root
        root = repo_root()
    if root is None or not (root / ".git").exists() or shutil.which("git") is None:
        return None
    return root


def _version_of(text: str | None) -> str | None:
    m = VERSION_RE.search(text or "")
    return m.group(1) if m else None


def local_state(root: Path) -> Durum:
    head = _out(root, "rev-parse", "HEAD")
    if head is None:
        return Durum(False, neden="git deposu okunamadı")
    dal = _out(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    r = git(root, "status", "--porcelain", "--untracked-files=no")   # strip yok: "XY yol" sütunları
    if r is None or r.returncode != 0:
        return Durum(False, neden="git durumu okunamadı")
    st = r.stdout
    try:
        ver = _version_of((root / "bidr" / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        ver = None
    return Durum(True, yerel=head, yerel_surum=ver, dal=dal or None,
                 kirli=[ln[3:] for ln in st.splitlines() if ln.strip()])


def fetch(root: Path, timeout: float = FETCH_TIMEOUT) -> str | None:
    """Uzak main'i çeker; başarısızsa kısa neden, başarılıysa None."""
    if _out(root, "remote", "get-url", REMOTE) is None:
        return f"'{REMOTE}' uzak deposu tanımlı değil"
    r = git(root, "-c", "http.lowSpeedLimit=1000", "-c", f"http.lowSpeedTime={int(timeout)}",
            "fetch", "--quiet", "--no-tags", REMOTE, f"+refs/heads/{BRANCH}:{REMOTE_REF}", timeout=timeout)
    if r is None:
        return "uzak depoya ulaşılamadı (zaman aşımı ya da git çalışmadı)"
    if r.returncode != 0:
        lines = [x.strip() for x in r.stderr.splitlines() if x.strip()]
        msg = next((x for x in lines if x.startswith(("fatal:", "error:"))), lines[0] if lines else "git fetch başarısız")
        return f"uzak depoya ulaşılamadı ({msg[:160]})"
    return None


def compare(root: Path, d: Durum) -> Durum:
    """Yerel HEAD ile (önceden çekilmiş) `origin/main`'i ağa çıkmadan karşılaştırır."""
    uzak = _out(root, "rev-parse", "--verify", "--quiet", REMOTE_REF)
    if uzak is None:
        d.denetlendi, d.neden = False, f"{REMOTE}/{BRANCH} henüz çekilmedi"
        return d
    counts = _out(root, "rev-list", "--left-right", "--count", f"HEAD...{REMOTE_REF}")
    if counts is None:
        d.denetlendi, d.neden = False, "commit geçmişi karşılaştırılamadı"
        return d
    a, b = (int(x) for x in counts.split())
    d.uzak, d.ileride, d.geride = uzak, a, b
    d.uzak_surum = _version_of(_out(root, "show", f"{REMOTE_REF}:bidr/__init__.py"))
    return d


def check(root: Path | None = None, *, timeout: float = FETCH_TIMEOUT, network: bool = True) -> Durum:
    """Tam denetim. Hiçbir durumda hata fırlatmaz; ulaşılamazsa `denetlendi=False`."""
    r = clone_root(root)
    if r is None:
        return Durum(False, neden="git klonu değil (docker/pip kurulumu ya da git yok)")
    d = local_state(r)
    if not d.denetlendi:
        return d
    if network:
        why = fetch(r, timeout)
        if why:
            d.denetlendi, d.neden = False, why
            return d
    return compare(r, d)


# --- çalışma alanı -----------------------------------------------------------------------

def open_packages(ws: Path | str | None) -> dict[str, int]:
    """Çalışma alanında cevapsız iş paketleri: `work/<aşama>/<x>.json` olup `<x>.out.json`
    olmayanlar, aşama klasörüne göre sayılır. `_` ile başlayan dosya/klasör (durum dosyaları)
    ve eski sürümün yardımcı dosyası (`YENIDEN.json`) paket değildir."""
    if not ws:
        return {}
    w = Path(ws).expanduser() / "work"
    out: dict[str, int] = {}
    if not w.is_dir():
        return out
    for p in w.rglob("*.json"):
        rel = p.relative_to(w)
        if (p.name.endswith(".out.json") or p.name in HELPER_FILES
                or any(x.startswith("_") for x in rel.parts)):
            continue
        if not p.with_name(p.name[:-5] + ".out.json").exists():
            k = rel.parent.as_posix()
            out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def _open_note(pk: dict[str, int]) -> str:
    return ", ".join(f"work/{k}: {n}" for k, n in pk.items())


# --- metin -------------------------------------------------------------------------------

def _cmd() -> str:
    from bidr.pipeline.state import bidr_command
    return bidr_command()


def summary_lines(d: Durum, ws: str | None = None) -> list[str]:
    if not d.denetlendi and d.yerel is None:
        return [f"bidr güncellik: denetlenemedi ({d.neden})"]
    lines = [f"bidr {d.yerel_surum or '?'} · commit {d.yerel[:7]} · dal {d.dal or '(ayrık HEAD)'}"]
    if not d.denetlendi:
        lines.append(f"Uzak sürüm: denetlenemedi ({d.neden})")
    else:
        lines.append(f"Uzak {REMOTE}/{BRANCH}: commit {d.uzak[:7]} · sürüm {d.uzak_surum or '?'}")
    durum = []
    wsq = f" -w {ws}" if ws else ""
    if d.denetlendi:
        if d.geride:
            durum.append(f"{d.geride} commit geride")
        if d.ileride:
            durum.append(f"{d.ileride} commit ileride (uzakta olmayan yerel commit)")
        if not d.geride and not d.ileride:
            durum.append("güncel")
    if d.kirli:
        durum.append(f"yerel değişiklik var ({len(d.kirli)} dosya)")
    if d.dal != BRANCH:
        durum.append(f"dal {BRANCH} değil")
    lines.append("Durum: " + ("; ".join(durum) or "bilinmiyor"))
    if d.denetlendi and d.geride:
        pk = open_packages(ws)
        if d.kirli or d.dal != BRANCH or d.ileride:
            lines.append(f"Güncelleme şimdi yapılamaz; `{_cmd()} guncelle` ne yapılacağını söyler.")
        elif pk:
            lines.append(f"Açık iş paketi var ({_open_note(pk)}): aşama bitince `{_cmd()} guncelle{wsq}`.")
        else:
            lines.append(f"Güncellemek için: `{_cmd()} guncelle{wsq}` (aşama sınırında).")
    return lines


# --- bidr next hatırlatması --------------------------------------------------------------

def _cache_paths(root: Path, ws: str | None) -> list[Path]:
    """Denetim zamanı önce klonun git dışı `_tmp/`'sine (sandbox'ta da yazılabilir, klon başına),
    olmazsa çalışma alanına yazılır."""
    out = [root / "_tmp" / CACHE_NAME]
    if ws:
        out.append(Path(ws).expanduser() / ".bidr-guncel-denetim.json")
    return out


def _last_check(paths: list[Path]) -> float | None:
    for p in paths:
        try:
            return float(json.loads(p.read_text(encoding="utf-8"))["zaman"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return None


def _stamp(paths: list[Path], now: float) -> bool:
    for p in paths:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"zaman": now}) + "\n", encoding="utf-8")
            return True
        except OSError:
            continue
    return False


def next_notice(ws: str | None = None, *, root: Path | None = None, now: float | None = None) -> str | None:
    """`bidr next` sonuna eklenecek tek satır ya da None. Ağ denetimi günde en çok bir kez;
    arada önceki çekmenin `origin/main`'iyle ağsız karşılaştırılır. Hiçbir durumda hata
    fırlatmaz. Kapatma: BIDR_GUNCEL_DENETIM=0."""
    try:
        if os.environ.get(ENV_OFF, "").strip().lower() in ("0", "hayir", "hayır", "no", "false", "off"):
            return None
        r = clone_root(root)
        if r is None:
            return None
        if (r / ".git").is_dir() and not (r / ".git" / "HEAD").read_text(encoding="utf-8").strip() \
                .endswith(f"refs/heads/{BRANCH}"):
            return None                      # geliştirici başka dalda: alt süreç bile yok
        d = local_state(r)
        if not d.denetlendi or d.dal != BRANCH:
            return None
        now = time.time() if now is None else now
        paths = _cache_paths(r, ws)
        last = _last_check(paths)
        if last is None or not (0 <= now - last < DAY):
            if _stamp(paths, now):           # yazılamıyorsa her next'te beklememek için ağa çıkma
                fetch(r, NEXT_TIMEOUT)
        d = compare(r, d)
        if d.denetlendi and d.geride > 0:
            wsq = f" -w {ws}" if ws else ""
            return f"Yeni bidr sürümü var: `{_cmd()} guncelle{wsq}` ({d.geride} commit geride; aşama sınırında)"
    except Exception:  # noqa: BLE001 — hatırlatma hiçbir zaman next'i bozmaz
        return None
    return None


# --- güncelleme --------------------------------------------------------------------------

def _req_name(req: str) -> str:
    return re.split(r"[\s<>=!~\[;(]", req.strip(), maxsplit=1)[0]


def installed_extras(pyproject_text: str) -> list[str]:
    """Kurulu ek grupları: bütün paketleri bu Python ortamında kurulu olan
    `[project.optional-dependencies]` grupları (yeniden kurulumda korunur)."""
    import importlib.metadata as md
    import tomllib
    try:
        opt = tomllib.loads(pyproject_text).get("project", {}).get("optional-dependencies", {}) or {}
    except (tomllib.TOMLDecodeError, AttributeError):
        return []
    out = []
    for name, reqs in opt.items():
        try:
            if reqs and all(md.distribution(_req_name(x)) for x in reqs):
                out.append(name)
        except md.PackageNotFoundError:
            continue
    return out


def install_command(root: Path, extras: list[str]) -> list[str] | None:
    spec = str(root) + (f"[{','.join(extras)}]" if extras else "")
    if shutil.which("uv"):
        return ["uv", "pip", "install", "--python", sys.executable, "-e", spec]
    import importlib.util
    if importlib.util.find_spec("pip") is not None:
        return [sys.executable, "-m", "pip", "install", "-e", spec]
    return None


def reinstall(root: Path, old: str, out=print) -> bool:
    import shlex
    extras = installed_extras(_out(root, "show", f"{old}:pyproject.toml") or "")
    cmd = install_command(root, extras)
    if cmd is None:
        spec = str(root) + (f"[{','.join(extras)}]" if extras else "")
        out(f"Bağımlılıklar değişti ama uv ya da pip bulunamadı; elle kurun: uv pip install -e '{spec}'")
        return False
    out("Bağımlılıklar değişti (pyproject.toml); yeniden kuruluyor: " + " ".join(shlex.quote(c) for c in cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        out(f"Yeniden kurulum çalışmadı ({e}); yukarıdaki komutu elle çalıştırın.")
        return False
    if r.returncode != 0:
        out("Yeniden kurulum başarısız; yukarıdaki komutu elle çalıştırın:\n" + (r.stderr or r.stdout).strip()[-1500:])
        return False
    return True


def changelog_lines(root: Path, old: str, new: str) -> list[str]:
    diff = _out(root, "diff", "--unified=0", old, new, "--", "CHANGELOG.md") or ""
    return [ln[1:] for ln in diff.splitlines()
            if ln.startswith("+") and not ln.startswith("+++") and ln[1:].strip()]


_REFRESH = ("import sys\nfrom pathlib import Path\nfrom bidr.init.config import load_section\n"
            "from bidr.init.agentfiles import write_workspace_files\nws = Path(sys.argv[1])\n"
            "sec = load_section(ws)\nprint('\\n'.join(write_workspace_files(ws, sec)) if sec else '')\n")


def refresh_workspace(root: Path, ws: Path, out=print) -> None:
    """Çalışma alanının AGENTS.md'sini ve skill kopyalarını YENİ kodla yeniler (alt süreç:
    bu süreçte eski modüller yüklü)."""
    try:
        r = subprocess.run([sys.executable, "-c", _REFRESH, str(ws)], capture_output=True, text=True,
                           cwd=str(root), stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        out(f"Çalışma alanı dosyaları yenilenemedi ({e}); `bidr init` ile yenileyin.")
        return
    if r.returncode != 0:
        out("Çalışma alanı dosyaları yenilenemedi; `bidr init --answers …` ile yenileyin.")
        return
    notes = [x for x in r.stdout.splitlines() if x.strip()]
    if notes:
        out(f"Çalışma alanı ({ws}): " + "; ".join(notes))


def update(root: Path | None = None, ws: str | None = None, *, force: bool = False, out=print) -> int:
    """0: güncellendi ya da zaten güncel · 1: dokunulmadı (neden ve yapılacak yazılır)."""
    r = clone_root(root)
    cmd = _cmd()
    if r is None:
        out("Bu kurulum bir git klonu değil (docker imajı, pip kurulumu ya da git yok): bidr kendini "
            "güncelleyemez. Kurulumu yapan kaynağı yenileyin (ör. yeni imaj).")
        return 1
    d = local_state(r)
    if not d.denetlendi:
        out(f"Güncellenemedi: {d.neden}.")
        return 1
    if d.dal != BRANCH:
        out(f"Dal '{d.dal or '(ayrık HEAD)'}', {BRANCH} değil: dokunulmadı. Güncellemek için önce "
            f"`git -C {r} switch {BRANCH}` (dalınızdaki işi kaydettikten sonra), sonra `{cmd} guncelle`.")
        return 1
    if d.kirli:
        out(f"Repoda kaydedilmemiş yerel değişiklik var ({len(d.kirli)} dosya): dokunulmadı.")
        for f in d.kirli[:10]:
            out(f"  {f}")
        out(f"Değişiklikleri saklamak için `git -C {r} stash` (ya da commit), atmak için kullanıcıya "
            f"sorup `git -C {r} restore .`; sonra `{cmd} guncelle`.")
        return 1
    pk = open_packages(ws)
    if pk and not force:
        out(f"Çalışma alanında açık iş paketi var ({_open_note(pk)}): bir aşama yarıdayken güncelleme "
            "paket ile cevabın sürümünü ayırabilir. Paketleri bitirip `apply` çalıştırın, aşama "
            f"sınırında yeniden `{cmd} guncelle -w {ws}`. (Kullanıcı yine de isterse: `--yine-de`.)")
        return 1
    why = fetch(r)
    if why:
        out(f"Güncellik denetlenemedi: {why}. Bağlantı gelince yeniden deneyin; bidr bu sürümle çalışmaya devam eder.")
        return 1
    d = compare(r, d)
    if not d.denetlendi:
        out(f"Güncellik denetlenemedi: {d.neden}.")
        return 1
    if d.geride == 0:
        out(f"bidr zaten güncel (commit {d.yerel[:7]}, sürüm {d.yerel_surum or '?'})."
            + (f" Yerelde uzakta olmayan {d.ileride} commit var." if d.ileride else ""))
        return 0
    if d.ileride:
        out(f"Yerel {BRANCH} uzaktan ayrılmış ({d.ileride} yerel, {d.geride} uzak commit): ileri sarma "
            f"mümkün değil, dokunulmadı. Yerel commit'leri ayrı dala alıp (`git -C {r} branch yedek`) "
            f"kullanıcıyla birlikte çözün.")
        return 1
    old = d.yerel
    m = git(r, "merge", "--ff-only", "--quiet", REMOTE_REF, timeout=60)
    if m is None or m.returncode != 0:
        err = (m.stderr.strip() if m is not None else "git çalışmadı")
        out(f"İleri sarma başarısız, dokunulmadı: {err[-500:]}")
        return 1
    new = _out(r, "rev-parse", "HEAD") or d.uzak
    try:
        new_ver = _version_of((r / "bidr" / "__init__.py").read_text(encoding="utf-8"))
    except OSError:
        new_ver = None
    out(f"bidr güncellendi: {old[:7]} → {new[:7]} ({d.geride} commit; sürüm "
        f"{d.yerel_surum or '?'} → {new_ver or '?'}).")
    log = (_out(r, "log", "--oneline", "--no-decorate", f"{old}..{new}") or "").splitlines()
    for ln in log[:15]:
        out(f"  {ln}")
    if len(log) > 15:
        out(f"  … {len(log) - 15} commit daha")
    ch = changelog_lines(r, old, new)
    if ch:
        out("CHANGELOG:")
        for ln in ch[:30]:
            out(f"  {ln}")
    rc = 0
    if _out(r, "diff", "--name-only", old, new, "--", "pyproject.toml"):
        if not reinstall(r, old, out):
            rc = 1
    if ws:
        wsp = Path(ws).expanduser()
        if (wsp / "config.yaml").exists():
            refresh_workspace(r, wsp, out)
        out(f"Sıradaki: `{cmd} next -w {ws}`")
    return rc
