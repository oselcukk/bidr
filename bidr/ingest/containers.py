"""Kapsayıcı dosyalar: arşivler ve e-posta ekleri.

Arşiv (zip; tar; `bsdtar` varsa 7z/rar) ve e-posta (.eml; `extract-msg` kuruluysa .msg)
içindeki her dosya envantere ayrı satır olarak girer. Üyenin `rel_path`'i izlenebilir
biçimdedir: kapsayıcının yolu + `!/` + üye yolu; iç içe kapsayıcılarda zincirlenir
(`arsiv.zip!/alt/ic.zip!/tutanak.pdf`, `ileti.eml!/ek.pdf`).

Güvenlik: kaynak salt okunurdur ve üye adları hiçbir zaman yazma yolu olarak kullanılmaz
(üyeler çalışma klasöründe içerik kimliğiyle adlandırılır: `<ws>/arsiv/<doc_id><ext>`).
Yol geçişi (`../`, mutlak yol) içeren üye açılmaz, hata satırı olur. Zip bombasına karşı
derinlik, üye sayısı, üye boyutu, toplam boyut ve sıkıştırma oranı sınırları uygulanır;
okuma da sınırla yapılır (beyan edilen boyuta güvenilmez). Şifreli üye/arşiv açık hata
kaydıdır. Açılamayan arşiv türü "desteklenmeyen arşiv" kaydıdır.
"""
from __future__ import annotations

import email
import email.policy
import io
import os
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

SEP = "!/"

ZIP_EXTS = {".zip"}
TAR_EXTS = {".tar", ".tgz", ".tbz", ".tbz2", ".txz"}
TAR_DOUBLE = (".tar.gz", ".tar.bz2", ".tar.xz")
BSDTAR_EXTS = {".7z", ".rar"}
EMAIL_EXTS = {".eml", ".msg"}

# Sınırlar (zip bombası / aşırı büyük arşiv)
MAX_DEPTH = 4                       # iç içe kapsayıcı derinliği (en dıştaki = 1)
MAX_MEMBERS = 5000                  # bir dış kapsayıcının bütün ağacında üye sayısı
MAX_MEMBER_BYTES = 200 * 1024 ** 2  # tek üyenin açılmış boyutu
MAX_TOTAL_BYTES = 2 * 1024 ** 3     # bir dış kapsayıcının ağacında toplam açılmış boyut
MAX_RATIO = 200                     # açılmış / sıkıştırılmış (1 MiB üstü üyelerde)
RATIO_MIN_BYTES = 1024 ** 2

SKIP_NAMES = {".ds_store", "thumbs.db", "desktop.ini", "icon\r", ".localized"}
SKIP_DIRS = {"__macosx", ".git", ".trash", ".trashes", ".spotlight-v100", ".fseventsd"}

# Kapsayıcı satırının durumu (arşivin kendisi; metni yok, üyeleri ayrı satırlarda)
ARCHIVE = "archive"


def full_ext(name: str) -> str:
    low = name.lower()
    for d in TAR_DOUBLE:
        if low.endswith(d):
            return d
    return posixpath.splitext(low)[1]


def kind_of(name: str) -> str:
    """'zip' | 'tar' | 'bsdtar' | 'email' | ''"""
    e = full_ext(name)
    if e in ZIP_EXTS:
        return "zip"
    if e in TAR_EXTS or e in TAR_DOUBLE:
        return "tar"
    if e in BSDTAR_EXTS:
        return "bsdtar"
    if e in EMAIL_EXTS:
        return "email"
    return ""


def is_archive(name: str) -> bool:
    return kind_of(name) in ("zip", "tar", "bsdtar")


