"""Eski biçimlerin maskelenebilir yeni biçime çevrilmesi (kaynak klasör modu).

- `.doc` (Word 97-2003) → `.docx`: macOS `textutil`; textutil yoksa (Linux/Windows) LibreOffice
  (`soffice --headless --convert-to pdf`) → `.pdf`. Uzantısı .doc olup içi docx (zip), RTF ya da HTML
  olan dosyalar da doğru biçime yönlendirilir.
- `.xls` (Excel 97-2003, BIFF) → `.xlsx`: xlrd ile okunur, openpyxl ile yazılır (hücre değerleri ve
  sayfa adları; formüller hesaplanmış değer olarak, biçim/grafik/görsel taşınmaz). İçi xlsx ya da
  HTML olan ".xls" dosyaları da yönlendirilir.
- `.msg` (Outlook) → `.eml`: `extract-msg` kitaplığı kuruluysa (başlıklar, gövde, ekler).
- `.ppt`/`.pptx` → `.pdf`: LibreOffice (`soffice`) varsa; yoksa çevrilemez, elle bakılmalı (açık mesaj).

LibreOffice tek süreçte (süreç içi kilit), her çağrıda ayrı geçici kullanıcı profiliyle
(`-env:UserInstallation=file://…`; kullanıcının açık LibreOffice'iyle çakışmaz) ve zaman aşımıyla
çalışır.

Çeviri yalnız geçici klasörde olur; kaynak dosyaya yazılmaz. Çevrilen dosya maskeli kopyada yeni
uzantısıyla durur; rapor özgün adı tutar.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

LEGACY_EXT = {".doc", ".xls", ".msg", ".ppt", ".pptx"}
TEXTUTIL_TIMEOUT = 180
SOFFICE_TIMEOUT = 240
SOFFICE_YOK = ("LibreOffice (soffice) bulunamadı: {ext} çevrilemedi. Kurun (Debian/Ubuntu: "
               "`sudo apt install libreoffice-core libreoffice-writer libreoffice-impress`; macOS: "
               "`brew install --cask libreoffice`) ya da dosyayı PDF olarak kaydedip yeniden çalıştırın")
_SOFFICE_LOCK = threading.Lock()


class ConvertError(RuntimeError):
    pass


def _sniff(path: Path) -> str:
    head = path.read_bytes()[:1024]
    if head.startswith(b"PK"):
        return "zip"
    if head.startswith(b"{\\rtf"):
        return "rtf"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return "ole"
    h = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if h.startswith((b"<", b"<!doctype", b"<html")):
        return "html"
    return "?"


def textutil_available() -> bool:
    return shutil.which("textutil") is not None


def _textutil_docx(src: Path, dst: Path) -> None:
    if not textutil_available():
        raise ConvertError("textutil yok (yalnız macOS'ta bulunur); .doc çevrilemedi — Windows/Linux'ta "
                           "dosyayı Word/LibreOffice ile .docx olarak kaydedip yeniden çalıştırın")
    try:
        info = subprocess.run(["textutil", "-info", str(src)], capture_output=True, timeout=TEXTUTIL_TIMEOUT)
        typ = next((ln.split(":", 1)[1].strip() for ln in info.stdout.decode("utf-8", "replace").splitlines()
                    if ln.strip().startswith("Type:")), "")
        if typ and not any(k in typ.lower() for k in ("word", "rich text")):
            # textutil tanımadığı dosyayı düz metin sayıp "çevirir": içerik bozuk çıkar
            raise ConvertError(f"textutil dosyayı Word belgesi olarak tanımadı ({typ}); bozuk ya da başka biçim")
        r = subprocess.run(["textutil", "-convert", "docx", "-output", str(dst), str(src)],
                           capture_output=True, timeout=TEXTUTIL_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise ConvertError("textutil zaman aşımı") from None
    if r.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
        raise ConvertError(f"textutil çeviremedi (kod {r.returncode}): "
                           f"{r.stderr.decode('utf-8', 'replace').strip()[:160]}")


def soffice_path() -> str | None:
    for n in ("soffice", "libreoffice"):
        p = shutil.which(n)
        if p:
            return p
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return str(mac) if mac.is_file() else None


@__import__("functools").lru_cache(maxsize=1)
def soffice_version() -> str:
    p = soffice_path()
    if not p:
        return ""
    try:
        r = subprocess.run([p, "--version"], capture_output=True, timeout=60)
        return (r.stdout or b"").decode("utf-8", "replace").strip()[:80] or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def _soffice_pdf(src: Path, outdir: Path, ext: str) -> Path:
    """LibreOffice ile PDF'e çevir: başsız, ayrı kullanıcı profili, tek süreç, zaman aşımı."""
    exe = soffice_path()
    if not exe:
        raise ConvertError(("sunum biçimi çevrilemedi: " if ext in (".ppt", ".pptx") else "") + SOFFICE_YOK.format(ext=ext))
    outdir.mkdir(parents=True, exist_ok=True)
    with _SOFFICE_LOCK, tempfile.TemporaryDirectory(prefix="bidr-lo-") as prof:
        cmd = [exe, f"-env:UserInstallation={Path(prof).resolve().as_uri()}", "--headless", "--norestore",
               "--nolockcheck", "--convert-to", "pdf", "--outdir", str(outdir), str(src)]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=SOFFICE_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ConvertError(f"LibreOffice zaman aşımı ({SOFFICE_TIMEOUT} sn)") from None
        except OSError as e:
            raise ConvertError(f"LibreOffice çalıştırılamadı: {e}") from None
    out = outdir / f"{src.stem}.pdf"
    if r.returncode != 0 or not out.is_file() or out.stat().st_size == 0:
        raise ConvertError(f"LibreOffice çeviremedi (kod {r.returncode}): "
                           f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[:160]}")
    return out


