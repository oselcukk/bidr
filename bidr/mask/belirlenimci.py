"""Belirlenimci çıktı: aynı girdi + aynı kurallar → bayt bayt aynı maskeli dosya.

Kaynakları:
- PDF: PyMuPDF her `save`'de rastgele trailer `/ID` üretir. Kayıt `no_new_id=True` ile yapılır: özgün dosyanın
  `/ID`'si korunur, özgünde yoksa eklenmez (`pdf_kaydet`).
- OOXML (docx/xlsx): yazıcılar zip girdilerine kayıt anının saatini koyar; openpyxl `docProps/core.xml`'e
  `modified` (özgünde yoksa `created`) olarak o anı yazar. `ooxml_sabitle` zip'i sabit girdi zamanıyla yeniden
  yazar; core.xml'de yalnız `created`/`modified` kalır ve değerleri özgün dosyanınkidir (özgünde yoksa alan
  çıkarılır). Kişisel üst veri alanları (yazar, son değiştiren, başlık …) maskelemede zaten boşaltılır; boş
  hâlleri de core.xml'e yazılmaz.
- Arşivler (zip/tar): üye zamanı sabit, sahip bilgisi boş; tar.gz başlığında zaman 0 (`zip_bilgisi`,
  `tar_bilgisi`, `tar_ac`).

Sabit zaman 1980-01-01 00:00 (zip'in gösterebildiği en eski an): özgün düzenleme zamanlarını taşımaz.
"""
from __future__ import annotations

import gzip
import tarfile
import zipfile
from pathlib import Path

ZIP_ZAMANI = (1980, 1, 1, 0, 0, 0)
CORE = "docProps/core.xml"
_CORE_TARIH = ("created", "modified")


def pdf_kaydet(doc, path, **kw) -> None:
    """PyMuPDF belgesini rastgele `/ID` üretmeden kaydeder (özgünün `/ID`'si korunur)."""
    doc.save(str(path), no_new_id=True, **kw)


def zip_bilgisi(ad: str, compress_type: int = zipfile.ZIP_DEFLATED) -> zipfile.ZipInfo:
    zi = zipfile.ZipInfo(ad, date_time=ZIP_ZAMANI)
    zi.compress_type = compress_type
    zi.create_system = 0                  # platformdan bağımsız (ZipInfo varsayılanı işletim sistemine göre)
    zi.external_attr = 0
    return zi


def _core_tarihleri(ozgun: Path | None) -> dict[str, tuple[str, dict]]:
    """Özgün dosyanın core.xml'indeki `created`/`modified` → (metin, öznitelikler)."""
    if ozgun is None:
        return {}
    from lxml import etree
    try:
        with zipfile.ZipFile(ozgun) as z:
            if CORE not in z.namelist():
                return {}
            root = etree.fromstring(z.read(CORE), parser=etree.XMLParser(resolve_entities=False))
    except Exception:                     # noqa: BLE001 — özgün zip değil/bozuk: tarih yok sayılır
        return {}
    out = {}
    for el in root:
        if isinstance(el.tag, str) and etree.QName(el).localname in _CORE_TARIH and (el.text or "").strip():
            out[etree.QName(el).localname] = (el.text.strip(), dict(el.attrib))
    return out


def _core_yaz(data: bytes, tarih: dict[str, tuple[str, dict]]) -> bytes:
    from lxml import etree
    try:
        root = etree.fromstring(data, parser=etree.XMLParser(resolve_entities=False))
    except etree.XMLSyntaxError:
        return data
    for el in list(root):
        ad = etree.QName(el).localname if isinstance(el.tag, str) else None
        if ad in tarih:
            el.text, attrs = tarih.pop(ad)
            el.attrib.clear()
            el.attrib.update(attrs)
        else:
            root.remove(el)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def ooxml_sabitle(dst: Path, ozgun: Path | None) -> None:
    """docx/xlsx yazımını belirlenimci yapar (yerinde): girdi sırası korunur, zamanlar sabit, core.xml yalnız
    özgünün `created`/`modified` değerleriyle. `ozgun` None: tarih alanları çıkarılır."""
    dst = Path(dst)
    tarih = _core_tarihleri(ozgun)
    tmp = dst.with_name(dst.name + ".sabit")
    with zipfile.ZipFile(dst) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == CORE:
                data = _core_yaz(data, dict(tarih))
            zout.writestr(zip_bilgisi(info.filename, info.compress_type), data)
    tmp.replace(dst)


def tar_bilgisi(ti: tarfile.TarInfo) -> tarfile.TarInfo:
    ti.mtime = 0
    ti.uid = ti.gid = 0
    ti.uname = ti.gname = ""
    return ti


def tar_ac(path: Path, mode: str) -> tarfile.TarFile:
    """Yazmak için tar; `w:gz`'de gzip başlığındaki zaman ve ad sabit."""
    if mode == "w:gz":
        raw = open(path, "wb")
        gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0)
        tf = tarfile.open(fileobj=gz, mode="w")
        kapat = tf.close

        def close():
            try:
                kapat()
            finally:
                gz.close()
                raw.close()
        tf.close = close
        return tf
    return tarfile.open(str(path), mode)


def eml_sinirlarini_sabitle(msg) -> None:
    """Çok parçalı e-postanın sınır (boundary) dizgeleri: `email` kitaplığı yazarken rastgele üretir. Sınır,
    yaprak parçaların içeriğinin özetinden ve parçanın sırasından türetilir (içerikte geçmesi pratikte
    olanaksız); yalnız sınırı henüz olmayan parçalara verilir."""
    import hashlib
    h = hashlib.sha256()
    for p in msg.walk():
        if not p.is_multipart():
            pl = p.get_payload(decode=False)
            h.update(pl.encode("utf-8", "surrogateescape") if isinstance(pl, str) else repr(pl).encode())
    oz = h.hexdigest()[:24]
    for i, p in enumerate(msg.walk()):
        if p.is_multipart() and p.get_boundary() is None:
            p.set_boundary(f"=_bidr_{oz}_{i}")