def skipped(path: str) -> bool:
    """Sistem/gizli dosyalar (kaynak taramasıyla aynı kural)."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return True
    if any(p.lower() in SKIP_DIRS or p.startswith(".") for p in parts[:-1]):
        return True
    name = parts[-1]
    return name.startswith(".") or name.startswith("~$") or name.lower() in SKIP_NAMES


def safe_name(name: str) -> tuple[str, bool]:
    """Üye adını normalleştir → (güvenli göreli yol, güvenli mi). `..` ve mutlak yol güvensizdir."""
    n = name.replace("\\", "/")
    unsafe = n.startswith("/") or bool(re.match(r"^[A-Za-z]:", n))
    parts = []
    for p in n.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            unsafe = True
            p = "__"
        parts.append(p)
    return "/".join(parts), not unsafe


@dataclass
class Member:
    rel: str                 # tam izlenebilir yol (kapsayıcı zinciri dahil)
    parent: str              # bir üst kapsayıcının rel'i
    ext: str
    size: int                # açılmış boyut (beyan; okununca gerçek)
    data: bytes | None = None
    status: str = ""         # önceden belirlenen durum (error/unsupported); boşsa normal belge
    error: str = ""
    path: Path | None = None  # `sink` baytları diske yazdıysa oradaki kopya
    sha: str = ""


@dataclass
class Note:
    """Kapsayıcının kendisine ait not (bozuk, desteklenmeyen, sınır)."""
    rel: str
    status: str              # archive | error | unsupported
    error: str = ""
    members: int = 0


class _Budget:
    def __init__(self) -> None:
        self.members = 0
        self.total = 0
        self.stopped = False


class LimitError(Exception):
    pass


class EncryptedError(Exception):
    pass


def _read_limited(f, limit: int = MAX_MEMBER_BYTES) -> bytes:
    data = f.read(limit + 1)
    if len(data) > limit:
        raise LimitError(f"üye boyut sınırı aşıldı (>{limit // 1024 ** 2} MiB)")
    return data


def bsdtar_available() -> bool:
    return shutil.which("bsdtar") is not None


# ------------------------------------------------------------------ listeleyiciler
# Her biri (ad, boyut, sıkıştırılmış boyut | None, şifreli, okuyucu) üretir.

def _zip_name(zi: zipfile.ZipInfo) -> str:
    n = zi.filename
    if not (zi.flag_bits & 0x800) and any(ord(c) > 127 for c in n):
        # UTF-8 bayrağı yok: zipfile cp437 diye çözdü; Türkçe Windows arşivleri cp857 yazar
        try:
            n = n.encode("cp437").decode("cp857")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return n


def _list_zip(src) -> Iterator[tuple]:
    with zipfile.ZipFile(src) as z:
        for zi in z.infolist():
            if zi.is_dir():
                continue
            enc = bool(zi.flag_bits & 0x1)

            def reader(zi=zi):
                try:
                    with z.open(zi) as f:
                        return _read_limited(f)
                except RuntimeError as e:  # parola gerekli
                    if "encrypt" in str(e).lower() or "password" in str(e).lower():
                        raise EncryptedError(str(e)) from e
                    raise
            yield _zip_name(zi), zi.file_size, zi.compress_size, enc, reader


def _list_tar(src) -> Iterator[tuple]:
    kw = {"fileobj": src} if isinstance(src, io.BytesIO) else {"name": str(src)}
    with tarfile.open(mode="r:*", **kw) as t:
        for ti in t:
            if not ti.isfile():
                continue

            def reader(ti=ti):
                f = t.extractfile(ti)
                if f is None:
                    raise RuntimeError("tar üyesi okunamadı")
                with f:
                    return _read_limited(f)
            yield ti.name, ti.size, None, False, reader


def _list_bsdtar(src) -> Iterator[tuple]:
    with tempfile.TemporaryDirectory(prefix="bidr-arc-") as td:
        if isinstance(src, io.BytesIO):
            p = Path(td) / "a"
            p.write_bytes(src.getvalue())
        else:
            p = Path(src)
        r = subprocess.run(["bsdtar", "-tf", str(p)], capture_output=True, timeout=300)
        err = r.stderr.decode("utf-8", "replace")
        if r.returncode != 0:
            if "encrypt" in err.lower() or "passphrase" in err.lower():
                raise EncryptedError(err.strip()[:200])
            raise RuntimeError(f"bsdtar: {err.strip()[:200]}")
        names = [n for n in r.stdout.decode("utf-8", "replace").splitlines() if n and not n.endswith("/")]
        for n in names:

            def reader(n=n):
                rr = subprocess.run(["bsdtar", "-xOf", str(p), "--", n], capture_output=True, timeout=600)
                e = rr.stderr.decode("utf-8", "replace")
                if rr.returncode != 0:
                    if "encrypt" in e.lower() or "passphrase" in e.lower():
                        raise EncryptedError(e.strip()[:200])
                    raise RuntimeError(f"bsdtar: {e.strip()[:200]}")
                if len(rr.stdout) > MAX_MEMBER_BYTES:
                    raise LimitError(f"üye boyut sınırı aşıldı (>{MAX_MEMBER_BYTES // 1024 ** 2} MiB)")
                return rr.stdout
            yield n, 0, None, False, reader


# ------------------------------------------------------------------- e-posta

_MIME_EXT = {"application/pdf": ".pdf", "text/plain": ".txt", "text/html": ".html",
             "image/jpeg": ".jpg", "image/png": ".png", "application/zip": ".zip",
             "application/msword": ".doc", "application/vnd.ms-excel": ".xls",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
             "message/rfc822": ".eml"}


def parse_eml(data: bytes):
    return email.message_from_bytes(data, policy=email.policy.default)


def eml_attachments(msg) -> list[tuple[str, bytes]]:
    """(dosya adı, bayt) — iletilen ileti (message/rfc822) bütün olarak .eml eki sayılır."""
    out: list[tuple[str, bytes]] = []

    def walk(m, root: bool) -> None:
        ct = m.get_content_type()
        if ct == "message/rfc822" and not root:
            inner = m.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            name = m.get_filename() or "iletilen-ileti.eml"
            if not name.lower().endswith(".eml"):
                name += ".eml"
            try:
                data = inner.as_bytes() if hasattr(inner, "as_bytes") else bytes(inner)
            except Exception:
                data = b""
            out.append((name, data))
            return
        if m.is_multipart():
            for p in m.get_payload():
                walk(p, False)
            return
        if root:
            return
        disp = m.get_content_disposition()
        fn = m.get_filename()
        if disp == "attachment" or (fn and disp != "inline"):
            data = m.get_payload(decode=True) or b""
            name = fn or f"ek{_MIME_EXT.get(ct, '.bin')}"
            out.append((name, data))

    walk(msg, True)
    return out


def _load_msg(src):
    try:
        import extract_msg  # isteğe bağlı kitaplık
    except ImportError:
        return None
    if isinstance(src, io.BytesIO):
        with tempfile.NamedTemporaryFile(suffix=".msg", delete=False) as tf:
            tf.write(src.getvalue())
        try:
            return extract_msg.Message(tf.name)
        finally:
            os.unlink(tf.name)
    return extract_msg.Message(str(src))


def msg_attachments(m) -> list[tuple[str, bytes]]:
    out = []
    for k, a in enumerate(getattr(m, "attachments", []) or [], 1):
        data = getattr(a, "data", None)
        if isinstance(data, (bytes, bytearray)):
            name = getattr(a, "longFilename", None) or getattr(a, "shortFilename", None) or f"ek-{k}.bin"
            out.append((name, bytes(data)))
    return out


def _list_email(src, ext: str) -> Iterator[tuple]:
    if ext == ".msg":
        m = _load_msg(src)
        if m is None:
            return
        atts = msg_attachments(m)
    else:
        data = src.getvalue() if isinstance(src, io.BytesIO) else Path(src).read_bytes()
        atts = eml_attachments(parse_eml(data))
    for name, data in atts:
        # ek adındaki yol ayraçları ad parçasıdır, klasör değil
        base = re.sub(r"[\\/]+", "_", name).strip() or "ek.bin"
        yield base, len(data), None, False, (lambda d=data: _check_size(d))


def _check_size(d: bytes) -> bytes:
    if len(d) > MAX_MEMBER_BYTES:
        raise LimitError(f"üye boyut sınırı aşıldı (>{MAX_MEMBER_BYTES // 1024 ** 2} MiB)")
    return d


# ------------------------------------------------------------------- gezinme

def _lister(kind: str, src, ext: str):
    if kind == "zip":
        return _list_zip(src)
    if kind == "tar":
        return _list_tar(src)
    if kind == "bsdtar":
        return _list_bsdtar(src)
    return _list_email(src, ext)


def walk(path: Path, rel: str, *, want_data: bool, sink=None) -> tuple[list[Member], list[Note]]:
    """Bir kaynak dosyanın (kapsayıcı) bütün üyelerini çıkar (iç içe dahil).

    `want_data=False`: yalnız liste (iç içe kapsayıcılar yine okunur); True: her üyenin baytları
    okunur ve `sink(member, data)` ile hemen teslim edilir (bellekte tutulmaz; sink yoksa
    `Member.data`'da kalır). Hata fırlatmaz: sorunlar üye satırına ya da `Note`'a yazılır.
    """
    members: list[Member] = []
    notes: list[Note] = []
    budget = _Budget()
    _walk(Path(path), rel, 1, budget, want_data, members, notes, sink)
    return members, notes


def write_cache(ws_root: Path, m: Member, data: bytes) -> None:
    """Üyenin baytlarını `<ws>/arsiv/<doc_id><ext>`'e yaz; `m.path`, `m.sha` dolar."""
    import hashlib

    from bidr.common import doc_id_from_sha

    m.sha = hashlib.sha256(data).hexdigest()
    p = cache_path(ws_root, doc_id_from_sha(m.sha), m.ext)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)
    m.path = p