def converter_id(src: Path) -> str:
    """Bu dosyanın çevirisini etkileyen araç ve sürümü (önbellek anahtarı)."""
    ext = src.suffix.lower()
    if ext == ".doc" and textutil_available():
        return "textutil"
    if ext in (".doc", ".ppt", ".pptx"):
        return f"soffice:{soffice_version()}"
    if ext == ".xls":
        try:
            import xlrd
            import openpyxl
            return f"xlrd:{getattr(xlrd, '__version__', '?')}:openpyxl:{getattr(openpyxl, '__version__', '?')}"
        except ImportError:
            return "xlrd:yok"
    return "?"


def _xls_to_xlsx(src: Path, dst: Path) -> None:
    try:
        import xlrd
        import openpyxl
    except ImportError as e:
        raise ConvertError(f"{e.name} kurulu değil; .xls çevrilemedi") from None
    try:
        book = xlrd.open_workbook(str(src), on_demand=True)
    except Exception as e:
        raise ConvertError(f"xlrd okuyamadı ({type(e).__name__}: {str(e)[:120]})") from None
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    try:
        used = set()
        for sh in book.sheets():
            title = "".join(c for c in sh.name if c not in "[]:*?/\\")[:31] or "Sayfa"
            t, i = title, 1
            while t.lower() in used:
                i += 1
                t = f"{title[:28]}{i}"
            used.add(t.lower())
            ws = wb.create_sheet(t)
            for r in range(sh.nrows):
                for c, cell in enumerate(sh.row(r)):
                    v = cell.value
                    if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK, xlrd.XL_CELL_ERROR):
                        continue
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            v = xlrd.xldate_as_datetime(v, book.datemode)
                        except Exception:
                            pass
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        v = bool(v)
                    elif isinstance(v, str):
                        v = "".join(ch for ch in v if ch in "\t\n\r" or ord(ch) >= 32)   # openpyxl kontrol karakteri almaz
                    ws.cell(row=r + 1, column=c + 1, value=v)
            for (r0, r1, c0, c1) in getattr(sh, "merged_cells", []) or []:
                if r1 - r0 > 0 and c1 - c0 > 0:
                    try:
                        ws.merge_cells(start_row=r0 + 1, end_row=r1, start_column=c0 + 1, end_column=c1)
                    except Exception:
                        pass
        if not wb.worksheets:
            wb.create_sheet("Sayfa")
    finally:
        book.release_resources()
    wb.save(str(dst))


