"""Eski biçimlerin maskelenebilir yeni biçime çevrilmesi (kaynak klasör modu).

- `.doc` (Word 97-2003) → `.docx`: macOS `textutil` (Windows/Linux'ta yok: çevrilemez, elle bakılmalı).
  Uzantısı .doc olup içi docx (zip), RTF ya da HTML olan dosyalar da doğru biçime yönlendirilir.
- `.xls` (Excel 97-2003, BIFF) → `.xlsx`: xlrd ile okunur, openpyxl ile yazılır (hücre değerleri ve
  sayfa adları; formüller hesaplanmış değer olarak, biçim/grafik/görsel taşınmaz). İçi xlsx ya da
  HTML olan ".xls" dosyaları da yönlendirilir.
- `.msg` (Outlook) → `.eml`: `extract-msg` kitaplığı kuruluysa (başlıklar, gövde, ekler).
- `.ppt`/`.pptx`: çevirici yok (LibreOffice gerekir): çevrilemez, elle bakılmalı.

Çeviri yalnız geçici klasörde olur; kaynak dosyaya yazılmaz. Çevrilen dosya maskeli kopyada yeni
uzantısıyla durur; rapor özgün adı tutar.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

LEGACY_EXT = {".doc", ".xls", ".msg", ".ppt", ".pptx"}
TEXTUTIL_TIMEOUT = 180


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
        raise ConvertError("sunum biçimi maskelenemiyor (çevirici yok: LibreOffice gerekir); "
                           "PDF olarak kaydedip yeniden çalıştırın")
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
        out = workdir / f"{stem}.docx"
        _textutil_docx(src, out)
        return out, "textutil"
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