def _walk(src, rel: str, depth: int, budget: _Budget, want_data: bool,
          members: list[Member], notes: list[Note], sink=None) -> None:
    kind = kind_of(rel.rsplit(SEP, 1)[-1])
    ext = full_ext(rel)
    if kind == "bsdtar" and not bsdtar_available():
        notes.append(Note(rel, "unsupported", f"desteklenmeyen arşiv ({ext}): bsdtar yok"))
        return
    if kind == "email" and ext == ".msg" and _msg_lib() is None:
        return  # .msg satırı extract'ta "desteklenmeyen" olur; ekleri okunamaz
    note = Note(rel, ARCHIVE if kind != "email" else "")
    seen: dict[str, int] = {}
    n_enc = 0
    try:
        for name, size, csize, enc, reader in _lister(kind, src, ext):
            if budget.stopped:
                break
            safe, ok = safe_name(name)
            if not safe or skipped(safe):
                continue
            if budget.members >= MAX_MEMBERS:
                budget.stopped = True
                note.error = _join(note.error, f"üye sayısı sınırı ({MAX_MEMBERS}); kalanlar alınmadı")
                break
            k = seen.get(safe, 0)
            seen[safe] = k + 1
            if k:  # aynı adlı iki ek/üye: izlenebilir ve tekil kalsın
                stem, e = posixpath.splitext(safe)
                safe = f"{stem} ({k + 1}){e}"
            mrel = f"{rel}{SEP}{safe}"
            m = Member(mrel, rel, full_ext(safe), size)
            budget.members += 1
            note.members += 1
            members.append(m)
            if not ok:
                m.status, m.error = "error", f"güvensiz üye yolu (yol geçişi): {name[:120]}"
                continue
            if enc:
                n_enc += 1
                m.status, m.error = "error", "şifreli arşiv üyesi (parola gerekli); açılmadı"
                continue
            if size > MAX_MEMBER_BYTES:
                m.status, m.error = "error", f"üye boyut sınırı (>{MAX_MEMBER_BYTES // 1024 ** 2} MiB); açılmadı"
                continue
            if csize is not None and size > RATIO_MIN_BYTES and size > MAX_RATIO * max(csize, 1):
                m.status, m.error = "error", "sıkıştırma oranı şüpheli (zip bombası?); açılmadı"
                continue
            if budget.total + size > MAX_TOTAL_BYTES:
                m.status, m.error = "error", "arşiv toplam boyut sınırı; açılmadı"
                continue
            sub = kind_of(safe)
            if not (want_data or sub):
                budget.total += size
                continue
            try:
                data = reader()
            except EncryptedError:
                n_enc += 1
                m.status, m.error = "error", "şifreli arşiv üyesi (parola gerekli); açılmadı"
                continue
            except LimitError as e:
                m.status, m.error = "error", str(e)
                continue
            except Exception as e:
                m.status, m.error = "error", f"üye okunamadı: {type(e).__name__}: {e}"[:300]
                continue
            if budget.total + len(data) > MAX_TOTAL_BYTES:
                m.status, m.error = "error", "arşiv toplam boyut sınırı; açılmadı"
                continue
            budget.total += len(data)
            m.size = len(data)
            if want_data:
                if sink is not None:
                    sink(m, data)
                else:
                    m.data = data
            if sub:
                if depth >= MAX_DEPTH:
                    m.status, m.error = "error", f"iç içe kapsayıcı derinlik sınırı ({MAX_DEPTH}); açılmadı"
                    m.data = None
                    continue
                _walk(io.BytesIO(data), mrel, depth + 1, budget, want_data, members, notes, sink)
    except EncryptedError as e:
        note.status, note.error = "error", f"şifreli arşiv (parola gerekli); açılmadı: {e}"[:300]
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError, RuntimeError, ValueError) as e:
        if kind != "email":
            note.status = "error"
            note.error = _join(note.error, f"bozuk/okunamayan arşiv: {type(e).__name__}: {e}"[:300])
    except Exception as e:  # e-posta ayrıştırma vb.: üye çıkarılamadı, belge yine işlenir
        note.error = _join(note.error, f"ekler okunamadı: {type(e).__name__}: {e}"[:300])
    if n_enc and note.status == ARCHIVE:
        note.error = _join(note.error, f"{n_enc} şifreli üye açılmadı")
    if note.status or note.error:
        notes.append(note)