def _msg_to_eml(src: Path, dst: Path) -> None:
    try:
        import extract_msg
    except ImportError:
        raise ConvertError("extract-msg kitaplığı kurulu değil; .msg çevrilemedi "
                           "(`pip install extract-msg`)") from None
    import email.policy
    from email.message import EmailMessage
    try:
        m = extract_msg.Message(str(src))
    except Exception as e:
        raise ConvertError(f".msg okunamadı ({type(e).__name__}: {str(e)[:120]})") from None
    try:
        msg = EmailMessage(policy=email.policy.default)
        for hdr, attr in (("Subject", "subject"), ("From", "sender"), ("To", "to"), ("Cc", "cc"),
                          ("Date", "date")):
            v = getattr(m, attr, None)
            if v:
                msg[hdr] = str(v).replace("\r", " ").replace("\n", " ")
        body = getattr(m, "body", None) or ""
        msg.set_content(str(body))
        html = getattr(m, "htmlBody", None)
        if html:
            if isinstance(html, bytes):
                html = html.decode("utf-8", "replace")
            msg.add_alternative(html, subtype="html")
        from bidr.ingest.containers import msg_attachments
        for name, data in msg_attachments(m):
            msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    finally:
        try:
            m.close()
        except Exception:
            pass
    dst.write_bytes(msg.as_bytes())


def convert(src: Path, workdir: Path) -> tuple[Path, str]:
    """Eski biçimli `src` → `workdir` içinde yeni biçimli dosya. → (yol, yöntem).
    Çevrilemezse `ConvertError` (neden anlaşılır Türkçe)."""
    ext = src.suffix.lower()
    stem = src.stem or "belge"
    kind = _sniff(src)
    workdir.mkdir(parents=True, exist_ok=True)
    if ext in (".ppt", ".pptx"):
        return _soffice_pdf(src, workdir, ext), "soffice"
    if ext == ".doc":
        if kind == "zip":
            out = workdir / f"{stem}.docx"
            shutil.copyfile(src, out)
            return out, "uzantı düzeltme (içi docx)"
        if kind == "html":
            out = workdir / f"{stem}.html"
            shutil.copyfile(src, out)
            return out, "uzantı düzeltme (içi HTML)"
        if kind not in ("ole", "rtf"):
            raise ConvertError("tanınmayan .doc içeriği (Word 97-2003/RTF değil)")
        if textutil_available():                    # macOS: mevcut yol
            out = workdir / f"{stem}.docx"
            _textutil_docx(src, out)
            return out, "textutil"
        if soffice_path():                          # Linux/Windows: LibreOffice → PDF
            return _soffice_pdf(src, workdir, ext), "soffice"
        raise ConvertError("textutil yok (yalnız macOS) ve " + SOFFICE_YOK.format(ext=".doc"))
    if ext == ".xls":
        if kind == "zip":
            out = workdir / f"{stem}.xlsx"
            shutil.copyfile(src, out)
            return out, "uzantı düzeltme (içi xlsx)"
        if kind == "html":
            out = workdir / f"{stem}.html"
            shutil.copyfile(src, out)
            return out, "uzantı düzeltme (içi HTML)"
        out = workdir / f"{stem}.xlsx"
        _xls_to_xlsx(src, out)
        return out, "xlrd→openpyxl"
    if ext == ".msg":
        out = workdir / f"{stem}.eml"
        _msg_to_eml(src, out)
        return out, "extract-msg"
    raise ConvertError(f"eski biçim değil: {ext}")
