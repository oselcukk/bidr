"""`bidr maskele --kaynak DIR --out DIR`: bölüm belge klasörünün model öncesi maskeli kopyası.

Kaynak klasör salt okunurdur; hiçbir dosyasına yazılmaz. Çıktı klasörü kaynakla aynı ağaçtır:

- desteklenen biçimler (`formats.kind_of`: PDF, DOCX, XLSX, düz metin, HTML, görseller) maskelenir
  ve maskeli kopya bağımsız olarak yeniden taranır (`run.mask_and_check`, `bidr maskele` ile aynı);
- kaplar (ingest'in açtığı türler: zip, tar ailesi, 7z/rar, .eml) açılır, üyeleri aynı kurallarla
  (iç içe kaplar dahil) maskelenir ve kap maskeli üyelerle yeniden paketlenir: zip → zip, tar → aynı
  sıkıştırmalı tar, .eml → .eml (başlıklar ve gövde de maskelenir); 7z/rar yazılamadığından
  `<ad>.zip` olarak paketlenir;
- eski biçimler (`eski.convert`): .doc → .docx (macOS textutil), .xls → .xlsx (xlrd → openpyxl),
  .msg → .eml (extract-msg kuruluysa) çevrilip maskelenir; maskeli kopyada yeni uzantısıyla durur
  (rapor: `ozgun_bicim`, `donusum`). Çevrilemeyen (araç yok, .ppt/.pptx, bozuk) olduğu gibi
  kopyalanır ve "elle bakılmalı" olur;
- desteklenmeyen biçimler olduğu gibi kopyalanır ve "elle bakılmalı" listesine girer (içleri
  maskelenmedi);
- gizli/sistem dosyaları (`.DS_Store`, `~$` kilit dosyaları …; ingest'in de atladıkları) kopyalanmaz.

Maskeleme hiçbir kanıtı düşürmez: maskelemesi eksik kalan (`basarisiz`, `taranamadi`) dosyanın
maskeli kopyası, maskelenemeyen (`hata`, `desteklenmiyor`) dosyanın özgünü ağaçta kalır; hepsi
raporda `elle_bakilmali: true` olur. `ayir=True` (`--ayir`): bu dosyalar maskeli kopyaya girmez,
kopyanın DIŞINDA ayrı bir klasöre (`<out>.elle-bakilmali/`, aynı göreli yol; kap üyeleri
`<kap>/<üye>`) konur ve raporda `ayrilan` listesinde yer alır (kaptaki e-posta eki yerine kısa
bir not eklenir). Dosya/klasör adlarındaki kişisel veri de (ad, öğrenci no …) yer
tutucuyla değiştirilir; rapor özgün yolu (`dosya`) ve maskeli yolu (`hedef`) birlikte tutar.

Rapor (`<out>.maskeleme-raporu.json`, çıktı klasörünün DIŞINDA) özgün dosya adlarını içerir:
modele verilmez. Rapora bulunan değerlerin kendisi yazılmaz; yalnız tür ve sayı.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from bidr.ingest import containers as C

from .detect import MaskRules, detect, mask_text
from .eski import LEGACY_EXT, ConvertError, convert as convert_legacy
from .formats import kind_of as mask_kind, mask_html, pdf_engine
from .ocr import ocr_available
from .run import MARKER, MaskRunError, _c, _inside, _prepare_dir, mask_cached

SURUM = 1
ILERLEME = "maskeleme-ilerleme.json"      # -w verilince çalışma alanına: {toplam, biten, durum, …} (dosya adı yok)
REPORT_SUFFIX = ".maskeleme-raporu.json"
SIKI_SUFFIX = ".elle-bakilmali"
ADDR_HEADERS = {"from", "to", "cc", "bcc", "reply-to", "sender", "return-path", "delivered-to",
                "resent-from", "resent-to", "resent-cc", "disposition-notification-to"}
# Adres başlıklarında "[EPOSTA]" geçerli adres olmadığından e-posta ayrıştırıcıları onu siler;
# yerine ayrılmış (.invalid, RFC 2606) bir yer tutucu adres yazılır. Tespit bunu kişisel veri saymaz.
ADDR_PLACEHOLDER = "eposta@maskeli.invalid"


class _Ctx:
    def __init__(self, rules: MaskRules, eng: str, ayir: Path | None = None, model_text: str | None = None,
                 ws: str | None = None):
        self.rules = rules
        self.ws = Path(ws) if ws else None
        from . import bolge as BG
        from .run import elle_kayit
        self.kararlar = BG.kararlar_yukle(self.ws) if self.ws else {}       # bölge kararları + kullanıcı çizimleri
        self.elle = {}                                                     # kaynak sha256 → elle maskelenmiş sürüm
        for v in (elle_kayit(self.ws) if self.ws else {}).values():
            if v.get("kaynak_sha") and v.get("dosya") and (self.ws / v["dosya"]).is_file():
                self.elle[v["kaynak_sha"]] = dict(v, yol=str(self.ws / v["dosya"]))
        self.eng = eng
        self.model_text = model_text        # en üst düzey dosyanın modelin okuma metni (yolu), varsa
        self.ayir = ayir                    # --ayir: elle bakılmalı dosyaların ayrı klasörü
        self.records: list[dict] = []
        self.last: dict | None = None       # son `_handle` çağrısının ana kaydı

    def set_aside(self, written: Path, rec: dict | None) -> bool:
        """--ayir: elle bakılmalı (kap dışı) dosyayı ayrı klasöre kopyala. → ayrıldı mı."""
        if self.ayir is None or rec is None or not rec.get("elle_bakilmali") or rec.get("durum") == "kap":
            return False
        if not written.exists() or not rec.get("hedef"):
            return False
        rel = rec["hedef"].replace(C.SEP, "/")
        target = self.ayir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(written, target)
        rec["ayrildi"] = rel
        return True


def renamed(masked: str, base: str, written: str) -> str:
    """Maskeli ad + yazılan dosyanın ad değişikliği: ek (7z → `.7z.zip`) ya da uzantı (`.doc` → `.docx`,
    `.msg` → `.eml`)."""
    if written == base:
        return masked
    if written.startswith(base):
        return masked + written[len(base):]
    old, new = os.path.splitext(base)[1], os.path.splitext(written)[1]
    if old and masked.lower().endswith(old.lower()):
        return masked[: len(masked) - len(old)] + new
    return masked + new


# ------------------------------------------------------------------ adlar

def mask_name(name: str, rules: MaskRules) -> str:
    """Dosya/klasör adındaki kişisel veri → yer tutucu; uzantı korunur (`.tar.gz` dahil)."""
    ext = C.full_ext(name)
    stem = name[: len(name) - len(ext)] if ext and name.lower().endswith(ext) else name
    if not ext or stem == "":
        stem, ext = name, ""
    new, _ = mask_text(stem, rules)
    return (new + name[len(stem):]) if new != stem else name


def _mask_relpath(parts: list[str], rules: MaskRules) -> list[str]:
    return [mask_name(p, rules) for p in parts]


def _unique(name: str, taken: set[str]) -> str:
    if name.lower() not in taken:
        taken.add(name.lower())
        return name
    ext = C.full_ext(name)
    stem = name[: len(name) - len(ext)] if ext else name
    k = 2
    while f"{stem} ({k}){ext}".lower() in taken:
        k += 1
    out = f"{stem} ({k}){ext}"
    taken.add(out.lower())
    return out


class _Namer:
    """Maskeli göreli yollar; maskeleme iki adı aynı yapıyorsa ` (2)` eki (klasör başına)."""

    def __init__(self, rules: MaskRules):
        self.rules = rules
        self.dirs: dict[tuple, str] = {}           # özgün klasör yolu → maskeli ad
        self.taken: dict[tuple, set] = {}          # maskeli üst klasör → kullanılan adlar

    def path(self, parts: list[str]) -> list[str]:
        out: list[str] = []
        for i, p in enumerate(parts):
            key = tuple(parts[: i + 1])
            last = i == len(parts) - 1
            if not last and key in self.dirs:
                out.append(self.dirs[key])
                continue
            taken = self.taken.setdefault(tuple(out), set())
            m = _unique(mask_name(p, self.rules), taken)
            if not last:
                self.dirs[key] = m
            out.append(m)
        return out


# ------------------------------------------------------------------ tek dosya

def _record(ctx: _Ctx, rel: str, hedef: str, **kw) -> dict:
    rec = {"dosya": rel, "hedef": hedef, **kw}
    ctx.records.append(rec)
    ctx.last = rec
    return rec


def _copy_as_is(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def _handle(src: Path, rel: str, hedef: str, dst: Path, ctx: _Ctx, depth: int = 1) -> Path:
    """`src`'yi işle, sonucu `dst`'ye yaz (ad değişebilir: 7z/rar → .zip). → yazılan yol."""
    name = rel.rsplit(C.SEP, 1)[-1].rsplit("/", 1)[-1]
    ck = C.kind_of(name)
    ext = C.full_ext(name)
    if ck in ("zip", "tar", "bsdtar") or (ck == "email" and ext == ".eml"):
        if depth > C.MAX_DEPTH:
            _copy_as_is(src, dst)
            _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="hata", elle_bakilmali=True,
                    neden=f"iç içe kap derinlik sınırı ({C.MAX_DEPTH}); açılmadı, olduğu gibi kopyalandı")
            return dst
        if ck == "email":
            return _handle_eml(src, rel, hedef, dst, ctx, depth)
        return _handle_archive(src, rel, hedef, dst, ctx, depth, ck, ext)
    kind = mask_kind(src)
    if kind is None and ext in LEGACY_EXT:
        return _handle_legacy(src, rel, hedef, dst, ctx, depth, ext)
    if kind is None:
        _copy_as_is(src, dst)
        _record(ctx, rel, hedef, bicim=ext.lstrip(".") or "?", durum="desteklenmiyor", elle_bakilmali=True,
                neden="biçim maskelenemiyor; olduğu gibi kopyalandı (içi maskelenmedi), elle bakılmalı")
        return dst
    return _mask_one(src, rel, hedef, dst, ctx, kind)


def _mask_one(src: Path, rel: str, hedef: str, dst: Path, ctx: _Ctx, kind: str) -> Path:
    rec = {"bicim": kind}
    if kind == "pdf":
        rec["motor"] = ctx.eng
    dst.parent.mkdir(parents=True, exist_ok=True)
    mt = None
    if ctx.model_text and C.SEP not in rel:          # kap üyesi değil: en üst düzey dosya
        from .run import read_model_text
        mt = read_model_text(Path(ctx.model_text))
        if mt is not None:
            rec["model_metni"] = True
    from .onbellek import sha256_file
    sha = sha256_file(src)
    rec["sha256"] = sha
    e = ctx.elle.get(sha)
    if e is not None:                                # elle maskelenmiş sürüm (bidr maskele yukle): aynı içerik
        shutil.copyfile(e["yol"], dst)
        rec.update(durum="elle_maskelendi", elle_bakilmali=False, neden="elle maskelendi (bidr maskele yukle)",
                   elle_yukleme={k: e.get(k) for k in ("kim", "zaman", "sha256")})
        _record(ctx, rel, hedef, **rec)
        return dst
    # önbellek (`-w` verildiyse `<ws>/.cache/maske.sqlite`, `aday` katmanı): değişmeyen dosya yeniden işlenmez; yarıda
    # kesilen koşunun bitmiş dosyaları yeniden denemede önbellekten gelir
    # kanıt kipi bu sonucu maskeli kopyanın sha256'sıyla yeniden kullanır (`run.kaynak_sonucu`): çerçevesiz hâl de
    # önbelleğe girsin diye geçici `temiz` verilir
    from .onbellek import aktif
    with tempfile.TemporaryDirectory(prefix="bidr-temiz-") as td:
        temiz = Path(td) / f"temiz{dst.suffix}" if aktif() is not None else None
        rec.update(mask_cached(src, dst, ctx.rules, ctx.eng, model_text=mt, kararlar=ctx.kararlar, sha=sha, kind=kind,
                               temiz=temiz, cikti_kaydet=temiz is not None))
    if rec["durum"] == "hata":
        _copy_as_is(src, dst)
        rec["neden"] = rec["neden"] + " — özgün dosya olduğu gibi kopyalandı (kişisel veri içerebilir)"
    elif rec["durum"] != "tamam":
        rec["neden"] = rec["neden"] + " — maskeli kopya ağaçta (eksik maskeleme)"
    _record(ctx, rel, hedef, **rec)
    return dst


WS_RAPOR = "maskeleme-kaynak-raporu.json"      # -w verilince çalışma alanına da yazılır (inceleme komutları okur)


def _handle_legacy(src: Path, rel: str, hedef: str, dst: Path, ctx: _Ctx, depth: int, ext: str) -> Path:
    """Eski biçim → yeni biçime çevir (geçici klasörde) → maskele. Çevrilemezse olduğu gibi kopyala."""
    with tempfile.TemporaryDirectory(prefix="bidr-eski-") as td:
        try:
            conv, how = convert_legacy(src, Path(td))
        except ConvertError as e:
            _copy_as_is(src, dst)
            _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="desteklenmiyor", elle_bakilmali=True,
                    neden=f"eski biçim çevrilemedi: {e}; olduğu gibi kopyalandı (içi maskelenmedi), elle bakılmalı")
            return dst
        except Exception as e:
            _copy_as_is(src, dst)
            _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="hata", elle_bakilmali=True,
                    neden=f"eski biçim çevrilemedi ({type(e).__name__}: {str(e)[:160]}); olduğu gibi kopyalandı")
            return dst
        new_ext = conv.suffix
        dst2 = dst.with_name(renamed(dst.name, src.name, conv.name))
        hedef2 = hedef[: len(hedef) - len(dst.name)] + dst2.name if hedef.endswith(dst.name) else \
            renamed(hedef, src.name, conv.name)
        n0 = len(ctx.records)
        kind = mask_kind(conv)
        if conv.suffix == ".eml":
            out = _handle_eml(conv, rel, hedef2, dst2, ctx, depth)
        elif kind is not None:
            out = _mask_one(conv, rel, hedef2, dst2, ctx, kind)
        else:                                       # olmamalı: çevirici desteklenen biçim üretir
            _copy_as_is(src, dst)
            _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="desteklenmiyor", elle_bakilmali=True,
                    neden=f"eski biçim çevrildi ama {conv.suffix} maskelenemiyor; olduğu gibi kopyalandı")
            return dst
        main = ctx.records[n0] if len(ctx.records) > n0 else None
        if main is not None:
            main["ozgun_bicim"] = ext.lstrip(".")
            main["donusum"] = f"{ext.lstrip('.')} → {new_ext.lstrip('.')} ({how})"
            if how in ("textutil", "xlrd→openpyxl"):
                main.setdefault("uyarilar", []).append(
                    "eski biçimden çevrildi: yazı biçimi, gömülü görsel/grafik ve formüller maskeli kopyada "
                    "korunmayabilir (özgün dosya kaynakta)")
            ctx.last = main
        return out


# ------------------------------------------------------------------ arşivler

def _tar_mode(ext: str) -> str:
    if ext in (".tar.gz", ".tgz"):
        return "w:gz"
    if ext in (".tar.bz2", ".tbz", ".tbz2"):
        return "w:bz2"
    if ext in (".tar.xz", ".txz"):
        return "w:xz"
    return "w"


def _handle_archive(src: Path, rel: str, hedef: str, dst: Path, ctx: _Ctx, depth: int,
                    ck: str, ext: str) -> Path:
    if ck == "bsdtar":
        if not C.bsdtar_available():
            _copy_as_is(src, dst)
            _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="desteklenmiyor", elle_bakilmali=True,
                    neden="bsdtar yok: arşiv açılamadı; olduğu gibi kopyalandı (içi maskelenmedi)")
            return dst
        dst = dst.with_name(dst.name + ".zip")
        hedef = hedef + ".zip"
    n0 = len(ctx.records)
    namer = _Namer(ctx.rules)
    seen: dict[str, int] = {}
    members = 0
    sorun: list[str] = []
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = dst.with_name(dst.name + ".yaziliyor")
    try:
        with tempfile.TemporaryDirectory(prefix="bidr-maske-") as td:
            if ck == "tar":
                writer = tarfile.open(str(tmp_out), _tar_mode(ext))
            else:
                writer = zipfile.ZipFile(str(tmp_out), "w", compression=zipfile.ZIP_DEFLATED)
            with writer:
                for name, size, _csize, enc, reader in C._lister(ck, src, ext):
                    safe, ok = C.safe_name(name)
                    if not safe or C.skipped(safe):
                        continue
                    k = seen.get(safe, 0)
                    seen[safe] = k + 1
                    if k:
                        stem, e = os.path.splitext(safe)
                        safe = f"{stem} ({k + 1}){e}"
                    members += 1
                    mrel = f"{rel}{C.SEP}{safe}"
                    mparts = namer.path(safe.split("/"))
                    mhedef = f"{hedef}{C.SEP}{'/'.join(mparts)}"
                    if members > C.MAX_MEMBERS:
                        sorun.append(f"üye sayısı sınırı ({C.MAX_MEMBERS}); kalanlar alınmadı")
                        _record(ctx, mrel, None, bicim="?", durum="hata", elle_bakilmali=True,
                                neden="üye sayısı sınırı; maskeli kopyaya alınmadı")
                        break
                    why = None
                    if not ok:
                        why = "güvensiz üye yolu (yol geçişi)"
                    elif enc:
                        why = "şifreli arşiv üyesi (parola gerekli)"
                    elif size > C.MAX_MEMBER_BYTES:
                        why = "üye boyut sınırı"
                    data = None
                    if why is None:
                        try:
                            data = reader()
                        except C.EncryptedError:
                            why = "şifreli arşiv üyesi (parola gerekli)"
                        except Exception as e:
                            why = f"üye okunamadı: {type(e).__name__}: {e}"[:200]
                    if data is None:
                        _record(ctx, mrel, None, bicim=C.full_ext(safe).lstrip(".") or "?", durum="hata",
                                elle_bakilmali=True, neden=f"{why}; maskeli kopyaya alınamadı")
                        continue
                    i = members
                    d_in = Path(td) / f"g{i}"
                    d_out = Path(td) / f"c{i}"
                    d_in.mkdir()
                    d_out.mkdir()
                    base = safe.rsplit("/", 1)[-1]
                    f_in = d_in / base
                    f_in.write_bytes(data)
                    del data
                    written = _handle(f_in, mrel, mhedef, d_out / base, ctx, depth + 1)
                    if ctx.set_aside(written, ctx.last):
                        shutil.rmtree(d_in, ignore_errors=True)
                        shutil.rmtree(d_out, ignore_errors=True)
                        continue                 # --ayir: elle bakılmalı üye kaba girmez
                    arc = "/".join(mparts[:-1] + [renamed(mparts[-1], base, written.name)])   # 7z → +.zip; .doc → .docx
                    if ck == "tar":
                        writer.add(str(written), arcname=arc, recursive=False)
                    else:
                        writer.write(str(written), arcname=arc)
                    shutil.rmtree(d_in, ignore_errors=True)
                    shutil.rmtree(d_out, ignore_errors=True)
        tmp_out.replace(dst)
    except Exception as e:     # bozuk/okunamayan arşiv: üye kayıtları geri alınır, özgün kopyalanır
        if tmp_out.exists():
            tmp_out.unlink()
        del ctx.records[n0:]
        if dst.name.endswith(".zip") and ck == "bsdtar":
            dst = dst.with_name(dst.name[: -len(".zip")])
            hedef = hedef[: -len(".zip")]
        _copy_as_is(src, dst)
        _record(ctx, rel, hedef, bicim=ext.lstrip("."), durum="hata", elle_bakilmali=True,
                neden=f"arşiv açılamadı ({type(e).__name__}: {str(e)[:160]}); olduğu gibi kopyalandı")
        return dst
    rec = {"bicim": ext.lstrip("."), "durum": "kap", "uye": members,
           "elle_bakilmali": bool(sorun)}
    if ck == "bsdtar":
        rec["not"] = f"{ext} yazılamadığından zip olarak paketlendi"
    if sorun:
        rec["neden"] = "; ".join(sorun)
    ctx.records.insert(n0, {"dosya": rel, "hedef": hedef, **rec})
    ctx.last = ctx.records[n0]
    return dst


# ------------------------------------------------------------------ e-posta (.eml)

def _mask_addr_header(value: str, rules: MaskRules) -> tuple[str, Counter]:
    counts: Counter = Counter()
    pairs = email.utils.getaddresses([value])
    out = []
    for disp, addr in pairs:
        d2, c = mask_text(disp, rules)
        counts.update(c)
        if addr and detect(addr, rules):
            counts["eposta"] += 1
            addr = ADDR_PLACEHOLDER
        out.append(email.utils.formataddr((d2, addr)) if (d2 or addr) else "")
    return ", ".join(x for x in out if x), counts


def _mask_headers(msg, rules: MaskRules, counts: Counter) -> None:
    for k in list(dict.fromkeys(msg.keys())):
        vals = msg.get_all(k) or []
        new_vals, changed = [], False
        for v in vals:
            sv = str(v)
            if k.lower() in ADDR_HEADERS:
                nv, c = _mask_addr_header(sv, rules)
            elif k.lower() in ("content-type", "content-disposition", "content-transfer-encoding",
                               "mime-version", "content-id"):
                nv, c = sv, Counter()
            else:
                nv, c = mask_text(sv, rules)
            counts.update(c)
            changed |= nv != sv
            new_vals.append(nv)
        if changed:
            del msg[k]
            for nv in new_vals:
                msg[k] = nv


def _is_attachment(part) -> bool:
    disp = part.get_content_disposition()
    return disp == "attachment" or (bool(part.get_filename()) and disp != "inline")


def _eml_texts(msg) -> list[str]:
    """Yeniden tarama için: başlıklar + ek olmayan metin gövdeleri (iletilen iletiler dahil)."""
    out = []
    for k, v in msg.items():
        if k.lower() in ("content-type", "content-disposition", "content-transfer-encoding"):
            continue
        out.append(str(v).replace(ADDR_PLACEHOLDER, ""))
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_content_maintype() == "text" and not _is_attachment(part):
            try:
                out.append(part.get_content())
            except Exception:
                out.append(part.get_payload(decode=True).decode("utf-8", "replace"))
    return out


def _leaves(m):
    """Yaprak parçalar; iletilen iletilere (message/rfc822) inilmez (onlar ayrıca işlenir)."""
    if m.get_content_type() == "message/rfc822":
        return
    if m.is_multipart():
        for p in m.get_payload():
            yield from _leaves(p)
    else:
        yield m


def _handle_eml(src: Path, rel: str, hedef: str, dst: Path, ctx: _Ctx, depth: int) -> Path:
    n0 = len(ctx.records)
    counts: Counter = Counter()
    namer_taken: set[str] = set()
    seen: dict[str, int] = {}
    n_att = 0
    try:
        msg = email.message_from_bytes(src.read_bytes(), policy=email.policy.default)
        with tempfile.TemporaryDirectory(prefix="bidr-maske-") as td:
            def visit(m, root: bool):
                nonlocal n_att
                _mask_headers(m, ctx.rules, counts)
                if m.is_multipart():
                    for p in m.get_payload():
                        visit_part(p)
                    return
                if root:
                    _mask_body(m)

            def _mask_body(p):
                if p.get_content_maintype() != "text":
                    return
                try:
                    text = p.get_content()
                except Exception:
                    text = (p.get_payload(decode=True) or b"").decode("utf-8", "replace")
                sub = p.get_content_subtype()
                if sub == "html":
                    hi = Path(td) / "govde.html"
                    ho = Path(td) / "govde-m.html"
                    hi.write_text(text, encoding="utf-8")
                    r = mask_html(hi, ho, ctx.rules)
                    counts.update(r["maskelenen"])
                    new = ho.read_text(encoding="utf-8")
                else:
                    new, c = mask_text(text, ctx.rules)
                    counts.update(c)
                if new != text:
                    p.set_content(new, subtype=sub, charset="utf-8")

            def visit_part(p):
                nonlocal n_att
                ct = p.get_content_type()
                if ct == "message/rfc822":
                    inner = p.get_payload()
                    inner = inner[0] if isinstance(inner, list) and inner else inner
                    name = p.get_filename() or "iletilen-ileti.eml"
                    if not name.lower().endswith(".eml"):
                        name += ".eml"
                    data = inner.as_bytes() if hasattr(inner, "as_bytes") else bytes(inner)
                    disp = p.get_content_disposition()
                    had_name = bool(p.get_filename())
                    newdata, newname, aside = _member(name, data)
                    if aside:
                        p.set_content(_aside_note(newname), subtype="plain", charset="utf-8",
                                      disposition="attachment", filename=newname + ".ayrildi.txt")
                        return
                    newmsg = email.message_from_bytes(newdata, policy=email.policy.default)
                    kw = {"disposition": disp} if disp else {}
                    if had_name:
                        kw["filename"] = newname
                    p.set_content(newmsg, **kw)
                    return
                if p.is_multipart():
                    _mask_headers(p, ctx.rules, counts)
                    for q in p.get_payload():
                        visit_part(q)
                    return
                if not _is_attachment(p) and p.get_content_maintype() == "text":
                    _mask_body(p)
                    return
                if not _is_attachment(p):
                    return                      # satır içi görsel vb.: ingest okumaz; aşağıda ayrıca
                fn = p.get_filename()
                data = p.get_payload(decode=True) or b""
                name = fn or f"ek{C._MIME_EXT.get(ct, '.bin')}"
                newdata, newname, aside = _member(name, data)
                if aside:
                    p.set_content(_aside_note(newname), subtype="plain", charset="utf-8",
                                  disposition="attachment", filename=newname + ".ayrildi.txt")
                    return
                maintype, subtype = ct.split("/", 1)
                p.set_content(newdata, maintype=maintype, subtype=subtype,
                              disposition=p.get_content_disposition() or "attachment", filename=newname)

            def _member(name: str, data: bytes) -> tuple[bytes, str, bool]:
                nonlocal n_att
                n_att += 1
                base = re.sub(r"[\\/]+", "_", name).strip() or "ek.bin"
                k = seen.get(base, 0)
                seen[base] = k + 1
                if k:
                    stem, e = os.path.splitext(base)
                    base = f"{stem} ({k + 1}){e}"
                mname = _unique(mask_name(base, ctx.rules), namer_taken)
                d_in, d_out = Path(td) / f"g{n_att}", Path(td) / f"c{n_att}"
                d_in.mkdir()
                d_out.mkdir()
                (d_in / base).write_bytes(data)
                written = _handle(d_in / base, f"{rel}{C.SEP}{base}", f"{hedef}{C.SEP}{mname}",
                                  d_out / base, ctx, depth + 1)
                mname = renamed(mname, base, written.name)
                if ctx.set_aside(written, ctx.last):
                    return b"", mname, True
                return written.read_bytes(), mname, False

            visit(msg, True)
            # satır içi (ek olmayan) metin dışı parçalar: ingest okumaz ama dosyada kalır → görsel ise
            # görsel maskelemesinden geçir
            for p in _leaves(msg):
                if _is_attachment(p) or p.get_content_maintype() != "image":
                    continue
                data = p.get_payload(decode=True) or b""
                ext = C._MIME_EXT.get(p.get_content_type(), "." + p.get_content_subtype())
                newdata, _, aside = _member(f"satir-ici{ext}", data)
                if aside:
                    p.set_content(_aside_note("satır içi görsel"), subtype="plain", charset="utf-8",
                                  disposition="inline")
                    continue
                p.set_content(newdata, maintype="image", subtype=p.get_content_subtype(),
                              disposition="inline", cid=p.get("Content-ID"))
            out_bytes = msg.as_bytes()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(out_bytes)
        check = email.message_from_bytes(out_bytes, policy=email.policy.default)
        kalan: Counter = Counter()
        for t in _eml_texts(check):
            kalan.update(f.kind for f in detect(t, ctx.rules))
    except Exception as e:
        del ctx.records[n0:]
        _copy_as_is(src, dst)
        _record(ctx, rel, hedef, bicim="eml", durum="hata", elle_bakilmali=True,
                neden=f"e-posta maskelenemedi ({type(e).__name__}: {str(e)[:160]}); olduğu gibi kopyalandı")
        return dst
    rec = {"bicim": "eml", "durum": "tamam" if not kalan else "basarisiz", "elle_bakilmali": bool(kalan),
           "bulunan": _c(counts + kalan), "maskelenen": _c(counts), "kalan": _c(kalan), "uye": n_att}
    if kalan:
        rec["neden"] = ("maskeleme başarısız; kalan: " + ", ".join(f"{k}×{n}" for k, n in sorted(kalan.items()))
                        + " — maskeli kopya ağaçta (eksik maskeleme)")
    ctx.records.insert(n0, {"dosya": rel, "hedef": hedef, **rec})
    ctx.last = ctx.records[n0]
    return dst


def _aside_note(name: str) -> str:
    return (f"[{name}: maskelemesi eksik kaldığı için --ayir ile maskeli kopyanın dışına ayrıldı; "
            "maskeleme raporundaki 'ayrilan' listesine bakın]\n")


# ------------------------------------------------------------------ çalıştırma

def _files(src: Path) -> tuple[list[Path], list[str]]:
    keep, skipped = [], []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src).as_posix()
        (skipped if C.skipped(rel) or any(x.lower() in C.SKIP_DIRS for x in rel.split("/")[:-1])
         else keep).append(p)
    return keep, [p.relative_to(src).as_posix() for p in skipped]


def _work(args) -> list[dict]:
    src, rel, hedef, dst, rules, eng, ayir, mtext, ws, ob_yol = args
    from . import onbellek
    if ob_yol:                  # işçi süreç: etkin önbellek (ana süreç `onbellek.ac` ile ortama koydu; açıkça da verilir)
        os.environ[onbellek.ENV] = ob_yol
    ctx = _Ctx(rules, eng, Path(ayir) if ayir else None, mtext, ws)
    once = os.environ.get("BIDR_MASKE_WS")
    if ws:                      # çalışma alanının form şablon belleği (kullanıcı çizimi önerileri; raster._sablonlar)
        os.environ["BIDR_MASKE_WS"] = str(ws)
    try:
        written = _handle(Path(src), rel, hedef, Path(dst), ctx)
    except Exception as e:      # beklenmeyen: kanıt düşmesin
        _copy_as_is(Path(src), Path(dst))
        written = Path(dst)
        ctx.records.append({"dosya": rel, "hedef": hedef, "bicim": "?", "durum": "hata", "elle_bakilmali": True,
                            "neden": f"beklenmeyen hata ({type(e).__name__}: {str(e)[:160]}); "
                                     "olduğu gibi kopyalandı"})
        ctx.last = ctx.records[-1]
    finally:
        if ws:
            if once is None:
                os.environ.pop("BIDR_MASKE_WS", None)
            else:
                os.environ["BIDR_MASKE_WS"] = once
    if ctx.last is not None and ctx.last.get("dosya") == rel and ctx.set_aside(written, ctx.last):
        written.unlink()           # --ayir: maskeli kopyada kalmaz
        root, d = Path(dst).parents[len(hedef.split("/")) - 1], written.parent
        while d != root and d.is_dir() and not any(d.iterdir()):
            d.rmdir()
            d = d.parent
    return ctx.records


def _base(path: str, converted) -> str:
    """Yolun son öğesi; eski biçimden çevrilen dosyada uzantısız (uzantı değişimi ad maskelemesi değil)."""
    b = path.rsplit(C.SEP, 1)[-1].rsplit("/", 1)[-1]
    return os.path.splitext(b)[0] if converted else b


def report_path(out: Path) -> Path:
    return out.parent / (out.name + REPORT_SUFFIX)


def ayir_path(out: Path) -> Path:
    return out.parent / (out.name + SIKI_SUFFIX)


def _marker_yaz(d: Path, **alan) -> None:
    (d / MARKER).write_text(json.dumps({"surum": SURUM, **alan}, ensure_ascii=False, indent=1), encoding="utf-8")


def marker_durumu(d: Path) -> str | None:
    """Maskeli kopya klasörünün işareti: None (işaret yok: bidr'in değil ya da hiç koşmadı), "yarim" (koşu başladı,
    bitmedi: kesildi ya da sürüyor) ya da "tamam". Eski işaret (durum alanı yok) bitmiş koşunundur."""
    try:
        j = json.loads((Path(d) / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(j.get("durum") or "tamam") if isinstance(j, dict) else None


def _ilerleme_yaz(p: Path | None, **alan) -> None:
    if p is None:
        return
    try:
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"surum": SURUM, "mod": "kaynak", **alan,
                                   "zaman": datetime.now().astimezone().isoformat(timespec="seconds")},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError:
        pass


def run_source(source: Path, out: Path, *, rules: MaskRules | None = None, engine: str = "auto",
               workers: int = 1, report: Path | None = None, progress=None, ayir: bool = False,
               ws: Path | None = None, onbellek_kullan: bool = True) -> dict:
    """`ws`: çalışma alanı verilirse ve kaynak daha önce okunmuşsa (`inventory.csv` + `text/<doc_id>.txt`)
    modelin okuma metniyle el yazısı denetimi yapılır (bkz. `run.model_text_gaps`); ayrıca çalışma alanının
    önbelleği (`.cache/maske.sqlite`, `onbellek_kullan`) kullanılır ve ilerleme `<ws>/maskeleme-ilerleme.json`'a
    yazılır (toplam, biten; dosya adı yazılmaz).

    Yeniden başlatılabilir: maskeli kopyanın işareti (`.bidr-maskeleme.json`) koşunun BAŞINDA `durum: "yarim"`
    olarak yazılır, sonunda `"tamam"` olur. Kesilen koşunun klasörü bidr'in kendi çıktısı olarak tanınır (yeniden
    koşu "bidr'in üretmediği dosyalar" diye reddetmez); bitmiş dosyalar önbellekten gelir, kaldığı yerden sürer."""
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"kaynak klasör yok: {src}")
    out = Path(out).expanduser().resolve()
    if _inside(out, src) or _inside(src, out):
        raise MaskRunError(f"çıktı klasörü kaynak klasörle iç içe olamaz: {out} / {src}")
    rep_p = Path(report).expanduser().resolve() if report else report_path(out)
    if _inside(rep_p, src) or _inside(rep_p, out):
        raise MaskRunError(f"rapor kaynak ya da çıktı klasörünün içinde olamaz: {rep_p}")
    ayir_d = ayir_path(out) if ayir else None
    if ayir_d is not None and (_inside(ayir_d, src) or _inside(src, ayir_d)):
        raise MaskRunError(f"--ayir klasörü kaynak klasörle iç içe olamaz: {ayir_d}")
    rules = rules or MaskRules()
    eng = pdf_engine(engine)
    _prepare_dir(out)
    bas = datetime.now().astimezone().isoformat(timespec="seconds")
    _marker_yaz(out, mod="kaynak", durum="yarim", zaman=bas)
    if ayir_d is not None:
        _prepare_dir(ayir_d)
        _marker_yaz(ayir_d, mod="kaynak-ayir", durum="yarim", zaman=bas)
    uyarilar = list(rules.warnings)
    if not ocr_available():
        uyarilar.append("OCR yok (tesseract + tur/eng dil verisi): taranmış sayfalar ve görseller taranamadı; "
                        "bu dosyalar 'taranamadi' durumunda kalır")
    if eng == "pypdf":
        uyarilar.append("PyMuPDF kurulu değil: PDF'ler pypdf ile en iyi çabayla maskelendi; taranmış "
                        "sayfalardaki veri ve imzalar kapatılamaz (`pip install 'bidr[maske]'`)")
    files, skipped = _files(src)
    namer = _Namer(rules)
    from . import onbellek
    from .run import source_model_texts
    wsr = Path(ws).expanduser().resolve() if ws else None
    mtexts = source_model_texts(wsr) if wsr else {}
    env_once = {k: os.environ.get(k) for k in (onbellek.ENV, "BIDR_MASKE_WS")}
    ob_yol = None
    if wsr is not None and onbellek_kullan:
        onbellek.ac(wsr)
        ob_yol = str((wsr / onbellek.DOSYA).resolve())
    elif not onbellek_kullan:
        os.environ.pop(onbellek.ENV, None)
    ilerleme_p = wsr / ILERLEME if wsr is not None else None
    if ilerleme_p is not None and (_inside(ilerleme_p, src) or _inside(ilerleme_p, out)):
        ilerleme_p = None
    try:
        records = _run_jobs(src, out, files, namer, mtexts, rules, eng, ayir_d, wsr, ob_yol, workers, progress,
                            ilerleme_p, bas)
    finally:
        for k, v in env_once.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return _finish(src, out, rep_p, ayir_d, ayir, rules, eng, uyarilar, files, skipped, records, ws, bas)


def _run_jobs(src, out, files, namer, mtexts, rules, eng, ayir_d, wsr, ob_yol, workers, progress, ilerleme_p,
              bas) -> list[dict]:
    jobs = []
    for p in files:
        rel = p.relative_to(src).as_posix()
        hedef = "/".join(namer.path(rel.split("/")))
        mt = mtexts.get(rel)
        jobs.append((str(p), rel, hedef, str(out / hedef), rules, eng, str(ayir_d) if ayir_d else None,
                     str(mt) if mt else None, str(wsr) if wsr else None, ob_yol))
    n = len(jobs)
    _ilerleme_yaz(ilerleme_p, durum="suruyor", toplam=n, biten=0, baslangic=bas)
    sonuc: list[list[dict] | None] = [None] * n

    def bitti(i: int, k: int) -> None:
        if progress:
            recs = sonuc[k]
            progress(i, n, recs[0]["dosya"] if recs else jobs[k][1])
        _ilerleme_yaz(ilerleme_p, durum="suruyor", toplam=n, biten=i, baslangic=bas)
    if workers > 1 and n > 1:
        # tamamlanma sırasıyla ilerleme (yavaş bir dosya sayacı tutmasın); rapor sırası iş sırasıdır
        with ProcessPoolExecutor(max_workers=workers) as ex:
            fut = {ex.submit(_work, j): k for k, j in enumerate(jobs)}
            for i, f in enumerate(as_completed(fut), 1):
                k = fut[f]
                sonuc[k] = f.result()
                bitti(i, k)
    else:
        for k, j in enumerate(jobs):
            sonuc[k] = _work(j)
            bitti(k + 1, k)
    records: list[dict] = []
    for recs in sonuc:
        records += recs or []
    _ilerleme_yaz(ilerleme_p, durum="bitti", toplam=n, biten=n, baslangic=bas)
    return records


def _finish(src, out, rep_p, ayir_d, ayir, rules, eng, uyarilar, files, skipped, records, ws, bas) -> dict:
    for r in records:
        r.setdefault("elle_bakilmali", False)
    durumlar = Counter(r["durum"] for r in records)
    toplam = {k: Counter() for k in ("bulunan", "maskelenen", "kalan")}
    for r in records:
        for k in toplam:
            toplam[k].update(r.get(k) or {})
    elle = [{"dosya": r["dosya"], "hedef": r.get("hedef"), "durum": r["durum"], "neden": r.get("neden", ""),
             **({"ayrildi": r["ayrildi"]} if r.get("ayrildi") else {})}
            for r in records if r.get("elle_bakilmali")]
    ayrilan = [{"dosya": r["dosya"], "hedef": r.get("hedef"), "ayrildi": r["ayrildi"], "durum": r["durum"]}
               for r in records if r.get("ayrildi")]
    rapor = {
        "surum": SURUM, "mod": "kaynak", "zaman": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kaynak_klasor": str(src), "maskeli_klasor": str(out), "pdf_motoru": eng, "ocr": ocr_available(),
        "kurallar": {"turler": list(rules.kinds), "ogrenci_no_desen_sayisi": len(rules.student_patterns),
                     "ad_listesi_sayisi": len(rules.names), "etiket_alani": rules.label_fields},
        "ozet": {"dosya": len(files), "kayit": len(records), **dict(sorted(durumlar.items())),
                 "atlanan_gizli_sistem": len(skipped), "elle_bakilmali": len(elle),
                 **{k: _c(v) for k, v in toplam.items()},
                 "imza_bolgesi": sum(r.get("imza_bolgesi", 0) for r in records),
                 "imza_ortusen_kelime": sum(r.get("imza_ortusen_kelime", 0) for r in records),
                 "imza_metinle_ortusen_elle": sum(r.get("imza_metin_elle", 0) for r in records),
                 "eski_bicim_cevrilen": sum(1 for r in records if r.get("donusum")),
                 "onbellekten": sum(1 for r in records if r.get("onbellek")),
                 "model_metni_denetlenen": sum(1 for r in records if r.get("model_metni")),
                 "el_yazisi_elle_dosya": sum(1 for r in records if r.get("el_yazisi_elle")),
                 **({"ayrilan": len(ayrilan)} if ayir else {}),
                 "ad_degisen": sum(1 for r in records if r.get("hedef") and
                                   _base(r["hedef"], r.get("donusum")) != _base(r["dosya"], r.get("donusum")))},
        "uyarilar": uyarilar, "elle_bakilmali": elle, "atlanan": skipped, "dosyalar": records,
    }
    if ayir_d is not None:
        rapor["ayrilan_klasor"] = str(ayir_d)
        rapor["ayrilan"] = ayrilan
        _marker_yaz(ayir_d, mod="kaynak-ayir", durum="tamam", zaman=bas, rapor=str(rep_p))
    rep_p.parent.mkdir(parents=True, exist_ok=True)
    rep_p.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    if ws:
        # ön işleme (bidr file öncesi): bolgeler/karar/ciz/sayfa/yukle -w bu raporu okur
        wr = Path(ws).expanduser().resolve() / WS_RAPOR
        if not (_inside(wr, src) or _inside(wr, out)):
            tmp = wr.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(dict(rapor, rapor=str(rep_p)), ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(wr)
    rapor["rapor"] = str(rep_p)
    _marker_yaz(out, mod="kaynak", durum="tamam", zaman=rapor["zaman"], baslangic=bas, rapor=str(rep_p))
    return rapor