def _join(a: str, b: str) -> str:
    return f"{a}; {b}" if a else b


def _msg_lib():
    try:
        import extract_msg
        return extract_msg
    except ImportError:
        return None


# ------------------------------------------------------- aşağı akış için kaynak yolu

def cache_dir(ws_root: Path) -> Path:
    return Path(ws_root) / "arsiv"


def cache_path(ws_root: Path, did: str, ext: str) -> Path:
    return cache_dir(ws_root) / f"{did}{ext}"


def source_path(src_root: Path, rel_path: str, ws_root: Path) -> Path | None:
    """Envanter `rel_path`'inin diskteki dosyası. Düz dosyada `src_root/rel_path`; arşiv/e-posta
    üyesinde çalışma klasöründeki açılmış kopya (yoksa kaynaktan yeniden açılır). Bulunamazsa None.

    Kanıt dosyalama, describe ve transcribe üye dosyaya bu yolla erişmelidir (üyenin kendisi
    kopyalanır; arşiv değil).
    """
    src_root = Path(src_root)
    if SEP not in rel_path:
        p = src_root / rel_path
        return p if p.is_file() else None
    top = rel_path.split(SEP, 1)[0]
    outer = src_root / top
    if not outer.is_file():
        return None

    def sink(m: Member, data: bytes) -> None:
        if m.rel == rel_path:
            write_cache(ws_root, m, data)

    members, _ = walk(outer, top, want_data=True, sink=sink)
    return next((m.path for m in members if m.rel == rel_path and m.path), None)
